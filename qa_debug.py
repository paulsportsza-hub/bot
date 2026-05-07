#!/usr/bin/env python3
"""Debug: understand message flow"""

import asyncio
import time
from telethon import TelegramClient
from telethon.tl.functions.messages import GetBotCallbackAnswerRequest

API_ID = 32418601
API_HASH = "95e313a8ef5b998be0515dd8328fac57"
SESSION_PATH = "/home/paulsportsza/bot/data/telethon_qa_session"
BOT = "@mzansiedge_bot"


async def main():
    client = TelegramClient(SESSION_PATH, API_ID, API_HASH)
    await client.start()
    me = await client.get_me()
    bot = await client.get_entity(BOT)
    print(f"Me: {me.id}, Bot: {bot.id}")

    # Get current state
    print("\n--- Current last 10 messages ---")
    msgs = await client.get_messages(bot, limit=10)
    for m in msgs:
        direction = "OUT" if m.out else "IN"
        btns = []
        if m.reply_markup and hasattr(m.reply_markup, "rows"):
            for row in m.reply_markup.rows:
                for btn in row.buttons:
                    btns.append(getattr(btn, "text", "?"))
        print(f"  [{direction}] id={m.id} date={m.date} text={repr(m.message[:60] if m.message else '')} btns={btns[:4]}")

    print("\n--- Sending /qa force_onboard ---")
    last_id = msgs[0].id if msgs else 0
    print(f"  Last seen id: {last_id}")

    await client.send_message(bot, "/qa force_onboard")
    await asyncio.sleep(3)

    msgs2 = await client.get_messages(bot, limit=5)
    for m in msgs2:
        direction = "OUT" if m.out else "IN"
        print(f"  [{direction}] id={m.id} text={repr(m.message[:80] if m.message else '')}")

    new_after_fo = [m for m in msgs2 if not m.out and m.id > last_id]
    print(f"  New bot msgs after force_onboard: {[(m.id, m.message[:50]) for m in new_after_fo]}")
    last_id2 = msgs2[0].id

    print("\n--- Sending /start ---")
    await client.send_message(bot, "/start")

    # Wait and poll
    for i in range(10):
        await asyncio.sleep(1.5)
        msgs3 = await client.get_messages(bot, limit=5)
        new = [m for m in msgs3 if not m.out and m.id > last_id2]
        if new:
            print(f"  Got response at poll {i+1}:")
            for m in new:
                btns = []
                if m.reply_markup and hasattr(m.reply_markup, "rows"):
                    for row in m.reply_markup.rows:
                        for btn in row.buttons:
                            btns.append(getattr(btn, "text", "?"))
                print(f"    id={m.id} text={repr(m.message[:100] if m.message else '')} btns={btns[:5]}")
            break
        else:
            print(f"  Poll {i+1}: no new msgs (last_id2={last_id2}, latest={msgs3[0].id if msgs3 else 'none'})")

    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
