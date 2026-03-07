"""Wave 25B — UX Polish tests.

Tests for: spoiler tag fix, portfolio return calculation,
spoiler return visibility, button layout.
"""
from __future__ import annotations

import os
import sys
import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

import pytest
import pytest_asyncio

sys.path.insert(0, "/home/paulsportsza/bot")
sys.path.insert(0, "/home/paulsportsza")

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("ODDS_API_KEY", "test-odds-key")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-anthropic-key")
os.environ.setdefault("ADMIN_IDS", "123456")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")


def _create_settlement_db(edges: list[dict]) -> str:
    """Create a temp SQLite DB with edge_results. Returns path."""
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
    """)
    for e in edges:
        conn.execute("""
            INSERT INTO edge_results
            (edge_id, match_key, sport, league, edge_tier, composite_score,
             bet_type, recommended_odds, bookmaker, predicted_ev, result,
             match_score, actual_return, recommended_at, settled_at, match_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            e.get("edge_id", "e1"), e["match_key"], e.get("sport", "soccer"),
            e.get("league", "PSL"), e.get("edge_tier", "gold"), e.get("composite_score", 70),
            e.get("bet_type", "Home Win"), e["recommended_odds"], e.get("bookmaker", "hwb"),
            e.get("predicted_ev", 5.0), e.get("result"), e.get("match_score"),
            e.get("actual_return"), e.get("recommended_at", datetime.now(timezone.utc).isoformat()),
            e.get("settled_at"), e.get("match_date", datetime.now(timezone.utc).strftime("%Y-%m-%d")),
        ))
    conn.commit()
    conn.close()
    return path


# ── Spoiler Tag Tests ────────────────────────────────────


def test_spoiler_tags_not_blocks():
    """Wave 26A: blurred cards show return only, no spoiler tags or per-card CTAs."""
    from bot import _build_hot_tips_page

    tips = [{
        "home_team": "Chiefs", "away_team": "Pirates",
        "sport_key": "soccer_south_africa_psl", "league": "PSL",
        "league_key": "psl", "display_tier": "gold", "edge_rating": "gold",
        "outcome": "Chiefs Win", "odds": 2.10, "bookmaker": "hollywoodbets",
        "ev": 5.0, "match_id": "test_match_1", "event_id": "test_event_1",
    }]

    text, markup = _build_hot_tips_page(tips, page=0, user_tier="bronze")

    # Should NOT contain block characters or spoiler tags (Wave 26A removed spoilers)
    assert "█" not in text
    assert "<tg-spoiler>" not in text
    # Blurred card shows return amount
    assert "return on R300" in text
    # Footer has lock indicator
    assert "🔒" in text


def test_spoiler_return_visible():
    """Return amount should NOT be inside spoiler tags."""
    from bot import _build_hot_tips_page

    tips = [{
        "home_team": "Sundowns", "away_team": "Orlando",
        "sport_key": "soccer_south_africa_psl", "league": "PSL",
        "league_key": "psl", "display_tier": "gold", "edge_rating": "gold",
        "outcome": "Sundowns Win", "odds": 1.80, "bookmaker": "betway",
        "ev": 4.0, "match_id": "test_match_2", "event_id": "test_event_2",
    }]

    text, markup = _build_hot_tips_page(tips, page=0, user_tier="bronze")

    # Return line (💰 R540 return on R300) should be visible, not behind spoiler
    # Find return text
    lines = text.split("\n")
    for line in lines:
        if "return on R300" in line:
            assert "<tg-spoiler>" not in line, "Return amount should not be inside spoiler"
            break


# ── Portfolio Return Tests ───────────────────────────────


def test_portfolio_return_calculation():
    """R100 × top N hits should produce correct total return."""
    now_iso = datetime.now(timezone.utc).isoformat()
    edges = [
        {"match_key": f"team_a_vs_team_{i}", "recommended_odds": 2.0 + i * 0.1,
         "result": "hit", "actual_return": (2.0 + i * 0.1) * 100,
         "settled_at": now_iso, "match_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
         "edge_id": f"e{i}", "predicted_ev": 5.0}
        for i in range(5)
    ]
    db_path = _create_settlement_db(edges)

    with patch("scrapers.edge.settlement.DB_PATH", db_path):
        from scrapers.edge.settlement import get_top_10_portfolio_return
        result = get_top_10_portfolio_return(days=7)

    assert result["count"] == 5
    assert result["stake_per_edge"] == 100
    # Sum of (2.0, 2.1, 2.2, 2.3, 2.4) * 100 = 1100.0
    assert result["total_return"] == 1100.0

    os.unlink(db_path)


# ── Button Layout Test ───────────────────────────────────


def test_button_layout_2_per_row():
    """InlineKeyboard rows should have max 2 buttons."""
    from bot import _build_hot_tips_page

    tips = [{
        "home_team": f"Team {i}", "away_team": f"Opp {i}",
        "sport_key": "soccer_south_africa_psl", "league": "PSL",
        "league_key": "psl", "display_tier": "silver", "edge_rating": "silver",
        "outcome": f"Team {i} Win", "odds": 2.0 + i * 0.1,
        "bookmaker": "hwb", "ev": 3.0, "match_id": f"match_{i}", "event_id": f"event_{i}",
    } for i in range(3)]

    text, markup = _build_hot_tips_page(tips, page=0, user_tier="diamond")

    # Check all rows have <= 2 buttons
    for row in markup.inline_keyboard:
        assert len(row) <= 2, f"Row has {len(row)} buttons, max is 2: {[b.text for b in row]}"
