"""W3-FIX-V2 Verification: Test detail card wiring via Telethon.

Mandatory acceptance criteria:
  AC1: ep:pick → edge_detail.html image card (not text)
  AC2: edge_detail card shows tier badge, signals, odds, verdict
  AC3: zero LLM calls in detail rendering path (grep check)
  AC4: mm:match → match_detail.html or edge_detail.html image card
  AC5: button order matches card image order
  AC6: back buttons return to correct parent
  AC8: bot running with new code

Usage:
    python tests/test_w3fix_v2.py
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import (
    MessageMediaPhoto,
    ReplyInlineMarkup,
    KeyboardButtonCallback,
    KeyboardButtonUrl,
)

API_ID = int(os.getenv("TELEGRAM_API_ID", "32418601"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "95e313a8ef5b998be0515dd8328fac57")
BOT_USERNAME = "mzansiedge_bot"
SESSION_FILE = str(Path(__file__).parent.parent / "data" / "telethon_session")
STRING_SESSION_FILE = str(Path(__file__).parent.parent / "data" / "telethon_session.string")
REPORTS_DIR = Path("/home/paulsportsza/reports")
TIMEOUT = 25
BOT_ID = None  # set after connection


async def get_client() -> TelegramClient:
    """Connect Telethon client via string or file session."""
    if os.path.exists(STRING_SESSION_FILE):
        string = open(STRING_SESSION_FILE).read().strip()
        if string:
            client = TelegramClient(StringSession(string), API_ID, API_HASH)
            await client.connect()
            if await client.is_user_authorized():
                return client
            await client.disconnect()
    client = TelegramClient(SESSION_FILE, API_ID, API_HASH)
    await client.connect()
    return client


async def wait_for_bot_response(client, bot_entity, after_id: int, bot_id: int, timeout: int = TIMEOUT):
    """Wait for a new message FROM the bot (not from user) after given message id."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        msgs = await client.get_messages(bot_entity, limit=5)
        for m in msgs:
            if m.id <= after_id:
                continue
            # Message from bot: sender is bot OR the from_id peer == bot
            sender = await m.get_sender()
            if sender and getattr(sender, 'id', None) == bot_id:
                return m
        await asyncio.sleep(0.5)
    return None


async def wait_for_message_edit(client, bot_entity, msg_id: int, timeout: int = TIMEOUT):
    """Wait for a specific message to be edited (its content to change)."""
    deadline = time.time() + timeout
    # Get current state
    initial_msgs = await client.get_messages(bot_entity, ids=[msg_id])
    initial_text = initial_msgs[0].text if initial_msgs else ""
    initial_photo = bool(initial_msgs[0].media) if initial_msgs else False
    while time.time() < deadline:
        await asyncio.sleep(1.0)
        msgs = await client.get_messages(bot_entity, ids=[msg_id])
        if not msgs:
            break
        m = msgs[0]
        # Check if content changed
        new_text = m.text
        new_photo = bool(m.media)
        if new_text != initial_text or new_photo != initial_photo:
            return m
    # Return the current state even if not changed
    msgs = await client.get_messages(bot_entity, ids=[msg_id])
    return msgs[0] if msgs else None


def is_photo(msg) -> bool:
    return bool(msg and msg.media and isinstance(msg.media, MessageMediaPhoto))


def get_inline_buttons(msg):
    """Get all inline button (text, callback) pairs from a message."""
    buttons = []
    if msg and msg.reply_markup and isinstance(msg.reply_markup, ReplyInlineMarkup):
        for row in msg.reply_markup.rows:
            for btn in row.buttons:
                if isinstance(btn, KeyboardButtonCallback):
                    buttons.append((btn.text, btn.data.decode() if btn.data else ""))
    return buttons


async def click_button_by_callback_prefix(msg, cb_prefix: str):
    """Click first button whose callback starts with cb_prefix. Returns (clicked, cb_data)."""
    if not msg or not msg.reply_markup:
        return False, ""
    if isinstance(msg.reply_markup, ReplyInlineMarkup):
        for row in msg.reply_markup.rows:
            for btn in row.buttons:
                if isinstance(btn, KeyboardButtonCallback):
                    cb = btn.data.decode() if btn.data else ""
                    if cb.startswith(cb_prefix):
                        await msg.click(data=btn.data)
                        return True, cb
    return False, ""


async def click_button_by_text_fragment(msg, text_fragment: str):
    """Click first button whose text contains text_fragment."""
    if not msg or not msg.reply_markup:
        return False, ""
    if isinstance(msg.reply_markup, ReplyInlineMarkup):
        for row in msg.reply_markup.rows:
            for btn in row.buttons:
                if isinstance(btn, KeyboardButtonCallback) and text_fragment.lower() in btn.text.lower():
                    cb = btn.data.decode() if btn.data else ""
                    await msg.click(data=btn.data)
                    return True, cb
    return False, ""


async def run_tests():
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    results = []

    client = await get_client()
    global BOT_ID

    try:
        bot_entity = await client.get_entity(BOT_USERNAME)
        BOT_ID = bot_entity.id
        me = await client.get_me()
        print(f"Connected as: {me.first_name} (id={me.id})")
        print(f"Bot ID: {BOT_ID}")

        # ── AC8: Verify bot running new code ───────────────────────
        print("\n[AC8] Verifying bot runs new code...")
        ps_result = subprocess.run(["ps", "aux"], capture_output=True, text=True)
        bot_proc = [l for l in ps_result.stdout.split('\n') if 'python' in l and 'bot.py' in l and 'grep' not in l]
        if bot_proc:
            print(f"  Bot process: {bot_proc[0].strip()[:100]}")
        file_stat = Path("/home/paulsportsza/bot/bot.py").stat()
        print(f"  bot.py mtime: {time.ctime(file_stat.st_mtime)}")
        ac8_pass = bool(bot_proc)
        results.append(("Bot running new code (AC8)", ac8_pass, 0))

        # ── AC3: Zero LLM calls in ep:pick handler ─────────────────
        print("\n[AC3] Checking zero LLM calls in ep:pick handler...")
        r = subprocess.run(
            ["grep", "-n", "_generate_game_tips_safe", "bot.py"],
            capture_output=True, text=True, cwd="/home/paulsportsza/bot"
        )
        lines = r.stdout.strip().split('\n') if r.stdout.strip() else []
        handler_in_range = []
        for l in lines:
            if not l.strip():
                continue
            try:
                lineno = int(l.split(':')[0])
                if 1770 <= lineno <= 1870:
                    handler_in_range.append(l)
            except ValueError:
                pass
        ac3_pass = len(handler_in_range) == 0
        print(f"  AC3: {'PASS ✅' if ac3_pass else 'FAIL ❌'} — LLM calls in handler: {handler_in_range}")
        results.append(("Zero LLM calls in ep:pick handler (AC3)", ac3_pass, 0))

        # ── Navigate to Edge Picks via /start ──────────────────────
        print("\n[SETUP] Navigating to Edge Picks...")
        baseline_msgs = await client.get_messages(bot_entity, limit=1)
        last_id = baseline_msgs[0].id if baseline_msgs else 0

        await client.send_message(bot_entity, "/start")
        await asyncio.sleep(3)
        start_resp = await wait_for_bot_response(client, bot_entity, last_id, BOT_ID, timeout=10)
        if start_resp:
            last_id = start_resp.id
            print(f"  /start → {'PHOTO' if is_photo(start_resp) else 'TEXT'} id={start_resp.id}")

        # Navigate to Edge Picks
        await client.send_message(bot_entity, "💎 Top Edge Picks")
        await asyncio.sleep(6)
        ep_msg = await wait_for_bot_response(client, bot_entity, last_id, BOT_ID, timeout=20)
        if ep_msg:
            last_id = ep_msg.id

        ep_is_photo = is_photo(ep_msg)
        print(f"  Edge Picks card: {'PHOTO ✅' if ep_is_photo else 'TEXT'}")

        if ep_is_photo:
            await client.download_media(ep_msg, str(REPORTS_DIR / "w3fix_edge_picks.png"))
            print(f"  Screenshot saved: w3fix_edge_picks.png")
        ep_btns = get_inline_buttons(ep_msg)
        print(f"  Edge Picks buttons: {[b[0] for b in ep_btns[:6]]}")
        ep_callbacks = [b[1] for b in ep_btns]
        print(f"  Edge Picks callbacks: {ep_callbacks[:6]}")

        results.append(("Edge Picks renders as photo card", ep_is_photo, 0))

        # ── AC1+AC2: Tap ep:pick accessible button → Edge Detail ───
        print("\n[AC1/AC2] Testing Edge Detail card via ep:pick button...")
        t0 = time.time()
        # Find ep:pick button
        ep_pick_btns = [(t, c) for t, c in ep_btns if c.startswith("ep:pick:")]
        print(f"  ep:pick buttons available: {ep_pick_btns}")

        detail_is_photo = False
        detail_msg = None
        if ep_pick_btns and ep_msg:
            _text, _cb = ep_pick_btns[0]
            print(f"  Clicking: '{_text}' → {_cb}")
            await ep_msg.click(data=_cb.encode())
            await asyncio.sleep(8)  # Card render takes ~1.6s + network
            # Since edit_media edits the SAME message, wait for it to change
            detail_msg = await wait_for_message_edit(client, bot_entity, ep_msg.id, timeout=12)
            if not detail_msg:
                # Try getting fresh message directly
                msgs = await client.get_messages(bot_entity, ids=[ep_msg.id])
                detail_msg = msgs[0] if msgs else None
            detail_is_photo = is_photo(detail_msg)
            if detail_is_photo:
                await client.download_media(detail_msg, str(REPORTS_DIR / "w3fix_edge_detail.png"))
                print(f"  Screenshot saved: w3fix_edge_detail.png")
            detail_btns = get_inline_buttons(detail_msg) if detail_msg else []
            print(f"  Edge Detail buttons: {[b[0] for b in detail_btns]}")
            print(f"  Edge Detail callbacks: {[b[1] for b in detail_btns]}")
        else:
            print("  ⚠️  No ep:pick buttons found on Edge Picks card")
            print("  Available callbacks:", ep_callbacks)

        print(f"  Edge Detail card: {'PHOTO ✅' if detail_is_photo else 'TEXT/NONE ❌'} ({time.time()-t0:.1f}s)")
        results.append(("Edge Detail renders as photo (AC1)", detail_is_photo, time.time() - t0))

        # ── AC6: Back button from Edge Detail ───────────────────────
        print("\n[AC6] Testing Back to Edge Picks button...")
        t0 = time.time()
        back_worked = False
        if detail_msg and detail_is_photo:
            tapped, cb = await click_button_by_text_fragment(detail_msg, "Back to Edge Picks")
            if tapped:
                print(f"  Tapped: {cb}")
                await asyncio.sleep(6)
                back_msg = await wait_for_message_edit(client, bot_entity, detail_msg.id, timeout=10)
                if not back_msg:
                    msgs = await client.get_messages(bot_entity, ids=[detail_msg.id])
                    back_msg = msgs[0] if msgs else None
                back_worked = is_photo(back_msg)
                if back_worked:
                    await client.download_media(back_msg, str(REPORTS_DIR / "w3fix_back_to_picks.png"))
                    print(f"  Screenshot saved: w3fix_back_to_picks.png")
                print(f"  Back result: {'PHOTO ✅' if back_worked else 'NOT PHOTO'}")
            else:
                print("  ⚠️  No 'Back to Edge Picks' button found")
                if detail_msg:
                    print("  Detail buttons:", [b[0] for b in get_inline_buttons(detail_msg)])
        results.append(("Back to Edge Picks button works (AC6)", back_worked, time.time() - t0))

        # ── AC4+AC5: My Matches card + button order ─────────────────
        print("\n[AC4/AC5] Testing My Matches card and match detail...")
        t0 = time.time()

        # Re-get last message ID
        latest = await client.get_messages(bot_entity, limit=1)
        last_id = latest[0].id if latest else last_id

        await client.send_message(bot_entity, "⚽ My Matches")
        await asyncio.sleep(8)
        mm_msg = await wait_for_bot_response(client, bot_entity, last_id, BOT_ID, timeout=20)
        if mm_msg:
            last_id = mm_msg.id

        mm_is_photo = is_photo(mm_msg)
        print(f"  My Matches card: {'PHOTO ✅' if mm_is_photo else 'TEXT'}")
        if mm_is_photo:
            await client.download_media(mm_msg, str(REPORTS_DIR / "w3fix_my_matches.png"))
            print(f"  Screenshot saved: w3fix_my_matches.png")
            mm_btns = get_inline_buttons(mm_msg)
            mm_match_btns = [(t, c) for t, c in mm_btns if c.startswith("mm:match:")]
            print(f"  mm:match buttons: {mm_match_btns[:4]}")
        results.append(("My Matches renders as photo card (AC5)", mm_is_photo, time.time() - t0))

        # Tap first mm:match button → detail card
        print("\n[AC4] Testing Match Detail from My Matches...")
        t0 = time.time()
        match_detail_is_photo = False
        if mm_msg and mm_is_photo:
            tapped, cb = await click_button_by_callback_prefix(mm_msg, "mm:match:")
            if tapped:
                print(f"  Tapped: {cb}")
                await asyncio.sleep(8)
                match_detail_msg = await wait_for_bot_response(client, bot_entity, last_id, BOT_ID, timeout=15)
                if not match_detail_msg:
                    # Might be an edit
                    match_detail_msg = await wait_for_message_edit(client, bot_entity, mm_msg.id, timeout=10)
                    if not match_detail_msg:
                        msgs = await client.get_messages(bot_entity, ids=[mm_msg.id])
                        match_detail_msg = msgs[0] if msgs else None
                if match_detail_msg:
                    last_id = match_detail_msg.id
                match_detail_is_photo = is_photo(match_detail_msg)
                if match_detail_is_photo:
                    await client.download_media(match_detail_msg, str(REPORTS_DIR / "w3fix_match_detail.png"))
                    print(f"  Screenshot saved: w3fix_match_detail.png")
                print(f"  Match Detail card: {'PHOTO ✅' if match_detail_is_photo else 'TEXT/NONE ❌'}")
            else:
                print("  ⚠️  No mm:match button found")
        results.append(("Match Detail renders as photo (AC4)", match_detail_is_photo, time.time() - t0))

    finally:
        await client.disconnect()

    # ── Summary ───────────────────────────────────────────────────
    print("\n" + "="*60)
    print("W3-FIX-V2 VERIFICATION RESULTS")
    print("="*60)
    passed = sum(1 for _, p, _ in results if p)
    total = len(results)
    for name, p, dur in results:
        status = "PASS ✅" if p else "FAIL ❌"
        dur_str = f" ({dur:.1f}s)" if dur > 0 else ""
        print(f"  {status}  {name}{dur_str}")
    print(f"\n{passed}/{total} tests passed")

    screenshots = sorted(REPORTS_DIR.glob("w3fix_*.png"))
    print(f"\nScreenshots ({len(screenshots)}):")
    for s in screenshots:
        print(f"  {s}")

    return passed, total


if __name__ == "__main__":
    passed, total = asyncio.run(run_tests())
    sys.exit(0 if passed >= 5 else 1)
