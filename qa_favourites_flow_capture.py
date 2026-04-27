#!/usr/bin/env python3
"""Capture the actual prod onboarding favourites flow (Step 3/5).

Goal: confirm what the user sees when picking favourite teams. The hypothesis
is that the UI is text-input based (user types → list updates dynamically),
not list-with-buttons.

Flow:
1. /reset — wipe profile
2. /start — open onboarding
3. Click "I bet regularly" (experienced)
4. Toggle Soccer + click "Done"
5. Capture the cards shown at Step 3/5 — should be onboarding_favourites_manual
6. Type "Kaizer Chiefs, Arsenal" — capture the response (should be celebration card)
7. Save photos at /tmp/qa_fav_flow_{step}.png
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

_bot_dir = Path(__file__).parent
sys.path.insert(0, str(_bot_dir))
load_dotenv(_bot_dir / ".env")

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import (
    ReplyInlineMarkup,
    KeyboardButtonCallback,
    MessageMediaPhoto,
)

API_ID = int(os.getenv("TELEGRAM_API_ID", "32418601"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "95e313a8ef5b998be0515dd8328fac57")
BOT_USERNAME = "@mzansiedge_bot"
STRING_SESSION_FILE = str(_bot_dir / "data" / "telethon_session.string")

WAIT_MID = 8.0
WAIT_LONG = 15.0


def _load_session() -> str | None:
    s = Path(STRING_SESSION_FILE)
    if s.is_file():
        return s.read_text().strip()
    return None


async def _wait_for_bot_message(client, entity, after_id: int, timeout: float = 12.0) -> list:
    start = time.time()
    while time.time() - start < timeout:
        msgs = await client.get_messages(entity, limit=15)
        new = [m for m in msgs if m.id > after_id and not m.out]
        if new:
            return list(reversed(new))
        await asyncio.sleep(1.0)
    return []


async def _click_cb(client, entity, msg, cb_data: str, wait: float = WAIT_MID) -> list:
    """Click a callback button. Returns either new bot messages OR the edited
    same-id message (if the bot edited in place)."""
    if not msg.reply_markup or not isinstance(msg.reply_markup, ReplyInlineMarkup):
        raise RuntimeError(f"No inline markup on message {msg.id}")
    for row in msg.reply_markup.rows:
        for btn in row.buttons:
            if isinstance(btn, KeyboardButtonCallback) and btn.data == cb_data.encode():
                before = await client.get_messages(entity, limit=1)
                before_id = before[0].id if before else 0
                clicked_msg_id = msg.id
                await msg.click(data=cb_data.encode())
                await asyncio.sleep(wait)
                new_msgs = await _wait_for_bot_message(client, entity, before_id, timeout=wait)
                if new_msgs:
                    return new_msgs
                # No new messages — bot may have edited the same message in place
                edited = await client.get_messages(entity, ids=clicked_msg_id)
                if edited:
                    return [edited]
                return []
    raise RuntimeError(f"Callback data '{cb_data}' not found in markup")


async def _save_photo(msg, out_path: str):
    if msg.media and isinstance(msg.media, MessageMediaPhoto):
        await msg.download_media(file=out_path)
        return True
    return False


async def _dump_msg(msg, label: str, out_dir: Path):
    out_path = out_dir / f"{label}.png"
    if await _save_photo(msg, str(out_path)):
        print(f"  📷 Photo saved: {out_path}")
    text = (msg.message or "").strip()
    if text:
        text_path = out_dir / f"{label}.txt"
        text_path.write_text(text)
        print(f"  📝 Text ({len(text)} chars): {text[:100]}{'…' if len(text) > 100 else ''}")
    if msg.reply_markup and isinstance(msg.reply_markup, ReplyInlineMarkup):
        buttons = []
        for row in msg.reply_markup.rows:
            for btn in row.buttons:
                if isinstance(btn, KeyboardButtonCallback):
                    buttons.append(f"{btn.text} -> {btn.data.decode()}")
        if buttons:
            print(f"  🔘 Buttons: {buttons}")


async def main():
    out_dir = Path("/tmp/qa_fav_flow")
    out_dir.mkdir(exist_ok=True)
    print(f"Output dir: {out_dir}")

    session_str = _load_session()
    if not session_str:
        print("ERROR: No session file at " + STRING_SESSION_FILE)
        return 1

    async with TelegramClient(StringSession(session_str), API_ID, API_HASH) as client:
        entity = await client.get_entity(BOT_USERNAME)
        print(f"Connected to {BOT_USERNAME}")

        # Step 0: Reset onboarding state only (admin command, preserves subscription)
        print("\n=== Step 0: /qa force_onboard ===")
        sent = await client.send_message(entity, "/qa force_onboard")
        await asyncio.sleep(WAIT_MID)
        msgs = await _wait_for_bot_message(client, entity, sent.id, timeout=10.0)
        for m in msgs:
            if m.message:
                print(f"  Reset response: {m.message[:80]}")

        # Step 1: /start
        print("\n=== Step 1: /start ===")
        sent = await client.send_message(entity, "/start")
        await asyncio.sleep(WAIT_LONG)
        msgs = await _wait_for_bot_message(client, entity, sent.id, timeout=15.0)
        if not msgs:
            print("  FAIL: No response to /start")
            return 1
        last = msgs[-1]
        await _dump_msg(last, "01_welcome", out_dir)

        # Step 2: Click "I bet regularly" (experienced) — welcome card already has ob_exp buttons
        print("\n=== Step 2: Choose 'experienced' ===")
        msgs = await _click_cb(client, entity, last, "ob_exp:experienced")
        if msgs:
            last = msgs[-1]
            await _dump_msg(last, "03_after_exp", out_dir)

        # Step 4: Toggle Soccer
        print("\n=== Step 4: Toggle soccer ===")
        msgs = await _click_cb(client, entity, last, "ob_sport:soccer")
        if msgs:
            last = msgs[-1]
            await _dump_msg(last, "04_soccer_selected", out_dir)

        # Step 5: Sports done
        print("\n=== Step 5: Sports done ===")
        msgs = await _click_cb(client, entity, last, "ob_nav:sports_done")
        if msgs:
            last = msgs[-1]
            await _dump_msg(last, "05_favourites_step_entry", out_dir)

        # Step 6: Type team names
        print("\n=== Step 6: Type team names ===")
        sent = await client.send_message(entity, "Kaizer Chiefs, Arsenal, Liverpool")
        await asyncio.sleep(WAIT_LONG)
        msgs = await _wait_for_bot_message(client, entity, sent.id, timeout=20.0)
        if msgs:
            for i, m in enumerate(msgs):
                await _dump_msg(m, f"06_after_typing_{i}", out_dir)

    print(f"\n✅ Done. Captures in {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
