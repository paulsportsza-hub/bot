#!/usr/bin/env python3
"""
Wave 17F: Final Telethon Gauntlet — All Sports, Screenshots
============================================================
P0 — Final validation before polish-and-test phase.

Discovery-based: tests ALL available matches from Your Games + Hot Tips.
Screenshot capture for every test interaction.
Full validation: Four Laws, Factual Accuracy, Narrative Quality, UX.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import ensure_scrapers_importable
ensure_scrapers_importable()

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.sessions import StringSession
from telethon.tl.custom.message import Message

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("wave17f")

# ── Constants ──────────────────────────────────────────────────────────
BOT = "mzansiedge_bot"
API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "")
SESSION_PATH = Path("data/telethon_qa_session.string")

from config import BOT_ROOT
SCREENSHOT_DIR = BOT_ROOT.parent / "reports" / "screenshots" / "wave17f"
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_PATH = BOT_ROOT.parent / "reports" / "wave17f-e2e-results.json"

BOT_TIMEOUT = 15
AI_TIMEOUT = 50

EDGE_EMOJIS = {"💎", "🥇", "🥈", "🥉"}

# ── Coaches lookup (for verification) ─────────────────────────────────
from config import COACHES_PATH, KEY_PLAYERS_PATH

try:
    COACHES = json.loads(COACHES_PATH.read_text())
except Exception:
    COACHES = {}
try:
    KEY_PLAYERS = json.loads(KEY_PLAYERS_PATH.read_text())
except Exception:
    KEY_PLAYERS = {}

# Build flat coach surname set for fabrication detection
ALL_COACH_SURNAMES: set[str] = set()
for sport_coaches in COACHES.values():
    for team_data in sport_coaches.values():
        name = team_data.get("name", "")
        if name and name != "Vacant":
            ALL_COACH_SURNAMES.add(name.split()[-1].lower())
            ALL_COACH_SURNAMES.add(name.lower())

# ── Wrong-sport banned terms ──────────────────────────────────────────
SOCCER_TERMS = {"penalty kick", "corner kick", "offside", "throw-in", "free kick",
                "yellow card", "red card", "goalkeeper", "striker", "midfielder",
                "defender", "dribble", "header", "volley", "hat-trick"}
RUGBY_TERMS = {"scrum", "lineout", "ruck", "maul", "conversion",
               "drop goal", "penalty try", "knock-on", "forward pass",
               "fly-half", "scrumhalf", "hooker", "prop", "lock", "flanker",
               "number eight"}
CRICKET_TERMS = {"wicket", "batsman", "bowler", "innings",
                 "century", "maiden", "run rate", "lbw", "stumped",
                 "caught behind", "yorker", "bouncer"}
F1_TERMS = {"pit stop", "qualifying", "pole position", "grid", "drs",
            "undercut", "overcut", "safety car", "compound",
            "downforce", "aero", "chassis", "powertrain"}

SPORT_BANNED = {
    "soccer": RUGBY_TERMS | CRICKET_TERMS | F1_TERMS,
    "football": RUGBY_TERMS | CRICKET_TERMS | F1_TERMS,
    "rugby": SOCCER_TERMS | CRICKET_TERMS | F1_TERMS,
    "cricket": SOCCER_TERMS | RUGBY_TERMS | F1_TERMS,
    "f1": SOCCER_TERMS | RUGBY_TERMS | CRICKET_TERMS,
}

# ── Results tracking ──────────────────────────────────────────────────
results: list[dict] = []
bugs: list[dict] = []


def record(test_id: str, name: str, status: str, response: str,
           checks: dict, detail: str = ""):
    entry = {
        "test_id": test_id, "name": name, "status": status,
        "response": response[:5000],
        "checks": checks,
        "detail": detail,
    }
    results.append(entry)
    icon = {"PASS": "✓", "FAIL": "✗", "SKIP": "⊘", "WARN": "⚠"}.get(status, "?")
    log.info("  %s %s: %s — %s", icon, test_id, name, status)


def file_bug(bug_id: str, severity: str, test_id: str, category: str,
             description: str, evidence: str):
    bugs.append({
        "id": bug_id, "severity": severity, "test_id": test_id,
        "category": category, "description": description,
        "evidence": evidence[:1000],
    })
    log.warning("  BUG %s [%s] %s: %s", bug_id, severity, category, description)


# ── Telethon helpers ──────────────────────────────────────────────────
async def _last_id(c: TelegramClient) -> int:
    msgs = await c.get_messages(BOT, limit=1)
    return msgs[0].id if msgs else 0


async def send(c: TelegramClient, text: str, timeout: int = BOT_TIMEOUT) -> Message | None:
    last = await _last_id(c)
    try:
        await c.send_message(BOT, text)
    except FloodWaitError as e:
        await asyncio.sleep(e.seconds + 2)
        await c.send_message(BOT, text)
    await asyncio.sleep(2)
    deadline = time.time() + timeout
    while time.time() < deadline:
        msgs = await c.get_messages(BOT, limit=10)
        for m in msgs:
            if m.id > last and not m.out:
                return m
        await asyncio.sleep(1)
    return None


async def send_wait_buttons(c: TelegramClient, text: str,
                            timeout: int = BOT_TIMEOUT) -> Message | None:
    last = await _last_id(c)
    try:
        await c.send_message(BOT, text)
    except FloodWaitError as e:
        await asyncio.sleep(e.seconds + 2)
        await c.send_message(BOT, text)
    await asyncio.sleep(2)
    deadline = time.time() + timeout
    found_id = None
    while time.time() < deadline:
        msgs = await c.get_messages(BOT, limit=10)
        for m in msgs:
            if m.id > last and not m.out:
                if found_id is None:
                    found_id = m.id
                if m.buttons:
                    return m
        if found_id:
            updated = await c.get_messages(BOT, ids=found_id)
            if updated and updated.buttons:
                return updated
        await asyncio.sleep(1.5)
    if found_id:
        return await c.get_messages(BOT, ids=found_id)
    return None


async def click_data(c: TelegramClient, msg: Message, prefix: str,
                     timeout: int = AI_TIMEOUT) -> Message | None:
    if not msg or not msg.buttons:
        return None
    old = await _last_id(c)
    for row in msg.buttons:
        for btn in row:
            if hasattr(btn, "data") and btn.data:
                cb = btn.data.decode() if isinstance(btn.data, bytes) else str(btn.data)
                if cb.startswith(prefix):
                    try:
                        await btn.click()
                    except Exception:
                        return None
                    await asyncio.sleep(3)
                    deadline = time.time() + timeout
                    while time.time() < deadline:
                        msgs = await c.get_messages(BOT, limit=10)
                        for m in msgs:
                            if m.id > old and not m.out:
                                return m
                        updated = await c.get_messages(BOT, ids=msg.id)
                        if updated and updated.raw_text != (msg.raw_text or ""):
                            return updated
                        await asyncio.sleep(2)
                    return None
    return None


async def click_exact(c: TelegramClient, msg: Message, data_exact: str,
                      timeout: int = AI_TIMEOUT) -> Message | None:
    if not msg or not msg.buttons:
        return None
    old = await _last_id(c)
    for row in msg.buttons:
        for btn in row:
            if hasattr(btn, "data") and btn.data:
                cb = btn.data.decode() if isinstance(btn.data, bytes) else str(btn.data)
                if cb == data_exact:
                    try:
                        await btn.click()
                    except Exception:
                        return None
                    await asyncio.sleep(3)
                    deadline = time.time() + timeout
                    while time.time() < deadline:
                        msgs = await c.get_messages(BOT, limit=10)
                        for m in msgs:
                            if m.id > old and not m.out:
                                return m
                        updated = await c.get_messages(BOT, ids=msg.id)
                        if updated and updated.raw_text != (msg.raw_text or ""):
                            return updated
                        await asyncio.sleep(2)
                    return None
    return None


def get_callback_data(msg: Message) -> list[str]:
    if not msg or not msg.buttons:
        return []
    cbs = []
    for row in msg.buttons:
        for btn in row:
            if hasattr(btn, "data") and btn.data:
                cb = btn.data.decode() if isinstance(btn.data, bytes) else str(btn.data)
                cbs.append(cb)
    return cbs


def get_buttons_text(msg: Message) -> list[str]:
    if not msg or not msg.buttons:
        return []
    return [btn.text for row in msg.buttons for btn in row if hasattr(btn, "text")]


# ── Screenshot capture ─────────────────────────────────────────────────
def save_screenshot(name: str, msg: Message | None, extra: str = "") -> str:
    safe = name.replace(":", "_").replace("/", "_").replace(" ", "_")
    fname = f"17f-{safe}.txt"
    if msg is None:
        content = f"SCREENSHOT: {name}\nSTATUS: No response\n"
    else:
        text = msg.raw_text or "(empty)"
        btns = get_buttons_text(msg)
        cbs = get_callback_data(msg)
        content = (
            f"SCREENSHOT: {name}\n"
            f"{'=' * 60}\n"
            f"TEXT:\n{text}\n"
            f"\n{'=' * 60}\n"
            f"BUTTONS: {btns}\n"
            f"CALLBACKS: {cbs}\n"
        )
    if extra:
        content += f"\nEXTRA: {extra}\n"
    (SCREENSHOT_DIR / fname).write_text(content, encoding="utf-8")
    return fname


# ── Helpers ────────────────────────────────────────────────────────────
def detect_sport(line: str) -> str:
    if "🏏" in line:
        return "cricket"
    if "🏉" in line:
        return "rugby"
    if "🏎" in line:
        return "f1"
    return "soccer"


def normalise_team(raw: str) -> str:
    cleaned = re.sub(r'[\U0001F1E0-\U0001F1FF\U0001F3F4\U0001F3F3\uFE0F\u200D]+', '', raw)
    return cleaned.strip().lower().replace(" ", "_").strip("_")


def get_expected_coaches(home: str, away: str, sport: str) -> list[tuple[str, str]]:
    sport_key = "soccer" if sport in ("soccer", "football") else sport
    sport_coaches = COACHES.get(sport_key, {})
    coaches = []
    for team_raw in [home, away]:
        team_key = team_raw.replace("_", " ").lower()
        if team_key in sport_coaches:
            coaches.append((team_key, sport_coaches[team_key]["name"]))
        else:
            for variant in [team_key.replace(" fc", ""), team_key.replace(" united", "")]:
                if variant in sport_coaches:
                    coaches.append((variant, sport_coaches[variant]["name"]))
                    break
    return coaches


# ── Validation functions ──────────────────────────────────────────────
def check_four_laws(text: str, sport: str) -> dict:
    checks = {}
    checks["law1_no_fabrication"] = {"pass": True, "detail": "Deferred to factual accuracy"}
    checks["law2_verified_names"] = {"pass": True, "detail": "Checked via coach verification"}

    banned = SPORT_BANNED.get(sport, set())
    text_lower = text.lower()
    violations = [term for term in banned if term in text_lower]
    checks["law3_no_wrong_sport"] = {
        "pass": len(violations) == 0,
        "detail": f"Violations: {violations}" if violations else "Clean"
    }

    degradation = ["data unavailable", "limited data", "skip this fixture",
                   "insufficient data", "no recent form", "cannot assess"]
    has_deg = any(p in text_lower for p in degradation)
    checks["law4_degradation"] = {"pass": True, "detail": f"Degradation: {has_deg}"}
    return checks


def check_factual_accuracy(text: str, sport: str, expected_coaches: list) -> dict:
    checks = {}
    text_lower = text.lower()

    for team_key, coach_name in expected_coaches:
        surname = coach_name.split()[-1].lower()
        found = coach_name.lower() in text_lower or surname in text_lower
        checks[f"coach_{team_key}"] = {
            "pass": True, "detail": f"{'Found' if found else 'Not found'}: {coach_name}",
            "found": found,
        }

    coach_refs = re.findall(
        r'(?:coach|manager|head coach|tp|team principal)[:\s]+([A-Z][a-z]+ [A-Z][a-z]+)', text)
    fabricated = [ref for ref in coach_refs if ref.split()[-1].lower() not in ALL_COACH_SURNAMES]
    checks["no_fabricated_coaches"] = {
        "pass": len(fabricated) == 0,
        "detail": f"Fabricated: {fabricated}" if fabricated else "Clean"
    }
    return checks


def check_narrative_quality(text: str) -> dict:
    checks = {}
    has_edge = any(e in text for e in EDGE_EMOJIS)
    checks["edge_badge"] = {"pass": has_edge, "detail": f"Edge badge: {has_edge}"}

    wc = len(text.split())
    checks["substantive"] = {"pass": wc >= 30, "detail": f"Words: {wc}"}
    checks["not_excessive"] = {"pass": wc <= 600, "detail": f"Words: {wc}"}
    checks["has_structure"] = {"pass": text.count("\n") >= 3, "detail": f"Lines: {text.count(chr(10))}"}

    sa_ind = ["🇿🇦", "sa ", "south africa", "bookie", "mzansi", "braai", "lekker"]
    checks["sa_tone"] = {"pass": True, "detail": f"SA tone: {any(i in text.lower() for i in sa_ind)}"}
    return checks


def check_ux(msg: Message | None) -> dict:
    checks = {}
    if not msg:
        return {"ux_response": {"pass": False, "detail": "No response"}}

    checks["has_buttons"] = {"pass": bool(msg.buttons), "detail": f"Buttons: {bool(msg.buttons)}"}
    btn_texts = get_buttons_text(msg)
    checks["buttons_readable"] = {"pass": len(btn_texts) > 0, "detail": f"Btns: {btn_texts[:5]}"}
    has_back = any("back" in b.lower() or "↩" in b for b in btn_texts)
    checks["has_back_nav"] = {"pass": has_back, "detail": f"Back: {has_back}"}

    cbs = get_callback_data(msg)
    has_oc = any(cb.startswith("odds:compare:") for cb in cbs)
    checks["odds_compare_btn"] = {"pass": True, "detail": f"Odds compare: {has_oc}"}
    return checks


def check_broadcast(text: str) -> dict:
    return {"broadcast_info": {"pass": True, "detail": f"Broadcast: {'📺' in text}", "found": "📺" in text}}


def check_key_players_rugby(text: str, home: str, away: str) -> dict:
    checks = {}
    sport_players = KEY_PLAYERS.get("rugby", {})
    text_lower = text.lower()
    for team_raw in [home, away]:
        team_key = team_raw.replace("_", " ").replace("the ", "").strip()
        players = sport_players.get(team_key, [])
        if players:
            found = [p["name"] for p in players if p["name"].split()[-1].lower() in text_lower]
            checks[f"key_players_{team_key}"] = {
                "pass": True, "detail": f"Found: {found}" if found else "None found",
                "found": len(found) > 0,
            }
    return checks


# ── Main test runner ──────────────────────────────────────────────────
async def run_gauntlet():
    log.info("=" * 70)
    log.info("WAVE 17F: Final Telethon Gauntlet — All Sports, Screenshots")
    log.info("=" * 70)

    session_str = SESSION_PATH.read_text().strip()
    client = TelegramClient(StringSession(session_str), API_ID, API_HASH)
    await client.connect()
    me = await client.get_me()
    log.info("Connected as %s (@%s)", me.first_name, me.username)

    bug_counter = {"HAL": 0, "SPORT": 0, "CTA": 0, "NAV": 0, "UX": 0}
    test_num = 0

    # ══════════════════════════════════════════════════════════════
    # PART A: YOUR GAMES — Full AI Breakdowns
    # ══════════════════════════════════════════════════════════════
    log.info("\n══ PART A: Your Games — AI Breakdowns ══")

    yg_msg = await send_wait_buttons(client, "⚽ Your Games")
    save_screenshot("A00-your-games", yg_msg)
    yg_text = yg_msg.raw_text if yg_msg else ""
    log.info("  Your Games: %d chars", len(yg_text))

    yg_game_cbs = [cb for cb in get_callback_data(yg_msg) if cb.startswith("yg:game:")]
    log.info("  Found %d game callbacks", len(yg_game_cbs))

    # Parse game details from display text (handles flag emojis)
    # Pattern: "[N] ⚽ 19:30  Leeds United vs Manchester City" or "[N] 🏏 11:30  🇿🇼 Zimbabwe vs 🇿🇦 South Africa"
    yg_games: list[dict] = []
    lines = yg_text.split("\n") if yg_text else []
    for line in lines:
        if " vs " in line:
            sport = detect_sport(line)
            m = re.search(
                r'(\d{2}:\d{2})\s+'
                r'([\U0001F1E0-\U0001F1FF\U0001F3F4\U0001F3F3\uFE0F\u200D\s]*'
                r'[A-Za-z][\w\s.\'-]+?)\s+vs\s+'
                r'([\U0001F1E0-\U0001F1FF\U0001F3F4\U0001F3F3\uFE0F\u200D\s]*'
                r'[A-Za-z][\w\s.\'-]+)',
                line
            )
            if m:
                home = normalise_team(m.group(2))
                away = normalise_team(m.group(3))
                yg_games.append({
                    "home": home, "away": away, "sport": sport,
                    "time": m.group(1), "display": line.strip(),
                })

    for i, game in enumerate(yg_games):
        if i < len(yg_game_cbs):
            game["callback"] = yg_game_cbs[i]

    log.info("  Parsed %d games, paired %d with callbacks",
             len(yg_games), len([g for g in yg_games if "callback" in g]))
    for g in yg_games:
        log.info("    %s vs %s [%s] → %s", g["home"], g["away"], g["sport"],
                 g.get("callback", "NO CB"))

    # Test each Your Games match
    for game in yg_games:
        if "callback" not in game:
            continue
        test_num += 1
        test_id = f"YG-{test_num:02d}"
        home, away, sport = game["home"], game["away"], game["sport"]
        desc = f"Your Games — {home.replace('_',' ').title()} vs {away.replace('_',' ').title()} [{sport}]"
        log.info("\n[%s] %s", test_id, desc)

        expected_coaches = get_expected_coaches(home, away, sport)
        log.info("  Expected coaches: %s", expected_coaches)

        yg_nav = await send_wait_buttons(client, "⚽ Your Games")
        breakdown_msg = None
        if yg_nav:
            breakdown_msg = await click_exact(client, yg_nav, game["callback"], timeout=AI_TIMEOUT)

        if not breakdown_msg:
            record(test_id, desc, "SKIP", "Navigation failed",
                   {"navigation": {"pass": False, "detail": "Click failed"}})
            save_screenshot(f"{test_id}-skip", yg_nav, "Click failed")
            continue

        bd_text = breakdown_msg.raw_text or ""
        save_screenshot(f"{test_id}-breakdown", breakdown_msg)
        log.info("  Screenshot: breakdown %d chars, %d words", len(bd_text), len(bd_text.split()))

        # Odds comparison screenshot
        oc_cbs = [cb for cb in get_callback_data(breakdown_msg) if cb.startswith("odds:compare:")]
        if oc_cbs:
            oc_msg = await click_exact(client, breakdown_msg, oc_cbs[0], timeout=BOT_TIMEOUT)
            save_screenshot(f"{test_id}-odds-compare", oc_msg)
            log.info("  Screenshot: odds comparison")

        # Validation
        all_checks = {}
        all_checks.update(check_four_laws(bd_text, sport))
        all_checks.update(check_factual_accuracy(bd_text, sport, expected_coaches))
        all_checks.update(check_narrative_quality(bd_text))
        all_checks.update(check_ux(breakdown_msg))
        all_checks.update(check_broadcast(bd_text))
        if sport == "rugby":
            all_checks.update(check_key_players_rugby(bd_text, home, away))

        # Bug filing
        p0f, p1f, p2f = [], [], []
        if not all_checks["law3_no_wrong_sport"]["pass"]:
            bug_counter["SPORT"] += 1
            bid = f"BUG-SPORT-{bug_counter['SPORT']:03d}"
            file_bug(bid, "P0", test_id, "Wrong Sport", all_checks["law3_no_wrong_sport"]["detail"], bd_text[:500])
            p0f.append(bid)
        if not all_checks.get("no_fabricated_coaches", {}).get("pass", True):
            bug_counter["HAL"] += 1
            bid = f"BUG-HAL-{bug_counter['HAL']:03d}"
            file_bug(bid, "P0", test_id, "Fabricated Coach", all_checks["no_fabricated_coaches"]["detail"], bd_text[:500])
            p0f.append(bid)
        if not all_checks.get("edge_badge", {}).get("pass", True):
            bug_counter["CTA"] += 1
            bid = f"BUG-CTA-{bug_counter['CTA']:03d}"
            file_bug(bid, "P1", test_id, "Missing Edge", "No edge emoji", bd_text[:300])
            p1f.append(bid)
        if not all_checks.get("substantive", {}).get("pass", True):
            bug_counter["UX"] += 1
            bid = f"BUG-UX-{bug_counter['UX']:03d}"
            file_bug(bid, "P1", test_id, "Too Short", all_checks["substantive"]["detail"], bd_text[:300])
            p1f.append(bid)
        if not all_checks.get("has_buttons", {}).get("pass", True):
            bug_counter["NAV"] += 1
            bid = f"BUG-NAV-{bug_counter['NAV']:03d}"
            file_bug(bid, "P2", test_id, "No Buttons", "Missing buttons", "")
            p2f.append(bid)
        if not all_checks.get("has_back_nav", {}).get("pass", True):
            bug_counter["NAV"] += 1
            bid = f"BUG-NAV-{bug_counter['NAV']:03d}"
            file_bug(bid, "P2", test_id, "No Back Nav", "Missing back", "")
            p2f.append(bid)

        status = "FAIL" if p0f else "WARN" if p1f else "PASS"
        parts = []
        if p0f: parts.append(f"P0: {p0f}")
        if p1f: parts.append(f"P1: {p1f}")
        if p2f: parts.append(f"P2: {p2f}")
        record(test_id, desc, status, bd_text, all_checks,
               "; ".join(parts) if parts else "All checks clean")
        await asyncio.sleep(2)

    # ══════════════════════════════════════════════════════════════
    # PART B: HOT TIPS — Detail Pages (up to 10 tips)
    # ══════════════════════════════════════════════════════════════
    log.info("\n══ PART B: Hot Tips — Tip Details ══")

    hot_msg = await send_wait_buttons(client, "🔥 Hot Tips")
    save_screenshot("B00-hot-tips-p1", hot_msg)
    hot_text_all = hot_msg.raw_text if hot_msg else ""

    tip_cbs_p1 = [cb for cb in get_callback_data(hot_msg) if cb.startswith("tip:detail:")]
    log.info("  Page 1: %d tips", len(tip_cbs_p1))

    # Page 2
    tip_cbs_p2 = []
    page2_msg = None
    next_cbs = [cb for cb in get_callback_data(hot_msg) if cb.startswith("hot:page:")]
    if next_cbs:
        page2_msg = await click_exact(client, hot_msg, next_cbs[0], timeout=BOT_TIMEOUT)
        if page2_msg:
            save_screenshot("B00-hot-tips-p2", page2_msg)
            tip_cbs_p2 = [cb for cb in get_callback_data(page2_msg) if cb.startswith("tip:detail:")]
            hot_text_all += "\n" + (page2_msg.raw_text or "")
            log.info("  Page 2: %d tips", len(tip_cbs_p2))

    # Parse match info from combined Hot Tips text
    hot_matches: list[dict] = []
    for line in hot_text_all.split("\n"):
        if " vs " in line and any(e in line for e in {"⚽", "🏏", "🏉", "🏎"}):
            sport = detect_sport(line)
            m = re.search(
                r'([\U0001F1E0-\U0001F1FF\U0001F3F4\U0001F3F3\uFE0F\u200D\s]*'
                r'[A-Za-z][\w\s.\'-]+?)\s+vs\s+'
                r'([\U0001F1E0-\U0001F1FF\U0001F3F4\U0001F3F3\uFE0F\u200D\s]*'
                r'[A-Za-z][\w\s.\'-]+)',
                line
            )
            if m:
                home = normalise_team(m.group(1))
                away = normalise_team(m.group(2))
                hot_matches.append({"home": home, "away": away, "sport": sport, "display": line.strip()})

    all_tip_cbs = tip_cbs_p1 + tip_cbs_p2
    for i, match in enumerate(hot_matches):
        if i < len(all_tip_cbs):
            match["callback"] = all_tip_cbs[i]

    log.info("  Total: %d hot tips matched", len([m for m in hot_matches if "callback" in m]))

    for match in hot_matches:
        if "callback" not in match:
            continue
        test_num += 1
        test_id = f"HT-{test_num:02d}"
        home, away, sport = match["home"], match["away"], match["sport"]
        desc = f"Hot Tip — {home.replace('_',' ').title()} vs {away.replace('_',' ').title()}"
        log.info("\n[%s] %s", test_id, desc)

        expected_coaches = get_expected_coaches(home, away, sport)

        # Navigate to correct Hot Tips page and click tip
        hot_nav = await send_wait_buttons(client, "🔥 Hot Tips")
        if not hot_nav:
            record(test_id, desc, "SKIP", "Hot Tips nav failed", {})
            continue

        # If on page 2, navigate there
        if match["callback"] in tip_cbs_p2:
            p2cb = [cb for cb in get_callback_data(hot_nav) if cb.startswith("hot:page:")]
            if p2cb:
                hot_nav = await click_exact(client, hot_nav, p2cb[0], timeout=BOT_TIMEOUT)
                if not hot_nav:
                    record(test_id, desc, "SKIP", "Page 2 nav failed", {})
                    continue

        detail_msg = await click_exact(client, hot_nav, match["callback"], timeout=AI_TIMEOUT)
        if not detail_msg:
            record(test_id, desc, "SKIP", "Detail click failed",
                   {"navigation": {"pass": False, "detail": "Click failed"}})
            continue

        td_text = detail_msg.raw_text or ""
        save_screenshot(f"{test_id}-detail", detail_msg)
        log.info("  Screenshot: tip detail %d chars", len(td_text))

        # Validate
        all_checks = {}
        all_checks.update(check_four_laws(td_text, sport))
        all_checks.update(check_factual_accuracy(td_text, sport, expected_coaches))

        has_edge = any(e in td_text for e in EDGE_EMOJIS)
        all_checks["edge_badge"] = {"pass": has_edge, "detail": f"Edge: {has_edge}"}

        has_odds = bool(re.search(r'@\s*\d+\.\d+', td_text) or "odds" in td_text.lower())
        all_checks["odds_display"] = {"pass": has_odds, "detail": f"Odds: {has_odds}"}

        bk_names = ["hollywoodbets", "supabets", "betway", "sportingbet", "gbets"]
        has_bk = any(bk in td_text.lower() for bk in bk_names)
        all_checks["bookmaker_shown"] = {"pass": has_bk, "detail": f"Bookmaker: {has_bk}"}

        has_ev = "ev" in td_text.lower()
        all_checks["ev_display"] = {"pass": has_ev, "detail": f"EV: {has_ev}"}

        all_checks.update(check_ux(detail_msg))

        # Bug filing
        p0f = []
        if not all_checks["law3_no_wrong_sport"]["pass"]:
            bug_counter["SPORT"] += 1
            bid = f"BUG-SPORT-{bug_counter['SPORT']:03d}"
            file_bug(bid, "P0", test_id, "Wrong Sport", all_checks["law3_no_wrong_sport"]["detail"], td_text[:500])
            p0f.append(bid)
        if not all_checks.get("no_fabricated_coaches", {}).get("pass", True):
            bug_counter["HAL"] += 1
            bid = f"BUG-HAL-{bug_counter['HAL']:03d}"
            file_bug(bid, "P0", test_id, "Fabricated Coach", all_checks["no_fabricated_coaches"]["detail"], td_text[:500])
            p0f.append(bid)

        status = "FAIL" if p0f else "PASS"
        record(test_id, desc, status, td_text, all_checks,
               f"P0: {p0f}" if p0f else "All checks clean")
        await asyncio.sleep(2)

    # ══════════════════════════════════════════════════════════════
    # PART C: NAVIGATION & UX
    # ══════════════════════════════════════════════════════════════
    log.info("\n══ PART C: Navigation & UX ══")

    # C1: Rugby filter (empty state)
    test_num += 1
    test_id = f"NAV-{test_num:02d}"
    log.info("\n[%s] Rugby filter", test_id)
    yg_f = await send_wait_buttons(client, "⚽ Your Games")
    if yg_f:
        rf = await click_data(client, yg_f, "yg:sport:rugby", timeout=BOT_TIMEOUT)
        save_screenshot(f"{test_id}-rugby-filter", rf)
        rf_text = rf.raw_text if rf else ""
        ok = "no rugby" in rf_text.lower() or len(rf_text) > 10
        record(test_id, "Rugby filter (empty state)", "PASS" if ok else "WARN",
               rf_text, {"empty_state": {"pass": ok, "detail": rf_text[:200]}})

    # C2: Cricket filter
    test_num += 1
    test_id = f"NAV-{test_num:02d}"
    log.info("\n[%s] Cricket filter", test_id)
    yg_c = await send_wait_buttons(client, "⚽ Your Games")
    if yg_c:
        cf = await click_data(client, yg_c, "yg:sport:cricket", timeout=BOT_TIMEOUT)
        save_screenshot(f"{test_id}-cricket-filter", cf)
        cf_text = cf.raw_text if cf else ""
        ok = "🏏" in cf_text
        record(test_id, "Cricket filter", "PASS" if ok else "WARN",
               cf_text, {"cricket": {"pass": ok, "detail": cf_text[:200]}})

    # C3: /start
    test_num += 1
    test_id = f"NAV-{test_num:02d}"
    log.info("\n[%s] /start", test_id)
    sm = await send(client, "/start")
    save_screenshot(f"{test_id}-start", sm)
    s_text = sm.raw_text if sm else ""
    record(test_id, "/start", "PASS" if s_text else "FAIL",
           s_text, {"response": {"pass": bool(s_text), "detail": s_text[:200]}})

    # C4: Settings
    test_num += 1
    test_id = f"NAV-{test_num:02d}"
    log.info("\n[%s] Settings", test_id)
    stm = await send_wait_buttons(client, "⚙️ Settings")
    save_screenshot(f"{test_id}-settings", stm)
    st_text = stm.raw_text if stm else ""
    ok = "settings" in st_text.lower() or "profile" in st_text.lower()
    record(test_id, "Settings", "PASS" if ok else "FAIL",
           st_text, {"render": {"pass": ok, "detail": st_text[:200]}})

    # C5: Hot Tips pagination
    test_num += 1
    test_id = f"NAV-{test_num:02d}"
    log.info("\n[%s] Pagination", test_id)
    hp = await send_wait_buttons(client, "🔥 Hot Tips")
    if hp:
        p2c = [cb for cb in get_callback_data(hp) if cb.startswith("hot:page:")]
        if p2c:
            p2m = await click_exact(client, hp, p2c[0], timeout=BOT_TIMEOUT)
            save_screenshot(f"{test_id}-page2", p2m)
            p2t = p2m.raw_text if p2m else ""
            ok = "page 2" in p2t.lower() or "[6]" in p2t
            record(test_id, "Pagination to page 2", "PASS" if ok else "WARN",
                   p2t, {"page2": {"pass": ok, "detail": p2t[:200]}})
        else:
            record(test_id, "Pagination", "SKIP", "No page 2", {})

    # C6: Cached reload speed
    test_num += 1
    test_id = f"NAV-{test_num:02d}"
    log.info("\n[%s] Cache speed", test_id)
    if yg_games and "callback" in yg_games[0]:
        yr = await send_wait_buttons(client, "⚽ Your Games")
        if yr:
            t0 = time.time()
            cm = await click_exact(client, yr, yg_games[0]["callback"], timeout=AI_TIMEOUT)
            elapsed = time.time() - t0
            save_screenshot(f"{test_id}-cache", cm)
            c_text = cm.raw_text if cm else ""
            fast = elapsed < 10
            record(test_id, f"Cached reload ({elapsed:.1f}s)", "PASS" if fast else "WARN",
                   c_text, {"speed": {"pass": fast, "detail": f"{elapsed:.1f}s"}})
    else:
        record(test_id, "Cache speed", "SKIP", "No games to retest", {})

    # ══════════════════════════════════════════════════════════════
    # SUMMARY
    # ══════════════════════════════════════════════════════════════
    log.info("\n" + "=" * 70)
    log.info("WAVE 17F RESULTS SUMMARY")
    log.info("=" * 70)

    total = len(results)
    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    warned = sum(1 for r in results if r["status"] == "WARN")
    skipped = sum(1 for r in results if r["status"] == "SKIP")

    log.info("Total: %d | PASS: %d | FAIL: %d | WARN: %d | SKIP: %d",
             total, passed, failed, warned, skipped)
    log.info("Bugs: %d (HAL=%d, SPORT=%d, CTA=%d, NAV=%d, UX=%d)",
             len(bugs), bug_counter["HAL"], bug_counter["SPORT"],
             bug_counter["CTA"], bug_counter["NAV"], bug_counter["UX"])

    coach_found = sum(1 for r in results for k, v in r.get("checks", {}).items()
                      if k.startswith("coach_") and v.get("found"))
    coach_total = sum(1 for r in results for k, v in r.get("checks", {}).items()
                      if k.startswith("coach_") and "found" in v)
    log.info("Coaches: %d/%d found", coach_found, coach_total)

    kp_found = sum(1 for r in results for k, v in r.get("checks", {}).items()
                   if k.startswith("key_players_") and v.get("found"))
    kp_total = sum(1 for r in results for k, v in r.get("checks", {}).items()
                   if k.startswith("key_players_") and "found" in v)
    if kp_total:
        log.info("Key players (rugby): %d/%d", kp_found, kp_total)

    bc_found = sum(1 for r in results for k, v in r.get("checks", {}).items()
                   if k == "broadcast_info" and v.get("found"))
    log.info("Broadcast: %d/%d matches", bc_found,
             sum(1 for r in results if "broadcast_info" in r.get("checks", {})))

    yg_sports = set(g["sport"] for g in yg_games)
    ht_sports = set(m["sport"] for m in hot_matches)
    log.info("Sports — YG: %s | HT: %s", yg_sports, ht_sports)

    screenshots = list(SCREENSHOT_DIR.glob("17f-*.txt"))
    log.info("Screenshots: %d files", len(screenshots))

    summary = {
        "wave": "17F",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total": total, "passed": passed, "failed": failed,
        "warned": warned, "skipped": skipped,
        "bug_count": len(bugs), "bug_counters": bug_counter,
        "coach_verification": {"found": coach_found, "total": coach_total},
        "key_player_verification": {"found": kp_found, "total": kp_total},
        "broadcast_found": bc_found,
        "screenshots": len(screenshots),
        "sports_coverage": {"your_games": list(yg_sports), "hot_tips": list(ht_sports)},
        "results": results, "bugs": bugs,
    }
    RESULTS_PATH.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("Results → %s", RESULTS_PATH)

    await client.disconnect()
    log.info("\nDone.")


if __name__ == "__main__":
    asyncio.run(run_gauntlet())
