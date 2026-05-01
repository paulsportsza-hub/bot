#!/usr/bin/env python3
"""HG-4 synthetic verdict demonstration for FIX-NARRATIVE-W82-VARIANT-EXPANSION-01.

Generates 30 synthetic match-keys spanning Core 7 sports + all 4 tiers,
calls narrative_spec._render_baseline directly, captures the resulting
verdict text VERBATIM, hashes the first 8 tokens (lowercased,
whitespace-normalised) to detect opening-shape repetition, and groups
verdicts by hash bucket.

Acceptance per the brief:
  - ≥5 distinct opening-shape hashes across the 30 verdicts.
  - No single bucket > 50% of corpus (i.e. between 3-10 verdicts per bucket).

Output: prints a markdown-formatted block ready to paste into the wave
report under ## HG-4 evidence.
"""
from __future__ import annotations

import hashlib
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from narrative_spec import NarrativeSpec, _render_baseline


# 30 synthetic fixtures spanning Core 7 sports + 4 tiers + multiple leagues.
FIXTURES = [
    # EPL
    ("Liverpool", "Chelsea", "Anfield", "Arne Slot", "WWWDW", "LWLDL", 2, 10, "gold", "back", "epl", 1.65, "Supabets"),
    ("Manchester City", "Brentford", "Etihad Stadium", "Pep Guardiola", "WWWWW", "LLLDW", 1, 14, "diamond", "strong back", "epl", 1.36, "Supabets"),
    ("Arsenal", "Tottenham Hotspur", "Emirates Stadium", "Mikel Arteta", "WWWLW", "DLWWD", 3, 6, "gold", "back", "epl", 1.72, "Hollywoodbets"),
    ("Aston Villa", "Newcastle United", "Villa Park", "Unai Emery", "DWWLD", "WLLDW", 8, 5, "silver", "lean", "epl", 2.05, "Sportingbet"),
    ("Manchester United", "Liverpool", "Old Trafford", "Michael Carrick", "LDWWL", "WWWDW", 12, 2, "gold", "back", "epl", 2.10, "WSB"),
    ("Everton", "West Ham", "Hill Dickinson Stadium", "David Moyes", "WLLDW", "DLLWD", 14, 13, "silver", "lean", "epl", 2.15, "Hollywoodbets"),
    ("Nottingham Forest", "Newcastle United", "City Ground", "Vitor Pereira", "WDLDW", "WLLDW", 9, 5, "silver", "lean", "epl", 2.52, "Supabets"),
    # PSL
    ("Mamelodi Sundowns", "Orlando Pirates", "Loftus Versfeld", "Miguel Cardoso", "WWWWD", "DWLLW", 1, 4, "diamond", "strong back", "psl", 1.45, "Hollywoodbets"),
    ("Kaizer Chiefs", "Stellenbosch", "FNB Stadium", "Khalil Ben Youssef", "DWLDD", "WWDLL", 6, 3, "silver", "lean", "psl", 1.95, "Betway"),
    ("Sekhukhune United", "AmaZulu", "Peter Mokaba Stadium", "Eric Tinkler", "WLDWW", "DWLDW", 5, 8, "bronze", "speculative punt", "psl", 3.20, "Sportingbet"),
    # Champions League
    ("Bayern Munich", "Borussia Dortmund", "Allianz Arena", "Vincent Kompany", "WWDWW", "LDWLW", 1, 4, "gold", "back", "champions_league", 1.55, "Supabets"),
    ("Real Madrid", "FC Barcelona", "Bernabéu", "Alvaro Arbeloa", "WDWWW", "WWLDW", 1, 2, "diamond", "strong back", "champions_league", 1.85, "WSB"),
    ("Atletico Madrid", "Sevilla", "Metropolitano", "Diego Simeone", "WWLWD", "DWLLD", 4, 9, "silver", "lean", "champions_league", 1.65, "Hollywoodbets"),
    # La Liga / Serie A / Ligue 1 / Primeira
    ("Juventus", "Inter Milan", "Allianz Stadium Turin", "Luciano Spalletti", "DWWLW", "WWWDD", 4, 1, "gold", "back", "serie_a", 2.20, "Betway"),
    ("AC Milan", "Napoli", "San Siro", "Massimiliano Allegri", "WLWWD", "WDWWW", 5, 2, "silver", "lean", "serie_a", 2.65, "Sportingbet"),
    ("Paris Saint Germain", "Marseille", "Parc des Princes", "Luis Enrique", "WWWWW", "WLDWL", 1, 4, "diamond", "strong back", "ligue_1", 1.40, "Supabets"),
    # URC + Super Rugby + International Rugby
    ("Stormers", "Bulls", "DHL Stadium", "", "WLDWW", "WWDLD", 2, 5, "gold", "back", "urc", 1.85, "Hollywoodbets"),
    ("Sharks", "Lions", "Kings Park", "", "DLWLD", "LDLLW", 8, 11, "silver", "lean", "urc", 2.30, "Betway"),
    ("Stade Toulousain", "Munster", "", "", "", "", None, None, "silver", "lean", "champions_cup_rugby", 1.75, "Hollywoodbets"),
    ("South Africa Rugby", "New Zealand Rugby", "Ellis Park", "", "WWWWW", "WDWLW", 1, 2, "diamond", "strong back", "international_rugby", 2.10, "WSB"),
    ("Crusaders", "Blues", "Apollo Projects Stadium", "", "WWWLW", "WDLWW", 1, 3, "gold", "back", "super_rugby", 1.65, "Sportingbet"),
    ("England Rugby", "France Rugby", "Twickenham", "", "WLWDW", "WWDLW", 2, 3, "gold", "back", "six_nations", 2.05, "Supabets"),
    # Cricket — IPL + SA20 + T20I
    ("Mumbai Indians", "Chennai Super Kings", "Wankhede Stadium", "", "WLWWL", "WWLDD", 4, 5, "gold", "back", "ipl", 1.95, "Hollywoodbets"),
    ("Royal Challengers Bangalore", "Gujarat Titans", "Chinnaswamy Stadium", "", "WWLDW", "LWWLD", 3, 6, "silver", "lean", "ipl", 2.10, "Betway"),
    ("Sunrisers Hyderabad", "Delhi Capitals", "Rajiv Gandhi Stadium", "", "LWDLW", "DWLLD", 7, 9, "silver", "lean", "ipl", 2.45, "Sportingbet"),
    ("MI Cape Town", "Joburg Super Kings", "Newlands", "", "WDWLW", "WLLDW", 2, 4, "bronze", "speculative punt", "sa20", 2.85, "Hollywoodbets"),
    ("Australia Cricket", "India Cricket", "MCG", "", "WWDWL", "WLWWD", 2, 1, "gold", "back", "t20i", 1.95, "WSB"),
    # Bonus / lower-tier
    ("Olympique Lyonnais", "Olympique Marseille", "Groupama Stadium", "", "DWLDW", "WWDLW", 8, 4, "silver", "lean", "ligue_1", 2.20, "Supabets"),
    ("Sporting CP", "FC Porto", "Estádio José Alvalade", "", "WWWWW", "WWDWW", 1, 2, "gold", "back", "primeira", 2.05, "Betway"),
    ("Boca Juniors", "River Plate", "La Bombonera", "", "WWLDW", "DWWLW", 3, 1, "silver", "lean", "argentine", 2.35, "Hollywoodbets"),
]


def make_spec(home, away, venue, coach, home_form, away_form, home_pos, away_pos, tier, action, league, odds, bookmaker):
    sport = "soccer"
    if league in ("urc", "super_rugby", "champions_cup_rugby", "six_nations", "international_rugby"):
        sport = "rugby"
    elif league in ("ipl", "sa20", "t20i"):
        sport = "cricket"
    return NarrativeSpec(
        home_name=home, away_name=away,
        competition=league.upper().replace("_", " "),
        sport=sport,
        home_story_type="momentum" if (home_pos and home_pos <= 4) else "neutral",
        away_story_type="crisis" if (away_pos and away_pos >= 12) else "inconsistent",
        home_coach=coach, away_coach="",
        home_position=home_pos, away_position=away_pos,
        home_points=68 if home_pos else None,
        away_points=42 if away_pos else None,
        home_form=home_form, away_form=away_form,
        outcome="home", outcome_label=home,
        bookmaker=bookmaker, odds=odds, ev_pct=4.5,
        fair_prob_pct=63.0, composite_score=70.0, bookmaker_count=4,
        support_level=2 if tier in ("diamond", "gold") else 1,
        contradicting_signals=0,
        evidence_class="supported" if tier in ("diamond", "gold") else "lean",
        tone_band="confident" if tier == "diamond" else "moderate",
        risk_factors=["Squad rotation possible after midweek fixtures"],
        risk_severity="moderate",
        verdict_action=action, verdict_sizing="standard stake",
        edge_tier=tier, venue=venue,
    )


def opening_hash(verdict_text: str) -> str:
    """Hash first 8 lowercased whitespace-normalised tokens of a verdict."""
    tokens = verdict_text.lower().split()
    head = " ".join(tokens[:8])
    return hashlib.md5(head.encode("utf-8")).hexdigest()[:8]


def main():
    print("# HG-4 evidence — 30 synthetic verdicts via narrative_spec._render_baseline")
    print()
    print(f"Total fixtures: {len(FIXTURES)}")
    print()

    buckets: dict[str, list[tuple[str, str]]] = defaultdict(list)
    full_records: list[tuple[str, str, str, str]] = []  # (label, hash, full_baseline, verdict)

    for fx in FIXTURES:
        spec = make_spec(*fx)
        baseline = _render_baseline(spec)
        # Extract verdict section
        idx = baseline.find("🏆 <b>Verdict</b>\n")
        verdict = baseline[idx + len("🏆 <b>Verdict</b>\n"):].strip() if idx >= 0 else baseline.strip()
        h = opening_hash(verdict)
        label = f"{fx[0]}_vs_{fx[1]}".lower().replace(" ", "_")
        buckets[h].append((label, verdict))
        full_records.append((label, h, baseline, verdict))

    print(f"Distinct opening-shape hashes: {len(buckets)}")
    print(f"Acceptance threshold: >= 5 distinct hashes")
    print(f"Result: {'PASS' if len(buckets) >= 5 else 'FAIL'}")
    print()
    max_bucket_size = max(len(v) for v in buckets.values())
    max_pct = max_bucket_size / len(FIXTURES) * 100
    print(f"Largest bucket: {max_bucket_size} verdicts ({max_pct:.1f}% of corpus)")
    print(f"No-single-bucket-> 50% rule: {'PASS' if max_pct <= 50 else 'FAIL'}")
    print()

    # Sort buckets by size desc for readable output
    sorted_buckets = sorted(buckets.items(), key=lambda kv: -len(kv[1]))
    for i, (h, items) in enumerate(sorted_buckets, 1):
        print(f"## Bucket {i} (hash=0x{h}): {len(items)} verdicts")
        for label, verdict in items:
            # Print one full verbatim verdict per fixture
            print(f"  - {label}: {verdict!r}")
        print()


if __name__ == "__main__":
    main()
