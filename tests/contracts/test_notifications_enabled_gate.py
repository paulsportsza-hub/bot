"""BUILD-CONTRACT-TESTS-01 — Test 5: NOTIFICATIONS_ENABLED Gate

Invariants:
  (a) With NOTIFICATIONS_ENABLED=False, _can_send_notification() returns False
      for any input regardless of tier or push count.
  (b) With NOTIFICATIONS_ENABLED=True (and user not muted), tier daily caps fire:
      Bronze=3, Gold=4, Diamond=5.

Uses unittest.mock to avoid live DB calls.
"""
from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


pytestmark = pytest.mark.asyncio


async def test_notifications_disabled_always_false():
    """When NOTIFICATIONS_ENABLED=False, every user returns False immediately."""
    import bot
    with patch.object(bot, "NOTIFICATIONS_ENABLED", False):
        result = await bot._can_send_notification(user_id=999)
    assert result is False, "Expected False when NOTIFICATIONS_ENABLED=False"


async def test_notifications_disabled_overrides_mute_check():
    """NOTIFICATIONS_ENABLED=False short-circuits before any DB call."""
    import bot
    import db as _db
    with patch.object(bot, "NOTIFICATIONS_ENABLED", False):
        with patch.object(_db, "is_muted", new_callable=AsyncMock) as mock_mute:
            result = await bot._can_send_notification(user_id=999)
    # is_muted should never have been called
    mock_mute.assert_not_called()
    assert result is False


@pytest.mark.parametrize("tier,cap", [
    ("bronze", 3),
    ("gold", 4),
    ("diamond", 5),
])
async def test_tier_cap_at_limit(tier: str, cap: int):
    """At exactly the daily cap, the notification is NOT allowed (count >= cap)."""
    import bot
    import db as _db
    with patch.object(bot, "NOTIFICATIONS_ENABLED", True):
        with patch.object(_db, "is_muted", new_callable=AsyncMock, return_value=False):
            with patch.object(bot, "get_effective_tier", new_callable=AsyncMock, return_value=tier):
                with patch.object(_db, "get_push_count", new_callable=AsyncMock, return_value=cap):
                    result = await bot._can_send_notification(user_id=1)
    assert result is False, (
        f"{tier} cap={cap}: expected False when push count == cap, got True"
    )


@pytest.mark.parametrize("tier,cap", [
    ("bronze", 3),
    ("gold", 4),
    ("diamond", 5),
])
async def test_tier_cap_below_limit(tier: str, cap: int):
    """One below the daily cap, the notification IS allowed (count < cap)."""
    import bot
    import db as _db
    with patch.object(bot, "NOTIFICATIONS_ENABLED", True):
        with patch.object(_db, "is_muted", new_callable=AsyncMock, return_value=False):
            with patch.object(bot, "get_effective_tier", new_callable=AsyncMock, return_value=tier):
                with patch.object(_db, "get_push_count", new_callable=AsyncMock, return_value=cap - 1):
                    result = await bot._can_send_notification(user_id=1)
    assert result is True, (
        f"{tier} cap={cap}: expected True when push count == cap-1, got False"
    )


async def test_muted_user_returns_false():
    """A muted user always gets False even when NOTIFICATIONS_ENABLED=True."""
    import bot
    import db as _db
    with patch.object(bot, "NOTIFICATIONS_ENABLED", True):
        with patch.object(_db, "is_muted", new_callable=AsyncMock, return_value=True):
            result = await bot._can_send_notification(user_id=42)
    assert result is False, "Expected False for muted user"


def test_caps_dict_values():
    """Verify the caps dict in bot.py has the locked values bronze=3, gold=4, diamond=5."""
    bot_py = os.path.join(os.path.dirname(__file__), "..", "..", "bot.py")
    with open(bot_py, encoding="utf-8") as f:
        source = f.read()

    import re
    # Find the caps dict inside _can_send_notification
    m = re.search(r"caps\s*=\s*\{([^}]+)\}", source)
    assert m, "caps dict not found in bot.py"
    caps_str = m.group(1)
    assert '"bronze"' in caps_str or "'bronze'" in caps_str
    assert '"gold"' in caps_str or "'gold'" in caps_str
    assert '"diamond"' in caps_str or "'diamond'" in caps_str
    assert ": 3" in caps_str or ":3" in caps_str, "bronze cap must be 3"
    assert ": 4" in caps_str or ":4" in caps_str, "gold cap must be 4"
    assert ": 5" in caps_str or ":5" in caps_str, "diamond cap must be 5"
