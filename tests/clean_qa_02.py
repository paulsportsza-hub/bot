"""CLEAN-QA-02 — Full Gold Tier Telethon E2E Capture.

Connects as Gold tier user, navigates every Edge card,
captures EXACT FULL message text for scoring.
"""
import asyncio
import json
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from telethon import TelegramClient
from telethon.sessions import StringSession

API_ID = int(os.environ.get("TELEGRAM_API_ID", "32418601"))
API_HASH = os.environ.get("TELEGRAM_API_HASH", "95e313a8ef5b998be0515dd8328fac57")
STRING_SESSION_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "telethon_qa_session.string"
)
BOT_USERNAME = "mzansiedge_bot"
from config import BOT_ROOT
REPORT_DIR = str(BOT_ROOT.parent / "reports")


async def get_client():
    string = open(STRING_SESSION_FILE).read().strip()
    client = TelegramClient(StringSession(string), API_ID, API_HASH)
    await client.connect()
    if not await client.is_user_authorized():
        print("ERROR: Not logged in.")
        sys.exit(1)
    return client


async def send_and_wait(client, text, wait=10):
    """Send message/button text and wait for bot responses."""
    await client.send_message(BOT_USERNAME, text)
    await asyncio.sleep(wait)
    messages = await client.get_messages(BOT_USERNAME, limit=15)
    return [m for m in messages if not m.out]


async def click_button_and_wait(msg, btn_data, wait=10):
    """Click an inline button by callback data and wait."""
    await msg.click(data=btn_data)
    await asyncio.sleep(wait)


async def get_latest_messages(client, limit=10):
    """Get latest bot messages."""
    messages = await client.get_messages(BOT_USERNAME, limit=limit)
    return [m for m in messages if not m.out]


def extract_buttons(msg):
    """Extract all button info from a message."""
    buttons = []
    if msg.buttons:
        for row_idx, row in enumerate(msg.buttons):
            for col_idx, btn in enumerate(row):
                data = (btn.data or b"").decode("utf-8", errors="ignore") if btn.data else ""
                buttons.append({
                    "text": btn.text or "",
                    "data": data,
                    "url": btn.url or "" if hasattr(btn, 'url') else "",
                    "row": row_idx,
                    "col": col_idx
                })
    return buttons


def msg_to_dict(msg):
    """Convert a Telegram message to a serialisable dict."""
    return {
        "id": msg.id,
        "text": msg.text or "",
        "raw_text": msg.raw_text or "",
        "buttons": extract_buttons(msg),
        "date": str(msg.date),
    }


async def run_qa():
    captures = {
        "meta": {
            "wave": "CLEAN-QA-02",
            "timestamp": datetime.now().isoformat(),
            "user_tier": "gold",
            "user_id": 411927634,
        },
        "start": None,
        "edge_picks_pages": [],
        "card_details": [],
        "errors": [],
    }

    client = await get_client()
    print("Connected to Telegram as Gold tier user")

    try:
        # ─── Step 1: /start ───
        print("\n[1] Sending /start...")
        responses = await send_and_wait(client, "/start", wait=8)
        if responses:
            captures["start"] = msg_to_dict(responses[0])
            print(f"    Got response: {len(responses[0].text or '')} chars")
        else:
            captures["errors"].append("No response to /start")
            print("    ERROR: No response")

        # ─── Step 2: Top Edge Picks ───
        print("\n[2] Sending '💎 Top Edge Picks'...")
        responses = await send_and_wait(client, "💎 Top Edge Picks", wait=15)

        # Find the main tips message (one with inline buttons)
        tips_msg = None
        all_responses = []
        for msg in responses:
            all_responses.append(msg_to_dict(msg))
            if msg.buttons:
                for row in (msg.buttons or []):
                    for btn in row:
                        data = (btn.data or b"").decode("utf-8", errors="ignore") if btn.data else ""
                        if "edge:detail" in data:
                            tips_msg = msg
                            break
                    if tips_msg:
                        break
            if tips_msg:
                break

        page_0 = {
            "page": 0,
            "messages": all_responses,
            "tips_msg": msg_to_dict(tips_msg) if tips_msg else None,
        }
        captures["edge_picks_pages"].append(page_0)

        if tips_msg:
            print(f"    Found tips message: {len(tips_msg.text or '')} chars, {len(extract_buttons(tips_msg))} buttons")
        else:
            # Try fallback - maybe the most recent message with buttons
            for msg in responses:
                if msg.buttons:
                    tips_msg = msg
                    page_0["tips_msg"] = msg_to_dict(msg)
                    break
            if tips_msg:
                print(f"    Fallback tips message: {len(tips_msg.text or '')} chars")
            else:
                captures["errors"].append("No tips message found with buttons")
                print("    ERROR: No tips message with buttons found")

        # ─── Step 3: Navigate ALL pages ───
        if tips_msg and tips_msg.buttons:
            # Find pagination buttons (hot:page:N)
            page_num = 1
            current_msg = tips_msg
            while True:
                next_btn = None
                for row in (current_msg.buttons or []):
                    for btn in row:
                        data = (btn.data or b"").decode("utf-8", errors="ignore") if btn.data else ""
                        if data == f"hot:page:{page_num}":
                            next_btn = btn
                            break
                    if next_btn:
                        break

                if not next_btn:
                    # Also check for "Next" text buttons
                    for row in (current_msg.buttons or []):
                        for btn in row:
                            if "next" in (btn.text or "").lower() or "➡️" in (btn.text or ""):
                                data = (btn.data or b"").decode("utf-8", errors="ignore") if btn.data else ""
                                if "hot:page:" in data:
                                    next_btn = btn
                                    break
                        if next_btn:
                            break

                if not next_btn:
                    print(f"    No more pages after page {page_num - 1}")
                    break

                print(f"\n[3.{page_num}] Navigating to page {page_num}...")
                data = (next_btn.data or b"").decode("utf-8", errors="ignore")
                await click_button_and_wait(current_msg, data.encode(), wait=8)
                new_msgs = await get_latest_messages(client, limit=5)

                page_data = {"page": page_num, "messages": []}
                for m in new_msgs:
                    page_data["messages"].append(msg_to_dict(m))
                    if m.buttons:
                        current_msg = m
                        page_data["tips_msg"] = msg_to_dict(m)

                captures["edge_picks_pages"].append(page_data)
                print(f"    Got page {page_num}")
                page_num += 1
                if page_num > 10:  # Safety limit
                    break

        # ─── Step 4: Tap into EVERY card detail ───
        print("\n[4] Tapping into every card detail...")
        all_detail_buttons = []

        # Collect edge:detail buttons from ALL pages
        for page in captures["edge_picks_pages"]:
            tips = page.get("tips_msg")
            if tips:
                for btn in tips.get("buttons", []):
                    if "edge:detail" in btn.get("data", ""):
                        all_detail_buttons.append(btn)

        print(f"    Found {len(all_detail_buttons)} detail buttons across all pages")

        # Need to re-get the current message for clicking
        # Go back to page 0 first if we navigated
        if len(captures["edge_picks_pages"]) > 1 and tips_msg:
            print("    Returning to page 0...")
            await client.send_message(BOT_USERNAME, "💎 Top Edge Picks")
            await asyncio.sleep(12)
            latest = await get_latest_messages(client, limit=10)
            for m in latest:
                if m.buttons:
                    tips_msg = m
                    break

        # Now tap each card
        card_idx = 0
        for btn_info in all_detail_buttons:
            card_idx += 1
            btn_data = btn_info["data"]
            btn_text = btn_info["text"]
            print(f"\n    [{card_idx}/{len(all_detail_buttons)}] Tapping: {btn_text} ({btn_data})")

            try:
                # Get fresh message state
                latest = await get_latest_messages(client, limit=5)
                clickable_msg = None
                for m in latest:
                    if m.buttons:
                        for row in m.buttons:
                            for b in row:
                                d = (b.data or b"").decode("utf-8", errors="ignore") if b.data else ""
                                if d == btn_data:
                                    clickable_msg = m
                                    break
                            if clickable_msg:
                                break
                    if clickable_msg:
                        break

                if not clickable_msg:
                    # If button not found on current page, navigate to correct page
                    # Try sending Top Edge Picks again
                    await client.send_message(BOT_USERNAME, "💎 Top Edge Picks")
                    await asyncio.sleep(12)
                    latest = await get_latest_messages(client, limit=10)
                    for m in latest:
                        if m.buttons:
                            for row in m.buttons:
                                for b in row:
                                    d = (b.data or b"").decode("utf-8", errors="ignore") if b.data else ""
                                    if d == btn_data:
                                        clickable_msg = m
                                        break
                                if clickable_msg:
                                    break
                        if clickable_msg:
                            break

                if clickable_msg:
                    await click_button_and_wait(clickable_msg, btn_data.encode(), wait=12)
                    detail_msgs = await get_latest_messages(client, limit=5)

                    card_detail = {
                        "index": card_idx,
                        "button_text": btn_text,
                        "button_data": btn_data,
                        "messages": [msg_to_dict(m) for m in detail_msgs],
                    }
                    captures["card_details"].append(card_detail)
                    print(f"        Captured: {len(detail_msgs[0].text or '') if detail_msgs else 0} chars")

                    # Go back to picks list for next card
                    back_clicked = False
                    for m in detail_msgs:
                        if m.buttons:
                            for row in m.buttons:
                                for b in row:
                                    d = (b.data or b"").decode("utf-8", errors="ignore") if b.data else ""
                                    if "hot:back" in d:
                                        await click_button_and_wait(m, d.encode(), wait=6)
                                        back_clicked = True
                                        break
                                if back_clicked:
                                    break
                        if back_clicked:
                            break

                    if not back_clicked:
                        # Send Top Edge Picks again
                        await client.send_message(BOT_USERNAME, "💎 Top Edge Picks")
                        await asyncio.sleep(10)
                else:
                    captures["errors"].append(f"Could not find clickable button for {btn_data}")
                    print(f"        ERROR: Button not found in current messages")

            except Exception as e:
                captures["errors"].append(f"Error tapping {btn_data}: {str(e)}")
                print(f"        ERROR: {e}")
                # Try to recover
                await client.send_message(BOT_USERNAME, "💎 Top Edge Picks")
                await asyncio.sleep(10)

        # ─── Step 5: Save raw captures ───
        ts = datetime.now().strftime("%Y%m%d-%H%M")
        outfile = os.path.join(REPORT_DIR, f"clean-qa-02-captures-{ts}.json")
        with open(outfile, "w") as f:
            json.dump(captures, f, indent=2, ensure_ascii=False, default=str)
        print(f"\nCaptures saved to: {outfile}")
        print(f"Total pages: {len(captures['edge_picks_pages'])}")
        print(f"Total card details: {len(captures['card_details'])}")
        print(f"Errors: {len(captures['errors'])}")

        return captures, outfile

    finally:
        await client.disconnect()


if __name__ == "__main__":
    captures, outfile = asyncio.run(run_qa())
