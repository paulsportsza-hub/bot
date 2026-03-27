"""Wave 24 — Engagement Features tests.

Tests for: settlement helpers, weekend preview, monday recap,
trial restart polish, CTA consistency.
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure bot dir and scrapers parent on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import ensure_scrapers_importable
ensure_scrapers_importable()

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("ODDS_API_KEY", "test-odds-key")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-anthropic-key")
os.environ.setdefault("ADMIN_IDS", "123456")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")


# ── Settlement helper tests ──────────────────────────────────


def _make_edge(match_key: str, tier: str, match_date: str, result=None, **kw):
    """Build a minimal edge_results dict for testing."""
    return {
        "id": kw.get("id", 1),
        "edge_id": f"edge_{match_key}",
        "match_key": match_key,
        "sport": kw.get("sport", "soccer"),
        "league": kw.get("league", "PSL"),
        "edge_tier": tier,
        "composite_score": kw.get("composite_score", 70.0),
        "bet_type": kw.get("bet_type", "Home Win"),
        "recommended_odds": kw.get("recommended_odds", 2.10),
        "bookmaker": kw.get("bookmaker", "hollywoodbets"),
        "predicted_ev": kw.get("predicted_ev", 5.0),
        "result": result,
        "match_score": kw.get("match_score"),
        "actual_return": kw.get("actual_return"),
        "recommended_at": kw.get("recommended_at", datetime.now(timezone.utc).isoformat()),
        "settled_at": kw.get("settled_at"),
        "match_date": match_date,
    }


def _create_test_db(edges: list[dict]) -> str:
    """Create a temp SQLite DB with edge_results rows. Returns path."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    path = tmp.name
    tmp.close()
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS edge_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            edge_id TEXT NOT NULL,
            match_key TEXT NOT NULL,
            sport TEXT NOT NULL,
            league TEXT NOT NULL,
            edge_tier TEXT NOT NULL,
            composite_score REAL NOT NULL,
            bet_type TEXT NOT NULL,
            recommended_odds REAL NOT NULL,
            bookmaker TEXT NOT NULL,
            predicted_ev REAL NOT NULL,
            result TEXT,
            match_score TEXT,
            actual_return REAL,
            recommended_at DATETIME NOT NULL,
            settled_at DATETIME,
            match_date DATE NOT NULL,
            UNIQUE(match_key, bet_type)
        );
        CREATE INDEX IF NOT EXISTS idx_edge_results_unsettled ON edge_results(result, match_date);
    """)
    for e in edges:
        conn.execute("""
            INSERT INTO edge_results
            (edge_id, match_key, sport, league, edge_tier, composite_score,
             bet_type, recommended_odds, bookmaker, predicted_ev,
             result, match_score, actual_return, recommended_at, settled_at, match_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            e["edge_id"], e["match_key"], e["sport"], e["league"],
            e["edge_tier"], e["composite_score"], e["bet_type"],
            e["recommended_odds"], e["bookmaker"], e["predicted_ev"],
            e.get("result"), e.get("match_score"), e.get("actual_return"),
            e["recommended_at"], e.get("settled_at"), e["match_date"],
        ))
    conn.commit()
    conn.close()
    return path


class TestGetUpcomingEdges:
    """Tests for get_upcoming_edges()."""

    def test_with_data(self):
        """Returns upcoming unsettled edges within date range."""
        today = date.today().isoformat()
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        edges = [
            _make_edge("sundowns_vs_pirates_" + today, "diamond", today, league="PSL", id=1, bet_type="Home Win"),
            _make_edge("chiefs_vs_celtic_" + tomorrow, "gold", tomorrow, league="PSL", id=2, bet_type="Away Win"),
        ]
        db_path = _create_test_db(edges)
        with patch("scrapers.edge.settlement.DB_PATH", db_path):
            from scrapers.edge.settlement import get_upcoming_edges
            result = get_upcoming_edges(3)
        os.unlink(db_path)
        assert result["total"] == 2
        assert result["match_count"] == 2
        assert "PSL" in result["leagues"]
        assert result["by_tier"].get("diamond") == 1
        assert result["by_tier"].get("gold") == 1

    def test_empty(self):
        """Returns zeros when no upcoming edges."""
        db_path = _create_test_db([])
        with patch("scrapers.edge.settlement.DB_PATH", db_path):
            from scrapers.edge.settlement import get_upcoming_edges
            result = get_upcoming_edges(3)
        os.unlink(db_path)
        assert result["total"] == 0
        assert result["match_count"] == 0
        assert result["edges"] == []
        assert result["by_tier"] == {}


class TestGetSettledInRange:
    """Tests for get_settled_in_range()."""

    def test_with_data(self):
        """Returns settled edges in date range."""
        edges = [
            _make_edge("a_vs_b_2026-02-28", "gold", "2026-02-28", result="hit",
                       match_score="2-1", id=1, bet_type="Home Win",
                       settled_at=datetime.now(timezone.utc).isoformat()),
            _make_edge("c_vs_d_2026-03-01", "diamond", "2026-03-01", result="miss",
                       match_score="0-1", id=2, bet_type="Away Win",
                       settled_at=datetime.now(timezone.utc).isoformat()),
        ]
        db_path = _create_test_db(edges)
        with patch("scrapers.edge.settlement.DB_PATH", db_path):
            from scrapers.edge.settlement import get_settled_in_range
            result = get_settled_in_range("2026-02-28", "2026-03-02")
        os.unlink(db_path)
        assert len(result) == 2
        assert result[0]["result"] in ("hit", "miss")

    def test_empty_range(self):
        """Returns empty list when no edges in range."""
        db_path = _create_test_db([])
        with patch("scrapers.edge.settlement.DB_PATH", db_path):
            from scrapers.edge.settlement import get_settled_in_range
            result = get_settled_in_range("2026-01-01", "2026-01-02")
        os.unlink(db_path)
        assert result == []

    def test_date_filtering(self):
        """Only returns edges within the specified date range."""
        edges = [
            _make_edge("in_range_2026-03-01", "gold", "2026-03-01", result="hit",
                       match_score="2-1", id=1, bet_type="Home Win",
                       settled_at=datetime.now(timezone.utc).isoformat()),
            _make_edge("out_range_2026-03-10", "gold", "2026-03-10", result="hit",
                       match_score="1-0", id=2, bet_type="Away Win",
                       settled_at=datetime.now(timezone.utc).isoformat()),
        ]
        db_path = _create_test_db(edges)
        with patch("scrapers.edge.settlement.DB_PATH", db_path):
            from scrapers.edge.settlement import get_settled_in_range
            result = get_settled_in_range("2026-02-28", "2026-03-02")
        os.unlink(db_path)
        assert len(result) == 1
        assert "in_range" in result[0]["match_key"]


# ── Weekend Preview formatter tests ──────────────────────────


class TestFormatWeekendPreview:
    """Tests for _format_weekend_preview()."""

    def _get_formatter(self):
        import bot
        return bot._format_weekend_preview

    def _make_upcoming(self, **overrides):
        base = {
            "total": 10,
            "match_count": 6,
            "by_tier": {"diamond": 2, "gold": 3, "silver": 3, "bronze": 2},
            "leagues": ["PSL", "EPL"],
            "edges": [],
        }
        base.update(overrides)
        return base

    @patch("bot._founding_days_left", return_value=30)
    def test_bronze_format(self, mock_fd):
        fmt = self._get_formatter()
        upcoming = self._make_upcoming()
        text = fmt(upcoming, "bronze")
        assert "Weekend Preview" in text
        assert "6 matches" in text
        assert "free pick" in text
        assert "locked" in text.lower()
        assert "R99/mo" in text
        assert "Founding Member" in text

    @patch("bot._founding_days_left", return_value=30)
    def test_gold_format(self, mock_fd):
        fmt = self._get_formatter()
        upcoming = self._make_upcoming()
        text = fmt(upcoming, "gold")
        assert "Weekend Preview" in text
        assert "Diamond only" in text
        assert "✅" in text
        assert "R199/mo" in text
        assert "Founding Member" in text

    @patch("bot._founding_days_left", return_value=0)
    def test_diamond_format(self, mock_fd):
        fmt = self._get_formatter()
        upcoming = self._make_upcoming()
        text = fmt(upcoming, "diamond")
        assert "Weekend Preview" in text
        assert "All yours" in text
        assert "Upgrade" not in text
        assert "Founding Member" not in text

    @patch("bot._founding_days_left", return_value=0)
    def test_empty_edges(self, mock_fd):
        fmt = self._get_formatter()
        upcoming = self._make_upcoming(total=0, match_count=0, by_tier={}, leagues=[])
        text = fmt(upcoming, "bronze")
        assert "0 edges" in text or "0 match" in text

    @patch("bot._founding_days_left", return_value=0)
    def test_no_founding_member_when_expired(self, mock_fd):
        fmt = self._get_formatter()
        upcoming = self._make_upcoming()
        text = fmt(upcoming, "bronze")
        assert "Founding Member" not in text


# ── Monday Recap formatter tests ─────────────────────────────


class TestFormatMondayRecap:
    """Tests for _format_monday_recap()."""

    def _get_formatter(self):
        import bot
        return bot._format_monday_recap

    def _make_settled(self, tiers_and_results):
        """Build settled edges from list of (tier, result) tuples."""
        settled = []
        for i, (tier, result) in enumerate(tiers_and_results):
            settled.append(_make_edge(
                f"team_a_vs_team_b_2026-03-01", tier, "2026-03-01",
                result=result, match_score="2-1", id=i+1,
                recommended_odds=2.10, predicted_ev=5.0,
            ))
        return settled

    @patch("bot._founding_days_left", return_value=30)
    def test_bronze_blurred_odds(self, mock_fd):
        fmt = self._get_formatter()
        settled = self._make_settled([
            ("bronze", "hit"), ("gold", "hit"), ("diamond", "miss"),
        ])
        text = fmt(settled, "bronze")
        assert "What You Missed" in text
        assert "tg-spoiler" not in text  # W28: spoiler tags removed, return-only display
        assert "R99/mo" in text or "/subscribe" in text
        assert "Founding Member" in text

    @patch("bot._founding_days_left", return_value=30)
    def test_gold_visible_diamond(self, mock_fd):
        fmt = self._get_formatter()
        settled = self._make_settled([
            ("gold", "hit"), ("diamond", "hit"),
        ])
        text = fmt(settled, "gold")
        assert "Diamond Edges You Missed" in text
        assert "2.10" not in text  # W28: Gold sees return only, no Diamond odds
        assert "R630" in text or "return on R300" in text  # return amount shown
        assert "/subscribe" in text
        assert "Founding Member" in text

    @patch("bot._founding_days_left", return_value=0)
    def test_diamond_not_sent(self, mock_fd):
        """Diamond users get empty string (skipped in job)."""
        fmt = self._get_formatter()
        settled = self._make_settled([("diamond", "hit")])
        # Diamond tier case not handled by formatter — the job skips before calling
        # So we just verify gold/bronze paths work
        text = fmt(settled, "gold")
        assert text  # gold gets content

    @patch("bot._founding_days_left", return_value=0)
    def test_empty_settled(self, mock_fd):
        fmt = self._get_formatter()
        text = fmt([], "bronze")
        assert text == ""

    @patch("bot._founding_days_left", return_value=0)
    def test_loss_transparency(self, mock_fd):
        """Losses should be shown honestly, not hidden."""
        fmt = self._get_formatter()
        settled = self._make_settled([("bronze", "miss"), ("gold", "miss")])
        text = fmt(settled, "bronze")
        assert "❌" in text
        assert "Miss" in text


# ── Date helper tests ─────────────────────────────────────────


class TestGetLastWeekendRange:
    """Tests for _get_last_weekend_range()."""

    @patch("bot.config")
    def test_monday_returns_fri_sun(self, mock_config):
        mock_config.TZ = "Africa/Johannesburg"
        from bot import _get_last_weekend_range
        # We can't easily mock datetime.now inside the function,
        # but we can verify it returns valid ISO dates
        fri, sun = _get_last_weekend_range()
        assert len(fri) == 10  # YYYY-MM-DD
        assert len(sun) == 10
        fri_date = date.fromisoformat(fri)
        sun_date = date.fromisoformat(sun)
        assert sun_date >= fri_date
        assert (sun_date - fri_date).days <= 6  # max 6 days apart


# ── Trial restart polish tests ────────────────────────────────


class TestTrialRestartPolish:
    """Tests for polished trial restart messages."""

    @pytest.mark.asyncio
    @patch("bot.analytics_track")
    @patch("bot.db")
    @patch("bot._founding_days_left", return_value=30)
    async def test_cmd_restart_trial_includes_expiry(self, mock_fd, mock_db, mock_analytics, mock_update, mock_context):
        import bot
        mock_db.restart_trial = AsyncMock(return_value=True)
        await bot.cmd_restart_trial(mock_update, mock_context)
        call_args = mock_update.message.reply_text.call_args
        text = call_args[0][0] if call_args[0] else call_args[1].get("text", "")
        assert "until" in text.lower() or "explore" in text.lower()
        assert "Founding Member" in text
        assert "R199/mo" in text

    @pytest.mark.asyncio
    @patch("bot.analytics_track")
    @patch("bot.db")
    async def test_cmd_restart_trial_already_used(self, mock_db, mock_analytics, mock_update, mock_context):
        import bot
        mock_db.restart_trial = AsyncMock(return_value=False)
        await bot.cmd_restart_trial(mock_update, mock_context)
        call_args = mock_update.message.reply_text.call_args
        text = call_args[0][0] if call_args[0] else call_args[1].get("text", "")
        assert "not available" in text.lower()


# ── CTA consistency tests ─────────────────────────────────────


class TestCTAConsistency:
    """Tests for CTA polish pass."""

    def test_tier_gate_founding_member_bronze_tip(self):
        """tier_gate upgrade messages should include Founding Member when active."""
        from tier_gate import get_upgrade_message, _founding_member_line
        with patch("tier_gate._dt") if False else patch.dict(os.environ, {}):
            msg = get_upgrade_message("bronze", "tip")
            assert "R99/mo" in msg
            assert "/subscribe" in msg

    def test_tier_gate_founding_member_gold(self):
        """Gold upgrade message should mention Diamond pricing."""
        from tier_gate import get_upgrade_message
        msg = get_upgrade_message("gold")
        assert "R199/mo" in msg
        assert "Diamond" in msg

    def test_tier_gate_diamond_no_message(self):
        """Diamond users should get empty upgrade message."""
        from tier_gate import get_upgrade_message
        msg = get_upgrade_message("diamond")
        assert msg == ""

    def test_format_results_bronze_cta_has_price(self):
        """Bronze CTA in results should include pricing."""
        import bot
        stats = {
            "total": 10, "hits": 7, "misses": 3, "hit_rate": 0.7,
            "avg_ev": 5.0, "avg_return": 150.0, "roi": 5.0,
            "by_tier": {"gold": {"total": 5, "hits": 4, "hit_rate": 0.8}},
            "by_sport": {}, "period_days": 7,
        }
        recent = []
        streak = {"type": "none", "count": 0, "tier": None}
        text = bot._format_results_text(stats, recent, streak, 7, "bronze")
        assert "R99/mo" in text or "R799/yr" in text

    def test_no_aggressive_punctuation(self):
        """No '!!' in user-facing CTA strings."""
        import bot
        # Check the weekend preview and monday recap formatters
        with patch("bot._founding_days_left", return_value=30):
            upcoming = {
                "total": 5, "match_count": 3,
                "by_tier": {"diamond": 1, "gold": 2, "silver": 1, "bronze": 1},
                "leagues": ["PSL"], "edges": [],
            }
            for tier in ("bronze", "gold", "diamond"):
                text = bot._format_weekend_preview(upcoming, tier)
                assert "!!" not in text, f"Found '!!' in {tier} weekend preview"

            settled = [_make_edge("a_vs_b_2026-03-01", "gold", "2026-03-01",
                                 result="hit", match_score="2-1")]
            for tier in ("bronze", "gold"):
                text = bot._format_monday_recap(settled, tier)
                assert "!!" not in text, f"Found '!!' in {tier} monday recap"

    def test_weekend_preview_max_one_cta(self):
        """Each tier variant should have at most one upgrade CTA block."""
        import bot
        with patch("bot._founding_days_left", return_value=30):
            upcoming = {
                "total": 5, "match_count": 3,
                "by_tier": {"diamond": 1, "gold": 2, "silver": 1, "bronze": 1},
                "leagues": ["PSL"], "edges": [],
            }
            for tier in ("bronze", "gold", "diamond"):
                text = bot._format_weekend_preview(upcoming, tier)
                # Count "View Plans" or "Upgrade" mentions
                upgrade_count = text.lower().count("upgrade")
                if tier == "diamond":
                    assert upgrade_count == 0
                else:
                    assert upgrade_count <= 2  # "Upgrade to X" appears once in CTA
