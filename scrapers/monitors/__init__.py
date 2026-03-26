"""Data drift monitors for scraper data quality checks."""

from .bookmaker_coverage import run as run_bookmaker_coverage
from .join_health import run as run_join_health
from .null_rate_monitor import run as run_null_rate
from .odds_freshness import run as run_odds_freshness


def run_all_monitors(db_path: str = "odds.db") -> dict[str, bool]:
    """Run all configured monitors and return their pass/fail status."""
    return {
        "null_rate": run_null_rate(db_path),
        "bookmaker_coverage": run_bookmaker_coverage(db_path),
        "join_health": run_join_health(db_path),
        "odds_freshness": run_odds_freshness(db_path),
    }
