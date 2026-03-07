"""Wave 17C — 100-Match Factual Accuracy Gauntlet.

Generates AI breakdowns for 100 matches across all supported sports.
For EVERY breakdown, verifies EVERY factual claim against real data.
Logs EVERY inaccuracy as a BUG-HAL.

Usage:
    cd /home/paulsportsza/bot && source .venv/bin/activate
    python tests/e2e_wave17c.py 2>&1 | tee /home/paulsportsza/reports/e2e-wave17c-raw.txt
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, "/home/paulsportsza")

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("wave17c")

# Suppress noisy HTTP/connection logs
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("anthropic").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

REPORT_DIR = Path("/home/paulsportsza/reports/e2e-screenshots")
REPORT_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_PATH = Path("/home/paulsportsza/reports/wave17c-e2e-results.json")

# Import bot functions directly
from bot import (
    _build_game_analysis_prompt,
    sanitize_ai_response,
    validate_sport_context,
    fact_check_output,
    _format_verified_context,
)

# Import match context fetcher
from scrapers.match_context_fetcher import get_match_context

# Claude API
import anthropic

client = anthropic.Anthropic()
MODEL = "claude-haiku-4-5-20251001"

# ── Claim Extraction Helpers ──────────────────────────────────

# Person name pattern: 2+ consecutive capitalised words
PERSON_RE = re.compile(r'\b([A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,})+)\b')

# Section headers to ignore in name detection
SECTION_HEADERS = {"the setup", "the edge", "the risk", "verdict", "bookmaker odds",
                   "sa bookmaker", "south africa", "south african", "crystal palace",
                   "aston villa", "west ham", "manchester city", "manchester united",
                   "nottingham forest", "newcastle united", "brighton hove",
                   "borussia dortmund", "real madrid", "paris saint"}

# Position claim patterns
POSITION_RE = re.compile(
    r'(?:sit|sitting|in|currently|placed|ranked|lie|lying)\s+(\d+)(?:st|nd|rd|th)',
    re.IGNORECASE,
)

# Historical claim patterns
HISTORY_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in [
        r'\bhistorically\b', r'\btraditionally\b', r'\bknown for\b', r'\bfamous for\b',
        r"\bhaven't won .* since\b", r'\blast time .* was\b', r'\bfirst time since\b',
        r'\bin recent years\b', r'\bover the past\b', r'\bdating back to\b',
        r'\bever since\b', r'\blegendary\b',
    ]
]

# Tactical/style patterns
STYLE_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in [
        r'\bcounter.?attack', r'\bpossession.?based\b', r'\bpark.?the bus\b',
        r'\bhigh press\b', r'\blow block\b', r'\btiki.?taka\b', r'\bdirect football\b',
        r'\broute one\b', r'\btotal football\b', r'\bgegenpressing\b',
        r'\bplaying style\b', r'\btactical\b', r'\bformation\b',
        r'\b4\-3\-3\b', r'\b4\-4\-2\b', r'\b3\-5\-2\b', r'\b3\-4\-3\b',
        r'\b4\-2\-3\-1\b', r'\b5\-3\-2\b', r'\b4\-1\-4\-1\b',
    ]
]

# Condition/weather patterns
CONDITION_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in [
        r'\bpitch condition', r'\bweather\b', r'\btravel fatigue\b',
        r'\bfixture congestion\b', r'\bmid.?week\b', r'\brotation\b',
        r'\bcold conditions\b', r'\bheat\b', r'\baltitude\b',
        r'\brain\b', r'\bwind\b', r'\btemperature\b',
    ]
]

# Venue/stadium patterns — only match SPECIFIC stadium/venue names, not generic usage
# Generic "home venue", "at this venue", "home ground" are acceptable (home/away context)
VENUE_RE = re.compile(
    r'(?:Old Trafford|Anfield|Stamford Bridge|Emirates Stadium|Etihad Stadium|'
    r'Camp Nou|Bernab[ée]u|San Siro|Allianz Arena|Signal Iduna Park|'
    r'Wembley|Loftus Versfeld|Ellis Park|FNB Stadium|Cape Town Stadium|'
    r'Moses Mabhida|DHL Stadium|Wanderers Stadium|Kingspark|Newlands|'
    r'Kings Park|Soccer City|Orlando Stadium|Peter Mokaba|'
    r'Mbombela Stadium|Hollywoodbets Kings)',
    re.IGNORECASE,
)

# Injury/transfer patterns — only flag AFFIRMATIVE claims, not disclaimers
# "cannot assess injury status" is a disclaimer (ok), "X is injured" is a claim (flag)
INJURY_RE = re.compile(
    r'\b(?:is\s+(?:injured|suspended|sidelined|absent|ruled out)|'
    r'has\s+(?:a\s+)?(?:hamstring|ACL|muscle|knee|ankle)\s+(?:injury|problem)|'
    r'(?:signed|transferred|loaned)\s+(?:from|to)\b|'
    r'(?:will\s+)?miss(?:es|ing)?\s+(?:the|this)\s+(?:match|game|fixture)|'
    r'fitness doubt\b)',
    re.IGNORECASE,
)

# Wrong-sport term lists (from sport_terms.py integration)
try:
    from scrapers.sport_terms import SPORT_BANNED_TERMS
except ImportError:
    SPORT_BANNED_TERMS = {}


# ── 100-Match Fixture List ─────────────────────────────────────

FIXTURES: list[dict] = []

# --- SOCCER: EPL (10) ---
_epl = [
    ("Arsenal", "Chelsea", "epl"),
    ("Liverpool", "West Ham", "epl"),
    ("Manchester City", "Nottingham Forest", "epl"),
    ("Leeds United", "Manchester City", "epl"),
    ("Manchester United", "Crystal Palace", "epl"),
    ("Fulham", "Tottenham", "epl"),
    ("Brighton", "Arsenal", "epl"),
    ("Aston Villa", "Chelsea", "epl"),
    ("Everton", "Burnley", "epl"),
    ("Bournemouth", "Sunderland", "epl"),
]
for h, a, l in _epl:
    FIXTURES.append({"home": h, "away": a, "league": l, "sport": "soccer", "category": "EPL"})

# --- SOCCER: PSL (10) ---
_psl = [
    ("Kaizer Chiefs", "Orlando Pirates", "psl"),
    ("Mamelodi Sundowns", "Sekhukhune United", "psl"),
    ("Mamelodi Sundowns", "Golden Arrows", "psl"),
    ("Stellenbosch", "AmaZulu", "psl"),
    ("Siwelele", "TS Galaxy", "psl"),
    ("Siwelele", "Stellenbosch", "psl"),
    ("Richards Bay", "Kaizer Chiefs", "psl"),
    ("Polokwane City", "Orlando Pirates", "psl"),
    ("Golden Arrows", "Chippa United", "psl"),
    ("Magesi", "Polokwane City", "psl"),
]
for h, a, l in _psl:
    FIXTURES.append({"home": h, "away": a, "league": l, "sport": "soccer", "category": "PSL"})

# --- SOCCER: Champions League (5) ---
_cl = [
    ("Real Madrid", "Benfica", "champions_league"),
    ("Juventus", "Galatasaray", "champions_league"),
    ("Paris Saint-Germain", "AS Monaco", "champions_league"),
    ("Atalanta", "Borussia Dortmund", "champions_league"),
    ("Bayern Munich", "Inter Milan", "champions_league"),
]
for h, a, l in _cl:
    FIXTURES.append({"home": h, "away": a, "league": l, "sport": "soccer", "category": "Champions League"})

# --- SOCCER: La Liga (5) ---
_laliga = [
    ("Barcelona", "Real Madrid", "la_liga"),
    ("Atletico Madrid", "Sevilla", "la_liga"),
    ("Real Sociedad", "Villarreal", "la_liga"),
    ("Athletic Bilbao", "Girona", "la_liga"),
    ("Valencia", "Real Betis", "la_liga"),
]
for h, a, l in _laliga:
    FIXTURES.append({"home": h, "away": a, "league": l, "sport": "soccer", "category": "La Liga"})

# --- SOCCER: Serie A (5) ---
_seria = [
    ("AC Milan", "Inter Milan", "serie_a"),
    ("Juventus", "Napoli", "serie_a"),
    ("Roma", "Lazio", "serie_a"),
    ("Atalanta", "Fiorentina", "serie_a"),
    ("Bologna", "Torino", "serie_a"),
]
for h, a, l in _seria:
    FIXTURES.append({"home": h, "away": a, "league": l, "sport": "soccer", "category": "Serie A"})

# --- SOCCER: Bundesliga (5) ---
_buli = [
    ("Bayern Munich", "Borussia Dortmund", "bundesliga"),
    ("RB Leipzig", "Bayer Leverkusen", "bundesliga"),
    ("VfB Stuttgart", "Eintracht Frankfurt", "bundesliga"),
    ("Wolfsburg", "Freiburg", "bundesliga"),
    ("Borussia Monchengladbach", "Union Berlin", "bundesliga"),
]
for h, a, l in _buli:
    FIXTURES.append({"home": h, "away": a, "league": l, "sport": "soccer", "category": "Bundesliga"})

# --- SOCCER: Ligue 1 (5) ---
_l1 = [
    ("Paris Saint-Germain", "Marseille", "ligue_1"),
    ("Lyon", "Monaco", "ligue_1"),
    ("Lille", "Nice", "ligue_1"),
    ("Rennes", "Lens", "ligue_1"),
    ("Strasbourg", "Toulouse", "ligue_1"),
]
for h, a, l in _l1:
    FIXTURES.append({"home": h, "away": a, "league": l, "sport": "soccer", "category": "Ligue 1"})

# --- SOCCER: Cross-league mix / Edge Cases (5) ---
_edge_soccer = [
    ("Ipswich", "Swansea City", "epl"),  # Lower-table / newly promoted
    ("Leeds United", "Norwich City", "epl"),  # Championship teams in EPL data
    ("Leicester", "Norwich City", "epl"),  # Yo-yo club
    ("Chippa United", "Marumo Gallants", "psl"),  # Smaller PSL sides
    ("Durban City", "Sekhukhune United", "psl"),  # Newly added PSL team
]
for h, a, l in _edge_soccer:
    FIXTURES.append({"home": h, "away": a, "league": l, "sport": "soccer", "category": "Soccer Edge Cases"})

# --- CRICKET (20) ---
_cricket_sa20 = [
    ("Joburg Super Kings", "Pretoria Capitals", "sa20"),
    ("Paarl Royals", "Durban Super Giants", "sa20"),
    ("MI Cape Town", "Sunrisers Eastern Cape", "sa20"),
    ("Joburg Super Kings", "MI Cape Town", "sa20"),
    ("Pretoria Capitals", "Paarl Royals", "sa20"),
    ("Sunrisers Eastern Cape", "Durban Super Giants", "sa20"),
    ("MI Cape Town", "Pretoria Capitals", "sa20"),
    ("Paarl Royals", "Joburg Super Kings", "sa20"),
    ("Durban Super Giants", "Sunrisers Eastern Cape", "sa20"),
    ("Pretoria Capitals", "MI Cape Town", "sa20"),
]
for h, a, l in _cricket_sa20:
    FIXTURES.append({"home": h, "away": a, "league": l, "sport": "cricket", "category": "SA20"})

_cricket_intl = [
    ("South Africa", "India", "test_matches"),
    ("Australia", "England", "test_matches"),
    ("New Zealand", "Pakistan", "test_matches"),
    ("West Indies", "Sri Lanka", "test_matches"),
    ("Zimbabwe", "South Africa", "test_matches"),
]
for h, a, l in _cricket_intl:
    FIXTURES.append({"home": h, "away": a, "league": l, "sport": "cricket", "category": "Cricket International"})

_cricket_nodata = [
    ("Afghanistan", "Ireland", "test_matches"),
    ("Nepal", "UAE", "test_matches"),
    ("Namibia", "Uganda", "test_matches"),
    ("Hong Kong", "Jersey", "test_matches"),
    ("Papua New Guinea", "Vanuatu", "test_matches"),
]
for h, a, l in _cricket_nodata:
    FIXTURES.append({"home": h, "away": a, "league": l, "sport": "cricket", "category": "Cricket No-Data"})

# --- RUGBY (20) ---
_urc = [
    ("Stormers", "Bulls", "urc"),
    ("Sharks", "Lions", "urc"),
    ("Stormers", "Leinster", "urc"),
    ("Bulls", "Munster", "urc"),
    ("Glasgow Warriors", "Edinburgh", "urc"),
    ("Connacht", "Scarlets", "urc"),
    ("Ospreys", "Dragons", "urc"),
    ("Benetton", "Zebre", "urc"),
]
for h, a, l in _urc:
    FIXTURES.append({"home": h, "away": a, "league": l, "sport": "rugby", "category": "URC"})

_six_nations = [
    ("England", "France", "six_nations"),
    ("Ireland", "Scotland", "six_nations"),
    ("Wales", "Italy", "six_nations"),
    ("France", "Ireland", "six_nations"),
    ("Scotland", "England", "six_nations"),
    ("Italy", "France", "six_nations"),
]
for h, a, l in _six_nations:
    FIXTURES.append({"home": h, "away": a, "league": l, "sport": "rugby", "category": "Six Nations"})

_super_rugby = [
    ("Crusaders", "Blues", "super_rugby"),
    ("Hurricanes", "Chiefs", "super_rugby"),
    ("Brumbies", "Waratahs", "super_rugby"),
    ("Highlanders", "Moana Pasifika", "super_rugby"),
    ("Queensland Reds", "Western Force", "super_rugby"),
    ("Fijian Drua", "Crusaders", "super_rugby"),
]
for h, a, l in _super_rugby:
    FIXTURES.append({"home": h, "away": a, "league": l, "sport": "rugby", "category": "Super Rugby"})

# --- F1 (5) ---
_f1 = [
    ("Bahrain Grand Prix", "F1 2026", "f1"),
    ("Saudi Arabian Grand Prix", "F1 2026", "f1"),
    ("Australian Grand Prix", "F1 2026", "f1"),
    ("Pre-Season Testing", "F1 2026", "f1"),
    ("Japanese Grand Prix", "F1 2026", "f1"),
]
for race, season, l in _f1:
    FIXTURES.append({"home": race, "away": season, "league": l, "sport": "f1", "category": "F1"})

# --- DELIBERATELY DIFFICULT (5) ---
_difficult = [
    # Famous manager trap — Man Utd (post-Ten Hag era)
    {"home": "Manchester United", "away": "Liverpool", "league": "epl", "sport": "soccer",
     "category": "Difficult", "trap": "Famous manager — will Claude name a manager?"},
    # Famous manager trap — Chelsea (revolving door)
    {"home": "Chelsea", "away": "Newcastle United", "league": "epl", "sport": "soccer",
     "category": "Difficult", "trap": "Famous manager — Chelsea's manager carousel"},
    # Recently transferred star player
    {"home": "Barcelona", "away": "Real Madrid", "league": "la_liga", "sport": "soccer",
     "category": "Difficult", "trap": "Star players who may have moved — will Claude name them?"},
    # Newly promoted/relegated team
    {"home": "Southampton", "away": "Fulham", "league": "epl", "sport": "soccer",
     "category": "Difficult", "trap": "Relegated team — will Claude cite old Premier League position?"},
    # Obscure matchup with zero data
    {"home": "Baroka FC", "away": "Black Leopards", "league": "psl", "sport": "soccer",
     "category": "Difficult", "trap": "Obscure matchup — pure degradation test, zero data expected"},
]
FIXTURES.extend(_difficult)

assert len(FIXTURES) == 100, f"Expected 100 fixtures, got {len(FIXTURES)}"

# ── Odds Data Simulator ───────────────────────────────────────

def _build_fake_odds(home: str, away: str) -> str:
    """Build a plausible odds data string for the Claude prompt."""
    import random
    # Generate plausible odds
    r = random.random()
    if r < 0.4:
        # Home favourite
        home_odds = round(random.uniform(1.4, 2.0), 2)
        draw_odds = round(random.uniform(3.2, 4.5), 2)
        away_odds = round(random.uniform(3.5, 7.0), 2)
    elif r < 0.7:
        # Balanced
        home_odds = round(random.uniform(2.3, 3.0), 2)
        draw_odds = round(random.uniform(3.0, 3.5), 2)
        away_odds = round(random.uniform(2.5, 3.2), 2)
    else:
        # Away favourite
        home_odds = round(random.uniform(3.5, 6.0), 2)
        draw_odds = round(random.uniform(3.2, 4.0), 2)
        away_odds = round(random.uniform(1.5, 2.2), 2)
    bookmakers = ["Hollywoodbets", "Betway", "GBets", "Supabets", "Sportingbet"]
    bk = random.choice(bookmakers)
    return (
        f"ODDS DATA:\n"
        f"  {home}: {home_odds} ({bk})\n"
        f"  Draw: {draw_odds} ({bk})\n"
        f"  {away}: {away_odds} ({bk})\n"
    )


# ── Claim Extraction ──────────────────────────────────────────

def extract_all_claims(text: str, verified_ctx: dict, sport: str) -> dict:
    """Extract and categorise ALL factual claims from AI text."""
    claims = {
        "position_claims": [],
        "form_claims": [],
        "stat_claims": [],
        "person_names": [],
        "historical_claims": [],
        "tactical_claims": [],
        "venue_claims": [],
        "condition_claims": [],
        "injury_claims": [],
        "wrong_sport_terms": [],
        "total": 0,
    }

    # Build verified names set
    verified_names: set[str] = set()
    if verified_ctx and verified_ctx.get("data_available"):
        for side in ("home_team", "away_team"):
            team = verified_ctx.get(side, {})
            name = team.get("name", "")
            if name:
                verified_names.add(name.lower())
                for word in name.split():
                    if len(word) > 3:
                        verified_names.add(word.lower())
        for game in verified_ctx.get("head_to_head", []):
            for key in ("home", "away"):
                h2h_name = game.get(key, "")
                if h2h_name:
                    verified_names.add(h2h_name.lower())

    for line in text.split('\n'):
        if not line.strip():
            continue

        # 1. Position claims
        for m in POSITION_RE.finditer(line):
            claims["position_claims"].append({
                "claimed": int(m.group(1)),
                "context": line.strip()[:120],
            })

        # 2. Form claims: "won X of last Y", "unbeaten in X"
        for m in re.finditer(r'(?:won|lost|drawn)\s+(\d+)\s+of\s+(?:their\s+)?last\s+(\d+)',
                             line, re.IGNORECASE):
            claims["form_claims"].append({"value": m.group(0), "context": line.strip()[:120]})
        for m in re.finditer(r'unbeaten\s+in\s+(?:their\s+)?(?:last\s+)?(\d+)',
                             line, re.IGNORECASE):
            claims["form_claims"].append({"value": m.group(0), "context": line.strip()[:120]})
        # Form strings like WWDLW
        for m in re.finditer(r'\b([WDLP]{4,})\b', line):
            claims["form_claims"].append({"value": m.group(1), "context": line.strip()[:120]})

        # 3. Statistical claims
        for m in re.finditer(r'(\d+\.?\d*)\s+goals?\s+(?:per\s+game|in\s+\d+\s+games?)',
                             line, re.IGNORECASE):
            claims["stat_claims"].append({"value": m.group(0), "context": line.strip()[:120]})
        for m in re.finditer(r'(\d+)\s+clean\s+sheets?', line, re.IGNORECASE):
            claims["stat_claims"].append({"value": m.group(0), "context": line.strip()[:120]})
        for m in re.finditer(r'(\d+)\s+points?\b', line, re.IGNORECASE):
            # Only count if it looks like a league points claim
            if any(w in line.lower() for w in ("table", "league", "position", "standing", "games")):
                claims["stat_claims"].append({"value": m.group(0), "context": line.strip()[:120]})

        # 4. Person names (unverified)
        for name in PERSON_RE.findall(line):
            name_lower = name.lower()
            if name_lower in verified_names:
                continue
            if any(h in name_lower for h in SECTION_HEADERS):
                continue
            # Check if any part is a known team fragment
            parts = name_lower.split()
            if all(p in verified_names for p in parts if len(p) > 3):
                continue
            claims["person_names"].append({"name": name, "context": line.strip()[:120]})

        # 5. Historical claims
        for pat in HISTORY_PATTERNS:
            if pat.search(line):
                claims["historical_claims"].append({"pattern": pat.pattern, "context": line.strip()[:120]})
                break

        # 6. Tactical/style claims
        for pat in STYLE_PATTERNS:
            if pat.search(line):
                claims["tactical_claims"].append({"pattern": pat.pattern, "context": line.strip()[:120]})
                break

        # 7. Venue/stadium claims
        if VENUE_RE.search(line):
            claims["venue_claims"].append({"context": line.strip()[:120]})

        # 8. Condition/weather claims
        for pat in CONDITION_PATTERNS:
            if pat.search(line):
                claims["condition_claims"].append({"pattern": pat.pattern, "context": line.strip()[:120]})
                break

        # 9. Injury/transfer claims
        if INJURY_RE.search(line):
            claims["injury_claims"].append({"context": line.strip()[:120]})

        # 10. Wrong-sport terms
        banned = SPORT_BANNED_TERMS.get(sport, {}).get("banned", [])
        for term in banned:
            if re.search(rf'\b{re.escape(term)}\b', line, re.IGNORECASE):
                claims["wrong_sport_terms"].append({"term": term, "context": line.strip()[:120]})

    claims["total"] = sum(len(v) for v in claims.values() if isinstance(v, list))
    return claims


# ── Claim Verification ────────────────────────────────────────

def verify_claims(claims: dict, verified_ctx: dict, raw_text: str) -> list[dict]:
    """Verify extracted claims against verified context. Returns list of BUG-HALs."""
    bugs = []

    verified_positions: dict[str, int] = {}
    if verified_ctx and verified_ctx.get("data_available"):
        for side in ("home_team", "away_team"):
            team = verified_ctx.get(side, {})
            name = team.get("name", "")
            pos = team.get("league_position")
            if name and pos is not None:
                verified_positions[name.lower()] = pos

    # Category A: Wrong facts
    for pc in claims["position_claims"]:
        ctx_lower = pc["context"].lower()
        for team_name, real_pos in verified_positions.items():
            if team_name in ctx_lower and pc["claimed"] != real_pos:
                bugs.append({
                    "category": "A",
                    "type": "Wrong league position",
                    "detail": f"Claimed {pc['claimed']}, verified {real_pos} for {team_name}",
                    "context": pc["context"],
                })

    # Category B: Unverified facts
    for pn in claims["person_names"]:
        bugs.append({
            "category": "B",
            "type": "Unverified person name",
            "detail": f"Name '{pn['name']}' not in VERIFIED_DATA",
            "context": pn["context"],
        })

    for hc in claims["historical_claims"]:
        bugs.append({
            "category": "B",
            "type": "Historical claim",
            "detail": f"Pattern: {hc['pattern']}",
            "context": hc["context"],
        })

    for tc in claims["tactical_claims"]:
        bugs.append({
            "category": "B",
            "type": "Tactical/style description",
            "detail": f"Pattern: {tc['pattern']}",
            "context": tc["context"],
        })

    for vc in claims["venue_claims"]:
        bugs.append({
            "category": "B",
            "type": "Venue/stadium reference",
            "detail": "Venue mentioned not in VERIFIED_DATA",
            "context": vc["context"],
        })

    for cc in claims["condition_claims"]:
        bugs.append({
            "category": "B",
            "type": "Condition/weather reference",
            "detail": f"Pattern: {cc['pattern']}",
            "context": cc["context"],
        })

    for ic in claims["injury_claims"]:
        bugs.append({
            "category": "B",
            "type": "Injury/transfer reference",
            "detail": "Injury/transfer claim not in VERIFIED_DATA",
            "context": ic["context"],
        })

    # Category C: Wrong sport context
    for wst in claims["wrong_sport_terms"]:
        bugs.append({
            "category": "C",
            "type": "Wrong sport term",
            "detail": f"Banned term '{wst['term']}' found",
            "context": wst["context"],
        })

    # Category D: Graceful degradation failure
    has_verified = verified_ctx and verified_ctx.get("data_available", False)
    if not has_verified:
        # Check that no factual claims were made without verified data
        if claims["position_claims"]:
            bugs.append({
                "category": "D",
                "type": "Position claim without verified data",
                "detail": f"{len(claims['position_claims'])} position claims made with no VERIFIED_DATA",
                "context": claims["position_claims"][0]["context"],
            })
        if claims["form_claims"]:
            bugs.append({
                "category": "D",
                "type": "Form claim without verified data",
                "detail": f"{len(claims['form_claims'])} form claims made with no VERIFIED_DATA",
                "context": claims["form_claims"][0]["context"],
            })
        if claims["stat_claims"]:
            bugs.append({
                "category": "D",
                "type": "Stat claim without verified data",
                "detail": f"{len(claims['stat_claims'])} stat claims made with no VERIFIED_DATA",
                "context": claims["stat_claims"][0]["context"],
            })

    return bugs


# ── Generate + Verify One Match ───────────────────────────────

async def test_one_match(idx: int, fixture: dict) -> dict:
    """Generate AI breakdown for one match and verify all claims."""
    match_id = f"{fixture['category'].replace(' ', '-')}-{idx+1:03d}"
    home = fixture["home"]
    away = fixture["away"]
    league = fixture["league"]
    sport = fixture["sport"]
    trap = fixture.get("trap", "")

    match_label = f"{home} vs {away}"
    log.info("  [%d/100] %s — %s/%s%s", idx + 1, match_label, sport, league,
             f" (TRAP: {trap})" if trap else "")

    result = {
        "match_id": match_id,
        "match": match_label,
        "sport": sport,
        "league": league,
        "category": fixture["category"],
        "trap": trap,
        "has_verified_data": False,
        "raw_response": "",
        "processed_response": "",
        "claims_extracted": 0,
        "claims_verified_correct": 0,
        "claims_incorrect": 0,
        "unverified_claims": 0,
        "wrong_sport_terms": 0,
        "bug_hals": [],
        "status": "CLEAN",
        "error": "",
    }

    try:
        # Step 1: Fetch verified context
        ctx_data = {}
        if sport == "f1":
            # F1 uses race name, not team vs team
            ctx_data = {"data_available": False, "sport": "f1"}
        else:
            try:
                ctx_data = await get_match_context(
                    home_team=home, away_team=away, league=league, sport=sport,
                )
            except Exception as e:
                ctx_data = {"data_available": False, "error": str(e)}

        result["has_verified_data"] = ctx_data.get("data_available", False)

        # Step 2: Build prompt
        system_prompt = _build_game_analysis_prompt(sport)
        verified_block = _format_verified_context(ctx_data)
        odds_block = _build_fake_odds(home, away)

        if sport == "f1":
            user_msg = f"Analyse the {home} ({away}).\n\n{odds_block}"
        else:
            user_msg = f"Analyse {home} vs {away} ({league}).\n\n"
            if verified_block:
                user_msg += verified_block + "\n\n"
            user_msg += odds_block

        # Step 3: Call Claude Haiku
        response = client.messages.create(
            model=MODEL,
            max_tokens=800,
            system=system_prompt,
            messages=[{"role": "user", "content": user_msg}],
        )
        raw = response.content[0].text
        result["raw_response"] = raw

        # Step 4: Run post-processing pipeline (same as bot)
        processed = sanitize_ai_response(raw)
        processed = validate_sport_context(processed, sport)
        # Guard against None head_to_head (real bot bug — logged as BUG-CODE-001)
        if ctx_data and ctx_data.get("head_to_head") is None:
            ctx_data["head_to_head"] = []
        processed = fact_check_output(processed, ctx_data)
        result["processed_response"] = processed

        # Step 5: Extract claims from PROCESSED output (what the user would see)
        claims = extract_all_claims(processed, ctx_data, sport)
        result["claims_extracted"] = claims["total"]

        # Step 6: Verify claims
        bugs = verify_claims(claims, ctx_data, processed)

        if bugs:
            result["bug_hals"] = bugs
            result["claims_incorrect"] = sum(1 for b in bugs if b["category"] == "A")
            result["unverified_claims"] = sum(1 for b in bugs if b["category"] == "B")
            result["wrong_sport_terms"] = sum(1 for b in bugs if b["category"] == "C")
            result["status"] = "FAIL"
            for b in bugs:
                log.warning("    BUG-HAL [%s]: %s — %s", b["category"], b["type"], b["detail"][:80])
        else:
            result["claims_verified_correct"] = claims["total"]
            result["status"] = "CLEAN"

    except Exception as e:
        result["error"] = f"{type(e).__name__}: {str(e)}"
        result["status"] = "ERROR"
        log.error("    ERROR: %s", result["error"])
        traceback.print_exc()

    # Save per-match capture
    safe_id = match_id.replace(":", "_").replace("/", "_")
    capture = (
        f"MATCH-ID: {match_id}\n"
        f"Match: {match_label}\n"
        f"Sport: {sport} | League: {league}\n"
        f"Category: {fixture['category']}\n"
        f"Trap: {trap or 'None'}\n"
        f"Verified data: {result['has_verified_data']}\n"
        f"Claims extracted: {result['claims_extracted']}\n"
        f"BUG-HALs: {len(result['bug_hals'])}\n"
        f"Status: {'✅ CLEAN' if result['status'] == 'CLEAN' else '❌ FAIL' if result['status'] == 'FAIL' else '⚠️ ERROR'}\n"
        f"\n--- RAW RESPONSE ---\n{result['raw_response']}\n"
        f"\n--- PROCESSED RESPONSE ---\n{result['processed_response']}\n"
    )
    if result["bug_hals"]:
        capture += "\n--- BUG-HALs ---\n"
        for b in result["bug_hals"]:
            capture += f"  [{b['category']}] {b['type']}: {b['detail']}\n    Context: {b['context']}\n"
    (REPORT_DIR / f"17c-{safe_id}.txt").write_text(capture, encoding="utf-8")

    return result


# ── Main ──────────────────────────────────────────────────────

async def run_gauntlet():
    log.info("=" * 70)
    log.info("WAVE 17C: 100-MATCH FACTUAL ACCURACY GAUNTLET")
    log.info("=" * 70)
    log.info("Model: %s", MODEL)
    log.info("Fixtures: %d", len(FIXTURES))
    log.info("")

    all_results: list[dict] = []
    start_time = time.time()

    # Process in batches of 5 for progress visibility
    for batch_start in range(0, len(FIXTURES), 5):
        batch = FIXTURES[batch_start:batch_start + 5]
        batch_label = f"Batch {batch_start // 5 + 1}/{(len(FIXTURES) + 4) // 5}"
        log.info("--- %s (%s) ---", batch_label, batch[0]["category"])

        tasks = [test_one_match(batch_start + i, f) for i, f in enumerate(batch)]
        batch_results = await asyncio.gather(*tasks, return_exceptions=True)

        for r in batch_results:
            if isinstance(r, Exception):
                log.error("  Batch exception: %s", r)
                all_results.append({
                    "match_id": "ERROR", "status": "ERROR",
                    "error": str(r), "bug_hals": [],
                })
            else:
                all_results.append(r)

        # Brief pause between batches to avoid rate limits
        await asyncio.sleep(1)

    elapsed = time.time() - start_time
    log.info("")
    log.info("=" * 70)
    log.info("GAUNTLET COMPLETE — %.1f seconds (%.1f per match)", elapsed, elapsed / len(FIXTURES))
    log.info("=" * 70)

    # ── Summary ────────────────────────────────────────────────
    total = len(all_results)
    clean = sum(1 for r in all_results if r["status"] == "CLEAN")
    failed = sum(1 for r in all_results if r["status"] == "FAIL")
    errors = sum(1 for r in all_results if r["status"] == "ERROR")

    all_bugs = []
    for r in all_results:
        for b in r.get("bug_hals", []):
            b["match_id"] = r.get("match_id", "?")
            b["match"] = r.get("match", "?")
            b["sport"] = r.get("sport", "?")
            b["league"] = r.get("league", "?")
            all_bugs.append(b)

    cat_a = sum(1 for b in all_bugs if b["category"] == "A")
    cat_b = sum(1 for b in all_bugs if b["category"] == "B")
    cat_c = sum(1 for b in all_bugs if b["category"] == "C")
    cat_d = sum(1 for b in all_bugs if b["category"] == "D")

    log.info("")
    log.info("RESULTS SUMMARY:")
    log.info("  Total matches: %d", total)
    log.info("  Clean: %d", clean)
    log.info("  Failed: %d", failed)
    log.info("  Errors: %d", errors)
    log.info("")
    log.info("BUG-HAL BREAKDOWN:")
    log.info("  Category A (wrong facts): %d", cat_a)
    log.info("  Category B (unverified): %d", cat_b)
    log.info("  Category C (wrong sport): %d", cat_c)
    log.info("  Category D (degradation): %d", cat_d)
    log.info("  TOTAL BUG-HALs: %d", len(all_bugs))

    # Per-sport breakdown
    log.info("")
    log.info("PER-SPORT BREAKDOWN:")
    sports = {}
    for r in all_results:
        cat = r.get("category", "Unknown")
        if cat not in sports:
            sports[cat] = {"total": 0, "clean": 0, "failed": 0, "bugs": 0}
        sports[cat]["total"] += 1
        if r["status"] == "CLEAN":
            sports[cat]["clean"] += 1
        elif r["status"] == "FAIL":
            sports[cat]["failed"] += 1
        sports[cat]["bugs"] += len(r.get("bug_hals", []))

    for cat, s in sorted(sports.items()):
        pct = (s["clean"] / s["total"] * 100) if s["total"] > 0 else 0
        log.info("  %-25s %d matches, %d clean, %d failed, %d bugs (%.0f%% pass)",
                 cat, s["total"], s["clean"], s["failed"], s["bugs"], pct)

    # List all BUG-HALs
    if all_bugs:
        log.info("")
        log.info("BUG-HAL REGISTRY:")
        for i, b in enumerate(all_bugs, 1):
            log.info("  BUG-HAL-%03d [%s]: %s — %s", i, b["category"], b["match"], b["type"])
            log.info("    Detail: %s", b["detail"][:100])
            log.info("    Context: %s", b["context"][:100])
    else:
        log.info("")
        log.info("BUG-HAL REGISTRY: EMPTY — Zero hallucinations detected!")

    # Pattern analysis
    if all_bugs:
        log.info("")
        log.info("PATTERN ANALYSIS:")
        type_counts: dict[str, int] = {}
        for b in all_bugs:
            type_counts[b["type"]] = type_counts.get(b["type"], 0) + 1
        for t, c in sorted(type_counts.items(), key=lambda x: -x[1]):
            log.info("  %s: %d occurrences", t, c)

    # Save JSON results
    summary = {
        "wave": "17C",
        "total": total,
        "clean": clean,
        "failed": failed,
        "errors": errors,
        "bug_hals_total": len(all_bugs),
        "cat_a": cat_a,
        "cat_b": cat_b,
        "cat_c": cat_c,
        "cat_d": cat_d,
        "per_sport": sports,
        "bugs": all_bugs,
        "results": all_results,
        "elapsed_seconds": elapsed,
    }
    RESULTS_PATH.write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    log.info("")
    log.info("Results: %s", RESULTS_PATH)

    # Verdict
    log.info("")
    if len(all_bugs) == 0 and errors == 0:
        log.info("🟢 VERDICT: LAUNCH READY — 100/100 clean, zero BUG-HALs")
    elif len(all_bugs) == 0 and errors > 0:
        log.info("🟡 VERDICT: NEEDS REVIEW — %d errors but zero BUG-HALs in completed matches", errors)
    else:
        log.info("🔴 VERDICT: NEEDS FIXES — %d BUG-HALs found across %d matches", len(all_bugs), failed)


if __name__ == "__main__":
    asyncio.run(run_gauntlet())
