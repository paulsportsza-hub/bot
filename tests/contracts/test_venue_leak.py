"""BUILD-EVIDENCE-ENRICH-VENUE-SCOREBOARD-PROJECTION-01 (2026-04-30) — verified-list mode.

Supersedes the FIX-NARRATIVE-VENUE-LEAK-01 (2026-04-28) absolute-ban corpus.
Rule 18 was flipped from absolute-ban to verified-list — venue mentions are
allowed when they match `pack.venue` (case-insensitive) or appear in the
canonical bot/data/stadiums.json fallback (when pack.venue is empty).

Asserts:
  1. data/stadiums.json loads without error and has ≥ 80 venues.
  2. Each curated venue mentioned with pack.venue="" passes (canonical fallback).
  3. Each curated venue mentioned with pack.venue="<different venue>" fails (cross-fixture invention).
  4. pack.venue match (case-insensitive substring, either direction) is allowed.
  5. Rule 18 fail-open semantics: pack.venue empty AND no canonical hits → no leak.
  6. Specific dry-run cross-fixture cases still rejected when pack.venue is set differently.
  7. Gate 9 of `min_verdict_quality` rejects cross-fixture venue mentions.
  8. Clean text returns no leaks regardless of pack.venue.
  9. Case-insensitive matching survives the verified-list flip.
  10. Multi-venue detection deduplicates results.

Pure Python — no bot.py import, no LLM, no DB.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from narrative_spec import (
    _load_banned_venues,
    find_venue_leaks,
    validate_no_venue_leak,
    min_verdict_quality,
)


@dataclass
class _Pack:
    """Minimal stand-in for EvidencePack — only `.venue` is read by the gate."""
    venue: str = ""


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
            "goodison park",         # Everton (legacy stale per Rule 2)
            "selhurst park",         # Crystal Palace
            "fnb stadium",           # SA — Chiefs
            "loftus versfeld",       # SA — Sundowns / Bulls
            "wembley stadium",       # International
            "twickenham",            # Rugby
        ]
        for r in REQUIRED:
            assert r in venues_lower, f"Required venue missing from stadiums.json: {r!r}"


# ── 2. Canonical fallback: pack.venue empty → curated hits ALLOWED ────────────


class TestStadiumsJsonFallback:
    """When pack.venue is empty, every curated stadiums.json hit is canonical
    and therefore ALLOWED. This is the verified-list-mode replacement for the
    legacy TestPerVenueDetection (which asserted absolute-ban detection)."""

    @pytest.mark.parametrize("venue", _load_banned_venues())
    def test_venue_with_empty_pack_passes(self, venue):
        text = f"The home crowd at {venue} gives them an edge tonight."
        # pack.venue empty → canonical fallback applies → no leak
        assert find_venue_leaks(text, _Pack(venue="")) == []

    @pytest.mark.parametrize("venue", _load_banned_venues())
    def test_validate_no_venue_leak_returns_true_with_empty_pack(self, venue):
        text = f"Back the home side at {venue}."
        assert validate_no_venue_leak(text, _Pack(venue="")) is True


# ── 3. Cross-fixture invention: pack.venue set ≠ mention → LEAK ───────────────


class TestUnverifiedVenueRejected:
    """When pack.venue is set to one venue but the prose names a different
    curated venue, that's cross-fixture invention and remains a LEAK.
    These 322-test-corpus inversions cover the FIX-NARRATIVE-VOICE-COMPREHENSIVE-01
    failure modes (Stamford Bridge × Chelsea match → also flagged when on a
    different match)."""

    @pytest.mark.parametrize("venue", _load_banned_venues())
    def test_venue_with_mismatched_pack_fails(self, venue):
        # Pick a "different" pack.venue per fixture — anything not equal
        # to or substring-matching `venue`. Use a known-distinct sentinel.
        sentinel = "Sentinel Verified Ground"
        # Skip self-overlap: ensure sentinel doesn't substring-match `venue`
        # and vice-versa (defensive for future stadiums.json additions).
        if sentinel.lower() in venue.lower() or venue.lower() in sentinel.lower():
            pytest.skip(f"Sentinel collides with curated entry {venue!r}")
        text = f"The home crowd at {venue} gives them an edge tonight."
        hits = find_venue_leaks(text, _Pack(venue=sentinel))
        assert hits, f"Cross-fixture invention {venue!r} should be flagged with pack={sentinel!r}"
        assert validate_no_venue_leak(text, _Pack(venue=sentinel)) is False


# ── 4. Verified venue allowed: pack.venue == mention → ALLOWED ────────────────


class TestVerifiedVenueAllowed:
    """When pack.venue matches the venue named in prose, the gate allows it.
    Match is case-insensitive substring (either direction) so 'Anfield' vs
    'Anfield, Liverpool' both pass."""

    # 5+ cases per sport across soccer, rugby, cricket, MMA + neutral cases.
    # Each tuple: (pack_venue, prose_venue) where prose_venue is the form
    # appearing in narrative text. Both sides curated stadiums.json entries.
    VERIFIED_PAIRS = [
        # Soccer — EPL
        ("Anfield", "Anfield"),
        ("Old Trafford", "Old Trafford"),
        ("Etihad Stadium", "Etihad Stadium"),
        ("Emirates Stadium", "Emirates Stadium"),
        ("Stamford Bridge", "Stamford Bridge"),
        ("Tottenham Hotspur Stadium", "Tottenham Hotspur Stadium"),
        # Soccer — UCL / international
        ("Camp Nou", "Camp Nou"),
        ("Allianz Arena", "Allianz Arena"),
        ("San Siro", "San Siro"),
        ("Estadio Santiago Bernabéu", "Estadio Santiago Bernabéu"),
        ("Wembley Stadium", "Wembley Stadium"),
        ("Estadio Metropolitano", "Estadio Metropolitano"),
        # Soccer — PSL
        ("FNB Stadium", "FNB Stadium"),
        ("Loftus Versfeld", "Loftus Versfeld"),
        ("Orlando Stadium", "Orlando Stadium"),
        # Rugby
        ("Twickenham", "Twickenham"),
        ("Aviva Stadium", "Aviva Stadium"),
        ("Murrayfield", "Murrayfield"),
        ("Stade de France", "Stade de France"),
        ("Cape Town Stadium", "Cape Town Stadium"),
        # Cricket
        ("Wankhede Stadium", "Wankhede Stadium"),
        ("Eden Gardens", "Eden Gardens"),
        ("Newlands", "Newlands"),
        ("Wanderers", "Wanderers"),
        ("M. Chinnaswamy Stadium", "M. Chinnaswamy Stadium"),
        # MMA / boxing
        ("T-Mobile Arena", "T-Mobile Arena"),
        ("MGM Grand Garden Arena", "MGM Grand Garden Arena"),
        ("Madison Square Garden", "Madison Square Garden"),
        ("UFC Apex", "UFC Apex"),
    ]

    @pytest.mark.parametrize("pack_venue,prose_venue", VERIFIED_PAIRS)
    def test_verified_venue_passes(self, pack_venue, prose_venue):
        venues = {v.lower() for v in _load_banned_venues()}
        if pack_venue.lower() not in venues:
            pytest.skip(f"{pack_venue!r} not in stadiums.json — cannot run case in current corpus")
        text = f"The atmosphere at {prose_venue} is electric tonight. Back the home side."
        hits = find_venue_leaks(text, _Pack(venue=pack_venue))
        assert hits == [], f"Verified venue {pack_venue!r} matched against {prose_venue!r} should pass — got {hits!r}"
        assert validate_no_venue_leak(text, _Pack(venue=pack_venue)) is True

    def test_pack_venue_case_insensitive(self):
        text = "Tonight at ANFIELD the atmosphere is set."
        assert find_venue_leaks(text, _Pack(venue="anfield")) == []
        assert find_venue_leaks(text, _Pack(venue="Anfield")) == []
        assert find_venue_leaks(text, _Pack(venue="ANFIELD")) == []

    def test_pack_venue_substring_either_direction(self):
        # pack.venue carries the city suffix; prose carries the bare name.
        text = "The crowd at Anfield will turn this one."
        assert find_venue_leaks(text, _Pack(venue="Anfield, Liverpool")) == []
        # Reverse: pack.venue is bare; prose carries city suffix in stadiums.json form.
        text2 = "Tonight at Old Trafford the home form holds."
        assert find_venue_leaks(text2, _Pack(venue="Old Trafford, Manchester")) == []


# ── 5. Rule 18 fail-open semantics ────────────────────────────────────────────


class TestRule18FailOpen:
    """When pack.venue is empty AND no canonical fallback hits, the gate
    is fail-open (no leak). The legacy absolute-ban behaviour is preserved
    only in the sense that text without venue mentions remains clean."""

    def test_empty_pack_no_venue_text_no_leak(self):
        """Text without any venue mention returns no leaks regardless of pack."""
        verdict = "Back Liverpool — the form gap is huge and the table tells the story."
        assert find_venue_leaks(verdict, _Pack(venue="")) == []
        assert find_venue_leaks(verdict, None) == []

    def test_empty_pack_legitimate_canonical_mention_passes(self):
        """When pack.venue is empty, canonical fallback applies — Anfield mention OK."""
        verdict = "Back Liverpool — Anfield carries the form home."
        assert find_venue_leaks(verdict, _Pack(venue="")) == []

    def test_none_pack_treated_as_empty(self):
        """Legacy callers passing no pack get the canonical-fallback default."""
        verdict = "Back Chelsea — Stamford Bridge holds firm tonight."
        assert find_venue_leaks(verdict, None) == []
        assert find_venue_leaks(verdict) == []  # default arg

    def test_dict_pack_with_venue_field(self):
        """Serialised evidence_pack dicts (not dataclass) must work too."""
        text = "The atmosphere at Anfield is set."
        assert find_venue_leaks(text, {"venue": "Anfield"}) == []
        # Different venue in pack → leak
        assert find_venue_leaks(text, {"venue": "Old Trafford"}), "expected leak when pack.venue differs"


# ── 6. Specific dry-run cross-fixture cases (Stamford Bridge / Villa Park / Goodison) ──


class TestDryRunLeakedVenuesCaught:
    """The exact verdicts that leaked in the FIX-NARRATIVE-VOICE-COMPREHENSIVE-01
    dry-run still fail the verified-list gate when pack.venue is set
    differently — i.e. when the leak is genuinely cross-fixture."""

    def test_stamford_bridge_caught_when_pack_is_different(self):
        # A Chelsea-vs-X match where pack.venue is correctly Stamford Bridge
        # would PASS — that's the verified-list win. But here we simulate
        # a different fixture (e.g. Newcastle home) where the verdict
        # incorrectly cites Stamford Bridge.
        verdict = ("Newcastle look the value at 1.74 on Supabets, with the Magpies in "
                   "strong home form. The head-to-head history leans the hosts' way at "
                   "Stamford Bridge for the analytical edge. Back Newcastle.")
        hits = find_venue_leaks(verdict, _Pack(venue="St James' Park"))
        # Note: skip if neither the prose venue nor the pack.venue is in the corpus.
        venues = {v.lower() for v in _load_banned_venues()}
        if "stamford bridge" not in venues:
            pytest.skip("stamford bridge not in stadiums.json corpus")
        assert "Stamford Bridge" in hits or any(h.lower() == "stamford bridge" for h in hits)

    def test_villa_park_caught_when_pack_is_different(self):
        verdict = ("Tottenham are the pick at 2.25. Spurs at Villa Park carry threat. Back Spurs.")
        hits = find_venue_leaks(verdict, _Pack(venue="Tottenham Hotspur Stadium"))
        venues = {v.lower() for v in _load_banned_venues()}
        if "villa park" not in venues:
            pytest.skip("villa park not in stadiums.json corpus")
        assert any(h.lower() == "villa park" for h in hits)

    def test_goodison_park_caught_when_pack_is_different(self):
        verdict = ("City roll into Goodison Park in strong form with three wins from their "
                   "last five. Back Manchester City.")
        hits = find_venue_leaks(verdict, _Pack(venue="Etihad Stadium"))
        venues = {v.lower() for v in _load_banned_venues()}
        if "goodison park" not in venues:
            pytest.skip("goodison park not in stadiums.json corpus")
        assert any(h.lower() == "goodison park" for h in hits)


# ── 7. Clean text passes regardless of pack ───────────────────────────────────


class TestCleanTextPasses:
    """Verdicts that don't mention a venue must pass under both modes."""

    def test_clean_verdict_no_leak_with_pack(self):
        verdict = ("Back Brighton at 2.70 with WSB. The Magpies have lost five from five "
                   "and Brighton have won four from five. Back Brighton.")
        assert find_venue_leaks(verdict, _Pack(venue="Anfield")) == []
        assert validate_no_venue_leak(verdict, _Pack(venue="Anfield")) is True

    def test_clean_verdict_no_leak_with_empty_pack(self):
        verdict = ("Back Brighton at 2.70 with WSB. The Magpies have lost five from five.")
        assert find_venue_leaks(verdict, _Pack(venue="")) == []

    def test_generic_park_word_no_false_positive(self):
        """Generic 'park' as in 'park the bus' must not trigger any banned venue."""
        verdict = ("Take the under at 1.90 on Betway — both sides will park the bus and the "
                   "form suggests goals are scarce. Back the under.")
        assert find_venue_leaks(verdict, _Pack(venue="")) == []
        assert find_venue_leaks(verdict, _Pack(venue="Anfield")) == []

    def test_generic_stadium_word_no_false_positive(self):
        verdict = ("The home stadium gives Liverpool an edge here. Back the Reds.")
        assert find_venue_leaks(verdict, _Pack(venue="")) == []
        assert find_venue_leaks(verdict, _Pack(venue="Old Trafford")) == []


# ── 8. Gate 9 wired into min_verdict_quality ──────────────────────────────────


class TestGate9Wiring:
    """min_verdict_quality must reject cross-fixture venue leaks via Gate 9
    when evidence_pack carries a different venue."""

    def test_gate_9_rejects_cross_fixture_venue_in_verdict(self):
        # Verdict satisfies Gates 1-8 but cites Stamford Bridge while
        # evidence_pack.venue is Anfield (Liverpool match).
        verdict = ("Back Liverpool at 1.74 with Supabets. The Reds hold home form and "
                   "the head-to-head leans the hosts' way at Stamford Bridge for "
                   "the analytical edge. Back Liverpool.")
        evidence_pack = {"venue": "Anfield"}
        assert min_verdict_quality(verdict, tier="gold", evidence_pack=evidence_pack) is False

    def test_gate_9_passes_verified_venue(self):
        # Verdict cites Anfield AND evidence_pack.venue is Anfield → passes.
        verdict = ("Back Liverpool at 1.74 with Supabets. The Reds hold home form and "
                   "Anfield carries the analytical edge tonight for a disciplined back. "
                   "Back Liverpool.")
        evidence_pack = {"venue": "Anfield"}
        assert min_verdict_quality(verdict, tier="gold", evidence_pack=evidence_pack) is True

    def test_gate_9_passes_clean_verdict(self):
        verdict = ("Back Chelsea at 1.74 with Supabets. Maresca's Blues hold home form and "
                   "the head-to-head history leans the hosts' way for the analytical edge "
                   "and disciplined back. Back Chelsea.")
        evidence_pack = {"venue": "Stamford Bridge"}
        assert min_verdict_quality(verdict, tier="gold", evidence_pack=evidence_pack) is True


# ── 9. Case-insensitive matching ──────────────────────────────────────────────


class TestCaseInsensitive:
    def test_uppercase_venue_with_mismatched_pack(self):
        verdict = "Back Liverpool — STAMFORD BRIDGE will be rocking."
        hits = find_venue_leaks(verdict, _Pack(venue="Anfield"))
        assert hits, "expected leak — uppercase venue with different pack.venue"
        assert validate_no_venue_leak(verdict, _Pack(venue="Anfield")) is False

    def test_lowercase_venue_with_mismatched_pack(self):
        verdict = "Back Manchester City — anfield is a fortress."
        hits = find_venue_leaks(verdict, _Pack(venue="Etihad Stadium"))
        assert hits

    def test_mixed_case_pack_venue_normalised(self):
        text = "Tonight at the Etihad Stadium the home form holds."
        assert find_venue_leaks(text, _Pack(venue="EtIhAd StAdIuM")) == []


# ── 10. Multi-venue detection ─────────────────────────────────────────────────


class TestMultiVenueDetection:
    def test_multiple_curated_venues_with_one_verified(self):
        """When pack.venue verifies one and prose names two, only the
        unverified mention is flagged."""
        verdict = "From Stamford Bridge to Anfield, the form is night and day."
        hits = find_venue_leaks(verdict, _Pack(venue="Anfield"))
        # Anfield is verified; Stamford Bridge is the cross-fixture leak.
        hits_lower = {h.lower() for h in hits}
        assert "anfield" not in hits_lower
        assert "stamford bridge" in hits_lower

    def test_unique_dedup(self):
        verdict = "Anfield. Anfield. Anfield."
        hits = find_venue_leaks(verdict, _Pack(venue="Old Trafford"))
        # Should report unique only — one entry for "Anfield".
        assert len(hits) == 1


# ── 11. Empty / edge inputs ───────────────────────────────────────────────────


class TestEdgeInputs:
    def test_empty_string(self):
        assert find_venue_leaks("", _Pack(venue="")) == []
        assert find_venue_leaks("", _Pack(venue="Anfield")) == []
        assert validate_no_venue_leak("", _Pack(venue="Anfield")) is True

    def test_whitespace_only(self):
        assert find_venue_leaks("   \n\t  ", _Pack(venue="Anfield")) == []
        assert validate_no_venue_leak("   ", _Pack(venue="")) is True

    def test_none_text_safe_via_legacy_signature(self):
        # find_venue_leaks must not crash on falsy text under either pack mode.
        assert find_venue_leaks("", _Pack(venue="Anfield")) == []
        assert find_venue_leaks("", None) == []


# ── 12. Cache stability ───────────────────────────────────────────────────────


class TestCacheStability:
    """Repeated calls must return stable results (loader is cached)."""

    def test_repeated_load_returns_same_tuple(self):
        a = _load_banned_venues()
        b = _load_banned_venues()
        assert a is b  # cached, same object identity
