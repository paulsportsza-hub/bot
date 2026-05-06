from __future__ import annotations

from dataclasses import asdict
import logging

import pytest

import narrative_validator as nv
import narrative_spec
import verdict_engine_v2


GOOD_VERDICT = (
    "Price still supports Liverpool - back Liverpool at 1.96 with Supabets, "
    "standard stake."
)


def _pack(**overrides):
    pack = {
        "match_id": "liverpool_vs_chelsea_2026-05-07",
        "match_key": "liverpool_vs_chelsea_2026-05-07",
        "home_team": "Liverpool",
        "away_team": "Chelsea",
        "recommended_team": "Liverpool",
        "outcome_label": "Liverpool",
        "sport": "soccer",
        "league": "epl",
        "recommended_odds": 1.96,
        "bookmaker": "Supabets",
        "signals": {
            "price_edge": {"available": True},
            "form_h2h": {"available": True},
            "lineup_injury": {"available": True},
            "movement": {"available": True, "direction": "favourable"},
            "market_agreement": {"available": True},
            "tipster": {"available": True},
        },
    }
    pack.update(overrides)
    return pack


def _details(result):
    return [failure.detail for failure in result.failures]


def test_v2_delegation_happy_path_flag_on(monkeypatch):
    monkeypatch.setenv("VERDICT_ENGINE_V2", "1")
    calls = []

    def fake_validate(text, ctx, **_kwargs):
        calls.append((text, ctx))
        return ()

    monkeypatch.setattr(verdict_engine_v2, "validate_verdict", fake_validate)

    result = nv.validate_narrative_for_persistence(
        content={
            "narrative_html": "ignored legacy narrative",
            "verdict_html": GOOD_VERDICT,
            "match_id": "liverpool_vs_chelsea_2026-05-07",
            "narrative_source": "w84",
        },
        evidence_pack=_pack(),
        edge_tier="gold",
        source_label="w84",
    )

    assert result.passed is True
    assert calls
    assert calls[0][0] == GOOD_VERDICT
    assert calls[0][1].match_key == "liverpool_vs_chelsea_2026-05-07"
    assert calls[0][1].recommended_team == "Liverpool"


def test_v2_delegation_uses_edge_state_outcome_and_signals(monkeypatch):
    monkeypatch.setenv("VERDICT_ENGINE_V2", "1")
    pack = {
        "match_id": "liverpool_vs_chelsea_2026-05-07",
        "match_key": "liverpool_vs_chelsea_2026-05-07",
        "home_team": "Liverpool",
        "away_team": "Chelsea",
        "sport": "soccer",
        "league": "epl",
        "recommended_odds": 1.96,
        "bookmaker": "Supabets",
        "edge_state": {
            "outcome": "Home Win",
            "signals": {
                "price_edge": {"available": True},
                "form_h2h": {"available": True},
            },
        },
    }

    result = nv.validate_verdict_for_persistence(
        "Recent results strengthen the case for Chelsea. Back Chelsea at 1.96 with Supabets, standard stake.",
        "gold",
        pack,
        "verdict-cache",
    )

    assert result.passed is False
    assert "verdict_missing_recommended_team_or_nickname" in _details(result)


def test_v2_delegation_signal_claim_rejection(monkeypatch):
    monkeypatch.setenv("VERDICT_ENGINE_V2", "1")
    pack = _pack(signals={"price_edge": {"available": True}})

    result = nv.validate_verdict_for_persistence(
        "Recent results strengthen the case for Liverpool. Back Liverpool, standard stake.",
        "gold",
        pack,
        "verdict-cache",
    )

    assert result.passed is False
    assert "unsupported_form_claim" in _details(result)


def test_v2_delegation_team_integrity_rejection(monkeypatch):
    monkeypatch.setenv("VERDICT_ENGINE_V2", "1")

    result = nv.validate_verdict_for_persistence(
        "Price still supports Chelsea - back Chelsea at 1.96 with Supabets, standard stake.",
        "gold",
        _pack(),
        "verdict-cache",
    )

    assert result.passed is False
    assert "verdict_missing_recommended_team_or_nickname" in _details(result)


def test_v2_delegation_sport_vocabulary_rejection(monkeypatch):
    monkeypatch.setenv("VERDICT_ENGINE_V2", "1")

    result = nv.validate_verdict_for_persistence(
        "The wicket angle supports Liverpool - back Liverpool at 1.96 with Supabets, standard stake.",
        "gold",
        _pack(),
        "verdict-cache",
    )

    assert result.passed is False
    assert "sport_vocabulary:wicket" in _details(result)


def test_v2_delegation_engine_exception_falls_through_to_legacy(
    monkeypatch,
    caplog,
):
    monkeypatch.setenv("VERDICT_ENGINE_V2", "1")

    def boom(_text, _ctx, **_kwargs):
        raise RuntimeError("boom v2")

    monkeypatch.setattr(verdict_engine_v2, "validate_verdict", boom)
    caplog.set_level(logging.WARNING)

    result = nv.validate_verdict_for_persistence(
        GOOD_VERDICT,
        "gold",
        _pack(),
        "verdict-cache",
    )

    assert result.passed is True
    assert "NARRATIVE_VALIDATOR_V2_DELEGATION_FAIL" in caplog.text
    assert "liverpool_vs_chelsea_2026-05-07" in caplog.text
    assert "boom v2" in caplog.text


def test_v2_reject_survives_legacy_merge_exception(monkeypatch, caplog):
    monkeypatch.setenv("VERDICT_ENGINE_V2", "1")

    def legacy_boom(*_args, **_kwargs):
        raise RuntimeError("legacy boom")

    monkeypatch.setattr(nv, "_validate_verdict_legacy_path", legacy_boom)
    caplog.set_level(logging.WARNING)

    result = nv.validate_verdict_for_persistence(
        "Recent results strengthen the case for Liverpool. Back Liverpool at 1.96 with Supabets, standard stake.",
        "gold",
        _pack(signals={"price_edge": {"available": True}}),
        "verdict-cache",
    )

    assert result.passed is False
    assert "unsupported_form_claim" in _details(result)
    assert "NARRATIVE_VALIDATOR_V2_LEGACY_MERGE_FAIL" in caplog.text
    assert "legacy boom" in caplog.text


def test_v2_narrative_reject_survives_legacy_gate_exception(monkeypatch, caplog):
    monkeypatch.setenv("VERDICT_ENGINE_V2", "1")
    monkeypatch.setattr(
        verdict_engine_v2,
        "validate_verdict",
        lambda _text, _ctx, **_kwargs: ("forced_v2_reject",),
    )
    monkeypatch.setattr(narrative_spec, "min_verdict_quality", lambda *_a, **_kw: True)

    def venue_boom(*_args, **_kwargs):
        raise RuntimeError("legacy venue boom")

    monkeypatch.setattr(narrative_spec, "find_venue_leaks", venue_boom)
    caplog.set_level(logging.WARNING)

    result = nv.validate_narrative_for_persistence(
        content={
            "narrative_html": "",
            "verdict_html": GOOD_VERDICT,
            "match_id": "liverpool_vs_chelsea_2026-05-07",
            "narrative_source": "w84",
        },
        evidence_pack=_pack(),
        edge_tier="gold",
        source_label="w84",
    )

    assert result.passed is False
    assert "forced_v2_reject" in _details(result)
    assert "NARRATIVE_VALIDATOR_V2_LEGACY_MERGE_FAIL" in caplog.text
    assert "legacy venue boom" in caplog.text


def test_legacy_path_unchanged_under_flag_off(monkeypatch):
    monkeypatch.setenv("VERDICT_ENGINE_V2", "0")

    def fail_if_called():
        raise AssertionError("V2 should not run when VERDICT_ENGINE_V2=0")

    monkeypatch.setattr(nv, "_verdict_engine_v2_module", fail_if_called)
    pack = _pack()

    cases = {
        "empty": nv.validate_verdict_for_persistence("", "gold", pack, "verdict-cache"),
        "good": nv.validate_verdict_for_persistence(
            GOOD_VERDICT,
            "gold",
            pack,
            "verdict-cache",
        ),
        "telemetry": nv.validate_verdict_for_persistence(
            "The supporting signals back the read. Back Liverpool at 1.96 with Supabets, standard stake.",
            "gold",
            pack,
            "verdict-cache",
        ),
    }

    assert {name: asdict(result) for name, result in cases.items()} == {
        "empty": {"passed": True, "failures": [], "severity": None},
        "good": {"passed": True, "failures": [], "severity": None},
        "telemetry": {
            "passed": False,
            "failures": [
                {
                    "gate": "telemetry_vocabulary",
                    "severity": "CRITICAL",
                    "detail": "verdict hits=['the signals', 'the reads']",
                    "section": "verdict_html",
                }
            ],
            "severity": "CRITICAL",
        },
    }
