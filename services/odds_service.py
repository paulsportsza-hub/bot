"""Odds service — queries the odds_snapshots table for multi-bookmaker odds.

The Dataminer agent populates the odds_snapshots table via scrapers.
This service reads from it to provide best-odds lookups and line movement data.
"""

from __future__ import annotations

import datetime as dt
import logging

import aiosqlite

import config

log = logging.getLogger("mzansiedge.odds_service")

# Path to the odds database (shared with Dataminer scrapers)
ODDS_DB_PATH = str(config.DATA_DIR / "odds_snapshots.db")


async def get_best_odds(
    match_id: str,
    market_type: str = "1x2",
) -> dict:
    """Returns latest odds for a match across all bookmakers, sorted by best value.

    Args:
        match_id: The Odds API event_id or a normalized match identifier
        market_type: Market type — "1x2" (match winner), "totals", "spreads"

    Returns:
        dict with keys:
            - match_id: str
            - market_type: str
            - outcomes: dict mapping outcome (e.g. "home", "away", "draw") to:
                - best_odds: float (highest available odds)
                - best_bookmaker: str (bookmaker_key with best odds)
                - all_bookmakers: dict[bookmaker_key, float] (all available odds)
            - last_updated: str (ISO timestamp of most recent snapshot)
            - bookmaker_count: int (number of bookmakers with odds)
    """
    result = {
        "match_id": match_id,
        "market_type": market_type,
        "outcomes": {},
        "last_updated": None,
        "bookmaker_count": 0,
    }

    try:
        async with aiosqlite.connect(ODDS_DB_PATH) as conn:
            conn.row_factory = aiosqlite.Row

            # Get the latest snapshot per bookmaker per outcome for this match
            query = """
                SELECT bookmaker, outcome, odds, timestamp
                FROM odds_snapshots
                WHERE match_id = ? AND market_type = ?
                AND timestamp = (
                    SELECT MAX(t2.timestamp)
                    FROM odds_snapshots t2
                    WHERE t2.match_id = odds_snapshots.match_id
                    AND t2.bookmaker = odds_snapshots.bookmaker
                    AND t2.outcome = odds_snapshots.outcome
                    AND t2.market_type = odds_snapshots.market_type
                )
                ORDER BY odds DESC
            """
            async with conn.execute(query, (match_id, market_type)) as cursor:
                rows = await cursor.fetchall()

            if not rows:
                return result

            bookmakers = set()
            latest_ts = None

            for row in rows:
                outcome = row["outcome"]
                bookmaker = row["bookmaker"]
                odds = row["odds"]
                ts = row["timestamp"]

                bookmakers.add(bookmaker)
                if latest_ts is None or ts > latest_ts:
                    latest_ts = ts

                if outcome not in result["outcomes"]:
                    result["outcomes"][outcome] = {
                        "best_odds": odds,
                        "best_bookmaker": bookmaker,
                        "all_bookmakers": {},
                    }

                result["outcomes"][outcome]["all_bookmakers"][bookmaker] = odds

                # Update best if this is higher
                if odds > result["outcomes"][outcome]["best_odds"]:
                    result["outcomes"][outcome]["best_odds"] = odds
                    result["outcomes"][outcome]["best_bookmaker"] = bookmaker

            result["last_updated"] = latest_ts
            result["bookmaker_count"] = len(bookmakers)

    except Exception as exc:
        log.warning("Failed to query odds_snapshots for match %s: %s", match_id, exc)

    return result


async def get_odds_movement(
    match_id: str,
    hours: int = 24,
    market_type: str = "1x2",
) -> list[dict]:
    """Returns odds history for line movement detection.

    Args:
        match_id: The event/match identifier
        hours: How many hours of history to fetch (default 24)
        market_type: Market type filter

    Returns:
        list of dicts sorted by timestamp ascending, each with:
            - bookmaker: str
            - outcome: str
            - odds: float
            - timestamp: str (ISO format)
    """
    result = []

    try:
        cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)).isoformat()

        async with aiosqlite.connect(ODDS_DB_PATH) as conn:
            conn.row_factory = aiosqlite.Row

            query = """
                SELECT bookmaker, outcome, odds, timestamp
                FROM odds_snapshots
                WHERE match_id = ? AND market_type = ? AND timestamp >= ?
                ORDER BY timestamp ASC
            """
            async with conn.execute(query, (match_id, market_type, cutoff)) as cursor:
                rows = await cursor.fetchall()

            for row in rows:
                result.append({
                    "bookmaker": row["bookmaker"],
                    "outcome": row["outcome"],
                    "odds": row["odds"],
                    "timestamp": row["timestamp"],
                })

    except Exception as exc:
        log.warning("Failed to query odds movement for match %s: %s", match_id, exc)

    return result


async def detect_line_movement(
    match_id: str,
    outcome: str,
    hours: int = 24,
) -> dict | None:
    """Analyse line movement for a specific outcome.

    Returns:
        dict with keys: direction ("shortening"/"drifting"/"stable"), magnitude (float), hours (int)
        or None if insufficient data.
    """
    history = await get_odds_movement(match_id, hours=hours)
    if not history:
        return None

    # Filter to the specific outcome
    outcome_history = [h for h in history if h["outcome"] == outcome]
    if len(outcome_history) < 2:
        return None

    # Calculate average odds at start vs end of period
    half = len(outcome_history) // 2
    early = outcome_history[:half]
    late = outcome_history[half:]

    avg_early = sum(h["odds"] for h in early) / len(early) if early else 0
    avg_late = sum(h["odds"] for h in late) / len(late) if late else 0

    if avg_early == 0:
        return None

    change = avg_late - avg_early
    magnitude = abs(change)

    if magnitude < 0.03:
        direction = "stable"
    elif change < 0:
        direction = "shortening"  # odds getting lower = more money coming in
    else:
        direction = "drifting"  # odds getting longer = money moving away

    return {
        "direction": direction,
        "magnitude": magnitude,
        "hours": hours,
    }
