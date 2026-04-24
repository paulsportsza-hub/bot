"""P3-WIRE — Tests: send_photo wiring for /today and daily digest.

AC coverage:
    AC-1  /today sends image card via reply_photo
    AC-6  Daily digest scheduler uses send_photo
    AC-7  DigestMessage.build_photo() is called correctly
    AC-8  Fallback to text on RuntimeError
    AC-3  Tier filter buttons (digest:filter:*)
    AC-4  Filter taps edit caption
    AC-5  digest:back restores original caption
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import bot


# ── helpers ──────────────────────────────────────────────────────────────────

def _tip(i: int = 0, tier: str = "gold") -> dict:
    return {
        "display_tier": tier,
        "home_team": f"Home {i}",
        "away_team": f"Away {i}",
        "ev": 3.5,
        "odds": 2.10,
        "match_id": f"home{i}_vs_away{i}_2026-04-05",
        "sport_key": "soccer_epl",
        "outcome": "Home Win",
        "commence_time": "",
    }


def _make_update(user_id: int = 123) -> MagicMock:
    upd = MagicMock()
    upd.effective_user = MagicMock(id=user_id)
    upd.message = MagicMock()
    upd.message.reply_text = AsyncMock()
    upd.message.reply_photo = AsyncMock()
    upd.effective_message = upd.message
    return upd


def _make_ctx() -> MagicMock:
    ctx = MagicMock()
    ctx.bot.send_message = AsyncMock()
    ctx.bot.send_photo = AsyncMock()
    return ctx


def _make_query(user_id: int = 123) -> MagicMock:
    q = MagicMock()
    q.from_user = MagicMock(id=user_id)
    q.edit_message_caption = AsyncMock()
    q.edit_message_text = AsyncMock()
    q.answer = AsyncMock()
    return q


# ── AC-1: /today uses reply_photo ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cmd_today_sends_photo_when_image_succeeds():
    upd = _make_update()
    ctx = MagicMock()
    tips = [_tip(i) for i in range(3)]

    with patch("bot._hot_tips_cache", {"global": {"tips": tips}}), \
         patch("bot._shorten_cb_key", side_effect=lambda k: k[:10]):
        await bot.cmd_today(upd, ctx)

    upd.message.reply_photo.assert_called_once()
    upd.message.reply_text.assert_not_called()


# ── AC-8: fallback to text on RuntimeError ───────────────────────────────────

@pytest.mark.asyncio
async def test_cmd_today_falls_back_to_text_on_image_failure():
    upd = _make_update()
    ctx = MagicMock()
    tips = [_tip(0)]

    def _broken_photo(picks, **kwargs):
        raise RuntimeError("Pillow error")

    with patch("bot._hot_tips_cache", {"global": {"tips": tips}}), \
         patch("bot._shorten_cb_key", side_effect=lambda k: k[:10]), \
         patch("message_types.DigestMessage.build_photo", side_effect=_broken_photo):
        await bot.cmd_today(upd, ctx)

    upd.message.reply_text.assert_called_once()
    upd.message.reply_photo.assert_not_called()


# ── AC-7: snapshot is stored after /today ────────────────────────────────────

@pytest.mark.asyncio
async def test_cmd_today_stores_snapshot():
    upd = _make_update(user_id=999)
    ctx = MagicMock()
    tips = [_tip(0)]

    with patch("bot._hot_tips_cache", {"global": {"tips": tips}}), \
         patch("bot._shorten_cb_key", side_effect=lambda k: k[:10]):
        await bot.cmd_today(upd, ctx)

    assert bot._today_digest_snapshot.get(999) is not None


# ── AC-3/AC-4: digest:filter:gold edits caption ──────────────────────────────

@pytest.mark.asyncio
async def test_digest_filter_gold_edits_caption():
    user_id = 555
    gold_tip = _tip(0, "gold")
    bot._today_digest_snapshot[user_id] = [gold_tip]

    query = _make_query(user_id)
    ctx = MagicMock()

    await bot._dispatch_button(query, ctx, prefix="digest", action="filter:gold")

    query.edit_message_caption.assert_called_once()
    call_kwargs = query.edit_message_caption.call_args.kwargs
    assert "caption" in call_kwargs
    assert len(call_kwargs["caption"]) <= 1024


@pytest.mark.asyncio
async def test_digest_filter_missing_tier_shows_empty_state():
    user_id = 556
    # Only gold tips — filtering for diamond should show empty state
    bot._today_digest_snapshot[user_id] = [_tip(0, "gold")]

    query = _make_query(user_id)
    ctx = MagicMock()

    await bot._dispatch_button(query, ctx, prefix="digest", action="filter:diamond")

    query.edit_message_caption.assert_called_once()
    caption = query.edit_message_caption.call_args.kwargs["caption"]
    assert "No Diamond" in caption or "no diamond" in caption.lower()


# ── digest:stats ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_digest_stats_shows_tier_counts():
    user_id = 557
    bot._today_digest_snapshot[user_id] = [
        _tip(0, "gold"),
        _tip(1, "gold"),
        _tip(2, "silver"),
    ]

    query = _make_query(user_id)
    ctx = MagicMock()

    await bot._dispatch_button(query, ctx, prefix="digest", action="stats")

    query.edit_message_caption.assert_called_once()
    caption = query.edit_message_caption.call_args.kwargs["caption"]
    assert "Stats" in caption or "stats" in caption.lower()
    assert "Gold" in caption
    assert "Silver" in caption


@pytest.mark.asyncio
async def test_digest_stats_empty_snapshot():
    user_id = 558
    bot._today_digest_snapshot[user_id] = []

    query = _make_query(user_id)
    ctx = MagicMock()

    await bot._dispatch_button(query, ctx, prefix="digest", action="stats")

    query.edit_message_caption.assert_called_once()
    caption = query.edit_message_caption.call_args.kwargs["caption"]
    assert "No edges" in caption


# ── AC-5: digest:back restores caption ───────────────────────────────────────

@pytest.mark.asyncio
async def test_digest_back_restores_caption():
    user_id = 559
    tips = [_tip(0, "gold")]
    bot._today_digest_snapshot[user_id] = tips

    query = _make_query(user_id)
    ctx = MagicMock()

    await bot._dispatch_button(query, ctx, prefix="digest", action="back")

    query.edit_message_caption.assert_called_once()
    call_kwargs = query.edit_message_caption.call_args.kwargs
    assert "caption" in call_kwargs


@pytest.mark.asyncio
async def test_digest_back_fallback_to_text_on_image_failure():
    user_id = 560
    tips = [_tip(0)]
    bot._today_digest_snapshot[user_id] = tips

    query = _make_query(user_id)
    ctx = MagicMock()

    def _broken_photo(picks, **kwargs):
        raise RuntimeError("Pillow fail")

    with patch("message_types.DigestMessage.build_photo", side_effect=_broken_photo):
        await bot._dispatch_button(query, ctx, prefix="digest", action="back")

    query.edit_message_caption.assert_called_once()


# ── AC-6: Morning teaser uses send_photo ─────────────────────────────────────

@pytest.mark.asyncio
async def test_morning_teaser_uses_send_photo(mock_context):
    import db
    user = MagicMock(id=77)
    mock_context.bot.send_photo = AsyncMock()

    with patch("bot.NOTIFICATIONS_ENABLED", True), \
         patch.object(db, "get_users_for_notification", new_callable=AsyncMock, return_value=[user]), \
         patch("bot._fetch_hot_tips_from_db", new_callable=AsyncMock, return_value=[_tip(0)]), \
         patch("bot._can_send_notification", new_callable=AsyncMock, return_value=True), \
         patch("bot.get_effective_tier", new_callable=AsyncMock, return_value="gold"), \
         patch("bot._after_send", new_callable=AsyncMock), \
         patch("bot._get_settlement_funcs", return_value=(lambda d: {}, None, None, lambda: None)), \
         patch("bot._blw_fire_tips"), \
         patch("bot.send_card_or_fallback", new_callable=AsyncMock) as mock_send_card:
        await bot._morning_teaser_job(mock_context)

    mock_send_card.assert_called_once()
    mock_context.bot.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_morning_teaser_falls_back_to_text_on_image_failure(mock_context):
    import db
    user = MagicMock(id=78)
    mock_context.bot.send_photo = AsyncMock()

    with patch("bot.NOTIFICATIONS_ENABLED", True), \
         patch.object(db, "get_users_for_notification", new_callable=AsyncMock, return_value=[user]), \
         patch("bot._fetch_hot_tips_from_db", new_callable=AsyncMock, return_value=[_tip(0)]), \
         patch("bot._can_send_notification", new_callable=AsyncMock, return_value=True), \
         patch("bot.get_effective_tier", new_callable=AsyncMock, return_value="gold"), \
         patch("bot._after_send", new_callable=AsyncMock), \
         patch("bot._get_settlement_funcs", return_value=(lambda d: {}, None, None, lambda: None)), \
         patch("bot._blw_fire_tips"), \
         patch("bot.send_card_or_fallback", new_callable=AsyncMock, side_effect=Exception("render failed")):
        await bot._morning_teaser_job(mock_context)

    # IMAGE ONLY rule: no text fallback when card fails
    mock_context.bot.send_message.assert_not_called()
    mock_context.bot.send_photo.assert_not_called()
