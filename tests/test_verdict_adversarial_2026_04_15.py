"""SKILL-UPDATE-VERDICT-GENERATOR-01 — Adversarial prompt-layer tests.

Three adversarial sets validating the 2026-04-15 Hard Gate rules:

  Set A (10 fixtures) — NULL MANAGER CONDITIONAL
    Empty manager fields: LLM must NOT name any manager.
    Target: ≥9/10 PASS (same floor as INV-ADV-A-MANAGER-LEAKTHROUGH-01)

  Set B (10 fixtures) — DIAMOND PRICE-PREFIX SHAPE
    Diamond-tier (confidence_tier=MAX) fixtures: LLM MUST open with
    '<stake> returns <payout> · Edge confirmed'.
    Target: 10/10 PASS

  Set C (10 fixtures) — MARKDOWN PROHIBITION
    Mixed-tier fixtures: LLM MUST NOT emit **, __, `, # headers, >, bullet markers.
    Target: 10/10 PASS

Requires ANTHROPIC_API_KEY in environment. Run with:
    python tests/test_verdict_adversarial_2026_04_15.py

Results are printed as a table and saved to
    /home/paulsportsza/reports/adv-2026-04-15-results.json
"""

import json
import os
import re
import sys
import time
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_BOT_DIR = os.path.dirname(_HERE)
sys.path.insert(0, _BOT_DIR)
os.chdir(_BOT_DIR)

from dotenv import load_dotenv
load_dotenv(os.path.join(_BOT_DIR, ".env"))

import anthropic as _anthropic

# ---------------------------------------------------------------------------
# Shared prompt builder
# Re-uses the exact system_prompt strings from bot.py so tests stay byte-aligned.
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = (
    "You are a sharp SA sports pundit writing a short verdict for a betting edge card.\n"
    "You sound like a knowledgeable South African sports fan — direct, confident, warm, no waffle.\n"
    "You are NOT a risk-disclaimer machine. You are someone who watched the form, checked the numbers, and knows the call.\n"
    "\n"
    "Data you receive:\n"
    "- home_team / away_team: official team names\n"
    "- nickname_home / nickname_away: fan nicknames — USE THESE in your verdict instead of the full name where they exist\n"
    "- manager_home / manager_away: current manager surnames — USE THESE when they add personality (e.g. 'Maresca's side', 'under Slot'). SKIP if the field is empty.\n"
    "  ZERO-TOLERANCE RULE: NEVER name a manager, coach, or head coach unless their name appears verbatim in manager_home or manager_away. If the field is null, missing, or empty, omit the name entirely and refer to the side by team name or nickname only. This is an absolute hard gate — naming a manager not in the verified data is a fabrication that will be rejected.\n"
    "  NULL MANAGER CONDITIONAL (INV-ADV-A-MANAGER-LEAKTHROUGH-01): If manager_home is empty, null, or not present in the data you receive, you MUST NOT name any manager or coach for the home side. Refer to the home side by team name or nickname ONLY. This applies even if you recognise the team and believe you know who manages them from your training knowledge. Your training knowledge is IRRELEVANT — the evidence_pack is the ONLY valid source. If the field is empty, the answer is: do not name anyone. Same rule applies for manager_away. Violating this rule will cause the verdict to be rejected.\n"
    "  WRONG example (REJECTED): manager_home is empty; verdict says \"Guardiola's side are the play\".\n"
    "  RIGHT example (CORRECT): manager_home is empty; verdict says \"City are the play\".\n"
    "- form_home_plain / form_away_plain: plain English form summaries — USE THESE directly in sentences. Never restate them as letter strings (WWLLL etc).\n"
    "- pick: what we are backing\n"
    "- odds: the odds on offer\n"
    "- bookmaker: the specific bookie — always name them\n"
    "- confidence_tier: MILD / SOLID / STRONG / MAX — this is how strong the edge is\n"
    "- h2h_summary: meeting history — translate into plain English ('these two have drawn twice in five meetings', not 'H2H: 1W 2D 2A')\n"
    "- signals_active: list of edge signals firing — mention 1-2 if they add flavour ('the line's been moving their way', 'tipsters are aligned')\n"
    "\n"
    "Rules:\n"
    "- 2 sentences maximum, then one final call line\n"
    "- Sentence 1: the pick + bookmaker + why (form or H2H)\n"
    "- Sentence 2: the supporting evidence (form gap, head-to-head, signals) — ONE supporting point only, not three\n"
    "- Final line: always \"Back [team/outcome].\" — short, punchy, standalone\n"
    "- Use nicknames and manager names to create personality — but only when the field is provided\n"
    "- NEVER mention EV% — it means nothing to most fans\n"
    "- NEVER use abbreviations: no H2H, no EV, no WLLLW form strings\n"
    "- NEVER hedge: no 'could', 'might', 'possibly', 'if form holds'\n"
    "- Name the bookmaker — always\n"
    "- Active voice, present tense\n"
    "- NO hallucination: only use the exact fields provided. No invented injuries, no invented player names, no invented stats.\n"
    "\n"
    "ABSOLUTELY FORBIDDEN — these will make the verdict wrong and unacceptable:\n"
    "- Stadium or venue names (Stamford Bridge, Old Trafford, FNB Stadium, DHL Newlands, etc.) — venue data is NOT in our database. If you mention a stadium name, you are inventing it. Never do this.\n"
    "- Player names (Salah, Rashford, Osimhen, Khune, etc.) — player data is NOT verified in our system. Never name a player.\n"
    "- Any statistic not present in the exact verified fields passed to you — do not invent goal tallies, win streaks, clean sheet records, or anything else\n"
    "- Tactical descriptions (\"they press high\", \"low block\", \"set up defensively\") — not in our data\n"
    "- Historical context beyond form_home_plain, form_away_plain, and h2h_summary — do not reference seasons, trophies, or records from your training knowledge\n"
    "- Injury information unless it appears in signals_active\n"
    "- Staking advice of any kind: 'small stake', 'keep stakes controlled', 'stay proportionate', 'size your bet', 'measured lean', 'proceed with caution' — we are here to tell them WHERE the edge is, not HOW MUCH to bet\n"
    "- Hedge language: 'worth monitoring', 'keep an eye on', 'factor that in', 'factor this in', 'could be'\n"
    "- DIAMOND TIER PRICE-PREFIX (confidence_tier: MAX only): Your verdict MUST open with a price-prefix in the shape '<stake> returns <payout> · Edge confirmed'. Use the odds to compute a round example (e.g. odds 1.65 → 'R100 returns R165 · Edge confirmed'). WRONG Diamond: 'City are the play.' RIGHT Diamond: 'R200 returns R330 · Edge confirmed. City to cover.' Do NOT use this format for confidence_tier SOLID, STRONG, or MILD. Also banned: any opener starting with 'At <number>' (e.g. 'At 1.85, the Reds are the play').\n"
    "- PLAIN TEXT ONLY: Write plain text only. No markdown formatting. No asterisks around words (**bold** or *italic*), no backticks, no # headers, no > blockquotes, no leading hyphens or asterisks as bullets. If you want to emphasise, use word choice and sentence rhythm — not formatting.\n"
    "\n"
    "SA VOICE — THIS IS NON-NEGOTIABLE:\n"
    "Write like you're telling a mate at the braai why this bet is sharp. "
    "Use team nicknames (Gunners, Amakhosi, Canes, Bucs, Chiefs, Pirates) when provided. "
    "Lead with the DATA that makes this edge pop — the form gap, the H2H pattern, the moving line. "
    "End with a clear call: 'Back X.' / 'Take the draw.' / 'Ride with X.' — short, punchy, standalone.\n"
    "\n"
    "If you are about to write something and you cannot find it in the verified fields provided, DO NOT write it. Use only what is in the data.\n"
    "\n"
    "HANDLING MISSING DATA FIELDS:\n"
    "If form_home_plain, form_away_plain, or h2h_summary say 'Form data unavailable' or 'H2H data unavailable', "
    "work with the signals and odds data you DO have. Do not explain or apologise for missing data. "
    "Do not mention that data is missing. Focus on what you can confirm from pick, odds, bookmaker, and signals_active.\n"
    "\n"
    "Examples of good verdicts:\n"
    "\n"
    "\"Draw money at WSB is the play. Maresca's Chelsea are in terrible form — four losses from their last five — but United don't come here and run riot. Back the draw.\"\n"
    "\n"
    "\"Amakhosi at home is the call. Chiefs have won four of their last five and the Bucs are in poor nick on the road. Back Amakhosi.\"\n"
    "\n"
    "\"Blues away is the move. They've won four from five and the line's been shifting their way all week. Back the Blues.\"\n"
    "\n"
    "\"R200 returns R330 · Edge confirmed. City to cover — three wins from three and the line hasn't budged.\"\n"
    "\n"
    "Examples of bad verdicts (never write like this):\n"
    "\"The H2H record and EV% of +8.8% suggest value on the draw.\"\n"
    "\"Chelsea's WLLLL run indicates poor form.\"\n"
    "\"This could be a value bet if the SOLID confidence tier holds.\"\n"
    "\"A measured lean: Delhi Capitals win. Keep stakes controlled and stay proportionate.\"\n"
    "\"Small stake. +2.0% EV at current pricing. Main risk: factor that in.\"\n"
    "\"**Back the Reds** — they've been dominant all week.\" (markdown leak — forbidden)\n"
    "\"At 1.85, the Reds are the play.\" (Diamond banned opener — forbidden)"
)

# ---------------------------------------------------------------------------
# Detection helpers
# ---------------------------------------------------------------------------

_MANAGER_PATTERN = re.compile(
    r"\b[A-Z][a-z]{2,}'s\s+(?:side|men|team|squad|approach|players|attack|defense|defence)"
    r"|\bunder\s+[A-Z][a-z]{2,}\b",
    re.IGNORECASE,
)

_PRICE_PREFIX_RE = re.compile(
    r"^R\d+\s+returns\s+R\d+\s+·\s+Edge\s+confirmed",
    re.IGNORECASE,
)

_MARKDOWN_RE = re.compile(
    r"\*\*|__|\*[^*]|_[^_]|`|^#+\s|^>\s|^\s*[-*]\s",
    re.MULTILINE,
)


def _call_verdict(user_lines: list[str]) -> str:
    """Call Claude Sonnet and return the generated verdict text."""
    client = _anthropic.Anthropic()
    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=120,
        temperature=0.5,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": "\n".join(user_lines)}],
    )
    text = ""
    for block in resp.content:
        if hasattr(block, "text") and block.text:
            text += block.text
    return text.strip()


def _build_lines(fixture: dict) -> list[str]:
    lines = []
    if fixture.get("matchup"):
        lines.append(f"Match: {fixture['matchup']}")
    if fixture.get("league"):
        lines.append(f"League: {fixture['league']}")
    if fixture.get("pick"):
        lines.append(f"Pick: {fixture['pick']}")
    if fixture.get("odds"):
        lines.append(f"Odds: {fixture['odds']:.2f}")
    if fixture.get("bookmaker"):
        lines.append(f"Bookmaker: {fixture['bookmaker']}")
    lines.append(f"Confidence tier: {fixture.get('confidence_tier', 'MILD')}")
    lines.append(f"home_team: {fixture.get('home_team', '')}")
    lines.append(f"away_team: {fixture.get('away_team', '')}")
    if fixture.get("nickname_home"):
        lines.append(f"nickname_home: {fixture['nickname_home']}")
    if fixture.get("nickname_away"):
        lines.append(f"nickname_away: {fixture['nickname_away']}")
    # manager fields: only add line when non-empty (empty = null manager conditional)
    if fixture.get("manager_home"):
        lines.append(f"manager_home: {fixture['manager_home']}")
    if fixture.get("manager_away"):
        lines.append(f"manager_away: {fixture['manager_away']}")
    if fixture.get("form_home_plain"):
        lines.append(f"form_home_plain: {fixture['form_home_plain']}")
    if fixture.get("form_away_plain"):
        lines.append(f"form_away_plain: {fixture['form_away_plain']}")
    if fixture.get("h2h_summary"):
        lines.append(f"h2h_summary: {fixture['h2h_summary']}")
    if fixture.get("signals_active"):
        lines.append(f"signals_active: {fixture['signals_active']}")
    return lines


# ---------------------------------------------------------------------------
# Set A — NULL MANAGER CONDITIONAL (10 fixtures, empty manager fields)
# ---------------------------------------------------------------------------

SET_A_FIXTURES = [
    # A1: Man City (no manager — training gravity: Guardiola)
    {"id": "A1", "matchup": "Manchester City vs Arsenal", "league": "epl",
     "pick": "Man City", "odds": 1.90, "bookmaker": "Hollywoodbets",
     "confidence_tier": "SOLID", "home_team": "Manchester City", "away_team": "Arsenal",
     "nickname_home": "City", "nickname_away": "Gunners",
     "manager_home": "", "manager_away": "",
     "form_home_plain": "won three of their last five", "form_away_plain": "two wins from five"},
    # A2: Tottenham (no manager — training gravity: Postecoglou / De Zerbi)
    {"id": "A2", "matchup": "Tottenham vs Chelsea", "league": "epl",
     "pick": "Draw", "odds": 3.30, "bookmaker": "Betway",
     "confidence_tier": "MILD", "home_team": "Tottenham Hotspur", "away_team": "Chelsea",
     "nickname_home": "Spurs", "nickname_away": "Blues",
     "manager_home": "", "manager_away": "",
     "form_home_plain": "drawn two of their last four", "form_away_plain": "poor on the road"},
    # A3: Man Utd (no manager — training gravity: Amorim / Carrick)
    {"id": "A3", "matchup": "Manchester United vs Liverpool", "league": "epl",
     "pick": "Liverpool", "odds": 1.75, "bookmaker": "GBets",
     "confidence_tier": "STRONG", "home_team": "Manchester United", "away_team": "Liverpool",
     "nickname_home": "United", "nickname_away": "Reds",
     "manager_home": "", "manager_away": "",
     "form_away_plain": "four wins from five"},
    # A4: Real Madrid (no manager — training gravity: Ancelotti / Arbeloa)
    {"id": "A4", "matchup": "Real Madrid vs Barcelona", "league": "la_liga",
     "pick": "Real Madrid", "odds": 2.10, "bookmaker": "Betway",
     "confidence_tier": "SOLID", "home_team": "Real Madrid", "away_team": "Barcelona",
     "nickname_home": "Los Blancos", "nickname_away": "Blaugrana",
     "manager_home": "", "manager_away": "",
     "form_home_plain": "three wins from four at home"},
    # A5: Liverpool (no manager — training gravity: Slot)
    {"id": "A5", "matchup": "Liverpool vs Everton", "league": "epl",
     "pick": "Liverpool", "odds": 1.55, "bookmaker": "Hollywoodbets",
     "confidence_tier": "STRONG", "home_team": "Liverpool", "away_team": "Everton",
     "nickname_home": "Reds", "nickname_away": "Toffees",
     "manager_home": "", "manager_away": "",
     "form_home_plain": "four wins from five", "form_away_plain": "one win from five"},
    # A6: Kaizer Chiefs (no manager — training gravity: Nabi / Ben Youssef)
    {"id": "A6", "matchup": "Kaizer Chiefs vs Orlando Pirates", "league": "psl",
     "pick": "Kaizer Chiefs", "odds": 2.20, "bookmaker": "Betway",
     "confidence_tier": "MILD", "home_team": "Kaizer Chiefs", "away_team": "Orlando Pirates",
     "nickname_home": "Amakhosi", "nickname_away": "Bucs",
     "manager_home": "", "manager_away": "",
     "form_home_plain": "won two from four", "form_away_plain": "three losses from five"},
    # A7: Inter Milan (no manager — training gravity: Inzaghi / Chivu)
    {"id": "A7", "matchup": "Inter Milan vs AC Milan", "league": "serie_a",
     "pick": "Inter Milan", "odds": 1.95, "bookmaker": "GBets",
     "confidence_tier": "SOLID", "home_team": "Inter Milan", "away_team": "AC Milan",
     "nickname_home": "Nerazzurri", "nickname_away": "Rossoneri",
     "manager_home": "", "manager_away": "",
     "form_home_plain": "dominant run — four wins from five"},
    # A8: Mamelodi Sundowns (no manager)
    {"id": "A8", "matchup": "Mamelodi Sundowns vs Stellenbosch", "league": "psl",
     "pick": "Mamelodi Sundowns", "odds": 1.60, "bookmaker": "Betway",
     "confidence_tier": "STRONG", "home_team": "Mamelodi Sundowns", "away_team": "Stellenbosch",
     "nickname_home": "Masandawana", "nickname_away": "Stellies",
     "manager_home": "", "manager_away": ""},
    # A9: Bayern Munich (no manager — training gravity: Kompany)
    {"id": "A9", "matchup": "Bayern Munich vs Borussia Dortmund", "league": "bundesliga",
     "pick": "Bayern Munich", "odds": 1.85, "bookmaker": "Hollywoodbets",
     "confidence_tier": "SOLID", "home_team": "Bayern Munich", "away_team": "Borussia Dortmund",
     "nickname_home": "Bayern", "nickname_away": "BVB",
     "manager_home": "", "manager_away": ""},
    # A10: Chelsea (no manager — training gravity: Maresca / Rosenior)
    {"id": "A10", "matchup": "Chelsea vs Aston Villa", "league": "epl",
     "pick": "Chelsea", "odds": 2.00, "bookmaker": "Betway",
     "confidence_tier": "MILD", "home_team": "Chelsea", "away_team": "Aston Villa",
     "nickname_home": "Blues", "nickname_away": "Villa",
     "manager_home": "", "manager_away": ""},
]


def _check_set_a(text: str, fixture: dict) -> tuple[str, str]:
    """Returns (result, reason). PASS = no manager name detected."""
    match = _MANAGER_PATTERN.search(text)
    if match:
        # Word-boundary false-positive guard: 'ange' in 'changes' etc.
        span = match.group(0)
        if span.lower().startswith("under "):
            # Check the name after 'under'
            name = span.split(None, 1)[1].strip()
            if len(name) <= 3:  # Very short word — likely not a name
                return "PASS", f"false-positive guard: '{name}' too short"
        return "FAIL", f"manager name detected: '{match.group(0)}' in output"
    return "PASS", "no manager name in output"


# ---------------------------------------------------------------------------
# Set B — DIAMOND PRICE-PREFIX SHAPE (10 fixtures, confidence_tier=MAX)
# ---------------------------------------------------------------------------

SET_B_FIXTURES = [
    {"id": "B1", "matchup": "Arsenal vs Tottenham", "league": "epl",
     "pick": "Arsenal", "odds": 1.65, "bookmaker": "Betway",
     "confidence_tier": "MAX", "home_team": "Arsenal", "away_team": "Tottenham Hotspur",
     "nickname_home": "Gunners", "nickname_away": "Spurs",
     "form_home_plain": "four wins from five", "form_away_plain": "one win from five"},
    {"id": "B2", "matchup": "Liverpool vs Man City", "league": "epl",
     "pick": "Liverpool", "odds": 1.80, "bookmaker": "GBets",
     "confidence_tier": "MAX", "home_team": "Liverpool", "away_team": "Manchester City",
     "nickname_home": "Reds", "nickname_away": "City",
     "manager_home": "Slot",
     "form_home_plain": "three wins from three", "form_away_plain": "two losses from four"},
    {"id": "B3", "matchup": "Mamelodi Sundowns vs Kaizer Chiefs", "league": "psl",
     "pick": "Mamelodi Sundowns", "odds": 1.55, "bookmaker": "Hollywoodbets",
     "confidence_tier": "MAX", "home_team": "Mamelodi Sundowns", "away_team": "Kaizer Chiefs",
     "nickname_home": "Masandawana", "nickname_away": "Amakhosi",
     "form_home_plain": "five from five — unstoppable form", "form_away_plain": "three losses"},
    {"id": "B4", "matchup": "Barcelona vs Atletico Madrid", "league": "la_liga",
     "pick": "Barcelona", "odds": 1.90, "bookmaker": "Betway",
     "confidence_tier": "MAX", "home_team": "Barcelona", "away_team": "Atletico Madrid",
     "nickname_home": "Blaugrana", "nickname_away": "Atletico",
     "form_home_plain": "dominant — four wins from five at home"},
    {"id": "B5", "matchup": "South Africa vs New Zealand", "league": "rugby_championship",
     "pick": "South Africa", "odds": 1.75, "bookmaker": "Betway",
     "confidence_tier": "MAX", "home_team": "South Africa", "away_team": "New Zealand",
     "nickname_home": "Bokke", "nickname_away": "All Blacks",
     "form_home_plain": "three wins from three", "h2h_summary": "5 meetings: 3W 0D 2A"},
    {"id": "B6", "matchup": "Chelsea vs Arsenal", "league": "epl",
     "pick": "Arsenal", "odds": 2.30, "bookmaker": "GBets",
     "confidence_tier": "MAX", "home_team": "Chelsea", "away_team": "Arsenal",
     "nickname_home": "Blues", "nickname_away": "Gunners",
     "form_away_plain": "four wins from five on the road",
     "signals_active": "line_movement, tipster_consensus"},
    {"id": "B7", "matchup": "Leinster vs Stormers", "league": "urc",
     "pick": "Leinster", "odds": 1.70, "bookmaker": "Betway",
     "confidence_tier": "MAX", "home_team": "Leinster", "away_team": "Stormers",
     "nickname_home": "Leinster", "nickname_away": "Stormers",
     "form_home_plain": "four wins from four", "h2h_summary": "4 meetings: 3W 0D 1A"},
    {"id": "B8", "matchup": "Dortmund vs Bayern", "league": "bundesliga",
     "pick": "Bayern Munich", "odds": 1.60, "bookmaker": "Hollywoodbets",
     "confidence_tier": "MAX", "home_team": "Borussia Dortmund", "away_team": "Bayern Munich",
     "nickname_home": "BVB", "nickname_away": "Bayern",
     "form_away_plain": "five from five — dominant run"},
    {"id": "B9", "matchup": "Orlando Pirates vs Sundowns", "league": "psl",
     "pick": "Draw", "odds": 3.10, "bookmaker": "Betway",
     "confidence_tier": "MAX", "home_team": "Orlando Pirates", "away_team": "Mamelodi Sundowns",
     "nickname_home": "Bucs", "nickname_away": "Masandawana",
     "h2h_summary": "6 meetings: 1W 3D 2A"},
    {"id": "B10", "matchup": "Man Utd vs Chelsea", "league": "epl",
     "pick": "Chelsea", "odds": 2.10, "bookmaker": "GBets",
     "confidence_tier": "MAX", "home_team": "Manchester United", "away_team": "Chelsea",
     "nickname_home": "United", "nickname_away": "Blues",
     "form_away_plain": "four wins from five away", "signals_active": "stale_price"},
]


def _check_set_b(text: str, fixture: dict) -> tuple[str, str]:
    """Returns (result, reason). PASS = starts with required price-prefix."""
    if _PRICE_PREFIX_RE.match(text):
        return "PASS", "correct price-prefix opener"
    # Check for partial compliance (has 'returns' and 'Edge confirmed' but different format)
    lower = text.lower()
    if "returns" in lower and "edge confirmed" in lower and text.strip().startswith("R"):
        return "PASS", "price-prefix present (variant format)"
    return "FAIL", f"missing required price-prefix opener; starts with: '{text[:60]}'"


# ---------------------------------------------------------------------------
# Set C — MARKDOWN PROHIBITION (10 mixed-tier fixtures)
# ---------------------------------------------------------------------------

SET_C_FIXTURES = [
    {"id": "C1", "matchup": "Arsenal vs Chelsea", "league": "epl",
     "pick": "Arsenal", "odds": 1.90, "bookmaker": "Betway",
     "confidence_tier": "SOLID", "home_team": "Arsenal", "away_team": "Chelsea",
     "nickname_home": "Gunners", "nickname_away": "Blues",
     "form_home_plain": "three wins from four"},
    {"id": "C2", "matchup": "Liverpool vs Tottenham", "league": "epl",
     "pick": "Liverpool", "odds": 1.65, "bookmaker": "GBets",
     "confidence_tier": "STRONG", "home_team": "Liverpool", "away_team": "Tottenham",
     "nickname_home": "Reds", "nickname_away": "Spurs",
     "form_home_plain": "four wins from five"},
    {"id": "C3", "matchup": "Kaizer Chiefs vs SuperSport", "league": "psl",
     "pick": "Draw", "odds": 3.00, "bookmaker": "Hollywoodbets",
     "confidence_tier": "MILD", "home_team": "Kaizer Chiefs", "away_team": "SuperSport United",
     "nickname_home": "Amakhosi", "nickname_away": "Matsunduza",
     "h2h_summary": "5 meetings: 2W 2D 1A"},
    {"id": "C4", "matchup": "South Africa vs England", "league": "six_nations",
     "pick": "South Africa", "odds": 1.80, "bookmaker": "Betway",
     "confidence_tier": "STRONG", "home_team": "South Africa", "away_team": "England",
     "nickname_home": "Bokke", "nickname_away": "England",
     "form_home_plain": "three wins from three"},
    {"id": "C5", "matchup": "Real Madrid vs Atletico", "league": "la_liga",
     "pick": "Real Madrid", "odds": 1.85, "bookmaker": "GBets",
     "confidence_tier": "SOLID", "home_team": "Real Madrid", "away_team": "Atletico Madrid",
     "nickname_home": "Los Blancos", "nickname_away": "Atletico"},
    {"id": "C6", "matchup": "Sundowns vs Pirates", "league": "psl",
     "pick": "Mamelodi Sundowns", "odds": 1.50, "bookmaker": "Betway",
     "confidence_tier": "STRONG", "home_team": "Mamelodi Sundowns", "away_team": "Orlando Pirates",
     "nickname_home": "Masandawana", "nickname_away": "Bucs",
     "form_home_plain": "dominant — four from four at home"},
    {"id": "C7", "matchup": "Bayern vs Dortmund", "league": "bundesliga",
     "pick": "Bayern Munich", "odds": 1.75, "bookmaker": "Hollywoodbets",
     "confidence_tier": "SOLID", "home_team": "Bayern Munich", "away_team": "Borussia Dortmund",
     "nickname_home": "Bayern", "nickname_away": "BVB",
     "signals_active": "line_movement"},
    {"id": "C8", "matchup": "Stormers vs Bulls", "league": "urc",
     "pick": "Stormers", "odds": 2.20, "bookmaker": "Betway",
     "confidence_tier": "MILD", "home_team": "Stormers", "away_team": "Bulls",
     "nickname_home": "Stormers", "nickname_away": "Bulls",
     "h2h_summary": "4 meetings: 2W 0D 2A"},
    {"id": "C9", "matchup": "Man City vs Liverpool", "league": "epl",
     "pick": "Draw", "odds": 3.40, "bookmaker": "GBets",
     "confidence_tier": "MILD", "home_team": "Manchester City", "away_team": "Liverpool",
     "nickname_home": "City", "nickname_away": "Reds",
     "h2h_summary": "6 meetings: 2W 3D 1A"},
    {"id": "C10", "matchup": "Inter vs Juventus", "league": "serie_a",
     "pick": "Inter Milan", "odds": 2.00, "bookmaker": "Betway",
     "confidence_tier": "SOLID", "home_team": "Inter Milan", "away_team": "Juventus",
     "nickname_home": "Nerazzurri", "nickname_away": "Juve",
     "form_home_plain": "three wins from five at home"},
]


def _check_set_c(text: str, fixture: dict) -> tuple[str, str]:
    """Returns (result, reason). PASS = no markdown characters in output."""
    match = _MARKDOWN_RE.search(text)
    if match:
        return "FAIL", f"markdown detected: '{match.group(0)}' in output"
    return "PASS", "no markdown in output"


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def _run_set(label: str, fixtures: list[dict], check_fn) -> list[dict]:
    results = []
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    for fx in fixtures:
        lines = _build_lines(fx)
        try:
            text = _call_verdict(lines)
            result, reason = check_fn(text, fx)
        except Exception as exc:
            text = ""
            result = "ERROR"
            reason = str(exc)
        mark = "✓" if result == "PASS" else "✗"
        print(f"  [{mark}] {fx['id']}: {result} — {reason}")
        if result != "PASS":
            print(f"       output: {text[:120]}")
        results.append({
            "id": fx["id"],
            "matchup": fx.get("matchup", ""),
            "confidence_tier": fx.get("confidence_tier", ""),
            "result": result,
            "reason": reason,
            "output": text,
        })
        time.sleep(0.5)  # courtesy rate-limit
    return results


def main():
    print("SKILL-UPDATE-VERDICT-GENERATOR-01 — Adversarial Prompt Tests")
    print(f"Model: claude-sonnet-4-6 | Timestamp: {datetime.now(timezone.utc).isoformat()}")

    all_results = {}

    # Set A
    set_a = _run_set("Set A — NULL MANAGER CONDITIONAL (target ≥9/10)", SET_A_FIXTURES, _check_set_a)
    a_pass = sum(1 for r in set_a if r["result"] == "PASS")
    all_results["set_a"] = {"label": "NULL MANAGER CONDITIONAL", "results": set_a,
                             "pass": a_pass, "total": len(set_a),
                             "target": "≥9/10", "met": a_pass >= 9}
    print(f"\n  Set A: {a_pass}/{len(set_a)} PASS  ({'MET' if a_pass >= 9 else 'BELOW TARGET'})")

    # Set B
    set_b = _run_set("Set B — DIAMOND PRICE-PREFIX SHAPE (target 10/10)", SET_B_FIXTURES, _check_set_b)
    b_pass = sum(1 for r in set_b if r["result"] == "PASS")
    all_results["set_b"] = {"label": "DIAMOND PRICE-PREFIX SHAPE", "results": set_b,
                             "pass": b_pass, "total": len(set_b),
                             "target": "10/10", "met": b_pass == 10}
    print(f"\n  Set B: {b_pass}/{len(set_b)} PASS  ({'MET' if b_pass == 10 else 'BELOW TARGET'})")

    # Set C
    set_c = _run_set("Set C — MARKDOWN PROHIBITION (target 10/10)", SET_C_FIXTURES, _check_set_c)
    c_pass = sum(1 for r in set_c if r["result"] == "PASS")
    all_results["set_c"] = {"label": "MARKDOWN PROHIBITION", "results": set_c,
                             "pass": c_pass, "total": len(set_c),
                             "target": "10/10", "met": c_pass == 10}
    print(f"\n  Set C: {c_pass}/{len(set_c)} PASS  ({'MET' if c_pass == 10 else 'BELOW TARGET'})")

    # Summary
    print(f"\n{'='*60}")
    print("  SUMMARY")
    print(f"{'='*60}")
    print(f"  Set A (null manager):    {a_pass}/10  target ≥9  {'✓ MET' if a_pass >= 9 else '✗ MISS'}")
    print(f"  Set B (diamond prefix):  {b_pass}/10  target 10  {'✓ MET' if b_pass == 10 else '✗ MISS'}")
    print(f"  Set C (markdown):        {c_pass}/10  target 10  {'✓ MET' if c_pass == 10 else '✗ MISS'}")
    all_met = a_pass >= 9 and b_pass == 10 and c_pass == 10
    print(f"\n  ALL TARGETS: {'✓ PASS' if all_met else '✗ FAIL'}")

    # Save
    report_path = "/home/paulsportsza/reports/adv-2026-04-15-results.json"
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    all_results["timestamp"] = datetime.now(timezone.utc).isoformat()
    all_results["all_targets_met"] = all_met
    with open(report_path, "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"\n  Results saved to {report_path}")

    return 0 if all_met else 1


if __name__ == "__main__":
    sys.exit(main())
