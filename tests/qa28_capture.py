"""QA-28: Narrative capture via Telethon.

Navigates to Top Edge Picks via hot:go callback, then captures all cards.

Usage:
    .venv/bin/python tests/qa28_capture.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import BOT_ROOT
from dotenv import load_dotenv
load_dotenv()

from telethon import TelegramClient
from telethon.errors import FloodWaitError, DataInvalidError
from telethon.sessions import StringSession
from telethon.tl.custom.message import Message

BOT_USERNAME = "mzansiedge_bot"
API_ID = int(os.environ.get("TELEGRAM_API_ID", "0"))
API_HASH = os.environ.get("TELEGRAM_API_HASH", "")
SESSION_PATH = Path("data/telethon_session.string")
REPORT_PATH = BOT_ROOT.parent / "reports" / "qa28-captures.json"
REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)

BANNED_MARKERS = [
    "MATCH_DATA_UNAVAILABLE", "TEMPLATE_FALLBACK", "Unable to generate",
    "ESPN data unavailable", "Data not available", "[TEAM_A]", "[TEAM_B]",
]


async def get_client() -> TelegramClient:
    string = SESSION_PATH.read_text().strip()
    client = TelegramClient(StringSession(string), API_ID, API_HASH)
    await client.connect()
    if not await client.is_user_authorized():
        print("ERROR: Telethon session not authorized.")
        sys.exit(1)
    return client


async def latest_bot_msg(client: TelegramClient) -> Message | None:
    msgs = await client.get_messages(BOT_USERNAME, limit=5)
    for m in msgs:
        if not m.out:
            return m
    return None


async def wait_new_msg(client: TelegramClient, after_id: int, timeout: int = 20) -> Message | None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        msgs = await client.get_messages(BOT_USERNAME, limit=5)
        for m in msgs:
            if m.id > after_id and not m.out:
                return m
        await asyncio.sleep(1)
    return None


async def wait_edit(client: TelegramClient, msg_id: int, prev_text: str, timeout: int = 15) -> Message | None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        updated = await client.get_messages(BOT_USERNAME, ids=msg_id)
        if updated:
            txt = updated.text or ""
            if txt != prev_text and len(txt) > 30:
                return updated
        await asyncio.sleep(1)
    return None


async def send_cmd(client: TelegramClient, text: str, wait: float = 3.0) -> None:
    try:
        await client.send_message(BOT_USERNAME, text)
    except FloodWaitError as e:
        await asyncio.sleep(e.seconds + 2)
        await client.send_message(BOT_USERNAME, text)
    await asyncio.sleep(wait)


async def click_cb(client: TelegramClient, msg: Message, cb: str, timeout: int = 30) -> Message | None:
    """Click inline button with exact callback data."""
    if not msg or not msg.buttons:
        return None
    target = None
    for row in msg.buttons:
        for btn in row:
            bdata = (btn.data or b"").decode("utf-8", errors="ignore") if btn.data else ""
            if bdata == cb:
                target = btn
                break
        if target:
            break
    if not target:
        print(f"    [click_cb] not found: {cb!r}")
        print(f"    Available: {[((b.data or b'').decode('utf-8','ignore') if b.data else '') for row in (msg.buttons or []) for b in row]}")
        return None

    last_id = await (async_last_id := client.get_messages(BOT_USERNAME, limit=1))
    last_id = (await client.get_messages(BOT_USERNAME, limit=1))[0].id if True else 0
    msgs_before = set()
    recent = await client.get_messages(BOT_USERNAME, limit=5)
    for m in recent:
        if not m.out:
            msgs_before.add(m.id)
    prev_text = msg.text or ""

    try:
        await target.click()
    except DataInvalidError:
        print(f"    DataInvalidError: {cb!r}")
        return None
    except FloodWaitError as e:
        await asyncio.sleep(e.seconds + 2)
        try:
            await target.click()
        except DataInvalidError:
            return None

    await asyncio.sleep(3)
    deadline = time.time() + timeout
    while time.time() < deadline:
        msgs = await client.get_messages(BOT_USERNAME, limit=5)
        for m in msgs:
            if not m.out and m.id not in msgs_before:
                return m
        updated = await client.get_messages(BOT_USERNAME, ids=msg.id)
        if updated and updated.id == msg.id:
            new_txt = updated.text or ""
            if new_txt != prev_text and len(new_txt) > 30:
                return updated
        await asyncio.sleep(1)
    return await latest_bot_msg(client)


def get_btns(msg: Message) -> list[dict]:
    if not msg or not msg.buttons:
        return []
    result = []
    for row in msg.buttons:
        for btn in row:
            cd = (btn.data or b"").decode("utf-8", errors="ignore") if btn.data else ""
            result.append({"text": btn.text or "", "data": cd})
    return result


def edge_card_btns(msg: Message) -> list[tuple[str, str]]:
    """Return (text, data) for edge card detail buttons."""
    result = []
    for b in get_btns(msg):
        cd = b["data"]
        # Hot tips cards use edge:detail:match_key
        if cd.startswith("edge:detail:"):
            result.append((b["text"], cd))
    return result


def match_key_from(cb: str) -> str:
    parts = cb.split(":", 2)
    return parts[2] if len(parts) >= 3 else cb


def next_page_btn(msg: Message) -> str | None:
    for b in get_btns(msg):
        if "next" in b["text"].lower() or b["data"].startswith("hot:page:"):
            return b["data"]
    return None


async def get_hot_tips_msg(client: TelegramClient) -> Message | None:
    """Navigate to Hot Tips. Returns the list message or None."""
    last_id_before = (await client.get_messages(BOT_USERNAME, limit=1))[0].id

    # Strategy 1: Send keyboard button text "💎 Top Edge Picks"
    await send_cmd(client, "💎 Top Edge Picks", wait=4)
    msgs = await client.get_messages(BOT_USERNAME, limit=3)
    for m in msgs:
        if not m.out and m.id > last_id_before:
            txt = m.text or ""
            print(f"  Response: {txt[:100]}")
            if "Edge Picks" in txt or "Edge Found" in txt or "edge" in txt.lower():
                # Check if it's hot tips (not my_matches)
                btns_list = get_btns(m)
                edge_cards = [b for b in btns_list if b["data"].startswith("edge:detail:")]
                hot_go = [b for b in btns_list if b["data"] == "hot:go"]
                if edge_cards:
                    print(f"  Got Hot Tips with {len(edge_cards)} edge cards!")
                    return m
                elif hot_go:
                    # It's My Matches — click "hot:go" inline button
                    print(f"  Got My Matches. Clicking hot:go...")
                    hot_msg = await click_cb(client, m, "hot:go", timeout=25)
                    if hot_msg:
                        txt2 = hot_msg.text or ""
                        print(f"  After hot:go: {txt2[:100]}")
                        return hot_msg
            # Fall through to check for inline hot:go btn
            btns_list = get_btns(m)
            for b in btns_list:
                if b["data"] == "hot:go":
                    print(f"  Clicking hot:go from {b['text']!r}...")
                    hot_msg = await click_cb(client, m, "hot:go", timeout=25)
                    if hot_msg:
                        return hot_msg
            # Return whatever we got
            if m.text and len(m.text) > 30:
                return m

    # Strategy 2: /start then click hot:go
    last_id2 = (await client.get_messages(BOT_USERNAME, limit=1))[0].id
    await send_cmd(client, "/start", wait=4)
    start = await wait_new_msg(client, last_id2, timeout=15)
    if start:
        print(f"  /start response: {(start.text or '')[:80]}")
        # Look for hot:go in start or any recent message
        for b in get_btns(start):
            if b["data"] == "hot:go":
                hot = await click_cb(client, start, "hot:go", timeout=25)
                if hot:
                    return hot

    return None


async def main():
    client = await get_client()
    print(f"Connected. QA-28 Telethon capture from @{BOT_USERNAME}")

    all_cards = []
    transport_errors = []
    visited_keys = set()

    print("\n[1] Navigating to Top Edge Picks (Hot Tips)...")
    list_msg = await get_hot_tips_msg(client)
    if not list_msg:
        print("FATAL: Cannot reach Hot Tips")
        await client.disconnect()
        return all_cards, ["Cannot reach Hot Tips"]

    print(f"\n  Hot Tips page: {(list_msg.text or '')[:200]}")
    print(f"  Buttons: {[b['text'][:25] for b in get_btns(list_msg)]}")

    # Process cards page by page
    page = 0
    max_pages = 5
    while page < max_pages:
        page += 1
        card_list = edge_card_btns(list_msg)
        all_btns = get_btns(list_msg)
        print(f"\n[Page {page}] MsgID={list_msg.id}")
        print(f"  All buttons: {[b['text'][:25] for b in all_btns]}")
        print(f"  Edge card buttons ({len(card_list)}): {[(t[:20], d[:40]) for t,d in card_list]}")

        if not card_list:
            print(f"  No edge:detail cards found on page {page}.")
            # Maybe these are my_matches type buttons
            non_edge = [(b['text'][:25], b['data'][:40]) for b in all_btns
                        if b['data'] and 'back' not in b['data'] and 'menu' not in b['data'].lower()
                        and b['data'] not in ('hot:go', '') and not b['data'].startswith('hot:page:')
                        and not b['data'].startswith('edge:page:')]
            print(f"  Non-edge buttons: {non_edge}")

        for card_text, card_cb in card_list:
            mk = match_key_from(card_cb)
            if mk in visited_keys:
                continue
            visited_keys.add(mk)

            cn = len(all_cards) + 1
            print(f"\n  Card {cn}: {mk}")
            print(f"    btn={card_text!r} cb={card_cb!r}")

            detail = await click_cb(client, list_msg, card_cb, timeout=35)

            if not detail or len(detail.text or "") < 30:
                print(f"    ERROR: no detail. detail={detail}")
                transport_errors.append(f"No detail for {mk}")
                all_cards.append({
                    "card_num": cn, "match_key": mk, "btn_text": card_text,
                    "btn_data": card_cb, "detail_text": "",
                    "detail_buttons": [], "banned_markers": [], "text_len": 0,
                    "error": "No detail captured",
                    "captured_at": datetime.now(timezone.utc).isoformat(),
                })
                # Re-navigate to hot tips
                list_msg = await get_hot_tips_msg(client)
                if not list_msg:
                    await client.disconnect()
                    return all_cards, transport_errors
                # Skip to current page
                for _ in range(page - 1):
                    npb = next_page_btn(list_msg)
                    if npb:
                        list_msg = await click_cb(client, list_msg, npb, timeout=15) or list_msg
                break  # Restart page processing
            
            dtext = detail.text or ""
            dbtns = get_btns(detail)
            banned = [m for m in BANNED_MARKERS if m in dtext]
            print(f"    Captured {len(dtext)} chars. Banned: {banned or 'none'}")
            print(f"    Snippet:\n{dtext[:300]}")
            print(f"    Detail btns: {[(b['text'][:20], b['data'][:30]) for b in dbtns]}")

            all_cards.append({
                "card_num": cn, "match_key": mk, "btn_text": card_text,
                "btn_data": card_cb, "detail_text": dtext,
                "detail_buttons": [{"text": b["text"], "data": b["data"]} for b in dbtns],
                "banned_markers": banned, "text_len": len(dtext),
                "captured_at": datetime.now(timezone.utc).isoformat(),
            })

            # Go back
            back_cb = None
            for b in dbtns:
                if any(kw in b["data"] for kw in ["hot:back", "back"]) or \
                   any(kw in b["text"].lower() for kw in ["↩️", "back", "picks"]):
                    back_cb = b["data"]
                    break
            if back_cb:
                returned = await click_cb(client, detail, back_cb, timeout=20)
                if returned and len(returned.text or "") > 30:
                    list_msg = returned
                    print(f"    Back to list OK. Buttons: {[b['text'][:20] for b in get_btns(list_msg)]}")
                else:
                    print(f"    Back failed. Re-navigating...")
                    list_msg = await get_hot_tips_msg(client)
                    if not list_msg:
                        await client.disconnect()
                        return all_cards, transport_errors
                    for _ in range(page - 1):
                        npb = next_page_btn(list_msg)
                        if npb:
                            list_msg = await click_cb(client, list_msg, npb, timeout=15) or list_msg
            else:
                print(f"    No back btn. Re-navigating...")
                await asyncio.sleep(2)
                list_msg = await get_hot_tips_msg(client)
                if not list_msg:
                    await client.disconnect()
                    return all_cards, transport_errors
                for _ in range(page - 1):
                    npb = next_page_btn(list_msg)
                    if npb:
                        list_msg = await click_cb(client, list_msg, npb, timeout=15) or list_msg

        # Next page?
        npb = next_page_btn(list_msg)
        if not npb:
            print(f"\n  No next page. Done — {len(all_cards)} cards.")
            break
        prev_txt = list_msg.text or ""
        print(f"\n  Next page: {npb}")
        next_list = await click_cb(client, list_msg, npb, timeout=20)
        if not next_list or (next_list.text or "") == prev_txt:
            print("  Next page same/failed. Done.")
            break
        list_msg = next_list

    await client.disconnect()
    return all_cards, transport_errors


if __name__ == "__main__":
    cards, errors = asyncio.run(main())
    print(f"\n{'='*60}")
    print(f"CAPTURE: {len(cards)} cards, {len(errors)} transport errors")
    for e in errors:
        print(f"  - {e}")

    report = {
        "qa_id": "QA-28",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "total_cards": len(cards),
        "cards_with_content": sum(1 for c in cards if c.get("text_len", 0) > 100),
        "transport_errors": errors,
        "cards": cards,
    }
    with open(REPORT_PATH, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nSaved to: {REPORT_PATH}")
