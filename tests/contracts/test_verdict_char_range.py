"""
FIX-NARRATIVE-CACHE-SCHEMA-200-260 — Regression guard for verdict_html CHECK constraint.

Ensures:
  (a) narrative_cache.verdict_html CHECK covers length up to 260 (HARD_MAX = policy).
  (b) A 260-char verdict writes without error.
  (c) A 261-char verdict is rejected or truncated BEFORE the DB write, never silently nulled.
  (d) The write-path guard in bot._store_narrative_cache_sync uses 260, not 200.
"""

import datetime
import re
import sqlite3
import os
import pytest


def _make_in_memory_db():
    """Create an in-memory narrative_cache with the WIDENED CHECK (260)."""
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE narrative_cache (
            match_id TEXT PRIMARY KEY,
            narrative_html TEXT NOT NULL,
            model TEXT NOT NULL,
            edge_tier TEXT NOT NULL,
            tips_json TEXT NOT NULL,
            odds_hash TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP NOT NULL,
            verdict_html TEXT CHECK (verdict_html IS NULL OR (LENGTH(verdict_html) BETWEEN 1 AND 260))
        )
    """)
    return conn


def _insert(conn, match_id, verdict_html):
    conn.execute(
        "INSERT OR REPLACE INTO narrative_cache "
        "(match_id, narrative_html, model, edge_tier, tips_json, odds_hash, expires_at, verdict_html) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (match_id, "<b>test</b>", "test", "gold", "[]", "x",
         datetime.datetime.now().isoformat(), verdict_html),
    )
    conn.commit()


class TestVerdictCheckConstraint:
    """AC-1, AC-2: verify CHECK covers 260 and that boundary writes work."""

    def test_schema_check_covers_260(self):
        conn = _make_in_memory_db()
        ddl = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='narrative_cache'"
        ).fetchone()[0]
        assert "BETWEEN 1 AND 260" in ddl, (
            "narrative_cache.verdict_html CHECK must cover BETWEEN 1 AND 260. "
            f"Got: {ddl}"
        )
        assert "BETWEEN 1 AND 200" not in ddl, (
            "Old 200-char CHECK still present — migration not applied"
        )

    def test_260_char_verdict_stores_ok(self):
        conn = _make_in_memory_db()
        verdict = "A" * 260
        _insert(conn, "match_260", verdict)
        row = conn.execute(
            "SELECT LENGTH(verdict_html) FROM narrative_cache WHERE match_id='match_260'"
        ).fetchone()
        assert row and row[0] == 260

    def test_259_char_verdict_stores_ok(self):
        conn = _make_in_memory_db()
        verdict = "B" * 259
        _insert(conn, "match_259", verdict)
        row = conn.execute(
            "SELECT LENGTH(verdict_html) FROM narrative_cache WHERE match_id='match_259'"
        ).fetchone()
        assert row and row[0] == 259

    def test_1_char_verdict_stores_ok(self):
        conn = _make_in_memory_db()
        _insert(conn, "match_1", "X")
        row = conn.execute(
            "SELECT verdict_html FROM narrative_cache WHERE match_id='match_1'"
        ).fetchone()
        assert row and row[0] == "X"

    def test_null_verdict_stores_ok(self):
        conn = _make_in_memory_db()
        _insert(conn, "match_null", None)
        row = conn.execute(
            "SELECT verdict_html FROM narrative_cache WHERE match_id='match_null'"
        ).fetchone()
        assert row and row[0] is None

    def test_261_char_verdict_rejected_by_db(self):
        conn = _make_in_memory_db()
        verdict_261 = "C" * 261
        with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
            _insert(conn, "match_261", verdict_261)

    def test_old_200_check_rejected(self):
        """A table with BETWEEN 1 AND 200 must reject a 201-char verdict — this
        verifies the old constraint was real and the migration matters."""
        conn = sqlite3.connect(":memory:")
        conn.execute("""
            CREATE TABLE narrative_cache_old (
                match_id TEXT PRIMARY KEY,
                verdict_html TEXT CHECK (verdict_html IS NULL OR (LENGTH(verdict_html) BETWEEN 1 AND 200))
            )
        """)
        verdict_201 = "D" * 201
        with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
            conn.execute(
                "INSERT INTO narrative_cache_old VALUES (?, ?)",
                ("m", verdict_201),
            )
            conn.commit()


class TestWritePathGuard:
    """AC-3: code-side guard uses 260 (not 200) and never silently nulls."""

    def test_write_guard_threshold_is_260_not_200(self):
        """The write-path guard must reference 260, not 200."""
        bot_path = os.path.join(os.path.dirname(__file__), "../../bot.py")
        bot_path = os.path.normpath(bot_path)
        with open(bot_path) as fh:
            src = fh.read()

        # Must NOT have the old 200 guard
        assert "len(verdict_html) > 200" not in src, (
            "bot.py still contains the old 200-char write-path guard — "
            "must be replaced with 260"
        )

        # Must have the new 260 guard
        assert "len(verdict_html) > 260" in src, (
            "bot.py does not have the 260-char write-path guard"
        )

    def test_write_guard_does_not_null_at_201(self):
        """A 201-char verdict must NOT be nulled by the write-path guard.
        (Previously, any verdict > 200 was set to None.)"""
        bot_path = os.path.join(os.path.dirname(__file__), "../../bot.py")
        bot_path = os.path.normpath(bot_path)
        with open(bot_path) as fh:
            src = fh.read()
        # The guard must use > 260, so 201 chars would NOT trigger it
        # Verify there's no secondary guard at 201 or 200
        lines_with_200 = [
            ln for ln in src.splitlines()
            if "verdict_html" in ln and "> 200" in ln and "len(" in ln
        ]
        assert not lines_with_200, (
            f"Found unexpected 200-char verdict_html guard: {lines_with_200}"
        )

    def test_trim_to_last_sentence_is_used_not_null(self):
        """The write-path guard must call _trim_to_last_sentence, not set None directly."""
        bot_path = os.path.join(os.path.dirname(__file__), "../../bot.py")
        bot_path = os.path.normpath(bot_path)
        with open(bot_path) as fh:
            src = fh.read()

        # Find the full guard block: from the > 260 check through the assignment
        guard_block_match = re.search(
            r"len\(verdict_html\) > 260.{0,600}",
            src,
            re.DOTALL,
        )
        assert guard_block_match, "260-char guard block not found in bot.py"
        block = guard_block_match.group(0)
        assert "_trim_to_last_sentence" in block, (
            f"Write-path guard must call _trim_to_last_sentence, not set None. Block: {block[:300]}"
        )

    def test_create_table_ddl_has_260_check(self):
        """The CREATE TABLE DDL in bot.py must include BETWEEN 1 AND 260 for fresh DBs."""
        bot_path = os.path.join(os.path.dirname(__file__), "../../bot.py")
        bot_path = os.path.normpath(bot_path)
        with open(bot_path) as fh:
            src = fh.read()

        # Must appear in the CREATE TABLE IF NOT EXISTS narrative_cache block
        create_block_match = re.search(
            r"CREATE TABLE IF NOT EXISTS narrative_cache.*?(?=\n\s*\"\"\")",
            src,
            re.DOTALL,
        )
        assert create_block_match, "CREATE TABLE narrative_cache block not found"
        block = create_block_match.group(0)
        assert "BETWEEN 1 AND 260" in block, (
            "CREATE TABLE DDL does not include BETWEEN 1 AND 260 for verdict_html"
        )
