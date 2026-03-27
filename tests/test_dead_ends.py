"""Dead-end checks for core callback surfaces."""

from __future__ import annotations

import re
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import BOT_ROOT

import pytest

import bot
import db


def _callbacks(markup) -> list[str]:
    return [
        btn.callback_data
        for row in markup.inline_keyboard
        for btn in row
        if getattr(btn, "callback_data", None)
    ]


def _has_back_path(markup) -> bool:
    callbacks = _callbacks(markup)
    return any(
        cb.startswith(
            ("nav:main", "menu:home", "hot:back:", "settings:home", "yg:all:0")
        )
        for cb in callbacks
    )


def _tip(match_id: str = "dead_end_test") -> dict:
    return {
        "match_id": match_id,
        "event_id": match_id,
        "home_team": "Arsenal",
        "away_team": "Chelsea",
        "league": "Premier League",
        "league_key": "epl",
        "sport_key": "soccer_epl",
        "commence_time": "2026-03-29T15:30:00Z",
        "outcome": "Arsenal",
        "odds": 1.85,
        "bookmaker": "Hollywoodbets",
        "bookmaker_key": "hollywoodbets",
        "odds_by_bookmaker": {"hollywoodbets": 1.85, "betway": 1.8},
        "ev": 8.5,
        "prob": 58,
        "kelly": 3.2,
        "edge_rating": "diamond",
        "display_tier": "diamond",
        "edge_score": 62,
        "edge_v2": {"confirming_signals": 3},
    }


def test_hot_tips_page_has_back_or_home_path(monkeypatch) -> None:
    monkeypatch.setattr(
        bot,
        "_get_broadcast_details",
        lambda **_: {"broadcast": "", "kickoff": "Sat 29 Mar · 17:30"},
    )
    monkeypatch.setattr(bot, "_get_portfolio_line", lambda: "")
    monkeypatch.setattr(bot, "_founding_days_left", lambda: 8)
    _, markup = bot._build_hot_tips_page([_tip()], user_tier="diamond")
    assert _has_back_path(markup)


def test_settings_notifications_has_back_or_home_path() -> None:
    markup = bot._build_settings_notifications_keyboard(None, {})
    assert _has_back_path(markup)


def test_settings_sports_has_back_or_home_path() -> None:
    markup = bot._build_settings_sports_keyboard(["soccer"], [])
    assert _has_back_path(markup)


def test_hot_tips_detail_rows_have_back_or_home_path() -> None:
    bot._remember_hot_tip_origin(7, "dead_end_test", page=0)
    rows = bot._build_hot_tips_detail_rows(7, match_key="dead_end_test")
    callbacks = [btn.callback_data for row in rows for btn in row if btn.callback_data]
    assert "hot:back:0" in callbacks
    assert "nav:main" in callbacks


def test_results_surface_has_back_or_home_path() -> None:
    markup = bot._build_results_buttons(7, "bronze")
    assert _has_back_path(markup)


@pytest.mark.asyncio
async def test_main_menu_is_reachable_from_start(
    test_db, mock_update, mock_context
) -> None:
    await db.upsert_user(51515, "reachable", "Reachable")
    await db.set_onboarding_done(51515)
    mock_update.effective_user.id = 51515
    mock_update.effective_user.username = "reachable"
    mock_update.effective_user.first_name = "Reachable"

    await bot.cmd_start(mock_update, mock_context)

    markup = mock_update.message.reply_text.call_args.kwargs["reply_markup"]
    labels = [button.text for row in markup.keyboard for button in row]
    assert "💎 Top Edge Picks" in labels
    assert "⚙️ Settings" in labels


def test_no_orphan_callback_prefixes() -> None:
    source = (BOT_ROOT / "bot.py").read_text()
    handled_prefixes = set(re.findall(r'(?:if|elif) prefix == "([^"]+)"', source))
    callback_literals = re.findall(r'callback_data="([^"]+)"', source)
    callback_prefixes = {callback.split(":", 1)[0] for callback in callback_literals}

    missing = sorted(
        prefix for prefix in callback_prefixes if prefix not in handled_prefixes
    )
    assert missing == []
