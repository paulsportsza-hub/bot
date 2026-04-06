"""R11-QA-02 — Full card capture via Telethon.

Captures list view + every detail card for founder scoring.
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
SESSION_PATH = Path("data/telethon_session.string")
from config import BOT_ROOT
REPORT_DIR = BOT_ROOT.parent / "reports" / "r11-qa-02"
REPORT_DIR.mkdir(parents=True, exist_ok=True)

BOT_REPLY_TIMEOUT = 20
DETAIL_TIMEOUT = 30  # detail cards may take longer


async def _get_last_msg_id(client: TelegramClient) -> int:
    msgs = await client.get_messages(BOT_USERNAME, limit=1)
    return msgs[0].id if msgs else 0


async def get_latest_bot_msg(client: TelegramClient) -> "Message | None":
    msgs = await client.get_messages(BOT_USERNAME, limit=5)
    for m in msgs:
        if not m.out:
            return m
    return None


async def send_and_wait(client, text, timeout=BOT_REPLY_TIMEOUT):
    last_id = await _get_last_msg_id(client)
    try:
        await client.send_message(BOT_USERNAME, text)
    except FloodWaitError as e:
        await asyncio.sleep(e.seconds + 2)
        await client.send_message(BOT_USERNAME, text)

    await asyncio.sleep(2)
    deadline = time.time() + timeout
    while time.time() < deadline:
        msgs = await client.get_messages(BOT_USERNAME, limit=5)
        for m in msgs:
            if m.id > last_id and not m.out:
                return m
        await asyncio.sleep(1)
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
                if cb.startswith(data_prefix):
                    try:
                        await btn.click()
                    except FloodWaitError as e:
                        await asyncio.sleep(e.seconds + 2)
                        await btn.click()
                    except Exception as e:
                        print(f"  Click error: {e}")
                        return None

                    await asyncio.sleep(3)

                    # Wait for response with timeout
                    deadline = time.time() + timeout
                    last_text = ""
                    while time.time() < deadline:
                        # Check for NEW message
                        msgs = await client.get_messages(BOT_USERNAME, limit=5)
                        for m in msgs:
                            if m.id > old_id and not m.out:
                                # Check if message is still loading (spinner)
                                if m.text and ("loading" in m.text.lower() or
                                               "analysing" in m.text.lower() or
                                               "..." in m.text and len(m.text) < 50):
                                    last_text = m.text
                                    break
                                return m

                        # Check if ORIGINAL message was edited
                        updated = await client.get_messages(BOT_USERNAME, ids=original_id)
                        if updated and updated.text != last_text:
                            if updated.text and not ("loading" in updated.text.lower() or
                                                     "analysing" in updated.text.lower()):
                                return updated
                            last_text = updated.text or ""

                        await asyncio.sleep(2)

                    # Final check
                    updated = await client.get_messages(BOT_USERNAME, ids=original_id)
                    if updated:
                        return updated
                    return None
    return None


def extract_buttons(msg):
    """Extract all button texts and callback data."""
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
    """Convert a message to a serializable dict."""
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
    print(f"Connected as: {(await client.get_me()).first_name}")

    captures = {
        "timestamp": datetime.now().isoformat(),
        "list_views": [],
        "detail_cards": [],
    }

    # ── Step 1: QA tier override to diamond (see all edges) ──
    print("\n=== Setting QA tier to diamond ===")
    qa_msg = await send_and_wait(client, "/qa set_diamond")
    if qa_msg:
        print(f"  QA response: {qa_msg.text[:100]}...")

    # ── Step 2: Trigger Hot Tips (list view) ──
    print("\n=== Triggering Top Edge Picks ===")
    list_msg = await send_and_wait(client, "💎 Top Edge Picks", timeout=30)
    if not list_msg:
        print("ERROR: No list view response!")
        await client.disconnect()
        return

    all_pages = []
    page_num = 0

    # Capture first page
    print(f"  Page {page_num}: {len(list_msg.text)} chars")
    all_pages.append(msg_to_dict(list_msg, f"list_page_{page_num}"))

    # Check for pagination — capture all pages
    while list_msg and list_msg.buttons:
        next_found = False
        for row in list_msg.buttons:
            for btn in row:
                if hasattr(btn, "data") and btn.data:
                    cb = btn.data.decode() if isinstance(btn.data, bytes) else str(btn.data)
                    if cb.startswith("hot:page:") and "next" in btn.text.lower() or "➡" in btn.text:
                        page_num += 1
                        print(f"  Navigating to page {page_num}...")
                        list_msg = await click_button_by_data(client, list_msg, cb.split(":")[0] + ":" + cb.split(":")[1] + ":" + cb.split(":")[2])
                        if list_msg:
                            all_pages.append(msg_to_dict(list_msg, f"list_page_{page_num}"))
                            print(f"  Page {page_num}: {len(list_msg.text)} chars")
                        next_found = True
                        break
            if next_found:
                break
        if not next_found:
            break

    captures["list_views"] = all_pages

    # ── Step 3: Collect all edge:detail button data from all pages ──
    edge_buttons = []
    for page in all_pages:
        for btn in page.get("buttons", []):
            if btn["data"].startswith("edge:detail:"):
                match_key = btn["data"].replace("edge:detail:", "")
                if match_key not in [e["match_key"] for e in edge_buttons]:
                    edge_buttons.append({"text": btn["text"], "data": btn["data"], "match_key": match_key})

    print(f"\n=== Found {len(edge_buttons)} unique edge cards to capture ===")

    # ── Step 4: Navigate back to first page, then tap each card ──
    # Re-trigger list to get fresh state
    list_msg = await send_and_wait(client, "💎 Top Edge Picks", timeout=30)
    await asyncio.sleep(2)

    for i, edge_btn in enumerate(edge_buttons):
        print(f"\n--- Card {i+1}/{len(edge_buttons)}: {edge_btn['match_key']} ---")

        # Tap the edge detail button
        detail_msg = await click_button_by_data(client, list_msg, edge_btn["data"])

        if detail_msg:
            card_data = msg_to_dict(detail_msg, f"card_{i+1}_{edge_btn['match_key']}")
            card_data["match_key"] = edge_btn["match_key"]
            card_data["list_button_text"] = edge_btn["text"]
            captures["detail_cards"].append(card_data)
            print(f"  Captured: {len(detail_msg.text)} chars")
            print(f"  Preview: {detail_msg.text[:150]}...")
        else:
            print(f"  FAILED to capture card!")
            captures["detail_cards"].append({
                "match_key": edge_btn["match_key"],
                "text": None,
                "error": "No response from button tap",
            })

        # Navigate back to list for next card
        if detail_msg:
            back_msg = await click_button_by_data(client, detail_msg, "hot:back")
            if back_msg:
                list_msg = back_msg
            else:
                # Re-trigger list
                await asyncio.sleep(1)
                list_msg = await send_and_wait(client, "💎 Top Edge Picks", timeout=30)
        else:
            await asyncio.sleep(1)
            list_msg = await send_and_wait(client, "💎 Top Edge Picks", timeout=30)

        await asyncio.sleep(2)

    # ── Step 5: Reset QA tier ──
    print("\n=== Resetting QA tier ===")
    await send_and_wait(client, "/qa reset")

    # ── Save captures ──
    report_path = REPORT_DIR / "captures.json"
    with open(report_path, "w") as f:
        json.dump(captures, f, indent=2, ensure_ascii=False)
    print(f"\nSaved {len(captures['detail_cards'])} cards to {report_path}")

    # Also save raw text captures
    raw_path = REPORT_DIR / "raw_captures.txt"
    with open(raw_path, "w") as f:
        f.write(f"R11-QA-02 Raw Captures — {datetime.now().isoformat()}\n")
        f.write("=" * 80 + "\n\n")

        f.write("LIST VIEW\n")
        f.write("-" * 80 + "\n")
        for page in captures["list_views"]:
            f.write(f"\n{page['label']}:\n")
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
            f.write(card.get("text") or "(no content)")
            f.write("\n\nButtons:\n")
            for btn in card.get("buttons", []):
                f.write(f"  [{btn['text']}] → {btn['data']}\n")
            f.write("\n")

    print(f"Saved raw text to {raw_path}")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
