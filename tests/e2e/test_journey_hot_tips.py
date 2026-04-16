"""Hot Tips and cross-flow journey coverage with deterministic test edges."""

from __future__ import annotations

import re
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import bot


pytestmark = pytest.mark.asyncio


def _make_query(user_id: int = 9001) -> MagicMock:
    query = MagicMock()
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    query.from_user = SimpleNamespace(
        id=user_id, first_name="Tester", username="tester"
    )
    # BUILD-W3: query.message must be a MagicMock with .photo for card sender
    query.message = MagicMock()
    query.message.chat_id = user_id
    query.message.chat = SimpleNamespace(send_message=AsyncMock())
    query.message.photo = [MagicMock()]  # simulate existing photo message
    query.message.edit_media = AsyncMock()
    query.message.delete = AsyncMock()
    query.message.edit_text = AsyncMock()
    return query


def _make_context() -> MagicMock:
    ctx = MagicMock()
    ctx.bot.send_message = AsyncMock()
    ctx.bot.send_photo = AsyncMock()  # BUILD-W3: card sender uses send_photo
    return ctx


def _callbacks(markup) -> list[str]:
    return [
        btn.callback_data
        for row in markup.inline_keyboard
        for btn in row
        if getattr(btn, "callback_data", None)
    ]


def _button_labels(markup) -> list[str]:
    return [btn.text for row in markup.inline_keyboard for btn in row]


def _visible_card_lines(text: str) -> list[str]:
    return re.findall(r"^<b>\[\d+\]</b>.*$", text, flags=re.MULTILINE)


async def test_main_menu_has_hot_tips_button() -> None:
    labels = _button_labels(bot.kb_main())
    assert "💎 Top Edge Picks" in labels


async def test_hot_go_dispatch_sends_hot_tips_surface(monkeypatch, test_edges) -> None:
    query = _make_query()
    ctx = _make_context()
    query.message.photo = None  # new message → card sent via send_photo
    monkeypatch.setattr(bot, "get_effective_tier", AsyncMock(return_value="diamond"))
    monkeypatch.setattr(
        bot.db,
        "get_user",
        AsyncMock(return_value=SimpleNamespace(consecutive_misses=0)),
    )

    await bot._dispatch_button(query, ctx, "hot", "go")

    # BUILD-W3: card pipeline sends photo, not plain text message
    ctx.bot.send_photo.assert_awaited_once()
    sent_markup = ctx.bot.send_photo.await_args.kwargs["reply_markup"]
    assert any(cb.startswith("ep:pick:") for cb in _callbacks(sent_markup))


async def test_build_hot_tips_page_shows_edge_cards(test_edges) -> None:
    text, _, _ = await bot._build_hot_tips_page(test_edges, page=0, user_tier="diamond")
    assert "Arsenal vs Chelsea" in text
    assert "Premier League" in text
    assert "Sat 29 Mar" in text


async def test_page_zero_has_next_button(test_edges) -> None:
    _, markup, _ = await bot._build_hot_tips_page(test_edges, page=0, user_tier="diamond")
    assert "hot:page:1" in _callbacks(markup)


async def test_page_one_has_prev_button(test_edges) -> None:
    _, markup, _ = await bot._build_hot_tips_page(test_edges, page=1, user_tier="diamond")
    assert "hot:page:0" in _callbacks(markup)


async def test_hot_page_dispatch_renders_second_page(monkeypatch, test_edges) -> None:
    query = _make_query()
    ctx = _make_context()
    bot._ht_tips_snapshot[query.from_user.id] = list(test_edges)
    monkeypatch.setattr(bot, "get_effective_tier", AsyncMock(return_value="diamond"))
    monkeypatch.setattr(
        bot.db,
        "get_user",
        AsyncMock(return_value=SimpleNamespace(consecutive_misses=0)),
    )

    await bot._dispatch_button(query, ctx, "hot", "page:1")

    # BUILD-W3: photo→photo pagination via edit_media (no flicker)
    query.message.edit_media.assert_awaited_once()
    rendered_markup = query.message.edit_media.await_args.kwargs["reply_markup"]
    assert "hot:page:0" in _callbacks(rendered_markup)


async def test_accessible_buttons_use_edge_detail_for_diamond(test_edges) -> None:
    _, markup, _ = await bot._build_hot_tips_page(test_edges, page=0, user_tier="diamond")
    callbacks = _callbacks(markup)
    assert any(cb.startswith("ep:pick:") for cb in callbacks)
    assert not any(cb.startswith("hot:upgrade:") for cb in callbacks)


async def test_bronze_page_uses_upgrade_buttons_for_locked_edges(test_edges) -> None:
    _, markup, _ = await bot._build_hot_tips_page(test_edges, page=0, user_tier="bronze")
    callbacks = _callbacks(markup)
    assert any(cb.startswith("hot:upgrade:") for cb in callbacks)


async def test_build_game_buttons_has_bet_cta(test_edges) -> None:
    rows = bot._build_game_buttons(
        [test_edges[0]],
        event_id=test_edges[0]["event_id"],
        user_id=1,
        source="edge_picks",
        user_tier="diamond",
        edge_tier="diamond",
        selected_outcome="Arsenal",
    )
    assert rows[0][0].text.startswith("💎 Back Arsenal on HWB")
    assert rows[0][0].url


async def test_build_game_buttons_has_compare_odds_button(test_edges) -> None:
    rows = bot._build_game_buttons(
        [test_edges[0]],
        event_id=test_edges[0]["event_id"],
        user_id=1,
        source="edge_picks",
        user_tier="diamond",
        edge_tier="diamond",
    )
    labels = [btn.text for row in rows for btn in row]
    assert "📊 Compare All Odds" not in labels  # Removed per BUTTON-REWORK-01


async def test_detail_rows_include_back_to_edge_picks(test_edges) -> None:
    bot._remember_hot_tip_origin(123, test_edges[0]["match_id"], page=1)
    rows = bot._build_hot_tips_detail_rows(123, match_key=test_edges[0]["match_id"])
    callbacks = [btn.callback_data for row in rows for btn in row if btn.callback_data]
    assert "hot:back:1" in callbacks
    # Menu button removed from detail rows per BUTTON-REWORK-01


@pytest.mark.no_test_edges
async def test_thin_slate_empty_state_is_safe() -> None:
    text, markup, _ = await bot._build_hot_tips_page([], page=0, user_tier="diamond")
    assert "thin slate" in text.lower()
    assert "yg:all:0" in _callbacks(markup)
    # Menu button removed from inline keyboards per BUTTON-REWORK-01


async def test_header_count_matches_total_edges(test_edges) -> None:
    text, _, _ = await bot._build_hot_tips_page(test_edges, page=0, user_tier="diamond")
    assert "6 Live Edges Found" in text


async def test_cards_show_league_and_kickoff_metadata(test_edges) -> None:
    text, _, _ = await bot._build_hot_tips_page(test_edges, page=0, user_tier="diamond")
    # FIX-DSTV-CHANNEL-PERM-01: DStv channel suffix permanently removed
    assert "Premier League · 📅 Sat 29 Mar · 17:30" in text
    assert "DStv" not in text


async def test_sport_icon_matches_rugby_tip(test_edges) -> None:
    text, _, _ = await bot._build_hot_tips_page([test_edges[1]], page=0, user_tier="diamond")
    assert "🏉 <b>Bulls vs Stormers</b>" in text


async def test_compare_odds_back_button_returns_to_edge_picks(test_edges) -> None:
    user_id = 44
    event_id = test_edges[0]["event_id"]
    bot._remember_odds_compare_origin(
        user_id,
        event_id,
        "edge_picks",
        match_key=test_edges[0]["match_id"],
        back_page=1,
    )
    back_button = bot._build_odds_compare_back_button(user_id, event_id)
    assert back_button.callback_data == "hot:back:1"


async def test_hot_upgrade_dispatch_returns_view_plans_and_back(
    monkeypatch, test_edges
) -> None:
    query = _make_query(user_id=77)
    ctx = _make_context()
    bot._ht_tips_snapshot[77] = list(test_edges)
    bot._remember_hot_tip_origin(77, test_edges[0]["match_id"], page=0)
    monkeypatch.setattr(bot, "get_effective_tier", AsyncMock(return_value="bronze"))

    await bot._dispatch_button(
        query, ctx, "hot", f"upgrade:{test_edges[0]['match_id']}"
    )

    text = query.edit_message_text.await_args.args[0]
    markup = query.edit_message_text.await_args.kwargs["reply_markup"]
    callbacks = _callbacks(markup)
    assert "Locked" in text
    assert "sub:plans" in callbacks
    assert "hot:back:0" in callbacks
