"""REGFIX-04: CTA Bookmaker Alignment tests.

Verifies that _select_best_bookmaker_for_outcome() picks the bookmaker with
the best odds for the RECOMMENDED outcome, not the globally highest odds.
"""
import pytest

from bot import _select_best_bookmaker_for_outcome


class TestCTABookmakerSelection:
    def test_selects_best_for_home(self):
        odds = {
            "gbets": {"home": 5.00, "draw": 4.60, "away": 1.52},
            "betway": {"home": 5.10, "draw": 4.30, "away": 1.60},
            "hollywoodbets": {"home": 4.80, "draw": 4.50, "away": 1.55},
        }
        bk, price = _select_best_bookmaker_for_outcome(odds, "home")
        assert bk == "betway"
        assert price == 5.10

    def test_selects_best_for_away(self):
        odds = {
            "gbets": {"home": 5.00, "draw": 4.60, "away": 1.52},
            "betway": {"home": 5.10, "draw": 4.30, "away": 1.60},
        }
        bk, price = _select_best_bookmaker_for_outcome(odds, "away")
        assert bk == "betway"
        assert price == 1.60

    def test_selects_best_for_draw(self):
        odds = {
            "gbets": {"home": 5.00, "draw": 4.60, "away": 1.52},
            "betway": {"home": 5.10, "draw": 4.30, "away": 1.60},
        }
        bk, price = _select_best_bookmaker_for_outcome(odds, "draw")
        assert bk == "gbets"
        assert price == 4.60

    def test_missing_outcome_returns_none(self):
        odds = {
            "gbets": {"home": 5.00, "away": 1.52},   # no draw
            "betway": {"home": 5.10, "away": 1.60},  # no draw
        }
        bk, price = _select_best_bookmaker_for_outcome(odds, "draw")
        assert bk is None
        assert price is None

    def test_single_bookmaker(self):
        odds = {"gbets": {"home": 3.00, "draw": 3.50, "away": 2.10}}
        bk, price = _select_best_bookmaker_for_outcome(odds, "home")
        assert bk == "gbets"
        assert price == 3.00

    def test_empty_odds(self):
        bk, price = _select_best_bookmaker_for_outcome({}, "home")
        assert bk is None
        assert price is None

    def test_does_not_select_globally_best(self):
        """THE critical test: away has highest global odds but we want home."""
        odds = {
            "gbets": {"home": 2.00, "draw": 3.00, "away": 8.00},
            "betway": {"home": 2.20, "draw": 2.80, "away": 7.50},
        }
        bk, price = _select_best_bookmaker_for_outcome(odds, "home")
        # Must pick betway (2.20 for home), NOT gbets (8.00 for away)
        assert bk == "betway"
        assert price == 2.20

    def test_flat_format_returns_none(self):
        """Flat {bk: float} format: function returns (None, None) — caller falls back."""
        flat = {"gbets": 2.00, "betway": 2.20}
        bk, price = _select_best_bookmaker_for_outcome(flat, "home")
        assert bk is None
        assert price is None

    def test_partial_coverage(self):
        """Only some bookmakers offer the requested outcome."""
        odds = {
            "gbets": {"home": 5.00, "away": 1.52},          # no draw
            "betway": {"home": 5.10, "draw": 4.30, "away": 1.60},
            "hwb": {"draw": 4.50},                           # draw only
        }
        bk, price = _select_best_bookmaker_for_outcome(odds, "draw")
        assert bk == "hwb"
        assert price == 4.50

    def test_ties_returns_first_seen(self):
        """Exact tie: whichever bookmaker is iterated first wins (stable)."""
        odds = {
            "gbets": {"home": 3.00},
            "betway": {"home": 3.00},
        }
        bk, price = _select_best_bookmaker_for_outcome(odds, "home")
        assert bk in ("gbets", "betway")
        assert price == 3.00
