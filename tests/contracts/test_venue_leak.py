"""FIX-NARRATIVE-VENUE-LEAK-01 regression guard (2026-04-28).

Asserts:
  1. data/stadiums.json loads without error and has ≥ 80 venues.
  2. Every curated venue name triggers `find_venue_leaks` (substring match).
  3. `validate_no_venue_leak` returns False on any venue mention.
  4. Clean text returns no leaks.
  5. Gate 9 of `min_verdict_quality` rejects venue-containing verdicts.
  6. Specific dry-run leaks (Stamford Bridge, Villa Park, Goodison Park) are caught.
  7. Case-insensitive matching.
  8. Common false-positive guards (generic "stadium" / "park" alone don't trigger).

Pure Python — no bot.py import, no LLM, no DB.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from narrative_spec import (
    _load_banned_venues,
    find_venue_leaks,
    validate_no_venue_leak,
    min_verdict_quality,
)


# ── 1. stadiums.json loads + has reasonable coverage ──────────────────────────


class TestStadiumsListIntegrity:
    """data/stadiums.json must load and carry meaningful coverage."""

    def test_stadiums_json_loads(self):
        venues = _load_banned_venues()
        assert isinstance(venues, tuple)
        assert len(venues) >= 80, f"Expected ≥ 80 curated venues, got {len(venues)}"

    def test_no_empty_or_whitespace_entries(self):
        for v in _load_banned_venues():
            assert v.strip() == v, f"Whitespace-padded entry: {v!r}"
            assert len(v) >= 4, f"Suspiciously short entry: {v!r}"

    def test_no_generic_single_words(self):
        """Bare 'Stadium', 'Park', 'Arena', 'Ground' would cause false positives."""
        BANNED_GENERICS = {"stadium", "park", "arena", "ground", "field"}
        for v in _load_banned_venues():
            assert v.lower() not in BANNED_GENERICS, (
                f"Generic single-word venue {v!r} would cause widespread false positives"
            )

    def test_high_volume_leagues_covered(self):
        """EPL + PSL + UCL major venues must be present."""
        venues_lower = {v.lower() for v in _load_banned_venues()}
        REQUIRED = [
            "stamford bridge",       # Chelsea
            "old trafford",          # Man United
            "anfield",               # Liverpool
            "etihad stadium",        # Man City
            "emirates stadium",      # Arsenal
            "villa park",            # Aston Villa
            "goodison park",         # Everton (banned even though stale per Rule 2)
            "selhurst park",         # Crystal Palace
            "fnb stadium",           # SA — Chiefs
            "loftus versfeld",       # SA — Sundowns / Bulls
            "wembley stadium",       # International
            "twickenham",            # Rugby
        ]
        for r in REQUIRED:
            assert r in venues_lower, f"Required venue missing from stadiums.json: {r!r}"


# ── 2. Per-venue scan triggers a hit ──────────────────────────────────────────


class TestPerVenueDetection:
    """Every entry in the curated list must trigger find_venue_leaks."""

    @pytest.mark.parametrize("venue", _load_banned_venues())
    def test_venue_in_sentence_triggers_hit(self, venue):
        text = f"The home crowd at {venue} gives them an edge tonight."
        hits = find_venue_leaks(text)
        assert hits, f"Curated venue {venue!r} not detected in: {text!r}"

    @pytest.mark.parametrize("venue", _load_banned_venues())
    def test_validate_no_venue_leak_returns_false(self, venue):
        text = f"Back the home side at {venue}."
        assert validate_no_venue_leak(text) is False


# ── 3. Specific dry-run leaks caught ──────────────────────────────────────────


class TestDryRunLeakedVenuesCaught:
    """The exact verdicts that leaked in the FIX-NARRATIVE-VOICE-COMPREHENSIVE-01
    dry-run must be rejected by this gate."""

    def test_stamford_bridge_caught(self):
        # From Sonnet Card 5: Chelsea vs Nottingham Forest
        verdict = ("Maresca's Chelsea look the value at 1.74 on Supabets, with the Blues in "
                   "strong home form and Forest arriving as the shakier side on the road. "
                   "The head-to-head history leans Chelsea's way at Stamford Bridge, and the "
                   "form gap between these two sides is hard to ignore. Back Chelsea.")
        hits = find_venue_leaks(verdict)
        assert "Stamford Bridge" in hits or "stamford bridge" in [h.lower() for h in hits]
        assert validate_no_venue_leak(verdict) is False

    def test_villa_park_caught(self):
        # From Sonnet Card 7: Aston Villa vs Tottenham
        verdict = ("Emery's Villa are the pick at 2.25 on Supabets. Villa at Villa Park "
                   "carry genuine threat. Back Villa.")
        hits = find_venue_leaks(verdict)
        assert any("villa park" == h.lower() for h in hits)
        assert validate_no_venue_leak(verdict) is False

    def test_goodison_park_caught(self):
        # From Haiku Card 9: Everton vs Manchester City
        verdict = ("City roll into Goodison Park in strong form with three wins from their "
                   "last five. Back Manchester City.")
        hits = find_venue_leaks(verdict)
        assert any("goodison park" == h.lower() for h in hits)
        assert validate_no_venue_leak(verdict) is False


# ── 4. Clean text passes ──────────────────────────────────────────────────────


class TestCleanTextPasses:
    """Verdicts that don't mention a venue must pass."""

    def test_clean_verdict_no_leak(self):
        verdict = ("Back Brighton at 2.70 with WSB. The Magpies have lost five from five "
                   "and Brighton have won four from five. Back Brighton.")
        assert find_venue_leaks(verdict) == []
        assert validate_no_venue_leak(verdict) is True

    def test_generic_home_advantage_no_leak(self):
        verdict = ("Back the home side at 1.85 — the form gap is massive and the home crowd "
                   "will turn this one. Back Arsenal.")
        assert find_venue_leaks(verdict) == []
        assert validate_no_venue_leak(verdict) is True

    def test_generic_park_word_no_false_positive(self):
        """Generic 'park' as in 'park the bus' shouldn't trigger any banned venue."""
        verdict = ("Take the under at 1.90 on Betway — both sides will park the bus and the "
                   "form suggests goals are scarce. Back the under.")
        assert find_venue_leaks(verdict) == []

    def test_generic_stadium_word_no_false_positive(self):
        verdict = ("The home stadium gives Liverpool an edge here. Back the Reds.")
        # "Anfield" is in the curated list but the verdict doesn't mention it.
        # Generic "home stadium" must NOT trigger a false positive.
        assert find_venue_leaks(verdict) == []


# ── 5. Gate 9 wired into min_verdict_quality ──────────────────────────────────


class TestGate9Wiring:
    """min_verdict_quality must reject venue leaks via Gate 9."""

    def test_gate_9_rejects_venue_in_verdict(self):
        # Verdict satisfies Gates 1-8 but contains "Stamford Bridge".
        verdict = ("Back Chelsea at 1.74 with Supabets. Maresca's Blues hold home form and "
                   "the head-to-head history leans Chelsea's way at Stamford Bridge for "
                   "the analytical edge. Back Chelsea.")
        assert min_verdict_quality(verdict, tier="gold") is False

    def test_gate_9_passes_clean_verdict(self):
        # Same verdict shape, no venue mention — must pass all 9 gates.
        verdict = ("Back Chelsea at 1.74 with Supabets. Maresca's Blues hold home form and "
                   "the head-to-head history leans the hosts' way for the analytical edge "
                   "and disciplined back. Back Chelsea.")
        assert min_verdict_quality(verdict, tier="gold") is True


# ── 6. Case-insensitive matching ──────────────────────────────────────────────


class TestCaseInsensitive:
    def test_uppercase_venue_caught(self):
        verdict = "Back Chelsea — STAMFORD BRIDGE will be rocking."
        assert find_venue_leaks(verdict)
        assert validate_no_venue_leak(verdict) is False

    def test_lowercase_venue_caught(self):
        verdict = "Back Liverpool — anfield is a fortress."
        assert find_venue_leaks(verdict)
        assert validate_no_venue_leak(verdict) is False

    def test_mixed_case_venue_caught(self):
        verdict = "Back Manchester City at the EtIhAd StAdIuM."
        assert find_venue_leaks(verdict)
        assert validate_no_venue_leak(verdict) is False


# ── 7. Multi-venue detection ──────────────────────────────────────────────────


class TestMultiVenueDetection:
    def test_multiple_venues_all_reported(self):
        verdict = "From Stamford Bridge to Anfield, the form is night and day."
        hits = find_venue_leaks(verdict)
        assert len(hits) >= 2
        hits_lower = {h.lower() for h in hits}
        assert "stamford bridge" in hits_lower
        assert "anfield" in hits_lower

    def test_unique_dedup(self):
        verdict = "Anfield. Anfield. Anfield."
        hits = find_venue_leaks(verdict)
        # Should report unique only — one entry for "Anfield".
        assert len(hits) == 1


# ── 8. Empty / edge inputs ────────────────────────────────────────────────────


class TestEdgeInputs:
    def test_empty_string(self):
        assert find_venue_leaks("") == []
        assert validate_no_venue_leak("") is True

    def test_whitespace_only(self):
        assert find_venue_leaks("   \n\t  ") == []
        assert validate_no_venue_leak("   ") is True

    def test_none_safe(self):
        # validate_no_venue_leak takes str — but find_venue_leaks must not crash on falsy.
        # (We don't pass None directly; this guards the empty path.)
        assert find_venue_leaks("") == []


# ── 9. Cache stability ────────────────────────────────────────────────────────


class TestCacheStability:
    """Repeated calls must return stable results (loader is cached)."""

    def test_repeated_load_returns_same_tuple(self):
        a = _load_banned_venues()
        b = _load_banned_venues()
        assert a is b  # cached, same object identity
