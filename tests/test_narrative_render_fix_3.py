from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

import bot
from scripts import pregenerate_narratives as pregen
from scrapers import match_context_fetcher as mcf


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


def _insert_cache_row(
    db_path: str,
    match_id: str,
    html: str,
    *,
    tips: list[dict] | None = None,
    evidence_json: str | None = None,
) -> None:
    conn = sqlite3.connect(db_path)
    now = datetime.now(timezone.utc)
    expires = now + timedelta(hours=6)
    conn.execute(
        "INSERT INTO narrative_cache "
        "(match_id, narrative_html, model, edge_tier, tips_json, odds_hash, evidence_json, created_at, expires_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            match_id,
            html,
            "sonnet",
            "bronze",  # gold+w82 hits WATERTIGHT-01 before banned-phrase check
            json.dumps(tips or [{"outcome": "home", "odds": 2.2, "ev": 4.1}]),
            "",
            evidence_json,
            now.isoformat(),
            expires.isoformat(),
        ),
    )
    conn.commit()
    conn.close()


def test_banned_phrases_include_stake_size_measured() -> None:
    assert "keeps the stake size measured" in bot.BANNED_NARRATIVE_PHRASES


@pytest.mark.asyncio
async def test_get_cached_narrative_rejects_stale_risk_filler(tmp_path) -> None:
    db_path = str(tmp_path / "test_odds.db")
    original = bot._NARRATIVE_DB_PATH
    bot._NARRATIVE_DB_PATH = db_path
    _init_cache_db(db_path)

    try:
        bot._ensure_narrative_cache_table()
        _insert_cache_row(
            db_path,
            "arsenal_vs_bournemouth_2026-04-11",
            "🎯 <b>Arsenal vs Bournemouth</b>\n\n"
            "📋 <b>The Setup</b>\n"
            "Arsenal look settled in this fixture.\n\n"
            "🎯 <b>The Edge</b>\nEdge text.\n\n"
            "⚠️ <b>The Risk</b>\n"
            "No specific flags on this one — clean risk profile, size normally. "
            "That keeps the stake size measured.\n\n"
            "🏆 <b>Verdict</b>\nBack Arsenal.",
        )

        cached = await bot._get_cached_narrative("arsenal_vs_bournemouth_2026-04-11")
        assert cached is None

        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT status FROM narrative_cache WHERE match_id = ?",
            ("arsenal_vs_bournemouth_2026-04-11",),
        ).fetchone()
        conn.close()
        # Rejected rows are quarantined (UPDATE), not deleted
        assert row is not None
        assert row[0] == "quarantined"
    finally:
        bot._NARRATIVE_DB_PATH = original


@pytest.mark.asyncio
async def test_get_cached_narrative_rejects_h2h_claim_in_risk_prose(tmp_path) -> None:
    db_path = str(tmp_path / "test_odds.db")
    original = bot._NARRATIVE_DB_PATH
    bot._NARRATIVE_DB_PATH = db_path
    _init_cache_db(db_path)

    try:
        bot._ensure_narrative_cache_table()
        _insert_cache_row(
            db_path,
            "crystal_palace_vs_newcastle_2026-04-11",
            "📋 <b>The Setup</b>\n"
            "Crystal Palace host Newcastle United.\n\n"
            "🎯 <b>The Edge</b>\nEdge text.\n\n"
            "⚠️ <b>The Risk</b>\n"
            "That head-to-head record of five straight draws is hard to ignore.\n\n"
            "🏆 <b>Verdict</b>\nBack Newcastle United.",
            tips=[
                {
                    "outcome": "away",
                    "odds": 2.51,
                    "ev": 1.6,
                    "edge_v2": {
                        "match_key": "crystal_palace_vs_newcastle_2026-04-11",
                        "league": "epl",
                        "signals": {
                            "form_h2h": {
                                "h2h_total": 5,
                                "h2h_a_wins": 1,
                                "h2h_b_wins": 3,
                                "h2h_draws": 1,
                            },
                        },
                    },
                }
            ],
        )

        cached = await bot._get_cached_narrative("crystal_palace_vs_newcastle_2026-04-11")
        assert cached is None
    finally:
        bot._NARRATIVE_DB_PATH = original


@pytest.mark.asyncio
async def test_get_cached_narrative_rejects_stale_setup_form_claims_when_context_metadata_is_old(tmp_path) -> None:
    db_path = str(tmp_path / "test_odds.db")
    original = bot._NARRATIVE_DB_PATH
    bot._NARRATIVE_DB_PATH = db_path
    _init_cache_db(db_path)

    try:
        bot._ensure_narrative_cache_table()
        evidence_json = json.dumps(
            {
                "espn_context": {
                    "data_available": True,
                    "provenance": {
                        "available": True,
                        "fetched_at": "2026-03-15T00:00:00+00:00",
                        "stale_minutes": 5 * 24 * 60,
                    },
                }
            }
        )
        _insert_cache_row(
            db_path,
            "arsenal_vs_bournemouth_2026-04-11",
            "📋 <b>The Setup</b>\n"
            "Arsenal have turned their ground into a fortress this season. Form reads WWWWD.\n\n"
            "🎯 <b>The Edge</b>\nEdge text.\n\n"
            "⚠️ <b>The Risk</b>\nRisk text.\n\n"
            "🏆 <b>Verdict</b>\nBack Arsenal.",
            evidence_json=evidence_json,
        )

        cached = await bot._get_cached_narrative("arsenal_vs_bournemouth_2026-04-11")
        assert cached is None
    finally:
        bot._NARRATIVE_DB_PATH = original


def test_extract_edge_data_normalises_match_key_team_names() -> None:
    tips = [
        {
            "outcome": "home",
            "odds": 2.2,
            "ev": 4.5,
            "prob": 48.0,
            "edge_v2": {
                "match_key": "kaizer_chiefs_vs_magesi_2026-03-20",
                "league": "psl",
                "confirming_signals": 2,
                "contradicting_signals": 0,
                "composite_score": 58,
                "signals": {},
            },
        }
    ]

    home_team, away_team = bot._extract_teams_from_tips(tips, "", "")
    edge_data = bot._extract_edge_data(tips, home_team, away_team)

    assert home_team == "Kaizer Chiefs"
    assert away_team == "Magesi"
    assert edge_data["home_team"] == "Kaizer Chiefs"
    assert edge_data["away_team"] == "Magesi"


@pytest.mark.asyncio
async def test_pregen_context_lift_retries_with_alternate_names(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    async def _fake_get_match_context(*, home_team: str, away_team: str, **kwargs):
        calls.append((home_team, away_team))
        if len(calls) == 1:
            return {
                "data_available": True,
                "home_team": {"name": "Benetton Rugby"},
                "away_team": {"name": "Ospreys Rugby"},
            }
        return {
            "data_available": True,
            "home_team": {"name": "Benetton Treviso", "league_position": 5, "form": "WWLWW"},
            "away_team": {"name": "Ospreys", "league_position": 9, "form": "LDWLW"},
        }

    monkeypatch.setattr(mcf, "get_match_context", _fake_get_match_context)
    # Bypass primary sport-specific fetcher (has its own cache) so the ESPN fallback runs.
    import fetchers as _fetchers_mod
    monkeypatch.setattr(_fetchers_mod, "get_fetcher", lambda sport: (_ for _ in ()).throw(ImportError("test bypass")))

    ctx = await pregen._get_match_context(
        "Benetton Rugby",
        "Ospreys Rugby",
        "urc",
        "rugby",
        home_key="benetton_treviso",
        away_key="ospreys",
    )

    assert calls == [
        ("benetton_treviso", "ospreys"),
        ("benetton_rugby", "ospreys_rugby"),
    ]
    assert ctx["home_team"]["league_position"] == 5
    assert ctx["away_team"]["form"] == "LDWLW"
