"""SO #38 — E2E test: BUILD-BOOKMAKER-DIRECTORY-CARD-01

Verifies the affiliate:compare callback by navigating to the Bookmakers
screen via the Main Menu and asserting all four requirements.

Run:
    cd /home/paulsportsza/bot
    .venv/bin/python tests/test_e2e_so38_bookmaker_directory.py
"""
from __future__ import annotations

import asyncio
import os
import sys

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import (
    ReplyInlineMarkup,
    KeyboardButtonCallback,
    KeyboardButtonUrl,
    MessageMediaPhoto,
)

# ── Configuration ────────────────────────────────────────
API_ID   = int(os.getenv("TELEGRAM_API_ID", "32418601"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "95e313a8ef5b998be0515dd8328fac57")
BOT_USERNAME = "mzansiedge_bot"
TIMEOUT  = 15  # seconds


def _load_session() -> TelegramClient:
    """Prefer file session that exists on disk."""
    candidates = [
        "/home/paulsportsza/bot/mzansi_qa.session",
        "/home/paulsportsza/bot/telethon_qa_session.session",
        "/home/paulsportsza/bot/data/telethon_qa_session.session",
        "/home/paulsportsza/bot/anon_session.session",
    ]
    string_file = "/home/paulsportsza/bot/data/telethon_qa_session.string"
    if os.path.exists(string_file):
        s = open(string_file).read().strip()
        if s:
            return TelegramClient(StringSession(s), API_ID, API_HASH)
    for p in candidates:
        base = p.replace(".session", "")
        if os.path.exists(p):
            return TelegramClient(base, API_ID, API_HASH)
    sys.exit("ERROR: no usable Telethon session found")


async def _wait_for_new_messages(client, entity, after_id, wait=TIMEOUT):
    await asyncio.sleep(wait)
    msgs = await client.get_messages(entity, limit=20)
    return list(reversed([m for m in msgs if m.id > after_id]))


async def _click_callback(client, entity, msg, data: bytes):
    """Simulate inline button click via GotCallbackQuery."""
    from telethon.tl.functions.messages import GetBotCallbackAnswerRequest
    try:
        await client(GetBotCallbackAnswerRequest(
            peer=entity, msg_id=msg.id, data=data
        ))
    except Exception:
        pass


async def run_test():
    client = _load_session()
    await client.connect()
    if not await client.is_user_authorized():
        await client.disconnect()
        sys.exit("ERROR: Telethon session not authorized.")

    entity = await client.get_entity(BOT_USERNAME)

    # ── Step 1: Send /menu to get the main menu with Bookmakers button ──
    print("[1] Sending /menu ...")
    sent = await client.send_message(entity, "/menu")
    msgs_after = await _wait_for_new_messages(client, entity, sent.id, wait=12)

    menu_msg = None
    for m in msgs_after:
        if m.reply_markup and not m.out:
            menu_msg = m
            break

    if menu_msg is None:
        # Fall back: send "Bookmakers" directly as text
        print("[!] No menu reply with markup found — trying direct 'Bookmakers' text")
        sent2 = await client.send_message(entity, "Bookmakers")
        msgs_after = await _wait_for_new_messages(client, entity, sent2.id, wait=12)
        menu_msg = next((m for m in msgs_after if m.reply_markup and not m.out), None)

    # ── Step 2: Find and click the Bookmakers button ──
    bookmakers_btn = None
    if menu_msg and isinstance(menu_msg.reply_markup, ReplyInlineMarkup):
        for row in menu_msg.reply_markup.rows:
            for btn in row.buttons:
                if isinstance(btn, KeyboardButtonCallback):
                    label = btn.text.lower()
                    if "bookmaker" in label or "bookie" in label:
                        bookmakers_btn = btn
                        break
            if bookmakers_btn:
                break

    # Check if bot responded directly to /menu with the directory already
    # (some menu flows may already show it)
    if bookmakers_btn is None:
        print("[!] No 'Bookmakers' callback button found in menu response.")
        print("    Attempting direct callback send: affiliate:compare")
        # Trigger affiliate:compare via /start + direct callback
        sent3 = await client.send_message(entity, "/start")
        msgs_after3 = await _wait_for_new_messages(client, entity, sent3.id, wait=10)
        for m in msgs_after3:
            if not m.out and m.reply_markup and isinstance(m.reply_markup, ReplyInlineMarkup):
                for row in m.reply_markup.rows:
                    for btn in row.buttons:
                        if isinstance(btn, KeyboardButtonCallback):
                            label = btn.text.lower()
                            if "bookmaker" in label:
                                bookmakers_btn = btn
                                menu_msg = m
                                break
                    if bookmakers_btn:
                        break
                if bookmakers_btn:
                    break

    if bookmakers_btn is None:
        # Last resort: manually trigger the callback
        print("[!] Still no bookmakers button. Forcing affiliate:compare callback.")
    else:
        print(f"[2] Found bookmakers button: '{bookmakers_btn.text}' — clicking ...")

    # ── Step 3: Click the Bookmakers button ──
    if bookmakers_btn and menu_msg:
        await _click_callback(client, entity, menu_msg, bookmakers_btn.data)
    else:
        # Direct message trigger as last resort
        sent4 = await client.send_message(entity, "🎰 Bookmakers")
        msgs_after = await _wait_for_new_messages(client, entity, sent4.id, wait=8)

    await asyncio.sleep(TIMEOUT)

    # ── Step 4: Grab most recent bot message ──
    all_msgs = await client.get_messages(entity, limit=10)
    bot_msgs = [m for m in all_msgs if not m.out]
    target = bot_msgs[0] if bot_msgs else None

    if target is None:
        print("ERROR: No response from bot.")
        await client.disconnect()
        sys.exit(1)

    print(f"\n[3] Bot response message id={target.id}")

    # ── Assertions ──────────────────────────────────────────────────────
    results = {}

    # A1 — Is it a photo?
    is_photo = isinstance(target.media, MessageMediaPhoto)
    results["A1"] = ("PASS" if is_photo else "FAIL",
                     f"Response is {'a photo' if is_photo else 'text (not a photo)'}")

    # A2 — Does it have an inline keyboard?
    has_markup = (
        target.reply_markup is not None
        and isinstance(target.reply_markup, ReplyInlineMarkup)
    )
    results["A2"] = ("PASS" if has_markup else "FAIL",
                     f"Inline keyboard: {'present' if has_markup else 'MISSING'}")

    # Flatten all button labels
    btn_labels = []
    btn_types  = []
    if has_markup:
        for row in target.reply_markup.rows:
            for btn in row.buttons:
                label = getattr(btn, "text", "")
                btn_labels.append(label)
                btn_types.append(type(btn).__name__)

    print(f"    Button labels: {btn_labels}")
    print(f"    Button types:  {btn_types}")

    # A3 — At least one known SA bookmaker name in button labels
    SA_NAMES = {"betway", "hollywoodbets", "sportingbet", "supabets", "gbets"}
    found_bk = [lbl for lbl in btn_labels if any(bk in lbl.lower() for bk in SA_NAMES)]
    results["A3"] = ("PASS" if found_bk else "FAIL",
                     f"SA bookmaker buttons found: {found_bk or 'NONE'}")

    # A4 — Back button present (↩️ or text contains "back")
    back_btns = [lbl for lbl in btn_labels if "↩️" in lbl or "back" in lbl.lower()]
    results["A4"] = ("PASS" if back_btns else "FAIL",
                     f"Back button: {back_btns or 'MISSING'}")

    # ── Report ───────────────────────────────────────────────────────────
    print("\n" + "="*55)
    print("SO #38 — BUILD-BOOKMAKER-DIRECTORY-CARD-01  E2E Results")
    print("="*55)
    print(f"{'ID':<4}  {'Verdict':<6}  Detail")
    print("-"*55)
    for aid, (verdict, detail) in results.items():
        print(f"{aid:<4}  {verdict:<6}  {detail}")
    print("="*55)

    all_pass = all(v == "PASS" for v, _ in results.values())
    overall = "PASS" if all_pass else "FAIL"
    print(f"\nOverall: {overall}\n")

    # Print message text for OCR context
    if target.text:
        print("--- Bot message text (first 500 chars) ---")
        print(target.text[:500])
        print("-------------------------------------------")

    await client.disconnect()
    return overall, results


if __name__ == "__main__":
    overall, results = asyncio.run(run_test())
    sys.exit(0 if overall == "PASS" else 1)
