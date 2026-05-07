from __future__ import annotations

from dataclasses import asdict

import pytest

from narrative_validator import validate_verdict_for_persistence
from verdict_engine_v2 import ACTION_BY_TIER


CORE7_CONTEXTS = (
    {
        "id": "soccer",
        "match_key": "liverpool_vs_chelsea_2026-05-07",
        "sport": "soccer",
        "league": "epl",
        "home_team": "Liverpool",
        "away_team": "Chelsea",
        "team": "Liverpool",
        "nickname": "the Reds",
    },
    {
        "id": "rugby",
        "match_key": "crusaders_vs_blues_2026-05-07",
        "sport": "rugby",
        "league": "super_rugby",
        "home_team": "Crusaders",
        "away_team": "Blues",
        "team": "Crusaders",
        "nickname": "the Crusaders",
    },
    {
        "id": "cricket",
        "match_key": "delhi_capitals_vs_kolkata_knight_riders_2026-05-08",
        "sport": "cricket",
        "league": "ipl",
        "home_team": "Delhi Capitals",
        "away_team": "Kolkata Knight Riders",
        "team": "Delhi Capitals",
        "nickname": "Delhi",
    },
    {
        "id": "tennis",
        "match_key": "carlos_alcaraz_vs_jannik_sinner_2026-05-08",
        "sport": "tennis",
        "league": "atp",
        "home_team": "Carlos Alcaraz",
        "away_team": "Jannik Sinner",
        "team": "Carlos Alcaraz",
        "nickname": "Alcaraz",
    },
    {
        "id": "basketball",
        "match_key": "los_angeles_lakers_vs_boston_celtics_2026-05-09",
        "sport": "basketball",
        "league": "nba",
        "home_team": "Los Angeles Lakers",
        "away_team": "Boston Celtics",
        "team": "Los Angeles Lakers",
        "nickname": "the Lakers",
    },
    {
        "id": "mma",
        "match_key": "dricus_du_plessis_vs_khamzat_chimaev_2026-05-10",
        "sport": "mma",
        "league": "ufc",
        "home_team": "Dricus Du Plessis",
        "away_team": "Khamzat Chimaev",
        "team": "Dricus Du Plessis",
        "nickname": "Dricus",
    },
    {
        "id": "boxing",
        "match_key": "tyson_fury_vs_oleksandr_usyk_2026-05-11",
        "sport": "boxing",
        "league": "heavyweight",
        "home_team": "Tyson Fury",
        "away_team": "Oleksandr Usyk",
        "team": "Tyson Fury",
        "nickname": "Fury",
    },
)


def _pack(context: dict[str, str], tier: str) -> dict[str, object]:
    return {
        "match_id": context["match_key"],
        "match_key": context["match_key"],
        "home_team": context["home_team"],
        "away_team": context["away_team"],
        "recommended_team": context["team"],
        "outcome_label": context["team"],
        "sport": context["sport"],
        "league": context["league"],
        "recommended_odds": 1.91,
        "odds": 1.91,
        "bookmaker": "Supabets",
        "edge_tier": tier,
        "nickname": context["nickname"],
        "signals": {
            "price_edge": {"available": True},
            "form_h2h": {"available": True},
            "lineup_injury": {"available": True},
            "movement": {"available": True, "direction": "toward"},
            "market_agreement": {"available": True, "bookmaker_count": 4},
            "tipster": {"available": True},
        },
    }


def _verdict(context: dict[str, str], action_template: str) -> str:
    team = context["team"]
    action = action_template.format(team=team)
    return (
        f"{team} at 1.91 with Supabets -- "
        f"the price still looks playable for {team}. {action}"
    )


def _gate_names(result) -> set[str]:
    return {failure.gate for failure in result.failures}


def test_every_v2_action_template_passes_persistence_validator() -> None:
    assert set(ACTION_BY_TIER) == {"diamond", "gold", "silver", "bronze"}

    failures: list[dict[str, object]] = []
    exercised: set[tuple[str, str]] = set()
    for tier, action_templates in ACTION_BY_TIER.items():
        assert action_templates, f"ACTION_BY_TIER[{tier!r}] must not be empty"
        for action_template in action_templates:
            exercised.add((tier, action_template))
            for context in CORE7_CONTEXTS:
                result = validate_verdict_for_persistence(
                    _verdict(context, action_template),
                    tier,
                    _pack(context, tier),
                    "validator-v2-action-parity",
                )
                if not result.passed:
                    failures.append(
                        {
                            "tier": tier,
                            "sport": context["id"],
                            "action_template": action_template,
                            "failures": [asdict(failure) for failure in result.failures],
                        }
                    )

    expected = {
        (tier, action_template)
        for tier, action_templates in ACTION_BY_TIER.items()
        for action_template in action_templates
    }
    assert exercised == expected
    if failures:
        pytest.fail(f"V2 action templates rejected by validator: {failures!r}")


@pytest.mark.parametrize(
    ("source_tier", "action_template", "target_tier"),
    (
        ("diamond", "{team} is the play, full stake.", "silver"),
        ("diamond", "{team} is the play, full stake.", "bronze"),
        ("gold", "{team} is the play, standard stake.", "silver"),
        ("gold", "{team} is the play, standard stake.", "bronze"),
        ("silver", "Lean {team}, standard stake.", "diamond"),
        ("silver", "Lean {team}, standard stake.", "gold"),
        ("silver", "{team} gets the nod, standard stake.", "diamond"),
        ("silver", "{team} gets the nod, standard stake.", "gold"),
        ("silver", "{team} gets the nod, standard stake.", "bronze"),
        ("bronze", "Worth a small play on {team}, light stake.", "diamond"),
        ("bronze", "Worth a small play on {team}, light stake.", "gold"),
        ("bronze", "Worth a small play on {team}, light stake.", "silver"),
        ("bronze", "Small lean to {team}, light stake.", "diamond"),
        ("bronze", "Small lean to {team}, light stake.", "gold"),
        ("bronze", "Small lean to {team}, light stake.", "silver"),
    ),
)
def test_tier_scoped_v2_action_templates_still_reject_cross_tier(
    source_tier: str,
    action_template: str,
    target_tier: str,
) -> None:
    context = CORE7_CONTEXTS[0]
    result = validate_verdict_for_persistence(
        _verdict(context, action_template),
        target_tier,
        _pack(context, target_tier),
        f"validator-v2-action-parity:{source_tier}-as-{target_tier}",
    )

    assert result.passed is False
    assert "imperative_close" in _gate_names(result), [
        asdict(failure) for failure in result.failures
    ]
