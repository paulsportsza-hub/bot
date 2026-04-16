#!/usr/bin/env python3
"""Telethon E2E test for BUILD-MYMATCHES-CARD-OVERHAUL-01.

Captures BEFORE/AFTER screenshots of non-Edge My Matches card,
plus Edge card verification (unaffected).

Usage:
  python scripts/card_overhaul_telethon.py before   # BEFORE screenshots
  python scripts/card_overhaul_telethon.py after    # AFTER screenshots
  python scripts/card_overhaul_telethon.py edge     # Edge card unaffected
"""
import asyncio
import os
import sys
import time

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from telethon import TelegramClient
from telethon.tl.custom import Message

API_ID = int(os.environ["TELEGRAM_API_ID"])
API_HASH = os.environ["TELEGRAM_API_HASH"]
SESSION = os.path.join(os.path.dirname(__file__), "..", "data", "telethon_session")
BOT = "@mzansiedge_bot"
REPORT_DIR = "/home/paulsportsza/reports/e2e-screenshots"


async def wait_for_response(conv, timeout=60):
    """Wait for bot response, handling edits."""
    msg = await asyncio.wait_for(conv.get_response(), timeout=timeout)
    # Wait a bit for edits (spinner → final content)
    for _ in range(12):
        await asyncio.sleep(2.5)
        try:
            updated = await conv.get_edit(timeout=3)
            msg = updated
        except asyncio.TimeoutError:
            break
    return msg


async def save_response(msg: Message, label: str):
    """Save message text to file."""
    os.makedirs(REPORT_DIR, exist_ok=True)
    path = os.path.join(REPORT_DIR, f"{label}.txt")
    text = msg.text or msg.raw_text or "(empty)"
    with open(path, "w") as f:
        f.write(text)
    print(f"  Saved: {path} ({len(text)} chars)")
    return text


async def tap_button(conv, msg, text_match):
    """Find and tap an inline button by text match."""
    if not msg.buttons:
        print(f"  No buttons on message to find '{text_match}'")
        return None
    for row in msg.buttons:
        for btn in row:
            if text_match.lower() in (btn.text or "").lower():
                await btn.click()
                return await wait_for_response(conv, timeout=45)
    print(f"  Button '{text_match}' not found")
    return None


async def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "before"
    print(f"=== Card Overhaul E2E: {mode.upper()} ===\n")

    client = TelegramClient(SESSION, API_ID, API_HASH)
    await client.start()

    async with client.conversation(BOT, timeout=90) as conv:
        # Step 1: Send /start to ensure fresh state
        await conv.send_message("/start")
        await asyncio.sleep(3)
        try:
            await conv.get_response()
        except asyncio.TimeoutError:
            pass

        # Step 2: Tap "My Matches" to get the list
        print("1. Sending 'My Matches' keyboard tap...")
        await conv.send_message("⚽ My Matches")
        list_msg = await wait_for_response(conv, timeout=30)
        list_text = await save_response(list_msg, f"{mode}_01_my_matches_list")
        print(f"   List: {list_text[:100]}...")

        if not list_msg.buttons:
            print("   No buttons found on My Matches list. Exiting.")
            await client.disconnect()
            return

        # Step 3: Tap the FIRST game (non-Edge card)
        print("\n2. Tapping first game for non-Edge card...")
        first_game_btn = None
        for row in list_msg.buttons:
            for btn in row:
                # Game buttons are inline with team names or [N] prefix
                btn_text = btn.text or ""
                if "vs" in btn_text.lower() or btn_text.startswith("["):
                    first_game_btn = btn
                    break
            if first_game_btn:
                break

        if not first_game_btn:
            # Try the first inline button that's not navigation
            for row in list_msg.buttons:
                for btn in row:
                    btn_text = (btn.text or "").lower()
                    if btn_text and "menu" not in btn_text and "back" not in btn_text and "edge" not in btn_text:
                        first_game_btn = btn
                        break
                if first_game_btn:
                    break

        if first_game_btn:
            print(f"   Tapping: '{first_game_btn.text}'")
            await first_game_btn.click()
            card_msg = await wait_for_response(conv, timeout=60)
            card_text = await save_response(card_msg, f"{mode}_02_non_edge_card")
            print(f"   Card: {card_text[:200]}...")

            # Check for key sections
            checks = {
                "header": "🎯" in card_text,
                "haiku_preview": "Match Preview" in card_text,
                "h2h_section": "H2H" in card_text or "Head to Head" in card_text,
                "injury_watch": "Injury Watch" in card_text or "Key Absences" in card_text,
                "key_stats": "Key Stats" in card_text,
                "odds": "Odds" in card_text or "odds" in card_text,
            }
            print(f"\n   Section checks:")
            for name, found in checks.items():
                status = "FOUND" if found else "NOT FOUND"
                print(f"     {name}: {status}")
        else:
            print("   No game button found to tap.")

        # Step 4: Edge card verification (if mode == "edge")
        if mode == "edge":
            print("\n3. Checking Edge card (via Hot Tips)...")
            await conv.send_message("💎 Top Edge Picks")
            edge_list = await wait_for_response(conv, timeout=30)
            edge_list_text = await save_response(edge_list, f"{mode}_03_edge_list")

            if edge_list.buttons:
                # Tap first edge pick
                for row in edge_list.buttons:
                    for btn in row:
                        btn_text = (btn.text or "").lower()
                        if "💎" in btn.text or "🥇" in btn.text or "🥈" in btn.text or "🥉" in btn.text:
                            print(f"   Tapping edge: '{btn.text}'")
                            await btn.click()
                            edge_card = await wait_for_response(conv, timeout=45)
                            edge_text = await save_response(edge_card, f"{mode}_04_edge_card")
                            print(f"   Edge card: {edge_text[:200]}...")

                            # Verify Edge card is NOT affected (should NOT have new sections)
                            has_match_preview = "Match Preview" in edge_text
                            has_h2h_full = "H2H · Last 5" in edge_text
                            print(f"\n   Edge card isolation check:")
                            print(f"     'Match Preview' section: {'FOUND (REGRESSION!)' if has_match_preview else 'NOT FOUND (correct)'}")
                            print(f"     'H2H · Last 5' section: {'FOUND (check)' if has_h2h_full else 'NOT FOUND (correct)'}")
                            break
                    else:
                        continue
                    break

    await client.disconnect()
    print(f"\n=== Done. Screenshots in {REPORT_DIR} ===")


if __name__ == "__main__":
    asyncio.run(main())
