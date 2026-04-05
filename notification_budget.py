"""
Notification audible budget for MzansiEdge.

Tracks per-user daily audible notification count. Persists across restarts
via the bot's SQLite database (mzansiedge.db).

Rules (P3-05):
  - Morning digest (non-21:00 hour): audible if budget allows
  - Pre-match Gold+ alert: audible if budget allows
  - Post-match results: always silent
  - Evening recap (21:00 SAST): always silent
  - Max 3 audible per user per SAST calendar day
  - Counter resets at 00:00 SAST — call reset() in the nightly cron job

Usage:
    import notification_budget as nb
    if nb.can_send_audible(user_id):
        nb.record_audible(user_id)
        disable_notification = False
    else:
        disable_notification = True
"""

import logging
import os

log = logging.getLogger(__name__)

MAX_AUDIBLE_PER_DAY = 3
_TABLE = "notification_audible_counts"

# Module-level flag: table creation is idempotent but we only need one check per process.
_table_created: bool = False


# ── DB helpers ────────────────────────────────────────────


def _db_path() -> str:
    """Return absolute path to the bot's main SQLite database."""
    try:
        import config  # noqa: PLC0415
        if config.DATABASE_PATH is not None:
            return str(config.DATABASE_PATH)
    except Exception:
        pass
    return os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "data", "mzansiedge.db"
    )


def _get_conn():
    from db_connection import get_connection  # noqa: PLC0415
    return get_connection(_db_path())


def _ensure_table() -> None:
    """Create audible counts table if it does not exist. Runs at most once per process."""
    global _table_created
    if _table_created:
        return
    try:
        conn = _get_conn()
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {_TABLE} (
                user_id   INTEGER NOT NULL,
                sast_date TEXT    NOT NULL,
                count     INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (user_id, sast_date)
            )
        """)
        conn.commit()
        conn.close()
        _table_created = True
    except Exception as exc:
        log.warning("notification_budget: failed to create table: %s", exc)


# ── Date helper ───────────────────────────────────────────


def _today_sast() -> str:
    """Return today's date in SAST as an ISO string (YYYY-MM-DD)."""
    from datetime import datetime  # noqa: PLC0415
    from zoneinfo import ZoneInfo  # noqa: PLC0415
    return datetime.now(ZoneInfo("Africa/Johannesburg")).date().isoformat()


# ── Public API ────────────────────────────────────────────


def can_send_audible(user_id: int) -> bool:
    """Return True if user has audible notifications remaining today (SAST).

    Fails open on DB error — always returns True rather than silencing
    notifications unexpectedly.
    """
    try:
        _ensure_table()
        conn = _get_conn()
        row = conn.execute(
            f"SELECT count FROM {_TABLE} WHERE user_id = ? AND sast_date = ?",
            (user_id, _today_sast()),
        ).fetchone()
        conn.close()
        count = int(row[0]) if row else 0
        return count < MAX_AUDIBLE_PER_DAY
    except Exception as exc:
        log.warning("notification_budget.can_send_audible error (fail-open): %s", exc)
        return True


def record_audible(user_id: int) -> None:
    """Increment the audible count for user today (SAST).

    Idempotent on duplicate calls — uses SQLite UPSERT.
    """
    try:
        _ensure_table()
        conn = _get_conn()
        conn.execute(
            f"""
            INSERT INTO {_TABLE} (user_id, sast_date, count)
            VALUES (?, ?, 1)
            ON CONFLICT (user_id, sast_date)
            DO UPDATE SET count = count + 1
            """,
            (user_id, _today_sast()),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        log.warning("notification_budget.record_audible error: %s", exc)


def reset() -> None:
    """Delete audible count rows for past SAST dates.

    Call this at 00:00 SAST. Rows for the current SAST day are left intact
    so that early-morning sends are counted correctly.
    """
    try:
        _ensure_table()
        conn = _get_conn()
        today = _today_sast()
        deleted = conn.execute(
            f"DELETE FROM {_TABLE} WHERE sast_date < ?", (today,)
        ).rowcount
        conn.commit()
        conn.close()
        if deleted:
            log.info("notification_budget.reset: pruned %d stale rows", deleted)
    except Exception as exc:
        log.warning("notification_budget.reset error: %s", exc)
