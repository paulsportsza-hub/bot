#!/usr/bin/env python3
"""
Wave 26A-REVIEW: Detail View Checks (v2)
==========================================
Taps locked/accessible edge buttons and captures the edited message.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, "/home/paulsportsza")

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.sessions import StringSession

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("wave26a_detail2")

BOT = "mzansiedge_bot"
API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "")
SESSION_PATH = Path("data/telethon_session.string")

CAPTURE_DIR = Path("/home/paulsportsza/reports/screenshots/wave26a_review")
CAPTURE_DIR.mkdir(parents=True, exist_ok=True)

results = []


def record(check_id, name, status, evidence):
    results.append({"check_id": check_id, "name": name, "status": status, "evidence": evidence[:3000]})
    icon = {"PASS": "✓", "FAIL": "✗", "WARN": "⚠"}.get(status, "?")
    log.info("  %s %s: %s — %s", icon, check_id, name, status)


async def run():
    session_str = SESSION_PATH.read_text().strip()
    client = TelegramClient(StringSession(session_str), API_ID, API_HASH)
    await client.connect()
    if not await client.is_user_authorized():
        log.error("Not authorized")
        return

    log.info("Connected.")

    # ── Step 1: Get tips_bronze, find locked button, tap it ──
    log.info("=== LOCKED DETAIL TEST ===")
    await client.send_message(BOT, "/qa tips_bronze")
    await asyncio.sleep(5)

    # Get all messages, find the Tips page (not the QA confirmation)
    msgs = await client.get_messages(BOT, limit=10)
    tips_msg = None
    for m in msgs:
        if not m.out and m.buttons:
            # The tips page has numbered edge buttons
            for row in m.buttons:
                for btn in row:
                    if "🔒" in (btn.text or ""):
                        tips_msg = m
                        break
                if tips_msg:
                    break
        if tips_msg:
            break

    if not tips_msg:
        log.error("Could not find tips_bronze message with 🔒 buttons")
        record("7", "Locked detail view", "SKIP", "No tips message found")
    else:
        tips_msg_id = tips_msg.id
        log.info("Tips message ID: %d", tips_msg_id)

        # Find first 🔒 button and click it
        locked_btn = None
        for row in tips_msg.buttons:
            for btn in row:
                if "🔒" in (btn.text or ""):
                    locked_btn = btn
                    break
            if locked_btn:
                break

        log.info("Clicking locked button: %s", locked_btn.text)
        try:
            await locked_btn.click()
        except Exception as e:
            log.warning("Click error: %s", e)

        # Wait for edit
        await asyncio.sleep(5)

        # Re-fetch the SAME message to see if it was edited
        edited_msgs = await client.get_messages(BOT, ids=[tips_msg_id])
        edited = edited_msgs[0] if edited_msgs else None

        # Also check for NEW messages after the tips message
        new_msgs = await client.get_messages(BOT, limit=10, min_id=tips_msg_id)
        new_bot_msgs = [m for m in new_msgs if not m.out]

        # The detail view could be an edit or a new message
        detail_text = ""
        detail_btns = []

        if edited and edited.text and edited.text != tips_msg.text:
            log.info("Found EDITED message (detail view via edit)")
            detail_text = edited.text or ""
            if edited.buttons:
                for row in edited.buttons:
                    for b in row:
                        detail_btns.append(b.text or "")
        elif new_bot_msgs:
            # Check new messages for the detail view (skip QA confirmation)
            for nm in new_bot_msgs:
                t = nm.text or ""
                if "QA:" not in t and len(t) > 50:
                    detail_text = t
                    if nm.buttons:
                        for row in nm.buttons:
                            for b in row:
                                detail_btns.append(b.text or "")
                    break

        if not detail_text:
            # Last resort: maybe the locked button triggers a callback answer (toast), not a page change
            # For sub:plans, it should show a plan comparison page
            log.info("No edited/new content found. Checking all recent messages...")
            all_recent = await client.get_messages(BOT, limit=15)
            for m in all_recent:
                if not m.out:
                    t = m.text or ""
                    if ("Plan" in t or "Diamond" in t or "R199" in t or "R99" in t or
                        "subscribe" in t.lower() or "upgrade" in t.lower()) and "QA:" not in t:
                        detail_text = t
                        if m.buttons:
                            for row in m.buttons:
                                for b in row:
                                    detail_btns.append(b.text or "")
                        break

        log.info("Locked detail text length: %d", len(detail_text))
        log.info("Locked detail buttons: %s", detail_btns)
        (CAPTURE_DIR / "07_detail_locked_v2.txt").write_text(
            detail_text + "\n\n== BUTTONS ==\n" + "\n".join(detail_btns))

        if detail_text:
            # Check 7a: Plan comparison or lock info
            has_plans = "R199" in detail_text or "R99" in detail_text or "Diamond" in detail_text
            record("7a", "Locked edge shows plan comparison",
                   "PASS" if has_plans else "WARN",
                   f"plans={has_plans}, text_start={detail_text[:300]}")

            # Check 7b: No bookmaker link
            has_bk_link = any("betway" in b.lower() or "hollywoodbets" in b.lower()
                             or "gbets" in b.lower() or "Bet on" in b for b in detail_btns)
            record("7b", "No bookmaker link on locked edge",
                   "PASS" if not has_bk_link else "FAIL",
                   f"bk_link={has_bk_link}")

            # Check 7c: No Compare Odds
            has_compare = any("Compare" in b or "All Odds" in b for b in detail_btns)
            record("7c", "No Compare Odds on locked edge",
                   "PASS" if not has_compare else "FAIL",
                   f"compare={has_compare}")

            # Check 7d: No prompt leak
            prompt_leak = any(p in detail_text for p in [
                "VERIFIED_DATA", "ODDS DATA", "You may ONLY", "system prompt",
                "CRITICAL RULES", "FORMATTING RULES"])
            record("7d", "No prompt leak in locked detail",
                   "PASS" if not prompt_leak else "FAIL",
                   f"prompt_leak={prompt_leak}")

            # Check 7e: No odds/EV/bookmaker text exposed
            has_odds_leak = ("EV +" in detail_text and "%" in detail_text and
                           not "R99" in detail_text)
            record("7e", "No odds/EV leak on locked edge",
                   "PASS" if not has_odds_leak else "FAIL",
                   f"ev_leak={has_odds_leak}")
        else:
            record("7a", "Locked edge response", "WARN",
                   "Could not capture detail view — may be a callback toast")

    await asyncio.sleep(3)

    # ── Step 2: Get tips_gold, tap accessible Gold edge ──
    log.info("\n=== ACCESSIBLE DETAIL TEST ===")
    await client.send_message(BOT, "/qa tips_gold")
    await asyncio.sleep(5)

    msgs = await client.get_messages(BOT, limit=10)
    tips_msg = None
    for m in msgs:
        if not m.out and m.buttons:
            for row in m.buttons:
                for btn in row:
                    if "🥇" in (btn.text or "") and "🔒" not in (btn.text or ""):
                        tips_msg = m
                        break
                if tips_msg:
                    break
        if tips_msg:
            break

    if not tips_msg:
        log.error("No accessible 🥇 button found in tips_gold")
        record("8", "Accessible detail view", "SKIP", "No Gold button found")
    else:
        tips_msg_id = tips_msg.id
        accessible_btn = None
        for row in tips_msg.buttons:
            for btn in row:
                if "🥇" in (btn.text or "") and "🔒" not in (btn.text or ""):
                    accessible_btn = btn
                    break
            if accessible_btn:
                break

        log.info("Clicking accessible button: %s", accessible_btn.text)
        try:
            await accessible_btn.click()
        except Exception as e:
            log.warning("Click error: %s", e)

        # AI breakdown takes time
        await asyncio.sleep(20)

        # Check for spinner/loading, wait more if needed
        for attempt in range(8):
            edited_msgs = await client.get_messages(BOT, ids=[tips_msg_id])
            edited = edited_msgs[0] if edited_msgs else None
            new_msgs = await client.get_messages(BOT, limit=10, min_id=tips_msg_id)
            new_bot_msgs = [m for m in new_msgs if not m.out]

            # Check both edited and new
            detail_text = ""
            if edited and edited.text and len(edited.text) > 200 and "📋" in edited.text:
                detail_text = edited.text
                break
            for nm in new_bot_msgs:
                t = nm.text or ""
                if len(t) > 200 and ("📋" in t or "Setup" in t or "Edge" in t) and "QA:" not in t:
                    detail_text = t
                    break
            if detail_text:
                break
            log.info("  Waiting for AI breakdown (attempt %d)...", attempt + 1)
            await asyncio.sleep(5)

        # Final collection
        detail_btns = []
        if not detail_text:
            # Try all recent messages
            all_recent = await client.get_messages(BOT, limit=15)
            for m in all_recent:
                if not m.out:
                    t = m.text or ""
                    if len(t) > 200 and "QA:" not in t and ("📋" in t or "SA Bookmaker" in t):
                        detail_text = t
                        if m.buttons:
                            for row in m.buttons:
                                for b in row:
                                    detail_btns.append(b.text or "")
                        break

        if not detail_text and edited:
            detail_text = edited.text or ""
            if edited.buttons:
                for row in edited.buttons:
                    for b in row:
                        detail_btns.append(b.text or "")

        log.info("Accessible detail text length: %d", len(detail_text))
        (CAPTURE_DIR / "08_detail_accessible_v2.txt").write_text(
            detail_text + "\n\n== BUTTONS ==\n" + "\n".join(detail_btns))

        if detail_text and len(detail_text) > 100:
            # Check 8a: AI breakdown sections
            sections = sum(1 for s in ["📋", "🎯", "⚠️", "🏆"] if s in detail_text)
            record("8a", "Full AI breakdown sections",
                   "PASS" if sections >= 3 else "WARN",
                   f"sections={sections}/4, text_preview={detail_text[:400]}")

            # Check 8b: Bookmaker deep link
            has_bk = any("Bet on" in b or "→" in b for b in detail_btns)
            record("8b", "Bookmaker deep link button",
                   "PASS" if has_bk else "WARN",
                   f"bk_btn={has_bk}, buttons={detail_btns}")

            # Check 8c: Compare Odds
            has_compare = any("Compare" in b or "All Odds" in b for b in detail_btns)
            record("8c", "Compare All Odds button",
                   "PASS" if has_compare else "WARN",
                   f"compare={has_compare}")

            # Check 8d: SA Bookmaker Odds
            has_odds = "SA Bookmaker" in detail_text or "Odds" in detail_text
            record("8d", "SA Bookmaker Odds visible",
                   "PASS" if has_odds else "WARN",
                   f"odds={has_odds}")

            # Check 8e: No prompt leak
            prompt_leak = any(p in detail_text for p in [
                "VERIFIED_DATA", "ODDS DATA", "You may ONLY", "system prompt",
                "CRITICAL RULES", "FORMATTING RULES"])
            record("8e", "No prompt leak in accessible detail",
                   "PASS" if not prompt_leak else "FAIL",
                   f"prompt_leak={prompt_leak}")

            # Check 8f: Signal display
            has_signals = "✅" in detail_text or "❌" in detail_text or "signal" in detail_text.lower()
            record("8f", "Signal display present",
                   "PASS" if has_signals else "WARN",
                   f"signals={has_signals}")
        else:
            record("8a", "Accessible detail view", "WARN",
                   f"Content too short ({len(detail_text)} chars). May need longer wait or different message capture.")

    # Reset
    await client.send_message(BOT, "/qa reset")
    await asyncio.sleep(2)
    await client.disconnect()

    # Summary
    log.info("")
    log.info("=" * 50)
    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    warned = sum(1 for r in results if r["status"] == "WARN")
    log.info("Detail checks: %d | PASS: %d | FAIL: %d | WARN: %d",
             len(results), passed, failed, warned)

    out = CAPTURE_DIR / "detail_results_v2.json"
    out.write_text(json.dumps(results, indent=2))
    for r in results:
        print(f"  {r['check_id']}: {r['status']} — {r['name']}")


if __name__ == "__main__":
    asyncio.run(run())
