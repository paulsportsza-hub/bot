#!/usr/bin/env python3
"""W67-CALIBRATE: 20-Game Opus Benchmark (Verdict Calibration).

Runs the FULL current pipeline on 20 specific matches using Claude Opus.
Includes: W67 graduated stale tiers, 6 verdict decision rules, 19 banned phrases,
verdict balance check. Tracks positive vs skip vs conditional verdicts.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
import time

# Add project paths
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import BOT_ROOT, ensure_scrapers_importable
ensure_scrapers_importable()

from dotenv import load_dotenv
_bot_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_bot_dir, ".env"))

import anthropic

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("opus_audit")

MODEL_ID = os.environ.get("NARRATIVE_MODEL", "claude-sonnet-4-20250514")

# Import narrative functions from bot.py
import bot
from bot import (
    build_verified_narrative,
    _build_analyst_prompt,
    sanitize_ai_response,
    validate_sport_context,
    fact_check_output,
    _ensure_risk_not_empty,
    _has_empty_sections,
    _has_banned_patterns,
    _check_stale_contradiction,
    _format_verified_context,
    _format_signal_data_for_prompt,
    _build_programmatic_narrative,
    _validate_breakdown,
    _extract_text_from_response,
    WEB_SEARCH_TOOL,
    SPORT_TERMINOLOGY,
)

# ── 20 Matches (W65: same as W61, blues_vs_crusaders replaced with PSL) ──

# W73-LAUNCH: 10-match Sonnet benchmark (was 20-match Opus audit)
MATCHES = [
    # EPL (4 matches)
    {"match_id": "arsenal_vs_everton_2026-03-14", "home": "Arsenal", "away": "Everton", "league": "epl", "sport": "soccer"},
    {"match_id": "chelsea_vs_newcastle_2026-03-14", "home": "Chelsea", "away": "Newcastle", "league": "epl", "sport": "soccer"},
    {"match_id": "manchester_united_vs_aston_villa_2026-03-15", "home": "Manchester United", "away": "Aston Villa", "league": "epl", "sport": "soccer"},
    {"match_id": "liverpool_vs_tottenham_2026-03-15", "home": "Liverpool", "away": "Tottenham", "league": "epl", "sport": "soccer"},
    # Champions League (2 matches)
    {"match_id": "real_madrid_vs_manchester_city_2026-03-11", "home": "Real Madrid", "away": "Manchester City", "league": "champions_league", "sport": "soccer"},
    {"match_id": "paris_saint_germain_vs_chelsea_2026-03-11", "home": "Paris Saint Germain", "away": "Chelsea", "league": "champions_league", "sport": "soccer"},
    # Six Nations Rugby (2 matches)
    {"match_id": "scotland_vs_france_2026-03-07", "home": "Scotland", "away": "France", "league": "six_nations", "sport": "rugby"},
    {"match_id": "italy_vs_england_2026-03-07", "home": "Italy", "away": "England", "league": "six_nations", "sport": "rugby"},
    # PSL (1 match)
    {"match_id": "orlando_pirates_vs_richards_bay_2026-03-11", "home": "Orlando Pirates", "away": "Richards Bay", "league": "psl", "sport": "soccer"},
    # Super Rugby (1 match)
    {"match_id": "brumbies_vs_reds_2026-03-07", "home": "Brumbies", "away": "Queensland Reds", "league": "super_rugby", "sport": "rugby"},
]


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
    match_id: str, home: str, away: str, league: str, sport: str,
) -> str:
    """Fetch enrichment data (weather, lineup, injuries)."""
    parts = []
    home_key = home.lower().replace(" ", "_")
    away_key = away.lower().replace(" ", "_")

    # Weather
    try:
        from scrapers.weather_helper import get_venue_city, format_weather_for_narrative_sync
        city = get_venue_city(home_key)
        if city:
            weather = format_weather_for_narrative_sync(city, match_id.rsplit("_", 1)[-1], sport)
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


def _get_edge_v2(match_id: str, sport: str, league: str) -> dict:
    """Compute edge_v2 data for a match. Returns best edge dict or empty dict."""
    try:
        from scrapers.edge.edge_v2_helper import calculate_edge_v2
        # Try all 3 outcomes and pick the one with the highest edge
        best_edge = None
        best_ev = -999
        for outcome in ["home", "draw", "away"]:
            try:
                edge = calculate_edge_v2(
                    match_id, outcome=outcome, market_type="1x2",
                    sport=sport, league=league,
                )
                if edge and edge.get("edge_pct", 0) > best_ev:
                    best_ev = edge["edge_pct"]
                    best_edge = edge
            except Exception:
                continue
        return best_edge or {}
    except Exception as exc:
        log.warning("edge_v2 failed for %s: %s", match_id, exc)
        return {}


async def _generate_one(match: dict, claude: anthropic.AsyncAnthropic) -> dict:
    """Generate narrative for a single match using the full production pipeline.

    Returns dict with all metadata + the full narrative output.
    """
    t0 = time.time()
    match_id = match["match_id"]
    home = match["home"]
    away = match["away"]
    league = match["league"]
    sport = match["sport"]

    log.info("Processing %s vs %s (%s)...", home, away, league)

    # 1. Edge V2 signals
    try:
        edge = await asyncio.to_thread(_get_edge_v2, match_id, sport, league)
    except Exception as exc:
        log.warning("edge_v2 error for %s: %s", match_id, exc)
        edge = {}
    ev = edge.get("edge_pct", 0)
    has_signals = bool(edge.get("signals"))

    # 2. Match context (ESPN)
    ctx = await _get_match_context(home, away, league, sport)
    if not isinstance(ctx, dict):
        log.warning("ctx is %s not dict for %s, defaulting to {}", type(ctx), match_id)
        ctx = {}
    has_context = ctx.get("data_available", False)

    # 3. Build tips from edge data
    tips = []
    if ev > 0 and edge:
        tips.append({
            "outcome": edge.get("outcome", "?"),
            "odds": edge.get("best_odds", 0),
            "bookie": edge.get("best_bookmaker", "?"),
            "ev": ev,
            "prob": round(edge.get("fair_probability", 0) * 100, 1) if edge.get("fair_probability") else 0,
            "edge_v2": edge,
        })

    # 4. Enrichment
    enrichment = await _get_enrichment(match_id, home, away, league, sport)

    # 5. Build verified narrative (Pass 1 — code)
    try:
        verified_sentences = build_verified_narrative(ctx, tips, enrichment, sport)
    except Exception as exc:
        log.warning("build_verified_narrative failed for %s: %s", match_id, exc)
        verified_sentences = {"setup": [], "edge": [], "risk": [], "verdict": []}

    # 6. Build user message with IMMUTABLE CONTEXT + SIGNAL DATA (W59 injection)
    verified_context = _format_verified_context(ctx)
    signal_data_block = _format_signal_data_for_prompt(edge)

    from html import escape as h
    user_msg_parts = [f"Match: {h(home)} vs {h(away)}"]

    section_labels = [
        ("setup", "SETUP FACTS"), ("edge", "EDGE FACTS"),
        ("risk", "RISK FACTS"), ("verdict", "VERDICT FACTS"),
    ]
    has_any = any(verified_sentences.get(s) for s, _ in section_labels)
    if has_any or signal_data_block:
        user_msg_parts.append("\n== IMMUTABLE CONTEXT (verified -- do not alter facts) ==")
        for section, label in section_labels:
            sentences = verified_sentences.get(section, [])
            if sentences:
                user_msg_parts.append(f"\n{label}:")
                for s in sentences:
                    user_msg_parts.append(f"- {s}")
            if section == "edge" and signal_data_block:
                user_msg_parts.append(f"\n{signal_data_block}")
        user_msg_parts.append("\n== END IMMUTABLE CONTEXT ==")

    # Odds context
    odds_lines = []
    if tips:
        for t in tips:
            odds_lines.append(f"{t['outcome']}: {t['odds']:.2f} ({t['bookie']}) EV {t['ev']:+.1f}%")
    user_msg_parts.append(f"\nOdds:\n" + "\n".join(odds_lines) if odds_lines else "\nNo odds data.")
    user_message = "\n".join(user_msg_parts)

    # 7. Get banned terms
    banned_terms_str = ""
    try:
        from scrapers.sport_terms import SPORT_BANNED_TERMS
        banned_list = SPORT_BANNED_TERMS.get(sport, {}).get("banned", [])
        banned_terms_str = ", ".join(banned_list) if banned_list else ""
    except ImportError:
        pass

    # 8. Call Claude Opus with quality-gate retry
    system_prompt = _build_analyst_prompt(sport, banned_terms=banned_terms_str, mandatory_search=True)
    narrative = ""
    max_attempts = 2
    input_tokens = 0
    output_tokens = 0

    for attempt in range(1, max_attempts + 1):
        try:
            messages = [{"role": "user", "content": user_message}]
            if attempt >= 2 and narrative:
                messages = [
                    {"role": "user", "content": user_message},
                    {"role": "assistant", "content": narrative},
                    {"role": "user", "content": (
                        "YOUR PREVIOUS OUTPUT WAS REJECTED BY OUR QUALITY SYSTEM.\n"
                        "REWRITE the ENTIRE analysis. Be SPECIFIC: name bookmakers, cite exact "
                        "odds prices, reference actual form strings from IMMUTABLE CONTEXT."
                    )},
                ]
            resp = await claude.messages.create(
                model=MODEL_ID,
                max_tokens=1024,
                system=system_prompt,
                messages=messages,
                tools=[WEB_SEARCH_TOOL],
                timeout=90.0,  # W69-VERIFY: longer timeout for web search
            )
            narrative = _extract_text_from_response(resp)
            input_tokens = resp.usage.input_tokens
            output_tokens = resp.usage.output_tokens
        except Exception as exc:
            log.error("Claude error for %s (attempt %d): %s", match_id, attempt, exc)
            narrative = ""
            break

        if not narrative or narrative.strip() == "NO_DATA":
            break

        # Post-process (full W59+W60 pipeline)
        try:
            narrative = sanitize_ai_response(narrative)
        except Exception as exc:
            log.error("sanitize_ai_response failed for %s: %s", match_id, exc, exc_info=True)
        try:
            narrative = validate_sport_context(narrative, sport)
        except Exception as exc:
            log.error("validate_sport_context failed for %s: %s", match_id, exc, exc_info=True)
        try:
            narrative = fact_check_output(narrative, ctx, tips=tips, sport=sport)
        except Exception as exc:
            log.error("fact_check_output failed for %s: %s", match_id, exc, exc_info=True)
        try:
            narrative = _ensure_risk_not_empty(narrative, tips=tips, sport=sport)
        except Exception as exc:
            log.error("_ensure_risk_not_empty failed for %s: %s", match_id, exc, exc_info=True)

        # W63-EMPTY: Final empty section guard
        if _has_empty_sections(narrative):
            log.warning("Empty sections in %s — using programmatic fallback", match_id)
            _prog = _build_programmatic_narrative({}, tips, sport)
            if _prog:
                narrative = sanitize_ai_response(_prog)

        if _has_banned_patterns(narrative) and attempt < max_attempts:
            log.warning("Banned phrases in %s (attempt %d) — retrying", match_id, attempt)
            continue

        # W64-VERDICT: Stale price contradiction check
        if _check_stale_contradiction(narrative, edge) and attempt < max_attempts:
            log.warning("Stale contradiction in %s (attempt %d) — retrying", match_id, attempt)
            continue

        try:
            passed, issues = _validate_breakdown(narrative, ctx)
        except Exception as exc:
            log.error("_validate_breakdown failed for %s: %s", match_id, exc, exc_info=True)
            passed, issues = True, []  # Skip quality gate on error
        if passed:
            break
        elif attempt == max_attempts:
            log.warning("Quality gate failed for %s, falling back to programmatic", match_id)
            try:
                narrative = _build_programmatic_narrative(ctx, tips, sport)
                if narrative:
                    narrative = sanitize_ai_response(narrative)
            except Exception as exc:
                log.error("_build_programmatic_narrative failed for %s: %s", match_id, exc, exc_info=True)
            break

    duration = time.time() - t0
    is_no_data = not narrative or narrative.strip() == "NO_DATA"

    # Quality checks
    sa_books = ["hollywoodbets", "wsb", "supabets", "gbets", "betway", "sportingbet",
                "playabets", "supersportbet", "world sports betting"]
    lower = narrative.lower() if narrative else ""
    names_bookmakers = any(bk in lower for bk in sa_books)
    cites_odds = bool(re.search(r"\d+\.\d{2}", narrative)) if narrative else False

    # W67: Full banned phrases list (19 total)
    banned_phrases = [
        "back the value where", "odds diverge", "form inconsistency is the",
        "both sides have something", "one bad half can flip",
        "proceed with caution", "value play",
        # W64-VERDICT additions
        "grab it before", "before they wake up", "before they catch up",
        "before they realise", "before they adjust", "move fast",
        "won't last forever", "before they slash",
        # W67-CALIBRATE additions
        "the numbers say value, but", "one to watch, not back",
        "this one to watch", "makes this one to watch",
    ]
    banned_hits = [bp for bp in banned_phrases if bp in lower]

    has_signal_ref = any(kw in lower for kw in [
        "composite", "signal", "confirming", "contradicting",
        "benchmark", "pinnacle", "consensus", "edge v2",
        "steam", "tipster", "market agreement",
    ]) if narrative else False

    # W67: Verdict classification (6 decision rules + positive/skip/conditional)
    verdict_style = "unknown"
    verdict_class = "unknown"  # positive, skip, conditional
    if narrative:
        verdict_section = ""
        if "🏆" in narrative:
            vs_start = narrative.index("🏆")
            verdict_section = narrative[vs_start:].lower()
        # Classify by W67 decision rules
        if any(kw in verdict_section for kw in ["likely gone", "verify", "priced", "hours ago"]):
            verdict_style = "dead_price_skip"
            verdict_class = "skip"
        elif any(kw in verdict_section for kw in ["caution", "check live odds", "pricing delay"]):
            verdict_style = "stale_caution"
            verdict_class = "skip"
        elif any(kw in verdict_section for kw in ["sharpest value", "signals confirm", "composite hits"]):
            verdict_style = "conviction_play"
            verdict_class = "positive"
        elif any(kw in verdict_section for kw in ["sits", "above", "benchmark", "supporting"]):
            verdict_style = "price_target"
            verdict_class = "positive"
        elif any(kw in verdict_section for kw in ["offers", "over fair value", "fair value"]):
            verdict_style = "clean_edge"
            verdict_class = "positive"
        elif any(kw in verdict_section for kw in ["pure price play", "both point the other"]):
            verdict_style = "contrarian"
            verdict_class = "conditional"
        elif any(kw in verdict_section for kw in ["watch", "skip", "not enough", "pass on"]):
            verdict_style = "honest_skip"
            verdict_class = "skip"
        else:
            # Heuristic: if it names a bookmaker + price, it's likely positive
            if re.search(r"\d+\.\d{2}", verdict_section) and any(bk in verdict_section for bk in sa_books):
                verdict_class = "positive"

    # W64: Stale contradiction detection (for reporting, not retry)
    stale_contradiction = _check_stale_contradiction(narrative, edge) if narrative else False

    # W63: Empty section detection
    has_empty = _has_empty_sections(narrative) if narrative else True

    return {
        "match_id": match_id,
        "home": home,
        "away": away,
        "league": league,
        "sport": sport,
        "duration": round(duration, 2),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "status": "NO_DATA" if is_no_data else "OK",
        "has_context": has_context,
        "has_signals": has_signals,
        "ev": round(ev, 1),
        "edge_tier": edge.get("tier", "none"),
        "names_bookmakers": names_bookmakers,
        "cites_odds": cites_odds,
        "banned_hits": banned_hits,
        "references_signals": has_signal_ref,
        "verdict_style": verdict_style,
        "verdict_class": verdict_class,
        "stale_contradiction": stale_contradiction,
        "has_empty_sections": has_empty,
        "narrative": narrative if not is_no_data else "NO_DATA",
        "user_message_preview": user_message[:500],
    }


async def main():
    """Run the 20-match Opus audit."""
    log.info("=" * 70)
    log.info("W73-LAUNCH: %d-Game Sonnet Benchmark", len(MATCHES))
    log.info("Model: %s", MODEL_ID)
    log.info("=" * 70)

    claude = anthropic.AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    results = []
    for i, match in enumerate(MATCHES, 1):
        log.info("[%d/%d] %s vs %s (%s)...", i, len(MATCHES), match["home"], match["away"], match["league"])
        try:
            result = await _generate_one(match, claude)
            results.append(result)
            status = result["status"]
            dur = result["duration"]
            tokens = result["output_tokens"]
            log.info("  -> %s in %.1fs (%d tokens)", status, dur, tokens)
        except Exception as exc:
            log.error("  -> FATAL ERROR for %s: %s", match["match_id"], exc)
            results.append({
                "match_id": match["match_id"],
                "home": match["home"],
                "away": match["away"],
                "league": match["league"],
                "sport": match["sport"],
                "duration": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "status": "ERROR",
                "narrative": f"ERROR: {exc}",
                "has_context": False,
                "has_signals": False,
                "names_bookmakers": False,
                "cites_odds": False,
                "banned_hits": [],
                "references_signals": False,
            })

        # Rate limit
        if i < len(MATCHES):
            await asyncio.sleep(1.0)

    # Summary
    ok = [r for r in results if r["status"] == "OK"]
    no_data = [r for r in results if r["status"] == "NO_DATA"]
    errors = [r for r in results if r["status"] == "ERROR"]

    log.info("\n" + "=" * 70)
    log.info("W67-CALIBRATE BENCHMARK SUMMARY")
    log.info("=" * 70)
    log.info("Full narratives: %d/20", len(ok))
    log.info("NO_DATA: %d/20", len(no_data))
    log.info("Errors: %d/20", len(errors))
    if ok:
        times = [r["duration"] for r in ok]
        import statistics
        log.info("Avg time: %.1fs | Min: %.1fs | Max: %.1fs | Median: %.1fs",
                 statistics.mean(times), min(times), max(times), statistics.median(times))
        log.info("Naming SA bookmakers: %d/%d", sum(1 for r in ok if r["names_bookmakers"]), len(ok))
        log.info("Citing specific odds: %d/%d", sum(1 for r in ok if r["cites_odds"]), len(ok))
        log.info("References signal data: %d/%d", sum(1 for r in ok if r["references_signals"]), len(ok))
        all_banned = []
        for r in ok:
            all_banned.extend(r.get("banned_hits", []))
        log.info("Banned phrase hits: %d (W67: 19 phrases checked)", len(all_banned))
        if all_banned:
            for bp in set(all_banned):
                log.info("  BANNED: '%s' x%d", bp, all_banned.count(bp))

        # W67 verdict metrics
        verdict_styles = [r.get("verdict_style", "unknown") for r in ok]
        verdict_classes = [r.get("verdict_class", "unknown") for r in ok]
        unique_styles = set(verdict_styles)
        log.info("Verdict style variety: %d unique styles (%s)",
                 len(unique_styles), ", ".join(sorted(unique_styles)))
        positive_count = sum(1 for v in verdict_classes if v == "positive")
        skip_count = sum(1 for v in verdict_classes if v == "skip")
        conditional_count = sum(1 for v in verdict_classes if v == "conditional")
        unknown_count = sum(1 for v in verdict_classes if v == "unknown")
        log.info("VERDICT DISTRIBUTION:")
        log.info("  Positive: %d/%d (%.0f%%)", positive_count, len(ok), positive_count / len(ok) * 100)
        log.info("  Skip: %d/%d (%.0f%%)", skip_count, len(ok), skip_count / len(ok) * 100)
        log.info("  Conditional: %d/%d (%.0f%%)", conditional_count, len(ok), conditional_count / len(ok) * 100)
        log.info("  Unknown: %d/%d", unknown_count, len(ok))
        target_met = positive_count >= len(ok) * 0.44
        log.info("  TARGET (>=44%% positive): %s", "PASS" if target_met else "FAIL")

        stale_count = sum(1 for r in ok if r.get("stale_contradiction"))
        log.info("Stale contradictions: %d/%d", stale_count, len(ok))
        empty_count = sum(1 for r in ok if r.get("has_empty_sections"))
        log.info("Empty sections: %d/%d", empty_count, len(ok))

    # Save raw JSON
    report_data = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "model": MODEL_ID,
        "wave": "W67",
        "total_matches": len(MATCHES),
        "results": results,
    }
    _reports_dir = BOT_ROOT.parent / "reports"
    _reports_dir.mkdir(parents=True, exist_ok=True)
    json_path = str(_reports_dir / "sonnet_benchmark_w73_20260307.json")
    with open(json_path, "w") as f:
        json.dump(report_data, f, indent=2, ensure_ascii=False)
    log.info("Raw results saved to: %s", json_path)


if __name__ == "__main__":
    asyncio.run(main())
