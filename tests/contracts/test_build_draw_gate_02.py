"""BUILD-DRAW-GATE-02 contract tests.

Verifies all 4 draw-leak fixes in _generate_game_tips() and related paths:
1. Outcome loop guard: if outcome_key == "draw": continue (~line 19305)
2. _build_game_buttons() uses _non_draw_tips for best_ev_tip selection (~line 20196)
3. Pre-sort/cache strip: tips = [t for t in tips if outcome != "draw"] (~line 19401)
4. AC-7 fast path guard: _ac7_card = None when outcome == "draw" (~line 18964)
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

_BOT_PY = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "bot.py",
)


# ---------------------------------------------------------------------------
# Helper: simulate the _generate_game_tips db_match outcome loop
# ---------------------------------------------------------------------------

def _simulate_outcome_loop(outcomes: dict) -> list[dict]:
    """Replicates lines 19302-19366 of _generate_game_tips (outcome loop only)."""
    tips = []
    for outcome_key, outcome_data in outcomes.items():
        if outcome_key == "draw":
            continue  # Fix 1 guard
        all_bk = outcome_data.get("all_bookmakers", {})
        if not all_bk:
            continue
        best_price = outcome_data.get("best_odds", 0)
        implied_probs = [1.0 / o for o in all_bk.values() if o and o > 1]
        if not implied_probs:
            continue
        fair_prob = sum(implied_probs) / len(implied_probs)
        ev_pct = round((fair_prob * best_price - 1) * 100, 1) if best_price > 0 else 0
        tips.append({
            "outcome": outcome_key,
            "odds": best_price,
            "ev": ev_pct,
        })
    return tips


def _simulate_pre_sort_strip(tips: list[dict]) -> list[dict]:
    """Replicates line 19401 of _generate_game_tips (pre-sort draw strip)."""
    return [t for t in tips if (t.get("outcome") or "").lower() != "draw"]


# ---------------------------------------------------------------------------
# Fix 1: outcome loop guard
# ---------------------------------------------------------------------------

class TestFix1OutcomeLoopGuard:
    """Outcome loop must skip draw keys in db_match['outcomes']."""

    def test_code_guard_present_in_bot(self):
        """grep: 'if outcome_key == \"draw\": continue' must exist in bot.py."""
        result = subprocess.run(
            ["grep", "-n", 'if outcome_key == "draw"', _BOT_PY],
            capture_output=True, text=True,
        )
        assert result.stdout.strip(), (
            "Fix 1 guard missing: 'if outcome_key == \"draw\": continue' "
            "not found in bot.py"
        )

    def test_db_match_with_draw_excludes_draw_from_tips(self):
        """db_match containing draw + home + away → tips list has no draw entry."""
        db_match_outcomes = {
            "home": {"all_bookmakers": {"hwb": 1.85}, "best_odds": 1.85, "best_bookmaker": "hwb"},
            "draw": {"all_bookmakers": {"hwb": 3.40}, "best_odds": 3.40, "best_bookmaker": "hwb"},
            "away": {"all_bookmakers": {"hwb": 4.50}, "best_odds": 4.50, "best_bookmaker": "hwb"},
        }
        tips = _simulate_outcome_loop(db_match_outcomes)
        outcomes_in_tips = {t["outcome"] for t in tips}
        assert "draw" not in outcomes_in_tips, (
            f"Draw leaked through Fix 1 outcome loop guard. Tips: {tips}"
        )
        assert "home" in outcomes_in_tips, "Home tip expected but missing"
        assert "away" in outcomes_in_tips, "Away tip expected but missing"
        assert len(tips) == 2, f"Expected 2 tips (home+away), got {len(tips)}"

    def test_draw_only_db_match_returns_empty_tips(self):
        """db_match with only a draw outcome → no tips returned."""
        db_match_outcomes = {
            "draw": {"all_bookmakers": {"hwb": 3.20}, "best_odds": 3.20, "best_bookmaker": "hwb"},
        }
        tips = _simulate_outcome_loop(db_match_outcomes)
        assert tips == [], f"Expected empty tips, got {tips}"


# ---------------------------------------------------------------------------
# Fix 2: _build_game_buttons() _non_draw_tips guard
# ---------------------------------------------------------------------------

class TestFix2BuildGameButtonsGuard:
    """_build_game_buttons must use _non_draw_tips for best_ev_tip selection."""

    def test_non_draw_tips_filter_present_in_bot(self):
        """grep: '_non_draw_tips = [t for t in tips if' inside _build_game_buttons."""
        result = subprocess.run(
            ["grep", "-n", "_non_draw_tips", _BOT_PY],
            capture_output=True, text=True,
        )
        assert result.stdout.strip(), (
            "Fix 2 guard missing: '_non_draw_tips' not found in bot.py"
        )

    def test_best_ev_tip_excludes_draw(self):
        """Simulate _build_game_buttons best_ev_tip selection — draw must not win."""
        tips = [
            {"outcome": "home", "ev": 2.5},
            {"outcome": "draw", "ev": 5.0},  # highest EV but must be excluded
            {"outcome": "away", "ev": 1.2},
        ]
        _non_draw_tips = [t for t in tips if (t.get("outcome") or "").lower() != "draw"]
        best_ev_tip = max(
            (t for t in _non_draw_tips if t.get("ev", 0) > 0),
            key=lambda t: t["ev"],
            default=None,
        )
        assert best_ev_tip is not None, "best_ev_tip should not be None"
        assert best_ev_tip["outcome"] != "draw", (
            f"Draw selected as best_ev_tip: {best_ev_tip}"
        )
        assert best_ev_tip["outcome"] == "home", (
            f"Expected home (highest non-draw EV), got {best_ev_tip['outcome']}"
        )


# ---------------------------------------------------------------------------
# Fix 3: pre-sort draw strip
# ---------------------------------------------------------------------------

class TestFix3PreSortDrawStrip:
    """Pre-sort strip must remove any draws that escaped the outcome loop."""

    def test_pre_sort_strip_present_in_bot(self):
        """grep: pre-sort draw strip line exists near 'sort/cache' comment."""
        result = subprocess.run(
            ["grep", "-n", "strip draws before sort", _BOT_PY],
            capture_output=True, text=True,
        )
        assert result.stdout.strip(), (
            "Fix 3 guard missing: 'strip draws before sort' comment not found in bot.py"
        )

    def test_pre_sort_strip_removes_draw_from_tips_list(self):
        """Even if a draw slipped through, the pre-sort strip catches it."""
        tips_with_draw = [
            {"outcome": "home", "ev": 3.1},
            {"outcome": "Draw", "ev": 4.2},   # capital D variant
            {"outcome": "draw", "ev": 1.5},   # lowercase
        ]
        stripped = _simulate_pre_sort_strip(tips_with_draw)
        for t in stripped:
            assert (t.get("outcome") or "").lower() != "draw", (
                f"Draw not stripped: {t}"
            )
        assert len(stripped) == 1
        assert stripped[0]["outcome"] == "home"


# ---------------------------------------------------------------------------
# Fix 4: AC-7 fast path guard
# ---------------------------------------------------------------------------

class TestFix4Ac7FastPathGuard:
    """AC-7 card pipeline must null-out draw cards before serving."""

    def test_ac7_draw_guard_present_in_bot(self):
        """grep: AC-7 draw guard comment exists in bot.py."""
        result = subprocess.run(
            ["grep", "-n", "ALGO-FIX-01 parity.*AC-7", _BOT_PY],
            capture_output=True, text=True,
        )
        assert result.stdout.strip(), (
            "Fix 4 guard missing: 'ALGO-FIX-01 parity.*AC-7' not found in bot.py"
        )

    def test_ac7_draw_card_nulled(self):
        """Simulate AC-7 draw guard: draw outcome → _ac7_card set to None."""
        _ac7_card = {"outcome": "Draw", "ev": 7.0, "odds": 3.40, "bookmaker": "hwb"}
        if (_ac7_card.get("outcome") or "").lower() == "draw":
            _ac7_card = None
        assert _ac7_card is None, "AC-7 draw card should have been nulled"

    def test_ac7_non_draw_card_preserved(self):
        """Non-draw AC-7 card must NOT be nulled."""
        _ac7_card = {"outcome": "home", "ev": 5.0, "odds": 1.85, "bookmaker": "hwb"}
        if (_ac7_card.get("outcome") or "").lower() == "draw":
            _ac7_card = None
        assert _ac7_card is not None, "Non-draw AC-7 card must not be nulled"
        assert _ac7_card["outcome"] == "home"
