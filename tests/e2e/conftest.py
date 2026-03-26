"""Shared E2E fixtures with deterministic hot-tips data."""

from __future__ import annotations

import copy
import json
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
def inject_test_edges(monkeypatch, request, test_edges) -> None:
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
