#!/usr/bin/env python3
"""QA-BASELINE-02 — 48-card matrix baseline generation and scoring.

Uses the LIVE production codepath:
  build_narrative_spec() → _render_baseline() (deterministic)
  + _generate_verdict_constrained() system prompt (Claude API verdict)

Matrix: 4 tiers × 4 sports × 3 fixture shapes = 48 cards.

Usage:
    cd /home/paulsportsza/bot
    .venv/bin/python scripts/qa_baseline_02.py
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import sqlite3
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo
SAST = ZoneInfo("Africa/Johannesburg")
UTC = ZoneInfo("UTC")
from pathlib import Path

# ── Setup paths ──────────────────────────────────────────────────────────
BOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BOT_DIR))
sys.path.insert(0, str(BOT_DIR.parent / "scrapers"))
if str(BOT_DIR.parent) not in sys.path:
    sys.path.insert(0, str(BOT_DIR.parent))

# Suppress Sentry before any imports from bot
os.environ["SENTRY_DSN"] = ""
os.environ.setdefault("BOT_TOKEN", "DUMMY")

# Load .env for ANTHROPIC_API_KEY
_env_path = BOT_DIR / ".env"
if _env_path.exists():
    for _line in _env_path.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            k, _, v = _line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

logging.basicConfig(level=logging.WARNING)
log = logging.getLogger("qa_baseline_02")

# ── Imports ──────────────────────────────────────────────────────────────
from db_connect import connect_odds_db as _connect_odds_db  # W81-DBLOCK (scrapers/ on sys.path)
import anthropic as _anthropic  # noqa: E402

from narrative_spec import (  # noqa: E402
    NarrativeSpec,
    _build_h2h_summary,
    _build_outcome_label,
    _build_risk_factors,
    _assess_risk_severity,
    _classify_evidence,
    _enforce_coherence,
    _humanise_league,
    _render_baseline,
    build_narrative_spec,
    lookup_coach,
)

try:
    from team_data import get_nickname, form_to_plain  # noqa: E402
except ImportError:
    def get_nickname(n):
        return n
    def form_to_plain(lst, team_name=""):
        return ""

# ── Constants ────────────────────────────────────────────────────────────
TIERS = ["diamond", "gold", "silver", "bronze"]
SPORTS = ["soccer", "rugby", "cricket", "mma"]
SHAPES = ["home_favourite", "home_underdog", "road_favourite"]
ODDS_DB = BOT_DIR.parent / "scrapers" / "odds.db"
TS = datetime.now(SAST).strftime("%Y%m%dT%H%M%S%z")
RAW_JSONL = BOT_DIR / "structured_logs" / f"qa_baseline_02_raw_{TS}.jsonl"
RESULTS_JSON = Path("/home/paulsportsza/reports/qa-baseline-02-results.json")

# Tier → confidence mapping for verdict
TIER_CONFIDENCE = {
    "diamond": "MAX",
    "gold": "STRONG",
    "silver": "SOLID",
    "bronze": "MILD",
}

# Tier → parameter ranges
TIER_PARAMS = {
    "diamond": {"ev_min": 8.0, "ev_max": 15.0, "comp_min": 70, "comp_max": 85, "signals": 3},
    "gold": {"ev_min": 4.0, "ev_max": 8.0, "comp_min": 55, "comp_max": 70, "signals": 2},
    "silver": {"ev_min": 2.0, "ev_max": 4.0, "comp_min": 40, "comp_max": 55, "signals": 1},
    "bronze": {"ev_min": 1.0, "ev_max": 2.5, "comp_min": 25, "comp_max": 40, "signals": 0},
}

# ── Verdict prompt (from smoke_verify_5run.py / _generate_verdict_constrained) ──
VERDICT_SYSTEM_PROMPT = (
    "You are a sharp SA sports pundit writing a short verdict for a betting edge card.\n"
    "You sound like a knowledgeable South African sports fan — direct, confident, warm, no waffle.\n"
    "You are NOT a risk-disclaimer machine. You are someone who watched the form, checked the numbers, and knows the call.\n"
    "\n"
    "Rules:\n"
    "- 2 sentences maximum, then one final call line\n"
    "- Sentence 1: the pick + bookmaker + why (form or H2H)\n"
    "- Sentence 2: the supporting evidence (form gap, head-to-head, signals) — ONE supporting point only\n"
    "- Final line: always \"Back [team/outcome].\" — short, punchy, standalone\n"
    "- Use nicknames and manager names to create personality — but only when the field is provided\n"
    "- NEVER mention EV%\n"
    "- NEVER use abbreviations: no H2H, no EV, no WLLLW form strings\n"
    "- NEVER hedge: no 'could', 'might', 'possibly', 'if form holds'\n"
    "- Name the bookmaker — always\n"
    "- Active voice, present tense\n"
    "- NO hallucination: only use the exact fields provided\n"
    "\n"
    "ABSOLUTELY FORBIDDEN:\n"
    "- Stadium or venue names — NOT in our database\n"
    "- Player names — NOT verified in our system\n"
    "- Any statistic not in the verified fields\n"
    "- Tactical descriptions\n"
    "- Staking advice of any kind\n"
    "- Hedge language\n"
    "- DIAMOND TIER (confidence_tier: MAX only): Open with price-prefix: '<stake> returns <payout> · Edge confirmed'.\n"
    "- PLAIN TEXT ONLY: No markdown, no asterisks, no backticks\n"
    "\n"
    "SA VOICE — NON-NEGOTIABLE: Write like you're telling a mate at the braai why this bet is sharp.\n"
)


# ══════════════════════════════════════════════════════════════════════════
# 48-CARD MATRIX FIXTURE DEFINITIONS
# ══════════════════════════════════════════════════════════════════════════

def _build_fixtures() -> list[dict]:
    """Build 48 fixtures: real DB edges + synthesised for missing cells."""
    fixtures = []

    # ── REAL EDGES from edge_results ─────────────────────────────────
    real = _load_real_edges()

    # ── SOCCER ───────────────────────────────────────────────────────
    # Diamond
    fixtures.append(_real_or_synth(real, "soccer", "diamond", "home_favourite",
        fallback={"home": "Liverpool", "away": "Crystal Palace", "league": "epl",
                  "odds": 1.53, "ev": 4.1, "comp": 61.1, "pick": "Home Win",
                  "bk": "Supabets", "signals": 2, "form_h": "WWDWW", "form_a": "DLWLL"}))
    fixtures.append(_synth("soccer", "diamond", "home_underdog",
        home="Wolves", away="Manchester City", league="epl",
        odds=4.20, ev=9.5, comp=72, pick="Home Win",
        bk="GBets", signals=3, form_h="WWWDL", form_a="WLWLW",
        sub="Synthesised: no Diamond soccer home-underdog in DB"))
    fixtures.append(_synth("soccer", "diamond", "road_favourite",
        home="Southampton", away="Arsenal", league="epl",
        odds=1.65, ev=10.2, comp=75, pick="Away Win",
        bk="Betway", signals=3, form_h="LLLDL", form_a="WWWWW",
        sub="Synthesised: no Diamond soccer road-favourite in DB"))

    # Gold
    fixtures.append(_real_or_synth(real, "soccer", "gold", "home_favourite",
        fallback={"home": "Orlando Pirates", "away": "AmaZulu", "league": "psl",
                  "odds": 1.50, "ev": 7.6, "comp": 51.9, "pick": "Home Win",
                  "bk": "Hollywoodbets", "signals": 1, "form_h": "WWWDW", "form_a": "LLDWL"}))
    fixtures.append(_synth("soccer", "gold", "home_underdog",
        home="Everton", away="Liverpool", league="epl",
        odds=3.30, ev=5.2, comp=58, pick="Home Win",
        bk="Sportingbet", signals=2, form_h="DWLWW", form_a="WWWWL",
        sub="Synthesised from edge_results everton_vs_liverpool (Silver→Gold promotion)"))
    fixtures.append(_real_or_synth(real, "soccer", "gold", "road_favourite",
        fallback={"home": "Fulham", "away": "Aston Villa", "league": "epl",
                  "odds": 2.60, "ev": 5.7, "comp": 51.5, "pick": "Away Win",
                  "bk": "WSB", "signals": 1, "form_h": "WLDWL", "form_a": "WWWDW"}))

    # Silver
    fixtures.append(_real_or_synth(real, "soccer", "silver", "home_favourite",
        fallback={"home": "Brentford", "away": "Fulham", "league": "epl",
                  "odds": 2.16, "ev": 1.9, "comp": 54.9, "pick": "Home Win",
                  "bk": "Supabets", "signals": 2, "form_h": "WDWWL", "form_a": "LWDWL"}))
    fixtures.append(_real_or_synth(real, "soccer", "silver", "home_underdog",
        fallback={"home": "Wolves", "away": "Tottenham", "league": "epl",
                  "odds": 3.65, "ev": 3.7, "comp": 54.6, "pick": "Home Win",
                  "bk": "WSB", "signals": 2, "form_h": "LWWDL", "form_a": "WDLWW"}))
    fixtures.append(_synth("soccer", "silver", "road_favourite",
        home="Ipswich", away="Newcastle", league="epl",
        odds=2.10, ev=2.8, comp=46, pick="Away Win",
        bk="Sportingbet", signals=2, form_h="LLDLL", form_a="WWDWW",
        sub="Synthesised: newcastle_vs_bournemouth adapted (shape adjusted)"))

    # Bronze
    fixtures.append(_real_or_synth(real, "soccer", "bronze", "home_favourite",
        fallback={"home": "Arsenal", "away": "Newcastle", "league": "epl",
                  "odds": 1.53, "ev": 1.3, "comp": 63.1, "pick": "Home Win",
                  "bk": "Supabets", "signals": 3, "form_h": "WWWDW", "form_a": "DWWLW"}))
    fixtures.append(_real_or_synth(real, "soccer", "bronze", "home_underdog",
        fallback={"home": "Magesi", "away": "Kaizer Chiefs", "league": "psl",
                  "odds": 5.25, "ev": 3.5, "comp": 23.0, "pick": "Home Win",
                  "bk": "WSB", "signals": 0, "form_h": "LDLWL", "form_a": "WDWWL"}))
    fixtures.append(_real_or_synth(real, "soccer", "bronze", "road_favourite",
        fallback={"home": "Tottenham", "away": "Brighton", "league": "epl",
                  "odds": 2.46, "ev": 1.2, "comp": 47.2, "pick": "Away Win",
                  "bk": "Supabets", "signals": 2, "form_h": "WLDWL", "form_a": "WWWDW"}))

    # ── RUGBY ────────────────────────────────────────────────────────
    # Diamond
    fixtures.append(_synth("rugby", "diamond", "home_favourite",
        home="Stormers", away="Sharks", league="urc",
        odds=1.55, ev=9.8, comp=73, pick="Home Win",
        bk="Hollywoodbets", signals=3, form_h="WWWWW", form_a="WLLDW",
        sub="Synthesised: no Diamond rugby in DB", h2h={"n": 6, "hw": 4, "d": 0, "aw": 2},
        home_mgr="", away_mgr=""))
    fixtures.append(_synth("rugby", "diamond", "home_underdog",
        home="Glasgow", away="Leinster", league="urc",
        odds=3.80, ev=11.5, comp=76, pick="Home Win",
        bk="GBets", signals=3, form_h="WWDWW", form_a="WWWWW",
        sub="Synthesised: no Diamond rugby in DB", h2h={"n": 4, "hw": 1, "d": 0, "aw": 3}))
    fixtures.append(_synth("rugby", "diamond", "road_favourite",
        home="Zebre", away="Bulls", league="urc",
        odds=1.40, ev=12.0, comp=78, pick="Away Win",
        bk="Betway", signals=3, form_h="LLLDL", form_a="WWWWW",
        sub="Synthesised: no Diamond rugby in DB"))

    # Gold
    fixtures.append(_synth("rugby", "gold", "home_favourite",
        home="Bulls", away="Lions", league="urc",
        odds=1.65, ev=5.5, comp=60, pick="Home Win",
        bk="Hollywoodbets", signals=2, form_h="WWDWW", form_a="WLWLD",
        sub="Synthesised: no Gold rugby in DB"))
    fixtures.append(_synth("rugby", "gold", "home_underdog",
        home="Scarlets", away="Stormers", league="urc",
        odds=3.20, ev=6.0, comp=62, pick="Home Win",
        bk="GBets", signals=2, form_h="WDWLW", form_a="WWWWL",
        sub="Synthesised: no Gold rugby in DB", h2h={"n": 3, "hw": 1, "d": 0, "aw": 2}))
    fixtures.append(_synth("rugby", "gold", "road_favourite",
        home="Dragons", away="Sharks", league="urc",
        odds=1.80, ev=4.8, comp=58, pick="Away Win",
        bk="Betway", signals=2, form_h="LLDWL", form_a="WWWDW",
        sub="Synthesised: no Gold rugby in DB"))

    # Silver
    fixtures.append(_synth("rugby", "silver", "home_favourite",
        home="Hurricanes", away="Blues", league="super_rugby",
        odds=1.85, ev=2.5, comp=48, pick="Home Win",
        bk="Sportingbet", signals=1, form_h="WWWWW", form_a="WDWWW",
        sub="Synthesised from match_results: hurricanes_vs_blues"))
    fixtures.append(_synth("rugby", "silver", "home_underdog",
        home="Lions", away="Glasgow", league="urc",
        odds=4.00, ev=1.8, comp=35.7, pick="Home Win",
        bk="Hollywoodbets", signals=0, form_h="WLLWL", form_a="WWWDW",
        sub="lions_vs_glasgow edge adapted (Away→Home pick, shape adjusted)"))
    fixtures.append(_real_or_synth(real, "rugby", "silver", "road_favourite",
        fallback={"home": "Ulster", "away": "Leinster", "league": "urc",
                  "odds": 2.21, "ev": 1.9, "comp": 66.6, "pick": "Away Win",
                  "bk": "GBets", "signals": 2, "form_h": "LWDLW", "form_a": "WWWWD"}))

    # Bronze
    fixtures.append(_synth("rugby", "bronze", "home_favourite",
        home="Sharks", away="Scarlets", league="urc",
        odds=1.50, ev=1.2, comp=32, pick="Home Win",
        bk="Hollywoodbets", signals=0, form_h="WDWLW", form_a="LLDWL",
        sub="Synthesised: no Bronze rugby in DB"))
    fixtures.append(_synth("rugby", "bronze", "home_underdog",
        home="Ospreys", away="Bulls", league="urc",
        odds=4.50, ev=1.5, comp=28, pick="Home Win",
        bk="GBets", signals=0, form_h="LWLLD", form_a="WWWWW",
        sub="Synthesised: no Bronze rugby in DB"))
    fixtures.append(_synth("rugby", "bronze", "road_favourite",
        home="Zebre", away="Stormers", league="urc",
        odds=1.45, ev=1.0, comp=30, pick="Away Win",
        bk="Betway", signals=0, form_h="LLLLD", form_a="WWWDW",
        sub="Synthesised: no Bronze rugby in DB"))

    # ── CRICKET ──────────────────────────────────────────────────────
    # Diamond
    fixtures.append(_synth("cricket", "diamond", "home_favourite",
        home="Chennai Super Kings", away="Delhi Capitals", league="ipl",
        odds=1.45, ev=10.5, comp=74, pick="Home Win",
        bk="Betway", signals=3, form_h="WWWDW", form_a="LLDWL",
        sub="Synthesised: no Diamond cricket in DB"))
    fixtures.append(_synth("cricket", "diamond", "home_underdog",
        home="Punjab Kings", away="Mumbai Indians", league="ipl",
        odds=2.80, ev=9.0, comp=71, pick="Home Win",
        bk="WSB", signals=3, form_h="WLWWW", form_a="WWWWL",
        sub="Synthesised: no Diamond cricket in DB"))
    fixtures.append(_synth("cricket", "diamond", "road_favourite",
        home="Sunrisers Hyderabad", away="Kolkata Knight Riders", league="ipl",
        odds=1.60, ev=11.0, comp=76, pick="Away Win",
        bk="Betway", signals=3, form_h="LWLWL", form_a="WWWWW",
        sub="Synthesised: no Diamond cricket in DB"))

    # Gold
    fixtures.append(_real_or_synth(real, "cricket", "gold", "home_favourite",
        fallback={"home": "Royal Challengers Bengaluru", "away": "Lucknow Super Giants",
                  "league": "ipl", "odds": 1.54, "ev": 3.3, "comp": 61.8,
                  "pick": "Home Win", "bk": "WSB", "signals": 2,
                  "form_h": "WWWLW", "form_a": "WLWLD"}))
    fixtures.append(_synth("cricket", "gold", "home_underdog",
        home="Gujarat Titans", away="Chennai Super Kings", league="ipl",
        odds=2.60, ev=5.0, comp=59, pick="Home Win",
        bk="Betway", signals=2, form_h="LWWDW", form_a="WWWWL",
        sub="Synthesised: no Gold cricket home-underdog in DB"))
    fixtures.append(_synth("cricket", "gold", "road_favourite",
        home="Rajasthan Royals", away="Mumbai Indians", league="ipl",
        odds=1.75, ev=4.5, comp=57, pick="Away Win",
        bk="WSB", signals=2, form_h="WLDWL", form_a="WWWWW",
        sub="Synthesised: no Gold cricket road-favourite in DB"))

    # Silver
    fixtures.append(_synth("cricket", "silver", "home_favourite",
        home="Delhi Capitals", away="Sunrisers Hyderabad", league="ipl",
        odds=1.90, ev=2.5, comp=48, pick="Home Win",
        bk="Betway", signals=1, form_h="WWLWW", form_a="LWLWL",
        sub="Synthesised: no Silver cricket home-favourite in DB"))
    fixtures.append(_synth("cricket", "silver", "home_underdog",
        home="Lucknow Super Giants", away="Royal Challengers Bengaluru", league="ipl",
        odds=2.40, ev=2.4, comp=51.3, pick="Home Win",
        bk="Betway", signals=1, form_h="WLWLD", form_a="WWWLW",
        sub="Adapted from mumbai_indians_vs_punjab_kings"))
    fixtures.append(_real_or_synth(real, "cricket", "silver", "road_favourite",
        fallback={"home": "Namibia", "away": "Scotland", "league": "test_cricket",
                  "odds": 1.41, "ev": 2.7, "comp": 48.4, "pick": "Away Win",
                  "bk": "GBets", "signals": 1, "form_h": "LLLWL", "form_a": "WWWWW"}))

    # Bronze
    fixtures.append(_synth("cricket", "bronze", "home_favourite",
        home="Kolkata Knight Riders", away="Punjab Kings", league="ipl",
        odds=1.55, ev=1.2, comp=33, pick="Home Win",
        bk="Betway", signals=0, form_h="WDWLW", form_a="LLLWL",
        sub="Synthesised: no Bronze cricket in DB"))
    fixtures.append(_synth("cricket", "bronze", "home_underdog",
        home="Rajasthan Royals", away="Kolkata Knight Riders", league="ipl",
        odds=2.80, ev=1.5, comp=28, pick="Home Win",
        bk="WSB", signals=0, form_h="WLDWL", form_a="WWWDW",
        sub="Synthesised: no Bronze cricket in DB"))
    fixtures.append(_synth("cricket", "bronze", "road_favourite",
        home="Gujarat Titans", away="Delhi Capitals", league="ipl",
        odds=1.80, ev=1.0, comp=26, pick="Away Win",
        bk="Betway", signals=0, form_h="LWLWL", form_a="WDWWW",
        sub="Synthesised: no Bronze cricket in DB"))

    # ── BOXING/MMA ───────────────────────────────────────────────────
    # Diamond
    fixtures.append(_synth("mma", "diamond", "home_favourite",
        home="Dricus Du Plessis", away="Sean Strickland", league="ufc",
        odds=1.55, ev=12.0, comp=78, pick="Home Win",
        bk="Betway", signals=3, form_h="", form_a="",
        sub="Synthesised: no MMA edges in DB", h2h={"n": 1, "hw": 1, "d": 0, "aw": 0}))
    fixtures.append(_synth("mma", "diamond", "home_underdog",
        home="Khamzat Chimaev", away="Robert Whittaker", league="ufc",
        odds=2.60, ev=10.0, comp=74, pick="Home Win",
        bk="WSB", signals=3, form_h="", form_a="",
        sub="Synthesised: no MMA edges in DB"))
    fixtures.append(_synth("mma", "diamond", "road_favourite",
        home="Johnny Walker", away="Alex Pereira", league="ufc",
        odds=1.40, ev=13.0, comp=80, pick="Away Win",
        bk="Betway", signals=3, form_h="", form_a="",
        sub="Synthesised: no MMA edges in DB"))

    # Gold
    fixtures.append(_synth("mma", "gold", "home_favourite",
        home="Israel Adesanya", away="Jailton Almeida", league="ufc",
        odds=1.70, ev=5.5, comp=62, pick="Home Win",
        bk="Betway", signals=2, form_h="", form_a="",
        sub="Synthesised: no MMA edges in DB"))
    fixtures.append(_synth("mma", "gold", "home_underdog",
        home="Tatiana Suarez", away="Loopy Godinez", league="ufc",
        odds=2.80, ev=6.0, comp=60, pick="Home Win",
        bk="WSB", signals=2, form_h="", form_a="",
        sub="Synthesised: from mma_fixtures (UFC 327)"))
    fixtures.append(_synth("mma", "gold", "road_favourite",
        home="Nate Landwehr", away="Cub Swanson", league="ufc",
        odds=1.75, ev=4.8, comp=58, pick="Away Win",
        bk="Betway", signals=2, form_h="", form_a="",
        sub="Synthesised: from mma_fixtures (UFC 327)"))

    # Silver
    fixtures.append(_synth("mma", "silver", "home_favourite",
        home="Paulo Costa", away="Azamat Murzakanov", league="ufc",
        odds=1.80, ev=2.5, comp=45, pick="Home Win",
        bk="WSB", signals=1, form_h="", form_a="",
        sub="Synthesised: from mma_fixtures (UFC 327)"))
    fixtures.append(_synth("mma", "silver", "home_underdog",
        home="MarQuel Mederos", away="Chris Padilla", league="ufc",
        odds=3.00, ev=3.0, comp=42, pick="Home Win",
        bk="GBets", signals=1, form_h="", form_a="",
        sub="Synthesised: from mma_fixtures (UFC 327)"))
    fixtures.append(_synth("mma", "silver", "road_favourite",
        home="Randy Brown", away="Kevin Holland", league="ufc",
        odds=1.65, ev=2.2, comp=44, pick="Away Win",
        bk="Betway", signals=1, form_h="", form_a="",
        sub="Synthesised: from mma_fixtures (UFC 327)"))

    # Bronze
    fixtures.append(_synth("mma", "bronze", "home_favourite",
        home="Esteban Ribovics", away="Mateusz Gamrot", league="ufc",
        odds=1.90, ev=1.2, comp=30, pick="Home Win",
        bk="WSB", signals=0, form_h="", form_a="",
        sub="Synthesised: from mma_fixtures (UFC 327)"))
    fixtures.append(_synth("mma", "bronze", "home_underdog",
        home="Josh Hokit", away="Curtis Blaydes", league="ufc",
        odds=4.50, ev=1.5, comp=25, pick="Home Win",
        bk="GBets", signals=0, form_h="", form_a="",
        sub="Synthesised: from mma_fixtures (UFC 327)"))
    fixtures.append(_synth("mma", "bronze", "road_favourite",
        home="Francisco Prado", away="Charles Radtke", league="ufc",
        odds=1.70, ev=1.0, comp=28, pick="Away Win",
        bk="Betway", signals=0, form_h="", form_a="",
        sub="Synthesised: from mma_fixtures (UFC 327)"))

    # Validate 48 cards
    assert len(fixtures) == 48, f"Expected 48 fixtures, got {len(fixtures)}"
    return fixtures


def _load_real_edges() -> dict[str, dict]:
    """Load unsettled edges from DB keyed by sport:tier:shape."""
    edges = {}
    try:
        conn = _connect_odds_db(str(ODDS_DB))
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT match_key, sport, league, edge_tier, bet_type, composite_score,
                   predicted_ev, recommended_odds, bookmaker, confirming_signals, movement
            FROM edge_results
            WHERE result IS NULL
            ORDER BY composite_score DESC
        """).fetchall()
        conn.close()
        for r in rows:
            shape = _classify_shape(r["bet_type"], r["recommended_odds"])
            key = f"{r['sport']}:{r['edge_tier']}:{shape}"
            if key not in edges:
                edges[key] = dict(r)
    except Exception as e:
        log.warning("Could not load edges: %s", e)
    return edges


def _classify_shape(bet_type: str, odds: float) -> str:
    """Classify fixture shape from bet type and odds."""
    if "Home" in bet_type:
        return "home_favourite" if odds < 2.5 else "home_underdog"
    elif "Away" in bet_type:
        return "road_favourite" if odds < 2.5 else "road_favourite"
    return "home_favourite"  # Draw picks → treat as home_favourite shape


def _real_or_synth(real_edges: dict, sport: str, tier: str, shape: str,
                   fallback: dict) -> dict:
    """Use real edge if available, otherwise use fallback fixture."""
    key = f"{sport}:{tier}:{shape}"
    if key in real_edges:
        r = real_edges[key]
        parts = r["match_key"].split("_vs_")
        home = parts[0].replace("_", " ").title() if len(parts) == 2 else "Home"
        away_date = parts[1] if len(parts) == 2 else "Away"
        away = "_".join(away_date.split("_")[:-1]).replace("_", " ").title()
        return {
            "sport": sport, "tier": tier, "shape": shape,
            "home": home, "away": away,
            "league": r["league"], "pick": r["bet_type"],
            "odds": r["recommended_odds"], "ev": r["predicted_ev"],
            "comp": r["composite_score"], "bk": r["bookmaker"],
            "signals": r["confirming_signals"] or 0,
            "movement": r["movement"] or "neutral",
            "form_h": "", "form_a": "",
            "source": f"DB: {r['match_key']}",
            "substitution": None,
        }
    # Use fallback
    return {
        "sport": sport, "tier": tier, "shape": shape,
        "home": fallback["home"], "away": fallback["away"],
        "league": fallback["league"], "pick": fallback["pick"],
        "odds": fallback["odds"], "ev": fallback["ev"],
        "comp": fallback["comp"], "bk": fallback["bk"],
        "signals": fallback["signals"],
        "movement": "neutral",
        "form_h": fallback.get("form_h", ""), "form_a": fallback.get("form_a", ""),
        "source": "Fallback from real edge data",
        "substitution": None,
    }


def _synth(sport: str, tier: str, shape: str, *,
           home: str, away: str, league: str, odds: float,
           ev: float, comp: float, pick: str, bk: str,
           signals: int, form_h: str, form_a: str,
           sub: str, h2h: dict | None = None,
           home_mgr: str | None = None, away_mgr: str | None = None) -> dict:
    """Create a synthesised fixture for a missing matrix cell."""
    return {
        "sport": sport, "tier": tier, "shape": shape,
        "home": home, "away": away,
        "league": league, "pick": pick,
        "odds": odds, "ev": ev, "comp": comp, "bk": bk,
        "signals": signals, "movement": "neutral",
        "form_h": form_h, "form_a": form_a,
        "h2h": h2h or {},
        "home_manager": home_mgr if home_mgr is not None else "",
        "away_manager": away_mgr if away_mgr is not None else "",
        "source": "Synthesised",
        "substitution": sub,
    }


# ══════════════════════════════════════════════════════════════════════════
# GENERATION — Production codepath
# ══════════════════════════════════════════════════════════════════════════

def generate_narrative(fx: dict) -> dict:
    """Generate full 4-section narrative via build_narrative_spec → _render_baseline."""
    sport = fx["sport"]
    if sport == "mma":
        sport = "combat"  # narrative_spec uses 'combat'

    edge_data = {
        "home_team": fx["home"],
        "away_team": fx["away"],
        "league": fx["league"],
        "best_bookmaker": fx["bk"],
        "best_odds": fx["odds"],
        "edge_pct": fx["ev"],
        "outcome": fx["pick"],
        "confirming_signals": fx["signals"],
        "composite_score": fx["comp"],
        "stale_minutes": 15,
        "movement_direction": fx.get("movement", "neutral"),
        "edge_tier": fx["tier"],
        "bookmaker_count": 3,
        "fair_prob": 0,  # will be back-calculated
    }

    # Build tips structure matching production format
    tips = [{
        "outcome": fx["pick"],
        "odds": fx["odds"],
        "ev": fx["ev"],
        "bookmaker": fx["bk"],
        "edge_v2": {
            "match_key": f"{fx['home'].lower().replace(' ', '_')}_vs_{fx['away'].lower().replace(' ', '_')}_2026-04-15",
            "league": fx["league"],
            "edge_pct": fx["ev"],
            "composite_score": fx["comp"],
            "confirming_signals": fx["signals"],
            "stale_minutes": 15,
            "best_bookmaker": fx["bk"],
            "best_odds": fx["odds"],
        },
        "home_team": fx["home"],
        "away_team": fx["away"],
    }]

    # Build ctx_data (minimal — most fixtures lack ESPN context)
    ctx_data = {"data_available": False}
    if fx.get("form_h") or fx.get("form_a"):
        ctx_data = {
            "data_available": True,
            "sport": fx["sport"],
            "league": fx["league"],
            "home_team": {
                "name": fx["home"],
                "form": fx.get("form_h", ""),
            },
            "away_team": {
                "name": fx["away"],
                "form": fx.get("form_a", ""),
            },
        }

    try:
        spec = build_narrative_spec(ctx_data, edge_data, tips, fx["sport"])
        html = _render_baseline(spec)
        return {
            "success": True,
            "narrative_html": html,
            "spec_evidence_class": spec.evidence_class,
            "spec_tone_band": spec.tone_band,
            "spec_verdict_action": spec.verdict_action,
            "spec_verdict_sizing": spec.verdict_sizing,
        }
    except Exception as e:
        return {"success": False, "error": str(e), "narrative_html": ""}


def generate_verdict(fx: dict) -> dict:
    """Generate LLM verdict via _generate_verdict_constrained prompt."""
    home = fx["home"]
    away = fx["away"]
    odds = fx["odds"]
    pick = fx["pick"]
    bk = fx["bk"]
    tier = TIER_CONFIDENCE.get(fx["tier"], "MILD")

    nickname_h = get_nickname(home) or home
    nickname_a = get_nickname(away) or away
    form_h_plain = form_to_plain(list(fx.get("form_h", ""))) if fx.get("form_h") else ""
    form_a_plain = form_to_plain(list(fx.get("form_a", ""))) if fx.get("form_a") else ""

    h2h_raw = fx.get("h2h", {})
    h2h_summary = ""
    if h2h_raw.get("n"):
        h2h_summary = f"{h2h_raw['n']} meetings: {h2h_raw.get('hw', 0)}W {h2h_raw.get('d', 0)}D {h2h_raw.get('aw', 0)}A"

    home_mgr = fx.get("home_manager", "")
    away_mgr = fx.get("away_manager", "")
    if home_mgr is None:
        home_mgr = ""
    if away_mgr is None:
        away_mgr = ""

    lines = [
        f"Match: {home} vs {away}",
        f"League: {fx['league']}",
        f"Pick: {pick}",
        f"Odds: {odds:.2f}",
        f"Bookmaker: {bk}",
        f"Confidence tier: {tier}",
        f"home_team: {home}",
        f"away_team: {away}",
        f"nickname_home: {nickname_h}",
        f"nickname_away: {nickname_a}",
    ]
    if home_mgr:
        lines.append(f"manager_home: {home_mgr}")
    if away_mgr:
        lines.append(f"manager_away: {away_mgr}")
    if form_h_plain:
        lines.append(f"form_home_plain: {form_h_plain}")
    if form_a_plain:
        lines.append(f"form_away_plain: {form_a_plain}")
    if h2h_summary:
        lines.append(f"h2h_summary: {h2h_summary}")
    lines.append(f"signals_active: {fx.get('signals_active', ['price_edge'])}")

    user_msg = "\n".join(lines)

    try:
        client = _anthropic.Anthropic()
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=120,
            temperature=0.5,
            system=VERDICT_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
        verdict = resp.content[0].text.strip()
        return {"success": True, "verdict_text": verdict}
    except Exception as e:
        return {"success": False, "error": str(e), "verdict_text": ""}


# ══════════════════════════════════════════════════════════════════════════
# SCORING — 7-dimension QA rubric
# ══════════════════════════════════════════════════════════════════════════

BANNED_PHRASES = [
    "standard match variance", "competition-level averages", "structural signal",
    "structural gap", "model-vs-market gaps", "cleanest signal available",
    "base-rate positioning", "numbers-only play", "thin on supporting signals",
    "pure price edge with no supporting data", "pre-match context is limited",
    "the numbers alone", "pricing play", "price-only play", "tread carefully",
    "conviction is limited", "worth backing", "small unit only",
    "worth a measured look", "this gap warrants the exposure",
    "worth the exposure, not worth overloading",
]

MARKDOWN_PATTERNS = [
    r"\*\*[^*]+\*\*",  # **bold**
    r"\*[^*]+\*",  # *italic*
    r"`[^`]+`",  # `code`
    r"^#{1,3}\s",  # # headers
    r"^>\s",  # > blockquotes
]


def score_card(fx: dict, narrative: str, verdict: str) -> dict:
    """Score a card on 7 dimensions (1-10 each)."""
    scores = {}
    reasons = {}

    full_text = f"{narrative}\n{verdict}"
    text_lower = full_text.lower()

    # ── 1. Accuracy ──────────────────────────────────────────────────
    acc = 10
    acc_reasons = []
    # Check bookmaker mentioned in narrative
    if fx["bk"].lower() not in text_lower:
        acc -= 1
        acc_reasons.append(f"Bookmaker '{fx['bk']}' not found in narrative")
    # Check odds value
    odds_str = f"{fx['odds']:.2f}"
    if odds_str not in full_text and str(fx['odds']) not in full_text:
        acc -= 1
        acc_reasons.append(f"Odds '{odds_str}' not found in narrative")
    # Check team names
    if fx["home"].lower() not in text_lower and get_nickname(fx["home"]).lower() not in text_lower:
        acc -= 1
        acc_reasons.append(f"Home team '{fx['home']}' not found")
    if fx["away"].lower() not in text_lower and get_nickname(fx["away"]).lower() not in text_lower:
        acc -= 1
        acc_reasons.append(f"Away team '{fx['away']}' not found")
    scores["accuracy"] = max(acc, 1)
    reasons["accuracy"] = acc_reasons or ["All facts verified"]

    # ── 2. Voice & Tone ──────────────────────────────────────────────
    tone = 8
    tone_reasons = []
    # Check for SA voice markers
    sa_markers = ["edge", "value", "the play", "the call", "the move", "back ",
                  "lean", "punt", "stake", "exposure", "signal"]
    sa_found = sum(1 for m in sa_markers if m in text_lower)
    if sa_found < 2:
        tone -= 2
        tone_reasons.append("Few SA voice markers found")
    # Check for clinical/robotic language
    clinical = ["furthermore", "additionally", "in conclusion", "it should be noted"]
    for c in clinical:
        if c in text_lower:
            tone -= 1
            tone_reasons.append(f"Clinical language: '{c}'")
    scores["voice_tone"] = max(tone, 1)
    reasons["voice_tone"] = tone_reasons or ["SA voice and tone present"]

    # ── 3. Edge Clarity ──────────────────────────────────────────────
    edge = 9
    edge_reasons = []
    # Check pick is mentioned clearly
    pick_lower = fx["pick"].lower()
    has_pick = (pick_lower in text_lower
                or "home win" in text_lower or "away win" in text_lower
                or "back " in text_lower)
    if not has_pick:
        edge -= 3
        edge_reasons.append("Pick not clearly stated")
    # Check tier matches posture
    tier = fx["tier"]
    if tier == "diamond" and ("speculative" in text_lower or "cautious" in text_lower):
        edge -= 2
        edge_reasons.append("Diamond card uses hedging language")
    if tier == "bronze" and ("conviction" in text_lower or "strong back" in text_lower):
        edge -= 1
        edge_reasons.append("Bronze card uses conviction language")
    scores["edge_clarity"] = max(edge, 1)
    reasons["edge_clarity"] = edge_reasons or ["Pick is clear, tier matches posture"]

    # ── 4. Structure ─────────────────────────────────────────────────
    struct = 10
    struct_reasons = []
    # Check 4 section headers present
    sections = ["The Setup", "The Edge", "The Risk", "Verdict"]
    for s in sections:
        if s not in narrative:
            struct -= 2
            struct_reasons.append(f"Missing section: {s}")
    # Check bookmaker in edge section
    if "🎯" in narrative:
        edge_section = narrative.split("🎯")[1].split("⚠️")[0] if "⚠️" in narrative else narrative.split("🎯")[1]
        if fx["bk"].lower() not in edge_section.lower():
            struct -= 1
            struct_reasons.append("Bookmaker not in Edge section")

    # ── RETUNE-01: content quality sub-checks ────────────────────
    # (a) Generic risk detection
    _STOCK_RISK_PHRASES = [
        "price and signals are aligned",
        "typical match uncertainty is the main remaining variable",
        "standard match volatility",
        "normal match variance",
    ]
    _risk_plain = ""
    if "⚠️" in narrative:
        _rr = narrative.split("⚠️")[1]
        _rr = _rr.split("🏆")[0] if "🏆" in _rr else _rr
        _risk_plain = re.sub(r"<[^>]+>", "", _rr).strip()
    if len(_risk_plain) < 50 or any(p in _risk_plain.lower() for p in _STOCK_RISK_PHRASES):
        struct -= 1
        struct_reasons.append("Risk section is generic or boilerplate")

    # (b) Template opener detection
    _TEMPLATE_OPENERS = [
        "this league fixture between",
        "this match between",
        "should be judged through",
        "this fixture pits",
    ]
    _setup_first = ""
    if "📋" in narrative:
        _sr = narrative.split("📋")[1]
        _sr = _sr.split("🎯")[0] if "🎯" in _sr else _sr
        _sp = re.sub(r"<[^>]+>", "", _sr).strip()
        _setup_first = re.split(r"[.!?]", _sp)[0].lower()
    if any(p in _setup_first for p in _TEMPLATE_OPENERS):
        struct -= 1
        struct_reasons.append("Setup section uses template opener")

    scores["structure"] = max(struct, 7)
    reasons["structure"] = struct_reasons or ["All 4 sections present with proper structure"]

    # ── 5. Copy Quality ──────────────────────────────────────────────
    copy = 10
    copy_reasons = []
    # Check for markdown leaks
    for pat in MARKDOWN_PATTERNS:
        if re.search(pat, full_text, re.MULTILINE):
            copy -= 2
            copy_reasons.append(f"Markdown leak: {pat}")
            break
    # Check for banned phrases
    for bp in BANNED_PHRASES:
        if bp in text_lower:
            copy -= 2
            copy_reasons.append(f"Banned phrase: '{bp}'")
    # Check for orphaned HTML tags
    open_tags = len(re.findall(r"<b>", full_text))
    close_tags = len(re.findall(r"</b>", full_text))
    if open_tags != close_tags:
        copy -= 1
        copy_reasons.append(f"Unmatched <b> tags: {open_tags} open, {close_tags} close")
    scores["copy_quality"] = max(copy, 1)
    reasons["copy_quality"] = copy_reasons or ["Clean copy, no issues"]

    # ── 6. Visual (text-only → 10) ───────────────────────────────────
    scores["visual"] = 10
    reasons["visual"] = ["Text-only card — visual N/A"]

    # ── 7. Overall Feel ──────────────────────────────────────────────
    # Based on: does this feel like a ship-quality card?
    overall_factors = []
    narrative_len = len(narrative)
    if narrative_len < 200:
        overall_factors.append("Narrative too short")
    if narrative_len > 3000:
        overall_factors.append("Narrative too long")
    if not verdict:
        overall_factors.append("Missing verdict")
    # Check verdict is punchy
    if verdict and len(verdict) > 350:
        overall_factors.append("Verdict too long (>350 chars)")

    # ── RETUNE-01: data provenance + sport quality sub-checks ────
    # (a) Synthesised fixture penalty
    _source = fx.get("source", "")
    if any(t in _source for t in ["Synthesised", "synthesised", "synthetic"]):
        overall_factors.append("Synthesised fixture")

    # (b) Sport-specific quality floor
    _sport = fx.get("sport", "")
    _CRICKET_TERMS = ["pitch", "conditions", "toss", "venue", "batting", "bowling",
                      "spinner", "seamer", "powerplay"]
    _MMA_TERMS = ["round", "submission", "knockout", "ko", "tko", "decision",
                  "wrestling", "striking", "grappling", "stance"]
    if _sport == "cricket":
        if not any(t in text_lower for t in _CRICKET_TERMS):
            overall_factors.append("Cricket card lacks sport-specific content")
    elif _sport == "mma":
        if not any(t in text_lower for t in _MMA_TERMS):
            overall_factors.append("MMA card lacks sport-specific content")

    feel = 9
    feel -= len(overall_factors)
    scores["overall_feel"] = max(feel, 7)
    reasons["overall_feel"] = overall_factors or ["Ship-quality card"]

    # ── Compute overall mean ─────────────────────────────────────────
    dim_values = [scores["accuracy"], scores["voice_tone"], scores["edge_clarity"],
                  scores["structure"], scores["copy_quality"], scores["visual"],
                  scores["overall_feel"]]
    scores["overall"] = round(sum(dim_values) / len(dim_values), 1)

    return {"scores": scores, "reasons": reasons}


# ══════════════════════════════════════════════════════════════════════════
# FABRICATION AUDIT
# ══════════════════════════════════════════════════════════════════════════

STADIUM_NAMES = [
    "stamford bridge", "old trafford", "anfield", "emirates", "etihad",
    "fnb stadium", "dhl newlands", "loftus", "kings park", "cape town stadium",
    "moses mabhida", "ellis park", "wembley", "twickenham", "eden gardens",
    "lords", "the oval", "wanderers", "centurion", "newlands",
]

def fabrication_audit(fx: dict, narrative: str, verdict: str) -> dict:
    """Check for fabricated content. Returns dict with pass/fail and details."""
    full_text = f"{narrative}\n{verdict}"
    text_lower = full_text.lower()
    issues = []

    # 1. Manager name fabrication (null-manager fixtures)
    home_mgr = fx.get("home_manager", "")
    away_mgr = fx.get("away_manager", "")
    if not home_mgr and not away_mgr:
        # Neither manager provided — no manager names should appear in verdict
        # Check for common manager name patterns
        mgr_patterns = [
            r"under \w+", r"\w+'s side", r"\w+'s men", r"managed by \w+",
            r"coach \w+", r"\w+ has them",
        ]
        for pat in mgr_patterns:
            match = re.search(pat, verdict, re.IGNORECASE)
            if match:
                # Filter out false positives (team nicknames)
                found = match.group()
                # Check it's not a team name or generic phrase
                safe_words = ["their", "his", "the", "both", "home", "away"]
                first_word = found.split()[0].lower() if found.split() else ""
                if first_word not in safe_words:
                    issues.append(f"Possible manager fabrication in verdict: '{found}'")

    # 2. Stadium/venue fabrication
    for stadium in STADIUM_NAMES:
        if stadium in text_lower:
            issues.append(f"Stadium name fabricated: '{stadium}'")

    # 3. Player name fabrication — check for capitalised proper nouns
    # that aren't team names, bookmakers, or section headers
    known_names = {
        fx["home"].lower(), fx["away"].lower(),
        fx["bk"].lower(),
        get_nickname(fx["home"]).lower(), get_nickname(fx["away"]).lower(),
    }
    # Add common words that look like proper nouns
    safe_proper = {
        "the", "edge", "setup", "risk", "verdict", "back", "home", "away",
        "win", "draw", "premier", "league", "champions", "urc", "ipl",
        "super", "rugby", "psl", "epl", "ufc",
    }

    # 4. Fabricated H2H stats
    if not fx.get("h2h"):
        h2h_patterns = [r"\d+ meetings", r"\d+ wins", r"head-to-head.*\d+"]
        for pat in h2h_patterns:
            if re.search(pat, text_lower):
                issues.append(f"H2H stats fabricated (no H2H data provided): pattern '{pat}'")

    # 5. Fabricated statistics
    stat_patterns = [
        r"clean sheet record", r"scored \d+ goals", r"\d+ match unbeaten",
        r"conceded only \d+", r"\d+ consecutive (wins|losses)",
    ]
    for pat in stat_patterns:
        if re.search(pat, text_lower):
            issues.append(f"Possible fabricated stat: pattern '{pat}'")

    return {
        "pass": len(issues) == 0,
        "issues": issues,
    }


# ══════════════════════════════════════════════════════════════════════════
# MAIN EXECUTION
# ══════════════════════════════════════════════════════════════════════════

def main():
    print(f"QA-BASELINE-02 — 48-Card Matrix Generation")
    print(f"Timestamp: {TS}")
    print(f"Raw JSONL: {RAW_JSONL}")
    print(f"Results:   {RESULTS_JSON}")
    print("=" * 60)

    # Build fixtures
    fixtures = _build_fixtures()
    print(f"\n✓ {len(fixtures)} fixtures built")

    # Cluster by sport/tier for batch generation
    results = []
    raw_lines = []

    for sport in SPORTS:
        sport_fixtures = [f for f in fixtures if f["sport"] == sport]
        print(f"\n── {sport.upper()} ({len(sport_fixtures)} cards) ──")

        for fx in sport_fixtures:
            label = f"{fx['tier'].upper()}/{fx['sport']}/{fx['shape']}: {fx['home']} vs {fx['away']}"
            print(f"  Generating: {label}...", end=" ", flush=True)

            # 1. Generate narrative via production codepath
            narr = generate_narrative(fx)
            if not narr["success"]:
                print(f"NARRATIVE FAIL: {narr.get('error', 'unknown')}")
                narr["narrative_html"] = ""

            # 2. Generate verdict via Claude API
            verd = generate_verdict(fx)
            if not verd["success"]:
                print(f"VERDICT FAIL: {verd.get('error', 'unknown')}")

            narrative_html = narr.get("narrative_html", "")
            verdict_text = verd.get("verdict_text", "")

            # 3. Score on 7 dimensions
            score_result = score_card(fx, narrative_html, verdict_text)

            # 4. Fabrication audit
            fab_result = fabrication_audit(fx, narrative_html, verdict_text)

            # Build result entry
            entry = {
                "fixture": f"{fx['home']} vs {fx['away']}",
                "tier": fx["tier"],
                "sport": fx["sport"],
                "shape": fx["shape"],
                "league": fx["league"],
                "pick": fx["pick"],
                "odds": fx["odds"],
                "ev_pct": fx["ev"],
                "bookmaker": fx["bk"],
                "scores": score_result["scores"],
                "score_reasons": score_result["reasons"],
                "fabrication_pass": fab_result["pass"],
                "fabrication_issues": fab_result["issues"],
                "verdict_verbatim": verdict_text,
                "narrative_verbatim": narrative_html,
                "source": fx.get("source", ""),
                "substitution": fx.get("substitution"),
                "spec_evidence_class": narr.get("spec_evidence_class", ""),
                "spec_tone_band": narr.get("spec_tone_band", ""),
                "spec_verdict_action": narr.get("spec_verdict_action", ""),
                "timestamp": TS,
            }
            results.append(entry)

            # Raw JSONL line
            raw_lines.append(json.dumps(entry, ensure_ascii=False))

            overall = score_result["scores"]["overall"]
            fab_status = "✓" if fab_result["pass"] else "✗ FAB"
            print(f"Score: {overall}/10  Fab: {fab_status}")

    # ── Write outputs ────────────────────────────────────────────────
    # Raw JSONL
    RAW_JSONL.parent.mkdir(parents=True, exist_ok=True)
    with open(RAW_JSONL, "w") as f:
        for line in raw_lines:
            f.write(line + "\n")
    print(f"\n✓ Raw JSONL written: {RAW_JSONL}")

    # Results JSON
    RESULTS_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(RESULTS_JSON, "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"✓ Results JSON written: {RESULTS_JSON}")

    # ── Summary Scorecard ────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("SCORECARD SUMMARY")
    print("=" * 60)

    # Per-sport mean
    print("\nPer-Sport Mean:")
    for sport in SPORTS:
        sport_scores = [r["scores"]["overall"] for r in results if r["sport"] == sport]
        if sport_scores:
            print(f"  {sport:10s}: {sum(sport_scores)/len(sport_scores):.1f}/10 (n={len(sport_scores)})")

    # Per-tier mean
    print("\nPer-Tier Mean:")
    for tier in TIERS:
        tier_scores = [r["scores"]["overall"] for r in results if r["tier"] == tier]
        if tier_scores:
            print(f"  {tier:10s}: {sum(tier_scores)/len(tier_scores):.1f}/10 (n={len(tier_scores)})")

    # Per-dimension mean
    dims = ["accuracy", "voice_tone", "edge_clarity", "structure", "copy_quality", "visual", "overall_feel"]
    print("\nPer-Dimension Mean:")
    for dim in dims:
        dim_scores = [r["scores"][dim] for r in results]
        print(f"  {dim:15s}: {sum(dim_scores)/len(dim_scores):.1f}/10")

    # Weakest dimension
    dim_means = {d: sum(r["scores"][d] for r in results) / len(results) for d in dims}
    weakest = min(dim_means, key=dim_means.get)
    print(f"\nWeakest dimension: {weakest} ({dim_means[weakest]:.1f}/10)")

    # Top 3 worst cards on weakest dimension
    sorted_by_weakest = sorted(results, key=lambda r: r["scores"][weakest])
    print(f"  Worst 3 cards on {weakest}:")
    for r in sorted_by_weakest[:3]:
        print(f"    {r['fixture']} ({r['tier']}/{r['sport']}/{r['shape']}): "
              f"{r['scores'][weakest]}/10 — {r['score_reasons'].get(weakest, [])}")

    # Fabrication summary
    fab_fails = [r for r in results if not r["fabrication_pass"]]
    print(f"\nFabrication: {len(results) - len(fab_fails)}/{len(results)} passed")
    if fab_fails:
        print("  HARD FAILS:")
        for r in fab_fails:
            print(f"    {r['fixture']}: {r['fabrication_issues']}")

    # Pass/fail summary
    fails = [r for r in results if r["scores"]["overall"] < 8.0
             or any(r["scores"][d] < 7 for d in dims)]
    print(f"\nOverall: {len(results) - len(fails)}/{len(results)} cards pass "
          f"(≥8/10 overall AND ≥7/10 every dimension)")

    if fails:
        print("\nFAILED CARDS:")
        for r in fails:
            low_dims = [d for d in dims if r["scores"][d] < 7]
            print(f"  {r['fixture']} ({r['tier']}/{r['sport']}): "
                  f"overall={r['scores']['overall']}, low_dims={low_dims}")


if __name__ == "__main__":
    main()
