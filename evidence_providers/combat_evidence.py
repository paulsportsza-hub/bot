"""Combat evidence adapter for MMA and boxing.

MMA uses API-Sports via RapidAPI.
Boxing uses Boxing-Data via RapidAPI.

The provider accepts an optional *sport* hint because evidence_pack already
knows whether the current fixture is MMA or boxing. That keeps dispatch
deterministic while preserving the shared EvidenceProvider contract.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

import aiohttp

from evidence_providers.base import SportEvidence

log = logging.getLogger("mzansi.combat_evidence")

_API_TIMEOUT_S = 3
_CACHE_TTL_S = 900

_MMA_API_BASE = "https://v1.mma.api-sports.io"
_MMA_API_HOST = "v1.mma.api-sports.io"
_BOXING_API_BASE = "https://boxing-data-api.p.rapidapi.com/v2"
_BOXING_API_HOST = "boxing-data-api.p.rapidapi.com"

_CACHE: dict[str, tuple[SportEvidence, float]] = {}


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalise(text: str) -> str:
    return " ".join(str(text or "").lower().replace("-", " ").replace("_", " ").split())


def _cache_key(match_key: str, sport: str) -> str:
    return f"{sport}:{match_key}"


def _pct(value: Any) -> str:
    if value in (None, ""):
        return ""
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return ""
    if numeric > 1:
        return f"{round(numeric, 1):g}%"
    return f"{round(numeric * 100, 1):g}%"


def _int_text(value: Any) -> str:
    if value in (None, ""):
        return ""
    try:
        return str(int(round(float(value))))
    except (TypeError, ValueError):
        return str(value)


def _clean_method(value: Any) -> str:
    method = str(value or "").strip()
    if not method:
        return ""
    return method.replace("_", " ")


class CombatEvidenceProvider:
    """Dual-source combat adapter with explicit MMA vs boxing dispatch."""

    async def fetch_evidence(
        self,
        match_key: str,
        home: str,
        away: str,
        sport: str | None = None,
    ) -> SportEvidence:
        requested_sport = self._resolve_sport(match_key, sport)
        now = time.monotonic()
        key = _cache_key(match_key, requested_sport)
        if key in _CACHE:
            cached_ev, ts = _CACHE[key]
            if now - ts < _CACHE_TTL_S:
                return cached_ev

        try:
            ev = await self._do_fetch(requested_sport, match_key, home, away)
        except asyncio.TimeoutError:
            ev = self._unavailable(requested_sport, "fetch timeout")
        except aiohttp.ClientResponseError as exc:
            if exc.status == 429:
                ev = self._unavailable(requested_sport, "rate limited (429)")
            else:
                ev = self._unavailable(requested_sport, f"HTTP {exc.status}")
        except Exception as exc:
            ev = self._unavailable(requested_sport, str(exc))

        # Count the live API call against the appropriate pool.
        try:
            from evidence_providers import rate_monitor
            if requested_sport == "mma":
                rate_monitor.record_call("api_sports")
            else:
                rate_monitor.record_call("boxing_data")
        except Exception:
            pass

        _CACHE[key] = (ev, now)
        return ev

    def format_for_prompt(self, evidence: SportEvidence) -> str:
        if not evidence.available or not evidence.data:
            return ""

        requested_sport = str(evidence.data.get("requested_sport") or evidence.sport or "").lower()
        profiles = evidence.data.get("fighter_profiles") or {}
        recent_fights = evidence.data.get("recent_fights") or {}
        title_implications = str(evidence.data.get("title_implications") or "").strip()

        if not profiles:
            return ""

        parts = ["[FIGHTER PROFILES]"]
        for side in ("home", "away"):
            profile = profiles.get(side) or {}
            name = str(profile.get("name") or side.title()).strip()
            segments: list[str] = []

            if requested_sport == "boxing":
                record = str(profile.get("record") or "").strip()
                if record:
                    segments.append(f"record {record}")
                ko_rate = _pct(profile.get("ko_rate"))
                if ko_rate:
                    segments.append(f"KO rate {ko_rate}")
                title_status = str(profile.get("title_status") or "").strip()
                if title_status:
                    segments.append(title_status)
            else:
                ko_rate = _pct(profile.get("ko_rate"))
                sub_rate = _pct(profile.get("sub_rate"))
                reach_cm = _int_text(profile.get("reach_cm"))
                ranking = _int_text(profile.get("ranking"))
                weight_class = str(profile.get("weight_class") or "").strip()
                if ko_rate:
                    segments.append(f"KO rate {ko_rate}")
                if sub_rate:
                    segments.append(f"submission rate {sub_rate}")
                if reach_cm:
                    segments.append(f"reach {reach_cm} cm")
                if ranking:
                    segments.append(f"ranking #{ranking}")
                if weight_class:
                    segments.append(weight_class)

            age = _int_text(profile.get("age"))
            if age:
                segments.append(f"age {age}")

            if segments:
                parts.append(f"{name}: " + ", ".join(segments))

            bouts = recent_fights.get(side) or []
            if bouts:
                rendered = []
                for bout in bouts[:2]:
                    result = str(bout.get("result") or "").strip()
                    opponent = str(bout.get("opponent") or "").strip()
                    method = _clean_method(bout.get("method"))
                    round_no = _int_text(bout.get("round"))
                    event = str(bout.get("event") or "").strip()
                    chunk = " ".join(part for part in [result, opponent] if part).strip()
                    if method:
                        chunk = f"{chunk} via {method}".strip()
                    if round_no:
                        chunk = f"{chunk} (R{round_no})".strip()
                    if event:
                        chunk = f"{chunk} at {event}".strip()
                    if chunk:
                        rendered.append(chunk)
                if rendered:
                    parts.append(f"Recent {name} fights: " + "; ".join(rendered))

        if title_implications:
            parts.append(f"Title implications: {title_implications}")

        return "\n".join(parts)

    def contributes_key_facts(self, evidence: SportEvidence) -> int:
        if not evidence.available or not evidence.data:
            return 0
        count = 0
        profiles = evidence.data.get("fighter_profiles") or {}
        recent_fights = evidence.data.get("recent_fights") or {}
        if profiles.get("home") or profiles.get("away"):
            count += 1
        if recent_fights.get("home") or recent_fights.get("away"):
            count += 1
        if evidence.data.get("title_implications"):
            count += 1
        return min(count, 3)

    async def _do_fetch(
        self,
        requested_sport: str,
        match_key: str,
        home: str,
        away: str,
    ) -> SportEvidence:
        if requested_sport == "mma":
            api_key = os.getenv("API_SPORTS_KEY", "")
            if not api_key:
                return self._unavailable("mma", "API_SPORTS_KEY not set")
        else:
            api_key = os.getenv("BOXING_DATA_API_KEY", "")
            if not api_key:
                return self._unavailable("boxing", "BOXING_DATA_API_KEY not set")

        timeout = aiohttp.ClientTimeout(total=_API_TIMEOUT_S)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            if requested_sport == "mma":
                data = await self._fetch_mma_evidence(session, api_key, home, away)
                source_name = "api-sports-mma"
            else:
                data = await self._fetch_boxing_evidence(session, api_key, home, away)
                source_name = "boxing-data"

        if not data.get("fighter_profiles"):
            return self._unavailable(
                requested_sport,
                f"No combat evidence found for {home} vs {away}",
                source_name=source_name,
            )

        data["requested_sport"] = requested_sport
        data["match_key"] = match_key
        return SportEvidence(
            sport=requested_sport,
            available=True,
            source_name=source_name,
            fetched_at=_utc_iso(),
            data=data,
        )

    async def _fetch_mma_evidence(
        self,
        session: aiohttp.ClientSession,
        api_key: str,
        home: str,
        away: str,
    ) -> dict[str, Any]:
        headers = {
            "x-rapidapi-key": api_key,
            "x-rapidapi-host": _MMA_API_HOST,
        }
        home_profile = await self._fetch_mma_fighter(session, headers, home)
        away_profile = await self._fetch_mma_fighter(session, headers, away)
        home_recent = await self._fetch_mma_recent_fights(session, headers, home)
        away_recent = await self._fetch_mma_recent_fights(session, headers, away)
        title_implications = self._derive_title_implications(home_profile, away_profile, "mma")
        return {
            "fighter_profiles": {"home": home_profile, "away": away_profile},
            "recent_fights": {"home": home_recent, "away": away_recent},
            "h2h": [],
            "title_implications": title_implications,
        }

    async def _fetch_boxing_evidence(
        self,
        session: aiohttp.ClientSession,
        api_key: str,
        home: str,
        away: str,
    ) -> dict[str, Any]:
        headers = {
            "x-rapidapi-key": api_key,
            "x-rapidapi-host": _BOXING_API_HOST,
        }
        home_profile = await self._fetch_boxer(session, headers, home)
        away_profile = await self._fetch_boxer(session, headers, away)
        home_recent = await self._fetch_boxing_recent_fights(session, headers, home)
        away_recent = await self._fetch_boxing_recent_fights(session, headers, away)
        title_implications = self._derive_title_implications(home_profile, away_profile, "boxing")
        return {
            "fighter_profiles": {"home": home_profile, "away": away_profile},
            "recent_fights": {"home": home_recent, "away": away_recent},
            "h2h": [],
            "title_implications": title_implications,
        }

    async def _fetch_mma_fighter(
        self,
        session: aiohttp.ClientSession,
        headers: dict[str, str],
        fighter_name: str,
    ) -> dict[str, Any]:
        payload = await self._get_json(
            session,
            f"{_MMA_API_BASE}/fighters",
            headers=headers,
            params={"search": fighter_name},
        )
        fighter = self._first_item(payload)
        return {
            "name": fighter.get("name") or fighter_name,
            "record": self._join_record(fighter),
            "ko_rate": fighter.get("ko_rate") or fighter.get("ko_percentage"),
            "sub_rate": fighter.get("sub_rate") or fighter.get("submission_rate"),
            "weight_class": fighter.get("weight_class") or fighter.get("division"),
            "reach_cm": fighter.get("reach_cm") or fighter.get("reach"),
            "age": fighter.get("age"),
            "ranking": fighter.get("ranking") or fighter.get("rank"),
            "country": fighter.get("country"),
            "title_status": fighter.get("title_status"),
        }

    async def _fetch_mma_recent_fights(
        self,
        session: aiohttp.ClientSession,
        headers: dict[str, str],
        fighter_name: str,
    ) -> list[dict[str, Any]]:
        payload = await self._get_json(
            session,
            f"{_MMA_API_BASE}/events",
            headers=headers,
            params={"search": fighter_name},
        )
        return self._extract_recent_bouts(payload, fighter_name)

    async def _fetch_boxer(
        self,
        session: aiohttp.ClientSession,
        headers: dict[str, str],
        fighter_name: str,
    ) -> dict[str, Any]:
        payload = await self._get_json(
            session,
            f"{_BOXING_API_BASE}/boxers",
            headers=headers,
            params={"search": fighter_name},
        )
        boxer = self._first_item(payload)
        return {
            "name": boxer.get("name") or fighter_name,
            "record": boxer.get("record") or self._join_record(boxer),
            "ko_rate": boxer.get("ko_rate") or boxer.get("knockout_ratio"),
            "sub_rate": None,
            "weight_class": boxer.get("weight_class") or boxer.get("division"),
            "reach_cm": boxer.get("reach_cm") or boxer.get("reach"),
            "age": boxer.get("age"),
            "ranking": boxer.get("ranking") or boxer.get("rank"),
            "country": boxer.get("country"),
            "title_status": boxer.get("title_status") or boxer.get("titles"),
        }

    async def _fetch_boxing_recent_fights(
        self,
        session: aiohttp.ClientSession,
        headers: dict[str, str],
        fighter_name: str,
    ) -> list[dict[str, Any]]:
        payload = await self._get_json(
            session,
            f"{_BOXING_API_BASE}/fights",
            headers=headers,
            params={"search": fighter_name},
        )
        return self._extract_recent_bouts(payload, fighter_name)

    async def _get_json(
        self,
        session: aiohttp.ClientSession,
        url: str,
        *,
        headers: dict[str, str],
        params: dict[str, Any],
    ) -> Any:
        async with session.get(url, headers=headers, params=params) as resp:
            resp.raise_for_status()
            return await resp.json()

    def _resolve_sport(self, match_key: str, sport: str | None) -> str:
        requested = _normalise(sport or "")
        if requested in {"mma", "boxing"}:
            return requested
        if requested == "combat":
            inferred = self._infer_from_match_key(match_key)
            if inferred:
                return inferred
        inferred = self._infer_from_match_key(match_key)
        return inferred or "mma"

    def _infer_from_match_key(self, match_key: str) -> str | None:
        norm = _normalise(match_key)
        if any(token in norm for token in ("boxing", "box", "wba", "wbc", "ibf", "wbo")):
            return "boxing"
        if any(token in norm for token in ("mma", "ufc", "bellator", "pfl", "one")):
            return "mma"
        return None

    def _first_item(self, payload: Any) -> dict[str, Any]:
        if isinstance(payload, dict):
            for key in ("response", "data", "results", "items"):
                value = payload.get(key)
                if isinstance(value, list) and value:
                    item = value[0]
                    if isinstance(item, dict):
                        return item
            return payload
        if isinstance(payload, list) and payload and isinstance(payload[0], dict):
            return payload[0]
        return {}

    def _extract_recent_bouts(self, payload: Any, fighter_name: str) -> list[dict[str, Any]]:
        raw_items: list[dict[str, Any]] = []
        if isinstance(payload, dict):
            for key in ("response", "data", "results", "items"):
                value = payload.get(key)
                if isinstance(value, list):
                    raw_items = [item for item in value if isinstance(item, dict)]
                    break
        elif isinstance(payload, list):
            raw_items = [item for item in payload if isinstance(item, dict)]

        fighter_norm = _normalise(fighter_name)
        bouts: list[dict[str, Any]] = []
        for item in raw_items[:8]:
            opponent = (
                item.get("opponent")
                or item.get("opponent_name")
                or item.get("rival")
                or self._extract_opponent_from_names(item, fighter_norm)
            )
            bout = {
                "opponent": opponent,
                "result": item.get("result") or item.get("outcome"),
                "method": item.get("method") or item.get("win_method"),
                "round": item.get("round") or item.get("end_round"),
                "event": item.get("event") or item.get("event_name"),
                "date": item.get("date"),
            }
            if any(bout.values()):
                bouts.append(bout)
            if len(bouts) >= 3:
                break
        return bouts

    def _extract_opponent_from_names(self, item: dict[str, Any], fighter_norm: str) -> str:
        home_name = str(item.get("home") or item.get("fighter_1") or item.get("red_corner") or "").strip()
        away_name = str(item.get("away") or item.get("fighter_2") or item.get("blue_corner") or "").strip()
        if home_name and _normalise(home_name) != fighter_norm:
            return home_name
        if away_name and _normalise(away_name) != fighter_norm:
            return away_name
        return ""

    def _join_record(self, payload: dict[str, Any]) -> str:
        wins = payload.get("wins")
        losses = payload.get("losses")
        draws = payload.get("draws")
        if wins is None and losses is None and draws is None:
            return str(payload.get("record") or "").strip()
        parts = [str(int(v)) if isinstance(v, (int, float)) else str(v or 0) for v in (wins, losses, draws)]
        return "-".join(parts)

    def _derive_title_implications(
        self,
        home_profile: dict[str, Any],
        away_profile: dict[str, Any],
        sport: str,
    ) -> str:
        for profile in (home_profile, away_profile):
            status = str(profile.get("title_status") or "").strip()
            if status:
                return status
        weight_class = str(home_profile.get("weight_class") or away_profile.get("weight_class") or "").strip()
        if weight_class:
            suffix = "title picture" if sport == "boxing" else "contender picture"
            return f"{weight_class} {suffix}"
        return ""

    def _unavailable(
        self,
        sport: str,
        error: str,
        *,
        source_name: str | None = None,
    ) -> SportEvidence:
        source = source_name or ("boxing-data" if sport == "boxing" else "api-sports-mma")
        return SportEvidence(
            sport=sport,
            available=False,
            source_name=source,
            error=error,
        )
