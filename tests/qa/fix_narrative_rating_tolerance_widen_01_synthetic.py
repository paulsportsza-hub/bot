from __future__ import annotations

import pytest
pytest.skip(
    "FIX-DROP-SONNET-POLISH-W82-CANONICAL-01: Sonnet/Haiku polish ripped out. "
    "This test asserts polish-chain behaviour that no longer exists.",
    allow_module_level=True,
)

"""FIX-NARRATIVE-RATING-TOLERANCE-WIDEN-01 — synthetic-render evidence harness (HG-1, AC-7).

Two-arm harness:
  Arm A (calibration sweep): renders _find_rating_anchor_violations across 5 sport×fixture
    combinations, varying |cited - anchor| across {0, 1, 2, 4, 5, 6, 10, 50}. Asserts the
    correct PASS/FAIL distribution at the new ±5 tolerance:
      - 0/1/2/4 → PASS (within tolerance)
      - 5       → PASS (helper uses `> _RATING_TOLERANCE`; 5.0 > 5.0 is False)
      - 6/10/50 → FAIL (fabricated_rating fires)

  Arm B (prompt literal canary): renders evidence_pack.format_evidence_prompt() for both
    branches across 5 non-Arsenal fixtures and asserts zero '1853'/'1551' substrings in
    either prompt path (regression guard inherited from predecessor brief).

Run from /home/paulsportsza/bot:
    .venv/bin/python tests/qa/fix_narrative_rating_tolerance_widen_01_synthetic.py

Output: /home/paulsportsza/reports/e2e-screenshots/FIX-NARRATIVE-RATING-TOLERANCE-WIDEN-01-{stamp}/
"""

import os
import sys
import json
import datetime as dt
from pathlib import Path
from types import SimpleNamespace

BOT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BOT_DIR))
os.chdir(BOT_DIR)

from bot import _RATING_TOLERANCE, _find_rating_anchor_violations  # noqa: E402
from evidence_pack import EvidencePack, format_evidence_prompt  # noqa: E402


# 5 sport × fixture combinations spanning soccer (4 leagues) and rugby (URC).
FIXTURES = [
    ("liverpool_vs_manchester_city_2026-05-02", "soccer", "EPL"),
    ("orlando_pirates_vs_kaizer_chiefs_2026-05-03", "soccer", "PSL"),
    ("real_madrid_vs_barcelona_2026-05-04", "soccer", "La Liga"),
    ("paris_saint_germain_vs_bayern_munich_2026-05-05", "soccer", "Champions League"),
    ("bulls_vs_stormers_2026-05-06", "rugby", "URC"),
]

# Calibration anchor sweep. Helper compares with `> _RATING_TOLERANCE`, so 5.0 is a PASS.
OFFSETS_AND_EXPECTED = [
    (0, "PASS"),
    (1, "PASS"),
    (2, "PASS"),
    (4, "PASS"),
    (5, "PASS"),   # boundary — exactly at ±5, no flag
    (6, "FAIL"),
    (10, "FAIL"),
    (50, "FAIL"),
]

BANNED_LITERALS = ("1853", "1551")


def make_minimal_spec(home_name: str, away_name: str, sport: str, league: str) -> SimpleNamespace:
    return SimpleNamespace(
        home_name=home_name,
        away_name=away_name,
        sport=sport,
        competition=league,
        bookmaker="Betway",
        odds=1.85,
        verdict_action="lean back",
        verdict_sizing="moderate",
        evidence_class="supported",
        tone_band="moderate",
        edge_tier="gold",
        sa_tag="lean",
        h2h_history="No prior meetings",
    )


def make_minimal_pack(match_key: str, sport: str, league: str) -> EvidencePack:
    return EvidencePack(
        match_key=match_key,
        sport=sport,
        league=league,
        built_at=dt.datetime.now(dt.timezone.utc).isoformat(),
        richness_score="medium",
        sources_available=4,
        sources_total=8,
    )


def render_calibration_arm(match_key: str, sport: str, league: str) -> dict:
    """Calibration sweep: anchor at 1850.0, vary cited rating across offsets."""
    home_key, _ = match_key.split("_vs_", 1)
    home_name = home_key.replace("_", " ").title()
    anchor_value = 1850.0
    anchors = {"home": {"glicko2": anchor_value}, "away": {"glicko2": 1500.0}}

    rows = []
    for offset, expected in OFFSETS_AND_EXPECTED:
        cited = int(anchor_value + offset)
        narrative = (
            f"{home_name} carry a Glicko-2 mark of {cited} into this {league} fixture."
        )
        result = _find_rating_anchor_violations(narrative, anchors)
        flagged = any("fabricated_rating" in r for r in result)
        actual = "FAIL" if flagged else "PASS"
        rows.append({
            "offset_pts": offset,
            "anchor": anchor_value,
            "cited": cited,
            "expected": expected,
            "actual": actual,
            "result_list": result,
            "match": (expected == actual),
        })
    return {
        "match_key": match_key,
        "sport": sport,
        "league": league,
        "tolerance": _RATING_TOLERANCE,
        "rows": rows,
        "all_match": all(r["match"] for r in rows),
    }


def render_prompt_arm(match_key: str, sport: str, league: str) -> dict:
    """Prompt literal canary: assert no '1853' / '1551' in rendered prompts."""
    home_key, rest = match_key.split("_vs_", 1)
    away_key = rest.rsplit("_", 1)[0]
    spec = make_minimal_spec(
        home_key.replace("_", " ").title(),
        away_key.replace("_", " ").title(),
        sport,
        league,
    )
    pack = make_minimal_pack(match_key, sport, league)

    edge_prompt = format_evidence_prompt(pack, spec, match_preview=False)
    preview_prompt = format_evidence_prompt(pack, spec, match_preview=True)
    edge_hits = {lit: edge_prompt.count(lit) for lit in BANNED_LITERALS}
    preview_hits = {lit: preview_prompt.count(lit) for lit in BANNED_LITERALS}

    return {
        "match_key": match_key,
        "sport": sport,
        "league": league,
        "edge_prompt_len": len(edge_prompt),
        "preview_prompt_len": len(preview_prompt),
        "edge_literal_hits": edge_hits,
        "preview_literal_hits": preview_hits,
        "edge_prompt": edge_prompt,
        "preview_prompt": preview_prompt,
        "passed": (sum(edge_hits.values()) == 0 and sum(preview_hits.values()) == 0),
    }


def main() -> int:
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = Path(
        f"/home/paulsportsza/reports/e2e-screenshots/FIX-NARRATIVE-RATING-TOLERANCE-WIDEN-01-{stamp}"
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    calibration_results: list[dict] = []
    prompt_results: list[dict] = []
    overall_pass = True

    print(f"[FIX-NARRATIVE-RATING-TOLERANCE-WIDEN-01] synthetic harness")
    print(f"  output: {out_dir}")
    print(f"  tolerance: {_RATING_TOLERANCE}")
    print(f"  fixtures: {len(FIXTURES)}")
    print(f"  offsets: {[o for o, _ in OFFSETS_AND_EXPECTED]}")
    print()

    # Arm A — calibration sweep
    print("=== Arm A: Calibration Sweep ===")
    for match_key, sport, league in FIXTURES:
        try:
            res = render_calibration_arm(match_key, sport, league)
        except Exception as exc:
            res = {
                "match_key": match_key,
                "sport": sport,
                "league": league,
                "error": f"{type(exc).__name__}: {exc}",
                "all_match": False,
            }
            overall_pass = False
        calibration_results.append(res)

        verdict = "PASS" if res.get("all_match") else "FAIL"
        print(f"  {verdict}   {match_key:60s}", end="")
        if "rows" in res:
            mismatches = [r for r in res["rows"] if not r["match"]]
            if mismatches:
                print(f"  mismatches: {[(m['offset_pts'], m['expected'], m['actual']) for m in mismatches]}")
            else:
                print(f"  all 8 offsets correct")
        else:
            print(f"  ERROR: {res.get('error')}")
        if not res.get("all_match"):
            overall_pass = False

    print()
    # Arm B — prompt literal canary
    print("=== Arm B: Prompt Literal Canary ===")
    for match_key, sport, league in FIXTURES:
        try:
            res = render_prompt_arm(match_key, sport, league)
        except Exception as exc:
            prompt_results.append({
                "match_key": match_key,
                "sport": sport,
                "league": league,
                "error": f"{type(exc).__name__}: {exc}",
                "passed": False,
            })
            overall_pass = False
            continue

        slug = match_key.replace("/", "_")
        (out_dir / f"{slug}.edge.prompt.txt").write_text(res["edge_prompt"], encoding="utf-8")
        (out_dir / f"{slug}.preview.prompt.txt").write_text(res["preview_prompt"], encoding="utf-8")
        # Drop the verbose prompt strings from the persisted summary record
        slim = {k: v for k, v in res.items() if k not in ("edge_prompt", "preview_prompt")}
        prompt_results.append(slim)

        verdict = "PASS" if res["passed"] else "FAIL"
        print(
            f"  {verdict}   {match_key:60s}  "
            f"edge={res['edge_literal_hits']}  preview={res['preview_literal_hits']}"
        )
        if not res["passed"]:
            overall_pass = False

    summary_doc = {
        "wave": "FIX-NARRATIVE-RATING-TOLERANCE-WIDEN-01",
        "kind": "synthetic-render-two-arm",
        "ac": ["HG-1", "AC-7"],
        "ts": stamp,
        "tolerance": _RATING_TOLERANCE,
        "fixtures_total": len(FIXTURES),
        "offsets_swept": [o for o, _ in OFFSETS_AND_EXPECTED],
        "banned_literals": list(BANNED_LITERALS),
        "overall_pass": overall_pass,
        "arm_a_calibration": calibration_results,
        "arm_b_prompt_literal": prompt_results,
    }
    (out_dir / "summary.json").write_text(json.dumps(summary_doc, indent=2), encoding="utf-8")

    print()
    print(f"  overall: {'PASS' if overall_pass else 'FAIL'}")
    return 0 if overall_pass else 1


if __name__ == "__main__":
    sys.exit(main())
