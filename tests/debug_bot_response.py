"""Debug: dump everything the bot sends in response to various commands."""
import asyncio, os, sys
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import ReplyInlineMarkup, KeyboardButtonCallback, ReplyKeyboardMarkup

API_ID = int(os.getenv("TELEGRAM_API_ID", "32418601"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "95e313a8ef5b998be0515dd8328fac57")
BOT_USERNAME = "mzansiedge_bot"

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STRING_SESSION_FILE = os.path.join(_BASE, "data", "telethon_qa_session.string")
SESSION_FILE = os.path.join(_BASE, "data", "telethon_qa_session")

async def get_client():
    if os.path.exists(STRING_SESSION_FILE):
        string = open(STRING_SESSION_FILE).read().strip()
        if string:
            c = TelegramClient(StringSession(string), API_ID, API_HASH)
            await c.connect()
            if await c.is_user_authorized():
                print("Using string session ✓")
                return c
            await c.disconnect()
    c = TelegramClient(SESSION_FILE, API_ID, API_HASH)
    await c.connect()
    return c

async def main():
    client = await get_client()
    entity = await client.get_entity(BOT_USERNAME)

    sent = await client.send_message(entity, "💎 Top Edge Picks")
    sent_id = sent.id
    print(f"Sent message id={sent_id}, waiting 20s...")
    await asyncio.sleep(20)

    msgs = await client.get_messages(entity, limit=40)
    after = [m for m in msgs if m.id > sent_id]
    after_chrono = list(reversed(after))

    print(f"\nTotal messages received after sent_id={sent_id}: {len(after_chrono)}")

    for i, m in enumerate(after_chrono):
        print(f"\n--- MSG[{i}] id={m.id} out={m.out} ---")
        print(f"  text: {(m.text or '')[:300]!r}")
        print(f"  media: {type(m.media).__name__ if m.media else None}")
        print(f"  reply_markup type: {type(m.reply_markup).__name__ if m.reply_markup else None}")
        if m.reply_markup and isinstance(m.reply_markup, ReplyInlineMarkup):
            for row in m.reply_markup.rows:
                for btn in row.buttons:
                    if isinstance(btn, KeyboardButtonCallback):
                        data = btn.data.decode() if isinstance(btn.data, bytes) else str(btn.data)
                        print(f"    INLINE_BTN: '{btn.text}' -> {data}")
                    elif hasattr(btn, 'text'):
                        print(f"    INLINE_BTN (other): '{btn.text}'")
        elif m.reply_markup and isinstance(m.reply_markup, ReplyKeyboardMarkup):
            for row in m.reply_markup.rows:
                for btn in row.buttons:
                    print(f"    REPLY_KB_BTN: '{btn.text}'")

    await client.disconnect()

asyncio.run(main())
