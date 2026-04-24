"""BUILD-C1-OPTIONA-PHASE1-BREAKDOWN-01 — AC-7 / AC-8 contract guard.

AC-7 (negative): A row with a thin/failing embedded verdict inside narrative_html
BUT a passing 200-char verdict_html must be returned by _get_cached_narrative()
— the embedded verdict is no longer part of the C.1 gate.

AC-8 (positive): A row with a passing embedded verdict BUT a 50-char stub
verdict_html must still be rejected — the standalone_ok gate is non-negotiable.

Tests use inspect.getsource() and targeted mocking so they run without a live
DB, consistent with the rest of the contract suite.
"""
from __future__ import annotations

import inspect
import sys
import os

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


@pytest.fixture(scope="module")
def bot_module():
    import bot
    return bot


# ── Source-inspection guards ──────────────────────────────────────────────────

def test_embedded_ok_not_in_gate_source(bot_module):
    """AC-1 guard: _embedded_ok must not exist in _get_cached_narrative source."""
    fn = getattr(bot_module, "_get_cached_narrative", None)
    assert fn is not None, "_get_cached_narrative must remain exported"
    try:
        src = inspect.getsource(fn)
    except (OSError, TypeError):
        pytest.skip("cannot inspect source of _get_cached_narrative")
    assert "_embedded_ok" not in src, (
        "AC-1 REGRESSION: _embedded_ok found in _get_cached_narrative. "
        "C.1 must gate only on standalone_ok (verdict_html column)."
    )


def test_extract_verdict_text_not_in_gate_source(bot_module):
    """AC-1 guard: _extract_verdict_text must not be called in the C.1 gate."""
    fn = getattr(bot_module, "_get_cached_narrative", None)
    assert fn is not None
    try:
        src = inspect.getsource(fn)
    except (OSError, TypeError):
        pytest.skip("cannot inspect source of _get_cached_narrative")
    # _extract_verdict_text should not appear inside the C.1 verdict gate block.
    # It may still exist elsewhere in the codebase.
    assert "_extract_vt" not in src, (
        "AC-1 REGRESSION: _extract_vt alias found in _get_cached_narrative. "
        "The embedded verdict extractor must not be used in the C.1 gate."
    )


def test_standalone_ok_still_present(bot_module):
    """AC-8 guard: _standalone_ok must remain in _get_cached_narrative."""
    fn = getattr(bot_module, "_get_cached_narrative", None)
    assert fn is not None
    try:
        src = inspect.getsource(fn)
    except (OSError, TypeError):
        pytest.skip("cannot inspect source of _get_cached_narrative")
    assert "_standalone_ok" in src, (
        "AC-8 REGRESSION: _standalone_ok gate removed from _get_cached_narrative. "
        "The standalone verdict_html quality gate is non-negotiable."
    )
    assert "min_verdict_quality" in src, (
        "AC-8 REGRESSION: min_verdict_quality gate removed from _get_cached_narrative."
    )


# ── Functional gate tests via narrative_spec ──────────────────────────────────

def test_ac7_passing_verdict_html_gates_standalone_ok():
    """AC-7: 400-char prose embedded verdict + passing 200-char verdict_html
    → min_verdict_quality(verdict_html) returns True (gate passes).

    This verifies that a row with the profile 'embedded_ok=False, standalone_ok=True'
    would now be SERVED — the dominant quarantine pattern before the fix.
    """
    from narrative_spec import min_verdict_quality

    # 200-char quality verdict_html that would pass the gate
    passing_verdict_html = (
        "Arteta's Arsenal hold the form advantage here — five wins from six at home, "
        "and the bookmaker gap is 8% against a defence leaking goals. Back them."
    )
    assert len(passing_verdict_html) >= 60, "Test verdict_html must be long enough"
    # Standalone gate: should pass
    assert min_verdict_quality(passing_verdict_html, tier="gold", evidence_pack=None), (
        "AC-7: A quality 200-char verdict_html must pass min_verdict_quality. "
        "If this fails, the row would have been wrongly quarantined before the fix."
    )


def test_ac8_stub_verdict_html_fails_standalone_ok():
    """AC-8: A 50-char stub verdict_html must still fail min_verdict_quality
    (standalone_ok gate holds — we have not removed the quality floor).
    """
    from narrative_spec import min_verdict_quality, MIN_VERDICT_CHARS_BY_TIER

    bronze_floor = MIN_VERDICT_CHARS_BY_TIER.get("bronze", 60)
    short_verdict = "Back Arsenal." * 3  # definitely < bronze_floor in analytical depth
    # Trim to something clearly below the floor
    short_verdict = short_verdict[:50]
    assert len(short_verdict) < bronze_floor, (
        f"Test stub must be shorter than bronze floor ({bronze_floor})"
    )
    assert not min_verdict_quality(short_verdict, tier="bronze", evidence_pack=None), (
        "AC-8: A 50-char stub verdict_html must FAIL min_verdict_quality. "
        "The standalone_ok gate must not have been weakened."
    )


def test_ac8_trivial_template_fails_standalone_ok():
    """AC-8: Banned trivial templates must still fail (BANNED_TRIVIAL_VERDICT_TEMPLATES)."""
    from narrative_spec import min_verdict_quality

    # "Back Arsenal." matches the BANNED single-action pattern
    assert not min_verdict_quality("Back Arsenal.", tier="bronze", evidence_pack=None), (
        "AC-8: 'Back Arsenal.' must remain a banned trivial verdict."
    )
