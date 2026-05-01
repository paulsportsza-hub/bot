from __future__ import annotations

import os
import sys


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from card_data import _allocate_tips_by_tier


def _tips(tier: str, count: int, start: int = 0) -> list[dict]:
    return [
        {
            "id": f"{tier}-{idx}",
            "edge_tier": tier,
            "ev": 100 - start - idx,
        }
        for idx in range(start, start + count)
    ]


def _ids(tips: list[dict]) -> list[str]:
    return [tip["id"] for tip in tips]


def _tier_count(tips: list[dict], tier: str) -> int:
    return len([tip for tip in tips if tip["edge_tier"] == tier])


def test_allocator_empty_tips_returns_empty_list() -> None:
    assert _allocate_tips_by_tier([]) == []


def test_allocator_single_tier_returns_available_tips_in_order() -> None:
    tips = _tips("bronze", 5)

    allocated = _allocate_tips_by_tier(tips, min_per_tier=3)

    assert allocated == tips


def test_allocator_empty_middle_tier_does_not_reserve_slots() -> None:
    tips = _tips("diamond", 5) + _tips("bronze", 5)

    allocated = _allocate_tips_by_tier(tips, min_per_tier=3)

    assert len(allocated) == 10
    assert _tier_count(allocated, "diamond") == 5
    assert _tier_count(allocated, "bronze") == 5


def test_allocator_all_diamond_keeps_flat_target_cap() -> None:
    tips = _tips("diamond", 12)

    allocated = _allocate_tips_by_tier(tips, min_per_tier=3)

    assert _ids(allocated) == [f"diamond-{idx}" for idx in range(10)]


def test_allocator_balanced_tiers_reserves_three_per_non_empty_tier() -> None:
    tips = (
        _tips("diamond", 4)
        + _tips("gold", 4)
        + _tips("silver", 4)
        + _tips("bronze", 4)
    )

    allocated = _allocate_tips_by_tier(tips, min_per_tier=3)

    assert len(allocated) == 12
    assert _ids(allocated) == [
        "diamond-0",
        "diamond-1",
        "diamond-2",
        "gold-0",
        "gold-1",
        "gold-2",
        "silver-0",
        "silver-1",
        "silver-2",
        "bronze-0",
        "bronze-1",
        "bronze-2",
    ]


def test_allocator_mixed_tiers_fills_remaining_from_global_tier_order() -> None:
    tips = _tips("diamond", 5) + _tips("gold", 1) + _tips("bronze", 5)

    allocated = _allocate_tips_by_tier(tips, min_per_tier=3)

    assert _ids(allocated) == [
        "diamond-0",
        "diamond-1",
        "diamond-2",
        "gold-0",
        "bronze-0",
        "bronze-1",
        "bronze-2",
        "diamond-3",
        "diamond-4",
        "bronze-3",
    ]


def test_allocator_real_ratio_keeps_silver_and_bronze_coverage() -> None:
    tips = (
        _tips("diamond", 20)
        + _tips("gold", 16)
        + _tips("silver", 4)
        + _tips("bronze", 4)
    )

    allocated = _allocate_tips_by_tier(tips, min_per_tier=3)

    assert len(allocated) == 12
    assert _tier_count(allocated, "diamond") == 3
    assert _tier_count(allocated, "gold") == 3
    assert _tier_count(allocated, "silver") == 3
    assert _tier_count(allocated, "bronze") == 3
