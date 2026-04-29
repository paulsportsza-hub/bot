"""FIX-W84-PREMIUM-MANDATORY-COVERAGE-01 — AC-2 regression guard.

Premium-tier (Diamond+Gold) Sonnet rejection MUST escalate to Haiku polish
fallback before any defer is recorded. Three sub-cases:

  (a) Sonnet network/exception fail   → Haiku attempted → row written
  (b) Sonnet quality-gate fail        → Haiku attempted → row written
  (c) Both Sonnet and Haiku fail      → defer row written, no narrative_cache row

This test is a static-source regression guard plus a behavioural unit test on
the thin-evidence directive helper. The full async chain runs through bot.py
imports (Telegram, anthropic SDK, etc.) and is exercised by the live pregen
sweep — covering it in a unit test would require mocking the entire universe.
The static guard catches the common failure mode: someone removes a wire.
"""
from __future__ import annotations

from pathlib import Path

import pytest

_PREGEN_PATH = Path(__file__).parents[2] / "scripts" / "pregenerate_narratives.py"


def _source() -> str:
    return _PREGEN_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Sub-case (a): Sonnet exception → Wave 2 intercept calls Haiku
# ---------------------------------------------------------------------------

def test_wave2_intercept_calls_haiku_on_sonnet_exhaustion():
    src = _source()
    # The intercept block must call _attempt_haiku_polish_fallback when the
    # narrative ended up as W82/baseline_no_edge for a Diamond/Gold edge.
    assert 'narrative_source in ("w82", "baseline_no_edge")' in src, (
        "Wave 2 intercept gating predicate missing"
    )
    assert "_premium_intercept_tier in (\"gold\", \"diamond\")" in src, (
        "Wave 2 intercept tier check missing"
    )
    assert "_attempt_haiku_polish_fallback(" in src, (
        "Wave 2 intercept must invoke _attempt_haiku_polish_fallback"
    )


# ---------------------------------------------------------------------------
# Sub-case (b): Sonnet quality-gate fail → Haiku escalation before defer
# ---------------------------------------------------------------------------

def test_quality_gate_path_calls_haiku_before_defer():
    src = _source()
    # The GOLD-QUALITY-GATE failure block must invoke Haiku before the early-return.
    # Look for the Haiku call inside the `if _gold_verdict_failed:` block.
    qg_idx = src.find("if _gold_verdict_failed:")
    assert qg_idx >= 0, "GOLD-QUALITY-GATE failure block missing"
    # Find the next 80 lines after this branch and confirm Haiku call is present
    # before any `INSERT OR REPLACE INTO gold_verdict_failed_edges`.
    block = src[qg_idx:qg_idx + 4000]
    haiku_idx = block.find("_attempt_haiku_polish_fallback(")
    assert haiku_idx >= 0, (
        "GOLD-QUALITY-GATE failure block must invoke _attempt_haiku_polish_fallback "
        "before deferring (FIX-W84-PREMIUM-MANDATORY-COVERAGE-01 AC-2)"
    )
    # Confirm record_premium_defer is called (not the legacy INSERT OR REPLACE).
    assert "_record_premium_defer(" in block, (
        "Quality-gate path must use _record_premium_defer (Wave 2 machinery), "
        "not the legacy INSERT OR REPLACE which loses consecutive_count"
    )


def test_quality_gate_haiku_uses_thin_evidence_when_coverage_empty():
    src = _source()
    # The Haiku call from the quality-gate path must pass the thin-evidence flag
    # derived from `_coverage_level == "empty"`.
    qg_idx = src.find("if _gold_verdict_failed:")
    block = src[qg_idx:qg_idx + 4000]
    assert 'thin_evidence=(_coverage_level == "empty")' in block, (
        "Quality-gate Haiku call must pass thin_evidence flag based on coverage_level — "
        "this prevents Haiku from hallucinating concrete recent events when "
        "ESPN context was empty"
    )


# ---------------------------------------------------------------------------
# Sub-case (c): Haiku also fails → defer row, no narrative_cache row
# ---------------------------------------------------------------------------

def test_quality_gate_haiku_failure_returns_premium_deferred():
    src = _source()
    qg_idx = src.find("if _gold_verdict_failed:")
    block = src[qg_idx:qg_idx + 4000]
    # On Haiku failure, the function returns the deferred-result dict.
    assert '"premium_deferred": True' in block, (
        "Quality-gate Haiku-also-failed path must return premium_deferred=True"
    )
    assert '"premium_defer_count":' in block, (
        "Quality-gate Haiku-also-failed path must surface defer count to caller"
    )


def test_quality_gate_haiku_failure_does_not_write_narrative_cache():
    src = _source()
    qg_idx = src.find("if _gold_verdict_failed:")
    block = src[qg_idx:qg_idx + 4000]
    # The early-return on Haiku failure means we never reach the cache-write
    # call site below in the function. Confirm the return statement is present.
    return_idx = block.find('return {')
    assert return_idx >= 0, "Defer path must return early before cache-write"
    # And confirm the return dict does NOT include any narrative_cache keys.
    return_block = block[return_idx:return_idx + 500]
    assert '"narrative_html"' not in return_block, (
        "Defer return dict must not contain narrative_html (no row write)"
    )


# ---------------------------------------------------------------------------
# Schema migration guard: gold_verdict_failed_edges must carry consecutive_count
# ---------------------------------------------------------------------------

def test_record_premium_defer_idempotent_alter_table():
    src = _source()
    # The _record_premium_defer helper must include the idempotent ALTER TABLE
    # that adds consecutive_count to legacy DBs.
    assert (
        "ALTER TABLE gold_verdict_failed_edges ADD COLUMN consecutive_count"
        in src
    ), (
        "_record_premium_defer must include idempotent ALTER TABLE for "
        "consecutive_count column (legacy DBs created without it)"
    )


def test_record_premium_defer_uses_upsert_not_insert_or_replace():
    src = _source()
    # INSERT OR REPLACE silently drops consecutive_count to its default;
    # we must use ON CONFLICT ... DO UPDATE to preserve and increment it.
    assert "ON CONFLICT(match_key) DO UPDATE SET" in src, (
        "_record_premium_defer must use UPSERT semantics — INSERT OR REPLACE "
        "would drop consecutive_count to default (1) on every defer"
    )
    assert "consecutive_count=consecutive_count + 1" in src, (
        "UPSERT must increment consecutive_count, not reset it"
    )


# ---------------------------------------------------------------------------
# Thin-evidence directive: behavioural test
# ---------------------------------------------------------------------------

def test_thin_evidence_directive_is_present():
    """The _THIN_EVIDENCE_DIRECTIVE constant must contain the three priorities
    the brief calls out: verdict's analytical statement, H2H+form, market-derived."""
    from scripts.pregenerate_narratives import _THIN_EVIDENCE_DIRECTIVE

    assert "verdict" in _THIN_EVIDENCE_DIRECTIVE.lower()
    assert "head-to-head" in _THIN_EVIDENCE_DIRECTIVE.lower() or "h2h" in _THIN_EVIDENCE_DIRECTIVE.lower()
    assert "form" in _THIN_EVIDENCE_DIRECTIVE.lower()
    assert "market" in _THIN_EVIDENCE_DIRECTIVE.lower()
    # Goal: 800-1500 chars per brief.
    assert "800" in _THIN_EVIDENCE_DIRECTIVE or "1500" in _THIN_EVIDENCE_DIRECTIVE
    # Anti-hallucination clause.
    assert "manufacture" in _THIN_EVIDENCE_DIRECTIVE.lower() or "hallucinate" in _THIN_EVIDENCE_DIRECTIVE.lower()


def test_haiku_helper_accepts_thin_evidence_param():
    """`_attempt_haiku_polish_fallback` must accept the thin_evidence keyword."""
    import inspect

    from scripts.pregenerate_narratives import _attempt_haiku_polish_fallback

    sig = inspect.signature(_attempt_haiku_polish_fallback)
    assert "thin_evidence" in sig.parameters, (
        "_attempt_haiku_polish_fallback must expose thin_evidence keyword "
        "(FIX-W84-PREMIUM-MANDATORY-COVERAGE-01 AC-2)"
    )
    # Default should be False (preserves existing Wave 2 callers).
    assert sig.parameters["thin_evidence"].default is False


# ---------------------------------------------------------------------------
# Premium intercept retains the existing Wave 2 carve-outs
# ---------------------------------------------------------------------------

def test_wave2_intercept_skips_when_skip_w84_set():
    """The Wave 2 intercept must keep the `_skip_w84` carve-out — non-edge
    previews and coverage-gate denials don't trigger Haiku fallback (those
    are intentional W82 baselines, not failure-mode silent downgrades)."""
    src = _source()
    # The intercept block uniquely starts with this conditional + tier check.
    intercept_idx = src.find('narrative_source in ("w82", "baseline_no_edge")')
    assert intercept_idx >= 0, "Wave 2 intercept gate not found"
    block = src[intercept_idx:intercept_idx + 1500]
    assert "and not _skip_w84" in block, (
        "Wave 2 intercept must keep `_skip_w84` carve-out — see Rule 23"
    )
    assert "and not _is_non_edge" in block, (
        "Wave 2 intercept must keep `_is_non_edge` carve-out — see Rule 23"
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
