from __future__ import annotations

import asyncio
import logging
import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from infra.dispatch.bridge.spawn_sequence import (
    BriefExecutionMeta,
    MODEL_COMMANDS,
    MultiStepSpawn,
    _agent_cmd,
    _brief_execution_meta_from_data,
    _review_gate_instruction,
    resolve_full_stack_route,
)


def _meta(
    brief_id: str,
    *,
    klass: str,
    title: str,
    target_repo: str = "bot",
    files: tuple[str, ...] = (),
    risk_tags: tuple[str, ...] = (),
    agent: str = "Sonnet - AUDITOR",
) -> BriefExecutionMeta:
    return BriefExecutionMeta(
        brief_id=brief_id,
        klass=klass,
        target_repo=target_repo,
        agent=agent,
        files=files,
        risk_tags=risk_tags,
        title=title,
    )


@pytest.mark.parametrize(
    ("meta", "executor", "reviewer", "review_mode", "mechanism"),
    [
        (
            _meta(
                "FIX-ALERTS-DOUBLE-POST-DEDUP-01",
                klass="FIX",
                title="Deduplicate alert DM fanout double-post before publish-batch",
                files=("alerts/dm_fanout.py",),
                risk_tags=("fanout", "claim-before-send"),
            ),
            "codex-xhigh",
            "opus-max",
            "adversarial",
            "subprocess",
        ),
        (
            _meta(
                "QA-IMAGES-ZERO-TEXT-01",
                klass="QA",
                title="Mechanical QA harness contract for zero text image regressions",
                files=("scripts/qa_images_zero_text_01.py", "tests/contracts/test_qa_images.py"),
            ),
            "codex-xhigh",
            "sonnet",
            "review",
            "subprocess",
        ),
        (
            _meta(
                "FIX-SO45-CODEX-INLINE-SUBAGENT-01",
                klass="FIX",
                title="Dispatch governance review-gate inline Codex sub-agent",
                target_repo="dispatch",
                files=("cmux_bridge/spawn_sequence.py", "enqueue.py"),
                risk_tags=("dispatch-state", "review-gate"),
            ),
            "codex-xhigh",
            "opus-max",
            "adversarial",
            "subprocess",
        ),
        (
            _meta(
                "FIX-SO30-BLAST-RADIUS-01",
                klass="DOCS",
                title="Canonical blast-radius docs discipline",
                files=("ops/DEV-STANDARDS.md",),
                risk_tags=("low",),
            ),
            "sonnet",
            "codex-medium",
            "review",
            "subprocess",
        ),
        (
            _meta(
                "FIX-CARD-MATCH-CANONICAL-FAMILY-01",
                klass="FIX",
                title="Bounded canonical family card fix routine",
                files=("card_templates/match_detail.html", "card_templates/my_matches.html"),
            ),
            "sonnet",
            "codex-medium",
            "review",
            "subprocess",
        ),
    ],
)
def test_replay_historical_briefs_route_per_bible(
    meta: BriefExecutionMeta,
    executor: str,
    reviewer: str,
    review_mode: str,
    mechanism: str,
) -> None:
    route = resolve_full_stack_route(meta)
    assert route.executor_cmd == MODEL_COMMANDS[executor]
    assert route.reviewer == reviewer
    assert route.review_mode == review_mode
    assert route.mechanism == mechanism


def test_agent_cmd_dispatch_modes(monkeypatch: pytest.MonkeyPatch) -> None:
    meta = _meta(
        "FIX-CARD-MATCH-CANONICAL-FAMILY-01",
        klass="FIX",
        title="Bounded canonical family card fix routine",
        files=("card_templates/match_detail.html",),
        agent="Codex XHigh - AUDITOR",
    )

    monkeypatch.setenv("DISPATCH_MODE", "hybrid")
    assert _agent_cmd(meta.agent, meta) == "codex --profile xhigh"

    monkeypatch.setenv("DISPATCH_MODE", "full-stack")
    assert _agent_cmd(meta.agent, meta) == "claude --model sonnet"

    monkeypatch.setenv("DISPATCH_MODE", "pure-codex")
    assert _agent_cmd("Sonnet - AUDITOR", meta) == "codex --profile xhigh"


def test_hybrid_mode_logs_shadow_route(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    meta = _meta(
        "FIX-CARD-MATCH-CANONICAL-FAMILY-01",
        klass="FIX",
        title="Bounded canonical family card fix routine",
        files=("card_templates/match_detail.html",),
        agent="Codex XHigh - AUDITOR",
    )
    monkeypatch.setenv("DISPATCH_MODE", "hybrid")

    with caplog.at_level(logging.INFO):
        _agent_cmd(meta.agent, meta)

    assert "shadow_route=" in caplog.text
    assert "actual_agent='Codex XHigh - AUDITOR'" in caplog.text


def test_queue_nested_meta_drives_resolver_metadata() -> None:
    parsed = _brief_execution_meta_from_data(
        {
            "brief_id": "BUILD-FULL-STACK-BRIEFMETA-PARSER-01",
            "agent": "Sonnet - AUDITOR",
            "klass": "BUILD",
            "target_repo": "bot",
            "files_in_scope": ["README.md"],
            "meta": {
                "brief_id": "BUILD-FULL-STACK-BRIEFMETA-PARSER-01",
                "klass": "BUILD",
                "target_repo": "dispatch",
                "agent": "Sonnet - AUDITOR",
                "files": ["dispatch_queue.py", "enqueue.py"],
                "risk_tags": ["dispatch-state", "review-gate"],
                "review_mode": "adversarial-review",
                "title": "BriefExecutionMeta parser",
                "declared_model_override": "codex-high",
            },
        }
    )

    assert parsed.target_repo == "dispatch"
    assert parsed.files == ("dispatch_queue.py", "enqueue.py")
    assert parsed.risk_tags == ("dispatch-state", "review-gate")
    assert parsed.review_mode == "adversarial-review"
    assert parsed.title == "BriefExecutionMeta parser"
    assert parsed.declared_model_override == "codex-high"


def test_full_stack_review_gate_uses_resolved_claude_reviewer() -> None:
    meta = _meta(
        "FIX-SO45-CODEX-INLINE-SUBAGENT-01",
        klass="FIX",
        title="Dispatch governance review-gate inline Codex sub-agent",
        target_repo="dispatch",
        files=("cmux_bridge/spawn_sequence.py", "enqueue.py"),
        risk_tags=("dispatch-state", "review-gate"),
    )
    route = resolve_full_stack_route(meta)

    instruction = _review_gate_instruction(
        meta.brief_id,
        "/tmp/_briefs/FIX-SO45-CODEX-INLINE-SUBAGENT-01/dispatch.md",
        {},
        route,
    )

    assert "claude_review.py" in instruction
    assert "--model opus" in instruction
    assert "--effort max" in instruction
    assert "--review-mode adversarial" in instruction
    assert "codex --profile" not in instruction


def test_sonnet_reviewer_is_claude_routable() -> None:
    meta = _meta(
        "QA-IMAGES-ZERO-TEXT-01",
        klass="QA",
        title="Mechanical QA harness contract for zero text image regressions",
        files=("scripts/qa_images_zero_text_01.py",),
    )
    route = resolve_full_stack_route(meta)

    instruction = _review_gate_instruction(
        meta.brief_id,
        "/tmp/_briefs/QA-IMAGES-ZERO-TEXT-01/dispatch.md",
        {},
        route,
    )

    assert route.reviewer == "sonnet"
    assert "claude_review.py" in instruction
    assert "--model sonnet" in instruction


def test_cowork_queue_route_gets_cowork_review_instruction() -> None:
    meta = _meta(
        "FIX-NARRATIVE-CACHE-PREMIUM-01",
        klass="FIX",
        title="Premium narrative verdict pregen quality gate",
        files=("narrative_cache.py",),
        risk_tags=("premium-narrative",),
    )
    route = resolve_full_stack_route(meta)

    instruction = _review_gate_instruction(
        meta.brief_id,
        "/tmp/_briefs/FIX-NARRATIVE-CACHE-PREMIUM-01/dispatch.md",
        {},
        route,
    )

    assert route.mechanism == "cowork-queue"
    assert "Cowork queue" in instruction
    assert "awaiting_review" in instruction


def test_multistep_spawn_hybrid_smoke_uses_actual_agent_and_logs_shadow(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("DISPATCH_MODE", "hybrid")
    sent_text: list[str] = []
    mock_cmux = MagicMock()
    mock_cmux.surface_send_text.side_effect = lambda _sid, text: sent_text.append(text)

    split_printf_re = re.compile(r'printf "%s%s\\n" "([^"]+)" "([^"]+)"')

    def surface_text(_sid: str) -> str:
        rendered: list[str] = []
        for text in sent_text:
            rendered.append(text)
            rendered.extend(a + b for a, b in split_printf_re.findall(text))
        return "\n".join(rendered)

    mock_cmux.surface_read_text.side_effect = surface_text
    brief_data = {
        "agent": "Codex XHigh - AUDITOR",
        "brief_id": "FIX-CARD-MATCH-CANONICAL-FAMILY-01",
        "notion_url": "https://notion.so/test",
        "enqueued_at": "2026-05-07T00:00:00Z",
        "klass": "FIX",
        "title": "Bounded canonical family card fix routine",
        "files_in_scope": ["card_templates/match_detail.html"],
    }

    async def run_spawn() -> None:
        with patch("asyncio.sleep", new=AsyncMock()):
            await MultiStepSpawn(server="test-server").run("surface-1", brief_data, mock_cmux)

    with caplog.at_level(logging.INFO):
        asyncio.run(run_spawn())

    assert any(text == "codex --profile xhigh" for text in sent_text)
    assert "shadow_route=" in caplog.text
