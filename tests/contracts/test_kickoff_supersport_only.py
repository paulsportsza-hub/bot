"""INV-FIX-KICKOFF-SOURCE-AUDIT-02 — repo-wide supersport-only kickoff source.

Extends INV-TIMEZONE-POST-SAST-UNIFY-REGRESSION-01 (SO #40) from bot.py-only to
the full repo. Scans every .py file under /home/paulsportsza/{bot,scrapers,publisher}
and asserts that every SELECT from broadcast_schedule either (a) restricts to
source = 'supersport_scraper', or (b) is an explicit broadcast/channel metadata
query (channel name, DStv number, logo URL, free-to-air flag, FTA-only SELECT,
health metrics).

broadcast_schedule holds two kinds of rows:
  - source = 'supersport_scraper' → authoritative kickoff (UTC→SAST converted)
  - source IS NULL                → DStv EPG: includes re-airs, pre-shows, and
                                    classic replays whose start_time is a
                                    broadcast slot, not the real kickoff.

Fuzzy team-name matching across both sources can land on a re-air row and
display a kickoff ±1h (or more) off the real time — the 2026-04-22 TG
Community posts showed 22:00 SAST for a 21:00 SAST fixture because an
autogen/publisher code path outside bot.py did exactly that.
"""
from __future__ import annotations

import re
from pathlib import Path


_REPO_ROOTS = [
    Path("/home/paulsportsza/bot"),
    Path("/home/paulsportsza/scrapers"),
    Path("/home/paulsportsza/publisher"),
]

# Paths under each root that are not production code. These are excluded
# from the scan because the contract governs what ships to users, not
# what the contract test itself contains.
_EXCLUDE_SUBSTRINGS = (
    "/__pycache__/",
    "/.venv/",
    "/.pytest_cache/",
    "/node_modules/",
    "/tests/",
    "/test_",
    "_test.py",
    ".bak-",
    ".bak.",
    ".v2-",
    ".backup",
    "/.git/",
    "/logs/",
    "/reports/",
)

# Markers that, if present within the SELECT window, indicate a
# broadcast/channel METADATA query rather than a kickoff-driving one.
# Metadata queries may legitimately span all sources because they feed
# channel-name / DStv-number / FTA display — never the kickoff time.
_METADATA_MARKERS = (
    "dstv_number IS NOT NULL",
    "channel_logo_url",
    "is_free_to_air = 1",       # free-to-air option lookup
    "_get_supersport_channel",  # caller of the logo query
    "channel_name, channel_short",  # pure channel projection
    "MAX(scraped_at)",          # health-metric freshness check
    "COUNT(*)",                 # health-metric row count
    "COUNT(DISTINCT",           # health-metric distinct count
)


def _source_filter_ok(stmt: str) -> bool:
    """Return True if a SQL SELECT from broadcast_schedule restricts source."""
    s = stmt.replace("\n", " ")
    return (
        "source = 'supersport_scraper'" in s
        or "source='supersport_scraper'" in s
        or re.search(r"source\s*=\s*\?", s) is not None
    )


def _is_metadata_query(window: str) -> bool:
    """Return True when the SELECT window is a broadcast/channel metadata query."""
    return any(marker in window for marker in _METADATA_MARKERS)


_DML_KEYWORDS = ("DELETE", "UPDATE", "INSERT")


def _find_broadcast_schedule_selects(src: str) -> list[tuple[int, str]]:
    """Return (line_no, window_text) for each SELECT ... FROM broadcast_schedule.

    The window is a ±15-line slice around the FROM clause. One window per
    distinct SELECT (de-duplicated by proximity, same as SO #40 guard).
    DELETE / UPDATE / INSERT statements that happen to contain
    "FROM broadcast_schedule" (e.g. ``DELETE FROM broadcast_schedule WHERE ...``)
    are excluded — the contract governs SELECTs, not writes.
    """
    found: list[tuple[int, str]] = []
    lines = src.splitlines()
    for i, line in enumerate(lines):
        if "FROM broadcast_schedule" not in line:
            continue
        # Skip non-SELECT statements. Look on the same line first; for
        # multi-line SELECTs the SELECT keyword sits above FROM — check
        # up to 10 lines back.
        preceding = "\n".join(lines[max(0, i - 10): i + 1]).upper()
        if any(f"{kw} FROM BROADCAST_SCHEDULE" in preceding for kw in _DML_KEYWORDS):
            continue
        if "SELECT" not in preceding:
            continue
        start = max(0, i - 15)
        end = min(len(lines), i + 15)
        window = "\n".join(lines[start:end])
        if not any(abs(ln - (i + 1)) < 10 for ln, _ in found):
            found.append((i + 1, window))
    return found


def _iter_py_files() -> list[Path]:
    files: list[Path] = []
    for root in _REPO_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            s = str(path)
            if any(excl in s for excl in _EXCLUDE_SUBSTRINGS):
                continue
            files.append(path)
    return files


def test_repo_kickoff_queries_supersport_only() -> None:
    """Every kickoff-driving SELECT from broadcast_schedule across the repo
    must filter by source = 'supersport_scraper'.

    Whitelisted metadata queries (channel name, DStv number, logo, FTA,
    scrape-health metrics) may span all sources.
    """
    violations: list[str] = []

    for path in _iter_py_files():
        try:
            src = path.read_text()
        except (OSError, UnicodeDecodeError):
            continue
        if "broadcast_schedule" not in src:
            continue
        for ln, window in _find_broadcast_schedule_selects(src):
            if "FROM broadcast_schedule" not in window:
                continue
            if _is_metadata_query(window):
                continue
            if not _source_filter_ok(window):
                violations.append(
                    f"{path}:{ln} broadcast_schedule SELECT missing "
                    f"\"source = 'supersport_scraper'\" filter"
                )

    assert not violations, (
        "Kickoff-resolution queries across bot/, scrapers/, and publisher/ "
        "must restrict to source='supersport_scraper' to avoid DStv EPG "
        "re-airs drifting the displayed kickoff by ±1h.\n\n"
        + "\n".join(violations)
    )


def test_bot_py_kickoff_queries_supersport_only() -> None:
    """Backward-compatible SO #40 guard — bot.py alone.

    Retained so a single-file regression can fail quickly when bot.py
    is the file under edit.
    """
    bot_py = Path(__file__).resolve().parents[2] / "bot.py"
    src = bot_py.read_text()

    violations: list[str] = []
    for ln, window in _find_broadcast_schedule_selects(src):
        if "FROM broadcast_schedule" not in window:
            continue
        if _is_metadata_query(window):
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


def test_regression_guard_catches_injected_violation(tmp_path) -> None:
    """Inject a synthetic unfiltered kickoff query into a temp .py file and
    confirm the repo-wide scanner flags it.

    This pins the contract: if a future contributor adds a new
    broadcast_schedule SELECT without the source filter, the test fires.
    """
    probe = tmp_path / "synthetic_violation.py"
    probe.write_text(
        '"""synthetic kickoff-driving query without the source filter."""\n'
        "import sqlite3\n"
        "def bad_kickoff_lookup(conn, home, away, date_str):\n"
        "    return conn.execute(\n"
        "        \"SELECT start_time FROM broadcast_schedule \"\n"
        "        \"WHERE broadcast_date = ? AND home_team LIKE ? AND away_team LIKE ?\",\n"
        "        (date_str, f\"%{home}%\", f\"%{away}%\"),\n"
        "    ).fetchone()\n"
    )

    src = probe.read_text()
    hits = _find_broadcast_schedule_selects(src)
    assert hits, "probe file should produce at least one broadcast_schedule SELECT"

    unfiltered = [
        (ln, window) for ln, window in hits
        if not _is_metadata_query(window) and not _source_filter_ok(window)
    ]
    assert unfiltered, (
        "Synthetic unfiltered query was not flagged — regression scanner is broken"
    )
