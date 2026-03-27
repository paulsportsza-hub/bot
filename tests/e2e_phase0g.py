#!/usr/bin/env python3
"""
Phase 0G: End-to-End Match Screen Audit via Telethon
=====================================================
P0 — Walk through EVERY match screen and catalogue:
  1. Broken/empty match screens
  2. AI prompt leaks (VERIFIED_DATA, ODDS_DATA, ODDS DATA)
  3. Unhelpful or ugly fallback messages

4 Screens tested:
  A. My Matches (sticky keyboard button)
  B. Top Edge Picks (sticky keyboard button)
  C. Game Breakdown (tap a match from My Matches)
  D. Odds Comparison (button from Game Breakdown)

Special checks:
  - Cricket coverage (the founder's reported bug)
  - Broadcast schedule presence
  - Sport filter buttons
  - All edge tier badges render correctly
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
from config import ensure_scrapers_importable, BOT_ROOT
ensure_scrapers_importable()

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.sessions import StringSession
from telethon.tl.custom.message import Message

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("phase0g")

# ── Constants ──────────────────────────────────────────────────────────
BOT = "mzansiedge_bot"
API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "")
SESSION_PATH = Path("data/telethon_session.string")

SCREENSHOT_DIR = BOT_ROOT.parent / "reports" / "screenshots" / "phase0g"
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_PATH = BOT_ROOT.parent / "reports" / "phase0g-e2e-results.json"

BOT_TIMEOUT = 15       # seconds for normal bot responses
AI_TIMEOUT = 60        # seconds for AI game breakdown (Claude call)
SPINNER_POLL = 3       # seconds between spinner checks
MAX_SPINNER_POLLS = 20 # max polls (60s total)

# Prompt leak patterns — these should NEVER appear in user-facing output
PROMPT_LEAK_PATTERNS = [
    r"VERIFIED.?DATA",
    r"ODDS.?DATA",
    r"VERIFIED_DATA",
    r"ODDS_DATA",
    r"you may ONLY state facts",
    r"facts that appear in",
    r"CRITICAL RULES",
    r"FACTUAL CLAIMS",
    r"NARRATIVE & OPINION",
    r"SPORT VALIDATION",
    r"FORMATTING RULES",
    r"section headers",
    r"banned terms for this sport",
    r"claude-haiku",
    r"system prompt",
    r"You are MzansiEdge",
    r"parameterised by sport",
    r"do not invent",
    r"ZERO EXCEPTIONS",
]

# Edge tier badges that should appear correctly
EDGE_BADGES = {
    "diamond": ("💎", "DIAMOND EDGE"),
    "gold": ("🥇", "GOLDEN EDGE"),
    "silver": ("🥈", "SILVER EDGE"),
    "bronze": ("🥉", "BRONZE EDGE"),
}

# ── Results tracking ──────────────────────────────────────────────────
results: list[dict] = []
bugs: list[dict] = []
raw_captures: list[dict] = []


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
    bug = {
        "id": bug_id, "severity": severity, "test_id": test_id,
        "category": category, "description": description,
        "evidence": evidence[:3000],
    }
    bugs.append(bug)
    log.warning("  🐛 %s [%s] %s: %s", bug_id, severity, category, description)


def save_capture(screen: str, text: str, buttons: list[str] | None = None):
    """Save raw response text for the report."""
    raw_captures.append({
        "screen": screen,
        "text": text[:5000],
        "buttons": buttons or [],
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    })
    # Also save to file
    safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", screen)
    fpath = SCREENSHOT_DIR / f"{safe_name}.txt"
    fpath.write_text(text[:5000], encoding="utf-8")


# ── Telethon helpers ──────────────────────────────────────────────────

async def send_and_wait(client, text: str, timeout: int = BOT_TIMEOUT) -> Message | None:
    """Send a message to the bot and wait for a response."""
    await client.send_message(BOT, text)
    await asyncio.sleep(2)

    messages = await client.get_messages(BOT, limit=3)
    for msg in messages:
        if msg.out:
            continue
        return msg
    return None


async def wait_for_stable_response(client, timeout: int = AI_TIMEOUT) -> Message | None:
    """Wait for the bot to stop editing a message (spinner → final content).

    Returns the final stable message once it stops changing.
    """
    last_text = ""
    polls = 0
    while polls < MAX_SPINNER_POLLS:
        await asyncio.sleep(SPINNER_POLL)
        messages = await client.get_messages(BOT, limit=3)
        for msg in messages:
            if msg.out:
                continue
            current = msg.text or msg.message or ""
            if current == last_text and len(current) > 50:
                return msg
            last_text = current
            break
        polls += 1
    # Return whatever we have
    messages = await client.get_messages(BOT, limit=3)
    for msg in messages:
        if not msg.out:
            return msg
    return None


async def click_button(client, msg: Message, text_match: str) -> Message | None:
    """Click an inline button matching the given text pattern."""
    if not msg or not msg.buttons:
        return None
    for row in msg.buttons:
        for btn in row:
            if text_match.lower() in (btn.text or "").lower():
                try:
                    await btn.click()
                except Exception as e:
                    # "Encrypted data invalid" is common with edited messages — ignore
                    log.debug("Button click warning (non-fatal): %s", e)
                # Always wait and fetch latest message after click
                await asyncio.sleep(3)
                messages = await client.get_messages(BOT, limit=5)
                for m in messages:
                    if not m.out:
                        return m
                return None
    return None


async def click_callback_button(client, msg: Message, data_match: str) -> Message | None:
    """Click an inline button by callback_data prefix.

    Handles the common 'Encrypted data invalid' error that occurs when
    the bot has edited the message since we fetched it. The click still
    goes through — we just need to re-fetch the latest message.
    """
    if not msg or not msg.buttons:
        return None
    for row in msg.buttons:
        for btn in row:
            if hasattr(btn, "data") and btn.data and data_match.encode() in btn.data:
                try:
                    await btn.click()
                except Exception as e:
                    # "Encrypted data invalid" — the click was sent, just ignore the ack error
                    log.debug("Callback click warning (non-fatal): %s", e)
                # Wait longer for AI responses
                await asyncio.sleep(4)
                messages = await client.get_messages(BOT, limit=5)
                for m in messages:
                    if not m.out:
                        return m
                return None
    return None


def get_buttons_text(msg: Message) -> list[str]:
    """Extract all button texts from a message."""
    if not msg or not msg.buttons:
        return []
    texts = []
    for row in msg.buttons:
        for btn in row:
            texts.append(btn.text or "")
    return texts


def get_buttons_data(msg: Message) -> list[str]:
    """Extract all callback_data from inline buttons."""
    if not msg or not msg.buttons:
        return []
    data = []
    for row in msg.buttons:
        for btn in row:
            if hasattr(btn, "data") and btn.data:
                data.append(btn.data.decode("utf-8", errors="replace"))
            elif hasattr(btn, "url") and btn.url:
                data.append(f"url:{btn.url[:80]}")
            else:
                data.append(f"text:{btn.text or ''}")
    return data


def check_prompt_leaks(text: str) -> list[str]:
    """Check for any prompt leak patterns in text. Returns list of matches."""
    found = []
    for pattern in PROMPT_LEAK_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            found.append(pattern)
    return found


def check_edge_badges(text: str) -> dict:
    """Check if edge badges are correctly formatted."""
    found = {}
    for tier, (emoji, label) in EDGE_BADGES.items():
        if emoji in text:
            found[tier] = {"emoji": True, "label": label in text}
    return found


# ── Test: My Matches (Screen A) ──────────────────────────────────────

async def test_my_matches(client):
    """A: Test My Matches screen — default view and sport filters."""
    log.info("=" * 60)
    log.info("SCREEN A: My Matches")
    log.info("=" * 60)

    # A-01: Send "⚽ My Matches" and check default view
    msg = await send_and_wait(client, "⚽ My Matches")
    if not msg:
        record("A-01", "My Matches loads", "FAIL", "", {"loaded": False},
               "No response from bot")
        file_bug("BUG-0G-001", "P1", "A-01", "empty_screen",
                 "My Matches returns no response", "")
        return None

    text = msg.text or msg.message or ""
    btns = get_buttons_text(msg)
    btn_data = get_buttons_data(msg)
    save_capture("A01_my_matches_default", text, btns)

    # Check it loaded with content
    has_matches = bool(re.search(r"\[?\d+\]?.*vs", text, re.IGNORECASE))
    has_header = "my matches" in text.lower() or "your games" in text.lower()
    leaks = check_prompt_leaks(text)

    checks = {
        "loaded": bool(text),
        "has_matches": has_matches,
        "has_header": has_header,
        "prompt_leaks": leaks,
        "button_count": len(btns),
    }

    if leaks:
        file_bug("BUG-0G-002", "P0", "A-01", "prompt_leak",
                 f"My Matches leaks prompt text: {leaks}", text[:500])

    if has_matches:
        record("A-01", "My Matches loads with matches", "PASS", text, checks)
    elif "no live matches" in text.lower() or "no matches" in text.lower():
        record("A-01", "My Matches loads (empty state)", "WARN", text, checks,
               "No matches found — empty state shown")
    else:
        record("A-01", "My Matches loads", "PASS" if text else "FAIL", text, checks)

    # A-02: Check sport filter buttons exist
    sport_emojis = {"⚽", "🏉", "🏏", "🥊"}
    found_filters = [b for b in btns if any(e in b for e in sport_emojis)]
    has_sport_filters = len(found_filters) > 0

    record("A-02", "Sport filter buttons present", "PASS" if has_sport_filters else "WARN",
           str(btns), {"filters_found": found_filters, "all_buttons": btns})

    # A-03: Tap cricket filter
    cricket_msg = None
    for row in (msg.buttons or []):
        for btn in row:
            if "🏏" in (btn.text or ""):
                try:
                    await btn.click()
                except Exception as e:
                    log.debug("Cricket filter click warning (non-fatal): %s", e)
                # Always wait and fetch latest regardless of click error
                await asyncio.sleep(4)
                messages = await client.get_messages(BOT, limit=5)
                for m in messages:
                    if not m.out:
                        cricket_msg = m
                        break
                break

    if cricket_msg:
        ctext = cricket_msg.text or cricket_msg.message or ""
        save_capture("A03_my_matches_cricket", ctext, get_buttons_text(cricket_msg))
        leaks = check_prompt_leaks(ctext)
        cricket_matches = bool(re.search(r"\[?\d+\]?.*vs", ctext, re.IGNORECASE))

        record("A-03", "Cricket filter works",
               "PASS" if cricket_matches else "WARN",
               ctext,
               {"cricket_matches": cricket_matches, "prompt_leaks": leaks,
                "content_length": len(ctext)},
               "" if cricket_matches else "No cricket matches shown after filter")

        if leaks:
            file_bug("BUG-0G-003", "P0", "A-03", "prompt_leak",
                     f"Cricket filter leaks: {leaks}", ctext[:500])
    else:
        record("A-03", "Cricket filter works", "SKIP", "",
               {"reason": "Could not click cricket filter"})

    # A-04: Check for broadcast info in matches
    has_broadcast = "📺" in text or "SS " in text or "DStv" in text
    record("A-04", "Broadcast info present", "PASS" if has_broadcast else "WARN",
           text[:500], {"has_broadcast": has_broadcast})

    return msg


# ── Test: Top Edge Picks (Screen B) ──────────────────────────────────

async def test_top_edge_picks(client):
    """B: Test Top Edge Picks screen."""
    log.info("=" * 60)
    log.info("SCREEN B: Top Edge Picks")
    log.info("=" * 60)

    # B-01: Send "💎 Top Edge Picks"
    msg = await send_and_wait(client, "💎 Top Edge Picks", timeout=AI_TIMEOUT)
    if not msg:
        record("B-01", "Top Edge Picks loads", "FAIL", "", {"loaded": False},
               "No response from bot")
        file_bug("BUG-0G-010", "P1", "B-01", "empty_screen",
                 "Top Edge Picks returns no response", "")
        return None

    # Wait for spinner to complete
    text = msg.text or msg.message or ""
    if "..." in text or "analysing" in text.lower() or len(text) < 50:
        log.info("  Waiting for spinner to complete...")
        msg = await wait_for_stable_response(client) or msg
        text = msg.text or msg.message or ""

    btns = get_buttons_text(msg)
    btn_data = get_buttons_data(msg)
    save_capture("B01_top_edge_picks", text, btns)

    leaks = check_prompt_leaks(text)
    has_tips = bool(re.search(r"\[?\d+\]?", text))
    has_edge_badge = any(e in text for e in ["💎", "🥇", "🥈", "🥉"])
    has_odds = bool(re.search(r"\d+\.\d{2}", text))

    checks = {
        "loaded": bool(text),
        "has_tips": has_tips,
        "has_edge_badge": has_edge_badge,
        "has_odds": has_odds,
        "prompt_leaks": leaks,
        "button_count": len(btns),
        "content_length": len(text),
    }

    if leaks:
        file_bug("BUG-0G-011", "P0", "B-01", "prompt_leak",
                 f"Top Edge Picks leaks: {leaks}", text[:500])

    if has_tips:
        record("B-01", "Top Edge Picks shows tips", "PASS", text, checks)
    elif "no value bets" in text.lower() or "no tips" in text.lower():
        record("B-01", "Top Edge Picks (no tips found)", "WARN", text, checks,
               "No tips found — empty state")
    else:
        record("B-01", "Top Edge Picks loads", "PASS" if text else "FAIL", text, checks)

    # B-02: Check edge tier grouping
    tier_headers = []
    for tier, (emoji, label) in EDGE_BADGES.items():
        if label in text:
            tier_headers.append(tier)
    record("B-02", "Edge tier grouping",
           "PASS" if tier_headers else "WARN",
           text[:500], {"tier_headers": tier_headers},
           "Tips grouped by tier" if tier_headers else "No tier grouping visible")

    # B-03: Check for bookmaker names (should show real bookmaker, not just "Betway")
    bookmaker_names = ["Hollywoodbets", "Supabets", "Sportingbet", "GBets", "WSB",
                       "Betway", "SuperSportBet", "Playabets"]
    found_bookmakers = [b for b in bookmaker_names if b.lower() in text.lower()]
    record("B-03", "Multi-bookmaker display",
           "PASS" if len(found_bookmakers) >= 1 else "WARN",
           text[:500], {"bookmakers_found": found_bookmakers})

    # B-04: Check for broadcast/kickoff info
    has_broadcast = "📺" in text
    has_kickoff = "⏰" in text or bool(re.search(r"\d{1,2}:\d{2}", text))
    record("B-04", "Broadcast/kickoff in tips",
           "PASS" if (has_broadcast or has_kickoff) else "WARN",
           text[:300], {"has_broadcast": has_broadcast, "has_kickoff": has_kickoff})

    # B-05: Try to tap the first tip for detail view
    tip_detail_msg = None
    tip_data = [d for d in btn_data if d.startswith("tip:detail:")]
    if tip_data:
        tip_detail_msg = await click_callback_button(client, msg, "tip:detail:")
    elif btns:
        # Try clicking first numbered tip button
        for b in btns:
            if "🔍" in b or "detail" in b.lower():
                tip_detail_msg = await click_button(client, msg, b)
                break

    if tip_detail_msg:
        td_text = tip_detail_msg.text or tip_detail_msg.message or ""
        # Wait for spinner if needed
        if "..." in td_text or len(td_text) < 50:
            tip_detail_msg = await wait_for_stable_response(client) or tip_detail_msg
            td_text = tip_detail_msg.text or tip_detail_msg.message or ""

        save_capture("B05_tip_detail", td_text, get_buttons_text(tip_detail_msg))
        leaks = check_prompt_leaks(td_text)
        td_checks = {
            "loaded": bool(td_text),
            "has_odds": bool(re.search(r"\d+\.\d{2}", td_text)),
            "has_edge_badge": any(e in td_text for e in ["💎", "🥇", "🥈", "🥉"]),
            "prompt_leaks": leaks,
            "content_length": len(td_text),
        }

        if leaks:
            file_bug("BUG-0G-012", "P0", "B-05", "prompt_leak",
                     f"Tip detail leaks: {leaks}", td_text[:500])

        record("B-05", "Tip detail view", "PASS" if td_text else "FAIL",
               td_text, td_checks)
    else:
        record("B-05", "Tip detail view", "SKIP", "",
               {"reason": "No tip detail button found"})

    return msg


# ── Test: Game Breakdown (Screen C) ──────────────────────────────────

async def test_game_breakdown(client, my_matches_msg: Message | None):
    """C: Test Game Breakdown — tap a match from My Matches."""
    log.info("=" * 60)
    log.info("SCREEN C: Game Breakdown")
    log.info("=" * 60)

    # First go back to My Matches if needed
    if not my_matches_msg or not my_matches_msg.buttons:
        my_matches_msg = await send_and_wait(client, "⚽ My Matches")

    if not my_matches_msg:
        record("C-01", "Navigate to My Matches", "FAIL", "", {},
               "Could not load My Matches")
        return

    # C-01: Find and tap a match (look for yg:game: buttons)
    btn_data = get_buttons_data(my_matches_msg)
    game_buttons = [d for d in btn_data if d.startswith("yg:game:")]

    if not game_buttons:
        record("C-01", "Find game buttons", "WARN", str(btn_data),
               {"game_buttons": 0, "all_buttons": btn_data},
               "No yg:game: buttons found in My Matches")
        return

    log.info("  Found %d game buttons: %s", len(game_buttons), game_buttons[:5])

    # Tap the first match
    game_msg = await click_callback_button(client, my_matches_msg, "yg:game:")
    if not game_msg:
        record("C-01", "Tap first match", "FAIL", "",
               {"reason": "Button click returned no response"})
        return

    # C-02: Wait for AI breakdown to complete
    gtext = game_msg.text or game_msg.message or ""
    if "..." in gtext or "analysing" in gtext.lower() or len(gtext) < 80:
        log.info("  Waiting for AI analysis (up to 60s)...")
        game_msg = await wait_for_stable_response(client) or game_msg
        gtext = game_msg.text or game_msg.message or ""

    gbtns = get_buttons_text(game_msg)
    gbtn_data = get_buttons_data(game_msg)
    save_capture("C02_game_breakdown", gtext, gbtns)

    # C-02: Check for prompt leaks
    leaks = check_prompt_leaks(gtext)
    has_setup = "📋" in gtext or "The Setup" in gtext
    has_edge = "🎯" in gtext or "The Edge" in gtext
    has_risk = "⚠️" in gtext or "The Risk" in gtext
    has_verdict = "🏆" in gtext or "Verdict" in gtext
    has_odds = bool(re.search(r"\d+\.\d{2}", gtext))
    has_sections = sum([has_setup, has_edge, has_risk, has_verdict])

    checks = {
        "loaded": bool(gtext),
        "has_ai_narrative": has_sections >= 2,
        "sections": {"setup": has_setup, "edge": has_edge, "risk": has_risk, "verdict": has_verdict},
        "has_odds": has_odds,
        "prompt_leaks": leaks,
        "content_length": len(gtext),
    }

    if leaks:
        file_bug("BUG-0G-020", "P0", "C-02", "prompt_leak",
                 f"Game Breakdown leaks prompt text: {leaks}", gtext[:800])
        record("C-02", "Game Breakdown — prompt leaks", "FAIL", gtext, checks)
    elif has_sections >= 2:
        record("C-02", "Game Breakdown — AI narrative", "PASS", gtext, checks)
    elif "no sa bookmaker odds" in gtext.lower():
        record("C-02", "Game Breakdown — no odds fallback", "WARN", gtext, checks,
               "Fallback shown: no SA bookmaker odds")
    else:
        record("C-02", "Game Breakdown loads", "PASS" if gtext else "FAIL", gtext, checks)

    # C-03: Check for ugly/unhelpful fallback text
    ugly_patterns = [
        r"couldn.?t fetch",
        r"error occurred",
        r"something went wrong",
        r"try again later",
        r"no data available",
        r"cannot provide",
        r"unable to",
        r"I don.?t have",
        r"I cannot",
        r"not available",
        r"form data unavailable",
    ]
    ugly_matches = []
    for p in ugly_patterns:
        if re.search(p, gtext, re.IGNORECASE):
            ugly_matches.append(p)

    if ugly_matches:
        file_bug("BUG-0G-021", "P2", "C-03", "unhelpful_fallback",
                 f"Unhelpful text found: {ugly_matches}", gtext[:500])
        record("C-03", "No unhelpful fallback text", "FAIL", gtext[:500],
               {"ugly_patterns_found": ugly_matches})
    else:
        record("C-03", "No unhelpful fallback text", "PASS", gtext[:200],
               {"ugly_patterns_found": []})

    # C-04: Check CTA button format
    cta_buttons = [b for b in gbtns if "bet on" in b.lower() or "📲" in b]
    has_compare = any("compare" in b.lower() or "📊" in b.lower() for b in gbtns)
    has_back = any("back" in b.lower() or "↩️" in b for b in gbtns)

    record("C-04", "Button layout (CTA + Compare + Back)",
           "PASS" if (cta_buttons or has_compare) and has_back else "WARN",
           str(gbtns),
           {"cta_buttons": cta_buttons, "has_compare": has_compare, "has_back": has_back})

    # C-05: Check broadcast info
    has_broadcast = "📺" in gtext
    has_kickoff = "⏰" in gtext or bool(re.search(r"\d{1,2}:\d{2}", gtext))
    record("C-05", "Broadcast/kickoff in breakdown",
           "PASS" if (has_broadcast or has_kickoff) else "WARN",
           gtext[:300], {"has_broadcast": has_broadcast, "has_kickoff": has_kickoff})

    return game_msg, gbtn_data


# ── Test: Odds Comparison (Screen D) ─────────────────────────────────

async def test_odds_comparison(client, game_msg_data):
    """D: Test Odds Comparison screen."""
    log.info("=" * 60)
    log.info("SCREEN D: Odds Comparison")
    log.info("=" * 60)

    if not game_msg_data:
        record("D-01", "Navigate to Odds Comparison", "SKIP", "",
               {"reason": "No game breakdown available"})
        return

    game_msg, gbtn_data = game_msg_data

    # D-01: Find and tap "Compare Odds" or "📊" button
    compare_data = [d for d in gbtn_data if d.startswith("odds:compare:")]
    if not compare_data:
        record("D-01", "Find odds compare button", "WARN", str(gbtn_data),
               {"compare_buttons": 0},
               "No odds:compare: button found (may not have odds data)")
        return

    cmp_msg = await click_callback_button(client, game_msg, "odds:compare:")
    if not cmp_msg:
        record("D-01", "Tap odds compare button", "FAIL", "",
               {"reason": "Click returned no response"})
        return

    ctext = cmp_msg.text or cmp_msg.message or ""
    # Wait for potential spinner
    if len(ctext) < 50:
        await asyncio.sleep(3)
        messages = await client.get_messages(BOT, limit=3)
        for m in messages:
            if not m.out:
                cmp_msg = m
                ctext = m.text or m.message or ""
                break

    cbtns = get_buttons_text(cmp_msg)
    save_capture("D01_odds_comparison", ctext, cbtns)

    leaks = check_prompt_leaks(ctext)
    has_odds = bool(re.search(r"\d+\.\d{2}", ctext))
    bookmaker_names = ["Hollywoodbets", "Supabets", "Sportingbet", "GBets", "WSB",
                       "Betway", "SuperSportBet", "Playabets"]
    found_bookmakers = [b for b in bookmaker_names if b.lower() in ctext.lower()]
    has_multiple_bk = len(found_bookmakers) >= 2
    has_markets = any(m in ctext.lower() for m in ["home win", "draw", "away win",
                                                     "match winner", "🏠", "🤝", "🏟️"])

    checks = {
        "loaded": bool(ctext),
        "has_odds": has_odds,
        "bookmakers_found": found_bookmakers,
        "has_multiple_bookmakers": has_multiple_bk,
        "has_markets": has_markets,
        "prompt_leaks": leaks,
    }

    if leaks:
        file_bug("BUG-0G-030", "P0", "D-01", "prompt_leak",
                 f"Odds Comparison leaks: {leaks}", ctext[:500])

    if has_odds and has_multiple_bk:
        record("D-01", "Odds Comparison shows multi-bookmaker", "PASS", ctext, checks)
    elif has_odds:
        record("D-01", "Odds Comparison shows odds (limited BK)", "WARN", ctext, checks,
               f"Only {len(found_bookmakers)} bookmaker(s)")
    else:
        record("D-01", "Odds Comparison loads", "PASS" if ctext else "FAIL", ctext, checks)

    # D-02: Check for back button
    has_back = any("back" in b.lower() or "↩️" in b for b in cbtns)
    record("D-02", "Odds Comparison has back button",
           "PASS" if has_back else "WARN", str(cbtns), {"has_back": has_back})

    # D-03: Check for affiliate CTA buttons
    cta_btns = [b for b in cbtns if "📲" in b or "bet on" in b.lower()]
    record("D-03", "Odds Comparison has affiliate CTAs",
           "PASS" if cta_btns else "WARN", str(cbtns),
           {"cta_buttons": cta_btns})


# ── Test: Cricket Specifically (Screen E) ─────────────────────────────

async def test_cricket_breakdown(client):
    """E: Specifically test cricket game breakdown — the founder's reported bug."""
    log.info("=" * 60)
    log.info("SCREEN E: Cricket Game Breakdown (Founder Bug)")
    log.info("=" * 60)

    # E-01: Go to My Matches → Cricket filter
    msg = await send_and_wait(client, "⚽ My Matches")
    if not msg:
        record("E-01", "Load My Matches for cricket", "FAIL", "", {})
        return

    # Click cricket filter
    cricket_msg = None
    for row in (msg.buttons or []):
        for btn in row:
            if "🏏" in (btn.text or ""):
                try:
                    await btn.click()
                except Exception:
                    pass
                await asyncio.sleep(4)
                messages = await client.get_messages(BOT, limit=5)
                for m in messages:
                    if not m.out:
                        cricket_msg = m
                        break
                break

    if not cricket_msg:
        record("E-01", "Cricket filter", "SKIP", "",
               {"reason": "Could not click cricket filter"})
        # Try direct approach — look for any cricket game button
        cricket_msg = msg

    ctext = cricket_msg.text or cricket_msg.message or ""
    btn_data = get_buttons_data(cricket_msg)
    game_buttons = [d for d in btn_data if d.startswith("yg:game:")]

    if not game_buttons:
        record("E-01", "Find cricket matches", "WARN", ctext,
               {"game_buttons_found": 0},
               "No cricket matches in My Matches")
        return

    # E-02: Tap a cricket match
    game_msg = await click_callback_button(client, cricket_msg, "yg:game:")
    if not game_msg:
        record("E-02", "Tap cricket match", "FAIL", "", {})
        return

    gtext = game_msg.text or game_msg.message or ""
    if "..." in gtext or "analysing" in gtext.lower() or len(gtext) < 80:
        log.info("  Waiting for cricket AI analysis (up to 60s)...")
        game_msg = await wait_for_stable_response(client) or game_msg
        gtext = game_msg.text or game_msg.message or ""

    save_capture("E02_cricket_breakdown", gtext, get_buttons_text(game_msg))

    # E-02: THE CRITICAL CHECK — prompt leaks in cricket
    leaks = check_prompt_leaks(gtext)
    has_sections = sum([
        "📋" in gtext, "🎯" in gtext, "⚠️" in gtext, "🏆" in gtext
    ])

    checks = {
        "loaded": bool(gtext),
        "has_ai_narrative": has_sections >= 2,
        "prompt_leaks": leaks,
        "content_length": len(gtext),
    }

    if leaks:
        file_bug("BUG-0G-040", "P0", "E-02", "prompt_leak",
                 f"CRICKET BREAKDOWN LEAKS PROMPT: {leaks}\n\n"
                 "This is the exact bug the founder reported — AI output contains "
                 "internal prompt language like VERIFIED_DATA/ODDS_DATA",
                 gtext[:1000])
        record("E-02", "Cricket breakdown — PROMPT LEAK", "FAIL", gtext, checks,
               "THE FOUNDER BUG: AI leaks internal prompt language")
    elif has_sections >= 2:
        record("E-02", "Cricket breakdown — AI narrative", "PASS", gtext, checks)
    elif "no sa bookmaker odds" in gtext.lower():
        record("E-02", "Cricket breakdown — no odds", "WARN", gtext, checks,
               "Cricket match has no SA bookmaker odds")
    else:
        record("E-02", "Cricket breakdown loads", "PASS" if gtext else "FAIL",
               gtext, checks)

    # E-03: Check for cricket-specific wrong-sport terms
    soccer_terms = ["clean sheet", "penalty kick", "corner kick", "offside",
                    "free kick", "yellow card", "red card"]
    rugby_terms = ["try line", "lineout", "scrum", "ruck", "maul", "conversion"]
    wrong_sport = []
    for term in soccer_terms + rugby_terms:
        if term.lower() in gtext.lower():
            wrong_sport.append(term)

    if wrong_sport:
        file_bug("BUG-0G-041", "P1", "E-03", "wrong_sport_terms",
                 f"Cricket analysis uses wrong-sport terms: {wrong_sport}", gtext[:500])
        record("E-03", "No wrong-sport terms in cricket", "FAIL", gtext[:300],
               {"wrong_terms": wrong_sport})
    else:
        record("E-03", "No wrong-sport terms in cricket", "PASS", gtext[:200],
               {"wrong_terms": []})

    # E-04: Check for unhelpful fallback
    ugly_patterns = [
        r"VERIFIED.?DATA",
        r"ODDS.?DATA",
        r"cannot provide analysis",
        r"I don.?t have",
        r"form data unavailable",
    ]
    ugly = [p for p in ugly_patterns if re.search(p, gtext, re.IGNORECASE)]
    if ugly:
        file_bug("BUG-0G-042", "P1", "E-04", "unhelpful_fallback",
                 f"Cricket breakdown has unhelpful text: {ugly}", gtext[:500])
        record("E-04", "Cricket fallback is helpful", "FAIL", gtext[:300],
               {"ugly_patterns": ugly})
    else:
        record("E-04", "Cricket fallback is helpful", "PASS", gtext[:200],
               {"ugly_patterns": []})


# ── Test: Data Gap Analysis (Screen F) ────────────────────────────────

async def test_data_gaps(client):
    """F: Check data coverage across all sports in the live bot."""
    log.info("=" * 60)
    log.info("SCREEN F: Data Gap Analysis")
    log.info("=" * 60)

    # F-01: Query DB for coverage stats
    from config import ODDS_DB_PATH
    from db_connection import get_connection
    conn = get_connection(str(ODDS_DB_PATH))
    c = conn.cursor()

    # Matches per league with bookmaker count
    c.execute("""
        SELECT league, COUNT(DISTINCT match_id) as matches,
               COUNT(DISTINCT bookmaker) as bookmakers,
               MAX(scraped_at) as last_scrape
        FROM odds_snapshots
        WHERE scraped_at > datetime('now', '-2 days')
        GROUP BY league
        ORDER BY matches DESC
    """)
    league_coverage = c.fetchall()

    # Broadcast coverage
    c.execute("""
        SELECT COUNT(*) FROM broadcast_schedule
        WHERE start_time > datetime('now')
    """)
    upcoming_broadcasts = c.fetchone()[0]

    # Matches with odds but no broadcast
    c.execute("""
        SELECT DISTINCT os.match_id, os.home_team, os.away_team, os.league
        FROM odds_snapshots os
        LEFT JOIN broadcast_schedule bs ON (
            bs.programme_title LIKE '%' || REPLACE(os.home_team, '_', ' ') || '%'
            OR bs.programme_title LIKE '%' || REPLACE(os.away_team, '_', ' ') || '%'
        )
        WHERE os.scraped_at > datetime('now', '-1 day')
          AND bs.id IS NULL
        LIMIT 10
    """)
    no_broadcast = c.fetchall()

    conn.close()

    checks = {
        "leagues_covered": len(league_coverage),
        "upcoming_broadcasts": upcoming_broadcasts,
        "coverage": {r[0]: {"matches": r[1], "bookmakers": r[2], "last_scrape": r[3][:16]}
                     for r in league_coverage},
        "no_broadcast_matches": len(no_broadcast),
    }

    # F-01: League coverage
    record("F-01", "Odds coverage across leagues",
           "PASS" if len(league_coverage) >= 8 else "WARN",
           json.dumps(checks["coverage"], indent=2),
           checks)

    # F-02: Cricket coverage specifically
    cricket_leagues = [r for r in league_coverage if r[0] in ("test_cricket", "sa20", "t20_world_cup")]
    cricket_matches = sum(r[1] for r in cricket_leagues)
    record("F-02", f"Cricket coverage ({cricket_matches} matches across {len(cricket_leagues)} leagues)",
           "PASS" if cricket_matches >= 10 else "WARN",
           str(cricket_leagues),
           {"cricket_matches": cricket_matches, "cricket_leagues": [r[0] for r in cricket_leagues]})

    # F-03: Combat coverage
    combat_leagues = [r for r in league_coverage if r[0] in ("boxing", "ufc")]
    combat_matches = sum(r[1] for r in combat_leagues)
    record("F-03", f"Combat coverage ({combat_matches} matches)",
           "PASS" if combat_matches >= 10 else "WARN",
           str(combat_leagues),
           {"combat_matches": combat_matches})

    # F-04: Broadcast coverage
    record("F-04", f"Broadcast schedule ({upcoming_broadcasts} upcoming)",
           "PASS" if upcoming_broadcasts >= 100 else "WARN",
           f"{upcoming_broadcasts} upcoming broadcasts",
           {"upcoming_broadcasts": upcoming_broadcasts})


# ── Main runner ───────────────────────────────────────────────────────

async def run_all_tests():
    """Run all Phase 0G tests."""
    log.info("Phase 0G: Match Screen Audit — Starting")
    log.info("=" * 60)

    session_str = SESSION_PATH.read_text().strip()
    client = TelegramClient(StringSession(session_str), API_ID, API_HASH)

    try:
        await client.connect()
        if not await client.is_user_authorized():
            log.error("Telethon session not authorized. Run save_telegram_session.py first.")
            return

        log.info("Connected to Telegram as user")

        # Run data gap analysis first (doesn't need Telethon)
        await test_data_gaps(client)

        # Screen A: My Matches
        my_matches_msg = await test_my_matches(client)
        await asyncio.sleep(2)

        # Screen B: Top Edge Picks
        await test_top_edge_picks(client)
        await asyncio.sleep(2)

        # Screen C: Game Breakdown (uses match from My Matches)
        game_data = await test_game_breakdown(client, my_matches_msg)
        await asyncio.sleep(2)

        # Screen D: Odds Comparison (uses game from breakdown)
        await test_odds_comparison(client, game_data)
        await asyncio.sleep(2)

        # Screen E: Cricket (the founder's bug)
        await test_cricket_breakdown(client)

    except FloodWaitError as e:
        log.error("Telegram flood wait: %d seconds", e.seconds)
        record("FLOOD", "Flood wait", "FAIL", str(e), {"wait_seconds": e.seconds})
    except Exception as e:
        log.error("Test runner error: %s", e, exc_info=True)
        record("ERROR", "Test runner error", "FAIL", str(e), {})
    finally:
        await client.disconnect()

    # ── Summary ──
    log.info("")
    log.info("=" * 60)
    log.info("PHASE 0G RESULTS SUMMARY")
    log.info("=" * 60)

    total = len(results)
    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    warned = sum(1 for r in results if r["status"] == "WARN")
    skipped = sum(1 for r in results if r["status"] == "SKIP")

    log.info("Total: %d | PASS: %d | FAIL: %d | WARN: %d | SKIP: %d",
             total, passed, failed, warned, skipped)
    log.info("")

    if bugs:
        log.info("BUGS FILED: %d", len(bugs))
        for b in bugs:
            log.info("  %s [%s] %s: %s", b["id"], b["severity"], b["category"],
                     b["description"][:80])
    else:
        log.info("No bugs filed.")

    # Save results
    report = {
        "phase": "0G",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "summary": {
            "total": total, "passed": passed, "failed": failed,
            "warned": warned, "skipped": skipped,
            "bugs_filed": len(bugs),
        },
        "results": results,
        "bugs": bugs,
        "raw_captures": raw_captures,
    }
    RESULTS_PATH.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    log.info("Results saved to %s", RESULTS_PATH)
    log.info("Screenshots saved to %s", SCREENSHOT_DIR)

    return report


if __name__ == "__main__":
    report = asyncio.run(run_all_tests())
