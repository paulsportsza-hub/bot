"""FIX-NARRATIVE-RATING-PROMPT-PLACEHOLDER-01 — synthetic-render evidence harness (AC-9b).

Renders evidence_pack.format_evidence_prompt() for 5 non-Arsenal fixtures and
asserts zero '1853'/'1551' substring in either prompt path (edge + match_preview).

Run from /home/paulsportsza/bot:
    .venv/bin/python tests/qa/fix_narrative_rating_prompt_placeholder_01_synthetic.py

Output: /home/paulsportsza/reports/e2e-screenshots/FIX-NARRATIVE-RATING-PROMPT-PLACEHOLDER-01-{stamp}/
"""
from __future__ import annotations

import os
import sys
import json
import datetime as dt
from pathlib import Path
from types import SimpleNamespace

# bot/ on sys.path for module resolution
BOT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BOT_DIR))
os.chdir(BOT_DIR)

from evidence_pack import format_evidence_prompt, EvidencePack  # type: ignore  # noqa: E402


# 5 non-Arsenal fixtures — covers EPL non-Arsenal, PSL, UCL, La Liga, URC
FIXTURES = [
    ("liverpool_vs_manchester_city_2026-05-02", "soccer", "EPL"),
    ("orlando_pirates_vs_kaizer_chiefs_2026-05-03", "soccer", "PSL"),
    ("real_madrid_vs_barcelona_2026-05-04", "soccer", "La Liga"),
    ("paris_saint_germain_vs_bayern_munich_2026-05-05", "soccer", "Champions League"),
    ("bulls_vs_stormers_2026-05-06", "rugby", "URC"),
]

BANNED_LITERALS = ["1853", "1551"]


def make_minimal_spec(home_name: str, away_name: str, sport: str, league: str) -> SimpleNamespace:
    """Minimal NarrativeSpec stand-in compatible with format_evidence_prompt usage."""
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
        sa_tag="lean",
        h2h_history="No prior meetings",
    )


def make_minimal_pack(match_key: str, sport: str, league: str) -> EvidencePack:
    """Minimal EvidencePack with ratings-anchor lookup enabled (real DB query)."""
    return EvidencePack(
        match_key=match_key,
        sport=sport,
        league=league,
        built_at=dt.datetime.now(dt.timezone.utc).isoformat(),
        richness_score="medium",
        sources_available=4,
        sources_total=8,
    )


def render_one(match_key: str, sport: str, league: str) -> dict:
    """Render both prompt branches for one fixture and return findings."""
    home_key, rest = match_key.split("_vs_", 1)
    away_key = rest.rsplit("_", 1)[0]
    home_name = home_key.replace("_", " ").title()
    away_name = away_key.replace("_", " ").title()

    spec = make_minimal_spec(home_name, away_name, sport, league)
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
    }


def main() -> int:
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = Path(f"/home/paulsportsza/reports/e2e-screenshots/FIX-NARRATIVE-RATING-PROMPT-PLACEHOLDER-01-{stamp}")
    out_dir.mkdir(parents=True, exist_ok=True)

    summary: list[dict] = []
    overall_pass = True

    for match_key, sport, league in FIXTURES:
        try:
            result = render_one(match_key, sport, league)
        except Exception as exc:
            summary.append({
                "match_key": match_key,
                "sport": sport,
                "league": league,
                "error": f"{type(exc).__name__}: {exc}",
            })
            overall_pass = False
            continue

        # Persist verbatim prompt outputs for the report
        slug = match_key.replace("/", "_")
        (out_dir / f"{slug}.edge.prompt.txt").write_text(result["edge_prompt"], encoding="utf-8")
        (out_dir / f"{slug}.preview.prompt.txt").write_text(result["preview_prompt"], encoding="utf-8")

        edge_total = sum(result["edge_literal_hits"].values())
        preview_total = sum(result["preview_literal_hits"].values())
        passed = (edge_total == 0 and preview_total == 0)

        summary.append({
            "match_key": match_key,
            "sport": sport,
            "league": league,
            "edge_prompt_len": result["edge_prompt_len"],
            "preview_prompt_len": result["preview_prompt_len"],
            "edge_literal_hits": result["edge_literal_hits"],
            "preview_literal_hits": result["preview_literal_hits"],
            "passed": passed,
        })
        if not passed:
            overall_pass = False

    summary_doc = {
        "wave": "FIX-NARRATIVE-RATING-PROMPT-PLACEHOLDER-01",
        "kind": "synthetic-render",
        "ac": "AC-9b",
        "ts": stamp,
        "fixtures_total": len(FIXTURES),
        "overall_pass": overall_pass,
        "banned_literals": BANNED_LITERALS,
        "results": summary,
    }
    (out_dir / "summary.json").write_text(json.dumps(summary_doc, indent=2), encoding="utf-8")

    # Console verdict
    print(f"[FIX-NARRATIVE-RATING-PROMPT-PLACEHOLDER-01] synthetic harness")
    print(f"  output: {out_dir}")
    print(f"  fixtures: {len(FIXTURES)}")
    for row in summary:
        if "error" in row:
            print(f"  ERROR  {row['match_key']:60s}  {row['error']}")
            continue
        verdict = "PASS" if row["passed"] else "FAIL"
        print(
            f"  {verdict}   {row['match_key']:60s}  "
            f"edge={row['edge_literal_hits']}  preview={row['preview_literal_hits']}"
        )
    print(f"  overall: {'PASS' if overall_pass else 'FAIL'}")
    return 0 if overall_pass else 1


if __name__ == "__main__":
    sys.exit(main())
