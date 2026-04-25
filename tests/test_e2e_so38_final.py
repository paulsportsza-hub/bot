"""SO #38 — E2E test: BUILD-BOOKMAKER-DIRECTORY-CARD-01

Flow:
  /menu  →  [📖 Guide]  →  [🏦 Bookmaker Quick Start]  →  [🎰 Bookmakers]
  (that final click triggers affiliate:compare)

Assertions:
  A1 - Response is a photo (image card)
  A2 - Inline keyboard present with bookmaker sign-up buttons
  A3 - At least one SA bookmaker name in button labels
  A4 - Back button present (↩️)

Run:
    cd /home/paulsportsza/bot
    .venv/bin/python tests/test_e2e_so38_final.py
"""
from __future__ import annotations

import asyncio
import os
import sys

from telethon import TelegramClient
from telethon.tl.functions.messages import GetBotCallbackAnswerRequest
from telethon.tl.types import (
    ReplyInlineMarkup,
    KeyboardButtonCallback,
    KeyboardButtonUrl,
    MessageMediaPhoto,
)

API_ID       = 32418601
API_HASH     = "95e313a8ef5b998be0515dd8328fac57"
BOT_USERNAME = "mzansiedge_bot"
SESSION      = "/home/paulsportsza/bot/anon_session"
STEP_WAIT    = 8   # seconds between steps


async def click_and_wait(client, entity, msg, data: bytes, wait: float = STEP_WAIT):
    """Send a callback query and wait for the bot to update the message."""
    try:
        await client(GetBotCallbackAnswerRequest(
            peer=entity, msg_id=msg.id, data=data,
        ))
    except Exception as e:
        print(f"    [callback req error — ok to ignore: {e}]")
    await asyncio.sleep(wait)


def _find_btn(reply_markup, *keywords) -> tuple | None:
    """Return (row_msg, btn) for the first button whose label matches any keyword."""
    if not isinstance(reply_markup, ReplyInlineMarkup):
        return None
    for row in reply_markup.rows:
        for btn in row.buttons:
            label = getattr(btn, "text", "").lower()
            if any(kw.lower() in label for kw in keywords):
                return btn
    return None


async def run_test():
    client = TelegramClient(SESSION, API_ID, API_HASH)
    await client.connect()
    if not await client.is_user_authorized():
        await client.disconnect()
        sys.exit("ERROR: session not authorized")

    entity = await client.get_entity(BOT_USERNAME)

    # ── Step 1: /menu ─────────────────────────────────────────────────
    print("[1] Sending /menu ...")
    sent = await client.send_message(entity, "/menu")
    await asyncio.sleep(STEP_WAIT)
    msgs = await client.get_messages(entity, limit=20)
    menu_msgs = [m for m in msgs if not m.out and m.id > sent.id]
    # Find the message that contains the Guide button (guide:menu callback)
    menu_msg = None
    for m in menu_msgs:
        if not isinstance(m.reply_markup, ReplyInlineMarkup):
            continue
        for row in m.reply_markup.rows:
            for btn in row.buttons:
                if isinstance(btn, KeyboardButtonCallback) and btn.data == b"guide:menu":
                    menu_msg = m
                    break
            if menu_msg:
                break
        if menu_msg:
            break
    if not menu_msg:
        # Fallback: any message with a button whose text contains "guide"
        menu_msg = next(
            (m for m in menu_msgs
             if isinstance(m.reply_markup, ReplyInlineMarkup)
             and _find_btn(m.reply_markup, "guide", "📖")),
            None,
        )
    if not menu_msg:
        print("  ERROR: no inline keyboard with Guide button in /menu response")
        for m in menu_msgs:
            print(f"    msg id={m.id} markup={type(m.reply_markup).__name__}")
            if isinstance(m.reply_markup, ReplyInlineMarkup):
                for row in m.reply_markup.rows:
                    print(f"      row: {[b.text for b in row.buttons]}")
        await client.disconnect(); sys.exit(1)
    print(f"  Got menu message id={menu_msg.id}")
    guide_btn = _find_btn(menu_msg.reply_markup, "guide", "📖")
    if not guide_btn:
        print("  ERROR: no Guide button in /menu response")
        for row in menu_msg.reply_markup.rows:
            print(f"    row: {[b.text for b in row.buttons]}")
        await client.disconnect(); sys.exit(1)
    print(f"  Found Guide button: '{guide_btn.text}'")

    # ── Step 2: Click Guide → guide:menu ──────────────────────────────
    print("[2] Clicking Guide button ...")
    await click_and_wait(client, entity, menu_msg, guide_btn.data, wait=STEP_WAIT)
    msgs2 = await client.get_messages(entity, limit=20)
    # The guide menu is usually an edited version of menu_msg — check same id or newer bot messages
    guide_msg = None
    # Look for a bot message with "bookmaker" topic button
    for m in msgs2:
        if m.out:
            continue
        if isinstance(m.reply_markup, ReplyInlineMarkup):
            bk_btn = _find_btn(m.reply_markup, "bookmaker", "🏦")
            if bk_btn:
                guide_msg = m
                print(f"  Got guide menu in message id={m.id}")
                break
    # Fallback: re-send guide:menu directly
    if guide_msg is None:
        print("  [!] Guide menu not detected, sending guide:menu text trigger ...")
        sent_g = await client.send_message(entity, "📖 Guide")
        await asyncio.sleep(STEP_WAIT)
        msgs2b = await client.get_messages(entity, limit=20)
        for m in msgs2b:
            if m.out: continue
            if isinstance(m.reply_markup, ReplyInlineMarkup) and m.id > sent_g.id:
                bk_btn = _find_btn(m.reply_markup, "bookmaker", "🏦")
                if bk_btn:
                    guide_msg = m
                    break
        if guide_msg is None:
            print("  ERROR: could not reach guide menu")
            await client.disconnect(); sys.exit(1)

    bk_topic_btn = _find_btn(guide_msg.reply_markup, "bookmaker", "🏦")
    print(f"  Found Bookmaker topic button: '{bk_topic_btn.text}'")

    # ── Step 3: Click Bookmaker Quick Start → guide:bookmaker ─────────
    print("[3] Clicking Bookmaker Quick Start ...")
    await click_and_wait(client, entity, guide_msg, bk_topic_btn.data, wait=STEP_WAIT)
    msgs3 = await client.get_messages(entity, limit=20)
    bk_topic_msg = None
    for m in msgs3:
        if m.out: continue
        if isinstance(m.reply_markup, ReplyInlineMarkup):
            aff_btn = _find_btn(m.reply_markup, "bookmakers", "🎰")
            if aff_btn:
                bk_topic_msg = m
                print(f"  Got Bookmaker topic page id={m.id}")
                break
    if bk_topic_msg is None:
        print("  ERROR: guide:bookmaker response not found")
        await client.disconnect(); sys.exit(1)

    aff_btn = _find_btn(bk_topic_msg.reply_markup, "bookmakers", "🎰")
    print(f"  Found affiliate button: '{aff_btn.text}'")

    # ── Step 4: Click 🎰 Bookmakers → affiliate:compare ───────────────
    print("[4] Clicking 🎰 Bookmakers (affiliate:compare) ...")
    await click_and_wait(client, entity, bk_topic_msg, aff_btn.data, wait=STEP_WAIT)
    msgs4 = await client.get_messages(entity, limit=10)

    # The bot edits the message — look for the most recent bot message that
    # has bookmaker-related content
    target = None
    for m in msgs4:
        if m.out:
            continue
        # Check text for bookmaker names OR check button labels
        has_bk_text = m.text and any(bk in m.text.lower() for bk in
                                      ["betway", "hollywoodbets", "supabets", "gbets",
                                       "sportingbet", "sa bookmakers", "bookmaker"])
        has_bk_btns = False
        if isinstance(m.reply_markup, ReplyInlineMarkup):
            for row in m.reply_markup.rows:
                for btn in row.buttons:
                    if any(bk in btn.text.lower() for bk in
                           ["betway", "hollywoodbets", "supabets", "gbets", "sportingbet"]):
                        has_bk_btns = True
                        break
        if has_bk_text or has_bk_btns:
            target = m
            break

    if target is None:
        # Fall back to most recent non-user message
        target = next((m for m in msgs4 if not m.out), None)

    if target is None:
        print("ERROR: No bot response captured")
        await client.disconnect(); sys.exit(1)

    print(f"\n[5] Captured target message id={target.id}")

    # ── Assertions ────────────────────────────────────────────────────
    is_photo = isinstance(target.media, MessageMediaPhoto)
    has_markup = isinstance(target.reply_markup, ReplyInlineMarkup)

    btn_labels = []
    btn_types  = []
    if has_markup:
        for row in target.reply_markup.rows:
            for btn in row.buttons:
                label = getattr(btn, "text", "")
                btn_labels.append(label)
                btn_types.append(type(btn).__name__)

    SA_NAMES = {"betway", "hollywoodbets", "sportingbet", "supabets", "gbets"}
    found_bk = [lbl for lbl in btn_labels
                if any(bk in lbl.lower() for bk in SA_NAMES)]
    back_btns = [lbl for lbl in btn_labels
                 if "↩️" in lbl or "back" in lbl.lower()]

    results = {
        "A1": ("PASS" if is_photo else "FAIL",
               f"Response is {'a photo (image card)' if is_photo else 'text message (not a photo)'}"),
        "A2": ("PASS" if has_markup else "FAIL",
               f"Inline keyboard {'present' if has_markup else 'MISSING'}"),
        "A3": ("PASS" if found_bk else "FAIL",
               f"SA bookmaker buttons: {found_bk or 'NONE'}"),
        "A4": ("PASS" if back_btns else "FAIL",
               f"Back button: {back_btns or 'MISSING'}"),
    }

    print("\n" + "="*58)
    print("SO #38 — BUILD-BOOKMAKER-DIRECTORY-CARD-01  E2E Results")
    print("="*58)
    print(f"{'ID':<4}  {'Verdict':<6}  Detail")
    print("-"*58)
    for aid, (verdict, detail) in results.items():
        print(f"{aid:<4}  {verdict:<6}  {detail}")
    print("="*58)
    overall = "PASS" if all(v == "PASS" for v, _ in results.values()) else "FAIL"
    print(f"\nOverall: {overall}\n")
    print(f"All buttons present: {btn_labels}")

    if target.text:
        print("\n--- Bot message text (first 600 chars) ---")
        print(target.text[:600])
        print("-------------------------------------------")

    await client.disconnect()
    return overall, results


if __name__ == "__main__":
    overall, results = asyncio.run(run_test())
    sys.exit(0 if overall == "PASS" else 1)
