"""Shared E2E fixtures with deterministic hot-tips data."""

from __future__ import annotations

import copy
import json
import sqlite3
import time
from pathlib import Path

import pytest


def pytest_configure(config) -> None:
    config.addinivalue_line(
        "markers",
        "no_test_edges: disable the deterministic hot-tips data fixture for this test",
    )


@pytest.fixture(scope="session")
def _test_edges_seed() -> list[dict]:
    path = Path(__file__).parent / "fixtures" / "test_edges.json"
    return json.loads(path.read_text())


@pytest.fixture
def test_edges(_test_edges_seed) -> list[dict]:
    return copy.deepcopy(_test_edges_seed)


@pytest.fixture(autouse=True)
def inject_test_edges(monkeypatch, request, test_edges, tmp_path) -> None:
    """Inject deterministic Hot Tips data for E2E callback paths."""
    import bot

    bot._hot_tips_cache.clear()
    bot._ht_tips_snapshot.clear()
    bot._ht_page_state.clear()
    bot._ht_detail_origin.clear()
    bot._odds_compare_origin.clear()

    monkeypatch.setattr(
        bot,
        "_get_broadcast_details",
        lambda **_: {
            "broadcast": "SuperSport PSL (DStv 202)",
            "kickoff": "Sat 29 Mar · 17:30",
        },
    )
    monkeypatch.setattr(bot, "_get_portfolio_line", lambda: "")
    monkeypatch.setattr(bot, "_founding_days_left", lambda: 8)

    if request.node.get_closest_marker("no_test_edges"):
        return

    db_path = tmp_path / "odds.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
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
                recommended_at TEXT NOT NULL,
                match_date TEXT NOT NULL,
                confirming_signals INTEGER,
                is_displayed_in_rollups INTEGER DEFAULT 1
            )
            """
        )
        for idx, edge in enumerate(test_edges):
            outcome = (edge.get("outcome") or "").strip().lower()
            home = (edge.get("home_team") or "").strip().lower()
            away = (edge.get("away_team") or "").strip().lower()
            if outcome == away:
                bet_type = "Away Win"
                outcome_key = "away"
            elif outcome == "draw":
                bet_type = "Draw"
                outcome_key = "draw"
            else:
                bet_type = "Home Win"
                outcome_key = "home"
            edge["edge_id"] = edge.get("edge_id") or f"e2e_edge_{idx}"
            edge["recommended_at"] = edge.get("recommended_at") or f"2026-03-01T00:{idx:02d}:00+00:00"
            edge["outcome_key"] = edge.get("outcome_key") or outcome_key
            conn.execute(
                """
                INSERT INTO edge_results (
                    edge_id, match_key, sport, league, edge_tier, composite_score,
                    bet_type, recommended_odds, bookmaker, predicted_ev, result,
                    recommended_at, match_date, confirming_signals, is_displayed_in_rollups
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, 1)
                """,
                (
                    edge["edge_id"],
                    edge["match_id"],
                    edge.get("sport_key", "soccer"),
                    edge.get("league_key", ""),
                    edge.get("display_tier", edge.get("edge_rating", "bronze")),
                    float(edge.get("edge_score") or 0),
                    bet_type,
                    float(edge.get("odds") or 0),
                    edge.get("bookmaker_key") or edge.get("bookmaker") or "",
                    float(edge.get("ev") or 0),
                    edge["recommended_at"],
                    str(edge["match_id"])[-10:],
                    int((edge.get("edge_v2") or {}).get("confirming_signals") or 0),
                ),
            )
        conn.commit()
    finally:
        conn.close()

    import scrapers.edge.edge_config as edge_config

    monkeypatch.setattr(edge_config, "DB_PATH", str(db_path))

    def _load(limit: int = 10) -> list[dict]:
        return copy.deepcopy(test_edges[: max(int(limit or 10), 1)])

    async def _fetch() -> list[dict]:
        return _load(len(test_edges))

    async def _proof() -> dict:
        return {
            "stats_7d": {
                "total": 12,
                "hits": 8,
                "misses": 4,
                "hit_rate": 8 / 12,
            },
            "roi_7d": 12.5,
            "last_10_results": [
                "hit",
                "miss",
                "hit",
                "hit",
                "miss",
                "hit",
                "hit",
                "hit",
                "miss",
                "hit",
            ],
            "recently_settled": [],
            "yesterday_results": [],
        }

    async def _summary(_days: int = 7) -> dict:
        return {"total": 12, "hits": 8, "hit_rate_pct": 67.0, "roi": 12.5}

    monkeypatch.setattr(bot, "_load_tips_from_edge_results", _load)
    monkeypatch.setattr(bot, "_fetch_hot_tips_from_db", _fetch)
    monkeypatch.setattr(bot, "_fetch_hot_tips_from_db_inner", _fetch)
    monkeypatch.setattr(bot, "_get_hot_tips_result_proof", _proof)
    monkeypatch.setattr(bot, "_get_edge_tracker_summary", _summary)

    bot._hot_tips_cache["global"] = {
        "tips": copy.deepcopy(test_edges),
        "ts": time.time(),
        "thin_slate": {"state": "none", "candidate_count": 0, "weaker_tip": None},
    }
