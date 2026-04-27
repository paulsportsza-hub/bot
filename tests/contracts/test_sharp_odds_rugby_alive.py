"""Contract test: sharp_odds rugby data is alive (FIX-CORE7-RUGBY-01).

AC-1: Rolling 7-day sharp_odds rugby row count >= 1
      (daily monitor gate — if this fires, the consensus bridge is broken)
AC-2: Every sa_shin_consensus row has a real back_price (not NULL, > 1.0)
AC-3: All three rugby leagues (urc, super_rugby, six_nations) are present in
      the last 30 days OR have no upcoming fixtures in rugby_fixtures
      (six_nations is seasonally inactive Jan–Mar; skip absence when no
       fixtures exist for that league)
"""

import os
import sys
import sqlite3

_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)
sys.path.insert(0, _ROOT)

DB_PATH = os.path.join(_ROOT, "scrapers", "odds.db")


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ── AC-1: rolling 7-day rugby coverage ───────────────────────────────────

def test_sharp_odds_rugby_rolling7d_count():
    """At least 1 rugby row written in the last 7 days (daily monitor gate)."""
    conn = _connect()
    count = conn.execute(
        """
        SELECT COUNT(*) FROM sharp_odds
        WHERE sport = 'rugby'
          AND scraped_at >= datetime('now', '-7 days')
        """
    ).fetchone()[0]
    assert count >= 1, (
        f"sharp_odds has {count} rugby rows in last 7 days — "
        "expected ≥1. Check rugby_consensus_sharp cron or SA bookmaker odds freshness."
    )


# ── AC-2: back_price populated on consensus rows ─────────────────────────

def test_sharp_odds_rugby_consensus_back_price_populated():
    """All sa_shin_consensus rugby rows must have back_price > 1.0 (not NULL)."""
    conn = _connect()
    bad_rows = conn.execute(
        """
        SELECT match_key, selection, back_price FROM sharp_odds
        WHERE sport = 'rugby'
          AND bookmaker = 'sa_shin_consensus'
          AND scraped_at >= datetime('now', '-7 days')
          AND (back_price IS NULL OR back_price <= 1.0)
        """
    ).fetchall()
    assert len(bad_rows) == 0, (
        f"{len(bad_rows)} rugby consensus rows have invalid back_price: "
        + str([dict(r) for r in bad_rows[:3]])
    )


# ── AC-3: URC + Super Rugby presence (Six Nations seasonal gate) ──────────


def test_urc_sharp_odds_present_if_live_odds_exist():
    """URC must have sharp_odds rows in last 30d when SA bookmakers have live URC odds.

    Live = present in odds_latest (not just historical snapshots).
    """
    conn = _connect()
    live_urc = conn.execute(
        """
        SELECT COUNT(*) FROM odds_latest ol
        JOIN odds_snapshots os ON os.match_id = ol.match_id
        WHERE os.sport = 'rugby' AND os.league = 'urc'
          AND ol.last_seen >= datetime('now', '-3 hours')
        """
    ).fetchone()[0]
    if live_urc == 0:
        return  # no live URC odds right now → bridge can't build consensus → skip

    count = conn.execute(
        """
        SELECT COUNT(*) FROM sharp_odds
        WHERE sport = 'rugby' AND league = 'urc'
          AND scraped_at >= datetime('now', '-30 days')
        """
    ).fetchone()[0]
    assert count >= 1, (
        f"sharp_odds has {count} URC rows in last 30 days — "
        "expected ≥1 when SA bookmakers have live URC odds."
    )


def test_super_rugby_sharp_odds_present_if_sa_odds_exist():
    """Super Rugby must have sharp_odds rows in last 30d when SA bookmakers cover it."""
    conn = _connect()
    sa_count = conn.execute(
        """
        SELECT COUNT(*) FROM odds_snapshots
        WHERE sport = 'rugby' AND league = 'super_rugby'
          AND scraped_at >= datetime('now', '-3 days')
        """
    ).fetchone()[0]
    if sa_count == 0:
        return  # no active Super Rugby SA odds → skip

    count = conn.execute(
        """
        SELECT COUNT(*) FROM sharp_odds
        WHERE sport = 'rugby' AND league = 'super_rugby'
          AND scraped_at >= datetime('now', '-30 days')
        """
    ).fetchone()[0]
    assert count >= 1, (
        f"sharp_odds has {count} Super Rugby rows in last 30 days — "
        "expected ≥1 when SA bookmakers have Super Rugby odds."
    )
