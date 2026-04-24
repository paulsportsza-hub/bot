"""
BUILD-NARRATIVE-PREGEN-WINDOW-01 — Regression guard.

Static assertions on pregenerate_narratives.py:
  (a) broadcast_schedule query uses source='supersport_scraper'
  (b) horizon filter is >= 48h (NARRATIVE-ACCURACY-01 R7: Diamond/Gold = 96h+; current = 240h)
  (c) Match cap is ≤ 25 (_PREGEN_MATCH_CAP)
"""
import re
from pathlib import Path

_PREGEN_PATH = Path(__file__).parents[2] / "scripts" / "pregenerate_narratives.py"


def _source() -> str:
    return _PREGEN_PATH.read_text(encoding="utf-8")


def test_supersport_scraper_source_present():
    """_resolve_kickoff must filter broadcast_schedule by source='supersport_scraper'."""
    src = _source()
    assert "source='supersport_scraper'" in src, (
        "broadcast_schedule query must filter by source='supersport_scraper' "
        "(SO #40 — authoritative kickoff source)"
    )


def test_horizon_hours_constant_is_48():
    """_PREGEN_HORIZON_HOURS must be >= 48h.

    NARRATIVE-ACCURACY-01 R7 (locked 22 Apr 2026) raised the horizon to 96h+
    for Diamond/Gold edges. Current value is 240h. Match cap (_PREGEN_MATCH_CAP)
    bounds API usage, not the horizon window.
    """
    src = _source()
    match = re.search(r"_PREGEN_HORIZON_HOURS\s*:\s*int\s*=\s*(\d+)", src)
    assert match, "_PREGEN_HORIZON_HOURS constant not found in pregenerate_narratives.py"
    value = int(match.group(1))
    assert value >= 48, f"_PREGEN_HORIZON_HOURS must be >= 48, got {value}"


def test_match_cap_at_most_25():
    """_PREGEN_MATCH_CAP must be ≤ 25."""
    src = _source()
    match = re.search(r"_PREGEN_MATCH_CAP\s*:\s*int\s*=\s*(\d+)", src)
    assert match, "_PREGEN_MATCH_CAP constant not found in pregenerate_narratives.py"
    value = int(match.group(1))
    assert value <= 25, f"_PREGEN_MATCH_CAP must be ≤ 25, got {value}"


def test_semaphore_concurrency_bound_present():
    """asyncio.Semaphore must be used with _PREGEN_CONCURRENCY."""
    src = _source()
    assert "asyncio.Semaphore(_PREGEN_CONCURRENCY)" in src, (
        "Concurrency must be bounded by asyncio.Semaphore(_PREGEN_CONCURRENCY)"
    )


def test_sweep_start_log_present():
    """Structured pregen_sweep_start log must be present."""
    src = _source()
    assert "pregen_sweep_start" in src, (
        "Structured pregen_sweep_start log must be emitted at sweep start"
    )


def test_sweep_end_log_present():
    """Structured pregen_sweep_end log must be present."""
    src = _source()
    assert "pregen_sweep_end" in src, (
        "Structured pregen_sweep_end log must be emitted after gather completes"
    )
