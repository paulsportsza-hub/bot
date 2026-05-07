"""Contracts for display-scoped edge_results runtime rollups."""

from __future__ import annotations

import json
import sqlite3
import sys
import types
from datetime import date, timedelta
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
FUTURE_DATE = (date.today() + timedelta(days=2)).isoformat()


def _create_serving_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE edge_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            edge_id TEXT NOT NULL,
            match_key TEXT NOT NULL,
            sport TEXT NOT NULL,
            league TEXT NOT NULL,
            edge_tier TEXT NOT NULL,
            composite_score REAL NOT NULL,
            bet_type TEXT NOT NULL,
            recommended_odds REAL NOT NULL,
            bookmaker TEXT NOT NULL,
            predicted_ev REAL NOT NULL,
            result TEXT,
            match_score TEXT,
            actual_return REAL,
            recommended_at DATETIME NOT NULL,
            settled_at DATETIME,
            match_date DATE NOT NULL,
            confirming_signals INTEGER,
            is_displayed_in_rollups INTEGER
        );
        """
    )
    conn.executemany(
        """
        INSERT INTO edge_results (
            edge_id, match_key, sport, league, edge_tier, composite_score,
            bet_type, recommended_odds, bookmaker, predicted_ev, result,
            recommended_at, match_date, confirming_signals, is_displayed_in_rollups
        )
        VALUES (?, ?, 'soccer', 'epl', ?, ?, 'Home Win', 2.1, 'betway', 5.0,
                NULL, ?, ?, 3, ?)
        """,
        [
            (
                "displayed_alpha_old",
                f"alpha_vs_beta_{FUTURE_DATE}",
                "gold",
                50.0,
                "2026-05-01T10:00:00+00:00",
                FUTURE_DATE,
                1,
            ),
            (
                "hidden_alpha_new",
                f"alpha_vs_beta_{FUTURE_DATE}",
                "diamond",
                99.0,
                "2026-05-01T11:00:00+00:00",
                FUTURE_DATE,
                0,
            ),
            (
                "hidden_beta",
                f"gamma_vs_delta_{FUTURE_DATE}",
                "diamond",
                98.0,
                "2026-05-01T11:00:00+00:00",
                FUTURE_DATE,
                0,
            ),
            (
                "null_gamma",
                f"epsilon_vs_zeta_{FUTURE_DATE}",
                "diamond",
                97.0,
                "2026-05-01T11:00:00+00:00",
                FUTURE_DATE,
                None,
            ),
        ],
    )
    conn.commit()
    conn.close()


def _create_legacy_serving_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE edge_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            edge_id TEXT NOT NULL,
            match_key TEXT NOT NULL,
            sport TEXT NOT NULL,
            league TEXT NOT NULL,
            edge_tier TEXT NOT NULL,
            composite_score REAL NOT NULL,
            bet_type TEXT NOT NULL,
            recommended_odds REAL NOT NULL,
            bookmaker TEXT NOT NULL,
            predicted_ev REAL NOT NULL,
            result TEXT,
            recommended_at DATETIME NOT NULL,
            match_date DATE NOT NULL,
            confirming_signals INTEGER
        );
        """
    )
    conn.execute(
        """
        INSERT INTO edge_results (
            edge_id, match_key, sport, league, edge_tier, composite_score,
            bet_type, recommended_odds, bookmaker, predicted_ev, result,
            recommended_at, match_date, confirming_signals
        )
        VALUES (
            'legacy_alpha', ?, 'soccer', 'epl', 'gold', 55.0,
            'Home Win', 2.1, 'betway', 5.0, NULL,
            '2026-05-01T10:00:00+00:00', ?, 3
        )
        """,
        (f"legacy_vs_alpha_{FUTURE_DATE}", FUTURE_DATE),
    )
    conn.commit()
    conn.close()


def _create_digest_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE edge_results (
            result TEXT,
            recommended_odds REAL,
            settled_at TEXT,
            is_displayed_in_rollups INTEGER
        );
        """
    )
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    conn.executemany(
        """
        INSERT INTO edge_results (
            result, recommended_odds, settled_at, is_displayed_in_rollups
        )
        VALUES (?, ?, ?, ?)
        """,
        [
            ("hit", 2.0, f"{yesterday}T10:00:00", 1),
            ("miss", 9.0, f"{yesterday}T11:00:00", 0),
            ("hit", 99.0, f"{yesterday}T12:00:00", None),
        ],
    )
    conn.commit()
    conn.close()


def _create_legacy_digest_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE edge_results (
            result TEXT,
            recommended_odds REAL,
            settled_at TEXT
        );
        """
    )
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    conn.executemany(
        """
        INSERT INTO edge_results (result, recommended_odds, settled_at)
        VALUES (?, ?, ?)
        """,
        [
            ("hit", 2.0, f"{yesterday}T10:00:00"),
            ("miss", 2.0, f"{yesterday}T11:00:00"),
        ],
    )
    conn.commit()
    conn.close()


def test_load_tips_from_edge_results_uses_displayed_cohort_for_dedup(monkeypatch, tmp_path):
    import bot
    import scrapers.edge.edge_config as edge_config

    db_path = tmp_path / "odds.db"
    _create_serving_db(db_path)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO edge_results (
                edge_id, match_key, sport, league, edge_tier, composite_score,
                bet_type, recommended_odds, bookmaker, predicted_ev, result,
                recommended_at, match_date, confirming_signals, is_displayed_in_rollups
            )
            VALUES (
                'displayed_alias_home', ?, 'soccer', 'epl', 'gold', 49.0,
                '1', 2.1, 'betway', 5.0, NULL,
                '2026-05-01T10:00:00+00:00', ?, 3, 1
            )
            """,
            (f"alias_home_vs_beta_{FUTURE_DATE}", FUTURE_DATE),
        )
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr(edge_config, "DB_PATH", str(db_path))
    monkeypatch.setattr(edge_config, "MAX_PRODUCTION_EDGE_PCT", 30.0)
    monkeypatch.setattr(edge_config, "MAX_RECOMMENDED_ODDS", 50.0)

    tips = bot._load_tips_from_edge_results(limit=10, skip_punt_filter=True)

    assert [tip["match_id"] for tip in tips] == [
        f"alpha_vs_beta_{FUTURE_DATE}",
        f"alias_home_vs_beta_{FUTURE_DATE}",
    ]
    assert tips[0]["edge_id"] == "displayed_alpha_old"
    assert tips[0]["display_tier"] == "gold"
    assert tips[1]["outcome_key"] == "home"


def test_load_edge_tip_by_key_uses_displayed_cohort(monkeypatch, tmp_path):
    import bot
    import scrapers.edge.edge_config as edge_config

    db_path = tmp_path / "odds.db"
    _create_serving_db(db_path)

    monkeypatch.setattr(edge_config, "DB_PATH", str(db_path))

    tip = bot._load_edge_tip_by_key(f"alpha_vs_beta_{FUTURE_DATE}")

    assert tip is not None
    assert tip["edge_id"] == "displayed_alpha_old"
    assert tip["display_tier"] == "gold"


@pytest.mark.asyncio
async def test_detail_refresh_helpers_use_displayed_cohort(monkeypatch, tmp_path):
    import bot
    import scrapers.edge.edge_config as edge_config

    db_path = tmp_path / "odds.db"
    _create_serving_db(db_path)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "UPDATE edge_results SET recommended_at = datetime('now'), predicted_ev = 4.5 "
            "WHERE edge_id = 'displayed_alpha_old'"
        )
        conn.execute(
            "UPDATE edge_results SET recommended_at = datetime('now'), predicted_ev = 99.0 "
            "WHERE edge_id = 'hidden_alpha_new'"
        )
        conn.commit()
    finally:
        conn.close()

    edge_v2_mod = types.ModuleType("scrapers.edge.edge_v2_helper")

    def fail_live_calc(*args, **kwargs):
        raise RuntimeError("force stored fallback")

    edge_v2_mod.calculate_edge_v2 = fail_live_calc
    monkeypatch.setitem(sys.modules, "scrapers.edge.edge_v2_helper", edge_v2_mod)
    monkeypatch.setattr(edge_config, "DB_PATH", str(db_path))

    match_key = f"alpha_vs_beta_{FUTURE_DATE}"

    assert bot._get_fresh_tier_from_er(match_key) == "gold"
    assert bot._quick_edge_tier_lookup(match_key) == "gold"
    assert bot._quick_ev_lookup(match_key) == 4.5
    assert bot._blw_get_edge_id(match_key, str(db_path)) == "displayed_alpha_old"
    assert bot._enrich_edge_data_from_db(match_key, "Home Win")["composite_score"] == 50.0
    assert await bot._get_current_ev_for_match(match_key) == 4.5


@pytest.mark.asyncio
async def test_live_hot_tips_fallback_suppresses_hidden_edge_result_selection(
    monkeypatch, tmp_path
):
    import bot
    import scrapers.edge.edge_config as edge_config

    db_path = tmp_path / "odds.db"
    _create_serving_db(db_path)
    monkeypatch.setattr(edge_config, "DB_PATH", str(db_path))
    monkeypatch.setattr(edge_config, "MAX_PRODUCTION_EDGE_PCT", 30.0)
    monkeypatch.setattr(edge_config, "MAX_RECOMMENDED_ODDS", 50.0)
    monkeypatch.setattr(bot, "DB_LEAGUES", ("epl",))
    bot._hot_tips_cache.clear()

    services_mod = types.ModuleType("services")
    odds_service_mod = types.ModuleType("services.odds_service")
    odds_service_mod.LEAGUE_MARKET_TYPE = {"epl": "1x2"}
    monkeypatch.setitem(sys.modules, "services", services_mod)
    monkeypatch.setitem(sys.modules, "services.odds_service", odds_service_mod)

    edge_v2_mod = types.ModuleType("scrapers.edge.edge_v2_helper")
    edge_v2_mod.calculate_edge_v2 = lambda *args, **kwargs: {
        "tier": "gold",
        "composite_score": 60.0,
        "edge_pct": 5.0,
        "outcome": "home",
        "confidence": "medium",
        "best_bookmaker": "betway",
        "best_odds": 2.1,
        "fair_probability": 0.55,
    }
    monkeypatch.setitem(sys.modules, "scrapers.edge.edge_v2_helper", edge_v2_mod)

    card_pipeline_mod = types.ModuleType("card_pipeline")
    card_pipeline_mod.verify_card_populates = lambda tip, match_id: (True, [])
    card_pipeline_mod._log_card_population_failure = lambda *args, **kwargs: None
    monkeypatch.setitem(sys.modules, "card_pipeline", card_pipeline_mod)

    class FakeOddsService:
        async def get_all_matches(self, market_type="1x2", league="epl"):
            return [
                {
                    "match_id": f"gamma_vs_delta_{FUTURE_DATE}",
                    "home_team": "Gamma",
                    "away_team": "Delta",
                    "bookmaker_count": 2,
                    "last_updated": "2026-05-01T12:00:00+00:00",
                    "outcomes": {
                        "home": {
                            "all_bookmakers": {"betway": 2.1, "hollywoodbets": 2.0},
                            "best_odds": 2.1,
                            "best_bookmaker": "betway",
                        }
                    },
                }
            ]

    monkeypatch.setattr(bot, "odds_svc", FakeOddsService())

    tips = await bot._fetch_hot_tips_from_db_inner()

    assert tips == []


@pytest.mark.asyncio
async def test_live_hot_tips_fallback_filters_newly_logged_hidden_edge(
    monkeypatch, tmp_path
):
    import bot
    import scrapers.edge.edge_config as edge_config

    db_path = tmp_path / "odds.db"
    _create_serving_db(db_path)
    monkeypatch.setattr(edge_config, "DB_PATH", str(db_path))
    monkeypatch.setattr(edge_config, "MAX_PRODUCTION_EDGE_PCT", 30.0)
    monkeypatch.setattr(edge_config, "MAX_RECOMMENDED_ODDS", 50.0)
    monkeypatch.setattr(bot, "DB_LEAGUES", ("epl",))
    bot._hot_tips_cache.clear()

    services_mod = types.ModuleType("services")
    odds_service_mod = types.ModuleType("services.odds_service")
    odds_service_mod.LEAGUE_MARKET_TYPE = {"epl": "1x2"}
    monkeypatch.setitem(sys.modules, "services", services_mod)
    monkeypatch.setitem(sys.modules, "services.odds_service", odds_service_mod)

    match_key = f"theta_vs_iota_{FUTURE_DATE}"

    def fake_calculate_edge_v2(*args, **kwargs):
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                """
                INSERT INTO edge_results (
                    edge_id, match_key, sport, league, edge_tier, composite_score,
                    bet_type, recommended_odds, bookmaker, predicted_ev, result,
                    recommended_at, match_date, confirming_signals, is_displayed_in_rollups
                )
                VALUES (
                    'hidden_theta', ?, 'soccer', 'epl', 'gold', 60.0,
                    'Home Win', 2.1, 'betway', 5.0, NULL,
                    '2026-05-01T12:00:00+00:00', ?, 3, 0
                )
                """,
                (match_key, FUTURE_DATE),
            )
            conn.commit()
        finally:
            conn.close()
        return {
            "tier": "gold",
            "composite_score": 60.0,
            "edge_pct": 5.0,
            "outcome": "home",
            "confidence": "medium",
            "best_bookmaker": "betway",
            "best_odds": 2.1,
            "fair_probability": 0.55,
        }

    edge_v2_mod = types.ModuleType("scrapers.edge.edge_v2_helper")
    edge_v2_mod.calculate_edge_v2 = fake_calculate_edge_v2
    monkeypatch.setitem(sys.modules, "scrapers.edge.edge_v2_helper", edge_v2_mod)

    card_pipeline_mod = types.ModuleType("card_pipeline")
    card_pipeline_mod.verify_card_populates = lambda tip, match_id: (True, [])
    card_pipeline_mod._log_card_population_failure = lambda *args, **kwargs: None
    monkeypatch.setitem(sys.modules, "card_pipeline", card_pipeline_mod)

    class FakeOddsService:
        async def get_all_matches(self, market_type="1x2", league="epl"):
            return [
                {
                    "match_id": match_key,
                    "home_team": "Theta",
                    "away_team": "Iota",
                    "bookmaker_count": 2,
                    "last_updated": "2026-05-01T12:00:00+00:00",
                    "outcomes": {
                        "home": {
                            "all_bookmakers": {"betway": 2.1, "hollywoodbets": 2.0},
                            "best_odds": 2.1,
                            "best_bookmaker": "betway",
                        }
                    },
                }
            ]

    monkeypatch.setattr(bot, "odds_svc", FakeOddsService())

    tips = await bot._fetch_hot_tips_from_db_inner()

    assert tips == []


def test_hot_tips_cache_revalidates_display_flags(monkeypatch, tmp_path):
    import bot
    import scrapers.edge.edge_config as edge_config

    db_path = tmp_path / "odds.db"
    _create_serving_db(db_path)
    monkeypatch.setattr(edge_config, "DB_PATH", str(db_path))

    cached = [
        {
            "match_id": f"alpha_vs_beta_{FUTURE_DATE}",
            "outcome_key": "home",
            "edge_id": "displayed_alpha_old",
            "recommended_at": "2026-05-01T10:00:00+00:00",
        },
        {
            "match_id": f"gamma_vs_delta_{FUTURE_DATE}",
            "outcome_key": "1",
            "edge_id": "hidden_beta",
        },
        {"match_id": f"orphan_vs_edge_{FUTURE_DATE}", "outcome_key": "home"},
        {
            "match_id": f"alpha_vs_beta_{FUTURE_DATE}",
            "outcome_key": "home",
            "edge_id": "hidden_alpha_new",
            "recommended_at": "2026-05-01T11:00:00+00:00",
        },
    ]

    filtered = bot._filter_cached_hot_tips_by_display_flags(cached)

    assert filtered == [cached[0]]
    assert bot._cached_tip_has_displayed_rollup(cached[0])
    assert not bot._cached_tip_has_displayed_rollup(cached[1])
    assert not bot._cached_tip_has_displayed_rollup(cached[2])
    assert not bot._cached_tip_has_displayed_rollup(cached[3])


def test_hot_tips_cache_revalidation_drops_settled_exact_edge_id(monkeypatch, tmp_path):
    import bot
    import scrapers.edge.edge_config as edge_config

    db_path = tmp_path / "odds.db"
    _create_serving_db(db_path)
    monkeypatch.setattr(edge_config, "DB_PATH", str(db_path))
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "UPDATE edge_results SET result = 'hit' WHERE edge_id = 'displayed_alpha_old'"
        )
        conn.commit()
    finally:
        conn.close()

    cached_tip = {
        "match_id": f"alpha_vs_beta_{FUTURE_DATE}",
        "outcome_key": "home",
        "edge_id": "displayed_alpha_old",
        "recommended_at": "2026-05-01T10:00:00+00:00",
    }

    assert bot._filter_cached_hot_tips_by_display_flags([cached_tip]) == []
    assert not bot._cached_tip_has_displayed_rollup(cached_tip)


def test_my_matches_edge_info_revalidates_hot_tips_cache(monkeypatch, tmp_path):
    import bot
    import scrapers.edge.edge_config as edge_config

    db_path = tmp_path / "odds.db"
    _create_serving_db(db_path)
    monkeypatch.setattr(edge_config, "DB_PATH", str(db_path))

    displayed_tip = {
        "match_id": f"alpha_vs_beta_{FUTURE_DATE}",
        "outcome_key": "home",
        "edge_id": "displayed_alpha_old",
        "recommended_at": "2026-05-01T10:00:00+00:00",
        "home_team": "Alpha",
        "away_team": "Beta",
        "display_tier": "gold",
        "edge_v2": {"tier": "gold", "signals": {}},
    }
    hidden_tip = {
        "match_id": f"gamma_vs_delta_{FUTURE_DATE}",
        "outcome_key": "home",
        "edge_id": "hidden_beta",
        "home_team": "Gamma",
        "away_team": "Delta",
        "display_tier": "diamond",
        "edge_v2": {"tier": "diamond", "signals": {}},
    }
    monkeypatch.setattr(
        bot,
        "_hot_tips_cache",
        {"global": {"tips": [displayed_tip, hidden_tip], "ts": 1.0}},
    )

    edge_info = bot._get_edge_info_for_games(
        [
            {"id": "shown", "home_team": "Alpha", "away_team": "Beta"},
            {"id": "hidden", "home_team": "Gamma", "away_team": "Delta"},
        ]
    )

    assert list(edge_info) == ["shown"]
    assert edge_info["shown"]["tip"] == displayed_tip


def test_hot_tips_cache_revalidation_fails_closed_on_visibility_lookup_error(
    monkeypatch, tmp_path
):
    import bot
    import scrapers.edge.edge_config as edge_config

    db_path = tmp_path / "odds.db"
    _create_serving_db(db_path)
    monkeypatch.setattr(edge_config, "DB_PATH", str(db_path))
    monkeypatch.setattr(bot, "_edge_results_selection_visibility", lambda *_args, **_kwargs: None)
    cached_tip = {
        "match_id": f"alpha_vs_beta_{FUTURE_DATE}",
        "outcome_key": "home",
    }

    assert bot._filter_cached_hot_tips_by_display_flags([cached_tip]) == []
    with pytest.raises(RuntimeError):
        bot._filter_cached_hot_tips_by_display_flags(
            [cached_tip],
            raise_on_error=True,
        )


@pytest.mark.asyncio
async def test_game_analysis_cache_revalidation_prunes_hidden_tips(monkeypatch, tmp_path):
    import bot
    import scrapers.edge.edge_config as edge_config

    db_path = tmp_path / "odds.db"
    _create_serving_db(db_path)
    monkeypatch.setattr(edge_config, "DB_PATH", str(db_path))

    hidden_tip = {
        "match_id": f"gamma_vs_delta_{FUTURE_DATE}",
        "outcome_key": "home",
        "edge_id": "hidden_beta",
        "home_team": "Gamma",
        "away_team": "Delta",
    }
    monkeypatch.setattr(bot, "_game_tips_cache", {"hidden-event": [hidden_tip]})
    monkeypatch.setattr(
        bot,
        "_analysis_cache",
        {"hidden-event": ("cached html", [hidden_tip], "diamond", "w82", 1.0)},
    )

    visible = await bot._revalidate_game_tips_for_display(
        "hidden-event",
        [hidden_tip],
        match_key=f"gamma_vs_delta_{FUTURE_DATE}",
        context="test",
    )

    assert visible == []
    assert "hidden-event" not in bot._game_tips_cache
    assert "hidden-event" not in bot._analysis_cache


@pytest.mark.asyncio
async def test_game_tip_revalidation_uses_canonical_match_key_for_external_event_id(
    monkeypatch,
    tmp_path,
):
    import bot
    import scrapers.edge.edge_config as edge_config

    db_path = tmp_path / "odds.db"
    _create_serving_db(db_path)
    monkeypatch.setattr(edge_config, "DB_PATH", str(db_path))
    match_key = f"alpha_vs_beta_{FUTURE_DATE}"
    tip = {
        "event_id": "odds-api-event-id",
        "outcome_key": "home",
        "home_team": "Alpha",
        "away_team": "Beta",
    }

    visible = await bot._revalidate_game_tips_for_display(
        "odds-api-event-id",
        [tip],
        match_key=match_key,
        context="test",
    )

    assert visible
    assert visible[0]["match_id"] == match_key
    assert visible[0]["match_key"] == match_key


def test_edge_result_bet_type_normalisation_maps_1x2_aliases():
    import bot

    assert bot._normalise_edge_result_bet_type("1") == "home"
    assert bot._normalise_edge_result_bet_type("2") == "away"
    assert bot._normalise_edge_result_bet_type("X") == "draw"


def test_display_filter_fails_closed_on_schema_introspection_error():
    import bot
    import card_generator
    import edge_detail_renderer
    import evidence_pack

    class BrokenConn:
        def execute(self, *_args, **_kwargs):
            raise sqlite3.OperationalError("schema busy")

    assert bot._edge_results_display_filter(BrokenConn()) == "AND 0 = 1"
    assert edge_detail_renderer._edge_results_display_filter(BrokenConn()) == "AND 0 = 1"
    assert card_generator._edge_results_display_filter(BrokenConn()) == "AND 0 = 1"
    assert evidence_pack._edge_results_display_filter(BrokenConn()) == "AND 0 = 1"


def test_hot_tips_revalidation_distinguishes_schema_failure(monkeypatch, tmp_path):
    import bot
    import scrapers.edge.edge_config as edge_config

    db_path = tmp_path / "odds.db"
    _create_serving_db(db_path)
    monkeypatch.setattr(edge_config, "DB_PATH", str(db_path))
    monkeypatch.setattr(bot, "_edge_results_display_filter", lambda _conn, alias="": "AND 0 = 1")
    tip = {"match_id": f"alpha_vs_beta_{FUTURE_DATE}", "outcome_key": "home"}

    assert bot._filter_cached_hot_tips_by_display_flags([tip]) == []
    with pytest.raises(RuntimeError):
        bot._filter_cached_hot_tips_by_display_flags([tip], raise_on_error=True)


@pytest.mark.asyncio
async def test_hot_tips_async_revalidation_fails_closed_on_schema_failure(monkeypatch, tmp_path):
    import bot
    import scrapers.edge.edge_config as edge_config

    db_path = tmp_path / "odds.db"
    _create_serving_db(db_path)
    monkeypatch.setattr(edge_config, "DB_PATH", str(db_path))
    monkeypatch.setattr(bot, "_edge_results_display_filter", lambda _conn, alias="": "AND 0 = 1")
    tip = {"match_id": f"alpha_vs_beta_{FUTURE_DATE}", "outcome_key": "home"}

    assert await bot._revalidate_hot_tips_for_display([tip]) == []
    with pytest.raises(RuntimeError):
        await bot._revalidate_hot_tips_for_display([tip], raise_on_error=True)


def test_selection_visibility_uses_displayed_cohort_when_newer_row_hidden(tmp_path):
    import bot

    db_path = tmp_path / "odds.db"
    _create_serving_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = lambda cur, row: dict(zip([c[0] for c in cur.description], row))
    try:
        visibility = bot._edge_results_selection_visibility(conn, FUTURE_DATE)
    finally:
        conn.close()

    assert visibility[(f"alpha_vs_beta_{FUTURE_DATE}", "home")]
    assert not visibility[(f"gamma_vs_delta_{FUTURE_DATE}", "home")]


@pytest.mark.asyncio
async def test_odds_api_fallback_suppressed_when_display_scope_active(monkeypatch):
    import bot

    monkeypatch.setattr(bot, "_edge_results_display_scope_active", lambda: True)

    assert await bot._fetch_hot_tips_all_sports() == []


def test_edge_detail_runtime_readers_use_displayed_cohort(monkeypatch, tmp_path):
    import bot
    import edge_detail_renderer
    import scrapers.edge.edge_config as edge_config

    db_path = tmp_path / "odds.db"
    _create_serving_db(db_path)
    monkeypatch.setattr(edge_config, "DB_PATH", str(db_path))
    mixed_match = f"theta_vs_iota_{FUTURE_DATE}"
    conn = sqlite3.connect(db_path)
    try:
        conn.executemany(
            """
            INSERT INTO edge_results (
                edge_id, match_key, sport, league, edge_tier, composite_score,
                bet_type, recommended_odds, bookmaker, predicted_ev, result,
                recommended_at, match_date, confirming_signals, is_displayed_in_rollups
            )
            VALUES (?, ?, 'soccer', 'epl', ?, ?, ?, 2.1, 'betway', 5.0,
                    NULL, ?, ?, 3, ?)
            """,
            [
                (
                    "hidden_mixed_home",
                    mixed_match,
                    "diamond",
                    99.0,
                    "Home Win",
                    "2026-05-01T11:00:00+00:00",
                    FUTURE_DATE,
                    0,
                ),
                (
                    "displayed_mixed_away",
                    mixed_match,
                    "gold",
                    50.0,
                    "Away Win",
                    "2026-05-01T10:00:00+00:00",
                    FUTURE_DATE,
                    1,
                ),
                (
                    "displayed_alias_home",
                    f"alias_home_vs_beta_{FUTURE_DATE}",
                    "gold",
                    51.0,
                    "home",
                    "2026-05-01T10:00:00+00:00",
                    FUTURE_DATE,
                    1,
                ),
                (
                    "displayed_alias_numeric_home",
                    f"alias_one_vs_beta_{FUTURE_DATE}",
                    "gold",
                    52.0,
                    "1",
                    "2026-05-01T10:00:00+00:00",
                    FUTURE_DATE,
                    1,
                ),
            ],
        )
        conn.commit()
    finally:
        conn.close()

    displayed = edge_detail_renderer._load_edge_result(
        f"alpha_vs_beta_{FUTURE_DATE}",
        "home",
    )
    hidden = edge_detail_renderer._load_edge_result(
        f"gamma_vs_delta_{FUTURE_DATE}",
        "home",
    )

    assert displayed is not None
    assert displayed["edge_tier"] == "gold"
    assert hidden is None
    assert edge_detail_renderer._load_edge_result(
        f"alias_home_vs_beta_{FUTURE_DATE}",
        "home",
    )["bet_type"] == "home"
    assert edge_detail_renderer._load_edge_result(
        f"alias_one_vs_beta_{FUTURE_DATE}",
        "home",
    )["bet_type"] == "1"
    assert edge_detail_renderer._resolve_outcome("1", "Alias One", "Beta") == (
        "home",
        "Alias One",
    )
    assert edge_detail_renderer._resolve_outcome("away win", "Alias One", "Beta") == (
        "away",
        "Beta",
    )
    assert edge_detail_renderer._load_edge_result(mixed_match, "home") is None
    assert edge_detail_renderer._load_edge_result(mixed_match)["bet_type"] == "Away Win"
    stale_tip_html = edge_detail_renderer.render_edge_detail(
        mixed_match,
        "diamond",
        tip_data={
            "match_key": mixed_match,
            "outcome_key": "home",
            "home_team": "Theta",
            "away_team": "Iota",
            "edge_tier": "diamond",
            "display_tier": "diamond",
            "ev": 5.0,
            "recommended_odds": 2.1,
            "bookmaker": "betway",
            "league": "epl",
            "edge_id": "hidden_mixed_home",
        },
    )
    assert "No current edge data" in stale_tip_html
    assert bot._edge_result_has_displayed_rollup(f"alpha_vs_beta_{FUTURE_DATE}")
    assert not bot._edge_result_has_displayed_rollup(f"gamma_vs_delta_{FUTURE_DATE}")


def test_pre_match_alert_revalidation_uses_display_flag(monkeypatch, tmp_path):
    import bot
    import scrapers.edge.edge_config as edge_config

    db_path = tmp_path / "odds.db"
    _create_serving_db(db_path)
    monkeypatch.setattr(edge_config, "DB_PATH", str(db_path))

    assert bot._pre_match_edge_still_displayed(
        {"edge_id": "displayed_alpha_old", "match_key": f"alpha_vs_beta_{FUTURE_DATE}"},
        FUTURE_DATE,
    )
    assert not bot._pre_match_edge_still_displayed(
        {"edge_id": "hidden_beta", "match_key": f"gamma_vs_delta_{FUTURE_DATE}"},
        FUTURE_DATE,
    )


def test_tier_fire_schema_does_not_create_display_column(tmp_path):
    import bot

    db_path = tmp_path / "odds.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("CREATE TABLE edge_results (edge_id TEXT)")
        conn.commit()
    finally:
        conn.close()

    bot._ensure_tier_fire_alerts_schema(str(db_path))

    conn = sqlite3.connect(db_path)
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(edge_results)")}
    finally:
        conn.close()

    assert "posted_to_alerts_direct_claimed_at" in cols
    assert "posted_to_alerts_direct_claim_id" in cols
    assert "is_displayed_in_rollups" not in cols


def test_load_welcome_pick_sidecar_uses_displayed_cohort(monkeypatch, tmp_path):
    import bot
    import scrapers.edge.edge_config as edge_config

    db_path = tmp_path / "odds.db"
    _create_serving_db(db_path)
    sidecar = tmp_path / "welcome_pick.json"
    sidecar.write_text(
        json.dumps(
            {
                "match_key": f"gamma_vs_delta_{FUTURE_DATE}",
                "edge_tier": "diamond",
                "confirming_signals": 3,
                "composite_score": 98.0,
            }
        )
    )

    monkeypatch.setattr(edge_config, "DB_PATH", str(db_path))
    monkeypatch.setattr(bot, "_WELCOME_PICK_JSON", sidecar)
    monkeypatch.setattr(bot, "_welcome_pick_cache", None)
    monkeypatch.setattr(bot, "_welcome_pick_ts", 0.0)

    assert bot._load_welcome_pick() is None


def test_load_welcome_pick_sidecar_allows_displayed_pick(monkeypatch, tmp_path):
    import bot
    import scrapers.edge.edge_config as edge_config

    db_path = tmp_path / "odds.db"
    _create_serving_db(db_path)
    sidecar = tmp_path / "welcome_pick.json"
    sidecar.write_text(
        json.dumps(
            {
                "match_key": f"alpha_vs_beta_{FUTURE_DATE}",
                "edge_tier": "gold",
                "confirming_signals": 3,
                "composite_score": 50.0,
            }
        )
    )

    monkeypatch.setattr(edge_config, "DB_PATH", str(db_path))
    monkeypatch.setattr(bot, "_WELCOME_PICK_JSON", sidecar)
    monkeypatch.setattr(bot, "_welcome_pick_cache", None)
    monkeypatch.setattr(bot, "_welcome_pick_ts", 0.0)

    pick = bot._load_welcome_pick()

    assert pick is not None
    assert pick["match_key"] == f"alpha_vs_beta_{FUTURE_DATE}"


def test_load_welcome_pick_cache_revalidates_display_flag(monkeypatch, tmp_path):
    import bot
    import scrapers.edge.edge_config as edge_config

    db_path = tmp_path / "odds.db"
    _create_serving_db(db_path)
    sidecar = tmp_path / "welcome_pick.json"
    sidecar.write_text(
        json.dumps(
            {
                "match_key": f"alpha_vs_beta_{FUTURE_DATE}",
                "edge_tier": "gold",
                "confirming_signals": 3,
                "composite_score": 50.0,
            }
        )
    )

    monkeypatch.setattr(edge_config, "DB_PATH", str(db_path))
    monkeypatch.setattr(bot, "_WELCOME_PICK_JSON", sidecar)
    monkeypatch.setattr(bot, "_welcome_pick_cache", None)
    monkeypatch.setattr(bot, "_welcome_pick_ts", 0.0)

    assert bot._load_welcome_pick() is not None

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "UPDATE edge_results SET is_displayed_in_rollups = 0 "
            "WHERE edge_id = 'displayed_alpha_old'"
        )
        conn.commit()
    finally:
        conn.close()

    assert bot._load_welcome_pick() is None


def test_load_welcome_pick_does_not_return_expired_cache_on_db_failure(monkeypatch, tmp_path):
    import bot
    import scrapers.db_connect as db_connect
    import scrapers.edge.edge_config as edge_config

    db_path = tmp_path / "odds.db"
    monkeypatch.setattr(edge_config, "DB_PATH", str(db_path))
    monkeypatch.setattr(bot, "_WELCOME_PICK_JSON", tmp_path / "missing_welcome_pick.json")
    monkeypatch.setattr(
        bot,
        "_welcome_pick_cache",
        {"match_key": f"gamma_vs_delta_{FUTURE_DATE}", "edge_tier": "diamond"},
    )
    monkeypatch.setattr(bot, "_welcome_pick_ts", 1.0)

    def _locked(_path):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(db_connect, "connect_odds_db", _locked)

    assert bot._load_welcome_pick() is None


def test_load_tips_from_edge_results_tolerates_legacy_schema(monkeypatch, tmp_path):
    import bot
    import scrapers.edge.edge_config as edge_config

    db_path = tmp_path / "odds.db"
    _create_legacy_serving_db(db_path)

    monkeypatch.setattr(edge_config, "DB_PATH", str(db_path))
    monkeypatch.setattr(edge_config, "MAX_PRODUCTION_EDGE_PCT", 30.0)
    monkeypatch.setattr(edge_config, "MAX_RECOMMENDED_ODDS", 50.0)

    tips = bot._load_tips_from_edge_results(limit=10, skip_punt_filter=True)

    assert [tip["edge_id"] for tip in tips] == ["legacy_alpha"]


def test_displayed_rollup_gate_checks_legacy_row_existence(monkeypatch, tmp_path):
    import bot
    import scrapers.edge.edge_config as edge_config

    db_path = tmp_path / "odds.db"
    _create_legacy_serving_db(db_path)
    monkeypatch.setattr(edge_config, "DB_PATH", str(db_path))

    assert bot._edge_result_has_displayed_rollup(f"legacy_vs_alpha_{FUTURE_DATE}")
    assert not bot._edge_result_has_displayed_rollup(f"missing_vs_edge_{FUTURE_DATE}")


def test_compute_digest_stats_excludes_hidden_and_null_rollup_rows(
    monkeypatch, tmp_path
):
    import card_generator

    bot_root = tmp_path / "bot"
    scrapers_root = tmp_path / "scrapers"
    bot_root.mkdir()
    scrapers_root.mkdir()
    db_path = scrapers_root / "odds.db"
    _create_digest_db(db_path)

    scrapers_mod = types.ModuleType("scrapers")
    scrapers_mod.__path__ = []
    db_connect_mod = types.ModuleType("scrapers.db_connect")
    db_connect_mod.connect_odds_db_readonly = (
        lambda path, timeout=2.0: sqlite3.connect(path)
    )
    monkeypatch.setitem(sys.modules, "scrapers", scrapers_mod)
    monkeypatch.setitem(sys.modules, "scrapers.db_connect", db_connect_mod)
    monkeypatch.setattr(card_generator, "__file__", str(bot_root / "card_generator.py"))

    assert card_generator.compute_digest_stats() == {
        "last_10": "1-0",
        "roi_7d": "+100.0%",
        "yesterday": "1-0",
    }


def test_compute_digest_stats_tolerates_legacy_schema(monkeypatch, tmp_path):
    import card_generator

    bot_root = tmp_path / "bot"
    scrapers_root = tmp_path / "scrapers"
    bot_root.mkdir()
    scrapers_root.mkdir()
    db_path = scrapers_root / "odds.db"
    _create_legacy_digest_db(db_path)

    scrapers_mod = types.ModuleType("scrapers")
    scrapers_mod.__path__ = []
    db_connect_mod = types.ModuleType("scrapers.db_connect")
    db_connect_mod.connect_odds_db_readonly = (
        lambda path, timeout=2.0: sqlite3.connect(path)
    )
    monkeypatch.setitem(sys.modules, "scrapers", scrapers_mod)
    monkeypatch.setitem(sys.modules, "scrapers.db_connect", db_connect_mod)
    monkeypatch.setattr(card_generator, "__file__", str(bot_root / "card_generator.py"))

    assert card_generator.compute_digest_stats() == {
        "last_10": "1-1",
        "roi_7d": "+0.0%",
        "yesterday": "1-1",
    }


def test_runtime_rollup_queries_carry_display_filter_contract():
    bot_source = (REPO_ROOT / "bot.py").read_text(encoding="utf-8")
    dashboard_source = (REPO_ROOT / "dashboard" / "health_dashboard.py").read_text(
        encoding="utf-8"
    )
    evidence_source = (REPO_ROOT / "evidence_pack.py").read_text(encoding="utf-8")
    card_source = (REPO_ROOT / "card_generator.py").read_text(encoding="utf-8")
    reel_source = (REPO_ROOT / "scripts" / "reel_cards" / "reel_generator.py").read_text(
        encoding="utf-8"
    )

    assert bot_source.count("_edge_results_display_filter(") >= 10
    assert "WHERE match_key = ? " in bot_source
    assert bot_source.count("PRAGMA table_info(edge_results)") >= 2
    assert bot_source.count("COALESCE(is_displayed_in_rollups, 0) = 1") >= 2
    assert "ADD COLUMN is_displayed_in_rollups INTEGER DEFAULT 1" not in bot_source
    assert "ADD COLUMN is_displayed_in_rollups" not in bot_source
    assert "_filter_cached_hot_tips_by_display_flags" in bot_source
    assert "_cached_tip_has_displayed_rollup" in bot_source
    assert "async def _revalidate_hot_tips_for_display" in bot_source
    assert "async def _revalidate_game_tips_for_display" in bot_source
    assert "cached_visible_tips = await _revalidate_game_tips_for_display" in bot_source
    assert "_ea_visible_tips = await _revalidate_game_tips_for_display" in bot_source
    assert "_pre_visible_tips = await _revalidate_game_tips_for_display" in bot_source
    assert "_cached_visible_tips = await _revalidate_game_tips_for_display" in bot_source
    assert bot_source.count("_revalidate_hot_tips_for_display(") >= 8
    assert "if not tips:\n        # Cold path: load from DB when no cache exists" in bot_source
    assert "_card_tip and not await asyncio.to_thread(" in bot_source
    assert "_oc_revalidation_failed" in bot_source
    assert "elif not _oc_revalidation_failed" in bot_source
    assert 'return "AND 0 = 1"' in bot_source
    assert "raise_on_error=True" in bot_source
    assert "Warm hot tips display revalidation failed; preserving cache" in bot_source
    assert "_edge_results_display_scope_active" in bot_source
    assert "SELECT 1 FROM edge_results WHERE match_key = ? LIMIT 1" in bot_source
    assert "edge_results_display_filter(conn" in dashboard_source
    assert "COALESCE({prefix}is_displayed_in_rollups, 0) = 1" in dashboard_source
    assert "def _edge_results_display_filter(conn)" in evidence_source
    assert "def _edge_results_display_filter(conn)" in card_source
    assert "_edge_results_display_filter(conn, \"e\")" in reel_source
    assert "{display_filter}" in reel_source
