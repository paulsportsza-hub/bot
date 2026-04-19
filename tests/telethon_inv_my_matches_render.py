"""INV-MY-MATCHES-RENDER-02 — Telethon E2E investigation.

Tests the My Matches rendering path to identify the morning digest regression.
Simulates:
1. yg:all:0 inline button press (normal My Matches tap)
2. /schedule command (legacy CMD path)
3. Reply keyboard "⚽ My Matches" tap
Captures verbatim output and checks for morning digest strings.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import (
    ReplyInlineMarkup,
    KeyboardButtonCallback,
    MessageMediaPhoto,
)

API_ID = int(os.getenv("TELEGRAM_API_ID", "32418601"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "95e313a8ef5b998be0515dd8328fac57")
BOT_USERNAME = "mzansiedge_bot"
SESSION_FILE = str(ROOT / "data" / "telethon_session")
STRING_SESSION_FILE = str(ROOT / "data" / "telethon_session.string")
TIMEOUT = 15


async def get_client() -> TelegramClient:
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
    if not await client.is_user_authorized():
        print("ERROR: Not logged in. Run save_telegram_session.py first.")
        sys.exit(1)
    return client


def msg_summary(msg) -> str:
    """Return a short summary of a message for logging."""
    is_photo = isinstance(msg.media, MessageMediaPhoto)
    text = (msg.message or msg.text or "")[:200]
    caption = (msg.message or "")[:200] if is_photo else ""
    btns = []
    if msg.reply_markup and isinstance(msg.reply_markup, ReplyInlineMarkup):
        for row in msg.reply_markup.rows:
            for btn in row.buttons:
                btns.append(getattr(btn, "text", ""))
    return f"[{'PHOTO' if is_photo else 'TEXT'}] text={repr(text[:80])} caption={repr(caption[:80])} buttons={btns}"


async def click_callback(client: TelegramClient, entity, msg, callback_data: bytes, wait: float = TIMEOUT):
    """Click an inline button by raw callback data."""
    await client.request(
        __import__("telethon").functions.messages.GetBotCallbackAnswerRequest(
            peer=entity,
            msg_id=msg.id,
            data=callback_data,
        )
    )
    await asyncio.sleep(wait)
    messages = await client.get_messages(entity, limit=5)
    return list(reversed(messages))


async def run_test(client: TelegramClient) -> dict:
    entity = await client.get_entity(BOT_USERNAME)
    results = {}

    # ── Test 1: /schedule command ─────────────────────────────────
    print("\n[T1] Sending /schedule command...")
    t0 = time.time()
    sent = await client.send_message(entity, "/schedule")
    await asyncio.sleep(TIMEOUT)
    msgs = await client.get_messages(entity, limit=10)
    recent = [m for m in msgs if m.id > sent.id]
    recent = list(reversed(recent))
    elapsed = time.time() - t0
    print(f"  Got {len(recent)} message(s) in {elapsed:.1f}s")
    for m in recent:
        print(f"  {msg_summary(m)}")

    # Check for morning digest strings
    t1_morning_digest = False
    t1_photo = False
    t1_my_matches_header = False
    for m in recent:
        text = (m.message or m.text or "")
        if "MORNING DIGEST" in text or "TODAY'S EDGE PICKS" in text:
            t1_morning_digest = True
        if isinstance(m.media, MessageMediaPhoto):
            t1_photo = True
        if "My Matches" in text or "my matches" in text.lower():
            t1_my_matches_header = True

    results["test1_schedule_command"] = {
        "messages": len(recent),
        "elapsed": round(elapsed, 1),
        "has_photo": t1_photo,
        "morning_digest_in_text": t1_morning_digest,
        "my_matches_in_text": t1_my_matches_header,
        "summaries": [msg_summary(m) for m in recent],
        "pass": not t1_morning_digest,
    }

    # ── Test 2: Tap yg:all:0 inline button from /menu ────────────
    print("\n[T2] Getting /menu to find inline My Matches button...")
    sent2 = await client.send_message(entity, "/menu")
    await asyncio.sleep(8)
    msgs2 = await client.get_messages(entity, limit=5)
    menu_msgs = [m for m in msgs2 if m.id > sent2.id and m.reply_markup]
    menu_msg = menu_msgs[0] if menu_msgs else None

    if menu_msg:
        print(f"  Menu message: {msg_summary(menu_msg)}")
        # Find and click "My Matches" button
        if menu_msg.reply_markup and isinstance(menu_msg.reply_markup, ReplyInlineMarkup):
            for row in menu_msg.reply_markup.rows:
                for btn in row.buttons:
                    if isinstance(btn, KeyboardButtonCallback) and "My Matches" in btn.text:
                        print(f"  Clicking button: {btn.text!r} (data={btn.data})")
                        t0 = time.time()
                        try:
                            await menu_msg.click(data=btn.data)
                        except Exception as e:
                            print(f"  Click result: {e}")
                        await asyncio.sleep(TIMEOUT)
                        msgs_after = await client.get_messages(entity, limit=10)
                        recent2 = [m for m in msgs_after if m.id >= menu_msg.id]
                        recent2 = list(reversed(recent2))
                        elapsed = time.time() - t0
                        print(f"  Got {len(recent2)} message(s) in {elapsed:.1f}s")
                        for m in recent2:
                            print(f"  {msg_summary(m)}")

                        t2_morning_digest = any(
                            "MORNING DIGEST" in (m.message or m.text or "")
                            or "TODAY'S EDGE PICKS" in (m.message or m.text or "")
                            for m in recent2
                        )
                        t2_photo = any(isinstance(m.media, MessageMediaPhoto) for m in recent2)
                        results["test2_yg_inline_button"] = {
                            "elapsed": round(elapsed, 1),
                            "has_photo": t2_photo,
                            "morning_digest_in_text": t2_morning_digest,
                            "summaries": [msg_summary(m) for m in recent2[:3]],
                            "pass": not t2_morning_digest,
                        }
                        break
    else:
        print("  No menu message found")
        results["test2_yg_inline_button"] = {"pass": False, "error": "no menu msg"}

    # ── Test 3: Reply keyboard "⚽ My Matches" ────────────────────
    print("\n[T3] Sending '⚽ My Matches' reply keyboard text...")
    t0 = time.time()
    sent3 = await client.send_message(entity, "⚽ My Matches")
    await asyncio.sleep(TIMEOUT)
    msgs3 = await client.get_messages(entity, limit=10)
    recent3 = [m for m in msgs3 if m.id > sent3.id]
    recent3 = list(reversed(recent3))
    elapsed = time.time() - t0
    print(f"  Got {len(recent3)} message(s) in {elapsed:.1f}s")
    for m in recent3:
        print(f"  {msg_summary(m)}")

    t3_morning_digest = any(
        "MORNING DIGEST" in (m.message or m.text or "")
        or "TODAY'S EDGE PICKS" in (m.message or m.text or "")
        for m in recent3
    )
    t3_photo = any(isinstance(m.media, MessageMediaPhoto) for m in recent3)
    t3_has_content = len(recent3) > 0
    results["test3_reply_keyboard"] = {
        "elapsed": round(elapsed, 1),
        "has_photo": t3_photo,
        "morning_digest_in_text": t3_morning_digest,
        "has_response": t3_has_content,
        "summaries": [msg_summary(m) for m in recent3[:3]],
        "pass": not t3_morning_digest and t3_has_content,
    }

    # ── Test 4: Check what happens after morning-digest-like card ──
    # We simulate by first sending hot tips (which has a My Matches button)
    # then clicking the My Matches button on that response
    print("\n[T4] Simulating My Matches click from a card with My Matches button...")
    sent4 = await client.send_message(entity, "💎 Edge Picks")
    await asyncio.sleep(TIMEOUT)
    msgs4 = await client.get_messages(entity, limit=10)
    hot_msgs = [m for m in msgs4 if m.id > sent4.id and m.reply_markup]
    hot_msg = hot_msgs[0] if hot_msgs else None

    if hot_msg:
        print(f"  Hot tips message: {msg_summary(hot_msg)}")
        if hot_msg.reply_markup and isinstance(hot_msg.reply_markup, ReplyInlineMarkup):
            found_mm = False
            for row in hot_msg.reply_markup.rows:
                for btn in row.buttons:
                    if isinstance(btn, KeyboardButtonCallback) and "My Matches" in btn.text:
                        print(f"  Clicking My Matches from hot tips card: {btn.text!r}")
                        t0 = time.time()
                        try:
                            await hot_msg.click(data=btn.data)
                        except Exception as e:
                            print(f"  Click result: {e}")
                        await asyncio.sleep(TIMEOUT)
                        msgs_after4 = await client.get_messages(entity, limit=10)
                        recent4 = [m for m in msgs_after4 if m.id >= hot_msg.id]
                        recent4 = list(reversed(recent4))
                        elapsed = time.time() - t0
                        print(f"  Got {len(recent4)} message(s) in {elapsed:.1f}s")
                        for m in recent4:
                            print(f"  {msg_summary(m)}")

                        t4_morning_digest = any(
                            "MORNING DIGEST" in (m.message or m.text or "")
                            for m in recent4
                        )
                        t4_photo_changed = any(
                            isinstance(m.media, MessageMediaPhoto) and m.id == hot_msg.id
                            for m in recent4
                        )
                        results["test4_mm_from_card"] = {
                            "elapsed": round(elapsed, 1),
                            "morning_digest_persists": t4_morning_digest,
                            "summaries": [msg_summary(m) for m in recent4[:3]],
                            "pass": not t4_morning_digest,
                        }
                        found_mm = True
                        break
                if found_mm:
                    break
            if not found_mm:
                results["test4_mm_from_card"] = {"pass": None, "note": "no My Matches button on hot tips card"}
    else:
        results["test4_mm_from_card"] = {"pass": None, "note": "no hot tips card found"}

    return results


async def main():
    print("INV-MY-MATCHES-RENDER-02 — Telethon E2E investigation")
    print("=" * 60)
    client = await get_client()
    try:
        results = await run_test(client)
    finally:
        await client.disconnect()

    print("\n" + "=" * 60)
    print("RESULTS SUMMARY")
    print("=" * 60)
    all_pass = True
    for test_name, result in results.items():
        status = "PASS" if result.get("pass") else ("SKIP" if result.get("pass") is None else "FAIL")
        print(f"{status} {test_name}")
        for k, v in result.items():
            if k not in ("pass", "summaries"):
                print(f"       {k}: {v}")
        if "summaries" in result:
            for s in result["summaries"]:
                print(f"       >> {s}")
        if result.get("pass") is False:
            all_pass = False

    print("\nOVERALL:", "PASS" if all_pass else "FAIL")
    return results


if __name__ == "__main__":
    asyncio.run(main())
