#!/usr/bin/env python3
"""R5-QA-01: Full Telethon QA — capture edge list + up to 10 detail cards."""
from __future__ import annotations

import asyncio
import os
import sys
import json
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
STRING_SESSION_FILE = Path(__file__).resolve().parent.parent / "data" / "telethon_session.string"
FILE_SESSION = Path(__file__).resolve().parent.parent / "data" / "telethon_session"
from config import BOT_ROOT
OUTPUT_DIR = BOT_ROOT.parent / "reports" / "r5-qa"
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
    if msg is None:
        return ""
    return msg.message or msg.text or ""


def get_buttons(msg):
    if msg is None or not msg.reply_markup or not isinstance(msg.reply_markup, ReplyInlineMarkup):
        return []
    btns = []
    for row in msg.reply_markup.rows:
        for btn in row.buttons:
            btns.append(btn)
    return btns


def get_button_info(msg):
    info = []
    for btn in get_buttons(msg):
        if isinstance(btn, KeyboardButtonCallback):
            data = btn.data.decode() if isinstance(btn.data, bytes) else str(btn.data)
            info.append({"type": "callback", "text": btn.text or "", "data": data})
        elif isinstance(btn, KeyboardButtonUrl):
            info.append({"type": "url", "text": btn.text or "", "url": btn.url or ""})
    return info


def find_edge_detail_buttons(msg):
    detail_btns = []
    for btn in get_buttons(msg):
        if isinstance(btn, KeyboardButtonCallback):
            data = btn.data.decode() if isinstance(btn.data, bytes) else str(btn.data)
            if data.startswith("edge:detail:"):
                detail_btns.append((btn, data, btn.text or ""))
    return detail_btns


async def get_fresh_list(client, bot, wait=15):
    """Send fresh Edge Picks request and return the response message."""
    await client.send_message(bot, "💎 Top Edge Picks")
    await asyncio.sleep(wait)
    msgs = await client.get_messages(bot, limit=10)
    for m in msgs:
        if find_edge_detail_buttons(m):
            return m
    # Fallback: look for any edge-related message
    for m in msgs:
        txt = get_text(m)
        if "edge" in txt.lower() or "pick" in txt.lower():
            return m
    return None


async def click_button_on_msg(client, msg, target_data, wait=20):
    """Click a specific callback button on a message by matching data."""
    for btn in get_buttons(msg):
        if isinstance(btn, KeyboardButtonCallback):
            data = btn.data.decode() if isinstance(btn.data, bytes) else str(btn.data)
            if data == target_data:
                t0 = time.time()
                try:
                    await msg.click(data=btn.data)
                except Exception as e:
                    print(f"  Click error: {e}")
                    return None, 0
                await asyncio.sleep(wait)
                refreshed = await client.get_messages(msg.peer_id, ids=msg.id)
                return refreshed, time.time() - t0
    return None, 0


async def navigate_to_page(client, msg, page_num, wait=10):
    """Navigate to a specific page by clicking Next buttons."""
    current = msg
    for _ in range(page_num):
        for btn in get_buttons(current):
            if isinstance(btn, KeyboardButtonCallback):
                data = btn.data.decode() if isinstance(btn.data, bytes) else str(btn.data)
                if "hot:page:" in data and ("➡" in (btn.text or "") or "Next" in (btn.text or "")):
                    try:
                        await current.click(data=btn.data)
                    except Exception as e:
                        print(f"  Page nav error: {e}")
                        return current
                    await asyncio.sleep(wait)
                    refreshed = await client.get_messages(current.peer_id, ids=current.id)
                    if refreshed:
                        current = refreshed
                    break
    return current


async def main():
    ts_start = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print("=" * 70)
    print("R5-QA-01: Full Telethon QA — Edge Cards")
    print(f"Time: {ts_start}")
    print("=" * 70)

    client = await get_client()
    bot = await client.get_entity(BOT_USERNAME)
    results = []

    # --- Step 1: Get initial list ---
    print("\n[STEP 1] Sending '💎 Top Edge Picks'...")
    list_msg = await get_fresh_list(client, bot, wait=20)

    if not list_msg:
        print("ERROR: No Edge Picks response found")
        await client.disconnect()
        return

    list_text = get_text(list_msg)
    list_buttons = get_button_info(list_msg)
    print(f"\n{'='*70}")
    print("LIST VIEW (Page 1)")
    print(f"{'='*70}")
    print(list_text)
    print(f"\nButtons: {len(list_buttons)}")
    for b in list_buttons:
        print(f"  [{b['type']}] {b['text']} -> {b.get('data', b.get('url', ''))}")
    print(f"{'='*70}\n")

    results.append({
        "type": "list", "page": 1,
        "text": list_text, "buttons": list_buttons,
    })

    # Collect page 1 detail buttons
    page1_details = []
    for _, data, text in find_edge_detail_buttons(list_msg):
        page1_details.append({"data": data, "text": text, "page": 0})

    # --- Check for page 2 ---
    has_page2 = any(
        "hot:page:" in b.get("data", "") and ("Next" in b["text"] or "➡" in b["text"])
        for b in list_buttons if b["type"] == "callback"
    )

    page2_details = []
    if has_page2:
        print("[STEP 1b] Navigating to page 2...")
        p2_msg = await navigate_to_page(client, list_msg, 1)
        if p2_msg:
            p2_text = get_text(p2_msg)
            p2_buttons = get_button_info(p2_msg)
            print(f"\n{'='*70}")
            print("LIST VIEW (Page 2)")
            print(f"{'='*70}")
            print(p2_text)
            print(f"\nButtons: {len(p2_buttons)}")
            for b in p2_buttons:
                print(f"  [{b['type']}] {b['text']} -> {b.get('data', b.get('url', ''))}")
            print(f"{'='*70}\n")

            results.append({
                "type": "list", "page": 2,
                "text": p2_text, "buttons": p2_buttons,
            })

            for _, data, text in find_edge_detail_buttons(p2_msg):
                page2_details.append({"data": data, "text": text, "page": 1})

    # Check for page 3
    has_page3 = False
    if has_page2:
        p2_buttons_check = get_button_info(p2_msg) if p2_msg else []
        has_page3 = any(
            "hot:page:" in b.get("data", "") and ("Next" in b["text"] or "➡" in b["text"])
            for b in p2_buttons_check if b["type"] == "callback"
        )

    page3_details = []
    if has_page3:
        print("[STEP 1c] Navigating to page 3...")
        # Get fresh list and navigate to page 3
        fresh = await get_fresh_list(client, bot, wait=15)
        if fresh:
            p3_msg = await navigate_to_page(client, fresh, 2)
            if p3_msg:
                p3_text = get_text(p3_msg)
                p3_buttons = get_button_info(p3_msg)
                if p3_text != get_text(fresh):
                    print(f"\n{'='*70}")
                    print("LIST VIEW (Page 3)")
                    print(f"{'='*70}")
                    print(p3_text)
                    print(f"{'='*70}\n")
                    results.append({
                        "type": "list", "page": 3,
                        "text": p3_text, "buttons": p3_buttons,
                    })
                    for _, data, text in find_edge_detail_buttons(p3_msg):
                        page3_details.append({"data": data, "text": text, "page": 2})

    # Combine all detail targets
    all_targets = page1_details + page2_details + page3_details
    max_cards = min(10, len(all_targets))
    print(f"\nTotal edge detail buttons found: {len(all_targets)}")
    print(f"Will capture: {max_cards} cards\n")

    # --- Step 2: Click into each detail card ---
    for i in range(max_cards):
        target = all_targets[i]
        print(f"\n[CARD {i+1}/{max_cards}] {target['text']} ({target['data']})")

        # Get a FRESH list message each time
        print("  Getting fresh list...")
        fresh_msg = await get_fresh_list(client, bot, wait=12)
        if not fresh_msg:
            print(f"  WARN: Could not get fresh list for card {i+1}")
            continue

        # Navigate to correct page if needed
        if target["page"] > 0:
            print(f"  Navigating to page {target['page'] + 1}...")
            fresh_msg = await navigate_to_page(client, fresh_msg, target["page"])

        # Click the detail button
        print(f"  Clicking detail button...")
        detail_msg, load_time = await click_button_on_msg(
            client, fresh_msg, target["data"], wait=20
        )

        if detail_msg:
            detail_text = get_text(detail_msg)
            fresh_text = get_text(fresh_msg)
            if detail_text and detail_text != fresh_text:
                detail_buttons = get_button_info(detail_msg)
                print(f"\n{'='*70}")
                print(f"CARD {i+1} — Load time: {load_time:.1f}s")
                print(f"{'='*70}")
                print(detail_text)
                print(f"\nButtons ({len(detail_buttons)}):")
                for b in detail_buttons:
                    print(f"  [{b['type']}] {b['text']} -> {b.get('data', b.get('url', ''))}")
                print(f"{'='*70}\n")

                results.append({
                    "type": "card",
                    "index": i + 1,
                    "btn_data": target["data"],
                    "btn_text": target["text"],
                    "text": detail_text,
                    "buttons": detail_buttons,
                    "load_time_s": round(load_time, 1),
                })
            else:
                # Retry with more wait
                print(f"  Detail didn't load, waiting 15 more seconds...")
                await asyncio.sleep(15)
                detail_msg2 = await client.get_messages(fresh_msg.peer_id, ids=fresh_msg.id)
                if detail_msg2:
                    detail_text2 = get_text(detail_msg2)
                    load_time2 = time.time() - (time.time() - load_time)
                    if detail_text2 and detail_text2 != fresh_text:
                        detail_buttons2 = get_button_info(detail_msg2)
                        print(f"\n{'='*70}")
                        print(f"CARD {i+1} (delayed) — Load time: {load_time + 15:.1f}s")
                        print(f"{'='*70}")
                        print(detail_text2)
                        print(f"\nButtons ({len(detail_buttons2)}):")
                        for b in detail_buttons2:
                            print(f"  [{b['type']}] {b['text']} -> {b.get('data', b.get('url', ''))}")
                        print(f"{'='*70}\n")
                        results.append({
                            "type": "card",
                            "index": i + 1,
                            "btn_data": target["data"],
                            "btn_text": target["text"],
                            "text": detail_text2,
                            "buttons": detail_buttons2,
                            "load_time_s": round(load_time + 15, 1),
                        })
                    else:
                        print(f"  WARN: Card {i+1} still not loaded after extended wait")
        else:
            print(f"  WARN: No response for card {i+1}")

    # --- Summary ---
    cards = [r for r in results if r["type"] == "card"]
    print(f"\n{'='*70}")
    print(f"CAPTURE COMPLETE: {len(cards)}/{max_cards} cards captured")
    print(f"{'='*70}")

    # Save
    ts = datetime.now().strftime("%Y%m%d-%H%M")
    outfile = OUTPUT_DIR / f"r5-qa-telethon-{ts}.json"
    with open(outfile, "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    txtfile = OUTPUT_DIR / f"r5-qa-telethon-{ts}.txt"
    with open(txtfile, "w") as f:
        f.write(f"R5-QA-01: Full Telethon QA\n")
        f.write(f"Time: {ts_start}\n")
        f.write(f"Cards captured: {len(cards)}/{max_cards}\n")
        f.write("=" * 70 + "\n\n")
        for r in results:
            if r["type"] == "list":
                f.write(f"=== LIST VIEW (Page {r['page']}) ===\n")
                f.write(r["text"] + "\n")
                f.write(f"Buttons: {len(r['buttons'])}\n")
                for b in r["buttons"]:
                    f.write(f"  [{b['type']}] {b['text']} -> {b.get('data', b.get('url', ''))}\n")
                f.write("\n")
            else:
                f.write(f"=== CARD {r['index']} ({r.get('btn_text','')}) ===\n")
                f.write(f"Load time: {r.get('load_time_s', '?')}s\n")
                f.write(r["text"] + "\n")
                f.write(f"Buttons ({len(r['buttons'])}):\n")
                for b in r["buttons"]:
                    f.write(f"  [{b['type']}] {b['text']} -> {b.get('data', b.get('url', ''))}\n")
                f.write("\n")

    print(f"\nSaved JSON: {outfile}")
    print(f"Saved TXT:  {txtfile}")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
