"""Wave 25A — Anti-fatigue engine + /mute + re-engagement tests.

Tests for: mute/unmute, daily push caps, push count reset,
re-engagement nudge, last_active tracking.
"""
from __future__ import annotations

import os
import sys
import datetime as dt
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

sys.path.insert(0, "/home/paulsportsza/bot")
sys.path.insert(0, "/home/paulsportsza")

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("ODDS_API_KEY", "test-odds-key")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-anthropic-key")
os.environ.setdefault("ADMIN_IDS", "123456")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

import db


@pytest_asyncio.fixture
async def fresh_db(test_db):
    """Use the shared test_db fixture and create a test user."""
    u = db.User(id=111, username="testuser", first_name="Test", onboarding_done=True, is_active=True)
    async with db.async_session() as s:
        s.add(u)
        await s.commit()
    yield


# ── Mute Tests ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_mute_24h(fresh_db):
    """Test /mute sets muted_until 24h ahead, _can_send_notification returns False."""
    until = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=24)
    await db.set_muted_until(111, until)

    assert await db.is_muted(111) is True

    from bot import _can_send_notification
    assert await _can_send_notification(111) is False


@pytest.mark.asyncio
async def test_mute_week(fresh_db):
    """Test muting for 7 days."""
    until = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=7)
    await db.set_muted_until(111, until)

    assert await db.is_muted(111) is True

    async with db.async_session() as s:
        u = await s.get(db.User, 111)
        muted = u.muted_until
        if muted.tzinfo is None:
            muted = muted.replace(tzinfo=dt.timezone.utc)
        remaining = (muted - dt.datetime.now(dt.timezone.utc)).days
        assert remaining >= 6


@pytest.mark.asyncio
async def test_mute_unmute(fresh_db):
    """Test /mute off clears muted_until."""
    until = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=24)
    await db.set_muted_until(111, until)
    assert await db.is_muted(111) is True

    await db.set_muted_until(111, None)
    assert await db.is_muted(111) is False


# ── Daily Cap Tests ──────────────────────────────────────


@pytest.mark.asyncio
async def test_daily_cap_bronze(fresh_db):
    """Bronze users capped at 3 pushes/day."""
    # User is bronze by default
    from bot import _can_send_notification, _after_send

    for _ in range(3):
        assert await _can_send_notification(111) is True
        await _after_send(111)

    assert await _can_send_notification(111) is False


@pytest.mark.asyncio
async def test_daily_cap_diamond(fresh_db):
    """Diamond users capped at 5 pushes/day."""
    await db.set_user_tier(111, "diamond")
    from bot import _can_send_notification, _after_send

    for _ in range(5):
        assert await _can_send_notification(111) is True
        await _after_send(111)

    assert await _can_send_notification(111) is False


@pytest.mark.asyncio
async def test_push_count_resets_on_new_day(fresh_db):
    """Push count resets when the date changes."""
    yesterday = (dt.date.today() - dt.timedelta(days=1)).isoformat()
    async with db.async_session() as s:
        u = await s.get(db.User, 111)
        u.daily_push_count = 3
        u.last_push_date = yesterday
        await s.commit()

    count = await db.get_push_count(111)
    assert count == 0  # New day = reset


# ── Re-engagement Tests ──────────────────────────────────


@pytest.mark.asyncio
async def test_reengagement_72h(fresh_db):
    """Users inactive for 72h+ are returned by get_inactive_users."""
    old = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=80)
    async with db.async_session() as s:
        u = await s.get(db.User, 111)
        u.last_active_at = old
        await s.commit()

    inactive = await db.get_inactive_users(hours=72, nudge_cooldown_days=7)
    assert any(u.id == 111 for u in inactive)


@pytest.mark.asyncio
async def test_reengagement_cooldown(fresh_db):
    """No second nudge within 7 days of the last one."""
    old = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=80)
    recent_nudge = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=2)
    async with db.async_session() as s:
        u = await s.get(db.User, 111)
        u.last_active_at = old
        u.nudge_sent_at = recent_nudge
        await s.commit()

    inactive = await db.get_inactive_users(hours=72, nudge_cooldown_days=7)
    assert not any(u.id == 111 for u in inactive)


# ── Last Active Tests ────────────────────────────────────


@pytest.mark.asyncio
async def test_last_active_updates(fresh_db):
    """Verify last_active_at is set on update_last_active call."""
    async with db.async_session() as s:
        u = await s.get(db.User, 111)
        assert u.last_active_at is None

    await db.update_last_active(111)

    async with db.async_session() as s:
        u = await s.get(db.User, 111)
        assert u.last_active_at is not None
        now = dt.datetime.now(dt.timezone.utc)
        active = u.last_active_at
        if active.tzinfo is None:
            active = active.replace(tzinfo=dt.timezone.utc)
        assert (now - active).total_seconds() < 10
