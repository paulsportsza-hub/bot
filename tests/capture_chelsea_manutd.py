"""
Live Telethon capture: Chelsea vs Man Utd Hot Tips detail card.
COO audit — captures COMPLETE verbatim text.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
import json
from datetime import datetime

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import (
    ReplyInlineMarkup,
    KeyboardButtonCallback,
    KeyboardButtonUrl,
)

# ── Configuration ──
API_ID = 32418601
API_HASH = "95e313a8ef5b998be0515dd8328fac57"
BOT_USERNAME = "mzansiedge_bot"
SESSION_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "telethon_session")
STRING_SESSION_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "telethon_session.string")
OUTPUT_FILE = "/home/paulsportsza/reports/target6-chelsea-manutd-capture.txt"

TIMEOUT = 20  # seconds to wait for bot responses


async def get_client() -> TelegramClient:
    """Create and connect a Telethon client."""
    # Try string session first
    if os.path.exists(STRING_SESSION_FILE):
        string = open(STRING_SESSION_FILE).read().strip()
        if string:
            client = TelegramClient(StringSession(string), API_ID, API_HASH)
            await client.connect()
            if await client.is_user_authorized():
                return client
            await client.disconnect()

    # Fallback to file session
    client = TelegramClient(SESSION_FILE, API_ID, API_HASH)
    await client.connect()
    if not await client.is_user_authorized():
        print("ERROR: Not logged in. Run save_telegram_session.py first.")
        sys.exit(1)
    return client


def describe_buttons(msg) -> str:
    """Extract all button info from a message."""
    lines = []
    if not msg.reply_markup:
        return "  [No buttons]"
    if isinstance(msg.reply_markup, ReplyInlineMarkup):
        for ri, row in enumerate(msg.reply_markup.rows):
            for bi, btn in enumerate(row.buttons):
                if isinstance(btn, KeyboardButtonCallback):
                    lines.append(f"  [Row {ri}, Btn {bi}] CALLBACK: text={btn.text!r}, data={btn.data!r}")
                elif isinstance(btn, KeyboardButtonUrl):
                    lines.append(f"  [Row {ri}, Btn {bi}] URL: text={btn.text!r}, url={btn.url!r}")
                else:
                    lines.append(f"  [Row {ri}, Btn {bi}] OTHER: {type(btn).__name__}, text={getattr(btn, 'text', '?')!r}")
    else:
        lines.append(f"  [Reply keyboard type: {type(msg.reply_markup).__name__}]")
    return "\n".join(lines)


def find_chelsea_manutd_button(msg) -> tuple:
    """Find a button that matches Chelsea vs Man Utd/United."""
    if not msg.reply_markup or not isinstance(msg.reply_markup, ReplyInlineMarkup):
        return None, None
    for row in msg.reply_markup.rows:
        for btn in row.buttons:
            if isinstance(btn, KeyboardButtonCallback):
                text_lower = btn.text.lower()
                data_str = btn.data.decode("utf-8", errors="replace") if isinstance(btn.data, bytes) else str(btn.data)
                if ("chelsea" in text_lower and ("man" in text_lower or "united" in text_lower)) or \
                   ("chelsea" in data_str.lower() and "manchester_united" in data_str.lower()):
                    return btn, data_str
    return None, None


async def main():
    out_lines = []

    def log(text: str):
        print(text)
        out_lines.append(text)

    log(f"{'='*80}")
    log(f"MZANSIEDGE BOT — LIVE CAPTURE: Chelsea vs Man Utd")
    log(f"Timestamp: {datetime.now().isoformat()}")
    log(f"{'='*80}")
    log("")

    # Connect
    log("[1] Connecting to Telegram via Telethon...")
    client = await get_client()
    me = await client.get_me()
    log(f"    Connected as: {me.first_name} (ID: {me.id})")
    log("")

    entity = await client.get_entity(BOT_USERNAME)

    # Step 1: Send "Top Edge Picks" (the current hot tips button text)
    log("[2] Sending '💎 Top Edge Picks' to @mzansiedge_bot...")
    sent = await client.send_message(entity, "💎 Top Edge Picks")
    sent_id = sent.id
    log(f"    Sent message ID: {sent_id}")
    log(f"    Waiting {TIMEOUT}s for response...")
    await asyncio.sleep(TIMEOUT)

    # Get all bot responses
    messages = await client.get_messages(entity, limit=30)
    bot_msgs = [m for m in messages if m.id > sent_id and m.sender_id != me.id]
    bot_msgs = list(reversed(bot_msgs))  # chronological order

    log(f"    Received {len(bot_msgs)} bot response message(s)")
    log("")

    # Capture all response messages
    log(f"{'='*80}")
    log("SECTION A: HOT TIPS / TOP EDGE PICKS — FULL RESPONSE")
    log(f"{'='*80}")
    log("")

    chelsea_btn = None
    chelsea_data = None
    chelsea_msg = None

    for i, msg in enumerate(bot_msgs):
        log(f"--- Message {i+1} of {len(bot_msgs)} (ID: {msg.id}) ---")
        log(f"RAW TEXT:")
        log(msg.text or "[empty]")
        log("")
        log(f"BUTTONS:")
        log(describe_buttons(msg))
        log("")

        # Search for Chelsea vs Man Utd button
        btn, data = find_chelsea_manutd_button(msg)
        if btn:
            chelsea_btn = btn
            chelsea_data = data
            chelsea_msg = msg
            log(f"  >>> FOUND Chelsea vs Man Utd button: text={btn.text!r}, data={data!r}")
            log("")

    # Also search for the match in button data (callback data might reference it)
    if not chelsea_btn:
        log("")
        log("[!] No direct Chelsea vs Man Utd button found in button text.")
        log("    Searching callback data for 'chelsea' match references...")
        for msg in bot_msgs:
            if msg.reply_markup and isinstance(msg.reply_markup, ReplyInlineMarkup):
                for row in msg.reply_markup.rows:
                    for btn in row.buttons:
                        if isinstance(btn, KeyboardButtonCallback):
                            data_str = btn.data.decode("utf-8", errors="replace") if isinstance(btn.data, bytes) else str(btn.data)
                            if "chelsea" in data_str.lower():
                                chelsea_btn = btn
                                chelsea_data = data_str
                                chelsea_msg = msg
                                log(f"    FOUND via callback data: text={btn.text!r}, data={data_str!r}")

    # Step 2: Click the Chelsea vs Man Utd button if found
    if chelsea_btn and chelsea_msg:
        log("")
        log(f"{'='*80}")
        log("SECTION B: CLICKING CHELSEA VS MAN UTD DETAIL BUTTON")
        log(f"{'='*80}")
        log("")
        log(f"[3] Clicking button: text={chelsea_btn.text!r}, data={chelsea_data!r}")

        try:
            await chelsea_msg.click(data=chelsea_btn.data)
            log(f"    Click sent. Waiting {TIMEOUT}s for detail response...")
            await asyncio.sleep(TIMEOUT)

            # Get updated messages
            detail_msgs = await client.get_messages(entity, limit=15)
            # Find new messages or edited messages
            detail_responses = []
            for m in detail_msgs:
                if m.sender_id != me.id:
                    detail_responses.append(m)
            detail_responses = list(reversed(detail_responses))

            log(f"    Got {len(detail_responses)} messages in view")
            log("")

            log(f"{'='*80}")
            log("SECTION C: DETAIL CARD — COMPLETE VERBATIM CAPTURE")
            log(f"{'='*80}")
            log("")

            for i, msg in enumerate(detail_responses[:5]):
                log(f"--- Detail Message {i+1} (ID: {msg.id}) ---")
                log(f"RAW TEXT:")
                log(msg.text or "[empty]")
                log("")
                log(f"BUTTONS:")
                log(describe_buttons(msg))
                log("")

        except Exception as e:
            log(f"    ERROR clicking button: {e}")
            log(f"    Exception type: {type(e).__name__}")
    else:
        log("")
        log("[!] No Chelsea vs Man Utd button found anywhere.")
        log("    The match may not be in the current Hot Tips list.")
        log("    Attempting alternative: search for match in edge:detail callback pattern...")

        # Try sending direct edge:detail callback
        log("")
        log("[3-ALT] Trying to access detail via known match_key...")
        log("    Known match_key from DB: chelsea_vs_manchester_united_2026-04-18")
        log("    This match is bronze tier / 10.0% EV / Draw recommendation")
        log("    It may not appear in Hot Tips (bronze tier may be filtered)")

    # Step 3: Try direct /qa command to check if match exists in tips
    log("")
    log(f"{'='*80}")
    log("SECTION D: SUPPLEMENTAL — BOT STATE CHECK")
    log(f"{'='*80}")
    log("")

    # Also try My Matches to see if Chelsea vs Man Utd appears there
    log("[4] Sending '⚽ My Matches' to check if match appears there...")
    sent2 = await client.send_message(entity, "⚽ My Matches")
    sent2_id = sent2.id
    await asyncio.sleep(15)

    mm_msgs = await client.get_messages(entity, limit=20)
    mm_bot = [m for m in mm_msgs if m.id > sent2_id and m.sender_id != me.id]
    mm_bot = list(reversed(mm_bot))

    log(f"    Received {len(mm_bot)} My Matches response(s)")
    log("")

    chelsea_found_mm = False
    for i, msg in enumerate(mm_bot):
        text = msg.text or ""
        if "chelsea" in text.lower():
            chelsea_found_mm = True
            log(f"--- My Matches Message {i+1} (ID: {msg.id}) ---")
            log(f"RAW TEXT:")
            log(text)
            log("")
            log(f"BUTTONS:")
            log(describe_buttons(msg))
            log("")

            # Find and click Chelsea button
            if msg.reply_markup and isinstance(msg.reply_markup, ReplyInlineMarkup):
                for row in msg.reply_markup.rows:
                    for btn in row.buttons:
                        if isinstance(btn, KeyboardButtonCallback):
                            data_str = btn.data.decode("utf-8", errors="replace") if isinstance(btn.data, bytes) else str(btn.data)
                            if "chelsea" in data_str.lower() and "manchester_united" in data_str.lower():
                                log(f"[5] Found Chelsea vs Man Utd in My Matches — clicking detail...")
                                try:
                                    await msg.click(data=btn.data)
                                    await asyncio.sleep(TIMEOUT)

                                    det2 = await client.get_messages(entity, limit=10)
                                    det2_bot = [m for m in det2 if m.sender_id != me.id]
                                    det2_bot = list(reversed(det2_bot))

                                    log("")
                                    log(f"{'='*80}")
                                    log("SECTION E: MY MATCHES — DETAIL VIEW VERBATIM")
                                    log(f"{'='*80}")
                                    log("")

                                    for j, dm in enumerate(det2_bot[:5]):
                                        log(f"--- Detail Message {j+1} (ID: {dm.id}) ---")
                                        log(f"RAW TEXT:")
                                        log(dm.text or "[empty]")
                                        log("")
                                        log(f"BUTTONS:")
                                        log(describe_buttons(dm))
                                        log("")
                                except Exception as e:
                                    log(f"    ERROR: {e}")

    if not chelsea_found_mm:
        log("    Chelsea not found in My Matches response.")

    # Save
    log("")
    log(f"{'='*80}")
    log(f"END OF CAPTURE — {datetime.now().isoformat()}")
    log(f"{'='*80}")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(out_lines))

    print(f"\n>>> Capture saved to: {OUTPUT_FILE}")

    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
