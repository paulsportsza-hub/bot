"""Unit tests for reverse trial system (Wave 21)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
import pytest_asyncio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.asyncio
class TestTrialDB:
    """Test trial database helpers in db.py."""

    async def test_start_trial(self, test_db):
        """start_trial sets user to diamond with trial_status=active."""
        import db

        user = await db.upsert_user(9001, "trial_user", "Trial")
        await db.start_trial(9001, days=7)

        user = await db.get_user(9001)
        assert user.trial_status == "active"
        assert user.user_tier == "diamond"
        assert user.trial_start_date is not None
        assert user.trial_end_date is not None
        assert user.trial_end_date > user.trial_start_date

    async def test_expire_trial(self, test_db):
        """expire_trial downgrades to bronze with trial_status=expired."""
        import db

        await db.upsert_user(9002, "trial_user", "Trial")
        await db.start_trial(9002, days=7)
        await db.expire_trial(9002)

        user = await db.get_user(9002)
        assert user.trial_status == "expired"
        assert user.user_tier == "bronze"

    async def test_restart_trial_works_once(self, test_db):
        """restart_trial works once, returns False on second attempt."""
        import db

        await db.upsert_user(9003, "trial_user", "Trial")
        await db.start_trial(9003, days=7)
        await db.expire_trial(9003)

        # First restart succeeds
        success = await db.restart_trial(9003)
        assert success is True

        user = await db.get_user(9003)
        assert user.trial_status == "restarted"
        assert user.user_tier == "diamond"
        assert user.trial_restart_used is True

        # Expire again
        await db.expire_trial(9003)

        # Second restart fails
        success = await db.restart_trial(9003)
        assert success is False

    async def test_restart_trial_fails_no_prior_trial(self, test_db):
        """restart_trial fails if user never had a trial."""
        import db

        await db.upsert_user(9004, "no_trial", "No")
        success = await db.restart_trial(9004)
        assert success is False

    async def test_is_trial_active(self, test_db):
        """is_trial_active returns True during trial, False after expiry."""
        import db

        await db.upsert_user(9005, "trial_check", "Check")

        # Before trial
        assert await db.is_trial_active(9005) is False

        # During trial
        await db.start_trial(9005, days=7)
        assert await db.is_trial_active(9005) is True

        # After expiry
        await db.expire_trial(9005)
        assert await db.is_trial_active(9005) is False

    async def test_trial_stats(self, test_db):
        """get_trial_stats returns trial info dict."""
        import db

        await db.upsert_user(9006, "stats_user", "Stats")
        await db.start_trial(9006, days=7)

        stats = await db.get_trial_stats(9006)
        assert "days_remaining" in stats
        assert "detail_views" in stats
        assert stats["days_remaining"] <= 7
