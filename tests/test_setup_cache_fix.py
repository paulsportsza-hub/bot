from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

import bot


def _init_cache_db(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS odds_latest (
            match_id TEXT, bookmaker TEXT, home_odds REAL,
            draw_odds REAL, away_odds REAL
        )"""
    )
    conn.commit()
    conn.close()


def _insert_cache_row(db_path: str, match_id: str, html: str, *, narrative_source: str = "w84") -> None:
    conn = sqlite3.connect(db_path)
    now = datetime.now(timezone.utc)
    expires = now + timedelta(hours=6)
    conn.execute(
        "INSERT INTO narrative_cache "
        "(match_id, narrative_html, model, edge_tier, tips_json, odds_hash, created_at, expires_at, narrative_source) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            match_id,
            html,
            "sonnet",
            "gold",
            json.dumps([{"outcome": "home", "odds": 2.8, "ev": 7.5}]),
            "",
            now.isoformat(),
            expires.isoformat(),
            narrative_source,
        ),
    )
    conn.commit()
    conn.close()


def test_find_stale_setup_patterns_flags_price_setup_copy() -> None:
    narrative = (
        "🎯 <b>Barcelona vs Atletico Madrid</b>\n\n"
        "📋 <b>The Setup</b>\n"
        "Barcelona vs Atletico Madrid in Champions League. "
        "The 1.62 on Barcelona win at PlayaBets (62% implied) looks generous when "
        "we're reading this closer to 75%, giving us a 21.8% expected value gap worth exploring.\n\n"
        "🎯 <b>The Edge</b>\nEdge text.\n\n"
        "⚠️ <b>The Risk</b>\nRisk text.\n\n"
        "🏆 <b>Verdict</b>\nBack Barcelona."
    )

    reasons = bot._find_stale_setup_patterns(narrative)

    assert "bookmaker_in_setup" in reasons
    assert "pricing_language_in_setup" in reasons
    assert "odds_in_setup" in reasons


def test_find_stale_setup_patterns_flags_apology_setup_copy() -> None:
    narrative = (
        "🎯 <b>Chelsea vs Manchester City</b>\n\n"
        "📋 <b>The Setup</b>\n"
        "Home side Chelsea line up with limited context available. "
        "Form (L-W-L-D-D) for what it's worth. "
        "Manchester City enter this fixture without a strong recent record to lean on.\n\n"
        "🎯 <b>The Edge</b>\nEdge text."
    )

    reasons = bot._find_stale_setup_patterns(narrative)

    assert reasons == ["apology_language_in_setup"]


def test_find_stale_setup_patterns_ignores_clean_setup_with_price_in_edge() -> None:
    narrative = (
        "🎯 <b>Brentford vs Wolves</b>\n\n"
        "📋 <b>The Setup</b>\n"
        "Brentford look like one of those sides you assess by the latest run rather than the badge. "
        "Form reads W-D-L-D-W — no clean trend in either direction.\n\n"
        "🎯 <b>The Edge</b>\n"
        "Betway's 2.80 on Brentford win offers 7.5% expected value against fair value.\n\n"
        "⚠️ <b>The Risk</b>\n"
        "Risk text.\n\n"
        "🏆 <b>Verdict</b>\n"
        "Back Brentford at 2.80 with Betway."
    )

    assert bot._find_stale_setup_patterns(narrative) == []


@pytest.mark.asyncio
async def test_get_cached_narrative_rejects_and_deletes_stale_setup_cache(tmp_path) -> None:
    db_path = str(tmp_path / "test_odds.db")
    original = bot._NARRATIVE_DB_PATH
    bot._NARRATIVE_DB_PATH = db_path
    _init_cache_db(db_path)

    try:
        bot._ensure_narrative_cache_table()
        _insert_cache_row(
            db_path,
            "barcelona_vs_atletico_madrid_2026-04-07",
            "🎯 <b>Barcelona vs Atletico Madrid</b>\n\n"
            "📋 <b>The Setup</b>\n"
            "The 1.62 on Barcelona win at PlayaBets (62% implied) creates a 21.8% expected value gap.\n\n"
            "🎯 <b>The Edge</b>\nEdge text.",
        )

        cached = await bot._get_cached_narrative("barcelona_vs_atletico_madrid_2026-04-07")
        assert cached is None

        conn = sqlite3.connect(db_path)
        count = conn.execute(
            "SELECT COUNT(*) FROM narrative_cache WHERE match_id = ?",
            ("barcelona_vs_atletico_madrid_2026-04-07",),
        ).fetchone()[0]
        conn.close()
        assert count == 0
    finally:
        bot._NARRATIVE_DB_PATH = original


def test_invalidate_stale_setup_cache_entries_deletes_only_matching_rows(tmp_path) -> None:
    db_path = str(tmp_path / "test_odds.db")
    original = bot._NARRATIVE_DB_PATH
    bot._NARRATIVE_DB_PATH = db_path
    _init_cache_db(db_path)

    try:
        bot._ensure_narrative_cache_table()
        _insert_cache_row(
            db_path,
            "chelsea_vs_manchester_city_2026-04-12",
            "🎯 <b>Chelsea vs Manchester City</b>\n\n"
            "📋 <b>The Setup</b>\n"
            "Home side Chelsea line up with limited context available. Form (L-W-L-D-D) for what it's worth.\n\n"
            "🎯 <b>The Edge</b>\nEdge text.",
        )
        _insert_cache_row(
            db_path,
            "arsenal_vs_bournemouth_2026-04-11",
            "🎯 <b>Arsenal vs Bournemouth</b>\n\n"
            "📋 <b>The Setup</b>\n"
            "Arsenal have turned home fixtures into routine pressure tests for visiting sides.\n\n"
            "🎯 <b>The Edge</b>\nBetway's 2.10 on Arsenal win offers 4.0% expected value.\n\n"
            "🏆 <b>Verdict</b>\nBack Arsenal at 2.10 with Betway.",
        )

        invalidated = bot._invalidate_stale_setup_cache_entries()
        assert invalidated == [
            {
                "match_id": "chelsea_vs_manchester_city_2026-04-12",
                "reasons": ["apology_language_in_setup"],
            }
        ]

        conn = sqlite3.connect(db_path)
        rows = conn.execute(
            "SELECT match_id FROM narrative_cache ORDER BY match_id"
        ).fetchall()
        conn.close()
        assert rows == [("arsenal_vs_bournemouth_2026-04-11",)]
    finally:
        bot._NARRATIVE_DB_PATH = original
