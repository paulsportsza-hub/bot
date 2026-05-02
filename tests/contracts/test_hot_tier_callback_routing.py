from __future__ import annotations

from pathlib import Path

import pytest

from bot import _filter_hot_tips_by_tier


REPO_ROOT = Path(__file__).resolve().parents[2]
BOT_SOURCE = REPO_ROOT / "bot.py"


def _tip(tier: str, idx: int) -> dict:
    return {
        "id": f"{tier}-{idx}",
        "edge_tier": tier,
        "ev": 5.0 + idx,
        "edge_score": 70,
    }


TIPS = [
    _tip("diamond", 1),
    _tip("gold", 1),
    _tip("gold", 2),
    _tip("silver", 1),
    _tip("bronze", 1),
]


@pytest.mark.parametrize(
    ("tier", "expected_ids"),
    [
        ("bronze", ["bronze-1"]),
        ("silver", ["silver-1"]),
        ("gold", ["gold-1", "gold-2"]),
        ("diamond", ["diamond-1"]),
    ],
)
def test_hot_tier_callback_reaches_tier_filtered_list(
    tier: str,
    expected_ids: list[str],
) -> None:
    assert [tip["id"] for tip in _filter_hot_tips_by_tier(TIPS, tier)] == expected_ids


def test_hot_tier_invalid_fallback_and_upgrade_tier_upsell_are_wired() -> None:
    assert _filter_hot_tips_by_tier(TIPS, "invalid") == []

    source = BOT_SOURCE.read_text(encoding="utf-8")
    hot_start = source.index('elif prefix == "hot":')
    hot_end = source.index('elif prefix == "ep":', hot_start)
    hot_block = source[hot_start:hot_end]

    assert 'elif action.startswith("tier:"):' in hot_block
    assert "await _do_hot_tips_flow(query.message.chat_id, ctx.bot, user_id=user_id)" in hot_block
    assert 'elif action == "upgrade" or action.startswith("upgrade:"):' in hot_block
    assert "_upg_requested_tier" in hot_block
    assert 'hot:upgrade:tier:{key}' in source
