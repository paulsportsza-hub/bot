"""FIX-COST-WAVE-02 Phase 1 — anthropic_client.py contract tests.

Covers AC-4 from the wave brief:
  (a) verdict scope-key load
  (b) narrative scope-key load
  (c) KeyError on missing scope-key (no silent fallback to ANTHROPIC_API_KEY)
  (d) call shape with cache_control pass-through
  (e) fallback when CLAUDE_VENDOR=openrouter

Network-free — patches the anthropic SDK + openrouter_client module so no
real HTTP call fires.
"""
from __future__ import annotations

import importlib
import sys
import types
from typing import Any
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def isolated_env(monkeypatch: pytest.MonkeyPatch):
    """Wipe wave env vars so each test starts from a clean slate."""
    for k in (
        "CLAUDE_VENDOR",
        "VERDICT_ANTHROPIC_API_KEY",
        "NARRATIVE_ANTHROPIC_API_KEY",
        "ANTHROPIC_API_KEY",
    ):
        monkeypatch.delenv(k, raising=False)
    yield monkeypatch


@pytest.fixture
def fake_anthropic_sdk(monkeypatch: pytest.MonkeyPatch):
    """Install a fake `anthropic` module that records constructor args and
    returns a mock client with a `.messages.create()` spy.
    """
    fake = types.ModuleType("anthropic")

    created: list[dict[str, Any]] = []
    last_create_kwargs: dict[str, Any] = {}

    class _FakeUsage:
        input_tokens = 156
        cache_creation_input_tokens = 2019
        cache_read_input_tokens = 0
        output_tokens = 60

    class _FakeResponse:
        usage = _FakeUsage()
        content = [types.SimpleNamespace(text="stub verdict.", type="text")]

    class _FakeMessages:
        def create(self, **kwargs: Any) -> _FakeResponse:
            last_create_kwargs.clear()
            last_create_kwargs.update(kwargs)
            return _FakeResponse()

    class _FakeAnthropic:
        def __init__(self, *, api_key: str | None = None, **_: Any) -> None:
            created.append({"cls": "Anthropic", "api_key": api_key})
            self.messages = _FakeMessages()

    class _FakeAsyncMessages:
        async def create(self, **kwargs: Any) -> _FakeResponse:
            last_create_kwargs.clear()
            last_create_kwargs.update(kwargs)
            return _FakeResponse()

    class _FakeAsyncAnthropic:
        def __init__(self, *, api_key: str | None = None, **_: Any) -> None:
            created.append({"cls": "AsyncAnthropic", "api_key": api_key})
            self.messages = _FakeAsyncMessages()

    fake.Anthropic = _FakeAnthropic           # type: ignore[attr-defined]
    fake.AsyncAnthropic = _FakeAsyncAnthropic  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "anthropic", fake)

    # Force re-import so anthropic_client picks up the fake on next import.
    sys.modules.pop("anthropic_client", None)

    return types.SimpleNamespace(
        created=created,
        last_create_kwargs=last_create_kwargs,
    )


def _load_module():
    """Import anthropic_client fresh inside each test."""
    if "anthropic_client" in sys.modules:
        return importlib.reload(sys.modules["anthropic_client"])
    return importlib.import_module("anthropic_client")


# ── AC-4(a) — verdict scope-key load ──────────────────────────────────────

def test_verdict_scope_key_loaded(isolated_env, fake_anthropic_sdk) -> None:
    isolated_env.setenv("VERDICT_ANTHROPIC_API_KEY", "sk-ant-verdict-xxx")
    ac = _load_module()
    client = ac.Anthropic(scope_key_name="VERDICT_ANTHROPIC_API_KEY")
    assert client.scope_key_name == "VERDICT_ANTHROPIC_API_KEY"
    assert client._vendor == "anthropic_direct"
    assert fake_anthropic_sdk.created[-1] == {
        "cls": "Anthropic",
        "api_key": "sk-ant-verdict-xxx",
    }


# ── AC-4(b) — narrative scope-key load ────────────────────────────────────

def test_narrative_scope_key_loaded(isolated_env, fake_anthropic_sdk) -> None:
    isolated_env.setenv("NARRATIVE_ANTHROPIC_API_KEY", "sk-ant-narrative-yyy")
    ac = _load_module()
    client = ac.AsyncAnthropic(scope_key_name="NARRATIVE_ANTHROPIC_API_KEY")
    assert client.scope_key_name == "NARRATIVE_ANTHROPIC_API_KEY"
    assert client._vendor == "anthropic_direct"
    assert fake_anthropic_sdk.created[-1] == {
        "cls": "AsyncAnthropic",
        "api_key": "sk-ant-narrative-yyy",
    }


# ── AC-4(c) — KeyError on missing scope-key; no silent fallback ──────────

def test_missing_scope_key_raises_keyerror(isolated_env, fake_anthropic_sdk) -> None:
    # ANTHROPIC_API_KEY is present — but that's a generic key and MUST NOT
    # be silently used when the caller asks for a specific scope.
    isolated_env.setenv("ANTHROPIC_API_KEY", "sk-ant-generic-should-not-be-used")
    ac = _load_module()
    with pytest.raises(KeyError, match="VERDICT_ANTHROPIC_API_KEY"):
        ac.Anthropic(scope_key_name="VERDICT_ANTHROPIC_API_KEY")
    # And the bare, empty, or non-string scope is refused up-front.
    with pytest.raises(TypeError):
        ac.Anthropic(scope_key_name="")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        ac.Anthropic(scope_key_name=None)  # type: ignore[arg-type]


# ── AC-4(d) — call shape with cache_control ──────────────────────────────

def test_call_shape_cache_control_passthrough(isolated_env, fake_anthropic_sdk) -> None:
    isolated_env.setenv("VERDICT_ANTHROPIC_API_KEY", "sk-ant-verdict-xxx")
    ac = _load_module()
    client = ac.Anthropic(scope_key_name="VERDICT_ANTHROPIC_API_KEY")
    system_blocks = [
        {"type": "text", "text": "SYSTEM", "cache_control": {"type": "ephemeral"}}
    ]
    resp = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=180,
        temperature=0.5,
        system=system_blocks,
        messages=[{"role": "user", "content": "hi"}],
        allow_haiku_fallback=True,  # openrouter-only kwarg — must be absorbed
    )
    assert resp.usage.cache_creation_input_tokens == 2019
    k = fake_anthropic_sdk.last_create_kwargs
    # Structured system array with cache_control reaches the SDK untouched.
    assert k["system"] == system_blocks
    assert k["system"][0]["cache_control"] == {"type": "ephemeral"}
    # openrouter-only kwarg was stripped before reaching the SDK.
    assert "allow_haiku_fallback" not in k


# ── AC-4(e) — CLAUDE_VENDOR=openrouter kill-switch ──────────────────────

def test_kill_switch_delegates_to_openrouter(isolated_env, fake_anthropic_sdk) -> None:
    # Scope-key is absent on purpose — kill-switch must ignore it.
    isolated_env.setenv("CLAUDE_VENDOR", "openrouter")
    isolated_env.setenv("OPENROUTER_API_KEY", "sk-or-fallback-zzz")

    # Stub openrouter_client so we don't hit the real OR HTTP path.
    fake_or = types.ModuleType("openrouter_client")

    sync_inst = MagicMock(name="or_sync_inst")
    async_inst = MagicMock(name="or_async_inst")
    sync_inst.messages.create.return_value = MagicMock(
        usage=MagicMock(input_tokens=0, output_tokens=0),
        content=[types.SimpleNamespace(text="via openrouter")],
    )

    fake_or.Anthropic = MagicMock(return_value=sync_inst)         # type: ignore[attr-defined]
    fake_or.AsyncAnthropic = MagicMock(return_value=async_inst)   # type: ignore[attr-defined]
    isolated_env.setitem(sys.modules, "openrouter_client", fake_or)

    ac = _load_module()
    client = ac.Anthropic(scope_key_name="VERDICT_ANTHROPIC_API_KEY")
    assert client._vendor == "openrouter"
    # Calling through the wrapper reaches the OR fake.
    client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=10,
        system="sys",
        messages=[{"role": "user", "content": "x"}],
    )
    assert sync_inst.messages.create.called
    # Direct SDK was never constructed under the kill-switch.
    assert all(c["cls"] != "Anthropic" for c in fake_anthropic_sdk.created)
