from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import bot
import db
from renderers import telegram_renderer
from services import templates


def _fixture(home: str = "Arsenal", away: str = "Chelsea") -> dict:
    return {
        "home": home,
        "away": away,
        "kickoff": "Today 19:30 SAST",
        "league": "Premier League",
        "broadcast": "📺 SS EPL (DStv 203)",
    }


def test_hot_tips_empty_state_shows_fixture_bridge():
    text, _ = bot._build_hot_tips_page(
        [],
        user_tier="diamond",
        thin_slate_mode="no_tips",
        thin_slate_fixtures=[_fixture()],
    )

    assert "thin slate" in text.lower()
    assert "Up Next" in text
    assert "Arsenal vs Chelsea" in text
    assert "DStv 203" in text
    assert "market is efficient" not in text


def test_hot_tips_below_threshold_state_calls_out_watchlist():
    text, _ = bot._build_hot_tips_page(
        [],
        user_tier="diamond",
        thin_slate_mode="below_threshold",
        thin_slate_fixtures=[_fixture()],
        thin_slate_weaker_tip={
            "sport_key": "soccer_epl",
            "home_team": "Arsenal",
            "away_team": "Chelsea",
            "outcome": "Arsenal",
            "odds": 2.18,
        },
    )

    assert "No Gold or Diamond-grade edges" in text
    assert "Watchlist" in text
    assert "Arsenal @ 2.18" in text
    assert "not strong enough" in text


@pytest.mark.asyncio
async def test_morning_teaser_no_tips_becomes_fixture_briefing(mock_context):
    user = MagicMock(id=77)

    with patch.object(db, "get_users_for_notification", new_callable=AsyncMock, return_value=[user]), \
         patch("bot._fetch_hot_tips_from_db", new_callable=AsyncMock, return_value=[]), \
         patch("bot._fetch_hot_tips_all_sports", new_callable=AsyncMock, return_value=[]), \
         patch("bot._get_user_fixture_preview", new_callable=AsyncMock, return_value=[_fixture()]), \
         patch("bot._can_send_notification", new_callable=AsyncMock, return_value=True), \
         patch("bot.get_effective_tier", new_callable=AsyncMock, return_value="bronze"), \
         patch("bot._after_send", new_callable=AsyncMock):
        await bot._morning_teaser_job(mock_context)

    text = mock_context.bot.send_message.call_args.kwargs["text"]
    assert "Today's Slate" in text
    assert "Arsenal vs Chelsea" in text
    assert "check back around kickoff" in text
    assert "market is tight" not in text


@pytest.mark.asyncio
async def test_weekend_preview_uses_fixture_card_when_no_edges(mock_context):
    class _ThursdayDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 3, 12, 18, 0, 0, tzinfo=tz)

    user = MagicMock(id=88)
    get_upcoming = MagicMock(return_value={
        "total": 0,
        "match_count": 0,
        "by_tier": {},
        "leagues": [],
        "edges": [],
    })

    with patch("datetime.datetime", _ThursdayDateTime), \
         patch("bot._get_settlement_funcs", return_value=(None, None, None, None, get_upcoming, None)), \
         patch.object(db, "get_all_onboarded_users", new_callable=AsyncMock, return_value=[user]), \
         patch("bot._can_send_notification", new_callable=AsyncMock, return_value=True), \
         patch("bot.get_effective_tier", new_callable=AsyncMock, return_value="bronze"), \
         patch("bot._get_user_fixture_preview", new_callable=AsyncMock, return_value=[_fixture("Chiefs", "Pirates")]), \
         patch("bot._after_send", new_callable=AsyncMock):
        await bot._weekend_preview_job(mock_context)

    text = mock_context.bot.send_message.call_args.kwargs["text"]
    assert "Weekend Preview" in text
    assert "fixtures on deck" in text
    assert "Chiefs vs Pirates" in text


@pytest.mark.asyncio
async def test_monday_recap_uses_week_ahead_when_no_results(mock_context):
    class _MondayDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 3, 9, 8, 0, 0, tzinfo=tz)

    user = MagicMock(id=99)
    get_settled = MagicMock(return_value=[])

    with patch("datetime.datetime", _MondayDateTime), \
         patch("bot._get_settlement_funcs", return_value=(None, None, None, None, None, get_settled)), \
         patch.object(db, "get_all_onboarded_users", new_callable=AsyncMock, return_value=[user]), \
         patch("bot._can_send_notification", new_callable=AsyncMock, return_value=True), \
         patch("bot.get_effective_tier", new_callable=AsyncMock, return_value="bronze"), \
         patch("bot._get_user_fixture_preview", new_callable=AsyncMock, return_value=[_fixture("Bulls", "Stormers")]), \
         patch("bot._after_send", new_callable=AsyncMock):
        await bot._monday_recap_job(mock_context)

    text = mock_context.bot.send_message.call_args.kwargs["text"]
    assert "Week Ahead" in text
    assert "Bulls vs Stormers" in text
    assert "week builds" in text


def test_user_facing_quota_strings_are_removed():
    assert "API quota:" not in templates.TEMPLATES["picks_header"]["telegram"]
    assert "API quota:" not in templates.TEMPLATES["picks_empty"]["telegram"]
    assert "API quota:" not in templates.TEMPLATES["picks_empty_newbie"]["telegram"]
    assert "API quota:" not in telegram_renderer.render_picks_header({
        "picks": [{}],
        "total_events": 4,
        "total_markets": 12,
        "risk_label": "Moderate",
    })
