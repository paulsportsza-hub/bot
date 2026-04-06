"""Contract tests for the combat evidence provider infrastructure."""

from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from evidence_providers import get_sport_provider
from evidence_providers.base import EvidenceProvider, SportEvidence
from evidence_providers.combat_evidence import CombatEvidenceProvider, _CACHE


_MMA_DATA = {
    "requested_sport": "mma",
    "fighter_profiles": {
        "home": {
            "name": "Dricus Du Plessis",
            "record": "23-2-0",
            "ko_rate": 0.48,
            "sub_rate": 0.17,
            "weight_class": "Middleweight",
            "reach_cm": 193,
            "age": 31,
            "ranking": 1,
        },
        "away": {
            "name": "Khamzat Chimaev",
            "record": "14-0-0",
            "ko_rate": 0.43,
            "sub_rate": 0.36,
            "weight_class": "Middleweight",
            "reach_cm": 191,
            "age": 30,
            "ranking": 2,
        },
    },
    "recent_fights": {
        "home": [{"opponent": "Sean Strickland", "result": "W", "method": "Decision", "round": 5, "event": "UFC 312"}],
        "away": [{"opponent": "Robert Whittaker", "result": "W", "method": "Submission", "round": 1, "event": "UFC 308"}],
    },
    "h2h": [],
    "title_implications": "Middleweight title eliminator",
}

_BOXING_DATA = {
    "requested_sport": "boxing",
    "fighter_profiles": {
        "home": {
            "name": "Canelo Alvarez",
            "record": "62-2-2",
            "ko_rate": 0.63,
            "weight_class": "Super Middleweight",
            "reach_cm": 179,
            "age": 35,
            "ranking": 1,
            "title_status": "Undisputed champion",
        },
        "away": {
            "name": "Terence Crawford",
            "record": "41-0-0",
            "ko_rate": 0.76,
            "weight_class": "Super Middleweight",
            "reach_cm": 188,
            "age": 38,
            "ranking": 2,
            "title_status": "Four-division champion",
        },
    },
    "recent_fights": {
        "home": [{"opponent": "Jaime Munguia", "result": "W", "method": "Decision", "round": 12, "event": "Las Vegas"}],
        "away": [{"opponent": "Israil Madrimov", "result": "W", "method": "Decision", "round": 12, "event": "Riyadh"}],
    },
    "h2h": [],
    "title_implications": "Undisputed title defense",
}


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _provider() -> CombatEvidenceProvider:
    _CACHE.clear()
    return CombatEvidenceProvider()


class TestMMAProviderReturnsValidSportEvidence:
    def test_available_true_on_good_response(self):
        provider = _provider()
        good_ev = SportEvidence(
            sport="mma",
            available=True,
            source_name="api-sports-mma",
            data=_MMA_DATA,
        )
        with (
            patch.dict(os.environ, {"API_SPORTS_KEY": "test-key"}),
            patch.object(provider, "_do_fetch", new=AsyncMock(return_value=good_ev)),
        ):
            ev = _run(provider.fetch_evidence("ufc_312_ddp_vs_khamzat", "Dricus Du Plessis", "Khamzat Chimaev", sport="mma"))

        assert isinstance(ev, SportEvidence)
        assert ev.available is True
        assert ev.sport == "mma"
        assert ev.source_name == "api-sports-mma"
        assert ev.data["fighter_profiles"]["home"]["name"] == "Dricus Du Plessis"


class TestBoxingProviderReturnsValidSportEvidence:
    def test_available_true_on_good_response(self):
        provider = _provider()
        good_ev = SportEvidence(
            sport="boxing",
            available=True,
            source_name="boxing-data",
            data=_BOXING_DATA,
        )
        with (
            patch.dict(os.environ, {"BOXING_DATA_API_KEY": "test-key"}),
            patch.object(provider, "_do_fetch", new=AsyncMock(return_value=good_ev)),
        ):
            ev = _run(provider.fetch_evidence("boxing_canelo_vs_crawford", "Canelo Alvarez", "Terence Crawford", sport="boxing"))

        assert ev.available is True
        assert ev.sport == "boxing"
        assert ev.source_name == "boxing-data"
        assert ev.data["fighter_profiles"]["away"]["record"] == "41-0-0"


class TestCombatDispatchesBySubSport:
    def test_explicit_mma_sport_routes_to_mma(self):
        provider = _provider()
        with patch.object(provider, "_do_fetch", new=AsyncMock(return_value=SportEvidence(sport="mma", available=True, data=_MMA_DATA))) as mocked:
            _run(provider.fetch_evidence("fight_001", "Dricus Du Plessis", "Khamzat Chimaev", sport="mma"))
        assert mocked.await_args.args[0] == "mma"

    def test_match_key_inference_routes_to_boxing(self):
        provider = _provider()
        with patch.object(provider, "_do_fetch", new=AsyncMock(return_value=SportEvidence(sport="boxing", available=True, data=_BOXING_DATA))) as mocked:
            _run(provider.fetch_evidence("boxing_canelo_vs_crawford", "Canelo Alvarez", "Terence Crawford", sport="combat"))
        assert mocked.await_args.args[0] == "boxing"


class TestCombatGracefulDegradation:
    def test_timeout_returns_unavailable(self):
        provider = _provider()
        with patch.object(provider, "_do_fetch", new=AsyncMock(side_effect=asyncio.TimeoutError())):
            ev = _run(provider.fetch_evidence("ufc_timeout_case", "A", "B", sport="mma"))
        assert ev.available is False
        assert "timeout" in ev.error.lower()

    def test_429_returns_unavailable(self):
        import aiohttp

        provider = _provider()
        exc = aiohttp.ClientResponseError(request_info=MagicMock(), history=(), status=429)
        with patch.object(provider, "_do_fetch", new=AsyncMock(side_effect=exc)):
            ev = _run(provider.fetch_evidence("boxing_limit_case", "A", "B", sport="boxing"))
        assert ev.available is False
        assert "429" in ev.error or "rate" in ev.error.lower()


class TestMMANoDuplicationWithESPN:
    def test_format_omits_basic_mma_record_line(self):
        provider = _provider()
        ev = SportEvidence(sport="mma", available=True, data=_MMA_DATA)
        rendered = provider.format_for_prompt(ev)
        assert "[FIGHTER PROFILES]" in rendered
        assert "23-2-0" not in rendered
        assert "KO rate" in rendered
        assert "submission rate" in rendered
        assert "reach 193 cm" in rendered


class TestBoxingFillsESPNGap:
    def test_boxing_format_includes_record_when_espn_has_no_data(self):
        provider = _provider()
        ev = SportEvidence(sport="boxing", available=True, data=_BOXING_DATA)
        rendered = provider.format_for_prompt(ev)
        assert "record 62-2-2" in rendered
        assert "KO rate 63%" in rendered
        assert "Undisputed champion" in rendered


class TestCombatKeyFacts:
    def test_key_facts_max_three(self):
        provider = _provider()
        ev = SportEvidence(sport="boxing", available=True, data=_BOXING_DATA)
        assert provider.contributes_key_facts(ev) == 3

    def test_unavailable_returns_zero(self):
        provider = _provider()
        assert provider.contributes_key_facts(SportEvidence(sport="mma", available=False)) == 0


class TestRegistryAndProtocol:
    def test_mma_provider_registered(self):
        assert get_sport_provider("mma") is not None

    def test_boxing_provider_registered(self):
        assert get_sport_provider("boxing") is not None

    def test_combat_provider_registered(self):
        assert get_sport_provider("combat") is not None

    def test_combat_implements_protocol(self):
        assert isinstance(get_sport_provider("mma"), EvidenceProvider)
