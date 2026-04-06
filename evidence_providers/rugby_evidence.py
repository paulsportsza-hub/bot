"""API-Sports Rugby adapter implementing EvidenceProvider.

This provider supplements ESPN's rugby context with:
  - head-to-head summaries
  - venue-specific home record
  - per-team try rates when the upstream statistics payload exposes them

It intentionally does NOT duplicate standings, coaches, or key-player data that
already comes from the ESPN path.
"""

from __future__ import annotations

import asyncio
import difflib
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

import aiohttp

from evidence_providers.base import SportEvidence

log = logging.getLogger("mzansi.rugby_evidence")

_API_BASE = "https://v1.rugby.api-sports.io"
_API_HOST = "v1.rugby.api-sports.io"
_API_TIMEOUT_S = 3
_CACHE_TTL_S = 900

_CACHE: dict[str, tuple[SportEvidence, float]] = {}


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalise(name: str) -> str:
    return (
        name.lower()
        .replace("-", " ")
        .replace("_", " ")
        .replace("&", "and")
        .strip()
    )


def _extract_response(body: dict[str, Any]) -> Any:
    response = body.get("response")
    if response is None:
        return body.get("data")
    return response


def _first_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                return item
    return {}


def _safe_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None


def _safe_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _nested_get(data: dict[str, Any], *path: str) -> Any:
    current: Any = data
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _pick_number(data: dict[str, Any], paths: list[tuple[str, ...]]) -> float | None:
    for path in paths:
        value = _safe_float(_nested_get(data, *path))
        if value is not None:
            return value
    return None


def _record_string(block: dict[str, Any]) -> str:
    wins = _safe_int(block.get("wins")) or 0
    draws = _safe_int(block.get("draws")) or 0
    losses = _safe_int(block.get("loses"))
    if losses is None:
        losses = _safe_int(block.get("losses"))
    losses = losses or 0
    return f"W{wins} D{draws} L{losses}"


def _team_name_candidates(team_block: dict[str, Any]) -> list[str]:
    candidates = [
        team_block.get("name"),
        team_block.get("team", {}).get("name") if isinstance(team_block.get("team"), dict) else None,
    ]
    return [_normalise(name) for name in candidates if isinstance(name, str) and name.strip()]


def _best_team_id(response: Any, team_name: str) -> int | None:
    target = _normalise(team_name)
    items = response if isinstance(response, list) else [response]
    best_id: int | None = None
    best_score = 0.0

    for item in items:
        if not isinstance(item, dict):
            continue
        team_block = item.get("team") if isinstance(item.get("team"), dict) else item
        if not isinstance(team_block, dict):
            continue
        team_id = _safe_int(team_block.get("id"))
        if team_id is None:
            continue

        for candidate in _team_name_candidates(item):
            if candidate == target:
                return team_id
            if target in candidate or candidate in target:
                if best_score < 0.95:
                    best_id = team_id
                    best_score = 0.95
            else:
                score = difflib.SequenceMatcher(None, target, candidate).ratio()
                if score > best_score:
                    best_id = team_id
                    best_score = score

    if best_score >= 0.72:
        return best_id
    return None


def _extract_fixture_teams(fixture: dict[str, Any]) -> tuple[int | None, int | None]:
    teams = fixture.get("teams", {})
    home_id = _safe_int(_nested_get(teams, "home", "id"))
    away_id = _safe_int(_nested_get(teams, "away", "id"))
    return home_id, away_id


def _extract_fixture_scores(fixture: dict[str, Any]) -> tuple[int | None, int | None]:
    home_score = _safe_int(_nested_get(fixture, "scores", "home"))
    away_score = _safe_int(_nested_get(fixture, "scores", "away"))
    if home_score is None or away_score is None:
        home_score = _safe_int(_nested_get(fixture, "goals", "home"))
        away_score = _safe_int(_nested_get(fixture, "goals", "away"))
    if home_score is None or away_score is None:
        home_score = _safe_int(_nested_get(fixture, "points", "home"))
        away_score = _safe_int(_nested_get(fixture, "points", "away"))
    return home_score, away_score


def _extract_h2h_summary(
    fixtures: list[dict[str, Any]],
    home_id: int,
    away_id: int,
) -> dict[str, Any]:
    total_meetings = 0
    home_wins = 0
    away_wins = 0
    total_points = 0
    counted_points = 0
    latest_venue = ""

    for fixture in fixtures:
        fix = fixture.get("fixture", {}) if isinstance(fixture.get("fixture"), dict) else fixture
        fixture_home_id, fixture_away_id = _extract_fixture_teams(fixture)
        home_score, away_score = _extract_fixture_scores(fixture)

        if home_score is None or away_score is None:
            continue

        total_meetings += 1
        total_points += home_score + away_score
        counted_points += 1

        if not latest_venue:
            latest_venue = _nested_get(fix, "venue", "name") or fixture.get("venue", "") or ""

        if home_score == away_score:
            continue

        winner_id = fixture_home_id if home_score > away_score else fixture_away_id
        if winner_id == home_id:
            home_wins += 1
        elif winner_id == away_id:
            away_wins += 1

    if total_meetings == 0:
        return {}

    avg_total_points = round(total_points / counted_points, 1) if counted_points else None
    result = {
        "total_meetings": total_meetings,
        "home_wins": home_wins,
        "away_wins": away_wins,
    }
    if avg_total_points is not None:
        result["avg_total_points"] = avg_total_points
    if latest_venue:
        result["latest_venue"] = latest_venue
    return result


def _extract_try_stats(team_stats: dict[str, Any]) -> dict[str, Any]:
    tries_for = _pick_number(
        team_stats,
        [
            ("total", "tries", "for"),
            ("total", "tries", "scored"),
            ("tries", "for"),
            ("tries", "scored"),
            ("attack", "tries_for"),
        ],
    )
    tries_against = _pick_number(
        team_stats,
        [
            ("total", "tries", "against"),
            ("total", "tries", "received"),
            ("tries", "against"),
            ("tries", "received"),
            ("defence", "tries_against"),
        ],
    )
    games_played = _pick_number(
        team_stats,
        [
            ("total", "games", "played"),
            ("games", "played"),
            ("played",),
        ],
    )

    if tries_for is None and tries_against is None:
        return {}

    result: dict[str, Any] = {}
    if tries_for is not None:
        result["tries_for"] = int(tries_for) if tries_for.is_integer() else round(tries_for, 1)
    if tries_against is not None:
        result["tries_against"] = int(tries_against) if tries_against.is_integer() else round(tries_against, 1)
    if games_played and tries_for is not None:
        result["avg_per_game"] = round(tries_for / games_played, 1)
    return result


def _extract_venue_stats(team_stats: dict[str, Any], fallback_venue: str) -> dict[str, Any]:
    home_block = _first_dict(team_stats.get("home"))
    if not home_block:
        return {}

    games_played = _pick_number(home_block, [("games", "played"), ("played",)])
    points_scored = _pick_number(
        home_block,
        [
            ("points", "scored"),
            ("points", "for"),
            ("scores", "for"),
        ],
    )

    result: dict[str, Any] = {
        "home_record": _record_string(home_block),
    }
    if fallback_venue:
        result["venue"] = fallback_venue
    if games_played and points_scored is not None:
        result["avg_home_score"] = round(points_scored / games_played, 1)
    return result


class RugbyEvidenceProvider:
    """API-Sports Rugby adapter."""

    async def fetch_evidence(
        self, match_key: str, home: str, away: str
    ) -> SportEvidence:
        now = time.monotonic()
        if match_key in _CACHE:
            cached_ev, ts = _CACHE[match_key]
            if now - ts < _CACHE_TTL_S:
                return cached_ev

        api_key = os.getenv("API_SPORTS_KEY", "")
        if not api_key:
            ev = SportEvidence(
                sport="rugby",
                available=False,
                source_name="api-sports-rugby",
                error="API_SPORTS_KEY not set",
            )
            _CACHE[match_key] = (ev, now)
            return ev

        try:
            ev = await self._do_fetch(api_key, home, away)
        except asyncio.TimeoutError:
            ev = SportEvidence(
                sport="rugby",
                available=False,
                source_name="api-sports-rugby",
                error="fetch timeout",
            )
        except aiohttp.ClientResponseError as exc:
            if exc.status == 429:
                error = "rate limited (429)"
            else:
                error = f"HTTP {exc.status}"
            ev = SportEvidence(
                sport="rugby",
                available=False,
                source_name="api-sports-rugby",
                error=error,
            )
        except Exception as exc:
            ev = SportEvidence(
                sport="rugby",
                available=False,
                source_name="api-sports-rugby",
                error=str(exc),
            )

        # Count the live API call against the shared api_sports pool.
        try:
            from evidence_providers import rate_monitor
            rate_monitor.record_call("api_sports")
        except Exception:
            pass

        _CACHE[match_key] = (ev, now)
        return ev

    def format_for_prompt(self, evidence: SportEvidence) -> str:
        if not evidence.available or not evidence.data:
            return ""

        parts = ["[RUGBY CONTEXT]"]
        try_stats = evidence.data.get("try_stats", {})
        h2h = evidence.data.get("h2h", {})
        venue_stats = evidence.data.get("venue_stats", {})

        home_name = evidence.data.get("home_team", "Home")
        away_name = evidence.data.get("away_team", "Away")

        home_try = _first_dict(try_stats.get("home"))
        away_try = _first_dict(try_stats.get("away"))
        if home_try or away_try:
            fragments: list[str] = []
            if home_try:
                segment = f"{home_name} {home_try.get('avg_per_game', '?')} tries/game"
                if home_try.get("tries_against") is not None:
                    segment += f", {home_try['tries_against']} conceded"
                fragments.append(segment)
            if away_try:
                segment = f"{away_name} {away_try.get('avg_per_game', '?')} tries/game"
                if away_try.get("tries_against") is not None:
                    segment += f", {away_try['tries_against']} conceded"
                fragments.append(segment)
            if fragments:
                parts.append("Try profile: " + "; ".join(fragments) + ".")

        if h2h:
            sentence = (
                f"H2H: {h2h.get('total_meetings', 0)} meetings, "
                f"{home_name} won {h2h.get('home_wins', 0)}, "
                f"{away_name} won {h2h.get('away_wins', 0)}"
            )
            if h2h.get("avg_total_points") is not None:
                sentence += f", average total points {h2h['avg_total_points']}"
            parts.append(sentence + ".")

        if venue_stats:
            sentence = "Venue form: "
            if venue_stats.get("venue"):
                sentence += f"{venue_stats['venue']}; "
            sentence += venue_stats.get("home_record", "home record unavailable")
            if venue_stats.get("avg_home_score") is not None:
                sentence += f"; average home score {venue_stats['avg_home_score']}"
            parts.append(sentence + ".")

        if len(parts) == 1:
            return ""
        return "\n".join(parts)

    def contributes_key_facts(self, evidence: SportEvidence) -> int:
        if not evidence.available or not evidence.data:
            return 0
        count = 0
        if evidence.data.get("h2h"):
            count += 1
        if evidence.data.get("try_stats"):
            count += 1
        if evidence.data.get("venue_stats"):
            count += 1
        return min(count, 3)

    async def _do_fetch(
        self,
        api_key: str,
        home: str,
        away: str,
    ) -> SportEvidence:
        timeout = aiohttp.ClientTimeout(total=_API_TIMEOUT_S)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            home_id = await self._resolve_team_id(session, api_key, home)
            away_id = await self._resolve_team_id(session, api_key, away)

            if not home_id or not away_id:
                missing = home if not home_id else away
                return SportEvidence(
                    sport="rugby",
                    available=False,
                    source_name="api-sports-rugby",
                    error=f"Team not found: {missing}",
                )

            h2h_raw, home_stats_raw, away_stats_raw = await asyncio.gather(
                self._fetch_h2h(session, api_key, home_id, away_id),
                self._fetch_team_statistics(session, api_key, home_id),
                self._fetch_team_statistics(session, api_key, away_id),
            )

            h2h_fixtures = h2h_raw if isinstance(h2h_raw, list) else []
            h2h = _extract_h2h_summary(h2h_fixtures, home_id, away_id)

            home_stats = _first_dict(home_stats_raw)
            away_stats = _first_dict(away_stats_raw)
            try_stats: dict[str, Any] = {}
            if home_stats:
                home_try = _extract_try_stats(home_stats)
                if home_try:
                    try_stats["home"] = home_try
            if away_stats:
                away_try = _extract_try_stats(away_stats)
                if away_try:
                    try_stats["away"] = away_try

            venue_stats = _extract_venue_stats(home_stats, h2h.get("latest_venue", "")) if home_stats else {}

            data = {
                "home_team": home,
                "away_team": away,
                "h2h": h2h,
                "venue_stats": venue_stats,
                "try_stats": try_stats,
            }

            if not any((h2h, venue_stats, try_stats)):
                return SportEvidence(
                    sport="rugby",
                    available=False,
                    source_name="api-sports-rugby",
                    error="No supplementary rugby evidence returned",
                    data=data,
                )

            return SportEvidence(
                sport="rugby",
                available=True,
                source_name="api-sports-rugby",
                fetched_at=_utc_iso(),
                data=data,
            )

    async def _api_get(
        self,
        session: aiohttp.ClientSession,
        api_key: str,
        endpoint: str,
        params: dict[str, Any],
    ) -> Any:
        url = f"{_API_BASE}/{endpoint}"
        headers = {
            "x-rapidapi-key": api_key,
            "x-rapidapi-host": _API_HOST,
        }
        async with session.get(url, headers=headers, params=params) as resp:
            resp.raise_for_status()
            body = await resp.json()
        return _extract_response(body)

    async def _resolve_team_id(
        self,
        session: aiohttp.ClientSession,
        api_key: str,
        team_name: str,
    ) -> int | None:
        queries = (
            {"search": team_name},
            {"name": team_name},
        )
        for params in queries:
            try:
                response = await self._api_get(session, api_key, "teams", params)
            except aiohttp.ClientResponseError as exc:
                if exc.status == 404:
                    continue
                raise
            team_id = _best_team_id(response, team_name)
            if team_id is not None:
                return team_id
        return None

    async def _fetch_h2h(
        self,
        session: aiohttp.ClientSession,
        api_key: str,
        home_id: int,
        away_id: int,
    ) -> Any:
        response = await self._api_get(
            session,
            api_key,
            "fixtures/headtohead",
            {"h2h": f"{home_id}-{away_id}", "last": 10},
        )
        return response if isinstance(response, list) else []

    async def _fetch_team_statistics(
        self,
        session: aiohttp.ClientSession,
        api_key: str,
        team_id: int,
    ) -> Any:
        attempts = (
            {"id": team_id},
            {"team": team_id},
        )
        last_response: Any = []
        for params in attempts:
            try:
                response = await self._api_get(session, api_key, "teams/statistics", params)
            except aiohttp.ClientResponseError as exc:
                if exc.status in (400, 404):
                    continue
                raise
            last_response = response
            if response:
                return response
        return last_response
