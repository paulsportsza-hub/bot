"""W92-VERDICT-QUALITY P3 — narrative_skip_log SQLite-backed skip counter.

Verifies the three helpers in ``scripts.pregenerate_narratives`` that replace
the in-memory ``_banned_shape_reject_count`` dict with a persistent
``narrative_skip_log`` row in ``odds.db``:

  - ``_load_skip_count(match_key)`` → returns count; 0 if absent.
  - ``_bump_skip_count(match_key)`` → increments, persists, sets skipped_flag
    when count reaches ``_BANNED_SHAPE_SKIP_THRESHOLD``, returns new count.
  - ``_clear_skip_count(match_key)`` → removes the row (and clears the cache).

Uses an isolated sqlite file and monkey-patches ``SCRAPERS_ROOT`` so the tests
never touch the live ``odds.db``.
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scripts import pregenerate_narratives as _pn


class TestNarrativeSkipLog(unittest.TestCase):
    """W92-VERDICT-QUALITY P3: SQLite-backed banned-shape skip counter."""

    def setUp(self):
        # Isolated sqlite file — shaped as if it were SCRAPERS_ROOT / "odds.db".
        self._tmpdir = tempfile.mkdtemp(prefix="w92_skip_log_")
        self._fake_scrapers_root = Path(self._tmpdir)
        # Pre-create odds.db so connect_odds_db can open it cleanly.
        (self._fake_scrapers_root / "odds.db").touch()
        # Patch module-level SCRAPERS_ROOT used by the helpers.
        self._scrapers_patch = patch.object(
            _pn, "SCRAPERS_ROOT", self._fake_scrapers_root
        )
        self._scrapers_patch.start()
        # Wipe the module-level cache between tests — these helpers use it as
        # a write-through cache so leftover state would mask DB behaviour.
        _pn._banned_shape_reject_count.clear()

    def tearDown(self):
        self._scrapers_patch.stop()
        _pn._banned_shape_reject_count.clear()
        # Clean temp files.
        for p in self._fake_scrapers_root.glob("*"):
            try:
                p.unlink()
            except Exception:
                pass
        try:
            os.rmdir(self._tmpdir)
        except OSError:
            pass

    # ── _load_skip_count ───────────────────────────────────────────────────

    def test_load_skip_count_returns_zero_for_unseen_fixture(self):
        """Fresh DB → load returns 0 and does NOT raise."""
        assert _pn._load_skip_count("arsenal_vs_chelsea_2026-05-01") == 0

    def test_load_skip_count_populates_cache(self):
        """After a DB read, the in-memory cache must have the value."""
        _pn._load_skip_count("arsenal_vs_chelsea_2026-05-01")
        assert "arsenal_vs_chelsea_2026-05-01" in _pn._banned_shape_reject_count

    def test_load_skip_count_empty_key_returns_zero(self):
        """Empty/None match_key → 0, no DB touch."""
        assert _pn._load_skip_count("") == 0

    # ── _bump_skip_count ───────────────────────────────────────────────────

    def test_bump_skip_count_increments_from_zero(self):
        """First bump → count = 1."""
        count = _pn._bump_skip_count("arsenal_vs_chelsea_2026-05-01")
        assert count == 1

    def test_bump_skip_count_increments_existing(self):
        """Second bump → count = 2; persists across the cache."""
        _pn._bump_skip_count("arsenal_vs_chelsea_2026-05-01")
        count2 = _pn._bump_skip_count("arsenal_vs_chelsea_2026-05-01")
        assert count2 == 2

    def test_bump_skip_count_persists_to_db(self):
        """After bump, a separate sqlite3 read should see the row."""
        _pn._bump_skip_count("arsenal_vs_chelsea_2026-05-01")
        db_path = self._fake_scrapers_root / "odds.db"
        conn = sqlite3.connect(str(db_path))
        try:
            row = conn.execute(
                "SELECT skip_count, skipped_flag FROM narrative_skip_log "
                "WHERE match_key = ?",
                ("arsenal_vs_chelsea_2026-05-01",),
            ).fetchone()
        finally:
            conn.close()
        assert row is not None
        assert row[0] == 1

    def test_bump_sets_skipped_flag_at_threshold(self):
        """When count >= _BANNED_SHAPE_SKIP_THRESHOLD, skipped_flag becomes 1."""
        threshold = _pn._BANNED_SHAPE_SKIP_THRESHOLD
        for _ in range(threshold):
            _pn._bump_skip_count("arsenal_vs_chelsea_2026-05-01")
        db_path = self._fake_scrapers_root / "odds.db"
        conn = sqlite3.connect(str(db_path))
        try:
            row = conn.execute(
                "SELECT skipped_flag FROM narrative_skip_log WHERE match_key = ?",
                ("arsenal_vs_chelsea_2026-05-01",),
            ).fetchone()
        finally:
            conn.close()
        assert row is not None
        assert row[0] == 1, "skipped_flag must be 1 once threshold is reached"

    # ── _clear_skip_count ──────────────────────────────────────────────────

    def test_clear_skip_count_removes_row_and_cache_entry(self):
        """After clear, DB row is gone and cache is clean."""
        key = "arsenal_vs_chelsea_2026-05-01"
        _pn._bump_skip_count(key)
        assert _pn._load_skip_count(key) == 1
        _pn._clear_skip_count(key)
        # Cache cleared.
        assert key not in _pn._banned_shape_reject_count
        # DB row removed.
        db_path = self._fake_scrapers_root / "odds.db"
        conn = sqlite3.connect(str(db_path))
        try:
            row = conn.execute(
                "SELECT skip_count FROM narrative_skip_log WHERE match_key = ?",
                (key,),
            ).fetchone()
        finally:
            conn.close()
        assert row is None

    def test_clear_skip_count_empty_key_is_noop(self):
        """Empty/None key → silent no-op, no exception."""
        _pn._clear_skip_count("")

    # ── W81-DBLOCK compliance ──────────────────────────────────────────────

    def test_module_uses_connect_odds_db_not_raw_sqlite3(self):
        """W81-DBLOCK: helpers must go through ``scrapers.db_connect`` — never
        open ``sqlite3.connect`` directly. Regression guard.
        """
        import inspect
        source = inspect.getsource(_pn._load_skip_count)
        source += inspect.getsource(_pn._bump_skip_count)
        source += inspect.getsource(_pn._clear_skip_count)
        assert "sqlite3.connect" not in source
        assert "connect_odds_db" in source


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
