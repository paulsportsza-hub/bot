"""FIX-TIMEZONE-CANON-01B — Chelsea regression + forbidden idiom guards.

The Chelsea bug (18 Apr 2026):
  UK kickoff 20:00 BST → bot displayed 22:00 SAST (should be 21:00 SAST).
  Root cause: old code did `_ts + timedelta(hours=2)` on a BST-aware timestamp,
  yielding BST 22:00 instead of SAST 21:00.

This module:
  1. Verifies the old logic was wrong (documentation test).
  2. Verifies the new to_sast() path produces the correct result.
  3. Verifies forbidden idioms are absent from bot.py and dashboard/app.py.
"""
from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

# Make timezone_utils importable from publisher
_PUB = Path(__file__).resolve().parents[3] / "publisher"
if str(_PUB) not in sys.path:
    sys.path.insert(0, str(_PUB))

from timezone_utils import assume_utc, assume_sast, to_sast, UTC, SAST, UK


# ── Chelsea regression tests ─────────────────────────────────────────────────

def test_chelsea_old_logic_was_wrong():
    """Document that the old `timedelta(hours=2)` logic produced 22:00 for BST input."""
    # Odds scraped at UK/BST 20:00 → stored as BST-aware ISO string
    bst_ts = datetime(2026, 4, 18, 20, 0, 0, tzinfo=UK)  # 20:00 BST = 19:00 UTC = 21:00 SAST
    # Old buggy path:
    old_result = bst_ts + timedelta(hours=2)
    assert old_result.strftime("%H:%M") == "22:00", (
        "Old code produced 22:00 (the Chelsea bug) — documenting it was wrong"
    )


def test_chelsea_new_logic_is_correct():
    """New to_sast() correctly converts BST 20:00 → SAST 21:00."""
    bst_ts = datetime(2026, 4, 18, 20, 0, 0, tzinfo=UK)  # 20:00 BST = 21:00 SAST
    sast_dt = to_sast(bst_ts)
    assert sast_dt.strftime("%H:%M") == "21:00", (
        f"Expected 21:00 SAST, got {sast_dt.strftime('%H:%M')}"
    )
    assert sast_dt.tzinfo == SAST


def test_chelsea_utc_source_new_logic():
    """UTC odds timestamp → SAST via to_sast(), not timedelta."""
    # Odds stored as UTC 19:00 (= BST 20:00 = SAST 21:00)
    utc_ts = datetime(2026, 4, 18, 19, 0, 0, tzinfo=UTC)
    sast_dt = to_sast(utc_ts)
    assert sast_dt.strftime("%H:%M") == "21:00"
    assert sast_dt.tzinfo == SAST


def test_chelsea_naive_utc_source():
    """Naive UTC odds_ts (no Z) → assume_utc then to_sast → correct SAST."""
    naive_utc = datetime(2026, 4, 18, 19, 0, 0)  # naive, from DB as UTC
    aware = assume_utc(naive_utc)
    sast_dt = to_sast(aware)
    assert sast_dt.strftime("%H:%M") == "21:00"


def test_format_freshness_path_simulation():
    """Simulate the fixed _format_freshness() code path for a BST odds timestamp."""
    odds_ts = "2026-04-18T20:00:00+01:00"  # BST-aware string
    _ts = datetime.fromisoformat(odds_ts.replace("Z", "+00:00"))
    # New code: check tzinfo, use to_sast()
    if _ts.tzinfo is None:
        _ts = assume_utc(_ts)
    _sast = to_sast(_ts)
    assert _sast.strftime("%H:%M") == "21:00", (
        f"Expected 21:00 SAST for BST 20:00, got {_sast.strftime('%H:%M')}"
    )


def test_format_freshness_utc_z_suffix():
    """Simulate UTC Z-suffix timestamp (most common DB format) → 21:00 SAST."""
    odds_ts = "2026-04-18T19:00:00Z"
    _ts = datetime.fromisoformat(odds_ts.replace("Z", "+00:00"))
    if _ts.tzinfo is None:
        _ts = assume_utc(_ts)
    _sast = to_sast(_ts)
    assert _sast.strftime("%H:%M") == "21:00"


# ── BST boundary ──────────────────────────────────────────────────────────────

def test_winter_uk_kickoff_sast():
    """December (GMT): UK 15:00 GMT → SAST 17:00 (UTC+2 same as SAST)."""
    winter_uk = datetime(2026, 12, 5, 15, 0, 0, tzinfo=UK)
    assert to_sast(winter_uk).strftime("%H:%M") == "17:00"


def test_bst_march_boundary():
    """Just after BST starts: UK 20:00 BST (late March) → SAST 21:00."""
    post_bst = datetime(2026, 3, 30, 20, 0, 0, tzinfo=UK)  # BST active
    assert to_sast(post_bst).strftime("%H:%M") == "21:00"


# ── Forbidden idiom grep guards ───────────────────────────────────────────────

_BOT_PY = Path(__file__).resolve().parents[2] / "bot.py"
_DASH_PY = Path(__file__).resolve().parents[3] / "dashboard" / "app.py"


def _grep_forbidden(path: Path) -> list[str]:
    result = subprocess.run(
        ["grep", "-nE",
         r"datetime\.utcnow\(\)|timedelta\(hours\s*=\s*2\)|\.replace\(\s*tzinfo\s*=",
         str(path)],
        capture_output=True, text=True,
    )
    return result.stdout.splitlines()


def test_bot_py_no_forbidden_idioms():
    hits = _grep_forbidden(_BOT_PY)
    assert hits == [], f"Forbidden tz idioms in bot.py:\n" + "\n".join(hits)


def test_dashboard_no_forbidden_idioms():
    hits = _grep_forbidden(_DASH_PY)
    assert hits == [], f"Forbidden tz idioms in dashboard/app.py:\n" + "\n".join(hits)
