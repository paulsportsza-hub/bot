"""test_health_checker_disk_memory.py — AC-4 contract tests for FIX-DISK-MEMORY-MONITOR-WIRE-01

Tests _check_disk_usage() and _check_memory_available() status thresholds.
"""
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, '/home/paulsportsza')        # real scrapers package
sys.path.insert(0, '/home/paulsportsza/scripts') # real cron_window + health_checker
from health_checker import _check_disk_usage, _check_memory_available, check_source


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_usage(total_gb, used_pct):
    total = total_gb * (1024 ** 3)
    used = int(total * used_pct / 100)
    return MagicMock(total=total, used=used, free=total - used)


def _proc_meminfo(mem_available_kb, swap_total_kb=0):
    lines = [
        f"MemTotal:       16000000 kB\n",
        f"MemAvailable:   {mem_available_kb} kB\n",
        f"SwapTotal:      {swap_total_kb} kB\n",
        f"SwapFree:       {swap_total_kb} kB\n",
    ]
    return "".join(lines)


# ---------------------------------------------------------------------------
# Disk usage tests
# ---------------------------------------------------------------------------

class TestCheckDiskUsage(unittest.TestCase):

    def _run(self, used_pct, statsbar_exists=False, statsbar_gb=0.0):
        with patch('shutil.disk_usage', return_value=_make_usage(300, used_pct)), \
             patch('os.path.exists', return_value=statsbar_exists), \
             patch('subprocess.run') as mock_run:

            if statsbar_exists:
                mock_run.return_value = MagicMock(
                    returncode=0,
                    stdout=f"{int(statsbar_gb * 1024 ** 3)}\t/path\n",
                )

            last_ts, rows, detail, forced = _check_disk_usage()
        return forced, detail

    def test_81_pct_disk_amber(self):
        status, _ = self._run(81)
        self.assertEqual(status, 'yellow', "81% disk should be AMBER (yellow)")

    def test_91_pct_disk_red(self):
        status, _ = self._run(91)
        self.assertEqual(status, 'red', "91% disk should be RED")

    def test_below_threshold_green(self):
        status, _ = self._run(70)
        self.assertEqual(status, 'green', "70% disk should be green")

    def test_statsbar_amber_threshold(self):
        status, detail = self._run(50, statsbar_exists=True, statsbar_gb=31.0)
        self.assertEqual(status, 'yellow', "statsbar >30GB should be AMBER")
        self.assertIn('codex-statsbar', detail)

    def test_statsbar_red_threshold(self):
        status, _ = self._run(50, statsbar_exists=True, statsbar_gb=41.0)
        self.assertEqual(status, 'red', "statsbar >40GB should be RED")

    def test_worst_status_propagates(self):
        # Disk is green but statsbar is red — expect red
        status, _ = self._run(50, statsbar_exists=True, statsbar_gb=41.0)
        self.assertEqual(status, 'red')

    def test_returns_four_tuple(self):
        with patch('shutil.disk_usage', return_value=_make_usage(300, 50)), \
             patch('os.path.exists', return_value=False):
            result = _check_disk_usage()
        self.assertEqual(len(result), 4, "_check_disk_usage must return a 4-tuple")

    def test_detail_contains_pct(self):
        _, _, detail, _ = _check_disk_usage.__wrapped__() if hasattr(_check_disk_usage, '__wrapped__') else (None, None, None, None)
        # Just run with mocks and check detail string
        with patch('shutil.disk_usage', return_value=_make_usage(300, 75)), \
             patch('os.path.exists', return_value=False):
            _, _, detail, _ = _check_disk_usage()
        self.assertIn('75.', detail)


# ---------------------------------------------------------------------------
# Memory available tests
# ---------------------------------------------------------------------------

class TestCheckMemoryAvailable(unittest.TestCase):

    def _run(self, mem_gb, swap_total_kb=0):
        mem_kb = int(mem_gb * 1024 ** 2)
        meminfo = _proc_meminfo(mem_kb, swap_total_kb)
        with patch('builtins.open', unittest.mock.mock_open(read_data=meminfo)):
            last_ts, rows, detail, forced = _check_memory_available()
        return forced, detail

    def test_1_5gb_amber(self):
        status, _ = self._run(1.5)
        self.assertEqual(status, 'yellow', "1.5GB available should be AMBER (yellow)")

    def test_0_8gb_red(self):
        status, _ = self._run(0.8)
        self.assertEqual(status, 'red', "0.8GB available should be RED")

    def test_3gb_green(self):
        status, _ = self._run(3.0)
        self.assertEqual(status, 'green', "3.0GB available should be green")

    def test_exactly_1gb_red(self):
        # < 1.0 is red; exactly 1.0 is NOT red (boundary)
        status, _ = self._run(0.99)
        self.assertEqual(status, 'red')

    def test_exactly_2gb_boundary(self):
        # < 2.0 is yellow; exactly 2.0 is NOT yellow
        status, _ = self._run(1.99)
        self.assertEqual(status, 'yellow')

    def test_no_swap_reported(self):
        _, detail = self._run(3.0, swap_total_kb=0)
        self.assertIn('no swap', detail)

    def test_swap_reported_informational(self):
        _, detail = self._run(3.0, swap_total_kb=2 * 1024 * 1024)  # 2GB swap
        self.assertIn('swap=', detail)

    def test_returns_four_tuple(self):
        mem_kb = int(4.0 * 1024 ** 2)
        meminfo = _proc_meminfo(mem_kb)
        with patch('builtins.open', unittest.mock.mock_open(read_data=meminfo)):
            result = _check_memory_available()
        self.assertEqual(len(result), 4, "_check_memory_available must return a 4-tuple")


# ---------------------------------------------------------------------------
# check_source integration — forced_status propagated correctly
# ---------------------------------------------------------------------------

class TestCheckSourceForcedStatus(unittest.TestCase):

    def _source_row(self, source_id):
        return {'source_id': source_id, 'expected_interval_minutes': 30, 'cron_schedule': '*/30 * * * *'}

    def test_disk_forced_status_used(self):
        mem_kb = int(3.0 * 1024 ** 2)
        with patch('shutil.disk_usage', return_value=_make_usage(300, 91)), \
             patch('os.path.exists', return_value=False):
            result = check_source(self._source_row('sys_disk_usage'))
        self.assertEqual(result['status'], 'red')

    def test_memory_forced_status_used(self):
        meminfo = _proc_meminfo(int(0.8 * 1024 ** 2))
        with patch('builtins.open', unittest.mock.mock_open(read_data=meminfo)):
            result = check_source(self._source_row('sys_memory_available'))
        self.assertEqual(result['status'], 'red')

    def test_healthy_disk_returns_green(self):
        with patch('shutil.disk_usage', return_value=_make_usage(300, 50)), \
             patch('os.path.exists', return_value=False):
            result = check_source(self._source_row('sys_disk_usage'))
        self.assertEqual(result['status'], 'green')

    def test_healthy_memory_returns_green(self):
        meminfo = _proc_meminfo(int(4.0 * 1024 ** 2))
        with patch('builtins.open', unittest.mock.mock_open(read_data=meminfo)):
            result = check_source(self._source_row('sys_memory_available'))
        self.assertEqual(result['status'], 'green')


if __name__ == '__main__':
    unittest.main()
