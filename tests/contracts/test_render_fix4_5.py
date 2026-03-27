"""RENDER-FIX4-5 contract tests — H2H Dedup + Risk Seed Entropy.

Tests required by brief:
1. H2H single-source: build_verified_narrative() no longer injects H2H into setup sentences.
   NarrativeSpec._render_setup() still includes H2H bridge (single source).
2. Risk diversity: 5 different matches produce at least 3 distinct risk texts.
3. No H2H regression: _render_setup() still includes H2H bridge when spec.h2h_summary is set.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from narrative_spec import NarrativeSpec, _build_risk_factors, _render_setup

# ── Helpers ────────────────────────────────────────────────────────────────────

_SAMPLE_CTX = {
    "home": {
        "name": "Arsenal",
        "position": 2,
        "points": 55,
        "form": "WWWDL",
        "games_played": 5,
        "record": "W15 D8 L5",
        "goals_per_game": 2.1,
        "home_record": "W9 D3 L2",
        "coach": "Mikel Arteta",
    },
    "away": {
        "name": "Chelsea",
        "position": 8,
        "points": 38,
        "form": "LWDWL",
        "games_played": 5,
        "record": "W10 D8 L10",
        "goals_per_game": 1.5,
        "away_record": "W4 D4 L6",
        "coach": "Enzo Maresca",
    },
    "head_to_head": [
        {"home": "Arsenal", "away": "Chelsea", "score": "3-1", "date": "2025-10-20"},
        {"home": "Chelsea", "away": "Arsenal", "score": "2-2", "date": "2025-04-15"},
        {"home": "Arsenal", "away": "Chelsea", "score": "1-0", "date": "2024-10-19"},
    ],
    "league": "epl",
    "venue": "Emirates Stadium",
}


def _make_edge(match_key: str, outcome: str = "home", sport: str = "soccer") -> dict:
    return {
        "match_key": match_key,
        "outcome": outcome,
        "sport": sport,
        "home_team": match_key.split("_vs_")[0] if "_vs_" in match_key else "Home",
        "away_team": match_key.split("_vs_")[1].split("_")[0] if "_vs_" in match_key else "Away",
        "stale_minutes": 0,
        "confirming_signals": 0,
        "movement_direction": "neutral",
        "tipster_against": 0,
    }


# ── Test 1: H2H single-source — build_verified_narrative() no longer adds H2H ─

class TestH2HSingleSource:
    """FIX-4: build_verified_narrative() must not inject H2H into setup sentences."""

    def test_build_verified_narrative_no_h2h_in_setup(self):
        """H2H data in ctx_data must NOT produce H2H sentences in the setup list."""
        import bot  # noqa: PLC0415
        result = bot.build_verified_narrative(_SAMPLE_CTX, tips=None, sport="soccer")
        setup_text = " ".join(result.get("setup", []))
        # H2H should not appear in verified_narrative setup any more
        assert "meetings" not in setup_text.lower(), (
            f"build_verified_narrative() still injects H2H into setup: {setup_text!r}"
        )
        assert "head to head" not in setup_text.lower(), (
            f"build_verified_narrative() still injects H2H into setup: {setup_text!r}"
        )
        assert "most recent was" not in setup_text.lower(), (
            "build_verified_narrative() still injects H2H 'most recent was' into setup"
        )


# ── Test 2: Risk diversity — 5 matches yield at least 3 distinct risk texts ───

class TestRiskSeedEntropy:
    """FIX-5: High-entropy seed must produce diverse risk text across cards."""

    def test_risk_diversity_five_matches(self):
        """5 different matches (all confirming=0) must produce >= 3 distinct texts."""
        matches = [
            ("arsenal_vs_chelsea_2026-03-01", "home", "soccer"),
            ("sundowns_vs_pirates_2026-03-01", "away", "soccer"),
            ("bulls_vs_sharks_2026-03-08", "home", "rugby"),
            ("proteas_vs_england_2026-03-10", "away", "cricket"),
            ("spurs_vs_liverpool_2026-03-15", "draw", "soccer"),
        ]
        risk_texts = set()
        for match_key, outcome, sport in matches:
            ed = _make_edge(match_key, outcome, sport)
            factors = _build_risk_factors(ed, ctx_data=None, sport=sport)
            # The single factor text (default path, no confirming signals)
            risk_texts.add(factors[0] if factors else "")

        assert len(risk_texts) >= 3, (
            f"Expected >= 3 distinct risk texts from 5 matches, got {len(risk_texts)}: "
            + str(risk_texts)
        )


# ── Test 3: No H2H regression — _render_setup() still includes H2H bridge ────

class TestRenderSetupH2HBridge:
    """FIX-4 regression: NarrativeSpec._render_setup() must still render H2H."""

    def test_render_setup_includes_h2h_bridge(self):
        """When spec.h2h_summary is set, _render_setup() must include H2H text."""
        spec = NarrativeSpec(
            home_name="Arsenal",
            away_name="Chelsea",
            competition="Premier League",
            sport="soccer",
            home_story_type="momentum",
            away_story_type="inconsistent",
            home_form="WWWDL",
            away_form="LWDWL",
            home_position=2,
            away_position=8,
            h2h_summary="3 meetings: Arsenal 2W 1D 0L",
            ev_pct=3.5,
            odds=2.1,
            outcome="home",
            bookmaker="betway",
        )
        output = _render_setup(spec)
        # H2H bridge should appear exactly once
        h2h_count = output.lower().count("head to head")
        assert h2h_count == 1, (
            f"Expected H2H bridge exactly once in _render_setup() output, "
            f"found {h2h_count} times. Output:\n{output}"
        )
        assert "arsenal" in output.lower() or "chelsea" in output.lower()
