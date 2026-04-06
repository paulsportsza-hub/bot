#!/usr/bin/env python3
"""IMG-W1.5 — Batch logo fetcher CLI.

Fetches team/fighter logos from external APIs and stores them in the local
logo cache. Uses logo_cache.prefetch_logo() — see bot/logo_cache.py.

Usage
-----
    # All sports, all known teams:
    python scripts/fetch_logos.py --all

    # Specific sport:
    python scripts/fetch_logos.py --sport soccer
    python scripts/fetch_logos.py --sport rugby
    python scripts/fetch_logos.py --sport cricket
    python scripts/fetch_logos.py --sport mma

    # Specific league:
    python scripts/fetch_logos.py --sport soccer --league epl

    # Single team:
    python scripts/fetch_logos.py --sport soccer --team Arsenal

    # Dry run (list teams without fetching):
    python scripts/fetch_logos.py --all --dry-run

    # Show cache stats:
    python scripts/fetch_logos.py --stats

Environment
-----------
    Run from /home/paulsportsza/bot/ with .venv active.
    Requires API_FOOTBALL_KEY, API_SPORTS_KEY, SPORTMONKS_CRICKET_TOKEN in .env.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

# Make bot/ importable when script is run from the bot dir
_BOT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(_BOT_DIR))

import logo_cache
from logo_cache import _fuzzy_match_team, prefetch_logo, get_logo, _LOGO_DB, _team_key
from db_connection import get_connection


# ── Team data ─────────────────────────────────────────────────────────────────

def _get_team_list() -> dict[str, dict[str, list[str]]]:
    """Return {sport: {league: [team_names]}} from config.TOP_TEAMS."""
    try:
        import config
        team_map: dict[str, dict[str, list[str]]] = {}
        for league_key, teams in config.TOP_TEAMS.items():
            sport = config.LEAGUE_SPORT.get(league_key, "soccer")
            team_map.setdefault(sport, {}).setdefault(league_key, []).extend(teams)
        return team_map
    except Exception as exc:
        print(f"Warning: could not load config.TOP_TEAMS — {exc}", file=sys.stderr)
        return _FALLBACK_TEAMS


# Fallback minimal team list when config is not available
_FALLBACK_TEAMS: dict[str, dict[str, list[str]]] = {
    "soccer": {
        "epl": [
            "Arsenal", "Chelsea", "Liverpool", "Manchester City",
            "Manchester United", "Tottenham", "Newcastle United",
            "Aston Villa", "West Ham", "Brighton",
        ],
        "psl": [
            "Kaizer Chiefs", "Orlando Pirates", "Mamelodi Sundowns",
            "Supersport United", "Cape Town City",
        ],
        "la_liga": ["Real Madrid", "Barcelona", "Atletico Madrid"],
        "bundesliga": ["Bayern Munich", "Borussia Dortmund"],
        "serie_a": ["Juventus", "AC Milan", "Inter Milan"],
        "ligue_1": ["Paris Saint Germain"],
        "champions_league": [],
    },
    "rugby": {
        "urc": ["Bulls", "Stormers", "Lions", "Sharks", "Leinster", "Ulster"],
        "super_rugby": ["Blues", "Crusaders", "Chiefs", "Hurricanes", "Brumbies"],
        "international_rugby": ["South Africa", "New Zealand", "Ireland", "England", "France"],
    },
    "cricket": {
        "ipl": ["Mumbai Indians", "Chennai Super Kings", "Royal Challengers Bangalore"],
        "sa20": ["Paarl Royals", "Sunrisers Eastern Cape"],
        "t20_international": ["South Africa", "India", "Australia", "England"],
    },
    "mma": {
        "ufc": ["Jon Jones", "Dricus Du Plessis", "Islam Makhachev", "Alex Pereira"],
    },
}


# ── Cache stats ───────────────────────────────────────────────────────────────

def _show_stats() -> None:
    """Print a summary of the logo cache."""
    try:
        conn = get_connection(db_path=_LOGO_DB, readonly=True)
        rows = conn.execute(
            "SELECT sport, status, COUNT(*) AS n FROM logo_cache GROUP BY sport, status ORDER BY sport, status"
        ).fetchall()
        conn.close()
    except Exception as exc:
        print(f"Error reading cache: {exc}", file=sys.stderr)
        return

    print("Logo cache summary")
    print("─" * 40)
    if not rows:
        print("  (empty)")
        return
    for row in rows:
        print(f"  {row['sport']:10s}  {row['status']:8s}  {row['n']:4d}")
    print("─" * 40)
    print(f"  DB: {_LOGO_DB}")
    print(f"  Dir: {logo_cache._LOGO_DIR}")


# ── Fetch runner ──────────────────────────────────────────────────────────────

def _fetch_teams(
    teams: list[tuple[str, str, str]],  # (team_name, sport, league)
    dry_run: bool = False,
    delay: float = 0.5,
) -> None:
    """Fetch logos for a list of (team, sport, league) tuples."""
    total = len(teams)
    ok = failed = skipped = 0

    for i, (team, sport, league) in enumerate(teams, 1):
        status_prefix = f"[{i:3d}/{total}]"
        key = _team_key(team, sport)

        if dry_run:
            print(f"{status_prefix} DRY-RUN  {sport:8s}  {team}")
            continue

        # Check if already cached
        cached = get_logo(team, sport, league)
        if cached is not None:
            print(f"{status_prefix} CACHED   {sport:8s}  {team}")
            skipped += 1
            continue

        result = prefetch_logo(team, sport, league)
        if result is not None:
            print(f"{status_prefix} OK       {sport:8s}  {team}  → {result.name}")
            ok += 1
        else:
            print(f"{status_prefix} FAILED   {sport:8s}  {team}")
            failed += 1

        # Polite delay between API calls
        if i < total:
            time.sleep(delay)

    if not dry_run:
        print()
        print(f"Done. OK={ok}  FAILED={failed}  SKIPPED={skipped}  TOTAL={total}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def _build_team_list(
    sport_filter: str | None,
    league_filter: str | None,
    team_filter: str | None,
) -> list[tuple[str, str, str]]:
    """Build a flat list of (team_name, sport, league) tuples to fetch."""
    all_teams = _get_team_list()
    result: list[tuple[str, str, str]] = []

    for sport, leagues in all_teams.items():
        if sport_filter and sport.lower() != sport_filter.lower():
            continue
        for league, teams in leagues.items():
            if league_filter and league.lower() != league_filter.lower():
                continue
            for team in teams:
                if team_filter:
                    if _fuzzy_match_team(team_filter, [team]) is None:
                        continue
                result.append((team, sport, league))

    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Batch-fetch team logos into the MzansiEdge logo cache.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--all", action="store_true", help="Fetch all known teams")
    parser.add_argument("--sport", metavar="SPORT", help="Filter by sport (soccer/rugby/cricket/mma)")
    parser.add_argument("--league", metavar="LEAGUE", help="Filter by league key (e.g. epl, psl)")
    parser.add_argument("--team", metavar="TEAM", help="Fetch a single team (fuzzy match)")
    parser.add_argument("--dry-run", action="store_true", help="List teams without fetching")
    parser.add_argument("--stats", action="store_true", help="Show cache statistics and exit")
    parser.add_argument(
        "--delay", type=float, default=0.5, metavar="SECS",
        help="Delay between API calls in seconds (default: 0.5)",
    )

    args = parser.parse_args()

    if args.stats:
        _show_stats()
        return

    if not (args.all or args.sport or args.team):
        parser.print_help()
        sys.exit(1)

    teams = _build_team_list(
        sport_filter=args.sport,
        league_filter=args.league,
        team_filter=args.team,
    )

    if not teams:
        print("No teams matched the given filters.")
        sys.exit(0)

    print(f"{'DRY-RUN: ' if args.dry_run else ''}Fetching {len(teams)} logo(s)…")
    _fetch_teams(teams, dry_run=args.dry_run, delay=args.delay)


if __name__ == "__main__":
    main()
