"""FIX-FILE-ID-REUSE-AC5-AC6-01 (AC5) — token-rotation startup probe contract.

Validates startup_token_rotation_probe() and clear_all() behaviour:
  T1  empty cache → probe is a no-op (no clear, returns False)
  T2  valid file_id (bot.get_file succeeds) → no clear, returns False
  T3  Forbidden → clears entire table, returns True
  T4  BadRequest "Wrong file identifier" → clears entire table, returns True
  T5  BadRequest with unrelated message → no clear, returns False
  T6  Generic Exception → no clear, returns False
  T7  clear_all() removes every row and returns count
"""
from __future__ import annotations

import os
import sys

import pytest
from unittest.mock import AsyncMock, MagicMock

# ── env setup (mirrors conftest.py; safe to repeat) ────────────────────────
os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("ODDS_API_KEY", "test-key")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("OPENROUTER_API_KEY", "test-key")
os.environ.setdefault("ADMIN_IDS", "123456")
os.environ.setdefault("SENTRY_DSN", "")

_bot_dir = os.path.join(os.path.dirname(__file__), "..", "..")
if _bot_dir not in sys.path:
    sys.path.insert(0, _bot_dir)


def _make_cache(tmp_path):
    from file_id_cache import FileIdCache
    return FileIdCache(db_path=str(tmp_path / "rot_probe.db"))


def _seed(cache, n: int = 3) -> None:
    for i in range(n):
        cache.put(f"edge_picks.html:480x2:row{i:08d}", f"file_id_{i}")


# ════════════════════════════════════════════════════════════════════════════
# clear_all()
# ════════════════════════════════════════════════════════════════════════════


def test_t7_clear_all_removes_every_row(tmp_path):
    cache = _make_cache(tmp_path)
    _seed(cache, 5)
    assert cache.stats()["entries"] == 5

    removed = cache.clear_all()

    assert removed == 5
    assert cache.stats()["entries"] == 0


def test_t7_clear_all_on_empty_cache(tmp_path):
    cache = _make_cache(tmp_path)
    removed = cache.clear_all()
    assert removed == 0


# ════════════════════════════════════════════════════════════════════════════
# startup_token_rotation_probe()
# ════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_t1_empty_cache_is_noop(tmp_path):
    """Empty cache → probe returns False, never calls bot.get_file."""
    cache = _make_cache(tmp_path)
    bot = MagicMock()
    bot.get_file = AsyncMock()

    cleared = await cache.startup_token_rotation_probe(bot)

    assert cleared is False
    bot.get_file.assert_not_called()


@pytest.mark.asyncio
async def test_t2_valid_file_id_no_clear(tmp_path):
    """bot.get_file succeeds → cache untouched, returns False."""
    cache = _make_cache(tmp_path)
    _seed(cache, 3)

    bot = MagicMock()
    bot.get_file = AsyncMock(return_value=MagicMock(file_path="photos/foo.jpg"))

    cleared = await cache.startup_token_rotation_probe(bot)

    assert cleared is False
    assert cache.stats()["entries"] == 3
    bot.get_file.assert_awaited_once()


@pytest.mark.asyncio
async def test_t3_forbidden_clears_table(tmp_path):
    """Forbidden → clear_all() runs, returns True."""
    from telegram.error import Forbidden

    cache = _make_cache(tmp_path)
    _seed(cache, 4)
    assert cache.stats()["entries"] == 4

    bot = MagicMock()
    bot.get_file = AsyncMock(side_effect=Forbidden("bot was kicked"))

    cleared = await cache.startup_token_rotation_probe(bot)

    assert cleared is True
    assert cache.stats()["entries"] == 0


@pytest.mark.asyncio
async def test_t4_wrong_file_identifier_clears_table(tmp_path):
    """BadRequest with 'Wrong file identifier' → clear_all() runs, returns True."""
    from telegram.error import BadRequest

    cache = _make_cache(tmp_path)
    _seed(cache, 4)

    bot = MagicMock()
    bot.get_file = AsyncMock(
        side_effect=BadRequest("Wrong file identifier specified")
    )

    cleared = await cache.startup_token_rotation_probe(bot)

    assert cleared is True
    assert cache.stats()["entries"] == 0


@pytest.mark.asyncio
async def test_t5_unrelated_badrequest_does_not_clear(tmp_path):
    """BadRequest with unrelated message → no clear, returns False."""
    from telegram.error import BadRequest

    cache = _make_cache(tmp_path)
    _seed(cache, 2)

    bot = MagicMock()
    bot.get_file = AsyncMock(side_effect=BadRequest("Message is not modified"))

    cleared = await cache.startup_token_rotation_probe(bot)

    assert cleared is False
    assert cache.stats()["entries"] == 2


@pytest.mark.asyncio
async def test_t6_generic_exception_does_not_clear(tmp_path):
    """Generic Exception (e.g. network error) → no clear, returns False."""
    cache = _make_cache(tmp_path)
    _seed(cache, 2)

    bot = MagicMock()
    bot.get_file = AsyncMock(side_effect=RuntimeError("network down"))

    cleared = await cache.startup_token_rotation_probe(bot)

    assert cleared is False
    assert cache.stats()["entries"] == 2
