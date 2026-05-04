"""Regression guard: database connection factory enforcement.

W81-DBLOCK: These 3 tests make regression architecturally impossible.

If ANY test fails:
  - test_no_raw_sqlite_connect → someone added raw sqlite3.connect() to production code
  - test_wal_mode_enforced     → WAL mode is not applied by get_connection()
  - test_busy_timeout_enforced → busy_timeout is not set by get_connection()

DO NOT modify the exclusion list without understanding why.

BUILD-TEST-ISOLATION: WAL and timeout tests use a fresh tmp DB, not the live
scrapers/odds.db. Scraper write locks must never cause test flakiness.
"""

import subprocess
import sys
import os


def _get_project_root():
    """Return the project home directory."""
    import os
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


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
    ]

    assert len(violations) == 0, (
        f"\nREGRESSION W81-DBLOCK: {len(violations)} production file(s) use raw "
        f"sqlite3.connect() instead of get_connection() / connect_odds_db():\n\n"
        + "\n".join(violations)
        + "\n\nFix: replace sqlite3.connect(...) with:\n"
        + "  Bot:     from db_connection import get_connection; conn = get_connection(path)\n"
        + "  Scraper: from scrapers.db_connect import connect_odds_db; conn = connect_odds_db(path)"
    )


def test_wal_mode_enforced(tmp_path):
    """Verify get_connection() applies WAL mode to every new SQLite DB.

    Uses an isolated tmp DB — never touches the live scrapers/odds.db.
    Scraper write locks cannot interfere with this test.
    """
    _bot_dir = os.path.join(_get_project_root(), "bot")
    sys.path.insert(0, _bot_dir)
    from db_connection import get_connection

    test_db = str(tmp_path / "test_wal.db")
    conn = get_connection(test_db)
    try:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal", (
            f"Expected WAL journal mode, got '{mode}'. "
            "get_connection() must apply WAL mode to every connection."
        )
    finally:
        conn.close()


def test_busy_timeout_enforced(tmp_path):
    """Verify get_connection() applies busy_timeout=30000ms to every new SQLite DB.

    Uses an isolated tmp DB — never touches the live scrapers/odds.db.
    Scraper write locks cannot interfere with this test.
    """
    _bot_dir = os.path.join(_get_project_root(), "bot")
    sys.path.insert(0, _bot_dir)
    from db_connection import get_connection, _BUSY_MS

    test_db = str(tmp_path / "test_timeout.db")
    conn = get_connection(test_db)
    try:
        timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        assert timeout == _BUSY_MS, (
            f"Expected busy_timeout={_BUSY_MS}ms, got {timeout}ms. "
            "Every connection must have a 30-second wait before raising OperationalError."
        )
    finally:
        conn.close()
