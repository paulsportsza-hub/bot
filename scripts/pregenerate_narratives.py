#!/usr/bin/env python3
"""W60-CACHE: Pre-generate narratives for all live edges.

Usage:
    python scripts/pregenerate_narratives.py --sweep full          # All edges
    python scripts/pregenerate_narratives.py --sweep refresh       # Stale/expired only
    python scripts/pregenerate_narratives.py --sweep uncached_only # New edges without cache

Generates Claude narratives for each live edge and stores them in the
narrative_cache table of odds.db. Bot serves these instantly on user tap.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import re
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
SAST = ZoneInfo("Africa/Johannesburg")
UTC = ZoneInfo("UTC")

# Add project paths
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import SCRAPERS_ROOT, BOT_ROOT
sys.path.insert(0, str(SCRAPERS_ROOT.parent))
sys.path.insert(0, str(SCRAPERS_ROOT))

from dotenv import load_dotenv
_bot_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_bot_dir, ".env"))

# FIX-DROP-SONNET-POLISH-W82-CANONICAL-01: pregen sweep produces W82 baseline only.
# No Sonnet polish, no Haiku fallback, no LLM polish path. _render_baseline is canonical.
from evidence_pack import (
    _build_h2h_injection,
    build_evidence_pack,
    _inject_h2h_sentence,
    serialise_evidence_pack,
)

# Configure the pregenerate logger directly rather than root via basicConfig.
# bot.py (imported below) adds its own handlers to root — basicConfig would
# add a duplicate, causing every log line to appear 2-3 times.
log = logging.getLogger("pregenerate")
if not log.handlers and not logging.getLogger().handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
log.setLevel(logging.INFO)

# FIX-DROP-SONNET-POLISH-W82-CANONICAL-01: W82 deterministic baseline is the only path.
NARRATIVE_SOURCE_LABEL = "w82"

# Import narrative functions from bot.py (safe — guarded by __name__ == __main__)
# FIX-DROP-SONNET-POLISH-W82-CANONICAL-01: only baseline-path imports retained.
import bot
from bot import (
    _apply_sport_subs,
    _check_verdict_balance,
    _compute_odds_hash,
    _ensure_narrative_cache_table,
    _final_polish,
    _get_cached_narrative,
    _sanitise_jargon,
    _store_narrative_cache,
    _VERDICT_BLACKLIST,
)
import config

# FIX-DROP-SONNET-POLISH-W82-CANONICAL-01: rename-protection sentinel for the
# W82 baseline rendering surface. If any of these are renamed/deleted by a future
# wave, fail loud at startup rather than silently producing empty cache rows.
_REQUIRED_BOT_FUNCTIONS = [
    "_apply_sport_subs",
    "_final_polish",
    "_sanitise_jargon",
    "_store_narrative_cache",
    "_get_cached_narrative",
]
_missing = [fn for fn in _REQUIRED_BOT_FUNCTIONS if not hasattr(bot, fn)]
if _missing:
    raise ImportError(
        f"pregenerate_narratives.py: required bot functions missing: {_missing}. "
        "Did a wave rename/delete these without updating imports?"
    )


# BASELINE-FIX: match-level dedup — tracks matches currently being generated.
# Prevents the same match being generated twice in concurrent calls to main().
# Module-level so it persists across multiple main() invocations within a process.
_in_progress_matches: set[str] = set()

# AC3 F5 — FIX-VERDICT-SHAPE-GUARD-01: track consecutive banned-shape rejections
# per fixture within this process run. After 3, mark narrative_cache as
# skipped_banned_shape so the serving layer falls back to programmatic verdict.
#
# W92-VERDICT-QUALITY P3: backed by narrative_skip_log table in odds.db for
# cross-process persistence. The module-level dict acts as a write-through cache
# so hot-loop sweeps avoid a DB hit per iteration. DB is system-of-record.
_banned_shape_reject_count: dict[str, int] = {}
_BANNED_SHAPE_SKIP_THRESHOLD = 1  # INV-SONNET-SPIKE-01: reduced 3→1; one retry is sufficient, 3 triples cost

# BUILD-NARRATIVE-PREGEN-WINDOW-01: sweep universe bounds.
# Hourly sweeps process only matches kicking off within the next 48h,
# capped at 60 matches ordered by soonest kickoff.
# Concurrency is bounded to 3 simultaneous LLM slots so pregen never
# starves _edge_precompute_job.
# FIX-PREGEN-TIER-DRIFT-01 (2026-04-25): cap raised 25 → 60 to accommodate the
# 240h premium horizon expansion (FIX-AI-BREAKDOWN-COVERAGE-01). At 25, the
# nearest-kickoff sort cut Gold/Diamond fixtures 7-9 days out (53+ matches now
# fit the window). 60 covers the full premium universe while keeping daily LLM
# spend bounded (~$9/mo delta at full saturation).
_PREGEN_HORIZON_HOURS: int = 240
_PREGEN_MATCH_CAP: int = 60
_PREGEN_CONCURRENCY: int = 3

# FIX-PREGEN-DIAMOND-PRIORITY-01 (locked 2026-04-28).
# Tier priority order — Diamond first, Bronze last. Premium tiers MUST refresh
# before Bronze when the cap budget is constrained. INV-CORPUS-LIVE-COVERAGE-01
# measured a 4h11m Diamond blackout pre-fix when Bronze candidates with sooner
# kickoffs displaced Diamond on cap truncation. Order matches the canonical
# tier ordering used across GATE_MATRIX (Diamond > Gold > Silver > Bronze).
_TIER_PRIORITY: dict[str, int] = {
    "diamond": 0,
    "gold": 1,
    "silver": 2,
    "bronze": 3,
}


def _kickoff_unix(target: dict) -> float:
    """Extract kickoff timestamp from a pregen candidate; large default for missing.

    Best-effort: any parse failure returns +inf so the candidate sorts last
    within its tier band. Never raises.
    """
    raw = (
        target.get("_resolved_kickoff")
        or target.get("kickoff")
        or target.get("commence_time")
        or target.get("match_date")
    )
    if not raw:
        return float("inf")
    try:
        if isinstance(raw, (int, float)):
            return float(raw)
        if isinstance(raw, datetime):
            return raw.timestamp()
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).timestamp()
    except Exception:
        return float("inf")


def _apply_premium_horizon_filter(
    edges: list[dict], horizon_cutoff: datetime
) -> tuple[list[dict], int]:
    """FIX-W84-PREMIUM-MANDATORY-COVERAGE-01 (locked 2026-04-29).

    Filter pregen candidates by ``_PREGEN_HORIZON_HOURS`` while exempting
    premium tiers. Diamond + Gold edges always pass through regardless of
    kickoff distance — the 240h horizon was clipping legitimate Gold/Diamond
    fixtures (e.g. EPL May 9 ~10 days out) and pushing premium consumers onto
    synthesis-on-tap baselines. Silver + Bronze still respect the horizon.

    Each candidate must have ``_resolved_kickoff`` populated (a ``datetime``)
    by the caller before invocation.

    Returns
    -------
    tuple[list[dict], int]
        ``(filtered_edges, premium_bypass_count)`` — the second element counts
        premium edges that survived solely because of the bypass (kickoff was
        beyond ``horizon_cutoff``).
    """
    out: list[dict] = []
    bypass_count = 0
    for he in edges:
        ko = he.get("_resolved_kickoff")
        tier = (he.get("tier") or he.get("edge_tier") or "").lower()
        is_premium = tier in ("gold", "diamond")
        if is_premium:
            out.append(he)
            if ko is not None and ko > horizon_cutoff:
                bypass_count += 1
        else:
            if ko is not None and ko <= horizon_cutoff:
                out.append(he)
    return out, bypass_count


# W92-VERDICT-QUALITY P3: narrative_skip_log DDL + helpers. Persistent skip counts
# survive process restarts and give EdgeOps a durable audit trail of which fixtures
# hit the banned-shape guard and when.
# BUILD-NARRATIVE-WATERTIGHT-01 C.2: add ``skip_reason`` TEXT column so EdgeOps can
# distinguish banned-shape rejections from quality-gate / fact-check / coverage skips.
_NARRATIVE_SKIP_LOG_DDL = """
CREATE TABLE IF NOT EXISTS narrative_skip_log (
    match_key TEXT PRIMARY KEY,
    skip_count INTEGER NOT NULL DEFAULT 0,
    skipped_flag INTEGER NOT NULL DEFAULT 0,
    last_updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    skip_reason TEXT
)
"""


def _ensure_skip_reason_column(conn) -> None:
    """BUILD-NARRATIVE-WATERTIGHT-01 C.2: idempotent migration for existing DBs.

    Adds the ``skip_reason`` column to pre-existing ``narrative_skip_log`` tables
    created before this wave. Existing rows are preserved (NULL skip_reason).
    """
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(narrative_skip_log)").fetchall()}
        if "skip_reason" not in cols:
            conn.execute("ALTER TABLE narrative_skip_log ADD COLUMN skip_reason TEXT")
            conn.commit()
    except Exception as _mig_err:
        log.debug("narrative_skip_log skip_reason migration skipped: %s", _mig_err)


def _load_skip_count(match_key: str) -> int:
    """Return persisted skip count for ``match_key`` from narrative_skip_log.

    W92-VERDICT-QUALITY P3. Returns 0 if row absent or on any DB error (fail-open).
    Uses module dict as write-through cache — first call populates cache, then
    subsequent calls read from dict without touching the DB.
    """
    if not match_key:
        return 0
    # Cache hit — avoid DB round trip on hot sweep loop.
    if match_key in _banned_shape_reject_count:
        return _banned_shape_reject_count[match_key]
    try:
        from scrapers.db_connect import connect_odds_db as _skp_conn
        conn = _skp_conn(str(SCRAPERS_ROOT / "odds.db"), timeout=3)
        try:
            conn.execute(_NARRATIVE_SKIP_LOG_DDL)
            row = conn.execute(
                "SELECT skip_count FROM narrative_skip_log WHERE match_key = ?",
                (match_key,),
            ).fetchone()
        finally:
            conn.close()
    except Exception as err:
        log.debug("narrative_skip_log load failed for %s: %s", match_key, err)
        return 0
    count = int(row[0]) if row else 0
    _banned_shape_reject_count[match_key] = count
    return count


def _bump_skip_count(match_key: str, reason: str = "banned_shape") -> int:
    """Increment skip count for ``match_key`` and persist to narrative_skip_log.

    W92-VERDICT-QUALITY P3. Returns the NEW count. Sets ``skipped_flag=1`` when the
    count reaches ``_BANNED_SHAPE_SKIP_THRESHOLD`` so downstream consumers can
    distinguish "hit threshold" from "below threshold".
    BUILD-NARRATIVE-WATERTIGHT-01 C.2: ``reason`` is persisted in the skip_reason
    column so EdgeOps can slice skip_log rows by cause (banned_shape, fact_check_strip,
    empty_verdict, coverage_gap, verdict_quality_gate_double_fail, etc.).
    Updates the module dict cache. Best-effort — on DB error we still bump the
    in-memory cache so the process-local retry logic keeps working.
    """
    if not match_key:
        return 0
    # Always bump the cache first so callers see a consistent increment even on DB error.
    current = _load_skip_count(match_key)
    new_count = current + 1
    _banned_shape_reject_count[match_key] = new_count
    flag = 1 if new_count >= _BANNED_SHAPE_SKIP_THRESHOLD else 0
    try:
        from scrapers.db_connect import connect_odds_db as _skp_conn
        conn = _skp_conn(str(SCRAPERS_ROOT / "odds.db"), timeout=3)
        try:
            conn.execute(_NARRATIVE_SKIP_LOG_DDL)
            _ensure_skip_reason_column(conn)
            conn.execute(
                "INSERT INTO narrative_skip_log "
                "(match_key, skip_count, skipped_flag, last_updated_at, skip_reason) "
                "VALUES (?, ?, ?, CURRENT_TIMESTAMP, ?) "
                "ON CONFLICT(match_key) DO UPDATE SET "
                "skip_count = excluded.skip_count, "
                "skipped_flag = excluded.skipped_flag, "
                "skip_reason = excluded.skip_reason, "
                "last_updated_at = CURRENT_TIMESTAMP",
                (match_key, new_count, flag, reason),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as err:
        log.debug("narrative_skip_log bump failed for %s: %s", match_key, err)
    return new_count


def _clear_skip_count(match_key: str) -> None:
    """Reset skip count for ``match_key`` (cache + DB).

    W92-VERDICT-QUALITY P3. Called after a successful narrative generation so the
    fixture is not carrying stale rejection history across sweeps. Best-effort.
    """
    if not match_key:
        return
    _banned_shape_reject_count.pop(match_key, None)
    try:
        from scrapers.db_connect import connect_odds_db as _skp_conn
        conn = _skp_conn(str(SCRAPERS_ROOT / "odds.db"), timeout=3)
        try:
            conn.execute(_NARRATIVE_SKIP_LOG_DDL)
            conn.execute(
                "DELETE FROM narrative_skip_log WHERE match_key = ?",
                (match_key,),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as err:
        log.debug("narrative_skip_log clear failed for %s: %s", match_key, err)

_RUNTIME_SCHEMA_REQUIREMENTS = {
    "narrative_cache": {
        "match_id",
        "narrative_html",
        "model",
        "edge_tier",
        "tips_json",
        "odds_hash",
        "created_at",
        "expires_at",
        "evidence_json",
        "narrative_source",
        "structured_card_json",  # AC-1 (P1P3-BUILD) — added via ALTER TABLE at bot startup
        "verdict_html",          # PIPELINE-BUILD-01
        "evidence_class",        # PIPELINE-BUILD-01
        "tone_band",             # PIPELINE-BUILD-01
        "spec_json",             # PIPELINE-BUILD-01
        "context_json",          # PIPELINE-BUILD-01
        "generation_ms",         # PIPELINE-BUILD-01
        "setup_validated",       # NARRATIVE-ACCURACY-01
        "verdict_validated",     # NARRATIVE-ACCURACY-01
        "setup_attempts",        # NARRATIVE-ACCURACY-01
        "verdict_attempts",      # NARRATIVE-ACCURACY-01
    },
    "shadow_narratives": {
        "match_key",
        "evidence_json",
        "prompt_text",
        "raw_draft",
        "verification_report",
        "verification_passed",
        "w82_baseline",
        "model",
        "created_at",
    },
}


def _pregen_enrichment_live_safe() -> tuple[bool, int | None]:
    """Always use read-only enrichment during pregen — no lock dependency.

    BUILD-16a: Pregen only READS from odds_snapshots. SQLite WAL mode permits
    concurrent reads during write transactions. The scraper writer lock
    (/tmp/mzansi_scraper.lock) is irrelevant to read-only pregen operations.
    """
    return True, None


def _validate_pregen_runtime_schema(db_path: str | None = None) -> None:
    """Read-only schema validation for runtime sweeps.

    Runtime pregen must not perform DDL/migrations. If required columns are absent,
    this should fail fast and surface a deploy-time schema issue instead of trying to
    alter tables while other writers are active.
    """
    path = db_path or bot._NARRATIVE_DB_PATH
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=1.0)
    try:
        conn.execute("PRAGMA query_only=ON")
        missing_tables: list[str] = []
        missing_columns: list[str] = []
        for table_name, required_columns in _RUNTIME_SCHEMA_REQUIREMENTS.items():
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
                (table_name,),
            ).fetchone()
            if row is None:
                missing_tables.append(table_name)
                continue
            cols = {
                result[1]
                for result in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
            }
            missing = sorted(required_columns - cols)
            if missing:
                missing_columns.append(f"{table_name}: {', '.join(missing)}")
        if missing_tables or missing_columns:
            problems = []
            if missing_tables:
                problems.append(f"missing tables: {', '.join(sorted(missing_tables))}")
            if missing_columns:
                problems.append(f"missing columns: {'; '.join(missing_columns)}")
            raise RuntimeError(
                "Runtime pregen schema validation failed; run the narrative cache migration "
                f"outside the sweep hot path ({'; '.join(problems)})"
            )
    finally:
        conn.close()


def _canonical_context_team_key(name: str) -> str:
    """Resolve a display/raw team name to the canonical odds key for context reads."""
    if not name:
        return ""
    try:
        from scrapers.odds_normaliser import normalise_key
        from scrapers.utils.team_mapper import normalise_team as mapper_normalise

        candidate = name.strip()
        if "_" in candidate:
            key = candidate.lower()
        else:
            key = mapper_normalise(candidate)
        return normalise_key(key)
    except Exception:
        return name.lower().replace(" ", "_")


def _needs_pregen_context_lift(ctx: dict) -> bool:
    """Retry once in pregen when context would still collapse to thin/no-context prose."""
    if not ctx or not ctx.get("data_available"):
        return True
    # VERDICT-FIX Fix 3: PARTIAL context is accepted as-is — no retry needed
    if ctx.get("_context_mode") == "PARTIAL":
        return False

    def _has_setup_signal(team: dict) -> bool:
        return bool(
            team.get("league_position")
            or team.get("position")
            or team.get("form")
            or team.get("last_5")
            or team.get("top_scorer")
        )

    home = ctx.get("home_team") or {}
    away = ctx.get("away_team") or {}
    return not (_has_setup_signal(home) or _has_setup_signal(away))


def _build_partial_context(
    home: str,
    away: str,
    league: str,
    sport: str,
    *,
    home_key: str = "",
    away_key: str = "",
) -> dict:
    """VERDICT-FIX Fix 3: Build a minimal partial context dict when ESPN data is thin.

    Returns a dict with _context_mode='PARTIAL' so:
    - _needs_pregen_context_lift() accepts it (stops retrying)
    - build_narrative_spec() has team names for no-context prose
    - W84 AI path is skipped (AI hallucinates with thin packs)
    """
    partial: dict = {
        "data_available": True,
        "_context_mode": "PARTIAL",
        "sport": sport,
        "league": league,
        "home_team": {
            "team_name": home,
            "team_key": home_key or home.lower().replace(" ", "_"),
        },
        "away_team": {
            "team_name": away,
            "team_key": away_key or away.lower().replace(" ", "_"),
        },
    }
    # Try to enrich with Elo data (rugby/cricket have Elo coverage)
    try:
        from scrapers.elo.elo_helper import get_elo_probability
        hk = home_key or home.lower().replace(" ", "_")
        ak = away_key or away.lower().replace(" ", "_")
        elo_result = get_elo_probability(hk, ak, sport, require_confidence="low", league=league)
        if elo_result:
            partial["elo_home_prob"] = elo_result.get("home_win") or elo_result.get("elo_prob")
            partial["elo_diff"] = elo_result.get("elo_diff")
            partial["elo_confidence"] = elo_result.get("confidence")
    except Exception:
        pass
    return partial


def _context_fetch_attempts(
    home: str,
    away: str,
    *,
    home_key: str = "",
    away_key: str = "",
) -> list[tuple[str, str]]:
    """Build one or two deterministic pregen-only context lookup attempts."""
    attempts: list[tuple[str, str]] = []

    primary = (
        _canonical_context_team_key(home_key or home),
        _canonical_context_team_key(away_key or away),
    )
    if all(primary):
        attempts.append(primary)

    fallback = (
        home.lower().replace(" ", "_"),
        away.lower().replace(" ", "_"),
    )
    if all(fallback) and fallback not in attempts:
        attempts.append(fallback)

    return attempts


async def _get_match_context(
    home: str,
    away: str,
    league: str,
    sport: str,
    *,
    home_key: str = "",
    away_key: str = "",
    match_date: str = "",
) -> dict:
    """Fetch match context: API-Football primary (soccer), ESPN fallback.

    CLEAN-DATA-v2: Uses sport-specific fetchers as primary data source.
    Falls back to ESPN when fetcher unavailable or returns thin context.
    """
    # ── Primary: Sport-specific fetcher (API-Football for soccer; SportMonks for cricket;
    #    API-Sports for MMA/Boxing/Rugby) ─────
    if sport in ("soccer", "football", "cricket", "rugby", "mma", "boxing", "combat"):
        try:
            from fetchers import get_fetcher
            from fetchers.base_fetcher import ensure_schema

            fetcher_sport = "soccer" if sport in ("soccer", "football") else sport
            fetcher = get_fetcher(fetcher_sport)
            live_safe, scraper_pid = _pregen_enrichment_live_safe()
            if live_safe:
                log.info(
                    "Scraper writer lock active (PID %s) — read-only enrichment for %s vs %s",
                    scraper_pid, home, away,
                )

            # Build match_key for cache lookup
            h_key = _canonical_context_team_key(home_key or home) or home.lower().replace(" ", "_")
            a_key = _canonical_context_team_key(away_key or away) or away.lower().replace(" ", "_")
            match_key = f"{h_key}_vs_{a_key}"

            ctx = await fetcher.fetch_and_cache(
                match_key=match_key,
                home_team=h_key,
                away_team=a_key,
                league=league,
                sport=fetcher_sport,
                live_safe=live_safe,
            )
            if ctx and not _needs_pregen_context_lift(ctx):
                log.info("%s fetcher context hit for %s vs %s", fetcher_sport, home, away)
                return ctx
            log.info("%s fetcher context thin for %s vs %s — trying ESPN fallback", fetcher_sport, home, away)
        except Exception as exc:
            log.warning("Fetcher failed for %s vs %s: %s — falling back to ESPN", home, away, exc)

    # ── Fallback: ESPN (all sports) ───────────────────────────────────
    try:
        from scrapers.match_context_fetcher import get_match_context

        attempts = _context_fetch_attempts(home, away, home_key=home_key, away_key=away_key)
        last_ctx: dict = {}
        for idx, (home_candidate, away_candidate) in enumerate(attempts):
            live_safe, scraper_pid = _pregen_enrichment_live_safe()
            if live_safe:
                log.info(
                    "Scraper writer lock active (PID %s) — using read-only enrichment for %s vs %s",
                    scraper_pid,
                    home,
                    away,
                )
            ctx = await get_match_context(
                home_team=home_candidate,
                away_team=away_candidate,
                league=league,
                sport=sport,
                match_date=match_date,
                live_safe=live_safe,
            )
            last_ctx = ctx
            if not _needs_pregen_context_lift(ctx):
                return ctx
            if idx + 1 < len(attempts):
                log.info(
                    "Pregen thin-context lift retry for %s vs %s via %s vs %s",
                    home,
                    away,
                    home_candidate,
                    away_candidate,
                )
        # VERDICT-FIX Fix 3: If all ESPN attempts still thin, build partial context from Elo/signal data
        if _needs_pregen_context_lift(last_ctx):
            partial = _build_partial_context(home, away, league, sport, home_key=home_key, away_key=away_key)
            if partial:
                log.warning(
                    "W84_PARTIAL_CONTEXT league=%s sport=%s teams=%s vs %s reason=THIN_ESPN",
                    league, sport, home, away,
                )
                return partial
        return last_ctx
    except Exception as exc:
        log.warning("Match context fetch failed for %s vs %s: %s", home, away, exc)
        return {}


async def _get_enrichment(
    match_id: str, home: str, away: str, league: str, sport: str, commence_time: str,
) -> str:
    """Fetch enrichment data (lineup, injuries)."""
    parts = []
    home_key = home.lower().replace(" ", "_")
    away_key = away.lower().replace(" ", "_")

    # Lineups
    try:
        from scrapers.lineups.lineup_helper import format_lineup_for_narrative
        lineup_text = format_lineup_for_narrative(match_id, home_key, away_key, league)
        if lineup_text:
            parts.append(lineup_text)
    except Exception:
        pass

    return "\n".join(parts) if parts else ""


# ── W69-VERIFY Layer 2: Post-generation cross-check ──

# Regex patterns for extracting factual claims from narratives
# FIX-DROP-SONNET-POLISH-W82-CANONICAL-01: removed _extract_claims +
# _verify_narrative_claims (Layer 2 LLM fact-checker — only fired against
# Sonnet/Haiku polish output) and _shadow_token_count (LLM token telemetry
# helper). The W82 baseline is deterministic Python; nothing to fact-check.


# ── BASELINE-FIX: Data Source Alignment ──
# Snapshot-only baselines may still refresh bookmaker+price from odds.db. For
# real edge_results rows, FIX-VERDICT-CORPUS-ARCHITECTURE-HARDENING-01 pins the
# verdict bookmaker+price to the frozen algo recommendation in edge_results.

_VALID_BK_DISPLAY = {
    "hollywoodbets", "betway", "supabets", "sportingbet",
    "gbets", "world sports betting", "playabets", "supersportbet",
}


def _log_integrity_event(signal: str, fixture_id: str = "", reason: str = "") -> None:
    """Write a raw integrity event row to narrative_integrity_log in odds.db.

    MONITOR-P0-FIX-01: Called at verdict quality / manager name rejection sites
    to instrument validator_reject_rate, banned_template_hit_rate, and
    manager_name_fabrication_attempts signals.
    Best-effort — swallows all exceptions silently (never blocks generation).
    """
    try:
        from scripts.monitor_narrative_integrity import write_integrity_event
        write_integrity_event(signal, fixture_id=fixture_id, reason=reason)
    except Exception as _lie:
        log.debug("_log_integrity_event: %s/%s failed: %s", signal, fixture_id, _lie)


async def _refresh_edge_from_odds_db(edge: dict) -> dict:
    """Refresh bookmaker+price from odds.db for non-edge snapshot baselines.

    FIX-VERDICT-CORPUS-ARCHITECTURE-HARDENING-01:
    Positive edge_results rows are already frozen recommendations. Re-deriving
    their bookmaker from latest odds_snapshots/odds service can make the
    verdict cite a different SA book than edge_results.bookmaker, so this helper
    returns those rows unchanged.

    Updates edge dict in place and returns it.
    """
    if not edge.get("is_non_edge", False) and edge.get("best_bookmaker") and edge.get("best_odds"):
        return edge

    match_key = edge.get("match_key", "")
    outcome = edge.get("recommended_outcome") or edge.get("outcome", "")
    if not match_key or not outcome:
        return edge

    try:
        from services.odds_service import get_best_odds
        best = await get_best_odds(match_key)
        outcomes = best.get("outcomes", {})
        outcome_data = outcomes.get(outcome, {})
        if not outcome_data:
            log.debug("BASELINE-FIX: no odds.db data for %s outcome=%s", match_key, outcome)
            return edge

        fresh_odds = outcome_data.get("best_odds", 0)
        fresh_bk_key = outcome_data.get("best_bookmaker", "")

        if fresh_odds <= 1.0 or not fresh_bk_key:
            return edge

        fresh_bk_display = bot._display_bookmaker_name(fresh_bk_key)

        # Recalculate EV with the fresh price
        fair_prob = edge.get("fair_probability") or edge.get("fair_prob", 0)
        if fair_prob and fair_prob > 0:
            fresh_ev = round((fresh_odds * fair_prob - 1) * 100, 2)
        else:
            fresh_ev = edge.get("edge_pct", 0)

        old_bk = edge.get("best_bookmaker", "?")
        old_odds = edge.get("best_odds", 0)
        if old_bk != fresh_bk_display or abs(old_odds - fresh_odds) > 0.005:
            log.info(
                "BASELINE-FIX: refreshed %s: %s@%.2f → %s@%.2f (EV %.1f%% → %.1f%%)",
                match_key, old_bk, old_odds, fresh_bk_display, fresh_odds,
                edge.get("edge_pct", 0), fresh_ev,
            )
        edge["best_odds"] = fresh_odds
        edge["best_bookmaker"] = fresh_bk_display
        edge["edge_pct"] = fresh_ev
        edge["ev"] = fresh_ev
        # Store the raw key for downstream code that may need it
        edge["best_bookmaker_key"] = fresh_bk_key
    except Exception as exc:
        log.warning("BASELINE-FIX: failed to refresh odds for %s: %s", match_key, exc)

    return edge


def _verdict_bookmaker_aligned(narrative: str, bk_display: str, odds: float) -> bool:
    """Check that the verdict section references the correct bookmaker+price.

    Returns True if the verdict contains both the expected bookmaker name and
    the expected odds value (within 0.03 tolerance).
    """
    if not narrative or not bk_display:
        return True  # Nothing to check
    verdict_start = narrative.find("\U0001f3c6")  # 🏆
    if verdict_start == -1:
        return True  # No verdict section — nothing to misalign
    verdict_text = narrative[verdict_start:]
    verdict_lower = verdict_text.lower()

    # Check bookmaker name present
    if bk_display.lower() not in verdict_lower:
        return False

    # Check odds value present (within 0.03 tolerance)
    if odds and odds > 1.0:
        odds_str = f"{odds:.2f}"
        if odds_str in verdict_text:
            return True
        # Tolerance check: extract all decimal numbers from verdict
        import re as _re
        found_prices = _re.findall(r'\d+\.\d{2}', verdict_text)
        return any(abs(float(p) - odds) <= 0.03 for p in found_prices)

    return True


def _realign_verdict_bookmaker(
    narrative: str,
    correct_bk: str,
    correct_odds: float,
    all_bk_displays: set[str] | None = None,
) -> str:
    """Replace wrong bookmaker+price in verdict section with correct values.

    Scans the verdict section for any SA bookmaker display name that doesn't
    match correct_bk and replaces it, along with the adjacent price.
    """
    if not narrative or not correct_bk or not correct_odds:
        return narrative
    verdict_start = narrative.find("\U0001f3c6")  # 🏆
    if verdict_start == -1:
        return narrative

    import re as _re

    verdict_section = narrative[verdict_start:]
    prefix = narrative[:verdict_start]

    bk_names = all_bk_displays or {
        "Hollywoodbets", "Betway", "SupaBets", "Sportingbet",
        "GBets", "World Sports Betting", "PlayaBets", "SuperSportBet",
    }
    correct_odds_str = f"{correct_odds:.2f}"

    fixed = verdict_section
    for bk_name in bk_names:
        if bk_name.lower() == correct_bk.lower():
            continue
        if bk_name.lower() not in fixed.lower():
            continue
        # Replace patterns: "BkName @ X.XX", "at X.XX (BkName)", "at X.XX with BkName",
        # "X.XX (BkName)", "(BkName @ X.XX)", "with BkName"
        # Use case-insensitive replacement of the bookmaker name
        bk_pattern = _re.escape(bk_name)
        fixed = _re.sub(bk_pattern, correct_bk, fixed, flags=_re.IGNORECASE)

    # Now fix any remaining wrong price adjacent to the correct bookmaker
    # Pattern: "correct_bk @ X.XX" or "X.XX (correct_bk)" etc.
    bk_esc = _re.escape(correct_bk)
    # Replace "BK @ WRONG_PRICE" with "BK @ CORRECT_PRICE"
    fixed = _re.sub(
        rf'({bk_esc}\s*@\s*)\d+\.\d{{2}}',
        rf'\g<1>{correct_odds_str}',
        fixed,
        flags=_re.IGNORECASE,
    )
    # Replace "at WRONG_PRICE (BK)" or "at WRONG_PRICE with BK"
    fixed = _re.sub(
        rf'(at\s+)\d+\.\d{{2}}(\s*(?:\(|with)\s*{bk_esc})',
        rf'\g<1>{correct_odds_str}\2',
        fixed,
        flags=_re.IGNORECASE,
    )
    # Replace "WRONG_PRICE (BK)"
    fixed = _re.sub(
        rf'\d+\.\d{{2}}(\s*\(\s*{bk_esc}\s*\))',
        rf'{correct_odds_str}\1',
        fixed,
        flags=_re.IGNORECASE,
    )

    return prefix + fixed


def _raw_outcome_from_serving_tip(tip: dict) -> str:
    """Convert live serving labels back into edge outcome keys."""
    outcome = str(tip.get("outcome") or "").strip().lower()
    home = str(tip.get("home_team") or "").strip().lower()
    away = str(tip.get("away_team") or "").strip().lower()
    if outcome == "draw":
        return "draw"
    if outcome and outcome == home:
        return "home"
    if outcome and outcome == away:
        return "away"
    return outcome or "home"


def _normalise_outcome_label(outcome: str, home_team: str = "", away_team: str = "") -> str:
    """Normalise team-name labels and raw outcome values to home/away/draw keys."""
    value = str(outcome or "").strip().lower()
    if not value:
        return ""

    if value in {"home", "away", "draw"}:
        return value

    home = str(home_team or "").strip().lower()
    away = str(away_team or "").strip().lower()
    if value == home:
        return "home"
    if value == away:
        return "away"
    return value


def _edge_from_serving_tip(tip: dict) -> dict | None:
    """Rebuild an edge-shaped dict from the live edge_results serving row."""
    match_key = tip.get("match_id") or tip.get("event_id") or ""
    if not match_key:
        return None

    home = tip.get("home_team", "")
    away = tip.get("away_team", "")
    raw_outcome = _raw_outcome_from_serving_tip(tip)
    tip_for_edge = dict(tip)
    tip_for_edge["outcome"] = raw_outcome
    tip_for_edge["bookie"] = tip.get("bookmaker", tip.get("bookie", "?"))

    edge_data = bot._extract_edge_data([tip_for_edge], home_team=home, away_team=away)
    league = tip.get("league_key") or edge_data.get("league") or ""
    movement_direction = edge_data.get("movement_direction", "")
    tipster_against = edge_data.get("tipster_against", 0)
    market_agreement = float(edge_data.get("market_agreement", 0) or 0) / 100.0
    signals = {}
    if movement_direction:
        signals["movement"] = {"direction": movement_direction}
    if tipster_against:
        signals["tipster"] = {"against_count": tipster_against}
    if market_agreement:
        signals["market_agreement"] = {"score": market_agreement}

    return {
        "match_key": match_key,
        "home_team": home,
        "away_team": away,
        "league": league,
        "sport": tip.get("sport_key", config.LEAGUE_SPORT.get(league, "soccer")),
        "recommended_outcome": raw_outcome,
        "outcome": raw_outcome,
        "best_odds": edge_data.get("best_odds", tip.get("recommended_odds", tip.get("odds", 0))),
        "best_bookmaker": edge_data.get("best_bookmaker", tip.get("recommended_bookmaker", tip.get("bookmaker", "?"))),
        "best_bookmaker_key": tip.get("recommended_bookmaker_key", tip.get("bookmaker_key", "")),
        "edge_pct": edge_data.get("edge_pct", tip.get("ev", 0)),
        "fair_probability": edge_data.get("fair_prob", 0.0),
        "composite_score": edge_data.get("composite_score", tip.get("edge_score", 0)),
        "confirming_signals": edge_data.get("confirming_signals", 0),
        "contradicting_signals": edge_data.get("contradicting_signals", 0),
        "bookmaker_count": edge_data.get("bookmaker_count", 0),
        "stale_minutes": edge_data.get("stale_minutes", 0),
        "signals": signals,
        "tier": tip.get("display_tier") or tip.get("edge_rating") or "bronze",
        "sharp_source": tip.get("sharp_source", "edge_results"),
        "commence_time": tip.get("commence_time", ""),
    }


def _load_shadow_pregen_edges(limit: int = 100) -> list[dict]:
    """Shadow pregen must use the same authoritative edge_results source as serving."""
    try:
        serving_tips = bot._load_tips_from_edge_results(limit=limit, skip_punt_filter=True)
    except Exception as exc:
        log.error("Failed to load live edge_results tips for shadow pregen: %s", exc)
        return []

    edges: list[dict] = []
    for tip in serving_tips:
        edge = _edge_from_serving_tip(tip)
        if not edge:
            continue
        if not edge.get("best_odds") or edge.get("edge_pct", 0) <= 0:
            continue
        edges.append(edge)
    return edges


def _infer_commence_time_from_match_key(match_key: str) -> str | None:
    """Infer a stable kickoff placeholder from the match-key date suffix."""
    m = re.search(r"(\d{4}-\d{2}-\d{2})$", str(match_key or ""))
    if not m:
        return None
    return f"{m.group(1)}T00:00:00+00:00"


def _pick_baseline_outcome(odds_data: dict) -> tuple[str, dict] | tuple[None, None]:
    """Choose a deterministic baseline outcome from current odds."""
    outcomes = odds_data.get("outcomes") or {}
    ranked: list[tuple[float, str, dict]] = []
    for outcome_key, outcome_data in outcomes.items():
        best_odds = float(outcome_data.get("best_odds") or 0.0)
        if best_odds > 1.0:
            ranked.append((best_odds, outcome_key, outcome_data))
    if not ranked:
        return None, None
    ranked.sort(key=lambda item: (item[0], item[1]))
    _best_odds, selected_key, selected_data = ranked[0]
    return selected_key, selected_data


def _baseline_composite_score(bookmaker_count: int) -> float:
    """Estimate a stable composite from market coverage for no-edge baselines."""
    return float(min(60, 44 + max(0, bookmaker_count) * 4))


def _build_baseline_edge_from_snapshot_row(row: dict) -> dict | None:
    """Build a template-only baseline edge for matches with no live edge row."""
    from services.odds_service import get_best_odds

    match_key = row.get("match_key") or row.get("match_id") or ""
    commence_time = row.get("commence_time")
    if not match_key or not commence_time:
        return None

    odds_data = asyncio.run(get_best_odds(match_key, row.get("market_type") or "1x2"))
    outcome_key, outcome_data = _pick_baseline_outcome(odds_data)
    if not outcome_key or not outcome_data:
        return None

    all_bookmakers = outcome_data.get("all_bookmakers") or {}
    clean_prices = [float(price) for price in all_bookmakers.values() if price and float(price) > 1.0]
    fair_probability = (
        sum((1.0 / price) for price in clean_prices) / len(clean_prices)
        if clean_prices else 0.0
    )
    best_odds = float(outcome_data.get("best_odds") or 0.0)
    raw_edge_pct = round((fair_probability * best_odds - 1.0) * 100.0, 1) if fair_probability and best_odds > 0 else 0.0
    bookmaker_count = int(odds_data.get("bookmaker_count") or len({bk for bk in all_bookmakers if bk}) or 0)

    return {
        "match_key": match_key,
        "home_team": bot._display_team_name(odds_data.get("home_team") or row.get("home_team") or ""),
        "away_team": bot._display_team_name(odds_data.get("away_team") or row.get("away_team") or ""),
        "league": row.get("league") or odds_data.get("league") or "",
        "sport": row.get("sport") or "soccer",
        "recommended_outcome": outcome_key,
        "outcome": outcome_key,
        "best_odds": best_odds,
        "best_bookmaker": bot._display_bookmaker_name(outcome_data.get("best_bookmaker") or ""),
        "best_bookmaker_key": outcome_data.get("best_bookmaker") or "",
        "edge_pct": min(raw_edge_pct, 0.0),
        "ev": min(raw_edge_pct, 0.0),
        "fair_probability": fair_probability,
        "composite_score": _baseline_composite_score(bookmaker_count),
        "confirming_signals": 0,
        "contradicting_signals": 0,
        "bookmaker_count": bookmaker_count,
        "stale_minutes": 0,
        "signals": {},
        "tier": "bronze",
        "sharp_source": "odds_snapshots",
        "commence_time": commence_time,
        "narrative_source_hint": "baseline_no_edge",
        "is_non_edge": True,
    }


def _load_snapshot_baseline_edges(limit: int = 100) -> list[dict]:
    """Find upcoming matches in odds_snapshots that never made it into edge_results."""
    try:
        from scrapers.db_connect import connect_odds_db as _connect_odds_db
        from services.odds_service import LEAGUE_MARKET_TYPE
    except Exception as exc:
        log.error("Failed to import odds DB connector for baseline pregen: %s", exc)
        return []

    rows: list[dict] = []
    conn = _connect_odds_db(str(SCRAPERS_ROOT / "odds.db"))
    conn.row_factory = lambda cursor, row: dict(zip([col[0] for col in cursor.description], row))
    try:
        today = time.strftime("%Y-%m-%d")
        query = """
            SELECT
                os.match_id AS match_key,
                os.home_team,
                os.away_team,
                os.league,
                os.sport,
                os.market_type
            FROM odds_snapshots os
            LEFT JOIN edge_results er
              ON er.match_key = os.match_id
             AND er.result IS NULL
            WHERE er.match_key IS NULL
              AND substr(os.match_id, -10) >= ?
            GROUP BY os.match_id, os.home_team, os.away_team, os.league, os.sport, os.market_type
            ORDER BY substr(os.match_id, -10) ASC, MAX(os.scraped_at) DESC
            LIMIT ?
        """
        raw_rows = conn.execute(query, (today, limit)).fetchall()
        seen: set[str] = set()
        for row in raw_rows:
            match_key = row.get("match_key") or ""
            if not match_key or match_key in seen:
                continue
            expected_market_type = LEAGUE_MARKET_TYPE.get(row.get("league") or "", "1x2")
            if (row.get("market_type") or "") != expected_market_type:
                continue
            seen.add(match_key)
            row["commence_time"] = _infer_commence_time_from_match_key(match_key)
            if not row["commence_time"]:
                continue
            rows.append(row)
    except Exception as exc:
        log.error("Snapshot baseline discovery failed: %s", exc)
        rows = []
    finally:
        conn.close()

    baseline_edges: list[dict] = []
    for row in rows:
        try:
            edge = _build_baseline_edge_from_snapshot_row(row)
        except Exception as exc:
            log.warning("Baseline edge build failed for %s: %s", row.get("match_key", "?"), exc)
            continue
        if edge and edge.get("best_odds"):
            baseline_edges.append(edge)
    return baseline_edges


# BUILD-ENRICH-09: Fixture table sources for pregen discovery (beyond odds_snapshots).
# Each entry describes how to query a specific fixture table.
_FIXTURE_DISCOVERY_SOURCES = [
    {
        "table": "sportmonks_fixtures",
        "sport": "cricket",
        "home_col": "home_team",
        "away_col": "away_team",
        "league_col": "league_name",
        "date_col": "match_date",
        "status_col": "status",
    },
    {
        "table": "mma_fixtures",
        "sport": "mma",
        "home_col": "fighter1_name",
        "away_col": "fighter2_name",
        "league_col": "event_slug",
        "date_col": "fight_date",
        "status_col": "status",
    },
    {
        "table": "rugby_fixtures",
        "sport": "rugby",
        "home_col": "home_team",
        "away_col": "away_team",
        "league_col": "league_name",
        "date_col": "match_date",
        "status_col": "status",
    },
]

_FIXTURE_TERMINAL_STATUSES = {"Finished", "Cancelled"}


# FIX-PREGEN-EDGE-RESULTS-COUPLING-01 (locked 2026-04-28).
# Pregen writes only for matches that already have an unsettled edge_results row
# (the deeplink resolver requires presence in edge_results to serve a card).
# The allowlist is an explicit escape valve for warm-coverage cases where we
# want pregen to seed narrative_cache for an entire league regardless of edge
# presence (e.g. league-wide preview content). Default empty: zero ghost-cache
# writes, full intersection coupling.
_PREGEN_WARM_COVERAGE_ALLOWLIST: frozenset[str] = frozenset()


def _load_unsettled_edge_match_keys(db_path: str) -> set[str]:
    """Return distinct match_keys with an unsettled edge_results row.

    Mirrors the deeplink resolver's preference (`ORDER BY result IS NULL DESC`)
    by selecting only rows where result IS NULL. Returns an empty set on any
    DB error so the caller can fall through to the allowlist branch and never
    crash the pregen sweep.
    """
    try:
        from scrapers.db_connect import connect_odds_db as _connect_odds_db
        conn = _connect_odds_db(db_path)
        try:
            rows = conn.execute(
                "SELECT DISTINCT match_key FROM edge_results "
                "WHERE result IS NULL AND match_key IS NOT NULL"
            ).fetchall()
        finally:
            conn.close()
        return {r[0] for r in rows if r and r[0]}
    except Exception as exc:
        log.warning("_load_unsettled_edge_match_keys: query failed: %s", exc)
        return set()


def _fixture_home_prefix(key: str) -> str:
    """First two underscore-separated words of a normalised team key.

    Used for fuzzy deduplication: 'royal_challengers_bengaluru' and
    'royal_challengers_bangalore' both return 'royal_challengers', which
    correctly identifies them as the same team despite a city rename.
    """
    parts = key.split("_")[:2]
    return "_".join(parts) if len(parts) == 2 else key


def discover_pregen_targets(
    db_path: str | None = None,
    hours_ahead: int = 48,
    hours_ahead_premium: int = 240,
) -> list[dict]:
    """Discover upcoming matches from ALL fixture sources for pregen.

    BUILD-ENRICH-09: Scans sportmonks_fixtures (cricket), mma_fixtures (MMA),
    rugby_fixtures (rugby), and odds_snapshots (soccer/existing) for matches
    with commence_time in the next *hours_ahead* hours.

    FIX-AI-BREAKDOWN-COVERAGE-01 (2026-04-25): Diamond/Gold edges get the full
    Edge Picks lookahead horizon (hours_ahead_premium, default 240h = 10 days)
    so AI Breakdowns are pre-baked for every premium-tier match a user can see.
    Silver/Bronze edges use the standard hours_ahead window (48h). Fixtures
    with no edge_results row use the standard window. Closes Bible G14.

    Returns a unified list of dicts:
        {match_key, sport, home_team, away_team, league, commence_time, source_table}

    Deduplication rules:
    - odds_snapshots version preferred (always scanned first).
    - Exact match_key collision → skip fixture-table entry.
    - Fuzzy collision (same date + league + home team prefix) → skip fixture-table entry.

    Matches with NULL commence_time are skipped.
    Missing fixture tables are handled gracefully (logged as WARNING, skipped).
    """
    try:
        from scrapers.db_connect import connect_odds_db as _connect_odds_db
        from scrapers.utils.team_mapper import normalise_team as _norm_team
    except Exception as exc:
        log.error("discover_pregen_targets: import failed: %s", exc)
        return []

    path = db_path or str(SCRAPERS_ROOT / "odds.db")
    now = datetime.now(SAST)
    window_start_date = now.strftime("%Y-%m-%d")
    # Scan the wider premium window; standard-window filtering applied after discovery.
    _effective_max_hours = max(hours_ahead, hours_ahead_premium)
    window_end_date = (now + timedelta(hours=_effective_max_hours)).strftime("%Y-%m-%d")
    # Cutoff timestamps for tier-aware horizon filtering (applied post-discovery).
    _standard_cutoff = (now + timedelta(hours=hours_ahead)).strftime("%Y-%m-%d")
    _premium_cutoff = (now + timedelta(hours=hours_ahead_premium)).strftime("%Y-%m-%d")

    targets: list[dict] = []
    # Exact dedup by match_key
    seen_keys: set[str] = set()
    # Fuzzy dedup: (date_10, league_normalised, home_prefix_2) for odds_snapshots entries
    _seen_fuzzy: set[tuple] = set()

    # ── Step 1: odds_snapshots (soccer/existing — always first for dedup priority) ──
    try:
        conn = _connect_odds_db(path)
        conn.row_factory = lambda cursor, row: dict(
            zip([col[0] for col in cursor.description], row)
        )
        rows = conn.execute(
            """
            SELECT match_id, home_team, away_team, league, sport
            FROM odds_snapshots
            WHERE substr(match_id, -10) >= ?
              AND substr(match_id, -10) <= ?
            GROUP BY match_id
            ORDER BY substr(match_id, -10) ASC
            """,
            (window_start_date, window_end_date),
        ).fetchall()
        for row in rows:
            mkey = (row.get("match_id") or "").strip()
            if not mkey or mkey in seen_keys:
                continue
            commence = _infer_commence_time_from_match_key(mkey)
            if not commence:
                continue
            targets.append(
                {
                    "match_key": mkey,
                    "sport": row.get("sport") or "soccer",
                    "home_team": row.get("home_team") or "",
                    "away_team": row.get("away_team") or "",
                    "league": row.get("league") or "",
                    "commence_time": commence,
                    "source_table": "odds_snapshots",
                }
            )
            seen_keys.add(mkey)
            # Register for fuzzy dedup: other sources skip on (date, league, home_prefix) collision
            date_10 = mkey[-10:] if len(mkey) >= 10 else ""
            league_norm = (row.get("league") or "").lower().replace(" ", "_")
            home_prefix = _fixture_home_prefix(row.get("home_team") or "")
            if date_10 and league_norm:
                _seen_fuzzy.add((date_10, league_norm, home_prefix))
        conn.close()
    except Exception as exc:
        log.warning("discover_pregen_targets: odds_snapshots scan failed: %s", exc)

    # ── Step 2: fixture tables (cricket, MMA, rugby) ──
    for source in _FIXTURE_DISCOVERY_SOURCES:
        table = source["table"]
        sport = source["sport"]
        home_col = source["home_col"]
        away_col = source["away_col"]
        league_col = source["league_col"]
        date_col = source["date_col"]
        status_col = source["status_col"]

        try:
            conn = _connect_odds_db(path)
            conn.row_factory = lambda cursor, row: dict(
                zip([col[0] for col in cursor.description], row)
            )
            rows = conn.execute(
                f"""
                SELECT {home_col}, {away_col}, {league_col}, {date_col}
                FROM {table}
                WHERE substr({date_col}, 1, 10) >= ?
                  AND substr({date_col}, 1, 10) <= ?
                  AND {status_col} NOT IN ({",".join("?" * len(_FIXTURE_TERMINAL_STATUSES))})
                  AND {home_col} IS NOT NULL
                  AND {away_col} IS NOT NULL
                  AND {date_col} IS NOT NULL
                """,
                (window_start_date, window_end_date, *_FIXTURE_TERMINAL_STATUSES),
            ).fetchall()
            conn.close()
        except Exception as exc:
            log.warning(
                "discover_pregen_targets: %s scan failed (table may not exist): %s",
                table,
                exc,
            )
            continue

        for row in rows:
            home = (row.get(home_col) or "").strip()
            away = (row.get(away_col) or "").strip()
            league = (row.get(league_col) or "").strip()
            raw_date = str(row.get(date_col) or "")
            date_10 = raw_date[:10]

            if not home or not away or not date_10:
                continue

            h_key = _norm_team(home)
            a_key = _norm_team(away)
            mkey = f"{h_key}_vs_{a_key}_{date_10}"

            # Exact dedup
            if mkey in seen_keys:
                continue

            # Fuzzy dedup (same date + league + home-team prefix as an odds_snapshots entry)
            league_norm = league.lower().replace(" ", "_")
            home_prefix = _fixture_home_prefix(h_key)
            if (date_10, league_norm, home_prefix) in _seen_fuzzy:
                log.debug(
                    "discover_pregen_targets: fuzzy-dedup %s (date=%s league=%s home_prefix=%s)",
                    mkey,
                    date_10,
                    league_norm,
                    home_prefix,
                )
                continue

            # Build ISO commence_time
            if len(raw_date) >= 16:
                commence = f"{raw_date[:16].replace(' ', 'T')}:00+00:00"
            else:
                commence = f"{date_10}T00:00:00+00:00"

            targets.append(
                {
                    "match_key": mkey,
                    "sport": sport,
                    "home_team": home,
                    "away_team": away,
                    "league": league,
                    "commence_time": commence,
                    "source_table": table,
                }
            )
            seen_keys.add(mkey)

    # BUILD-NARRATIVE-VOICE-01 Fix C: tier-aware horizon filter.
    # Targets within the standard window always pass. Targets in the premium-only
    # band (standard < date <= premium) pass only if they have a Diamond/Gold edge.
    if hours_ahead_premium > hours_ahead:
        # Fetch premium-tier match keys from edge_results (Diamond + Gold).
        _premium_match_keys: set[str] = set()
        try:
            _tc = _connect_odds_db(path)
            _rows = _tc.execute(
                "SELECT DISTINCT match_key FROM edge_results WHERE edge_tier IN ('diamond','gold')"
            ).fetchall()
            _tc.close()
            _premium_match_keys = {r[0] for r in _rows if r[0]}
        except Exception as _exc:
            log.warning("discover_pregen_targets: tier lookup failed (non-fatal): %s", _exc)

        filtered: list[dict] = []
        for target in targets:
            date_10 = target["match_key"][-10:] if len(target["match_key"]) >= 10 else ""
            if date_10 <= _standard_cutoff:
                # Within standard window — always include.
                filtered.append(target)
            elif date_10 <= _premium_cutoff:
                # In premium-only band — include only for Diamond/Gold edges.
                if target["match_key"] in _premium_match_keys:
                    filtered.append(target)
                else:
                    log.debug(
                        "discover_pregen_targets: skipping non-premium target beyond %dh: %s",
                        hours_ahead, target["match_key"],
                    )
        _pre_count = len(targets)
        targets = filtered
        log.info(
            "discover_pregen_targets: tier-aware filter: %d → %d targets "
            "(%d premium-tier fixtures kept beyond %dh window)",
            _pre_count, len(targets),
            sum(1 for t in targets if t["match_key"][-10:] > _standard_cutoff),
            hours_ahead,
        )

    # FIX-PREGEN-EDGE-RESULTS-COUPLING-01: intersect candidate set with edge_results.match_key
    # (unsettled) to prevent ghost-cache writes that fail mechanically at the deeplink resolver.
    # The allowlist (default empty) is an explicit escape valve for warm-coverage cases.
    edge_match_keys = _load_unsettled_edge_match_keys(path)
    _raw_count = len(targets)
    _intersect_kept = sum(1 for t in targets if t["match_key"] in edge_match_keys)
    _allowlist_kept = sum(
        1 for t in targets
        if t["match_key"] not in edge_match_keys
        and (t.get("league") or "") in _PREGEN_WARM_COVERAGE_ALLOWLIST
    )
    targets = [
        t for t in targets
        if t["match_key"] in edge_match_keys
        or (t.get("league") or "") in _PREGEN_WARM_COVERAGE_ALLOWLIST
    ]
    log.info(
        "discover_pregen_targets: edge_results coupling: raw=%d, edge_intersection=%d, "
        "allowlist_kept=%d, final=%d",
        _raw_count, _intersect_kept, _allowlist_kept, len(targets),
    )

    log.info(
        "discover_pregen_targets: %d targets (%d from odds_snapshots, %d from fixture tables)",
        len(targets),
        sum(1 for t in targets if t["source_table"] == "odds_snapshots"),
        sum(1 for t in targets if t["source_table"] != "odds_snapshots"),
    )
    return targets


def _build_fixture_only_edge(target: dict) -> dict:
    """Build a minimal no-odds edge dict from a fixture-discovery target.

    BUILD-ENRICH-09: Used for matches discovered from fixture tables that have no
    SA bookmaker odds yet. The narrative pipeline (NarrativeSpec + _render_baseline)
    handles zero-signal, zero-odds contexts gracefully.
    """
    return {
        "match_key": target["match_key"],
        "home_team": target.get("home_team", ""),
        "away_team": target.get("away_team", ""),
        "league": target.get("league", ""),
        "sport": target.get("sport", "soccer"),
        "commence_time": target.get("commence_time", ""),
        "best_odds": 0.0,
        "ev": 0.0,
        "edge_pct": 0.0,
        "fair_probability": 0.0,
        "composite_score": 0.0,
        "confirming_signals": 0,
        "contradicting_signals": 0,
        "bookmaker_count": 0,
        "stale_minutes": 0,
        "signals": {},
        "tier": "bronze",
        "sharp_source": target.get("source_table", "fixture"),
        "skip_sonnet_polish": target.get("sport", "soccer") not in ("mma", "boxing", "combat", "rugby", "cricket"),
        "narrative_source_hint": "fixture_only",
    }


def _load_pregen_edges(limit: int = 100, sport: str | None = None) -> list[dict]:
    """Load positive-EV live edges plus snapshot-only baseline matches.

    BUILD-ENRICH-09: After loading the existing edge and snapshot sources, also
    discovers matches from fixture tables (rugby_fixtures, mma_fixtures,
    sportmonks_fixtures) that have no SA bookmaker odds yet. These receive
    narrative cards generated from enriched context only (no odds/EV data).
    The existing odds_snapshots discovery path is unchanged (additive only).
    """
    live_edges = _load_shadow_pregen_edges(limit=limit)
    seen = {edge.get("match_key", "") for edge in live_edges if edge.get("match_key")}

    # FIX-PREGEN-EDGE-RESULTS-COUPLING-01: _load_snapshot_baseline_edges()
    # explicitly returns matches in odds_snapshots that have NO unsettled
    # edge_results row (its SQL filters `WHERE er.match_key IS NULL`). Those
    # are exactly the ghost-cache writes the deeplink resolver cannot serve.
    # Drop them here unless their league is in the warm-coverage allowlist;
    # baseline_no_edge cards are still served via the live-tap path
    # (`_generate_narrative_v2(live_tap=True, ctx_data=None, tips=[])`).
    snapshot_edges = _load_snapshot_baseline_edges(limit=limit)
    _snap_raw = len(snapshot_edges)
    snapshot_edges = [
        e for e in snapshot_edges
        if (e.get("league") or "") in _PREGEN_WARM_COVERAGE_ALLOWLIST
    ]
    if _snap_raw and _snap_raw != len(snapshot_edges):
        log.info(
            "_load_pregen_edges: edge_results coupling on snapshot baseline: "
            "%d → %d (allowlist_kept=%d)",
            _snap_raw, len(snapshot_edges), len(snapshot_edges),
        )
    for edge in snapshot_edges:
        match_key = edge.get("match_key", "")
        if match_key and match_key not in seen:
            live_edges.append(edge)
            seen.add(match_key)

    # BUILD-ENRICH-09: Add fixture-table targets not covered by odds_snapshots.
    # discover_pregen_targets() includes odds_snapshots matches first (already in seen)
    # then fixture-table matches — so only the new ones pass the seen check.
    # FIX-AI-BREAKDOWN-COVERAGE-01 (2026-04-25): premium horizon raised 96h → 240h
    # to align with Edge Picks lookahead and close AI Breakdown coverage gap (Bible G14).
    try:
        fixture_targets = discover_pregen_targets(hours_ahead_premium=240)
        fixture_added = 0
        for target in fixture_targets:
            mkey = target.get("match_key", "")
            if mkey and mkey not in seen:
                edge = _build_fixture_only_edge(target)
                live_edges.append(edge)
                seen.add(mkey)
                fixture_added += 1
        if fixture_added:
            log.info(
                "_load_pregen_edges: added %d fixture-only targets from discovery",
                fixture_added,
            )
    except Exception as exc:
        log.warning("_load_pregen_edges: fixture discovery failed (non-fatal): %s", exc)

    if sport:
        def _sport_matches(edge: dict) -> bool:
            sp = (edge.get("sport") or "soccer").lower()
            if sp == sport:
                return True
            # "combat" is a parent category for mma/boxing sub-sports
            if sport in ("mma", "boxing") and sp == "combat":
                league = (edge.get("league") or "").lower()
                return (sport == "mma" and league == "ufc") or (sport == "boxing" and "box" in league)
            return False
        live_edges = [e for e in live_edges if _sport_matches(e)]
    return live_edges[:limit]



# FIX-DROP-SONNET-POLISH-W82-CANONICAL-01: removed _build_minimal_haiku_prompt
# (only used by the now-deleted Haiku non-edge preview path).


# FIX-DROP-SONNET-POLISH-W82-CANONICAL-01: removed _recover_missing_emoji_headers
# and _validate_preview_polish (Haiku polish recovery + non-edge preview validator).


# FIX-DROP-SONNET-POLISH-W82-CANONICAL-01: removed generate_section + generate_and_validate
# (W84 Haiku validator pair — only fired against LLM polish output).


def _is_past_kickoff(match_key: str, cutoff_hours: int = 24) -> bool:
    """Return True if match_key's date suffix is more than cutoff_hours in the past."""
    m = re.search(r"(\d{4}-\d{2}-\d{2})$", str(match_key or ""))
    if not m:
        return False
    try:
        kickoff = datetime.fromisoformat(m.group(1) + "T00:00:00+00:00")
        return (datetime.now(SAST) - kickoff).total_seconds() > cutoff_hours * 3600
    except ValueError:
        return False


# FIX-DROP-SONNET-POLISH-W82-CANONICAL-01: removed Haiku polish fallback,
# premium-tier defer alert constants, thin-evidence directive, and the
# _record_premium_defer / _clear_premium_defer table writers. The new
# pregen path produces W82 baseline for every tier — no defers, no fallbacks.
# gold_verdict_failed_edges table is left in place (cheap, harmless).


async def _generate_one(
    edge: dict,
    sweep_type: str = "full",
) -> dict:
    """Render the W82 deterministic baseline for a single edge and stage cache write data.

    FIX-DROP-SONNET-POLISH-W82-CANONICAL-01: this is now the only narrative
    generation path. Sonnet/Haiku polish has been ripped out — `_render_baseline`
    is canonical for every tier. Returns dict with match_key, success, model, duration.
    """
    t0 = time.time()
    match_key = edge.get("match_key", "")

    # BUILD-PREGEN-KICKOFF-FILTER-01: skip fixtures >24h past kickoff
    if _is_past_kickoff(match_key):
        log.info("PREGEN-SKIP: %s is >24h past kickoff — skipping", match_key)
        return {"match_key": match_key, "success": False, "skipped_past_kickoff": True, "duration": time.time() - t0}
    home = edge.get("home_team", "")
    away = edge.get("away_team", "")
    home_key = ""
    away_key = ""

    # Parse team names from match_key if not provided (edge_v2 dicts omit them)
    parts = match_key.rsplit("_", 1)[0] if "_" in match_key else match_key
    if "_vs_" in parts:
        home_key, away_key = parts.split("_vs_", 1)
        home = home or bot._display_team_name(home_key)
        away = away or bot._display_team_name(away_key)

    league = edge.get("league") or ""
    sport = edge.get("sport", "soccer")
    commence = edge.get("commence_time", "")

    # Refine "combat" to mma/boxing
    if sport == "combat":
        if "ufc" in league.lower():
            sport = "mma"
        elif "box" in league.lower():
            sport = "boxing"

    # BASELINE-FIX: Refresh bookmaker+price from odds.db before building tips/spec.
    edge = await _refresh_edge_from_odds_db(edge)

    # 1. Match context — feeds the NarrativeSpec; not used to call any LLM.
    _mk_date_m = re.search(r"(\d{4}-\d{2}-\d{2})$", match_key)
    _mk_date = _mk_date_m.group(1) if _mk_date_m else ""
    ctx = await _get_match_context(
        home,
        away,
        league,
        sport,
        home_key=home_key,
        away_key=away_key,
        match_date=_mk_date,
    )
    evidence_pack = await build_evidence_pack(
        match_key,
        edge,
        sport,
        league,
        espn_ctx=ctx,
        home_team=home,
        away_team=away,
    )
    evidence_json = serialise_evidence_pack(evidence_pack)

    # NARRATIVE-ACCURACY-01 Rule 1: pre-compute derived claims (kept for cache schema parity).
    _derived_claims: dict = {}
    try:
        from narrative_spec import build_derived_claims as _bdc
        _ctx_h = (ctx or {}).get("home_team", {}) if isinstance((ctx or {}).get("home_team"), dict) else {}
        _ctx_a = (ctx or {}).get("away_team", {}) if isinstance((ctx or {}).get("away_team"), dict) else {}
        _derived_claims = _bdc(_ctx_h, _ctx_a, sport)
    except Exception as _dc_err:
        log.debug("ACCURACY-01: build_derived_claims failed: %s", _dc_err)

    # Compute coverage_json for narrative_cache persistence (COVERAGE-GATE-BUILD)
    _coverage_json = None
    try:
        from evidence_pack import serialise_coverage_metrics as _scm
        _cm = getattr(evidence_pack, "coverage_metrics", None)
        if _cm is not None:
            _coverage_json = _scm(_cm)
    except Exception as _cov_err:
        log.debug("coverage_json computation failed: %s", _cov_err)

    # 2. Build tips from edge data
    tips = []
    ev = bot._normalise_edge_pct_contract(edge.get("ev"), edge.get("edge_pct", 0))
    fair_prob = edge.get("fair_prob") or edge.get("fair_probability", 0)
    _bk_key = edge.get("best_bookmaker_key", "") or edge.get("bookmaker_key", "")
    tips.append({
        "outcome": edge.get("recommended_outcome") or edge.get("outcome", "?"),
        "odds": edge.get("best_odds", 0),
        "bookie": edge.get("best_bookmaker", "?"),
        "bookmaker": edge.get("best_bookmaker", "?"),
        "bookmaker_key": _bk_key,
        "odds_by_bookmaker": {_bk_key: float(edge.get("best_odds", 0))} if _bk_key and edge.get("best_odds", 0) > 0 else {},
        "ev": ev,
        "prob": round(fair_prob * 100, 1) if fair_prob else 0,
        "edge_v2": edge,
        "home_team": home,
        "away_team": away,
        "edge_tier": edge.get("edge_tier") or edge.get("tier", "bronze"),
        "display_tier": edge.get("edge_tier") or edge.get("tier", "bronze"),
        "recommended_odds": edge.get("best_odds", 0),
        "recommended_bookmaker": edge.get("best_bookmaker", "?"),
        "recommended_bookmaker_key": _bk_key,
    })

    # 3. Build edge_data for NarrativeSpec
    _pregen_sigs = edge.get("signals", {})
    _pregen_outcome_raw = edge.get("recommended_outcome") or edge.get("outcome", "?")
    _pregen_edge_data = {
        "home_team": home,
        "away_team": away,
        "league": league,
        "best_bookmaker": edge.get("best_bookmaker", "?"),
        "best_odds": edge.get("best_odds", 0),
        "edge_pct": ev,
        "outcome": _pregen_outcome_raw,
        "outcome_team": home if _pregen_outcome_raw == "home" else (
            away if _pregen_outcome_raw == "away" else _pregen_outcome_raw
        ),
        "confirming_signals": edge.get("confirming_signals", 0),
        "composite_score": edge.get("composite_score", 0),
        "bookmaker_count": edge.get("bookmaker_count", 0),
        "market_agreement": _pregen_sigs.get("market_agreement", {}).get("score", 0) * 100
            if isinstance(_pregen_sigs.get("market_agreement"), dict) else 0,
        "stale_minutes": edge.get("stale_minutes", 0),
        "movement_direction": _pregen_sigs.get("movement", {}).get("direction", ""),
        "tipster_against": _pregen_sigs.get("tipster", {}).get("against_count", 0),
        "edge_tier": edge.get("edge_tier") or edge.get("tier", "bronze"),
    }

    # BUILD-PREGEN-STUB-GATE-01: Skip pregen when edge_data sentinels are unresolved.
    if not edge.get("is_non_edge", False):
        _gate_outcome = _pregen_edge_data.get("outcome", "")
        _gate_odds = _pregen_edge_data.get("best_odds", 0) or 0
        _gate_bookmaker = _pregen_edge_data.get("best_bookmaker", "")
        if (
            _gate_outcome in ("", "?")
            or not _gate_odds
            or _gate_bookmaker in ("", "?")
        ):
            log.warning(
                "PREGEN SKIP: incomplete edge_data for %s "
                "(outcome=%r, odds=%r, bookmaker=%r)",
                match_key, _gate_outcome, _gate_odds, _gate_bookmaker,
            )
            return {
                "match_key": match_key,
                "success": False,
                "skipped_incomplete": True,
                "duration": time.time() - t0,
            }

    # 4. NarrativeSpec → deterministic baseline (W82 canonical, single path)
    narrative = ""
    spec = None
    narrative_source = NARRATIVE_SOURCE_LABEL  # always "w82"
    _is_non_edge = edge.get("is_non_edge", False)
    served_model = "baseline"
    try:
        from narrative_spec import build_narrative_spec, _render_baseline
        spec = build_narrative_spec(ctx, _pregen_edge_data, tips, sport)
        narrative = _render_baseline(spec)
        narrative = _sanitise_jargon(narrative)
        narrative = _apply_sport_subs(narrative, sport)
        narrative = _final_polish(narrative, _pregen_edge_data)
        log.info("Pregen W82-CANONICAL: baseline rendered for %s", match_key)
    except Exception:
        _ctx_home = (ctx or {}).get("home", {}) if ctx else {}
        _ctx_away = (ctx or {}).get("away", {}) if ctx else {}
        log.exception(
            "PREGEN failed: match_key=%s sport=%s league=%s "
            "home_record_type=%s away_record_type=%s",
            match_key,
            sport,
            league,
            type(_ctx_home.get("record", "")).__name__,
            type(_ctx_away.get("record", "")).__name__,
        )
        narrative = ""

    # H2H injection on the W82 baseline (only if not already present from _h2h_bridge).
    if narrative and evidence_pack is not None and spec is not None:
        _spec_h2h = getattr(spec, "h2h_summary", "") or ""
        _h2h_already_present = (
            _spec_h2h
            and _spec_h2h.split(",")[0].lower() in narrative.lower()
        )
        if not _h2h_already_present:
            _w82_h2h = _build_h2h_injection(evidence_pack, spec)
            if _w82_h2h:
                narrative = _inject_h2h_sentence(narrative, _w82_h2h)

    if not narrative or narrative.strip() == "NO_DATA":
        return {"match_key": match_key, "success": False, "duration": time.time() - t0}

    # Verdict cap (defence in depth — narrative_spec.py also enforces this)
    _pregen_edge_tier = edge.get("tier", "bronze")
    if narrative and not _is_non_edge:
        from narrative_spec import cap_verdict_in_narrative as _cap_all
        narrative = _cap_all(narrative)

    # 5. Build the full HTML message (used for logging/debug; the cache write
    # passes "" for narrative_html per BUILD-VERDICT-ONLY-STRIP-AI-BREAKDOWN-01)
    from html import escape as h
    hf, af = "", ""
    try:
        hf_fn = getattr(bot, "_get_flag_prefixes", None)
        if hf_fn:
            hf, af = hf_fn(home, away)
    except Exception:
        pass

    lines = [f"\U0001f3af <b>{hf}{h(home)} vs {af}{h(away)}</b>"]
    if commence:
        lines.append(f"\U0001f4c5 {commence}")
    lines.append("")

    edge_tier = edge.get("tier", "bronze")

    # Inject edge badge into verdict
    if narrative and tips:
        try:
            from services.edge_rating import EDGE_EMOJIS, EDGE_LABELS  # type: ignore
            tier_emoji = EDGE_EMOJIS.get(edge_tier, "")
            tier_label = EDGE_LABELS.get(edge_tier, "")
            if tier_emoji and tier_label:
                badge = f" — {tier_emoji} {tier_label}"
                narrative = re.sub(
                    r"(\U0001f3c6\s*(?:<b>)?Verdict(?:</b>)?)",
                    rf"\1{badge}",
                    narrative,
                    count=1,
                )
        except ImportError:
            pass

    if narrative:
        lines.append(narrative.lstrip("\n"))
        lines.append("")

    # Odds display — map outcome to team names
    _outcome_map = {"home": home, "away": away, "draw": "Draw"}
    if tips:
        lines.append("<b>SA Bookmaker Odds:</b>")
        for tip in tips:
            ev_ind = f"+{tip['ev']}%" if tip["ev"] > 0 else f"{tip['ev']}%"
            value_marker = " \U0001f4b0" if tip["ev"] > 2 else ""
            display_outcome = _outcome_map.get(tip['outcome'], tip['outcome'])
            lines.append(
                f"  {h(display_outcome)}: <b>{tip['odds']:.2f}</b> ({h(tip['bookie'])})\n"
                f"    {tip['prob']}% \u00b7 EV: {ev_ind}{value_marker}"
            )

    msg = _final_polish(_sanitise_jargon("\n".join(lines)))

    # 6. Build the cache row (caller batch-writes after all generation)
    _structured_card_json = None
    try:
        from card_pipeline import build_card_data as _build_card
        _card_tip = tips[0] if tips else None
        _card_data = _build_card(match_key, tip=_card_tip, include_analysis=True)
        _structured_card_json = json.dumps(_card_data, default=str)
        log.info(
            "P1P3-BUILD: card data built for %s (%d sources)",
            match_key, len(_card_data.get("data_sources_used", [])),
        )
    except Exception as _card_err:
        log.debug("card_pipeline: build_card_data failed for %s: %s", match_key, _card_err)

    _ctx_had_data = bool(ctx and ctx.get("data_available"))
    _final_model = served_model if _ctx_had_data else "instant-baseline-no-ctx"
    duration = time.time() - t0
    generation_ms = int(duration * 1000)

    # Verdict_html: deterministic _render_verdict only — no LLM.
    _verdict_html = None
    _evidence_class = None
    _tone_band = None
    _spec_json_str = None
    _context_json_str = None
    if spec is not None:
        _evidence_class = getattr(spec, "evidence_class", None)
        _tone_band = getattr(spec, "tone_band", None)
        try:
            from verdict_corpus import render_verdict as _rv_det
            _verdict_html = _rv_det(spec)
            if _verdict_html and _VERDICT_BLACKLIST and any(p in _verdict_html.lower() for p in _VERDICT_BLACKLIST):
                _bv_action = getattr(spec, "verdict_action", "back") or "back"
                _bv_outcome = getattr(spec, "outcome_label", "") or "this outcome"
                _bv_odds = getattr(spec, "odds", 0) or 0
                _verdict_html = f"{_bv_action.title()} — {_bv_outcome} at {_bv_odds:.2f}. Edge confirmed."
            if _verdict_html and len(_verdict_html) > 300:
                _verdict_html = _verdict_html[:300].rsplit(" ", 1)[0].rstrip(",. ")
            log.info("VERDICT-W82: rendered for %s (deterministic)", match_key)
        except Exception as _verd_err:
            log.debug("verdict deterministic render failed for %s: %s", match_key, _verd_err)

        # Serialise spec for cache
        try:
            _spec_dict = {
                "evidence_class": _evidence_class,
                "tone_band": _tone_band,
                "verdict_action": getattr(spec, "verdict_action", ""),
                "verdict_sizing": getattr(spec, "verdict_sizing", ""),
                "support_level": getattr(spec, "support_level", 0),
                "risk_severity": getattr(spec, "risk_severity", ""),
                "ev_pct": getattr(spec, "ev_pct", 0),
                "composite_score": getattr(spec, "composite_score", 0),
                "edge_tier": edge_tier,
            }
            _spec_json_str = json.dumps(_spec_dict, default=str)
        except Exception:
            pass

    # Serialise context for cache
    if ctx and ctx.get("data_available"):
        try:
            _context_json_str = json.dumps(ctx, default=str)
        except Exception:
            pass

    return {
        "match_key": match_key, "success": True, "model": _final_model,
        "duration": duration, "narrative": narrative,
        "_cache": {
            "match_id": match_key,
            "html": msg,
            "tips": tips,
            "edge_tier": edge_tier,
            "model": _final_model,
            "evidence_json": evidence_json,
            "narrative_source": narrative_source,
            "verification_failure": "",
            "coverage_json": _coverage_json,
            "structured_card_json": _structured_card_json,
            "verdict_html": _verdict_html,
            "evidence_class": _evidence_class,
            "tone_band": _tone_band,
            "spec_json": _spec_json_str,
            "context_json": _context_json_str,
            "generation_ms": generation_ms,
            "setup_validated": 1,
            "verdict_validated": 1,
            "setup_attempts": 1,
            "verdict_attempts": 1,
        },
    }


async def _verify_and_fill_cache(
    edges: list[dict],
    sweep: str,
) -> None:
    """Post-sweep: verify all edges have cache entries, fill gaps.

    Runs after the main generation loop + batch write. Catches edges that
    failed generation or had DB write failures.
    """
    if not edges:
        return

    gaps = []
    for edge in edges:
        mk = edge.get("match_key", "")
        if not mk:
            continue
        cached = await _get_cached_narrative(mk)
        if not cached:
            gaps.append(edge)

    if not gaps:
        log.info("Cache verification: 100%% coverage (%d/%d)", len(edges), len(edges))
        return

    log.warning("Cache gaps found: %d/%d edges missing", len(gaps), len(edges))
    for i, edge in enumerate(gaps, 1):
        mk = edge.get("match_key", "")
        log.info("  Filling gap [%d/%d]: %s", i, len(gaps), mk)
        try:
            result = await _generate_one(edge, sweep_type=sweep)
            if result.get("success") and result.get("_cache"):
                pw = result["_cache"]
                try:
                    # BUILD-VERDICT-ONLY-STRIP-AI-BREAKDOWN-01 — narrative_html
                    # generation retired. Verdict on the card image is now the
                    # only narrative surface. We pass "" for html so the
                    # writer stores no long-form prose; verdict_html still
                    # rides through and is what the card image consumes.
                    await _store_narrative_cache(
                        pw["match_id"],
                        "",
                        pw["tips"],
                        pw["edge_tier"],
                        pw["model"],
                        evidence_json=pw.get("evidence_json"),
                        narrative_source=pw.get("narrative_source", "w82"),
                        coverage_json=pw.get("coverage_json"),
                        structured_card_json=pw.get("structured_card_json"),
                        verdict_html=pw.get("verdict_html"),
                        evidence_class=pw.get("evidence_class"),
                        tone_band=pw.get("tone_band"),
                        spec_json=pw.get("spec_json"),
                        context_json=pw.get("context_json"),
                        generation_ms=pw.get("generation_ms"),
                        setup_validated=pw.get("setup_validated"),
                        verdict_validated=pw.get("verdict_validated"),
                        setup_attempts=pw.get("setup_attempts"),
                        verdict_attempts=pw.get("verdict_attempts"),
                    )
                    log.info("  -> Gap filled for %s", mk)
                except Exception as store_exc:
                    log.warning("  -> Cache write failed for %s: %s", mk, store_exc)
            else:
                log.warning("  -> Gap fill FAILED for %s", mk)
        except Exception as exc:
            log.error("  -> Gap fill ERROR for %s: %s", mk, exc)
        if i < len(gaps):
            await asyncio.sleep(1.0)

    # Final count
    still_missing = 0
    for edge in edges:
        mk = edge.get("match_key", "")
        if mk and not await _get_cached_narrative(mk):
            still_missing += 1
    coverage = ((len(edges) - still_missing) / len(edges)) * 100
    log.info("Cache coverage after gap fill: %.0f%% (%d/%d)", coverage, len(edges) - still_missing, len(edges))


def _quarantine_stale_cache_rows(db_path: str | None = None) -> int:
    """Mark existing narrative_cache rows past their kickoff by >24h as quarantined=1.

    Idempotent — safe to call on every pregen run.
    Returns the number of rows newly quarantined.
    """
    path = db_path or str(bot._NARRATIVE_DB_PATH)
    # Use today's date as cutoff: any match dated before today is ≥24h old at midnight UTC.
    # This matches _is_past_kickoff which checks total_seconds > 24 * 3600.
    cutoff_date = datetime.now(SAST).strftime("%Y-%m-%d")
    try:
        conn = sqlite3.connect(path, timeout=5.0)
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            cur = conn.execute(
                "UPDATE narrative_cache "
                "SET quarantined = 1 "
                "WHERE COALESCE(quarantined, 0) = 0 "
                "  AND substr(match_id, -10) < ?",
                (cutoff_date,),
            )
            count = cur.rowcount
            conn.commit()
            if count:
                log.info("PREGEN-QUARANTINE: marked %d stale narrative_cache rows as quarantined", count)
            return count
        finally:
            conn.close()
    except Exception as exc:
        log.warning("PREGEN-QUARANTINE: failed to quarantine stale rows: %s", exc)
        return 0


def _resolve_kickoff(edge: dict, db_path: str) -> "datetime":
    """Resolve authoritative kickoff datetime for a pregen edge.

    BUILD-NARRATIVE-PREGEN-WINDOW-01: Priority order (SO #40):
    1. broadcast_schedule WHERE source='supersport_scraper' — exact kickoff time
    2. commence_time field in the edge dict (from fixture tables)
    3. Date suffix from match_key (day-level fallback, midnight SAST)

    Returns a timezone-aware datetime. Returns datetime.max (SAST) when
    unresolvable so the edge is excluded from any forward-horizon window.
    """
    mk = edge.get("match_key", "") or ""
    home = (edge.get("home_team") or "")[:8]
    away = (edge.get("away_team") or "")[:8]
    date_10 = mk[-10:] if len(mk) >= 10 else ""

    # 1. broadcast_schedule WHERE source='supersport_scraper' (SO #40)
    if date_10:
        try:
            from scrapers.db_connect import connect_odds_db as _bsconn
            _bsc = _bsconn(db_path, timeout=2)
            try:
                row = _bsc.execute(
                    """
                    SELECT start_time FROM broadcast_schedule
                    WHERE source='supersport_scraper'
                      AND broadcast_date = ?
                      AND (home_team LIKE ? OR away_team LIKE ?)
                    ORDER BY start_time ASC
                    LIMIT 1
                    """,
                    (date_10, f"%{home}%", f"%{away}%"),
                ).fetchone()
                if row and row[0]:
                    dt = datetime.fromisoformat(str(row[0]).replace("Z", "+00:00"))
                    return dt if dt.tzinfo else dt.replace(tzinfo=SAST)
            finally:
                _bsc.close()
        except Exception:
            pass

    # 2. commence_time from edge dict (fixture tables populate this)
    ct = edge.get("commence_time") or ""
    if ct:
        try:
            dt = datetime.fromisoformat(str(ct).replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
        except (ValueError, TypeError):
            pass

    # 3. Date suffix from match_key (day-level fallback)
    if date_10:
        try:
            parts = [int(x) for x in date_10.split("-")]
            return datetime(*parts, tzinfo=SAST)
        except (ValueError, TypeError):
            pass

    # Unresolvable — place at far future so it is excluded from any horizon window
    return datetime.max.replace(tzinfo=SAST)


async def main(sweep: str, sport: str | None = None, limit: int = 100, dry_run: bool = False) -> None:
    """Run the pre-generation sweep.

    FIX-DROP-SONNET-POLISH-W82-CANONICAL-01: deterministic W82 baseline only —
    no LLM client setup, no Sonnet/Haiku traffic, no model selection.
    """
    log.info(
        "Starting %s sweep (W82 baseline canonical, deterministic)%s%s",
        sweep,
        f" sport={sport}" if sport else "",
        " [DRY RUN]" if dry_run else "",
    )

    # BUILD-PREGEN-KICKOFF-FILTER-01: quarantine any stale past-kickoff cache rows
    if not dry_run:
        await asyncio.to_thread(_quarantine_stale_cache_rows)

    # BUILD-16a: No scraper lock dependency. Pregen reads via WAL mode —
    # concurrent with scraper writes. No waiting, no deferral.

    # Runtime sweeps validate schema read-only; deploy/startup migration must happen elsewhere.
    _validate_pregen_runtime_schema()

    # Shadow pregen must track the same edge reality the live bot serves.
    edges = await asyncio.to_thread(_load_pregen_edges, limit, sport)

    if not edges:
        log.info("No live edges found — nothing to pre-generate")
        return

    log.info("Found %d live edges", len(edges))

    # Filter for refresh/uncached_only mode: skip edges with fresh cache
    if sweep in ("refresh", "uncached_only"):
        filtered = []
        skipped_refresh = 0
        for edge in edges:
            mk = edge.get("match_key", "")
            cached = await _get_cached_narrative(mk)
            if not cached:
                filtered.append(edge)
                continue

            cached_tips = cached.get("tips") or []
            if not cached_tips:
                continue

            cached_outcome = _normalise_outcome_label(
                cached_tips[0].get("outcome"),
                edge.get("home_team", ""),
                edge.get("away_team", ""),
            )
            edge_outcome = _normalise_outcome_label(
                edge.get("recommended_outcome") or edge.get("outcome", ""),
                edge.get("home_team", ""),
                edge.get("away_team", ""),
            )
            if cached_outcome and edge_outcome and cached_outcome != edge_outcome:
                log.info(
                    "R14-BUILD-02: Outcome divergence for %s: cached=%s, current=%s -> regenerating",
                    mk,
                    cached_outcome,
                    edge_outcome,
                )
                filtered.append(edge)
            else:
                skipped_refresh += 1
                log.debug("Pregen skip gate (warm cache): skipping %s", mk)
        log.info(
            "Pregen skip gate: %d/%d matches skipped (warm cache), %d need regeneration",
            skipped_refresh, len(edges), len(filtered),
        )
        edges = filtered

    # BUILD-SONNET-BURN-FIX-01 FIX-5: full-sweep conditional skip.
    # Skip when: cache exists (banned-phrase gate already passed inside
    # _get_cached_narrative), cache is ≤24h old, and odds_hash matches
    # the current snapshot (proxy for "evidence unchanged"). This cuts
    # Sonnet spend on every full sweep while still regenerating when
    # anything material has changed.
    if sweep == "full":
        filtered_full = []
        skipped_full = 0
        for edge in edges:
            mk = edge.get("match_key", "")
            cached = await _get_cached_narrative(mk)
            if not cached:
                filtered_full.append(edge)
                continue

            created_at_raw = cached.get("created_at_raw") or cached.get("created_at")
            age_ok = False
            try:
                if created_at_raw:
                    created_at = datetime.fromisoformat(str(created_at_raw).replace("Z", "+00:00"))
                    if created_at.tzinfo is None:
                        created_at = created_at.replace(tzinfo=UTC)
                    age_sec = (datetime.now(SAST) - created_at).total_seconds()
                    age_ok = age_sec <= 24 * 3600
            except (ValueError, TypeError):
                age_ok = False

            if not age_ok:
                filtered_full.append(edge)
                continue

            stored_hash = cached.get("odds_hash") or ""
            try:
                current_hash = await asyncio.to_thread(_compute_odds_hash, mk)
            except Exception:
                current_hash = ""

            if stored_hash and current_hash and stored_hash == current_hash:
                skipped_full += 1
                log.debug("Pregen skip gate (full/hash match): skipping %s", mk)
                continue
            elif not stored_hash or not current_hash:
                log.debug("Pregen skip gate (full): hash unavailable for %s, regenerating", mk)

            filtered_full.append(edge)

        log.info(
            "Pregen skip gate: %d/%d matches skipped (warm cache + hash match), %d need regeneration",
            skipped_full,
            len(edges),
            len(filtered_full),
        )
        edges = filtered_full

    if not edges:
        log.info("All edges have fresh cache — nothing to do")
        return

    # BUILD-NARRATIVE-PREGEN-WINDOW-01: 48h horizon filter + 25-match hard cap.
    # Resolves authoritative kickoff via broadcast_schedule (source='supersport_scraper'),
    # falling back to commence_time then match_key date. Sorts nearest-kickoff first
    # so the most urgent narratives always get generated first when the cap fires.
    #
    # FIX-W84-PREMIUM-MANDATORY-COVERAGE-01 (locked 2026-04-29):
    # Premium tiers (gold/diamond) bypass _PREGEN_HORIZON_HOURS entirely. Only
    # Silver/Bronze still respect the 240h window. Match-cap stays in place but
    # premium edges fill the cap first via the existing tier-priority sort, and
    # any premium edge that DOES overflow the cap is logged at WARNING with the
    # PremiumOverflowCap signature — never dropped silently.
    _db_path = str(SCRAPERS_ROOT / "odds.db")
    _horizon_cutoff = datetime.now(SAST) + timedelta(hours=_PREGEN_HORIZON_HOURS)
    _pre_horizon_count = len(edges)

    for _he in edges:
        _he["_resolved_kickoff"] = _resolve_kickoff(_he, _db_path)
    _edges_in_window, _premium_bypass_count = _apply_premium_horizon_filter(
        edges, _horizon_cutoff
    )
    if _premium_bypass_count:
        log.info(
            "FIX-W84-PREMIUM-MANDATORY-COVERAGE-01 PremiumHorizonBypass count=%d horizon_hours=%d",
            _premium_bypass_count, _PREGEN_HORIZON_HOURS,
        )

    # FIX-PREGEN-DIAMOND-PRIORITY-01: tier-priority sort BEFORE _PREGEN_MATCH_CAP
    # truncation. Premium tiers (Diamond > Gold > Silver) refresh first; Bronze
    # fills the remainder. Within a tier, nearest kickoff still wins. Replaces
    # the prior kickoff-only sort that allowed Bronze to displace premium when
    # the cap fired. The candidate dict carries `tier` from its source builder
    # (`_edge_from_serving_tip`, `_build_baseline_edge_from_snapshot_row`,
    # `_build_fixture_only_edge`) — all use lowercase tier strings.
    _edges_in_window.sort(key=lambda e: (
        _TIER_PRIORITY.get((e.get("tier") or e.get("edge_tier") or "bronze").lower(), 99),
        _kickoff_unix(e),
    ))
    log.info(
        "pregen_tier_priority_sort: diamond=%d, gold=%d, silver=%d, bronze=%d, other=%d",
        sum(1 for e in _edges_in_window if (e.get("tier") or e.get("edge_tier") or "").lower() == "diamond"),
        sum(1 for e in _edges_in_window if (e.get("tier") or e.get("edge_tier") or "").lower() == "gold"),
        sum(1 for e in _edges_in_window if (e.get("tier") or e.get("edge_tier") or "").lower() == "silver"),
        sum(1 for e in _edges_in_window if (e.get("tier") or e.get("edge_tier") or "").lower() == "bronze"),
        sum(1 for e in _edges_in_window if (e.get("tier") or e.get("edge_tier") or "").lower() not in _TIER_PRIORITY),
    )

    if len(_edges_in_window) > _PREGEN_MATCH_CAP:
        # FIX-W84-PREMIUM-MANDATORY-COVERAGE-01: tier-priority sort guarantees
        # premium edges fill the cap first. Any premium that DOES get truncated
        # is logged at WARNING with the PremiumOverflowCap signature so EdgeOps
        # can size up the cap rather than swallow the drop silently.
        _capped_window = _edges_in_window[:_PREGEN_MATCH_CAP]
        _dropped_window = _edges_in_window[_PREGEN_MATCH_CAP:]
        _total_premium = sum(
            1 for _e in _edges_in_window
            if (_e.get("tier") or _e.get("edge_tier") or "").lower() in ("gold", "diamond")
        )
        _premium_dropped = [
            _e for _e in _dropped_window
            if (_e.get("tier") or _e.get("edge_tier") or "").lower() in ("gold", "diamond")
        ]
        if _premium_dropped:
            try:
                import sentry_sdk as _pregen_sentry_local
            except Exception:
                _pregen_sentry_local = None
            for _pe in _premium_dropped:
                _pe_mid = _pe.get("match_key") or _pe.get("match_id") or "<unknown>"
                _pe_tier = (_pe.get("tier") or _pe.get("edge_tier") or "").lower()
                log.warning(
                    "FIX-W84-PREMIUM-MANDATORY-COVERAGE-01 PremiumOverflowCap "
                    "match_id=%s tier=%s total_premium=%d cap=%d",
                    _pe_mid, _pe_tier, _total_premium, _PREGEN_MATCH_CAP,
                )
                if _pregen_sentry_local is not None:
                    try:
                        _pregen_sentry_local.add_breadcrumb(
                            category="pregen.premium_overflow",
                            level="warning",
                            message="FIX-W84-PREMIUM-MANDATORY-COVERAGE-01 PremiumOverflowCap",
                            data={
                                "match_id": _pe_mid,
                                "tier": _pe_tier,
                                "total_premium": _total_premium,
                                "cap": _PREGEN_MATCH_CAP,
                            },
                        )
                    except Exception:
                        pass
        log.warning(
            "pregen_cap_hit: %d matches within %dh window — capping to nearest-kickoff %d (premium_overflow=%d)",
            len(_edges_in_window), _PREGEN_HORIZON_HOURS, _PREGEN_MATCH_CAP, len(_premium_dropped),
        )
        _edges_in_window = _capped_window
    elif _pre_horizon_count != len(_edges_in_window):
        log.info(
            "pregen_horizon_filter: %d → %d matches (horizon=%dh, cap=%d)",
            _pre_horizon_count, len(_edges_in_window), _PREGEN_HORIZON_HOURS, _PREGEN_MATCH_CAP,
        )

    edges = _edges_in_window

    if not edges:
        log.info("No matches within %dh pregen window — nothing to do", _PREGEN_HORIZON_HOURS)
        return

    # FIX-DROP-SONNET-POLISH-W82-CANONICAL-01: no Claude client — pregen sweep
    # is pure Python (NarrativeSpec → _render_baseline). The validator stack at
    # _store_narrative_cache fires on each row; that is the only quality gate.
    results = {
        "success": 0,
        "failed": 0,
        "skipped": 0,
        "dropped": 0,
        "total_duration": 0.0,
        "w82_baseline_served": 0,
    }
    sweep_verdicts: list[str] = []
    pending_writes: list[dict] = []

    # BUILD-NARRATIVE-PREGEN-WINDOW-01: bounded concurrency via Semaphore.
    # At most _PREGEN_CONCURRENCY (3) matches are generated simultaneously,
    # so pregen never consumes all available LLM slots and _edge_precompute_job
    # can schedule freely between awaits.
    _sem = asyncio.Semaphore(_PREGEN_CONCURRENCY)
    _sweep_wall_start = time.time()
    log.info(
        "pregen_sweep_start match_count=%d horizon_hours=%d concurrency_cap=%d",
        len(edges), _PREGEN_HORIZON_HOURS, _PREGEN_CONCURRENCY,
    )

    async def _process_edge(edge: dict, idx: int, total: int) -> None:
        mk = edge.get("match_key", "")

        # W67-CALIBRATE Fix 5: Skip no-odds matches.
        # BUILD-DUAL-MODEL-PREGEN: Do NOT skip zero/negative edge_pct — non-edge
        # matches are valid Haiku targets as long as they have SA odds.
        if not edge.get("best_odds"):
            log.info("SKIP: %s — no active odds data", mk)
            results["skipped"] += 1
            return

        # BASELINE-FIX: match-level dedup — drop if already being generated
        if mk in _in_progress_matches:
            log.info("DROP: %s — already in progress (duplicate edge in sweep)", mk)
            results["dropped"] += 1
            return
        _in_progress_matches.add(mk)

        if dry_run:
            log.info("[%d/%d] DRY RUN: would generate %s (%s / %s)", idx, total, mk, edge.get("sport", "?"), edge.get("league", "?"))
            results["success"] += 1
            _in_progress_matches.discard(mk)
            return

        log.info("[%d/%d] Generating W82 baseline for %s...", idx, total, mk)

        try:
            async with _sem:
                result = await _generate_one(edge, sweep_type=sweep)
            if result.get("success"):
                results["success"] += 1
                log.info("  -> OK in %.1fs", result["duration"])
                # Collect cache write for batch
                if result.get("_cache"):
                    pending_writes.append(result["_cache"])
                    results["w82_baseline_served"] += 1
                # W67-CALIBRATE: collect verdict for balance check
                narr = result.get("narrative", "")
                if narr and "Verdict" in narr:
                    verdict_start = narr.find("Verdict")
                    sweep_verdicts.append(narr[verdict_start:verdict_start + 300])
            else:
                results["failed"] += 1
                log.warning("  -> FAILED for %s", mk)
            results["total_duration"] += result.get("duration", 0)
        except Exception as exc:
            results["failed"] += 1
            log.error("  -> ERROR for %s: %s", mk, exc)
        finally:
            # BASELINE-FIX: always release match slot, even on failure
            _in_progress_matches.discard(mk)

    await asyncio.gather(
        *[_process_edge(edge, i, len(edges)) for i, edge in enumerate(edges, 1)]
    )

    _sweep_wall_elapsed = time.time() - _sweep_wall_start
    log.info(
        "pregen_sweep_end match_count=%d success=%d failed=%d skipped=%d dropped=%d wall_secs=%.1f",
        len(edges),
        results["success"],
        results["failed"],
        results["skipped"],
        results["dropped"],
        _sweep_wall_elapsed,
    )

    # FIX-DROP-SONNET-POLISH-W82-CANONICAL-01: every row is a fresh W82 baseline.
    # No w84 preservation logic — there's no longer a w84 quality gradient to
    # protect. The validator gates inside _store_narrative_cache fire on each
    # write; rejected writes are refused there.
    if pending_writes:
        log.info("Writing %d narratives to cache...", len(pending_writes))
        write_ok = 0
        for pw in pending_writes:
            match_id = pw["match_id"]
            try:
                # BUILD-VERDICT-ONLY-STRIP-AI-BREAKDOWN-01 — narrative_html
                # generation retired. Verdict on the card image is the only
                # narrative surface; pass "" for html, keep verdict_html.
                await _store_narrative_cache(
                    match_id,
                    "",
                    pw["tips"],
                    pw["edge_tier"],
                    pw["model"],
                    evidence_json=pw.get("evidence_json"),
                    narrative_source=pw.get("narrative_source", NARRATIVE_SOURCE_LABEL),
                    coverage_json=pw.get("coverage_json"),
                    structured_card_json=pw.get("structured_card_json"),
                    verdict_html=pw.get("verdict_html"),
                    evidence_class=pw.get("evidence_class"),
                    tone_band=pw.get("tone_band"),
                    spec_json=pw.get("spec_json"),
                    context_json=pw.get("context_json"),
                    generation_ms=pw.get("generation_ms"),
                )
                write_ok += 1
            except Exception as exc:
                log.warning("Cache write failed for %s: %s", match_id, exc)
        log.info(
            "Cache writes: %d/%d successful (W82 baseline)",
            write_ok, len(pending_writes),
        )

    # W67-CALIBRATE: Verdict balance check
    _check_verdict_balance(sweep_verdicts)

    # W79-P3D: Verify cache coverage after sweep
    await _verify_and_fill_cache(edges, sweep)

    # Summary — FIX-DROP-SONNET-POLISH-W82-CANONICAL-01: W82 is the only path.
    log.info(
        "\n=== Sweep Complete ===\n"
        "Mode: %s (W82 baseline canonical)\n"
        "Total: %d edges\n"
        "Generated: %d\n"
        "Failed: %d\n"
        "Skipped (no odds): %d\n"
        "Dropped (duplicate): %d\n"
        "W82 baseline served: %d\n"
        "W84 served: 0 (haiku: 0, sonnet: 0)\n"
        "W82 fallback: %d\n"
        "Total time: %.1fs\n"
        "Avg per edge: %.1fs",
        sweep,
        len(edges),
        results["success"],
        results["failed"],
        results["skipped"],
        results["dropped"],
        results["w82_baseline_served"],
        results["w82_baseline_served"],
        results["total_duration"],
        results["total_duration"] / max(len(edges), 1),
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pre-generate narratives for live edges")
    parser.add_argument(
        "--sweep", choices=["full", "refresh", "uncached_only"], default="uncached_only",
        help="full = all edges, refresh = stale/expired only, uncached_only = new edges without cache (default)",
    )
    parser.add_argument(
        "--sport", default=None,
        help="Filter to a specific sport (soccer, rugby, cricket, mma, boxing)",
    )
    parser.add_argument(
        "--limit", type=int, default=100,
        help="Maximum number of edges to process (default: 100)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", default=False,
        help="Print what would be generated without writing to cache",
    )
    args = parser.parse_args()

    # W81-HEALTH: PID lock — prevent concurrent pregen instances
    import fcntl as _fcntl
    from config import BOT_ROOT
    _PID_FILE = str(BOT_ROOT.parent / "logs" / "pregen.pid")
    _pid_fh = None
    try:
        _pid_fh = open(_PID_FILE, "w")
        _fcntl.flock(_pid_fh.fileno(), _fcntl.LOCK_EX | _fcntl.LOCK_NB)
        _pid_fh.write(str(os.getpid()) + "\n")
        _pid_fh.flush()
    except (IOError, OSError):
        log.warning("pregenerate_narratives.py: another instance is already running — exiting.")
        sys.exit(0)

    # EDGE-FIX-03: wire Sentry boundary — bot Sentry already initialised via
    # `import bot` above. Set pregen-specific tag so events are filterable.
    try:
        import sentry_sdk as _pregen_sentry
        _pregen_sentry.set_tag("boundary_site", "pregen_narratives")
    except Exception:
        _pregen_sentry = None

    _pregen_success = False
    try:
        asyncio.run(main(args.sweep, sport=args.sport, limit=args.limit, dry_run=args.dry_run))
        _pregen_success = True
    except Exception as _pregen_exc:
        if _pregen_sentry:
            try:
                _pregen_sentry.capture_exception(_pregen_exc)
            except Exception:
                pass
        raise
    finally:
        if _pid_fh:
            try:
                _fcntl.flock(_pid_fh.fileno(), _fcntl.LOCK_UN)
                _pid_fh.close()
                os.unlink(_PID_FILE)
            except Exception:
                pass

    if _pregen_success:
        _sentinel = f"/tmp/cron_sentinel_pregenerate_narratives_{time.strftime('%Y%m%d%H%M')}"
        try:
            open(_sentinel, "w").close()
        except OSError:
            pass
