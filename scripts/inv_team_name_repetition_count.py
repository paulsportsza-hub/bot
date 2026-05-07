#!/usr/bin/env python3
"""INV-V2-VERDICT-TEAM-NAME-REPETITION-01 — count team-name occurrences per V2 verdict.

Reads narrative_cache rows for active V2-rendered edges, computes:
  1. Repetition distribution (1×, 2×, 3×, 4×+) of recommended_team in verdict_html.
  2. Per-row breakdown (match_id, sport, tier, bookmaker, odds, count, verdict).

Read-only. No production-code dependency beyond db_connect.
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))

from scrapers.db_connect import connect_odds_db

DEFAULT_DB = "/home/paulsportsza/scrapers/odds.db"


def _pretty_team(raw: str) -> str:
    fixes = {"psg": "PSG", "ts": "TS", "rcb": "RCB"}
    words = []
    for part in raw.replace("_", " ").split():
        words.append(fixes.get(part.lower(), part.capitalize()))
    return " ".join(words).strip()


def teams_from_match_key(match_id: str) -> tuple[str, str]:
    stem = re.sub(r"_\d{4}-\d{2}-\d{2}$", "", match_id or "")
    if "_vs_" not in stem:
        return "", ""
    home_raw, away_raw = stem.split("_vs_", 1)
    return _pretty_team(home_raw), _pretty_team(away_raw)


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def count_team_mentions(verdict: str, team: str) -> int:
    """Count how many times the team noun phrase (with ' win' suffix variants) appears."""
    if not verdict or not team:
        return 0
    haystack = _norm(verdict)
    # Try " win" suffix first (since recommended_team often arrives as 'Liverpool win'),
    # then fall back to bare team. Prefer the longer match for accuracy.
    needle_with = _norm(f"{team} win")
    needle_bare = _norm(team)
    matches_with = len(re.findall(rf"\b{re.escape(needle_with)}\b", haystack))
    if matches_with:
        return matches_with
    return len(re.findall(rf"\b{re.escape(needle_bare)}\b", haystack))


def _bet_type_team(match_id: str, bet_type: str) -> str:
    home, away = teams_from_match_key(match_id)
    bet_norm = _norm(bet_type)
    if bet_norm in {"home", "home win"}:
        return home
    if bet_norm in {"away", "away win"}:
        return away
    if bet_norm in {"draw", "x"}:
        return ""
    for team in (home, away):
        team_norm = _norm(team)
        if team_norm and (team_norm in bet_norm or bet_norm in team_norm):
            return team
    return ""


def fetch_rows(db_path: str) -> list[dict]:
    conn = connect_odds_db(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT nc.match_id, COALESCE(nc.verdict_html, '') AS verdict_html,
                   COALESCE(er.sport, '') AS sport,
                   COALESCE(er.league, '') AS league,
                   COALESCE(er.bet_type, '') AS bet_type,
                   COALESCE(er.edge_tier, '') AS edge_tier,
                   COALESCE(er.bookmaker, '') AS bookmaker,
                   COALESCE(er.recommended_odds, 0) AS recommended_odds,
                   COALESCE(er.match_date, '') AS match_date
              FROM narrative_cache nc
              JOIN edge_results er ON er.match_key = nc.match_id
             WHERE er.result IS NULL
               AND nc.engine_version = 'v2_microfact'
             ORDER BY er.match_date, nc.match_id
            """
        ).fetchall()
    finally:
        conn.close()

    out = []
    for r in rows:
        verdict = r["verdict_html"]
        team = _bet_type_team(r["match_id"], r["bet_type"])
        out.append(
            {
                "match_id": r["match_id"],
                "sport": r["sport"],
                "league": r["league"],
                "bet_type": r["bet_type"],
                "edge_tier": r["edge_tier"],
                "bookmaker": r["bookmaker"],
                "odds": r["recommended_odds"],
                "match_date": r["match_date"],
                "team": team,
                "verdict": verdict,
                "team_count": count_team_mentions(verdict, team),
            }
        )
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Count team-name repetition in V2 cache")
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    rows = fetch_rows(args.db)
    print(f"=== INV-V2-VERDICT-TEAM-NAME-REPETITION-01 ===")
    print(f"V2 cache rows analysed: {len(rows)}")
    if not rows:
        print("(no rows — V2 cache empty)")
        return 0

    dist = Counter(r["team_count"] for r in rows)
    print()
    print("Team-name occurrence distribution (recommended_team in verdict_html):")
    for k in sorted(dist):
        bar = "#" * dist[k]
        label = f"{k}×" if k < 4 else "4×+"
        print(f"  {label:>4} occurrences: {dist[k]:>3} rows  {bar}")
    print()
    high_rep = [r for r in rows if r["team_count"] >= 2]
    pct_2plus = 100.0 * len(high_rep) / len(rows)
    print(f"≥2× rows: {len(high_rep)}/{len(rows)} ({pct_2plus:.0f}%)")
    print(f"Max occurrences in any single row: {max(dist)}")
    print()

    print("Per-row breakdown:")
    for r in sorted(rows, key=lambda x: -x["team_count"]):
        print(
            f"  [{r['sport']}|{r['edge_tier']}|{r['bookmaker']}|odds={r['odds']}|count={r['team_count']}] "
            f"{r['match_id']}"
        )
        print(f"    > {r['verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
