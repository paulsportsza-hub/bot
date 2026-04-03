"""API-Football v3 fetcher — primary data source for soccer context.

Pro tier: 7,500 requests/day.  Replaces ESPN as primary, ESPN becomes fallback.

Endpoints used (per match, worst case ~6 calls):
  - /standings          (1 call, cached 24h — Tier A)
  - /fixtures/headtohead (1 call per pair, cached 24h)
  - /injuries           (1 call per fixture, cached 2-6h — Tier B)
  - /predictions        (1 call per fixture, cached 6h)
  - /coachs             (via existing coach_fetcher, cached 7d)

Budget: ~6 calls/match × ~50 matches/day ≈ 300 calls/day (4% of budget).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

import aiohttp

from db_connection import get_connection
from fetchers.base_fetcher import (
    BaseFetcher,
    FetchResult,
    get_cached_api_response,
    store_api_response,
    DB_PATH,
)

log = logging.getLogger("mzansi.fetchers.football")

API_FOOTBALL_BASE = "https://v3.football.api-sports.io"
REQUEST_TIMEOUT = 15  # seconds

# Internal league key → API-Football league ID + current season
LEAGUE_CONFIG: dict[str, dict[str, Any]] = {
    "psl":              {"api_id": 288, "season": 2025, "display": "South African PSL"},
    "epl":              {"api_id": 39,  "season": 2025, "display": "English Premier League"},
    "champions_league": {"api_id": 2,   "season": 2025, "display": "UEFA Champions League"},
    "la_liga":          {"api_id": 140, "season": 2025, "display": "La Liga"},
    "bundesliga":       {"api_id": 78,  "season": 2025, "display": "Bundesliga"},
    "serie_a":          {"api_id": 135, "season": 2025, "display": "Serie A"},
    "ligue_1":          {"api_id": 61,  "season": 2025, "display": "Ligue 1"},
}

# Static team name → API-Football team ID mapping (loaded from scrapers/)
_TEAM_IDS_CACHE: dict | None = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_api_key() -> str:
    """Resolve API-Football key from env or .env files."""
    key = os.environ.get("API_FOOTBALL_KEY", "")
    if key:
        return key
    # Try bot .env
    for env_path in [
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"),
        os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "scrapers", ".env"),
    ]:
        try:
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("API_FOOTBALL_KEY="):
                        return line.split("=", 1)[1].strip().strip('"').strip("'")
        except FileNotFoundError:
            continue
    return ""


def _load_team_ids() -> dict[str, int]:
    """Load team name → API-Football ID mapping."""
    global _TEAM_IDS_CACHE
    if _TEAM_IDS_CACHE is not None:
        return _TEAM_IDS_CACHE

    ids_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "scrapers", "api_football_ids.json",
    )
    try:
        with open(ids_path) as f:
            data = json.load(f)
        _TEAM_IDS_CACHE = data.get("soccer", {})
    except (FileNotFoundError, json.JSONDecodeError):
        _TEAM_IDS_CACHE = {}
    return _TEAM_IDS_CACHE


def _resolve_team_id(team_name: str) -> int | None:
    """Resolve normalised team name to API-Football team ID."""
    ids = _load_team_ids()
    normalised = team_name.lower().strip().replace("_", " ")

    # Direct match
    if normalised in ids:
        return ids[normalised]

    # Substring match (e.g. "sundowns" → "mamelodi sundowns")
    for name, tid in ids.items():
        if normalised in name or name in normalised:
            return tid

    return None


async def _api_fetch(
    session: aiohttp.ClientSession,
    endpoint: str,
    params: dict[str, Any],
    api_key: str,
) -> dict[str, Any]:
    """Fetch JSON from API-Football v3."""
    url = f"{API_FOOTBALL_BASE}/{endpoint}"
    headers = {"x-apisports-key": api_key}
    try:
        async with session.get(
            url, headers=headers, params=params,
            timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
        ) as resp:
            if resp.status != 200:
                log.warning("API-Football %s returned %d", endpoint, resp.status)
                return {}
            data = await resp.json()
            remaining = resp.headers.get("x-ratelimit-requests-remaining", "?")
            log.info(
                "API-Football %s: %d results, %s calls remaining",
                endpoint, data.get("results", 0), remaining,
            )
            return data
    except Exception as exc:
        log.warning("API-Football %s failed: %s", endpoint, exc)
        return {}


# ── Data Extraction ───────────────────────────────────────────────────────────


def _wdl_dict_to_str(stats: dict) -> str:
    """Convert API-Football record dict {'wins':N,'draws':N,'losses':N} → 'WN DN LN'."""
    w = int(stats.get("wins", 0) or 0)
    d = int(stats.get("draws", 0) or 0)
    l = int(stats.get("losses", 0) or 0)
    return f"W{w} D{d} L{l}"


def _extract_standings(
    standings_response: dict[str, Any],
    league_id: int,
) -> dict[str, dict[str, Any]]:
    """Parse standings response → {normalised_name: team_data}."""
    teams: dict[str, dict[str, Any]] = {}
    for league_block in standings_response.get("response", []):
        for group in league_block.get("league", {}).get("standings", []):
            for entry in group:
                team_info = entry.get("team", {})
                name = (team_info.get("name") or "").lower().strip()
                if not name:
                    continue

                all_stats = entry.get("all", {})
                home_stats = entry.get("home", {})
                away_stats = entry.get("away", {})

                # Form string from API-Football is last 5 chars like "WWDLD"
                form_raw = entry.get("form", "") or ""

                teams[name] = {
                    "name": team_info.get("name", ""),
                    "api_id": team_info.get("id"),
                    "position": entry.get("rank"),
                    "league_position": entry.get("rank"),
                    "points": entry.get("points"),
                    "games_played": all_stats.get("played", 0),
                    "matches_played": all_stats.get("played", 0),
                    "form": form_raw[-5:] if form_raw else "",
                    "goals_for": all_stats.get("goals", {}).get("for", 0),
                    "goals_against": all_stats.get("goals", {}).get("against", 0),
                    "goal_difference": entry.get("goalsDiff", 0),
                    "record": _wdl_dict_to_str({
                        "wins": all_stats.get("win", 0),
                        "draws": all_stats.get("draw", 0),
                        "losses": all_stats.get("lose", 0),
                    }),
                    "home_record": _wdl_dict_to_str({
                        "wins": home_stats.get("win", 0),
                        "draws": home_stats.get("draw", 0),
                        "losses": home_stats.get("lose", 0),
                    }),
                    "away_record": _wdl_dict_to_str({
                        "wins": away_stats.get("win", 0),
                        "draws": away_stats.get("draw", 0),
                        "losses": away_stats.get("lose", 0),
                    }),
                }
    return teams


def _extract_h2h(h2h_response: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse H2H response → list of past meetings."""
    meetings: list[dict[str, Any]] = []
    for fixture in h2h_response.get("response", []):
        fix = fixture.get("fixture", {})
        teams = fixture.get("teams", {})
        goals = fixture.get("goals", {})

        home_name = teams.get("home", {}).get("name", "")
        away_name = teams.get("away", {}).get("name", "")
        home_goals = goals.get("home")
        away_goals = goals.get("away")

        if home_goals is None or away_goals is None:
            continue

        meetings.append({
            "date": fix.get("date", ""),
            "home": home_name,
            "away": away_name,
            "home_goals": home_goals,
            "away_goals": away_goals,
            "venue": fix.get("venue", {}).get("name", ""),
            "result": (
                f"{home_name} {home_goals}-{away_goals} {away_name}"
            ),
        })
    return meetings[:5]  # last 5


def _extract_injuries(
    injuries_response: dict[str, Any],
) -> dict[str, list[dict[str, str]]]:
    """Parse injuries response → {team_name_lower: [{player, type, reason}]}."""
    by_team: dict[str, list[dict[str, str]]] = {}
    for entry in injuries_response.get("response", []):
        team_name = (entry.get("team", {}).get("name") or "").lower()
        player = entry.get("player", {})
        injury = {
            "player": player.get("name", ""),
            "type": player.get("type", ""),
            "reason": player.get("reason", ""),
        }
        by_team.setdefault(team_name, []).append(injury)
    return by_team


def _extract_predictions(
    pred_response: dict[str, Any],
) -> dict[str, Any]:
    """Parse predictions response → summary dict."""
    results = pred_response.get("response", [])
    if not results:
        return {}
    pred = results[0]
    predictions = pred.get("predictions", {})
    comparison = pred.get("comparison", {})
    teams = pred.get("teams", {})

    home_stats = teams.get("home", {}).get("league", {})
    away_stats = teams.get("away", {}).get("league", {})

    return {
        "winner": predictions.get("winner", {}).get("name"),
        "advice": predictions.get("advice"),
        "home_pct": predictions.get("percent", {}).get("home", "0%"),
        "draw_pct": predictions.get("percent", {}).get("draw", "0%"),
        "away_pct": predictions.get("percent", {}).get("away", "0%"),
        "comparison": comparison,
        "home_last_5_form": home_stats.get("form", ""),
        "away_last_5_form": away_stats.get("form", ""),
        "home_top_scorer": _extract_top_scorer(teams.get("home", {})),
        "away_top_scorer": _extract_top_scorer(teams.get("away", {})),
    }


def _extract_top_scorer(team_block: dict) -> dict[str, Any] | None:
    """Extract top scorer from predictions team block."""
    players = team_block.get("players", [])
    if not players:
        return None
    # First player is usually top scorer in predictions response
    p = players[0]
    return {"name": p.get("name", ""), "goals": p.get("goals", {}).get("total", 0)}


# ── Elo Integration ──────────────────────────────────────────────────────────

def _get_elo_ratings(
    home_team: str,
    away_team: str,
    db_path: str | None = None,
) -> tuple[float | None, float | None]:
    """Fetch Elo ratings from elo_ratings table if available."""
    conn = get_connection(db_path or DB_PATH, readonly=True)
    try:
        home_elo = None
        away_elo = None

        for team, setter in [(home_team, "home"), (away_team, "away")]:
            normalised = team.lower().strip().replace("_", " ")
            row = conn.execute(
                """SELECT rating FROM elo_ratings
                   WHERE LOWER(team) = ? AND sport = 'soccer'
                   ORDER BY updated_at DESC LIMIT 1""",
                (normalised,),
            ).fetchone()
            if row:
                if setter == "home":
                    home_elo = row["rating"]
                else:
                    away_elo = row["rating"]
        return home_elo, away_elo
    except Exception:
        return None, None
    finally:
        conn.close()


# ── Main Fetcher ──────────────────────────────────────────────────────────────

def _match_team_in_standings(
    team_name: str,
    standings: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    """Fuzzy-match a team name against standings keys."""
    normalised = team_name.lower().strip().replace("_", " ")

    # Direct match
    if normalised in standings:
        return standings[normalised]

    # Substring match
    for key, data in standings.items():
        if normalised in key or key in normalised:
            return data

    return None


class FootballFetcher(BaseFetcher):
    """API-Football v3 fetcher for soccer."""

    sport = "soccer"

    async def fetch_context(
        self,
        home_team: str,
        away_team: str,
        league: str,
        horizon_hours: float = 168.0,
        *,
        live_safe: bool = True,
        db_path: str | None = None,
    ) -> FetchResult:
        """Fetch soccer context from API-Football with caching and fallback."""
        db = db_path or DB_PATH
        api_key = _get_api_key()
        confidence: dict[str, float] = {}
        sources: dict[str, str] = {}

        league_cfg = LEAGUE_CONFIG.get(league)
        if not league_cfg:
            log.warning("Unknown league %s — no API-Football config", league)
            return self._espn_fallback(home_team, away_team, league)

        league_id = league_cfg["api_id"]
        season = league_cfg["season"]
        display_name = league_cfg["display"]

        if not api_key:
            log.warning("No API_FOOTBALL_KEY — falling back to ESPN")
            return self._espn_fallback(home_team, away_team, league)

        home_data: dict[str, Any] = {"name": home_team}
        away_data: dict[str, Any] = {"name": away_team}
        h2h_list: list[dict] = []
        venue = ""
        predictions_data: dict[str, Any] = {}

        async with aiohttp.ClientSession() as session:
            # ── Tier A: Standings (cached 24h) ────────────────────────────
            standings_cache_key = f"apif:standings:{league_id}:{season}"
            standings_raw = get_cached_api_response(standings_cache_key, db_path=db)

            if not standings_raw:
                standings_raw = await _api_fetch(
                    session, "standings",
                    {"league": league_id, "season": season},
                    api_key,
                )
                if standings_raw.get("response"):
                    store_api_response(
                        standings_cache_key, standings_raw,
                        "soccer", league, "standings",
                        ttl_hours=24.0, db_path=db,
                    )

            standings = _extract_standings(standings_raw, league_id)
            home_standing = _match_team_in_standings(home_team, standings)
            away_standing = _match_team_in_standings(away_team, standings)

            if home_standing:
                home_data.update(home_standing)
                confidence["home_standings"] = 1.0
                sources["home_standings"] = "api-football"
            if away_standing:
                away_data.update(away_standing)
                confidence["away_standings"] = 1.0
                sources["away_standings"] = "api-football"

            # ── H2H (cached 24h) ─────────────────────────────────────────
            home_id = _resolve_team_id(home_team)
            away_id = _resolve_team_id(away_team)

            if home_id and away_id:
                h2h_cache_key = f"apif:h2h:{min(home_id,away_id)}-{max(home_id,away_id)}"
                h2h_raw = get_cached_api_response(h2h_cache_key, db_path=db)

                if not h2h_raw:
                    h2h_raw = await _api_fetch(
                        session, "fixtures/headtohead",
                        {"h2h": f"{home_id}-{away_id}", "last": 5},
                        api_key,
                    )
                    if h2h_raw.get("response"):
                        store_api_response(
                            h2h_cache_key, h2h_raw,
                            "soccer", league, "h2h",
                            ttl_hours=24.0, db_path=db,
                        )

                h2h_list = _extract_h2h(h2h_raw)
                if h2h_list:
                    confidence["h2h"] = 1.0
                    sources["h2h"] = "api-football"

            # ── Fixture ID lookup (for injuries/predictions) ──────────────
            fixture_id = None
            if home_id and away_id:
                fix_cache_key = f"apif:fixture_id:{home_id}:{away_id}:{league_id}"
                fix_cached = get_cached_api_response(fix_cache_key, db_path=db)

                if fix_cached and fix_cached.get("fixture_id"):
                    fixture_id = fix_cached["fixture_id"]
                    venue = fix_cached.get("venue", "")
                else:
                    fix_data = await _api_fetch(
                        session, "fixtures",
                        {
                            "league": league_id,
                            "season": season,
                            "team": home_id,
                            "next": 5,
                        },
                        api_key,
                    )
                    for fix in fix_data.get("response", []):
                        teams = fix.get("teams", {})
                        fix_home_id = teams.get("home", {}).get("id")
                        fix_away_id = teams.get("away", {}).get("id")
                        if {fix_home_id, fix_away_id} == {home_id, away_id}:
                            fixture_id = fix.get("fixture", {}).get("id")
                            venue = fix.get("fixture", {}).get("venue", {}).get("name", "")
                            break

                    if fixture_id:
                        store_api_response(
                            fix_cache_key,
                            {"fixture_id": fixture_id, "venue": venue},
                            "soccer", league, "fixture_lookup",
                            ttl_hours=24.0, db_path=db,
                        )

            # ── Tier B: Injuries (horizon-dependent TTL) ──────────────────
            from fetchers.base_fetcher import horizon_bucket
            bucket = horizon_bucket(horizon_hours)

            if fixture_id and bucket in ("mid", "near"):
                injury_ttl = 2.0 if bucket == "near" else 6.0
                inj_cache_key = f"apif:injuries:{fixture_id}"
                inj_raw = get_cached_api_response(inj_cache_key, db_path=db)

                if not inj_raw:
                    inj_raw = await _api_fetch(
                        session, "injuries",
                        {"fixture": fixture_id},
                        api_key,
                    )
                    if inj_raw.get("response") is not None:
                        store_api_response(
                            inj_cache_key, inj_raw,
                            "soccer", league, "injuries",
                            ttl_hours=injury_ttl, db_path=db,
                        )

                injuries_by_team = _extract_injuries(inj_raw)
                home_injuries = (
                    injuries_by_team.get(home_team.lower(), [])
                    or next(
                        (v for k, v in injuries_by_team.items()
                         if home_team.lower() in k or k in home_team.lower()),
                        [],
                    )
                )
                away_injuries = (
                    injuries_by_team.get(away_team.lower(), [])
                    or next(
                        (v for k, v in injuries_by_team.items()
                         if away_team.lower() in k or k in away_team.lower()),
                        [],
                    )
                )
                if home_injuries:
                    home_data["injuries"] = home_injuries
                    confidence["home_injuries"] = 0.9
                    sources["home_injuries"] = "api-football"
                if away_injuries:
                    away_data["injuries"] = away_injuries
                    confidence["away_injuries"] = 0.9
                    sources["away_injuries"] = "api-football"

            # ── Predictions (cached 6h — includes top scorers + form) ─────
            if fixture_id:
                pred_cache_key = f"apif:predictions:{fixture_id}"
                pred_raw = get_cached_api_response(pred_cache_key, db_path=db)

                if not pred_raw:
                    pred_raw = await _api_fetch(
                        session, "predictions",
                        {"fixture": fixture_id},
                        api_key,
                    )
                    if pred_raw.get("response"):
                        store_api_response(
                            pred_cache_key, pred_raw,
                            "soccer", league, "predictions",
                            ttl_hours=6.0, db_path=db,
                        )

                predictions_data = _extract_predictions(pred_raw)

                # Enrich home/away with top scorer if not already set
                if predictions_data.get("home_top_scorer") and not home_data.get("top_scorer"):
                    home_data["top_scorer"] = predictions_data["home_top_scorer"]
                    sources["home_top_scorer"] = "api-football"
                if predictions_data.get("away_top_scorer") and not away_data.get("top_scorer"):
                    away_data["top_scorer"] = predictions_data["away_top_scorer"]
                    sources["away_top_scorer"] = "api-football"

                # Enrich form from predictions if standings didn't have it
                if predictions_data.get("home_last_5_form") and not home_data.get("form"):
                    home_data["form"] = predictions_data["home_last_5_form"][-5:]
                if predictions_data.get("away_last_5_form") and not away_data.get("form"):
                    away_data["form"] = predictions_data["away_last_5_form"][-5:]

        # ── Coach (existing coach_fetcher, cached 7d) ─────────────────────
        try:
            from scrapers.coach_fetcher import get_soccer_coach
            home_coach, away_coach = await asyncio.gather(
                get_soccer_coach(home_team, league, live_safe=live_safe),
                get_soccer_coach(away_team, league, live_safe=live_safe),
            )
            if home_coach:
                home_data["coach"] = home_coach
                confidence["home_coach"] = 1.0
                sources["home_coach"] = "api-football"
            if away_coach:
                away_data["coach"] = away_coach
                confidence["away_coach"] = 1.0
                sources["away_coach"] = "api-football"
        except Exception as exc:
            log.warning("Coach fetch failed: %s", exc)

        # ── Elo ratings ───────────────────────────────────────────────────
        home_elo, away_elo = _get_elo_ratings(home_team, away_team, db_path=db)

        # ── Assemble ESPN-compatible context dict ─────────────────────────
        context: dict[str, Any] = {
            "data_available": bool(home_data.get("position") or away_data.get("position") or h2h_list),
            "data_freshness": datetime.now(timezone.utc).isoformat(),
            "data_source": "api-football",
            "home_team": home_data,
            "away_team": away_data,
            "h2h": h2h_list,
            "competition": display_name,
            "season": f"{season}/{season + 1}",
            "venue": venue,
        }

        # Attach Elo for MEP check (not consumed by narrative_spec directly
        # but used by edge blending and MEP validation)
        if home_elo is not None:
            context["elo_home"] = home_elo
            confidence["elo_home"] = 1.0
            sources["elo_home"] = "elo_engine"
        if away_elo is not None:
            context["elo_away"] = away_elo
            confidence["elo_away"] = 1.0
            sources["elo_away"] = "elo_engine"

        if predictions_data:
            context["predictions"] = predictions_data

        return FetchResult(
            context=context,
            confidence=confidence,
            sources=sources,
        )

    def _espn_fallback(
        self,
        home_team: str,
        away_team: str,
        league: str,
    ) -> FetchResult:
        """Return empty result — ESPN fallback is handled by caller."""
        log.info("ESPN fallback for %s vs %s (%s)", home_team, away_team, league)
        return FetchResult(
            context={
                "data_available": False,
                "data_source": "none",
                "home_team": {"name": home_team},
                "away_team": {"name": away_team},
                "h2h": [],
                "competition": "",
                "season": "",
            },
            confidence={},
            sources={},
        )
