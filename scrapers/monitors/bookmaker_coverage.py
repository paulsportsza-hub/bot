"""Monitor multi-bookmaker coverage by league."""

from __future__ import annotations

import logging
import sys

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

MIN_BOOKMAKER_MATCH_RATE = 0.60
RECENT_WINDOW_SQL = "datetime('now', '-1 day')"


def check_coverage(db_path: str = "odds.db") -> list[dict]:
    """Return leagues with poor multi-bookmaker fixture coverage."""
    conn = connect_odds_db(db_path)
    violations: list[dict] = []
    try:
        rows = conn.execute(
            f"""
            SELECT league,
                   COUNT(*) AS total_fixtures,
                   SUM(CASE WHEN bookmaker_count >= 2 THEN 1 ELSE 0 END) AS multi_bk_fixtures
            FROM (
                SELECT league,
                       match_id,
                       COUNT(DISTINCT bookmaker) AS bookmaker_count
                FROM odds_snapshots
                WHERE scraped_at >= {RECENT_WINDOW_SQL}
                GROUP BY league, match_id
            )
            GROUP BY league
            """
        ).fetchall()
        for league, total_fixtures, multi_bk_fixtures in rows:
            if total_fixtures == 0:
                continue
            rate = multi_bk_fixtures / total_fixtures
            if rate < MIN_BOOKMAKER_MATCH_RATE:
                violations.append(
                    {
                        "league": league,
                        "total_fixtures": total_fixtures,
                        "multi_bk_fixtures": multi_bk_fixtures,
                        "rate": round(rate, 4),
                    }
                )
    finally:
        conn.close()
    return violations


def run(db_path: str = "odds.db") -> bool:
    """Run the bookmaker coverage monitor."""
    violations = check_coverage(db_path)
    if violations:
        lines = ["Bookmaker coverage violations:"]
        for violation in violations:
            lines.append(
                "  "
                f"{violation['league']}: {violation['rate'] * 100:.1f}% multi-bk "
                f"({violation['multi_bk_fixtures']}/{violation['total_fixtures']})"
            )
        send_alert("bookmaker_coverage", "\n".join(lines))
        return False

    send_all_clear("bookmaker_coverage")
    return True
