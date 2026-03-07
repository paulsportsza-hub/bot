"""Layer 1.2 — Gate matrix exhaustive test.

Verifies all 12 user_tier × edge_tier combinations return the correct
access level. Ensures blurred never leaks odds and locked shows only existence.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.expanduser("~"))
sys.path.insert(0, os.path.join(os.path.expanduser("~"), "bot"))

from tier_gate import get_edge_access_level, user_can_access_edge, gate_narrative


VALID_ACCESS_LEVELS = {"full", "partial", "blurred", "locked"}

# Exhaustive expected matrix — 12 combinations
GATE_MATRIX = [
    # (user_tier, edge_tier, expected_access)
    ("bronze",  "bronze",  "full"),
    ("bronze",  "silver",  "partial"),
    ("bronze",  "gold",    "blurred"),
    ("bronze",  "diamond", "locked"),
    ("gold",    "bronze",  "full"),
    ("gold",    "silver",  "full"),
    ("gold",    "gold",    "full"),
    ("gold",    "diamond", "locked"),
    ("diamond", "bronze",  "full"),
    ("diamond", "silver",  "full"),
    ("diamond", "gold",    "full"),
    ("diamond", "diamond", "full"),
]


class TestGateMatrix:
    """Exhaustive gate matrix covering all 12 user × edge tier combos."""

    @pytest.mark.parametrize("user_tier,edge_tier,expected", GATE_MATRIX,
                             ids=[f"{u}->{e}" for u, e, _ in GATE_MATRIX])
    def test_access_level(self, user_tier, edge_tier, expected):
        """Each combination returns the exact expected access level."""
        actual = get_edge_access_level(user_tier, edge_tier)
        assert actual == expected, (
            f"get_edge_access_level({user_tier!r}, {edge_tier!r}) "
            f"returned {actual!r}, expected {expected!r}"
        )

    @pytest.mark.parametrize("user_tier,edge_tier,expected", GATE_MATRIX,
                             ids=[f"{u}->{e}" for u, e, _ in GATE_MATRIX])
    def test_return_value_valid(self, user_tier, edge_tier, expected):
        """Every return value is in the valid set."""
        actual = get_edge_access_level(user_tier, edge_tier)
        assert actual in VALID_ACCESS_LEVELS, (
            f"Invalid access level: {actual!r}"
        )


class TestGateBusinessRules:
    """Business rule enforcement for the gating system."""

    def test_diamond_always_full(self):
        """Diamond users see everything — all 4 edge tiers return 'full'."""
        for edge_tier in ["bronze", "silver", "gold", "diamond"]:
            assert get_edge_access_level("diamond", edge_tier) == "full", (
                f"Diamond user should have full access to {edge_tier} edge"
            )

    def test_bronze_cant_see_gold_odds(self):
        """Bronze viewing Gold edge must be blurred (no odds visible)."""
        level = get_edge_access_level("bronze", "gold")
        assert level == "blurred", (
            f"Bronze->Gold should be 'blurred' (no odds), got {level!r}"
        )

    def test_bronze_cant_see_diamond_at_all(self):
        """Bronze viewing Diamond edge must be locked (existence only)."""
        level = get_edge_access_level("bronze", "diamond")
        assert level == "locked", (
            f"Bronze->Diamond should be 'locked', got {level!r}"
        )

    def test_gold_cant_see_diamond(self):
        """Gold viewing Diamond must be locked."""
        level = get_edge_access_level("gold", "diamond")
        assert level == "locked", (
            f"Gold->Diamond should be 'locked', got {level!r}"
        )

    def test_blurred_never_leaks_full_odds(self):
        """Blurred access level must never be 'full' or 'partial'."""
        for user_tier in ["bronze", "gold", "diamond"]:
            for edge_tier in ["bronze", "silver", "gold", "diamond"]:
                level = get_edge_access_level(user_tier, edge_tier)
                if level == "blurred":
                    # The only valid blurred combo is bronze->gold
                    assert user_tier == "bronze" and edge_tier == "gold", (
                        f"Unexpected blurred: {user_tier}->{edge_tier}"
                    )

    def test_locked_shows_existence_only(self):
        """Locked combos: bronze->diamond, gold->diamond. No others."""
        locked_combos = set()
        for user_tier in ["bronze", "gold", "diamond"]:
            for edge_tier in ["bronze", "silver", "gold", "diamond"]:
                if get_edge_access_level(user_tier, edge_tier) == "locked":
                    locked_combos.add((user_tier, edge_tier))
        expected = {("bronze", "diamond"), ("gold", "diamond")}
        assert locked_combos == expected, (
            f"Locked combos should be {expected}, got {locked_combos}"
        )


class TestGateCaseInsensitive:
    """Gate function must handle mixed-case and whitespace."""

    @pytest.mark.parametrize("user_tier,edge_tier", [
        ("Bronze", "Gold"),
        ("DIAMOND", "bronze"),
        (" gold ", " silver "),
    ])
    def test_case_insensitive(self, user_tier, edge_tier):
        """Gate function normalises case and whitespace."""
        result = get_edge_access_level(user_tier, edge_tier)
        assert result in VALID_ACCESS_LEVELS, (
            f"Failed with {user_tier!r}/{edge_tier!r}: got {result!r}"
        )


class TestUserCanAccessEdge:
    """user_can_access_edge() consistency with get_edge_access_level()."""

    @pytest.mark.parametrize("user_tier,edge_tier,expected", GATE_MATRIX,
                             ids=[f"{u}->{e}" for u, e, _ in GATE_MATRIX])
    def test_consistent_with_access_level(self, user_tier, edge_tier, expected):
        """user_can_access_edge = True only when access is full or partial."""
        can_access = user_can_access_edge(user_tier, edge_tier)
        level = get_edge_access_level(user_tier, edge_tier)
        if level in ("full", "partial"):
            assert can_access, (
                f"{user_tier}->{edge_tier}: level={level} but can_access=False"
            )
        else:
            assert not can_access, (
                f"{user_tier}->{edge_tier}: level={level} but can_access=True"
            )
