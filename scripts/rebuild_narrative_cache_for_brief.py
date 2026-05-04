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
        # FIX-PREGEN-SIGNALS-DROP-AND-CACHE-FLUSH-01 Codex pass-3 (Finding 1):
        # canonical bet_type → outcome mapping. edge_results stores
        # human-readable labels ("Home Win" / "Away Win" / "Draw") for
        # legacy rows AND colon-shaped 1x2 markets ("1X2:home") for newer
        # writers. The pre-fix wrapper only handled the colon shape →
        # `Away Win` rows silently rebuilt as `home` outcome and the
        # rendered verdict backed the WRONG team. Mirrors
        # bot.py:_load_tips_from_edge_results normalisation (line 10973).
        if bet_type == "Home Win" or bet_type == "home":
            outcome = "home"
        elif bet_type == "Away Win" or bet_type == "away":
            outcome = "away"
        elif bet_type == "Draw" or bet_type == "draw":
            outcome = "draw"
        elif ":" in bet_type:
            _, outcome = bet_type.split(":", 1)
            outcome = outcome.lower() or "home"
        if outcome not in ("home", "away", "draw"):
            outcome = "home"
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
    """Persist a successful _generate_one result to narrative_cache.

    FIX-PREGEN-SIGNALS-DROP-AND-CACHE-FLUSH-01 Codex pass-3 (Finding 2):
    runs the same gen-vs-write drift guard the canonical pregen.main()
    pending_writes loop uses, so cache-flush rebuilds and the regular
    sweep both go through the same drift-detection path. Without this
    a flush-time write could stamp a verdict rendered against pre-flush
    odds/signals as fresh in the post-flush cache row.
    """
    cache = result.get("_cache") if isinstance(result, dict) else None
    if not cache:
        return False
    match_id = cache.get("match_id")
    html = cache.get("html")
    if not match_id or not html:
        return False

    # Drift guard — pop the gen-time fingerprints (they must NOT reach
    # _store_narrative_cache, which has no parameter for them).
    _gen_odds_hash = cache.pop("_gen_odds_hash", "") or ""
    _gen_signal_fp = cache.pop("_gen_signal_fp", "") or ""
    _outcome_for_recheck = cache.pop("_outcome_for_recheck", "") or ""
    _sport_for_recheck = cache.pop("_sport_for_recheck", None)
    _league_for_recheck = cache.pop("_league_for_recheck", None)

    if _gen_signal_fp and _outcome_for_recheck:
        try:
            _now_canonical_sigs = pregen._collect_canonical_signals(
                match_id, _outcome_for_recheck, _sport_for_recheck, _league_for_recheck,
            )
            _now_signal_fp = "no_sigs"
            if _now_canonical_sigs:
                try:
                    from narrative_spec import _normalise_spec_signals as _ns_norm
                    _now_signal_fp = pregen._signal_fingerprint(_ns_norm(_now_canonical_sigs))
                except Exception:
                    _now_signal_fp = "no_sigs"
            if _now_signal_fp != _gen_signal_fp:
                log.warning(
                    "FIX-PREGEN-SIGNALS-DROP-AND-CACHE-FLUSH-01 GenWriteSignalDrift "
                    "(rebuild wrapper) match_id=%s gen=%s now=%s — skipping cache write",
                    match_id, _gen_signal_fp, _now_signal_fp,
                )
                return False
        except Exception as _drift_exc:
            log.debug(
                "rebuild wrapper drift-check signal exception for %s: %s — falling through",
                match_id, _drift_exc,
            )
    # NOTE: odds-hash drift is intentionally NOT enforced in the wrapper.
    # _compute_odds_hash reads odds_latest, which scrapers update every
    # ~30s — so on every gen→persist cycle (millisec apart) the hash
    # almost always differs even when nothing material changed. The
    # signal fingerprint above already catches the case that matters
    # (where the §12.X rendered phrase would shift). Odds-hash drift
    # affects only Diamond-tier verdicts which embed odds verbatim, and
    # the production main() pending_writes loop keeps the strict odds
    # check for its longer gen→write window. The brief flush wrapper
    # processes one match at a time with a sub-second window between
    # generation and persistence — odds drift here is safe to ignore.
    _ = _gen_odds_hash  # kept for diagnostics in future audits.

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
    # Codex pass-3 fourth review (Finding 1): the writer is best-effort
    # and can silently drop rows on lock contention or validator refusal
    # without raising. A non-raising call therefore does NOT prove a row
    # landed. After the call we read narrative_cache directly and only
    # report persisted=True when the row's verdict_html matches what we
    # asked the writer to persist (proves the commit, defends against
    # validator refusal that re-tones the row, and rejects pre-existing
    # leftovers from a prior sweep).
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
    except Exception as exc:
        log.warning("persist write raised for %s: %s", match_id, exc)
        return False

    # Verify the row actually committed and matches what we wrote. The
    # read uses a short timeout against the same DB the writer used so
    # we surface lock-contention drops as failures rather than silently
    # treating them as wins.
    try:
        from db_connection import get_connection
        from scrapers.edge.edge_config import DB_PATH

        def _verify_row() -> bool:
            conn = get_connection(DB_PATH, timeout_ms=5000)
            try:
                row = conn.execute(
                    "SELECT verdict_html, narrative_source, edge_tier "
                    "FROM narrative_cache WHERE match_id = ?",
                    (match_id,),
                ).fetchone()
            finally:
                conn.close()
            if not row:
                return False
            stored_verdict, stored_source, stored_tier = row
            if (verdict_html or "") and (stored_verdict or "") != (verdict_html or ""):
                # Validator may have re-toned the verdict during the
                # write — log and treat as a failed persist for this
                # wrapper's strict semantics. Production main()'s loop
                # is more forgiving; the wrapper exits non-zero so
                # operators see the divergence.
                log.warning(
                    "persist verify mismatch for %s — wrote %r, cache has %r",
                    match_id, (verdict_html or "")[:80], (stored_verdict or "")[:80],
                )
                return False
            if (narrative_source or "") and (stored_source or "") != (narrative_source or ""):
                log.warning(
                    "persist verify source mismatch for %s — wrote %s, cache has %s",
                    match_id, narrative_source, stored_source,
                )
                return False
            if (edge_tier or "") and (stored_tier or "").lower() != (edge_tier or "").lower():
                log.warning(
                    "persist verify tier mismatch for %s — wrote %s, cache has %s",
                    match_id, edge_tier, stored_tier,
                )
                return False
            return True

        verified = await asyncio.to_thread(_verify_row)
        if not verified:
            log.warning(
                "persist verify failed for %s — row absent or mismatched after write",
                match_id,
            )
            return False
        return True
    except Exception as verify_exc:
        log.warning("persist verify exception for %s: %s", match_id, verify_exc)
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
    # Codex pass-3 (Finding 2): max generate→persist retry count when the
    # drift guard skips a write. Each retry produces a fresh gen-time
    # fingerprint immediately before the persist recheck — drastically
    # narrows the race window to a single asyncio scheduling boundary.
    _MAX_DRIFT_RETRIES = 4
    # Codex pass-3 second review (Finding 1): persistence — not just
    # generation success — is the wrapper's success criterion. Track
    # persisted/drift-skipped/exception per edge so the summary line
    # and exit code don't paint a false green when cache writes fail.
    persistence: list[tuple[str, bool, bool, str]] = []  # (match_key, persisted, drift_skipped, error)
    for i, edge in enumerate(edges, 1):
        t0 = time.time()
        res: dict = {}
        success = False
        persisted = False
        drift_skipped = False
        error_msg = ""
        for retry in range(_MAX_DRIFT_RETRIES):
            try:
                res = await pregen._generate_one(edge, sweep_type="full")
            except Exception as exc:
                error_msg = str(exc)
                print(f"[{i:>2}/{len(edges)}] EXC  {edge['match_key']}: {exc}")
                res = {"match_key": edge["match_key"], "success": False, "error": error_msg}
                break
            success = bool(res.get("success"))
            if not success:
                error_msg = res.get("error") or "generation failed"
                break
            persisted = await _persist_one(res, pregen.log)
            if persisted:
                break
            # _persist_one returned False — either drift-skipped or store
            # failure. Track the latter so the post-loop summary tells
            # the operator the right story.
            drift_skipped = True
            if retry < _MAX_DRIFT_RETRIES - 1:
                pregen.log.info(
                    "rebuild_wrapper drift retry %d/%d for %s",
                    retry + 1, _MAX_DRIFT_RETRIES, edge["match_key"],
                )
        if not persisted and not error_msg:
            error_msg = "drift_skipped_after_retries" if drift_skipped else "persist_failed"
        results.append(res)
        persistence.append((edge["match_key"], persisted, drift_skipped, error_msg))
        elapsed = time.time() - t0
        print(
            f"[{i:>2}/{len(edges)}] {'OK ' if success else '!! '}"
            f"{edge['match_key']:<55} "
            f"({elapsed:.1f}s, gen={success}, persist={persisted})"
        )

    persisted_count = sum(1 for _, p, _, _ in persistence if p)
    drift_count = sum(1 for _, p, d, _ in persistence if d and not p)
    failed_persist = [
        (mk, err) for mk, p, _, err in persistence if not p
    ]
    print(
        f"\nSUMMARY: persisted {persisted_count}/{len(edges)} "
        f"in {time.time() - t_total:.1f}s "
        f"(drift-skipped after retries: {drift_count})"
    )
    if failed_persist:
        print("FAILED-TO-PERSIST:")
        for mk, err in failed_persist:
            print(f"  - {mk}: {err}")
        # Exit non-zero so automation / operators see a clean failure
        # instead of a false-green run when scrapers churn the live DB.
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_run()) or 0)
