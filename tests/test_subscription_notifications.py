from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

import bot


pytestmark = pytest.mark.asyncio


async def test_subscription_cancel_notification_not_founding_copy():
    fake_bot = MagicMock()
    fake_bot.send_message = AsyncMock()

    await bot._notify_payment_outcome(
        fake_bot,
        {
            "user_id": 6101,
            "outcome": "cancelled",
            "plan_code": "diamond_monthly",
            "subscription_deactivated": True,
        },
    )

    text = fake_bot.send_message.call_args.kwargs["text"]
    assert "Subscription cancelled" in text
    assert "founding slot" not in text.lower()


async def test_subscription_expiry_notification_not_silent():
    fake_bot = MagicMock()
    fake_bot.send_message = AsyncMock()

    await bot._notify_payment_outcome(
        fake_bot,
        {
            "user_id": 6101,
            "outcome": "expired",
            "plan_code": "diamond_monthly",
            "subscription_deactivated": True,
        },
    )

    text = fake_bot.send_message.call_args.kwargs["text"]
    assert "Subscription expired" in text
    assert "founding slot" not in text.lower()
