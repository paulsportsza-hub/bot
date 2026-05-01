"""Contract tests for FIX-EDGEOPS-NOISE-CLEANUP-V2-01.

Verifies the 7 acceptance criteria (A1, B1, C1, D1, D2, E1, F1) covering:

  Action A — RECOVERED notifications go to DB only (telegram_sent=0)
  Action B — coach_freshness_pct excludes 16 cricket-international entries
  Action C — fpl_injuries 24h debounce
  Action D1 — narrative_integrity_monitor self-alerts skip Telegram
  Action D2 — low_quality_verdict_count threshold raised 1 → 5
  Action E — OpenRouter quota alert fires once per band crossing
  Action F — sharp_odds_api 4h critical + publisher_content 30-min black

A/C/D1/E/F live in /home/paulsportsza/scripts/health_alerter.py (separate
non-git tree). The bot-repo tests verify that file's behaviour by inspecting
its source. B and D2 are implemented in scripts/monitor_narrative_integrity.py
and are tested directly.
"""

from __future__ import annotations

import importlib
import re
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

EXTERNAL_HEALTH_ALERTER = Path("/home/paulsportsza/scripts/health_alerter.py")


def _read_external() -> str:
    if not EXTERNAL_HEALTH_ALERTER.exists():
        raise unittest.SkipTest(
            f"external health_alerter not present at {EXTERNAL_HEALTH_ALERTER}"
        )
    return EXTERNAL_HEALTH_ALERTER.read_text()


class TestActionA_RecoveredSuppression(unittest.TestCase):
    """AC-A1: RECOVERED notifications land in DB but telegram_sent=0."""

    def test_a1_recovered_db_only_marker(self):
        src = _read_external()
        self.assertIn(
            "AC-1.1", src,
            "external health_alerter must carry AC-1.1 marker for RECOVERED suppression",
        )

    def test_a1_recovery_insert_uses_telegram_sent_zero(self):
        src = _read_external()
        self.assertIn("'status_recovered'", src)
        self.assertRegex(
            src,
            r"VALUES\s*\(\?,\s*'status_recovered',\s*'info',\s*\?,\s*\?,\s*0",
            "recovery insert must hardcode telegram_sent=0",
        )


class TestActionB_CoachFreshnessScopeFilter(unittest.TestCase):
    """AC-B1: coach_freshness_pct skips cricket-international (16 teams)."""

    def setUp(self):
        if "monitor_narrative_integrity" in sys.modules:
            del sys.modules["monitor_narrative_integrity"]
        self.mni = importlib.import_module("monitor_narrative_integrity")

    def test_b1_out_of_scope_set_size_is_16(self):
        self.assertEqual(
            len(self.mni.CRICKET_OUT_OF_SCOPE_TEAMS), 16,
            "CRICKET_OUT_OF_SCOPE_TEAMS must contain exactly 16 entries",
        )

    def test_b1_sa20_franchises_present(self):
        for team in (
            "sunrisers eastern cape", "pretoria capitals", "paarl royals",
            "joburg super kings", "durbans super giants", "mi cape town",
        ):
            self.assertIn(team, self.mni.CRICKET_OUT_OF_SCOPE_TEAMS)

    def test_b1_internationals_present(self):
        for team in (
            "south africa", "india", "australia", "england", "new zealand",
            "pakistan", "sri lanka", "west indies", "bangladesh", "zimbabwe",
        ):
            self.assertIn(team, self.mni.CRICKET_OUT_OF_SCOPE_TEAMS)

    def test_b1_out_of_scope_stale_is_filtered_from_pct(self):
        all_stale = [
            {"sport": "cricket", "team": t, "name": "?", "last_verified": "2026-02-27", "age_days": 60}
            for t in self.mni.CRICKET_OUT_OF_SCOPE_TEAMS
        ]
        # 1 in-scope soccer entry stale, 26 cricket entries (10 in-scope + 16 out-of-scope) checked.
        all_stale.append({"sport": "soccer", "team": "in_scope_team", "name": "?", "last_verified": "2026-01-01", "age_days": 120})
        fake_result = {"stale": all_stale, "missing": [], "checked": 27, "ok": False}

        # Patch freshness_check to return fake_result.
        from narrative_integrity_monitor import freshness_check as _orig
        import narrative_integrity_monitor as _nim
        _nim.freshness_check = lambda **kw: fake_result
        try:
            out = self.mni.signal_coach_freshness_pct()
        finally:
            _nim.freshness_check = _orig

        # After filter: 16 cricket-international stripped from stale (and from checked).
        # checked = 27 - 16 = 11; stale = 1; pct = round(1/11*100, 2) = 9.09 → GREEN.
        details = out["details"]
        self.assertIn('"checked": 11', details)
        self.assertIn('"stale": 1', details)
        self.assertEqual(out["band"], "GREEN")
        self.assertEqual(out["breach"], 0)

    def test_b1_no_out_of_scope_in_isolation_is_green(self):
        # If ONLY out-of-scope entries are stale, signal must be GREEN with breach=0.
        only_oos = [
            {"sport": "cricket", "team": t, "name": "?", "last_verified": "2026-02-27", "age_days": 60}
            for t in self.mni.CRICKET_OUT_OF_SCOPE_TEAMS
        ]
        fake_result = {"stale": only_oos, "missing": [], "checked": 16, "ok": False}
        import narrative_integrity_monitor as _nim
        _orig = _nim.freshness_check
        _nim.freshness_check = lambda **kw: fake_result
        try:
            out = self.mni.signal_coach_freshness_pct()
        finally:
            _nim.freshness_check = _orig
        self.assertEqual(out["band"], "GREEN")
        self.assertEqual(out["breach"], 0)


class TestActionC_FplInjuriesDebounce(unittest.TestCase):
    """AC-C1: fpl_injuries flapping <24h does not fire Telegram."""

    def test_c1_debounce_marker(self):
        src = _read_external()
        self.assertIn("AC-1.3", src)

    def test_c1_24h_window(self):
        src = _read_external()
        self.assertTrue(
            re.search(
                r"source_id\s*=\s*'fpl_injuries'.*?-1440 minutes",
                src, re.DOTALL,
            ),
            "fpl_injuries gate must use a 1440-minute (24h) lookback",
        )


class TestActionD1_NarrativeMonitorSelfSilence(unittest.TestCase):
    """AC-D1: narrative_integrity_monitor signals never reach Telegram."""

    def test_d1_external_alerter_skips_source(self):
        src = _read_external()
        self.assertIn("AC-1.4", src)
        self.assertIn("narrative_integrity_monitor", src)

    def test_d1_in_repo_fire_cycle_does_not_call_send_edgeops(self):
        # The _fire_cycle_alerts function MUST NOT directly invoke
        # _send_edgeops_alert anymore. We grep the source.
        target = REPO_ROOT / "scripts" / "monitor_narrative_integrity.py"
        src = target.read_text()
        # Locate the _fire_cycle_alerts body.
        start = src.index("def _fire_cycle_alerts(")
        end = src.index("\n\ndef ", start + 1)
        body = src[start:end]
        self.assertNotIn(
            "_send_edgeops_alert(", body,
            "D1: _fire_cycle_alerts must no longer call _send_edgeops_alert",
        )


class TestActionD2_LowQualityVerdictThreshold(unittest.TestCase):
    """AC-D2: low_quality_verdict_count threshold ≥ 5; does NOT fire on count=1."""

    def setUp(self):
        if "monitor_narrative_integrity" in sys.modules:
            del sys.modules["monitor_narrative_integrity"]
        self.mni = importlib.import_module("monitor_narrative_integrity")

    def test_d2_threshold_at_least_five(self):
        self.assertGreaterEqual(self.mni._THRESHOLDS["low_quality_verdict_count"], 5)

    def test_d2_count_one_is_green(self):
        band, breach = self.mni._compute_int_band("low_quality_verdict_count", 1)
        self.assertEqual(band, "GREEN")
        self.assertEqual(breach, 0)

    def test_d2_count_five_alerts(self):
        band, breach = self.mni._compute_int_band("low_quality_verdict_count", 5)
        self.assertEqual(band, "ALERT")
        self.assertEqual(breach, 1)


class TestActionE_OpenRouterOncePerCrossing(unittest.TestCase):
    """AC-E1: OpenRouter quota alert fires once per band crossing."""

    def test_e1_band_state_helpers_present(self):
        src = _read_external()
        for marker in (
            "_OPENROUTER_BAND_FILE",
            "_openrouter_current_band",
            "_get_openrouter_last_band",
            "_set_openrouter_last_band",
        ):
            self.assertIn(marker, src, f"missing OpenRouter band-state helper: {marker}")

    def test_e1_band_persisted_after_send(self):
        src = _read_external()
        # _set_openrouter_last_band must be invoked after a successful insert.
        self.assertRegex(
            src,
            r"_set_openrouter_last_band\(current_band\)",
            "band must be persisted after firing so the next poll skips",
        )


class TestActionF_SharpOddsAndPublisherThresholds(unittest.TestCase):
    """AC-F1: sharp_odds_api 4h critical + publisher_content 30-min black."""

    def test_f1_sharp_odds_60min_suppression(self):
        src = _read_external()
        self.assertRegex(
            src,
            r"source_id\s*==\s*'sharp_odds_api'\s+and\s+minutes_since.*<\s*60",
        )

    def test_f1_sharp_odds_4h_critical(self):
        src = _read_external()
        self.assertRegex(
            src,
            r"source_id\s*==\s*'sharp_odds_api'\s+and\s+minutes_since.*>=\s*240",
        )

    def test_f1_publisher_30min_threshold(self):
        src = _read_external()
        self.assertRegex(
            src,
            r"source_id\s*==\s*'publisher_content'\s+and\s+minutes_since.*<\s*30",
        )


if __name__ == "__main__":
    unittest.main()
