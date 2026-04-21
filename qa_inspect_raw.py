"""
Debug: Get full raw message data after ep:pick click to understand format.
"""
import asyncio
import os
from dotenv import load_dotenv

load_dotenv("/home/paulsportsza/bot/.env")

API_ID = int(os.environ["TELEGRAM_API_ID"])
API_HASH = os.environ["TELEGRAM_API_HASH"]
STRING_SESSION_FILE = "/home/paulsportsza/bot/data/telethon_session.string"
BOT = "mzansiedge_bot"


async def main():
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    from telethon.events import MessageEdited

    string = open(STRING_SESSION_FILE).read().strip()
    client = TelegramClient(StringSession(string), API_ID, API_HASH)
    await client.connect()

    entity = await client.get_entity(BOT)

    # Send trigger
    print("[1] Triggering Top Edge Picks…")
    sent = await client.send_message(entity, "💎 Top Edge Picks")
    sent_id = sent.id
    await asyncio.sleep(18)

    msgs = await client.get_messages(entity, limit=10)
    recent = sorted([m for m in msgs if m.id >= sent_id], key=lambda m: m.id)

    # Find ep:pick:0 button
    list_msg = None
    target_btn = None
    for msg in recent:
        if not msg.buttons:
            continue
        for row in msg.buttons:
            for btn in row:
                cbd = getattr(btn, "data", None)
                if cbd and b"ep:pick:0" in cbd:
                    list_msg = msg
                    target_btn = btn
                    break
            if target_btn:
                break
        if target_btn:
            break

    if not target_btn:
        print("[!] No ep:pick button found")
        await client.disconnect()
        return

    # Capture event on edit
    captured = {}

    @client.on(MessageEdited(chats=BOT))
    async def on_edit(event):
        if event.message.id == list_msg.id:
            raw = event.message
            captured["raw"] = raw
            # Try all text attributes
            captured["message"] = raw.message
            captured["text"] = raw.text
            # Try to get any string content from the raw object
            captured["stringify"] = str(raw)[:2000]

    print(f"[2] Clicking ep:pick:0 on msg {list_msg.id} …")
    await target_btn.click()
    await asyncio.sleep(20)

    if "raw" in captured:
        print("\n[3] CAPTURED raw fields:")
        print(f"  .message = {captured['message']!r}")
        print(f"  .text = {captured['text']!r}")
        print(f"  str(raw)[:2000]:\n{captured['stringify']}")
    else:
        # Try fetching the message directly via API
        print("[3] No edit event captured. Fetching raw via get_messages …")
        raw_msgs = await client.get_messages(entity, ids=[list_msg.id])
        if isinstance(raw_msgs, list):
            raw_msgs = raw_msgs
        else:
            raw_msgs = [raw_msgs]
        for rm in raw_msgs:
            if rm:
                print(f"\n  MSG {rm.id}:")
                print(f"  .message = {rm.message!r}")
                print(f"  .text = {rm.text!r}")
                print(f"  .media = {rm.media}")
                # raw message object
                print(f"  str(rm)[:3000]:\n{str(rm)[:3000]}")

    await client.disconnect()


asyncio.run(main())
