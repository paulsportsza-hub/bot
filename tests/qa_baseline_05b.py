"""QA-BASELINE-05b — Telethon E2E Narrative Scoring.

Sends real callbacks to @mzansiedge_bot via Telethon, captures verbatim
bot responses, and saves them for scoring.

Usage:
    cd /home/paulsportsza/bot && .venv/bin/python tests/qa_baseline_05b.py
"""

from __future__ import annotations

import asyncio
import json
import logging
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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("qa_b05b")

BOT_USERNAME = "mzansiedge_bot"
API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "")
SESSION_PATH = Path("data/telethon_qa_session.string")
OUTPUT_PATH = Path("/home/paulsportsza/reports/b05b_captures.json")

BOT_REPLY_TIMEOUT = 20
DETAIL_TIMEOUT = 30  # detail views may need narrative generation


async def _get_last_msg_id(client: TelegramClient) -> int:
    msgs = await client.get_messages(BOT_USERNAME, limit=1)
    return msgs[0].id if msgs else 0


async def send_and_wait(client, text, timeout=BOT_REPLY_TIMEOUT):
    """Send text message, wait for bot reply."""
    last_id = await _get_last_msg_id(client)
    try:
        await client.send_message(BOT_USERNAME, text)
    except FloodWaitError as e:
        log.warning("FloodWait: sleeping %ds", e.seconds)
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


async def wait_for_stable(client, msg_id, timeout=15):
    """Wait for message edits to stabilise (bot edits loading→final)."""
    prev_text = ""
    stable_count = 0
    deadline = time.time() + timeout
    while time.time() < deadline:
        updated = await client.get_messages(BOT_USERNAME, ids=msg_id)
        if updated and updated.text:
            if updated.text == prev_text:
                stable_count += 1
                if stable_count >= 2:
                    return updated
            else:
                prev_text = updated.text
                stable_count = 0
        await asyncio.sleep(2)
    # Return whatever we have
    return await client.get_messages(BOT_USERNAME, ids=msg_id)


async def click_by_data(client, msg, data_prefix, timeout=DETAIL_TIMEOUT):
    """Click inline button by callback_data prefix, return updated/new msg."""
    if not msg or not msg.buttons:
        return None
    for row in msg.buttons:
        for btn in row:
            if hasattr(btn, "data") and btn.data:
                cb = btn.data.decode() if isinstance(btn.data, bytes) else str(btn.data)
                if cb.startswith(data_prefix):
                    old_id = await _get_last_msg_id(client)
                    original_id = msg.id
                    try:
                        await btn.click()
                    except FloodWaitError as e:
                        log.warning("FloodWait on click: %ds", e.seconds)
                        await asyncio.sleep(e.seconds + 2)
                        await btn.click()
                    except Exception as e:
                        log.warning("Click error: %s", e)
                        return None

                    await asyncio.sleep(3)

                    # Check for new message first
                    msgs = await client.get_messages(BOT_USERNAME, limit=5)
                    for m in msgs:
                        if m.id > old_id and not m.out:
                            # Wait for edits to stabilise
                            return await wait_for_stable(client, m.id, timeout=timeout - 3)

                    # Bot edited the original
                    updated = await wait_for_stable(client, original_id, timeout=timeout - 3)
                    if updated:
                        return updated

                    return None
    return None


def extract_buttons(msg):
    """Extract all callback_data strings from message buttons."""
    buttons = []
    if not msg or not msg.buttons:
        return buttons
    for row in msg.buttons:
        for btn in row:
            if hasattr(btn, "data") and btn.data:
                cb = btn.data.decode() if isinstance(btn.data, bytes) else str(btn.data)
                buttons.append({"text": btn.text, "data": cb})
            elif hasattr(btn, "url") and btn.url:
                buttons.append({"text": btn.text, "url": btn.url})
    return buttons


def capture(msg, label=""):
    """Build a capture dict from a Telethon message."""
    if not msg:
        return {"label": label, "text": None, "buttons": [], "error": "no response"}
    return {
        "label": label,
        "text": msg.text or "",
        "raw_text": msg.raw_text or "",
        "buttons": extract_buttons(msg),
        "msg_id": msg.id,
        "timestamp": str(datetime.now()),
    }


async def main():
    if not SESSION_PATH.exists():
        log.error("No Telethon session at %s. Run save_telethon_qa_session.py first.", SESSION_PATH)
        sys.exit(1)

    session_str = SESSION_PATH.read_text().strip()
    client = TelegramClient(StringSession(session_str), API_ID, API_HASH)
    await client.start()
    me = await client.get_me()
    log.info("Connected as %s (@%s)", me.first_name, me.username)

    captures = {
        "run_at": str(datetime.now()),
        "user": me.first_name,
        "hot_tips_pages": [],
        "edge_details": [],
        "my_matches_page": None,
        "yg_game_details": [],
    }

    # ── Step 1: Hot Tips list pages ──────────────────────
    log.info("=" * 60)
    log.info("STEP 1: Sending '💎 Top Edge Picks'")
    tips_msg = await send_and_wait(client, "💎 Top Edge Picks", timeout=DETAIL_TIMEOUT)
    if not tips_msg:
        log.error("No response to Top Edge Picks!")
        captures["hot_tips_pages"].append(capture(None, "page_0"))
    else:
        # Wait for edits to settle (spinner → final)
        tips_msg = await wait_for_stable(client, tips_msg.id, timeout=20)
        page_cap = capture(tips_msg, "page_0")
        captures["hot_tips_pages"].append(page_cap)
        log.info("Page 0 captured: %d chars, %d buttons",
                 len(page_cap["text"]), len(page_cap["buttons"]))

        # Paginate: look for hot:page:N buttons
        page_num = 1
        current_msg = tips_msg
        while True:
            next_data = f"hot:page:{page_num}"
            has_next = any(
                b["data"] == next_data
                for b in extract_buttons(current_msg)
                if "data" in b
            )
            if not has_next:
                break
            log.info("Navigating to page %d", page_num)
            next_msg = await click_by_data(client, current_msg, next_data, timeout=15)
            if not next_msg:
                break
            page_cap = capture(next_msg, f"page_{page_num}")
            captures["hot_tips_pages"].append(page_cap)
            log.info("Page %d captured: %d chars", page_num, len(page_cap["text"]))
            current_msg = next_msg
            page_num += 1
            await asyncio.sleep(1)

    # ── Step 2: edge:detail for each visible tip ─────────
    log.info("=" * 60)
    log.info("STEP 2: Opening edge:detail views")

    # Collect all edge:detail buttons across all pages
    edge_buttons = []
    for page_cap in captures["hot_tips_pages"]:
        for b in page_cap.get("buttons", []):
            if "data" in b and b["data"].startswith("edge:detail:"):
                match_key = b["data"].replace("edge:detail:", "")
                edge_buttons.append({"match_key": match_key, "btn_text": b["text"]})

    log.info("Found %d edge:detail buttons across %d pages",
             len(edge_buttons), len(captures["hot_tips_pages"]))

    # Need to re-navigate to each page to click buttons
    # Re-send Top Edge Picks to get fresh page 0
    if edge_buttons:
        tips_msg = await send_and_wait(client, "💎 Top Edge Picks", timeout=DETAIL_TIMEOUT)
        if tips_msg:
            tips_msg = await wait_for_stable(client, tips_msg.id, timeout=20)

        current_page = 0
        current_msg = tips_msg

        for eb in edge_buttons:
            mk = eb["match_key"]
            detail_data = f"edge:detail:{mk}"
            log.info("  Opening: %s", mk)

            # Check if button is on current page
            page_buttons = [
                b["data"] for b in extract_buttons(current_msg)
                if "data" in b
            ]
            if detail_data not in page_buttons:
                # Try navigating pages to find it
                found = False
                for pg in range(5):
                    pg_data = f"hot:page:{pg}"
                    if pg_data in page_buttons:
                        current_msg = await click_by_data(client, current_msg, pg_data, timeout=15)
                        if current_msg:
                            page_buttons = [
                                b["data"] for b in extract_buttons(current_msg)
                                if "data" in b
                            ]
                            if detail_data in page_buttons:
                                found = True
                                current_page = pg
                                break
                if not found:
                    log.warning("  Could not find button for %s on any page", mk)
                    captures["edge_details"].append({
                        "match_key": mk, "text": None,
                        "error": "button not found on visible pages"
                    })
                    continue

            # Click the detail button
            detail_msg = await click_by_data(client, current_msg, detail_data, timeout=DETAIL_TIMEOUT)
            detail_cap = capture(detail_msg, f"edge_detail_{mk}")
            detail_cap["match_key"] = mk
            captures["edge_details"].append(detail_cap)

            if detail_msg and detail_msg.text:
                log.info("  Captured: %d chars", len(detail_msg.text))
            else:
                log.warning("  No response for %s", mk)

            await asyncio.sleep(2)

            # Navigate back to tips list
            if detail_msg:
                back_btn = None
                for b in extract_buttons(detail_msg):
                    if "data" in b and b["data"].startswith("hot:back"):
                        back_btn = b["data"]
                        break
                if back_btn:
                    current_msg = await click_by_data(client, detail_msg, back_btn, timeout=15)
                    if not current_msg:
                        # Re-send picks to reset
                        current_msg = await send_and_wait(client, "💎 Top Edge Picks", timeout=DETAIL_TIMEOUT)
                        if current_msg:
                            current_msg = await wait_for_stable(client, current_msg.id, timeout=15)
                else:
                    # No back button - re-send picks
                    current_msg = await send_and_wait(client, "💎 Top Edge Picks", timeout=DETAIL_TIMEOUT)
                    if current_msg:
                        current_msg = await wait_for_stable(client, current_msg.id, timeout=15)

    # ── Step 3: My Matches + yg:game detail views ────────
    log.info("=" * 60)
    log.info("STEP 3: Sending '⚽ My Matches'")
    mm_msg = await send_and_wait(client, "⚽ My Matches", timeout=DETAIL_TIMEOUT)
    if mm_msg:
        mm_msg = await wait_for_stable(client, mm_msg.id, timeout=20)
    captures["my_matches_page"] = capture(mm_msg, "my_matches")

    # Click up to 5 yg:game: buttons
    if mm_msg:
        yg_buttons = [
            b for b in extract_buttons(mm_msg)
            if "data" in b and b["data"].startswith("yg:game:")
        ]
        log.info("Found %d yg:game buttons", len(yg_buttons))

        for yb in yg_buttons[:5]:
            event_id = yb["data"].replace("yg:game:", "")
            log.info("  Opening yg:game: %s", event_id)

            game_msg = await click_by_data(client, mm_msg, yb["data"], timeout=DETAIL_TIMEOUT)
            game_cap = capture(game_msg, f"yg_game_{event_id}")
            game_cap["event_id"] = event_id
            captures["yg_game_details"].append(game_cap)

            if game_msg and game_msg.text:
                log.info("  Captured: %d chars", len(game_msg.text))
            else:
                log.warning("  No response for yg:game:%s", event_id)

            await asyncio.sleep(2)

            # Back to My Matches
            if game_msg:
                back_msg = await click_by_data(client, game_msg, "yg:all:", timeout=15)
                if back_msg:
                    mm_msg = back_msg
                else:
                    mm_msg = await send_and_wait(client, "⚽ My Matches", timeout=DETAIL_TIMEOUT)
                    if mm_msg:
                        mm_msg = await wait_for_stable(client, mm_msg.id, timeout=15)

    # ── Save captures ────────────────────────────────────
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(captures, indent=2, ensure_ascii=False))
    log.info("=" * 60)
    log.info("Captures saved to %s", OUTPUT_PATH)
    log.info("Hot Tips pages: %d", len(captures["hot_tips_pages"]))
    log.info("Edge details: %d", len(captures["edge_details"]))
    log.info("YG game details: %d", len(captures["yg_game_details"]))

    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
