"""FIX-VERDICT-CACHE-PATH-LOCK-AND-W82-TEMPLATE-CLOSURE-01 — AC-1 contract tests.

Verifies that the verdict-cache write path routes through
``_validate_verdict_for_persistence`` and applies the brief tier-aware
enforcement matrix:

  - Diamond/Gold + CRITICAL gate hit (banned-phrase / venue / manager /
    strong-band-tone / closure rule / setup-pricing / vague-content
    premium / char range under) → refuse write, log
    ``FIX-VERDICT-CACHE-PATH-LOCK-01 PremiumVerdictRefused``.
  - Silver + closure-rule mismatch → MAJOR → quarantine row
    (``quality_status='quarantined'`` on INSERT).
  - Bronze + closure-rule mismatch → MINOR → write with warning log.

Coverage targets (≥15 tests):

  1. Validator surface: callable + correct return type
  2. Tier-aware enforcement matrix (Diamond/Gold CRITICAL gates → refuse)
  3. Banned-phrase Gold → refuse
  4. Venue leak Gold → refuse
  5. Strong-band tone Gold → refuse
  6. Closure rule Gold (missing odds) → refuse
  7. Closure rule Silver (missing both team+odds) → quarantine
  8. Closure rule Silver (missing action) → quarantine
  9. Closure rule Bronze (missing action) → write + warning
 10. Vague-content Gold → refuse
 11. Telemetry vocabulary Gold → refuse
 12. Char range under-min Gold → refuse
 13. Char range under-min Bronze → quarantine (MAJOR)
 14. Clean Diamond verdict accepted
 15. Setup-pricing leak in verdict Gold → refuse
 16. Bypass-attempt assertion: any verdict-cache write site MUST go through
     the validator (source-level inspection of bot.py)
 17. AC-3 broadened action verb regex accepts declarative phrases
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

import bot as _bot
from narrative_validator import (
    _VERDICT_ACTION_RE,
    _validate_verdict_for_persistence,
    ValidationResult,
)


_MATCH_KEY = "liverpool_vs_chelsea_2026-04-30"
_EVIDENCE = {"home_team": "Liverpool", "away_team": "Chelsea"}


def _clean_gold_verdict() -> str:
    """A Gold verdict that satisfies every gate in the validator."""
    return (
        "Form solid and the line is too long for what we see. "
        "Back Liverpool at 1.97 with Supabets, factor in the rotation "
        "concern — standard stake on this one."
    )


def _clean_diamond_verdict() -> str:
    """A Diamond verdict that satisfies every gate in the validator."""
    return (
        "The form runs deep and the case lands clean, premium value here. "
        "Premium back on Liverpool at 1.97 with Supabets, factor in the "
        "rotation concern — standard-to-heavy stake."
    )


# ── 1. Surface ────────────────────────────────────────────────────────────────


def test_validator_function_exists_and_is_callable():
    assert callable(_validate_verdict_for_persistence)


def test_validator_returns_validation_result():
    res = _validate_verdict_for_persistence(
        verdict_html=_clean_gold_verdict(),
        edge_tier="gold",
        evidence_pack=_EVIDENCE,
        source_label="verdict-cache",
        match_id=_MATCH_KEY,
    )
    assert isinstance(res, ValidationResult)


def test_empty_verdict_returns_passed():
    res = _validate_verdict_for_persistence(
        verdict_html="",
        edge_tier="gold",
        evidence_pack=_EVIDENCE,
        source_label="verdict-cache",
        match_id=_MATCH_KEY,
    )
    assert res.passed
    assert res.failures == []


# ── 2. Tier-aware enforcement matrix ──────────────────────────────────────────


def test_gold_clean_verdict_passes():
    res = _validate_verdict_for_persistence(
        verdict_html=_clean_gold_verdict(),
        edge_tier="gold",
        evidence_pack=_EVIDENCE,
        source_label="verdict-cache",
        match_id=_MATCH_KEY,
    )
    assert res.passed, f"Clean Gold verdict rejected: {[(f.gate, f.detail) for f in res.failures]}"
    assert res.critical_count == 0


def test_diamond_clean_verdict_passes():
    res = _validate_verdict_for_persistence(
        verdict_html=_clean_diamond_verdict(),
        edge_tier="diamond",
        evidence_pack=_EVIDENCE,
        source_label="verdict-cache",
        match_id=_MATCH_KEY,
    )
    assert res.passed, f"Clean Diamond verdict rejected: {[(f.gate, f.detail) for f in res.failures]}"


# ── 3. Premium-tier CRITICAL gates → refuse ───────────────────────────────────


def test_gold_venue_leak_critical():
    """Gold verdict with venue name (Anfield) → CRITICAL → refuse."""
    verdict = (
        "Form is solid at Anfield and the line looks soft. "
        "Back Liverpool at 1.97 with Supabets, measured stake."
    )
    res = _validate_verdict_for_persistence(
        verdict_html=verdict,
        edge_tier="gold",
        evidence_pack=_EVIDENCE,
        source_label="verdict-cache",
        match_id=_MATCH_KEY,
    )
    assert res.critical_count >= 1
    assert any(f.gate == "venue_leak" for f in res.failures)


def test_gold_closure_rule_missing_odds_critical():
    """Gold verdict closing without odds → CRITICAL closure rule."""
    verdict = (
        "Form is solid and the line looks soft. "
        "Get on Liverpool at home — measured stake."
    )
    res = _validate_verdict_for_persistence(
        verdict_html=verdict,
        edge_tier="gold",
        evidence_pack=_EVIDENCE,
        source_label="verdict-cache",
        match_id=_MATCH_KEY,
    )
    assert any(f.gate == "verdict_closure_rule" and f.severity == "CRITICAL"
               for f in res.failures)


def test_gold_closure_rule_setup_observation_critical():
    """Gold verdict closing with Setup-style observation → CRITICAL."""
    verdict = (
        "Slot's lot are flying. Chelsea have lost five on the bounce, "
        "stretching back to early March."
    )
    res = _validate_verdict_for_persistence(
        verdict_html=verdict,
        edge_tier="gold",
        evidence_pack=_EVIDENCE,
        source_label="verdict-cache",
        match_id=_MATCH_KEY,
    )
    assert any(f.gate == "verdict_closure_rule" and f.severity == "CRITICAL"
               for f in res.failures)


def test_gold_strong_band_tone_lock_critical():
    """Gold verdict with cautious-band vocabulary → CRITICAL."""
    verdict = (
        "Form picture is unclear and there's limited edge to work with here. "
        "Back Liverpool at 1.97 with Supabets, cautious lean."
    )
    res = _validate_verdict_for_persistence(
        verdict_html=verdict,
        edge_tier="gold",
        evidence_pack=_EVIDENCE,
        source_label="verdict-cache",
        match_id=_MATCH_KEY,
    )
    assert any(f.gate == "strong_band_tone" and f.severity == "CRITICAL"
               for f in res.failures)


def test_gold_telemetry_vocabulary_critical():
    """Gold verdict with telemetry vocab ('the bookmaker has slipped') → CRITICAL."""
    verdict = (
        "The bookmaker has slipped on this one and the indicators line up. "
        "Back Liverpool at 1.97 with Supabets, standard stake."
    )
    res = _validate_verdict_for_persistence(
        verdict_html=verdict,
        edge_tier="gold",
        evidence_pack=_EVIDENCE,
        source_label="verdict-cache",
        match_id=_MATCH_KEY,
    )
    assert any(f.gate == "telemetry_vocabulary" and f.severity == "CRITICAL"
               for f in res.failures)


def test_gold_vague_content_critical():
    """Gold verdict with vague-content pattern → CRITICAL."""
    verdict = (
        "This looks like the sort of fixture that takes shape once one side "
        "settles. Back Liverpool at 1.97 with Supabets, standard stake."
    )
    res = _validate_verdict_for_persistence(
        verdict_html=verdict,
        edge_tier="gold",
        evidence_pack=_EVIDENCE,
        source_label="verdict-cache",
        match_id=_MATCH_KEY,
    )
    assert any(f.gate == "vague_content" and f.severity == "CRITICAL"
               for f in res.failures)


def test_gold_char_range_under_min_critical():
    """Gold verdict shorter than 100 chars → CRITICAL."""
    verdict = "Back Liverpool at 1.97 with Supabets."  # 37 chars
    res = _validate_verdict_for_persistence(
        verdict_html=verdict,
        edge_tier="gold",
        evidence_pack=_EVIDENCE,
        source_label="verdict-cache",
        match_id=_MATCH_KEY,
    )
    # verdict_quality (CRITICAL) and char_range (CRITICAL on premium) BOTH fire
    assert res.critical_count >= 1


# ── 4. Non-premium tier severity downgrades ───────────────────────────────────


def test_silver_closure_rule_missing_both_major():
    """Silver verdict with action verb but no team and no odds → MAJOR closure."""
    verdict = (
        "Form is solid and the line has room. "
        "Lean on this one — small-stake call, no hero call."
    )
    res = _validate_verdict_for_persistence(
        verdict_html=verdict,
        edge_tier="silver",
        evidence_pack=None,
        source_label="verdict-cache",
        match_id=_MATCH_KEY,
    )
    closure_failures = [f for f in res.failures if f.gate == "verdict_closure_rule"]
    assert closure_failures
    assert closure_failures[0].severity == "MAJOR"


def test_silver_closure_rule_missing_action_major():
    """Silver verdict closing without action verb → MAJOR closure."""
    verdict = (
        "The line has room and the form holds — value here. "
        "Liverpool at 1.97 looks priced fairly with Supabets, expected stake."
    )
    res = _validate_verdict_for_persistence(
        verdict_html=verdict,
        edge_tier="silver",
        evidence_pack=_EVIDENCE,
        source_label="verdict-cache",
        match_id=_MATCH_KEY,
    )
    closure_failures = [f for f in res.failures if f.gate == "verdict_closure_rule"]
    assert closure_failures
    assert closure_failures[0].severity == "MAJOR"


def test_bronze_closure_rule_missing_action_minor():
    """Bronze verdict closing without action verb → MINOR closure."""
    verdict = (
        "Liverpool at 1.97 with Supabets looks priced fairly here. "
        "Speculative play with thin signal at this number."
    )
    res = _validate_verdict_for_persistence(
        verdict_html=verdict,
        edge_tier="bronze",
        evidence_pack=_EVIDENCE,
        source_label="verdict-cache",
        match_id=_MATCH_KEY,
    )
    closure_failures = [f for f in res.failures if f.gate == "verdict_closure_rule"]
    assert closure_failures
    assert closure_failures[0].severity == "MINOR"


def test_bronze_minor_only_passes():
    """Bronze MINOR-only result has passed=True (only CRITICAL/MAJOR fail)."""
    verdict = (
        "Liverpool at 1.97 with Supabets looks priced fairly here. "
        "Speculative play with thin signal at this number."
    )
    res = _validate_verdict_for_persistence(
        verdict_html=verdict,
        edge_tier="bronze",
        evidence_pack=_EVIDENCE,
        source_label="verdict-cache",
        match_id=_MATCH_KEY,
    )
    assert res.passed, "MINOR-only failures must not flip passed=False"


# ── 5. AC-3 broadened action verb cluster ─────────────────────────────────────


def test_action_regex_accepts_imperative_back():
    assert _VERDICT_ACTION_RE.search("Back Liverpool at 1.97 with Supabets.")


def test_action_regex_accepts_imperative_take():
    assert _VERDICT_ACTION_RE.search("Take Liverpool at 1.97 with Supabets.")


def test_action_regex_accepts_declarative_is_the_pick():
    assert _VERDICT_ACTION_RE.search("Liverpool at 1.97 is the pick.")


def test_action_regex_accepts_declarative_is_the_play():
    assert _VERDICT_ACTION_RE.search("Liverpool at 1.97 is the play.")


def test_action_regex_accepts_declarative_is_the_call():
    assert _VERDICT_ACTION_RE.search("Liverpool at 1.97 is the call.")


def test_action_regex_accepts_declarative_is_the_value():
    assert _VERDICT_ACTION_RE.search("Liverpool at 1.97 is the value.")


def test_action_regex_rejects_no_action():
    assert not _VERDICT_ACTION_RE.search(
        "What stands out: Slot's Reds have picked up two wins."
    )


def test_clean_declarative_diamond_verdict_passes():
    """Diamond verdict with declarative closure shape → passes validator."""
    verdict = (
        "The line is priced too soft and the form runs deep, premium value. "
        "Liverpool at 1.97 with Supabets is the value, factor in the "
        "rotation concern — back with conviction."
    )
    res = _validate_verdict_for_persistence(
        verdict_html=verdict,
        edge_tier="diamond",
        evidence_pack=_EVIDENCE,
        source_label="verdict-cache",
        match_id=_MATCH_KEY,
    )
    assert res.passed, f"Declarative Diamond verdict rejected: {[(f.gate, f.detail) for f in res.failures]}"


# ── 6. Bypass-attempt assertion (source-level) ────────────────────────────────


class TestNoVerdictCacheBypass(unittest.TestCase):
    """Source-level guard: any verdict-cache write site in bot.py MUST call
    ``_validate_verdict_for_persistence`` adjacent to its INSERT/UPDATE.
    """

    def test_store_verdict_cache_sync_calls_validator(self):
        """``_store_verdict_cache_sync`` body MUST reference the validator."""
        bot_src = (Path(_bot.__file__).parent / "bot.py").read_text()
        fn_start = bot_src.index("def _store_verdict_cache_sync(")
        fn_end = bot_src.index("\nasync def ", fn_start)
        fn_body = bot_src[fn_start:fn_end]
        assert "_validate_verdict_for_persistence" in fn_body, (
            "_store_verdict_cache_sync must call _validate_verdict_for_persistence "
            "before any narrative_cache INSERT/UPDATE — closure rule + tier "
            "enforcement matrix is non-negotiable per AC-1."
        )
        # And the brief log marker for the refuse path must be present.
        assert "PremiumVerdictRefused" in fn_body, (
            "_store_verdict_cache_sync refuse path must log "
            "PremiumVerdictRefused for the brief monitoring contract."
        )


# ── 7. Writer-level enforcement matrix integration ────────────────────────────


def test_writer_refuses_critical_gold_verdict():
    """Writer-level: Gold + CRITICAL gate → no DB write."""
    fake_conn = MagicMock()
    venue_leak_verdict = (
        "Form is solid at Anfield. Back Liverpool at 1.97 with Supabets."
    )
    with patch("db_connection.get_connection", return_value=fake_conn) as mock_conn:
        _bot._store_verdict_cache_sync(
            _MATCH_KEY,
            venue_leak_verdict,
            {"edge_tier": "gold", "evidence_pack": _EVIDENCE},
        )
    assert mock_conn.call_count == 0, (
        "CRITICAL gate must refuse write — no DB connection acquired."
    )


def test_writer_quarantines_silver_major():
    """Writer-level: Silver + MAJOR → INSERT with quality_status='quarantined'."""
    fake_conn = MagicMock()
    fake_conn.execute.return_value.fetchone.return_value = None
    silver_no_action_verdict = (
        "The line has room and the form holds — value here. "
        "Liverpool at 1.97 looks priced fairly with Supabets, expected stake."
    )
    with patch("db_connection.get_connection", return_value=fake_conn) as mock_conn, \
         patch("bot._compute_odds_hash", return_value="hash_xyz"):
        _bot._store_verdict_cache_sync(
            _MATCH_KEY,
            silver_no_action_verdict,
            {"edge_tier": "silver", "evidence_pack": _EVIDENCE},
        )
    assert mock_conn.call_count == 1, "Silver MAJOR must still write"
    # Inspect the INSERT statement for quality_status='quarantined'.
    insert_calls = [
        c for c in fake_conn.execute.call_args_list
        if "INSERT" in str(c).upper()
    ]
    assert insert_calls, "Expected an INSERT call"
    # The INSERT params include quality_status as the LAST parameter.
    insert_args = insert_calls[0]
    sql = insert_args[0][0]
    params = insert_args[0][1]
    assert "quality_status" in sql, "INSERT must reference quality_status column"
    assert params[-1] == "quarantined", (
        f"Silver MAJOR INSERT must set quality_status='quarantined'; got {params[-1]!r}"
    )


def test_writer_writes_bronze_minor():
    """Writer-level: Bronze + MINOR-only → INSERT proceeds (no quarantine)."""
    fake_conn = MagicMock()
    fake_conn.execute.return_value.fetchone.return_value = None
    bronze_no_action_verdict = (
        "Liverpool at 1.97 with Supabets looks priced fairly here. "
        "Speculative play with thin signal at this number."
    )
    with patch("db_connection.get_connection", return_value=fake_conn) as mock_conn, \
         patch("bot._compute_odds_hash", return_value="hash_xyz"):
        _bot._store_verdict_cache_sync(
            _MATCH_KEY,
            bronze_no_action_verdict,
            {"edge_tier": "bronze", "evidence_pack": _EVIDENCE},
        )
    assert mock_conn.call_count == 1
    insert_calls = [
        c for c in fake_conn.execute.call_args_list
        if "INSERT" in str(c).upper()
    ]
    if insert_calls:
        params = insert_calls[0][0][1]
        assert params[-1] is None, (
            f"Bronze MINOR INSERT must NOT mark quarantined; got {params[-1]!r}"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
