"""BUILD-CONTRACT-TESTS-01 — Test 3: Market-Type Filter

BUILD-MY-MATCHES-01 (Permanent): Every SELECT from odds_latest or odds_snapshots
that references home_odds, draw_odds, or away_odds MUST include
market_type = '1x2' in the WHERE clause.

Static analysis — greps .py source files, no runtime DB queries.
"""
import os
import re
import glob


# Files whose SQL is legitimately exempt from the market_type filter:
# integrity/health monitors that must inspect ALL market types for data quality.
_EXEMPT_FILENAMES = {"odds_integrity.py", "health_monitor.py", "post_deploy_validation.py"}


def _find_py_files(*roots: str) -> list[str]:
    files: list[str] = []
    for root in roots:
        if os.path.isdir(root):
            files.extend(glob.glob(os.path.join(root, "**", "*.py"), recursive=True))
        elif os.path.isfile(root):
            files.append(root)
    return [
        f for f in files
        if "__pycache__" not in f
        and ".venv" not in f
        and os.path.basename(f) not in _EXEMPT_FILENAMES
    ]


def _extract_sql_strings(source: str) -> list[str]:
    """Extract multi-line string literals that look like SQL queries."""
    # Match triple-quoted strings and regular strings
    candidates = []
    # Triple-quoted
    for m in re.finditer(r'"""(.*?)"""', source, re.DOTALL):
        candidates.append(m.group(1))
    for m in re.finditer(r"'''(.*?)'''", source, re.DOTALL):
        candidates.append(m.group(1))
    return candidates


def _get_query_strings(source: str) -> list[str]:
    """Get all string literals from source that contain SELECT and odds_snapshots/odds_latest."""
    all_strings = _extract_sql_strings(source)
    relevant = []
    for s in all_strings:
        if re.search(r"\bSELECT\b", s, re.IGNORECASE):
            if re.search(r"\bodds_snapshots\b|\bodds_latest\b", s, re.IGNORECASE):
                relevant.append(s)
    return relevant


def _query_needs_filter(sql: str) -> bool:
    """Return True if this SQL references home/draw/away odds columns."""
    return bool(re.search(r"\b(home_odds|draw_odds|away_odds)\b", sql, re.IGNORECASE))


def _query_has_market_filter(sql: str) -> bool:
    """Return True if this SQL includes a market_type filter."""
    return bool(re.search(r"\bmarket_type\b", sql, re.IGNORECASE))


def test_odds_queries_have_market_type_filter():
    """Every odds_snapshots / odds_latest query that reads home/draw/away_odds
    must include a market_type filter to prevent BTTS/O-U data poisoning.

    BUILD-MY-MATCHES-01 (Permanent).
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

        for sql in _get_query_strings(source):
            if _query_needs_filter(sql) and not _query_has_market_filter(sql):
                # Truncate for readability
                snippet = sql.strip()[:200].replace("\n", " ")
                violations.append(f"{fpath}: ...{snippet}...")

    assert not violations, (
        f"\nBUILD-MY-MATCHES-01 VIOLATION: {len(violations)} SQL query/ies reference "
        f"home/draw/away_odds from odds_snapshots/odds_latest WITHOUT market_type filter:\n\n"
        + "\n".join(violations)
        + "\n\nFix: add AND market_type = '1x2' to WHERE clause."
    )
