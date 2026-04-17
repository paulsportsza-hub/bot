"""cron_window.py — Pure-Python cron expression evaluator for staleness window detection.

All cron expressions are interpreted as SAST (UTC+2), matching the live server's crontab.
No external dependencies. ~300 LOC.

Public API
----------
    parse_multi(expr)               -> list[str]
    is_in_window(expr, now_utc)     -> bool
    is_in_any_window(windows, now)  -> bool
    previous_fire(expr, now_utc)    -> datetime | None
    next_fire(expr, now_utc)        -> datetime | None
    last_window_close(windows, now) -> datetime | None

Timezone
--------
SAST = UTC+2, no DST. All cron expressions are evaluated in SAST time,
consistent with /etc/crontab on 178.128.171.28.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Optional

# SAST = UTC+2, no DST
_SAST_OFFSET = timedelta(hours=2)

# Maximum look-back / look-forward window for fire-time searches (8 days covers weekly crons)
_MAX_SCAN_MINUTES = 60 * 24 * 8


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _to_sast(dt_utc: datetime) -> datetime:
    """Convert a UTC datetime (aware or naive) to a naive SAST datetime."""
    if dt_utc.tzinfo is not None:
        utc_offset = dt_utc.utcoffset() or timedelta(0)
        naive_utc = dt_utc.replace(tzinfo=None) + utc_offset
    else:
        naive_utc = dt_utc
    return naive_utc + _SAST_OFFSET


def _from_sast(dt_sast_naive: datetime) -> datetime:
    """Convert a naive SAST datetime to a UTC-aware datetime."""
    return (dt_sast_naive - _SAST_OFFSET).replace(tzinfo=timezone.utc)


def _parse_field(field: str, lo: int, hi: int) -> frozenset:
    """Parse a single cron field into a frozenset of valid integer values.

    Handles: *, */n, a-b, a-b/n, comma-separated combinations.

    Args:
        field: Raw cron field string.
        lo:    Inclusive lower bound for the field (e.g. 0 for minutes, 1 for months).
        hi:    Inclusive upper bound (e.g. 59 for minutes, 12 for months).
    """
    result: set[int] = set()
    for part in field.split(','):
        part = part.strip()
        if part == '*':
            result.update(range(lo, hi + 1))
        elif part.startswith('*/'):
            step = int(part[2:])
            if step < 1:
                raise ValueError(f"Invalid step in cron field: {part!r}")
            result.update(range(lo, hi + 1, step))
        elif '-' in part:
            if '/' in part:
                rng, step_s = part.split('/', 1)
                a_s, b_s = rng.split('-', 1)
                a, b, step = int(a_s), int(b_s), int(step_s)
                result.update(range(a, b + 1, step))
            else:
                a_s, b_s = part.split('-', 1)
                a, b = int(a_s), int(b_s)
                result.update(range(a, b + 1))
        else:
            result.add(int(part))
    return frozenset(result)


class _ParsedCron:
    """Parsed representation of a 5-field cron expression."""

    __slots__ = ('minutes', 'hours', 'doms', 'months', 'dows', 'raw')

    def __init__(self, raw: str, minutes, hours, doms, months, dows):
        self.raw = raw
        self.minutes: frozenset[int] = minutes
        self.hours:   frozenset[int] = hours
        self.doms:    frozenset[int] = doms
        self.months:  frozenset[int] = months
        self.dows:    frozenset[int] = dows  # 0=Sun, 1=Mon, ..., 6=Sat

    def matches(self, dt_sast: datetime) -> bool:
        """Return True if dt_sast (naive, SAST) matches this cron expression."""
        if dt_sast.month not in self.months:
            return False
        # Standard cron: if both dom and dow are restricted (not *), use OR logic.
        # If either is *, the other must match. Detect * by comparing full-range size.
        dom_restricted = len(self.doms) < 31
        dow_restricted = len(self.dows) < 7
        dom_ok = dt_sast.day in self.doms
        # Python weekday(): Mon=0 → cron dow=1; Sun=6 → cron dow=0
        sast_dow = (dt_sast.weekday() + 1) % 7
        dow_ok = sast_dow in self.dows
        if dom_restricted and dow_restricted:
            # OR logic per POSIX cron
            if not (dom_ok or dow_ok):
                return False
        else:
            if not dom_ok:
                return False
            if not dow_ok:
                return False
        if dt_sast.hour not in self.hours:
            return False
        if dt_sast.minute not in self.minutes:
            return False
        return True

    def in_active_hours(self, dt_sast: datetime) -> bool:
        """Return True if dt_sast falls within the cron's active hour+day window.

        Unlike matches(), this does NOT check minutes — it answers "is this a
        period where the cron is expected to run (the window is open)?"
        """
        if dt_sast.month not in self.months:
            return False
        dom_restricted = len(self.doms) < 31
        dow_restricted = len(self.dows) < 7
        dom_ok = dt_sast.day in self.doms
        sast_dow = (dt_sast.weekday() + 1) % 7
        dow_ok = sast_dow in self.dows
        if dom_restricted and dow_restricted:
            if not (dom_ok or dow_ok):
                return False
        else:
            if not dom_ok:
                return False
            if not dow_ok:
                return False
        return dt_sast.hour in self.hours


_SKIP_VALUES = frozenset({'on-demand', '@reboot', ''})


def _parse_expr(expr: str) -> Optional[_ParsedCron]:
    """Parse a 5-field cron expression string. Returns None for non-parseable inputs."""
    expr = expr.strip()
    if expr in _SKIP_VALUES:
        return None
    parts = expr.split()
    if len(parts) != 5:
        return None
    m_field, h_field, dom_field, mon_field, dow_field = parts
    try:
        minutes = _parse_field(m_field, 0, 59)
        hours   = _parse_field(h_field, 0, 23)
        doms    = _parse_field(dom_field, 1, 31)
        months  = _parse_field(mon_field, 1, 12)
        # dow: normalize 7 → 0 (both mean Sunday)
        raw_dows = _parse_field(dow_field, 0, 7)
        dows = frozenset((d % 7) for d in raw_dows)
    except (ValueError, ZeroDivisionError):
        return None
    return _ParsedCron(expr, minutes, hours, doms, months, dows)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_multi(expr: str) -> list[str]:
    """Split a semicolon-separated multi-window cron string into individual expressions.

    Example:
        parse_multi("*/10 12-21 * * *; */20 8-11,22-23 * * *")
        → ["*/10 12-21 * * *", "*/20 8-11,22-23 * * *"]
    """
    if not expr or expr.strip() in _SKIP_VALUES:
        return []
    return [part.strip() for part in expr.split(';') if part.strip()]


def is_in_window(expr: str, now_utc: datetime) -> bool:
    """Return True if now_utc is inside this cron expression's active window.

    "In window" means the current SAST hour (and day-of-week, if restricted)
    is within the set of hours where this cron fires. Minute-level precision
    is NOT required — we check whether the window is open, not whether the
    exact fire-time has passed.

    Returns False for unparseable expressions (on-demand, etc.).
    """
    parsed = _parse_expr(expr)
    if parsed is None:
        return False
    now_sast = _to_sast(now_utc)
    return parsed.in_active_hours(now_sast)


def is_in_any_window(windows: list[str], now_utc: datetime) -> bool:
    """Return True if now_utc is inside ANY of the given cron windows."""
    return any(is_in_window(expr, now_utc) for expr in windows)


def previous_fire(expr: str, now_utc: datetime) -> Optional[datetime]:
    """Return the most recent scheduled fire time strictly before now_utc.

    Scans backwards minute-by-minute in SAST up to _MAX_SCAN_MINUTES (8 days).
    Returns a UTC-aware datetime, or None if no fire found.
    """
    parsed = _parse_expr(expr)
    if parsed is None:
        return None

    # Start 1 minute before now (exclusive "before now")
    now_sast = _to_sast(now_utc).replace(second=0, microsecond=0)
    candidate = now_sast - timedelta(minutes=1)

    for _ in range(_MAX_SCAN_MINUTES):
        if parsed.matches(candidate):
            return _from_sast(candidate)
        candidate -= timedelta(minutes=1)
    return None


def next_fire(expr: str, now_utc: datetime) -> Optional[datetime]:
    """Return the next scheduled fire time strictly after now_utc.

    Scans forwards minute-by-minute in SAST up to _MAX_SCAN_MINUTES (8 days).
    Returns a UTC-aware datetime, or None if no fire found.
    """
    parsed = _parse_expr(expr)
    if parsed is None:
        return None

    now_sast = _to_sast(now_utc).replace(second=0, microsecond=0)
    candidate = now_sast + timedelta(minutes=1)

    for _ in range(_MAX_SCAN_MINUTES):
        if parsed.matches(candidate):
            return _from_sast(candidate)
        candidate += timedelta(minutes=1)
    return None


def last_window_close(windows: list[str], now_utc: datetime) -> Optional[datetime]:
    """Return the most recent scheduled fire time across all windows, before now_utc.

    This is the "window close" time — the last moment when one of the given
    crons was scheduled to fire before the current inter-window gap began.

    Call this only when is_in_any_window() returns False; the result represents
    the end of the most recent active window.

    Returns None if no prior fire can be found (source never had a window).
    """
    best: Optional[datetime] = None
    for expr in windows:
        t = previous_fire(expr, now_utc)
        if t is not None:
            if best is None or t > best:
                best = t
    return best
