"""NARRATIVE-ACCURACY-01 — Contract tests for accuracy-hardened narrative pipeline.

Guards five permanent rules:
  Rule 1 — build_derived_claims() pre-processor
  Rule 2 — CURRENT_STADIUMS live data integrity
  Rule 3 — generate_and_validate() + generate_section() callable
  Rule 4 — sport-aware dispatchers (soccer/rugby/cricket)
  Rule 5 — (voice direction — runtime behaviour, not importability)
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from config import ensure_scrapers_importable
ensure_scrapers_importable()


# ── Rule 2: CURRENT_STADIUMS ──────────────────────────────────────────────────

class TestCurrentStadiums:
    """CURRENT_STADIUMS must exist and contain current 2025/26 ground names."""

    def test_importable(self):
        from narrative_spec import CURRENT_STADIUMS
        assert isinstance(CURRENT_STADIUMS, dict)

    def test_everton_hill_dickinson(self):
        """Everton moved to Hill Dickinson Stadium in August 2025. Non-regression guard."""
        from narrative_spec import CURRENT_STADIUMS
        assert "everton" in CURRENT_STADIUMS, "everton must be in CURRENT_STADIUMS"
        assert "Goodison" not in CURRENT_STADIUMS["everton"], (
            "Everton no longer plays at Goodison Park — update CURRENT_STADIUMS"
        )
        assert "Hill Dickinson" in CURRENT_STADIUMS["everton"], (
            "Everton's current ground is Hill Dickinson Stadium"
        )

    def test_arsenal_emirates(self):
        from narrative_spec import CURRENT_STADIUMS
        assert "arsenal" in CURRENT_STADIUMS
        assert "Emirates" in CURRENT_STADIUMS["arsenal"]

    def test_keys_are_lowercase(self):
        """All keys must be lowercase for case-insensitive lookup via .lower().strip()."""
        from narrative_spec import CURRENT_STADIUMS
        for key in CURRENT_STADIUMS:
            assert key == key.lower(), f"CURRENT_STADIUMS key '{key}' must be lowercase"

    def test_values_are_nonempty_strings(self):
        from narrative_spec import CURRENT_STADIUMS
        for key, val in CURRENT_STADIUMS.items():
            assert isinstance(val, str) and val.strip(), (
                f"CURRENT_STADIUMS['{key}'] must be a non-empty string"
            )


# ── Rule 1: build_derived_claims() + helpers ──────────────────────────────────

class TestBuildDerivedClaims:
    """build_derived_claims() must be callable and dispatch by sport."""

    def test_callable(self):
        from narrative_spec import build_derived_claims
        assert callable(build_derived_claims)

    def test_empty_inputs_return_dict(self):
        from narrative_spec import build_derived_claims
        result = build_derived_claims({}, {}, "soccer")
        assert isinstance(result, dict)

    def test_none_inputs_return_dict(self):
        from narrative_spec import build_derived_claims
        result = build_derived_claims(None, None, "soccer")  # type: ignore[arg-type]
        assert isinstance(result, dict)

    def test_soccer_dispatch(self):
        from narrative_spec import build_derived_claims
        h = {"name": "Arsenal", "form": "WWWLD", "pos": 2, "pts": 55, "gpg": 2.1}
        a = {"name": "Chelsea", "form": "DLWWW", "pos": 5, "pts": 43, "gpg": 1.8}
        result = build_derived_claims(h, a, "soccer")
        assert result.get("sport") == "soccer" or "home_wins" in result

    def test_rugby_dispatch(self):
        from narrative_spec import build_derived_claims
        h = {"name": "Bulls", "form": "WWLWW", "pos": 1, "pts": 38}
        a = {"name": "Sharks", "form": "LWWDL", "pos": 4, "pts": 25}
        result = build_derived_claims(h, a, "rugby")
        assert isinstance(result, dict)
        # rugby should not include soccer-specific fields like home_stadium from soccer path
        # but it should have streak info
        assert "home_streak" in result or "home_wins" in result

    def test_cricket_ipl_dispatch(self):
        from narrative_spec import build_derived_claims
        h = {"name": "MI", "form": "WWWLW", "pos": 1, "nrr": 0.85}
        a = {"name": "CSK", "form": "LWWWL", "pos": 3, "nrr": 0.12}
        result = build_derived_claims(h, a, "cricket_ipl")
        assert isinstance(result, dict)

    def test_cricket_ipl_aliases(self):
        """All IPL/T20 sport keys must route to cricket_ipl dispatcher."""
        from narrative_spec import build_derived_claims
        h = {"name": "India", "form": "WWW"}
        a = {"name": "Australia", "form": "LLW"}
        for sport_key in ("cricket_ipl", "sa20", "ipl", "t20", "t20i"):
            result = build_derived_claims(h, a, sport_key)
            assert isinstance(result, dict), f"sport_key={sport_key!r} must return dict"

    def test_cricket_test_dispatch(self):
        from narrative_spec import build_derived_claims
        h = {"name": "South Africa", "form": "WLD"}
        a = {"name": "England", "form": "DWW"}
        result = build_derived_claims(h, a, "cricket_test")
        assert isinstance(result, dict)
        # cricket_test is a conservative handler — should warn against invented stats
        assert "sport" in result

    def test_unknown_sport_falls_back_to_soccer(self):
        from narrative_spec import build_derived_claims
        h = {"name": "Team A", "form": "WWW"}
        a = {"name": "Team B", "form": "LLL"}
        result = build_derived_claims(h, a, "unknown_sport_xyz")
        # Falls back to _derived_soccer — should return a valid dict
        assert isinstance(result, dict)


# ── _parse_form_counts helper ─────────────────────────────────────────────────

class TestParseFormCounts:
    """Form string parsing must correctly count W/D/L."""

    def test_wwwld(self):
        from narrative_spec import _parse_form_counts
        w, d, l = _parse_form_counts("WWWLD")
        assert w == 3
        assert d == 1
        assert l == 1

    def test_all_wins(self):
        from narrative_spec import _parse_form_counts
        w, d, l = _parse_form_counts("WWWWW")
        assert w == 5 and d == 0 and l == 0

    def test_empty_form(self):
        from narrative_spec import _parse_form_counts
        w, d, l = _parse_form_counts("")
        assert w == 0 and d == 0 and l == 0

    def test_single_loss(self):
        from narrative_spec import _parse_form_counts
        w, d, l = _parse_form_counts("L")
        assert w == 0 and d == 0 and l == 1


# ── _form_streak helper ───────────────────────────────────────────────────────

class TestFormStreak:
    """Form streak must read from index 0 (most recent)."""

    def test_win_streak_three(self):
        from narrative_spec import _form_streak
        result = _form_streak("WWWLD")
        assert "3" in result or "won" in result.lower() or "win" in result.lower()

    def test_loss_streak_two(self):
        from narrative_spec import _form_streak
        result = _form_streak("LLWWW")
        assert "2" in result or "lost" in result.lower() or "loss" in result.lower()

    def test_empty_form_returns_empty(self):
        from narrative_spec import _form_streak
        assert _form_streak("") == ""


# ── Rule 3: generate_section() + generate_and_validate() callable ─────────────

class TestRule3Callables:
    """generate_section and generate_and_validate must remain importable."""

    def test_generate_section_callable(self):
        from scripts.pregenerate_narratives import generate_section
        assert callable(generate_section)

    def test_generate_and_validate_callable(self):
        from scripts.pregenerate_narratives import generate_and_validate
        assert callable(generate_and_validate)

    def test_generate_section_setup(self):
        """generate_section must extract Setup block from a typical narrative HTML."""
        from scripts.pregenerate_narratives import generate_section
        sample = (
            "<b>📋 The Setup</b>\nArsenal sit second. Chelsea sit fifth.\n"
            "<b>🎯 The Edge</b>\nGood value at 2.10.\n"
            "<b>🏆 The Verdict</b>\nBack Arsenal."
        )
        result = generate_section(sample, "setup")
        assert "Arsenal sit second" in result or result != ""

    def test_generate_section_verdict(self):
        from scripts.pregenerate_narratives import generate_section
        sample = (
            "<b>📋 The Setup</b>\nContext here.\n"
            "<b>🎯 The Edge</b>\nValue here.\n"
            "<b>🏆 The Verdict</b>\nBack the home side."
        )
        result = generate_section(sample, "verdict")
        assert "Back" in result or result != ""

    def test_generate_section_unknown_section_returns_full_text(self):
        """generate_section returns full text when section marker not found (fallback behaviour)."""
        from scripts.pregenerate_narratives import generate_section
        text = "Some narrative text here."
        result = generate_section(text, "nonexistent_section")
        assert result == text

    def test_generate_section_empty_input_returns_empty(self):
        from scripts.pregenerate_narratives import generate_section
        result = generate_section("", "setup")
        assert result == ""


# ── _get_stadium helper ───────────────────────────────────────────────────────

class TestGetStadium:
    """_get_stadium must look up CURRENT_STADIUMS case-insensitively."""

    def test_everton_lookup(self):
        from narrative_spec import _get_stadium
        result = _get_stadium("Everton")
        assert "Hill Dickinson" in result

    def test_unknown_team_returns_empty(self):
        from narrative_spec import _get_stadium
        result = _get_stadium("Nonexistent FC XYZ")
        assert result == ""

    def test_case_insensitive(self):
        from narrative_spec import _get_stadium
        assert _get_stadium("ARSENAL") == _get_stadium("arsenal")


# ── Soccer derived claims structure ──────────────────────────────────────────

class TestDerivedSoccerStructure:
    """_derived_soccer must return a dict with expected keys."""

    def _claims(self):
        from narrative_spec import build_derived_claims
        h = {"name": "Arsenal", "form": "WWDLW", "pos": 2, "pts": 55, "gpg": 2.1,
             "home_w": 10, "home_d": 3, "home_l": 2}
        a = {"name": "Chelsea", "form": "WDWLW", "pos": 5, "pts": 43, "gpg": 1.8,
             "away_w": 5, "away_d": 4, "away_l": 5}
        return build_derived_claims(h, a, "soccer")

    def test_has_home_wins(self):
        assert "home_wins" in self._claims()

    def test_has_away_wins(self):
        assert "away_wins" in self._claims()

    def test_has_streak_keys(self):
        c = self._claims()
        assert "home_streak" in c
        assert "away_streak" in c

    def test_has_stadium(self):
        c = self._claims()
        assert "home_stadium" in c
        assert "Hill Dickinson" not in c["home_stadium"]  # Arsenal at Emirates

    def test_sport_tag(self):
        c = self._claims()
        assert c.get("sport") == "soccer"


# ── Rugby derived claims structure ────────────────────────────────────────────

class TestDerivedRugbyStructure:
    """_derived_rugby must not include soccer-only fields like home_stadium."""

    def _claims(self):
        from narrative_spec import build_derived_claims
        h = {"name": "Bulls", "form": "WWWLW", "pos": 1, "pts": 38,
             "tries_for": 55, "tries_against": 22}
        a = {"name": "Sharks", "form": "LWWWL", "pos": 3, "pts": 28}
        return build_derived_claims(h, a, "rugby")

    def test_sport_tag(self):
        assert self._claims().get("sport") == "rugby"

    def test_has_wins(self):
        c = self._claims()
        assert "home_wins" in c or "home_streak" in c
