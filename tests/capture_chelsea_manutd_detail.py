"""
Live Telethon capture: Chelsea vs Man Utd detail card via My Matches.
COO audit — captures COMPLETE verbatim text.
Phase 2: Click the [3] CHE vs MAN button from My Matches.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from datetime import datetime

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import (
    ReplyInlineMarkup,
    KeyboardButtonCallback,
    KeyboardButtonUrl,
)

API_ID = 32418601
API_HASH = "95e313a8ef5b998be0515dd8328fac57"
BOT_USERNAME = "mzansiedge_bot"
SESSION_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "telethon_session")
STRING_SESSION_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "telethon_session.string")
OUTPUT_FILE = "/home/paulsportsza/reports/target6-chelsea-manutd-capture.txt"

TIMEOUT = 25  # longer timeout for AI analysis generation


def describe_buttons(msg) -> str:
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


async def get_client() -> TelegramClient:
    if os.path.exists(STRING_SESSION_FILE):
        string = open(STRING_SESSION_FILE).read().strip()
        if string:
            client = TelegramClient(StringSession(string), API_ID, API_HASH)
            await client.connect()
            if await client.is_user_authorized():
                return client
            await client.disconnect()
    client = TelegramClient(SESSION_FILE, API_ID, API_HASH)
    await client.connect()
    if not await client.is_user_authorized():
        print("ERROR: Not logged in.")
        sys.exit(1)
    return client


async def main():
    out_lines = []

    def log(text: str):
        print(text)
        out_lines.append(text)

    # Read existing capture to append
    existing = ""
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, "r") as f:
            existing = f.read()

    log("")
    log(f"{'='*80}")
    log(f"PHASE 2: CHELSEA VS MAN UTD — DETAIL CARD CAPTURE")
    log(f"Timestamp: {datetime.now().isoformat()}")
    log(f"{'='*80}")
    log("")

    client = await get_client()
    me = await client.get_me()
    log(f"[1] Connected as: {me.first_name} (ID: {me.id})")
    entity = await client.get_entity(BOT_USERNAME)

    # Step 1: Send My Matches to get the button
    log("[2] Sending '⚽ My Matches'...")
    sent = await client.send_message(entity, "⚽ My Matches")
    sent_id = sent.id
    await asyncio.sleep(15)

    messages = await client.get_messages(entity, limit=15)
    bot_msgs = [m for m in messages if m.id > sent_id and m.sender_id != me.id]
    bot_msgs = list(reversed(bot_msgs))

    log(f"    Got {len(bot_msgs)} response(s)")

    # Find the Chelsea vs Man Utd button
    target_btn = None
    target_msg = None
    for msg in bot_msgs:
        if msg.reply_markup and isinstance(msg.reply_markup, ReplyInlineMarkup):
            for row in msg.reply_markup.rows:
                for btn in row.buttons:
                    if isinstance(btn, KeyboardButtonCallback):
                        text = btn.text
                        if "CHE" in text and "MAN" in text:
                            target_btn = btn
                            target_msg = msg
                            data_str = btn.data.decode("utf-8", errors="replace") if isinstance(btn.data, bytes) else str(btn.data)
                            log(f"    Found button: text={text!r}, data={data_str!r}")

    if not target_btn or not target_msg:
        log("[!] Chelsea vs Man Utd button not found in My Matches!")
        log("    Cannot proceed with detail capture.")
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write(existing + "\n" + "\n".join(out_lines))
        await client.disconnect()
        return

    # Step 2: Click the button
    log("")
    log(f"[3] Clicking '[3] CHE vs MAN' button for detail view...")
    log(f"    Waiting {TIMEOUT}s for AI analysis...")

    # Record the message we're editing (the My Matches message)
    pre_click_text = target_msg.text
    pre_click_id = target_msg.id

    await target_msg.click(data=target_btn.data)
    await asyncio.sleep(TIMEOUT)

    # Get all recent messages and look for the detail
    detail_msgs = await client.get_messages(entity, limit=20)
    all_bot = [m for m in detail_msgs if m.sender_id != me.id]
    all_bot = list(reversed(all_bot))

    log("")
    log(f"{'='*80}")
    log("SECTION F: CHELSEA VS MAN UTD — GAME BREAKDOWN DETAIL")
    log(f"{'='*80}")
    log("")

    # The detail view typically edits the My Matches message or sends a new one
    # Check if the original My Matches message was edited
    # Refetch the specific message
    try:
        edited_msg = await client.get_messages(entity, ids=pre_click_id)
        if edited_msg and edited_msg.text != pre_click_text:
            log(f"--- EDITED MESSAGE (ID: {pre_click_id}) — DETAIL VIEW ---")
            log(f"RAW TEXT (VERBATIM):")
            log(edited_msg.text or "[empty]")
            log("")
            log(f"BUTTONS:")
            log(describe_buttons(edited_msg))
            log("")
        else:
            log(f"    Original message (ID: {pre_click_id}) was NOT edited.")
    except Exception as e:
        log(f"    Error refetching message: {e}")

    # Also check for new messages
    new_msgs = [m for m in all_bot if m.id > sent_id]
    log(f"    Total messages after click: {len(new_msgs)}")
    log("")

    for i, msg in enumerate(new_msgs):
        is_edited = (msg.id == pre_click_id)
        label = f"(EDITED from My Matches)" if is_edited else "(New message)"
        log(f"--- Message {i+1} (ID: {msg.id}) {label} ---")
        log(f"RAW TEXT (VERBATIM — COMPLETE):")
        log(msg.text or "[empty]")
        log("")
        log(f"BUTTONS:")
        log(describe_buttons(msg))
        log("")

    # Final separator
    log(f"{'='*80}")
    log(f"END OF DETAIL CAPTURE — {datetime.now().isoformat()}")
    log(f"{'='*80}")

    # Write combined output
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(existing + "\n" + "\n".join(out_lines))

    print(f"\n>>> Detail capture appended to: {OUTPUT_FILE}")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
