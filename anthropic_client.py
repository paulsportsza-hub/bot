"""Direct Anthropic SDK wrapper with scope-keyed billing — drop-in for openrouter_client.

FIX-COST-WAVE-02 (2026-04-26) — Phase 1

Routes Claude traffic directly to the Anthropic API (bypassing OpenRouter's
markup and its cache_control stripping). Callers supply a `scope_key_name`
(e.g. "VERDICT_ANTHROPIC_API_KEY") so per-scope spend shows up as distinct
billing lines on the Anthropic console.

Interface mirrors openrouter_client:
    import anthropic_client as _anthropic
    client = _anthropic.Anthropic(scope_key_name="VERDICT_ANTHROPIC_API_KEY")
    resp = client.messages.create(model=..., system=..., messages=..., ...)

cache_control pass-through:
    system=[{"type": "text", "text": ..., "cache_control": {"type": "ephemeral"}}]

Kill-switch:
    CLAUDE_VENDOR=openrouter → wrapper delegates to openrouter_client. This
    is the rollback substrate — do NOT kill the OPENROUTER_API_KEY until the
    48h soak confirms savings.
"""
from __future__ import annotations

import logging
import os
from typing import Any

log = logging.getLogger(__name__)


# Per-million-token prices (USD) used for observability logging only.
# Source: anthropic.com/pricing as of 2026-04-24.
_PRICING: dict[str, dict[str, float]] = {
    "claude-sonnet-4-5":              {"in": 3.00,  "out": 15.00, "cw": 3.75,  "cr": 0.30},
    "claude-sonnet-4-6":              {"in": 3.00,  "out": 15.00, "cw": 3.75,  "cr": 0.30},
    "claude-sonnet-4-20250514":       {"in": 3.00,  "out": 15.00, "cw": 3.75,  "cr": 0.30},
    "claude-haiku-4-5-20251001":      {"in": 1.00,  "out":  5.00, "cw": 1.25,  "cr": 0.10},
    "claude-opus-4-6":                {"in": 15.00, "out": 75.00, "cw": 18.75, "cr": 1.50},
    "claude-opus-4-7":                {"in": 15.00, "out": 75.00, "cw": 18.75, "cr": 1.50},
}


def _kill_switch_active() -> bool:
    return os.environ.get("CLAUDE_VENDOR", "").strip().lower() == "openrouter"


def _compute_cost_usd(
    model: str,
    input_tok: int,
    cache_write_tok: int,
    cache_read_tok: int,
    output_tok: int,
) -> float:
    p = _PRICING.get(model)
    if not p:
        return 0.0
    return (
        input_tok       * p["in"]  / 1_000_000.0
        + cache_write_tok * p["cw"]  / 1_000_000.0
        + cache_read_tok  * p["cr"]  / 1_000_000.0
        + output_tok      * p["out"] / 1_000_000.0
    )


def _strip_openrouter_only_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
    """Drop kwargs the Anthropic SDK doesn't accept."""
    for drop in ("allow_haiku_fallback",):
        kwargs.pop(drop, None)
    return kwargs


def _log_usage(scope_key_name: str, model: str, resp: Any) -> None:
    try:
        u = resp.usage
        in_tok = getattr(u, "input_tokens", 0) or 0
        cw     = getattr(u, "cache_creation_input_tokens", 0) or 0
        cr     = getattr(u, "cache_read_input_tokens", 0) or 0
        out    = getattr(u, "output_tokens", 0) or 0
        cost   = _compute_cost_usd(model, in_tok, cw, cr, out)
        log.info(
            "anthropic_call scope=%s model=%s system_tok=%d cache_write=%d cache_read=%d output_tok=%d cost_usd=%.6f",
            scope_key_name, model, in_tok, cw, cr, out, cost,
        )
    except Exception as exc:
        log.debug("anthropic_client: usage log failed: %s", exc)


# ── Sync ─────────────────────────────────────────────────────────────────────

class _SyncMessages:
    def __init__(self, impl_messages: Any, scope_key_name: str, vendor: str) -> None:
        self._impl = impl_messages
        self._scope = scope_key_name
        self._vendor = vendor

    def create(self, **kwargs: Any) -> Any:
        _strip_openrouter_only_kwargs(kwargs)
        resp = self._impl.create(**kwargs)
        if self._vendor == "anthropic_direct":
            _log_usage(self._scope, kwargs.get("model", "unknown"), resp)
        return resp


class Anthropic:
    """Sync client. Pass `scope_key_name` to pick the billing key.

    Kwargs `api_key` is optional and overrides the scope-key lookup (used
    by tests / manual scripts). In production, callers pass only
    `scope_key_name` and the key is resolved from `os.environ[scope_key_name]`.
    """

    def __init__(self, scope_key_name: str, api_key: str | None = None, **_kwargs: Any) -> None:
        if not isinstance(scope_key_name, str) or not scope_key_name:
            raise TypeError(
                "anthropic_client.Anthropic(scope_key_name=...) is required — "
                "no silent fallback to a generic ANTHROPIC_API_KEY."
            )
        self.scope_key_name = scope_key_name

        if _kill_switch_active():
            import openrouter_client as _or
            self._vendor = "openrouter"
            self._impl = _or.Anthropic()
            self.messages = _SyncMessages(self._impl.messages, scope_key_name, self._vendor)
            return

        if api_key is None:
            api_key = os.environ[scope_key_name]  # KeyError if missing — explicit failure
        from anthropic import Anthropic as _RealAnthropic
        self._vendor = "anthropic_direct"
        self._impl = _RealAnthropic(api_key=api_key)
        self.messages = _SyncMessages(self._impl.messages, scope_key_name, self._vendor)


# ── Async ────────────────────────────────────────────────────────────────────

class _AsyncMessages:
    def __init__(self, impl_messages: Any, scope_key_name: str, vendor: str) -> None:
        self._impl = impl_messages
        self._scope = scope_key_name
        self._vendor = vendor

    async def create(self, **kwargs: Any) -> Any:
        _strip_openrouter_only_kwargs(kwargs)
        resp = await self._impl.create(**kwargs)
        if self._vendor == "anthropic_direct":
            _log_usage(self._scope, kwargs.get("model", "unknown"), resp)
        return resp


class AsyncAnthropic:
    """Async counterpart of `Anthropic`. Same scope-key contract."""

    def __init__(self, scope_key_name: str, api_key: str | None = None, **_kwargs: Any) -> None:
        if not isinstance(scope_key_name, str) or not scope_key_name:
            raise TypeError(
                "anthropic_client.AsyncAnthropic(scope_key_name=...) is required — "
                "no silent fallback to a generic ANTHROPIC_API_KEY."
            )
        self.scope_key_name = scope_key_name

        if _kill_switch_active():
            import openrouter_client as _or
            self._vendor = "openrouter"
            self._impl = _or.AsyncAnthropic()
            self.messages = _AsyncMessages(self._impl.messages, scope_key_name, self._vendor)
            return

        if api_key is None:
            api_key = os.environ[scope_key_name]
        from anthropic import AsyncAnthropic as _RealAsyncAnthropic
        self._vendor = "anthropic_direct"
        self._impl = _RealAsyncAnthropic(api_key=api_key)
        self.messages = _AsyncMessages(self._impl.messages, scope_key_name, self._vendor)
