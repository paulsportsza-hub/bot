"""CricketData.org adapter implementing EvidenceProvider.

API: https://api.cricketdata.org  — free tier: 100 hits/day.
Auth: ?apikey=CRICKET_DATA_API_KEY query param.
Key endpoints:
  /api/currentMatches?apikey=          — live/upcoming matches
  /api/cricketScore?id=ID&apikey=      — full match detail
  /api/squads?seriesid=SID&apikey=     — team squads for a series

SA20 COVERAGE GAP (validated 2026-03-28):
  CricketData.org free tier primarily covers international fixtures.
  SA20 (domestic SA T20 franchise league) was NOT found in currentMatches
  during validation.  fetch_evidence returns available=False for SA20 matches.
  Resolution options:
    1. Upgrade to a paid CricketData.org plan with domestic coverage, or
    2. Switch to a dedicated SA20 data provider (e.g. CricAPI, SportRadar).
  Until resolved, SA20 narrative falls back to odds-only evidence.
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

log = logging.getLogger("mzansi.cricket_evidence")

_API_BASE = "https://api.cricketdata.org"
_API_TIMEOUT_S = 3          # per-call hard cap
_CACHE_TTL_S = 900          # 15 minutes — matches pregen cycle

# in-memory cache: match_key → (SportEvidence, monotonic_timestamp)
_CACHE: dict[str, tuple[SportEvidence, float]] = {}


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalise(name: str) -> str:
    return name.lower().replace("-", " ").replace("_", " ").strip()


def _team_in_match(match: dict[str, Any], home: str, away: str) -> bool:
    """Return True when both teams appear in a CricketData match dict."""
    teams_raw = match.get("teams") or []
    if isinstance(teams_raw, list):
        teams = [_normalise(t) for t in teams_raw]
    else:
        teams = []
    # also try match name
    name_blob = _normalise(match.get("name", ""))
    h_norm, a_norm = _normalise(home), _normalise(away)
    h_short = h_norm.split()[0] if h_norm else ""
    a_short = a_norm.split()[0] if a_norm else ""

    def _hit(token: str, candidates: list[str]) -> bool:
        if not token:
            return False
        if any(token in c or c in token for c in candidates):
            return True
        close = difflib.get_close_matches(token, candidates, n=1, cutoff=0.7)
        return bool(close)

    from_teams = _hit(h_short, teams) and _hit(a_short, teams)
    from_name = (h_short in name_blob or h_norm in name_blob) and (
        a_short in name_blob or a_norm in name_blob
    )
    return from_teams or from_name


def _find_best_match(
    matches: list[dict[str, Any]], home: str, away: str
) -> dict[str, Any] | None:
    for m in matches:
        if _team_in_match(m, home, away):
            return m
    return None


class CricketEvidenceProvider:
    """CricketData.org adapter."""

    # --- public API (EvidenceProvider protocol) ---

    async def fetch_evidence(
        self, match_key: str, home: str, away: str, sport: str | None = None
    ) -> SportEvidence:
        """Fetch cricket evidence for a match.  5s total budget enforced by caller."""
        now = time.monotonic()
        if match_key in _CACHE:
            cached_ev, ts = _CACHE[match_key]
            if now - ts < _CACHE_TTL_S:
                return cached_ev

        api_key = os.getenv("CRICKET_DATA_API_KEY", "")
        if not api_key:
            ev = SportEvidence(
                sport="cricket",
                available=False,
                source_name="cricketdata.org",
                error="CRICKET_DATA_API_KEY not set",
            )
            _CACHE[match_key] = (ev, now)
            return ev

        try:
            ev = await self._do_fetch(api_key, match_key, home, away)
        except asyncio.TimeoutError:
            ev = SportEvidence(
                sport="cricket",
                available=False,
                source_name="cricketdata.org",
                error="fetch timeout",
            )
        except aiohttp.ClientResponseError as exc:
            if exc.status == 429:
                ev = SportEvidence(
                    sport="cricket",
                    available=False,
                    source_name="cricketdata.org",
                    error="rate limited (429)",
                )
            else:
                ev = SportEvidence(
                    sport="cricket",
                    available=False,
                    source_name="cricketdata.org",
                    error=f"HTTP {exc.status}",
                )
        except Exception as exc:
            ev = SportEvidence(
                sport="cricket",
                available=False,
                source_name="cricketdata.org",
                error=str(exc),
            )

        # Count the live API call regardless of outcome (429 = still consumed a call).
        try:
            from evidence_providers import rate_monitor
            rate_monitor.record_call("cricketdata")
        except Exception:
            pass

        _CACHE[match_key] = (ev, now)
        return ev

    def format_for_prompt(self, evidence: SportEvidence) -> str:
        """Format evidence into a CRICKET CONTEXT section for the AI prompt."""
        if not evidence.available or not evidence.data:
            return ""

        parts = ["[CRICKET CONTEXT]"]
        match = evidence.data.get("match", {})
        squads = evidence.data.get("squads", [])

        if match.get("name"):
            parts.append(f"Series context: {match['name']}")
        if match.get("venue"):
            parts.append(f"Venue: {match['venue']}")
        if match.get("matchType"):
            parts.append(f"Format: {match['matchType'].upper()}")
        if match.get("status"):
            parts.append(f"Status: {match['status']}")
        if match.get("dateTimeGMT"):
            parts.append(f"Scheduled (UTC): {match['dateTimeGMT']}")

        if squads and isinstance(squads, list):
            for team_sq in squads:
                team_name = team_sq.get("teamName") or team_sq.get("team", "")
                players = team_sq.get("players") or []
                if team_name and players:
                    key_names = [
                        p.get("name", "") for p in players[:6] if p.get("name")
                    ]
                    parts.append(f"{team_name} squad: {', '.join(key_names)}")

        return "\n".join(parts)

    def contributes_key_facts(self, evidence: SportEvidence) -> int:
        """Return number of key facts (max 5) this evidence contributes."""
        if not evidence.available or not evidence.data:
            return 0
        match = evidence.data.get("match", {})
        squads = evidence.data.get("squads", [])
        count = 0
        if match.get("name"):
            count += 1  # series_context
        if squads:
            count += 1  # squads
        if match.get("venue"):
            count += 1  # pitch / venue
        if match.get("teams"):
            count += 1  # form proxy (team identities confirmed)
        if match.get("matchType"):
            count += 1  # h2h proxy (format known)
        return min(count, 5)

    # --- internal helpers ---

    async def _do_fetch(
        self, api_key: str, match_key: str, home: str, away: str
    ) -> SportEvidence:
        timeout = aiohttp.ClientTimeout(total=_API_TIMEOUT_S)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            match_data = await self._find_match(session, api_key, home, away)
            if not match_data:
                return SportEvidence(
                    sport="cricket",
                    available=False,
                    source_name="cricketdata.org",
                    error=(
                        f"Match not found for {home} vs {away}. "
                        "SA20 domestic league may not be covered on this plan."
                    ),
                )

            series_id = (
                match_data.get("seriesId")
                or match_data.get("series_id")
                or ""
            )
            squads: list[dict[str, Any]] = []
            if series_id:
                squads = await self._fetch_squads(session, api_key, str(series_id))

            return SportEvidence(
                sport="cricket",
                available=True,
                source_name="cricketdata.org",
                fetched_at=_utc_iso(),
                data={
                    "match": match_data,
                    "squads": squads,
                    "series_id": series_id,
                },
            )

    async def _find_match(
        self,
        session: aiohttp.ClientSession,
        api_key: str,
        home: str,
        away: str,
    ) -> dict[str, Any] | None:
        url = f"{_API_BASE}/api/currentMatches"
        params = {"apikey": api_key, "offset": 0}
        async with session.get(url, params=params) as resp:
            resp.raise_for_status()
            body = await resp.json()
        matches = body.get("data") or []
        if not isinstance(matches, list):
            return None
        log.debug("CricketData currentMatches: %d matches returned", len(matches))
        return _find_best_match(matches, home, away)

    async def _fetch_squads(
        self,
        session: aiohttp.ClientSession,
        api_key: str,
        series_id: str,
    ) -> list[dict[str, Any]]:
        url = f"{_API_BASE}/api/squads"
        params = {"apikey": api_key, "seriesid": series_id}
        try:
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    return []
                body = await resp.json()
            data = body.get("data") or []
            return data if isinstance(data, list) else []
        except Exception as exc:
            log.debug("CricketData squads fetch failed: %s", exc)
            return []
