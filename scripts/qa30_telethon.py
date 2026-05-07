#!/usr/bin/env python3
"""QA-30: Telethon E2E — capture Hot Tips + My Matches cards for scoring."""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import re
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
STRING_SESSION = Path(__file__).resolve().parent.parent / "data" / "telethon_qa_session.string"
FILE_SESSION = Path(__file__).resolve().parent.parent / "data" / "telethon_qa_session"

OUTPUT_DIR = Path(__file__).resolve().parent.parent.parent / "reports" / "qa30-captures"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


async def get_client() -> TelegramClient:
    if STRING_SESSION.exists():
        s = STRING_SESSION.read_text().strip()
        if s:
            c = TelegramClient(StringSession(s), API_ID, API_HASH)
            await c.connect()
            if await c.is_user_authorized():
                return c
            await c.disconnect()
    c = TelegramClient(str(FILE_SESSION), API_ID, API_HASH)
    await c.connect()
    if not await c.is_user_authorized():
        print("ERROR: Not logged in")
        sys.exit(1)
    return c


def get_text(msg) -> str:
    return msg.message or msg.text or ""


def get_buttons(msg):
    cb_buttons, url_buttons = [], []
    if not msg.reply_markup or not isinstance(msg.reply_markup, ReplyInlineMarkup):
        return cb_buttons, url_buttons
    for row in msg.reply_markup.rows:
        for btn in row.buttons:
            if isinstance(btn, KeyboardButtonCallback):
                cb_buttons.append({"text": btn.text, "data": btn.data.decode() if isinstance(btn.data, bytes) else btn.data})
            elif isinstance(btn, KeyboardButtonUrl):
                url_buttons.append({"text": btn.text, "url": btn.url})
    return cb_buttons, url_buttons


async def wait_for_response(client, bot_entity, after_id, timeout=30):
    """Wait for a new message from the bot after the given message ID."""
    start = time.time()
    while time.time() - start < timeout:
        msgs = await client.get_messages(bot_entity, limit=5)
        for m in msgs:
            if m.id > after_id and not m.out:
                return m
        await asyncio.sleep(1.0)
    return None


async def wait_for_edit(client, bot_entity, msg_id, initial_text, timeout=45):
    """Wait for a message to be edited (content changes from initial_text)."""
    start = time.time()
    while time.time() - start < timeout:
        msgs = await client.get_messages(bot_entity, ids=[msg_id])
        if msgs and msgs[0]:
            current = get_text(msgs[0])
            if current != initial_text and "Loading" not in current and "Analysing" not in current and "..." not in current[:30]:
                return msgs[0]
        await asyncio.sleep(1.5)
    # Return whatever we have
    msgs = await client.get_messages(bot_entity, ids=[msg_id])
    return msgs[0] if msgs else None


async def tap_callback(client, bot_entity, msg, callback_data: str, timeout=30):
    """Tap a callback button and wait for response/edit."""
    cb_buttons, _ = get_buttons(msg)
    target = None
    for btn in cb_buttons:
        if btn["data"] == callback_data or btn["data"].startswith(callback_data):
            target = btn
            break
    if not target:
        print(f"  WARNING: callback '{callback_data}' not found in buttons: {[b['data'] for b in cb_buttons]}")
        return None

    initial_text = get_text(msg)
    await msg.click(data=target["data"].encode() if isinstance(target["data"], str) else target["data"])
    await asyncio.sleep(2.0)

    # Check if message was edited
    edited = await wait_for_edit(client, bot_entity, msg.id, initial_text, timeout=timeout)
    if edited and get_text(edited) != initial_text:
        return edited

    # Check for new message
    new_msg = await wait_for_response(client, bot_entity, msg.id, timeout=5)
    return new_msg or edited


async def main():
    client = await get_client()
    bot = await client.get_entity(BOT_USERNAME)

    captures = {"hot_tips_list": [], "hot_tips_detail": [], "my_matches_list": [], "my_matches_detail": []}

    # ---- Phase A: Hot Tips (HT Panel) ----
    print("=" * 60)
    print("PHASE A: HOT TIPS (Top Edge Picks)")
    print("=" * 60)

    # Send the hot tips keyboard tap
    last_msg = await client.send_message(bot, "💎 Top Edge Picks")
    await asyncio.sleep(3.0)

    # Get the response
    msgs = await client.get_messages(bot, limit=10)
    ht_msg = None
    for m in msgs:
        if not m.out and m.id > last_msg.id:
            text = get_text(m)
            if "Edge Picks" in text or "Live Edges" in text or "edge" in text.lower():
                ht_msg = m
                break

    if not ht_msg:
        # Try waiting longer - might be loading
        await asyncio.sleep(8.0)
        msgs = await client.get_messages(bot, limit=10)
        for m in msgs:
            if not m.out and m.id > last_msg.id:
                ht_msg = m
                break

    if not ht_msg:
        print("ERROR: No Hot Tips response received")
        return

    ht_text = get_text(ht_msg)
    ht_cbs, ht_urls = get_buttons(ht_msg)
    print(f"\nHot Tips list captured ({len(ht_text)} chars)")
    captures["hot_tips_list"].append({
        "text": ht_text,
        "callback_buttons": ht_cbs,
        "url_buttons": ht_urls,
    })

    # Save raw list
    with open(OUTPUT_DIR / "ht_list_raw.txt", "w") as f:
        f.write(ht_text)

    # Find edge detail buttons
    edge_buttons = [b for b in ht_cbs if b["data"].startswith("edge:detail:")]
    print(f"Found {len(edge_buttons)} edge detail buttons")

    # Tap each detail button (up to 6 for HT panel)
    for i, btn in enumerate(edge_buttons[:8]):
        print(f"\n  Tapping HT card [{i+1}]: {btn['text'][:40]}... ({btn['data']})")
        detail_msg = await tap_callback(client, bot, ht_msg, btn["data"], timeout=45)
        if detail_msg:
            detail_text = get_text(detail_msg)
            detail_cbs, detail_urls = get_buttons(detail_msg)
            captures["hot_tips_detail"].append({
                "index": i + 1,
                "button_text": btn["text"],
                "callback_data": btn["data"],
                "text": detail_text,
                "callback_buttons": detail_cbs,
                "url_buttons": detail_urls,
            })
            with open(OUTPUT_DIR / f"ht_detail_{i+1}.txt", "w") as f:
                f.write(detail_text)
            print(f"    Captured: {len(detail_text)} chars")

            # Navigate back
            back_btns = [b for b in detail_cbs if "back" in b["data"].lower() or "hot:back" in b["data"]]
            if back_btns:
                await tap_callback(client, bot, detail_msg, back_btns[0]["data"], timeout=10)
                await asyncio.sleep(1.5)
                # Re-fetch the list message
                msgs = await client.get_messages(bot, ids=[ht_msg.id])
                if msgs and msgs[0]:
                    ht_msg = msgs[0]
        else:
            print(f"    WARNING: No response for {btn['data']}")
        await asyncio.sleep(1.0)

    # ---- Phase B: My Matches (MM Panel) ----
    print("\n" + "=" * 60)
    print("PHASE B: MY MATCHES")
    print("=" * 60)

    last_msg = await client.send_message(bot, "⚽ My Matches")
    await asyncio.sleep(3.0)

    msgs = await client.get_messages(bot, limit=10)
    mm_msg = None
    for m in msgs:
        if not m.out and m.id > last_msg.id:
            text = get_text(m)
            if "Match" in text or "game" in text.lower() or "[" in text:
                mm_msg = m
                break

    if not mm_msg:
        await asyncio.sleep(8.0)
        msgs = await client.get_messages(bot, limit=10)
        for m in msgs:
            if not m.out and m.id > last_msg.id:
                mm_msg = m
                break

    if not mm_msg:
        print("ERROR: No My Matches response")
    else:
        mm_text = get_text(mm_msg)
        mm_cbs, mm_urls = get_buttons(mm_msg)
        print(f"\nMy Matches list captured ({len(mm_text)} chars)")
        captures["my_matches_list"].append({
            "text": mm_text,
            "callback_buttons": mm_cbs,
            "url_buttons": mm_urls,
        })

        with open(OUTPUT_DIR / "mm_list_raw.txt", "w") as f:
            f.write(mm_text)

        # Find game detail buttons
        game_buttons = [b for b in mm_cbs if b["data"].startswith("yg:game:")]
        print(f"Found {len(game_buttons)} game detail buttons")

        for i, btn in enumerate(game_buttons[:6]):
            print(f"\n  Tapping MM card [{i+1}]: {btn['text'][:40]}... ({btn['data']})")
            detail_msg = await tap_callback(client, bot, mm_msg, btn["data"], timeout=45)
            if detail_msg:
                detail_text = get_text(detail_msg)
                detail_cbs, detail_urls = get_buttons(detail_msg)
                captures["my_matches_detail"].append({
                    "index": i + 1,
                    "button_text": btn["text"],
                    "callback_data": btn["data"],
                    "text": detail_text,
                    "callback_buttons": detail_cbs,
                    "url_buttons": detail_urls,
                })
                with open(OUTPUT_DIR / f"mm_detail_{i+1}.txt", "w") as f:
                    f.write(detail_text)
                print(f"    Captured: {len(detail_text)} chars")

                # Navigate back
                back_btns = [b for b in detail_cbs if "yg:all" in b["data"] or "back" in b["data"].lower()]
                if back_btns:
                    await tap_callback(client, bot, detail_msg, back_btns[0]["data"], timeout=10)
                    await asyncio.sleep(1.5)
                    msgs = await client.get_messages(bot, ids=[mm_msg.id])
                    if msgs and msgs[0]:
                        mm_msg = msgs[0]
            else:
                print(f"    WARNING: No response for {btn['data']}")
            await asyncio.sleep(1.0)

    # Save all captures
    with open(OUTPUT_DIR / "qa30_all_captures.json", "w") as f:
        json.dump(captures, f, indent=2, default=str)

    print("\n" + "=" * 60)
    print(f"CAPTURE COMPLETE")
    print(f"  HT details: {len(captures['hot_tips_detail'])}")
    print(f"  MM details: {len(captures['my_matches_detail'])}")
    print(f"  Total cards: {len(captures['hot_tips_detail']) + len(captures['my_matches_detail'])}")
    print(f"  Output: {OUTPUT_DIR}")
    print("=" * 60)

    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
