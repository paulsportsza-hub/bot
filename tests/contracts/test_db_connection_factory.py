"""Regression guard: FIX-DBLOCK-CONNECTION-FACTORY-AUDIT-01.

Broader coverage than test_db_connection.py — scans all production directories
including scripts/, publisher/, and bot/scripts/ for raw sqlite3.connect() calls.

If this test fails: a production file was added or modified with a raw
sqlite3.connect() call instead of the approved factory:
  - Bot code:     from db_connection import get_connection
  - Scraper code: from scrapers.db_connect import connect_odds_db

W81-DBLOCK: permanent rule — never call sqlite3.connect() directly.
"""
from __future__ import annotations

import os
import subprocess
import sys


def _project_root() -> str:
    # tests/contracts/ → tests/ → bot/ → project root
    return os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    )


def _scan(dirs: list[str]) -> list[str]:
    """Grep for sqlite3.connect( in the given dirs (Python files only)."""
    root = _project_root()
    targets = [os.path.join(root, d) for d in dirs]
    result = subprocess.run(
        ["grep", "-rn", "sqlite3.connect(", "--include=*.py"] + targets,
        capture_output=True, text=True,
    )
    if not result.stdout.strip():
        return []
    return result.stdout.strip().split("\n")


def _is_allowed(line: str) -> bool:
    """Return True if the occurrence is a permitted pattern."""
    # Comment lines only mentioning the pattern (e.g. "# never sqlite3.connect() directly")
    # Format: filepath:linenum:content — extract content after second colon
    parts = line.split(":", 2)
    if len(parts) >= 3:
        content = parts[2].lstrip()
        if content.startswith("#"):
            return True
    # The factory files themselves
    if "db_connection.py" in line or "db_connect.py" in line:
        return True
    # Test files and test directories
    if "/tests/" in line or "/test_" in os.path.basename(line.split(":")[0]):
        return True
    # Test helpers in qa/ subdirectories
    if "/qa/" in line and "test_" in os.path.basename(line.split(":")[0]):
        return True
    # Compiled bytecode
    if "__pycache__" in line or ".pyc" in line:
        return True
    # Virtual environment
    if ".venv" in line:
        return True
    # In-memory DBs used in tests (even if not in /tests/ path)
    if '":memory:"' in line or "':memory:'" in line:
        return True
    # URI read-only mode (file:path?mode=ro) — legitimate read-only pattern
    if "uri=True" in line:
        return True
    # The factory itself legitimately calls sqlite3.connect internally
    if "scrapers/db_connect.py" in line or "bot/db_connection.py" in line:
        return True
    # Migration scripts — one-shot, low frequency
    if "/migrations/" in line:
        return True
    # Archived canonical directory — not live production code
    if "_canonical_" in line:
        return True
    # evidence_pack.py has a special URI mode connection for read-only cache ops
    if "evidence_pack.py" in line:
        return True
    # Shell script with embedded Python snippet — not importable
    if ".sh:" in line:
        return True
    # compliance.py connects to its own quota DB, not odds.db
    if "compliance.py" in line:
        return True
    return False


def test_no_raw_sqlite_connect_scripts():
    """No raw sqlite3.connect() in /home/paulsportsza/scripts/ (production QA scripts)."""
    lines = _scan(["scripts"])
    violations = [ln for ln in lines if ln.strip() and not _is_allowed(ln)]
    assert violations == [], (
        f"\nREGRESSION W81-DBLOCK: {len(violations)} scripts/ file(s) use raw sqlite3.connect():\n\n"
        + "\n".join(violations)
        + "\n\nFix: use scrapers.db_connect.connect_odds_db()"
    )


def test_no_raw_sqlite_connect_publisher():
    """No raw sqlite3.connect() in publisher/ (excluding compliance.py quota DB)."""
    lines = _scan(["publisher"])
    violations = [ln for ln in lines if ln.strip() and not _is_allowed(ln)]
    assert violations == [], (
        f"\nREGRESSION W81-DBLOCK: {len(violations)} publisher/ file(s) use raw sqlite3.connect():\n\n"
        + "\n".join(violations)
        + "\n\nFix: use scrapers.db_connect.connect_odds_db()"
    )


def test_no_raw_sqlite_connect_bot_scripts():
    """No raw sqlite3.connect() in bot/scripts/ production scripts."""
    lines = _scan(["bot/scripts"])
    violations = [ln for ln in lines if ln.strip() and not _is_allowed(ln)]
    assert violations == [], (
        f"\nREGRESSION W81-DBLOCK: {len(violations)} bot/scripts/ file(s) use raw sqlite3.connect():\n\n"
        + "\n".join(violations)
        + "\n\nFix: use scrapers.db_connect.connect_odds_db()"
    )


def test_factory_wal_and_timeout(tmp_path):
    """connect_odds_db() applies WAL + busy_timeout=60000ms to every connection."""
    root = _project_root()
    scrapers_dir = os.path.join(root, "scrapers")
    if scrapers_dir not in sys.path:
        sys.path.insert(0, scrapers_dir)
    from db_connect import connect_odds_db  # type: ignore[import]

    test_db = str(tmp_path / "factory_test.db")
    conn = connect_odds_db(test_db)
    try:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal", f"Expected WAL, got '{mode}'"
        timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        assert timeout >= 30_000, (
            f"Expected busy_timeout >= 30000ms, got {timeout}ms. "
            "Factory must set at least 30s wait to survive scraper write windows."
        )
    finally:
        conn.close()
