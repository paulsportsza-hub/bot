"""Focused tests for the narrow founding-member payment flow."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import bot
import config
import db
from db import Base
from services.stitch_service import StitchService


pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def file_test_db(tmp_path, monkeypatch):
    """File-backed SQLite DB so concurrent slot assignment hits one shared database."""
    db_path = tmp_path / "founding-test.db"
    db_url = f"sqlite+aiosqlite:///{db_path}"
    test_engine = create_async_engine(db_url, echo=False)
    test_session = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

    original_engine = db.engine
    original_session = db.async_session
    original_db_url = config.DATABASE_URL

    monkeypatch.setattr(config, "DATABASE_URL", db_url)
    monkeypatch.setattr(config, "DATABASE_PATH", db_path)
    db.engine = test_engine
    db.async_session = test_session

    await db.init_db()

    yield

    db.engine = original_engine
    db.async_session = original_session
    monkeypatch.setattr(config, "DATABASE_URL", original_db_url)
    await test_engine.dispose()


async def _seed_founding_payment(user_id: int, reference: str, payment_id: str) -> None:
    await db.upsert_user(user_id, f"user{user_id}", f"User {user_id}")
    await db.create_payment_record(
        user_id=user_id,
        plan_code="founding_diamond",
        amount_cents=config.FOUNDING_MEMBER_PRICE,
        provider_reference=reference,
        provider="stitch",
        provider_payment_id=payment_id,
        checkout_url=f"https://mock.stitch.money/checkout/{payment_id}",
        is_founding=True,
        billing_status="awaiting_webhook",
    )


async def _confirm_founding(reference: str, payment_id: str, event_id: str) -> dict[str, object]:
    return await db.apply_payment_event(
        provider="stitch",
        provider_reference=reference,
        provider_payment_id=payment_id,
        provider_event_id=event_id,
        plan_code="founding_diamond",
        amount_cents=config.FOUNDING_MEMBER_PRICE,
        event_status="confirmed",
        billing_status="active",
        raw_event="{}",
    )


async def test_atomic_slot_assignment_assigns_unique_slots(file_test_db):
    await _seed_founding_payment(1, "mze-1-founding_diamond-aa", "mock-pay-1")
    await _seed_founding_payment(2, "mze-2-founding_diamond-bb", "mock-pay-2")

    left, right = await asyncio.gather(
        _confirm_founding("mze-1-founding_diamond-aa", "mock-pay-1", "event-1"),
        _confirm_founding("mze-2-founding_diamond-bb", "mock-pay-2", "event-2"),
    )

    assert {left["slot_number"], right["slot_number"]} == {1, 2}
    assert left["outcome"] == "confirmed"
    assert right["outcome"] == "confirmed"


async def test_slot_cap_100_enforced(test_db):
    for user_id in range(1, config.FOUNDING_MEMBER_SLOTS + 2):
        await _seed_founding_payment(
            user_id,
            f"mze-{user_id}-founding_diamond-cap",
            f"mock-cap-{user_id}",
        )

    last_outcome = None
    for user_id in range(1, config.FOUNDING_MEMBER_SLOTS + 2):
        last_outcome = await _confirm_founding(
            f"mze-{user_id}-founding_diamond-cap",
            f"mock-cap-{user_id}",
            f"cap-event-{user_id}",
        )

    assert await db.get_founding_member_count() == config.FOUNDING_MEMBER_SLOTS
    assert last_outcome == {
        "outcome": "no_slot_available",
        "payment_status": "confirmed",
        "slot_number": None,
        "user_id": config.FOUNDING_MEMBER_SLOTS + 1,
    }
    overflow_user = await db.get_user(config.FOUNDING_MEMBER_SLOTS + 1)
    assert overflow_user.is_founding_member is False
    assert overflow_user.user_tier == "bronze"

    overflow_payment = await db.get_payment_by_reference(
        "stitch",
        f"mze-{config.FOUNDING_MEMBER_SLOTS + 1}-founding_diamond-cap",
    )
    assert overflow_payment is not None
    assert overflow_payment.status == "confirmed_no_slot"
    assert overflow_payment.billing_status == "refund_pending"


async def test_duplicate_webhook_is_idempotent(test_db):
    await _seed_founding_payment(11, "mze-11-founding_diamond-dup", "mock-dup")

    first = await _confirm_founding("mze-11-founding_diamond-dup", "mock-dup", "dup-event")
    second = await _confirm_founding("mze-11-founding_diamond-dup", "mock-dup", "dup-event")

    assert first["outcome"] == "confirmed"
    assert second["outcome"] == "duplicate_webhook"
    assert await db.get_founding_member_count() == 1


async def test_duplicate_payment_is_idempotent(test_db):
    await _seed_founding_payment(12, "mze-12-founding_diamond-pay", "mock-pay")

    first = await _confirm_founding("mze-12-founding_diamond-pay", "mock-pay", "pay-event-1")
    second = await _confirm_founding("mze-12-founding_diamond-pay", "mock-pay", "pay-event-2")

    assert first["outcome"] == "confirmed"
    assert second["outcome"] == "duplicate_payment"
    assert second["slot_number"] == first["slot_number"] == 1


async def test_already_founding_member_guard(test_db):
    await _seed_founding_payment(21, "mze-21-founding_diamond-a", "mock-a")
    first = await _confirm_founding("mze-21-founding_diamond-a", "mock-a", "guard-event-1")
    assert first["outcome"] == "confirmed"

    await _seed_founding_payment(21, "mze-21-founding_diamond-b", "mock-b")
    second = await _confirm_founding("mze-21-founding_diamond-b", "mock-b", "guard-event-2")

    assert second["outcome"] == "already_founding_member"
    assert second["slot_number"] == first["slot_number"]

    second_payment = await db.get_payment_by_reference("stitch", "mze-21-founding_diamond-b")
    assert second_payment is not None
    assert second_payment.founding_slot_number == first["slot_number"]


async def test_refund_pending_can_transition_to_refunded(test_db):
    for user_id in range(1, config.FOUNDING_MEMBER_SLOTS + 2):
        await _seed_founding_payment(
            user_id,
            f"mze-{user_id}-founding_diamond-refund",
            f"mock-refund-{user_id}",
        )
        await _confirm_founding(
            f"mze-{user_id}-founding_diamond-refund",
            f"mock-refund-{user_id}",
            f"refund-event-{user_id}",
        )

    overflow_ref = f"mze-{config.FOUNDING_MEMBER_SLOTS + 1}-founding_diamond-refund"
    refunded = await db.mark_payment_refunded("stitch", overflow_ref)
    assert refunded is not None
    assert refunded.status == "refunded"
    assert refunded.billing_status == "refunded"


async def test_mock_e2e_founding_flow(test_db, mock_context):
    user_id = 3030
    await db.upsert_user(user_id, "founder", "Founder")

    # Ensure Stitch runs in mock mode (STITCH_MOCK_MODE may be False in test env)
    monkeypatch_mock_mode = patch("config.STITCH_MOCK_MODE", True)
    monkeypatch_mock_mode.start()

    query = MagicMock()
    query.from_user = SimpleNamespace(id=user_id)
    query.edit_message_text = AsyncMock()

    await bot._handle_sub_tier(query, "founding_diamond")

    disclosure_text = query.edit_message_text.call_args.args[0]
    assert "Founding Member Checkout" in disclosure_text
    assert "Full refund before" in disclosure_text
    assert "No refunds after" in disclosure_text

    continue_query = MagicMock()
    continue_query.from_user = SimpleNamespace(id=user_id)
    continue_query.edit_message_text = AsyncMock()
    await bot._dispatch_button(continue_query, mock_context, "sub", "founding_continue:founding_diamond")
    assert "email address" in continue_query.edit_message_text.call_args.args[0]

    loading_message = MagicMock()
    loading_message.delete = AsyncMock()
    update = MagicMock()
    update.effective_user = SimpleNamespace(id=user_id)
    update.message = MagicMock()
    update.message.text = "founder@example.com"
    update.message.reply_text = AsyncMock(return_value=loading_message)

    with patch("bot.send_card_or_fallback", new_callable=AsyncMock) as mock_card:
        handled = await bot._handle_sub_email(update, user_id)
    assert handled is True
    payment_id = bot._subscribe_state[user_id]["payment_id"]

    ready_text = mock_card.call_args.args[4]
    assert "webhook confirms payment" in ready_text

    verify_query = MagicMock()
    verify_query.from_user = SimpleNamespace(id=user_id)
    verify_query.answer = AsyncMock()
    verify_query.edit_message_text = AsyncMock()
    verify_query.message.photo = None  # force text→text path in _serve_response

    with patch.object(bot, "analytics_track"):
        await bot._handle_sub_verify(verify_query, payment_id)

    confirm_text = verify_query.edit_message_text.call_args_list[-1].args[0]
    assert "Founding Member confirmed" in confirm_text
    assert "#1" in confirm_text

    user = await db.get_user(user_id)
    assert user is not None
    assert user.is_founding_member is True
    assert user.user_tier == "diamond"
    assert user.founding_slot_number == 1

    monkeypatch_mock_mode.stop()


async def test_checkout_url_appends_redirect_uri(monkeypatch):
    monkeypatch.setattr(config, "STITCH_REDIRECT_URI", "https://mzansiedge.co.za/founding-success")

    checkout_url = StitchService.build_checkout_url("https://pay.stitch.money/checkout/pay-123")

    assert checkout_url == (
        "https://pay.stitch.money/checkout/pay-123"
        "?redirect_url=https%3A%2F%2Fmzansiedge.co.za%2Ffounding-success"
    )


async def test_checkout_url_preserves_existing_query_params(monkeypatch):
    monkeypatch.setattr(config, "STITCH_REDIRECT_URI", "https://mzansiedge.co.za/founding-success")

    checkout_url = StitchService.build_checkout_url(
        "https://pay.stitch.money/checkout/pay-123?foo=bar"
    )

    assert checkout_url == (
        "https://pay.stitch.money/checkout/pay-123"
        "?foo=bar&redirect_url=https%3A%2F%2Fmzansiedge.co.za%2Ffounding-success"
    )


async def test_status_and_admin_show_founding_visibility(test_db, mock_update, mock_context):
    user_id = 4040
    await db.upsert_user(user_id, "statusfounder", "Status Founder")
    await _seed_founding_payment(user_id, "mze-4040-founding_diamond-status", "mock-status")
    await _confirm_founding("mze-4040-founding_diamond-status", "mock-status", "status-event")

    mock_update.effective_user.id = user_id
    mock_update.message.reply_text = AsyncMock()
    with patch("bot.send_card_or_fallback", new_callable=AsyncMock) as mock_card:
        await bot.cmd_status(mock_update, mock_context)
    card_data = mock_card.call_args.args[3]
    assert card_data.get("founding_slot") is not None
    assert card_data["founding_slot"] == 1

    mock_update.effective_user.id = config.ADMIN_IDS[0]
    mock_update.message.reply_text = AsyncMock()
    with patch("bot.odds_svc.get_db_stats", new_callable=AsyncMock, return_value={
        "total_rows": 0,
        "bookmaker_count": 0,
        "latest_scrape": "N/A",
        "match_count": 0,
    }):
        await bot.cmd_admin(mock_update, mock_context)
    admin_text = mock_update.message.reply_text.call_args.args[0]
    assert "Founding Members" in admin_text
    assert "Recent founding payments" in admin_text
