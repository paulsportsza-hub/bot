"""API-Sports MMA fetcher — structured context for MMA/boxing matches.

Free tier: 100 requests/day.  Date window restriction on free plan.
API base: https://v1.mma.api-sports.io
Auth: x-apisports-key header (same key as API-Football).

Free tier note: /fights?date= only works for a narrow recent window
(~3 days). Upcoming bouts beyond that window require paid plan.
This fetcher attempts best-effort retrieval; gracefully returns empty
context when data is unavailable, letting ESPN fallback handle it.

Endpoints used:
  - /fights?date=YYYY-MM-DD  (fights on a given date)
  - /fighters?id={id}        (fighter profile/record)
"""

from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
from datetime import datetime, timezone, date, timedelta
from typing import Any

import aiohttp

from fetchers.base_fetcher import (
    BaseFetcher,
    FetchResult,
    get_cached_api_response,
    store_api_response,
    DB_PATH,
)

log = logging.getLogger("mzansi.fetchers.mma")

API_MMA_BASE = "https://v1.mma.api-sports.io"
REQUEST_TIMEOUT = 15

# Path to scrapers' odds.db (contains mma_fixtures table)
_BOT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCRAPERS_DB: str = os.path.join(
    os.environ.get("SCRAPERS_ROOT", os.path.join(os.path.dirname(_BOT_ROOT), "scrapers")),
    "odds.db",
)

# Daily budget tracking (in-memory, resets at UTC midnight)
_budget: dict[str, int] = {}
_budget_date: dict[str, str] = {}
DAILY_BUDGET = 90  # stay 10 under hard limit of 100


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
    today = date.today().isoformat()
    if _budget_date.get("mma") != today:
        _budget["mma"] = 0
        _budget_date["mma"] = today
    return _budget.get("mma", 0) < DAILY_BUDGET


def _consume_budget(n: int = 1) -> None:
    today = date.today().isoformat()
    if _budget_date.get("mma") != today:
        _budget["mma"] = 0
        _budget_date["mma"] = today
    _budget["mma"] = _budget.get("mma", 0) + n


async def _api_fetch(
    session: aiohttp.ClientSession,
    endpoint: str,
    params: dict[str, Any],
    api_key: str,
) -> dict[str, Any]:
    url = f"{API_MMA_BASE}/{endpoint}"
    headers = {"x-apisports-key": api_key}
    try:
        async with session.get(
            url, headers=headers, params=params,
            timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
        ) as resp:
            if resp.status != 200:
                log.warning("MMA API %s returned %d", endpoint, resp.status)
                return {}
            data = await resp.json()
            _consume_budget()
            remaining = resp.headers.get("x-ratelimit-requests-remaining", "?")
            log.info(
                "MMA API %s: %d results, %s daily calls remaining",
                endpoint, data.get("results", 0), remaining,
            )
            return data
    except Exception as exc:
        log.warning("MMA API %s failed: %s", endpoint, exc)
        return {}


# ── Data Extraction ────────────────────────────────────────────────────────────

def _normalise_fighter_name(name: str) -> str:
    return name.lower().strip().replace("_", " ")


def _fighter_names_match(api_name: str, search_name: str) -> bool:
    """Check if API fighter name matches search name."""
    api_n = _normalise_fighter_name(api_name)
    search_n = _normalise_fighter_name(search_name)
    if api_n == search_n:
        return True
    # Partial match: all words of search found in api name (or vice versa)
    search_words = set(search_n.split())
    api_words = set(api_n.split())
    if len(search_words) >= 2 and search_words.issubset(api_words):
        return True
    if len(api_words) >= 2 and api_words.issubset(search_words):
        return True
    # Last name match for well-known single-name references
    if len(search_words) == 1:
        return search_n in api_words
    return False


def _extract_fighter_from_fight(
    fight: dict[str, Any],
    fighter_name: str,
    is_home: bool = False,  # noqa: ARG001
) -> dict[str, Any] | None:
    """Extract fighter data from a fight record."""
    fighters = fight.get("fighters", {})
    home = fighters.get("home", {})
    away = fighters.get("away", {})

    for fighter in (home, away):
        name = fighter.get("name", "")
        if _fighter_names_match(name, fighter_name):
            return {
                "name": name,
                "api_id": fighter.get("id"),
                "wins": fighter.get("wins"),
                "losses": fighter.get("losses"),
                "draws": fighter.get("draws"),
            }
    return None


def _build_fighter_record_str(wins: Any, losses: Any, draws: Any) -> str:
    w = int(wins or 0)
    l = int(losses or 0)
    d = int(draws or 0)
    return f"W{w} D{d} L{l}"


def _extract_recent_fights(
    fights: list[dict[str, Any]],
    fighter_name: str,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Extract recent fight results for a fighter."""
    results = []
    for fight in sorted(fights, key=lambda x: x.get("date", ""), reverse=True):
        if fight.get("status", {}).get("short") not in ("FT", "Finished", "Fin"):
            continue
        fighters = fight.get("fighters", {})
        home = fighters.get("home", {})
        away = fighters.get("away", {})

        home_name = home.get("name", "")
        away_name = away.get("name", "")
        if not _fighter_names_match(home_name, fighter_name) and \
           not _fighter_names_match(away_name, fighter_name):
            continue

        result = fight.get("result", {})
        winner = result.get("winner", {}).get("name", "") if isinstance(result.get("winner"), dict) else ""
        method = result.get("method", "")

        results.append({
            "date": fight.get("date", ""),
            "opponent": away_name if _fighter_names_match(home_name, fighter_name) else home_name,
            "result": "W" if _fighter_names_match(winner, fighter_name) else "L",
            "method": method,
        })
        if len(results) >= limit:
            break
    return results


# ── DB Fixture Lookup ──────────────────────────────────────────────────────────

def _query_mma_fixture(home_team: str, away_team: str) -> dict[str, Any] | None:
    """Query mma_fixtures for an upcoming fight matching the given fighters.

    Synchronous — must be called via asyncio.to_thread() in async contexts (RUNTIME-R2).
    Uses connect_odds_db_readonly (W81-DBLOCK). Returns None on no match or error.
    """
    try:
        from scrapers.db_connect import connect_odds_db_readonly
        conn = connect_odds_db_readonly(_SCRAPERS_DB, timeout=1.0)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                """SELECT fighter1_name, fighter1_api_id,
                          fighter2_name, fighter2_api_id,
                          event_slug, fight_date, weight_class
                   FROM mma_fixtures
                   WHERE fight_date >= date('now')
                   AND status NOT IN ('Cancelled', 'Postponed')
                   ORDER BY fight_date ASC""",
            ).fetchall()
        finally:
            conn.close()
    except Exception as exc:
        log.debug("mma_fixtures DB lookup error: %s", exc)
        return None

    for row in rows:
        f1: str = row["fighter1_name"]
        f2: str = row["fighter2_name"]
        # Direct match: home_team == fighter1, away_team == fighter2
        if _fighter_names_match(f1, home_team) and _fighter_names_match(f2, away_team):
            return {
                "fighter1_name": f1,
                "fighter1_api_id": row["fighter1_api_id"],
                "fighter2_name": f2,
                "fighter2_api_id": row["fighter2_api_id"],
                "competition": row["event_slug"] or "MMA",
                "fight_date": row["fight_date"],
                "weight_class": row["weight_class"] or "",
            }
        # Swapped match: home_team == fighter2, away_team == fighter1
        if _fighter_names_match(f2, home_team) and _fighter_names_match(f1, away_team):
            return {
                "fighter1_name": f2,
                "fighter1_api_id": row["fighter2_api_id"],
                "fighter2_name": f1,
                "fighter2_api_id": row["fighter1_api_id"],
                "competition": row["event_slug"] or "MMA",
                "fight_date": row["fight_date"],
                "weight_class": row["weight_class"] or "",
            }
    return None


def _query_mma_fighters(fighter_api_id: int, db_path: str) -> dict[str, Any] | None:
    """Look up a fighter's record data from the mma_fighters table.

    Synchronous — must be called via asyncio.to_thread() in async contexts (RUNTIME-R2).
    Uses connect_odds_db_readonly (W81-DBLOCK). Returns None on no match or error.
    """
    try:
        from scrapers.db_connect import connect_odds_db_readonly
        conn = connect_odds_db_readonly(db_path, timeout=1.0)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                """SELECT api_id, name, record_wins, record_losses, record_draws,
                          reach, stance, weight_class, ranking
                   FROM mma_fighters
                   WHERE api_id = ?""",
                (fighter_api_id,),
            ).fetchone()
        finally:
            conn.close()
    except Exception as exc:
        log.debug("mma_fighters DB lookup error for id %d: %s", fighter_api_id, exc)
        return None

    if not row:
        return None
    return dict(row)


def _format_record_str(wins: Any, losses: Any, draws: Any) -> str:
    """Format a fighter record as 'W-L-D' string (e.g. '25-4-0')."""
    w = int(wins or 0)
    l_ = int(losses or 0)
    d = int(draws or 0)
    return f"{w}-{l_}-{d}"


# ── Main Fetcher ───────────────────────────────────────────────────────────────

class MMAFetcher(BaseFetcher):
    """API-Sports MMA fetcher for MMA and boxing matches.

    Note: Free tier restricts date range to a narrow window (~3 days).
    Upcoming fights outside this window will return empty context,
    falling through to ESPN fallback gracefully.
    """

    sport = "mma"

    async def fetch_context(
        self,
        home_team: str,
        away_team: str,
        league: str,  # noqa: ARG002
        horizon_hours: float = 168.0,  # noqa: ARG002
        *,
        live_safe: bool = True,  # noqa: ARG002
        db_path: str | None = None,
    ) -> FetchResult:
        db = db_path or DB_PATH
        api_key = _get_api_key()
        confidence: dict[str, float] = {}
        sources: dict[str, str] = {}

        # ── Step 1: Query mma_fixtures DB (W81-DBLOCK + RUNTIME-R2) ───────────
        db_fixture: dict[str, Any] | None = None
        try:
            db_fixture = await asyncio.wait_for(
                asyncio.to_thread(lambda: _query_mma_fixture(home_team, away_team)),
                timeout=3.0,
            )
        except Exception as exc:
            log.debug("mma_fixtures DB lookup failed: %s", exc)

        db_fixture_found = db_fixture is not None

        # Initialise fighter dicts — use DB names when available
        if db_fixture:
            fighter1_data: dict[str, Any] = {"name": db_fixture["fighter1_name"]}
            fighter2_data: dict[str, Any] = {"name": db_fixture["fighter2_name"]}
            competition: str = db_fixture["competition"]
            weight_class: str = db_fixture["weight_class"]
            log.info(
                "MMA fixture found in DB: %s vs %s (%s)",
                db_fixture["fighter1_name"], db_fixture["fighter2_name"], competition,
            )
        else:
            fighter1_data = {"name": home_team}
            fighter2_data = {"name": away_team}
            competition = "MMA"
            weight_class = ""

        # ── Step 1b: mma_fighters DB lookup (W81-DBLOCK + RUNTIME-R2) ───────────
        # Read cached fighter records (wins/losses/draws/ranking) written by the
        # api_sports_mma.py cron scraper.  Zero live API calls here.
        if db_fixture:
            f1_api_id = db_fixture.get("fighter1_api_id")
            f2_api_id = db_fixture.get("fighter2_api_id")
            for fighter_data, api_id in (
                (fighter1_data, f1_api_id),
                (fighter2_data, f2_api_id),
            ):
                if not api_id:
                    continue
                try:
                    record_row = await asyncio.wait_for(
                        asyncio.to_thread(
                            lambda _aid=api_id: _query_mma_fighters(_aid, _SCRAPERS_DB)
                        ),
                        timeout=3.0,
                    )
                except Exception as exc:
                    log.debug("mma_fighters lookup failed for api_id %s: %s", api_id, exc)
                    record_row = None

                if record_row:
                    fighter_data["form"] = _format_record_str(
                        record_row.get("record_wins"),
                        record_row.get("record_losses"),
                        record_row.get("record_draws"),
                    )
                    fighter_data["position"] = record_row.get("ranking")
                    if record_row.get("reach"):
                        fighter_data["reach"] = record_row["reach"]
                    if record_row.get("stance"):
                        fighter_data["stance"] = record_row["stance"]
                    # Propagate weight_class if not already set from fixtures
                    if not weight_class and record_row.get("weight_class"):
                        weight_class = record_row["weight_class"]
                    confidence[f"fighter{1 if fighter_data is fighter1_data else 2}_record"] = 0.95
                    sources[f"fighter{1 if fighter_data is fighter1_data else 2}_record"] = "mma_fighters_db"
                    log.info(
                        "MMA fighter record (DB): %s — %s, rank=%s",
                        fighter_data["name"],
                        fighter_data.get("form"),
                        fighter_data.get("position"),
                    )

        # ── Step 2: API enrichment (fighter records) ──────────────────────────
        all_fights: list[dict[str, Any]] = []
        if not api_key:
            log.warning("No API key — MMA fetcher API unavailable")
        elif not _check_budget():
            log.warning("MMA API daily budget exhausted — skipping API enrichment")
        else:
            all_fights = await self._fetch_fight_window(api_key, db)

        if all_fights:
            for fight in all_fights:
                f1 = _extract_fighter_from_fight(fight, home_team, is_home=True)
                if f1 and f1.get("api_id") and not fighter1_data.get("api_id"):
                    fighter1_data.update(f1)
                f2 = _extract_fighter_from_fight(fight, away_team, is_home=False)
                if f2 and f2.get("api_id") and not fighter2_data.get("api_id"):
                    fighter2_data.update(f2)

            if fighter1_data.get("wins") is not None:
                fighter1_data["record"] = _build_fighter_record_str(
                    fighter1_data.get("wins"),
                    fighter1_data.get("losses"),
                    fighter1_data.get("draws"),
                )
                fighter1_data["recent_fights"] = _extract_recent_fights(all_fights, home_team)
                confidence["fighter1_record"] = 0.9
                sources["fighter1_record"] = "api-sports-mma"

            if fighter2_data.get("wins") is not None:
                fighter2_data["record"] = _build_fighter_record_str(
                    fighter2_data.get("wins"),
                    fighter2_data.get("losses"),
                    fighter2_data.get("draws"),
                )
                fighter2_data["recent_fights"] = _extract_recent_fights(all_fights, away_team)
                confidence["fighter2_record"] = 0.9
                sources["fighter2_record"] = "api-sports-mma"

            # Update weight_class from API if not already populated from DB
            if not weight_class:
                for fight in all_fights:
                    fighters = fight.get("fighters", {})
                    home_name = fighters.get("home", {}).get("name", "")
                    away_name = fighters.get("away", {}).get("name", "")
                    if (
                        _fighter_names_match(home_name, home_team)
                        or _fighter_names_match(away_name, home_team)
                        or _fighter_names_match(home_name, away_team)
                        or _fighter_names_match(away_name, away_team)
                    ):
                        weight_class = fight.get("weight", {}).get("category", "") or ""
                        if weight_class:
                            break

        # ── Step 3: Build context ─────────────────────────────────────────────
        data_available = db_fixture_found or bool(
            fighter1_data.get("record") or fighter2_data.get("record")
        )

        context: dict[str, Any] = {
            "data_available": data_available,
            "data_freshness": datetime.now(timezone.utc).isoformat(),
            "data_source": "mma_fixtures_db" if db_fixture_found else "api-sports-mma",
            "home_team": fighter1_data,
            "away_team": fighter2_data,
            "h2h": [],
            "competition": competition,
            "season": "",
            "weight_class": weight_class,
        }

        return FetchResult(context=context, confidence=confidence, sources=sources)

    async def _fetch_fight_window(
        self,
        api_key: str,
        db: str,
        days_back: int = 3,
        days_forward: int = 7,
    ) -> list[dict[str, Any]]:
        """Fetch fights over a date window. Returns all fight objects found."""
        all_fights: list[dict[str, Any]] = []
        today = date.today()

        async with aiohttp.ClientSession() as session:
            for delta in range(-days_back, days_forward + 1):
                if not _check_budget():
                    break
                target = today + timedelta(days=delta)
                date_str = target.isoformat()

                cache_key = f"apim:fights:{date_str}"
                cached = get_cached_api_response(cache_key, db_path=db)
                if cached is not None:
                    all_fights.extend(cached.get("fights", []))
                    continue

                data = await _api_fetch(session, "fights", {"date": date_str}, api_key)
                errors = data.get("errors", {})
                if errors and "plan" in str(errors):
                    # Date outside free tier window — skip silently
                    log.debug("MMA API date %s outside free tier window", date_str)
                    continue

                fights = data.get("response", [])
                store_api_response(
                    cache_key, {"fights": fights},
                    "mma", "all", "fights",
                    ttl_hours=6.0, db_path=db,
                )
                all_fights.extend(fights)

        return all_fights

    def _empty_fallback(
        self,
        home_team: str,
        away_team: str,
    ) -> FetchResult:
        return FetchResult(
            context={
                "data_available": False,
                "data_source": "none",
                "home_team": {"name": home_team},
                "away_team": {"name": away_team},
                "h2h": [],
                "competition": "MMA",
                "season": "",
                "weight_class": "",
            },
            confidence={},
            sources={},
        )
