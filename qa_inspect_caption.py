"""
Debug: The edge detail card is a photo with caption. Extract the caption text.
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

    print("[1] Triggering Top Edge Picks…")
    sent = await client.send_message(entity, "💎 Top Edge Picks")
    sent_id = sent.id
    await asyncio.sleep(18)

    msgs = await client.get_messages(entity, limit=10)
    recent = sorted([m for m in msgs if m.id >= sent_id], key=lambda m: m.id)

    list_msg = None
    btn_0 = None
    for msg in recent:
        if not msg.buttons:
            continue
        for row in msg.buttons:
            for btn in row:
                cbd = getattr(btn, "data", None)
                if cbd and b"ep:pick:0" in cbd:
                    list_msg = msg
                    btn_0 = btn
                    break
            if btn_0:
                break
        if btn_0:
            break

    if not btn_0:
        print("[!] No ep:pick:0 found")
        await client.disconnect()
        return

    # Collect button data for all pick buttons
    all_pick_buttons = []
    for msg in recent:
        if not msg.buttons:
            continue
        for row in msg.buttons:
            for btn in row:
                cbd = getattr(btn, "data", None)
                if cbd and b"ep:pick:" in cbd:
                    all_pick_buttons.append((msg, btn))

    print(f"[2] Found {len(all_pick_buttons)} pick buttons")

    # Test clicking each one and capturing caption
    results = []
    clicked = set()
    for list_m, btn in all_pick_buttons[:7]:
        cbd = getattr(btn, "data", b"")
        if cbd in clicked:
            continue
        clicked.add(cbd)

        captured = {}

        @client.on(MessageEdited(chats=BOT))
        async def on_edit(event):
            raw = event.message
            # Try to get caption from media
            caption = ""
            if hasattr(raw, "message") and raw.message:
                caption = raw.message
            elif hasattr(raw, "text") and raw.text:
                caption = raw.text
            # PTB sends photos with caption stored in 'message' field
            # In Telethon, for media messages, .message holds the caption
            captured["msg_id"] = raw.id
            captured["caption"] = caption
            captured["raw_message_attr"] = raw.message
            captured["raw_text_attr"] = raw.text
            # Try accessing via the raw TL object
            try:
                captured["tl_message"] = raw.original_update.message.message
            except Exception:
                captured["tl_message"] = "N/A"

        print(f"\n[3] Clicking '{btn.text}'…")
        await btn.click()
        await asyncio.sleep(16)

        client.remove_event_handler(on_edit)

        print(f"   captured: {captured}")

        # Also try fetching directly
        fetched = await client.get_messages(entity, ids=[list_m.id])
        if isinstance(fetched, list) and fetched:
            fm = fetched[0]
        else:
            fm = fetched
        if fm:
            print(f"   Direct fetch .message: {repr(fm.message)[:300]}")
            print(f"   Direct fetch .text: {repr(fm.text)[:300]}")
            # Try getting caption from media photo
            if fm.media and hasattr(fm.media, "caption"):
                print(f"   Media caption: {repr(fm.media.caption)[:300]}")

        results.append({
            "btn": btn.text,
            "captured": captured,
        })

        # Go back
        latest = await client.get_messages(entity, limit=3)
        for lm in sorted(latest, key=lambda m: m.id, reverse=True):
            if lm.buttons:
                for row in lm.buttons:
                    for b in row:
                        bdata = getattr(b, "data", None)
                        if bdata and b"hot:back" in bdata:
                            try:
                                await b.click()
                                await asyncio.sleep(8)
                            except Exception:
                                pass
                break

    await client.disconnect()
    print("\n\nSummary:", results)


asyncio.run(main())
