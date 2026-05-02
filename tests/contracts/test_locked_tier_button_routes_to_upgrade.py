from __future__ import annotations

import pytest

from bot import _EDGE_PICKS_INDEX_TIERS, _build_index_markup


PLAN_RANK = {"diamond": 0, "gold": 1, "silver": 2, "bronze": 3}
COUNTS = {"diamond": 1, "gold": 2, "silver": 3, "bronze": 4}


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

    if PLAN_RANK[edge_tier] < PLAN_RANK[user_tier]:
        assert callback_data == f"hot:upgrade:tier:{edge_tier}"
    else:
        assert callback_data == f"hot:tier:{edge_tier}"
