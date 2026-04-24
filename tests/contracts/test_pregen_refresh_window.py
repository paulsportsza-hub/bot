"""
INV-PREGEN-REFRESH-PARITY-VERIFY-01 — Refresh-path bounds contract test.

Asserts via source-reading that main() in pregenerate_narratives.py:
  1. Applies the 48h horizon filter AFTER the sweep-mode branch
  2. Applies the 25-match cap AFTER the sweep-mode branch
  3. Uses asyncio.Semaphore(_PREGEN_CONCURRENCY) AFTER the sweep-mode branch
  4. Routes through _resolve_kickoff (SO #40 source='supersport_scraper') in
     the horizon filter loop
  5. Emits structured pregen_sweep_start log with horizon_hours and concurrency_cap fields
  6. Implements --dry-run in the argparse CLI

All four constraints must be active on the refresh path, not just in definitions.
"""

import re
from pathlib import Path

_PREGEN_PATH = Path(__file__).parents[2] / "scripts" / "pregenerate_narratives.py"


def _source() -> str:
    return _PREGEN_PATH.read_text(encoding="utf-8")


def _main_body() -> str:
    """Extract everything from `async def main(` to end of file."""
    src = _source()
    idx = src.find("async def main(")
    assert idx != -1, "async def main() not found in pregenerate_narratives.py"
    return src[idx:]


def _sweep_branch_offset(main_body: str) -> int:
    """Offset of the sweep-mode branch (`if sweep in ("refresh"`) within main_body."""
    idx = main_body.find('sweep in ("refresh"')
    assert idx != -1, (
        'Sweep-mode branch `sweep in ("refresh"` not found in main() — '
        "it must appear before the horizon filter"
    )
    return idx


# ---------------------------------------------------------------------------
# AC-1-A: 48h horizon filter appears in main() AFTER the sweep-mode branch
# ---------------------------------------------------------------------------

def test_horizon_filter_after_sweep_branch():
    """BUILD-NARRATIVE-PREGEN-WINDOW-01: 48h filter must apply to refresh path."""
    body = _main_body()
    branch_offset = _sweep_branch_offset(body)
    filter_offset = body.find("_horizon_cutoff = datetime.now(SAST)")
    assert filter_offset != -1, (
        "_horizon_cutoff assignment not found in main() — "
        "48h filter must be present in the refresh path"
    )
    assert filter_offset > branch_offset, (
        "48h horizon filter must appear AFTER the sweep-mode branch in main(). "
        f"sweep_branch@{branch_offset}, filter@{filter_offset}"
    )


# ---------------------------------------------------------------------------
# AC-1-B: _resolve_kickoff is called inside the horizon filter loop in main()
# ---------------------------------------------------------------------------

def test_resolve_kickoff_called_in_main():
    """SO #40: _resolve_kickoff() must be invoked in the horizon filter loop."""
    body = _main_body()
    branch_offset = _sweep_branch_offset(body)
    ko_call_offset = body.find("_resolve_kickoff(")
    assert ko_call_offset != -1, (
        "_resolve_kickoff() not called from main() — "
        "horizon filter must route through _resolve_kickoff"
    )
    assert ko_call_offset > branch_offset, (
        "_resolve_kickoff() must be called AFTER the sweep-mode branch "
        "so it applies to the refresh path"
    )


# ---------------------------------------------------------------------------
# AC-1-C: 25-match cap applied after the sweep-mode branch
# ---------------------------------------------------------------------------

def test_match_cap_applied_after_sweep_branch():
    """25-match hard cap must apply on the refresh path."""
    body = _main_body()
    branch_offset = _sweep_branch_offset(body)
    # Cap is enforced by the conditional `if len(_edges_in_window) > _PREGEN_MATCH_CAP:`
    cap_check_offset = body.find("len(_edges_in_window) > _PREGEN_MATCH_CAP")
    assert cap_check_offset != -1, (
        "Match cap check `len(_edges_in_window) > _PREGEN_MATCH_CAP` not found in main() — "
        "25-match cap must be enforced after horizon filtering"
    )
    assert cap_check_offset > branch_offset, (
        "Match cap check must appear AFTER the sweep-mode branch"
    )


# ---------------------------------------------------------------------------
# AC-1-D: Semaphore(_PREGEN_CONCURRENCY) set up after sweep-mode branch
# ---------------------------------------------------------------------------

def test_semaphore_after_sweep_branch():
    """Semaphore(3) must be set up on the refresh path (after the sweep branch)."""
    body = _main_body()
    branch_offset = _sweep_branch_offset(body)
    sem_offset = body.find("asyncio.Semaphore(_PREGEN_CONCURRENCY)")
    assert sem_offset != -1, (
        "asyncio.Semaphore(_PREGEN_CONCURRENCY) not found in main() — "
        "concurrency must be bounded by Semaphore"
    )
    assert sem_offset > branch_offset, (
        "asyncio.Semaphore(_PREGEN_CONCURRENCY) must appear AFTER the sweep-mode branch"
    )


# ---------------------------------------------------------------------------
# AC-1-E: pregen_sweep_start log contains horizon_hours and concurrency_cap
# ---------------------------------------------------------------------------

def test_sweep_start_log_contains_required_fields():
    """pregen_sweep_start log must contain horizon_hours and concurrency_cap fields."""
    src = _source()
    match = re.search(
        r'pregen_sweep_start\s+match_count=%d\s+horizon_hours=%d\s+concurrency_cap=%d',
        src,
    )
    assert match, (
        "pregen_sweep_start log must contain match_count=%d horizon_hours=%d "
        "concurrency_cap=%d — used for dry-run verification and monitoring"
    )


# ---------------------------------------------------------------------------
# AC-1-F: pregen_horizon_filter log is present for when filtering fires
# ---------------------------------------------------------------------------

def test_horizon_filter_log_present():
    """pregen_horizon_filter log must be emitted when matches are filtered out."""
    src = _source()
    assert "pregen_horizon_filter:" in src, (
        "pregen_horizon_filter log must be present to capture when the 48h filter fires"
    )


# ---------------------------------------------------------------------------
# AC-1-G: --dry-run CLI flag is implemented
# ---------------------------------------------------------------------------

def test_dry_run_flag_in_argparse():
    """--dry-run flag must be registered in the argparse CLI."""
    src = _source()
    assert '"--dry-run"' in src or "'--dry-run'" in src, (
        "--dry-run flag must be registered in argparse "
        "so refresh-path dry runs can be executed without DB writes or LLM calls"
    )


# ---------------------------------------------------------------------------
# AC-1-H: SO #40 source='supersport_scraper' filter inside _resolve_kickoff
# ---------------------------------------------------------------------------

def test_supersport_source_filter_in_resolve_kickoff():
    """_resolve_kickoff must query broadcast_schedule with source='supersport_scraper'."""
    src = _source()
    resolve_start = src.find("def _resolve_kickoff(")
    assert resolve_start != -1, "_resolve_kickoff not found in pregenerate_narratives.py"
    # Find end of function (next def at same indentation)
    next_def = src.find("\ndef ", resolve_start + 1)
    func_body = src[resolve_start:next_def] if next_def != -1 else src[resolve_start:]
    assert "source='supersport_scraper'" in func_body, (
        "_resolve_kickoff must filter broadcast_schedule by source='supersport_scraper' "
        "(SO #40 — authoritative kickoff source for the refresh-path horizon filter)"
    )
