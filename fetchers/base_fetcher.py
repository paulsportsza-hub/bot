"""Abstract base fetcher with MEP definitions and caching helpers.

Every sport fetcher inherits from BaseFetcher and implements fetch_context().
The returned dict MUST be ESPN-compatible so build_narrative_spec() and
build_evidence_pack() work unchanged.
"""

from __future__ import annotations

import json
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from db_connection import get_connection

log = logging.getLogger("mzansi.fetchers")

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "odds.db")

# ── MEP Definitions ───────────────────────────────────────────────────────────
# Minimum Enrichment Pack: fields required per sport per horizon to avoid
# template fallback.  Each entry maps horizon_bucket -> set of required fields.

MEP_DEFINITIONS: dict[str, dict[str, set[str]]] = {
    "soccer": {
        "far": {  # >7 days
            "team_names", "competition", "standings_position",
            "recent_form", "h2h_last_5", "venue", "elo_ratings",
        },
        "mid": {  # 2-7 days — adds coach
            "team_names", "competition", "standings_position",
            "recent_form", "h2h_last_5", "venue", "elo_ratings",
            "coach_names",
        },
        "near": {  # <2 days — adds injuries + lineups
            "team_names", "competition", "standings_position",
            "recent_form", "h2h_last_5", "venue", "elo_ratings",
            "coach_names", "injuries_list", "predicted_lineups",
        },
    },
    "rugby": {
        "far": {
            "team_names", "competition", "standings_position",
            "recent_form", "venue",
        },
        "mid": {
            "team_names", "competition", "standings_position",
            "recent_form", "venue", "h2h_last_5",
        },
        "near": {
            "team_names", "competition", "standings_position",
            "recent_form", "venue", "h2h_last_5",
        },
    },
    "cricket": {
        "far": {
            "team_names", "competition", "format",
            "standings", "recent_form", "venue",
        },
        "mid": {
            "team_names", "competition", "format",
            "standings", "recent_form", "venue", "h2h_last_5",
        },
        "near": {
            "team_names", "competition", "format",
            "standings", "recent_form", "venue", "h2h_last_5",
            "weather_forecast",
        },
    },
    "mma": {
        "far": {
            "fighter_names", "event_name", "fighter_records",
            "weight_class", "recent_fights",
        },
        "mid": {
            "fighter_names", "event_name", "fighter_records",
            "weight_class", "recent_fights",
        },
        "near": {
            "fighter_names", "event_name", "fighter_records",
            "weight_class", "recent_fights",
        },
    },
}


def horizon_bucket(hours: float) -> str:
    """Classify horizon into far/mid/near."""
    if hours > 7 * 24:
        return "far"
    if hours > 48:
        return "mid"
    return "near"


@dataclass
class FetchResult:
    """Result from a fetcher call with confidence metadata."""

    context: dict[str, Any]  # ESPN-compatible context dict
    confidence: dict[str, float] = field(default_factory=dict)  # field -> 0.0-1.0
    sources: dict[str, str] = field(default_factory=dict)  # field -> source name
    mep_met: bool = False
    mep_missing: list[str] = field(default_factory=list)
    fetched_at: str = ""

    def __post_init__(self) -> None:
        if not self.fetched_at:
            self.fetched_at = datetime.now(timezone.utc).isoformat()


# ── Cache Helpers ─────────────────────────────────────────────────────────────

def ensure_schema(db_path: str | None = None) -> None:
    """Create context_cache and match_context tables if they don't exist."""
    conn = get_connection(db_path or DB_PATH)
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS context_cache (
                cache_key   TEXT PRIMARY KEY,
                sport       TEXT NOT NULL,
                league      TEXT NOT NULL,
                endpoint    TEXT NOT NULL,
                data        TEXT NOT NULL,
                fetched_at  TEXT NOT NULL,
                expires_at  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS match_context (
                match_key       TEXT PRIMARY KEY,
                sport           TEXT NOT NULL,
                league          TEXT NOT NULL,
                context_json    TEXT NOT NULL,
                confidence_json TEXT NOT NULL DEFAULT '{}',
                sources_json    TEXT NOT NULL DEFAULT '{}',
                mep_met         INTEGER NOT NULL DEFAULT 0,
                mep_missing     TEXT NOT NULL DEFAULT '[]',
                horizon_bucket  TEXT NOT NULL DEFAULT 'far',
                fetched_at      TEXT NOT NULL,
                expires_at      TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_context_cache_expires
                ON context_cache(expires_at);
            CREATE INDEX IF NOT EXISTS idx_match_context_league
                ON match_context(league, sport);
            CREATE INDEX IF NOT EXISTS idx_match_context_expires
                ON match_context(expires_at);
        """)
    finally:
        conn.close()


def get_cached_context(
    match_key: str,
    db_path: str | None = None,
) -> dict[str, Any] | None:
    """Return cached match context if fresh, else None."""
    conn = get_connection(db_path or DB_PATH, readonly=True)
    try:
        row = conn.execute(
            "SELECT context_json, expires_at FROM match_context WHERE match_key = ?",
            (match_key,),
        ).fetchone()
        if not row:
            return None
        expires = datetime.fromisoformat(row["expires_at"])
        if datetime.now(timezone.utc) > expires:
            return None
        return json.loads(row["context_json"])
    except Exception:
        return None
    finally:
        conn.close()


def store_match_context(
    match_key: str,
    result: FetchResult,
    sport: str,
    league: str,
    bucket: str,
    ttl_hours: float = 6.0,
    db_path: str | None = None,
) -> None:
    """Store or update match context in DB."""
    now = datetime.now(timezone.utc)
    from datetime import timedelta
    expires = now + timedelta(hours=ttl_hours)

    conn = get_connection(db_path or DB_PATH)
    try:
        conn.execute(
            """INSERT OR REPLACE INTO match_context
               (match_key, sport, league, context_json, confidence_json,
                sources_json, mep_met, mep_missing, horizon_bucket,
                fetched_at, expires_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                match_key, sport, league,
                json.dumps(result.context),
                json.dumps(result.confidence),
                json.dumps(result.sources),
                1 if result.mep_met else 0,
                json.dumps(result.mep_missing),
                bucket,
                now.isoformat(),
                expires.isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_cached_api_response(
    cache_key: str,
    db_path: str | None = None,
) -> dict[str, Any] | None:
    """Return cached raw API response if not expired."""
    conn = get_connection(db_path or DB_PATH, readonly=True)
    try:
        row = conn.execute(
            "SELECT data, expires_at FROM context_cache WHERE cache_key = ?",
            (cache_key,),
        ).fetchone()
        if not row:
            return None
        expires = datetime.fromisoformat(row["expires_at"])
        if datetime.now(timezone.utc) > expires:
            return None
        return json.loads(row["data"])
    except Exception:
        return None
    finally:
        conn.close()


def store_api_response(
    cache_key: str,
    data: dict[str, Any],
    sport: str,
    league: str,
    endpoint: str,
    ttl_hours: float = 24.0,
    db_path: str | None = None,
) -> None:
    """Cache a raw API response."""
    now = datetime.now(timezone.utc)
    from datetime import timedelta
    expires = now + timedelta(hours=ttl_hours)

    conn = get_connection(db_path or DB_PATH)
    try:
        conn.execute(
            """INSERT OR REPLACE INTO context_cache
               (cache_key, sport, league, endpoint, data, fetched_at, expires_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (cache_key, sport, league, endpoint,
             json.dumps(data), now.isoformat(), expires.isoformat()),
        )
        conn.commit()
    finally:
        conn.close()


# ── Abstract Base ─────────────────────────────────────────────────────────────

class BaseFetcher(ABC):
    """Abstract base for sport-specific data fetchers."""

    sport: str = ""

    @abstractmethod
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
        """Fetch match context for a fixture.

        Returns a FetchResult with an ESPN-compatible context dict.
        Must never raise — returns partial/empty result on failure.
        """
        ...

    def check_mep(
        self,
        result: FetchResult,
        horizon_hours: float,
    ) -> tuple[bool, list[str]]:
        """Check if result meets MEP for sport and horizon."""
        bucket = horizon_bucket(horizon_hours)
        mep = MEP_DEFINITIONS.get(self.sport, {}).get(bucket, set())
        if not mep:
            return True, []

        present = set()
        ctx = result.context

        # Map context dict fields to MEP field names
        home = ctx.get("home_team", {})
        away = ctx.get("away_team", {})

        if home.get("name") and away.get("name"):
            present.add("team_names")
            present.add("fighter_names")
        if ctx.get("competition"):
            present.add("competition")
            present.add("event_name")
        if home.get("position") is not None or home.get("league_position") is not None:
            present.add("standings_position")
            present.add("standings")
        if home.get("form") or away.get("form"):
            present.add("recent_form")
        if ctx.get("h2h"):
            present.add("h2h_last_5")
        if ctx.get("venue"):
            present.add("venue")
        if ctx.get("elo_home") is not None or ctx.get("elo_away") is not None:
            present.add("elo_ratings")
        if home.get("coach") or away.get("coach"):
            present.add("coach_names")
        if ctx.get("injuries") or home.get("injuries") or away.get("injuries"):
            present.add("injuries_list")
        if home.get("lineup") or away.get("lineup"):
            present.add("predicted_lineups")
        if ctx.get("weather"):
            present.add("weather_forecast")
        if ctx.get("format"):
            present.add("format")
        if home.get("record") or home.get("wins") is not None:
            present.add("fighter_records")
        if home.get("weight_class") or ctx.get("weight_class"):
            present.add("weight_class")
        if home.get("recent_fights") or away.get("recent_fights"):
            present.add("recent_fights")

        missing = sorted(mep - present)
        return len(missing) == 0, missing

    async def fetch_and_cache(
        self,
        match_key: str,
        home_team: str,
        away_team: str,
        league: str,
        sport: str,
        horizon_hours: float = 168.0,
        *,
        live_safe: bool = True,
        db_path: str | None = None,
    ) -> dict[str, Any]:
        """High-level: check cache, fetch if stale, store, return ESPN-compat dict.

        This is the main entry point called by pregenerate_narratives.
        """
        db = db_path or DB_PATH
        ensure_schema(db)

        # Check cache first
        cached = get_cached_context(match_key, db_path=db)
        if cached:
            log.info("Cache hit for %s", match_key)
            return cached

        # Fetch fresh
        result = await self.fetch_context(
            home_team, away_team, league, horizon_hours,
            live_safe=live_safe, db_path=db,
        )

        # Check MEP
        mep_met, mep_missing = self.check_mep(result, horizon_hours)
        result.mep_met = mep_met
        result.mep_missing = mep_missing

        if mep_missing:
            log.warning(
                "MEP not met for %s (%s): missing %s",
                match_key, horizon_bucket(horizon_hours), mep_missing,
            )

        # Determine TTL based on horizon
        bucket = horizon_bucket(horizon_hours)
        ttl = {"far": 24.0, "mid": 6.0, "near": 1.0}.get(bucket, 6.0)

        # Store
        store_match_context(match_key, result, sport, league, bucket, ttl, db)

        return result.context
