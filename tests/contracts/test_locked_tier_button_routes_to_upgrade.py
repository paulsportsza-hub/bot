from __future__ import annotations

import pytest

from bot import _EDGE_PICKS_INDEX_TIERS, _build_index_markup
from card_data import edge_picks_index_tier_locked


COUNTS = {"diamond": 1, "gold": 2, "silver": 3, "bronze": 4}

# FIX-GOLDEN-LABEL-01: tier picker button must say "Gold" not "Golden"
EXPECTED_TIER_LABELS = {
    "diamond": "Diamond",
    "gold": "Gold",
    "silver": "Silver",
    "bronze": "Bronze",
}


def test_tier_picker_gold_label_not_golden() -> None:
    """Tier picker upgrade button must show 'Gold · Upgrade' not 'Golden · Upgrade'."""
    markup = _build_index_markup("bronze", COUNTS)
    row_index = list(_EDGE_PICKS_INDEX_TIERS).index("gold")
    button_text = markup.inline_keyboard[row_index][0].text
    assert "Gold · " in button_text, f"Expected 'Gold · ' in button text, got: {button_text!r}"
    assert "Golden" not in button_text, f"'Golden' must not appear in tier picker button, got: {button_text!r}"


@pytest.mark.parametrize("tier", list(_EDGE_PICKS_INDEX_TIERS))
def test_tier_picker_labels_use_title_case_not_edge_labels(tier: str) -> None:
    """Tier picker uses plain title-case names, not EDGE_LABELS ('GOLDEN EDGE' etc)."""
    markup = _build_index_markup("bronze", COUNTS)
    row_index = list(_EDGE_PICKS_INDEX_TIERS).index(tier)
    button_text = markup.inline_keyboard[row_index][0].text
    expected_label = EXPECTED_TIER_LABELS[tier]
    assert f"{expected_label} · " in button_text, (
        f"Tier '{tier}': expected label '{expected_label}', got button text: {button_text!r}"
    )
    assert "EDGE" not in button_text, (
        f"Tier picker must not show EDGE_LABELS text ('GOLDEN EDGE' etc): {button_text!r}"
    )


@pytest.mark.parametrize(
    ("user_tier", "edge_tier"),
    [
        (user_tier, edge_tier)
        for user_tier in ("bronze", "silver", "gold")
        for edge_tier in _EDGE_PICKS_INDEX_TIERS
    ],
)
def test_locked_tier_buttons_route_to_upgrade(
    user_tier: str,
    edge_tier: str,
) -> None:
    markup = _build_index_markup(user_tier, COUNTS)
    row_index = list(_EDGE_PICKS_INDEX_TIERS).index(edge_tier)
    callback_data = markup.inline_keyboard[row_index][0].callback_data

    if edge_picks_index_tier_locked(user_tier, edge_tier):
        assert callback_data == f"hot:upgrade:tier:{edge_tier}"
    else:
        assert callback_data == f"hot:tier:{edge_tier}"
