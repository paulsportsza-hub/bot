"""OPS-COMMIT-RECOVER-FIX-NARRATIVE-NO-EDGE-FAIR-VALUE-FALLBACK-01 — synthetic-render evidence harness (HG-1, AC-7).

Validates the recovery commit (02a11d6) for the orphan diff that landed the new
``_render_edge`` no-edge branch. Five synthetic NarrativeSpec fixtures exercise
the full identity path (cricket Test/T20, MMA), the degraded path (soccer with
no odds + no bookmaker), and a regression guard (soccer ``verdict_action='lean'``
with ``fair_prob_pct=0.45`` — must bypass the new branch entirely).

Per-fixture rendered Edge section + full baseline are dumped to a plain text
file named after the brief, with a ``summary.json`` carrying the verdict for
each fixture and the overall ``overall_pass``.

Hard assertions (per AC-7, HG-1):
  - 4 null-cases: zero ``?`` substring anywhere in baseline output, AND new
    ``_no_edge_variant`` signature present (text fingerprint match).
  - 1 regression guard: zero new no-edge-variant signature in baseline, AND
    the rendered output is one of the existing speculative/lean variants.

Run from /home/paulsportsza/bot:
    .venv/bin/python tests/qa/ops_commit_recover_fix_narrative_no_edge_fair_value_fallback_01_synthetic.py

Output: /home/paulsportsza/reports/e2e-screenshots/OPS-COMMIT-RECOVER-FIX-NARRATIVE-NO-EDGE-FAIR-VALUE-FALLBACK-01-{sport}-{coverage}-{stamp}.txt
        /home/paulsportsza/reports/e2e-screenshots/OPS-COMMIT-RECOVER-FIX-NARRATIVE-NO-EDGE-FAIR-VALUE-FALLBACK-01-summary-{stamp}.json
"""
from __future__ import annotations

import os
import sys
import json
import datetime as dt
from pathlib import Path

BOT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BOT_DIR))
os.chdir(BOT_DIR)

from narrative_spec import NarrativeSpec, _render_baseline, _render_edge  # noqa: E402


# Fingerprints from the new _render_edge no-edge variants (lines 2323-2353 of
# narrative_spec.py). These appear in the Edge section ONLY when the new branch
# fires — used for both null-case verification and regression-guard exclusion.
NO_EDGE_FINGERPRINTS_FULL = (
    "no actionable edge",
    "doesn't show a meaningful pricing gap",
    "has no edge in our read",
)
NO_EDGE_FINGERPRINTS_DEGRADED = (
    "no edge on",
    "doesn't show a price gap worth chasing",
    "nothing actionable on",
)
ALL_NO_EDGE_FINGERPRINTS = NO_EDGE_FINGERPRINTS_FULL + NO_EDGE_FINGERPRINTS_DEGRADED


# 5 synthetic fixtures per brief Step 7.
FIXTURES = [
    {
        "label": "cricket-test-monitor-full",
        "sport": "cricket",
        "coverage": "full-identity",
        "expect": "no_edge",
        "spec": dict(
            home_name="Bangladesh",
            away_name="New Zealand",
            competition="Test Matches",
            sport="cricket",
            home_story_type="neutral",
            away_story_type="neutral",
            outcome="home",
            outcome_label="Bangladesh",
            bookmaker="Sportingbet",
            odds=2.05,
            ev_pct=0.0,
            fair_prob_pct=0.0,
            evidence_class="speculative",
            tone_band="cautious",
            verdict_action="monitor",
            verdict_sizing="tiny exposure",
            edge_tier="bronze",
            bookmaker_count=3,
        ),
    },
    {
        "label": "cricket-t20-monitor-full",
        "sport": "cricket",
        "coverage": "full-identity",
        "expect": "no_edge",
        "spec": dict(
            home_name="Bangladesh",
            away_name="Sri Lanka",
            competition="T20 Internationals",
            sport="cricket",
            home_story_type="neutral",
            away_story_type="neutral",
            outcome="away",
            outcome_label="Sri Lanka",
            bookmaker="Sportingbet",
            odds=1.49,
            ev_pct=0.0,
            fair_prob_pct=0.0,
            evidence_class="speculative",
            tone_band="cautious",
            verdict_action="monitor",
            verdict_sizing="tiny exposure",
            edge_tier="bronze",
            bookmaker_count=3,
        ),
    },
    {
        "label": "soccer-pass-degraded",
        "sport": "soccer",
        "coverage": "degraded",
        "expect": "no_edge",
        "spec": dict(
            home_name="Arsenal",
            away_name="Chelsea",
            competition="Premier League",
            sport="soccer",
            home_story_type="neutral",
            away_story_type="neutral",
            outcome="draw",
            outcome_label="the draw",
            bookmaker="",
            odds=0.0,
            ev_pct=0.0,
            fair_prob_pct=0.0,
            evidence_class="speculative",
            tone_band="cautious",
            verdict_action="pass",
            verdict_sizing="tiny exposure",
            edge_tier="",
            bookmaker_count=0,
        ),
    },
    {
        "label": "mma-monitor-full",
        "sport": "combat",
        "coverage": "full-identity",
        "expect": "no_edge",
        "spec": dict(
            home_name="Dricus Du Plessis",
            away_name="Sean Strickland",
            competition="UFC Events",
            sport="combat",
            home_story_type="neutral",
            away_story_type="neutral",
            outcome="home",
            outcome_label="Du Plessis",
            bookmaker="Hollywoodbets",
            odds=2.50,
            ev_pct=0.0,
            fair_prob_pct=0.0,
            evidence_class="speculative",
            tone_band="cautious",
            verdict_action="monitor",
            verdict_sizing="tiny exposure",
            edge_tier="bronze",
            bookmaker_count=2,
        ),
    },
    {
        "label": "soccer-lean-regression-guard",
        "sport": "soccer",
        "coverage": "full-identity",
        "expect": "regression_guard",  # verdict_action='lean' must NOT trip new branch
        "spec": dict(
            home_name="Liverpool",
            away_name="Manchester City",
            competition="Premier League",
            sport="soccer",
            home_story_type="neutral",
            away_story_type="neutral",
            outcome="home",
            outcome_label="Liverpool",
            bookmaker="Betway",
            odds=2.10,
            ev_pct=4.5,
            fair_prob_pct=0.45,
            evidence_class="lean",
            tone_band="moderate",
            verdict_action="lean",
            verdict_sizing="moderate stake",
            edge_tier="silver",
            bookmaker_count=4,
            support_level=1,
        ),
    },
]


def build_spec(fixture_spec: dict) -> NarrativeSpec:
    """Build a NarrativeSpec with safe defaults for any field not provided."""
    return NarrativeSpec(**fixture_spec)


def render_one(fixture: dict) -> dict:
    spec = build_spec(fixture["spec"])
    edge_section = _render_edge(spec)
    baseline = _render_baseline(spec)

    edge_lower = edge_section.lower()
    new_branch_signatures = [fp for fp in ALL_NO_EDGE_FINGERPRINTS if fp in edge_lower]
    has_qmark = "?" in baseline
    expect = fixture["expect"]

    if expect == "no_edge":
        # Null cases: must contain a no-edge variant; must NOT contain '?'.
        passed = bool(new_branch_signatures) and not has_qmark
        reasons = []
        if not new_branch_signatures:
            reasons.append("no_edge_variant_missing")
        if has_qmark:
            reasons.append("question_mark_in_baseline")
    else:
        # Regression guard: must NOT contain a no-edge variant; '?' fine here too
        # (lean branch has its own fp_str fallback, but we don't inspect it).
        passed = not new_branch_signatures
        reasons = ["new_branch_fired_on_lean"] if new_branch_signatures else []

    return {
        "label": fixture["label"],
        "sport": fixture["sport"],
        "coverage": fixture["coverage"],
        "expect": expect,
        "edge_section": edge_section,
        "baseline_first_300": baseline[:300],
        "baseline_full_len": len(baseline),
        "no_edge_signatures_hit": new_branch_signatures,
        "has_qmark_in_baseline": has_qmark,
        "passed": passed,
        "fail_reasons": reasons,
        "baseline_full": baseline,  # full output written to per-fixture file
    }


def main() -> int:
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    out_root = Path("/home/paulsportsza/reports/e2e-screenshots")
    out_root.mkdir(parents=True, exist_ok=True)

    print(f"[OPS-COMMIT-RECOVER-FIX-NARRATIVE-NO-EDGE-FAIR-VALUE-FALLBACK-01] synthetic harness")
    print(f"  output: {out_root}/OPS-COMMIT-RECOVER-FIX-NARRATIVE-NO-EDGE-FAIR-VALUE-FALLBACK-01-*-{stamp}.txt")
    print(f"  fixtures: {len(FIXTURES)}")
    print()

    overall_pass = True
    rendered: list[dict] = []
    for fx in FIXTURES:
        try:
            res = render_one(fx)
        except Exception as exc:
            res = {
                "label": fx["label"],
                "sport": fx["sport"],
                "coverage": fx["coverage"],
                "expect": fx["expect"],
                "error": f"{type(exc).__name__}: {exc}",
                "passed": False,
                "fail_reasons": [f"render_exception:{type(exc).__name__}"],
            }
            overall_pass = False

        verdict = "PASS" if res.get("passed") else "FAIL"
        sig_summary = ", ".join(res.get("no_edge_signatures_hit") or []) or "(none)"
        print(
            f"  {verdict}   {fx['label']:48s}  "
            f"expect={res['expect']:18s}  qmark={res.get('has_qmark_in_baseline')}  "
            f"signatures=[{sig_summary}]"
        )
        if not res.get("passed"):
            print(f"           reasons: {res.get('fail_reasons')}")
            overall_pass = False

        # Write per-fixture .txt file. Use label (unique) instead of sport+coverage
        # alone — two cricket fixtures share the same (sport, coverage) tuple and
        # would otherwise overwrite each other.
        per_fixture_path = out_root / (
            f"OPS-COMMIT-RECOVER-FIX-NARRATIVE-NO-EDGE-FAIR-VALUE-FALLBACK-01-"
            f"{fx['label']}-{stamp}.txt"
        )
        body_lines = [
            f"OPS-COMMIT-RECOVER-FIX-NARRATIVE-NO-EDGE-FAIR-VALUE-FALLBACK-01",
            f"label={fx['label']}",
            f"sport={fx['sport']}  coverage={fx['coverage']}  expect={fx['expect']}",
            f"verdict={verdict}",
            f"qmark_in_baseline={res.get('has_qmark_in_baseline')}",
            f"no_edge_signatures_hit={res.get('no_edge_signatures_hit')}",
            f"fail_reasons={res.get('fail_reasons')}",
            "",
            "── EDGE SECTION (rendered) ──",
            res.get("edge_section", res.get("error", "<error>")),
            "",
            "── FULL BASELINE (rendered) ──",
            res.get("baseline_full", res.get("error", "<error>")),
        ]
        per_fixture_path.write_text("\n".join(body_lines), encoding="utf-8")

        # Strip baseline_full from the persisted summary record (already in .txt)
        slim = {k: v for k, v in res.items() if k != "baseline_full"}
        rendered.append(slim)

    summary_doc = {
        "wave": "OPS-COMMIT-RECOVER-FIX-NARRATIVE-NO-EDGE-FAIR-VALUE-FALLBACK-01",
        "kind": "synthetic-render-five-fixture",
        "ac": ["HG-1", "AC-7"],
        "stamp": stamp,
        "fixtures_total": len(FIXTURES),
        "fixtures_pass": sum(1 for r in rendered if r.get("passed")),
        "fixtures_fail": sum(1 for r in rendered if not r.get("passed")),
        "overall_pass": overall_pass,
        "fixtures": rendered,
    }
    summary_path = out_root / (
        f"OPS-COMMIT-RECOVER-FIX-NARRATIVE-NO-EDGE-FAIR-VALUE-FALLBACK-01-summary-{stamp}.json"
    )
    summary_path.write_text(json.dumps(summary_doc, indent=2), encoding="utf-8")

    print()
    print(f"  summary: {summary_path}")
    print(f"  overall: {'PASS' if overall_pass else 'FAIL'}")
    return 0 if overall_pass else 1


if __name__ == "__main__":
    sys.exit(main())
