#!/usr/bin/env python3
"""Re-verify existing shadow_narratives with the fixed verifier.

Reads raw_draft + evidence_json from the DB, re-runs verify_shadow_narrative(),
and prints comparison of old vs new pass/fail + rejection reasons.
"""
import json
import sqlite3
import sys
import os
import re
from dataclasses import dataclass, field
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, "/home/paulsportsza")

from evidence_pack import (
    EvidencePack,
    verify_shadow_narrative,
)


DB = "/home/paulsportsza/scrapers/odds.db"


@dataclass
class MinimalSpec:
    """Minimal spec-like object with fields the verifier needs."""
    home_name: str = ""
    away_name: str = ""
    bookmaker: str = ""
    odds: float = 0.0
    ev_pct: float = 0.0
    fair_prob_pct: float = 0.0
    evidence_class: str = ""
    verdict_action: str = "monitor"
    tone_band: str = "moderate"
    h2h_summary: str = ""
    home_form: str = ""
    away_form: str = ""
    home_position: int | None = None
    away_position: int | None = None
    home_points: int | None = None
    away_points: int | None = None
    home_coach: str = ""
    away_coach: str = ""
    home_story_type: str = "neutral"
    away_story_type: str = "neutral"
    competition: str = ""
    sport: str = "soccer"


def _build_spec_from_pack(pack: EvidencePack, match_key: str) -> MinimalSpec:
    """Build a minimal NarrativeSpec-like object from the evidence pack."""
    spec = MinimalSpec()

    # Parse teams from match_key
    parts = match_key.rsplit("_", 1)[0] if "_" in match_key else match_key
    if "_vs_" in parts:
        home_key, away_key = parts.split("_vs_", 1)
        spec.home_name = home_key.replace("_", " ").title()
        spec.away_name = away_key.replace("_", " ").title()

    spec.sport = pack.sport or "soccer"
    spec.competition = pack.league or ""

    # Extract from sa_odds
    if pack.sa_odds:
        prov = pack.sa_odds.provenance
        spec.bookmaker = getattr(prov, "best_bookmaker", "") or ""
        spec.odds = float(getattr(prov, "best_odds", 0.0) or 0.0)

    # Extract from edge_state
    if pack.edge_state:
        spec.ev_pct = float(getattr(pack.edge_state, "ev_pct", 0.0) or 0.0)
        spec.fair_prob_pct = float(getattr(pack.edge_state, "fair_prob_pct", 0.0) or 0.0)
        spec.evidence_class = getattr(pack.edge_state, "evidence_class", "") or ""
        spec.verdict_action = getattr(pack.edge_state, "verdict_action", "monitor") or "monitor"
        spec.tone_band = getattr(pack.edge_state, "tone_band", "moderate") or "moderate"

    # Extract from ESPN context
    if pack.espn_context:
        home = pack.espn_context.home_team
        away = pack.espn_context.away_team
        if home:
            _hget = home.get if isinstance(home, dict) else lambda k, d="": getattr(home, k, d)
            spec.home_form = str(_hget("form", "") or _hget("last_5", "") or "")
            spec.home_position = _hget("position", None)
            spec.home_points = _hget("points", None)
            spec.home_coach = _hget("coach", "") or ""
        if away:
            _aget = away.get if isinstance(away, dict) else lambda k, d="": getattr(away, k, d)
            spec.away_form = str(_aget("form", "") or _aget("last_5", "") or "")
            spec.away_position = _aget("position", None)
            spec.away_points = _aget("points", None)
            spec.away_coach = _aget("coach", "") or ""

    return spec


def _reconstruct_pack(ev_data: dict) -> EvidencePack:
    """Reconstruct EvidencePack from serialized evidence_json dict."""
    # EvidencePack is a dataclass — construct it from dict fields
    from evidence_pack import (
        SAOddsBlock, EdgeStateBlock, ESPNContextBlock,
        NewsBlock, SharpLinesBlock, SettlementBlock,
        MovementsBlock, InjuriesBlock,
    )

    def _build_block(cls, data):
        if data is None:
            return None
        if isinstance(data, dict):
            # Try constructing dataclass from dict
            try:
                return cls(**data)
            except TypeError:
                # Some blocks have nested dataclasses — need more work
                return data
        return data

    # Simple field extraction
    pack = EvidencePack(
        match_key=ev_data.get("match_key", ""),
        sport=ev_data.get("sport", "soccer"),
        league=ev_data.get("league", ""),
        built_at=ev_data.get("built_at", ""),
        pack_version=ev_data.get("pack_version", 1),
        richness_score=ev_data.get("richness_score", "low"),
        sources_available=ev_data.get("sources_available", 0),
        sources_total=ev_data.get("sources_total", 8),
    )

    # For nested blocks, store raw dicts as SimpleNamespace-like objects
    # The verifier accesses them via getattr/dict-like access
    import types

    class DictNS(dict):
        """Dict subclass that also supports attribute access (like SimpleNamespace).
        This way both d.key and d.get("key") and d["key"] and iteration all work."""
        def __getattr__(self, key):
            try:
                return self[key]
            except KeyError:
                raise AttributeError(key)

        def __setattr__(self, key, value):
            self[key] = value

    def _dict_to_ns(d):
        """Recursively convert dict to DictNS (supports both attr and dict access)."""
        if not isinstance(d, dict):
            return d
        return DictNS({
            k: _dict_to_ns(v) if isinstance(v, dict)
            else [_dict_to_ns(item) if isinstance(item, dict) else item for item in v] if isinstance(v, list)
            else v
            for k, v in d.items()
        })

    if ev_data.get("sa_odds"):
        pack.sa_odds = _dict_to_ns(ev_data["sa_odds"])
    if ev_data.get("edge_state"):
        pack.edge_state = _dict_to_ns(ev_data["edge_state"])
    if ev_data.get("espn_context"):
        pack.espn_context = _dict_to_ns(ev_data["espn_context"])
    if ev_data.get("news"):
        pack.news = _dict_to_ns(ev_data["news"])
    if ev_data.get("sharp_lines"):
        pack.sharp_lines = _dict_to_ns(ev_data["sharp_lines"])
    if ev_data.get("settlement_stats"):
        pack.settlement_stats = _dict_to_ns(ev_data["settlement_stats"])
    if ev_data.get("movements"):
        pack.movements = _dict_to_ns(ev_data["movements"])
    if ev_data.get("injuries"):
        pack.injuries = _dict_to_ns(ev_data["injuries"])
    # Reconstruct H2H block from espn_context.h2h (list of match dicts)
    ec = ev_data.get("espn_context", {}) or {}
    h2h_matches = ec.get("h2h", []) if isinstance(ec, dict) else []
    if h2h_matches and isinstance(h2h_matches, list) and len(h2h_matches) > 0:
        # Build summary from matches
        home_key = ev_data.get("match_key", "").split("_vs_")[0].replace("_", " ").lower() if "_vs_" in ev_data.get("match_key", "") else ""
        total = len(h2h_matches)
        home_wins = 0
        away_wins = 0
        draws = 0
        for m in h2h_matches:
            score = str(m.get("score", ""))
            if "-" in score:
                parts = score.split("-")
                try:
                    g1, g2 = int(parts[0].strip()), int(parts[1].strip())
                    h = str(m.get("home", "")).lower()
                    if g1 == g2:
                        draws += 1
                    elif (g1 > g2 and home_key in h) or (g2 > g1 and home_key not in h):
                        home_wins += 1
                    else:
                        away_wins += 1
                except ValueError:
                    pass
        summary = {"total": total, "home_wins": home_wins, "away_wins": away_wins, "draws": draws}
        summary_text = f"{total} meetings: {home_wins}W {draws}D {away_wins}L"
        pack.h2h = DictNS({
            "provenance": DictNS({"available": True, "source": "espn"}),
            "matches": [DictNS(m) if isinstance(m, dict) else m for m in h2h_matches],
            "summary": summary,
            "summary_text": summary_text,
        })

    return pack


def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    # Get the LATEST row per match_key (most recent shadow)
    rows = conn.execute("""
        SELECT sn.rowid, sn.match_key, sn.richness_score, sn.verification_passed,
               sn.raw_draft, sn.evidence_json, sn.verification_report,
               sn.w82_baseline, sn.created_at
        FROM shadow_narratives sn
        INNER JOIN (
            SELECT match_key, MAX(rowid) as max_id
            FROM shadow_narratives
            WHERE raw_draft IS NOT NULL AND evidence_json IS NOT NULL
            GROUP BY match_key
        ) latest ON sn.rowid = latest.max_id
        ORDER BY sn.created_at DESC
    """).fetchall()

    print(f"Re-verifying {len(rows)} match_keys...\n")

    results = []
    for row in rows:
        mk = row["match_key"]
        old_passed = bool(row["verification_passed"])
        old_report = json.loads(row["verification_report"]) if row["verification_report"] else {}
        old_rejections = old_report.get("rejection_reasons", [])

        # Reconstruct evidence pack and minimal spec
        ev_data = json.loads(row["evidence_json"])
        pack = _reconstruct_pack(ev_data)
        spec = _build_spec_from_pack(pack, mk)

        # Re-verify with fixed verifier
        try:
            result_tuple = verify_shadow_narrative(row["raw_draft"], pack, spec)
            if isinstance(result_tuple, tuple):
                _, new_report = result_tuple
            else:
                new_report = result_tuple
        except Exception as exc:
            print(f"  ERROR {mk}: {exc}")
            continue

        new_passed = new_report.get("passed", False)
        new_rejections = new_report.get("rejection_reasons", [])

        # Get hard check details
        old_hard = old_report.get("hard_checks", {})
        new_hard = new_report.get("hard_checks", {})

        # Normalise old_hard values (they may be dicts with "passed" key)
        old_hard_bool = {}
        for k, v in old_hard.items():
            if isinstance(v, dict):
                old_hard_bool[k] = v.get("passed", False)
            else:
                old_hard_bool[k] = bool(v)

        new_hard_bool = {}
        for k, v in new_hard.items():
            if isinstance(v, dict):
                new_hard_bool[k] = v.get("passed", False)
            else:
                new_hard_bool[k] = bool(v)

        # Find which checks flipped
        flipped = []
        for check_name, new_val in new_hard_bool.items():
            old_val = old_hard_bool.get(check_name)
            if old_val is not None and old_val != new_val:
                flipped.append((check_name, old_val, new_val))

        results.append({
            "match_key": mk,
            "richness": row["richness_score"],
            "old_passed": old_passed,
            "new_passed": new_passed,
            "old_rejections": old_rejections,
            "new_rejections": new_rejections,
            "flipped": flipped,
            "raw_draft": row["raw_draft"],
            "w82_baseline": row["w82_baseline"],
            "old_hard": old_hard_bool,
            "new_hard": new_hard_bool,
            "new_hard_detail": new_hard,
        })

        status = "PASS" if new_passed else "FAIL"
        flip_str = ""
        if flipped:
            flip_str = " | FLIPPED: " + ", ".join(f"{c}: {o}->{n}" for c, o, n in flipped)
        old_status = "PASS" if old_passed else "FAIL"
        print(f"  {mk:50s} {old_status}->{status} | old_rej={len(old_rejections)} new_rej={len(new_rejections)}{flip_str}")

    # Summary
    old_pass = sum(1 for r in results if r["old_passed"])
    new_pass = sum(1 for r in results if r["new_passed"])
    total = len(results)
    print(f"\n{'='*80}")
    print(f"SUMMARY: {old_pass}/{total} -> {new_pass}/{total} pass rate")
    print(f"Delta: +{new_pass - old_pass} newly passing")

    # Rejection frequency (new)
    print(f"\nRemaining rejection reasons (new verifier):")
    rej_counts = {}
    for r in results:
        for rej in r["new_rejections"]:
            # Truncate long rejection messages for display
            short = rej[:80] + "..." if len(rej) > 80 else rej
            rej_counts[short] = rej_counts.get(short, 0) + 1
    for rej, count in sorted(rej_counts.items(), key=lambda x: -x[1]):
        print(f"  {count}/{total} | {rej}")

    # Hard check pass rates (new)
    print(f"\nHard check pass rates (new verifier):")
    check_totals = {}
    check_passes = {}
    for r in results:
        for check, val in r["new_hard"].items():
            check_totals[check] = check_totals.get(check, 0) + 1
            if val:
                check_passes[check] = check_passes.get(check, 0) + 1
    for check in sorted(check_totals.keys()):
        passes = check_passes.get(check, 0)
        total_c = check_totals[check]
        pct = 100 * passes / total_c if total_c else 0
        marker = "✅" if pct == 100 else ("⚠️" if pct >= 50 else "❌")
        print(f"  {marker} {check:40s} {passes}/{total_c} ({pct:.0f}%)")

    # Dump full results for scoring
    with open("/home/paulsportsza/reports/qa3_reverify_results.json", "w") as f:
        output = []
        for r in results:
            output.append({
                "match_key": r["match_key"],
                "richness": r["richness"],
                "old_passed": r["old_passed"],
                "new_passed": r["new_passed"],
                "old_rejections": r["old_rejections"],
                "new_rejections": r["new_rejections"],
                "flipped": r["flipped"],
                "new_hard": r["new_hard"],
                "new_hard_detail": r["new_hard_detail"],
                "old_hard": r["old_hard"],
                "raw_draft": r["raw_draft"],
                "w82_baseline": r["w82_baseline"],
            })
        json.dump(output, f, indent=2)
    print(f"\nFull results saved to /home/paulsportsza/reports/qa3_reverify_results.json")


if __name__ == "__main__":
    main()
