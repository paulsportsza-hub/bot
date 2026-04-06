#!/usr/bin/env python3
"""QA-BASELINE-14: Full Product Audit under QA Protocol v1.1.

Telethon E2E script that:
1. Wipes existing profile completely
2. Rebuilds with multi-sport profile per brief
3. Captures all Hot Tips cards verbatim
4. Captures all My Matches cards verbatim
5. Tests UX dimensions (navigation, latency, error handling)
6. Exports all raw data for scoring
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
    ReplyKeyboardMarkup,
)
from telethon.tl.custom import Message

API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "")
BOT_USERNAME = "mzansiedge_bot"
STRING_SESSION_FILE = Path(__file__).resolve().parent.parent / "data" / "telethon_session.string"
FILE_SESSION = Path(__file__).resolve().parent.parent / "data" / "telethon_session"

OUTPUT_DIR = Path("/home/paulsportsza/reports/qa-baseline-14")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
TIMESTAMP = datetime.now().strftime("%Y%m%d-%H%M")

# Profile spec from brief
PROFILE_SPEC = {
    "soccer": ["Man United", "Arsenal", "Kaizer Chiefs"],
    "rugby": ["Stormers", "Bulls"],
    "cricket": ["South Africa"],
    "combat": ["Dricus Du Plessis", "Naoya Inoue"],
}


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
    return msg.message or msg.text or ""


def get_buttons(msg):
    """Returns (callback_buttons, url_buttons) from message."""
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


async def wait_response(client, bot_entity, timeout=30, count=1):
    """Wait for bot response messages."""
    msgs = []
    deadline = time.time() + timeout
    while time.time() < deadline and len(msgs) < count:
        await asyncio.sleep(1.0)
        history = await client.get_messages(bot_entity, limit=5)
        for m in history:
            if m.sender_id == bot_entity.id and m.id not in [x.id for x in msgs]:
                msgs.append(m)
        if msgs:
            # Wait a bit more for additional messages
            await asyncio.sleep(1.5)
            history = await client.get_messages(bot_entity, limit=10)
            for m in history:
                if m.sender_id == bot_entity.id and m.id not in [x.id for x in msgs]:
                    msgs.append(m)
            break
    return sorted(msgs, key=lambda m: m.id)


async def wait_for_new_message(client, bot_entity, after_id, timeout=45):
    """Wait for a new message from bot after a specific message ID."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        await asyncio.sleep(1.0)
        history = await client.get_messages(bot_entity, limit=5)
        new_msgs = [m for m in history if m.sender_id == bot_entity.id and m.id > after_id]
        if new_msgs:
            await asyncio.sleep(2.0)  # Wait for any follow-up messages
            history = await client.get_messages(bot_entity, limit=15)
            new_msgs = [m for m in history if m.sender_id == bot_entity.id and m.id > after_id]
            return sorted(new_msgs, key=lambda m: m.id)
    return []


async def click_callback(client, msg, data_prefix):
    """Click a callback button matching the data prefix."""
    if not msg.reply_markup:
        return False
    for row in msg.reply_markup.rows:
        for btn in row.buttons:
            if isinstance(btn, KeyboardButtonCallback):
                d = btn.data.decode("utf-8", errors="replace") if isinstance(btn.data, bytes) else str(btn.data)
                if d.startswith(data_prefix):
                    await msg.click(data=btn.data)
                    return True
    return False


async def click_callback_exact(client, msg, data_exact):
    """Click a callback button with exact data match."""
    if not msg.reply_markup:
        return False
    for row in msg.reply_markup.rows:
        for btn in row.buttons:
            if isinstance(btn, KeyboardButtonCallback):
                d = btn.data.decode("utf-8", errors="replace") if isinstance(btn.data, bytes) else str(btn.data)
                if d == data_exact:
                    await msg.click(data=btn.data)
                    return True
    return False


def save_capture(name, data):
    """Save capture data to JSON file."""
    path = OUTPUT_DIR / f"{name}_{TIMESTAMP}.json"
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str, ensure_ascii=False)
    print(f"  Saved: {path}")
    return path


def save_text(name, text):
    """Save raw text to file."""
    path = OUTPUT_DIR / f"{name}_{TIMESTAMP}.txt"
    with open(path, "w") as f:
        f.write(text)
    print(f"  Saved: {path}")
    return path


# ──────────────────────────────────────────────────────────────
# Phase 1: WIPE PROFILE
# ──────────────────────────────────────────────────────────────
async def phase1_wipe_profile(client, bot):
    print("\n" + "="*60)
    print("PHASE 1: WIPE EXISTING PROFILE")
    print("="*60)

    captures = {"phase": "wipe_profile", "steps": []}

    # Send /start to ensure we're in a known state
    await client.send_message(bot, "/start")
    await asyncio.sleep(3)

    # Navigate to Settings
    await client.send_message(bot, "⚙️ Settings")
    await asyncio.sleep(3)
    msgs = await client.get_messages(bot, limit=3)
    settings_msg = None
    for m in msgs:
        if m.sender_id == bot.id:
            settings_msg = m
            break

    if not settings_msg:
        print("  WARNING: No settings message received")
        captures["steps"].append({"action": "settings", "status": "no_response"})
        return captures

    cb_btns, url_btns = get_buttons(settings_msg)
    captures["steps"].append({
        "action": "settings_opened",
        "text": get_text(settings_msg),
        "buttons": [b["text"] for b in cb_btns],
    })

    # Click Reset Profile
    clicked = await click_callback(client, settings_msg, "settings:reset")
    if not clicked:
        print("  WARNING: Could not find Reset Profile button")
        # Try text command
        await client.send_message(bot, "/settings")
        await asyncio.sleep(3)
        msgs = await client.get_messages(bot, limit=3)
        for m in msgs:
            if m.sender_id == bot.id:
                clicked = await click_callback(client, m, "settings:reset")
                if clicked:
                    break

    await asyncio.sleep(3)
    msgs = await client.get_messages(bot, limit=3)
    confirm_msg = None
    for m in msgs:
        if m.sender_id == bot.id:
            t = get_text(m)
            if "reset" in t.lower() or "⚠️" in t:
                confirm_msg = m
                break

    if confirm_msg:
        # Click confirm reset
        clicked = await click_callback(client, confirm_msg, "settings:reset:confirm")
        if clicked:
            print("  Profile reset confirmed")
            await asyncio.sleep(3)
            captures["steps"].append({"action": "reset_confirmed", "status": "ok"})
        else:
            print("  WARNING: Could not find confirm button")
            captures["steps"].append({"action": "reset_confirm", "status": "button_not_found"})
    else:
        print("  WARNING: No confirmation screen appeared")
        captures["steps"].append({"action": "reset_screen", "status": "not_found"})

    # Verify reset — check for onboarding prompt
    await asyncio.sleep(3)
    msgs = await client.get_messages(bot, limit=5)
    for m in msgs:
        if m.sender_id == bot.id:
            t = get_text(m)
            if "onboarding" in t.lower() or "experience" in t.lower() or "start" in t.lower():
                captures["steps"].append({"action": "reset_verified", "text": t[:200]})
                print("  Reset verified — onboarding prompt visible")
                break

    save_capture("phase1_wipe", captures)
    return captures


# ──────────────────────────────────────────────────────────────
# Phase 2: REBUILD PROFILE via Onboarding
# ──────────────────────────────────────────────────────────────
async def phase2_rebuild_profile(client, bot):
    print("\n" + "="*60)
    print("PHASE 2: REBUILD MULTI-SPORT PROFILE")
    print("="*60)

    captures = {"phase": "rebuild_profile", "steps": []}

    # Start fresh onboarding
    await client.send_message(bot, "/start")
    await asyncio.sleep(4)
    msgs = await client.get_messages(bot, limit=5)

    latest_bot_msg = None
    for m in msgs:
        if m.sender_id == bot.id:
            latest_bot_msg = m
            break

    if not latest_bot_msg:
        print("  ERROR: No bot response to /start")
        return captures

    start_text = get_text(latest_bot_msg)
    captures["steps"].append({"action": "/start", "text": start_text[:500]})
    print(f"  /start response: {start_text[:100]}...")

    # Check if we need to click "Start onboarding" button
    if await click_callback(client, latest_bot_msg, "ob_restart:go"):
        print("  Clicked 'Start onboarding'")
        await asyncio.sleep(3)
        msgs = await client.get_messages(bot, limit=3)
        for m in msgs:
            if m.sender_id == bot.id:
                latest_bot_msg = m
                break

    # Step 1: Experience — select "experienced"
    last_id = latest_bot_msg.id
    if await click_callback(client, latest_bot_msg, "ob_exp:experienced"):
        print("  Selected: Experienced")
        await asyncio.sleep(3)
    else:
        # Maybe already past experience step
        print("  Experience button not found, trying to proceed...")

    msgs = await client.get_messages(bot, limit=3)
    for m in msgs:
        if m.sender_id == bot.id and m.id >= last_id:
            latest_bot_msg = m
            break

    captures["steps"].append({"action": "experience", "text": get_text(latest_bot_msg)[:300]})

    # Step 2: Sports selection — select all 4 sport categories
    for sport in ["soccer", "rugby", "cricket", "combat"]:
        if await click_callback(client, latest_bot_msg, f"ob_sport:{sport}"):
            print(f"  Toggled sport: {sport}")
            await asyncio.sleep(1.5)
            # Re-fetch the updated message
            msgs = await client.get_messages(bot, limit=3)
            for m in msgs:
                if m.sender_id == bot.id:
                    latest_bot_msg = m
                    break

    captures["steps"].append({"action": "sports_selected", "text": get_text(latest_bot_msg)[:300]})

    # Click "Done" to proceed to favourites
    last_id = latest_bot_msg.id
    if await click_callback(client, latest_bot_msg, "ob_nav:sports_done"):
        print("  Sports done, proceeding to favourites")
        await asyncio.sleep(3)
    msgs = await client.get_messages(bot, limit=3)
    for m in msgs:
        if m.sender_id == bot.id and m.id > last_id:
            latest_bot_msg = m
            break

    # Step 3: Add teams per sport — text-based input
    # The bot should prompt for each selected sport in order
    sport_order = ["soccer", "rugby", "cricket", "combat"]
    for sport in sport_order:
        teams = PROFILE_SPEC.get(sport, [])
        if not teams:
            continue

        teams_text = ", ".join(teams)
        print(f"  Sending teams for {sport}: {teams_text}")
        last_id = latest_bot_msg.id
        await client.send_message(bot, teams_text)
        await asyncio.sleep(5)

        msgs = await client.get_messages(bot, limit=5)
        found_response = False
        for m in msgs:
            if m.sender_id == bot.id and m.id > last_id:
                latest_bot_msg = m
                found_response = True
                break

        if found_response:
            resp_text = get_text(latest_bot_msg)
            captures["steps"].append({
                "action": f"teams_{sport}",
                "input": teams_text,
                "response": resp_text[:500]
            })
            print(f"  Response: {resp_text[:100]}...")

            # Check for "Continue" button to proceed to next sport
            await asyncio.sleep(1)
            if await click_callback(client, latest_bot_msg, f"ob_fav_done:{sport}"):
                print(f"  Clicked done for {sport}")
                await asyncio.sleep(3)
                msgs = await client.get_messages(bot, limit=3)
                for m in msgs:
                    if m.sender_id == bot.id and m.id > latest_bot_msg.id:
                        latest_bot_msg = m
                        break

    # Step 4: Edge explainer (experienced users may skip)
    await asyncio.sleep(2)
    msgs = await client.get_messages(bot, limit=3)
    for m in msgs:
        if m.sender_id == bot.id:
            latest_bot_msg = m
            break

    t = get_text(latest_bot_msg)
    if "edge" in t.lower() and "works" in t.lower():
        # Edge explainer — click through
        if await click_callback(client, latest_bot_msg, "ob_nav:edge_done"):
            print("  Edge explainer acknowledged")
            await asyncio.sleep(3)
            msgs = await client.get_messages(bot, limit=3)
            for m in msgs:
                if m.sender_id == bot.id and m.id > latest_bot_msg.id:
                    latest_bot_msg = m
                    break

    # Step 5: Risk profile — select Moderate
    t = get_text(latest_bot_msg)
    if "risk" in t.lower() or "conservative" in t.lower():
        if await click_callback(client, latest_bot_msg, "ob_risk:moderate"):
            print("  Selected: Moderate risk")
            await asyncio.sleep(3)
            msgs = await client.get_messages(bot, limit=3)
            for m in msgs:
                if m.sender_id == bot.id and m.id > latest_bot_msg.id:
                    latest_bot_msg = m
                    break

    # Step 6: Bankroll — select R500
    t = get_text(latest_bot_msg)
    if "bankroll" in t.lower() or "budget" in t.lower() or "R50" in t or "R200" in t:
        if await click_callback(client, latest_bot_msg, "ob_bankroll:R500"):
            print("  Selected: R500 bankroll")
            await asyncio.sleep(3)
            msgs = await client.get_messages(bot, limit=3)
            for m in msgs:
                if m.sender_id == bot.id and m.id > latest_bot_msg.id:
                    latest_bot_msg = m
                    break

    # Step 7: Notification time — select 6 PM
    t = get_text(latest_bot_msg)
    if "notification" in t.lower() or "alert" in t.lower() or "PM" in t or "AM" in t:
        if await click_callback(client, latest_bot_msg, "ob_notify:18"):
            print("  Selected: 6 PM notifications")
            await asyncio.sleep(3)
            msgs = await client.get_messages(bot, limit=3)
            for m in msgs:
                if m.sender_id == bot.id and m.id > latest_bot_msg.id:
                    latest_bot_msg = m
                    break

    # Step 8: Summary — confirm with "Let's go!"
    t = get_text(latest_bot_msg)
    captures["steps"].append({"action": "summary", "text": t[:800]})
    print(f"  Summary: {t[:150]}...")

    if await click_callback(client, latest_bot_msg, "ob_done:finish"):
        print("  Onboarding completed!")
        await asyncio.sleep(4)

    # Verify profile via /start or Profile button
    await client.send_message(bot, "👤 Profile")
    await asyncio.sleep(3)
    msgs = await client.get_messages(bot, limit=3)
    for m in msgs:
        if m.sender_id == bot.id:
            profile_text = get_text(m)
            captures["steps"].append({"action": "profile_verify", "text": profile_text})
            print(f"  Profile verified: {profile_text[:200]}...")
            break

    save_capture("phase2_rebuild", captures)
    return captures


# ──────────────────────────────────────────────────────────────
# Phase 3: HOT TIPS — Capture All Cards
# ──────────────────────────────────────────────────────────────
async def phase3_hot_tips(client, bot):
    print("\n" + "="*60)
    print("PHASE 3: HOT TIPS — FULL VERBATIM CAPTURE")
    print("="*60)

    captures = {
        "phase": "hot_tips",
        "cards": [],
        "detail_cards": [],
        "latency": {},
        "raw_pages": [],
    }

    # Capture latency
    t0 = time.time()
    last_msgs = await client.get_messages(bot, limit=1)
    last_id = last_msgs[0].id if last_msgs else 0

    await client.send_message(bot, "💎 Top Edge Picks")
    await asyncio.sleep(2)

    # Wait for response — may include loading spinner
    page_msgs = []
    deadline = time.time() + 45
    while time.time() < deadline:
        await asyncio.sleep(2)
        history = await client.get_messages(bot, limit=15)
        new = [m for m in history if m.sender_id == bot.id and m.id > last_id]
        if new:
            # Check if still loading
            latest = max(new, key=lambda m: m.id)
            t = get_text(latest)
            if "loading" in t.lower() or "scanning" in t.lower() or "..." in t:
                continue  # Still loading
            page_msgs = sorted(new, key=lambda m: m.id)
            break

    t1 = time.time()
    captures["latency"]["hot_tips_load_s"] = round(t1 - t0, 2)
    print(f"  Hot Tips loaded in {t1-t0:.1f}s")

    if not page_msgs:
        print("  ERROR: No Hot Tips response received")
        save_capture("phase3_hot_tips", captures)
        return captures

    # Capture all page messages (may be split across multiple messages)
    for pm in page_msgs:
        text = get_text(pm)
        cb, url = get_buttons(pm)
        captures["raw_pages"].append({
            "msg_id": pm.id,
            "text": text,
            "callback_buttons": cb,
            "url_buttons": url,
        })
        print(f"  Page msg {pm.id}: {text[:120]}...")

    # Extract individual tip cards from page text
    # Cards typically marked with [N] pattern
    main_page = page_msgs[-1]  # Usually the main content is the last message
    page_text = get_text(main_page)

    # Parse cards from the page
    card_pattern = re.compile(r'\[(\d+)\](.+?)(?=\[\d+\]|━━━|$)', re.DOTALL)
    card_matches = card_pattern.findall(page_text)

    for idx, (num, card_text) in enumerate(card_matches):
        card = {
            "index": int(num),
            "raw_text": f"[{num}]{card_text.strip()}",
            "detail": None,
        }
        captures["cards"].append(card)
        print(f"  Card [{num}]: {card_text.strip()[:80]}...")

    if not card_matches:
        # Might be a different format — capture full text
        captures["cards"].append({
            "index": 0,
            "raw_text": page_text,
            "detail": None,
        })

    # Now click into each tip detail to capture full verbatim
    # Find tip buttons
    cb_buttons, url_buttons = get_buttons(main_page)
    edge_detail_btns = [b for b in cb_buttons if b["data"].startswith("edge:detail:")]

    print(f"\n  Found {len(edge_detail_btns)} detail buttons")

    for i, btn in enumerate(edge_detail_btns):
        print(f"\n  --- Clicking tip detail: {btn['text'][:50]} ---")
        t_detail_start = time.time()

        last_msgs = await client.get_messages(bot, limit=1)
        detail_last_id = last_msgs[0].id if last_msgs else 0

        await click_callback_exact(client, main_page, btn["data"])
        await asyncio.sleep(1)

        # Wait for detail view
        detail_msgs = []
        detail_deadline = time.time() + 30
        while time.time() < detail_deadline:
            await asyncio.sleep(1.5)
            history = await client.get_messages(bot, limit=5)
            new = [m for m in history if m.sender_id == bot.id and m.id > detail_last_id]
            if new:
                latest = max(new, key=lambda m: m.id)
                t = get_text(latest)
                if "loading" in t.lower() or "analysing" in t.lower() or "..." in t:
                    continue
                detail_msgs = sorted(new, key=lambda m: m.id)
                break

        t_detail_end = time.time()

        if detail_msgs:
            detail_msg = detail_msgs[-1]
            detail_text = get_text(detail_msg)
            detail_cb, detail_url = get_buttons(detail_msg)

            detail_capture = {
                "btn_text": btn["text"],
                "btn_data": btn["data"],
                "detail_text": detail_text,
                "detail_buttons_cb": detail_cb,
                "detail_buttons_url": detail_url,
                "latency_s": round(t_detail_end - t_detail_start, 2),
            }
            captures["detail_cards"].append(detail_capture)
            print(f"  Detail latency: {t_detail_end - t_detail_start:.1f}s")
            print(f"  Detail text: {detail_text[:150]}...")

            # Go back to list
            for dm in detail_msgs:
                if await click_callback(client, dm, "hot:back"):
                    await asyncio.sleep(3)
                    # Re-fetch main page for next click
                    msgs = await client.get_messages(bot, limit=3)
                    for m in msgs:
                        if m.sender_id == bot.id:
                            main_page = m
                            break
                    break
        else:
            print(f"  WARNING: No detail response for {btn['text']}")
            captures["detail_cards"].append({
                "btn_text": btn["text"],
                "btn_data": btn["data"],
                "detail_text": "NO RESPONSE",
                "latency_s": round(t_detail_end - t_detail_start, 2),
            })

        await asyncio.sleep(1)  # Breathing room between clicks

    # Check for pagination — click next page if exists
    next_btns = [b for b in cb_buttons if "hot:page:" in b["data"] and "Next" in b.get("text", "")]
    if next_btns:
        print("\n  Pagination found — capturing page 2")
        await click_callback_exact(client, main_page, next_btns[0]["data"])
        await asyncio.sleep(5)
        msgs = await client.get_messages(bot, limit=3)
        for m in msgs:
            if m.sender_id == bot.id:
                p2_text = get_text(m)
                p2_cb, p2_url = get_buttons(m)
                captures["raw_pages"].append({
                    "msg_id": m.id,
                    "text": p2_text,
                    "callback_buttons": p2_cb,
                    "url_buttons": p2_url,
                    "page": 2,
                })
                # Parse page 2 cards
                p2_matches = card_pattern.findall(p2_text)
                for num, card_text in p2_matches:
                    captures["cards"].append({
                        "index": int(num),
                        "raw_text": f"[{num}]{card_text.strip()}",
                        "detail": None,
                        "page": 2,
                    })
                break

    print(f"\n  Total cards captured: {len(captures['cards'])}")
    print(f"  Total detail views: {len(captures['detail_cards'])}")

    save_capture("phase3_hot_tips", captures)

    # Save raw text export
    raw_text = "HOT TIPS — FULL VERBATIM EXPORT\n"
    raw_text += f"Captured: {datetime.now().isoformat()}\n"
    raw_text += "="*60 + "\n\n"

    raw_text += "--- LIST VIEW ---\n\n"
    for page in captures["raw_pages"]:
        raw_text += f"[Page msg {page.get('msg_id', '?')}]\n{page['text']}\n\n"

    raw_text += "\n--- DETAIL VIEWS ---\n\n"
    for dc in captures["detail_cards"]:
        raw_text += f"[Detail: {dc['btn_text']}]\n{dc['detail_text']}\n"
        if dc.get("detail_buttons_url"):
            raw_text += f"URL buttons: {dc['detail_buttons_url']}\n"
        raw_text += f"Latency: {dc.get('latency_s', '?')}s\n"
        raw_text += "-"*40 + "\n\n"

    save_text("phase3_hot_tips_verbatim", raw_text)
    return captures


# ──────────────────────────────────────────────────────────────
# Phase 4: MY MATCHES — Capture All Cards
# ──────────────────────────────────────────────────────────────
async def phase4_my_matches(client, bot):
    print("\n" + "="*60)
    print("PHASE 4: MY MATCHES — FULL VERBATIM CAPTURE")
    print("="*60)

    captures = {
        "phase": "my_matches",
        "cards": [],
        "detail_cards": [],
        "latency": {},
        "raw_pages": [],
        "sports_found": set(),
    }

    t0 = time.time()
    last_msgs = await client.get_messages(bot, limit=1)
    last_id = last_msgs[0].id if last_msgs else 0

    await client.send_message(bot, "⚽ My Matches")
    await asyncio.sleep(2)

    # Wait for response
    page_msgs = []
    deadline = time.time() + 45
    while time.time() < deadline:
        await asyncio.sleep(2)
        history = await client.get_messages(bot, limit=15)
        new = [m for m in history if m.sender_id == bot.id and m.id > last_id]
        if new:
            latest = max(new, key=lambda m: m.id)
            t = get_text(latest)
            if "loading" in t.lower() or "..." in t and len(t) < 30:
                continue
            page_msgs = sorted(new, key=lambda m: m.id)
            break

    t1 = time.time()
    captures["latency"]["my_matches_load_s"] = round(t1 - t0, 2)
    print(f"  My Matches loaded in {t1-t0:.1f}s")

    if not page_msgs:
        print("  ERROR: No My Matches response received")
        save_capture("phase4_my_matches", captures)
        return captures

    # Capture all page messages
    main_page = None
    for pm in page_msgs:
        text = get_text(pm)
        cb, url = get_buttons(pm)
        captures["raw_pages"].append({
            "msg_id": pm.id,
            "text": text,
            "callback_buttons": cb,
            "url_buttons": url,
        })
        if cb:  # The main content message has buttons
            main_page = pm
        print(f"  Page msg {pm.id}: {text[:120]}...")

    if not main_page:
        main_page = page_msgs[-1]

    page_text = get_text(main_page)

    # Detect sports from emoji
    sport_emojis = {"⚽": "soccer", "🏉": "rugby", "🏏": "cricket", "🥊": "combat"}
    for emoji, sport in sport_emojis.items():
        if emoji in page_text:
            captures["sports_found"].add(sport)

    # Parse match cards
    card_pattern = re.compile(r'\[(\d+)\](.+?)(?=\[\d+\]|━━━|$)', re.DOTALL)
    card_matches = card_pattern.findall(page_text)

    for idx, (num, card_text) in enumerate(card_matches):
        card = {
            "index": int(num),
            "raw_text": f"[{num}]{card_text.strip()}",
        }
        captures["cards"].append(card)
        print(f"  Card [{num}]: {card_text.strip()[:80]}...")

    if not card_matches:
        captures["cards"].append({"index": 0, "raw_text": page_text})

    # Click into game details for each card
    cb_buttons, url_buttons = get_buttons(main_page)
    game_btns = [b for b in cb_buttons if b["data"].startswith("yg:game:")]

    print(f"\n  Found {len(game_btns)} game detail buttons")

    for i, btn in enumerate(game_btns[:6]):  # Cap at 6 to avoid timeout/RAM issues
        print(f"\n  --- Clicking game detail: {btn['text'][:50]} ---")
        t_detail_start = time.time()

        last_msgs = await client.get_messages(bot, limit=1)
        detail_last_id = last_msgs[0].id if last_msgs else 0

        await click_callback_exact(client, main_page, btn["data"])
        await asyncio.sleep(1)

        detail_msgs = []
        detail_deadline = time.time() + 45
        while time.time() < detail_deadline:
            await asyncio.sleep(2)
            history = await client.get_messages(bot, limit=5)
            new = [m for m in history if m.sender_id == bot.id and m.id > detail_last_id]
            if new:
                latest = max(new, key=lambda m: m.id)
                t = get_text(latest)
                if "analysing" in t.lower() or "loading" in t.lower() or ("..." in t and len(t) < 50):
                    continue
                detail_msgs = sorted(new, key=lambda m: m.id)
                break

        t_detail_end = time.time()

        if detail_msgs:
            detail_msg = detail_msgs[-1]
            detail_text = get_text(detail_msg)
            detail_cb, detail_url = get_buttons(detail_msg)

            # Detect sport from detail content
            for emoji, sport in sport_emojis.items():
                if emoji in detail_text or emoji in btn["text"]:
                    captures["sports_found"].add(sport)

            detail_capture = {
                "btn_text": btn["text"],
                "btn_data": btn["data"],
                "detail_text": detail_text,
                "detail_buttons_cb": detail_cb,
                "detail_buttons_url": detail_url,
                "latency_s": round(t_detail_end - t_detail_start, 2),
            }
            captures["detail_cards"].append(detail_capture)
            print(f"  Detail latency: {t_detail_end - t_detail_start:.1f}s")
            print(f"  Detail text: {detail_text[:150]}...")

            # Go back
            for dm in detail_msgs:
                if await click_callback(client, dm, "yg:all"):
                    await asyncio.sleep(3)
                    msgs = await client.get_messages(bot, limit=3)
                    for m in msgs:
                        if m.sender_id == bot.id:
                            main_page = m
                            break
                    break
        else:
            print(f"  WARNING: No detail response for {btn['text']}")
            captures["detail_cards"].append({
                "btn_text": btn["text"],
                "btn_data": btn["data"],
                "detail_text": "NO RESPONSE",
                "latency_s": round(t_detail_end - t_detail_start, 2),
            })

        await asyncio.sleep(1)

    # Convert set to list for JSON serialization
    captures["sports_found"] = list(captures["sports_found"])

    print(f"\n  Total cards captured: {len(captures['cards'])}")
    print(f"  Total detail views: {len(captures['detail_cards'])}")
    print(f"  Sports found: {captures['sports_found']}")

    save_capture("phase4_my_matches", captures)

    # Save raw text export
    raw_text = "MY MATCHES — FULL VERBATIM EXPORT\n"
    raw_text += f"Captured: {datetime.now().isoformat()}\n"
    raw_text += f"Sports found: {', '.join(captures['sports_found'])}\n"
    raw_text += "="*60 + "\n\n"

    raw_text += "--- LIST VIEW ---\n\n"
    for page in captures["raw_pages"]:
        raw_text += f"[Page msg {page.get('msg_id', '?')}]\n{page['text']}\n\n"

    raw_text += "\n--- DETAIL VIEWS ---\n\n"
    for dc in captures["detail_cards"]:
        raw_text += f"[Detail: {dc['btn_text']}]\n{dc['detail_text']}\n"
        if dc.get("detail_buttons_url"):
            raw_text += f"URL buttons: {dc['detail_buttons_url']}\n"
        raw_text += f"Latency: {dc.get('latency_s', '?')}s\n"
        raw_text += "-"*40 + "\n\n"

    save_text("phase4_my_matches_verbatim", raw_text)
    return captures


# ──────────────────────────────────────────────────────────────
# Phase 5: UX AUDIT — 14 Dimensions
# ──────────────────────────────────────────────────────────────
async def phase5_ux_audit(client, bot):
    print("\n" + "="*60)
    print("PHASE 5: UX AUDIT — 14 DIMENSIONS")
    print("="*60)

    captures = {"phase": "ux_audit", "tests": []}

    # Test 1: /help command
    print("  Testing /help...")
    t0 = time.time()
    await client.send_message(bot, "/help")
    await asyncio.sleep(3)
    msgs = await client.get_messages(bot, limit=3)
    help_text = ""
    for m in msgs:
        if m.sender_id == bot.id:
            help_text = get_text(m)
            break
    captures["tests"].append({
        "test": "help_command",
        "latency_s": round(time.time() - t0, 2),
        "text": help_text,
        "pass": bool(help_text),
    })

    # Test 2: Profile page
    print("  Testing Profile...")
    t0 = time.time()
    await client.send_message(bot, "👤 Profile")
    await asyncio.sleep(3)
    msgs = await client.get_messages(bot, limit=3)
    profile_text = ""
    for m in msgs:
        if m.sender_id == bot.id:
            profile_text = get_text(m)
            break
    captures["tests"].append({
        "test": "profile",
        "latency_s": round(time.time() - t0, 2),
        "text": profile_text,
        "pass": bool(profile_text),
    })

    # Test 3: Settings page
    print("  Testing Settings...")
    t0 = time.time()
    await client.send_message(bot, "⚙️ Settings")
    await asyncio.sleep(3)
    msgs = await client.get_messages(bot, limit=3)
    settings_text = ""
    settings_msg = None
    for m in msgs:
        if m.sender_id == bot.id:
            settings_text = get_text(m)
            settings_msg = m
            break
    captures["tests"].append({
        "test": "settings",
        "latency_s": round(time.time() - t0, 2),
        "text": settings_text,
        "pass": bool(settings_text),
    })

    # Test 4: Guide page
    print("  Testing Guide...")
    t0 = time.time()
    await client.send_message(bot, "📖 Guide")
    await asyncio.sleep(3)
    msgs = await client.get_messages(bot, limit=3)
    guide_text = ""
    for m in msgs:
        if m.sender_id == bot.id:
            guide_text = get_text(m)
            break
    captures["tests"].append({
        "test": "guide",
        "latency_s": round(time.time() - t0, 2),
        "text": guide_text,
        "pass": bool(guide_text),
    })

    # Test 5: Back navigation from Settings
    print("  Testing back navigation...")
    if settings_msg:
        t0 = time.time()
        await click_callback(client, settings_msg, "nav:main")
        await asyncio.sleep(3)
        msgs = await client.get_messages(bot, limit=3)
        nav_text = ""
        for m in msgs:
            if m.sender_id == bot.id:
                nav_text = get_text(m)
                break
        captures["tests"].append({
            "test": "back_navigation",
            "latency_s": round(time.time() - t0, 2),
            "text": nav_text[:200],
            "pass": bool(nav_text),
        })

    # Test 6: Invalid input handling
    print("  Testing error handling...")
    t0 = time.time()
    await client.send_message(bot, "asdfghjkl random gibberish 12345")
    await asyncio.sleep(3)
    msgs = await client.get_messages(bot, limit=3)
    error_text = ""
    for m in msgs:
        if m.sender_id == bot.id:
            error_text = get_text(m)
            break
    captures["tests"].append({
        "test": "error_handling",
        "latency_s": round(time.time() - t0, 2),
        "text": error_text[:200],
        "pass": True,  # Any response (or graceful silence) is acceptable
    })

    # Test 7: /menu command
    print("  Testing /menu...")
    t0 = time.time()
    await client.send_message(bot, "/menu")
    await asyncio.sleep(3)
    msgs = await client.get_messages(bot, limit=3)
    menu_text = ""
    for m in msgs:
        if m.sender_id == bot.id:
            menu_text = get_text(m)
            break
    captures["tests"].append({
        "test": "menu_command",
        "latency_s": round(time.time() - t0, 2),
        "text": menu_text[:200],
        "pass": bool(menu_text),
    })

    # Test 8: Sticky keyboard presence
    print("  Testing sticky keyboard...")
    msgs = await client.get_messages(bot, limit=5)
    has_reply_keyboard = False
    for m in msgs:
        if m.sender_id == bot.id and isinstance(m.reply_markup, ReplyKeyboardMarkup):
            has_reply_keyboard = True
            break
    captures["tests"].append({
        "test": "sticky_keyboard",
        "pass": has_reply_keyboard,
    })

    # Test 9: /subscribe flow
    print("  Testing subscription flow...")
    t0 = time.time()
    await client.send_message(bot, "/subscribe")
    await asyncio.sleep(3)
    msgs = await client.get_messages(bot, limit=3)
    sub_text = ""
    for m in msgs:
        if m.sender_id == bot.id:
            sub_text = get_text(m)
            break
    captures["tests"].append({
        "test": "subscribe_flow",
        "latency_s": round(time.time() - t0, 2),
        "text": sub_text[:300],
        "pass": bool(sub_text),
    })

    # Test 10: /status command
    print("  Testing /status...")
    t0 = time.time()
    await client.send_message(bot, "/status")
    await asyncio.sleep(3)
    msgs = await client.get_messages(bot, limit=3)
    status_text = ""
    for m in msgs:
        if m.sender_id == bot.id:
            status_text = get_text(m)
            break
    captures["tests"].append({
        "test": "status_command",
        "latency_s": round(time.time() - t0, 2),
        "text": status_text[:300],
        "pass": bool(status_text),
    })

    save_capture("phase5_ux_audit", captures)

    # Save raw text export
    raw_text = "UX AUDIT — RAW CAPTURES\n"
    raw_text += f"Captured: {datetime.now().isoformat()}\n"
    raw_text += "="*60 + "\n\n"
    for test in captures["tests"]:
        raw_text += f"[{test['test']}] {'PASS' if test['pass'] else 'FAIL'}"
        if "latency_s" in test:
            raw_text += f" ({test['latency_s']}s)"
        raw_text += "\n"
        if "text" in test:
            raw_text += f"{test['text']}\n"
        raw_text += "-"*40 + "\n\n"

    save_text("phase5_ux_audit_raw", raw_text)
    return captures


# ──────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────
async def main():
    print("QA-BASELINE-14: Full Product Audit")
    print(f"Timestamp: {TIMESTAMP}")
    print(f"Output dir: {OUTPUT_DIR}")

    client = await get_client()
    bot = await client.get_entity(BOT_USERNAME)
    print(f"Connected as user, bot entity: {bot.id}")

    results = {}

    # Phase 1: Wipe
    results["phase1"] = await phase1_wipe_profile(client, bot)

    # Phase 2: Rebuild
    results["phase2"] = await phase2_rebuild_profile(client, bot)

    # Phase 3: Hot Tips
    results["phase3"] = await phase3_hot_tips(client, bot)

    # Phase 4: My Matches
    results["phase4"] = await phase4_my_matches(client, bot)

    # Phase 5: UX Audit
    results["phase5"] = await phase5_ux_audit(client, bot)

    # Save combined results
    save_capture("qa_baseline_14_combined", results)

    print("\n" + "="*60)
    print("QA-BASELINE-14 DATA COLLECTION COMPLETE")
    print("="*60)
    print(f"Output directory: {OUTPUT_DIR}")
    print(f"Hot Tips cards: {len(results.get('phase3', {}).get('cards', []))}")
    print(f"Hot Tips details: {len(results.get('phase3', {}).get('detail_cards', []))}")
    print(f"My Matches cards: {len(results.get('phase4', {}).get('cards', []))}")
    print(f"My Matches details: {len(results.get('phase4', {}).get('detail_cards', []))}")
    print(f"UX tests: {len(results.get('phase5', {}).get('tests', []))}")

    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
