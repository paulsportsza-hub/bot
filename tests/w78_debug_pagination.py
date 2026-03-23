#!/usr/bin/env python3
"""Debug pagination for W78 audit."""
import asyncio, os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import ReplyInlineMarkup, KeyboardButtonCallback

API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "")
BOT = "mzansiedge_bot"
STRING_SESSION_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "telethon_session.string")

async def main():
    string = open(STRING_SESSION_FILE).read().strip()
    client = TelegramClient(StringSession(string), API_ID, API_HASH)
    await client.connect()
    ent = await client.get_entity(BOT)

    # Send /tips
    sent = await client.send_message(ent, "/tips")
    await asyncio.sleep(3)
    msgs = await client.get_messages(ent, limit=10)
    tips_msg = None
    for m in msgs:
        if m.id > sent.id and not m.out and m.text:
            tips_msg = m
            break
    if not tips_msg:
        print("No tips response!")
        await client.disconnect()
        return

    print("Page 1 buttons:")
    all_btns = []
    if tips_msg.reply_markup and isinstance(tips_msg.reply_markup, ReplyInlineMarkup):
        for row in tips_msg.reply_markup.rows:
            for btn in row.buttons:
                if isinstance(btn, KeyboardButtonCallback):
                    data = btn.data.decode("utf-8", errors="replace")
                    all_btns.append((btn.text, data, btn.data))
                    print(f"  {btn.text:40s} | {data}")

    # Find Next button
    next_btns = [(t, d, raw) for t, d, raw in all_btns if "hot:page" in d]
    print(f"\nPagination buttons: {len(next_btns)}")
    for t, d, _ in next_btns:
        print(f"  {t} → {d}")

    if next_btns:
        # Click the first pagination button
        text, data, raw = next_btns[0]
        print(f"\nClicking: {text} → {data}")
        try:
            await tips_msg.click(data=raw)
        except Exception as e:
            print(f"Click error: {e}")
            await client.disconnect()
            return

        await asyncio.sleep(3)

        # Check if message was edited
        edited = await client.get_messages(ent, ids=tips_msg.id)
        if edited and edited.text and edited.text != tips_msg.text:
            print("\nPage 2 (edited message):")
            print(edited.text[:500])
            print("\nPage 2 buttons:")
            if edited.reply_markup and isinstance(edited.reply_markup, ReplyInlineMarkup):
                for row in edited.reply_markup.rows:
                    for btn in row.buttons:
                        if isinstance(btn, KeyboardButtonCallback):
                            d2 = btn.data.decode("utf-8", errors="replace")
                            print(f"  {btn.text:40s} | {d2}")
        else:
            print("Message was NOT edited")
            # Check new messages
            new = await client.get_messages(ent, limit=5)
            for nm in new:
                if nm.id > tips_msg.id and not nm.out:
                    print(f"New message: {nm.text[:200] if nm.text else '(none)'}")

    await client.disconnect()

asyncio.run(main())
