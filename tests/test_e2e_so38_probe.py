"""Probe script to discover the actual menu button layout for @mzansiedge_bot."""
from __future__ import annotations
import asyncio, os, sys
from telethon import TelegramClient
from telethon.tl.types import ReplyInlineMarkup, KeyboardButtonCallback

API_ID   = 32418601
API_HASH = "95e313a8ef5b998be0515dd8328fac57"
BOT_USERNAME = "mzansiedge_bot"

CANDIDATES = [
    "/home/paulsportsza/bot/mzansi_qa",
    "/home/paulsportsza/bot/telethon_session",
    "/home/paulsportsza/bot/data/telethon_session",
    "/home/paulsportsza/bot/anon_session",
]

async def main():
    client = None
    for path in CANDIDATES:
        if os.path.exists(path + ".session"):
            print(f"Using session: {path}")
            client = TelegramClient(path, API_ID, API_HASH)
            break
    if not client:
        sys.exit("No session found")

    await client.connect()
    if not await client.is_user_authorized():
        sys.exit("Not authorized")

    entity = await client.get_entity(BOT_USERNAME)
    # Get the last 5 bot messages to see current state
    all_msgs = await client.get_messages(entity, limit=15)
    bot_msgs = [m for m in all_msgs if not m.out]

    print("\nLast 5 bot messages:")
    for m in bot_msgs[:5]:
        print(f"\n  id={m.id} media={type(m.media).__name__ if m.media else 'None'}")
        if m.text:
            print(f"  text={m.text[:80]!r}")
        if m.reply_markup and isinstance(m.reply_markup, ReplyInlineMarkup):
            for row in m.reply_markup.rows:
                labels = [b.text for b in row.buttons]
                print(f"  row: {labels}")

    # Send /menu and capture response
    print("\n\nSending /menu...")
    sent = await client.send_message(entity, "/menu")
    await asyncio.sleep(12)

    fresh = await client.get_messages(entity, limit=20)
    new_msgs = [m for m in fresh if not m.out and m.id > sent.id]
    print(f"\nGot {len(new_msgs)} new bot messages after /menu:")
    for m in new_msgs:
        print(f"\n  id={m.id} media={type(m.media).__name__ if m.media else 'None'}")
        if m.text:
            print(f"  text={m.text[:120]!r}")
        if m.reply_markup and isinstance(m.reply_markup, ReplyInlineMarkup):
            for row in m.reply_markup.rows:
                for btn in row.buttons:
                    print(f"    btn: {btn.text!r} type={type(btn).__name__} data={getattr(btn, 'data', None)}")

    await client.disconnect()

asyncio.run(main())
