#!/usr/bin/env python3
"""INV-BUTTONS-QA-02 Phase 2: Click each settings sub-button and capture response."""
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
from telethon.tl.types import ReplyInlineMarkup, KeyboardButtonCallback
from telethon.tl.functions.messages import GetBotCallbackAnswerRequest

API_ID   = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "")
BOT_USERNAME = "mzansiedge_bot"

STRING_SESSION_FILE = Path(__file__).resolve().parent.parent / "data" / "telethon_session.string"
FILE_SESSION        = Path(__file__).resolve().parent.parent / "data" / "telethon_session"

WAIT_SECS = 6


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


def buttons_from_markup(markup) -> list[KeyboardButtonCallback]:
    if not isinstance(markup, ReplyInlineMarkup):
        return []
    out = []
    for row in markup.rows:
        for btn in row.buttons:
            if isinstance(btn, KeyboardButtonCallback):
                out.append(btn)
    return out


def describe_markup(markup) -> str:
    if markup is None:
        return "    (no markup)"
    if isinstance(markup, ReplyInlineMarkup):
        lines = []
        for row in markup.rows:
            for btn in row.buttons:
                if isinstance(btn, KeyboardButtonCallback):
                    lines.append(f"      [{btn.text}] cb={btn.data.decode()}")
                else:
                    lines.append(f"      [{btn.text}] (url/other)")
        return "\n".join(lines)
    return f"    {type(markup).__name__}"


async def wait_for_reply(client, entity, since_t: float, timeout: float = WAIT_SECS) -> list:
    deadline = time.monotonic() + timeout
    seen_ids: set[int] = set()
    replies = []
    while time.monotonic() < deadline:
        await asyncio.sleep(0.5)
        msgs = await client.get_messages(entity, limit=10)
        for m in msgs:
            if m.out:
                continue
            if m.date.timestamp() >= since_t and m.id not in seen_ids:
                seen_ids.add(m.id)
                replies.append(m)
    return replies


async def main() -> None:
    client = await get_client()
    if not await client.is_user_authorized():
        print("ERROR: session not authorised")
        return

    bot_entity = await client.get_entity(BOT_USERNAME)

    # Step 1: Send "⚙️ Settings" and get the settings inline keyboard
    print("Step 1: Send '⚙️ Settings'")
    t0 = time.time()
    await client.send_message(bot_entity, "⚙️ Settings")
    replies = await wait_for_reply(client, bot_entity, t0, timeout=8)

    settings_msg = None
    for m in replies:
        btns = buttons_from_markup(m.reply_markup)
        cbs = [b.data.decode() for b in btns]
        if any(cb.startswith("settings:") for cb in cbs):
            settings_msg = m
            break

    if settings_msg is None:
        print(f"  Got {len(replies)} replies, none contained settings:* inline buttons")
        for m in replies:
            print(f"  text={repr((m.text or '')[:100])}, markup={type(m.reply_markup).__name__}")
        await client.disconnect()
        return

    print(f"  Settings menu received (msg_id={settings_msg.id})")
    print(describe_markup(settings_msg.reply_markup))

    # Step 2: Click each settings sub-button and record what happens
    sub_buttons = [
        b for b in buttons_from_markup(settings_msg.reply_markup)
        if b.data.decode().startswith("settings:")
    ]

    print(f"\nStep 2: Clicking {len(sub_buttons)} settings sub-buttons...\n")
    for btn in sub_buttons:
        cb = btn.data.decode()
        print(f"  Clicking [{btn.text}] cb={cb}")
        t1 = time.time()
        try:
            await client(GetBotCallbackAnswerRequest(
                peer=bot_entity,
                msg_id=settings_msg.id,
                data=btn.data,
            ))
        except Exception as e:
            print(f"    GetBotCallbackAnswerRequest error: {e}")

        await asyncio.sleep(1.5)
        # Check if the message was edited
        try:
            updated = await client.get_messages(bot_entity, ids=settings_msg.id)
            if updated and updated.text != settings_msg.text:
                print(f"    msg edited → text={repr((updated.text or '')[:120])}")
                print(f"    markup:\n{describe_markup(updated.reply_markup)}")
            else:
                # Look for a new message sent instead
                new_msgs = await wait_for_reply(client, bot_entity, t1, timeout=3)
                new_msgs = [m for m in new_msgs if m.id != settings_msg.id]
                if new_msgs:
                    for nm in new_msgs:
                        print(f"    new message → text={repr((nm.text or '')[:120])}")
                        print(f"    markup:\n{describe_markup(nm.reply_markup)}")
                else:
                    print(f"    NO RESPONSE — message unchanged and no new message")
        except Exception as e:
            print(f"    check error: {e}")

        # Reset: re-send Settings to get a fresh base message for next click
        await asyncio.sleep(0.5)
        t2 = time.time()
        await client.send_message(bot_entity, "⚙️ Settings")
        fresh_replies = await wait_for_reply(client, bot_entity, t2, timeout=6)
        for m in fresh_replies:
            btns = buttons_from_markup(m.reply_markup)
            cbs = [b.data.decode() for b in btns]
            if any(c.startswith("settings:") for c in cbs):
                settings_msg = m
                break

        print()

    print("Done.")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
