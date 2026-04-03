from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

import bot
from narrative_spec import build_narrative_spec, _render_baseline, NarrativeSpec, _render_risk


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


def _insert_cache_row(db_path: str, match_id: str, html: str) -> None:
    conn = sqlite3.connect(db_path)
    now = datetime.now(timezone.utc)
    expires = now + timedelta(hours=6)
    conn.execute(
        "INSERT INTO narrative_cache "
        "(match_id, narrative_html, model, edge_tier, tips_json, odds_hash, created_at, expires_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            match_id,
            html,
            "sonnet",
            "gold",
            json.dumps([{"outcome": "home", "odds": 1.62, "ev": 5.0}]),
            "",
            now.isoformat(),
            expires.isoformat(),
        ),
    )
    conn.commit()
    conn.close()


def test_banned_phrases_include_let_that_shape_the_stake() -> None:
    assert "let that shape the stake" in bot.BANNED_NARRATIVE_PHRASES


@pytest.mark.asyncio
async def test_get_cached_narrative_rejects_shape_the_stake_filler(tmp_path) -> None:
    db_path = str(tmp_path / "test_odds.db")
    original = bot._NARRATIVE_DB_PATH
    bot._NARRATIVE_DB_PATH = db_path
    _init_cache_db(db_path)

    try:
        bot._ensure_narrative_cache_table()
        _insert_cache_row(
            db_path,
            "golden_arrows_vs_stellenbosch_2026-03-21",
            "📋 <b>The Setup</b>\nGolden Arrows host Stellenbosch.\n\n"
            "🎯 <b>The Edge</b>\nEdge text.\n\n"
            "⚠️ <b>The Risk</b>\nNo specific flags on this one. Let that shape the stake.\n\n"
            "🏆 <b>Verdict</b>\nBack Golden Arrows.",
        )

        cached = await bot._get_cached_narrative("golden_arrows_vs_stellenbosch_2026-03-21")
        assert cached is None

        conn = sqlite3.connect(db_path)
        count = conn.execute(
            "SELECT COUNT(*) FROM narrative_cache WHERE match_id = ?",
            ("golden_arrows_vs_stellenbosch_2026-03-21",),
        ).fetchone()[0]
        conn.close()
        assert count == 0
    finally:
        bot._NARRATIVE_DB_PATH = original


def test_normalise_edge_pct_contract_prefers_percent_value_over_decimal_ev() -> None:
    assert bot._normalise_edge_pct_contract(0.05, 5.0) == 5.0
    assert bot._normalise_edge_pct_contract(0.09, 9.0) == 9.0
    assert bot._normalise_edge_pct_contract(4.2, 4.2) == 4.2


def test_extract_edge_data_repairs_decimal_ev_contract() -> None:
    tips = [
        {
            "outcome": "home",
            "odds": 1.62,
            "ev": 0.05,
            "prob": 62.0,
            "edge_v2": {
                "match_key": "kaizer_chiefs_vs_magesi_2026-03-20",
                "league": "psl",
                "edge_pct": 5.0,
                "confirming_signals": 2,
                "contradicting_signals": 0,
                "composite_score": 58,
                "signals": {},
            },
        }
    ]

    home_team, away_team = bot._extract_teams_from_tips(tips, "", "")
    edge_data = bot._extract_edge_data(tips, home_team, away_team)

    assert edge_data["edge_pct"] == 5.0


def test_build_narrative_spec_suppresses_recent_result_opponent_and_scoreline() -> None:
    ctx_data = {
        "data_available": True,
        "league": "Premiership (PSL)",
        "home_team": {
            "name": "Kaizer Chiefs",
            "position": 8,
            "points": 31,
            "form": "WLLLW",
            "last_5": [
                {"result": "W", "opponent": "Durban City", "score": "1-0", "home_away": "home"},
            ],
        },
        "away_team": {
            "name": "Magesi",
            "position": 11,
            "points": 27,
            "form": "DDLDD",
            "last_5": [
                {"result": "D", "opponent": "Orbit College", "score": "1-1", "home_away": "away"},
            ],
        },
    }
    edge_data = {
        "home_team": "Kaizer Chiefs",
        "away_team": "Magesi",
        "league": "psl",
        "best_bookmaker": "Betway",
        "best_odds": 1.62,
        "edge_pct": 5.0,
        "fair_prob": 0.62,
        "outcome": "home",
        "confirming_signals": 2,
        "contradicting_signals": 0,
        "composite_score": 58,
    }
    tips = [
        {
            "outcome": "home",
            "odds": 1.62,
            "ev": 5.0,
            "prob": 62.0,
            "edge_v2": {"match_key": "kaizer_chiefs_vs_magesi_2026-03-20", "league": "psl", "signals": {}},
        }
    ]

    spec = build_narrative_spec(ctx_data, edge_data, tips, "soccer")
    baseline = _render_baseline(spec)

    assert "Durban City" not in baseline
    assert "Orbit College" not in baseline
    assert "1-0" not in baseline
    assert "1-1" not in baseline
    assert "Kaizer Chiefs" in baseline
    assert "Magesi" in baseline


def test_build_narrative_spec_downgrades_stale_context_claims() -> None:
    ctx_data = {
        "data_available": True,
        "data_freshness": "2026-03-15T00:00:00+00:00",
        "league": "Premier League",
        "home_team": {
            "name": "Arsenal",
            "position": 2,
            "points": 61,
            "form": "WWWDL",
            "coach": "Mikel Arteta",
        },
        "away_team": {
            "name": "Bournemouth",
            "position": 12,
            "points": 39,
            "form": "LDWLW",
            "coach": "Andoni Iraola",
        },
    }
    edge_data = {
        "home_team": "Arsenal",
        "away_team": "Bournemouth",
        "league": "epl",
        "best_bookmaker": "Betway",
        "best_odds": 2.10,
        "edge_pct": 5.2,
        "fair_prob": 0.52,
        "outcome": "home",
        "confirming_signals": 2,
        "contradicting_signals": 0,
        "composite_score": 58,
    }
    tips = [
        {
            "outcome": "home",
            "odds": 2.10,
            "ev": 5.2,
            "prob": 52.0,
            "edge_v2": {"match_key": "arsenal_vs_bournemouth_2026-03-20", "league": "epl", "signals": {}},
        }
    ]

    spec = build_narrative_spec(ctx_data, edge_data, tips, "soccer")
    baseline = _render_baseline(spec)

    assert spec.context_is_fresh is False
    assert "fortress this season" not in baseline.lower()
    assert "form reads" not in baseline.lower()
    assert "61 points" not in baseline
    assert "mid-table" not in baseline.lower()


def test_build_narrative_spec_injects_static_coaches_when_context_is_missing() -> None:
    ctx_data = {
        "home_team": {"name": "Arsenal"},
        "away_team": {"name": "Bournemouth"},
    }
    edge_data = {
        "home_team": "Arsenal",
        "away_team": "Bournemouth",
        "league": "epl",
    }

    spec = build_narrative_spec(ctx_data, edge_data, [], "soccer")

    assert spec.home_coach == "Mikel Arteta"
    assert spec.away_coach == "Andoni Iraola"


def test_render_risk_drops_shape_the_stake_closer() -> None:
    spec = NarrativeSpec(
        home_name="Kaizer Chiefs",
        away_name="Magesi",
        competition="Premiership (PSL)",
        sport="soccer",
        home_story_type="neutral",
        away_story_type="neutral",
        risk_factors=["Away side faces home crowd disadvantage — factor that in."],
        risk_severity="moderate",
    )

    risk = _render_risk(spec)

    assert "let that shape the stake" not in risk.lower()
    assert "size this with normal discipline" not in risk.lower()
    assert "stake" not in risk.lower()
