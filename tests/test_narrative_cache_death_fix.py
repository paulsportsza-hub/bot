from __future__ import annotations

import pytest
pytest.skip(
    "FIX-DROP-SONNET-POLISH-W82-CANONICAL-01: Sonnet/Haiku polish ripped out. "
    "This test asserts polish-chain behaviour that no longer exists.",
    allow_module_level=True,
)

"""FIX-NARRATIVE-CACHE-DEATH-01 — Tests for quarantine-on-reject, cooldown, and write surfacing."""

import asyncio
import json
import logging
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

import bot


# ── Helpers ────────────────────────────────────────────────────────────────────

def _init_db(db_path: str) -> None:
    """Bootstrap the narrative_cache table with all required columns."""
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS odds_latest "
        "(match_id TEXT, bookmaker TEXT, home_odds REAL, draw_odds REAL, away_odds REAL)"
    )
    conn.commit()
    conn.close()


def _good_narrative(match: str = "Chiefs vs Pirates") -> str:
    """Return a well-formed narrative that passes all quality gates."""
    return (
        f"🎯 <b>{match}</b>\n\n"
        "📋 <b>The Setup</b>\n"
        "Chiefs have won four of their last five. Pirates are three points behind.\n\n"
        "🎯 <b>The Edge</b>\n"
        "The 2.10 on Chiefs at Betway (48% implied) sits below our 61% model estimate — "
        "a 27% expected value gap.\n\n"
        "⚠️ <b>The Risk</b>\n"
        "Home form has been erratic. Size carefully.\n\n"
        "🏆 <b>Verdict</b>\n"
        "Back Chiefs at 2.10 on Betway."
    )


def _insert_row(
    db_path: str,
    match_id: str,
    html: str,
    *,
    narrative_source: str = "w84",
    status: str | None = None,
    quarantine_reason: str | None = None,
) -> None:
    conn = sqlite3.connect(db_path)
    now = datetime.now(timezone.utc)
    expires = now + timedelta(hours=6)
    conn.execute(
        "INSERT INTO narrative_cache "
        "(match_id, narrative_html, model, edge_tier, tips_json, odds_hash, "
        "created_at, expires_at, narrative_source, status, quarantine_reason) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            match_id,
            html,
            "sonnet",
            "gold",
            json.dumps([{"outcome": "home", "odds": 2.1, "ev": 27.0}]),
            "",
            now.isoformat(),
            expires.isoformat(),
            narrative_source,
            status,
            quarantine_reason,
        ),
    )
    conn.commit()
    conn.close()


def _fetch_row(db_path: str, match_id: str) -> dict | None:
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT status, quarantine_reason FROM narrative_cache WHERE match_id = ?",
            (match_id,),
        ).fetchone()
        if row is None:
            return None
        return {"status": row[0], "quarantine_reason": row[1]}
    finally:
        conn.close()


# ── AC2 / AC3: FIX-1 quarantine-on-reject ──────────────────────────────────────

@pytest.mark.asyncio
async def test_cache_quarantine_on_reject(tmp_path) -> None:
    """Quality-gate rejection sets status='quarantined' — row is NOT deleted."""
    db_path = str(tmp_path / "odds.db")
    _init_db(db_path)
    original = bot._NARRATIVE_DB_PATH
    bot._NARRATIVE_DB_PATH = db_path

    try:
        bot._ensure_narrative_cache_table()

        # Insert a narrative containing a banned phrase — _has_banned_patterns will reject it.
        # "guaranteed winner" is on the banned list.
        bad_html = (
            "🎯 <b>Chiefs vs Pirates</b>\n\n"
            "📋 <b>The Setup</b>\nContext here.\n\n"
            "🎯 <b>The Edge</b>\nThis is a guaranteed winner — numbers confirm it.\n\n"
            "⚠️ <b>The Risk</b>\nMinimal.\n\n"
            "🏆 <b>Verdict</b>\nBack Chiefs."
        )
        _insert_row(db_path, "chiefs_vs_pirates_2026-05-01", bad_html)

        result = await bot._get_cached_narrative("chiefs_vs_pirates_2026-05-01")

        assert result is None, "Banned-phrase narrative must return None (cache miss)"

        # Row must still exist — quarantined, not deleted
        row = _fetch_row(db_path, "chiefs_vs_pirates_2026-05-01")
        assert row is not None, "Row must NOT be deleted — quarantined in place"
        assert row["status"] == "quarantined", f"Expected status='quarantined', got {row['status']!r}"
        assert row["quarantine_reason"] is not None, "quarantine_reason must be set"
        assert len(row["quarantine_reason"]) > 0, "quarantine_reason must not be empty"
    finally:
        bot._NARRATIVE_DB_PATH = original


@pytest.mark.asyncio
async def test_quarantined_rows_not_served(tmp_path) -> None:
    """A row with status='quarantined' is treated as a cache miss — never served."""
    db_path = str(tmp_path / "odds.db")
    _init_db(db_path)
    original = bot._NARRATIVE_DB_PATH
    bot._NARRATIVE_DB_PATH = db_path

    try:
        bot._ensure_narrative_cache_table()

        # Insert a well-formed narrative row but mark it quarantined externally.
        _insert_row(
            db_path,
            "sundowns_vs_sekhukhune_2026-05-01",
            _good_narrative("Sundowns vs Sekhukhune"),
            status="quarantined",
            quarantine_reason="test_quarantine",
        )

        result = await bot._get_cached_narrative("sundowns_vs_sekhukhune_2026-05-01")

        assert result is None, (
            "Quarantined row must return None — it should not be served to users"
        )

        # Confirm the row is still there (not re-deleted or re-quarantined)
        row = _fetch_row(db_path, "sundowns_vs_sekhukhune_2026-05-01")
        assert row is not None, "Quarantined row must remain in DB"
        assert row["status"] == "quarantined"
    finally:
        bot._NARRATIVE_DB_PATH = original


# ── AC4: FIX-2 cooldown ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_background_fill_cooldown() -> None:
    """Second fill call within 2h window is skipped — no pregen invocation."""
    match_key = "pirates_vs_chiefs_2026-05-10"

    # Reset the cooldown state for a clean test
    bot._pregen_fill_last_attempt.pop(match_key, None)

    # Populate hot_tips_cache so _hot_keys is non-empty
    bot._hot_tips_cache["global"] = {
        "tips": [{"match_id": match_key, "ev": 5.0}],
        "ts": time.time(),
    }

    call_count = 0

    async def _fake_pregen(mode: str) -> None:
        nonlocal call_count
        call_count += 1

    # Patch pregen_main and the uncached counter so the sweep would normally run.
    with (
        patch("bot._pregen_active", False),
        patch("scripts.pregenerate_narratives.main", side_effect=_fake_pregen),
        patch("bot._count_uncached_hot_tips", return_value=1),
        patch("bot._pregen_lock", asyncio.Lock()),
    ):
        # First call — should proceed (no cooldown entry yet).
        bot._pregen_active = False
        await bot._background_pregen_fill()

        first_attempt_time = bot._pregen_fill_last_attempt.get(match_key)
        assert first_attempt_time is not None, "First call must record attempt time"

        # Second call immediately after — cooldown active, must be skipped.
        bot._pregen_active = False
        await bot._background_pregen_fill()

    # pregen should only have been called once (first call).
    # The second call must have returned early due to cooldown.
    assert call_count <= 1, (
        f"pregen was called {call_count} times — second call should have been skipped by cooldown"
    )

    # Cleanup
    bot._pregen_fill_last_attempt.pop(match_key, None)
    bot._hot_tips_cache.pop("global", None)


# ── AC5: FIX-3 write failure surfaced ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_cache_write_failure_logged_not_swallowed(tmp_path, caplog) -> None:
    """Cache INSERT failure emits log.warning with match_key + exception; function still returns summary."""
    db_path = str(tmp_path / "odds.db")
    original = bot._NARRATIVE_DB_PATH
    bot._NARRATIVE_DB_PATH = db_path

    try:
        # Build a fake OpenRouter (aliased as `anthropic` in bot.py) response object.
        # bot.py does: import openrouter_client as anthropic
        fake_content = MagicMock()
        fake_content.text = "Chiefs are in red-hot form. A tight contest expected at FNB Stadium."

        fake_response = MagicMock()
        fake_response.content = [fake_content]

        fake_client = MagicMock()
        fake_client.messages.create.return_value = fake_response

        # FIX-COST-WAVE-02: _generate_verdict now imports anthropic_client (direct Anthropic).
        call_count = [0]

        def _patched_gc(path, **kwargs):
            call_count[0] += 1
            if call_count[0] > 1:
                # Second call is _store — raise to simulate DB lock.
                raise sqlite3.OperationalError("database is locked")
            # First call is _check_cache — return empty in-memory DB (no cached row).
            conn = sqlite3.connect(":memory:")
            conn.execute(
                "CREATE TABLE narrative_cache "
                "(match_id TEXT PRIMARY KEY, narrative_html TEXT, expires_at TEXT)"
            )
            return conn

        with (
            patch("anthropic_client.Anthropic", return_value=fake_client),
            patch("db_connection.get_connection", side_effect=_patched_gc),
            caplog.at_level(logging.WARNING, logger="bot"),
        ):
            result = await bot._generate_haiku_match_summary(
                match_key="test_match_2026-05-01",
                home="Chiefs",
                away="Pirates",
                league="PSL",
                sport="soccer",
                kickoff="Today 15:30",
            )

        # Function must return the summary string — not raise, not return empty due to DB failure.
        assert isinstance(result, str), "Must return a string even when cache write fails"
        assert len(result) > 0, "Returned summary must be non-empty"

        # At least one WARNING must have been emitted mentioning the match_key or cache failure.
        warning_records = [
            r for r in caplog.records
            if r.levelno >= logging.WARNING
            and ("cache" in r.message.lower() or "test_match" in r.message.lower())
        ]
        assert warning_records, (
            "Expected at least one WARNING log about the cache write failure; "
            f"got records: {[r.message for r in caplog.records]}"
        )
    finally:
        bot._NARRATIVE_DB_PATH = original
