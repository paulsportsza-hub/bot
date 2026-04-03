"""SportMonks Cricket API v2 fetcher — primary data source for cricket context.

API plan: subscription tier. Endpoints used (per match, worst case ~6 calls):
  - /fixtures          (1 call per date range, cached 12h — Tier A)
  - /standings/season  (1 call per season, cached 12h)
  - /fixtures/{id}     (match detail with batting/bowling, cached 6h — Tier B)
  - /players/{id}      (player stats, cached 24h — Tier C)

Budget: ~6 calls/match × ~10 cricket matches/day ≈ 60 calls/day.
Rate limit: honour 429 responses, log remaining calls after each batch.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
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

log = logging.getLogger("mzansi.fetchers.cricket")

SPORTMONKS_BASE = "https://cricket.sportmonks.com/api/v2.0"
REQUEST_TIMEOUT = 15  # seconds

# Internal league key → SportMonks league ID + season
# Season IDs are discovered at runtime via /leagues; these are best-known current values.
LEAGUE_CONFIG: dict[str, dict[str, Any]] = {
    "ipl":             {"league_id": 1,   "season": None, "display": "Indian Premier League"},
    "t20_international": {"league_id": 3, "season": None, "display": "T20 International"},
    "csa_t20":         {"league_id": 10,  "season": None, "display": "CSA T20 Challenge"},
    # SA20 and others — IDs discovered at runtime via _discover_league_id()
    "sa20":            {"league_id": None, "season": None, "display": "SA20"},
    "test_cricket":    {"league_id": None, "season": None, "display": "Test Cricket"},
    "odi":             {"league_id": None, "season": None, "display": "ODI"},
    "t20_world_cup":   {"league_id": None, "season": None, "display": "ICC T20 World Cup"},
}

# Discovery cache: populated the first time _discover_league_id runs
_LEAGUE_ID_DISCOVERY: dict[str, int | None] = {}


# ── Helpers ───────────────────────────────────────────────────────────────────


def _get_api_token() -> str:
    """Resolve SportMonks Cricket API token from env or .env files."""
    token = os.environ.get("SPORTMONKS_CRICKET_TOKEN", "")
    if token:
        return token
    for env_path in [
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"),
        os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "scrapers",
            ".env",
        ),
    ]:
        try:
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("SPORTMONKS_CRICKET_TOKEN="):
                        return line.split("=", 1)[1].strip().strip('"').strip("'")
        except FileNotFoundError:
            continue
    return ""


async def _api_fetch(
    session: aiohttp.ClientSession,
    endpoint: str,
    params: dict[str, Any],
    token: str,
) -> dict[str, Any]:
    """Fetch JSON from SportMonks Cricket v2.

    Auth: api_token query parameter (NOT headers — SportMonks v2 spec).
    Logs x-ratelimit-remaining after every call.
    """
    url = f"{SPORTMONKS_BASE}/{endpoint}"
    all_params = {"api_token": token, **params}
    try:
        async with session.get(
            url,
            params=all_params,
            timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
        ) as resp:
            if resp.status == 429:
                log.warning("SportMonks rate limit hit on %s — skipping", endpoint)
                return {}
            if resp.status != 200:
                log.warning("SportMonks %s returned HTTP %d", endpoint, resp.status)
                return {}
            data = await resp.json()
            remaining = resp.headers.get("x-ratelimit-remaining", "?")
            used = resp.headers.get("x-ratelimit-used", "?")
            log.info(
                "SportMonks %s: %s calls remaining, %s used",
                endpoint,
                remaining,
                used,
            )
            return data
    except Exception as exc:
        log.warning("SportMonks %s failed: %s", endpoint, exc)
        return {}


def _paginate(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the data array regardless of pagination wrapper."""
    if isinstance(data.get("data"), list):
        return data["data"]
    return []


# ── League Discovery ──────────────────────────────────────────────────────────


async def _discover_league_id(
    session: aiohttp.ClientSession,
    token: str,
    league_key: str,
    db: str,
) -> int | None:
    """Find SportMonks league ID for unknown leagues via /leagues search.

    SA20 may be listed under different names — match by country (South Africa)
    and name keywords.
    """
    if league_key in _LEAGUE_ID_DISCOVERY:
        return _LEAGUE_ID_DISCOVERY[league_key]

    cache_key = f"sportmonks:leagues_list"
    leagues_raw = get_cached_api_response(cache_key, db_path=db)
    if not leagues_raw:
        leagues_raw = await _api_fetch(session, "leagues", {}, token)
        if leagues_raw.get("data"):
            store_api_response(
                cache_key, leagues_raw, "cricket", league_key, "leagues",
                ttl_hours=48.0, db_path=db,
            )

    SEARCH_TERMS: dict[str, list[str]] = {
        "sa20":         ["sa20", "sa 20", "south africa twenty", "mzansi super"],
        "test_cricket": ["test", "test championship", "test series"],
        "odi":          ["one day international", "odi", "world cup (one day)", "50 over"],
        "t20_world_cup": ["t20 world cup", "icc world twenty20", "twenty20 world cup"],
    }
    keywords = SEARCH_TERMS.get(league_key, [league_key.replace("_", " ")])

    for league in _paginate(leagues_raw):
        name_lower = (league.get("name") or "").lower()
        for kw in keywords:
            if kw.lower() in name_lower:
                lid = league.get("id")
                _LEAGUE_ID_DISCOVERY[league_key] = lid
                log.info("Discovered SportMonks league_id=%s for %s (%s)", lid, league_key, name_lower)
                return lid

    log.warning("Could not discover SportMonks league ID for %s", league_key)
    _LEAGUE_ID_DISCOVERY[league_key] = None
    return None


# ── Season Discovery ──────────────────────────────────────────────────────────


async def _get_current_season_id(
    session: aiohttp.ClientSession,
    token: str,
    league_id: int,
    db: str,
) -> int | None:
    """Return current active season ID for a league."""
    cache_key = f"sportmonks:seasons:{league_id}"
    seasons_raw = get_cached_api_response(cache_key, db_path=db)
    if not seasons_raw:
        seasons_raw = await _api_fetch(
            session, f"leagues/{league_id}", {"include": "seasons"}, token,
        )
        if seasons_raw.get("data"):
            store_api_response(
                cache_key, seasons_raw, "cricket", "", "seasons",
                ttl_hours=48.0, db_path=db,
            )

    league_data = seasons_raw.get("data", {})
    seasons = (league_data.get("seasons", {}).get("data") or []) if isinstance(league_data, dict) else []

    if not seasons:
        return None

    # Return the most recently started season
    active = [
        s for s in seasons
        if s.get("status") in ("Season finished", "Active", None)
    ]
    if not active:
        active = seasons

    # Sort by season start descending
    def _season_start(s: dict) -> datetime:
        raw = s.get("season_start") or ""
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            return datetime.min.replace(tzinfo=timezone.utc)

    active.sort(key=_season_start, reverse=True)
    return active[0].get("id")


# ── Data Extraction ───────────────────────────────────────────────────────────


def _extract_standings(standings_response: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Parse standings response → {team_name_lower: team_data}."""
    teams: dict[str, dict[str, Any]] = {}
    for entry in _paginate(standings_response):
        team = entry.get("team", {})
        if not team:
            # Standings rows may have team data at top level
            team = entry
        name = (team.get("name") or entry.get("team_name") or "").lower().strip()
        if not name:
            continue
        wins = int(entry.get("won") or 0)
        losses = int(entry.get("lost") or 0)
        draws = int(entry.get("draw") or 0)
        nr = int(entry.get("no_result") or 0)
        teams[name] = {
            "name": team.get("name", name),
            "position": entry.get("position"),
            "points": entry.get("points"),
            "games_played": int(entry.get("total") or 0),
            "matches_played": int(entry.get("total") or 0),
            "wins": wins,
            "losses": losses,
            "draws": draws,
            "no_result": nr,
            "record": f"W{wins} L{losses}" + (f" NR{nr}" if nr else ""),
            "nrr": entry.get("net_run_rate"),
            "form": entry.get("recent_form", ""),
        }
    return teams


def _extract_h2h(fixtures_response: dict[str, Any], home: str, away: str) -> list[dict[str, Any]]:
    """Filter fixtures for H2H between two teams → last 5 meetings."""
    home_lower = home.lower().strip()
    away_lower = away.lower().strip()
    meetings: list[dict[str, Any]] = []

    for fix in _paginate(fixtures_response):
        local = (fix.get("localteam", {}) or {}).get("name", "")
        visitor = (fix.get("visitorteam", {}) or {}).get("name", "")
        teams_lower = {local.lower(), visitor.lower()}
        if not ({home_lower, away_lower} & teams_lower):
            continue

        winner = (fix.get("winner_team_id") or 0)
        local_id = (fix.get("localteam", {}) or {}).get("id", 0)
        visitor_id = (fix.get("visitorteam", {}) or {}).get("id", 0)
        result_str = ""
        if winner == local_id:
            result_str = f"{local} won"
        elif winner == visitor_id:
            result_str = f"{visitor} won"
        else:
            result_str = "No result / tied"

        meetings.append({
            "date": fix.get("starting_at", ""),
            "home": local,
            "away": visitor,
            "venue": (fix.get("venue", {}) or {}).get("name", ""),
            "result": result_str,
            "format": fix.get("type", ""),
        })

    meetings.sort(key=lambda x: x.get("date") or "", reverse=True)
    return meetings[:5]


def _extract_squad(team_response: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract squad from team detail response → list of player dicts."""
    players = []
    squad_data = team_response.get("data", {})
    if isinstance(squad_data, dict):
        squad_data = squad_data.get("squad", {}).get("data", [])
    for p in squad_data or []:
        players.append({
            "id": p.get("id"),
            "name": p.get("fullname") or p.get("name", ""),
            "position": p.get("position", {}).get("name", "") if isinstance(p.get("position"), dict) else str(p.get("position", "")),
            "batting_style": p.get("battingstyle", ""),
            "bowling_style": p.get("bowlingstyle", ""),
        })
    return players


def _extract_player_stats(player_response: dict[str, Any]) -> dict[str, Any]:
    """Extract batting/bowling averages from player response."""
    p = player_response.get("data", {})
    if not isinstance(p, dict):
        return {}
    career = (p.get("career", {}) or {}).get("data", [])
    batting_avg = None
    bowling_avg = None
    for stint in career or []:
        if stint.get("type") == "Total":
            batting = (stint.get("batting", {}) or {})
            bowling = (stint.get("bowling", {}) or {})
            batting_avg = batting.get("average")
            bowling_avg = bowling.get("average")
            break
    return {
        "name": p.get("fullname") or p.get("name", ""),
        "batting_average": batting_avg,
        "bowling_average": bowling_avg,
        "batting_style": p.get("battingstyle", ""),
        "bowling_style": p.get("bowlingstyle", ""),
    }


def _extract_match_detail(detail_response: dict[str, Any]) -> dict[str, Any]:
    """Extract match detail including scoreboards for Test/ODI multi-innings."""
    fix = detail_response.get("data", {})
    if not isinstance(fix, dict):
        return {}

    batting = (fix.get("batting", {}) or {}).get("data", [])
    bowling = (fix.get("bowling", {}) or {}).get("data", [])
    scoreboards = (fix.get("scoreboards", {}) or {}).get("data", [])

    # Group by innings
    innings: list[dict[str, Any]] = []
    for sb in scoreboards or []:
        inning_no = sb.get("scoreboard", "").replace("1st Innings", "1").replace("2nd Innings", "2")
        team_id = sb.get("team_id")
        innings.append({
            "innings": inning_no,
            "team_id": team_id,
            "runs": sb.get("total"),
            "wickets": sb.get("wickets"),
            "overs": sb.get("overs"),
        })

    # Top batsmen
    top_batsmen = sorted(
        [b for b in batting if b.get("score") is not None],
        key=lambda b: int(b.get("score") or 0),
        reverse=True,
    )[:3]

    # Top bowlers (by wickets)
    top_bowlers = sorted(
        [b for b in bowling if b.get("wickets") is not None],
        key=lambda b: int(b.get("wickets") or 0),
        reverse=True,
    )[:3]

    return {
        "innings": innings,
        "top_batsmen": top_batsmen,
        "top_bowlers": top_bowlers,
        "toss_won": (fix.get("tosswon", {}) or {}).get("name", ""),
        "venue": (fix.get("venue", {}) or {}).get("name", ""),
        "note": fix.get("note", ""),
    }


def _match_team_in_standings(
    team_name: str,
    standings: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    """Fuzzy-match a team name against standings keys."""
    normalised = team_name.lower().strip().replace("_", " ")
    if normalised in standings:
        return standings[normalised]
    for key, data in standings.items():
        if normalised in key or key in normalised:
            return data
    return None


# ── Elo Integration ──────────────────────────────────────────────────────────


def _get_elo_ratings(
    home_team: str,
    away_team: str,
    db_path: str | None = None,
) -> tuple[float | None, float | None]:
    """Fetch Elo/Glicko-2 ratings from DB if available for cricket."""
    conn = get_connection(db_path or DB_PATH, readonly=True)
    try:
        home_elo = None
        away_elo = None
        for team, setter in [(home_team, "home"), (away_team, "away")]:
            normalised = team.lower().strip().replace("_", " ")
            row = conn.execute(
                """SELECT rating FROM elo_ratings
                   WHERE LOWER(team) = ? AND sport = 'cricket'
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


class CricketFetcher(BaseFetcher):
    """SportMonks Cricket API v2 fetcher for cricket."""

    sport = "cricket"

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
        """Fetch cricket context from SportMonks with caching and fallback."""
        db = db_path or DB_PATH
        token = _get_api_token()
        confidence: dict[str, float] = {}
        sources: dict[str, str] = {}

        if not token:
            log.warning("No SPORTMONKS_CRICKET_TOKEN — returning empty context")
            return self._empty_fallback(home_team, away_team, league)

        league_cfg = LEAGUE_CONFIG.get(league, {})
        display_name = league_cfg.get("display") or league.replace("_", " ").title()

        home_data: dict[str, Any] = {"name": home_team}
        away_data: dict[str, Any] = {"name": away_team}
        h2h_list: list[dict] = []
        standings_data: dict[str, dict] = {}
        venue = ""
        format_str = _infer_format(league)

        async with aiohttp.ClientSession() as session:
            # ── Resolve league ID ──────────────────────────────────────────
            league_id = league_cfg.get("league_id")
            if league_id is None:
                league_id = await _discover_league_id(session, token, league, db)

            # ── Tier A: Fixtures for date range + H2H (cached 12h) ────────
            today = datetime.now(timezone.utc).date()
            date1 = today.isoformat()
            date2 = (today + timedelta(days=14)).isoformat()
            fix_cache_key = f"sportmonks:fixtures:{date1}:{date2}"
            fixtures_raw = get_cached_api_response(fix_cache_key, db_path=db)

            if not fixtures_raw:
                fixtures_raw = await _api_fetch(
                    session,
                    "fixtures",
                    {
                        "filter[starts_between]": f"{date1},{date2}",
                        "include": "localteam,visitorteam,league,venue,tosswon,batting",
                    },
                    token,
                )
                if fixtures_raw.get("data"):
                    store_api_response(
                        fix_cache_key, fixtures_raw,
                        "cricket", league, "fixtures",
                        ttl_hours=12.0, db_path=db,
                    )

            h2h_list = _extract_h2h(fixtures_raw, home_team, away_team)
            if h2h_list:
                confidence["h2h"] = 0.9
                sources["h2h"] = "sportmonks"

            # ── Venue from upcoming fixture ────────────────────────────────
            home_lower = home_team.lower()
            away_lower = away_team.lower()
            for fix in _paginate(fixtures_raw):
                local = (fix.get("localteam", {}) or {}).get("name", "").lower()
                visitor = (fix.get("visitorteam", {}) or {}).get("name", "").lower()
                if (home_lower in local or local in home_lower) and (away_lower in visitor or visitor in away_lower):
                    venue = (fix.get("venue", {}) or {}).get("name", "") or venue
                    break

            # ── Tier A: Standings (league + season, cached 12h) ───────────
            if league_id:
                season_id = league_cfg.get("season") or await _get_current_season_id(
                    session, token, league_id, db,
                )
                if season_id:
                    stand_cache_key = f"sportmonks:standings:{season_id}"
                    standings_raw = get_cached_api_response(stand_cache_key, db_path=db)
                    if not standings_raw:
                        standings_raw = await _api_fetch(
                            session,
                            f"standings/season/{season_id}",
                            {},
                            token,
                        )
                        if standings_raw.get("data"):
                            store_api_response(
                                stand_cache_key, standings_raw,
                                "cricket", league, "standings",
                                ttl_hours=12.0, db_path=db,
                            )

                    standings_data = _extract_standings(standings_raw)
                    home_standing = _match_team_in_standings(home_team, standings_data)
                    away_standing = _match_team_in_standings(away_team, standings_data)
                    if home_standing:
                        home_data.update(home_standing)
                        confidence["home_standings"] = 0.9
                        sources["home_standings"] = "sportmonks"
                    if away_standing:
                        away_data.update(away_standing)
                        confidence["away_standings"] = 0.9
                        sources["away_standings"] = "sportmonks"

            # ── Tier B: Match detail (near horizon, cached 6h) ────────────
            from fetchers.base_fetcher import horizon_bucket
            bucket = horizon_bucket(horizon_hours)

            if bucket in ("near", "mid"):
                # Find the specific fixture ID for this match
                fix_id = None
                for fix in _paginate(fixtures_raw):
                    local = (fix.get("localteam", {}) or {}).get("name", "").lower()
                    visitor = (fix.get("visitorteam", {}) or {}).get("name", "").lower()
                    if (home_lower in local or local in home_lower) and (away_lower in visitor or visitor in away_lower):
                        fix_id = fix.get("id")
                        break

                if fix_id:
                    detail_cache_key = f"sportmonks:fixture_detail:{fix_id}"
                    detail_raw = get_cached_api_response(detail_cache_key, db_path=db)
                    if not detail_raw:
                        detail_raw = await _api_fetch(
                            session,
                            f"fixtures/{fix_id}",
                            {"include": "batting,bowling,lineup,scoreboards,tosswon"},
                            token,
                        )
                        if detail_raw.get("data"):
                            store_api_response(
                                detail_cache_key, detail_raw,
                                "cricket", league, "fixture_detail",
                                ttl_hours=6.0, db_path=db,
                            )

                    match_detail = _extract_match_detail(detail_raw)
                    if match_detail:
                        confidence["match_detail"] = 0.8
                        sources["match_detail"] = "sportmonks"
                        if match_detail.get("venue"):
                            venue = match_detail["venue"]
                        home_data["match_detail"] = match_detail

            # ── Injuries: SportMonks v2 doesn't have a dedicated injuries
            #    endpoint — graceful fallback, no data ─────────────────────
            home_data["injuries"] = []
            away_data["injuries"] = []

            # ── Player stats (top squad members, near horizon only) ───────
            if bucket == "near" and league_id:
                # Attempt to get squad for home team from fixtures
                for fix in _paginate(fixtures_raw):
                    local_id = (fix.get("localteam", {}) or {}).get("id")
                    local_name = (fix.get("localteam", {}) or {}).get("name", "").lower()
                    if home_lower in local_name or local_name in home_lower:
                        squad_cache_key = f"sportmonks:squad:{local_id}"
                        squad_raw = get_cached_api_response(squad_cache_key, db_path=db)
                        if not squad_raw and local_id:
                            squad_raw = await _api_fetch(
                                session,
                                f"teams/{local_id}",
                                {"include": "squad"},
                                token,
                            )
                            if squad_raw.get("data"):
                                store_api_response(
                                    squad_cache_key, squad_raw,
                                    "cricket", league, "squad",
                                    ttl_hours=24.0, db_path=db,
                                )
                        if squad_raw:
                            squad = _extract_squad(squad_raw)
                            home_data["squad"] = squad
                            # Fetch stats for first 2 players (capped to limit API calls)
                            player_stats: list[dict[str, Any]] = []
                            for player_entry in squad[:2]:
                                pid = player_entry.get("id")
                                if not pid:
                                    continue
                                ps_cache_key = f"sportmonks:player:{pid}"
                                ps_raw = get_cached_api_response(ps_cache_key, db_path=db)
                                if not ps_raw:
                                    ps_raw = await _api_fetch(
                                        session,
                                        f"players/{pid}",
                                        {"include": "career"},
                                        token,
                                    )
                                    if ps_raw.get("data"):
                                        store_api_response(
                                            ps_cache_key, ps_raw,
                                            "cricket", league, "player_stats",
                                            ttl_hours=24.0, db_path=db,
                                        )
                                if ps_raw:
                                    stats = _extract_player_stats(ps_raw)
                                    if stats.get("name"):
                                        player_stats.append(stats)
                            if player_stats:
                                home_data["player_stats"] = player_stats
                                confidence["home_player_stats"] = 0.7
                                sources["home_player_stats"] = "sportmonks"
                        break

        # ── Elo ratings ───────────────────────────────────────────────────
        home_elo, away_elo = _get_elo_ratings(home_team, away_team, db_path=db)

        # ── Assemble context dict (ESPN-compatible format) ────────────────
        context: dict[str, Any] = {
            "data_available": bool(
                home_data.get("position") is not None
                or away_data.get("position") is not None
                or h2h_list
            ),
            "data_freshness": datetime.now(timezone.utc).isoformat(),
            "data_source": "sportmonks",
            "home_team": home_data,
            "away_team": away_data,
            "h2h": h2h_list,
            "competition": display_name,
            "format": format_str,
            "venue": venue,
            "season": "",
            "standings": standings_data,
        }

        if home_elo is not None:
            context["elo_home"] = home_elo
            confidence["elo_home"] = 1.0
            sources["elo_home"] = "elo_engine"
        if away_elo is not None:
            context["elo_away"] = away_elo
            confidence["elo_away"] = 1.0
            sources["elo_away"] = "elo_engine"

        return FetchResult(
            context=context,
            confidence=confidence,
            sources=sources,
        )

    def _empty_fallback(
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
                "format": _infer_format(league),
                "venue": "",
            },
            confidence={},
            sources={},
        )


def _infer_format(league: str) -> str:
    """Infer cricket format from league key."""
    league_lower = league.lower()
    if "test" in league_lower:
        return "Test"
    if "odi" in league_lower or "one_day" in league_lower:
        return "ODI"
    return "T20"
