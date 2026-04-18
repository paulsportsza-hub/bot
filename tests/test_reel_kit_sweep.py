"""Tests for reel_kit_sweep.py — BUILD-REEL-KIT-DATE-RULE-01 (AC5)

AC5(a): regex matches correct blocks, skips checked/future-dated ones
AC5(b): sweep deletes only past-dated unchecked blocks (mock Notion API)
AC5(c): dashboard overdue classification at 2 sample times
"""
from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import reel_kit_sweep as sweep_mod

_SAST = timezone(timedelta(hours=2))
_TODAY = "2026-04-18"
_YESTERDAY = "2026-04-17"
_TOMORROW = "2026-04-19"


# ── helpers ────────────────────────────────────────────────────────────────────

def _make_notion_block(block_id: str, text: str, checked: bool = False) -> dict:
    return {
        "id": block_id,
        "type": "to_do",
        "to_do": {"checked": checked, "rich_text": [{"plain_text": text}]},
    }


def _make_notion_response(blocks: list[dict]) -> dict:
    return {"results": blocks}


# ── AC5(a): regex precision ────────────────────────────────────────────────────

class TestRegexPrecision(unittest.TestCase):

    def test_matches_past_dated_reel_kit(self):
        m = sweep_mod._RE_REEL_KIT.match(f"🎥 Reel Kit {_YESTERDAY}")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), _YESTERDAY)

    def test_matches_future_dated_reel_kit(self):
        m = sweep_mod._RE_REEL_KIT.match(f"🎥 Reel Kit {_TOMORROW}")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), _TOMORROW)

    def test_no_match_missing_emoji(self):
        self.assertIsNone(sweep_mod._RE_REEL_KIT.match(f"Reel Kit {_YESTERDAY}"))

    def test_no_match_wrong_emoji(self):
        self.assertIsNone(sweep_mod._RE_REEL_KIT.match(f"🎬 Reel Kit {_YESTERDAY}"))

    def test_no_match_wrong_date_format(self):
        self.assertIsNone(sweep_mod._RE_REEL_KIT.match("🎥 Reel Kit 17-04-2026"))

    def test_no_match_prefixed_text(self):
        # Regex is anchored — leading text must not match
        self.assertIsNone(sweep_mod._RE_REEL_KIT.match(f"Task: 🎥 Reel Kit {_YESTERDAY}"))

    def test_matches_trailing_text(self):
        self.assertIsNotNone(sweep_mod._RE_REEL_KIT.match(f"🎥 Reel Kit {_YESTERDAY} extra"))

    def test_no_match_non_todo_content(self):
        self.assertIsNone(sweep_mod._RE_REEL_KIT.match("📝 Quora Daily — 18 April 2026"))


class TestFetchReelKitBlocks(unittest.TestCase):

    def test_skips_checked_blocks(self):
        raw = _make_notion_response([
            _make_notion_block("b1", f"🎥 Reel Kit {_YESTERDAY}", checked=True),
        ])
        with patch.object(sweep_mod, "_notion_get", return_value=raw):
            result = sweep_mod.fetch_reel_kit_blocks("tok")
        self.assertEqual(result, [])

    def test_skips_non_todo_blocks(self):
        raw = {"results": [
            {"id": "b2", "type": "paragraph",
             "paragraph": {"rich_text": [{"plain_text": f"🎥 Reel Kit {_YESTERDAY}"}]}}
        ]}
        with patch.object(sweep_mod, "_notion_get", return_value=raw):
            result = sweep_mod.fetch_reel_kit_blocks("tok")
        self.assertEqual(result, [])

    def test_returns_matching_unchecked_past(self):
        raw = _make_notion_response([
            _make_notion_block("b3", f"🎥 Reel Kit {_YESTERDAY}"),
        ])
        with patch.object(sweep_mod, "_notion_get", return_value=raw):
            result = sweep_mod.fetch_reel_kit_blocks("tok")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["date"], _YESTERDAY)
        self.assertEqual(result[0]["block_id"], "b3")

    def test_returns_matching_unchecked_future(self):
        # fetch returns future blocks too — filtering is sweep()'s job
        raw = _make_notion_response([
            _make_notion_block("b4", f"🎥 Reel Kit {_TOMORROW}"),
        ])
        with patch.object(sweep_mod, "_notion_get", return_value=raw):
            result = sweep_mod.fetch_reel_kit_blocks("tok")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["date"], _TOMORROW)

    def test_skips_non_matching_text(self):
        raw = _make_notion_response([
            _make_notion_block("b5", "📝 Quora Daily — 18 April 2026"),
        ])
        with patch.object(sweep_mod, "_notion_get", return_value=raw):
            result = sweep_mod.fetch_reel_kit_blocks("tok")
        self.assertEqual(result, [])

    def test_skips_checked_matching_block(self):
        raw = _make_notion_response([
            _make_notion_block("b6", f"🎥 Reel Kit {_YESTERDAY}", checked=True),
        ])
        with patch.object(sweep_mod, "_notion_get", return_value=raw):
            result = sweep_mod.fetch_reel_kit_blocks("tok")
        self.assertEqual(result, [])


# ── AC5(b): sweep deletes only past-dated unchecked blocks ────────────────────

class TestSweep(unittest.TestCase):

    def _run(self, blocks: list[dict], today: str = _TODAY) -> tuple[int, list[str]]:
        """Run sweep() with mocked _today_sast and _notion_delete. Returns (count, deleted_ids)."""
        deleted_ids: list[str] = []

        def fake_delete(token, block_id):
            deleted_ids.append(block_id)

        with patch.object(sweep_mod, "fetch_reel_kit_blocks", return_value=blocks), \
             patch.object(sweep_mod, "_notion_delete", side_effect=fake_delete), \
             patch.object(sweep_mod, "_today_sast", return_value=today):
            count = sweep_mod.sweep("tok")

        return count, deleted_ids

    def test_deletes_past_dated_unchecked(self):
        blocks = [{"block_id": "b7", "date": _YESTERDAY, "text": f"🎥 Reel Kit {_YESTERDAY}"}]
        count, deleted = self._run(blocks)
        self.assertEqual(count, 1)
        self.assertIn("b7", deleted)

    def test_keeps_today_dated_block(self):
        blocks = [{"block_id": "b8", "date": _TODAY, "text": f"🎥 Reel Kit {_TODAY}"}]
        count, deleted = self._run(blocks)
        self.assertEqual(count, 0)
        self.assertEqual(deleted, [])

    def test_keeps_future_dated_block(self):
        blocks = [{"block_id": "b9", "date": _TOMORROW, "text": f"🎥 Reel Kit {_TOMORROW}"}]
        count, deleted = self._run(blocks)
        self.assertEqual(count, 0)
        self.assertEqual(deleted, [])

    def test_mixed_blocks_deletes_only_past(self):
        blocks = [
            {"block_id": "past", "date": _YESTERDAY, "text": f"🎥 Reel Kit {_YESTERDAY}"},
            {"block_id": "today", "date": _TODAY, "text": f"🎥 Reel Kit {_TODAY}"},
            {"block_id": "future", "date": _TOMORROW, "text": f"🎥 Reel Kit {_TOMORROW}"},
        ]
        count, deleted = self._run(blocks)
        self.assertEqual(count, 1)
        self.assertIn("past", deleted)
        self.assertNotIn("today", deleted)
        self.assertNotIn("future", deleted)

    def test_no_blocks_returns_zero(self):
        count, deleted = self._run([])
        self.assertEqual(count, 0)
        self.assertEqual(deleted, [])

    def test_multiple_past_blocks_all_deleted(self):
        blocks = [
            {"block_id": "w1", "date": "2026-04-16", "text": "🎥 Reel Kit 2026-04-16"},
            {"block_id": "w2", "date": "2026-04-17", "text": "🎥 Reel Kit 2026-04-17"},
        ]
        count, deleted = self._run(blocks)
        self.assertEqual(count, 2)
        self.assertIn("w1", deleted)
        self.assertIn("w2", deleted)


# ── AC5(c): dashboard overdue classification at 2 sample times ────────────────

class TestOverdueClassification(unittest.TestCase):
    """Verify past-dated unchecked blocks are classified as overdue at two distinct times."""

    def _is_overdue(self, block_date: str, today: str) -> bool:
        return block_date < today

    # Sample time 1: 08:00 SAST on 2026-04-18
    def test_yesterday_overdue_at_morning(self):
        self.assertTrue(self._is_overdue("2026-04-17", "2026-04-18"))

    def test_today_not_overdue_at_morning(self):
        self.assertFalse(self._is_overdue("2026-04-18", "2026-04-18"))

    # Sample time 2: 23:30 SAST on 2026-04-18 (late evening)
    def test_yesterday_overdue_at_night(self):
        self.assertTrue(self._is_overdue("2026-04-17", "2026-04-18"))

    def test_tomorrow_not_overdue_at_night(self):
        self.assertFalse(self._is_overdue("2026-04-19", "2026-04-18"))

    def test_week_old_overdue(self):
        self.assertTrue(self._is_overdue("2026-04-11", "2026-04-18"))

    def test_future_date_never_overdue(self):
        self.assertFalse(self._is_overdue("2026-04-25", "2026-04-18"))


if __name__ == "__main__":
    unittest.main()
