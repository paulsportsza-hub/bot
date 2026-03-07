"""Unit tests for tier_gate.py — content gating by subscription tier.

Wave 21: Bronze UX overhaul — list display ungated, gating at card render + View Detail.
"""

from __future__ import annotations

import sqlite3
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

import pytest


def _make_conn():
    """In-memory SQLite connection with daily_tip_views table."""
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS daily_tip_views (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            match_key TEXT NOT NULL,
            viewed_at TIMESTAMP NOT NULL
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_tip_views_user_date
        ON daily_tip_views(user_id, viewed_at)
    """)
    return conn


def _make_mock_helper():
    """Create a mock edge_v2_helper with realistic implementations."""
    helper = MagicMock()

    # check_tip_limit: bronze = 3/day
    def _check_limit(user_id, tier, conn):
        limits = {"bronze": 3, "gold": None, "diamond": None}
        limit = limits.get(tier)
        if limit is None:
            return (True, 999)
        row = conn.execute(
            "SELECT COUNT(*) FROM daily_tip_views WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        count = row[0] if row else 0
        remaining = max(0, limit - count)
        return (count < limit, remaining)

    def _record_view(user_id, match_key, conn):
        conn.execute(
            "INSERT INTO daily_tip_views (user_id, match_key, viewed_at) VALUES (?, ?, ?)",
            (user_id, match_key, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()

    helper.check_tip_limit = _check_limit
    helper.record_tip_view = _record_view

    return helper


def _make_edges(n=5, base_score=50):
    """Create n fake edge dicts with ascending composite scores."""
    tier_map = {True: "diamond", False: "bronze"}
    return [
        {
            "composite_score": base_score + i * 10,
            "tier": "gold" if base_score + i * 10 >= 50 else "bronze",
            "match_key": f"team_a_vs_team_b_match_{i}",
            "created_at": "2026-03-03T10:00:00+02:00",
        }
        for i in range(n)
    ]


# ── gate_edges tests (Wave 21: no filtering) ──────────────────


class TestGateEdges:
    """Test gate_edges() returns ALL edges (Wave 21 — list display ungated)."""

    def test_diamond_sees_all(self):
        """Diamond tier sees all edges with no restrictions."""
        import tier_gate
        mock = _make_mock_helper()
        tier_gate._edge_v2_helper = mock

        conn = _make_conn()
        edges = _make_edges(5, base_score=20)
        result, remaining, upgrade_msg = tier_gate.gate_edges(edges, user_id=100, user_tier="diamond", conn=conn)
        conn.close()

        assert len(result) == 5
        assert remaining == 999
        assert upgrade_msg is None

    def test_gold_sees_all(self):
        """Gold tier sees ALL edges — no composite cap filtering (Wave 21)."""
        import tier_gate
        mock = _make_mock_helper()
        tier_gate._edge_v2_helper = mock

        conn = _make_conn()
        # Scores: 20, 30, 40, 50, 60, 70, 80, 90
        edges = _make_edges(8, base_score=20)
        result, remaining, upgrade_msg = tier_gate.gate_edges(edges, user_id=100, user_tier="gold", conn=conn)
        conn.close()

        assert len(result) == 8  # ALL edges returned
        assert remaining == 999
        assert upgrade_msg is None

    def test_bronze_sees_all(self):
        """Bronze tier sees ALL edges in list — no filtering (Wave 21)."""
        import tier_gate
        mock = _make_mock_helper()
        tier_gate._edge_v2_helper = mock

        conn = _make_conn()
        # Scores: 20, 30, 40, 50, 60
        edges = _make_edges(5, base_score=20)
        result, remaining, upgrade_msg = tier_gate.gate_edges(edges, user_id=100, user_tier="bronze", conn=conn)
        conn.close()

        assert len(result) == 5  # ALL edges returned

    def test_bronze_remaining_views_tracked(self):
        """Bronze remaining views counter works for display."""
        import tier_gate
        mock = _make_mock_helper()
        tier_gate._edge_v2_helper = mock

        conn = _make_conn()
        edges = _make_edges(5, base_score=10)

        # Record 2 views
        now_utc = datetime.now(timezone.utc).isoformat()
        for i in range(2):
            conn.execute(
                "INSERT INTO daily_tip_views (user_id, match_key, viewed_at) VALUES (?, ?, ?)",
                (200, f"match_{i}", now_utc),
            )
        conn.commit()

        result, remaining, upgrade_msg = tier_gate.gate_edges(edges, user_id=200, user_tier="bronze", conn=conn)
        conn.close()

        assert len(result) == 5  # ALL edges returned (Wave 21)
        assert remaining == 1  # 3 - 2 = 1 remaining

    def test_gold_unlimited_views(self):
        """Gold user has no daily limit."""
        import tier_gate
        mock = _make_mock_helper()
        tier_gate._edge_v2_helper = mock

        conn = _make_conn()
        edges = _make_edges(3, base_score=20)

        now_utc = datetime.now(timezone.utc).isoformat()
        for i in range(10):
            conn.execute(
                "INSERT INTO daily_tip_views (user_id, match_key, viewed_at) VALUES (?, ?, ?)",
                (300, f"match_{i}", now_utc),
            )
        conn.commit()

        result, remaining, upgrade_msg = tier_gate.gate_edges(edges, user_id=300, user_tier="gold", conn=conn)
        conn.close()

        assert remaining == 999
        assert upgrade_msg is None


# ── user_can_access_edge tests ────────────────────────────────


class TestUserCanAccessEdge:
    """Test user_can_access_edge() tier permission matrix."""

    def test_diamond_accesses_everything(self):
        from tier_gate import user_can_access_edge
        for edge in ("bronze", "silver", "gold", "diamond"):
            assert user_can_access_edge("diamond", edge) is True

    def test_gold_accesses_up_to_gold(self):
        from tier_gate import user_can_access_edge
        assert user_can_access_edge("gold", "bronze") is True
        assert user_can_access_edge("gold", "silver") is True
        assert user_can_access_edge("gold", "gold") is True
        assert user_can_access_edge("gold", "diamond") is False

    def test_bronze_accesses_bronze_silver(self):
        from tier_gate import user_can_access_edge
        assert user_can_access_edge("bronze", "bronze") is True
        assert user_can_access_edge("bronze", "silver") is True
        assert user_can_access_edge("bronze", "gold") is False
        assert user_can_access_edge("bronze", "diamond") is False


# ── get_edge_access_level tests ───────────────────────────────


class TestGetEdgeAccessLevel:
    """Test get_edge_access_level() returns correct access level strings."""

    def test_diamond_full_access(self):
        from tier_gate import get_edge_access_level
        for edge in ("bronze", "silver", "gold", "diamond"):
            assert get_edge_access_level("diamond", edge) == "full"

    def test_gold_access_levels(self):
        from tier_gate import get_edge_access_level
        assert get_edge_access_level("gold", "bronze") == "full"
        assert get_edge_access_level("gold", "silver") == "full"
        assert get_edge_access_level("gold", "gold") == "full"
        assert get_edge_access_level("gold", "diamond") == "locked"

    def test_bronze_access_levels(self):
        from tier_gate import get_edge_access_level
        assert get_edge_access_level("bronze", "bronze") == "full"
        assert get_edge_access_level("bronze", "silver") == "partial"
        assert get_edge_access_level("bronze", "gold") == "blurred"
        assert get_edge_access_level("bronze", "diamond") == "locked"

    def test_case_insensitive(self):
        from tier_gate import get_edge_access_level
        assert get_edge_access_level("BRONZE", "GOLD") == "blurred"
        assert get_edge_access_level("Diamond", "bronze") == "full"


# ── check_tip_limit tests ────────────────────────────────────


class TestCheckTipLimit:
    """Test check_tip_limit() wrapper for View Detail gating."""

    def test_bronze_limit(self):
        import tier_gate
        mock = _make_mock_helper()
        tier_gate._edge_v2_helper = mock

        conn = _make_conn()
        can_view, remaining = tier_gate.check_tip_limit(100, "bronze", conn)
        conn.close()

        assert can_view is True
        assert remaining == 3

    def test_gold_unlimited(self):
        import tier_gate
        mock = _make_mock_helper()
        tier_gate._edge_v2_helper = mock

        conn = _make_conn()
        can_view, remaining = tier_gate.check_tip_limit(100, "gold", conn)
        conn.close()

        assert can_view is True
        assert remaining == 999


# ── record_view tests ────────────────────────────────────────


class TestRecordView:
    """Test record_view() inserts into daily_tip_views."""

    def test_records_view(self):
        """record_view inserts a row in daily_tip_views."""
        import tier_gate
        mock = _make_mock_helper()
        tier_gate._edge_v2_helper = mock

        conn = _make_conn()
        tier_gate.record_view(400, "chiefs_vs_pirates_2026-03-03", conn)

        row = conn.execute("SELECT * FROM daily_tip_views WHERE user_id = 400").fetchone()
        conn.close()

        assert row is not None
        assert row[2] == "chiefs_vs_pirates_2026-03-03"


# ── gate_narrative tests ─────────────────────────────────────


class TestGateNarrative:
    """Test gate_narrative() returns tier-appropriate narrative."""

    def test_returns_empty_when_no_module(self):
        """Returns empty string when narrative_generator not available."""
        import tier_gate
        tier_gate._narrative_gen = False  # Mark as unavailable

        result = tier_gate.gate_narrative({"composite_score": 80}, "gold")
        assert result == ""

    def test_calls_generator(self):
        """Calls generate_narrative_for_tier with correct args."""
        import tier_gate
        mock_gen = MagicMock()
        mock_gen.generate_narrative_for_tier.return_value = "Test narrative"
        tier_gate._narrative_gen = mock_gen

        result = tier_gate.gate_narrative({"composite_score": 80}, "gold")
        assert result == "Test narrative"
        mock_gen.generate_narrative_for_tier.assert_called_once_with({"composite_score": 80}, "gold")


# ── get_upgrade_message tests ────────────────────────────────


class TestUpgradeMessage:
    """Test get_upgrade_message() returns correct text per tier."""

    def test_bronze_tip_limit(self):
        from tier_gate import get_upgrade_message

        msg = get_upgrade_message("bronze", context="tip")
        assert "3 free detail views" in msg
        assert "/subscribe" in msg

    def test_bronze_gold_edge(self):
        from tier_gate import get_upgrade_message

        msg = get_upgrade_message("bronze", context="gold_edge")
        assert "Gold Edge" in msg
        assert "R99" in msg

    def test_bronze_diamond_edge(self):
        from tier_gate import get_upgrade_message

        msg = get_upgrade_message("bronze", context="diamond_edge")
        assert "Diamond Edge" in msg
        assert "R199" in msg

    def test_gold_upgrade(self):
        from tier_gate import get_upgrade_message

        msg = get_upgrade_message("gold")
        assert "Diamond" in msg

    def test_diamond_empty(self):
        from tier_gate import get_upgrade_message

        msg = get_upgrade_message("diamond")
        assert msg == ""
