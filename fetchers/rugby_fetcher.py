"""API-Sports Rugby fetcher — structured context for rugby matches.

Free tier: 100 requests/day.  Seasons 2022-2024 accessible; 2025+ restricted.
API base: https://v1.rugby.api-sports.io
Auth: x-apisports-key header (same key as API-Football).

Endpoints used (per match, worst case ~5 calls):
  - /teams?name={name}    (team ID lookup, cached 7d)
  - /standings?league=…   (1 call per league, cached 24h)
  - /games?league=…&team= (recent games for form + H2H, cached 12h)
"""

from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
from datetime import datetime, timezone, date
from typing import Any

import aiohttp

from fetchers.base_fetcher import (
    BaseFetcher,
    FetchResult,
    get_cached_api_response,
    store_api_response,
    DB_PATH,
)

log = logging.getLogger("mzansi.fetchers.rugby")

API_RUGBY_BASE = "https://v1.rugby.api-sports.io"
REQUEST_TIMEOUT = 15

# Internal league key → Rugby API league ID + seasons to try (newest first)
LEAGUE_CONFIG: dict[str, dict[str, Any]] = {
    "urc":                {"api_id": 76,  "seasons": [2025, 2024, 2023], "display": "United Rugby Championship"},
    "super_rugby":        {"api_id": 71,  "seasons": [2026, 2025, 2024], "display": "Super Rugby"},
    "six_nations":        {"api_id": 51,  "seasons": [2026, 2025, 2024], "display": "Six Nations"},
    "rugby_championship": {"api_id": 85,  "seasons": [2025, 2024, 2023], "display": "Rugby Championship"},
    "currie_cup":         {"api_id": 37,  "seasons": [2025, 2024, 2023], "display": "Currie Cup"},
    "premiership_rugby":  {"api_id": 13,  "seasons": [2025, 2024, 2023], "display": "Premiership Rugby"},
    "top_14":             {"api_id": 16,  "seasons": [2025, 2024, 2023], "display": "Top 14"},
}

# Daily budget tracking (in-memory, resets at UTC midnight)
_budget: dict[str, int] = {}   # {"rugby": count}
_budget_date: dict[str, str] = {}  # {"rugby": "2026-04-03"}
DAILY_BUDGET = 90  # stay 10 under hard limit of 100

# Path to scrapers/odds.db which holds the rugby_fixtures table
_SCRAPERS_ODDS_DB = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "scrapers", "odds.db",
)


def _query_rugby_fixture(
    home_team: str,
    away_team: str,
    scrapers_db: str = _SCRAPERS_ODDS_DB,
) -> dict[str, Any] | None:
    """Query rugby_fixtures for a specific upcoming match. Returns row dict or None.

    Uses connect_odds_db_readonly() per W81-DBLOCK — never bare sqlite3.connect().
    Read-only URI mode avoids joining the scraper write queue.
    """
    try:
        from scrapers.db_connect import connect_odds_db_readonly  # noqa: PLC0415
        conn = connect_odds_db_readonly(scrapers_db)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """SELECT home_team, away_team, league_name, match_date, status,
                      home_team_api_id, away_team_api_id, league_api_id
               FROM rugby_fixtures
               WHERE LOWER(home_team) = LOWER(?)
                 AND LOWER(away_team) = LOWER(?)
                 AND match_date >= date('now')
                 AND status NOT IN ('FT', 'Cancelled', 'Postponed')
               ORDER BY match_date ASC
               LIMIT 1""",
            (home_team, away_team),
        ).fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception as exc:
        log.warning("rugby_fixtures DB lookup failed: %s", exc)
        return None


def _query_rugby_standings(
    team_name: str,
    team_api_id: int | None,
    league_api_id: int | None,
    scrapers_db: str = _SCRAPERS_ODDS_DB,
) -> dict[str, Any] | None:
    """Look up a team's current standings from rugby_standings.

    Primary: match by team_api_id + league_api_id (precise, avoids name collisions).
    Fallback: match by LOWER(team_name) + league_api_id.
    Returns None when league_api_id is unknown, table is missing, or no row found.

    Uses connect_odds_db_readonly() per W81-DBLOCK.
    """
    if not league_api_id:
        return None
    try:
        from scrapers.db_connect import connect_odds_db_readonly  # noqa: PLC0415
        conn = connect_odds_db_readonly(scrapers_db)
        conn.row_factory = sqlite3.Row
        row = None
        if team_api_id:
            row = conn.execute(
                """SELECT position, played, won, drawn, lost, points, points_diff, form
                   FROM rugby_standings
                   WHERE team_api_id = ? AND league_api_id = ?
                   ORDER BY season DESC
                   LIMIT 1""",
                (team_api_id, league_api_id),
            ).fetchone()
        if row is None:
            row = conn.execute(
                """SELECT position, played, won, drawn, lost, points, points_diff, form
                   FROM rugby_standings
                   WHERE LOWER(team_name) = LOWER(?) AND league_api_id = ?
                   ORDER BY season DESC
                   LIMIT 1""",
                (team_name, league_api_id),
            ).fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception as exc:
        log.warning("rugby_standings DB lookup failed: %s", exc)
        return None


def _get_api_key() -> str:
    key = os.environ.get("API_FOOTBALL_KEY", "") or os.environ.get("API_SPORTS_KEY", "")
    if key:
        return key
    for env_path in [
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"),
        os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "scrapers", ".env",
        ),
    ]:
        try:
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith(("API_FOOTBALL_KEY=", "API_SPORTS_KEY=")):
                        return line.split("=", 1)[1].strip().strip('"').strip("'")
        except FileNotFoundError:
            continue
    return ""


def _check_budget() -> bool:
    """Return True if we have budget remaining today."""
    today = date.today().isoformat()
    if _budget_date.get("rugby") != today:
        _budget["rugby"] = 0
        _budget_date["rugby"] = today
    return _budget.get("rugby", 0) < DAILY_BUDGET


def _consume_budget(n: int = 1) -> None:
    today = date.today().isoformat()
    if _budget_date.get("rugby") != today:
        _budget["rugby"] = 0
        _budget_date["rugby"] = today
    _budget["rugby"] = _budget.get("rugby", 0) + n


async def _api_fetch(
    session: aiohttp.ClientSession,
    endpoint: str,
    params: dict[str, Any],
    api_key: str,
) -> dict[str, Any]:
    url = f"{API_RUGBY_BASE}/{endpoint}"
    headers = {"x-apisports-key": api_key}
    try:
        async with session.get(
            url, headers=headers, params=params,
            timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
        ) as resp:
            if resp.status != 200:
                log.warning("Rugby API %s returned %d", endpoint, resp.status)
                return {}
            data = await resp.json()
            _consume_budget()
            remaining = resp.headers.get("x-ratelimit-requests-remaining", "?")
            log.info(
                "Rugby API %s: %d results, %s daily calls remaining",
                endpoint, data.get("results", 0), remaining,
            )
            return data
    except Exception as exc:
        log.warning("Rugby API %s failed: %s", endpoint, exc)
        return {}


# ── Data Extraction ────────────────────────────────────────────────────────────

def _wdl_str(w: int, d: int, l: int) -> str:
    return f"W{w} D{d} L{l}"


def _extract_form_from_games(
    games: list[dict[str, Any]],
    team_id: int,
    limit: int = 5,
) -> str:
    """Extract W/D/L form string from recent finished games for a team."""
    results = []
    for g in sorted(games, key=lambda x: x.get("timestamp", 0), reverse=True):
        if g.get("status", {}).get("short") != "FT":
            continue
        teams = g.get("teams", {})
        scores = g.get("scores", {})
        home_id = teams.get("home", {}).get("id")
        away_id = teams.get("away", {}).get("id")
        home_score = scores.get("home", 0) or 0
        away_score = scores.get("away", 0) or 0

        if home_id == team_id:
            if home_score > away_score:
                results.append("W")
            elif home_score == away_score:
                results.append("D")
            else:
                results.append("L")
        elif away_id == team_id:
            if away_score > home_score:
                results.append("W")
            elif away_score == home_score:
                results.append("D")
            else:
                results.append("L")

        if len(results) >= limit:
            break

    return "".join(reversed(results))  # oldest → newest


def _extract_h2h_from_games(
    home_games: list[dict[str, Any]],
    home_id: int,
    away_id: int,
    home_name: str,
    away_name: str,
) -> list[dict[str, Any]]:
    """Derive H2H from home team's game list — find games vs away team."""
    meetings: list[dict[str, Any]] = []
    for g in sorted(home_games, key=lambda x: x.get("timestamp", 0), reverse=True):
        if g.get("status", {}).get("short") != "FT":
            continue
        teams = g.get("teams", {})
        scores = g.get("scores", {})
        h_id = teams.get("home", {}).get("id")
        a_id = teams.get("away", {}).get("id")
        if {h_id, a_id} != {home_id, away_id}:
            continue
        h_score = scores.get("home", 0) or 0
        a_score = scores.get("away", 0) or 0
        h_name = teams.get("home", {}).get("name", home_name)
        a_name = teams.get("away", {}).get("name", away_name)
        meetings.append({
            "date": g.get("date", ""),
            "home": h_name,
            "away": a_name,
            "home_goals": h_score,
            "away_goals": a_score,
            "result": f"{h_name} {h_score}-{a_score} {a_name}",
        })
        if len(meetings) >= 5:
            break
    return meetings


def _extract_standings_data(
    standings_response: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Parse standings response → {team_name_lower: data}."""
    teams: dict[str, dict[str, Any]] = {}
    for group in standings_response.get("response", []):
        for entry in (group if isinstance(group, list) else [group]):
            team = entry.get("team", {})
            name = (team.get("name") or "").lower().strip()
            if not name:
                continue
            games = entry.get("games", {})
            wins = games.get("win", {})
            draws = games.get("draw", {})
            losses = games.get("lose", {})
            w = int(wins.get("total", 0) or 0)
            d = int(draws.get("total", 0) or 0)
            l = int(losses.get("total", 0) or 0)
            played = int(games.get("played", 0) or 0)
            points = entry.get("points") or (w * 4 + d * 2)
            teams[name] = {
                "name": team.get("name", ""),
                "api_id": team.get("id"),
                "position": entry.get("position"),
                "league_position": entry.get("position"),
                "points": points,
                "games_played": played,
                "matches_played": played,
                "record": _wdl_str(w, d, l),
            }
    return teams


def _match_team_in_standings(
    team_name: str,
    standings: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    normalised = team_name.lower().strip().replace("_", " ")
    if normalised in standings:
        return standings[normalised]
    for key, data in standings.items():
        if normalised in key or key in normalised:
            return data
    return None


# ── Main Fetcher ───────────────────────────────────────────────────────────────

class RugbyFetcher(BaseFetcher):
    """API-Sports Rugby fetcher for rugby union matches."""

    sport = "rugby"

    async def fetch_context(
        self,
        home_team: str,
        away_team: str,
        league: str,
        horizon_hours: float = 168.0,  # noqa: ARG002
        *,
        live_safe: bool = True,  # noqa: ARG002
        db_path: str | None = None,
    ) -> FetchResult:
        db = db_path or DB_PATH

        # ── DB-first: rugby_fixtures ──────────────────────────────────────────
        # Query the scrapers odds.db for an upcoming fixture matching these teams.
        # Returns data_available=True immediately when found, avoiding API calls.
        try:
            fixture = await asyncio.wait_for(
                asyncio.to_thread(_query_rugby_fixture, home_team, away_team),
                timeout=3.0,
            )
        except Exception:
            fixture = None

        if fixture:
            competition = (
                fixture.get("league_name")
                or LEAGUE_CONFIG.get(league, {}).get("display", "")
            )
            home_data: dict[str, Any] = {"name": fixture["home_team"]}
            away_data: dict[str, Any] = {"name": fixture["away_team"]}

            # Enrich with standings from rugby_standings (RUNTIME-R2: to_thread + 3s timeout).
            league_api_id = fixture.get("league_api_id")
            for team_name, api_id, data in (
                (fixture["home_team"], fixture.get("home_team_api_id"), home_data),
                (fixture["away_team"], fixture.get("away_team_api_id"), away_data),
            ):
                try:
                    std = await asyncio.wait_for(
                        asyncio.to_thread(
                            _query_rugby_standings,
                            team_name, api_id, league_api_id,
                        ),
                        timeout=3.0,
                    )
                    if std:
                        data.update({
                            "position": std["position"],
                            "league_position": std["position"],
                            "points": std["points"],
                            "form": std["form"] or "",
                            "games_played": std["played"],
                            "matches_played": std["played"],
                            "record": (
                                f"W{std['won']} D{std['drawn']} L{std['lost']}"
                            ),
                        })
                except Exception:
                    pass  # standings enrichment is best-effort — never block fixture path

            return FetchResult(
                context={
                    "data_available": True,
                    "data_freshness": datetime.now(timezone.utc).isoformat(),
                    "data_source": "rugby_fixtures",
                    "home_team": home_data,
                    "away_team": away_data,
                    "h2h": [],
                    "competition": competition,
                    "season": "",
                    "venue": "",
                },
                confidence={"fixture": 1.0},
                sources={"fixture": "rugby_fixtures"},
            )
        # ─────────────────────────────────────────────────────────────────────

        api_key = _get_api_key()
        confidence: dict[str, float] = {}
        sources: dict[str, str] = {}

        league_cfg = LEAGUE_CONFIG.get(league)
        if not league_cfg:
            log.warning("Unknown rugby league %s — no Rugby API config", league)
            return self._empty_fallback(home_team, away_team, league)

        if not api_key:
            log.warning("No API key — falling back for rugby %s", league)
            return self._empty_fallback(home_team, away_team, league)

        if not _check_budget():
            log.warning("Rugby API daily budget exhausted — ESPN fallback")
            return self._empty_fallback(home_team, away_team, league)

        league_id = league_cfg["api_id"]
        seasons = league_cfg["seasons"]
        display_name = league_cfg["display"]

        home_data: dict[str, Any] = {"name": home_team}
        away_data: dict[str, Any] = {"name": away_team}
        h2h_list: list[dict] = []
        used_season: int | None = None

        async with aiohttp.ClientSession() as session:
            # ── Team ID lookup ────────────────────────────────────────────────
            home_id = await self._resolve_team_id(
                home_team, league_id, api_key, session, db,
            )
            away_id = await self._resolve_team_id(
                away_team, league_id, api_key, session, db,
            )

            if home_id:
                home_data["api_id"] = home_id
            if away_id:
                away_data["api_id"] = away_id

            # ── Standings (try seasons newest-first) ──────────────────────────
            standings_raw: dict[str, Any] = {}
            for season in seasons:
                standings_cache_key = f"apir:standings:{league_id}:{season}"
                _sr = get_cached_api_response(standings_cache_key, db_path=db)

                if not _sr:
                    if not _check_budget():
                        break
                    _sr = await _api_fetch(
                        session, "standings",
                        {"league": league_id, "season": season},
                        api_key,
                    )
                    if _sr.get("response"):
                        store_api_response(
                            standings_cache_key, _sr,
                            "rugby", league, "standings",
                            ttl_hours=24.0, db_path=db,
                        )
                        standings_raw = _sr
                        used_season = season
                        break
                    # Free plan error — try older season
                    errors = _sr.get("errors", {})
                    if errors:
                        log.info("Rugby standings season %d restricted: %s", season, errors)
                        continue
                else:
                    standings_raw = _sr
                    used_season = season
                    break

            if standings_raw.get("response"):
                standings = _extract_standings_data(standings_raw)
                home_std = _match_team_in_standings(home_team, standings)
                away_std = _match_team_in_standings(away_team, standings)
                if home_std:
                    home_data.update(home_std)
                    confidence["home_standings"] = 1.0
                    sources["home_standings"] = "api-sports-rugby"
                if away_std:
                    away_data.update(away_std)
                    confidence["away_standings"] = 1.0
                    sources["away_standings"] = "api-sports-rugby"

            # ── Recent games (form + H2H) ──────────────────────────────────
            season_for_games = used_season or seasons[-1]
            home_games: list[dict] = []

            if home_id and _check_budget():
                games_cache_key = f"apir:games:{league_id}:{home_id}:{season_for_games}"
                games_raw = get_cached_api_response(games_cache_key, db_path=db)

                if not games_raw:
                    games_raw = await _api_fetch(
                        session, "games",
                        {"league": league_id, "season": season_for_games, "team": home_id},
                        api_key,
                    )
                    if games_raw.get("response") is not None:
                        store_api_response(
                            games_cache_key, games_raw,
                            "rugby", league, "games",
                            ttl_hours=12.0, db_path=db,
                        )

                if games_raw:
                    home_games = games_raw.get("response", [])

                if home_games:
                    form_str = _extract_form_from_games(home_games, home_id)
                    if form_str:
                        home_data["form"] = form_str
                        confidence["home_form"] = 1.0
                        sources["home_form"] = "api-sports-rugby"

                    if away_id:
                        h2h_list = _extract_h2h_from_games(
                            home_games, home_id, away_id, home_team, away_team,
                        )
                        if h2h_list:
                            confidence["h2h"] = 1.0
                            sources["h2h"] = "api-sports-rugby"

            # Away team recent form (if not derived from H2H data)
            if away_id and _check_budget() and not away_data.get("form"):
                away_games_key = f"apir:games:{league_id}:{away_id}:{season_for_games}"
                away_games_raw = get_cached_api_response(away_games_key, db_path=db)
                if not away_games_raw:
                    away_games_raw = await _api_fetch(
                        session, "games",
                        {"league": league_id, "season": season_for_games, "team": away_id},
                        api_key,
                    )
                    if away_games_raw.get("response") is not None:
                        store_api_response(
                            away_games_key, away_games_raw,
                            "rugby", league, "games",
                            ttl_hours=12.0, db_path=db,
                        )
                if away_games_raw:
                    away_games = away_games_raw.get("response", [])
                    form_str = _extract_form_from_games(away_games, away_id)
                    if form_str:
                        away_data["form"] = form_str
                        confidence["away_form"] = 1.0
                        sources["away_form"] = "api-sports-rugby"

        season_label = f"{season_for_games}/{(season_for_games or 2024) + 1}"
        context: dict[str, Any] = {
            "data_available": bool(
                home_data.get("position") or away_data.get("position")
                or home_data.get("form") or h2h_list
            ),
            "data_freshness": datetime.now(timezone.utc).isoformat(),
            "data_source": "api-sports-rugby",
            "home_team": home_data,
            "away_team": away_data,
            "h2h": h2h_list,
            "competition": display_name,
            "season": season_label,
            "venue": "",
        }

        return FetchResult(context=context, confidence=confidence, sources=sources)

    async def _resolve_team_id(
        self,
        team_name: str,
        league_id: int,  # noqa: ARG002
        api_key: str,
        session: aiohttp.ClientSession,
        db: str,
    ) -> int | None:
        """Look up Rugby API team ID by name, with caching."""
        cache_key = f"apir:team_id:{team_name.lower().replace(' ', '_')}"
        cached = get_cached_api_response(cache_key, db_path=db)
        if cached and cached.get("team_id"):
            return cached["team_id"]

        if not _check_budget():
            return None

        data = await _api_fetch(session, "teams", {"name": team_name}, api_key)
        for team in data.get("response", []):
            tid = team.get("id")
            if tid:
                store_api_response(
                    cache_key, {"team_id": tid},
                    "rugby", "any", "team_lookup",
                    ttl_hours=168.0, db_path=db,  # cache 7 days
                )
                return tid

        # Substring fallback
        normalised = team_name.lower().strip()
        for word in normalised.split():
            if len(word) < 4:
                continue
            data2 = await _api_fetch(session, "teams", {"name": word}, api_key)
            for team in data2.get("response", []):
                tid = team.get("id")
                if tid:
                    store_api_response(
                        cache_key, {"team_id": tid},
                        "rugby", "any", "team_lookup",
                        ttl_hours=168.0, db_path=db,
                    )
                    return tid

        return None

    def _empty_fallback(
        self,
        home_team: str,
        away_team: str,
        league: str,
    ) -> FetchResult:
        return FetchResult(
            context={
                "data_available": False,
                "data_source": "none",
                "home_team": {"name": home_team},
                "away_team": {"name": away_team},
                "h2h": [],
                "competition": LEAGUE_CONFIG.get(league, {}).get("display", ""),
                "season": "",
            },
            confidence={},
            sources={},
        )
