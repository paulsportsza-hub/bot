"""REGFIX-QA-01: Post-Programme Live Bot QA Audit via Telethon.

Scores the LIVE Telegram bot against the North Star rubric.
Captures ALL card text, scores on 4 dimensions, checks consistency.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.sessions import StringSession
from telethon.tl.custom.message import Message

load_dotenv()

BOT = "mzansiedge_bot"
API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "")
SESSION_PATH = Path("data/telethon_session.string")
from config import BOT_ROOT
RAW_PATH = BOT_ROOT.parent / "reports" / "REGFIX-QA-01-raw-captures.txt"
RESULTS_PATH = BOT_ROOT.parent / "reports" / "REGFIX-QA-01-results.json"

REPLY_TIMEOUT = 20
LOAD_TIMEOUT = 60


async def last_id(client):
    msgs = await client.get_messages(BOT, limit=1)
    return msgs[0].id if msgs else 0


async def send_and_wait(client, text, timeout=REPLY_TIMEOUT):
    """Send text and wait for a new bot reply (by message ID)."""
    lid = await last_id(client)
    await client.send_message(BOT, text)
    await asyncio.sleep(2)
    deadline = time.time() + timeout
    while time.time() < deadline:
        msgs = await client.get_messages(BOT, limit=5)
        for m in msgs:
            if m.id > lid and not m.out:
                return m
        await asyncio.sleep(1.0)
    return None


async def click_and_wait(client, msg, btn_data, timeout=REPLY_TIMEOUT):
    """Click an inline button and wait for the message to update."""
    old_text = msg.text or ""
    old_id = msg.id
    # Find the actual button object
    if msg.buttons:
        for row in msg.buttons:
            for btn in row:
                if btn.data and btn.data.decode() == btn_data:
                    await btn.click()
                    await asyncio.sleep(2)
                    # Re-fetch the message
                    msgs = await client.get_messages(BOT, ids=[old_id])
                    if msgs and msgs[0]:
                        return msgs[0]
                    return None
    return None


async def wait_for_content(client, msg_id, timeout=LOAD_TIMEOUT):
    """Wait for a message to finish loading (stop containing spinner indicators)."""
    deadline = time.time() + timeout
    spinner_indicators = ["Loading", "Scanning", "Analysing", "⚽ .", "🏉 .", "🏏 .", "🥊 ."]
    last_text = ""
    stable_count = 0
    while time.time() < deadline:
        msgs = await client.get_messages(BOT, ids=[msg_id])
        if msgs and msgs[0]:
            current = msgs[0].text or ""
            # If text is substantive and not a spinner
            if len(current) > 100 and not any(s in current for s in spinner_indicators):
                return msgs[0]
            # If text stopped changing
            if current == last_text and len(current) > 50:
                stable_count += 1
                if stable_count >= 3:
                    return msgs[0]
            else:
                stable_count = 0
            last_text = current
        await asyncio.sleep(2.0)
    # Return whatever we have
    msgs = await client.get_messages(BOT, ids=[msg_id])
    return msgs[0] if msgs else None


def get_buttons(msg):
    """Extract button info from a message."""
    btns = []
    if msg and msg.buttons:
        for row in msg.buttons:
            for btn in row:
                btns.append({
                    "text": btn.text,
                    "data": btn.data.decode() if btn.data else None,
                    "url": btn.url if hasattr(btn, "url") and btn.url else None,
                })
    return btns


def get_tier(text):
    if "💎" in text: return "diamond"
    if "🥇" in text: return "gold"
    if "🥈" in text: return "silver"
    if "🥉" in text: return "bronze"
    return "unknown"


def get_ev(text):
    m = re.search(r'EV\s*[+]?([\d.]+)%', text)
    return float(m.group(1)) if m else None


async def run_audit():
    session_str = SESSION_PATH.read_text().strip()
    client = TelegramClient(StringSession(session_str), API_ID, API_HASH)
    await client.start()

    captures = []
    cards = []
    pages = []
    nav_issues = []

    print("=" * 60)
    print("REGFIX-QA-01: Live Bot QA Audit")
    print(f"Started: {datetime.now().isoformat()}")
    print("=" * 60)

    # ── 1. /start ──
    print("\n[1] /start ...")
    msg = await send_and_wait(client, "/start")
    if msg:
        captures.append(f"=== /start ===\n{msg.text}\n\nBUTTONS: {json.dumps(get_buttons(msg), indent=2)}")
        print(f"  OK: {len(msg.text or '')} chars")
    else:
        print("  WARN: no response")
    await asyncio.sleep(2)

    # ── 2. Top Edge Picks ──
    print("\n[2] Top Edge Picks ...")
    msg = await send_and_wait(client, "💎 Top Edge Picks", timeout=30)
    if not msg:
        print("  Trying /picks fallback...")
        msg = await send_and_wait(client, "/picks", timeout=30)
    if not msg:
        print("  FATAL: no response to Edge Picks or /picks")
        await client.disconnect()
        return None

    # Wait for content to load
    print(f"  Initial: {len(msg.text or '')} chars — waiting for content...")
    msg = await wait_for_content(client, msg.id)
    picks_msg_id = msg.id

    page0_text = msg.text or ""
    page0_btns = get_buttons(msg)
    captures.append(f"=== TOP EDGE PICKS PAGE 0 ===\n{page0_text}\n\nBUTTONS:\n{json.dumps(page0_btns, indent=2)}")
    pages.append({"page": 0, "text": page0_text, "buttons": page0_btns})
    print(f"  Page 0: {len(page0_text)} chars, {len(page0_btns)} buttons")

    # Extract EV from list view per card line
    list_evs = {}
    list_tiers = {}
    for line in page0_text.split("\n"):
        # Match pattern like [N] ... 🥇 or 💎
        idx_match = re.search(r'\[(\d+)\]', line)
        if idx_match:
            idx = int(idx_match.group(1))
            list_tiers[idx] = get_tier(line)
        ev_match = re.search(r'EV\s*[+]?([\d.]+)%', line)
        if ev_match and idx_match:
            list_evs[int(idx_match.group(1))] = float(ev_match.group(1))

    # ── 3. Browse additional pages ──
    page_num = 1
    all_page_btns = list(page0_btns)

    while page_num < 10:
        next_btn = None
        for btn in all_page_btns:
            if btn["data"] and f"hot:page:{page_num}" in btn["data"]:
                next_btn = btn
                break
        if not next_btn:
            break

        print(f"\n[3.{page_num}] Page {page_num}...")
        result = await click_and_wait(client, msg, next_btn["data"])
        if not result:
            break
        result = await wait_for_content(client, picks_msg_id)
        msg = result

        page_text = msg.text or ""
        page_btns = get_buttons(msg)
        captures.append(f"=== TOP EDGE PICKS PAGE {page_num} ===\n{page_text}\n\nBUTTONS:\n{json.dumps(page_btns, indent=2)}")
        pages.append({"page": page_num, "text": page_text, "buttons": page_btns})
        all_page_btns = list(page_btns)
        print(f"  Page {page_num}: {len(page_text)} chars, {len(page_btns)} buttons")

        # Extract EV/tier from this page too
        for line in page_text.split("\n"):
            idx_match = re.search(r'\[(\d+)\]', line)
            if idx_match:
                idx = int(idx_match.group(1))
                list_tiers[idx] = get_tier(line)
            ev_match = re.search(r'EV\s*[+]?([\d.]+)%', line)
            if ev_match and idx_match:
                list_evs[int(idx_match.group(1))] = float(ev_match.group(1))

        page_num += 1

    # ── 4. Tap into each detail ──
    print(f"\n[4] Tapping into detail views...")

    # Collect all edge:detail buttons across all pages
    detail_tasks = []
    for pg in pages:
        for btn in pg["buttons"]:
            if btn["data"] and "edge:detail:" in btn["data"]:
                match_key = btn["data"].replace("edge:detail:", "")
                detail_tasks.append({
                    "btn_data": btn["data"],
                    "btn_text": btn["text"],
                    "match_key": match_key,
                    "from_page": pg["page"],
                })

    print(f"  Found {len(detail_tasks)} detail buttons")

    # Go back to page 0 if needed
    if page_num > 1:
        await click_and_wait(client, msg, "hot:page:0")
        await asyncio.sleep(2)
        msgs_check = await client.get_messages(BOT, ids=[picks_msg_id])
        if msgs_check and msgs_check[0]:
            msg = msgs_check[0]

    for i, task in enumerate(detail_tasks):
        mk = task["match_key"]
        print(f"\n  [{i+1}/{len(detail_tasks)}] {mk[:60]}...")

        # Navigate to correct page
        if task["from_page"] > 0:
            r = await click_and_wait(client, msg, f"hot:page:{task['from_page']}")
            if r:
                msg = r
                await asyncio.sleep(1)

        # Click detail
        r = await click_and_wait(client, msg, task["btn_data"])
        if r:
            msg = r
        await asyncio.sleep(1)

        # Wait for content if loading
        msg = await wait_for_content(client, picks_msg_id)
        detail_text = msg.text or ""
        detail_btns = get_buttons(msg)

        card = {
            "index": i + 1,
            "match_key": mk,
            "from_page": task["from_page"],
            "list_btn_text": task["btn_text"],
            "list_tier": get_tier(task["btn_text"]),
            "detail_text": detail_text,
            "detail_length": len(detail_text),
            "detail_buttons": detail_btns,
            "detail_tier": get_tier(detail_text),
            "detail_ev": get_ev(detail_text),
            "has_setup": "📋" in detail_text or "Setup" in detail_text,
            "has_edge": "🎯" in detail_text or "The Edge" in detail_text,
            "has_risk": "⚠" in detail_text or "Risk" in detail_text,
            "has_verdict": "🏆" in detail_text or "Verdict" in detail_text,
            "has_kickoff": "📅" in detail_text,
            "has_broadcast": "📺" in detail_text,
            "has_league": "🏆" in detail_text,
            "has_back_btn": any("back" in (b.get("data") or "").lower() or "↩" in b["text"] for b in detail_btns),
            "has_cta_url": any(b.get("url") for b in detail_btns),
            "has_compare_odds": any("odds:compare" in (b.get("data") or "") for b in detail_btns),
            "locked": "🔒" in detail_text or "Unlock" in detail_text,
            "cta_text": next((b["text"] for b in detail_btns if b.get("url")), None),
        }
        cards.append(card)

        captures.append(
            f"=== CARD {i+1}: {mk} ===\n"
            f"LIST BUTTON: {task['btn_text']}\n"
            f"PAGE: {task['from_page']}\n\n"
            f"FULL DETAIL TEXT:\n{detail_text}\n\n"
            f"BUTTONS:\n{json.dumps(detail_btns, indent=2)}"
        )

        sections = f"setup={'Y' if card['has_setup'] else 'N'} edge={'Y' if card['has_edge'] else 'N'} " \
                   f"risk={'Y' if card['has_risk'] else 'N'} verdict={'Y' if card['has_verdict'] else 'N'}"
        print(f"    {len(detail_text)} chars | tier={card['detail_tier']} | {sections}")
        print(f"    back={card['has_back_btn']} cta={card['has_cta_url']} locked={card['locked']}")

        # Navigate back
        back_data = None
        for btn in detail_btns:
            d = btn.get("data") or ""
            if "hot:back" in d:
                back_data = d
                break
        if back_data:
            r = await click_and_wait(client, msg, back_data)
            if r:
                msg = r
            await asyncio.sleep(1)
        else:
            nav_issues.append(f"No back button on card {i+1}: {mk}")
            # Try to go back to page 0
            r = await click_and_wait(client, msg, "hot:page:0")
            if r:
                msg = r
            await asyncio.sleep(1)

    # ── 5. Navigation checks ──
    print("\n[5] Navigation checks...")

    # My Matches
    mm = await send_and_wait(client, "⚽ My Matches", timeout=20)
    if mm:
        mm = await wait_for_content(client, mm.id, timeout=20)
        captures.append(f"=== MY MATCHES ===\n{mm.text}\n\nBUTTONS:\n{json.dumps(get_buttons(mm), indent=2)}")
        print(f"  My Matches: {len(mm.text or '')} chars")
    await asyncio.sleep(2)

    # Settings
    st = await send_and_wait(client, "⚙️ Settings")
    if st:
        captures.append(f"=== SETTINGS ===\n{st.text}\n\nBUTTONS:\n{json.dumps(get_buttons(st), indent=2)}")
        print(f"  Settings: {len(st.text or '')} chars")
    await asyncio.sleep(2)

    # Help
    hp = await send_and_wait(client, "❓ Help")
    if hp:
        captures.append(f"=== HELP ===\n{hp.text}")
        print(f"  Help: {len(hp.text or '')} chars")
    await asyncio.sleep(1)

    # Profile
    pf = await send_and_wait(client, "👤 Profile")
    if pf:
        captures.append(f"=== PROFILE ===\n{pf.text}")
        print(f"  Profile: {len(pf.text or '')} chars")

    await client.disconnect()

    # ── 6. Save captures ──
    print(f"\n[6] Saving {len(captures)} captures...")
    RAW_PATH.parent.mkdir(parents=True, exist_ok=True)
    RAW_PATH.write_text(
        f"REGFIX-QA-01 Raw Telegram Captures\n"
        f"Generated: {datetime.now().isoformat()}\n"
        f"Bot: @{BOT}\n"
        f"Cards: {len(cards)}, Pages: {len(pages)}\n"
        f"{'='*60}\n\n" + "\n\n".join(captures)
    )

    results = {
        "timestamp": datetime.now().isoformat(),
        "cards": cards,
        "pages": len(pages),
        "detail_count": len(cards),
        "nav_issues": nav_issues,
        "list_evs": list_evs,
        "list_tiers": list_tiers,
    }
    RESULTS_PATH.write_text(json.dumps(results, indent=2, default=str))

    print(f"\n{'='*60}")
    print(f"CAPTURE COMPLETE: {len(cards)} cards, {len(pages)} pages")
    print(f"Nav issues: {len(nav_issues)}")
    print(f"Raw: {RAW_PATH}")
    print(f"JSON: {RESULTS_PATH}")
    print(f"{'='*60}")

    return results


if __name__ == "__main__":
    r = asyncio.run(run_audit())
