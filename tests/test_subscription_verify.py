from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import bot


pytestmark = pytest.mark.asyncio


async def test_subscription_verify_uses_subscription_status_endpoint():
    query = MagicMock()
    query.from_user = SimpleNamespace(id=7001)
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    query.message = MagicMock(photo=None)

    payment = SimpleNamespace(plan_code="gold_monthly")

    with (
        patch.object(bot.config, "STITCH_MOCK_MODE", False),
        patch.object(bot.db, "get_payment_by_provider_payment_id", new_callable=AsyncMock, return_value=payment),
        patch.object(bot.stitch_service, "get_subscription_status", new_callable=AsyncMock, return_value={"status": "pending"}) as get_subscription_status,
        patch.object(bot.stitch_service, "get_payment_status", new_callable=AsyncMock) as get_payment_status,
    ):
        await bot._handle_sub_verify(query, "sub_verify_7001")

    get_subscription_status.assert_awaited_once_with("sub_verify_7001")
    get_payment_status.assert_not_called()
    text = query.edit_message_text.call_args.args[0]
    assert "Provider status: <code>pending</code>" in text
