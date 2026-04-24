#!/usr/bin/env python3
"""INV-BUTTONS-QA-02: Settings button diagnostic via Telethon.

Sends "⚙️ Settings" to the bot and captures:
  - Whether a reply arrives
  - The exact text and reply_markup of the response
  - Whether the bot returns the kb_settings() inline keyboard or an error
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import (
    ReplyInlineMarkup,
    ReplyKeyboardMarkup,
    KeyboardButtonCallback,
    KeyboardButtonRow,
)

API_ID   = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "")
BOT_USERNAME = "mzansiedge_bot"

STRING_SESSION_FILE = Path(__file__).resolve().parent.parent / "data" / "telethon_session.string"
FILE_SESSION        = Path(__file__).resolve().parent.parent / "data" / "telethon_session"

SETTINGS_LABEL = "⚙️ Settings"
WAIT_SECS = 8


async def get_client() -> TelegramClient:
    if STRING_SESSION_FILE.exists():
        s = STRING_SESSION_FILE.read_text().strip()
        if s:
            c = TelegramClient(StringSession(s), API_ID, API_HASH)
            await c.connect()
            if await c.is_user_authorized():
                return c
    c = TelegramClient(str(FILE_SESSION), API_ID, API_HASH)
    await c.connect()
    return c


def describe_markup(markup) -> str:
    if markup is None:
        return "  reply_markup: None"
    if isinstance(markup, ReplyInlineMarkup):
        lines = ["  reply_markup: InlineKeyboardMarkup"]
        for row in markup.rows:
            for btn in row.buttons:
                if isinstance(btn, KeyboardButtonCallback):
                    lines.append(f"    [{btn.text}] → cb={btn.data.decode()}")
                else:
                    lines.append(f"    [{btn.text}] → (url/other)")
        return "\n".join(lines)
    if isinstance(markup, ReplyKeyboardMarkup):
        lines = ["  reply_markup: ReplyKeyboardMarkup"]
        for row in markup.rows:
            texts = [btn.text for btn in row.buttons]
            lines.append(f"    {texts}")
        return "\n".join(lines)
    return f"  reply_markup: {type(markup).__name__}"


async def main() -> None:
    client = await get_client()
    if not await client.is_user_authorized():
        print("ERROR: Telethon session not authorised. Run save_telethon_session.py first.")
        await client.disconnect()
        return

    print(f"Sending '{SETTINGS_LABEL}' to @{BOT_USERNAME} ...")
    await client.send_message(BOT_USERNAME, SETTINGS_LABEL)
    t0 = time.monotonic()

    # Collect all replies within WAIT_SECS
    replies = []
    deadline = t0 + WAIT_SECS
    while time.monotonic() < deadline:
        await asyncio.sleep(0.5)
        msgs = await client.get_messages(BOT_USERNAME, limit=5)
        for m in msgs:
            if m.out:
                continue  # skip our own messages
            if m.date.timestamp() >= t0:
                if not any(r.id == m.id for r in replies):
                    replies.append(m)

    if not replies:
        print(f"\nRESULT: NO REPLY received within {WAIT_SECS}s after sending '{SETTINGS_LABEL}'")
        print("=> Bot silently ignored the message — likely match missed in MessageHandler or exception swallowed.")
    else:
        print(f"\nRESULT: {len(replies)} reply(ies) received:\n")
        for i, m in enumerate(replies, 1):
            print(f"--- Reply {i} ---")
            print(f"  text: {repr(m.text or m.message or '')[:300]}")
            print(describe_markup(m.reply_markup))
            print()

    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
