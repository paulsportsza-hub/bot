"""Tier-specific journey coverage for list gating and detail CTAs."""

from __future__ import annotations

import asyncio

import pytest

import bot
from tier_gate import get_edge_access_level, get_upgrade_message, user_can_access_edge


def _tip(
    display_tier: str, *, edge_score: int, odds: float = 2.1, outcome: str = "Home"
) -> dict:
    return {
        "match_id": f"{display_tier}_{edge_score}_{odds}",
        "event_id": f"{display_tier}_{edge_score}_{odds}",
        "home_team": f"{display_tier.title()} Home",
        "away_team": f"{display_tier.title()} Away",
        "league": "Test League",
        "league_key": "test",
        "sport_key": "soccer_epl",
        "commence_time": "2026-03-29T15:30:00Z",
        "outcome": outcome,
        "odds": odds,
        "bookmaker": "Hollywoodbets",
        "bookmaker_key": "hollywoodbets",
        "odds_by_bookmaker": {"hollywoodbets": odds, "betway": max(odds - 0.05, 1.5)},
        "ev": 5.5,
        "prob": 54,
        "kelly": 2.4,
        "edge_rating": display_tier,
        "display_tier": display_tier,
        "edge_score": edge_score,
        "edge_v2": {"confirming_signals": 2},
    }


def _callbacks(markup) -> list[str]:
    return [
        btn.callback_data
        for row in markup.inline_keyboard
        for btn in row
        if getattr(btn, "callback_data", None)
    ]


@pytest.mark.parametrize(
    ("user_tier", "edge_tier", "expected"),
    [
        ("diamond", "diamond", "full"),
        ("diamond", "gold", "full"),
        ("diamond", "silver", "full"),
        ("diamond", "bronze", "full"),
        ("gold", "diamond", "blurred"),
        ("gold", "gold", "full"),
        ("gold", "silver", "full"),
        ("gold", "bronze", "full"),
        ("bronze", "diamond", "locked"),
        ("bronze", "gold", "blurred"),
        ("bronze", "silver", "partial"),
        ("bronze", "bronze", "full"),
    ],
)
def test_access_matrix_matches_product_rules(
    user_tier: str, edge_tier: str, expected: str
) -> None:
    assert get_edge_access_level(user_tier, edge_tier) == expected


@pytest.mark.parametrize(
    ("user_tier", "edge_tier", "expected"),
    [
        ("diamond", "diamond", True),
        ("diamond", "gold", True),
        ("gold", "gold", True),
        ("gold", "diamond", False),
        ("bronze", "silver", True),
        ("bronze", "gold", False),
    ],
)
def test_user_can_access_edge_matches_full_and_partial_rules(
    user_tier: str,
    edge_tier: str,
    expected: bool,
) -> None:
    assert user_can_access_edge(user_tier, edge_tier) is expected


def test_bronze_list_shows_locked_diamond_copy() -> None:
    text, _, _ = asyncio.run(bot._build_hot_tips_page(
        [_tip("diamond", edge_score=62)], user_tier="bronze"
    ))
    assert "Our highest-conviction pick." in text
    assert "@ 2.10" not in text


def test_bronze_list_shows_return_not_odds_for_gold() -> None:
    text, _, _ = asyncio.run(bot._build_hot_tips_page(
        [_tip("gold", edge_score=45, odds=2.15)], user_tier="bronze"
    ))
    assert "return on R300" in text
    assert "@ 2.15" not in text


def test_gold_list_blurs_diamond_but_keeps_card_visible() -> None:
    text, markup, _ = asyncio.run(bot._build_hot_tips_page(
        [_tip("diamond", edge_score=62, odds=1.85)], user_tier="gold"
    ))
    assert "Diamond Home vs Diamond Away" in text
    assert "return on R300" in text
    assert "@ 1.85" not in text
    assert any(cb.startswith("hot:upgrade:") for cb in _callbacks(markup))


def test_diamond_list_has_no_upgrade_cta() -> None:
    _, markup, _ = asyncio.run(bot._build_hot_tips_page(
        [_tip("diamond", edge_score=62)], user_tier="diamond"
    ))
    assert not any(cb.startswith("hot:upgrade:") for cb in _callbacks(markup))


def test_bronze_detail_cta_turns_into_view_plans_for_gold_edge() -> None:
    rows = bot._build_game_buttons(
        [_tip("gold", edge_score=45)],
        event_id="gold_edge",
        user_id=1,
        source="edge_picks",
        user_tier="bronze",
        edge_tier="gold",
    )
    assert rows[0][0].text == "📋 View Plans"
    assert rows[0][0].callback_data == "sub:plans"


def test_bronze_detail_cta_keeps_real_bookmaker_for_silver_edge() -> None:
    rows = bot._build_game_buttons(
        [_tip("silver", edge_score=39, odds=3.2, outcome="Silver Home")],
        event_id="silver_edge",
        user_id=1,
        source="edge_picks",
        user_tier="bronze",
        edge_tier="silver",
        selected_outcome="Silver Home",
    )
    assert rows[0][0].text.startswith("🥈 Back Silver Home @ 3.20 on HWB")
    assert rows[0][0].url


def test_gold_detail_cta_turns_into_view_plans_for_diamond_edge() -> None:
    rows = bot._build_game_buttons(
        [_tip("diamond", edge_score=62)],
        event_id="diamond_edge",
        user_id=1,
        source="edge_picks",
        user_tier="gold",
        edge_tier="diamond",
    )
    assert rows[0][0].callback_data == "sub:plans"


def test_upgrade_message_contains_gold_pricing() -> None:
    text = get_upgrade_message("bronze", context="gold_edge")
    assert "R99/mo" in text
    assert "/subscribe" in text


def test_upgrade_message_contains_diamond_pricing() -> None:
    text = get_upgrade_message("bronze", context="diamond_edge")
    assert "R199/mo" in text
    assert "/subscribe" in text


def test_composite_score_below_threshold_is_hidden_not_mis_tiered() -> None:
    visible = _tip("gold", edge_score=45)
    hidden = _tip("silver", edge_score=39)
    text, _, _ = asyncio.run(bot._build_hot_tips_page([visible, hidden], user_tier="diamond"))
    assert "Gold Home vs Gold Away" in text
    assert "Silver Home vs Silver Away" not in text


def test_tier_badge_in_list_matches_visible_diamond_card() -> None:
    text, _, _ = asyncio.run(bot._build_hot_tips_page(
        [_tip("diamond", edge_score=62)], user_tier="diamond"
    ))
    assert "💎" in text


def test_tier_badge_in_list_matches_visible_gold_card() -> None:
    text, _, _ = asyncio.run(bot._build_hot_tips_page(
        [_tip("gold", edge_score=45)], user_tier="diamond"
    ))
    assert "🥇" in text
