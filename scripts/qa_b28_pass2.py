#!/usr/bin/env python3
"""QA-BASELINE-28 Pass 2: Capture cards 1-4 from page 1 (fresh trigger)."""
from __future__ import annotations
import asyncio, json, os, sys, time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import ReplyInlineMarkup, KeyboardButtonCallback, KeyboardButtonUrl
from telethon.tl.functions.messages import GetBotCallbackAnswerRequest

API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "")
BOT_USERNAME = "mzansiedge_bot"
STRING_SESSION_FILE = Path(__file__).resolve().parent.parent / "data" / "telethon_session.string"

OUTPUT_FILE = Path(__file__).resolve().parent.parent.parent / "reports" / "qa-b28-pass2-captures.json"


def get_text(msg):
    if msg is None: return ""
    return msg.message or msg.text or ""


def get_buttons(msg):
    cb, url = [], []
    if msg is None or not msg.reply_markup or not isinstance(msg.reply_markup, ReplyInlineMarkup):
        return cb, url
    for row in msg.reply_markup.rows:
        for btn in row.buttons:
            if isinstance(btn, KeyboardButtonCallback):
                d = btn.data.decode("utf-8", errors="replace") if isinstance(btn.data, bytes) else str(btn.data)
                cb.append({"text": btn.text, "data": d})
            elif isinstance(btn, KeyboardButtonUrl):
                url.append({"text": btn.text, "url": btn.url})
    return cb, url


async def main():
    s = Path(STRING_SESSION_FILE).read_text().strip()
    client = TelegramClient(StringSession(s), API_ID, API_HASH)
    await client.connect()
    if not await client.is_user_authorized():
        print("ERROR: Not logged in"); return
    bot = await client.get_entity(BOT_USERNAME)
    print(f"Connected to @{BOT_USERNAME}")

    cards = []

    # Trigger fresh list
    ts = time.time()
    await client.send_message(bot, "\U0001f48e Top Edge Picks")
    print("Sent Top Edge Picks, waiting 8s...")
    await asyncio.sleep(8.0)

    msgs = await client.get_messages(bot, limit=3)
    list_msg = None
    for m in msgs:
        if m.date.timestamp() > ts - 2 and len(get_text(m)) > 100:
            list_msg = m; break

    if not list_msg:
        print("No response"); await client.disconnect(); return

    msg_id = list_msg.id
    print(f"List msg_id={msg_id}, {len(get_text(list_msg))} chars")

    # Identify page 1 detail buttons
    cbs, _ = get_buttons(list_msg)
    detail_btns = [b for b in cbs if b["data"].startswith("edge:detail:")]
    print(f"Page 1 has {len(detail_btns)} detail buttons:")
    for b in detail_btns:
        print(f"  {b['text']} -> {b['data']}")

    # Press each one, capture, go back
    for i, btn in enumerate(detail_btns):
        print(f"\n--- Card {i+1}: {btn['text']} ---")

        # Press detail button
        try:
            await client(GetBotCallbackAnswerRequest(peer=bot, msg_id=msg_id, data=btn["data"].encode()))
        except Exception:
            pass
        await asyncio.sleep(6.0)

        # Fetch updated message
        fetched = await client.get_messages(bot, ids=[msg_id])
        detail = fetched[0] if fetched and fetched[0] else None
        detail_text = get_text(detail)
        detail_cb, detail_url = get_buttons(detail)

        # If still loading, wait more
        if len(detail_text) < 150 or "loading" in detail_text.lower():
            print("  Still loading, waiting 20s...")
            await asyncio.sleep(20.0)
            fetched = await client.get_messages(bot, ids=[msg_id])
            detail = fetched[0] if fetched and fetched[0] else None
            detail_text = get_text(detail)
            detail_cb, detail_url = get_buttons(detail)

        print(f"  Captured: {len(detail_text)} chars")
        print(f"  Preview: {detail_text[:200]}")

        cards.append({
            "card_num": i + 1,
            "btn_text": btn["text"],
            "callback_data": btn["data"],
            "source": "telethon_e2e",
            "text": detail_text,
            "cb_buttons": detail_cb,
            "url_buttons": detail_url,
            "captured_at": datetime.now(timezone.utc).isoformat(),
        })

        # Go back - find hot:back button
        back_pressed = False
        for b2 in detail_cb:
            if "hot:back" in b2["data"]:
                try:
                    await client(GetBotCallbackAnswerRequest(peer=bot, msg_id=msg_id, data=b2["data"].encode()))
                except Exception:
                    pass
                await asyncio.sleep(3.0)
                back_pressed = True
                break

        if not back_pressed:
            # Re-trigger fresh
            ts2 = time.time()
            await client.send_message(bot, "\U0001f48e Top Edge Picks")
            await asyncio.sleep(8.0)
            msgs2 = await client.get_messages(bot, limit=3)
            for m2 in msgs2:
                if m2.date.timestamp() > ts2 - 2 and len(get_text(m2)) > 100:
                    msg_id = m2.id; break

    with open(OUTPUT_FILE, "w") as f:
        json.dump({"cards": cards}, f, indent=2, ensure_ascii=False)
    print(f"\nSaved to {OUTPUT_FILE}")
    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
