"""Regression guard: database connection factory enforcement.

W81-DBLOCK: These 3 tests make regression architecturally impossible.

If ANY test fails:
  - test_no_raw_sqlite_connect → someone added raw sqlite3.connect() to production code
  - test_wal_mode_enforced     → WAL mode is not active on odds.db
  - test_busy_timeout_enforced → busy_timeout is not set on new connections

DO NOT modify the exclusion list without understanding why.
"""

import subprocess
import sys
import os


def _get_project_root():
    """Return the /home/paulsportsza directory."""
    return "/home/paulsportsza"


def test_no_raw_sqlite_connect():
    """REGRESSION GUARD: No production file may call sqlite3.connect() directly.

    All connections must go through:
      - bot/db_connection.py  → get_connection()
      - scrapers/db_connect.py → connect_odds_db() / connect_db()

    ALLOWED exceptions (whitelisted below):
      - db_connection.py and db_connect.py themselves (the factory files)
      - test_* files and /tests/ directories (use :memory: legitimately)
      - __pycache__ directories
      - .venv (third-party packages)
    """
    root = _get_project_root()
    result = subprocess.run(
        ["grep", "-rn", "sqlite3.connect(",
         f"{root}/bot/", f"{root}/scrapers/",
         "--include=*.py"],
        capture_output=True, text=True
    )

    lines = result.stdout.strip().split("\n") if result.stdout.strip() else []

    violations = [
        line for line in lines
        if line.strip()
        and "db_connection.py" not in line
        and "db_connect.py" not in line
        and "__pycache__" not in line
        and ".venv" not in line
        and "/tests/" not in line
        and "test_" not in line.split("/")[-1]   # exclude test_*.py files
        and ":memory:" not in line                # in-memory DBs for unit tests
        and "uri=True" not in line                # read-only URI mode (file:path?mode=ro)
        and "shadow_review.py" not in line        # QA/diagnostic script, not production
        and "qa3_reverify.py" not in line         # QA/diagnostic script, not production
    ]

    assert len(violations) == 0, (
        f"\nREGRESSION W81-DBLOCK: {len(violations)} production file(s) use raw "
        f"sqlite3.connect() instead of get_connection() / connect_odds_db():\n\n"
        + "\n".join(violations)
        + "\n\nFix: replace sqlite3.connect(...) with:\n"
        + "  Bot:     from db_connection import get_connection; conn = get_connection(path)\n"
        + "  Scraper: from scrapers.db_connect import connect_odds_db; conn = connect_odds_db(path)"
    )


def test_wal_mode_enforced():
    """Verify WAL mode is active on odds.db via get_connection()."""
    sys.path.insert(0, "/home/paulsportsza/bot")
    from db_connection import get_connection

    odds_db = "/home/paulsportsza/scrapers/odds.db"
    if not os.path.exists(odds_db):
        import pytest
        pytest.skip("odds.db not present on this machine")

    conn = get_connection()
    try:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal", (
            f"Expected WAL journal mode, got '{mode}'. "
            "odds.db must be in WAL mode for concurrent access."
        )
    finally:
        conn.close()


def test_busy_timeout_enforced():
    """Verify busy_timeout=30000ms is configured on new connections."""
    sys.path.insert(0, "/home/paulsportsza/bot")
    from db_connection import get_connection, _BUSY_MS

    odds_db = "/home/paulsportsza/scrapers/odds.db"
    if not os.path.exists(odds_db):
        import pytest
        pytest.skip("odds.db not present on this machine")

    conn = get_connection()
    try:
        timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        assert timeout == _BUSY_MS, (
            f"Expected busy_timeout={_BUSY_MS}ms, got {timeout}ms. "
            "Every connection must have a 30-second wait before raising OperationalError."
        )
    finally:
        conn.close()
