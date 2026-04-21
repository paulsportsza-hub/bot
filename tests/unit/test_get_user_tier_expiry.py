"""Unit tests for get_user_tier() read-time expiry enforcement.

GAP-5 — BUILD-STITCH-GOLD-DIAMOND-01
"""

from __future__ import annotations

import asyncio
import datetime as dt
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_user(user_tier="gold", tier_expires_at=None, subscription_status=None, plan_code=None):
    u = MagicMock()
    u.user_tier = user_tier
    u.tier_expires_at = tier_expires_at
    u.subscription_status = subscription_status
    u.plan_code = plan_code
    u.is_founding_member = False
    u.founding_slot_number = None
    return u


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class TestGetUserTierExpiry:
    """Read-time expiry enforcement in get_user_tier()."""

    def test_gold_expired_beyond_grace_returns_bronze(self):
        """Gold user with tier_expires_at 4 days ago (past 3-day grace) → bronze."""
        now = dt.datetime.now(dt.timezone.utc)
        expires = now - dt.timedelta(days=4)
        user = _make_user(user_tier="gold", tier_expires_at=expires)

        mock_session = AsyncMock()
        mock_session.get = AsyncMock(return_value=user)
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("db.async_session", return_value=mock_ctx):
            import db
            result = _run(db.get_user_tier(999))
        assert result == "bronze"

    def test_gold_expired_within_grace_returns_gold(self):
        """Gold user with tier_expires_at 2 days ago (inside 3-day grace) → gold."""
        now = dt.datetime.now(dt.timezone.utc)
        expires = now - dt.timedelta(days=2)
        user = _make_user(user_tier="gold", tier_expires_at=expires)

        mock_session = AsyncMock()
        mock_session.get = AsyncMock(return_value=user)
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("db.async_session", return_value=mock_ctx):
            import db
            result = _run(db.get_user_tier(999))
        assert result == "gold"

    def test_gold_no_expiry_returns_gold(self):
        """Gold user with tier_expires_at=None → gold (legacy/founding data unchanged)."""
        user = _make_user(user_tier="gold", tier_expires_at=None)

        mock_session = AsyncMock()
        mock_session.get = AsyncMock(return_value=user)
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("db.async_session", return_value=mock_ctx):
            import db
            result = _run(db.get_user_tier(999))
        assert result == "gold"

    def test_bronze_no_expiry_check(self):
        """Bronze user with no expiry → bronze (expiry logic not triggered)."""
        user = _make_user(user_tier="bronze", tier_expires_at=None, subscription_status=None)

        mock_session = AsyncMock()
        mock_session.get = AsyncMock(return_value=user)
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("db.async_session", return_value=mock_ctx):
            import db
            result = _run(db.get_user_tier(999))
        assert result == "bronze"

    def test_diamond_expired_beyond_grace_returns_bronze(self):
        """Diamond user with tier_expires_at 5 days ago → bronze."""
        now = dt.datetime.now(dt.timezone.utc)
        expires = now - dt.timedelta(days=5)
        user = _make_user(user_tier="diamond", tier_expires_at=expires)

        mock_session = AsyncMock()
        mock_session.get = AsyncMock(return_value=user)
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("db.async_session", return_value=mock_ctx):
            import db
            result = _run(db.get_user_tier(999))
        assert result == "bronze"

    def test_user_not_found_returns_bronze(self):
        """Missing user → bronze."""
        mock_session = AsyncMock()
        mock_session.get = AsyncMock(return_value=None)
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("db.async_session", return_value=mock_ctx):
            import db
            result = _run(db.get_user_tier(99999))
        assert result == "bronze"
