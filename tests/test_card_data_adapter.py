"""IMG-W2 — Card Pipeline Data Adapter tests.

Covers AC-1 through AC-8 plus backward-compat (AC-9).
"""
from __future__ import annotations

import sys
import os

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from card_pipeline import (
    _compute_team_form,
    _compute_h2h,
    _split_injuries,
    _compute_signals,
    _compute_pick_team,
    _compute_no_edge_reason,
    _compute_key_stats,
    _compute_odds_structured,
    build_card_data,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────

def _results(home_scores: list[tuple]) -> list[dict]:
    """Build a list of match-result dicts for testing.

    Each tuple is (home_key, away_key, home_score, away_score).
    """
    return [
        {
            "home": h,
            "away": a,
            "home_score": hs,
            "away_score": as_,
            "league": "test",
            "match_key": f"{h}_vs_{a}_2026-01-01",
        }
        for h, a, hs, as_ in home_scores
    ]


def _verified_base() -> dict:
    return {
        "match_key": "chiefs_vs_pirates_2026-04-06",
        "matchup": "Chiefs vs Pirates",
        "home_key": "chiefs",
        "away_key": "pirates",
        "date_str": "2026-04-06",
        "odds": {},
        "best_odds": {},
        "lineups": [],
        "injuries": [],
        "results": [],
        "ratings": {},
        "fighters": {},
        "news": [],
        "tipster": {},
        "data_sources_used": [],
    }


# ── AC-1: home_form / away_form ───────────────────────────────────────────────

class TestTeamForm:
    def test_win_loss_draw(self):
        res = _results([
            ("chiefs", "sundowns", 2, 0),   # W
            ("amazulu", "chiefs", 1, 1),     # D
            ("chiefs", "galaxy", 0, 1),      # L
        ])
        form = _compute_team_form(res, "chiefs", last_n=5)
        assert form == ["W", "D", "L"]

    def test_away_perspective(self):
        res = _results([
            ("pirates", "chiefs", 3, 0),    # chiefs away → L
            ("chiefs", "pirates", 2, 2),    # chiefs home → D
        ])
        form = _compute_team_form(res, "chiefs", last_n=5)
        assert form == ["L", "D"]

    def test_capped_at_last_n(self):
        res = _results([("chiefs", f"opp{i}", i, 0) for i in range(10)])
        form = _compute_team_form(res, "chiefs", last_n=5)
        assert len(form) == 5

    def test_missing_scores_skipped(self):
        res = [{"home": "chiefs", "away": "pirates", "home_score": None, "away_score": None, "league": "t", "match_key": "x"}]
        form = _compute_team_form(res, "chiefs")
        assert form == []

    def test_empty_results_returns_empty(self):
        assert _compute_team_form([], "chiefs") == []


# ── AC-2: signals ─────────────────────────────────────────────────────────────

class TestSignals:
    def test_all_false_when_no_data(self):
        sigs = _compute_signals(None, _verified_base())
        assert sigs == {
            "price_edge": False,
            "form": False,
            "movement": False,
            "market": False,
            "tipster": False,
            "injury": False,
        }

    def test_price_edge_true_when_positive_ev(self):
        tip = {"ev": 3.5}
        sigs = _compute_signals(tip, _verified_base())
        assert sigs["price_edge"] is True

    def test_form_true_when_results_present(self):
        verified = _verified_base()
        verified["results"] = _results([("chiefs", "pirates", 1, 0)])
        sigs = _compute_signals(None, verified)
        assert sigs["form"] is True

    def test_tipster_true_when_sources_present(self):
        verified = _verified_base()
        verified["tipster"] = {"sources": 3, "home_consensus_pct": 55.0, "away_consensus_pct": 30.0}
        sigs = _compute_signals(None, verified)
        assert sigs["tipster"] is True
        assert sigs["market"] is True

    def test_injury_true_when_injuries_present(self):
        verified = _verified_base()
        verified["injuries"] = ["Ronaldo (pirates) — injured"]
        sigs = _compute_signals(None, verified)
        assert sigs["injury"] is True

    def test_six_keys_always_present(self):
        sigs = _compute_signals(None, _verified_base())
        assert set(sigs.keys()) == {"price_edge", "form", "movement", "market", "tipster", "injury"}


# ── AC-3: h2h ────────────────────────────────────────────────────────────────

class TestH2H:
    def test_invariant_hw_plus_d_plus_aw_equals_played(self):
        res = _results([
            ("chiefs", "pirates", 2, 1),   # hw
            ("chiefs", "pirates", 1, 1),   # d
            ("pirates", "chiefs", 2, 0),   # aw (reversed)
        ])
        h2h = _compute_h2h(res, "chiefs", "pirates")
        assert h2h["played"] == 3
        assert h2h["hw"] + h2h["d"] + h2h["aw"] == h2h["played"]

    def test_home_win(self):
        res = _results([("chiefs", "pirates", 2, 0)])
        h2h = _compute_h2h(res, "chiefs", "pirates")
        assert h2h == {"played": 1, "hw": 1, "d": 0, "aw": 0}

    def test_away_win(self):
        res = _results([("chiefs", "pirates", 0, 2)])
        h2h = _compute_h2h(res, "chiefs", "pirates")
        assert h2h == {"played": 1, "hw": 0, "d": 0, "aw": 1}

    def test_draw(self):
        res = _results([("chiefs", "pirates", 1, 1)])
        h2h = _compute_h2h(res, "chiefs", "pirates")
        assert h2h == {"played": 1, "hw": 0, "d": 1, "aw": 0}

    def test_non_h2h_excluded(self):
        res = _results([
            ("chiefs", "sundowns", 2, 0),   # not a chiefs vs pirates h2h
            ("pirates", "chiefs", 1, 0),    # reversed direction → aw
        ])
        h2h = _compute_h2h(res, "chiefs", "pirates")
        assert h2h["played"] == 1
        assert h2h["aw"] == 1

    def test_empty_results(self):
        h2h = _compute_h2h([], "chiefs", "pirates")
        assert h2h == {"played": 0, "hw": 0, "d": 0, "aw": 0}


# ── AC-4: home_injuries / away_injuries ──────────────────────────────────────

class TestInjuries:
    def test_home_and_away_split(self):
        injuries = [
            "Messi (chiefs) — hamstring",
            "Ronaldo (pirates) — knee",
        ]
        home, away = _split_injuries(injuries, "chiefs", "pirates")
        assert len(home) == 1
        assert len(away) == 1
        assert "Messi" in home[0]
        assert "Ronaldo" in away[0]

    def test_format_player_status(self):
        injuries = ["Dlamini (chiefs) — ankle sprain"]
        home, away = _split_injuries(injuries, "chiefs", "pirates")
        assert home[0] == "Dlamini (ankle sprain)"

    def test_unrelated_team_excluded(self):
        injuries = ["Nkosi (sundowns) — knee"]
        home, away = _split_injuries(injuries, "chiefs", "pirates")
        assert home == []
        assert away == []

    def test_empty_input(self):
        home, away = _split_injuries([], "chiefs", "pirates")
        assert home == []
        assert away == []


# ── AC-5: pick_team ──────────────────────────────────────────────────────────

class TestPickTeam:
    def test_home_maps_to_home_display(self):
        assert _compute_pick_team("Home", "Kaizer Chiefs", "Orlando Pirates") == "Kaizer Chiefs"

    def test_away_maps_to_away_display(self):
        assert _compute_pick_team("Away", "Kaizer Chiefs", "Orlando Pirates") == "Orlando Pirates"

    def test_draw_returns_draw(self):
        assert _compute_pick_team("Draw", "Chiefs", "Pirates") == "Draw"

    def test_case_insensitive(self):
        assert _compute_pick_team("home", "Chiefs", "Pirates") == "Chiefs"
        assert _compute_pick_team("AWAY", "Chiefs", "Pirates") == "Pirates"

    def test_unknown_outcome_passthrough(self):
        assert _compute_pick_team("Over 2.5", "Chiefs", "Pirates") == "Over 2.5"


# ── AC-6: no_edge_reason ─────────────────────────────────────────────────────

class TestNoEdgeReason:
    def test_empty_when_positive_ev(self):
        verified = _verified_base()
        verified["data_sources_used"] = ["odds_snapshots"]
        reason = _compute_no_edge_reason(3.5, verified, {"ev": 3.5})
        assert reason == ""

    def test_no_data_reason(self):
        reason = _compute_no_edge_reason(0.0, _verified_base(), None)
        assert "data" in reason.lower() or "insufficient" in reason.lower()

    def test_no_positive_ev_reason(self):
        verified = _verified_base()
        verified["data_sources_used"] = ["odds_snapshots"]
        verified["odds"] = {"betway": {"home": 1.5}}
        reason = _compute_no_edge_reason(-1.0, verified, None)
        assert "expected value" in reason.lower() or "positive" in reason.lower()

    def test_no_odds_reason(self):
        verified = _verified_base()
        verified["data_sources_used"] = ["match_results"]
        reason = _compute_no_edge_reason(0.0, verified, None)
        assert reason != ""


# ── AC-7: key_stats ──────────────────────────────────────────────────────────

class TestKeyStats:
    def test_always_returns_4_boxes(self):
        stats = _compute_key_stats(_verified_base(), "chiefs", "pirates", [], [], {"played": 0, "hw": 0, "d": 0, "aw": 0})
        assert len(stats) == 4

    def test_each_box_has_label_home_away(self):
        stats = _compute_key_stats(_verified_base(), "chiefs", "pirates", [], [], {"played": 0, "hw": 0, "d": 0, "aw": 0})
        for box in stats:
            assert "label" in box
            assert "home" in box
            assert "away" in box

    def test_form_box_when_form_available(self):
        stats = _compute_key_stats(
            _verified_base(), "chiefs", "pirates",
            ["W", "W", "L"], ["D", "W", "W"],
            {"played": 0, "hw": 0, "d": 0, "aw": 0}
        )
        labels = [s["label"] for s in stats]
        assert "Form (L5)" in labels
        form_box = next(s for s in stats if s["label"] == "Form (L5)")
        assert form_box["home"] == "WWL"
        assert form_box["away"] == "DWW"

    def test_h2h_box_when_h2h_available(self):
        h2h = {"played": 5, "hw": 2, "d": 1, "aw": 2}
        stats = _compute_key_stats(_verified_base(), "chiefs", "pirates", [], [], h2h)
        labels = [s["label"] for s in stats]
        assert "H2H" in labels
        h2h_box = next(s for s in stats if s["label"] == "H2H")
        assert "draw" in h2h_box

    def test_rating_box_when_ratings_available(self):
        verified = _verified_base()
        verified["ratings"] = {
            "chiefs": {"mu": 1523.4, "phi": 80.0, "played": 30, "sport": "soccer"},
        }
        stats = _compute_key_stats(verified, "chiefs", "pirates", [], [], {"played": 0, "hw": 0, "d": 0, "aw": 0})
        labels = [s["label"] for s in stats]
        assert "Rating" in labels


# ── AC-8: odds_structured ────────────────────────────────────────────────────

class TestOddsStructured:
    def test_three_outcomes_present(self):
        verified = _verified_base()
        verified["best_odds"] = {
            "home": {"bookmaker": "betway", "odds": 2.1, "stale": ""},
            "draw": {"bookmaker": "hollywoodbets", "odds": 3.4, "stale": ""},
            "away": {"bookmaker": "gbets", "odds": 3.8, "stale": ""},
        }
        structured = _compute_odds_structured(verified)
        assert "home" in structured
        assert "draw" in structured
        assert "away" in structured

    def test_each_outcome_has_bookmaker_odds_stale(self):
        verified = _verified_base()
        verified["best_odds"] = {
            "home": {"bookmaker": "betway", "odds": 2.1, "stale": ""},
        }
        structured = _compute_odds_structured(verified)
        assert structured["home"]["bookmaker"] == "betway"
        assert structured["home"]["odds"] == 2.1
        assert "stale" in structured["home"]

    def test_empty_when_no_odds(self):
        structured = _compute_odds_structured(_verified_base())
        assert structured == {}

    def test_draw_absent_when_no_draw_odds(self):
        verified = _verified_base()
        verified["best_odds"] = {
            "home": {"bookmaker": "betway", "odds": 2.0, "stale": ""},
            "away": {"bookmaker": "gbets", "odds": 3.0, "stale": ""},
        }
        structured = _compute_odds_structured(verified)
        assert "draw" not in structured


# ── AC-9: backward compatibility via build_card_data ─────────────────────────

class TestBuildCardDataBackwardCompat:
    """Smoke-tests: build_card_data still returns all original fields plus new ones."""

    def _build(self, **kwargs):
        """Call build_card_data with a mocked verified path (no real DB needed)."""
        from unittest.mock import patch, MagicMock
        mock_verified = _verified_base()
        mock_verified["matchup"] = "Chiefs vs Pirates"
        mock_verified["data_sources_used"] = []
        with patch("card_pipeline.build_verified_data_block", return_value=mock_verified):
            with patch("card_pipeline.generate_card_analysis", return_value=""):
                card = build_card_data(
                    "chiefs_vs_pirates_2026-04-06",
                    include_analysis=False,
                    **kwargs,
                )
        return card

    def test_original_fields_present(self):
        card = self._build()
        for field in ("matchup", "home_team", "away_team", "outcome", "odds",
                      "bookmaker", "confidence", "ev", "kickoff", "venue",
                      "broadcast", "sport", "tier", "analysis_text",
                      "data_sources_used", "_verified"):
            assert field in card, f"Original field missing: {field}"

    def test_new_fields_present(self):
        card = self._build()
        for field in ("home_form", "away_form", "signals", "h2h",
                      "home_injuries", "away_injuries", "pick_team",
                      "no_edge_reason", "key_stats", "odds_structured"):
            assert field in card, f"New field missing: {field}"

    def test_home_form_is_list(self):
        card = self._build()
        assert isinstance(card["home_form"], list)

    def test_signals_has_six_keys(self):
        card = self._build()
        assert set(card["signals"].keys()) == {
            "price_edge", "form", "movement", "market", "tipster", "injury"
        }

    def test_h2h_invariant(self):
        card = self._build()
        h = card["h2h"]
        assert h["hw"] + h["d"] + h["aw"] == h["played"]

    def test_key_stats_exactly_4(self):
        card = self._build()
        assert len(card["key_stats"]) == 4

    def test_pick_team_is_string(self):
        card = self._build()
        assert isinstance(card["pick_team"], str)
