"""BUILD-KO-SUPERSPORT-PRIMARY-01 AC-4 — Telethon E2E verify.

Opens the Polokwane City v Kaizer Chiefs card (2026-04-18) and checks:
  - KO time 17:30 visible on card
  - Channel "SuperSport PSL" visible on card
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import (
    ReplyInlineMarkup,
    KeyboardButtonCallback,
    MessageMediaPhoto,
)
from telethon.tl import functions

API_ID = int(os.getenv("TELEGRAM_API_ID", "32418601"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "95e313a8ef5b998be0515dd8328fac57")
BOT_USERNAME = "mzansiedge_bot"
STRING_SESSION_FILE = str(ROOT / "data" / "telethon_qa_session.string")
SESSION_FILE = str(ROOT / "data" / "telethon_qa_session")


async def get_client() -> TelegramClient:
    if os.path.exists(STRING_SESSION_FILE):
        s = open(STRING_SESSION_FILE).read().strip()
        if s:
            c = TelegramClient(StringSession(s), API_ID, API_HASH)
            await c.connect()
            if await c.is_user_authorized():
                return c
            await c.disconnect()
    c = TelegramClient(SESSION_FILE, API_ID, API_HASH)
    await c.connect()
    if not await c.is_user_authorized():
        print("ERROR: session not authorised")
        sys.exit(1)
    return c


async def find_button(msg, needle: str) -> bytes | None:
    if not msg.reply_markup or not isinstance(msg.reply_markup, ReplyInlineMarkup):
        return None
    for row in msg.reply_markup.rows:
        for btn in row.buttons:
            if isinstance(btn, KeyboardButtonCallback) and needle.lower() in (btn.text or "").lower():
                return btn.data
    return None


async def dump_text(msg) -> str:
    is_photo = isinstance(msg.media, MessageMediaPhoto)
    label = "PHOTO" if is_photo else "TEXT"
    text = msg.message or msg.text or ""
    btns = []
    if msg.reply_markup and isinstance(msg.reply_markup, ReplyInlineMarkup):
        for row in msg.reply_markup.rows:
            for btn in row.buttons:
                btns.append(getattr(btn, "text", ""))
    return f"[{label}] {text[:600]}\n     buttons={btns}"


async def main() -> int:
    client = await get_client()
    entity = await client.get_entity(BOT_USERNAME)
    print(f"Connected. Target: @{BOT_USERNAME}")

    # Clear chat — send /start to get fresh menu
    await client.send_message(entity, "⚽ My Matches")
    await asyncio.sleep(3)

    # Scan recent messages for the Polokwane v Chiefs button
    msgs = await client.get_messages(entity, limit=10)
    poly_cb = None
    host_msg = None
    for msg in msgs:
        if not msg.reply_markup or not isinstance(msg.reply_markup, ReplyInlineMarkup):
            continue
        for row in msg.reply_markup.rows:
            for btn in row.buttons:
                if isinstance(btn, KeyboardButtonCallback) and btn.text:
                    t = btn.text.lower()
                    if "polokwane" in t and ("kaizer" in t or "chiefs" in t or "kc" in t):
                        poly_cb = btn.data
                        host_msg = msg
                        print(f"Found button: {btn.text!r}")
                        break
                    if "poly" in t and ("kaizer" in t or "chiefs" in t or "kc" in t):
                        poly_cb = btn.data
                        host_msg = msg
                        print(f"Found button: {btn.text!r}")
                        break
            if poly_cb:
                break
        if poly_cb:
            break

    if not poly_cb:
        print("Polokwane v Chiefs button not found in recent messages.")
        print("Dumping recent messages:")
        for i, msg in enumerate(msgs[:5]):
            print(f"  [{i}] {await dump_text(msg)}")
        await client.disconnect()
        return 1

    # Tap the button
    print(f"\nTapping Polokwane v Chiefs button...")
    await client.request(
        functions.messages.GetBotCallbackAnswerRequest(
            peer=entity,
            msg_id=host_msg.id,
            data=poly_cb,
        )
    )
    await asyncio.sleep(6)

    # Read back the response — check for card photo OR text
    msgs = await client.get_messages(entity, limit=6)
    print("\n=== Recent responses ===")
    for i, msg in enumerate(list(reversed(msgs[:6]))):
        print(f"[{i}] {await dump_text(msg)}")

    # Success gate: any message/caption contains "17:30" AND "SuperSport PSL"
    found_time = False
    found_channel = False
    for msg in msgs[:6]:
        body = (msg.message or msg.text or "") + " "
        if "17:30" in body:
            found_time = True
        if "supersport psl" in body.lower():
            found_channel = True

    print("\n=== GATE ===")
    print(f" 17:30          : {'PASS' if found_time else 'FAIL'}")
    print(f" SuperSport PSL : {'PASS' if found_channel else 'FAIL'}")

    await client.disconnect()
    return 0 if (found_time and found_channel) else 2


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
