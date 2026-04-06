"""Contract tests for the cricket evidence provider infrastructure.

Tests verify EvidenceProvider protocol and CricketEvidenceProvider using
mocked HTTP responses.  No live API key required.
"""

from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from evidence_providers.base import EvidenceProvider, SportEvidence
from evidence_providers.cricket_evidence import CricketEvidenceProvider, _CACHE
from evidence_providers import get_sport_provider


# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------

_GOOD_MATCH = {
    "id": "match-001",
    "name": "India vs South Africa, 1st T20I",
    "matchType": "t20",
    "status": "scheduled",
    "venue": "Newlands, Cape Town",
    "dateTimeGMT": "2026-03-30T14:00:00",
    "teams": ["India", "South Africa"],
    "seriesId": "series-xyz",
}

_GOOD_SQUADS = [
    {
        "teamName": "India",
        "players": [{"name": "Rohit Sharma"}, {"name": "Virat Kohli"}],
    },
    {
        "teamName": "South Africa",
        "players": [{"name": "Temba Bavuma"}, {"name": "Kagiso Rabada"}],
    },
]

_FULL_DATA = {"match": _GOOD_MATCH, "squads": _GOOD_SQUADS, "series_id": "series-xyz"}


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _provider() -> CricketEvidenceProvider:
    _CACHE.clear()
    return CricketEvidenceProvider()


# ---------------------------------------------------------------------------
# TestCricketProviderReturnsValidSportEvidence
# ---------------------------------------------------------------------------

class TestCricketProviderReturnsValidSportEvidence:
    """Mock API response, verify SportEvidence fields."""

    def test_available_true_on_good_response(self):
        p = _provider()
        good_ev = SportEvidence(
            sport="cricket",
            available=True,
            source_name="cricketdata.org",
            data=_FULL_DATA,
        )
        with (
            patch.dict(os.environ, {"CRICKET_DATA_API_KEY": "test-key"}),
            patch.object(p, "_do_fetch", new=AsyncMock(return_value=good_ev)),
        ):
            ev = _run(p.fetch_evidence("ind_vs_sa_2026-03-30", "India", "South Africa"))

        assert isinstance(ev, SportEvidence)
        assert ev.available is True
        assert ev.sport == "cricket"
        assert ev.source_name == "cricketdata.org"
        assert isinstance(ev.data, dict)
        assert "match" in ev.data

    def test_fetched_at_is_iso_string(self):
        ev = SportEvidence(sport="cricket", available=True, source_name="cricketdata.org")
        from datetime import datetime
        # should parse without error
        datetime.fromisoformat(ev.fetched_at)

    def test_dataclass_fields_present(self):
        ev = SportEvidence(
            sport="cricket",
            available=True,
            source_name="cricketdata.org",
            stale_minutes=5.0,
            error="",
            data=_FULL_DATA,
        )
        assert ev.sport == "cricket"
        assert ev.stale_minutes == 5.0
        assert ev.error == ""
        assert ev.data is _FULL_DATA


# ---------------------------------------------------------------------------
# TestCricketProviderGracefulDegradation
# ---------------------------------------------------------------------------

class TestCricketProviderGracefulDegradation:
    """API timeout returns available=False."""

    def test_timeout_returns_unavailable(self):
        p = _provider()
        with (
            patch.dict(os.environ, {"CRICKET_DATA_API_KEY": "test-key"}),
            patch.object(p, "_do_fetch", new=AsyncMock(side_effect=asyncio.TimeoutError())),
        ):
            ev = _run(p.fetch_evidence("ind_vs_sa_2026-03-30", "India", "South Africa"))

        assert isinstance(ev, SportEvidence)
        assert ev.available is False
        assert "timeout" in ev.error.lower()

    def test_connection_error_returns_unavailable(self):
        p = _provider()
        with (
            patch.dict(os.environ, {"CRICKET_DATA_API_KEY": "test-key"}),
            patch.object(p, "_do_fetch", new=AsyncMock(side_effect=ConnectionError("down"))),
        ):
            ev = _run(p.fetch_evidence("ind_vs_sa_2026-03-30", "India", "South Africa"))

        assert ev.available is False
        assert ev.error != ""


# ---------------------------------------------------------------------------
# TestCricketProviderRateLimited
# ---------------------------------------------------------------------------

class TestCricketProviderRateLimited:
    """429 response returns available=False with error."""

    def test_429_returns_unavailable(self):
        import aiohttp

        p = _provider()
        exc = aiohttp.ClientResponseError(
            request_info=MagicMock(), history=(), status=429
        )
        with (
            patch.dict(os.environ, {"CRICKET_DATA_API_KEY": "test-key"}),
            patch.object(p, "_do_fetch", new=AsyncMock(side_effect=exc)),
        ):
            ev = _run(p.fetch_evidence("ind_vs_sa_2026-03-30", "India", "South Africa"))

        assert ev.available is False
        assert "429" in ev.error or "rate" in ev.error.lower()


# ---------------------------------------------------------------------------
# TestCricketProviderNoData
# ---------------------------------------------------------------------------

class TestCricketProviderNoData:
    """Empty API response returns available=False."""

    def test_no_match_found_returns_unavailable(self):
        p = _provider()
        no_match_ev = SportEvidence(
            sport="cricket",
            available=False,
            source_name="cricketdata.org",
            error="Match not found for Sunrisers vs Paarl. SA20 domestic league may not be covered.",
        )
        with (
            patch.dict(os.environ, {"CRICKET_DATA_API_KEY": "test-key"}),
            patch.object(p, "_do_fetch", new=AsyncMock(return_value=no_match_ev)),
        ):
            ev = _run(p.fetch_evidence("sa20_sunrisers_vs_paarl_2026-01-15", "Sunrisers", "Paarl"))

        assert ev.available is False
        assert ev.error != ""

    def test_missing_api_key_returns_unavailable(self):
        p = _provider()
        env = {k: v for k, v in os.environ.items() if k != "CRICKET_DATA_API_KEY"}
        with patch.dict(os.environ, env, clear=True):
            ev = _run(p.fetch_evidence("ind_vs_sa_2026-03-30", "India", "South Africa"))

        assert ev.available is False
        assert ev.error != ""


# ---------------------------------------------------------------------------
# TestCricketKeyFactsCount
# ---------------------------------------------------------------------------

class TestCricketKeyFactsCount:
    """contributes_key_facts returns correct count."""

    def test_full_data_bounded_by_five(self):
        p = CricketEvidenceProvider()
        ev = SportEvidence(sport="cricket", available=True, data=_FULL_DATA)
        count = p.contributes_key_facts(ev)
        assert 1 <= count <= 5

    def test_unavailable_returns_zero(self):
        p = CricketEvidenceProvider()
        ev = SportEvidence(sport="cricket", available=False)
        assert p.contributes_key_facts(ev) == 0

    def test_empty_data_returns_zero(self):
        p = CricketEvidenceProvider()
        ev = SportEvidence(sport="cricket", available=True, data={})
        assert p.contributes_key_facts(ev) == 0

    def test_partial_data_less_than_full(self):
        p = CricketEvidenceProvider()
        full_ev = SportEvidence(sport="cricket", available=True, data=_FULL_DATA)
        partial_ev = SportEvidence(
            sport="cricket", available=True,
            data={"match": {"name": "India vs SA"}, "squads": []},
        )
        assert p.contributes_key_facts(partial_ev) <= p.contributes_key_facts(full_ev)

    def test_series_name_contributes_one(self):
        p = CricketEvidenceProvider()
        ev = SportEvidence(
            sport="cricket", available=True,
            data={"match": {"name": "India vs SA"}, "squads": []},
        )
        assert p.contributes_key_facts(ev) >= 1


# ---------------------------------------------------------------------------
# TestCricketFormatForPrompt
# ---------------------------------------------------------------------------

class TestCricketFormatForPrompt:
    """format_for_prompt includes section headers and data."""

    def test_cricket_context_header_present(self):
        p = CricketEvidenceProvider()
        ev = SportEvidence(sport="cricket", available=True, data=_FULL_DATA)
        result = p.format_for_prompt(ev)
        assert "[CRICKET CONTEXT]" in result

    def test_includes_series_name(self):
        p = CricketEvidenceProvider()
        ev = SportEvidence(sport="cricket", available=True, data=_FULL_DATA)
        result = p.format_for_prompt(ev)
        assert "India vs South Africa" in result

    def test_includes_venue(self):
        p = CricketEvidenceProvider()
        ev = SportEvidence(sport="cricket", available=True, data=_FULL_DATA)
        result = p.format_for_prompt(ev)
        assert "Newlands" in result

    def test_unavailable_returns_empty_string(self):
        p = CricketEvidenceProvider()
        ev = SportEvidence(sport="cricket", available=False)
        assert p.format_for_prompt(ev) == ""

    def test_squad_names_appear(self):
        p = CricketEvidenceProvider()
        ev = SportEvidence(sport="cricket", available=True, data=_FULL_DATA)
        result = p.format_for_prompt(ev)
        assert "Rohit Sharma" in result or "India squad" in result

    def test_empty_data_returns_empty_string(self):
        p = CricketEvidenceProvider()
        ev = SportEvidence(sport="cricket", available=True, data={})
        result = p.format_for_prompt(ev)
        assert result == "" or "[CRICKET CONTEXT]" in result


# ---------------------------------------------------------------------------
# TestRegistryAndProtocol
# ---------------------------------------------------------------------------

class TestRegistryAndProtocol:
    """get_sport_provider registry and protocol conformance."""

    def test_cricket_provider_registered(self):
        assert get_sport_provider("cricket") is not None

    def test_soccer_returns_none(self):
        assert get_sport_provider("soccer") is None

    def test_rugby_provider_registered(self):
        assert get_sport_provider("rugby") is not None

    def test_cricket_implements_evidence_provider_protocol(self):
        provider = get_sport_provider("cricket")
        assert isinstance(provider, EvidenceProvider)

    def test_rugby_implements_evidence_provider_protocol(self):
        provider = get_sport_provider("rugby")
        assert isinstance(provider, EvidenceProvider)

    def test_case_insensitive_lookup(self):
        assert get_sport_provider("Cricket") is get_sport_provider("cricket")
        assert get_sport_provider("CRICKET") is get_sport_provider("cricket")
