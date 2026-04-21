#!/usr/bin/env python3
"""QA-BASELINE-28: Telethon E2E Card Capture — Actual Live Cards.

Captures ALL live cards shown by Hot Tips via Telethon button presses.
ALL scoring from LIVE BOT interaction — NOT database reads.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo
SAST = ZoneInfo("Africa/Johannesburg")
UTC = ZoneInfo("UTC")
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
from telethon.tl.functions.messages import GetBotCallbackAnswerRequest

API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "")
BOT_USERNAME = "mzansiedge_bot"
STRING_SESSION_FILE = Path(__file__).resolve().parent.parent / "data" / "telethon_session.string"
FILE_SESSION = Path(__file__).resolve().parent.parent / "data" / "telethon_session"

OUTPUT_FILE = Path(__file__).resolve().parent.parent.parent / "reports" / "qa-baseline-28-telethon-captures.json"
OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)


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
        print("ERROR: Not logged in")
        sys.exit(1)
    return c


def get_text(msg) -> str:
    if msg is None:
        return ""
    return msg.message or msg.text or ""


def get_buttons(msg):
    cb_buttons, url_buttons = [], []
    if msg is None or not msg.reply_markup or not isinstance(msg.reply_markup, ReplyInlineMarkup):
        return cb_buttons, url_buttons
    for row in msg.reply_markup.rows:
        for btn in row.buttons:
            if isinstance(btn, KeyboardButtonCallback):
                d = btn.data.decode("utf-8", errors="replace") if isinstance(btn.data, bytes) else str(btn.data)
                cb_buttons.append({"text": btn.text, "data": d})
            elif isinstance(btn, KeyboardButtonUrl):
                url_buttons.append({"text": btn.text, "url": btn.url})
    return cb_buttons, url_buttons


async def press_and_wait(client, bot_entity, msg_id, callback_data, wait_secs=4.0):
    """Press inline callback button on a message and return updated message."""
    data = callback_data.encode() if isinstance(callback_data, str) else callback_data
    try:
        await client(GetBotCallbackAnswerRequest(
            peer=bot_entity, msg_id=msg_id, data=data,
        ))
    except Exception:
        pass  # Callback answer timeout is normal for edit-based flows
    await asyncio.sleep(wait_secs)
    msgs = await client.get_messages(bot_entity, ids=[msg_id])
    return msgs[0] if msgs and msgs[0] else None


async def main():
    print("=" * 60)
    print("QA-BASELINE-28 — Telethon E2E Card Capture")
    print(f"Timestamp: {datetime.now(SAST).isoformat()}")
    print("=" * 60)

    client = await get_client()
    bot_entity = await client.get_entity(BOT_USERNAME)
    print(f"Connected to @{BOT_USERNAME}")

    captures = {
        "metadata": {
            "qa_round": "QA-BASELINE-28",
            "timestamp": datetime.now(SAST).isoformat(),
            "source": "telethon_e2e",
        },
        "list_pages": [],
        "cards": [],
    }

    # ── Step 1: Trigger Hot Tips listing ──
    ts_before = time.time()
    await client.send_message(bot_entity, "\U0001f48e Top Edge Picks")
    print("\nSent 'Top Edge Picks' — waiting for response...")
    await asyncio.sleep(6.0)

    # Find the bot's response
    msgs = await client.get_messages(bot_entity, limit=5)
    list_msg = None
    for m in msgs:
        if m.date.timestamp() > ts_before - 2:
            text = get_text(m)
            if len(text) > 50 and ("edge" in text.lower() or "pick" in text.lower() or "\U0001f525" in text):
                list_msg = m
                break

    if not list_msg:
        print("First response may be loading. Waiting 12s more...")
        await asyncio.sleep(12.0)
        msgs = await client.get_messages(bot_entity, limit=5)
        for m in msgs:
            if m.date.timestamp() > ts_before - 2 and len(get_text(m)) > 100:
                list_msg = m
                break

    if not list_msg:
        print("ERROR: No Hot Tips response. Aborting.")
        await client.disconnect()
        return

    msg_id = list_msg.id
    print(f"Got response (msg_id={msg_id})")

    # If it's a loading spinner, wait for edit
    initial_text = get_text(list_msg)
    if len(initial_text) < 200:
        print("Looks like loading spinner. Waiting for content edit...")
        for _ in range(15):
            await asyncio.sleep(3.0)
            refreshed = await client.get_messages(bot_entity, ids=[msg_id])
            if refreshed and refreshed[0]:
                new_text = get_text(refreshed[0])
                if len(new_text) > 200:
                    list_msg = refreshed[0]
                    break

    # ── Step 2: Collect all tip buttons across all pages ──
    all_tip_buttons = []  # list of (btn_data, btn_text, page_num)
    page_num = 0

    while True:
        page_num += 1
        current = await client.get_messages(bot_entity, ids=[msg_id])
        if not current or not current[0]:
            break
        current_msg = current[0]
        page_text = get_text(current_msg)
        page_cb, page_url = get_buttons(current_msg)

        print(f"\n--- Page {page_num} ({len(page_text)} chars, {len(page_cb)} buttons) ---")
        print(page_text[:300].replace("\n", " | "))

        captures["list_pages"].append({
            "page": page_num,
            "text": page_text,
            "cb_buttons": page_cb,
            "url_buttons": page_url,
        })

        # Collect edge:detail buttons from this page
        for btn in page_cb:
            if btn["data"].startswith("edge:detail:"):
                all_tip_buttons.append({
                    "data": btn["data"],
                    "text": btn["text"],
                    "page": page_num,
                    "page_data": f"hot:page:{page_num - 1}",
                })
                print(f"  TIP: {btn['text']} -> {btn['data']}")

        # Find next page button
        next_btn = None
        for btn in page_cb:
            if btn["data"].startswith("hot:page:"):
                try:
                    target_page_idx = int(btn["data"].split(":")[-1])
                    if target_page_idx >= page_num:  # 0-indexed pages in callback
                        next_btn = btn
                        break
                except ValueError:
                    pass

        if not next_btn:
            print("  (last page)")
            break

        print(f"  Navigating to next page via {next_btn['data']}...")
        await press_and_wait(client, bot_entity, msg_id, next_btn["data"], wait_secs=3.0)

    print(f"\nTotal tip cards found: {len(all_tip_buttons)}")

    # ── Step 3: For each tip button, press it and capture detail ──
    for i, tip_btn in enumerate(all_tip_buttons):
        card_num = i + 1
        print(f"\n{'='*40}")
        print(f"CARD {card_num}/{len(all_tip_buttons)}: {tip_btn['text']}")
        print(f"  Callback: {tip_btn['data']}")
        print(f"  (from page {tip_btn['page']})")

        # First navigate back to the correct page if needed
        if tip_btn["page"] > 1:
            page_cb_data = f"hot:page:{tip_btn['page'] - 1}"
            await press_and_wait(client, bot_entity, msg_id, page_cb_data, wait_secs=2.0)

        # Now press the detail button
        detail_msg = await press_and_wait(client, bot_entity, msg_id, tip_btn["data"], wait_secs=5.0)
        if not detail_msg:
            print("  FAILED to get detail message")
            captures["cards"].append({
                "card_num": card_num,
                "btn_text": tip_btn["text"],
                "callback_data": tip_btn["data"],
                "source": "telethon_e2e",
                "text": "CAPTURE_FAILED",
                "error": "No response after button press",
            })
            continue

        detail_text = get_text(detail_msg)
        detail_cb, detail_url = get_buttons(detail_msg)

        # Check if content changed — might need more time for slow generation
        if "loading" in detail_text.lower() or "analysing" in detail_text.lower() or len(detail_text) < 100:
            print("  Detail still loading, waiting 15s more...")
            await asyncio.sleep(15.0)
            detail_msg = await client.get_messages(bot_entity, ids=[msg_id])
            if detail_msg and detail_msg[0]:
                detail_msg = detail_msg[0]
                detail_text = get_text(detail_msg)
                detail_cb, detail_url = get_buttons(detail_msg)

        print(f"  Captured: {len(detail_text)} chars")
        print(f"  First 200 chars: {detail_text[:200]}")

        card_capture = {
            "card_num": card_num,
            "btn_text": tip_btn["text"],
            "callback_data": tip_btn["data"],
            "source": "telethon_e2e",
            "text": detail_text,
            "cb_buttons": detail_cb,
            "url_buttons": detail_url,
            "captured_at": datetime.now(SAST).isoformat(),
        }
        captures["cards"].append(card_capture)

        # Navigate back to list (page 0)
        # Look for back button in detail view
        back_pressed = False
        for btn in detail_cb:
            if "hot:back" in btn["data"]:
                await press_and_wait(client, bot_entity, msg_id, btn["data"], wait_secs=2.0)
                back_pressed = True
                break

        if not back_pressed:
            # Try navigating to page 0 directly
            await press_and_wait(client, bot_entity, msg_id, "hot:page:0", wait_secs=2.0)

    # ── Step 4: Banned phrase scan ──
    BANNED_PHRASES = [
        "confident",
        "value play",
        "strong recommendation",
        "high confidence",
        "back this",
        "we recommend",
        "sure thing",
    ]

    print("\n" + "=" * 60)
    print("BANNED PHRASE SCAN")
    print("=" * 60)
    banned_hits = []
    for card in captures["cards"]:
        text_lower = card.get("text", "").lower()
        for phrase in BANNED_PHRASES:
            if phrase in text_lower:
                banned_hits.append({
                    "card": card["card_num"],
                    "btn_text": card.get("btn_text", ""),
                    "phrase": phrase,
                    "context": text_lower[max(0, text_lower.index(phrase)-30):text_lower.index(phrase)+len(phrase)+30],
                })
                print(f"  P0 HIT: Card {card['card_num']} ({card.get('btn_text','')}) contains '{phrase}'")

    if not banned_hits:
        print("  No banned phrases found across all cards. PASS.")
    captures["banned_phrase_scan"] = {
        "phrases_checked": BANNED_PHRASES,
        "hits": banned_hits,
        "result": "FAIL" if banned_hits else "PASS",
    }

    # Save
    with open(OUTPUT_FILE, "w") as f:
        json.dump(captures, f, indent=2, ensure_ascii=False)
    print(f"\nCaptures saved to: {OUTPUT_FILE}")

    await client.disconnect()
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
