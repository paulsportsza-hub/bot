#!/usr/bin/env python3
"""
Wave 26A-REVIEW: Detail View Checks
====================================
Tap a locked edge (from tips_bronze) and an accessible edge (from tips_gold)
to verify detail view gating.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import ensure_scrapers_importable, BOT_ROOT
ensure_scrapers_importable()

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.sessions import StringSession

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("wave26a_detail")

BOT = "mzansiedge_bot"
API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "")
SESSION_PATH = Path("data/telethon_session.string")

CAPTURE_DIR = BOT_ROOT.parent / "reports" / "screenshots" / "wave26a_review"
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

    log.info("Connected. Running detail view checks...")

    # ── Step 1: Get tips_bronze and tap a locked edge ──
    log.info("=== Sending /qa tips_bronze ===")
    await client.send_message(BOT, "/qa tips_bronze")
    await asyncio.sleep(5)

    msgs = await client.get_messages(BOT, limit=5)
    # Find the message with edge buttons (🔒 icons)
    btn_msg = None
    for m in msgs:
        if m.buttons and not m.out:
            for row in m.buttons:
                for btn in row:
                    if "🔒" in (btn.text or ""):
                        btn_msg = m
                        break
                if btn_msg:
                    break
        if btn_msg:
            break

    if not btn_msg:
        log.error("No locked button found in tips_bronze")
        record("7a", "Locked edge tap", "SKIP", "No locked button found")
    else:
        # Find first 🔒 button
        locked_btn = None
        for row in btn_msg.buttons:
            for btn in row:
                if "🔒" in (btn.text or ""):
                    locked_btn = btn
                    break
            if locked_btn:
                break

        log.info("Tapping locked button: %s", locked_btn.text)
        try:
            await locked_btn.click()
        except Exception as e:
            log.warning("Click error (expected): %s", e)

        await asyncio.sleep(5)
        msgs_after = await client.get_messages(BOT, limit=5)
        latest = None
        for m in msgs_after:
            if not m.out:
                latest = m
                break

        if latest:
            text = latest.text or latest.message or ""
            btns = []
            if latest.buttons:
                for row in latest.buttons:
                    for b in row:
                        btns.append(b.text or "")

            (CAPTURE_DIR / "07_detail_locked.txt").write_text(
                text + "\n\n== BUTTONS ==\n" + "\n".join(btns))

            # Check 7a: Setup visible
            has_setup = "📋" in text or "Setup" in text
            record("7a", "Setup section visible on locked edge",
                   "PASS" if has_setup else "WARN",
                   f"has_setup={has_setup}")

            # Check 7b: Edge/Risk/Verdict show lock (no AI text)
            has_lock_line = "🔒" in text and ("Available on" in text or "Unlock" in text)
            record("7b", "Edge/Risk/Verdict show lock line",
                   "PASS" if has_lock_line else "WARN",
                   f"has_lock={has_lock_line}, text_preview={text[:500]}")

            # Check 7c: No bookmaker link
            has_bk_link = any("betway" in b.lower() or "hollywoodbets" in b.lower()
                             or "gbets" in b.lower() for b in btns)
            record("7c", "No bookmaker link on locked edge",
                   "PASS" if not has_bk_link else "FAIL",
                   f"bk_in_buttons={has_bk_link}")

            # Check 7d: No Compare Odds
            has_compare = any("Compare" in b or "All Odds" in b for b in btns)
            record("7d", "No Compare Odds on locked edge",
                   "PASS" if not has_compare else "FAIL",
                   f"compare_in_buttons={has_compare}")

            # Check 7e: Single CTA (subscribe/plans)
            has_cta = any("Plan" in b or "subscribe" in b.lower() or "Upgrade" in b or "View Plans" in b for b in btns)
            record("7e", "Single CTA at bottom",
                   "PASS" if has_cta else "WARN",
                   f"cta_buttons={[b for b in btns if 'Plan' in b or 'subscribe' in b.lower() or 'Upgrade' in b]}")

            # Check 7f: No AI text leak (VERIFIED_DATA, ODDS DATA, prompt instructions)
            prompt_leak = any(p in text for p in [
                "VERIFIED_DATA", "ODDS DATA", "You may ONLY", "system prompt",
                "CRITICAL RULES", "FORMATTING RULES"])
            record("7f", "No prompt leak in locked detail",
                   "PASS" if not prompt_leak else "FAIL",
                   f"prompt_leak={prompt_leak}")
        else:
            record("7a", "Locked edge tap", "SKIP", "No response after tap")

    await asyncio.sleep(3)

    # ── Step 2: Get tips_gold and tap an accessible (Gold) edge ──
    log.info("=== Sending /qa tips_gold ===")
    await client.send_message(BOT, "/qa tips_gold")
    await asyncio.sleep(5)

    msgs = await client.get_messages(BOT, limit=5)
    btn_msg = None
    for m in msgs:
        if m.buttons and not m.out:
            for row in m.buttons:
                for btn in row:
                    # Gold edge button has 🥇 tier emoji (not 🔒)
                    if "🥇" in (btn.text or "") and "🔒" not in (btn.text or ""):
                        btn_msg = m
                        break
                if btn_msg:
                    break
        if btn_msg:
            break

    if not btn_msg:
        log.error("No accessible Gold button found in tips_gold")
        record("8a", "Accessible edge tap", "SKIP", "No Gold button found")
    else:
        accessible_btn = None
        for row in btn_msg.buttons:
            for btn in row:
                if "🥇" in (btn.text or "") and "🔒" not in (btn.text or ""):
                    accessible_btn = btn
                    break
            if accessible_btn:
                break

        log.info("Tapping accessible button: %s", accessible_btn.text)
        try:
            await accessible_btn.click()
        except Exception as e:
            log.warning("Click error (expected): %s", e)

        # Wait for AI breakdown (may take longer)
        await asyncio.sleep(15)
        msgs_after = await client.get_messages(BOT, limit=5)
        latest = None
        for m in msgs_after:
            if not m.out:
                latest = m
                break

        # Wait more if it's still loading
        if latest:
            txt = latest.text or ""
            if len(txt) < 100 or "..." in txt or "scanning" in txt.lower():
                for _ in range(10):
                    await asyncio.sleep(5)
                    msgs_after = await client.get_messages(BOT, limit=5)
                    for m in msgs_after:
                        if not m.out:
                            latest = m
                            break
                    txt = latest.text or ""
                    if len(txt) > 200:
                        break

        if latest:
            text = latest.text or latest.message or ""
            btns = []
            if latest.buttons:
                for row in latest.buttons:
                    for b in row:
                        btns.append(b.text or "")

            (CAPTURE_DIR / "08_detail_accessible.txt").write_text(
                text + "\n\n== BUTTONS ==\n" + "\n".join(btns))

            # Check 8a: Full AI breakdown present (📋 🎯 ⚠️ 🏆 sections)
            sections_found = sum(1 for s in ["📋", "🎯", "⚠️", "🏆"] if s in text)
            record("8a", "Full AI breakdown sections",
                   "PASS" if sections_found >= 3 else "WARN",
                   f"sections_found={sections_found}/4")

            # Check 8b: Bookmaker deep link (URL button)
            has_bk_btn = any("Bet on" in b or "→" in b for b in btns)
            record("8b", "Bookmaker deep link button",
                   "PASS" if has_bk_btn else "WARN",
                   f"bk_button={has_bk_btn}, buttons={btns}")

            # Check 8c: Compare Odds button
            has_compare = any("Compare" in b or "All Odds" in b for b in btns)
            record("8c", "Compare All Odds button",
                   "PASS" if has_compare else "WARN",
                   f"compare={has_compare}")

            # Check 8d: Full signal breakdown (✅/❌)
            has_signals = "✅" in text or "❌" in text or "signals" in text.lower()
            record("8d", "Signal breakdown visible",
                   "PASS" if has_signals else "WARN",
                   f"signals={has_signals}")

            # Check 8e: SA Bookmaker Odds visible
            has_odds_section = "SA Bookmaker" in text or "bookmaker" in text.lower()
            record("8e", "SA Bookmaker Odds section",
                   "PASS" if has_odds_section else "WARN",
                   f"odds_section={has_odds_section}")

            # Check 8f: No prompt leak
            prompt_leak = any(p in text for p in [
                "VERIFIED_DATA", "ODDS DATA", "You may ONLY", "system prompt",
                "CRITICAL RULES", "FORMATTING RULES"])
            record("8f", "No prompt leak in accessible detail",
                   "PASS" if not prompt_leak else "FAIL",
                   f"prompt_leak={prompt_leak}")
        else:
            record("8a", "Accessible edge tap", "SKIP", "No response after tap")

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
    log.info("Detail checks: %d total | PASS: %d | FAIL: %d | WARN: %d",
             len(results), passed, failed, warned)

    # Save
    out = CAPTURE_DIR / "detail_results.json"
    out.write_text(json.dumps(results, indent=2))
    log.info("Saved: %s", out)

    for r in results:
        print(f"  {r['check_id']}: {r['status']} — {r['name']}")


if __name__ == "__main__":
    asyncio.run(run())
