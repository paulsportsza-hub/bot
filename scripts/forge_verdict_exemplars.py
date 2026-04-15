#!/usr/bin/env python3
"""FORGE-VERDICT-EXEMPLARS-01 — Force-generate 300-char candidate verdicts for Paul to rate.

Harness: selects 32 real fixtures from odds.db, generates 2 candidates each via
_generate_verdict_constrained() prompt (standalone — no bot import), validates,
and outputs to JSON + Notion.

Usage:
    cd /home/paulsportsza/bot
    .venv/bin/python scripts/forge_verdict_exemplars.py
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sys
import time
import urllib.request
from datetime import date
from pathlib import Path

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
BOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BOT_DIR))
sys.path.insert(0, str(BOT_DIR.parent / "scrapers"))

# Load .env
_env_path = BOT_DIR / ".env"
if _env_path.exists():
    for _line in _env_path.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            k, _, v = _line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("forge_verdicts")

# ---------------------------------------------------------------------------
# Imports (safe — no bot.py)
# ---------------------------------------------------------------------------
from scrapers.db_connect import connect_odds_db  # noqa: E402

try:
    from team_data import get_nickname, get_manager, form_to_plain  # noqa: E402
except ImportError:
    def get_nickname(n): return n
    def get_manager(n): return ""
    def form_to_plain(lst, team_name=""): return ""

try:
    import anthropic as _anthropic  # noqa: E402
except ImportError:
    log.error("anthropic SDK not installed — aborting")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ODDS_DB = "/home/paulsportsza/scrapers/odds.db"

LENGTH_BANDS = {
    "diamond": (200, 280),
    "gold":    (180, 260),
    "silver":  (140, 220),
    "bronze":  (120, 200),
}
CEILING = 300

TEMPERATURE = {"diamond": 0.7, "gold": 0.7, "silver": 0.5, "bronze": 0.5}

_VERDICT_BLACKLIST = [
    "home advantage", "away advantage",
    "historically", "tradition", "traditionally",
    "derby", "rivalry",
    "big game", "big match",
    "relegation battle", "title race",
    "form suggests", "expected to",
    "known for", "famous for",
    "ev edge", "ev%", "expected value",
    "the home side", "the away side",
    "measured lean", "keep stakes controlled", "stay proportionate",
    "factor that in", "factor this in", "small stake",
    "proceed with caution", "worth monitoring", "keep an eye on",
    "keep stakes", "stake manageable", "size your stake", "limit your stake",
]

NOTION_TOKEN = os.environ.get("NOTION_TOKEN", "")
NOTION_TASK_HUB = "31ed9048-d73c-814e-a179-ccd2cf35df1d"
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
OUTPUT_JSON = BOT_DIR / "data" / "_candidate-pool-01.json"

# ---------------------------------------------------------------------------
# System prompt (replicated from _generate_verdict_constrained in bot.py)
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = (
    "You are a sharp SA sports pundit writing a short verdict for a betting edge card.\n"
    "You sound like a knowledgeable South African sports fan — direct, confident, warm, no waffle.\n"
    "You are NOT a risk-disclaimer machine. You are someone who watched the form, checked the numbers, and knows the call.\n"
    "\n"
    "Data you receive:\n"
    "- home_team / away_team: official team names\n"
    "- nickname_home / nickname_away: fan nicknames — USE THESE in your verdict instead of the full name where they exist\n"
    "- manager_home / manager_away: current manager surnames — USE THESE when they add personality. SKIP if empty.\n"
    "- form_home_plain / form_away_plain: plain English form summaries — USE THESE directly. Never restate as letter strings.\n"
    "- pick: what we are backing\n"
    "- odds: the odds on offer\n"
    "- bookmaker: the specific bookie — always name them\n"
    "- confidence_tier: MILD / SOLID / STRONG / MAX — this is how strong the edge is\n"
    "- h2h_summary: meeting history — translate into plain English\n"
    "- signals_active: list of edge signals firing — mention 1-2 if they add flavour\n"
    "\n"
    "Rules:\n"
    "- 2 sentences maximum, then one final call line\n"
    "- Sentence 1: the pick + bookmaker + why (form or H2H)\n"
    "- Sentence 2: the supporting evidence — ONE supporting point only\n"
    "- Final line: always \"Back [team/outcome].\" — short, punchy, standalone\n"
    "- Use nicknames and manager names to create personality — only when provided\n"
    "- NEVER mention EV% — it means nothing to most fans\n"
    "- NEVER use abbreviations: no H2H, no EV, no WLLLW form strings\n"
    "- NEVER hedge: no 'could', 'might', 'possibly', 'if form holds'\n"
    "- Name the bookmaker — always\n"
    "- Active voice, present tense\n"
    "- NO hallucination: only use the exact fields provided.\n"
    "\n"
    "ABSOLUTELY FORBIDDEN:\n"
    "- Stadium or venue names — not in our database\n"
    "- Player names — not verified in our system\n"
    "- Any statistic not present in the exact verified fields passed to you\n"
    "- Tactical descriptions\n"
    "- Historical context beyond form/h2h_summary\n"
    "- Injury information unless it appears in signals_active\n"
    "- Staking advice of any kind: 'small stake', 'keep stakes controlled', etc.\n"
    "- Hedge language: 'worth monitoring', 'keep an eye on', 'factor that in'\n"
    "\n"
    "SA VOICE — NON-NEGOTIABLE:\n"
    "Write like you're telling a mate at the braai why this bet is sharp. "
    "Use team nicknames (Gunners, Amakhosi, Canes, Bucs, Chiefs, Pirates) when provided. "
    "Lead with the DATA. End with a clear call: 'Back X.' / 'Take the draw.' / 'Ride with X.'\n"
    "\n"
    "If you cannot find something in the verified fields, DO NOT write it.\n"
    "\n"
    "HANDLING MISSING DATA FIELDS:\n"
    "If form_home_plain, form_away_plain, or h2h_summary say 'Form data unavailable' or 'H2H data unavailable', "
    "work with the signals and odds data you DO have. Do not explain or apologise for missing data.\n"
    "\n"
    "Examples of good verdicts:\n"
    "\"Draw money at WSB is the play. Maresca's Chelsea are in terrible form — four losses from their last five — "
    "but Amorim's United don't come here and run riot. Back the draw.\"\n"
    "\n"
    "\"Amakhosi at home is the call. Chiefs have won four of their last five and the Bucs are in poor nick on the road. Back Amakhosi.\"\n"
    "\n"
    "\"Blues away is the move. They've won four from five and the line's been shifting their way all week. Back the Blues.\"\n"
    "\n"
    "Examples of bad verdicts (never write like this):\n"
    "\"The H2H record and EV% of +8.8% suggest value on the draw.\"\n"
    "\"Chelsea's WLLLL run indicates poor form.\"\n"
    "\"This could be a value bet if the SOLID confidence tier holds.\"\n"
    "\"A measured lean: keep stakes controlled.\"\n"
)

# ---------------------------------------------------------------------------
# Fixture matrix: 32 fixtures across tiers
# ---------------------------------------------------------------------------
# Format: (match_id, sport, league, assigned_tier, outcome, approx_odds, bookmaker, ev, confirming_signals)
# Sourced from edge_results (verified) and odds_snapshots (synthesized for Diamond tier)
FIXTURE_MATRIX = [
    # ── DIAMOND (8) ──────────────────────────────────────────────────────────
    ("arsenal_vs_sporting_cp_2026-04-15",      "soccer", "champions_league", "diamond", "Home Win", 1.55, "hollywoodbets", 4.2, 3),
    ("liverpool_vs_paris_saint_germain_2026-04-15", "soccer", "champions_league", "diamond", "Home Win", 1.8, "betway",    5.1, 3),
    ("atletico_madrid_vs_barcelona_2026-04-15", "soccer", "champions_league", "diamond", "Away Win", 2.2, "wsb",          6.3, 3),
    ("brighton_vs_chelsea_2026-04-21",          "soccer", "epl",              "diamond", "Away Win", 2.7, "wsb",          2.3, 2),
    ("manchester_city_vs_arsenal_2026-04-19",   "soccer", "epl",              "diamond", "Away Win", 4.25, "wsb",        10.1, 1),
    ("wolves_vs_tottenham_2026-04-25",          "soccer", "epl",              "diamond", "Home Win", 3.65, "wsb",         4.3, 2),
    ("ulster_vs_leinster_2026-04-17",           "rugby",  "urc",              "diamond", "Away Win", 2.21, "gbets",       1.9, 2),
    ("royal_challengers_bengaluru_vs_lucknow_super_giants_2026-04-15", "cricket", "ipl", "diamond", "Home Win", 1.51, "wsb", 1.3, 2),
    # ── GOLD (12) ────────────────────────────────────────────────────────────
    ("everton_vs_liverpool_2026-04-19",         "soccer", "epl",              "gold",    "Home Win", 3.25, "sportingbet", 3.2, 1),
    ("brentford_vs_fulham_2026-04-18",          "soccer", "epl",              "gold",    "Home Win", 2.16, "supabets",    1.6, 2),
    ("tottenham_vs_brighton_2026-04-18",        "soccer", "epl",              "gold",    "Away Win", 2.46, "supabets",    1.7, 2),
    ("newcastle_vs_bournemouth_2026-04-18",     "soccer", "epl",              "gold",    "Away Win", 3.7,  "sportingbet", 2.8, 2),
    ("west_ham_vs_everton_2026-04-25",          "soccer", "epl",              "gold",    "Away Win", 2.75, "wsb",         1.9, 2),
    ("fulham_vs_aston_villa_2026-04-25",        "soccer", "epl",              "gold",    "Away Win", 2.6,  "wsb",         3.6, 1),
    ("orlando_pirates_vs_amazulu_2026-04-18",   "soccer", "psl",              "gold",    "Home Win", 1.5,  "hollywoodbets", 6.8, 1),
    ("chiefs_vs_hurricanes_2026-04-12",         "rugby",  "super_rugby",      "gold",    "Home Win", 1.7,  "wsb",         2.1, 2),
    ("western_force_vs_crusaders_2026-04-12",   "rugby",  "super_rugby",      "gold",    "Away Win", 1.55, "betway",      1.8, 2),
    ("blues_vs_highlanders_2026-04-12",         "rugby",  "super_rugby",      "gold",    "Home Win", 1.65, "gbets",       2.0, 2),
    ("mumbai_indians_vs_punjab_kings_2026-04-16", "cricket", "ipl",           "gold",    "Away Win", 2.2,  "betway",      2.4, 1),
    ("dragons_vs_bulls_2026-04-17",             "rugby",  "urc",              "gold",    "Away Win", 1.2,  "gbets",       1.5, 2),
    # ── SILVER (8) ───────────────────────────────────────────────────────────
    ("manchester_united_vs_brentford_2026-04-27", "soccer", "epl",            "silver",  "Away Win", 4.5,  "wsb",         5.2, 1),
    ("lions_vs_glasgow_2026-04-18",             "rugby",  "urc",              "silver",  "Away Win", 4.25, "wsb",         2.0, 1),
    ("benetton_treviso_vs_munster_2026-04-18",  "rugby",  "urc",              "silver",  "Away Win", 1.85, "gbets",       1.5, 1),
    ("ospreys_vs_sharks_2026-04-18",            "rugby",  "urc",              "silver",  "Away Win", 1.8,  "wsb",         1.8, 1),
    ("scarlets_vs_cardiff_2026-04-18",          "rugby",  "urc",              "silver",  "Away Win", 2.5,  "gbets",       1.5, 1),
    ("liverpool_vs_crystal_palace_2026-04-25",  "soccer", "epl",              "silver",  "Away Win", 5.9,  "supersportbet", 3.3, 0),
    ("polokwane_city_vs_kaizer_chiefs_2026-04-15", "soccer", "psl",           "silver",  "Away Win", 2.1,  "hollywoodbets", 1.8, 1),
    ("stellenbosch_vs_sekhukhune_united_2026-04-15", "soccer", "psl",         "silver",  "Away Win", 2.9,  "gbets",       2.0, 1),
    # ── BRONZE (4) ───────────────────────────────────────────────────────────
    ("arsenal_vs_newcastle_2026-04-25",         "soccer", "epl",              "bronze",  "Away Win", 6.0,  "wsb",         2.6, 1),
    ("magesi_vs_kaizer_chiefs_2026-04-15",      "soccer", "psl",              "bronze",  "Home Win", 4.8,  "gbets",       3.3, 1),
    ("ts_galaxy_vs_richards_bay_2026-04-15",    "soccer", "psl",              "bronze",  "Home Win", 2.1,  "hollywoodbets", 1.5, 0),
    ("manchester_city_vs_southampton_2026-04-19", "soccer", "epl",            "bronze",  "Home Win", 1.25, "wsb",         1.0, 0),
]

# ---------------------------------------------------------------------------
# Evidence gathering
# ---------------------------------------------------------------------------

def _parse_teams(match_id: str) -> tuple[str, str]:
    """Parse home/away from match_id: home_vs_away_date or home_vs_away."""
    parts = match_id.rsplit("_", 1)
    core = parts[0] if len(parts) > 1 and len(parts[1]) == 10 else match_id
    if "_vs_" in core:
        h, a = core.split("_vs_", 1)
    else:
        tokens = core.split("_")
        half = len(tokens) // 2
        h = "_".join(tokens[:half])
        a = "_".join(tokens[half:])
    return h.strip("_"), a.strip("_")


def _title(s: str) -> str:
    return s.replace("_", " ").title()


def _get_injuries(c, home_raw: str, away_raw: str) -> dict:
    """Get verified injury data from team_injuries."""
    home_disp = _title(home_raw)
    away_disp = _title(away_raw)
    try:
        c.execute(
            """SELECT team, player_name, injury_type, injury_status
               FROM team_injuries
               WHERE team IN (?, ?)
               AND injury_status NOT IN ('Missing Fixture', 'Unknown')
               AND fetched_at > datetime('now', '-48 hours')""",
            (home_disp, away_disp),
        )
        rows = c.fetchall()
        result = {}
        for team, player, inj_type, status in rows:
            result.setdefault(team, []).append(f"{player} ({inj_type}/{status})")
        return result
    except Exception:
        return {}


def _get_line_movement(c, match_id: str) -> str | None:
    """Get line movement narrative from line_movements."""
    try:
        c.execute(
            """SELECT direction, narrative FROM line_movements
               WHERE match_id = ? ORDER BY detected_at DESC LIMIT 1""",
            (match_id,),
        )
        row = c.fetchone()
        return row[0] if row else None
    except Exception:
        return None


def _get_h2h(c, match_id: str) -> dict:
    """Try to get H2H from narrative_cache context_json."""
    try:
        c.execute(
            "SELECT context_json FROM narrative_cache WHERE match_id = ? AND context_json IS NOT NULL LIMIT 1",
            (match_id,),
        )
        row = c.fetchone()
        if row:
            ctx = json.loads(row[0])
            h2h = ctx.get("head_to_head") or {}
            return h2h if isinstance(h2h, dict) else {}
    except Exception:
        pass
    return {}


def _get_best_bookmaker_odds(c, match_id: str, outcome: str) -> tuple[float, str]:
    """Get best odds + bookmaker from odds_latest for the target outcome."""
    col = {"Home Win": "home_odds", "Draw": "draw_odds", "Away Win": "away_odds"}.get(outcome, "home_odds")
    try:
        c.execute(
            f"""SELECT bookmaker, {col} FROM odds_latest
                WHERE match_id = ? AND market_type = '1x2' AND {col} IS NOT NULL
                ORDER BY {col} DESC LIMIT 1""",
            (match_id,),
        )
        row = c.fetchone()
        if row:
            return float(row[1]), row[0]
    except Exception:
        pass
    return 0.0, ""


def _build_allowed_data(c, fixture: tuple) -> dict:
    """Build the allowed_data dict for _generate_verdict_constrained."""
    match_id, sport, league, tier, outcome, approx_odds, bk_fallback, ev, confirming = fixture

    home_raw, away_raw = _parse_teams(match_id)
    home_disp = _title(home_raw)
    away_disp = _title(away_raw)

    # Try to get live best odds
    live_odds, live_bk = _get_bookmaker_odds_smart(c, match_id, outcome, bk_fallback, approx_odds)

    # Injuries
    injuries = _get_injuries(c, home_raw, away_raw)
    home_inj = injuries.get(home_disp, [])
    away_inj = injuries.get(away_disp, [])

    # Line movement
    movement = _get_line_movement(c, match_id)

    # H2H
    h2h = _get_h2h(c, match_id)

    # H2H summary string
    h2h_summary = ""
    if h2h.get("n"):
        h2h_summary = (
            f"{h2h['n']} meetings: {h2h.get('hw',0)}W {h2h.get('d',0)}D {h2h.get('aw',0)}A"
        )

    # Signals
    signals_active = []
    if movement:
        signals_active.append(f"line_movement:{movement}")
    if confirming >= 2:
        signals_active.append("price_edge")
    if home_inj:
        signals_active.append("home_injury")
    if away_inj:
        signals_active.append("away_injury")

    # Confidence tier from confirming signals + ev
    if confirming >= 3 or (ev > 8 and confirming >= 2):
        conf_tier = "MAX"
    elif confirming >= 2 or ev > 4:
        conf_tier = "STRONG"
    elif confirming >= 1 or ev > 2:
        conf_tier = "SOLID"
    else:
        conf_tier = "MILD"

    # Nicknames + managers
    nick_home = get_nickname(home_disp)
    nick_away = get_nickname(away_disp)
    mgr_home = get_manager(home_disp)
    mgr_away = get_manager(away_disp)

    return {
        "matchup": f"{home_disp} vs {away_disp}",
        "home_team": home_disp,
        "away_team": away_disp,
        "pick": outcome,
        "odds": live_odds if live_odds else approx_odds,
        "bookmaker": live_bk if live_bk else bk_fallback,
        "ev": ev,
        "league": league,
        "league_key": league,
        "sport": sport,
        "confidence_tier": conf_tier,
        "home_form": None,  # ESPN not available in harness — form_to_plain will handle
        "away_form": None,
        "h2h": h2h,
        "h2h_summary": h2h_summary or "H2H data unavailable",
        "injuries": {"home": home_inj, "away": away_inj} if (home_inj or away_inj) else None,
        "home_injuries": home_inj or None,
        "away_injuries": away_inj or None,
        "line_movement": movement,
        "tipster": None,
        "momentum": {"confirming_signals": confirming},
        "signals": {s: 1 for s in signals_active},
        "price_edge_bps": int(ev * 100),
        "market_consensus": None,
    }, nick_home, nick_away, mgr_home, mgr_away


def _get_bookmaker_odds_smart(c, match_id, outcome, fallback_bk, fallback_odds):
    """Try odds_latest first, then fall back to fixture defaults."""
    odds, bk = _get_best_bookmaker_odds(c, match_id, outcome)
    if odds > 0:
        return odds, bk
    return fallback_odds, fallback_bk


# ---------------------------------------------------------------------------
# Verdict generation + validation
# ---------------------------------------------------------------------------

def _trim_to_last_sentence(text: str, max_chars: int = 300) -> str:
    if not text:
        return ""
    text = text.strip()
    if len(text) > max_chars:
        text = text[:max_chars]
    last = max(text.rfind("."), text.rfind("!"), text.rfind("?"))
    if last >= 20:
        return text[: last + 1].strip()
    last_dash = max(text.rfind("\u2014"), text.rfind("\u2013"))
    if last_dash > 60:
        return text[:last_dash].rstrip() + ".."
    return text.rsplit(" ", 1)[0].rstrip(",. ").strip()


def _validate(text: str, tier: str, allowed_data: dict) -> tuple[bool, list[str]]:
    """10-item validator. Returns (passed, list_of_fails)."""
    fails = []
    lo = text.lower()

    # 1. Minimum length
    lo_band, _ = LENGTH_BANDS[tier]
    if len(text) < lo_band:
        fails.append(f"too_short: {len(text)} < {lo_band}")

    # 2. Maximum length
    if len(text) > CEILING:
        fails.append(f"too_long: {len(text)} > {CEILING}")

    # 3. Blacklisted phrases
    for phrase in _VERDICT_BLACKLIST:
        if phrase in lo:
            fails.append(f"blacklist:{phrase}")
            break

    # 4. No echo markers (field names leaking)
    _echo = ["form_home_plain", "form_away_plain", "h2h_summary", "signals_active",
             "nickname_home", "confidence_tier:", "home_team:", "away_team:"]
    if any(m in lo for m in _echo):
        fails.append("field_name_leak")

    # 5. Complete sentence (ends with punctuation)
    if not re.search(r"[.!?]$", text.strip()):
        fails.append("no_terminal_punct")

    # 6. Names the bookmaker
    bk = (allowed_data.get("bookmaker") or "").lower()
    if bk and bk not in lo:
        fails.append("missing_bookmaker")

    # 7. Contains pick/team reference
    home_raw = (allowed_data.get("home_team") or "").split()[0].lower()
    away_raw = (allowed_data.get("away_team") or "").split()[0].lower()
    pick = (allowed_data.get("pick") or "").lower()
    if not any(t in lo for t in [home_raw, away_raw, pick, "draw", "home", "away"]):
        fails.append("no_pick_reference")

    # 8. No staking advice
    _stake_phrases = ["small stake", "large stake", "stake", "wager responsibly",
                      "keep stakes", "size your", "limit your stake"]
    if any(p in lo for p in _stake_phrases):
        fails.append("staking_advice")

    # 9. No disclaimer / hedge
    _hedges = ["could", "might", "possibly", "if form holds", "worth monitoring",
               "factor that in", "proceed with caution"]
    if any(h in lo for h in _hedges):
        fails.append("hedge_language")

    # 10. Does not start with "I" (LLM refusing)
    if text.strip().startswith("I ") or text.strip().startswith("I\u2019"):
        fails.append("starts_with_I")

    return (len(fails) == 0), fails


def _build_prompt_lines(allowed_data: dict, nick_home: str, nick_away: str,
                         mgr_home: str, mgr_away: str) -> str:
    """Build the user message lines for the API call."""
    ad = allowed_data
    lines: list[str] = []
    if ad.get("matchup"):
        lines.append(f"Match: {ad['matchup']}")
    if ad.get("league"):
        lines.append(f"League: {ad['league']}")
    if ad.get("pick"):
        lines.append(f"Pick: {ad['pick']}")
    odds = ad.get("odds") or 0
    if odds:
        lines.append(f"Odds: {float(odds):.2f}")
    if ad.get("bookmaker"):
        lines.append(f"Bookmaker: {ad['bookmaker']}")
    lines.append(f"Confidence tier: {ad.get('confidence_tier', 'MILD')}")
    lines.append(f"home_team: {ad.get('home_team', '')}")
    lines.append(f"away_team: {ad.get('away_team', '')}")
    lines.append(f"nickname_home: {nick_home}")
    lines.append(f"nickname_away: {nick_away}")
    if mgr_home:
        lines.append(f"manager_home: {mgr_home}")
    if mgr_away:
        lines.append(f"manager_away: {mgr_away}")

    # Form: try form_to_plain from empty list (no ESPN in harness)
    form_home = "Form data unavailable"
    form_away = "Form data unavailable"
    lines.append(f"form_home_plain: {form_home}")
    lines.append(f"form_away_plain: {form_away}")

    h2h_s = ad.get("h2h_summary") or "H2H data unavailable"
    lines.append(f"h2h_summary: {h2h_s}")

    sigs = ad.get("signals") or {}
    active_sigs = [k for k, v in sigs.items() if v and v > 0]
    if active_sigs:
        lines.append(f"signals_active: {', '.join(active_sigs)}")

    return "\n".join(lines)


def _generate_candidate(client, allowed_data: dict, nick_home: str, nick_away: str,
                         mgr_home: str, mgr_away: str, tier: str) -> str:
    """Call Anthropic API and return raw text."""
    user_msg = _build_prompt_lines(allowed_data, nick_home, nick_away, mgr_home, mgr_away)
    temp = TEMPERATURE[tier]
    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=220,
        temperature=temp,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
    )
    text = ""
    for block in resp.content:
        if hasattr(block, "text") and block.text:
            text += block.text
    return _trim_to_last_sentence(text.strip(), max_chars=CEILING)


def _build_evidence_summary(allowed_data: dict, injuries: dict) -> list[str]:
    """Build 3-5 bullet evidence summary for Notion output."""
    bullets = []
    odds = allowed_data.get("odds") or 0
    ev = allowed_data.get("ev") or 0
    if odds:
        bullets.append(f"Odds: {float(odds):.2f} @ {allowed_data.get('bookmaker','?')}, EV +{ev:.1f}%")
    if allowed_data.get("h2h_summary") and "unavailable" not in allowed_data["h2h_summary"].lower():
        bullets.append(f"H2H: {allowed_data['h2h_summary']}")
    if allowed_data.get("line_movement"):
        bullets.append(f"Line movement: {allowed_data['line_movement']}")
    sigs = allowed_data.get("signals") or {}
    active = [k for k, v in sigs.items() if v and v > 0]
    if active:
        bullets.append(f"Signals: {', '.join(active)}")
    inj_home = (injuries.get("home") or []) if injuries else []
    inj_away = (injuries.get("away") or []) if injuries else []
    if inj_home:
        bullets.append(f"Home injuries: {', '.join(inj_home[:2])}")
    if inj_away:
        bullets.append(f"Away injuries: {', '.join(inj_away[:2])}")
    return bullets or ["No additional evidence signals"]


# ---------------------------------------------------------------------------
# Notion delivery
# ---------------------------------------------------------------------------

def _notion_request(method: str, path: str, body: dict | None = None):
    url = f"https://api.notion.com/v1{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {NOTION_TOKEN}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except Exception as exc:
        log.error("Notion API error: %s", exc)
        return {}


def _create_notion_page(candidates_by_tier: dict, stats: dict) -> str:
    """Create the Notion candidate page under Task Hub."""
    if not NOTION_TOKEN:
        log.warning("No NOTION_TOKEN — skipping Notion page creation")
        return ""

    total = stats.get("total", 0)
    rejected = stats.get("rejected", 0)
    reject_rate = f"{rejected}/{total+rejected}" if total + rejected else "0/0"

    # Build page blocks
    blocks = [
        {"object": "block", "type": "heading_2",
         "heading_2": {"rich_text": [{"type": "text", "text": {"content": f"FORGE-VERDICT-EXEMPLARS-01 — {total} Candidates"}}]}},
        {"object": "block", "type": "paragraph",
         "paragraph": {"rich_text": [{"type": "text", "text": {"content":
             f"Generated: {date.today().isoformat()} | Validator reject rate: {reject_rate} | Sport mix: {stats.get('sport_mix','')}"
         }}]}},
        {"object": "block", "type": "divider", "divider": {}},
    ]

    tier_emoji = {"diamond": "💎", "gold": "🥇", "silver": "🥈", "bronze": "🥉"}

    for tier in ["diamond", "gold", "silver", "bronze"]:
        tier_candidates = candidates_by_tier.get(tier, [])
        if not tier_candidates:
            continue

        blocks.append({
            "object": "block", "type": "heading_2",
            "heading_2": {"rich_text": [{"type": "text", "text": {"content":
                f"{tier_emoji[tier]} {tier.upper()} EDGE — {len(tier_candidates)} candidates"
            }}]},
        })

        lo_band, hi_band = LENGTH_BANDS[tier]
        blocks.append({
            "object": "block", "type": "paragraph",
            "paragraph": {"rich_text": [{"type": "text", "text": {"content":
                f"Length band: {lo_band}–{hi_band} chars | Temperature: {TEMPERATURE[tier]}"
            }}]},
        })

        for i, cand in enumerate(tier_candidates, 1):
            fixture = cand["fixture"]
            home_raw, away_raw = _parse_teams(fixture)
            fixture_display = f"{_title(home_raw)} vs {_title(away_raw)}"
            ad = cand["allowed_data"]

            # Numbered item block
            blocks.append({
                "object": "block", "type": "heading_3",
                "heading_3": {"rich_text": [{"type": "text", "text": {"content":
                    f"{i}. {fixture_display}"
                }}]},
            })

            # Fixture metadata
            meta = (
                f"Pick: {ad.get('pick','')} @ {float(ad.get('odds',0)):.2f} ({ad.get('bookmaker','')}) | "
                f"Tier: {tier.upper()} | {cand['char_count']} chars"
            )
            blocks.append({
                "object": "block", "type": "paragraph",
                "paragraph": {"rich_text": [{"type": "text", "text": {"content": meta}}]},
            })

            # Verdict text (highlighted)
            blocks.append({
                "object": "block", "type": "quote",
                "quote": {"rich_text": [{"type": "text", "text": {"content": cand["verdict"]}}]},
            })

            # Evidence summary
            for bullet in cand["evidence_bullets"]:
                blocks.append({
                    "object": "block", "type": "bulleted_list_item",
                    "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": bullet}}]},
                })

            # Validator result
            val_status = "✅ PASS" if cand["passed"] else f"⚠️ FAIL: {', '.join(cand['fails'])}"
            blocks.append({
                "object": "block", "type": "paragraph",
                "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"Validator: {val_status}"}}]},
            })
            blocks.append({"object": "block", "type": "divider", "divider": {}})

    # Notion limit: max 100 blocks per request. Split if needed.
    page_body = {
        "parent": {"type": "page_id", "page_id": NOTION_TASK_HUB},
        "properties": {
            "title": {"title": [{"text": {"content": "FORGE-VERDICT-EXEMPLARS-01 — Candidates for rating"}}]}
        },
        "children": blocks[:100],
    }

    result = _notion_request("POST", "/pages", page_body)
    page_url = result.get("url", "")

    # If there are more than 100 blocks, append them
    if len(blocks) > 100:
        page_id = result.get("id", "")
        if page_id:
            for chunk_start in range(100, len(blocks), 90):
                chunk = blocks[chunk_start:chunk_start + 90]
                _notion_request("PATCH", f"/blocks/{page_id}/children", {"children": chunk})
                time.sleep(0.5)

    return page_url


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    log.info("FORGE-VERDICT-EXEMPLARS-01 starting — %d fixtures in matrix", len(FIXTURE_MATRIX))

    if not ANTHROPIC_API_KEY:
        log.error("ANTHROPIC_API_KEY not set — aborting")
        sys.exit(1)

    client = _anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    conn = connect_odds_db(ODDS_DB)
    c = conn.cursor()

    candidates_by_tier: dict[str, list] = {"diamond": [], "gold": [], "silver": [], "bronze": []}
    total_generated = 0
    total_rejected = 0
    sport_counts: dict[str, int] = {}

    for fixture_tuple in FIXTURE_MATRIX:
        match_id, sport, league, tier, outcome, approx_odds, bk, ev, confirming = fixture_tuple
        home_raw, away_raw = _parse_teams(match_id)
        log.info("  Processing %s (%s/%s)", match_id, tier, sport)

        sport_counts[sport] = sport_counts.get(sport, 0) + 1

        try:
            allowed_data, nick_home, nick_away, mgr_home, mgr_away = _build_allowed_data(c, fixture_tuple)
            injuries_raw = {"home": allowed_data.get("home_injuries") or [], "away": allowed_data.get("away_injuries") or []}
            evidence_bullets = _build_evidence_summary(allowed_data, injuries_raw)
        except Exception as exc:
            log.warning("    Failed to build allowed_data for %s: %s", match_id, exc)
            continue

        # Generate 2 candidates per fixture
        for cand_idx in range(2):
            attempts = 0
            verdict = ""
            passed = False
            fails: list[str] = []

            while attempts < 3:  # up to 2 retries
                attempts += 1
                try:
                    raw = _generate_candidate(
                        client, allowed_data, nick_home, nick_away, mgr_home, mgr_away, tier
                    )
                    if not raw:
                        log.warning("      [%d/%d] Empty verdict", cand_idx+1, attempts)
                        continue

                    ok, fails = _validate(raw, tier, allowed_data)
                    if ok:
                        verdict = raw
                        passed = True
                        break
                    else:
                        log.info("      [%d/%d] Validator fail: %s | '%s'", cand_idx+1, attempts, fails, raw[:60])
                        verdict = raw  # keep last attempt even if failed
                except Exception as exc:
                    log.warning("      API error attempt %d: %s", attempts, exc)
                    time.sleep(2)

            total_generated += 1
            if not passed:
                total_rejected += 1

            if verdict:
                candidates_by_tier[tier].append({
                    "fixture": match_id,
                    "sport": sport,
                    "league": league,
                    "tier": tier,
                    "candidate_idx": cand_idx + 1,
                    "verdict": verdict,
                    "char_count": len(verdict),
                    "passed": passed,
                    "fails": fails if not passed else [],
                    "allowed_data": {
                        k: v for k, v in allowed_data.items()
                        if k in ("matchup", "pick", "odds", "bookmaker", "confidence_tier",
                                 "h2h_summary", "home_injuries", "away_injuries", "line_movement", "ev")
                    },
                    "evidence_bullets": evidence_bullets,
                })
                log.info(
                    "      ✓ Candidate %d: %d chars | pass=%s | '%s'",
                    cand_idx + 1, len(verdict), passed, verdict[:60]
                )

    conn.close()

    # Stats
    total_candidates = sum(len(v) for v in candidates_by_tier.values())
    sport_mix_str = ", ".join(f"{sport}:{cnt}" for sport, cnt in sorted(sport_counts.items()))
    stats = {
        "total": total_candidates,
        "rejected": total_rejected,
        "reject_rate": f"{total_rejected}/{total_generated}",
        "by_tier": {tier: len(cands) for tier, cands in candidates_by_tier.items()},
        "sport_mix": sport_mix_str,
    }

    log.info("=== GENERATION COMPLETE ===")
    log.info("Total candidates: %d | Rejected: %d | Reject rate: %s",
             total_candidates, total_rejected, stats["reject_rate"])
    for tier, cands in candidates_by_tier.items():
        log.info("  %s: %d candidates", tier.upper(), len(cands))
    log.info("Sport mix: %s", sport_mix_str)

    # Write JSON output
    output = {
        "generated_at": date.today().isoformat(),
        "stats": stats,
        "candidates_by_tier": candidates_by_tier,
    }
    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(json.dumps(output, indent=2, ensure_ascii=False))
    log.info("JSON output: %s", OUTPUT_JSON)

    # Push to Notion
    notion_url = _create_notion_page(candidates_by_tier, stats)
    if notion_url:
        log.info("Notion page: %s", notion_url)
    else:
        log.warning("Notion page creation failed or skipped")

    # Print taster: best 3 per tier
    print("\n" + "=" * 70)
    print("FORGE-VERDICT-EXEMPLARS-01 — Taster (best 3 per tier)")
    print("=" * 70)
    for tier in ["diamond", "gold", "silver", "bronze"]:
        cands = [c for c in candidates_by_tier.get(tier, []) if c["passed"]]
        if not cands:
            cands = candidates_by_tier.get(tier, [])
        print(f"\n{'=' * 30} {tier.upper()} {'=' * 30}")
        for c in cands[:3]:
            home_raw, away_raw = _parse_teams(c["fixture"])
            print(f"  {_title(home_raw)} vs {_title(away_raw)} | {c['char_count']} chars")
            print(f"  \"{c['verdict']}\"")
            print()

    print(f"\nNotion URL: {notion_url or 'Not created'}")
    print(f"JSON: {OUTPUT_JSON}")
    return notion_url, stats


if __name__ == "__main__":
    main()
