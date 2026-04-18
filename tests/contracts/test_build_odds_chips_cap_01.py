"""BUILD-ODDS-CHIPS-CAP-01 contract: cap all_odds at 3 chips + dedup bookmakers.

Three fixes:
  Fix 1 (bot.py):      (_pick_chips + _other_chips)[:3]  — not _other_chips[:3]
  Fix 2 (card_data.py): _max_bk = 3  — not width-conditional 4/3/2
  Fix 3 (bot.py):      dedup by display name before chip selection

Regression guards:
  - For any tip with 4+ bookmakers, all_odds length <= 3
  - No duplicate bookie values in all_odds
"""
from __future__ import annotations

import inspect
import pathlib
import sys

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT.parent))

import bot
import card_data


def _enrich_source() -> str:
    return inspect.getsource(bot._enrich_tip_for_card)


class TestOddsChipsCap:
    """Source-level contracts for the three chip-overflow fixes."""

    def test_fix1_cap_applied_to_combined_list(self) -> None:
        """Cap must apply to the merged list, not just _other_chips."""
        src = _enrich_source()
        assert "(_pick_chips + _other_chips)[:3]" in src, (
            "Fix 1 missing: must be (_pick_chips + _other_chips)[:3], "
            "not _pick_chips + _other_chips[:3]"
        )
        assert "_pick_chips + _other_chips[:3]" not in src, (
            "Old broken pattern still present: _pick_chips + _other_chips[:3] "
            "allows a 4th chip when pick is present + 3 others"
        )

    def test_fix2_max_bk_capped_at_3_in_card_data(self) -> None:
        """card_data._build_odds_chips_row must use _max_bk = 3, not width-conditional."""
        src = inspect.getsource(card_data)
        assert "_max_bk = 3" in src, (
            "Fix 2 missing: card_data must have _max_bk = 3 (UX contract)"
        )
        assert "_max_bk = 4 if card_width" not in src, (
            "Old width-conditional _max_bk still present — must be fixed to 3"
        )

    def test_fix3_dedup_block_present(self) -> None:
        """Dedup block must appear before chip selection in _enrich_tip_for_card."""
        src = _enrich_source()
        assert "_seen_bk" in src, (
            "Fix 3 missing: dedup dict _seen_bk not found in _enrich_tip_for_card"
        )
        # Dedup must precede chip selection
        dedup_idx = src.find("_seen_bk")
        chip_idx = src.find("_pick_chips")
        assert dedup_idx < chip_idx, (
            "Fix 3: dedup (_seen_bk) must appear BEFORE chip selection (_pick_chips)"
        )

    def test_fix3_dedup_keeps_highest_odds(self) -> None:
        """Dedup logic must keep the highest odds per bookmaker."""
        src = _enrich_source()
        assert 'o["odds"] > _seen_bk[bk]["odds"]' in src, (
            "Fix 3: dedup must keep highest odds per bookmaker"
        )


class TestChipInvariants:
    """Functional tests: verify the invariants hold with synthetic tip data.

    These tests replicate the chip-selection logic directly so they do not
    require a live DB connection.
    """

    def _run_chip_selection(self, all_odds: list[dict]) -> list[dict]:
        """Mirror the fixed chip-selection logic from _enrich_tip_for_card."""
        # Fix 3: dedup by display name, keep highest odds per bookmaker
        seen_bk: dict[str, dict] = {}
        for o in all_odds:
            bk = o["bookie"]
            if bk not in seen_bk or o["odds"] > seen_bk[bk]["odds"]:
                seen_bk[bk] = o
        all_odds = list(seen_bk.values())

        # Fix 1: cap combined list at 3
        pick_chips = [o for o in all_odds if o.get("is_pick")]
        other_chips = [o for o in all_odds if not o.get("is_pick")]
        other_chips.sort(key=lambda x: x["odds"])
        return (pick_chips + other_chips)[:3]

    def test_four_distinct_bookmakers_capped_at_3(self) -> None:
        """4 distinct bookmakers → at most 3 chips rendered."""
        odds = [
            {"bookie": "HWB", "odds": 2.0},
            {"bookie": "GBets", "odds": 2.1},
            {"bookie": "Betway", "odds": 2.05, "is_pick": True},
            {"bookie": "Sportingbet", "odds": 1.95},
        ]
        result = self._run_chip_selection(odds)
        assert len(result) <= 3, f"Expected ≤ 3 chips, got {len(result)}"

    def test_five_bookmakers_capped_at_3(self) -> None:
        """5 bookmakers → exactly 3 chips."""
        odds = [
            {"bookie": "HWB", "odds": 2.0},
            {"bookie": "GBets", "odds": 2.1},
            {"bookie": "Betway", "odds": 2.05},
            {"bookie": "Sportingbet", "odds": 1.95},
            {"bookie": "Supabets", "odds": 2.08},
        ]
        result = self._run_chip_selection(odds)
        assert len(result) <= 3, f"Expected ≤ 3 chips, got {len(result)}"

    def test_pick_plus_three_others_capped_at_3(self) -> None:
        """Pick bookmaker + 3 others must NOT produce 4 chips (was the bug)."""
        odds = [
            {"bookie": "Betway", "odds": 2.10, "is_pick": True},
            {"bookie": "HWB", "odds": 1.90},
            {"bookie": "GBets", "odds": 2.00},
            {"bookie": "Sportingbet", "odds": 1.85},
        ]
        result = self._run_chip_selection(odds)
        assert len(result) <= 3, (
            f"Pick + 3 others produced {len(result)} chips — cap must apply to combined list"
        )

    def test_no_duplicate_bookmakers_in_result(self) -> None:
        """No bookie value should appear more than once in the chip list."""
        odds = [
            {"bookie": "HWB", "odds": 2.0},
            {"bookie": "HWB", "odds": 2.3},   # duplicate — higher odds should win
            {"bookie": "GBets", "odds": 1.9},
            {"bookie": "Betway", "odds": 2.05, "is_pick": True},
        ]
        result = self._run_chip_selection(odds)
        bookies = [o["bookie"] for o in result]
        assert len(bookies) == len(set(bookies)), (
            f"Duplicate bookmakers in chip list: {bookies}"
        )

    def test_dedup_keeps_higher_odds(self) -> None:
        """When a bookie appears twice, the higher-odds entry is kept."""
        odds = [
            {"bookie": "HWB", "odds": 1.80},
            {"bookie": "HWB", "odds": 2.20},  # higher — should survive
        ]
        result = self._run_chip_selection(odds)
        assert len(result) == 1
        assert result[0]["odds"] == 2.20, "Dedup must retain the higher odds entry"

    def test_two_bookmakers_unchanged(self) -> None:
        """Fewer than 4 distinct bookmakers renders all of them."""
        odds = [
            {"bookie": "HWB", "odds": 2.0},
            {"bookie": "GBets", "odds": 1.9},
        ]
        result = self._run_chip_selection(odds)
        assert len(result) == 2
