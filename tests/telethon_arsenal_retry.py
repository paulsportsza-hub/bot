#!/usr/bin/env python3
"""Single-fixture retry for arsenal_fulham (isolating possible timing issue)."""
import asyncio
import os
import sys
import time

sys.path.insert(0, "/home/paulsportsza/bot")
from dotenv import load_dotenv
load_dotenv("/home/paulsportsza/bot/.env")

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import MessageMediaPhoto

SESSION_FILE = "/home/paulsportsza/bot/data/telethon_qa_session.string"
BOT_USERNAME = "mzansiedge_bot"
EVIDENCE_DIR = "/home/paulsportsza/reports/telethon-silentdrop-evidence"
MATCH_KEY = "arsenal_vs_fulham_2026-05-04"
SHORTKEY = "arsenal_fulham_retry"

with open(SESSION_FILE) as f:
    SESSION_STR = f.read().strip()
API_ID = int(os.environ["TELEGRAM_API_ID"])
API_HASH = os.environ["TELEGRAM_API_HASH"]


def content(msg) -> str:
    if msg is None:
        return ""
    out = []
    if msg.text:
        out.append(msg.text)
    if msg.media:
        cap = getattr(msg, "caption", None) or getattr(msg.media, "caption", "")
        if cap:
            out.append(cap)
    return "\n".join(out)


async def wait_for_new(client, after_id: int, timeout: int = 45):
    deadline = time.time() + timeout
    while time.time() < deadline:
        msgs = await client.get_messages(BOT_USERNAME, limit=5)
        for m in reversed(msgs):
            if m.id > after_id and m.sender_id != (await client.get_me()).id:
                return m
        await asyncio.sleep(0.8)
    return None


async def main():
    async with TelegramClient(StringSession(SESSION_STR), API_ID, API_HASH) as client:
        print("Connected")
        # ensure diamond
        await client.send_message(BOT_USERNAME, "/qa set_diamond")
        await asyncio.sleep(3)
        me_id = (await client.get_me()).id

        # Send deep link
        pre = (await client.get_messages(BOT_USERNAME, limit=1))[0].id
        print(f"Pre-send latest id: {pre}")
        await client.send_message(BOT_USERNAME, f"/start card_{MATCH_KEY}")
        print(f"Sent deep link. Waiting for bot reply (exclude me={me_id})...")

        # wait up to 45s for a NEW message from the BOT (not me)
        deadline = time.time() + 45
        reply = None
        while time.time() < deadline:
            msgs = await client.get_messages(BOT_USERNAME, limit=5)
            for m in reversed(msgs):
                if m.id > pre and m.sender_id != me_id:
                    reply = m
                    break
            if reply:
                break
            await asyncio.sleep(1.0)

        if reply is None:
            print("FAIL — no bot reply within 45s")
            return
        print(f"Got reply id={reply.id} sender={reply.sender_id}")
        print(f"Photo? {isinstance(reply.media, MessageMediaPhoto)}")
        txt = content(reply)
        print(f"Caption/text: {txt[:500]!r}")
        if reply.reply_markup:
            for i, row in enumerate(reply.reply_markup.rows):
                for b in row.buttons:
                    cb = b.data.decode() if getattr(b, 'data', None) else ''
                    print(f"  row{i}: '{b.text}' cb={cb}")
        if isinstance(reply.media, MessageMediaPhoto):
            path = os.path.join(EVIDENCE_DIR, f"level2_{SHORTKEY}.jpg")
            await reply.download_media(file=path)
            print(f"Saved {path}")

            # Tap AI Breakdown if present
            ai_btn = None
            for row in reply.reply_markup.rows:
                for b in row.buttons:
                    if "Full AI Breakdown" in (b.text or ""):
                        ai_btn = b
                        break
                if ai_btn:
                    break
            if ai_btn:
                print(f"Tapping: '{ai_btn.text}'")
                before = reply.id
                await reply.click(data=ai_btn.data)
                # wait for L3
                deadline2 = time.time() + 45
                l3 = None
                while time.time() < deadline2:
                    msgs = await client.get_messages(BOT_USERNAME, limit=5)
                    for m in reversed(msgs):
                        if m.id > before and m.sender_id != me_id:
                            l3 = m
                            break
                    if l3:
                        break
                    await asyncio.sleep(1.0)
                if l3:
                    print(f"L3 got id={l3.id} photo={isinstance(l3.media, MessageMediaPhoto)}")
                    if isinstance(l3.media, MessageMediaPhoto):
                        l3path = os.path.join(EVIDENCE_DIR, f"level3_{SHORTKEY}.jpg")
                        await l3.download_media(file=l3path)
                        print(f"Saved {l3path}")
                    if l3.reply_markup:
                        for row in l3.reply_markup.rows:
                            for b in row.buttons:
                                cb = b.data.decode() if getattr(b, 'data', None) else ''
                                print(f"  L3 btn: '{b.text}' cb={cb}")
                else:
                    print("FAIL — no L3 reply")

        # reset
        await client.send_message(BOT_USERNAME, "/qa reset")
        print("Reset sent")


if __name__ == "__main__":
    asyncio.run(main())
