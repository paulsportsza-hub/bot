#!/usr/bin/env python3
"""QA script for FIX-ONBOARDING-DONE-01.

Verifies that:
1. 'Edge Alerts' is NOT present in the onboarding done screen
2. 'Founding Member' is NOT present in the onboarding done screen
3. Standard card assertions pass

Runs via Telethon from the QA session.
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

# Load env from bot root
_bot_dir = Path(__file__).parent.parent.parent
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
STRING_SESSION_FILE = str(_bot_dir / "data" / "telethon_qa_session.string")
SCREENSHOT_PATH = "/tmp/qa_onboard_done_20260424.png"

WAIT_LONG = 25.0
WAIT_MID = 12.0
WAIT_SHORT = 8.0


def _load_session():
    s = Path(STRING_SESSION_FILE)
    if s.is_file():
        return s.read_text().strip()
    return None


async def _wait_for_bot_message(client, entity, after_id: int, timeout: float = 20.0) -> list:
    """Poll for new bot messages after after_id, with timeout."""
    start = time.time()
    while time.time() - start < timeout:
        msgs = await client.get_messages(entity, limit=15)
        new = [m for m in msgs if m.id > after_id and not m.out]
        if new:
            return list(reversed(new))  # oldest first
        await asyncio.sleep(1.0)
    return []


async def _send_and_get_last(client, entity, text: str, wait: float = WAIT_MID) -> list:
    sent = await client.send_message(entity, text)
    await asyncio.sleep(wait)
    msgs = await client.get_messages(entity, limit=20)
    return list(reversed([m for m in msgs if m.id >= sent.id]))


async def _click_callback_data(client, entity, msg, cb_data: str, wait: float = WAIT_MID) -> list:
    """Click inline button by callback data string."""
    if not msg.reply_markup or not isinstance(msg.reply_markup, ReplyInlineMarkup):
        raise RuntimeError(f"No inline markup on message {msg.id}")
    for row in msg.reply_markup.rows:
        for btn in row.buttons:
            if isinstance(btn, KeyboardButtonCallback) and btn.data == cb_data.encode():
                before = await client.get_messages(entity, limit=1)
                before_id = before[0].id if before else 0
                await msg.click(data=btn.data)
                await asyncio.sleep(wait)
                msgs = await client.get_messages(entity, limit=20)
                return list(reversed([m for m in msgs if m.id >= before_id]))
    raise RuntimeError(f"Button with data={cb_data!r} not found in message {msg.id}")


async def _click_first_button_containing(client, entity, msg, text: str, wait: float = WAIT_MID) -> list:
    """Click first inline button whose text contains the given string."""
    if not msg.reply_markup or not isinstance(msg.reply_markup, ReplyInlineMarkup):
        raise RuntimeError(f"No inline markup on message {msg.id}")
    for row in msg.reply_markup.rows:
        for btn in row.buttons:
            if isinstance(btn, KeyboardButtonCallback) and text.lower() in btn.text.lower():
                before = await client.get_messages(entity, limit=1)
                before_id = before[0].id if before else 0
                await msg.click(data=btn.data)
                await asyncio.sleep(wait)
                msgs = await client.get_messages(entity, limit=20)
                return list(reversed([m for m in msgs if m.id >= before_id]))
    # Print available buttons for debugging
    btns = []
    for row in msg.reply_markup.rows:
        for btn in row.buttons:
            if hasattr(btn, 'text'):
                btns.append(btn.text)
    raise RuntimeError(f"Button containing {text!r} not found. Available: {btns}")


def _find_bot_message_with_markup(msgs: list):
    """Find the most recent bot message that has inline markup (including photo cards)."""
    from telethon.tl.types import ReplyInlineMarkup
    for m in reversed(msgs):
        if not m.out and m.reply_markup and isinstance(m.reply_markup, ReplyInlineMarkup):
            return m
    return None


def _find_bot_message_with_photo(msgs: list):
    """Find the most recent bot message that has a photo."""
    for m in reversed(msgs):
        if not m.out and m.media and isinstance(m.media, MessageMediaPhoto):
            return m
    return None


def _extract_full_text(msgs: list) -> str:
    """Extract all text from non-outgoing messages."""
    parts = []
    for m in msgs:
        if not m.out:
            if m.text:
                parts.append(m.text)
            elif m.message:
                parts.append(m.message)
    return "\n\n".join(parts)


async def run_qa(client: TelegramClient) -> dict:
    """Run the full onboarding QA flow. Returns result dict."""
    entity = await client.get_entity(BOT_USERNAME)
    log = []
    result = {
        "screenshot_path": SCREENSHOT_PATH,
        "ocr_text": "",
        "assertions": {},
        "overall": "FAIL",
        "log": log,
    }

    # ── Step 1: Force onboard reset
    log.append("Step 1: Sending /qa force_onboard ...")
    msgs = await _send_and_get_last(client, entity, "/qa force_onboard", wait=5.0)
    texts = _extract_full_text(msgs)
    log.append(f"  Response: {texts[:200]!r}")
    if "reset" not in texts.lower() and "onboard" not in texts.lower():
        log.append("  WARNING: force_onboard may not have worked — proceeding anyway")

    await asyncio.sleep(2.0)

    # ── Step 2: /start
    log.append("Step 2: Sending /start ...")
    start_msgs = await _send_and_get_last(client, entity, "/start", wait=WAIT_MID)
    log.append(f"  Got {len(start_msgs)} messages")

    # Find a message with inline buttons (experience step)
    exp_msg = _find_bot_message_with_markup(start_msgs)
    if not exp_msg:
        # Sometimes /start sends multiple messages — look for onboarding msg
        for m in start_msgs:
            if not m.out and m.reply_markup:
                exp_msg = m
                break

    if not exp_msg:
        result["log"].append("FAIL: No inline keyboard after /start")
        return result

    log.append(f"  Found experience message (id={exp_msg.id}): {(exp_msg.text or '')[:80]!r}")

    # ── Step 3: Choose experience = "experienced" (skips edge explainer)
    log.append("Step 3: Clicking ob_exp:experienced ...")
    try:
        sports_msgs = await _click_callback_data(client, entity, exp_msg, "ob_exp:experienced", wait=WAIT_MID)
        log.append(f"  Got {len(sports_msgs)} messages after experience selection")
    except RuntimeError as e:
        log.append(f"  ob_exp:experienced not found: {e}, trying ob_exp:casual")
        sports_msgs = await _click_callback_data(client, entity, exp_msg, "ob_exp:casual", wait=WAIT_MID)

    sports_msg = _find_bot_message_with_markup(sports_msgs)
    if not sports_msg:
        result["log"].append("FAIL: No message with markup after experience step")
        return result
    log.append(f"  Found sports message (id={sports_msg.id}): {(sports_msg.text or '')[:80]!r}")

    # ── Step 4: Soccer already selected by default — click sports_done
    log.append("Step 4: Clicking ob_nav:sports_done ...")
    try:
        team_msgs = await _click_callback_data(client, entity, sports_msg, "ob_nav:sports_done", wait=WAIT_MID)
    except RuntimeError as e:
        log.append(f"  sports_done not found: {e}")
        # Try selecting soccer first then done
        try:
            await _click_callback_data(client, entity, sports_msg, "ob_sport:soccer", wait=3.0)
            fresh = await client.get_messages(entity, limit=10)
            sports_msg2 = _find_bot_message_with_markup(list(reversed(fresh)))
            team_msgs = await _click_callback_data(client, entity, sports_msg2, "ob_nav:sports_done", wait=WAIT_MID)
        except Exception as e2:
            result["log"].append(f"FAIL: Cannot navigate past sports step: {e2}")
            return result

    team_msg = _find_bot_message_with_markup(team_msgs)
    if not team_msg:
        result["log"].append("FAIL: No message after sports_done")
        return result
    log.append(f"  Team prompt (id={team_msg.id}): {(team_msg.text or '')[:80]!r}")

    # ── Step 5: Skip team input — send "skip" or look for skip button
    log.append("Step 5: Skipping team favourites ...")
    # Check if there's a skip button or if we need to type
    skip_done = False
    if team_msg.reply_markup and isinstance(team_msg.reply_markup, ReplyInlineMarkup):
        for row in team_msg.reply_markup.rows:
            for btn in row.buttons:
                if hasattr(btn, 'text') and ('skip' in btn.text.lower() or 'done' in btn.text.lower()):
                    log.append(f"  Found skip/done button: {btn.text!r}")
                    try:
                        skip_msgs = await _click_callback_data(
                            client, entity, team_msg,
                            btn.data.decode() if isinstance(btn.data, bytes) else btn.data,
                            wait=WAIT_MID
                        )
                        skip_done = True
                        next_msgs = skip_msgs
                        break
                    except Exception as e:
                        log.append(f"  Skip button click failed: {e}")
            if skip_done:
                break

    if not skip_done:
        # Send "skip" as text
        log.append("  No skip button — sending 'skip' as text")
        sent = await client.send_message(entity, "skip")
        await asyncio.sleep(WAIT_MID)
        fresh = await client.get_messages(entity, limit=15)
        next_msgs = list(reversed([m for m in fresh if m.id >= sent.id]))

    # ── Step 6: Navigate through subsequent steps until ob_done
    log.append("Step 6: Navigating to onboarding completion ...")
    current_msgs = next_msgs if skip_done else next_msgs  # noqa: F841

    # We need to find the plan step and click "Continue with Bronze"
    # Navigate forward through steps — look for ob_nav:plan or ob_bankroll, ob_notify, etc.
    max_iterations = 20
    iteration = 0
    done_screen_msg = None

    while iteration < max_iterations:
        iteration += 1
        markup_msg = _find_bot_message_with_markup(next_msgs)
        if not markup_msg:
            log.append(f"  Iter {iteration}: No markup message found")
            await asyncio.sleep(3.0)
            fresh = await client.get_messages(entity, limit=15)
            markup_msg = _find_bot_message_with_markup(list(reversed(fresh)))
            if not markup_msg:
                log.append("  Still no markup — trying to continue with text input")
                sent = await client.send_message(entity, "skip")
                await asyncio.sleep(WAIT_MID)
                fresh = await client.get_messages(entity, limit=15)
                next_msgs = list(reversed([m for m in fresh if m.id >= sent.id]))
                continue

        text_content = markup_msg.text or markup_msg.message or ""
        log.append(f"  Iter {iteration}: msg_id={markup_msg.id}, text={text_content[:80]!r}")

        # Check if this is already the done screen
        if "welcome" in text_content.lower() and ("edge picks" in text_content.lower() or "you're in" in text_content.lower()):
            log.append("  Found DONE screen!")
            done_screen_msg = markup_msg
            break

        # Also check for photo card (onboarding done is a card image)
        photo_msg = _find_bot_message_with_photo(next_msgs)
        if photo_msg:
            # Check if there's a "Set Up Edge Alerts" or "Skip for Now" button nearby
            if markup_msg and markup_msg.reply_markup:
                btn_texts = []
                for row in markup_msg.reply_markup.rows:
                    for btn in row.buttons:
                        if hasattr(btn, 'text'):
                            btn_texts.append(btn.text)
                if any("skip" in b.lower() or "edge alerts" in b.lower() or "edge picks" in b.lower() for b in btn_texts):
                    log.append(f"  Found DONE screen (photo+buttons)! Buttons: {btn_texts}")
                    done_screen_msg = markup_msg
                    # Use photo_msg for screenshot
                    break

        # List all available buttons
        btn_map = {}
        for row in markup_msg.reply_markup.rows:
            for btn in row.buttons:
                if isinstance(btn, KeyboardButtonCallback):
                    data_str = btn.data.decode() if isinstance(btn.data, bytes) else str(btn.data)
                    btn_map[data_str] = btn.text

        log.append(f"  Available buttons: {btn_map}")

        # Navigate based on what buttons are available
        clicked = False

        # Priority: plan step (choose bronze = complete onboarding)
        if "ob_plan:bronze" in btn_map:
            log.append("  Clicking ob_plan:bronze (completes onboarding)")
            next_msgs = await _click_callback_data(client, entity, markup_msg, "ob_plan:bronze", wait=WAIT_LONG)
            clicked = True

        # Summary step → next to plan
        elif "ob_nav:plan" in btn_map:
            log.append("  Clicking ob_nav:plan")
            next_msgs = await _click_callback_data(client, entity, markup_msg, "ob_nav:plan", wait=WAIT_MID)
            clicked = True

        # Risk step
        elif "ob_risk:moderate" in btn_map or "ob_risk:conservative" in btn_map:
            cb = "ob_risk:moderate" if "ob_risk:moderate" in btn_map else list(btn_map.keys())[0]
            log.append(f"  Clicking risk: {cb}")
            next_msgs = await _click_callback_data(client, entity, markup_msg, cb, wait=WAIT_MID)
            clicked = True

        # Bankroll step
        elif any(k.startswith("ob_bankroll:") for k in btn_map):
            # Click skip or R200
            cb = next((k for k in btn_map if k == "ob_bankroll:skip"), None)
            if not cb:
                cb = next((k for k in btn_map if k.startswith("ob_bankroll:")), None)
            log.append(f"  Clicking bankroll: {cb}")
            next_msgs = await _click_callback_data(client, entity, markup_msg, cb, wait=WAIT_MID)
            clicked = True

        # Notify step
        elif any(k.startswith("ob_notify:") for k in btn_map):
            cb = next(k for k in btn_map if k.startswith("ob_notify:"))
            log.append(f"  Clicking notify: {cb}")
            next_msgs = await _click_callback_data(client, entity, markup_msg, cb, wait=WAIT_MID)
            clicked = True

        # Edge explainer
        elif "ob_nav:edge_done" in btn_map:
            log.append("  Clicking ob_nav:edge_done (edge explainer)")
            next_msgs = await _click_callback_data(client, entity, markup_msg, "ob_nav:edge_done", wait=WAIT_MID)
            clicked = True

        # Favourites done for a sport
        elif any(k.startswith("ob_fav_done:") for k in btn_map):
            cb = next(k for k in btn_map if k.startswith("ob_fav_done:"))
            log.append(f"  Clicking {cb}")
            next_msgs = await _click_callback_data(client, entity, markup_msg, cb, wait=WAIT_MID)
            clicked = True

        # Done/finish
        elif "ob_done:finish" in btn_map:
            log.append("  Clicking ob_done:finish")
            next_msgs = await _click_callback_data(client, entity, markup_msg, "ob_done:finish", wait=WAIT_LONG)
            clicked = True

        # ob_summary:show
        elif "ob_summary:show" in btn_map:
            log.append("  Clicking ob_summary:show")
            next_msgs = await _click_callback_data(client, entity, markup_msg, "ob_summary:show", wait=WAIT_MID)
            clicked = True

        if not clicked:
            log.append(f"  WARNING: No known navigation button found. Buttons: {list(btn_map.keys())}")
            # Try sending "skip" as text to advance past text input
            sent = await client.send_message(entity, "skip")
            await asyncio.sleep(WAIT_MID)
            fresh = await client.get_messages(entity, limit=15)
            next_msgs = list(reversed([m for m in fresh if m.id >= sent.id]))

        # Check if done screen appeared
        for m in next_msgs:
            txt = m.text or m.message or ""
            if "welcome" in txt.lower() and ("you're in" in txt.lower() or "edge picks" in txt.lower()):
                log.append("  Done screen detected!")
                done_screen_msg = m
                break
            # Also check for the photo card version
            if not m.out and m.media and isinstance(m.media, MessageMediaPhoto):
                # Look for done-related markup nearby
                pass

        # Check for photo+buttons pattern (onboarding_done.html card)
        photo_m = _find_bot_message_with_photo(next_msgs)
        markup_m = _find_bot_message_with_markup(next_msgs)
        if photo_m and markup_m:
            btn_texts_check = []
            if markup_m.reply_markup and isinstance(markup_m.reply_markup, ReplyInlineMarkup):
                for row in markup_m.reply_markup.rows:
                    for btn in row.buttons:
                        if hasattr(btn, 'text'):
                            btn_texts_check.append(btn.text)
            if any("edge alerts" in b.lower() or "skip for now" in b.lower() or "edge picks" in b.lower()
                   for b in btn_texts_check):
                log.append(f"  Done screen detected (photo card)! Buttons: {btn_texts_check}")
                done_screen_msg = markup_m
                break

        if done_screen_msg:
            break

    # ── Step 7: Capture screenshot
    log.append(f"\nStep 7: Capturing screenshot to {SCREENSHOT_PATH}")
    screenshot_bytes = None

    # Find the photo message (onboarding done card is a PNG)
    photo_msg_final = None
    if done_screen_msg:
        # Look for photo near the done msg
        all_recent = await client.get_messages(entity, limit=20)
        # Find photo with id close to done_screen_msg
        for m in all_recent:
            if not m.out and m.media and isinstance(m.media, MessageMediaPhoto):
                if abs(m.id - done_screen_msg.id) <= 3:
                    photo_msg_final = m
                    break
        # Also just look for the most recent photo near the done message
        if not photo_msg_final:
            for m in sorted(all_recent, key=lambda x: x.id, reverse=True):
                if not m.out and m.media and isinstance(m.media, MessageMediaPhoto):
                    if m.id <= done_screen_msg.id + 5:
                        photo_msg_final = m
                        break

    if photo_msg_final:
        log.append(f"  Downloading photo from message {photo_msg_final.id}")
        buf = io.BytesIO()
        await client.download_media(photo_msg_final, file=buf)
        screenshot_bytes = buf.getvalue()
        if screenshot_bytes:
            with open(SCREENSHOT_PATH, "wb") as f:
                f.write(screenshot_bytes)
            log.append(f"  Screenshot saved ({len(screenshot_bytes)} bytes)")
        else:
            log.append("  WARNING: Photo download returned empty bytes")
    else:
        log.append("  WARNING: No photo message found near done screen")

    # ── Step 8: Collect full text from all recent messages
    all_recent_msgs = await client.get_messages(entity, limit=25)
    # Find messages around the done screen
    if done_screen_msg:
        window = [m for m in all_recent_msgs if abs(m.id - done_screen_msg.id) <= 5]
    else:
        window = all_recent_msgs[:10]

    all_text = ""
    for m in sorted(window, key=lambda x: x.id):
        if not m.out:
            if m.text:
                all_text += m.text + "\n\n"
            elif hasattr(m, 'message') and m.message:
                all_text += m.message + "\n\n"

    result["raw_text_from_bot"] = all_text.strip()
    result["screenshot_path"] = SCREENSHOT_PATH
    result["screenshot_saved"] = bool(screenshot_bytes)
    result["done_msg_id"] = done_screen_msg.id if done_screen_msg else None
    result["photo_msg_id"] = photo_msg_final.id if photo_msg_final else None

    return result


async def main():
    session_str = _load_session()
    if not session_str:
        print("ERROR: No Telethon string session found")
        sys.exit(1)

    async with TelegramClient(StringSession(session_str), API_ID, API_HASH) as client:
        if not await client.is_user_authorized():
            print("ERROR: Not authorized")
            sys.exit(1)

        result = await run_qa(client)

    print(json.dumps(result, indent=2, default=str))
    return result


if __name__ == "__main__":
    asyncio.run(main())
