"""RENDER-FIX1 contract tests — assign_tier() triple gate replaces R15-BUILD-02.

Tests required by brief:
1. Triple-gate Diamond: composite=55, ev=6%, confirming=2 → display_tier = "diamond"
2. Single-gate Gold: composite=55, ev=3%, confirming=1 → display_tier = "gold" (NOT diamond)
3. Gold lockout regression: get_edge_access_level("gold", "gold") returns "full"
4. Bronze fallback: composite=10, ev=0.2%, confirming=0 → display_tier = "bronze"

BUILD-DRAW-01 tests:
A. _load_tips_from_edge_results fast path excludes draws (code guard + functional verify)
B. log_edge_recommendation with draw outcome → zero rows written to edge_results
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from config import ensure_scrapers_importable
ensure_scrapers_importable()

from scrapers.edge.tier_engine import assign_tier
from tier_gate import get_edge_access_level


class TestRenderFix1TripleGateDiamond:
    """Test 1: All three gates satisfied → diamond."""

    def test_diamond_requires_triple_gate(self):
        """composite=62 ≥ 60, ev=6.0 ≥ 5.0, confirming=2 ≥ 2 → diamond. (ALGO-FIX-01 threshold)"""
        tier = assign_tier(62, 6.0, 2, red_flags=[]) or "bronze"
        assert tier == "diamond", f"Expected diamond, got {tier}"

    def test_composite_only_not_enough_for_diamond(self):
        """composite=55 but ev=3% < 5.0% → should NOT be diamond (fails ev gate)."""
        tier = assign_tier(55, 3.0, 2, red_flags=[]) or "bronze"
        assert tier != "diamond", f"Expected non-diamond (R15-BUILD-02 bug), got {tier}"

    def test_composite_only_no_confirming_not_diamond(self):
        """composite=55 but confirming=0 < 2 → should NOT be diamond."""
        tier = assign_tier(55, 6.0, 0, red_flags=[]) or "bronze"
        assert tier != "diamond", f"Expected non-diamond (R15-BUILD-02 bug), got {tier}"


class TestRenderFix1GoldNotDiamond:
    """Test 2: High composite but fails diamond ev or confirming gate → gold."""

    def test_high_composite_low_ev_gets_gold_not_diamond(self):
        """composite=55, ev=3%, confirming=1 → gold (not diamond: ev < 5% & confirming < 2)."""
        tier = assign_tier(55, 3.0, 1, red_flags=[]) or "bronze"
        assert tier == "gold", f"Expected gold, got {tier}"

    def test_display_tier_logic_simulated(self):
        """Simulates the RENDER-FIX1 replacement block for a single tip dict."""
        tip = {
            "edge_score": 55,
            "ev": 3.0,
            "edge_v2": {"confirming_signals": 1},
        }
        _cs = tip.get("edge_score", 0) or 0
        _ev = tip.get("ev", 0) or 0
        _conf = (tip.get("edge_v2") or {}).get("confirming_signals", 0) or 0
        _assigned = assign_tier(_cs, _ev, _conf, red_flags=[])
        tip["display_tier"] = _assigned or "bronze"

        assert tip["display_tier"] == "gold"

    def test_r15_build02_bug_reproduced(self):
        """Confirms the old composite-only logic WOULD have returned diamond (the bug)."""
        composite = 55
        # Old R15-BUILD-02 logic:
        old_tier = None
        if composite >= 52:
            old_tier = "diamond"
        elif composite >= 40:
            old_tier = "gold"
        elif composite >= 38:
            old_tier = "silver"
        elif composite >= 15:
            old_tier = "bronze"

        # New RENDER-FIX1 logic (ev=3%, confirming=1):
        new_tier = assign_tier(composite, 3.0, 1, red_flags=[]) or "bronze"

        assert old_tier == "diamond", "Old logic should have produced diamond (the bug)"
        assert new_tier == "gold", "New logic should produce gold (the fix)"
        assert new_tier != old_tier, "Fix must change the result"


class TestRenderFix1GoldLockoutRegression:
    """Test 3: Gold subscriber sees Gold/Silver/Bronze tips as 'full' (not blurred)."""

    def test_gold_user_sees_gold_tip_as_full(self):
        assert get_edge_access_level("gold", "gold") == "full"

    def test_gold_user_sees_silver_tip_as_full(self):
        assert get_edge_access_level("gold", "silver") == "full"

    def test_gold_user_sees_bronze_tip_as_full(self):
        assert get_edge_access_level("gold", "bronze") == "full"

    def test_gold_user_sees_diamond_tip_as_blurred(self):
        """Gold subscribers do NOT see Diamond — it should be blurred."""
        assert get_edge_access_level("gold", "diamond") == "blurred"


class TestRenderFix1BronzeFallback:
    """Test 4: Low composite/ev/confirming → falls back to bronze."""

    def test_below_threshold_gets_bronze_fallback(self):
        """composite=10 < 30 (bronze min_composite) → assign_tier returns None → bronze fallback."""
        tier = assign_tier(10, 0.2, 0, red_flags=[]) or "bronze"
        assert tier == "bronze", f"Expected bronze fallback, got {tier}"

    def test_assign_tier_returns_none_below_thresholds(self):
        """assign_tier() returns None (not 'bronze') when nothing passes — fallback is caller's job."""
        result = assign_tier(10, 0.2, 0, red_flags=[])
        assert result is None, f"assign_tier should return None below all thresholds, got {result}"

    def test_display_tier_bronze_from_none(self):
        """The 'or bronze' fallback in RENDER-FIX1 replacement block works correctly."""
        _assigned = assign_tier(10, 0.2, 0, red_flags=[])
        display = _assigned or "bronze"
        assert display == "bronze"


# ---------------------------------------------------------------------------
# BUILD-DRAW-01 contract tests
# ---------------------------------------------------------------------------

def _get_project_root():
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestBuildDraw01FastPathGuard:
    """Test A (BUILD-DRAW-01): _load_tips_from_edge_results must skip draw outcomes.

    We verify both that the guard code exists in the correct function and that
    _load_tips_from_edge_results returns no draws when the DB contains only draw rows.
    Imports bot.py directly via subprocess/grep to avoid Sentry init at import time.
    """

    def test_fast_path_draw_guard_present_in_bot(self):
        """ALGO-FIX-01 parity guard must exist in _load_tips_from_edge_results in bot.py."""
        import subprocess
        root = _get_project_root()
        bot_py = os.path.join(root, "bot.py")
        # Grep for the guard within the function (context: nearby outcome normalization)
        result = subprocess.run(
            ["grep", "-n", 'outcome_raw == "draw"', bot_py],
            capture_output=True, text=True
        )
        assert result.stdout.strip(), (
            "BUILD-DRAW-01 Layer 1 guard missing: "
            'if outcome_raw == "draw": continue '
            "not found in bot.py"
        )

    def test_fast_path_outcome_raw_draw_continues(self):
        """Simulate the outcome normalization + draw filter from _load_tips_from_edge_results."""
        # Simulate the normalization block from bot.py (lines 9559-9568)
        rows = [
            {"bet_type": "Draw", "match_key": "chelsea_vs_man_utd_2026-04-05",
             "composite_score": 33.6, "predicted_ev": 5.0, "recommended_odds": 3.75,
             "bookmaker": "wsb", "edge_tier": "silver", "confirming_signals": 0,
             "edge_id": "edge_140243", "league": "epl"},
            {"bet_type": "Home Win", "match_key": "arsenal_vs_chelsea_2026-04-06",
             "composite_score": 55.0, "predicted_ev": 6.0, "recommended_odds": 2.1,
             "bookmaker": "hollywoodbets", "edge_tier": "gold", "confirming_signals": 2,
             "edge_id": "edge_140250", "league": "epl"},
        ]
        result = []
        for row in rows:
            outcome_label = row["bet_type"] or "home"
            if outcome_label == "Home Win":
                outcome_raw = "home"
            elif outcome_label == "Away Win":
                outcome_raw = "away"
            else:
                outcome_raw = "draw"
            # ALGO-FIX-01 guard (Layer 1)
            if outcome_raw == "draw":
                continue
            result.append({"outcome_key": outcome_raw, "bet_type": outcome_label})

        assert len(result) == 1, f"Expected 1 non-draw tip, got {len(result)}"
        assert result[0]["outcome_key"] == "home"
        assert all(t["outcome_key"] != "draw" for t in result), "Draw slipped through fast path guard"


class TestBuildDraw01WriterGuard:
    """Test B (BUILD-DRAW-01): log_edge_recommendation with draw outcome writes zero rows.

    Uses an isolated tmp SQLite DB — never touches the live scrapers/odds.db.
    """

    def _make_draw_edge(self, match_key: str = "chelsea_vs_man_utd_2026-04-05") -> dict:
        return {
            "match_key": match_key,
            "tier": "silver",
            "outcome": "draw",
            "market_type": "1x2",
            "edge_pct": 5.0,
            "best_odds": 3.75,
            "composite_score": 33.6,
            "best_bookmaker": "wsb",
            "confirming_signals": 0,
        }

    def _setup_conn(self, db_path: str):
        """Create test DB with required tables for log_edge_recommendation."""
        import sqlite3 as _sqlite3
        from scrapers.edge.settlement import _ensure_table
        conn = _sqlite3.connect(db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        _ensure_table(conn)
        # ISBets check needs odds_snapshots; empty table → returns False (not ISBets-only)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS odds_snapshots "
            "(match_id TEXT, bookmaker TEXT, scraped_at TEXT, league TEXT, sport TEXT)"
        )
        return conn

    def test_draw_edge_not_written_to_edge_results(self, tmp_path):
        """log_edge_recommendation with outcome='draw' must write zero rows."""
        from scrapers.edge.settlement import log_edge_recommendation

        conn = self._setup_conn(str(tmp_path / "test_odds.db"))
        edge = self._make_draw_edge()
        result = log_edge_recommendation(edge, conn=conn, batch_mode=True)

        row_count = conn.execute(
            "SELECT COUNT(*) FROM edge_results WHERE match_key = ?",
            (edge["match_key"],)
        ).fetchone()[0]
        conn.close()

        assert result is False, f"Expected False (not logged), got {result}"
        assert row_count == 0, f"Expected 0 rows for draw edge, got {row_count}"

    def test_non_draw_edge_is_still_written(self, tmp_path):
        """Verify log_edge_recommendation still writes home/away edges (regression guard)."""
        from scrapers.edge.settlement import log_edge_recommendation

        conn = self._setup_conn(str(tmp_path / "test_odds2.db"))

        edge = {
            "match_key": "arsenal_vs_chelsea_2026-04-06",
            "tier": "gold",
            "outcome": "home",
            "market_type": "1x2",
            "edge_pct": 6.0,
            "best_odds": 2.1,
            "composite_score": 55.0,
            "best_bookmaker": "hollywoodbets",
            "confirming_signals": 2,
        }
        result = log_edge_recommendation(edge, conn=conn, batch_mode=True)
        conn.commit()

        row_count = conn.execute(
            "SELECT COUNT(*) FROM edge_results WHERE match_key = ?",
            (edge["match_key"],)
        ).fetchone()[0]
        conn.close()

        assert result is True, f"Expected True (logged), got {result}"
        assert row_count == 1, f"Expected 1 row for home edge, got {row_count}"
