"""Odds service — queries the Dataminer's odds.db for multi-bookmaker odds.

Two tables used:
    odds_latest — maintained by scrapers, only active matches, auto-expired.
        (match_id, bookmaker, market_type, home_odds, draw_odds, away_odds,
         over_odds, under_odds, first_seen, last_seen, last_changed, change_count)
    odds_snapshots — append-only history, has league/team metadata.
        (id, bookmaker, match_id, home_team, away_team, league, sport, market_type,
         home_odds, draw_odds, away_odds, over_odds, under_odds, scraped_at, ...)

Query strategy: odds_latest for current odds (guaranteed fresh), odds_snapshots for
metadata (home_team, away_team, league) and historical movement.

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

from config import ODDS_DB_PATH

log = logging.getLogger("mzansiedge.odds_service")


def build_match_id(home_team: str, away_team: str, commence_time: str) -> str:
    """Build a normalised match_id from team names and date.

    Uses the Dataminer's team_mapper for raw-name normalisation (handles
    FC suffixes, abbreviations, SA-specific names) and odds_normaliser
    for cross-bookmaker alias resolution.

    Returns e.g. "kaizer_chiefs_vs_orlando_pirates_2026-02-28"
    """
    from scrapers.odds_normaliser import normalise_key
    from scrapers.utils.team_mapper import normalise_team as _mapper_normalise

    date_part = ""
    if commence_time:
        date_part = commence_time[:10]  # "2026-02-28" from "2026-02-28T15:00:00Z"

    home = normalise_key(_mapper_normalise(home_team))
    away = normalise_key(_mapper_normalise(away_team))

    if date_part:
        return f"{home}_vs_{away}_{date_part}"
    return f"{home}_vs_{away}"

# Column mapping for each market type → list of (outcome_key, column_name) pairs
MARKET_COLUMNS: dict[str, list[tuple[str, str]]] = {
    "1x2": [("home", "home_odds"), ("draw", "draw_odds"), ("away", "away_odds")],
    "match_winner": [("home", "home_odds"), ("away", "away_odds")],  # 2-way (combat/cricket)
    "over_under_2.5": [("over", "over_odds"), ("under", "under_odds")],
    "btts": [("yes", "home_odds"), ("no", "away_odds")],  # home_odds=Yes, away_odds=No
}

# Map league key → primary market type for that league
LEAGUE_MARKET_TYPE: dict[str, str] = {
    "ufc": "match_winner",
    "boxing": "match_winner",
    "t20_world_cup": "match_winner",
    "test_cricket": "match_winner",
    "sa20": "match_winner",
    "ipl": "match_winner",
}


def _correct_swapped_odds(
    raw_odds: list[dict], side_a: str, side_b: str,
) -> list[dict]:
    """Detect and correct bookmakers with home/away odds swapped.

    For 2-way markets (match_winner), if the majority of bookmakers agree
    that side_a < side_b (side_a is the favourite), but a bookmaker has
    side_a > side_b, that bookmaker likely has the teams swapped.
    We swap that bookmaker's odds to match the consensus.
    """
    # Count how many bookmakers have side_a < side_b (a is favourite)
    a_fav = 0
    b_fav = 0
    for entry in raw_odds:
        val_a = entry.get(side_a) or 0
        val_b = entry.get(side_b) or 0
        if val_a <= 0 or val_b <= 0:
            continue
        if val_a < val_b:
            a_fav += 1
        elif val_b < val_a:
            b_fav += 1

    total = a_fav + b_fav
    if total < 2:
        return raw_odds  # Not enough data to determine consensus

    # Determine consensus: which side is the favourite?
    # Need clear majority (>60%) to trigger swap correction
    if a_fav > b_fav and a_fav / total >= 0.6:
        consensus_fav = side_a  # side_a should have lower odds (favourite)
    elif b_fav > a_fav and b_fav / total >= 0.6:
        consensus_fav = side_b
    else:
        return raw_odds  # No clear consensus

    corrected = []
    for entry in raw_odds:
        val_a = entry.get(side_a) or 0
        val_b = entry.get(side_b) or 0
        if val_a <= 0 or val_b <= 0:
            corrected.append(entry)
            continue

        needs_swap = (
            (consensus_fav == side_a and val_a > val_b)
            or (consensus_fav == side_b and val_b > val_a)
        )
        if needs_swap:
            log.info(
                "Swap correction: %s has %s=%.2f/%s=%.2f → swapped (consensus: %s is favourite)",
                entry["bookmaker"], side_a, val_a, side_b, val_b, consensus_fav,
            )
            fixed = dict(entry)
            fixed[side_a] = val_b
            fixed[side_b] = val_a
            corrected.append(fixed)
        else:
            corrected.append(entry)

    return corrected


async def get_best_odds(
    match_id: str,
    market_type: str = "1x2",
) -> dict:
    """Returns latest odds for a match across all bookmakers, sorted by best value.

    Uses odds_latest for current odds (fast primary-key lookup) and
    odds_snapshots for metadata (home_team, away_team, league).

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
    from scrapers.odds_integrity import filter_outlier_prices
    from scrapers.odds_normaliser import normalise_match_id

    # Resolve any alias keys in the match_id before querying
    match_id = normalise_match_id(match_id)

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

    if not Path(str(ODDS_DB_PATH)).exists():
        log.debug("odds.db not found at %s", ODDS_DB_PATH)
        return result

    try:
        async with aiosqlite.connect(str(ODDS_DB_PATH)) as conn:
            conn.row_factory = aiosqlite.Row

            # Get current odds from odds_latest (one row per bookmaker, guaranteed fresh)
            odds_query = """
                SELECT bookmaker, home_odds, draw_odds, away_odds,
                       over_odds, under_odds, last_seen
                FROM odds_latest
                WHERE match_id = ? AND market_type = ?
            """
            async with conn.execute(odds_query, (match_id, market_type)) as cursor:
                rows = await cursor.fetchall()

            if not rows:
                return result

            # Get metadata (home_team, away_team, league) from odds_snapshots
            meta_query = """
                SELECT home_team, away_team, league
                FROM odds_snapshots
                WHERE match_id = ?
                ORDER BY scraped_at DESC LIMIT 1
            """
            async with conn.execute(meta_query, (match_id,)) as cursor:
                meta = await cursor.fetchone()

            if meta:
                result["home_team"] = meta["home_team"]
                result["away_team"] = meta["away_team"]
                result["league"] = meta["league"]

            bookmakers = set()
            latest_ts = None

            # Collect raw odds per bookmaker first (for swap detection)
            raw_odds: list[dict] = []
            for row in rows:
                entry = {
                    "bookmaker": row["bookmaker"],
                    "last_seen": row["last_seen"],
                }
                for outcome_key, col_name in columns:
                    entry[outcome_key] = row[col_name]
                raw_odds.append(entry)

            # Detect and correct home/away swaps for 2-way markets
            # If majority of bookmakers agree on which side is the favourite,
            # a bookmaker with inverted odds has home/away swapped
            if market_type == "match_winner" and len(raw_odds) >= 2:
                raw_odds = _correct_swapped_odds(raw_odds, "home", "away")

            for entry in raw_odds:
                bookmaker = entry["bookmaker"]
                ts = entry["last_seen"]
                bookmakers.add(bookmaker)
                if latest_ts is None or ts > latest_ts:
                    latest_ts = ts

                # Extract odds for each outcome
                for outcome_key, _col_name in columns:
                    odds_val = entry.get(outcome_key)
                    if odds_val is None or odds_val <= 0:
                        continue

                    result["outcomes"].setdefault(
                        outcome_key,
                        {
                            "best_odds": 0.0,
                            "best_bookmaker": "",
                            "all_bookmakers": {},
                        },
                    )
                    result["outcomes"][outcome_key]["all_bookmakers"][bookmaker] = odds_val

            for outcome_key, outcome_data in list(result["outcomes"].items()):
                all_prices = list(outcome_data.get("all_bookmakers", {}).items())
                clean_prices, _outliers = filter_outlier_prices(
                    all_prices,
                    match_id=match_id,
                    selection=outcome_key,
                )
                if not clean_prices:
                    del result["outcomes"][outcome_key]
                    continue

                clean_bookmakers = {bookmaker: price for bookmaker, price in clean_prices}
                best_bookmaker, best_odds = max(clean_prices, key=lambda item: item[1])
                outcome_data["all_bookmakers"] = clean_bookmakers
                outcome_data["best_bookmaker"] = best_bookmaker
                outcome_data["best_odds"] = best_odds

            result["last_updated"] = latest_ts
            result["bookmaker_count"] = len(bookmakers)

    except Exception as exc:
        log.warning("Failed to query odds for match %s: %s", match_id, exc)

    return result


async def get_all_matches(
    market_type: str = "1x2",
    league: str | None = None,
    limit: int = 100,
) -> list[dict]:
    """Returns latest odds for all active matches, optionally filtered by league.

    Uses odds_latest as the source of truth for active match_ids (scrapers
    auto-expire stale matches from this table). Joins to odds_snapshots only
    when a league filter is needed (odds_latest has no league column).

    Each entry has the same structure as get_best_odds() output.
    """
    results = []

    if not Path(str(ODDS_DB_PATH)).exists():
        return results

    try:
        async with aiosqlite.connect(str(ODDS_DB_PATH)) as conn:
            conn.row_factory = aiosqlite.Row

            # Get active match_ids from odds_latest (only current matches)
            if league:
                # JOIN to odds_snapshots for league metadata (odds_latest has no league col)
                query = """
                    SELECT DISTINCT ol.match_id
                    FROM odds_latest ol
                    INNER JOIN odds_snapshots os
                        ON ol.match_id = os.match_id
                        AND os.league = ?
                    WHERE ol.market_type = ?
                    LIMIT ?
                """
                params = (league, market_type, limit)
            else:
                query = """
                    SELECT DISTINCT match_id FROM odds_latest
                    WHERE market_type = ?
                    LIMIT ?
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
    from scrapers.odds_normaliser import normalise_match_id

    # Resolve any alias keys in the match_id before querying
    match_id = normalise_match_id(match_id)

    result = []
    columns = MARKET_COLUMNS.get(market_type)
    if not columns:
        return result

    if not Path(str(ODDS_DB_PATH)).exists():
        return result

    try:
        cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)).isoformat()

        async with aiosqlite.connect(str(ODDS_DB_PATH)) as conn:
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
    from scrapers.odds_normaliser import normalise_match_id

    match_id = normalise_match_id(match_id)
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


async def get_match_league(match_id: str) -> str | None:
    """Get league for a match_id from odds_snapshots metadata."""
    from scrapers.odds_normaliser import normalise_match_id

    match_id = normalise_match_id(match_id)
    if not Path(str(ODDS_DB_PATH)).exists():
        return None
    try:
        async with aiosqlite.connect(str(ODDS_DB_PATH)) as conn:
            async with conn.execute(
                "SELECT league FROM odds_snapshots WHERE match_id = ? LIMIT 1",
                (match_id,),
            ) as cur:
                row = await cur.fetchone()
                return row[0] if row else None
    except Exception:
        return None


async def get_db_stats() -> dict:
    """Get summary statistics from odds.db for admin dashboard."""
    stats = {"total_rows": 0, "bookmaker_count": 0, "latest_scrape": "N/A", "match_count": 0}

    if not Path(str(ODDS_DB_PATH)).exists():
        return stats

    try:
        async with aiosqlite.connect(str(ODDS_DB_PATH)) as conn:
            async with conn.execute("SELECT COUNT(*) FROM odds_snapshots") as cur:
                stats["total_rows"] = (await cur.fetchone())[0]
            async with conn.execute("SELECT COUNT(DISTINCT bookmaker) FROM odds_snapshots") as cur:
                stats["bookmaker_count"] = (await cur.fetchone())[0]
            async with conn.execute("SELECT MAX(scraped_at) FROM odds_snapshots") as cur:
                stats["latest_scrape"] = (await cur.fetchone())[0] or "N/A"
            async with conn.execute("SELECT COUNT(DISTINCT match_id) FROM odds_snapshots WHERE market_type IN ('1x2', 'match_winner')") as cur:
                stats["match_count"] = (await cur.fetchone())[0]
    except Exception as exc:
        log.warning("Failed to get DB stats: %s", exc)

    return stats
