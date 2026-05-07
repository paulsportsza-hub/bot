"""CLEAN-QA-02 — Capture remaining cards from pages 1 and 2."""
import asyncio
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from telethon import TelegramClient
from telethon.sessions import StringSession

API_ID = 32418601
API_HASH = "95e313a8ef5b998be0515dd8328fac57"
STRING_SESSION_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "telethon_qa_session.string"
)
BOT_USERNAME = "mzansiedge_bot"


def extract_buttons(msg):
    buttons = []
    if msg.buttons:
        for ri, row in enumerate(msg.buttons):
            for ci, btn in enumerate(row):
                data = (btn.data or b"").decode("utf-8", errors="ignore") if btn.data else ""
                buttons.append({"text": btn.text or "", "data": data,
                    "url": btn.url or "" if hasattr(btn, 'url') else "", "row": ri, "col": ci})
    return buttons


def msg_to_dict(msg):
    return {"id": msg.id, "text": msg.text or "", "raw_text": msg.raw_text or "",
            "buttons": extract_buttons(msg), "date": str(msg.date)}


async def run():
    string = open(STRING_SESSION_FILE).read().strip()
    client = TelegramClient(StringSession(string), API_ID, API_HASH)
    await client.connect()
    if not await client.is_user_authorized():
        print("Not logged in"); sys.exit(1)

    captures = {"pages": [], "card_details": [], "errors": []}

    try:
        # Get Top Edge Picks
        print("[1] Sending Top Edge Picks...")
        await client.send_message(BOT_USERNAME, "💎 Top Edge Picks")
        await asyncio.sleep(12)
        msgs = await client.get_messages(BOT_USERNAME, limit=10)
        tips_msg = None
        for m in msgs:
            if not m.out and m.buttons:
                for row in m.buttons:
                    for btn in row:
                        d = (btn.data or b"").decode("utf-8", errors="ignore") if btn.data else ""
                        if "edge:detail" in d:
                            tips_msg = m
                            break
                    if tips_msg: break
            if tips_msg: break

        if not tips_msg:
            print("ERROR: No tips message found"); return

        page0 = msg_to_dict(tips_msg)
        captures["pages"].append({"page": 0, "msg": page0})
        print(f"    Page 0: {len(page0['text'])} chars, {len(page0['buttons'])} buttons")

        # Navigate to page 1
        print("[2] Navigating to page 1...")
        for row in tips_msg.buttons:
            for btn in row:
                d = (btn.data or b"").decode("utf-8", errors="ignore") if btn.data else ""
                if d == "hot:page:1":
                    await btn.click()
                    await asyncio.sleep(8)
                    break

        msgs = await client.get_messages(BOT_USERNAME, limit=5)
        page1_msg = None
        for m in msgs:
            if not m.out and m.buttons:
                for row in m.buttons:
                    for btn in row:
                        d = (btn.data or b"").decode("utf-8", errors="ignore") if btn.data else ""
                        if "edge:detail" in d:
                            page1_msg = m
                            break
                    if page1_msg: break
            if page1_msg: break

        if page1_msg:
            p1 = msg_to_dict(page1_msg)
            captures["pages"].append({"page": 1, "msg": p1})
            print(f"    Page 1: {len(p1['text'])} chars, {len(p1['buttons'])} buttons")

            # Try page 2
            print("[3] Navigating to page 2...")
            for row in page1_msg.buttons:
                for btn in row:
                    d = (btn.data or b"").decode("utf-8", errors="ignore") if btn.data else ""
                    if d == "hot:page:2":
                        await btn.click()
                        await asyncio.sleep(8)
                        break

            msgs = await client.get_messages(BOT_USERNAME, limit=5)
            page2_msg = None
            for m in msgs:
                if not m.out and m.buttons:
                    for row in m.buttons:
                        for btn in row:
                            d = (btn.data or b"").decode("utf-8", errors="ignore") if btn.data else ""
                            if "edge:detail" in d:
                                page2_msg = m
                                break
                        if page2_msg: break
                if page2_msg: break

            if page2_msg:
                p2 = msg_to_dict(page2_msg)
                captures["pages"].append({"page": 2, "msg": p2})
                print(f"    Page 2: {len(p2['text'])} chars, {len(p2['buttons'])} buttons")

        # Now collect ALL edge:detail buttons from all pages
        all_detail_btns = []
        for page in captures["pages"]:
            for btn in page["msg"]["buttons"]:
                if "edge:detail" in btn.get("data", ""):
                    all_detail_btns.append(btn)

        print(f"\n[4] Found {len(all_detail_btns)} total detail buttons. Tapping cards 5+...")

        # We already captured cards 1-4, so skip those
        already_captured = {
            "edge:detail:brentford_vs_everton_2026-04-11",
            "edge:detail:paris_saint_germain_vs_liverpool_2026-04-07",
            "edge:detail:everton_vs_liverpool_2026-04-19",
            "edge:detail:brentford_vs_fulham_2026-04-18",
        }

        for btn_info in all_detail_btns:
            if btn_info["data"] in already_captured:
                continue

            btn_data = btn_info["data"]
            btn_text = btn_info["text"]
            print(f"\n    Tapping: {btn_text} ({btn_data})")

            # Need to navigate to the correct page first
            # Find which page this button is on
            target_page = None
            for page in captures["pages"]:
                for b in page["msg"]["buttons"]:
                    if b["data"] == btn_data:
                        target_page = page["page"]
                        break
                if target_page is not None:
                    break

            # Navigate to target page
            if target_page is not None and target_page > 0:
                await client.send_message(BOT_USERNAME, "💎 Top Edge Picks")
                await asyncio.sleep(10)
                msgs = await client.get_messages(BOT_USERNAME, limit=5)
                current = None
                for m in msgs:
                    if not m.out and m.buttons:
                        current = m
                        break

                if current and target_page > 0:
                    for p in range(1, target_page + 1):
                        for row in current.buttons:
                            for btn in row:
                                d = (btn.data or b"").decode("utf-8", errors="ignore") if btn.data else ""
                                if d == f"hot:page:{p}":
                                    await btn.click()
                                    await asyncio.sleep(6)
                                    break
                        msgs = await client.get_messages(BOT_USERNAME, limit=5)
                        for m in msgs:
                            if not m.out and m.buttons:
                                current = m
                                break

            # Now click the detail button
            msgs = await client.get_messages(BOT_USERNAME, limit=5)
            clickable = None
            for m in msgs:
                if not m.out and m.buttons:
                    for row in m.buttons:
                        for btn in row:
                            d = (btn.data or b"").decode("utf-8", errors="ignore") if btn.data else ""
                            if d == btn_data:
                                clickable = m
                                break
                        if clickable: break
                if clickable: break

            if clickable:
                for row in clickable.buttons:
                    for btn in row:
                        d = (btn.data or b"").decode("utf-8", errors="ignore") if btn.data else ""
                        if d == btn_data:
                            await btn.click()
                            await asyncio.sleep(12)
                            break

                detail_msgs = await client.get_messages(BOT_USERNAME, limit=5)
                card = {"button_text": btn_text, "button_data": btn_data,
                        "messages": [msg_to_dict(m) for m in detail_msgs if not m.out]}
                captures["card_details"].append(card)
                print(f"        Captured: {len(detail_msgs[0].text or '') if detail_msgs else 0} chars")
            else:
                captures["errors"].append(f"Could not find {btn_data}")
                print(f"        ERROR: Button not found")

        ts = datetime.now().strftime("%Y%m%d-%H%M")
        from config import BOT_ROOT
        outfile = str(BOT_ROOT.parent / "reports" / f"clean-qa-02-remaining-{ts}.json")
        with open(outfile, "w") as f:
            json.dump(captures, f, indent=2, ensure_ascii=False, default=str)
        print(f"\nSaved to: {outfile}")
        print(f"Pages: {len(captures['pages'])}, New details: {len(captures['card_details'])}, Errors: {len(captures['errors'])}")

    finally:
        await client.disconnect()

asyncio.run(run())
