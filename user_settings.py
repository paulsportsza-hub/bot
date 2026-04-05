"""
User notification preferences — P3-06.

Persists per-user settings that survive bot restarts:
  - tier_filter:  comma-separated active tiers (diamond,gold,silver,bronze)
  - sport_filter: comma-separated active sports (soccer,rugby,cricket,mma,boxing)
  - quiet_start:  SAST hour (0–23) for quiet window start, NULL = off
  - quiet_end:    SAST hour (0–23) for quiet window end, NULL = off

Midnight wrap-around is handled correctly (e.g. 22:00–07:00).
All changes are written to user_settings_log (AC-10 compliance).

Fail-open principle: every public function returns sensible defaults
on DB error — never silences notifications or shows empty screens due
to a transient lock.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime

log = logging.getLogger(__name__)

_TABLE = "user_settings"
_LOG_TABLE = "user_settings_log"
_table_created: bool = False

DEFAULT_TIERS = "diamond,gold,silver,bronze"
DEFAULT_SPORTS = "soccer,rugby,cricket,mma,boxing"

ALL_TIERS = ["diamond", "gold", "silver", "bronze"]
ALL_SPORTS = ["soccer", "rugby", "cricket", "mma", "boxing"]


# ── DB helpers ─────────────────────────────────────────────────────────────


def _db_path() -> str:
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
    """Create tables once per process. Idempotent."""
    global _table_created
    if _table_created:
        return
    try:
        conn = _get_conn()
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {_TABLE} (
                user_id      INTEGER PRIMARY KEY,
                tier_filter  TEXT    NOT NULL DEFAULT '{DEFAULT_TIERS}',
                sport_filter TEXT    NOT NULL DEFAULT '{DEFAULT_SPORTS}',
                quiet_start  INTEGER DEFAULT NULL,
                quiet_end    INTEGER DEFAULT NULL,
                updated_at   TEXT    NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {_LOG_TABLE} (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER NOT NULL,
                setting    TEXT    NOT NULL,
                old_value  TEXT,
                new_value  TEXT,
                changed_at TEXT    NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.commit()
        conn.close()
        _table_created = True
    except Exception as exc:
        log.warning("user_settings: table creation failed: %s", exc)


# ── Defaults ───────────────────────────────────────────────────────────────


def _defaults() -> dict:
    return {
        "tier_filter": DEFAULT_TIERS,
        "sport_filter": DEFAULT_SPORTS,
        "quiet_start": None,
        "quiet_end": None,
    }


# ── Public API ─────────────────────────────────────────────────────────────


def get_settings(user_id: int) -> dict:
    """Return settings dict for user.

    Creates a default row on first call. Fails open: returns defaults on
    any DB error so the rest of the bot keeps working.
    """
    try:
        _ensure_table()
        conn = _get_conn()
        row = conn.execute(
            f"SELECT tier_filter, sport_filter, quiet_start, quiet_end"
            f" FROM {_TABLE} WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        if row is None:
            conn.execute(
                f"INSERT OR IGNORE INTO {_TABLE} (user_id) VALUES (?)",
                (user_id,),
            )
            conn.commit()
            conn.close()
            return _defaults()
        result = {
            "tier_filter": row["tier_filter"] or DEFAULT_TIERS,
            "sport_filter": row["sport_filter"] or DEFAULT_SPORTS,
            "quiet_start": row["quiet_start"],
            "quiet_end": row["quiet_end"],
        }
        conn.close()
        return result
    except Exception as exc:
        log.warning("user_settings.get_settings error (fail-open): %s", exc)
        return _defaults()


def set_tier_filter(user_id: int, tiers: list[str]) -> None:
    """Persist the active tier list for a user."""
    try:
        _ensure_table()
        old = get_settings(user_id)["tier_filter"]
        new_val = ",".join(t for t in ALL_TIERS if t in tiers)
        conn = _get_conn()
        conn.execute(
            f"""
            INSERT INTO {_TABLE} (user_id, tier_filter)
            VALUES (?, ?)
            ON CONFLICT (user_id)
            DO UPDATE SET tier_filter = excluded.tier_filter,
                          updated_at  = datetime('now')
            """,
            (user_id, new_val),
        )
        conn.execute(
            f"INSERT INTO {_LOG_TABLE} (user_id, setting, old_value, new_value)"
            f" VALUES (?, 'tier_filter', ?, ?)",
            (user_id, old, new_val),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        log.warning("user_settings.set_tier_filter error: %s", exc)


def set_sport_filter(user_id: int, sports: list[str]) -> None:
    """Persist the active sport list for a user."""
    try:
        _ensure_table()
        old = get_settings(user_id)["sport_filter"]
        new_val = ",".join(s for s in ALL_SPORTS if s in sports)
        conn = _get_conn()
        conn.execute(
            f"""
            INSERT INTO {_TABLE} (user_id, sport_filter)
            VALUES (?, ?)
            ON CONFLICT (user_id)
            DO UPDATE SET sport_filter = excluded.sport_filter,
                          updated_at   = datetime('now')
            """,
            (user_id, new_val),
        )
        conn.execute(
            f"INSERT INTO {_LOG_TABLE} (user_id, setting, old_value, new_value)"
            f" VALUES (?, 'sport_filter', ?, ?)",
            (user_id, old, new_val),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        log.warning("user_settings.set_sport_filter error: %s", exc)


def set_quiet_hours(user_id: int, start: int | None, end: int | None) -> None:
    """Set quiet hours window. start/end are SAST hours (0–23). None = disabled."""
    try:
        _ensure_table()
        old = get_settings(user_id)
        old_val = (
            f"{old['quiet_start']}-{old['quiet_end']}"
            if old["quiet_start"] is not None
            else "off"
        )
        new_val = f"{start}-{end}" if start is not None else "off"
        conn = _get_conn()
        conn.execute(
            f"""
            INSERT INTO {_TABLE} (user_id, quiet_start, quiet_end)
            VALUES (?, ?, ?)
            ON CONFLICT (user_id)
            DO UPDATE SET quiet_start = excluded.quiet_start,
                          quiet_end   = excluded.quiet_end,
                          updated_at  = datetime('now')
            """,
            (user_id, start, end),
        )
        conn.execute(
            f"INSERT INTO {_LOG_TABLE} (user_id, setting, old_value, new_value)"
            f" VALUES (?, 'quiet_hours', ?, ?)",
            (user_id, old_val, new_val),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        log.warning("user_settings.set_quiet_hours error: %s", exc)


def is_quiet_now(user_id: int) -> bool:
    """Return True if current SAST time falls within the user's quiet window.

    Handles midnight wrap-around (e.g. 22:00–07:00 means hours 22,23,0–6).
    Fails open: returns False on DB error so notifications are never silenced
    unexpectedly due to a transient DB issue.
    """
    try:
        settings = get_settings(user_id)
        start = settings["quiet_start"]
        end = settings["quiet_end"]
        if start is None or end is None:
            return False
        from zoneinfo import ZoneInfo  # noqa: PLC0415
        now_hour = datetime.now(ZoneInfo("Africa/Johannesburg")).hour
        if start <= end:
            # Contiguous window (e.g. 02:00–06:00)
            return start <= now_hour < end
        # Midnight wrap-around (e.g. 22:00–07:00)
        return now_hour >= start or now_hour < end
    except Exception as exc:
        log.warning("user_settings.is_quiet_now error (fail-open): %s", exc)
        return False
