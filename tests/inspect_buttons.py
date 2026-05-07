"""Inspect button data in current hot tips messages."""
import asyncio
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import ReplyInlineMarkup, KeyboardButtonCallback

API_ID = 32418601
API_HASH = "95e313a8ef5b998be0515dd8328fac57"
STRING_SESSION_FILE = "data/telethon_qa_session.string"

async def run():
    string = open(STRING_SESSION_FILE).read().strip()
    client = TelegramClient(StringSession(string), API_ID, API_HASH)
    await client.connect()
    entity = await client.get_entity("mzansiedge_bot")

    msgs = await client.get_messages(entity, limit=15)
    for msg in msgs:
        if not msg.out:
            print(f"\n=== msg_id={msg.id} ===")
            if msg.text:
                print(f"Text (300 chars): {msg.text[:300]}")
            if msg.reply_markup and isinstance(msg.reply_markup, ReplyInlineMarkup):
                for i, row in enumerate(msg.reply_markup.rows):
                    for j, btn in enumerate(row.buttons):
                        if isinstance(btn, KeyboardButtonCallback):
                            d = btn.data.decode() if isinstance(btn.data, bytes) else btn.data
                            print(f"  Btn[{i},{j}]: text={btn.text!r} data={d!r}")
            elif msg.reply_markup:
                print(f"  Markup type: {type(msg.reply_markup).__name__}")

    await client.disconnect()

asyncio.run(run())
