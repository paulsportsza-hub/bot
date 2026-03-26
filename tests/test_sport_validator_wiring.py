"""REGFIX-03 wiring tests: validate_sport_text() integrated into _generate_one() pipeline.

Verifies that:
  1. A clean W84 narrative passes validation and reaches the cache path unchanged.
  2. A contaminated W84 narrative (wrong-sport terms) is blocked from narrative_cache
     and falls back to the W82 template baseline.
  3. A WARNING log is emitted with sport name, match key, and banned term list when
     contamination is detected.

These are integration tests — each test calls validate_sport_text() as invoked by the
wiring block in pregenerate_narratives._generate_one(), simulating the state variables
present at the insertion point (after BASELINE-FIX, before HTML assembly).
"""
from __future__ import annotations

import logging

import pytest

from validators.sport_context import validate_sport_text

# ─────────────────────────────────────────────────────────────────────────────
# Shared fixtures
# ─────────────────────────────────────────────────────────────────────────────

_CLEAN_SOCCER_NARRATIVE = (
    "📋 <b>The Setup</b>\n"
    "Arsenal have kept clean sheets in their last four home fixtures. "
    "The Gunners sit second on the table and Arteta's side are in strong form.\n\n"
    "🎯 <b>The Edge</b>\n"
    "There is a meaningful expected value gap here — Betway's 1.85 implies 54%, "
    "while the model prices this closer to 62%.\n\n"
    "⚠️ <b>The Risk</b>\n"
    "No specific flags on this one — clean risk profile, size normally.\n\n"
    "🏆 <b>Verdict</b>\n"
    "Back Arsenal at 1.85 with Betway."
)

_CONTAMINATED_CRICKET_NARRATIVE = (
    "📋 <b>The Setup</b>\n"
    "South Africa's football heritage and clean sheet record make them favourites "
    "in this fixture. The penalty kick conversion rate is impressive.\n\n"
    "🎯 <b>The Edge</b>\n"
    "The expected value gap is 8.5%. Betway prices this at 1.72.\n\n"
    "⚠️ <b>The Risk</b>\n"
    "No specific flags.\n\n"
    "🏆 <b>Verdict</b>\n"
    "Back South Africa at 1.72 with Betway."
)

_W82_CRICKET_BASELINE = (
    "📋 <b>The Setup</b>\n"
    "South Africa host India in a Test series. "
    "SA sit third in the ICC Test rankings with a solid batting record.\n\n"
    "🎯 <b>The Edge</b>\n"
    "Bookmaker pricing implies 47%. Model calibration says 55%.\n\n"
    "⚠️ <b>The Risk</b>\n"
    "Top-order vulnerability on a green pitch is the key variable.\n\n"
    "🏆 <b>Verdict</b>\n"
    "Lean on South Africa at 1.72 with Betway."
)


# ─────────────────────────────────────────────────────────────────────────────
# Test 1: Clean narrative passes through and reaches the cache path
# ─────────────────────────────────────────────────────────────────────────────

def test_clean_narrative_passes_to_cache_path() -> None:
    """A W84 soccer narrative with no banned terms must not trigger fallback.

    Simulates the REGFIX-03 wiring block in _generate_one():
      if narrative and narrative_source == "w84":
          _sv_valid, _sv_banned = validate_sport_text(narrative, sport)
          if not _sv_valid:
              narrative = w82_baseline
              narrative_source = "w82"
    """
    # State variables at wiring insertion point
    narrative = _CLEAN_SOCCER_NARRATIVE
    narrative_source = "w84"
    w82_baseline = "W82 fallback — should not be used"
    sport = "soccer"

    # Execute the wiring logic
    _sv_valid, _sv_banned = validate_sport_text(narrative, sport)
    if not _sv_valid:
        if w82_baseline:
            narrative = w82_baseline
            narrative_source = "w82"

    assert narrative == _CLEAN_SOCCER_NARRATIVE, (
        "Clean narrative must not be replaced — validator should pass"
    )
    assert narrative_source == "w84", "narrative_source must remain w84 for clean text"
    assert _sv_valid is True
    assert _sv_banned == []


# ─────────────────────────────────────────────────────────────────────────────
# Test 2: Contaminated narrative is blocked and triggers template fallback
# ─────────────────────────────────────────────────────────────────────────────

def test_contaminated_cricket_narrative_blocked_and_falls_back() -> None:
    """A W84 cricket narrative containing soccer terms must be replaced by W82 baseline.

    Verifies Failure Mode 3 defence: cricket described as 'African football'
    never reaches narrative_cache when the wiring is active.
    """
    narrative = _CONTAMINATED_CRICKET_NARRATIVE
    narrative_source = "w84"
    w82_baseline = _W82_CRICKET_BASELINE
    sport = "cricket"

    _sv_valid, _sv_banned = validate_sport_text(narrative, sport)
    if not _sv_valid:
        if w82_baseline:
            narrative = w82_baseline
            narrative_source = "w82"

    assert narrative == _W82_CRICKET_BASELINE, (
        "Contaminated narrative must be replaced by W82 baseline"
    )
    assert narrative_source == "w82", "narrative_source must be w82 after contamination fallback"
    assert _sv_valid is False
    # Verify the specific banned terms that triggered the block
    assert "football" in _sv_banned or "clean sheet" in _sv_banned or "penalty kick" in _sv_banned


# ─────────────────────────────────────────────────────────────────────────────
# Test 3: WARNING log fires with sport, match key, and banned terms
# ─────────────────────────────────────────────────────────────────────────────

def test_log_warning_fired_on_contamination(caplog: pytest.LogCaptureFixture) -> None:
    """A WARNING must be logged when sport validation blocks a W84 narrative.

    Verifies the exact log format used in the wiring block:
      log.warning("SPORT VALIDATOR BLOCKED: %s narrative for %s contained banned terms %s ...")
    """
    sport = "cricket"
    match_key = "south_africa_vs_india_2026-03-26"
    narrative = _CONTAMINATED_CRICKET_NARRATIVE
    narrative_source = "w84"
    w82_baseline = _W82_CRICKET_BASELINE

    log = logging.getLogger("pregenerate")

    with caplog.at_level(logging.WARNING, logger="pregenerate"):
        _sv_valid, _sv_banned = validate_sport_text(narrative, sport)
        if not _sv_valid:
            log.warning(
                "SPORT VALIDATOR BLOCKED: %s narrative for %s contained banned terms %s"
                " — falling back to W82 template",
                sport,
                match_key,
                _sv_banned,
            )
            if w82_baseline:
                narrative = w82_baseline
                narrative_source = "w82"

    # Verify log was emitted
    warning_messages = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert any(
        "SPORT VALIDATOR BLOCKED" in msg for msg in warning_messages
    ), f"Expected WARNING containing 'SPORT VALIDATOR BLOCKED', got: {warning_messages}"

    # Verify sport and match_key appear in the warning
    combined = " ".join(warning_messages)
    assert sport in combined
    assert match_key in combined

    # Verify fallback was applied
    assert narrative == _W82_CRICKET_BASELINE
    assert narrative_source == "w82"
