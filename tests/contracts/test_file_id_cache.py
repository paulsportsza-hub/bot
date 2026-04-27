"""BUILD-FILE-ID-REUSE-01 — file_id_cache + card_sender contract tests.

Validates:
  F1  get() returns None on cache miss
  F2  put() + get() round-trip returns stored file_id
  F3  get() returns None after TTL expiry
  F4  invalidate() removes entry; subsequent get() returns None
  F5  put() with empty file_id is a no-op (no row written)
  F6  stats() returns entry count
  F7  No bare sqlite3.connect() in file_id_cache module (W81-DBLOCK)
  S1  card_sender uses stored file_id for send_photo — no render called
  S2  card_sender stores file_id returned by send_photo
  S3  card_sender falls back to render when Telegram rejects file_id
  S4  card_sender stores file_id from edit_media result
  S5  _build_cache_key mirrors render_card_sync key format
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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

# ── Helpers ─────────────────────────────────────────────────────────────────

_FAKE_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00"
    b"\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x11\x00\x01\x85b"
    b"D\xa6\x00\x00\x00\x00IEND\xaeB`\x82"
)
_FAKE_FILE_ID = "AgACAgIAAxkBAAIBf2YAAbCdAAGnPQ"


def _make_cache(tmp_path):
    """Return a FileIdCache backed by a temp SQLite file."""
    from file_id_cache import FileIdCache
    return FileIdCache(db_path=str(tmp_path / "test_fid.db"))


def _make_bot():
    bot = MagicMock()
    msg = MagicMock()
    msg.photo = [MagicMock(file_id=_FAKE_FILE_ID)]
    bot.send_photo = AsyncMock(return_value=msg)
    bot.send_message = AsyncMock()
    return bot


# ════════════════════════════════════════════════════════════════════════════
# F — FileIdCache unit tests
# ════════════════════════════════════════════════════════════════════════════


def test_f1_miss_returns_none(tmp_path):
    """F1: get() on a key that was never stored returns None."""
    cache = _make_cache(tmp_path)
    assert cache.get("edge_picks.html:480x2:aabbcc112233") is None


def test_f2_put_get_round_trip(tmp_path):
    """F2: put() followed by get() returns the stored file_id."""
    cache = _make_cache(tmp_path)
    cache.put("edge_picks.html:480x2:aabbcc112233", _FAKE_FILE_ID)
    result = cache.get("edge_picks.html:480x2:aabbcc112233")
    assert result == _FAKE_FILE_ID


def test_f3_expired_entry_returns_none(tmp_path):
    """F3: get() returns None and removes the row when TTL has elapsed."""
    cache = _make_cache(tmp_path)
    cache.put("edge_picks.html:480x2:aabbcc112233", _FAKE_FILE_ID, ttl=1)
    time.sleep(1.05)  # let TTL elapse
    assert cache.get("edge_picks.html:480x2:aabbcc112233") is None


def test_f4_invalidate_removes_entry(tmp_path):
    """F4: invalidate() removes the entry; subsequent get() returns None."""
    cache = _make_cache(tmp_path)
    cache.put("edge_detail.html:480x2:xxyyzz998877", _FAKE_FILE_ID)
    assert cache.get("edge_detail.html:480x2:xxyyzz998877") == _FAKE_FILE_ID
    cache.invalidate("edge_detail.html:480x2:xxyyzz998877")
    assert cache.get("edge_detail.html:480x2:xxyyzz998877") is None


def test_f5_put_empty_file_id_is_noop(tmp_path):
    """F5: put() with empty string does not write a row."""
    cache = _make_cache(tmp_path)
    cache.put("edge_picks.html:480x2:aabbcc112233", "")
    assert cache.get("edge_picks.html:480x2:aabbcc112233") is None


def test_f6_stats_returns_counts(tmp_path):
    """F6: stats() returns a dict with at least an 'entries' key."""
    cache = _make_cache(tmp_path)
    cache.put("key1", _FAKE_FILE_ID)
    cache.put("key2", "another_file_id")
    s = cache.stats()
    assert s["entries"] == 2
    assert s["expired"] == 0


def test_f7_no_bare_sqlite_connect():
    """F7 (W81-DBLOCK): file_id_cache.py must not call sqlite3.connect() directly."""
    src_path = os.path.join(_bot_dir, "file_id_cache.py")
    with open(src_path) as f:
        source = f.read()
    assert "sqlite3.connect(" not in source, (
        "file_id_cache.py calls sqlite3.connect() directly — use get_connection() (W81-DBLOCK)"
    )


# ════════════════════════════════════════════════════════════════════════════
# S — card_sender integration tests
# ════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_s1_uses_file_id_on_cache_hit(tmp_path):
    """S1: When file_id cache has a hit, send_photo is called with the file_id — no render."""
    from file_id_cache import FileIdCache
    import card_sender

    cache = FileIdCache(db_path=str(tmp_path / "s1.db"))
    _key = card_sender._build_cache_key("edge_picks.html", {}, None)
    cache.put(_key, _FAKE_FILE_ID)

    bot = _make_bot()

    with patch("card_sender.render_card_sync") as mock_render:
        with patch("file_id_cache.file_id_cache", cache):
            await card_sender.send_card_or_fallback(
                bot=bot,
                chat_id=999,
                template="edge_picks.html",
                data={},
                text_fallback="",
                markup=MagicMock(),
            )

    mock_render.assert_not_called()
    bot.send_photo.assert_called_once()
    call_kwargs = bot.send_photo.call_args.kwargs
    assert call_kwargs["photo"] == _FAKE_FILE_ID


@pytest.mark.asyncio
async def test_s2_stores_file_id_after_send(tmp_path):
    """S2: After a successful send_photo with bytes, file_id is stored in cache."""
    from file_id_cache import FileIdCache
    import card_sender

    cache = FileIdCache(db_path=str(tmp_path / "s2.db"))
    bot = _make_bot()

    with patch("file_id_cache.file_id_cache", cache):
        with patch("card_sender.render_card_sync", return_value=_FAKE_PNG):
            await card_sender.send_card_or_fallback(
                bot=bot,
                chat_id=999,
                template="edge_picks.html",
                data={},
                text_fallback="",
                markup=MagicMock(),
            )

    # Confirm render used bytes (no prior cache hit)
    bot.send_photo.assert_called_once()
    call_kwargs = bot.send_photo.call_args.kwargs
    assert call_kwargs["photo"] == _FAKE_PNG

    # Confirm file_id was persisted
    _w = 480
    _hash = hashlib.md5(
        json.dumps({}, sort_keys=True, default=str).encode()
    ).hexdigest()[:12]
    stored = cache.get(f"edge_picks.html:{_w}x2:{_hash}")
    assert stored == _FAKE_FILE_ID


@pytest.mark.asyncio
async def test_s3_fallback_on_rejected_file_id(tmp_path):
    """S3: If Telegram rejects the stored file_id, card_sender re-renders and resends."""
    from file_id_cache import FileIdCache
    import card_sender

    cache = FileIdCache(db_path=str(tmp_path / "s3.db"))
    _w = 480
    _hash = hashlib.md5(
        json.dumps({}, sort_keys=True, default=str).encode()
    ).hexdigest()[:12]
    _key = f"edge_picks.html:{_w}x2:{_hash}"
    cache.put(_key, "stale_file_id")

    bot = MagicMock()
    # First send_photo call (with stale file_id) raises; second call succeeds
    good_msg = MagicMock()
    good_msg.photo = [MagicMock(file_id="new_file_id")]
    bot.send_photo = AsyncMock(side_effect=[Exception("Bad Request: wrong file identifier"), good_msg])

    with patch("file_id_cache.file_id_cache", cache):
        with patch("card_sender.render_card_sync", return_value=_FAKE_PNG):
            await card_sender.send_card_or_fallback(
                bot=bot,
                chat_id=999,
                template="edge_picks.html",
                data={},
                text_fallback="",
                markup=MagicMock(),
            )

    # Two send_photo calls: first rejected, second with bytes
    assert bot.send_photo.call_count == 2
    # Second call must use bytes, not the stale file_id
    second_call_photo = bot.send_photo.call_args_list[1].kwargs["photo"]
    assert second_call_photo == _FAKE_PNG

    # Stale file_id must have been evicted; new one stored
    assert cache.get(_key) == "new_file_id"


@pytest.mark.asyncio
async def test_s4_stores_file_id_from_edit_media_result(tmp_path):
    """S4: file_id from edit_media result is stored for future reuse."""
    from file_id_cache import FileIdCache
    import card_sender

    cache = FileIdCache(db_path=str(tmp_path / "s4.db"))

    bot = _make_bot()
    msg = MagicMock()
    msg.photo = [MagicMock()]  # existing photo → triggers edit_media path

    edited_msg = MagicMock()
    edited_msg.photo = [MagicMock(file_id="edit_result_fid")]
    msg.edit_media = AsyncMock(return_value=edited_msg)

    with patch("file_id_cache.file_id_cache", cache):
        with patch("card_sender.render_card_sync", return_value=_FAKE_PNG):
            await card_sender.send_card_or_fallback(
                bot=bot,
                chat_id=999,
                template="edge_picks.html",
                data={},
                text_fallback="",
                markup=MagicMock(),
                message_to_edit=msg,
            )

    _w = 480
    _hash = hashlib.md5(
        json.dumps({}, sort_keys=True, default=str).encode()
    ).hexdigest()[:12]
    stored = cache.get(f"edge_picks.html:{_w}x2:{_hash}")
    assert stored == "edit_result_fid"


def test_s5_build_cache_key_mirrors_renderer():
    """S5: _build_cache_key output matches render_card_sync's key format."""
    from card_sender import _build_cache_key

    template = "edge_detail.html"
    data = {"match_key": "arsenal_chelsea_2026-04-25", "tier": "gold"}

    _w = 540
    _dsf = 2
    _expected_hash = hashlib.md5(
        json.dumps(data, sort_keys=True, default=str).encode()
    ).hexdigest()[:12]
    _expected = f"{template}:{_w}x{_dsf}:{_expected_hash}"

    assert _build_cache_key(template, data, 540) == _expected


def test_s5_build_cache_key_default_width():
    """S5b: width=None resolves to 480 in the cache key."""
    from card_sender import _build_cache_key

    key = _build_cache_key("edge_picks.html", {}, None)
    assert key.startswith("edge_picks.html:480x2:")
