"""Monitor null and empty rates for critical snapshot fields."""

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

CRITICAL_FIELDS = {
    "odds_snapshots": ["match_id", "home_team", "away_team", "league", "bookmaker"],
}
NULL_RATE_THRESHOLD = 0.10


def check_null_rates(db_path: str = "odds.db") -> list[dict]:
    """Return null-rate violations for configured critical fields."""
    violations: list[dict] = []
    conn = connect_odds_db(db_path)
    try:
        for table, fields in CRITICAL_FIELDS.items():
            total_rows = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            if total_rows == 0:
                continue
            for field in fields:
                null_count = conn.execute(
                    f"""
                    SELECT COUNT(*)
                    FROM {table}
                    WHERE {field} IS NULL OR TRIM(CAST({field} AS TEXT)) = ''
                    """
                ).fetchone()[0]
                null_rate = null_count / total_rows
                if null_rate > NULL_RATE_THRESHOLD:
                    violations.append(
                        {
                            "table": table,
                            "field": field,
                            "null_rate": round(null_rate, 4),
                            "total_rows": total_rows,
                            "null_count": null_count,
                        }
                    )
    finally:
        conn.close()
    return violations


def run(db_path: str = "odds.db") -> bool:
    """Run the null-rate monitor and send alerts for any violations."""
    violations = check_null_rates(db_path)
    if violations:
        lines = ["Null rate violations:"]
        for violation in violations:
            lines.append(
                "  "
                f"{violation['table']}.{violation['field']}: "
                f"{violation['null_rate'] * 100:.1f}% null "
                f"({violation['null_count']}/{violation['total_rows']})"
            )
        send_alert("null_rate", "\n".join(lines))
        return False

    send_all_clear("null_rate")
    return True
