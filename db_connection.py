"""Centralised SQLite connection factory for the bot.

ALL database access MUST go through get_connection() — never bare sqlite3.connect().
This guarantees WAL mode + 30-second busy_timeout on every connection,
preventing 'database is locked' OperationalError.

W81-DBLOCK: This module is the PERMANENT fix. Adding WAL+timeout per-file
has been done THREE times and regressed each time. This factory makes it
structurally impossible to open a connection without the correct settings.

Standing order: No file in this project may call sqlite3.connect() directly.
Use: from db_connection import get_connection
"""

import logging
import os
import sqlite3
import time

log = logging.getLogger(__name__)

# The ONE database path — override via MZANSI_DB_PATH env var
ODDS_DB = os.environ.get(
    "MZANSI_DB_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scrapers", "odds.db"),
)

_BUSY_MS = 30_000          # 30 seconds
_RETRY_ATTEMPTS = 5        # W81-DBLOCK: was 3 — extra headroom for long scraper runs
_RETRY_BACKOFF = 0.25      # W81-DBLOCK: was 1.0 — faster first retry


def get_connection(db_path: str | None = None, readonly: bool = False) -> sqlite3.Connection:
    """Open a SQLite database with WAL + busy_timeout enforced.

    ALWAYS use this instead of sqlite3.connect().

    Args:
        db_path: Path to SQLite database (default: scrapers/odds.db via MZANSI_DB_PATH)
        readonly: If True, opens in read-only URI mode (no writes possible)

    Returns:
        sqlite3.Connection with WAL + busy_timeout + Row factory already set.
        sqlite3.Row supports both dict-style (row["col"]) and tuple (row[0]) access.
    """
    path = db_path or ODDS_DB

    if readonly:
        uri = f"file:{path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=_BUSY_MS / 1000)
    else:
        conn = sqlite3.connect(path, timeout=_BUSY_MS / 1000)

    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(f"PRAGMA busy_timeout={_BUSY_MS}")
    conn.row_factory = sqlite3.Row
    return conn


def write_with_retry(fn, *args, attempts: int = _RETRY_ATTEMPTS, backoff: float = _RETRY_BACKOFF, **kwargs):
    """Call fn(*args, **kwargs), retrying up to `attempts` times on 'database is locked'.

    Uses exponential backoff starting at `backoff` seconds.
    The fn callable is expected to perform side-effect write operations.

    Raises:
        sqlite3.OperationalError if all attempts are exhausted.
    """
    wait = backoff
    for attempt in range(1, attempts + 1):
        try:
            return fn(*args, **kwargs)
        except sqlite3.OperationalError as exc:
            if "locked" in str(exc).lower() and attempt < attempts:
                log.warning(
                    "write_with_retry: locked (attempt %d/%d), retrying in %.2fs",
                    attempt, attempts, wait,
                )
                time.sleep(wait)
                wait *= 2
            else:
                raise


def batch_write(conn: sqlite3.Connection, statements: list) -> None:
    """Execute a list of (sql, params) tuples in a single transaction with retry.

    All statements execute atomically — either all succeed or all roll back.

    Args:
        conn: Open connection (should be from get_connection())
        statements: list of (sql_string, params_tuple) pairs
    """
    def _run():
        with conn:
            for sql, params in statements:
                conn.execute(sql, params)

    write_with_retry(_run)
