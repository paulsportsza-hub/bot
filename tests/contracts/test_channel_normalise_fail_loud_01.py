"""FIX-DASH-CHANNEL-NORMALISE-FAIL-LOUD-01 — contract tests.

Verifies that _normalise_channel_key:
  1. Returns "" for unrecognised non-empty input.
  2. Logs a warning for unrecognised input.
  3. Does not send EdgeOps Telegram alerts for unrecognised input.
  4. Debounces repeated log-only alerts for the same raw value.
  5. Known channel values continue to map correctly (regression guard).
  6. Empty / whitespace-only input is silent (no alert).
"""
import importlib
import logging
import sys
import time
import unittest
from unittest.mock import patch


def _import_module():
    if "dashboard.health_dashboard" in sys.modules:
        return sys.modules["dashboard.health_dashboard"]
    return importlib.import_module("dashboard.health_dashboard")


class TestNormaliseChannelKeyFailLoud(unittest.TestCase):

    def setUp(self):
        mod = _import_module()
        # Reset debounce state before each test so alerts fire cleanly.
        mod._channel_normalise_alert_sent.clear()
        self.mod = mod

    # ── 1. Unknown input → returns ""
    def test_unknown_returns_empty(self):
        result = self.mod._normalise_channel_key("xyzzy_unknown_platform")
        self.assertEqual(result, "")

    # ── 2. Warning logged for unknown input
    def test_unknown_logs_warning(self):
        with self.assertLogs("dashboard.health_dashboard", level="WARNING") as cm:
            self.mod._normalise_channel_key("totally_unknown_channel_xyz")
        self.assertTrue(
            any("unrecognised" in line.lower() or "totally_unknown" in line for line in cm.output),
            f"Expected unrecognised-channel warning, got: {cm.output}",
        )

    # ── 3. Unknown input logs only, with no EdgeOps Telegram alert
    def test_unknown_logs_without_edgeops_alert(self):
        raw = "absolutely_unknown_channel_99"
        with patch.object(self.mod, "os") as mock_os, \
             patch("urllib.request.urlopen") as mock_urlopen, \
             self.assertLogs("dashboard.health_dashboard", level="WARNING") as cm:
            mock_os.environ = {"BOT_TOKEN": "test_token_abc"}
            mock_os.path = __import__("os").path
            self.mod._normalise_channel_key(raw)
        mock_urlopen.assert_not_called()
        self.assertTrue(any(raw in line for line in cm.output), cm.output)
        self.assertIn(raw, self.mod._channel_normalise_alert_sent)

    # ── 4. Debounce: second call within window does NOT fire alert again
    def test_debounce_suppresses_repeated_alert(self):
        raw = "duplicate_unknown_channel"
        # Pre-seed as fired 1 second ago (well within 1-hour window).
        self.mod._channel_normalise_alert_sent[raw.lower().strip()] = time.time() - 1

        with patch("urllib.request.urlopen") as mock_urlopen:
            self.mod._normalise_channel_key(raw)
        mock_urlopen.assert_not_called()

    # ── 5. Debounce: call after window expires logs again, but sends no Telegram alert
    def test_debounce_logs_after_window(self):
        raw = "expired_debounce_channel"
        # Pre-seed as fired 2 hours ago (past the 1-hour window).
        old_ts = time.time() - self.mod._CHANNEL_NORMALISE_DEBOUNCE_S - 1
        self.mod._channel_normalise_alert_sent[raw.lower().strip()] = (
            old_ts
        )
        with patch.object(self.mod, "os") as mock_os, \
             patch("urllib.request.urlopen") as mock_urlopen, \
             self.assertLogs("dashboard.health_dashboard", level="WARNING") as cm:
            mock_os.environ = {"BOT_TOKEN": "tok"}
            mock_os.path = __import__("os").path
            self.mod._normalise_channel_key(raw)
        mock_urlopen.assert_not_called()
        self.assertTrue(any(raw in line for line in cm.output), cm.output)
        self.assertGreater(self.mod._channel_normalise_alert_sent[raw.lower().strip()], old_ts)

    # ── 6. Empty string: silent, no alert
    def test_empty_input_silent(self):
        with patch("urllib.request.urlopen") as mock_urlopen:
            result = self.mod._normalise_channel_key("")
        self.assertEqual(result, "")
        mock_urlopen.assert_not_called()

    # ── 7. Whitespace-only: silent, no alert
    def test_whitespace_only_silent(self):
        with patch("urllib.request.urlopen") as mock_urlopen:
            result = self.mod._normalise_channel_key("   ")
        self.assertEqual(result, "")
        mock_urlopen.assert_not_called()

    # ── 8. Regression: known values still map correctly (no alert)
    def test_known_values_no_alert(self):
        known = [
            ("Telegram Alerts", "telegram_alerts"),
            ("Telegram Community", "telegram_community"),
            ("WhatsApp Channel", "whatsapp_channel"),
            ("Instagram", "instagram"),
            ("TikTok", "tiktok"),
            ("LinkedIn", "linkedin"),
            ("Threads", "threads"),
        ]
        with patch("urllib.request.urlopen") as mock_urlopen:
            for raw, expected in known:
                with self.subTest(raw=raw):
                    result = self.mod._normalise_channel_key(raw)
                    self.assertEqual(result, expected, f"Expected {expected!r} for {raw!r}")
        mock_urlopen.assert_not_called()

    # ── 9. No BOT_TOKEN: alert skipped silently (no exception)
    def test_no_bot_token_no_exception(self):
        with patch.object(self.mod, "os") as mock_os, \
             patch("urllib.request.urlopen") as mock_urlopen:
            mock_os.environ = {}
            mock_os.path = __import__("os").path
            result = self.mod._normalise_channel_key("no_token_unknown_channel")
        self.assertEqual(result, "")
        mock_urlopen.assert_not_called()

    # ── 10. _EDGEOPS_CHAT_ID_CHANNEL must be -1003877525865 (SO #20)
    def test_edgeops_chat_id_correct(self):
        self.assertEqual(self.mod._EDGEOPS_CHAT_ID_CHANNEL, -1003877525865)


if __name__ == "__main__":
    unittest.main()
