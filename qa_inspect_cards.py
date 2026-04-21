"""
Debug: Inspect what the bot actually sends when ep:pick buttons are clicked.
"""
import asyncio
import os
import re
import html as html_mod
from dotenv import load_dotenv

load_dotenv("/home/paulsportsza/bot/.env")

API_ID = int(os.environ["TELEGRAM_API_ID"])
API_HASH = os.environ["TELEGRAM_API_HASH"]
STRING_SESSION_FILE = "/home/paulsportsza/bot/data/telethon_session.string"
BOT = "mzansiedge_bot"


def strip_html(text: str) -> str:
    clean = re.sub(r"<[^>]+>", "", text)
    return html_mod.unescape(clean).strip()


async def main():
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    string = open(STRING_SESSION_FILE).read().strip()
    client = TelegramClient(StringSession(string), API_ID, API_HASH)
    await client.connect()

    entity = await client.get_entity(BOT)

    # Trigger Top Edge Picks
    print("[1] Sending '💎 Top Edge Picks' …")
    sent = await client.send_message(entity, "💎 Top Edge Picks")
    sent_id = sent.id
    await asyncio.sleep(20)

    msgs = await client.get_messages(entity, limit=20)
    recent = sorted([m for m in msgs if m.id >= sent_id], key=lambda m: m.id)
    print(f"[2] {len(recent)} messages received\n")

    # Show all messages in full
    for msg in recent:
        print(f"=== MSG {msg.id} ===")
        text = msg.text or msg.message or ""
        print(f"Text (first 600 chars):\n{text[:600]}")
        print(f"Has buttons: {bool(msg.buttons)}")
        if msg.buttons:
            for i, row in enumerate(msg.buttons):
                for btn in row:
                    cbd = getattr(btn, "data", None)
                    print(f"  Row {i}: {btn.text!r}  cb={cbd}")
        print()

    # Find the first ep:pick button and click it
    target_msg = None
    target_btn = None
    for msg in recent:
        if not msg.buttons:
            continue
        for row in msg.buttons:
            for btn in row:
                cbd = getattr(btn, "data", None)
                if cbd and b"ep:pick:0" in cbd:
                    target_msg = msg
                    target_btn = btn
                    break
            if target_btn:
                break
        if target_btn:
            break

    if not target_btn:
        print("[!] No ep:pick:0 button found")
        await client.disconnect()
        return

    print(f"[3] Clicking '{target_btn.text}' on msg {target_msg.id} …")
    await target_btn.click()
    await asyncio.sleep(16)

    # Fetch ALL messages now — the detail may be an EDIT of the list msg
    msgs2 = await client.get_messages(entity, limit=30)
    print(f"\n[4] After click: {len(msgs2)} messages total")

    for msg in sorted(msgs2, key=lambda m: m.id)[-10:]:
        print(f"\n=== MSG {msg.id} (edited: {msg.edit_date}) ===")
        text = msg.text or msg.message or ""
        print(f"Text (first 600 chars):\n{text[:600]}")
        if msg.buttons:
            for row in msg.buttons:
                for btn in row:
                    cbd = getattr(btn, "data", None)
                    print(f"  Btn: {btn.text!r}  cb={cbd}")

    await client.disconnect()


asyncio.run(main())
