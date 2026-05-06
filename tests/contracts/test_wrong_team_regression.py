from __future__ import annotations

import os
from dataclasses import dataclass, field

import verdict_corpus


@dataclass
class _Spec:
    home_name: str = "Delhi Capitals"
    away_name: str = "Chennai Super Kings"
    sport: str = "cricket"
    league: str = "ipl"
    competition: str = "IPL"
    outcome: str = "away"
    outcome_label: str = "Chennai Super Kings"
    recommended_team: str = "Chennai Super Kings"
    edge_tier: str = "silver"
    odds: float = 2.05
    ev_pct: float = 7.2
    bookmaker: str = "Betway"
    match_key: str = "delhi_capitals_vs_chennai_super_kings_2026-05-09"
    edge_revision: str = "wrong-team-regression"
    recommended_at: str = "2026-05-06T00:00:00Z"
    venue: str = "Delhi"
    nickname: str = "Chennai"
    coach: str = "Stephen Fleming"
    signals: dict = field(default_factory=lambda: {
        "price_edge": True,
        "form": True,
        "market": True,
    })
    evidence_pack: dict | None = None
    home_form: str = "WLWLW"
    away_form: str = "WWLWW"
    h2h: str = ""
    line_movement_direction: str | None = None
    bookmaker_count: int = 3
    tipster_sources_count: int | None = None
    tipster_available: bool = False
    tipster_agrees: bool | None = None
    verdict_action: str = "lean"
    verdict_sizing: str = "standard stake"


def test_delhi_vs_chennai_no_sunrisers() -> None:
    verdict = verdict_corpus.render_verdict(_Spec())

    assert "Sunrisers" not in verdict
    assert "Sunrisers Hyderabad" not in verdict
    assert ("Delhi" in verdict) or ("Chennai" in verdict)

    if os.environ.get("VERDICT_ENGINE_V2", "1").strip().lower() in {"0", "false", "no", "off", ""}:
        assert verdict_corpus.get_last_engine_version() == "legacy"
    else:
        assert verdict_corpus.get_last_engine_version() == "v2_microfact"
