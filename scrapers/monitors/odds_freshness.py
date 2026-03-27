"""Monitor odds freshness by bookmaker."""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone

from config import ensure_scrapers_importable
ensure_scrapers_importable()

if "scrapers.db_connect" not in sys.modules:
    import importlib.util as _ilu, os as _os
    _spec = _ilu.spec_from_file_location(
        "scrapers.db_connect",
        _os.path.normpath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "../../../scrapers/db_connect.py"))
    )
    _mod = _ilu.module_from_spec(_spec)
    sys.modules["scrapers.db_connect"] = _mod
    _spec.loader.exec_module(_mod)
    del _ilu, _os, _spec, _mod
from scrapers.db_connect import connect_odds_db

from .alert import send_alert, send_all_clear

logger = logging.getLogger(__name__)

STALE_THRESHOLD_HOURS = 2


def _parse_timestamp(value: str) -> datetime:
    normalized = value.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def check_freshness(db_path: str = "odds.db") -> list[dict]:
    """Return bookmakers with stale or unparseable scrape timestamps."""
    conn = connect_odds_db(db_path)
    violations: list[dict] = []
    try:
        rows = conn.execute(
            """
            SELECT bookmaker, MAX(scraped_at) AS last_scrape
            FROM odds_snapshots
            GROUP BY bookmaker
            """
        ).fetchall()
        now = datetime.now(timezone.utc)
        for bookmaker, last_scrape in rows:
            if not last_scrape:
                violations.append(
                    {"bookmaker": bookmaker, "last_scrape": None, "hours_stale": None}
                )
                continue
            try:
                last_scrape_dt = _parse_timestamp(last_scrape)
            except ValueError:
                violations.append(
                    {
                        "bookmaker": bookmaker,
                        "last_scrape": last_scrape,
                        "hours_stale": None,
                    }
                )
                continue

            hours_stale = (now - last_scrape_dt).total_seconds() / 3600
            if hours_stale > STALE_THRESHOLD_HOURS:
                violations.append(
                    {
                        "bookmaker": bookmaker,
                        "last_scrape": last_scrape,
                        "hours_stale": round(hours_stale, 1),
                    }
                )
    finally:
        conn.close()
    return violations


def run(db_path: str = "odds.db") -> bool:
    """Run the freshness monitor."""
    violations = check_freshness(db_path)
    if violations:
        lines = ["Stale bookmaker data:"]
        for violation in violations:
            hours = violation["hours_stale"]
            hours_text = "unknown age" if hours is None else f"{hours}h ago"
            lines.append(
                f"  {violation['bookmaker']}: last scrape {violation['last_scrape']} ({hours_text})"
            )
        send_alert("odds_freshness", "\n".join(lines), severity="CRITICAL")
        return False

    send_all_clear("odds_freshness")
    return True
