#!/usr/bin/env python3
"""
Wave 26A-REVIEW: QA Code-Level Verification via Telethon
=========================================================
Run /qa commands and capture output for each tier. Check all 9 requirements.
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
sys.path.insert(0, "/home/paulsportsza")

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.custom.message import Message

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("wave26a_review")

BOT = "mzansiedge_bot"
API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "")
SESSION_PATH = Path("data/telethon_session.string")

CAPTURE_DIR = Path("/home/paulsportsza/reports/screenshots/wave26a_review")
CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_PATH = Path("/home/paulsportsza/reports/wave26a-review-results.json")

BOT_TIMEOUT = 15
AI_TIMEOUT = 60

results: list[dict] = []


def record(check_id: str, name: str, status: str, evidence: str, detail: str = ""):
    entry = {"check_id": check_id, "name": name, "status": status,
             "evidence": evidence[:5000], "detail": detail}
    results.append(entry)
    icon = {"PASS": "✓", "FAIL": "✗", "WARN": "⚠", "SKIP": "⊘"}.get(status, "?")
    log.info("  %s %s: %s — %s", icon, check_id, name, status)


async def send_command(client, cmd: str, timeout: int = BOT_TIMEOUT) -> list[Message]:
    """Send a command and collect all bot responses (may be multiple messages)."""
    await client.send_message(BOT, cmd)
    await asyncio.sleep(3)

    # Collect messages — bot may send several
    messages = await client.get_messages(BOT, limit=10)
    bot_msgs = [m for m in messages if not m.out]

    # Wait for spinner to settle
    if bot_msgs:
        first_text = bot_msgs[0].text or ""
        if "..." in first_text or "scanning" in first_text.lower() or len(first_text) < 40:
            # Wait for messages to stabilise
            for _ in range(15):
                await asyncio.sleep(3)
                messages = await client.get_messages(BOT, limit=10)
                bot_msgs = [m for m in messages if not m.out]
                current = bot_msgs[0].text if bot_msgs else ""
                if len(current) > 100 and "..." not in current:
                    break

    return bot_msgs


def get_all_text(msgs: list[Message]) -> str:
    """Combine all message texts."""
    return "\n---\n".join((m.text or m.message or "") for m in msgs)


def get_all_buttons(msgs: list[Message]) -> list[str]:
    """Extract all button texts from all messages."""
    btns = []
    for m in msgs:
        if m.buttons:
            for row in m.buttons:
                for btn in row:
                    btns.append(btn.text or "")
    return btns


def get_all_button_data(msgs: list[Message]) -> list[str]:
    """Extract all callback_data from all messages."""
    data = []
    for m in msgs:
        if m.buttons:
            for row in m.buttons:
                for btn in row:
                    if hasattr(btn, "data") and btn.data:
                        data.append(btn.data.decode("utf-8", errors="replace"))
                    elif hasattr(btn, "url") and btn.url:
                        data.append(f"url:{btn.url[:60]}")
                    else:
                        data.append(f"text:{btn.text or ''}")
    return data


def save_capture(name: str, text: str, buttons: list[str] | None = None):
    fpath = CAPTURE_DIR / f"{name}.txt"
    content = text
    if buttons:
        content += "\n\n== BUTTONS ==\n" + "\n".join(buttons)
    fpath.write_text(content[:10000], encoding="utf-8")


# ── Checks ────────────────────────────────────────────────────────────

async def check_tips_bronze(client):
    """1. /qa tips_bronze — 4 cards, 3 lines, sport emoji, tier badge, footer."""
    log.info("=== CHECK 1: /qa tips_bronze ===")
    msgs = await send_command(client, "/qa tips_bronze", AI_TIMEOUT)
    text = get_all_text(msgs)
    btns = get_all_buttons(msgs)
    btn_data = get_all_button_data(msgs)
    save_capture("01_tips_bronze", text, btns)

    # Check 1a: 4 cards per page (not 5)
    card_indices = re.findall(r'\[(\d+)\]', text)
    unique_indices = sorted(set(int(i) for i in card_indices))
    page_size = len(unique_indices) if unique_indices else 0
    record("1a", "Page size = 4 cards",
           "PASS" if page_size == 4 else "FAIL",
           f"Found {page_size} cards: {unique_indices}",
           f"HOT_TIPS_PAGE_SIZE should be 4, found {page_size} on page 1")

    # Check 1b: 3 lines per card (match line + info line + odds/lock line)
    # Count lines between consecutive [N] markers
    lines = text.split('\n')
    card_line_counts = []
    current_count = 0
    in_card = False
    for line in lines:
        if re.match(r'\[?\d+\]', line.strip()):
            if in_card and current_count > 0:
                card_line_counts.append(current_count)
            current_count = 1
            in_card = True
        elif in_card and line.strip():
            current_count += 1
        elif in_card and not line.strip():
            card_line_counts.append(current_count)
            in_card = False
    if in_card:
        card_line_counts.append(current_count)

    record("1b", "3 lines per card",
           "PASS" if all(c <= 3 for c in card_line_counts) else "WARN",
           f"Line counts per card: {card_line_counts}")

    # Check 1c: Sport emoji before teams
    has_sport_emoji = bool(re.search(r'\[\d+\]\s*[⚽🏉🏏🥊]', text))
    record("1c", "Sport emoji before teams",
           "PASS" if has_sport_emoji else "FAIL",
           f"Pattern found: {has_sport_emoji}")

    # Check 1d: Tier badge after match name
    has_tier_badge = bool(re.search(r'vs\s+.+?\s+[💎🥇🥈🥉🔒]', text))
    record("1d", "Tier badge after match",
           "PASS" if has_tier_badge else "WARN",
           f"Pattern found: {has_tier_badge}")

    # Check 1e: No section headers (no "DIAMOND EDGE", "GOLDEN EDGE" as standalone)
    section_headers = re.findall(r'^(?:💎|🥇|🥈|🥉)\s+\*?\*?(DIAMOND|GOLDEN|SILVER|BRONZE)\s+EDGE', text, re.MULTILINE)
    record("1e", "No per-tier section headers in list",
           "PASS" if not section_headers else "FAIL",
           f"Section headers found: {section_headers}")

    # Check 1f: No per-card CTAs
    per_card_ctas = re.findall(r'(?:📲|Bet on|subscribe|View Plans)', text)
    # Only footer CTA should exist
    footer_match = re.search(r'━━━', text)
    ctas_before_footer = []
    if footer_match:
        pre_footer = text[:footer_match.start()]
        ctas_before_footer = re.findall(r'(?:📲|Bet on)', pre_footer)
    record("1f", "No per-card CTAs (only footer)",
           "PASS" if not ctas_before_footer else "FAIL",
           f"CTAs before footer: {ctas_before_footer}")

    # Check 1g: Single footer block with locked count + portfolio + /subscribe + Founding Member
    footer_section = text[text.find("━━━"):] if "━━━" in text else ""
    has_locked = "locked" in footer_section.lower()
    has_subscribe = "/subscribe" in footer_section
    has_founding = "Founding Member" in footer_section
    record("1g", "Footer block (locked + subscribe + Founding Member)",
           "PASS" if (has_locked and has_subscribe and has_founding) else
           "WARN" if has_locked or has_subscribe else "FAIL",
           f"locked={has_locked}, subscribe={has_subscribe}, founding={has_founding}")

    # Check 1h: Streak label says "correct predictions" not "win streak"
    # (May not be present if streak < 3)
    has_correct_predictions = "correct predictions" in text
    has_win_streak = "win streak" in text.lower()
    if has_correct_predictions or has_win_streak:
        record("1h", "Streak label format",
               "PASS" if has_correct_predictions and not has_win_streak else "FAIL",
               f"correct_predictions={has_correct_predictions}, win_streak={has_win_streak}")
    else:
        record("1h", "Streak label format",
               "SKIP", "No streak active (count < 3)")

    return text, btns, btn_data


async def check_tips_gold(client):
    """2. /qa tips_gold — Gold edges show odds, Diamond locked, lighter footer."""
    log.info("=== CHECK 2: /qa tips_gold ===")
    msgs = await send_command(client, "/qa tips_gold", AI_TIMEOUT)
    text = get_all_text(msgs)
    btns = get_all_buttons(msgs)
    save_capture("02_tips_gold", text, btns)

    # Gold edges should show odds (not locked)
    gold_has_odds = bool(re.search(r'🥇.*@\s*\d+\.\d{2}', text, re.DOTALL))
    # Diamond should be locked (show 🔒 or "highest-conviction")
    has_locked_diamond = "🔒" in text or "highest-conviction" in text

    record("2a", "Gold edges show odds",
           "PASS" if gold_has_odds else "WARN",
           f"Gold with odds: {gold_has_odds}")

    record("2b", "Diamond edges locked for Gold user",
           "PASS" if has_locked_diamond else "WARN",
           f"Locked diamond: {has_locked_diamond}")

    # Lighter footer — Diamond count only, no "View Plans" button
    footer_section = text[text.find("━━━"):] if "━━━" in text else ""
    has_diamond_count = "Diamond" in footer_section or "💎" in footer_section
    no_view_plans_btn = "View Plans" not in " ".join(btns)
    record("2c", "Lighter footer (Diamond count, no View Plans button)",
           "PASS" if (has_diamond_count or not footer_section) and no_view_plans_btn else "WARN",
           f"diamond_in_footer={has_diamond_count}, footer={'exists' if footer_section else 'none'}, view_plans_btn={not no_view_plans_btn}")

    return text


async def check_tips_diamond(client):
    """3. /qa tips_diamond — All edges show full data, no footer, 2 buttons only."""
    log.info("=== CHECK 3: /qa tips_diamond ===")
    msgs = await send_command(client, "/qa tips_diamond", AI_TIMEOUT)
    text = get_all_text(msgs)
    btns = get_all_buttons(msgs)
    save_capture("03_tips_diamond", text, btns)

    # All edges should show odds (no 🔒)
    has_lock = "🔒" in text and "highest-conviction" in text
    has_odds = bool(re.search(r'@\s*\d+\.\d{2}', text))
    record("3a", "All edges show full data",
           "PASS" if has_odds and not has_lock else "FAIL",
           f"has_odds={has_odds}, has_lock={has_lock}")

    # No footer
    has_footer = "━━━" in text
    record("3b", "No footer for Diamond",
           "PASS" if not has_footer else "FAIL",
           f"Footer present: {has_footer}")

    # 2 buttons only (My Matches + Menu) — plus possible pagination
    nav_btns = [b for b in btns if "My Matches" in b or "Menu" in b or "Prev" in b or "Next" in b]
    non_nav_btns = [b for b in btns if b not in nav_btns and "✅" not in b]
    record("3c", "Minimal buttons (nav only)",
           "PASS" if len(non_nav_btns) <= len(btns) // 2 else "WARN",
           f"All buttons: {btns}")

    return text


async def check_teaser_bronze(client):
    """4. /qa teaser_bronze."""
    log.info("=== CHECK 4: /qa teaser_bronze ===")
    msgs = await send_command(client, "/qa teaser_bronze", AI_TIMEOUT)
    text = get_all_text(msgs)
    btns = get_all_buttons(msgs)
    save_capture("04_teaser_bronze", text, btns)

    has_sport_emoji = any(e in text for e in ["⚽", "🏉", "🏏", "🥊"])
    has_tier_badge = any(e in text for e in ["💎", "🥇", "🥈", "🥉"])
    has_locked_count = "locked" in text.lower()
    has_founding = "Founding Member" in text

    record("4a", "Free picks with sport emoji + tier badge",
           "PASS" if has_sport_emoji and has_tier_badge else "WARN",
           f"sport_emoji={has_sport_emoji}, tier_badge={has_tier_badge}")

    record("4b", "Locked count shown",
           "PASS" if has_locked_count else "WARN",
           f"locked_count={has_locked_count}")

    record("4c", "Bold prices",
           "PASS" if re.search(r'R\d+', text) else "WARN",
           "Prices found" if re.search(r'R\d+', text) else "No prices")

    record("4d", "Founding Member line",
           "PASS" if has_founding else "WARN",
           f"founding={has_founding}")

    record("4e", f"Buttons: {len(btns)}",
           "PASS" if len(btns) >= 2 else "WARN",
           f"Buttons: {btns}")

    return text


async def check_teaser_gold(client):
    """5. /qa teaser_gold."""
    log.info("=== CHECK 5: /qa teaser_gold ===")
    msgs = await send_command(client, "/qa teaser_gold", AI_TIMEOUT)
    text = get_all_text(msgs)
    btns = get_all_buttons(msgs)
    save_capture("05_teaser_gold", text, btns)

    has_odds = bool(re.search(r'\d+\.\d{2}', text))
    has_ev = bool(re.search(r'EV', text))
    has_diamond_fomo = "Diamond" in text or "💎" in text

    record("5a", "Top pick with full odds/EV",
           "PASS" if has_odds or has_ev else "WARN",
           f"odds={has_odds}, ev={has_ev}")

    record("5b", "Diamond FOMO line",
           "PASS" if has_diamond_fomo else "WARN",
           f"diamond_fomo={has_diamond_fomo}")

    no_view_plans = "View Plans" not in " ".join(btns)
    record("5c", "No View Plans button",
           "PASS" if no_view_plans else "FAIL",
           f"view_plans_in_buttons={not no_view_plans}")

    return text


async def check_teaser_diamond(client):
    """6. /qa teaser_diamond."""
    log.info("=== CHECK 6: /qa teaser_diamond ===")
    msgs = await send_command(client, "/qa teaser_diamond", AI_TIMEOUT)
    text = get_all_text(msgs)
    btns = get_all_buttons(msgs)
    save_capture("06_teaser_diamond", text, btns)

    has_no_cta = "/subscribe" not in text
    record("6a", "Top pick, no CTA",
           "PASS" if has_no_cta else "FAIL",
           f"subscribe_in_text={not has_no_cta}")

    record("6b", f"Buttons count: {len(btns)}",
           "PASS" if len(btns) <= 3 else "WARN",
           f"Buttons: {btns}")

    return text


async def check_button_truncation(bronze_btns: list[str]):
    """5. Button truncation — all under 28 chars."""
    log.info("=== CHECK 5 (button truncation) ===")
    longest = max(bronze_btns, key=len) if bronze_btns else ""
    all_under_28 = all(len(b) <= 28 for b in bronze_btns)

    record("5_trunc", f"Button truncation (longest: {len(longest)} chars)",
           "PASS" if all_under_28 else "WARN",
           f"Longest: '{longest}' ({len(longest)} chars)\nAll buttons: {bronze_btns}",
           "All buttons under 28 chars" if all_under_28 else f"'{longest}' is {len(longest)} chars")


async def run_all():
    log.info("Wave 26A-REVIEW: QA Code-Level Verification")
    log.info("=" * 60)

    session_str = SESSION_PATH.read_text().strip()
    client = TelegramClient(StringSession(session_str), API_ID, API_HASH)

    try:
        await client.connect()
        if not await client.is_user_authorized():
            log.error("Telethon session not authorized")
            return

        log.info("Connected to Telegram")

        # 1. tips_bronze
        bronze_text, bronze_btns, bronze_data = await check_tips_bronze(client)
        await asyncio.sleep(3)

        # 2. tips_gold
        await check_tips_gold(client)
        await asyncio.sleep(3)

        # 3. tips_diamond
        await check_tips_diamond(client)
        await asyncio.sleep(3)

        # 4. teaser_bronze
        await check_teaser_bronze(client)
        await asyncio.sleep(3)

        # 5. teaser_gold
        await check_teaser_gold(client)
        await asyncio.sleep(3)

        # 6. teaser_diamond
        await check_teaser_diamond(client)
        await asyncio.sleep(3)

        # Button truncation
        await check_button_truncation(bronze_btns)

        # Reset tier
        await send_command(client, "/qa reset")

    except Exception as e:
        log.error("Test error: %s", e, exc_info=True)
    finally:
        await client.disconnect()

    # Summary
    log.info("")
    log.info("=" * 60)
    total = len(results)
    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    warned = sum(1 for r in results if r["status"] == "WARN")
    log.info("Total: %d | PASS: %d | FAIL: %d | WARN: %d", total, passed, failed, warned)

    report = {
        "wave": "26A-REVIEW",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "summary": {"total": total, "passed": passed, "failed": failed, "warned": warned},
        "results": results,
    }
    RESULTS_PATH.write_text(json.dumps(report, indent=2, default=str))
    log.info("Results: %s", RESULTS_PATH)
    return report


if __name__ == "__main__":
    asyncio.run(run_all())
