from __future__ import annotations

import os
import asyncio
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, "/home/paulsportsza")
sys.path.insert(0, "/home/paulsportsza/scrapers")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scrapers import coach_fetcher
from scrapers import match_context_fetcher as mcf
from scrapers.db_connect import connect_odds_db_readonly


def _seed_context_tables(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE team_api_ids ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "team_name TEXT, sport TEXT, league TEXT, espn_id TEXT, espn_display_name TEXT, espn_slug TEXT)"
    )
    conn.execute(
        "CREATE TABLE api_cache ("
        "cache_key TEXT PRIMARY KEY, data TEXT, fetched_at TEXT, expires_at TEXT)"
    )
    conn.execute(
        "CREATE TABLE api_usage ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, api_name TEXT, endpoint TEXT, "
        "status_code INTEGER, cached INTEGER, called_at TEXT DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.commit()
    conn.close()


def test_connect_odds_db_readonly_sets_query_only(tmp_path) -> None:
    db_path = str(tmp_path / "odds.db")
    _seed_context_tables(db_path)

    conn = connect_odds_db_readonly(db_path, timeout=0.2)
    try:
        query_only = conn.execute("PRAGMA query_only").fetchone()[0]
    finally:
        conn.close()

    assert query_only == 1


def test_get_cache_readonly_does_not_delete_expired_rows(tmp_path) -> None:
    db_path = str(tmp_path / "odds.db")
    _seed_context_tables(db_path)
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()

    writer = sqlite3.connect(db_path)
    writer.execute(
        "INSERT INTO api_cache (cache_key, data, fetched_at, expires_at) VALUES (?, ?, ?, ?)",
        ("expired:key", "{}", past, past),
    )
    writer.commit()
    writer.close()

    ro = connect_odds_db_readonly(db_path, timeout=0.2)
    try:
        assert mcf._get_cache(
            ro,
            "expired:key",
            allow_expired_cleanup=False,
        ) is None
    finally:
        ro.close()

    verify = sqlite3.connect(db_path)
    try:
        remaining = verify.execute(
            "SELECT COUNT(*) FROM api_cache WHERE cache_key = ?",
            ("expired:key",),
        ).fetchone()[0]
    finally:
        verify.close()

    assert remaining == 1


@pytest.mark.asyncio
async def test_get_soccer_coach_live_safe_uses_cached_value_only(tmp_path, monkeypatch) -> None:
    db_path = str(tmp_path / "odds.db")
    _seed_context_tables(db_path)
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()

    writer = sqlite3.connect(db_path)
    writer.execute(
        "INSERT INTO api_cache (cache_key, data, fetched_at, expires_at) VALUES (?, ?, ?, ?)",
        ("coach:epl:arsenal", '{"coach":"Mikel Arteta"}', future, future),
    )
    writer.commit()
    writer.close()

    class _ShouldNotBeCalled:
        def __init__(self, *args, **kwargs):
            raise AssertionError("live-safe coach path should not open network sessions")

    monkeypatch.setattr(coach_fetcher.aiohttp, "ClientSession", _ShouldNotBeCalled)

    coach = await coach_fetcher.get_soccer_coach(
        "arsenal",
        "epl",
        db_path=db_path,
        live_safe=True,
    )

    assert coach == "Mikel Arteta"


@pytest.mark.asyncio
async def test_live_safe_context_read_survives_writer_lock(tmp_path, monkeypatch) -> None:
    db_path = str(tmp_path / "odds.db")
    _seed_context_tables(db_path)

    writer = sqlite3.connect(db_path, isolation_level=None)
    writer.execute(
        "INSERT INTO team_api_ids (team_name, sport, league, espn_id, espn_display_name, espn_slug) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("arsenal", "soccer", "epl", "42", "Arsenal", "arsenal"),
    )
    writer.execute(
        "INSERT INTO team_api_ids (team_name, sport, league, espn_id, espn_display_name, espn_slug) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("chelsea", "soccer", "epl", "43", "Chelsea", "chelsea"),
    )
    writer.execute("BEGIN IMMEDIATE")

    async def _fake_soccer_context(session, conn, home_team, away_team, league, config, **kwargs):
        home = conn.execute(
            "SELECT espn_id FROM team_api_ids WHERE team_name = ? AND league = ?",
            (home_team, league),
        ).fetchone()
        away = conn.execute(
            "SELECT espn_id FROM team_api_ids WHERE team_name = ? AND league = ?",
            (away_team, league),
        ).fetchone()
        return {
            "data_available": True,
            "sport": "soccer",
            "league": config["display_name"],
            "league_key": league,
            "home_team": {"name": "Arsenal", "league_position": 2, "form": "WWDWW", "espn_id": home["espn_id"]},
            "away_team": {"name": "Chelsea", "league_position": 4, "form": "WLWDW", "espn_id": away["espn_id"]},
        }

    monkeypatch.setattr(mcf, "_get_soccer_context", _fake_soccer_context)

    try:
        ctx = await mcf.get_match_context(
            "arsenal",
            "chelsea",
            "epl",
            live_safe=True,
            db_path=db_path,
        )
    finally:
        writer.execute("ROLLBACK")
        writer.close()

    assert ctx["data_available"] is True
    assert ctx["home_team"]["form"] == "WWDWW"
    assert ctx["away_team"]["league_position"] == 4
