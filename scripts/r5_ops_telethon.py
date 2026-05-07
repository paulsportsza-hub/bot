#!/usr/bin/env python3
"""R5-OPS-01: Telethon verification — capture 3 edge cards from live bot."""
from __future__ import annotations

import asyncio
import os
import sys
import re
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import (
    ReplyInlineMarkup,
    KeyboardButtonCallback,
    KeyboardButtonUrl,
)

API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "")
BOT_USERNAME = "mzansiedge_bot"
STRING_SESSION_FILE = Path(__file__).resolve().parent.parent / "data" / "telethon_qa_session.string"
FILE_SESSION = Path(__file__).resolve().parent.parent / "data" / "telethon_qa_session"
from config import BOT_ROOT
OUTPUT_DIR = BOT_ROOT.parent / "reports" / "r5-ops"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


async def get_client() -> TelegramClient:
    if STRING_SESSION_FILE.exists():
        s = STRING_SESSION_FILE.read_text().strip()
        if s:
            c = TelegramClient(StringSession(s), API_ID, API_HASH)
            await c.connect()
            if await c.is_user_authorized():
                return c
            await c.disconnect()
    c = TelegramClient(str(FILE_SESSION), API_ID, API_HASH)
    await c.connect()
    if not await c.is_user_authorized():
        print("ERROR: Not logged in"); sys.exit(1)
    return c


def get_text(msg) -> str:
    return msg.message or msg.text or ""


def get_buttons(msg):
    if not msg.reply_markup or not isinstance(msg.reply_markup, ReplyInlineMarkup):
        return []
    btns = []
    for row in msg.reply_markup.rows:
        for btn in row.buttons:
            btns.append(btn)
    return btns


def find_edge_detail_buttons(msg):
    """Find buttons with edge:detail callback data."""
    detail_btns = []
    for btn in get_buttons(msg):
        if isinstance(btn, KeyboardButtonCallback):
            data = btn.data.decode() if isinstance(btn.data, bytes) else str(btn.data)
            if data.startswith("edge:detail:"):
                detail_btns.append(btn)
    return detail_btns


async def send_and_wait(client, bot, text, wait=8):
    await client.send_message(bot, text)
    await asyncio.sleep(wait)
    msgs = await client.get_messages(bot, limit=5)
    return msgs


async def click_and_wait(client, msg, btn, wait=12):
    """Click an inline button and wait for the message to be edited."""
    await msg.click(data=btn.data)
    await asyncio.sleep(wait)
    refreshed = await client.get_messages(msg.peer_id, ids=msg.id)
    return refreshed


async def main():
    print("=" * 60)
    print("R5-OPS-01: Telethon Edge Card Verification")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    client = await get_client()
    bot = await client.get_entity(BOT_USERNAME)
    results = []

    # --- Step 1: Request Top Edge Picks ---
    print("\n[1] Sending 💎 Top Edge Picks...")
    msgs = await send_and_wait(client, bot, "💎 Top Edge Picks", wait=15)

    # Find the tips list message (has edge:detail buttons)
    list_msg = None
    list_text = ""
    for m in msgs:
        btns = find_edge_detail_buttons(m)
        if btns:
            list_msg = m
            list_text = get_text(m)
            break

    if not list_msg:
        # Try the most recent message as fallback
        for m in msgs:
            txt = get_text(m)
            if "edge" in txt.lower() or "pick" in txt.lower() or "[1]" in txt:
                list_msg = m
                list_text = txt
                break

    if not list_msg:
        print("ERROR: No Hot Tips / Edge Picks response found")
        print("Last 3 messages:")
        for m in msgs[:3]:
            print(f"  [{m.id}] {get_text(m)[:200]}")
        await client.disconnect()
        return

    print(f"\n--- HOT TIPS LIST ---")
    print(list_text)
    print(f"--- END LIST ---\n")
    results.append({"type": "list", "text": list_text})

    # --- Step 2: Click up to 3 detail buttons ---
    detail_btns = find_edge_detail_buttons(list_msg)
    print(f"Found {len(detail_btns)} edge detail buttons")

    cards_captured = 0
    max_cards = min(3, len(detail_btns))

    for i in range(max_cards):
        btn = detail_btns[i]
        btn_data = btn.data.decode() if isinstance(btn.data, bytes) else str(btn.data)
        btn_text = btn.text or "(no label)"
        print(f"\n[{i+1}/{max_cards}] Clicking: {btn_text} ({btn_data})")

        # Re-fetch the list first (navigate back to fresh list)
        if i > 0:
            # Send fresh request to get new list message
            print("  Re-requesting edge picks for fresh message...")
            msgs2 = await send_and_wait(client, bot, "💎 Top Edge Picks", wait=15)
            for m in msgs2:
                btns2 = find_edge_detail_buttons(m)
                if btns2:
                    list_msg = m
                    detail_btns_fresh = btns2
                    # Find the matching button by data
                    for fb in detail_btns_fresh:
                        fd = fb.data.decode() if isinstance(fb.data, bytes) else str(fb.data)
                        if fd == btn_data:
                            btn = fb
                            break
                    break

        # Click the detail button
        detail_msg = await click_and_wait(client, list_msg, btn, wait=15)
        if detail_msg:
            detail_text = get_text(detail_msg)
            # Check if it's actually different from the list
            if detail_text and detail_text != list_text:
                print(f"\n--- CARD {i+1} ---")
                print(detail_text)

                # Also capture URL buttons
                url_btns = [b for b in get_buttons(detail_msg)
                            if isinstance(b, KeyboardButtonUrl)]
                if url_btns:
                    for ub in url_btns:
                        print(f"  [URL] {ub.text}: {ub.url}")

                print(f"--- END CARD {i+1} ---\n")
                results.append({
                    "type": "card",
                    "index": i + 1,
                    "btn_data": btn_data,
                    "text": detail_text,
                    "url_buttons": [{"text": b.text, "url": b.url}
                                    for b in url_btns] if url_btns else []
                })
                cards_captured += 1
            else:
                # Message might not have been edited yet — wait more and re-fetch
                print("  Detail didn't load yet, waiting 10 more seconds...")
                await asyncio.sleep(10)
                detail_msg2 = await client.get_messages(list_msg.peer_id, ids=list_msg.id)
                if detail_msg2:
                    detail_text2 = get_text(detail_msg2)
                    if detail_text2 and detail_text2 != list_text:
                        print(f"\n--- CARD {i+1} (delayed) ---")
                        print(detail_text2)
                        print(f"--- END CARD {i+1} ---\n")
                        results.append({
                            "type": "card",
                            "index": i + 1,
                            "btn_data": btn_data,
                            "text": detail_text2,
                        })
                        cards_captured += 1
                    else:
                        print(f"  WARN: Card {i+1} still showing list content after 25s total")
        else:
            print(f"  WARN: No response for card {i+1}")

    # --- Summary ---
    print("\n" + "=" * 60)
    print(f"RESULT: {cards_captured}/{max_cards} cards captured")
    print("=" * 60)

    # Save raw output
    ts = datetime.now().strftime("%Y%m%d-%H%M")
    outfile = OUTPUT_DIR / f"r5-ops-telethon-{ts}.txt"
    with open(outfile, "w") as f:
        f.write(f"R5-OPS-01: Telethon Edge Card Verification\n")
        f.write(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("=" * 60 + "\n\n")
        for r in results:
            if r["type"] == "list":
                f.write("=== HOT TIPS LIST ===\n")
                f.write(r["text"] + "\n\n")
            else:
                f.write(f"=== CARD {r['index']} ({r.get('btn_data','')}) ===\n")
                f.write(r["text"] + "\n")
                for ub in r.get("url_buttons", []):
                    f.write(f"  [URL] {ub['text']}: {ub['url']}\n")
                f.write("\n")

    print(f"\nSaved to: {outfile}")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
