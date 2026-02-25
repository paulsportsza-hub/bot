"""Odds service — queries the Dataminer's odds_snapshots table for multi-bookmaker odds.

Schema (from /home/paulsportsza/scrapers/db_schema.sql):
    odds_snapshots (
        id, bookmaker, match_id, home_team, away_team, league, sport, market_type,
        home_odds, draw_odds, away_odds, over_odds, under_odds, scraped_at, source_url, created_at
    )

match_id format: normalised composite key e.g. "kaizer_chiefs_vs_orlando_pirates_2026-02-28"
bookmaker keys: "hollywoodbets", "supabets" (lowercase)
market_types: "1x2", "over_under_2.5", "btts"
Odds are true decimal (2.50 = bet R1, get R2.50 total)
"""

from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path

import aiosqlite

log = logging.getLogger("mzansiedge.odds_service")

# Path to the odds database (shared with Dataminer scrapers)
ODDS_DB_PATH = "/home/paulsportsza/scrapers/odds.db"

# Column mapping for each market type → list of (outcome_key, column_name) pairs
MARKET_COLUMNS: dict[str, list[tuple[str, str]]] = {
    "1x2": [("home", "home_odds"), ("draw", "draw_odds"), ("away", "away_odds")],
    "over_under_2.5": [("over", "over_odds"), ("under", "under_odds")],
    "btts": [("yes", "home_odds"), ("no", "away_odds")],  # home_odds=Yes, away_odds=No
}


async def get_best_odds(
    match_id: str,
    market_type: str = "1x2",
) -> dict:
    """Returns latest odds for a match across all bookmakers, sorted by best value.

    Args:
        match_id: Normalised composite key (e.g. "kaizer_chiefs_vs_orlando_pirates_2026-02-28")
        market_type: "1x2", "over_under_2.5", or "btts"

    Returns:
        dict with keys:
            - match_id: str
            - market_type: str
            - home_team: str (from DB row)
            - away_team: str (from DB row)
            - league: str (from DB row)
            - outcomes: dict mapping outcome key (e.g. "home", "away", "draw") to:
                - best_odds: float (highest available odds)
                - best_bookmaker: str (bookmaker_key with best odds)
                - all_bookmakers: dict[bookmaker_key, float] (all available odds)
            - last_updated: str (ISO timestamp of most recent snapshot)
            - bookmaker_count: int (number of bookmakers with odds)
    """
    result: dict = {
        "match_id": match_id,
        "market_type": market_type,
        "home_team": "",
        "away_team": "",
        "league": "",
        "outcomes": {},
        "last_updated": None,
        "bookmaker_count": 0,
    }

    columns = MARKET_COLUMNS.get(market_type)
    if not columns:
        log.warning("Unknown market_type: %s", market_type)
        return result

    if not Path(ODDS_DB_PATH).exists():
        log.debug("odds.db not found at %s", ODDS_DB_PATH)
        return result

    try:
        async with aiosqlite.connect(ODDS_DB_PATH) as conn:
            conn.row_factory = aiosqlite.Row

            # Get the latest snapshot per bookmaker for this match + market
            query = """
                SELECT bookmaker, home_team, away_team, league,
                       home_odds, draw_odds, away_odds, over_odds, under_odds, scraped_at
                FROM odds_snapshots o1
                WHERE match_id = ? AND market_type = ?
                AND scraped_at = (
                    SELECT MAX(o2.scraped_at)
                    FROM odds_snapshots o2
                    WHERE o2.match_id = o1.match_id
                    AND o2.bookmaker = o1.bookmaker
                    AND o2.market_type = o1.market_type
                )
                ORDER BY scraped_at DESC
            """
            async with conn.execute(query, (match_id, market_type)) as cursor:
                rows = await cursor.fetchall()

            if not rows:
                return result

            bookmakers = set()
            latest_ts = None

            # Populate metadata from first row
            result["home_team"] = rows[0]["home_team"]
            result["away_team"] = rows[0]["away_team"]
            result["league"] = rows[0]["league"]

            for row in rows:
                bookmaker = row["bookmaker"]
                ts = row["scraped_at"]
                bookmakers.add(bookmaker)
                if latest_ts is None or ts > latest_ts:
                    latest_ts = ts

                # Extract odds for each outcome column
                for outcome_key, col_name in columns:
                    odds_val = row[col_name]
                    if odds_val is None or odds_val <= 0:
                        continue

                    if outcome_key not in result["outcomes"]:
                        result["outcomes"][outcome_key] = {
                            "best_odds": odds_val,
                            "best_bookmaker": bookmaker,
                            "all_bookmakers": {},
                        }

                    result["outcomes"][outcome_key]["all_bookmakers"][bookmaker] = odds_val

                    if odds_val > result["outcomes"][outcome_key]["best_odds"]:
                        result["outcomes"][outcome_key]["best_odds"] = odds_val
                        result["outcomes"][outcome_key]["best_bookmaker"] = bookmaker

            result["last_updated"] = latest_ts
            result["bookmaker_count"] = len(bookmakers)

    except Exception as exc:
        log.warning("Failed to query odds_snapshots for match %s: %s", match_id, exc)

    return result


async def get_all_matches(
    market_type: str = "1x2",
    league: str | None = None,
    limit: int = 100,
) -> list[dict]:
    """Returns latest odds for all matches, optionally filtered by league.

    Each entry has the same structure as get_best_odds() output.
    """
    results = []

    if not Path(ODDS_DB_PATH).exists():
        return results

    try:
        async with aiosqlite.connect(ODDS_DB_PATH) as conn:
            conn.row_factory = aiosqlite.Row

            # Get distinct match_ids with latest scrape
            if league:
                query = """
                    SELECT DISTINCT match_id FROM odds_snapshots
                    WHERE market_type = ? AND league = ?
                    ORDER BY scraped_at DESC LIMIT ?
                """
                params = (market_type, league, limit)
            else:
                query = """
                    SELECT DISTINCT match_id FROM odds_snapshots
                    WHERE market_type = ?
                    ORDER BY scraped_at DESC LIMIT ?
                """
                params = (market_type, limit)

            async with conn.execute(query, params) as cursor:
                match_rows = await cursor.fetchall()

        # Fetch best odds for each match
        for row in match_rows:
            odds_data = await get_best_odds(row["match_id"], market_type)
            if odds_data["outcomes"]:
                results.append(odds_data)

    except Exception as exc:
        log.warning("Failed to query all matches: %s", exc)

    return results


async def get_odds_movement(
    match_id: str,
    hours: int = 24,
    market_type: str = "1x2",
) -> list[dict]:
    """Returns odds history for line movement detection.

    Returns list of dicts sorted by scraped_at ascending, each with:
        - bookmaker: str
        - outcome: str (e.g. "home", "away", "draw", "over", "under", "yes", "no")
        - odds: float
        - scraped_at: str (ISO format)
    """
    result = []
    columns = MARKET_COLUMNS.get(market_type)
    if not columns:
        return result

    if not Path(ODDS_DB_PATH).exists():
        return result

    try:
        cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)).isoformat()

        async with aiosqlite.connect(ODDS_DB_PATH) as conn:
            conn.row_factory = aiosqlite.Row

            query = """
                SELECT bookmaker, home_odds, draw_odds, away_odds,
                       over_odds, under_odds, scraped_at
                FROM odds_snapshots
                WHERE match_id = ? AND market_type = ? AND scraped_at >= ?
                ORDER BY scraped_at ASC
            """
            async with conn.execute(query, (match_id, market_type, cutoff)) as cursor:
                rows = await cursor.fetchall()

            for row in rows:
                for outcome_key, col_name in columns:
                    odds_val = row[col_name]
                    if odds_val is not None and odds_val > 0:
                        result.append({
                            "bookmaker": row["bookmaker"],
                            "outcome": outcome_key,
                            "odds": odds_val,
                            "scraped_at": row["scraped_at"],
                        })

    except Exception as exc:
        log.warning("Failed to query odds movement for match %s: %s", match_id, exc)

    return result


async def detect_line_movement(
    match_id: str,
    outcome: str,
    hours: int = 24,
    market_type: str = "1x2",
) -> dict | None:
    """Analyse line movement for a specific outcome.

    Args:
        match_id: Normalised match ID
        outcome: Outcome key ("home", "away", "draw", "over", "under", "yes", "no")
        hours: Lookback window
        market_type: "1x2", "over_under_2.5", or "btts"

    Returns:
        dict with keys: direction ("shortening"/"drifting"/"stable"), magnitude (float), hours (int)
        or None if insufficient data.
    """
    history = await get_odds_movement(match_id, hours=hours, market_type=market_type)
    if not history:
        return None

    # Filter to the specific outcome
    outcome_history = [entry for entry in history if entry["outcome"] == outcome]
    if len(outcome_history) < 2:
        return None

    # Compare average odds in first half vs second half of the period
    half = len(outcome_history) // 2
    early = outcome_history[:half]
    late = outcome_history[half:]

    avg_early = sum(entry["odds"] for entry in early) / len(early) if early else 0
    avg_late = sum(entry["odds"] for entry in late) / len(late) if late else 0

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
