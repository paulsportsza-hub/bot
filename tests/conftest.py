"""Shared pytest fixtures for MzansiEdge tests."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Force test env before importing app modules
os.environ["SENTRY_DSN"] = ""  # NEVER send test errors to production Sentry
os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("ODDS_API_KEY", "test-odds-key")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-anthropic-key")
os.environ.setdefault("OPENROUTER_API_KEY", "test-openrouter-key")
os.environ.setdefault("ADMIN_IDS", "123456")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

import db  # noqa: E402
from db import Base  # noqa: E402


@pytest_asyncio.fixture
async def test_db():
    """Create a fresh in-memory database for each test."""
    test_engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    test_session = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Monkey-patch db module to use test engine/session
    original_engine = db.engine
    original_session = db.async_session
    db.engine = test_engine
    db.async_session = test_session

    yield test_session

    db.engine = original_engine
    db.async_session = original_session
    await test_engine.dispose()


@pytest.fixture
def mock_update():
    """Create a mock Telegram Update object."""
    update = MagicMock()
    update.effective_user = MagicMock()
    update.effective_user.id = 111222333
    update.effective_user.username = "testuser"
    update.effective_user.first_name = "Test"
    update.message = MagicMock()
    update.message.reply_text = AsyncMock()
    update.message.reply_photo = AsyncMock()
    update.callback_query = MagicMock()
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()
    update.callback_query.from_user = update.effective_user
    update.callback_query.data = ""
    # Ensure message is not treated as a photo message by _serve_response
    update.callback_query.message = MagicMock()
    update.callback_query.message.photo = None
    update.callback_query.message.delete = AsyncMock()
    return update


@pytest.fixture
def mock_context():
    """Create a mock ContextTypes.DEFAULT_TYPE."""
    ctx = MagicMock()
    mock_msg = MagicMock()
    mock_msg.delete = AsyncMock()
    ctx.bot.send_message = AsyncMock(return_value=mock_msg)
    return ctx
