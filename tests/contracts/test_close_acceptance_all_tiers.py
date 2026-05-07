from __future__ import annotations

from dataclasses import asdict

import pytest

from narrative_validator import validate_verdict_for_persistence


BASE_CONTEXT = {
    "match_key": "liverpool_vs_chelsea_2026-05-07",
    "sport": "soccer",
    "league": "epl",
    "home_team": "Liverpool",
    "away_team": "Chelsea",
    "team": "Liverpool",
    "nickname": "the Reds",
}


TIER_ACCEPTANCE_CASES = {
    "diamond": (
        "Back {team}, full stake.",
        "{team} is the play, full stake.",
        "Hard to look past {team}, go big at 1.91 on Supabets.",
    ),
    "gold": (
        "Back {team}, standard stake.",
        "{team} is the play, standard stake.",
        "{team} is the play, standard stake!",
    ),
    "silver": (
        "Lean {team}, standard stake.",
        "{team} gets the nod, standard stake.",
        "{team} gets the nod, standard stake!",
    ),
    "bronze": (
        "Worth a small play on {team}, light stake.",
        "Small lean to {team}, light stake.",
        "Worth a measured punt on {team}, light stake.",
    ),
}


TIER_NEGATIVE_CASES = {
    "diamond": "{team} go nuts, full stake.",
    "gold": "{team} fire away, standard stake.",
    "silver": "{team} call it now, standard stake.",
    "bronze": "{team} maybe worth it, light stake.",
}


def _pack(tier: str) -> dict[str, object]:
    return {
        "match_id": BASE_CONTEXT["match_key"],
        "match_key": BASE_CONTEXT["match_key"],
        "home_team": BASE_CONTEXT["home_team"],
        "away_team": BASE_CONTEXT["away_team"],
        "recommended_team": BASE_CONTEXT["team"],
        "outcome_label": BASE_CONTEXT["team"],
        "sport": BASE_CONTEXT["sport"],
        "league": BASE_CONTEXT["league"],
        "recommended_odds": 1.91,
        "odds": 1.91,
        "bookmaker": "Supabets",
        "edge_tier": tier,
        "nickname": BASE_CONTEXT["nickname"],
        "signals": {
            "price_edge": {"available": True},
            "form_h2h": {"available": True},
            "lineup_injury": {"available": True},
            "movement": {"available": True, "direction": "toward"},
            "market_agreement": {"available": True, "bookmaker_count": 4},
            "tipster": {"available": True},
        },
    }


def _verdict(action_template: str) -> str:
    team = BASE_CONTEXT["team"]
    action = action_template.format(team=team)
    return (
        f"{team} at 1.91 with Supabets -- "
        f"the price still looks playable for {team}. {action}"
    )


def _gate_names(result) -> set[str]:
    return {failure.gate for failure in result.failures}


@pytest.mark.parametrize(
    ("tier", "action_template"),
    [
        (tier, action_template)
        for tier, action_templates in TIER_ACCEPTANCE_CASES.items()
        for action_template in action_templates
    ],
)
def test_all_tier_close_acceptance(tier: str, action_template: str) -> None:
    result = validate_verdict_for_persistence(
        _verdict(action_template),
        tier,
        _pack(tier),
        "close-acceptance-all-tiers",
    )

    assert result.passed, [asdict(failure) for failure in result.failures]


@pytest.mark.parametrize("tier", ("diamond", "gold", "silver", "bronze"))
def test_per_tier_unknown_close_still_fails_gate_9(tier: str) -> None:
    result = validate_verdict_for_persistence(
        _verdict(TIER_NEGATIVE_CASES[tier]),
        tier,
        _pack(tier),
        "close-acceptance-all-tiers:negative",
    )

    assert result.passed is False
    assert "imperative_close" in _gate_names(result), [
        asdict(failure) for failure in result.failures
    ]


def test_diamond_close_shape_fails_silver_context() -> None:
    result = validate_verdict_for_persistence(
        _verdict("{team} is the play, full stake."),
        "silver",
        _pack("silver"),
        "close-acceptance-all-tiers:cross-tier",
    )

    assert result.passed is False
    assert "imperative_close" in _gate_names(result), [
        asdict(failure) for failure in result.failures
    ]
