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
import json
import logging
import os
import re
import sqlite3
import sys
import time

# Add project paths
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import SCRAPERS_ROOT, BOT_ROOT
sys.path.insert(0, str(SCRAPERS_ROOT.parent))
sys.path.insert(0, str(SCRAPERS_ROOT))

from dotenv import load_dotenv
_bot_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_bot_dir, ".env"))

import anthropic
from validators.sport_context import validate_sport_text  # REGFIX-03 wiring
from evidence_pack import (
    _build_h2h_injection,
    build_evidence_pack,
    _inject_h2h_sentence,
    _build_sharp_injection,
    _strip_model_generated_h2h_references,
    _inject_sharp_sentence,
    _strip_model_generated_sharp_references,
    _suppress_shadow_banned_phrases,
    format_evidence_prompt,
    serialise_evidence_pack,
    verify_shadow_narrative,
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

# Model IDs
MODELS = {
    "full": os.environ.get("NARRATIVE_MODEL", "claude-sonnet-4-20250514"),
    "refresh": os.environ.get("NARRATIVE_MODEL", "claude-sonnet-4-20250514"),
    "uncached_only": os.environ.get("NARRATIVE_MODEL", "claude-sonnet-4-20250514"),
}
SHADOW_MODEL = os.environ.get(
    "NARRATIVE_SHADOW_MODEL",
    os.environ.get("NARRATIVE_MODEL", "claude-sonnet-4-20250514"),
)
# W84-CONFIRM-1: W84 is now the permanent default generation path.
# The W84_SERVE env-var gate has been removed — W84 always serves.

# Import narrative functions from bot.py (safe — guarded by __name__ == __main__)
import bot
from bot import (
    build_verified_narrative,
    _build_analyst_prompt,
    _build_edge_risk_prompt,
    _build_setup_section_v2,
    _build_verdict_from_signals_v2,
    _build_edge_from_signals_v2,
    _build_risk_from_signals_v2,
    _apply_sport_subs,
    sanitize_ai_response,
    validate_sport_context,
    fact_check_output,
    _clean_fact_checked_output,
    get_verified_injuries,
    _has_banned_patterns,
    _format_verified_context,
    _format_signal_data_for_prompt,
    _build_programmatic_narrative,
    _build_signal_only_narrative,
    _validate_breakdown,
    _get_cached_narrative,
    _store_narrative_cache,
    _ensure_narrative_cache_table,
    _ensure_shadow_narratives_table,
    _check_verdict_balance,
    _extract_text_from_response,
    _strip_preamble,
    _store_shadow_narrative,
    _sanitise_jargon,
    _final_polish,
    WEB_SEARCH_TOOL,
    SPORT_TERMINOLOGY,
    _build_verified_scaffold,
    _parse_story_types_from_scaffold,
    _get_exemplars_for_prompt,
    _build_rewrite_prompt,
    _verify_rewrite,
    _add_section_bold,
    _build_polish_prompt,
    _validate_polish,
)
import config

# W81-HEALTH: Fail fast if required bot functions are missing (stale rename protection)
_REQUIRED_BOT_FUNCTIONS = [
    "build_verified_narrative",
    "fact_check_output",
    "_build_setup_section_v2",
    "_clean_fact_checked_output",
    "get_verified_injuries",
    "_get_exemplars_for_prompt",
    "_build_rewrite_prompt",
    "_verify_rewrite",
    "_build_polish_prompt",
    "_validate_polish",
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


def _scraper_lock_file() -> str:
    return os.environ.get("PREGEN_SCRAPER_LOCK_FILE", "/tmp/mzansi_scraper.lock")


def _scraper_wait_seconds() -> float:
    return float(os.environ.get("PREGEN_SCRAPER_WAIT_SECONDS", "720"))


def _scraper_wait_poll_seconds() -> float:
    return float(os.environ.get("PREGEN_SCRAPER_WAIT_POLL_SECONDS", "5"))


def _is_active_process(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _active_scraper_lock_pid(lock_file: str | None = None) -> int | None:
    path = lock_file or _scraper_lock_file()
    try:
        with open(path) as fh:
            raw = fh.read().strip()
    except FileNotFoundError:
        return None
    except OSError:
        return None
    if not raw:
        return None
    try:
        pid = int(raw)
    except ValueError:
        return None
    return pid if _is_active_process(pid) else None


def _pregen_enrichment_live_safe() -> tuple[bool, int | None]:
    """Always use read-only enrichment during pregen to eliminate DB write contention.

    W84-LOCKFIX: Previously this only checked /tmp/mzansi_scraper.lock, but 7+
    other cron processes write to odds.db without that lock file (sharp benchmark,
    closing_capture, clv_tracker, settlement, lineups, integrity, bot edge_v2).
    The lock-file check had a TOCTOU race even for the one writer it did cover.

    Fix: unconditionally return live_safe=True.  Pregen reads from api_cache
    (coach/ESPN data) but never writes.  Cache misses produce slightly thinner
    narratives for ONE cycle; the next run (or a user tap) populates the cache.
    This eliminates ALL write contention from pregen enrichment → odds.db.
    """
    return True, _active_scraper_lock_pid()


async def _wait_for_scraper_writer_window() -> bool:
    """Serialize pregen startup behind the scraper lock to avoid writer collisions."""
    active_pid = _active_scraper_lock_pid()
    if active_pid is None:
        return True

    wait_seconds = max(_scraper_wait_seconds(), 0.0)
    poll_seconds = max(_scraper_wait_poll_seconds(), 0.1)
    deadline = time.monotonic() + wait_seconds
    log.warning(
        "Scraper writer lock active via %s (PID %s) — delaying pregen startup up to %.0fs",
        _scraper_lock_file(),
        active_pid,
        wait_seconds,
    )
    while time.monotonic() < deadline:
        await asyncio.sleep(poll_seconds)
        active_pid = _active_scraper_lock_pid()
        if active_pid is None:
            log.info("Scraper writer lock cleared — proceeding with pregen startup")
            return True

    log.warning(
        "Scraper writer lock still active after %.0fs (PID %s) — deferring this sweep safely",
        wait_seconds,
        active_pid,
    )
    return False


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
) -> dict:
    """Fetch match context: API-Football primary (soccer), ESPN fallback.

    CLEAN-DATA-v2: Uses sport-specific fetchers as primary data source.
    Falls back to ESPN when fetcher unavailable or returns thin context.
    """
    # ── Primary: Sport-specific fetcher (API-Football for soccer) ─────
    if sport in ("soccer", "football"):
        try:
            from fetchers import get_fetcher
            from fetchers.base_fetcher import ensure_schema

            fetcher = get_fetcher("soccer")
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
                sport="soccer",
                live_safe=live_safe,
            )
            if ctx and not _needs_pregen_context_lift(ctx):
                log.info("API-Football context hit for %s vs %s", home, away)
                return ctx
            log.info("API-Football context thin for %s vs %s — trying ESPN fallback", home, away)
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
        return last_ctx
    except Exception as exc:
        log.warning("Match context fetch failed for %s vs %s: %s", home, away, exc)
        return {}


async def _get_enrichment(
    match_id: str, home: str, away: str, league: str, sport: str, commence_time: str,
) -> str:
    """Fetch enrichment data (weather, lineup, injuries)."""
    parts = []
    home_key = home.lower().replace(" ", "_")
    away_key = away.lower().replace(" ", "_")

    # Weather
    try:
        from scrapers.weather_helper import get_venue_city, format_weather_for_narrative_sync
        city = get_venue_city(home_key)
        if city and commence_time:
            weather = format_weather_for_narrative_sync(city, commence_time[:10], sport)
            if weather:
                parts.append(weather)
    except Exception:
        pass

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
_FORM_PATTERN = re.compile(r'(?:form|form reads|recent form)\s+(?:reads?\s+)?([WDL]{2,})', re.IGNORECASE)
_POSITION_PATTERN = re.compile(r'sit\s+(\d+(?:st|nd|rd|th))\s+(?:on|with)\s+(\d+)\s+points?', re.IGNORECASE)
_RECORD_PATTERN = re.compile(r'W(\d+)\s*(?:D(\d+)\s*)?L(\d+)', re.IGNORECASE)


def _extract_claims(narrative: str) -> list[str]:
    """Extract verifiable factual claims from a narrative."""
    claims = []
    for m in _FORM_PATTERN.finditer(narrative):
        claims.append(f"Form: {m.group(1)}")
    for m in _POSITION_PATTERN.finditer(narrative):
        claims.append(f"Position: {m.group(1)} on {m.group(2)} points")
    for m in _RECORD_PATTERN.finditer(narrative):
        d = m.group(2) or "0"
        claims.append(f"Record: W{m.group(1)} D{d} L{m.group(3)}")
    return claims


async def _verify_narrative_claims(
    narrative: str,
    home: str,
    away: str,
    claude: anthropic.AsyncAnthropic,
) -> list[str]:
    """Layer 2: Cross-check narrative claims using Haiku + web search.

    Returns list of contradiction descriptions (empty = all clear).
    """
    claims = _extract_claims(narrative)
    if not claims:
        return []

    claims_text = "\n".join(f"- {c}" for c in claims)
    try:
        resp = await claude.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            system=(
                "You are a sports fact-checker. Verify the following claims about "
                f"{home} vs {away} using web search. For each claim, respond with "
                "CONFIRMED or CONTRADICTED followed by the correct information. "
                "Be concise — one line per claim."
            ),
            messages=[{"role": "user", "content": f"Verify these claims:\n{claims_text}"}],
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 1}],
            timeout=30.0,
        )
        result = _extract_text_from_response(resp)
        contradictions = []
        for line in result.split("\n"):
            if "CONTRADICTED" in line.upper():
                contradictions.append(line.strip())
        return contradictions
    except Exception as exc:
        log.warning("Layer 2 verification failed for %s vs %s: %s", home, away, exc)
        return []


def _shadow_token_count(resp) -> int:
    usage = getattr(resp, "usage", None)
    if not usage:
        return 0
    return int(getattr(usage, "input_tokens", 0) or 0) + int(getattr(usage, "output_tokens", 0) or 0)


# ── BASELINE-FIX: Data Source Alignment ──
# Ensures narrative verdict bookmaker+price matches the SA Bookmaker Odds table.
# Both must read from odds.db (single source of truth), not stale edge_results.

_VALID_BK_DISPLAY = {
    "hollywoodbets", "betway", "supabets", "sportingbet",
    "gbets", "world sports betting", "playabets", "supersportbet",
}


async def _refresh_edge_from_odds_db(edge: dict) -> dict:
    """Refresh bookmaker+price from odds.db so narrative and odds table agree.

    edge_results stores pre-computed edges that may be stale.  odds.db
    (odds_latest) has the current best price.  This ensures the same price
    feeds both the narrative verdict and the SA Bookmaker Odds display.

    Updates edge dict in place and returns it.
    """
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
        "best_odds": edge_data.get("best_odds", tip.get("odds", 0)),
        "best_bookmaker": edge_data.get("best_bookmaker", tip.get("bookmaker", "?")),
        "best_bookmaker_key": tip.get("bookmaker_key", ""),
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
        serving_tips = bot._load_tips_from_edge_results(limit=limit)
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



async def _generate_one(
    edge: dict,
    model_id: str,
    claude: anthropic.AsyncAnthropic,
    sweep_type: str = "full",
) -> dict:
    """Generate narrative for a single edge and store in cache.

    Returns dict with match_key, success, model, duration.
    """
    t0 = time.time()
    match_key = edge.get("match_key", "")
    home = edge.get("home_team", "")
    away = edge.get("away_team", "")
    home_key = ""
    away_key = ""

    # Parse team names from match_key if not provided (edge_v2 dicts omit them)
    # match_key format: "team_a_vs_team_b_YYYY-MM-DD"
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
    # This ensures narrative verdict and SA Bookmaker Odds table use the same source.
    edge = await _refresh_edge_from_odds_db(edge)

    # 1. Match context
    ctx = await _get_match_context(
        home,
        away,
        league,
        sport,
        home_key=home_key,
        away_key=away_key,
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

    # 2. Build tips from edge data
    # edge_v2 uses "edge_pct"/"outcome"/"fair_probability"; normalise field names
    tips = []
    ev = bot._normalise_edge_pct_contract(edge.get("ev"), edge.get("edge_pct", 0))
    if ev > 0:
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
        })

    # 3. Build edge_data for NarrativeSpec (W82-WIRE)
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
    }

    use_web_search = sweep_type == "full"
    model_label = "opus" if "opus" in model_id else "sonnet"

    # 4. NarrativeSpec → deterministic baseline (W82-WIRE)
    narrative = ""
    w82_baseline = ""
    w82_polished = None
    spec = None
    narrative_source = "w82"
    served_model = model_label
    try:
        from narrative_spec import build_narrative_spec, _render_baseline
        spec = build_narrative_spec(ctx, _pregen_edge_data, tips, sport)
        narrative = _render_baseline(spec)
        narrative = _sanitise_jargon(narrative)
        narrative = _apply_sport_subs(narrative, sport)
        narrative = _final_polish(narrative, _pregen_edge_data)
        w82_baseline = narrative
        log.info("Pregen W82-WIRE: baseline rendered for %s", match_key)
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

    # 5. W84-CONFIRM-1: W84 is the permanent default generation path.
    # W82 baseline is always computed first and remains the per-row fallback.
    if narrative and spec is not None and evidence_pack is not None:
        try:
            prompt_text = format_evidence_prompt(evidence_pack, spec)
            resp = await claude.messages.create(
                model=SHADOW_MODEL,
                max_tokens=1200,
                messages=[{"role": "user", "content": prompt_text}],
                timeout=45.0,
            )
            model_draft = _strip_preamble(_extract_text_from_response(resp)).strip()
            sanitized_draft = sanitize_ai_response(model_draft)
            sanitized_draft = _strip_model_generated_h2h_references(sanitized_draft)
            sanitized_draft = _strip_model_generated_sharp_references(sanitized_draft)
            h2h_sentence = _build_h2h_injection(evidence_pack, spec)
            if h2h_sentence:
                sanitized_draft = _inject_h2h_sentence(sanitized_draft, h2h_sentence)
            sharp_sentence = _build_sharp_injection(evidence_pack, spec)
            if sharp_sentence:
                sanitized_draft = _inject_sharp_sentence(sanitized_draft, sharp_sentence)
            # R12-BUILD-03 Fix 3b: Suppress AFTER all injections (belt-and-suspenders)
            sanitized_draft = _suppress_shadow_banned_phrases(sanitized_draft)

            # R12-BUILD-03 Fix 2: Force-inject correct verdict bookmaker+odds
            # BEFORE verify, so the verifier sees the correct data.
            # Sonnet substitutes wrong bookmaker ~40% of the time for unusual names.
            _fix2_bk = tips[0]["bookie"] if tips else ""
            _fix2_odds = tips[0]["odds"] if tips else 0
            if _fix2_bk and _fix2_odds:
                sanitized_draft = _realign_verdict_bookmaker(
                    sanitized_draft, _fix2_bk, float(_fix2_odds)
                )
                # Fix 2b: If realign didn't fix it, force-inject bk@price into verdict
                if not _verdict_bookmaker_aligned(sanitized_draft, _fix2_bk, float(_fix2_odds)):
                    import re as _re2
                    _v_start = sanitized_draft.find("\U0001f3c6")  # 🏆
                    if _v_start != -1:
                        _v_section = sanitized_draft[_v_start:]
                        _odds_str = f"{float(_fix2_odds):.2f}"
                        # Find any "@ X.XX" or "at X.XX" pattern and replace with correct values
                        _v_fixed = _re2.sub(
                            r'(?:\b\w[\w\s]*?)\s*@\s*\d+\.\d{2}',
                            f'{_fix2_bk} @ {_odds_str}',
                            _v_section,
                            count=1,
                        )
                        if _v_fixed == _v_section:
                            # No @ pattern found — append recommendation
                            _v_fixed = _v_section.rstrip() + f" ({_fix2_bk} @ {_odds_str})"
                        sanitized_draft = sanitized_draft[:_v_start] + _v_fixed

            passed, report = verify_shadow_narrative(sanitized_draft, evidence_pack, spec)
            if passed:
                candidate = report.get("sanitized_draft") or sanitized_draft
                # BASELINE-FIX: Verify verdict bookmaker+price matches tip data
                _tip_bk = tips[0]["bookie"] if tips else ""
                _tip_odds = tips[0]["odds"] if tips else 0
                if _verdict_bookmaker_aligned(candidate, _tip_bk, _tip_odds):
                    narrative = candidate
                    narrative_source = "w84"
                    served_model = "opus" if "opus" in SHADOW_MODEL else "sonnet"
                    log.info("W84 SERVED for %s", match_key)
                else:
                    # Attempt to realign before falling back
                    realigned = _realign_verdict_bookmaker(candidate, _tip_bk, _tip_odds)
                    if _verdict_bookmaker_aligned(realigned, _tip_bk, _tip_odds):
                        narrative = realigned
                        narrative_source = "w84"
                        served_model = "opus" if "opus" in SHADOW_MODEL else "sonnet"
                        log.info(
                            "W84 SERVED (realigned) for %s: verdict → %s@%.2f",
                            match_key, _tip_bk, _tip_odds,
                        )
                    else:
                        log.warning(
                            "W84 VERDICT MISMATCH for %s: verdict has wrong bookmaker/price "
                            "(expected %s@%.2f) — serving W82 fallback",
                            match_key, _tip_bk, _tip_odds,
                        )
            else:
                reasons = "; ".join(report.get("rejection_reasons", [])[:3]) or "verification failed"
                log.warning("W84 VERIFY FAIL for %s: %s — serving W82 fallback", match_key, reasons)
        except Exception as exc:
            log.warning("W84 ERROR for %s: %s — serving W82 fallback", match_key, exc)

    # R11-BUILD-01 Fix A (Option A): Inject H2H into W82 fallback.
    # _inject_h2h_sentence() was only applied inside the W84 path above. When W84
    # fails verification, the W82 baseline lacks the last-score suffix, causing
    # _has_stale_h2h_summary() to reject the cached entry on read (loop).
    if narrative and narrative_source == "w82" and evidence_pack is not None and spec is not None:
        _w82_h2h = _build_h2h_injection(evidence_pack, spec)
        if _w82_h2h:
            narrative = _inject_h2h_sentence(narrative, _w82_h2h)

    if not narrative or narrative.strip() == "NO_DATA":
        return {"match_key": match_key, "success": False, "duration": time.time() - t0}

    # 7b. W69-VERIFY Layer 2: Post-generation cross-check (Opus full sweeps only)
    if use_web_search and narrative:
        contradictions = await _verify_narrative_claims(narrative, home, away, claude)
        if contradictions:
            log.warning("Layer 2 contradictions for %s: %s", match_key, contradictions)
            # Strip lines containing contradicted claims
            for c in contradictions:
                # Extract the claim text after "CONTRADICTED"
                claim_text = c.split("CONTRADICTED", 1)[-1].strip().strip(":-— ")
                if claim_text and len(claim_text) > 10:
                    # Try to find and remove the offending line
                    for line in narrative.split("\n"):
                        if any(word in line.lower() for word in claim_text.lower().split()[:3]):
                            narrative = narrative.replace(line, "")
                            break
            narrative = re.sub(r'\n{3,}', '\n\n', narrative)

    # BASELINE-FIX: Final verdict alignment enforcement.
    # After all post-processing (Layer 2 etc.), ensure the narrative still has
    # the correct bookmaker+price matching the odds table tip data.
    if narrative and tips:
        _final_bk = tips[0]["bookie"]
        _final_odds = tips[0]["odds"]
        if not _verdict_bookmaker_aligned(narrative, _final_bk, _final_odds):
            narrative = _realign_verdict_bookmaker(narrative, _final_bk, _final_odds)
            if not _verdict_bookmaker_aligned(narrative, _final_bk, _final_odds):
                # Realignment failed — fall back to W82 baseline which is guaranteed correct
                if w82_baseline:
                    log.warning(
                        "BASELINE-FIX: final alignment failed for %s — reverting to W82 baseline",
                        match_key,
                    )
                    narrative = w82_baseline
                    narrative_source = "w82"

    # REGFIX-03 WIRED: Validate Sonnet-generated (W84) narrative against sport's
    # banned-term dictionary BEFORE it reaches narrative_cache.
    # Failure mode 3 (cricket described as "African football") can only originate
    # in the W84 AI path — W82 baseline is code-generated and contamination-free.
    if narrative and narrative_source == "w84":
        _sv_valid, _sv_banned = validate_sport_text(narrative, sport)
        if not _sv_valid:
            log.warning(
                "SPORT VALIDATOR BLOCKED: %s narrative for %s contained banned terms %s"
                " — falling back to W82 template",
                sport, match_key, _sv_banned,
            )
            if w82_baseline:
                narrative = w82_baseline
                narrative_source = "w82"

    # 8. Build the full HTML message (simplified — no user-specific gating)
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

    # W75-FIX: edge_v2 tier is authoritative — no EV-threshold fallback
    edge_tier = edge.get("tier", "bronze")

    # Inject edge badge into verdict
    if narrative and tips:
        try:
            from services.edge_rating import EdgeRating, EDGE_EMOJIS, EDGE_LABELS
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

    # 9. Return cache-write data (caller batch-writes after all generation)
    duration = time.time() - t0
    return {
        "match_key": match_key, "success": True, "model": served_model,
        "duration": duration, "narrative": narrative,
        "_cache": {
            "match_id": match_key,
            "html": msg,
            "tips": tips,
            "edge_tier": edge_tier,
            "model": served_model,
            "evidence_json": evidence_json,
            "narrative_source": narrative_source,
            "_shadow": {
                "match_key": match_key,
                "pack": evidence_pack,
                "spec": spec,
                "evidence_json": evidence_json,
                "w82_baseline": w82_baseline or narrative,
                "w82_polished": w82_polished,
                "richness_score": evidence_pack.richness_score,
            },
        },
    }


async def _verify_and_fill_cache(
    edges: list[dict],
    model_id: str,
    claude: anthropic.AsyncAnthropic,
    sweep: str,
    shadow_tasks: list[asyncio.Task] | None = None,
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
            result = await _generate_one(edge, model_id, claude, sweep_type=sweep)
            if result.get("success") and result.get("_cache"):
                pw = result["_cache"]
                try:
                    await _store_narrative_cache(
                        pw["match_id"],
                        pw["html"],
                        pw["tips"],
                        pw["edge_tier"],
                        pw["model"],
                        evidence_json=pw.get("evidence_json"),
                        narrative_source=pw.get("narrative_source", "w82"),
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


async def main(sweep: str) -> None:
    """Run the pre-generation sweep."""
    model_id = MODELS.get(sweep, MODELS["refresh"])
    model_label = "Opus" if sweep == "full" else "Sonnet"
    log.info(
        "Starting %s sweep with %s (%s)",
        sweep,
        model_label,
        model_id,
    )

    if not await _wait_for_scraper_writer_window():
        return

    # Runtime sweeps validate schema read-only; deploy/startup migration must happen elsewhere.
    _validate_pregen_runtime_schema()

    # Shadow pregen must track the same edge reality the live bot serves.
    edges = await asyncio.to_thread(_load_shadow_pregen_edges, 100)

    if not edges:
        log.info("No live edges found — nothing to pre-generate")
        return

    log.info("Found %d live edges", len(edges))

    # Filter for refresh/uncached_only mode: skip edges with fresh cache
    if sweep in ("refresh", "uncached_only"):
        filtered = []
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
        log.info("%s mode: %d/%d edges need regeneration", sweep, len(filtered), len(edges))
        edges = filtered

    if not edges:
        log.info("All edges have fresh cache — nothing to do")
        return

    # Initialize Claude client
    claude = anthropic.AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    results = {
        "success": 0,
        "failed": 0,
        "skipped": 0,
        "dropped": 0,  # BASELINE-FIX: match-level dedup drops
        "total_duration": 0.0,
        "w84_served": 0,
        "w82_fallback": 0,
    }
    sweep_verdicts: list[str] = []
    pending_writes: list[dict] = []  # W79-P3D: collect cache writes, batch after generation

    for i, edge in enumerate(edges, 1):
        mk = edge.get("match_key", "")

        # W67-CALIBRATE Fix 5: Skip no-odds matches
        if not edge.get("best_odds") or edge.get("edge_pct", 0) == 0:
            log.info("SKIP: %s — no active odds data", mk)
            results["skipped"] += 1
            continue

        # BASELINE-FIX: match-level dedup — drop if already being generated
        if mk in _in_progress_matches:
            log.info("DROP: %s — already in progress (duplicate edge in sweep)", mk)
            results["dropped"] += 1
            continue
        _in_progress_matches.add(mk)

        log.info("[%d/%d] Generating narrative for %s (%s)...", i, len(edges), mk, model_label)

        try:
            result = await _generate_one(edge, model_id, claude, sweep_type=sweep)
            if result.get("success"):
                results["success"] += 1
                log.info("  -> OK in %.1fs", result["duration"])
                # Collect cache write for batch
                if result.get("_cache"):
                    pending_writes.append(result["_cache"])
                    if result["_cache"].get("narrative_source") == "w84":
                        results["w84_served"] += 1
                    else:
                        results["w82_fallback"] += 1
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

        # Rate limit: 1s between calls
        if i < len(edges):
            await asyncio.sleep(1.0)

    # W79-P3D: Batch-write all narratives to cache (separate from generation)
    if pending_writes:
        log.info("Writing %d narratives to cache...", len(pending_writes))
        write_ok = 0
        for pw in pending_writes:
            try:
                await _store_narrative_cache(
                    pw["match_id"],
                    pw["html"],
                    pw["tips"],
                    pw["edge_tier"],
                    pw["model"],
                    evidence_json=pw.get("evidence_json"),
                    narrative_source=pw.get("narrative_source", "w82"),
                )
                write_ok += 1
            except Exception as exc:
                log.warning("Cache write failed for %s: %s", pw["match_id"], exc)
        log.info("Cache writes: %d/%d successful", write_ok, len(pending_writes))

    # W67-CALIBRATE: Verdict balance check
    _check_verdict_balance(sweep_verdicts)

    # W79-P3D: Verify cache coverage after sweep
    await _verify_and_fill_cache(edges, model_id, claude, sweep)

    # Summary
    log.info(
        "\n=== Sweep Complete ===\n"
        "Mode: %s (%s)\n"
        "Total: %d edges\n"
        "Generated: %d\n"
        "Failed: %d\n"
        "Skipped (no odds): %d\n"
        "Dropped (duplicate): %d\n"
        "W84 served: %d\n"
        "W82 fallback: %d\n"
        "Total time: %.1fs\n"
        "Avg per edge: %.1fs",
        sweep,
        model_label,
        len(edges),
        results["success"],
        results["failed"],
        results["skipped"],
        results["dropped"],
        results["w84_served"],
        results["w82_fallback"],
        results["total_duration"],
        results["total_duration"] / max(len(edges), 1),
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pre-generate narratives for live edges")
    parser.add_argument(
        "--sweep", choices=["full", "refresh", "uncached_only"], required=True,
        help="full = all edges, refresh = stale/expired only, uncached_only = new edges without cache",
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

    _pregen_success = False
    try:
        asyncio.run(main(args.sweep))
        _pregen_success = True
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
