from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

import config
from scripts import picks_engine


_SAMPLE_EVENT = {
    "id": "event-1",
    "home_team": "Arsenal",
    "away_team": "Chelsea",
    "commence_time": "2026-03-25T18:00:00Z",
    "bookmakers": [
        {
            "key": "pinnacle",
            "title": "Pinnacle",
            "markets": [
                {
                    "key": "h2h",
                    "outcomes": [
                        {"name": "Arsenal", "price": 2.0},
                        {"name": "Chelsea", "price": 3.5},
                        {"name": "Draw", "price": 3.3},
                    ],
                }
            ],
        },
        {
            "key": "betway",
            "title": "Betway",
            "markets": [
                {
                    "key": "h2h",
                    "outcomes": [
                        {"name": "Arsenal", "price": 2.2},
                        {"name": "Chelsea", "price": 3.0},
                        {"name": "Draw", "price": 3.0},
                    ],
                }
            ],
        },
    ],
}


@pytest.mark.asyncio
async def test_get_picks_uses_calibrated_default_bankroll() -> None:
    with patch.dict(config.SPORTS_MAP, {"test_league": "soccer_test"}, clear=False), \
         patch.dict(config.LEAGUE_SPORT, {"test_league": "soccer"}, clear=False), \
         patch("scripts.picks_engine.fetch_odds_cached", new=AsyncMock(return_value={"ok": True, "data": [_SAMPLE_EVENT]})), \
         patch("scripts.picks_engine.get_quota", return_value={"requests_remaining": 88}):
        result = await picks_engine.get_picks_for_user(
            league_keys=["test_league"],
            risk_profile="moderate",
            bankroll=None,
        )

    assert result["ok"] is True
    assert result["picks"]
    assert result["picks"][0]["stake"] == pytest.approx(41.67, abs=0.01)
    assert picks_engine.BANKROLL_DEFAULT == config.DEFAULT_BANKROLL == 1000.0


def test_calculate_capped_stake_respects_profile_cap() -> None:
    stake = picks_engine._calculate_capped_stake(
        odds=3.4,
        true_prob=0.5,
        bankroll=1000.0,
        kelly_fraction=config.RISK_PROFILES["moderate"]["kelly_fraction"],
        max_stake_pct=config.RISK_PROFILES["moderate"]["max_stake_pct"] / 100.0,
    )

    assert stake == pytest.approx(50.0, abs=0.01)
