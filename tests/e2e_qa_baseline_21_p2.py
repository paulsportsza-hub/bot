#!/usr/bin/env python3
"""QA-BASELINE-21 Part 2: Capture page 2 detail cards + remaining MM cards."""

import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import ReplyInlineMarkup, KeyboardButtonCallback, KeyboardButtonUrl

API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "")
BOT = "mzansiedge_bot"
STRING_SESSION_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "telethon_qa_session.string")
SESSION_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "telethon_qa_session")

_entity = None

async def get_client():
    if os.path.exists(STRING_SESSION_FILE):
        s = open(STRING_SESSION_FILE).read().strip()
        if s:
            c = TelegramClient(StringSession(s), API_ID, API_HASH)
            await c.connect()
            if await c.is_user_authorized():
                return c
            await c.disconnect()
    c = TelegramClient(SESSION_FILE, API_ID, API_HASH)
    await c.connect()
    if not await c.is_user_authorized():
        sys.exit(1)
    return c

async def entity(client):
    global _entity
    if not _entity:
        _entity = await client.get_entity(BOT)
    return _entity

def get_buttons(msg):
    if not msg or not msg.reply_markup:
        return []
    buttons = []
    if isinstance(msg.reply_markup, ReplyInlineMarkup):
        for row in msg.reply_markup.rows:
            for btn in row.buttons:
                if isinstance(btn, KeyboardButtonCallback):
                    data = btn.data.decode("utf-8", errors="replace") if btn.data else ""
                    buttons.append({"text": btn.text, "data": data, "type": "callback"})
                elif isinstance(btn, KeyboardButtonUrl):
                    buttons.append({"text": btn.text, "url": btn.url, "type": "url"})
    return buttons

async def send_and_wait(client, text, wait=25):
    ent = await entity(client)
    t0 = time.time()
    sent = await client.send_message(ent, text)
    deadline = t0 + wait
    bot_msgs = []
    last_check = []
    while time.time() < deadline:
        await asyncio.sleep(1.0)
        messages = await client.get_messages(ent, limit=30)
        new = [m for m in messages if m.id > sent.id and not m.out]
        if new:
            if len(new) == len(last_check):
                latest = new[0]
                if latest.text and len(latest.text) > 30:
                    if "Loading" not in (latest.text or "") and "..." not in (latest.text or "")[-10:]:
                        bot_msgs = list(reversed(new))
                        break
            last_check = new
    if not bot_msgs:
        messages = await client.get_messages(ent, limit=30)
        new = [m for m in messages if m.id > sent.id and not m.out]
        bot_msgs = list(reversed(new))
    return bot_msgs, time.time() - t0

async def click_and_wait(client, msg, callback_data, wait=35):
    """Click a button and wait for response."""
    if not msg or not msg.reply_markup:
        return None, [], 0.0
    if isinstance(msg.reply_markup, ReplyInlineMarkup):
        for row in msg.reply_markup.rows:
            for btn in row.buttons:
                if isinstance(btn, KeyboardButtonCallback):
                    data = btn.data.decode("utf-8", errors="replace") if btn.data else ""
                    if data == callback_data:
                        t0 = time.time()
                        try:
                            await msg.click(data=btn.data)
                        except Exception as e:
                            print(f"    Click error: {e}")
                            return None, [], time.time() - t0
                        ent = await entity(client)
                        await asyncio.sleep(2)
                        deadline = t0 + wait
                        while time.time() < deadline:
                            edited = await client.get_messages(ent, ids=msg.id)
                            all_msgs = await client.get_messages(ent, limit=30)
                            new = [m for m in all_msgs if m.id > msg.id and not m.out]
                            if edited and edited.text and edited.text != msg.text:
                                return edited, list(reversed(new)), time.time() - t0
                            if new:
                                for nm in new:
                                    if nm.text and len(nm.text) > 50:
                                        return edited, list(reversed(new)), time.time() - t0
                            await asyncio.sleep(1)
                        edited = await client.get_messages(ent, ids=msg.id)
                        all_msgs = await client.get_messages(ent, limit=30)
                        new = [m for m in all_msgs if m.id > msg.id and not m.out]
                        return edited, list(reversed(new)), time.time() - t0
    return None, [], 0.0


async def main():
    print("QA-BASELINE-21 Part 2 — Remaining Cards")
    client = await get_client()
    print("Connected.")
    captures = {"page2_details": [], "mm_details": []}

    try:
        # ── Part A: Page 2 detail cards ──
        print("\n=== PAGE 2 DETAIL CARDS ===")
        # Send Hot Tips to get fresh message
        msgs, _ = await send_and_wait(client, "💎 Top Edge Picks", wait=25)
        if not msgs:
            print("ERROR: No Hot Tips response")
            return

        tips_msg = max(msgs, key=lambda m: len(m.text or ""))
        # Navigate to page 2
        page_btns = [b for b in get_buttons(tips_msg) if "hot:page:1" in b.get("data", "")]
        if page_btns:
            print("  Navigating to page 2...")
            edited, _, pw = await click_and_wait(client, tips_msg, page_btns[0]["data"], wait=10)
            if edited and edited.text:
                p2_msg = edited
                p2_text = p2_msg.text
                print(f"  Page 2 loaded ({len(p2_text)} chars)")

                # Extract edge buttons from page 2
                p2_buttons = get_buttons(p2_msg)
                p2_edge = [b for b in p2_buttons if b.get("data", "").startswith("edge:detail:")]
                print(f"  Page 2 edge buttons: {len(p2_edge)}")

                for i, btn in enumerate(p2_edge):
                    print(f"\n  --- P2 Card {i+1}: {btn['text']} ---")
                    edited2, new_msgs, wall = await click_and_wait(client, p2_msg, btn["data"], wait=35)

                    detail_text = ""
                    detail_buttons = []
                    if edited2 and edited2.text and len(edited2.text) > 100:
                        detail_text = edited2.text
                        detail_buttons = get_buttons(edited2)
                    elif new_msgs:
                        for nm in new_msgs:
                            if nm.text and len(nm.text) > 100:
                                detail_text = nm.text
                                detail_buttons = get_buttons(nm)
                                break

                    if detail_text:
                        print(f"    Wall: {wall:.1f}s")
                        print(f"  === VERBATIM ===")
                        print(detail_text)
                        print(f"  === BUTTONS ===")
                        for b in detail_buttons:
                            print(f"    [{b.get('type')}] {b.get('text')} → {b.get('data', b.get('url', ''))}")
                        print(f"  === END ===")
                        captures["page2_details"].append({
                            "button_text": btn["text"],
                            "button_data": btn["data"],
                            "text": detail_text,
                            "buttons": detail_buttons,
                            "wall_time": round(wall, 2),
                        })
                    else:
                        print(f"    WARNING: No detail ({wall:.1f}s)")
                        captures["page2_details"].append({
                            "button_text": btn["text"],
                            "button_data": btn["data"],
                            "text": "",
                            "wall_time": round(wall, 2),
                            "status": "NO_RESPONSE",
                        })

                    # Navigate back to page 2
                    if detail_buttons:
                        back_btns = [b for b in detail_buttons if b.get("data", "").startswith("hot:back")]
                        if back_btns:
                            nav_ed, _, _ = await click_and_wait(client, edited2 or p2_msg, back_btns[0]["data"], wait=8)
                            if nav_ed and nav_ed.text:
                                p2_msg = nav_ed
                            await asyncio.sleep(1)

        # ── Part B: My Matches remaining cards ──
        print("\n=== MY MATCHES REMAINING CARDS ===")
        msgs2, _ = await send_and_wait(client, "⚽ My Matches", wait=20)
        if not msgs2:
            print("ERROR: No My Matches response")
            return

        mm_msg = max(msgs2, key=lambda m: len(m.text or ""))
        mm_buttons = get_buttons(mm_msg)
        game_btns = [b for b in mm_buttons if b.get("data", "").startswith("yg:game:")]
        print(f"  Game buttons: {len(game_btns)}")

        # Try cards 2-4 (skip card 1, already captured)
        for i, btn in enumerate(game_btns[1:], start=2):
            print(f"\n  --- MM Card {i}: {btn['text']} ---")
            edited3, new_msgs, wall = await click_and_wait(client, mm_msg, btn["data"], wait=35)

            detail_text = ""
            detail_buttons = []
            if edited3 and edited3.text and len(edited3.text) > 100:
                detail_text = edited3.text
                detail_buttons = get_buttons(edited3)
            elif new_msgs:
                for nm in new_msgs:
                    if nm.text and len(nm.text) > 100:
                        detail_text = nm.text
                        detail_buttons = get_buttons(nm)
                        break

            if detail_text:
                print(f"    Wall: {wall:.1f}s")
                print(f"  === VERBATIM ===")
                print(detail_text)
                print(f"  === BUTTONS ===")
                for b in detail_buttons:
                    print(f"    [{b.get('type')}] {b.get('text')} → {b.get('data', b.get('url', ''))}")
                print(f"  === END ===")
                captures["mm_details"].append({
                    "card_index": i,
                    "button_text": btn["text"],
                    "button_data": btn["data"],
                    "text": detail_text,
                    "buttons": detail_buttons,
                    "wall_time": round(wall, 2),
                })
            else:
                print(f"    WARNING: No detail ({wall:.1f}s)")
                captures["mm_details"].append({
                    "card_index": i,
                    "button_text": btn["text"],
                    "button_data": btn["data"],
                    "text": "",
                    "wall_time": round(wall, 2),
                    "status": "NO_RESPONSE",
                })

            # Navigate back
            if detail_buttons:
                back_btns = [b for b in detail_buttons if "yg:all" in b.get("data", "")]
                if back_btns:
                    nav_ed, _, _ = await click_and_wait(client, edited3 or mm_msg, back_btns[0]["data"], wait=8)
                    if nav_ed and nav_ed.text:
                        mm_msg = nav_ed
                    await asyncio.sleep(1)

        with open("/home/paulsportsza/reports/qa-baseline-21-captures-p2.json", "w") as f:
            json.dump(captures, f, indent=2, default=str)
        print("\nPart 2 captures saved.")

    finally:
        await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
