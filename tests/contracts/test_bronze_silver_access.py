"""FIX-BRONZE-SILVER-ACCESS-01 — regression guard.

Bronze users can view Silver edge detail cards with full access (within the
3/day daily cap).  The cap is global — it applies across both Silver and Bronze
edge views combined.

AC-1 (test_bronze_can_view_silver):
    get_edge_access_level("bronze", "silver") == "full"

AC-2 (test_bronze_daily_cap_blocks_silver_after_3):
    After 3 distinct fixture views, check_tip_limit returns (False, 0).
    The same cap applies regardless of whether the viewed edge was Silver or Bronze.

AC-3 (test_bronze_gold_still_locked):
    get_edge_access_level("bronze", "gold") is NOT "full" — Gold stays locked for Bronze.

AC-4 (test_bronze_diamond_still_locked):
    get_edge_access_level("bronze", "diamond") == "locked" — Diamond stays locked.
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from config import ensure_scrapers_importable
ensure_scrapers_importable()

from tier_gate import get_edge_access_level


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_tip_views_db() -> str:
    """Create a temp odds.db with daily_tip_views table."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE daily_tip_views (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id   INTEGER NOT NULL,
            match_key TEXT    NOT NULL,
            viewed_at TEXT    NOT NULL
        )
    """)
    conn.execute("CREATE INDEX idx_tip_views ON daily_tip_views(user_id, viewed_at)")
    conn.commit()
    conn.close()
    return path


def _record_views(db_path: str, user_id: int, match_keys: list[str]) -> None:
    """Insert view rows (today) for the given user + match keys."""
    from datetime import datetime, timezone
    conn = sqlite3.connect(db_path)
    now_utc = datetime.now(timezone.utc).isoformat()
    for mk in match_keys:
        conn.execute(
            "INSERT INTO daily_tip_views (user_id, match_key, viewed_at) VALUES (?,?,?)",
            (user_id, mk, now_utc),
        )
    conn.commit()
    conn.close()


# ── tests ─────────────────────────────────────────────────────────────────────


class TestBronzeSilverAccessFix:
    """FIX-BRONZE-SILVER-ACCESS-01: Bronze gets full access to Silver edges."""

    def test_bronze_can_view_silver(self):
        """AC-1: get_edge_access_level('bronze', 'silver') must be 'full'."""
        level = get_edge_access_level("bronze", "silver")
        assert level == "full", (
            f"Expected 'full' for bronze->silver, got {level!r}. "
            "FIX-BRONZE-SILVER-ACCESS-01 regression."
        )

    def test_bronze_can_view_bronze(self):
        """Existing: bronze->bronze remains 'full'."""
        assert get_edge_access_level("bronze", "bronze") == "full"

    def test_bronze_gold_still_locked(self):
        """AC-3: Bronze->Gold must NOT be 'full' — Gold stays locked for Bronze."""
        level = get_edge_access_level("bronze", "gold")
        assert level != "full", (
            f"Bronze->Gold should not be 'full', got {level!r}."
        )
        assert level == "blurred"

    def test_bronze_diamond_still_locked(self):
        """AC-4: Bronze->Diamond must remain 'locked'."""
        level = get_edge_access_level("bronze", "diamond")
        assert level == "locked", (
            f"Bronze->Diamond should be 'locked', got {level!r}."
        )


class TestBronzeDailyCapIncludesSilver:
    """AC-2: The 3/day cap applies to Silver views for Bronze users."""

    def test_bronze_daily_cap_blocks_silver_after_3(self):
        """Bronze user who has used 3 views cannot open any more edges (incl. Silver)."""
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".."))
        from scrapers.edge.edge_v2_helper import check_tip_limit, record_tip_view

        db_path = _make_tip_views_db()
        try:
            user_id = 999001
            conn = sqlite3.connect(db_path)
            try:
                # Record 3 distinct fixtures (mix of silver-tier match keys)
                _record_views(db_path, user_id, [
                    "team_a_vs_team_b_2026-05-04",
                    "team_c_vs_team_d_2026-05-04",
                    "team_e_vs_team_f_2026-05-04",
                ])

                can_view, remaining = check_tip_limit(user_id, "bronze", conn)
            finally:
                conn.close()

            assert not can_view, "Bronze user should be blocked after 3 views"
            assert remaining == 0, f"Expected 0 remaining, got {remaining}"
        finally:
            os.unlink(db_path)

    def test_bronze_daily_cap_allows_before_3(self):
        """Bronze user who has used 2 views can still open one more edge."""
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".."))
        from scrapers.edge.edge_v2_helper import check_tip_limit

        db_path = _make_tip_views_db()
        try:
            user_id = 999002
            _record_views(db_path, user_id, [
                "team_a_vs_team_b_2026-05-04",
                "team_c_vs_team_d_2026-05-04",
            ])
            conn = sqlite3.connect(db_path)
            try:
                can_view, remaining = check_tip_limit(user_id, "bronze", conn)
            finally:
                conn.close()

            assert can_view, "Bronze user with 2 views used should still be allowed"
            assert remaining == 1, f"Expected 1 remaining, got {remaining}"
        finally:
            os.unlink(db_path)

    def test_bronze_silver_view_counts_against_cap(self):
        """A Silver edge view counts against the Bronze 3/day cap (same counter)."""
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".."))
        from scrapers.edge.edge_v2_helper import check_tip_limit, record_tip_view

        db_path = _make_tip_views_db()
        try:
            user_id = 999003
            conn = sqlite3.connect(db_path)
            try:
                # Record a Silver edge view
                record_tip_view(user_id, "chelsea_vs_arsenal_2026-05-04", conn)
                record_tip_view(user_id, "man_city_vs_liverpool_2026-05-04", conn)
                record_tip_view(user_id, "tottenham_vs_man_utd_2026-05-04", conn)

                # Now Bronze user should be at cap — Silver view counted the same
                can_view, remaining = check_tip_limit(user_id, "bronze", conn)
            finally:
                conn.close()

            assert not can_view, "Bronze user should be blocked after 3 views (incl. Silver)"
            assert remaining == 0
        finally:
            os.unlink(db_path)

    def test_gold_user_unlimited(self):
        """Gold users are never blocked by check_tip_limit."""
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".."))
        from scrapers.edge.edge_v2_helper import check_tip_limit

        db_path = _make_tip_views_db()
        try:
            user_id = 999004
            _record_views(db_path, user_id, [
                f"match_{i}_2026-05-04" for i in range(10)
            ])
            conn = sqlite3.connect(db_path)
            try:
                can_view, remaining = check_tip_limit(user_id, "gold", conn)
            finally:
                conn.close()

            assert can_view, "Gold user should never be blocked"
            assert remaining == 999
        finally:
            os.unlink(db_path)


class TestBronzeSilverIndexNotLocked:
    """AC-5 (FIX-BRONZE-SILVER-ACCESS-01): tier index must NOT show Silver as locked for Bronze."""

    def test_bronze_silver_index_not_locked(self):
        """edge_picks_index_tier_locked must return False for bronze→silver (full access)."""
        from card_data import edge_picks_index_tier_locked

        result = edge_picks_index_tier_locked("bronze", "silver")
        assert result is False, (
            f"bronze→silver should NOT be locked in the tier index (full access). Got {result!r}. "
            "FIX-BRONZE-SILVER-ACCESS-01 regression."
        )

    def test_bronze_gold_index_still_locked(self):
        """Bronze→Gold (blurred) must remain locked in the tier index."""
        from card_data import edge_picks_index_tier_locked

        assert edge_picks_index_tier_locked("bronze", "gold") is True

    def test_bronze_diamond_index_still_locked(self):
        """Bronze→Diamond (locked) must remain locked in the tier index."""
        from card_data import edge_picks_index_tier_locked

        assert edge_picks_index_tier_locked("bronze", "diamond") is True

    def test_gold_diamond_index_still_locked(self):
        """Gold→Diamond (locked) must remain locked in the tier index."""
        from card_data import edge_picks_index_tier_locked

        assert edge_picks_index_tier_locked("gold", "diamond") is True

    def test_diamond_all_not_locked(self):
        """Diamond user sees all tiers as accessible."""
        from card_data import edge_picks_index_tier_locked

        for tier in ("diamond", "gold", "silver", "bronze"):
            assert edge_picks_index_tier_locked("diamond", tier) is False, (
                f"diamond→{tier} should not be locked"
            )
