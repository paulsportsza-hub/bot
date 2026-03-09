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
import sys
import time

# Add project paths
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, "/home/paulsportsza")
sys.path.insert(0, "/home/paulsportsza/scrapers")

from dotenv import load_dotenv
_bot_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_bot_dir, ".env"))

import anthropic

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("pregenerate")

# Model IDs
MODELS = {
    "full": os.environ.get("NARRATIVE_MODEL", "claude-sonnet-4-20250514"),
    "refresh": os.environ.get("NARRATIVE_MODEL", "claude-sonnet-4-20250514"),
    "uncached_only": os.environ.get("NARRATIVE_MODEL", "claude-sonnet-4-20250514"),
}

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
    _check_verdict_balance,
    _extract_text_from_response,
    _strip_preamble,
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


async def _get_match_context(home: str, away: str, league: str, sport: str) -> dict:
    """Fetch ESPN match context for a match."""
    try:
        from scrapers.match_context_fetcher import get_match_context
        return await get_match_context(
            home_team=home.lower().replace(" ", "_"),
            away_team=away.lower().replace(" ", "_"),
            league=league,
            sport=sport,
        )
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

    # Parse team names from match_key if not provided (edge_v2 dicts omit them)
    if not home or not away:
        # match_key format: "team_a_vs_team_b_YYYY-MM-DD"
        parts = match_key.rsplit("_", 1)[0] if "_" in match_key else match_key
        if "_vs_" in parts:
            home_raw, away_raw = parts.split("_vs_", 1)
            home = home or home_raw.replace("_", " ").title()
            away = away or away_raw.replace("_", " ").title()

    league = edge.get("league", "")
    sport = edge.get("sport", "soccer")
    commence = edge.get("commence_time", "")

    # Refine "combat" to mma/boxing
    if sport == "combat":
        if "ufc" in league.lower():
            sport = "mma"
        elif "box" in league.lower():
            sport = "boxing"

    # 1. Match context
    ctx = await _get_match_context(home, away, league, sport)

    # 2. Build tips from edge data
    # edge_v2 uses "edge_pct"/"outcome"/"fair_probability"; normalise field names
    tips = []
    ev = edge.get("ev") or edge.get("edge_pct", 0)
    if ev > 0:
        fair_prob = edge.get("fair_prob") or edge.get("fair_probability", 0)
        tips.append({
            "outcome": edge.get("recommended_outcome") or edge.get("outcome", "?"),
            "odds": edge.get("best_odds", 0),
            "bookie": edge.get("best_bookmaker", "?"),
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
    spec = None
    try:
        from narrative_spec import build_narrative_spec, _render_baseline
        spec = build_narrative_spec(ctx, _pregen_edge_data, tips, sport)
        narrative = _render_baseline(spec)
        narrative = _sanitise_jargon(narrative)
        narrative = _apply_sport_subs(narrative, sport)
        narrative = _final_polish(narrative, _pregen_edge_data)
        log.info("Pregen W82-WIRE: baseline rendered for %s", match_key)
    except Exception as exc:
        log.error("Pregen W82-WIRE: baseline failed for %s: %s", match_key, exc)
        narrative = ""

    # 5. W82-POLISH: optional constrained LLM polish (pre-gen always attempts)
    if narrative and spec is not None:
        try:
            exemplars = _get_exemplars_for_prompt(
                spec.home_story_type, spec.away_story_type, ev, sport
            )
            prompt = _build_polish_prompt(narrative, spec, exemplars)
            resp = await claude.messages.create(
                model=model_id,
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
                timeout=40.0,
            )
            polished = _strip_preamble(_extract_text_from_response(resp))
            if polished and _validate_polish(polished, narrative, spec):
                log.info("POLISH PASS for %s", match_key)
                polished = _sanitise_jargon(polished)
                polished = _apply_sport_subs(polished, sport)
                polished = _final_polish(polished, _pregen_edge_data)
                narrative = polished
            else:
                log.warning("POLISH FAIL for %s — serving baseline", match_key)
        except Exception as exc:
            log.warning("POLISH ERROR for %s: %s — serving baseline", match_key, exc)

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
        "match_key": match_key, "success": True, "model": model_label,
        "duration": duration, "narrative": narrative,
        "_cache": {"match_id": match_key, "html": msg, "tips": tips, "edge_tier": edge_tier, "model": model_label},
    }


async def _verify_and_fill_cache(
    edges: list[dict],
    model_id: str,
    claude: anthropic.AsyncAnthropic,
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
            result = await _generate_one(edge, model_id, claude, sweep_type=sweep)
            if result.get("success") and result.get("_cache"):
                pw = result["_cache"]
                try:
                    await _store_narrative_cache(
                        pw["match_id"], pw["html"], pw["tips"], pw["edge_tier"], pw["model"]
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
    log.info("Starting %s sweep with %s (%s)", sweep, model_label, model_id)

    # Ensure table exists
    _ensure_narrative_cache_table()

    # Get all live edges
    try:
        from scrapers.edge.edge_v2_helper import get_top_edges
        edges = await asyncio.to_thread(get_top_edges, n=100)
    except Exception as exc:
        log.error("Failed to get edges: %s", exc)
        return

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
        log.info("%s mode: %d/%d edges need regeneration", sweep, len(filtered), len(edges))
        edges = filtered

    if not edges:
        log.info("All edges have fresh cache — nothing to do")
        return

    # Initialize Claude client
    claude = anthropic.AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    results = {"success": 0, "failed": 0, "skipped": 0, "total_duration": 0.0}
    sweep_verdicts: list[str] = []
    pending_writes: list[dict] = []  # W79-P3D: collect cache writes, batch after generation

    for i, edge in enumerate(edges, 1):
        mk = edge.get("match_key", "")

        # W67-CALIBRATE Fix 5: Skip no-odds matches
        if not edge.get("best_odds") or edge.get("edge_pct", 0) == 0:
            log.info("SKIP: %s — no active odds data", mk)
            results["skipped"] += 1
            continue

        log.info("[%d/%d] Generating narrative for %s (%s)...", i, len(edges), mk, model_label)

        try:
            result = await _generate_one(edge, model_id, claude, sweep_type=sweep)
            if result.get("success"):
                results["success"] += 1
                log.info("  -> OK in %.1fs", result["duration"])
                # Collect cache write for batch
                if result.get("_cache"):
                    pending_writes.append(result["_cache"])
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
                    pw["match_id"], pw["html"], pw["tips"], pw["edge_tier"], pw["model"]
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
        "Success: %d\n"
        "Failed: %d\n"
        "Skipped: %d\n"
        "Total time: %.1fs\n"
        "Avg per edge: %.1fs",
        sweep, model_label, len(edges),
        results["success"], results["failed"], results["skipped"],
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
    _PID_FILE = os.path.expanduser("~/logs/pregen.pid")
    _pid_fh = None
    try:
        _pid_fh = open(_PID_FILE, "w")
        _fcntl.flock(_pid_fh.fileno(), _fcntl.LOCK_EX | _fcntl.LOCK_NB)
        _pid_fh.write(str(os.getpid()) + "\n")
        _pid_fh.flush()
    except (IOError, OSError):
        log.warning("pregenerate_narratives.py: another instance is already running — exiting.")
        sys.exit(0)

    try:
        asyncio.run(main(args.sweep))
    finally:
        if _pid_fh:
            try:
                _fcntl.flock(_pid_fh.fileno(), _fcntl.LOCK_UN)
                _pid_fh.close()
                os.unlink(_PID_FILE)
            except Exception:
                pass
