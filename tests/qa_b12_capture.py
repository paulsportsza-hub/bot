"""QA-BASELINE-12 — Full card capture via Telethon.

Captures all Hot Tips pages + all detail cards + My Matches for scoring.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.sessions import StringSession

load_dotenv()

BOT_USERNAME = "mzansiedge_bot"
API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "")
SESSION_PATH = Path("data/telethon_qa_session.string")
REPORT_DIR = Path("/home/paulsportsza/reports/qa-baseline-12")
REPORT_DIR.mkdir(parents=True, exist_ok=True)

BOT_REPLY_TIMEOUT = 25
DETAIL_TIMEOUT = 40


async def _get_last_msg_id(client: TelegramClient) -> int:
    msgs = await client.get_messages(BOT_USERNAME, limit=1)
    return msgs[0].id if msgs else 0


async def send_and_wait(client, text, timeout=BOT_REPLY_TIMEOUT):
    last_id = await _get_last_msg_id(client)
    try:
        await client.send_message(BOT_USERNAME, text)
    except FloodWaitError as e:
        print(f"  FloodWait: {e.seconds}s")
        await asyncio.sleep(e.seconds + 2)
        await client.send_message(BOT_USERNAME, text)

    await asyncio.sleep(2.5)
    deadline = time.time() + timeout
    while time.time() < deadline:
        msgs = await client.get_messages(BOT_USERNAME, limit=5)
        for m in msgs:
            if m.id > last_id and not m.out:
                return m
        await asyncio.sleep(1.5)
    return None


async def click_button_by_data(client, msg, data_prefix, timeout=DETAIL_TIMEOUT):
    if not msg or not msg.buttons:
        return None
    old_id = await _get_last_msg_id(client)
    original_id = msg.id

    for row in msg.buttons:
        for btn in row:
            if hasattr(btn, "data") and btn.data:
                cb = btn.data.decode() if isinstance(btn.data, bytes) else str(btn.data)
                if cb == data_prefix or cb.startswith(data_prefix):
                    try:
                        await btn.click()
                    except FloodWaitError as e:
                        await asyncio.sleep(e.seconds + 2)
                        await btn.click()
                    except Exception as e:
                        print(f"  Click error: {e}")
                        return None

                    await asyncio.sleep(3)
                    deadline = time.time() + timeout
                    prev_text = ""
                    while time.time() < deadline:
                        # Check edited original
                        updated = await client.get_messages(BOT_USERNAME, ids=original_id)
                        if updated and updated.text:
                            cur = updated.text
                            if cur != prev_text and not any(
                                x in cur.lower()
                                for x in ["loading", "analysing", "⚽ loading"]
                            ):
                                if len(cur) > 50:
                                    return updated
                            prev_text = cur

                        # Check new message
                        msgs = await client.get_messages(BOT_USERNAME, limit=5)
                        for m in msgs:
                            if m.id > old_id and not m.out:
                                if not any(
                                    x in (m.text or "").lower()
                                    for x in ["loading", "analysing"]
                                ):
                                    if len(m.text or "") > 50:
                                        return m
                        await asyncio.sleep(2)

                    # Final check
                    updated = await client.get_messages(BOT_USERNAME, ids=original_id)
                    if updated and updated.text and len(updated.text) > 50:
                        return updated
                    return None
    return None


def extract_buttons(msg):
    buttons = []
    if msg and msg.buttons:
        for row in msg.buttons:
            for btn in row:
                cb = ""
                if hasattr(btn, "data") and btn.data:
                    cb = btn.data.decode() if isinstance(btn.data, bytes) else str(btn.data)
                elif hasattr(btn, "url") and btn.url:
                    cb = f"URL:{btn.url}"
                buttons.append({"text": btn.text, "data": cb})
    return buttons


def msg_to_dict(msg, label=""):
    if not msg:
        return {"label": label, "text": None, "buttons": []}
    return {
        "label": label,
        "text": msg.text or "",
        "buttons": extract_buttons(msg),
        "msg_id": msg.id,
        "date": str(msg.date),
    }


async def main():
    session_str = SESSION_PATH.read_text().strip()
    client = TelegramClient(StringSession(session_str), API_ID, API_HASH)
    await client.start()
    me = await client.get_me()
    print(f"Connected as: {me.first_name} (ID: {me.id})")

    captures = {
        "timestamp": datetime.now().isoformat(),
        "user_id": me.id,
        "list_views": [],
        "detail_cards": [],
        "my_matches": [],
    }

    # ── Step 1: Set QA tier to diamond ──
    print("\n=== Setting QA tier to diamond ===")
    qa_msg = await send_and_wait(client, "/qa set_diamond")
    if qa_msg:
        print(f"  QA: {qa_msg.text[:100]}...")

    # ── Step 2: Trigger Top Edge Picks ──
    print("\n=== Triggering 💎 Top Edge Picks ===")
    list_msg = await send_and_wait(client, "💎 Top Edge Picks", timeout=35)
    if not list_msg:
        print("ERROR: No list response!")
        await client.disconnect()
        return

    all_pages = []
    page_num = 0
    print(f"  Page {page_num}: {len(list_msg.text)} chars")
    all_pages.append(msg_to_dict(list_msg, f"list_page_{page_num}"))

    # ── Navigate all pages ──
    while list_msg and list_msg.buttons:
        next_found = False
        for row in list_msg.buttons:
            for btn in row:
                if hasattr(btn, "data") and btn.data:
                    cb = btn.data.decode() if isinstance(btn.data, bytes) else str(btn.data)
                    if cb.startswith("hot:page:"):
                        page_n = cb.split(":")[-1]
                        if page_n.isdigit() and int(page_n) > page_num:
                            page_num = int(page_n)
                            print(f"  Navigating to page {page_num}...")
                            next_msg = await click_button_by_data(
                                client, list_msg, cb
                            )
                            if next_msg:
                                all_pages.append(
                                    msg_to_dict(next_msg, f"list_page_{page_num}")
                                )
                                print(f"  Page {page_num}: {len(next_msg.text)} chars")
                                list_msg = next_msg
                            next_found = True
                            break
            if next_found:
                break
        if not next_found:
            break

    captures["list_views"] = all_pages

    # ── Step 3: Collect edge:detail buttons from all pages ──
    edge_buttons = []
    for page in all_pages:
        for btn in page.get("buttons", []):
            if btn["data"].startswith("edge:detail:"):
                match_key = btn["data"].replace("edge:detail:", "")
                if match_key not in [e["match_key"] for e in edge_buttons]:
                    edge_buttons.append({
                        "text": btn["text"],
                        "data": btn["data"],
                        "match_key": match_key,
                    })

    print(f"\n=== Found {len(edge_buttons)} unique edge cards ===")

    # ── Step 4: Capture each detail card ──
    # Re-trigger list
    list_msg = await send_and_wait(client, "💎 Top Edge Picks", timeout=35)
    await asyncio.sleep(2)

    for i, edge_btn in enumerate(edge_buttons):
        print(f"\n--- Card {i+1}/{len(edge_buttons)}: {edge_btn['match_key']} ---")

        # Make sure we're on the right page
        detail_msg = await click_button_by_data(client, list_msg, edge_btn["data"])

        if detail_msg:
            card_data = msg_to_dict(detail_msg, f"card_{i+1}_{edge_btn['match_key']}")
            card_data["match_key"] = edge_btn["match_key"]
            card_data["list_button_text"] = edge_btn["text"]
            captures["detail_cards"].append(card_data)
            print(f"  Captured: {len(detail_msg.text)} chars")
            print(f"  Preview: {detail_msg.text[:120]}...")
        else:
            print(f"  FAILED to capture card!")
            captures["detail_cards"].append({
                "match_key": edge_btn["match_key"],
                "text": None,
                "error": "No response from button tap",
            })

        # Navigate back
        if detail_msg:
            back_msg = await click_button_by_data(client, detail_msg, "hot:back")
            if back_msg:
                list_msg = back_msg
            else:
                await asyncio.sleep(1)
                list_msg = await send_and_wait(
                    client, "💎 Top Edge Picks", timeout=35
                )
        else:
            await asyncio.sleep(1)
            list_msg = await send_and_wait(client, "💎 Top Edge Picks", timeout=35)

        await asyncio.sleep(2)

    # ── Step 5: Capture My Matches ──
    print("\n=== Capturing ⚽ My Matches ===")
    mm_msg = await send_and_wait(client, "⚽ My Matches", timeout=30)
    if mm_msg:
        captures["my_matches"].append(msg_to_dict(mm_msg, "my_matches_page_0"))
        print(f"  My Matches page 0: {len(mm_msg.text)} chars")

        # Check for pagination
        mm_page = 0
        while mm_msg and mm_msg.buttons:
            next_found = False
            for row in mm_msg.buttons:
                for btn in row:
                    if hasattr(btn, "data") and btn.data:
                        cb = btn.data.decode() if isinstance(btn.data, bytes) else str(btn.data)
                        if cb.startswith("yg:all:") and "next" in btn.text.lower() or "➡" in btn.text:
                            mm_page += 1
                            next_mm = await click_button_by_data(client, mm_msg, cb)
                            if next_mm:
                                captures["my_matches"].append(
                                    msg_to_dict(next_mm, f"my_matches_page_{mm_page}")
                                )
                                print(f"  My Matches page {mm_page}: {len(next_mm.text)} chars")
                                mm_msg = next_mm
                            next_found = True
                            break
                if next_found:
                    break
            if not next_found:
                break
    else:
        print("  ERROR: No My Matches response!")

    # ── Step 6: Reset QA tier ──
    print("\n=== Resetting QA tier ===")
    await send_and_wait(client, "/qa reset")

    # ── Save captures ──
    report_path = REPORT_DIR / "captures.json"
    with open(report_path, "w") as f:
        json.dump(captures, f, indent=2, ensure_ascii=False)

    # Save raw text
    raw_path = REPORT_DIR / "raw_captures.txt"
    with open(raw_path, "w") as f:
        f.write(f"QA-BASELINE-12 Raw Captures — {datetime.now().isoformat()}\n")
        f.write("=" * 80 + "\n\n")

        f.write("HOT TIPS LIST VIEWS\n")
        f.write("-" * 80 + "\n")
        for page in captures["list_views"]:
            f.write(f"\n--- {page['label']} ---\n")
            f.write(page["text"] or "(empty)")
            f.write("\n\nButtons:\n")
            for btn in page.get("buttons", []):
                f.write(f"  [{btn['text']}] → {btn['data']}\n")
            f.write("\n")

        f.write("\n" + "=" * 80 + "\n")
        f.write("DETAIL CARDS\n")
        f.write("-" * 80 + "\n")
        for card in captures["detail_cards"]:
            f.write(f"\n{'='*60}\n")
            f.write(f"Card: {card.get('match_key', 'unknown')}\n")
            f.write(f"List button: {card.get('list_button_text', '')}\n")
            f.write(f"{'='*60}\n")
            f.write(card.get("text") or f"(FAILED: {card.get('error', 'unknown')})")
            f.write("\n\nButtons:\n")
            for btn in card.get("buttons", []):
                f.write(f"  [{btn['text']}] → {btn['data']}\n")
            f.write("\n")

        f.write("\n" + "=" * 80 + "\n")
        f.write("MY MATCHES\n")
        f.write("-" * 80 + "\n")
        for mm in captures["my_matches"]:
            f.write(f"\n--- {mm['label']} ---\n")
            f.write(mm.get("text") or "(empty)")
            f.write("\n\nButtons:\n")
            for btn in mm.get("buttons", []):
                f.write(f"  [{btn['text']}] → {btn['data']}\n")
            f.write("\n")

    total = len(captures["detail_cards"])
    ok = sum(1 for c in captures["detail_cards"] if c.get("text"))
    print(f"\nSaved {ok}/{total} cards + {len(captures['list_views'])} list pages + {len(captures['my_matches'])} My Matches pages")
    print(f"JSON: {report_path}")
    print(f"Raw:  {raw_path}")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
