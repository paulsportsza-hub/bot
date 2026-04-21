"""MzansiEdge — Sports data service.

Fetches sports, leagues, teams/players from The Odds API.
Caches aggressively to preserve API quota (500 requests/month free tier).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
SAST = ZoneInfo("Africa/Johannesburg")
UTC = ZoneInfo("UTC")
from pathlib import Path
from typing import Any

import httpx
from thefuzz import fuzz, process

import config

log = logging.getLogger("mzansiedge.sports_data")

CACHE_DIR = config.DATA_DIR / "sports_cache"
CACHE_DIR.mkdir(exist_ok=True)


# ═══════════════════════════════════════════════════════════
# CACHING LAYER
# ═══════════════════════════════════════════════════════════

def _cache_path(key: str) -> Path:
    """Get cache file path for a key."""
    return CACHE_DIR / f"{key}.json"


def _read_cache(key: str, ttl_hours: int = 24) -> Any | None:
    """Read from file cache if fresh."""
    path = _cache_path(key)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        fetched = datetime.fromisoformat(data["fetched_at"])
        if datetime.now(SAST) - fetched < timedelta(hours=ttl_hours):
            return data["payload"]
    except Exception as e:
        log.warning("Cache read failed for %s: %s", key, e)
    return None


def _write_cache(key: str, payload: Any) -> None:
    """Write to file cache."""
    path = _cache_path(key)
    try:
        path.write_text(json.dumps({
            "payload": payload,
            "fetched_at": datetime.now(SAST).isoformat(),
        }, ensure_ascii=False))
    except Exception as e:
        log.warning("Cache write failed for %s: %s", key, e)


# ═══════════════════════════════════════════════════════════
# API FUNCTIONS
# ═══════════════════════════════════════════════════════════

async def fetch_available_sports(include_inactive: bool = False) -> dict[str, list[dict]]:
    """Fetch all sports from The Odds API, grouped by category.

    Returns: {
        "Soccer": [{"key": "soccer_epl", "title": "EPL", "active": True}, ...],
        "Rugby Union": [...],
        ...
    }

    Cached for 24 hours.
    """
    cache_key = "all_sports"
    cached = _read_cache(cache_key, ttl_hours=24)
    if cached:
        return cached

    params: dict[str, str] = {"apiKey": config.ODDS_API_KEY}
    if include_inactive:
        params["all"] = "true"

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{config.ODDS_BASE_URL}/sports", params=params,
            )
            if resp.status_code != 200:
                log.error("Sports API returned %d: %s", resp.status_code, resp.text)
                return {}

            sports_list = resp.json()
            grouped: dict[str, list[dict]] = {}
            for sport in sports_list:
                group = sport.get("group", "Other")
                grouped.setdefault(group, []).append({
                    "key": sport["key"],
                    "title": sport.get("title", sport["key"]),
                    "active": sport.get("active", False),
                    "description": sport.get("description", ""),
                })

            _write_cache(cache_key, grouped)
            return grouped

    except Exception as e:
        log.error("Failed to fetch sports: %s", e)
        return {}


async def fetch_teams_for_sport(sport_key: str) -> list[str]:
    """Fetch upcoming events for a sport and extract unique team/player names.

    Returns sorted list: ["Arsenal", "Aston Villa", "Chelsea", ...]
    Cached for 12 hours.
    """
    cache_key = f"teams_{sport_key}"
    cached = _read_cache(cache_key, ttl_hours=12)
    if cached:
        return cached

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{config.ODDS_BASE_URL}/sports/{sport_key}/events",
                params={"apiKey": config.ODDS_API_KEY},
            )
            if resp.status_code != 200:
                log.error("Events API returned %d for %s", resp.status_code, sport_key)
                return []

            events = resp.json()
            teams: set[str] = set()
            for event in events:
                if event.get("home_team"):
                    teams.add(event["home_team"])
                if event.get("away_team"):
                    teams.add(event["away_team"])

            result = sorted(teams)
            _write_cache(cache_key, result)
            return result

    except Exception as e:
        log.error("Failed to fetch teams for %s: %s", sport_key, e)
        return []


async def fetch_events_for_league(league_key: str) -> list[dict]:
    """Fetch upcoming events for a league.

    Returns list of event dicts with: id, home_team, away_team, commence_time, sport_key.
    Cached for 2 hours. Uses /events endpoint (does NOT count against odds quota).
    """
    # Map internal league key → Odds API key
    api_key = config.SPORTS_MAP.get(league_key)
    if api_key is None:
        log.info("Skipping events fetch for unsupported league %s", league_key)
        return []
    cache_key = f"events_{api_key}"
    cached = _read_cache(cache_key, ttl_hours=2)
    if cached:
        return cached

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{config.ODDS_BASE_URL}/sports/{api_key}/events",
                params={"apiKey": config.ODDS_API_KEY},
            )
            if resp.status_code != 200:
                log.error("Events API returned %d for %s", resp.status_code, league_key)
                return []

            events = resp.json()
            _write_cache(cache_key, events)
            return events

    except Exception as e:
        log.error("Failed to fetch events for %s: %s", league_key, e)
        return []


async def get_top_teams_for_sport(
    sport_group: str,
    sport_key: str | None = None,
    limit: int = 10,
) -> list[str]:
    """Get top teams/players for a sport. API first, curated fallback.

    Args:
        sport_group: The group name (e.g. "Soccer", "Tennis")
        sport_key: Specific league key to fetch from (e.g. "soccer_epl")
        limit: Max number of results
    """
    if sport_key:
        api_teams = await fetch_teams_for_sport(sport_key)
        if api_teams:
            return api_teams[:limit]

    curated = CURATED_LISTS.get(sport_group, CURATED_LISTS.get(sport_key or "", []))
    return curated[:limit]


# ═══════════════════════════════════════════════════════════
# CURATED TOP LISTS (fallback when API has no events)
# ═══════════════════════════════════════════════════════════

CURATED_LISTS: dict[str, list[str]] = {
    # ── Soccer — SA ──
    "soccer_south_africa_premiership": [
        "Kaizer Chiefs", "Orlando Pirates", "Mamelodi Sundowns",
        "AmaZulu", "Royal AM", "Stellenbosch", "Cape Town City",
        "SuperSport United", "Sekhukhune United", "Richards Bay",
    ],
    "soccer_south_africa_psl": [
        "Kaizer Chiefs", "Orlando Pirates", "Mamelodi Sundowns",
        "AmaZulu", "Royal AM", "Stellenbosch", "Cape Town City",
        "SuperSport United", "Sekhukhune United", "Richards Bay",
    ],
    # ── Soccer — EPL ──
    "soccer_epl": [
        "Arsenal", "Manchester City", "Liverpool", "Chelsea",
        "Manchester United", "Tottenham", "Newcastle", "Aston Villa",
        "Brighton", "West Ham",
    ],
    # ── Soccer — La Liga ──
    "soccer_spain_la_liga": [
        "Real Madrid", "Barcelona", "Atletico Madrid", "Athletic Bilbao",
        "Real Sociedad", "Real Betis", "Villarreal", "Girona",
        "Sevilla", "Valencia",
    ],
    # ── Boxing ──
    "Boxing": [
        "Oleksandr Usyk", "Tyson Fury", "Canelo Alvarez",
        "Terence Crawford", "Naoya Inoue", "Dmitry Bivol",
        "Gervonta Davis", "Shakur Stevenson", "Errol Spence Jr",
        "Artur Beterbiev",
    ],
    # ── MMA / UFC ──
    "Mixed Martial Arts": [
        "Islam Makhachev", "Alex Pereira", "Jon Jones",
        "Leon Edwards", "Ilia Topuria", "Dricus Du Plessis",
        "Max Holloway", "Charles Oliveira", "Sean O'Malley",
        "Alexander Volkanovski",
    ],
    # ── Rugby ──
    "Rugby Union": [
        "Springboks", "Stormers", "Bulls", "Sharks", "Lions",
        "Crusaders", "Blues", "Chiefs", "Hurricanes", "Brumbies",
    ],
    "Rugby League": [
        "Penrith Panthers", "Melbourne Storm", "Brisbane Broncos",
        "Sydney Roosters", "Cronulla Sharks", "Manly Sea Eagles",
        "Parramatta Eels", "Newcastle Knights", "Canterbury Bulldogs", "Dolphins",
    ],
    # ── Cricket ──
    "Cricket": [
        "South Africa", "India", "Australia", "England",
        "New Zealand", "Pakistan", "West Indies", "Sri Lanka",
        "Bangladesh", "Afghanistan",
    ],
}


# ═══════════════════════════════════════════════════════════
# ALIAS DICTIONARY (common abbreviations, nicknames, SA slang)
# ═══════════════════════════════════════════════════════════

ALIASES: dict[str, str] = {
    # Soccer — EPL
    "mcu": "Manchester City", "man city": "Manchester City",
    "city": "Manchester City", "cityzens": "Manchester City",
    "sky blues": "Manchester City",
    "manu": "Manchester United", "man utd": "Manchester United",
    "man u": "Manchester United", "united": "Manchester United",
    "red devils": "Manchester United",
    "pool": "Liverpool", "lfc": "Liverpool", "reds": "Liverpool",
    "ars": "Arsenal", "gunners": "Arsenal", "gooners": "Arsenal",
    "che": "Chelsea", "blues": "Chelsea",
    "spurs": "Tottenham", "tottenham": "Tottenham Hotspur",
    "toon": "Newcastle", "nufc": "Newcastle",
    "villa": "Aston Villa", "avfc": "Aston Villa",
    "hammers": "West Ham", "whu": "West Ham",
    "wolves": "Wolverhampton",
    "forest": "Nottingham Forest", "nffc": "Nottingham Forest",
    "man united": "Manchester United",
    "newcastle": "Newcastle United",
    "brighton": "Brighton and Hove Albion",
    "everton": "Everton", "toffees": "Everton",
    "fulham": "Fulham", "palace": "Crystal Palace",
    "bournemouth": "AFC Bournemouth", "brentford": "Brentford",
    "chelsea": "Chelsea", "liverpool": "Liverpool", "arsenal": "Arsenal",
    # Soccer — SA PSL
    "chiefs": "Kaizer Chiefs", "kc": "Kaizer Chiefs", "amakhosi": "Kaizer Chiefs",
    "pirates": "Orlando Pirates", "bucs": "Orlando Pirates", "buccaneers": "Orlando Pirates",
    "sundowns": "Mamelodi Sundowns", "downs": "Mamelodi Sundowns",
    "masandawana": "Mamelodi Sundowns", "brazilians": "Mamelodi Sundowns",
    "amazulu": "AmaZulu", "usuthu": "AmaZulu",
    "cct": "Cape Town City", "ctc": "Cape Town City",
    "matsatsantsa": "SuperSport United", "supersport": "SuperSport United",
    "stellies": "Stellenbosch", "sekhukhune": "Sekhukhune United",
    "galaxy": "TS Galaxy", "polokwane": "Polokwane City",
    "glamour boys": "Kaizer Chiefs",
    # Soccer — La Liga
    "barca": "Barcelona", "fcb": "Barcelona", "blaugrana": "Barcelona",
    "madrid": "Real Madrid", "real": "Real Madrid", "los blancos": "Real Madrid",
    "atleti": "Atletico Madrid", "atletico": "Atletico Madrid",
    # Boxing
    "canelo": "Canelo Alvarez",
    "tank": "Gervonta Davis", "tank davis": "Gervonta Davis",
    "fury": "Tyson Fury",
    "usyk": "Oleksandr Usyk",
    "crawford": "Terence Crawford", "bud": "Terence Crawford",
    "shakur": "Shakur Stevenson",
    "monster": "Naoya Inoue", "inoue": "Naoya Inoue",
    # UFC / MMA
    "islam": "Islam Makhachev", "makhachev": "Islam Makhachev",
    "pereira": "Alex Pereira", "poatan": "Alex Pereira",
    "bones": "Jon Jones", "jones": "Jon Jones",
    "izzy": "Israel Adesanya", "adesanya": "Israel Adesanya",
    "dricus": "Dricus Du Plessis", "drc": "Dricus Du Plessis",
    "stillknocks": "Dricus Du Plessis",
    "max": "Max Holloway", "blessed": "Max Holloway",
    "topuria": "Ilia Topuria",
    "volk": "Alexander Volkanovski",
    "do bronx": "Charles Oliveira", "oliveira": "Charles Oliveira",
    "suga": "Sean O'Malley", "omalley": "Sean O'Malley",
    # Cricket
    "proteas": "South Africa", "sa": "South Africa",
    "blackcaps": "New Zealand", "nz": "New Zealand",
    "windies": "West Indies", "wi": "West Indies",
    "aussies": "Australia", "aus": "Australia",
    "poms": "England", "eng": "England",
    # Rugby
    "boks": "Springboks", "springboks": "Springboks", "bokke": "Springboks",
    "all blacks": "All Blacks",
    "les bleus": "France",
    # Boxing (extended)
    "canelo": "Canelo Alvarez",
    "tank": "Gervonta Davis", "tank davis": "Gervonta Davis",
    "fury": "Tyson Fury",
    # MMA (extended)
    "stillknocks": "Dricus Du Plessis",
    "poatan": "Alex Pereira",
}


# ═══════════════════════════════════════════════════════════
# FUZZY MATCHING
# ═══════════════════════════════════════════════════════════

def fuzzy_match_team(input_text: str, known_names: list[str]) -> list[dict]:
    """Match user input against known teams/players.

    Strategy:
    1. Exact match (case-insensitive)
    2. Alias lookup
    3. Levenshtein distance via thefuzz (handles typos)
    4. Substring match

    Returns top 3 matches with confidence score:
    [{"name": "Carlos Alcaraz", "confidence": 95, "match_type": "alias"}, ...]
    """
    text = input_text.strip().lower()
    if not text:
        return []

    results: list[dict] = []

    # 1. Exact match
    for name in known_names:
        if name.lower() == text:
            return [{"name": name, "confidence": 100, "match_type": "exact"}]

    # 2. Alias lookup
    if text in ALIASES:
        alias_target = ALIASES[text]
        for name in known_names:
            if name.lower() == alias_target.lower():
                return [{"name": name, "confidence": 98, "match_type": "alias"}]
        # Alias exists but target not in current list — still return it
        return [{"name": alias_target, "confidence": 95, "match_type": "alias"}]

    # 3. Fuzzy matching with thefuzz
    if known_names:
        fuzzy_results = process.extract(
            input_text, known_names, scorer=fuzz.token_sort_ratio, limit=3,
        )
        for name, score in fuzzy_results:
            if score >= 60:
                results.append({"name": name, "confidence": score, "match_type": "fuzzy"})

    # 4. Substring match
    for name in known_names:
        if text in name.lower() and not any(r["name"] == name for r in results):
            results.append({"name": name, "confidence": 75, "match_type": "substring"})

    results.sort(key=lambda x: x["confidence"], reverse=True)
    return results[:3]
