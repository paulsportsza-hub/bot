"""INV-TIMEZONE-POST-SAST-UNIFY-REGRESSION-01 — supersport-only kickoff source.

broadcast_schedule holds two kinds of rows:
  - source = 'supersport_scraper' → authoritative kickoff (UTC→SAST converted)
  - source IS NULL                → DStv EPG: includes re-airs, pre-shows,
                                    and classic replays whose start_time is
                                    a broadcast slot, not the real kickoff.

All kickoff-resolution queries in bot.py must filter to
source = 'supersport_scraper'; otherwise fuzzy team-name matching can land on
a re-air row and display a kickoff ±1h (or more) off the real time.
"""
from __future__ import annotations

import re
from pathlib import Path

_BOT_PY = Path(__file__).resolve().parents[2] / "bot.py"


def _source_filter_ok(stmt: str) -> bool:
    """Return True if a SQL SELECT from broadcast_schedule restricts source."""
    # Accept either 'supersport_scraper' literal or a placeholder that the
    # runtime binds to the same literal. The five production paths all use
    # the literal; a test shim may use a bind param.
    s = stmt.replace("\n", " ")
    return (
        "source = 'supersport_scraper'" in s
        or "source='supersport_scraper'" in s
        or re.search(r"source\s*=\s*\?", s) is not None
    )


def _find_broadcast_schedule_selects(src: str) -> list[tuple[int, str]]:
    """Return (line_no, statement_text) for each SELECT ... FROM broadcast_schedule."""
    found: list[tuple[int, str]] = []
    lines = src.splitlines()
    i = 0
    while i < len(lines):
        if "FROM broadcast_schedule" in lines[i] or "broadcast_schedule" in lines[i] and "SELECT" in "\n".join(lines[max(0, i - 8): i + 1]):
            # Walk backwards to find the preceding SELECT, forwards to find
            # the next closing paren/quote. Simpler: scan a 25-line window.
            start = max(0, i - 15)
            end = min(len(lines), i + 15)
            window = "\n".join(lines[start:end])
            # Only register each unique window once by line number
            if not any(abs(ln - (i + 1)) < 10 for ln, _ in found):
                found.append((i + 1, window))
        i += 1
    return found


def test_bot_py_kickoff_queries_supersport_only() -> None:
    """Every SELECT from broadcast_schedule in bot.py must filter by source.

    Exception: queries that are explicitly about channel/logo metadata
    (matched by '(dstv_number IS NOT NULL' or 'channel_logo_url' in the
    window) are allowed to span all sources — they resolve broadcast
    metadata, not kickoff times.
    """
    src = _BOT_PY.read_text()

    violations: list[str] = []
    for ln, window in _find_broadcast_schedule_selects(src):
        if "FROM broadcast_schedule" not in window:
            continue
        # Allow channel/logo-only queries — those don't drive kickoff display.
        if (
            "dstv_number IS NOT NULL" in window
            or "channel_logo_url" in window
            or "_get_supersport_channel" in window  # caller of the logo query
        ):
            continue
        if not _source_filter_ok(window):
            violations.append(
                f"bot.py:{ln} broadcast_schedule SELECT missing "
                f"\"source = 'supersport_scraper'\" filter"
            )

    assert not violations, (
        "Kickoff-resolution queries must restrict to source='supersport_scraper' "
        "to avoid DStv EPG re-airs drifting the displayed kickoff by ±1h.\n\n"
        + "\n".join(violations)
    )
