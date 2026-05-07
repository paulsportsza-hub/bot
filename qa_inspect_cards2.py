"""
Debug: Capture the FULL text of the edited message after ep:pick click.
The detail is in an EDITED message (same msg ID). We need to track the
specific message being edited.
"""
import asyncio
import os
import re
import html as html_mod
from dotenv import load_dotenv

load_dotenv("/home/paulsportsza/bot/.env")

API_ID = int(os.environ["TELEGRAM_API_ID"])
API_HASH = os.environ["TELEGRAM_API_HASH"]
STRING_SESSION_FILE = "/home/paulsportsza/bot/data/telethon_qa_session.string"
BOT = "mzansiedge_bot"


async def main():
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    from telethon.events import MessageEdited

    string = open(STRING_SESSION_FILE).read().strip()
    client = TelegramClient(StringSession(string), API_ID, API_HASH)
    await client.connect()

    entity = await client.get_entity(BOT)

    # Trigger Top Edge Picks
    print("[1] Sending '💎 Top Edge Picks' …")
    sent = await client.send_message(entity, "💎 Top Edge Picks")
    sent_id = sent.id
    await asyncio.sleep(20)

    msgs = await client.get_messages(entity, limit=10)
    recent = sorted([m for m in msgs if m.id >= sent_id], key=lambda m: m.id)

    # Find the message with ep:pick buttons
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
        print("[!] No ep:pick:0 found")
        await client.disconnect()
        return

    print(f"[2] List message ID: {list_msg.id}")
    _lt = repr(list_msg.text)[:200]
    print(f"[2] List message text: {_lt}")

    # Register a handler to capture the edited message
    edited_content = {"text": None, "buttons": None}

    @client.on(MessageEdited(chats=BOT))
    async def on_edit(event):
        if event.message.id == list_msg.id:
            edited_content["text"] = event.message.message or event.message.text or ""
            edited_content["buttons"] = event.message.buttons
            print(f"   [EDIT CAPTURED] msg {event.message.id}")
            print(f"   Text: {edited_content['text'][:500]!r}")

    print(f"\n[3] Clicking '{target_btn.text}' …")
    await target_btn.click()
    await asyncio.sleep(20)  # Wait for edit event

    # Also manually re-fetch the message
    refetched = await client.get_messages(entity, ids=[list_msg.id])
    if refetched:
        rm = refetched[0] if isinstance(refetched, list) else refetched
        print(f"\n[4] Re-fetched msg {rm.id}:")
        text = rm.message or rm.text or ""
        print(f"   Text (full): {text!r}")
        if rm.buttons:
            for row in rm.buttons:
                for btn in row:
                    cbd = getattr(btn, "data", None)
                    print(f"   Btn: {btn.text!r}  cb={cbd}")

    if edited_content["text"]:
        print(f"\n[5] Edit event captured:")
        print(f"   Full text: {edited_content['text']!r}")
    else:
        print("\n[5] No edit event captured via handler — trying fresh fetch of recent msgs")
        msgs3 = await client.get_messages(entity, limit=5)
        for m in sorted(msgs3, key=lambda x: x.id, reverse=True)[:3]:
            text = m.message or m.text or ""
            print(f"   MSG {m.id} (edited={m.edit_date}): {text[:400]!r}")
            if m.buttons:
                for row in m.buttons:
                    for b in row:
                        print(f"     Btn: {b.text!r}  cb={getattr(b, 'data', None)}")

    await client.disconnect()


asyncio.run(main())
