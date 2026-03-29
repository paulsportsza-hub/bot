"""Contract tests for the rugby evidence provider infrastructure."""

from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from evidence_providers import get_sport_provider
from evidence_providers.base import EvidenceProvider, SportEvidence
from evidence_providers.rugby_evidence import RugbyEvidenceProvider, _CACHE


_GOOD_DATA = {
    "home_team": "Bulls",
    "away_team": "Stormers",
    "h2h": {
        "total_meetings": 12,
        "home_wins": 7,
        "away_wins": 5,
        "avg_total_points": 48.3,
    },
    "venue_stats": {
        "venue": "Loftus Versfeld",
        "home_record": "W8 D0 L2",
        "avg_home_score": 31.4,
    },
    "try_stats": {
        "home": {"tries_for": 28, "tries_against": 14, "avg_per_game": 3.5},
        "away": {"tries_for": 22, "tries_against": 19, "avg_per_game": 2.8},
    },
}


def _run(coro):
    return asyncio.run(coro)


def _provider() -> RugbyEvidenceProvider:
    _CACHE.clear()
    return RugbyEvidenceProvider()


class TestRugbyProviderReturnsValidSportEvidence:
    def test_available_true_on_good_response(self):
        p = _provider()
        good_ev = SportEvidence(
            sport="rugby",
            available=True,
            source_name="api-sports-rugby",
            data=_GOOD_DATA,
        )
        with (
            patch.dict(os.environ, {"API_SPORTS_KEY": "test-key"}),
            patch.object(p, "_do_fetch", new=AsyncMock(return_value=good_ev)),
        ):
            ev = _run(p.fetch_evidence("bulls_vs_stormers_2026-03-30", "Bulls", "Stormers"))

        assert isinstance(ev, SportEvidence)
        assert ev.available is True
        assert ev.sport == "rugby"
        assert ev.source_name == "api-sports-rugby"
        assert ev.data["h2h"]["total_meetings"] == 12

    def test_dataclass_fields_present(self):
        ev = SportEvidence(
            sport="rugby",
            available=True,
            source_name="api-sports-rugby",
            stale_minutes=2.0,
            data=_GOOD_DATA,
        )
        assert ev.sport == "rugby"
        assert ev.stale_minutes == 2.0
        assert ev.data is _GOOD_DATA


class TestRugbyProviderGracefulDegradation:
    def test_timeout_returns_unavailable(self):
        p = _provider()
        with (
            patch.dict(os.environ, {"API_SPORTS_KEY": "test-key"}),
            patch.object(p, "_do_fetch", new=AsyncMock(side_effect=asyncio.TimeoutError())),
        ):
            ev = _run(p.fetch_evidence("bulls_vs_stormers_2026-03-30", "Bulls", "Stormers"))

        assert ev.available is False
        assert "timeout" in ev.error.lower()

    def test_missing_api_key_returns_unavailable(self):
        p = _provider()
        env = {k: v for k, v in os.environ.items() if k != "API_SPORTS_KEY"}
        with patch.dict(os.environ, env, clear=True):
            ev = _run(p.fetch_evidence("bulls_vs_stormers_2026-03-30", "Bulls", "Stormers"))

        assert ev.available is False
        assert "API_SPORTS_KEY" in ev.error

    def test_429_returns_unavailable(self):
        import aiohttp

        p = _provider()
        exc = aiohttp.ClientResponseError(
            request_info=MagicMock(), history=(), status=429
        )
        with (
            patch.dict(os.environ, {"API_SPORTS_KEY": "test-key"}),
            patch.object(p, "_do_fetch", new=AsyncMock(side_effect=exc)),
        ):
            ev = _run(p.fetch_evidence("bulls_vs_stormers_2026-03-30", "Bulls", "Stormers"))

        assert ev.available is False
        assert "429" in ev.error or "rate" in ev.error.lower()


class TestRugbyKeyFactsCount:
    def test_full_data_returns_three(self):
        p = RugbyEvidenceProvider()
        ev = SportEvidence(sport="rugby", available=True, data=_GOOD_DATA)
        assert p.contributes_key_facts(ev) == 3

    def test_unavailable_returns_zero(self):
        p = RugbyEvidenceProvider()
        ev = SportEvidence(sport="rugby", available=False)
        assert p.contributes_key_facts(ev) == 0

    def test_partial_data_bounded(self):
        p = RugbyEvidenceProvider()
        ev = SportEvidence(
            sport="rugby",
            available=True,
            data={"h2h": {"total_meetings": 4}, "try_stats": {}},
        )
        assert p.contributes_key_facts(ev) == 1


class TestRugbyFormatForPrompt:
    def test_rugby_context_header_present(self):
        p = RugbyEvidenceProvider()
        ev = SportEvidence(sport="rugby", available=True, data=_GOOD_DATA)
        result = p.format_for_prompt(ev)
        assert "[RUGBY CONTEXT]" in result

    def test_includes_try_and_venue_context(self):
        p = RugbyEvidenceProvider()
        ev = SportEvidence(sport="rugby", available=True, data=_GOOD_DATA)
        result = p.format_for_prompt(ev)
        assert "tries/game" in result
        assert "Loftus" in result

    def test_unavailable_returns_empty(self):
        p = RugbyEvidenceProvider()
        ev = SportEvidence(sport="rugby", available=False)
        assert p.format_for_prompt(ev) == ""


class TestRugbyNoDuplicationWithESPN:
    def test_output_does_not_repeat_standings_or_coaches(self):
        p = RugbyEvidenceProvider()
        ev = SportEvidence(sport="rugby", available=True, data=_GOOD_DATA)
        result = p.format_for_prompt(ev).lower()
        assert "standings" not in result
        assert "coach" not in result


class TestRegistryAndProtocol:
    def test_rugby_provider_registered(self):
        assert get_sport_provider("rugby") is not None

    def test_rugby_implements_evidence_provider_protocol(self):
        provider = get_sport_provider("rugby")
        assert isinstance(provider, EvidenceProvider)

    def test_case_insensitive_lookup(self):
        assert get_sport_provider("Rugby") is get_sport_provider("rugby")
        assert get_sport_provider("RUGBY") is get_sport_provider("rugby")
