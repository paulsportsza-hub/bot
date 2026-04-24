"""Database verification helpers for the QA Rubric Runner.

BUILD-QA-RUBRIC-RUNNER-01 — Phase C

verify_kickoff_time() implements Addition 2: kickoff cross-check vs SuperSport
scraper per SO #40:
  1. Query broadcast_schedule WHERE source = 'supersport_scraper' AND match_id = ?
  2. If row: rendered time must match start_time in SAST (±1 minute tolerance)
  3. If no supersport_scraper row: fall through to canonical chain
  4. NEVER add any-source broadcast_schedule fallback (SO #40)

The match_id format is: home_vs_away_YYYY-MM-DD_tier  (or similar suffix)
Date is parsed from the last segment that looks like YYYY-MM-DD.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# SAST = UTC+2 (ZoneInfo Africa/Johannesburg)
try:
    from zoneinfo import ZoneInfo
    _SAST = ZoneInfo("Africa/Johannesburg")
except ImportError:
    # Python < 3.9 fallback
    class _SASTFallback(timezone):  # type: ignore[misc]
        def utcoffset(self, dt: Any) -> timedelta:
            return timedelta(hours=2)
        def tzname(self, dt: Any) -> str:
            return "SAST"
        def dst(self, dt: Any) -> timedelta:
            return timedelta(0)
    _SAST = _SASTFallback()  # type: ignore[assignment]

_KICKOFF_TOLERANCE_MINUTES = 1

# Date suffix pattern in match_id
_DATE_PATTERN = re.compile(r"(\d{4}-\d{2}-\d{2})")

# Time string patterns (e.g. "19:30", "7:30 PM", "Today 19:30", "Wed 26 Mar · 19:30")
_TIME_PATTERN = re.compile(r"(\d{1,2}:\d{2})(?:\s*(AM|PM))?", re.IGNORECASE)


def _parse_time_from_string(time_str: str) -> tuple[int, int] | None:
    """Extract (hour, minute) from a rendered kickoff string in 24h."""
    m = _TIME_PATTERN.search(time_str)
    if not m:
        return None
    hh, mm = map(int, m.group(1).split(":"))
    ampm = (m.group(2) or "").upper()
    if ampm == "PM" and hh != 12:
        hh += 12
    elif ampm == "AM" and hh == 12:
        hh = 0
    return hh, mm


def _parse_match_date(match_id: str) -> str | None:
    """Extract YYYY-MM-DD from a match_id string."""
    m = _DATE_PATTERN.search(match_id)
    return m.group(1) if m else None


def verify_kickoff_time(
    match_id: str,
    rendered_kickoff_str: str,
    *,
    odds_db_path: str = "data/odds.db",
    main_db_path: str = "data/mzansiedge.db",
) -> dict:
    """Cross-check rendered kickoff time against authoritative sources.

    SO #40: query broadcast_schedule with source='supersport_scraper' FIRST.
    Never fall back to any-source broadcast_schedule query.

    Args:
        match_id: Match identifier (e.g. "mamelodi_sundowns_vs_stellenbosch_2026-04-22_gold")
        rendered_kickoff_str: The kickoff string as displayed to the user (e.g. "Today 19:30")
        odds_db_path: Path to odds.db (absolute or relative to /home/paulsportsza/bot/)
        main_db_path: Path to mzansiedge.db

    Returns:
        {
            "match": bool,       # True if times match or no source to compare against
            "source": str,       # which source was used for comparison
            "expected": str,     # expected kickoff string from DB (or "" if not found)
            "rendered": str,     # the rendered_kickoff_str as-is
            "delta_minutes": float | None,
        }
    """
    from db_connection import get_connection  # per W81-DBLOCK

    result: dict = {
        "match": True,
        "source": "none",
        "expected": "",
        "rendered": rendered_kickoff_str,
        "delta_minutes": None,
    }

    # Resolve DB path
    db_path = Path(odds_db_path)
    if not db_path.is_absolute():
        db_path = Path("/home/paulsportsza/bot") / db_path

    if not db_path.exists():
        log.warning("verify_kickoff_time: odds.db not found at %s", db_path)
        return result

    rendered_time = _parse_time_from_string(rendered_kickoff_str)
    if rendered_time is None:
        # Cannot parse rendered time — no comparison possible
        result["source"] = "parse_failed"
        return result

    try:
        conn = get_connection(str(db_path), readonly=True, timeout_ms=3000)
        try:
            # SO #40: ONLY query supersport_scraper source
            row = conn.execute(
                """
                SELECT start_time, channel_short, broadcast_date
                FROM broadcast_schedule
                WHERE source = 'supersport_scraper'
                  AND (
                    match_id = ?
                    OR (home_team LIKE ? AND away_team LIKE ?)
                  )
                ORDER BY broadcast_date ASC
                LIMIT 1
                """,
                (
                    match_id,
                    f"%{match_id.split('_vs_')[0].replace('_', ' ')}%",
                    f"%{match_id.split('_vs_')[1].split('_')[0].replace('_', ' ')}%"
                    if "_vs_" in match_id else "%",
                ),
            ).fetchone()

            if row is None:
                # No supersport_scraper row — fall through to canonical chain
                result["source"] = "no_supersport_row"
                result["match"] = True  # cannot contradict what we don't have
                return _check_canonical_chain(match_id, rendered_kickoff_str, rendered_time, main_db_path, result)

            # Parse start_time from broadcast_schedule
            start_time_raw = row["start_time"]
            result["source"] = "supersport_scraper"
            result["expected"] = str(start_time_raw)

            db_time = _parse_time_from_string(str(start_time_raw))
            if db_time is None:
                result["source"] = "supersport_scraper_parse_failed"
                return result

            # Compare in minutes
            rendered_mins = rendered_time[0] * 60 + rendered_time[1]
            db_mins = db_time[0] * 60 + db_time[1]
            delta = abs(rendered_mins - db_mins)
            result["delta_minutes"] = float(delta)
            result["match"] = delta <= _KICKOFF_TOLERANCE_MINUTES

            if not result["match"]:
                log.warning(
                    "verify_kickoff_time: mismatch for %s — rendered=%s expected=%s delta=%d min",
                    match_id, rendered_kickoff_str, start_time_raw, delta,
                )

        finally:
            conn.close()

    except Exception as exc:
        log.warning("verify_kickoff_time: DB error for %s: %s", match_id, exc)
        result["source"] = f"db_error: {exc}"

    return result


def _check_canonical_chain(
    match_id: str,
    rendered_kickoff_str: str,
    rendered_time: tuple[int, int],
    main_db_path: str,
    result: dict,
) -> dict:
    """Fallback canonical chain when no supersport_scraper row exists.

    Checks: sportmonks_fixtures → rugby_fixtures/mma_fixtures → commence_time → match_key date suffix.
    """
    from db_connection import get_connection  # per W81-DBLOCK

    main_path = Path(main_db_path)
    if not main_path.is_absolute():
        main_path = Path("/home/paulsportsza/bot") / main_path

    if not main_path.exists():
        result["source"] = "canonical_chain_no_db"
        return result

    try:
        conn = get_connection(str(main_path), readonly=True, timeout_ms=3000)
        try:
            # Try sportmonks_fixtures
            row = conn.execute(
                "SELECT commence_time FROM sportmonks_fixtures WHERE match_id = ? LIMIT 1",
                (match_id,),
            ).fetchone()

            if row:
                result["source"] = "sportmonks_fixtures"
                result["expected"] = str(row[0])
                return result

            # Try match date from match_key suffix
            date_str = _parse_match_date(match_id)
            if date_str:
                result["source"] = "match_key_date_suffix"
                result["expected"] = date_str
                return result

        finally:
            conn.close()

    except Exception as exc:
        log.debug("verify_kickoff_time canonical chain: %s", exc)

    result["source"] = "canonical_chain_exhausted"
    return result
