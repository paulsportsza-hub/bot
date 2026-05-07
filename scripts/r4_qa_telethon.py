#!/usr/bin/env python3
"""R4-QA-01: Comprehensive Telethon QA Audit — Full North Star Scoring.

Strategy: Navigate to Top Edge Picks, record the list, then for EACH card:
  1. Re-navigate to the list (fresh message)
  2. Click the card's detail button on that fresh message
  3. Wait and re-fetch to capture the edited (detail) message
  4. Record the detail content

This avoids stale message issues since inline callbacks edit the same message.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import re
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
OUTPUT_DIR = BOT_ROOT.parent / "reports" / "r4-qa"
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
    """Returns (callback_buttons, url_buttons) as lists of dicts."""
    cb, url = [], []
    if not msg.reply_markup or not isinstance(msg.reply_markup, ReplyInlineMarkup):
        return cb, url
    for row in msg.reply_markup.rows:
        for btn in row.buttons:
            if isinstance(btn, KeyboardButtonCallback):
                d = btn.data.decode("utf-8", errors="replace") if isinstance(btn.data, bytes) else str(btn.data)
                cb.append({"text": btn.text, "data": d})
            elif isinstance(btn, KeyboardButtonUrl):
                url.append({"text": btn.text, "url": btn.url})
    return cb, url


async def navigate_to_picks(client, entity, page: int = 0) -> tuple:
    """Send 💎 Top Edge Picks, optionally navigate to a specific page.
    Returns (message_object, text, cb_buttons, url_buttons).
    """
    await client.send_message(entity, "💎 Top Edge Picks")
    await asyncio.sleep(15)

    msgs = await client.get_messages(entity, limit=10)
    target = None
    for m in msgs:
        if getattr(m, 'sender_id', None) == entity.id:
            t = get_text(m)
            if "Edge Picks" in t or "Live Edges" in t or "Scanned" in t:
                target = m
                break
    if not target:
        for m in msgs:
            if getattr(m, 'sender_id', None) == entity.id:
                target = m
                break

    if not target:
        return None, "", [], []

    # Navigate to requested page if > 0
    if page > 0:
        cb, _ = get_buttons(target)
        for btn in cb:
            if btn["data"] == f"hot:page:{page}":
                await target.click(data=btn["data"].encode())
                await asyncio.sleep(8)
                # Re-fetch — bot edits the message
                msgs = await client.get_messages(entity, limit=10)
                for m in msgs:
                    if getattr(m, 'sender_id', None) == entity.id:
                        t = get_text(m)
                        if "[" in t and "vs" in t:
                            target = m
                            break
                break

    text = get_text(target)
    cb, url = get_buttons(target)
    return target, text, cb, url


async def click_detail_and_capture(client, entity, list_msg, btn_data: str) -> dict:
    """Click a detail button on the list message, wait for edit, capture detail content.
    Returns dict with detail info.
    """
    result = {"detail_text": "", "detail_cb_buttons": [], "detail_url_buttons": [],
              "load_time": 0, "error": None}

    t0 = time.time()
    try:
        # Click the inline button
        await list_msg.click(data=btn_data.encode("utf-8") if isinstance(btn_data, str) else btn_data)
        await asyncio.sleep(15)  # Wait for bot to edit the message
        result["load_time"] = time.time() - t0

        # Re-fetch messages — the clicked message should now show detail content
        msgs = await client.get_messages(entity, limit=10)

        # Find the detail view: look for 📋 (Setup section) or 🎯 (match header) or 🔒 (locked)
        for m in msgs:
            if getattr(m, 'sender_id', None) == entity.id:
                t = get_text(m)
                if any(x in t for x in ["📋 ", "🏆 Verdict", "The Setup", "🔒"]):
                    result["detail_text"] = t
                    cb, url = get_buttons(m)
                    result["detail_cb_buttons"] = cb
                    result["detail_url_buttons"] = url
                    break
                # Also check for the match header pattern (🎯 Team vs Team)
                if re.search(r'🎯\s+\S+.*vs\s+\S+', t):
                    result["detail_text"] = t
                    cb, url = get_buttons(m)
                    result["detail_cb_buttons"] = cb
                    result["detail_url_buttons"] = url
                    break

        if not result["detail_text"]:
            # Fallback: take most recent bot message that's NOT the list view
            for m in msgs:
                if getattr(m, 'sender_id', None) == entity.id:
                    t = get_text(m)
                    if "Edge Picks" not in t and "Live Edges" not in t and len(t) > 100:
                        result["detail_text"] = t
                        cb, url = get_buttons(m)
                        result["detail_cb_buttons"] = cb
                        result["detail_url_buttons"] = url
                        break

    except Exception as e:
        result["error"] = str(e)
        result["load_time"] = time.time() - t0

    return result


async def main():
    print("=" * 60)
    print("R4-QA-01: Telethon QA Audit — @mzansiedge_bot")
    print(f"Date: {datetime.now().isoformat()}")
    print("=" * 60)

    # Connect
    print("\n[CONNECT] Connecting to Telegram...")
    t0 = time.time()
    client = await get_client()
    me = await client.get_me()
    conn_time = time.time() - t0
    entity = await client.get_entity(BOT_USERNAME)
    print(f"  Connected as {me.first_name} (@{me.username}) in {conn_time:.1f}s")
    print(f"  Bot: @{BOT_USERNAME} (ID: {entity.id})")

    output = {
        "timestamp": datetime.now().isoformat(),
        "connection": {"user": me.first_name, "username": me.username, "time": conn_time,
                       "bot_id": entity.id},
        "start_response": {},
        "pages": [],
        "cards": [],
    }

    # /start
    print("\n[START] Sending /start...")
    await client.send_message(entity, "/start")
    await asyncio.sleep(5)
    start_msgs = await client.get_messages(entity, limit=10)
    for m in start_msgs:
        if getattr(m, 'sender_id', None) == entity.id:
            output["start_response"] = {"text": get_text(m)[:500]}
            print(f"  Response: {get_text(m)[:100]}...")
            break

    # Collect all pages and their card buttons
    print("\n[LIST] Loading Top Edge Picks pages...")
    all_card_buttons = []  # (page_num, btn_text, btn_data)

    # Page 0 (first page)
    _, p0_text, p0_cb, p0_url = await navigate_to_picks(client, entity, page=0)
    if p0_text:
        output["pages"].append({"page": 0, "text": p0_text, "buttons": p0_cb, "url_buttons": p0_url})
        for btn in p0_cb:
            if btn["data"].startswith("edge:detail:"):
                all_card_buttons.append((0, btn["text"], btn["data"]))
        card_count_p0 = len([b for b in p0_cb if b["data"].startswith("edge:detail:")])
        print(f"  Page 0: {card_count_p0} cards")

        # Check for pagination — look for hot:page: buttons
        page_buttons = [b for b in p0_cb if b["data"].startswith("hot:page:")]
        for pb in page_buttons:
            pnum = int(pb["data"].split(":")[-1])
            if pnum > 0:
                print(f"  Found Next page button → page {pnum}")
                _, pn_text, pn_cb, pn_url = await navigate_to_picks(client, entity, page=pnum)
                if pn_text:
                    output["pages"].append({"page": pnum, "text": pn_text, "buttons": pn_cb, "url_buttons": pn_url})
                    for btn in pn_cb:
                        if btn["data"].startswith("edge:detail:"):
                            all_card_buttons.append((pnum, btn["text"], btn["data"]))
                    cc = len([b for b in pn_cb if b["data"].startswith("edge:detail:")])
                    print(f"  Page {pnum}: {cc} cards")

                    # Check for more pages
                    more_pages = [b for b in pn_cb if b["data"].startswith("hot:page:")]
                    for mp in more_pages:
                        mn = int(mp["data"].split(":")[-1])
                        if mn > pnum:
                            print(f"  Found page {mn}...")
                            _, mn_text, mn_cb, mn_url = await navigate_to_picks(client, entity, page=mn)
                            if mn_text:
                                output["pages"].append({"page": mn, "text": mn_text, "buttons": mn_cb, "url_buttons": mn_url})
                                for btn in mn_cb:
                                    if btn["data"].startswith("edge:detail:"):
                                        all_card_buttons.append((mn, btn["text"], btn["data"]))
                                cc2 = len([b for b in mn_cb if b["data"].startswith("edge:detail:")])
                                print(f"  Page {mn}: {cc2} cards")

    print(f"\n  Total cards across all pages: {len(all_card_buttons)}")

    # Tap each card detail
    print("\n[DETAILS] Tapping each card for detail view...")
    for i, (page_num, btn_text, btn_data) in enumerate(all_card_buttons, 1):
        print(f"\n  Card {i}/{len(all_card_buttons)}: {btn_text}")
        match_key = btn_data.replace("edge:detail:", "")

        # Navigate to the correct page first
        list_msg, _, _, _ = await navigate_to_picks(client, entity, page=page_num)
        if not list_msg:
            print("    ERROR: Could not navigate to list page")
            output["cards"].append({
                "index": i, "button_text": btn_text, "match_key": match_key,
                "page": page_num, "error": "Could not navigate to list",
            })
            continue

        # Click the detail button
        detail = await click_detail_and_capture(client, entity, list_msg, btn_data)

        card_data = {
            "index": i,
            "button_text": btn_text,
            "match_key": match_key,
            "page": page_num,
            "detail_text": detail["detail_text"],
            "detail_cb_buttons": detail["detail_cb_buttons"],
            "detail_url_buttons": detail["detail_url_buttons"],
            "load_time": detail["load_time"],
            "error": detail["error"],
        }

        # Parse detail content
        text = detail["detail_text"]
        if text:
            # Teams
            tm = re.search(r'🎯\s*(.*?)\s+vs\s+(.*?)(?:\n|$)', text)
            if tm:
                card_data["home_team"] = tm.group(1).strip()
                card_data["away_team"] = tm.group(2).strip()

            # League
            lm = re.search(r'🏆\s*(.*?)(?:\n|$)', text)
            if lm:
                card_data["league"] = lm.group(1).strip()

            # Kickoff
            km = re.search(r'📅\s*(.*?)(?:\n|$)', text)
            if km:
                card_data["kickoff"] = km.group(1).strip()

            # Broadcast
            bm = re.search(r'📺\s*(.*?)(?:\n|$)', text)
            if bm:
                card_data["broadcast"] = bm.group(1).strip()

            # Edge tier
            for tier, emoji in [("DIAMOND", "💎"), ("GOLDEN", "🥇"), ("SILVER", "🥈"), ("BRONZE", "🥉")]:
                if emoji in text:
                    card_data["edge_tier"] = tier.lower()
                    break

            # EV
            ev = re.search(r'EV\s*\+?([\d.]+)%', text)
            if ev:
                card_data["ev_pct"] = ev.group(1)

            # CTA button bookmaker
            for ub in detail.get("detail_url_buttons", []):
                if any(x in ub["text"] for x in ["Bet", "Back", "→"]):
                    card_data["cta_button"] = ub["text"]
                    break
            for cb in detail.get("detail_cb_buttons", []):
                if any(x in cb["text"] for x in ["Back", "→"]) and "Edge Picks" not in cb["text"] and "Menu" not in cb["text"]:
                    card_data["cta_button"] = cb["text"]
                    break

            # Bookmaker in verdict/odds
            odds_bk = re.search(r'on\s+([\w]+)\s*→', text)
            if odds_bk:
                card_data["bookmaker_in_text"] = odds_bk.group(1)

            print(f"    {card_data.get('home_team', '?')} vs {card_data.get('away_team', '?')}")
            print(f"    League: {card_data.get('league', '?')}")
            print(f"    Tier: {card_data.get('edge_tier', '?')}")
            print(f"    CTA: {card_data.get('cta_button', 'NONE')}")
            print(f"    Load: {detail['load_time']:.1f}s")
            print(f"    Text: {len(text)} chars")
        else:
            print(f"    WARNING: Empty detail text! Error: {detail.get('error')}")

        output["cards"].append(card_data)

    # Save
    out_file = OUTPUT_DIR / "r4_qa_raw.json"
    out_file.write_text(json.dumps(output, indent=2, ensure_ascii=False))
    print(f"\n{'=' * 60}")
    print(f"Audit complete. Cards captured: {len(output['cards'])}")
    print(f"Output: {out_file}")

    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
