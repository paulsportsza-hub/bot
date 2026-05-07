#!/usr/bin/env python3
"""Quick probe: send '💎 Top Edge Picks' and dump what comes back."""
from __future__ import annotations
import asyncio, os, sys, time
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import KeyboardButtonCallback

API_ID = int(os.getenv("TELEGRAM_API_ID", "32418601"))
API_HASH = os.getenv("TELEGRAM_API_HASH")
BOT = "@mzansiedge_bot"
S_FILE = Path("/home/paulsportsza/bot/data/telethon_qa_session.string")


async def main():
    session = StringSession(S_FILE.read_text().strip())
    async with TelegramClient(session, API_ID, API_HASH) as client:
        ent = await client.get_entity(BOT)
        me = await client.get_me()

        baseline = (await client.get_messages(ent, limit=1))
        anchor = baseline[0].id if baseline else 0
        print(f"anchor id = {anchor}")

        await client.send_message(ent, "/qa set_diamond")
        await asyncio.sleep(1.5)

        await client.send_message(ent, "💎 Top Edge Picks")
        print("sent")

        # poll 20s
        found = None
        deadline = time.time() + 25
        while time.time() < deadline:
            await asyncio.sleep(0.8)
            msgs = await client.get_messages(ent, limit=6)
            for m in msgs:
                if m.sender_id == me.id: continue
                if m.id <= anchor: continue
                t = (m.text or "")
                if len(t) > 100 and m.reply_markup:
                    found = m
                    break
            if found:
                break

        if not found:
            print("NO MESSAGE FOUND — last 6:")
            for m in msgs:
                print(f"  id={m.id} sender={m.sender_id} text={(m.text or '')[:120]!r}")
            return

        print(f"\n=== MSG id={found.id} ===")
        print(f"TEXT (first 600): {found.text[:600]!r}")
        print("\nBUTTONS:")
        if found.reply_markup:
            for ri, row in enumerate(found.reply_markup.rows):
                for bi, btn in enumerate(row.buttons):
                    data = btn.data.decode("utf-8", errors="replace") if isinstance(btn.data, (bytes, bytearray)) else ""
                    print(f"  [{ri},{bi}] text={btn.text!r:40}  data={data!r}")


if __name__ == "__main__":
    asyncio.run(main())
