"""Tests for scripts/odds_client.py — best_odds, format_odds_message, fetch mocking."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from scripts.odds_client import best_odds, format_odds_message, fetch_odds, fetch_sports


# ── Sample event fixture ──────────────────────────────────

SAMPLE_EVENT = {
    "id": "abc123",
    "sport_key": "soccer_epl",
    "commence_time": "2025-03-01T15:00:00Z",
    "home_team": "Arsenal",
    "away_team": "Chelsea",
    "bookmakers": [
        {
            "key": "bet365",
            "title": "Bet365",
            "markets": [
                {
                    "key": "h2h",
                    "outcomes": [
                        {"name": "Arsenal", "price": 2.10},
                        {"name": "Chelsea", "price": 3.40},
                        {"name": "Draw", "price": 3.05},
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
                        {"name": "Arsenal", "price": 2.20},
                        {"name": "Chelsea", "price": 3.30},
                        {"name": "Draw", "price": 3.10},
                    ],
                }
            ],
        },
    ],
}


class TestBestOdds:
    def test_returns_best_across_bookmakers(self):
        result = best_odds(SAMPLE_EVENT)
        assert result["Arsenal"] == 2.20  # best from betway
        assert result["Chelsea"] == 3.40  # best from bet365
        assert result["Draw"] == 3.10     # best from betway

    def test_empty_bookmakers(self):
        event = {"bookmakers": []}
        assert best_odds(event) == {}

    def test_missing_bookmakers_key(self):
        event = {}
        assert best_odds(event) == {}

    def test_filters_by_market(self):
        event = {
            "bookmakers": [
                {
                    "key": "bk1",
                    "markets": [
                        {"key": "spreads", "outcomes": [{"name": "A", "price": 1.5}]},
                        {"key": "h2h", "outcomes": [{"name": "B", "price": 2.0}]},
                    ],
                }
            ]
        }
        result = best_odds(event, market="h2h")
        assert "B" in result
        assert "A" not in result


class TestFormatOddsMessage:
    def test_no_events(self):
        msg = format_odds_message([], "EPL")
        assert "EPL" in msg
        assert "No upcoming events" in msg

    def test_with_events(self):
        msg = format_odds_message([SAMPLE_EVENT], "EPL")
        assert "EPL" in msg
        assert "Arsenal" in msg
        assert "Chelsea" in msg
        assert "<b>" in msg  # HTML formatting

    def test_limits_to_8_events(self):
        events = [SAMPLE_EVENT] * 15
        msg = format_odds_message(events, "EPL")
        # Each event has "Arsenal vs" in heading — count match lines
        assert msg.count("Arsenal</b> vs") == 8


class TestFetchOdds:
    @pytest.mark.asyncio
    async def test_fetch_odds_success(self):
        mock_response = MagicMock()
        mock_response.json.return_value = [SAMPLE_EVENT]
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("scripts.odds_client.httpx.AsyncClient", return_value=mock_client):
            result = await fetch_odds("soccer_epl")
            assert len(result) == 1
            assert result[0]["home_team"] == "Arsenal"

    @pytest.mark.asyncio
    async def test_fetch_sports_success(self):
        mock_response = MagicMock()
        mock_response.json.return_value = [{"key": "soccer_epl", "title": "EPL"}]
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("scripts.odds_client.httpx.AsyncClient", return_value=mock_client):
            result = await fetch_sports()
            assert len(result) == 1
            assert result[0]["key"] == "soccer_epl"
