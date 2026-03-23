"""Contracts for the narrow founding payment flow."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import bot
import config


pytestmark = pytest.mark.asyncio


async def test_launch_config_is_locked():
    assert config.LAUNCH_DATE == "2026-04-27"
    assert config.FOUNDING_MEMBER_SLOTS == 100
    assert config.FOUNDING_MEMBER_PRICE == 69900
    assert config.STITCH_MOCK_MODE is True


async def test_manual_verify_does_not_become_source_of_truth_in_real_mode():
    query = MagicMock()
    query.from_user = SimpleNamespace(id=777)
    query.edit_message_text = AsyncMock()

    with (
        patch.object(bot.config, "STITCH_MOCK_MODE", False),
        patch.object(bot.stitch_service, "get_payment_status", new_callable=AsyncMock, return_value={"status": "success"}),
        patch.object(bot, "_process_stitch_event", new_callable=AsyncMock) as process_event,
    ):
        await bot._handle_sub_verify(query, "real-payment-1")

    process_event.assert_not_called()
    final_text = query.edit_message_text.call_args_list[-1].args[0]
    assert "webhook confirmation" in final_text.lower()


async def test_founding_disclosure_contract_includes_locked_commercial_rules(test_db):
    text, _ = await bot._build_founding_disclosure_surface()

    assert "Immediate Diamond access" in text
    assert "continuously subscribed" in text
    assert "If you cancel, you lose the founding price" in text
    assert "Full refund before" in text
    assert "No refunds after" in text
