"""Wave 25C — Post-match result alerts tests.

Tests for: user_edge_views logging, result alert hit/miss templates,
daily cap enforcement, losing streak CTA suppression, bundling.
"""
from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import ensure_scrapers_importable
ensure_scrapers_importable()

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("ODDS_API_KEY", "test-odds-key")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-anthropic-key")
os.environ.setdefault("ADMIN_IDS", "123456")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

import db


@pytest_asyncio.fixture
async def fresh_db(test_db):
    """Use the shared test_db fixture and create user_edge_views table + test user."""
    # Create user_edge_views table in test DB
    async with db.engine.begin() as conn:
        await conn.exec_driver_sql("""
            CREATE TABLE IF NOT EXISTS user_edge_views (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                edge_id TEXT NOT NULL,
                edge_tier TEXT NOT NULL,
                viewed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, edge_id)
            )
        """)

    u = db.User(id=222, username="viewer", first_name="Viewer", onboarding_done=True, is_active=True)
    async with db.async_session() as s:
        s.add(u)
        await s.commit()
    yield


# ── Edge View Logging Tests ──────────────────────────────


@pytest.mark.asyncio
async def test_user_edge_views_logging(fresh_db):
    """log_edge_view inserts a row; duplicate is ignored (dedup)."""
    await db.log_edge_view(222, "edge_abc", "gold")
    viewers = await db.get_edge_viewers("edge_abc")
    assert len(viewers) == 1
    assert viewers[0]["user_id"] == 222
    assert viewers[0]["edge_tier"] == "gold"

    # Duplicate insert should be silently ignored
    await db.log_edge_view(222, "edge_abc", "gold")
    viewers = await db.get_edge_viewers("edge_abc")
    assert len(viewers) == 1  # Still 1, not 2


@pytest.mark.asyncio
async def test_edges_viewed_by_user(fresh_db):
    """get_edges_viewed_by_user returns recent views for a user."""
    await db.log_edge_view(222, "edge_x", "diamond")
    await db.log_edge_view(222, "edge_y", "silver")

    viewed = await db.get_edges_viewed_by_user(222, since_hours=48)
    assert len(viewed) == 2
    edge_ids = {v["edge_id"] for v in viewed}
    assert edge_ids == {"edge_x", "edge_y"}


# ── Result Alert HIT Test ────────────────────────────────


@pytest.mark.asyncio
async def test_result_alert_hit(fresh_db):
    """Hit alert sends correct tier template with season accuracy."""
    from bot import _result_alerts_job

    # Log edge view
    await db.log_edge_view(222, "edge_hit_1", "gold")

    settled_edges = [{
        "edge_id": "edge_hit_1",
        "match_key": "chiefs_vs_pirates",
        "edge_tier": "gold",
        "result": "hit",
        "match_score": "2-1",
        "recommended_odds": 2.10,
        "predicted_ev": 5.0,
    }]
    season_stats = {"hit_rate": 0.62, "total": 100, "hits": 62, "misses": 38}

    mock_ctx = MagicMock()

    with patch("bot.NOTIFICATIONS_ENABLED", True):
      with patch("bot.asyncio.to_thread") as mock_thread:
        with patch("bot.send_card_or_fallback", new_callable=AsyncMock) as mock_card:
            # First call: get_recently_settled_since → edges
            # Second call: get_edge_stats → stats
            mock_thread.side_effect = [settled_edges, season_stats]
            await _result_alerts_job(mock_ctx)

    # Should have sent one card
    assert mock_card.call_count == 1
    card_kwargs = mock_card.call_args.kwargs
    assert card_kwargs["template"] == "notify_result_hit.html"  # Edge Hit
    assert "62%" in card_kwargs["data"]["season_accuracy"]  # Season accuracy
    assert "chiefs" in card_kwargs["data"]["match"].lower() or "pirates" in card_kwargs["data"]["match"].lower()


# ── Result Alert MISS Test ───────────────────────────────


@pytest.mark.asyncio
async def test_result_alert_miss(fresh_db):
    """Miss alert includes season accuracy and transparency line."""
    from bot import _result_alerts_job

    await db.log_edge_view(222, "edge_miss_1", "silver")

    settled_edges = [{
        "edge_id": "edge_miss_1",
        "match_key": "sundowns_vs_orlando",
        "edge_tier": "silver",
        "result": "miss",
        "match_score": "0-0",
        "recommended_odds": 1.80,
        "predicted_ev": 3.5,
    }]
    season_stats = {"hit_rate": 0.58, "total": 50, "hits": 29, "misses": 21}

    mock_ctx = MagicMock()

    with patch("bot.NOTIFICATIONS_ENABLED", True):
      with patch("bot.asyncio.to_thread") as mock_thread:
        with patch("bot.send_card_or_fallback", new_callable=AsyncMock) as mock_card:
            mock_thread.side_effect = [settled_edges, season_stats]
            await _result_alerts_job(mock_ctx)

    assert mock_card.call_count == 1
    card_kwargs = mock_card.call_args.kwargs
    assert card_kwargs["template"] == "notify_result_miss.html"  # Edge Missed
    assert "58%" in card_kwargs["data"]["season_accuracy"]  # Season accuracy
    assert "market was right" in card_kwargs["data"]["transparency_note"].lower()


# ── Daily Cap Test ───────────────────────────────────────


@pytest.mark.asyncio
async def test_result_alert_daily_cap(fresh_db):
    """Alerts suppressed when bronze user hits daily push cap (3)."""
    import datetime as _dt
    from bot import _result_alerts_job

    # Pre-fill push count to 2 so only 1 more can go through (cap=3)
    async with db.async_session() as s:
        u = await s.get(db.User, 222)
        u.daily_push_count = 2
        u.last_push_date = _dt.date.today().isoformat()
        await s.commit()

    # Log 3 edge views — only 1 should send (count goes 2→3, then blocked)
    for i in range(3):
        await db.log_edge_view(222, f"edge_cap_{i}", "bronze")

    settled_edges = [
        {
            "edge_id": f"edge_cap_{i}",
            "match_key": f"team_a_vs_team_{i}",
            "edge_tier": "bronze",
            "result": "hit",
            "match_score": "1-0",
            "recommended_odds": 2.0,
            "predicted_ev": 4.0,
        }
        for i in range(3)
    ]
    season_stats = {"hit_rate": 0.60, "total": 80, "hits": 48, "misses": 32}

    mock_ctx = MagicMock()

    with patch("bot.NOTIFICATIONS_ENABLED", True):
      with patch("bot.asyncio.to_thread") as mock_thread:
        with patch("bot.send_card_or_fallback", new_callable=AsyncMock) as mock_card:
            mock_thread.side_effect = [settled_edges, season_stats]
            await _result_alerts_job(mock_ctx)

    # Only 1 alert should be sent (push count was 2, cap is 3)
    assert mock_card.call_count == 1


# ── Losing Streak Suppression Test ───────────────────────


@pytest.mark.asyncio
async def test_losing_streak_suppression(fresh_db):
    """Upgrade CTA suppressed after 3+ consecutive misses."""
    from bot import _result_alerts_job

    # Set consecutive_misses to 3
    await db.update_consecutive_misses(222, 3)

    await db.log_edge_view(222, "edge_streak_1", "gold")

    settled_edges = [{
        "edge_id": "edge_streak_1",
        "match_key": "team_x_vs_team_y",
        "edge_tier": "gold",
        "result": "hit",
        "match_score": "3-1",
        "recommended_odds": 2.50,
        "predicted_ev": 6.0,
    }]
    season_stats = {"hit_rate": 0.55, "total": 60, "hits": 33, "misses": 27}

    mock_ctx = MagicMock()
    with patch("bot.NOTIFICATIONS_ENABLED", True):
      with patch("bot.asyncio.to_thread") as mock_thread:
        with patch("bot.send_card_or_fallback", new_callable=AsyncMock) as mock_card:
            mock_thread.side_effect = [settled_edges, season_stats]
            await _result_alerts_job(mock_ctx)

    assert mock_card.call_count == 1
    card_kwargs = mock_card.call_args.kwargs
    markup = card_kwargs.get("markup")
    # Should NOT have "View Plans" button (upgrade CTA suppressed)
    button_texts = [btn.text for row in markup.inline_keyboard for btn in row]
    assert "✨ View Plans" not in button_texts


# ── Result Alert Bundling Test ───────────────────────────


@pytest.mark.asyncio
async def test_result_alert_bundling(fresh_db):
    """>3 results for one user bundled into single summary message."""
    from bot import _result_alerts_job

    # Log 5 edge views
    for i in range(5):
        await db.log_edge_view(222, f"edge_bundle_{i}", "gold")

    settled_edges = [
        {
            "edge_id": f"edge_bundle_{i}",
            "match_key": f"team_a_vs_team_{i}",
            "edge_tier": "gold",
            "result": "hit" if i < 3 else "miss",
            "match_score": f"{i}-0",
            "recommended_odds": 2.0 + i * 0.1,
            "predicted_ev": 5.0,
        }
        for i in range(5)
    ]
    season_stats = {"hit_rate": 0.65, "total": 100, "hits": 65, "misses": 35}

    mock_ctx = MagicMock()

    with patch("bot.NOTIFICATIONS_ENABLED", True):
      with patch("bot.asyncio.to_thread") as mock_thread:
        with patch("bot.send_card_or_fallback", new_callable=AsyncMock) as mock_card:
            mock_thread.side_effect = [settled_edges, season_stats]
            await _result_alerts_job(mock_ctx)

    # Bundled: single card for >3 results
    assert mock_card.call_count == 1
    card_kwargs = mock_card.call_args.kwargs
    data = card_kwargs["data"]
    assert data["total"] == 5   # 5 edges settled
    assert data["hits"] == 3    # 3 hit
    assert data["misses"] == 2  # 2 missed
