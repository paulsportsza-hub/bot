"""BUILD-EDGE-RECOMPUTE-01 — Contract tests for odds-change recompute queue.

Verifies:
1. _drain_recompute_queue() reads and clears the queue file
2. Duplicate (match_id, market_type) pairs are de-duplicated
3. _queue_recompute() in runner.py writes when implied probability shift >= 1.5%
4. _queue_recompute() does NOT write when shift < 1.5%
"""
import os
import sys
import time
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ── Stub heavy scraper deps so runner.py can be imported in test context ─────

def _stub_heavy_deps():
    """Mock out modules that require runtime services (proxies, websockets, etc.)."""
    stubs = [
        "websockets",
        "scrapers.bookmakers.hollywoodbets",
        "scrapers.bookmakers.gbets",
        "scrapers.bookmakers.wsb",
        "scrapers.bookmakers.supabets",
        "scrapers.bookmakers.betway",
        "scrapers.bookmakers.sportingbet",
        "scrapers.bookmakers.playabets",
        "scrapers.bookmakers.supersportbet",
        "scrapers.bookmakers",
        "scrapers.deeplinks.link_store",
        "scrapers.deeplinks.resolvers",
        "scrapers.deeplinks",
        "scrapers.odds_integrity",
    ]
    for name in stubs:
        if name not in sys.modules:
            sys.modules[name] = MagicMock()

    # Patch the BRIGHTDATA_PROXY check if hollywoodbets was already imported with error
    os.environ.setdefault("BRIGHTDATA_PROXY", "http://dummy:dummy@proxy:22225")


# ── _drain_recompute_queue tests ─────────────────────────────────────────────

class TestDrainRecomputeQueue:
    def test_returns_empty_list_when_file_missing(self, tmp_path):
        queue_file = tmp_path / "edge_recompute_queue.txt"
        import bot
        original = bot._RECOMPUTE_QUEUE
        bot._RECOMPUTE_QUEUE = queue_file
        try:
            result = bot._drain_recompute_queue()
        finally:
            bot._RECOMPUTE_QUEUE = original
        assert result == []

    def test_drains_and_clears_queue(self, tmp_path):
        queue_file = tmp_path / "edge_recompute_queue.txt"
        ts = int(time.time())
        queue_file.write_text(
            f"chiefs_vs_pirates_2026-04-20|1x2|{ts}\n"
            f"sundowns_vs_swallows_2026-04-21|1x2|{ts}\n"
        )
        import bot
        original = bot._RECOMPUTE_QUEUE
        bot._RECOMPUTE_QUEUE = queue_file
        try:
            result = bot._drain_recompute_queue()
        finally:
            bot._RECOMPUTE_QUEUE = original

        assert len(result) == 2
        assert ("chiefs_vs_pirates_2026-04-20", "1x2") in result
        assert ("sundowns_vs_swallows_2026-04-21", "1x2") in result
        # Queue file must be cleared
        assert queue_file.read_text() == ""

    def test_deduplicates_same_match_market(self, tmp_path):
        queue_file = tmp_path / "edge_recompute_queue.txt"
        ts = int(time.time())
        queue_file.write_text(
            f"chiefs_vs_pirates_2026-04-20|1x2|{ts}\n"
            f"chiefs_vs_pirates_2026-04-20|1x2|{ts + 5}\n"  # duplicate
            f"chiefs_vs_pirates_2026-04-20|over_under_2.5|{ts}\n"  # different market
        )
        import bot
        original = bot._RECOMPUTE_QUEUE
        bot._RECOMPUTE_QUEUE = queue_file
        try:
            result = bot._drain_recompute_queue()
        finally:
            bot._RECOMPUTE_QUEUE = original

        assert len(result) == 2
        assert ("chiefs_vs_pirates_2026-04-20", "1x2") in result
        assert ("chiefs_vs_pirates_2026-04-20", "over_under_2.5") in result

    def test_returns_empty_list_for_empty_file(self, tmp_path):
        queue_file = tmp_path / "edge_recompute_queue.txt"
        queue_file.write_text("")
        import bot
        original = bot._RECOMPUTE_QUEUE
        bot._RECOMPUTE_QUEUE = queue_file
        try:
            result = bot._drain_recompute_queue()
        finally:
            bot._RECOMPUTE_QUEUE = original
        assert result == []

    def test_skips_malformed_lines(self, tmp_path):
        queue_file = tmp_path / "edge_recompute_queue.txt"
        ts = int(time.time())
        queue_file.write_text(
            f"chiefs_vs_pirates_2026-04-20|1x2|{ts}\n"
            "MALFORMED_LINE_NO_PIPE\n"
        )
        import bot
        original = bot._RECOMPUTE_QUEUE
        bot._RECOMPUTE_QUEUE = queue_file
        try:
            result = bot._drain_recompute_queue()
        finally:
            bot._RECOMPUTE_QUEUE = original

        assert len(result) == 1
        assert ("chiefs_vs_pirates_2026-04-20", "1x2") in result


# ── _queue_recompute (scraper side) tests ────────────────────────────────────

class TestQueueRecompute:
    def _import_runner(self):
        """Import scrapers.runner with all heavy deps stubbed."""
        _stub_heavy_deps()
        import scrapers.runner as runner
        return runner

    def _run(self, tmp_path, old_odds, new_odds, market="1x2"):
        queue_file = tmp_path / "edge_recompute_queue.txt"
        runner = self._import_runner()
        original = runner._RECOMPUTE_QUEUE
        runner._RECOMPUTE_QUEUE = str(queue_file)
        try:
            runner._queue_recompute("arsenal_vs_chelsea_2026-04-20", market, old_odds, new_odds)
        finally:
            runner._RECOMPUTE_QUEUE = original
        return queue_file

    def test_writes_when_shift_exceeds_threshold(self, tmp_path):
        # 2.00 → 1.80: implied 50% → 55.6% = 5.6% shift — above 1.5%
        queue_file = self._run(tmp_path, old_odds=2.00, new_odds=1.80)
        content = queue_file.read_text()
        assert "arsenal_vs_chelsea_2026-04-20" in content
        assert "1x2" in content

    def test_no_write_when_shift_below_threshold(self, tmp_path):
        # 2.00 → 1.98: implied 50% → 50.5% = 0.5% shift — below 1.5%
        queue_file = self._run(tmp_path, old_odds=2.00, new_odds=1.98)
        assert not queue_file.exists() or queue_file.read_text() == ""

    def test_no_write_when_both_odds_zero(self, tmp_path):
        # Both zero: old_impl=0, new_impl=0, no shift
        queue_file = self._run(tmp_path, old_odds=0, new_odds=0)
        assert not queue_file.exists() or queue_file.read_text() == ""

    def test_writes_over_under_market(self, tmp_path):
        # Over/under significant movement
        queue_file = self._run(tmp_path, old_odds=1.90, new_odds=1.65, market="over_under_2.5")
        content = queue_file.read_text()
        assert "over_under_2.5" in content

    def test_threshold_boundary_exact(self, tmp_path):
        # Exactly 1.5% shift — should write (>= threshold)
        runner = self._import_runner()
        old_impl = 0.50
        new_impl = old_impl + runner._MIN_IMPLIED_SHIFT
        new_odds = 1.0 / new_impl
        queue_file = self._run(tmp_path, old_odds=2.00, new_odds=new_odds)
        content = queue_file.read_text() if queue_file.exists() else ""
        assert "arsenal_vs_chelsea_2026-04-20" in content
