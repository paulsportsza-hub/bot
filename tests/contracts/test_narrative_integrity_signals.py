"""BUILD-COACHES-MONITOR-WIRE-01: Contract tests for coach freshness signals.

Verifies that:
- SIGNAL_FNS list exists in monitor_narrative_integrity and contains both new signals
- Each signal function produces a dict with all required keys
- signal names are correct
- band values are one of GREEN/WARN/ALERT
- breach is 0 or 1
"""
from __future__ import annotations

import importlib
import json
import sys
import os
from pathlib import Path

import pytest

# ── Path setup ─────────────────────────────────────────────────────────────────
_BOT_DIR = Path(__file__).resolve().parent.parent.parent
_SCRIPTS_DIR = _BOT_DIR / "scripts"
sys.path.insert(0, str(_BOT_DIR))
sys.path.insert(0, str(_SCRIPTS_DIR))

# ── Import module under test ────────────────────────────────────────────────────
import importlib.util

_spec = importlib.util.spec_from_file_location(
    "monitor_narrative_integrity",
    str(_SCRIPTS_DIR / "monitor_narrative_integrity.py"),
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)


# ── Helpers ─────────────────────────────────────────────────────────────────────
_REQUIRED_KEYS = {"signal", "value", "band", "breach", "details"}
_VALID_BANDS = {"GREEN", "WARN", "ALERT"}
_EXPECTED_SIGNALS = {"coach_freshness_pct", "bot_coaches_sync"}


class TestSignalFnsRegistered:
    """SIGNAL_FNS list exists and contains both new signals."""

    def test_signal_fns_attr_exists(self):
        assert hasattr(_mod, "SIGNAL_FNS"), "SIGNAL_FNS list missing from monitor module"

    def test_signal_fns_is_list(self):
        assert isinstance(_mod.SIGNAL_FNS, list), "SIGNAL_FNS must be a list"

    def test_both_coach_signals_in_signal_fns(self):
        names = {fn.__name__ for fn in _mod.SIGNAL_FNS}
        assert "signal_coach_freshness_pct" in names, (
            "signal_coach_freshness_pct not found in SIGNAL_FNS"
        )
        assert "signal_bot_coaches_sync" in names, (
            "signal_bot_coaches_sync not found in SIGNAL_FNS"
        )


class TestSignalFunctions:
    """Each signal function produces a well-formed dict."""

    def _call(self, fn_name: str) -> dict:
        fn = getattr(_mod, fn_name)
        return fn()

    def _assert_shape(self, result: dict, expected_signal: str):
        assert isinstance(result, dict), f"Signal {expected_signal} must return a dict"
        missing = _REQUIRED_KEYS - result.keys()
        assert not missing, (
            f"Signal {expected_signal} missing keys: {missing}"
        )
        assert result["signal"] == expected_signal, (
            f"Expected signal={expected_signal!r}, got {result['signal']!r}"
        )
        assert result["band"] in _VALID_BANDS, (
            f"band must be one of {_VALID_BANDS}, got {result['band']!r}"
        )
        assert result["breach"] in (0, 1), (
            f"breach must be 0 or 1, got {result['breach']!r}"
        )
        assert isinstance(result["value"], (int, float)), (
            f"value must be numeric, got {type(result['value'])}"
        )
        # details must be valid JSON (or empty string)
        if result["details"]:
            json.loads(result["details"])

    def test_coach_freshness_pct_shape(self):
        result = self._call("signal_coach_freshness_pct")
        self._assert_shape(result, "coach_freshness_pct")

    def test_bot_coaches_sync_shape(self):
        result = self._call("signal_bot_coaches_sync")
        self._assert_shape(result, "bot_coaches_sync")

    def test_coach_freshness_pct_value_is_percentage(self):
        result = self._call("signal_coach_freshness_pct")
        assert 0.0 <= result["value"] <= 100.0, (
            f"coach_freshness_pct value must be 0–100, got {result['value']}"
        )

    def test_bot_coaches_sync_value_non_negative(self):
        result = self._call("signal_bot_coaches_sync")
        assert result["value"] >= 0, (
            f"bot_coaches_sync value must be ≥ 0, got {result['value']}"
        )

    def test_coach_freshness_alert_threshold_consistency(self):
        """breach=1 iff band==ALERT."""
        result = self._call("signal_coach_freshness_pct")
        if result["band"] == "ALERT":
            assert result["breach"] == 1
        else:
            assert result["breach"] == 0

    def test_bot_coaches_sync_breach_consistency(self):
        """breach=1 iff band==ALERT."""
        result = self._call("signal_bot_coaches_sync")
        if result["band"] == "ALERT":
            assert result["breach"] == 1
        else:
            assert result["breach"] == 0
