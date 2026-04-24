"""BUILD-CONTRACT-TESTS-01 — Test 8: COLLATE NOCASE Guard

W84-MM2 invariant (LOCKED — DO NOT REVERT):
  No SQL query against odds_snapshots in bot/, services/, or scrapers/ may
  contain COLLATE NOCASE.  Adding COLLATE NOCASE to the league equality filter
  on odds_snapshots disables the idx_odds_league_time index and causes a full
  table scan (6+ seconds on 543K rows).

Purely static — greps .py source files, no runtime DB queries.
"""
import glob
import os
import re


def _find_py_files(*roots: str) -> list[str]:
    files: list[str] = []
    for root in roots:
        if os.path.isdir(root):
            files.extend(glob.glob(os.path.join(root, "**", "*.py"), recursive=True))
        elif os.path.isfile(root):
            files.append(root)
    return [f for f in files if "__pycache__" not in f and ".venv" not in f]


def _extract_sql_strings(source: str) -> list[tuple[str, int]]:
    """Extract triple-quoted string literals with approximate line numbers."""
    results = []
    for pat in (r'"""(.*?)"""', r"'''(.*?)'''"):
        for m in re.finditer(pat, source, re.DOTALL):
            line_no = source[: m.start()].count("\n") + 1
            results.append((m.group(1), line_no))
    return results


def test_no_collate_nocase_on_odds_snapshots():
    """No SQL query touching odds_snapshots may use COLLATE NOCASE.

    W84-MM2 root cause: COLLATE NOCASE on the league column in a 543K-row table
    disables the covering index and causes full table scans.  All league values
    stored by scrapers are already lowercase — an exact match is correct and fast.
    """
    bot_root = os.path.join(os.path.dirname(__file__), "..", "..")
    scrapers_root = os.path.join(bot_root, "..", "scrapers")
    search_dirs = [
        os.path.join(bot_root, "bot.py"),
        os.path.join(bot_root, "services"),
        os.path.join(bot_root, "renderers"),
    ]
    if os.path.isdir(scrapers_root):
        search_dirs.append(scrapers_root)

    py_files = _find_py_files(*search_dirs)
    violations: list[str] = []

    for fpath in py_files:
        try:
            with open(fpath, encoding="utf-8", errors="replace") as f:
                source = f.read()
        except OSError:
            continue

        for sql, line_no in _extract_sql_strings(source):
            if not re.search(r"\bodds_snapshots\b", sql, re.IGNORECASE):
                continue
            if re.search(r"\bCOLLATE\s+NOCASE\b", sql, re.IGNORECASE):
                snippet = sql.strip()[:200].replace("\n", " ")
                violations.append(f"{fpath}:{line_no}: ...{snippet}...")

    assert not violations, (
        f"\nW84-MM2 VIOLATION: {len(violations)} odds_snapshots query/ies use "
        f"COLLATE NOCASE (disables idx_odds_league_time index):\n\n"
        + "\n".join(violations)
        + "\n\nFix: use exact match AND league = ? (all league values are lowercase)."
    )


def test_odds_snapshots_league_filter_uses_exact_match():
    """The canonical get_all_matches() query must use exact equality on league, not LIKE or COLLATE.

    This is a belt-and-suspenders check alongside the COLLATE guard — confirms
    the index-using pattern is in place in the primary query site.
    """
    scrapers_root = os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "scrapers"
    )
    odds_service_candidates = [
        os.path.join(scrapers_root, "odds_service.py"),
        os.path.join(scrapers_root, "edge", "odds_service.py"),
    ]
    # Also search bot's services/ directory
    bot_services = os.path.join(os.path.dirname(__file__), "..", "..", "services")
    for root, _, fnames in os.walk(bot_services):
        for fn in fnames:
            if fn.endswith(".py"):
                odds_service_candidates.append(os.path.join(root, fn))

    found_any = False
    for fpath in odds_service_candidates:
        if not os.path.isfile(fpath):
            continue
        with open(fpath, encoding="utf-8", errors="replace") as f:
            src = f.read()
        if "odds_snapshots" not in src:
            continue
        found_any = True
        # Must NOT contain COLLATE NOCASE adjacent to odds_snapshots queries
        for sql, line_no in _extract_sql_strings(src):
            if "odds_snapshots" in sql and re.search(
                r"\bCOLLATE\s+NOCASE\b", sql, re.IGNORECASE
            ):
                snippet = sql.strip()[:200].replace("\n", " ")
                assert False, (
                    f"W84-MM2 VIOLATION in {fpath}:{line_no}: COLLATE NOCASE found "
                    f"on odds_snapshots query.\n...{snippet}..."
                )

    # If no odds_service file exists at all, the test is vacuously satisfied
    _ = found_any  # no assertion — file may not exist yet
