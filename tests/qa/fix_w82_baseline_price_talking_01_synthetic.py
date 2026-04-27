"""FIX-W82-BASELINE-PRICE-TALKING-01 — Synthetic-Render QA Harness.

Why synthetic, not Telethon: the W82 deterministic baseline path only ships when
Sonnet polish FAILS — and live W82 rows are rare (current cache: 7 active rows).
Triggering a live regen via Telethon for this specific code path is unreliable.
Per brief AC-7, synthetic-render evidence is allowed for this wave.

This harness drives the variant matrix in `_render_setup_no_context` directly by
calling `narrative_spec._render_baseline(spec)` with controlled inputs across:
  - 5 sports (soccer, rugby, cricket, mma, boxing)
  - 5 coverage profiles (premium_confident_multi, solid_balanced_single,
    thin_cautious_no_signal, premium_cautious_no_signal, solid_confident_no_signal)
  = 25 fixtures total

Each rendered baseline is scanned with both `_find_setup_strict_ban_violations`
AND `_validate_baseline_setup` (parity check). Each is also string-searched for
"market architecture" (not in strict-ban tokens but explicitly banned by Rule 12).
"""
from __future__ import annotations

import datetime as dt
import os
import sys
from pathlib import Path

# Ensure /home/paulsportsza/bot is on sys.path so we can `import bot` and
# `import narrative_spec` from anywhere this harness runs from.
_BOT_DIR = Path("/home/paulsportsza/bot")
if str(_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(_BOT_DIR))
os.chdir(_BOT_DIR)

# Lazy/late imports so the sys.path mutation above takes effect.
import narrative_spec  # noqa: E402
import bot  # noqa: E402


REPORT_DIR = Path("/home/paulsportsza/reports/e2e-screenshots")
REPORT_DIR.mkdir(parents=True, exist_ok=True)
TIMESTAMP = dt.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
PREFIX = "FIX-W82-BASELINE-PRICE-TALKING-01"


# Coverage profiles — drive every variant of `_render_setup_no_context` and
# downstream renderers. Each tuple: (name, composite, signals, ev, odds).
PROFILES = [
    ("premium_confident_multi", 78.0, 3, 9.5, 1.55),
    ("solid_balanced_single", 55.0, 1, 4.0, 1.85),
    ("thin_cautious_no_signal", 42.0, 0, 1.2, 2.10),  # variant 4 path
    ("premium_cautious_no_signal", 65.0, 0, 1.5, 3.40),  # live underdog path
    ("solid_confident_no_signal", 56.0, 0, 8.5, 1.60),  # short favourite path
]


# Sports + matched competition / sample teams. We pick sport-appropriate names so
# the renderer doesn't trip over inappropriate templates. Empty ctx_data forces
# the no-context branch which is the W82 path under audit.
SPORTS = [
    {
        "sport": "soccer",
        "competition": "Premier League",
        "home": "Brighton",
        "away": "Crystal Palace",
        "bookmaker": "Betway",
    },
    {
        "sport": "rugby",
        "competition": "United Rugby Championship",
        "home": "Stormers",
        "away": "Bulls",
        "bookmaker": "Hollywoodbets",
    },
    {
        "sport": "cricket",
        "competition": "SA20",
        "home": "Paarl Royals",
        "away": "Joburg Super Kings",
        "bookmaker": "Sportingbet",
    },
    {
        "sport": "mma",
        "competition": "UFC Fight Night",
        "home": "Dricus du Plessis",
        "away": "Sean Strickland",
        "bookmaker": "GBets",
    },
    {
        "sport": "boxing",
        "competition": "WBC Heavyweight",
        "home": "Tyson Fury",
        "away": "Anthony Joshua",
        "bookmaker": "Supabets",
    },
]


def build_spec(sport_cfg: dict, profile: tuple) -> "narrative_spec.NarrativeSpec":
    """Build a NarrativeSpec by going through `build_narrative_spec` so the same
    _classify_evidence + GATE-RELAX rules apply as in production. ctx_data is
    forced empty to drive `_render_setup_no_context`."""
    name, composite, signals, ev, odds = profile

    # Outcome: pick "home" for all to keep variant control simple. The away
    # advantage risk factor still fires when relevant via _build_risk_factors.
    edge_data = {
        "home_team": sport_cfg["home"],
        "away_team": sport_cfg["away"],
        "league": sport_cfg["competition"],
        "outcome": "home",
        "best_bookmaker": sport_cfg["bookmaker"],
        "best_odds": odds,
        "edge_pct": ev,
        "composite_score": composite,
        "confirming_signals": signals,
        "contradicting_signals": 0,
        "fair_probability": (1 + ev / 100.0) / odds,
        "stale_minutes": 0,
        "movement_direction": "neutral",
        "tipster_against": 0,
        "tipster_agrees": None,
        "tipster_available": False,
        "bookmaker_count": 4,
    }

    # Empty ctx_data → triggers `_render_setup_no_context` (the variant matrix
    # under audit). build_narrative_spec lazy-imports from bot.py — that's fine
    # because we already imported bot above.
    spec = narrative_spec.build_narrative_spec(
        ctx_data={},
        edge_data=edge_data,
        tips=[],
        sport=sport_cfg["sport"],
    )
    return spec


def scan_violations(html: str) -> dict:
    """Run all three checks on a rendered baseline:
       1. _find_setup_strict_ban_violations (polish-time enforcer)
       2. _validate_baseline_setup (baseline-time wrapper — must match #1)
       3. literal 'market architecture' string-search (Rule 12 explicit)
    """
    strict = bot._find_setup_strict_ban_violations(html)
    baseline = bot._validate_baseline_setup(html)

    # Setup section only for "market architecture" — pull it out using the
    # same extractor the validators use.
    setup_only = bot._extract_setup_section(html) or ""
    market_arch_hit = "market architecture" in setup_only.lower()

    return {
        "strict": strict,
        "baseline": baseline,
        "parity": strict == baseline,
        "market_architecture": market_arch_hit,
    }


def main() -> int:
    print(f"=== {PREFIX} synthetic-render harness ===")
    print(f"Timestamp: {TIMESTAMP}")
    print(f"Output dir: {REPORT_DIR}")
    print(f"Fixtures: {len(SPORTS)} sports x {len(PROFILES)} profiles = {len(SPORTS) * len(PROFILES)} cells")
    print()

    total_fixtures = 0
    total_strict_hits = 0
    total_baseline_hits = 0
    total_market_arch_hits = 0
    parity_failures = 0
    per_phrase_counts: dict[str, int] = {}
    per_fixture_results: list[dict] = []

    for sport_cfg in SPORTS:
        for profile in PROFILES:
            total_fixtures += 1
            profile_name = profile[0]
            sport = sport_cfg["sport"]

            # Build spec + render baseline
            try:
                spec = build_spec(sport_cfg, profile)
                rendered = narrative_spec._render_baseline(spec)
            except Exception as exc:
                print(f"FAIL [{sport}/{profile_name}] render exception: {exc}")
                per_fixture_results.append({
                    "sport": sport,
                    "profile": profile_name,
                    "verdict": "RENDER_FAIL",
                    "error": str(exc),
                })
                continue

            # Scan for violations
            scan = scan_violations(rendered)

            n_strict = len(scan["strict"])
            n_baseline = len(scan["baseline"])
            mkt = scan["market_architecture"]
            parity_ok = scan["parity"]

            total_strict_hits += n_strict
            total_baseline_hits += n_baseline
            if mkt:
                total_market_arch_hits += 1
            if not parity_ok:
                parity_failures += 1

            for hit in scan["strict"]:
                per_phrase_counts[hit] = per_phrase_counts.get(hit, 0) + 1

            verdict = "PASS" if (n_strict == 0 and n_baseline == 0 and not mkt and parity_ok) else "FAIL"

            # Save rendered baseline to evidence file
            evidence_path = REPORT_DIR / f"{PREFIX}-{sport}-{profile_name}-{TIMESTAMP}.txt"
            evidence_path.write_text(
                f"=== {PREFIX} synthetic render ===\n"
                f"Sport: {sport}\n"
                f"Profile: {profile_name}\n"
                f"Composite: {profile[1]}, Signals: {profile[2]}, EV%: {profile[3]}, Odds: {profile[4]}\n"
                f"Competition: {sport_cfg['competition']}\n"
                f"Match: {sport_cfg['home']} vs {sport_cfg['away']}\n"
                f"Bookmaker: {sport_cfg['bookmaker']}\n"
                f"Spec evidence_class: {spec.evidence_class}\n"
                f"Spec tone_band: {spec.tone_band}\n"
                f"Spec verdict_action: {spec.verdict_action}\n"
                f"Generated at: {TIMESTAMP}\n"
                f"Verdict: {verdict}\n"
                f"Strict ban hits: {scan['strict']}\n"
                f"Baseline hits: {scan['baseline']}\n"
                f"Parity: {parity_ok}\n"
                f"market_architecture: {mkt}\n"
                f"\n--- RENDERED BASELINE BEGIN ---\n"
                f"{rendered}\n"
                f"--- RENDERED BASELINE END ---\n",
                encoding="utf-8",
            )

            print(
                f"{verdict} [{sport}/{profile_name}] "
                f"strict={n_strict} baseline={n_baseline} "
                f"parity={'YES' if parity_ok else 'NO'} "
                f"market_arch={'YES' if mkt else 'no'}"
            )
            if scan["strict"]:
                for hit in scan["strict"]:
                    print(f"   strict-hit: {hit}")
            if mkt:
                print(f"   market_architecture: present in Setup")

            per_fixture_results.append({
                "sport": sport,
                "profile": profile_name,
                "verdict": verdict,
                "strict": scan["strict"],
                "baseline": scan["baseline"],
                "parity": parity_ok,
                "market_arch": mkt,
                "evidence_file": str(evidence_path),
            })

    print()
    print("=== SUMMARY ===")
    print(f"Total fixtures: {total_fixtures}")
    print(f"Total strict-ban hits: {total_strict_hits}")
    print(f"Total baseline-helper hits: {total_baseline_hits}")
    print(f"Total 'market architecture' hits: {total_market_arch_hits}")
    print(f"Parity failures (strict != baseline): {parity_failures}")
    print()
    print("Per-phrase counts:")
    if not per_phrase_counts:
        print("  (all zero — no phrase fired across any fixture)")
    else:
        for phrase, count in sorted(per_phrase_counts.items()):
            print(f"  {phrase}: {count}")
    print()

    overall = (
        total_strict_hits == 0
        and total_baseline_hits == 0
        and total_market_arch_hits == 0
        and parity_failures == 0
    )
    print(f"OVERALL VERDICT: {'PASS' if overall else 'FAIL'}")
    return 0 if overall else 1


if __name__ == "__main__":
    sys.exit(main())
