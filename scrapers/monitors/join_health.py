"""Monitor fixture join health across bookmaker snapshots."""

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

MAX_SINGLE_BOOKMAKER_RATE = 0.40
RECENT_WINDOW_SQL = "datetime('now', '-1 day')"


def check_join_health(db_path: str = "odds.db") -> list[dict]:
    """Return join-health violations for recently scraped fixtures."""
    conn = connect_odds_db(db_path)
    violations: list[dict] = []
    try:
        total_fixtures = conn.execute(
            f"""
            SELECT COUNT(*)
            FROM (
                SELECT match_id
                FROM odds_snapshots
                WHERE scraped_at >= {RECENT_WINDOW_SQL}
                GROUP BY match_id
            )
            """
        ).fetchone()[0]

        if total_fixtures == 0:
            return violations

        single_bookmaker_fixtures = conn.execute(
            f"""
            SELECT COUNT(*)
            FROM (
                SELECT match_id
                FROM odds_snapshots
                WHERE scraped_at >= {RECENT_WINDOW_SQL}
                GROUP BY match_id
                HAVING COUNT(DISTINCT bookmaker) = 1
            )
            """
        ).fetchone()[0]

        rate = single_bookmaker_fixtures / total_fixtures
        if rate > MAX_SINGLE_BOOKMAKER_RATE:
            violations.append(
                {
                    "issue": "high_single_bookmaker_rate",
                    "single_bk_fixtures": single_bookmaker_fixtures,
                    "total_fixtures": total_fixtures,
                    "rate": round(rate, 4),
                }
            )
    finally:
        conn.close()
    return violations


def run(db_path: str = "odds.db") -> bool:
    """Run the join-health monitor."""
    violations = check_join_health(db_path)
    if violations:
        lines = ["Join health issues:"]
        for violation in violations:
            lines.append(
                "  "
                f"{violation['issue']}: {violation['rate'] * 100:.1f}% single-bk "
                f"({violation['single_bk_fixtures']}/{violation['total_fixtures']})"
            )
        send_alert("join_health", "\n".join(lines))
        return False

    send_all_clear("join_health")
    return True
