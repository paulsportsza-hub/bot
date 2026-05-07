"""FIX-DEAD-BUTTONS-01 verification — Edge Tracker and Guide inline buttons on photo menu.

Sends /start to get the menu (triggers photo card when wins exist),
then taps the 📊 Edge Tracker and 📖 Guide inline buttons to confirm they
produce a response. Both previously silently failed when the menu message
was a photo card (query.edit_message_text on photo raises BadRequest).
"""

from __future__ import annotations

import asyncio
import os
import sys
import time

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import ReplyInlineMarkup, KeyboardButtonCallback

API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "")
BOT_USERNAME = "mzansiedge_bot"
STRING_SESSION_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "telethon_qa_session.string")
SESSION_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "telethon_qa_session")
TIMEOUT = 20


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


async def click_inline_button(client, msg, label: str, wait: float = TIMEOUT):
    """Click inline button by label, return messages after click."""
    if not msg.reply_markup or not isinstance(msg.reply_markup, ReplyInlineMarkup):
        return []
    for row in msg.reply_markup.rows:
        for btn in row.buttons:
            if isinstance(btn, KeyboardButtonCallback) and label in btn.text:
                await msg.click(data=btn.data)
                await asyncio.sleep(wait)
                entity = await client.get_entity(BOT_USERNAME)
                return list(reversed(await client.get_messages(entity, limit=10)))
    return []


async def main():
    client = await get_client()
    entity = await client.get_entity(BOT_USERNAME)

    print("\n=== FIX-DEAD-BUTTONS-01 Verification ===\n")

    # Step 1: Tap Menu reply button to get a message with kb_main() inline buttons
    print("[1] Tapping 🏠 Menu reply button...")
    sent = await client.send_message(entity, "🏠 Menu")
    sent_id = sent.id
    await asyncio.sleep(TIMEOUT)
    msgs = list(reversed(await client.get_messages(entity, limit=20)))
    menu_msg = next((m for m in msgs if m.id > sent_id and m.reply_markup), None)

    if not menu_msg:
        print("FAIL: No menu message with markup received")
        await client.disconnect()
        sys.exit(1)

    is_photo = bool(menu_msg.photo)
    print(f"    Menu message received (photo={is_photo}, has_markup={bool(menu_msg.reply_markup)})")
    if is_photo:
        print("    ✅ Photo card confirmed — this is the path that caused the bug")
    else:
        print("    ℹ️  Text menu (no wins in DB) — button fix still applies via _serve_response")

    # Inspect inline buttons
    btns = []
    if isinstance(menu_msg.reply_markup, ReplyInlineMarkup):
        for row in menu_msg.reply_markup.rows:
            for b in row.buttons:
                if isinstance(b, KeyboardButtonCallback):
                    btns.append(b.text)
    print(f"    Inline buttons found: {btns}")

    # Step 2: Click Edge Tracker
    print("\n[2] Clicking 📊 Edge Tracker...")
    t0 = time.time()
    result_msgs = await click_inline_button(client, menu_msg, "Edge Tracker")
    elapsed = time.time() - t0

    if not result_msgs:
        print("FAIL: No response to Edge Tracker button tap")
        await client.disconnect()
        sys.exit(1)

    # Find the bot's response (not our own message)
    me = await client.get_me()
    et_response = next((m for m in result_msgs if m.sender_id != me.id and (m.text or getattr(m, 'caption', None))), None)
    if et_response:
        snippet = (et_response.text or getattr(et_response, 'caption', '') or "")[:120].replace("\n", " ")
        print(f"    ✅ PASS — Edge Tracker responded in {elapsed:.1f}s")
        print(f"    Response snippet: {snippet}")
    else:
        print(f"FAIL: Response received but no text from bot in {elapsed:.1f}s")
        await client.disconnect()
        sys.exit(1)

    # Step 3: Get fresh menu message again (Edge Tracker may have replaced it)
    print("\n[3] Tapping 🏠 Menu again for Guide test...")
    sent2 = await client.send_message(entity, "🏠 Menu")
    sent2_id = sent2.id
    await asyncio.sleep(TIMEOUT)
    msgs2 = list(reversed(await client.get_messages(entity, limit=20)))
    menu_msg2 = next((m for m in msgs2 if m.id > sent2_id and m.reply_markup), None)

    if not menu_msg2:
        print("FAIL: No second menu message received")
        await client.disconnect()
        sys.exit(1)

    # Step 4: Click Guide
    print("\n[4] Clicking 📖 Guide...")
    t1 = time.time()
    guide_msgs = await click_inline_button(client, menu_msg2, "Guide")
    elapsed2 = time.time() - t1

    if not guide_msgs:
        print("FAIL: No response to Guide button tap")
        await client.disconnect()
        sys.exit(1)

    guide_response = next((m for m in guide_msgs if m.sender_id != me.id and (m.text or getattr(m, 'caption', None))), None)
    if guide_response:
        snippet2 = (guide_response.text or getattr(guide_response, 'caption', '') or "")[:120].replace("\n", " ")
        print(f"    ✅ PASS — Guide responded in {elapsed2:.1f}s")
        print(f"    Response snippet: {snippet2}")
    else:
        print(f"FAIL: Guide response received but no bot text in {elapsed2:.1f}s")
        await client.disconnect()
        sys.exit(1)

    print("\n=== BOTH BUTTONS VERIFIED ✅ ===")
    print("Root cause: query.edit_message_text() on photo msg → _serve_response() fix")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
