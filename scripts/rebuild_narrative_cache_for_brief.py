"""FIX-PREGEN-SIGNALS-DROP-AND-CACHE-FLUSH-01 Phase 4 wrapper.

The canonical pregen CLI does not accept --include-keys; per the brief's
escape hatch, we invoke ``_generate_one`` directly per match_key on the
candidate set (every match with an unsettled edge_results row, plus the
4 brief-flagged keys for belt-and-suspenders coverage).

Runs the full pregen pipeline (W82 baseline + evidence pack + verdict
cap + cache persistence) for each candidate, exercising the patched
``_pregen_edge_data`` block that now carries canonical
spec.signals + line_movement_direction.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

# Mirror pregenerate_narratives sys.path setup.
_BOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BOT_DIR))
_SCRAPERS_ROOT = _BOT_DIR.parent / "scrapers"
sys.path.insert(0, str(_SCRAPERS_ROOT.parent))
sys.path.insert(0, str(_SCRAPERS_ROOT))

from dotenv import load_dotenv

load_dotenv(_BOT_DIR / ".env")

from scripts import pregenerate_narratives as pregen  # noqa: E402

import bot  # noqa: E402  (also primes Sentry init)
from scrapers.db_connect import connect_odds_db  # noqa: E402
from scrapers.edge.edge_config import DB_PATH  # noqa: E402


BRIEF_KEYS = (
    "manchester_city_vs_brentford_2026-05-09",
    "liverpool_vs_chelsea_2026-05-09",
    "brighton_vs_wolves_2026-05-09",
    "fulham_vs_bournemouth_2026-05-09",
)


def _load_unsettled_edges_for_pregen() -> list[dict]:
    """Build edge dicts shaped like _edge_from_serving_tip / _build_baseline_edge.

    Reads unsettled edge_results rows directly so we can re-target the
    full set of currently-active edges without depending on the bot's
    serving-tip loader (which applies tier/punt filters).
    """
    conn = connect_odds_db(DB_PATH)
    conn.row_factory = lambda cur, row: dict(zip([c[0] for c in cur.description], row))
    try:
        rows = conn.execute(
            """
            SELECT match_key, sport, league, edge_tier, composite_score,
                   bet_type, recommended_odds, bookmaker, predicted_ev,
                   confirming_signals, recommended_at
            FROM edge_results
            WHERE result IS NULL
            ORDER BY recommended_at DESC
            """,
        ).fetchall()
    finally:
        conn.close()

    edges: list[dict] = []
    for row in rows:
        bet_type = (row.get("bet_type") or "").strip()
        outcome = "home"
        if ":" in bet_type:
            _, outcome = bet_type.split(":", 1)
        outcome = outcome.lower() or "home"
        match_key = row.get("match_key") or ""
        if not match_key or "_vs_" not in match_key:
            continue
        teams_part = match_key.rsplit("_", 1)[0]
        home_key, away_key = teams_part.split("_vs_", 1)
        home_display = bot._display_team_name(home_key) if hasattr(bot, "_display_team_name") else home_key
        away_display = bot._display_team_name(away_key) if hasattr(bot, "_display_team_name") else away_key
        odds = float(row.get("recommended_odds") or 0)
        ev_pct = float(row.get("predicted_ev") or 0)
        fair_prob = (1 + ev_pct / 100.0) / odds if odds else 0.0
        edge = {
            "match_key": match_key,
            "home_team": home_display,
            "away_team": away_display,
            "league": row.get("league") or "",
            "sport": (row.get("sport") or "soccer").lower(),
            "recommended_outcome": outcome,
            "outcome": outcome,
            "best_odds": odds,
            "best_bookmaker": row.get("bookmaker") or "",
            "best_bookmaker_key": row.get("bookmaker") or "",
            "edge_pct": ev_pct,
            "ev": ev_pct,
            "fair_probability": fair_prob,
            "fair_prob": fair_prob,
            "composite_score": float(row.get("composite_score") or 0),
            "confirming_signals": int(row.get("confirming_signals") or 0),
            "bookmaker_count": 0,
            "stale_minutes": 0,
            "signals": {},
            "tier": (row.get("edge_tier") or "bronze").lower(),
            "edge_tier": (row.get("edge_tier") or "bronze").lower(),
            "commence_time": "",
        }
        edges.append(edge)
    return edges


async def _persist_one(result: dict, log) -> bool:
    """Persist a successful _generate_one result to narrative_cache."""
    cache = result.get("_cache") if isinstance(result, dict) else None
    if not cache:
        return False
    match_id = cache.get("match_id")
    html = cache.get("html")
    if not match_id or not html:
        return False
    tips = cache.get("tips") or []
    edge_tier = cache.get("edge_tier") or "bronze"
    narrative_source = cache.get("narrative_source") or "w82"
    verdict_html = cache.get("verdict_html")
    evidence_class = cache.get("evidence_class")
    tone_band = cache.get("tone_band")
    spec_json = cache.get("spec_json")
    context_json = cache.get("context_json")
    coverage_json = cache.get("coverage_json")
    structured_card_json = cache.get("structured_card_json")
    evidence_json = cache.get("evidence_json")
    served_model = cache.get("model") or "baseline"
    generation_ms = int(cache.get("generation_ms") or 0)

    # bot._store_narrative_cache is the canonical async writer (W81-DBLOCK).
    try:
        await bot._store_narrative_cache(
            match_id,
            html,
            tips,
            edge_tier,
            served_model,
            evidence_json=evidence_json,
            narrative_source=narrative_source,
            coverage_json=coverage_json,
            structured_card_json=structured_card_json,
            verdict_html=verdict_html,
            evidence_class=evidence_class,
            tone_band=tone_band,
            spec_json=spec_json,
            context_json=context_json,
            generation_ms=generation_ms,
        )
        return True
    except Exception as exc:
        log.warning("persist failed for %s: %s", match_id, exc)
        return False


async def _run() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=60)
    parser.add_argument("--brief-only", action="store_true")
    args = parser.parse_args()

    edges = _load_unsettled_edges_for_pregen()
    print(f"loaded {len(edges)} unsettled-edge candidates")

    if args.brief_only:
        edges = [e for e in edges if e["match_key"] in BRIEF_KEYS]
        print(f"--brief-only filter applied → {len(edges)} candidates")
    else:
        edges = edges[: args.limit]
        # Ensure all 4 brief-flagged keys are processed even if outside the limit.
        existing = {e["match_key"] for e in edges}
        for k in BRIEF_KEYS:
            if k in existing:
                continue
            for full in _load_unsettled_edges_for_pregen():
                if full["match_key"] == k:
                    edges.append(full)
                    break

    print(f"processing {len(edges)} edges …\n")
    results: list[dict] = []
    t_total = time.time()
    for i, edge in enumerate(edges, 1):
        t0 = time.time()
        try:
            res = await pregen._generate_one(edge, sweep_type="full")
        except Exception as exc:
            print(f"[{i:>2}/{len(edges)}] EXC  {edge['match_key']}: {exc}")
            results.append({"match_key": edge["match_key"], "success": False, "error": str(exc)})
            continue
        success = bool(res.get("success"))
        results.append(res)
        persisted = False
        if success:
            persisted = await _persist_one(res, pregen.log)
        elapsed = time.time() - t0
        print(
            f"[{i:>2}/{len(edges)}] {'OK ' if success else '!! '}"
            f"{edge['match_key']:<55} ({elapsed:.1f}s, persist={persisted})"
        )

    successes = sum(1 for r in results if r.get("success"))
    print(f"\nSUMMARY: {successes}/{len(edges)} successful in {time.time() - t_total:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_run()) or 0)
