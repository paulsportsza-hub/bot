"""Contract: tier copy canon compliance — BUILD-TIER-COPY-01.

Guards three non-negotiable rules from TIER-COPY-CANON.md:
  1. Bronze must never claim '24h delayed edges'.
  2. Gold must never claim AI breakdowns.
  3. Diamond features list must contain all three pillar phrases.
"""
from card_data_adapters import (
    build_sub_plans_data,
    build_sub_upgrade_gold_data,
    build_sub_upgrade_bronze_data,
)

_DIAMOND_PILLARS = [
    "every edge unlocked",
    "full ai breakdown",
    "personalised alerts",
]


class TestTierCopyCanon:
    def test_bronze_no_delayed_edges(self):
        data = build_sub_plans_data()
        bronze = next(p for p in data["plans"] if p["tier"] == "bronze")
        combined = " ".join(bronze["features"]).lower()
        assert "24h delayed" not in combined, (
            "Bronze features must not claim '24h delayed edges' — access is tier-gated, not time-delayed"
        )
        assert "delayed edges" not in combined

    def test_gold_no_ai_breakdown(self):
        data = build_sub_plans_data()
        gold = next(p for p in data["plans"] if p["tier"] == "gold")
        combined = " ".join(gold["features"]).lower()
        assert "ai breakdown" not in combined, (
            "Gold must not claim AI breakdowns — Full AI Breakdown is Diamond-only"
        )
        assert "ai analysis" not in combined

    def test_diamond_three_pillars_in_plans(self):
        data = build_sub_plans_data()
        diamond = next(p for p in data["plans"] if p["tier"] == "diamond")
        combined = " ".join(diamond["features"]).lower()
        for pillar in _DIAMOND_PILLARS:
            assert pillar in combined, (
                f"Diamond features list missing pillar: {pillar!r}\n"
                f"Features: {diamond['features']}"
            )

    def test_diamond_three_pillars_in_gold_upgrade(self):
        data = build_sub_upgrade_gold_data()
        combined = " ".join(data["features"]).lower()
        for pillar in _DIAMOND_PILLARS:
            assert pillar in combined, (
                f"Gold upgrade Diamond features missing pillar: {pillar!r}\n"
                f"Features: {data['features']}"
            )

    def test_gold_upgrade_has_lock_note(self):
        data = build_sub_upgrade_gold_data()
        assert "lock_note" in data, "build_sub_upgrade_gold_data() must include lock_note"
        assert "diamond edges remain locked" in data["lock_note"].lower()

    def test_bronze_upgrade_diamond_has_features(self):
        data = build_sub_upgrade_bronze_data()
        diamond = next(p for p in data["target_plans"] if p["tier"] == "diamond")
        assert "features" in diamond, "Diamond entry in upgrade_bronze must have features list"
        combined = " ".join(diamond["features"]).lower()
        assert "every edge unlocked" in combined
        assert "full ai breakdown" in combined
        assert "personalised alerts" in combined
