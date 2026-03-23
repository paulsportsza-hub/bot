from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import bot
import narrative_spec


def _setup_text(narrative: str) -> str:
    return bot._extract_setup_section(narrative)


def test_edge_only_section_setup_has_no_ev_or_probability_language() -> None:
    result = bot._build_edge_only_section(
        [{
            "ev": 7.5,
            "outcome": "Chelsea win",
            "odds": 2.80,
            "bookmaker": "WSB",
            "prob": 38,
            "edge_score": 55,
        }]
    )
    setup = _setup_text(result).lower()

    for banned in (
        "expected value",
        "fair probability",
        "fair value",
        "implied probability",
        "model ",
        "bookmaker",
        "odds",
        "wsb",
        "2.80",
    ):
        assert banned not in setup


def test_edge_only_section_empty_setup_has_no_odds_language() -> None:
    result = bot._build_edge_only_section([])
    setup = _setup_text(result).lower()

    assert "odds" not in setup
    assert "bookmaker" not in setup
    assert "price" not in setup


def test_match_shape_note_league_has_no_probability_language() -> None:
    text = narrative_spec._match_shape_note("league", "fixture").lower()

    assert "implied probability" not in text
    assert "model probability" not in text
    assert "market consensus" not in text


def test_cleanup_expired_narrative_cache_rows_deletes_only_expired(tmp_path) -> None:
    db_path = str(tmp_path / "test_odds.db")
    original = bot._NARRATIVE_DB_PATH
    bot._NARRATIVE_DB_PATH = db_path

    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS odds_latest (
            match_id TEXT, bookmaker TEXT, home_odds REAL,
            draw_odds REAL, away_odds REAL
        )"""
    )
    conn.commit()

    try:
        bot._ensure_narrative_cache_table()
        past = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        future = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        conn.execute(
            "INSERT INTO narrative_cache "
            "(match_id, narrative_html, model, edge_tier, tips_json, odds_hash, created_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("expired_match", "<b>expired</b>", "sonnet", "gold", "[]", "", past, past),
        )
        conn.execute(
            "INSERT INTO narrative_cache "
            "(match_id, narrative_html, model, edge_tier, tips_json, odds_hash, created_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("fresh_match", "<b>fresh</b>", "sonnet", "gold", "[]", "", future, future),
        )
        conn.commit()

        removed = bot._cleanup_expired_narrative_cache_rows()
        assert removed == 1

        rows = conn.execute("SELECT match_id FROM narrative_cache ORDER BY match_id").fetchall()
        assert rows == [("fresh_match",)]
    finally:
        conn.close()
        bot._NARRATIVE_DB_PATH = original
