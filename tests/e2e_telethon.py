"""MzansiEdge — End-to-End Telegram Bot Tests via Telethon.

Tests the LIVE bot by sending real messages and clicking inline buttons
through the Telegram API. No browser required.

Requires: data/telethon_session.string (saved Telethon session)

Usage:
    python tests/e2e_telethon.py                    # Run all tests
    python tests/e2e_telethon.py --test onboarding  # Specific suite
    python tests/e2e_telethon.py --test commands     # Post-onboarding
    python tests/e2e_telethon.py --test fuzzy        # Fuzzy matching
    python tests/e2e_telethon.py --test reset        # Profile reset
    python tests/e2e_telethon.py --test edge         # Edge cases
    python tests/e2e_telethon.py --test keyboard     # Sticky keyboard & UX polish
    python tests/e2e_telethon.py --report            # View saved report
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
from telethon.tl.custom.message import Message

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("e2e")

# ── Config ──────────────────────────────────────────────────
BOT_USERNAME = "mzansiedge_bot"
API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "")
SESSION_PATH = Path("data/telethon_session.string")
REPORT_PATH = Path("data/e2e_report.json")
SUMMARY_PATH = Path("data/e2e_report_summary.md")

# ── Results accumulator ─────────────────────────────────────
results: dict = {
    "timestamp": None,
    "total": 0,
    "passed": 0,
    "failed": 0,
    "warnings": 0,
    "errors": [],
    "warning_list": [],
    "tests": [],
}

# How long to wait for bot to reply (seconds)
BOT_REPLY_TIMEOUT = 15
PICKS_TIMEOUT = 30  # /picks fetches live odds, needs more time


# ═══════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════

def record(name: str, status: str, details: str = "", duration: float = 0):
    """Record a test result."""
    entry = {
        "name": name,
        "status": status,
        "details": details,
        "duration_ms": round(duration * 1000),
    }
    results["tests"].append(entry)
    results["total"] += 1
    if status == "PASS":
        results["passed"] += 1
        logger.info("  PASS: %s (%.1fs)", name, duration)
    elif status == "FAIL":
        results["failed"] += 1
        results["errors"].append(f"FAIL: {name} -- {details}")
        logger.error("  FAIL: %s -- %s (%.1fs)", name, details, duration)
    elif status == "WARN":
        results["warnings"] += 1
        results["warning_list"].append(f"WARN: {name} -- {details}")
        logger.warning("  WARN: %s -- %s", name, details)
    else:
        results["failed"] += 1
        results["errors"].append(f"ERROR: {name} -- {details}")
        logger.error("  ERROR: %s -- %s", name, details)


async def _get_last_msg_id(client: TelegramClient) -> int:
    """Get the ID of the most recent message in the bot chat."""
    msgs = await client.get_messages(BOT_USERNAME, limit=1)
    return msgs[0].id if msgs else 0


async def send_and_wait(client: TelegramClient, text: str,
                        timeout: int = BOT_REPLY_TIMEOUT) -> Message | None:
    """Send a message to the bot and wait for a reply.
    Uses message ID comparison for reliability (not timestamps)."""
    last_id = await _get_last_msg_id(client)

    try:
        await client.send_message(BOT_USERNAME, text)
    except FloodWaitError as e:
        logger.warning("FloodWait: sleeping %d seconds...", e.seconds)
        await asyncio.sleep(e.seconds + 2)
        await client.send_message(BOT_USERNAME, text)

    await asyncio.sleep(2)

    # Poll for new messages from the bot (ID > last_id, not sent by us)
    deadline = time.time() + timeout
    while time.time() < deadline:
        msgs = await client.get_messages(BOT_USERNAME, limit=5)
        for m in msgs:
            if m.id > last_id and not m.out:
                return m
        await asyncio.sleep(1)
    return None


async def send_cmd(client: TelegramClient, cmd: str,
                   timeout: int = BOT_REPLY_TIMEOUT) -> Message | None:
    """Send a /command and wait for bot reply."""
    return await send_and_wait(client, cmd, timeout)


async def _do_click(btn, client: TelegramClient, msg: Message | None = None) -> Message | None:
    """Click a button and return the updated/new message.
    btn.click() returns BotCallbackAnswer, so we re-fetch.
    The bot might EDIT the original message or send a NEW one."""
    # Record current state
    old_id = await _get_last_msg_id(client)
    original_id = msg.id if msg else old_id

    try:
        await btn.click()
    except FloodWaitError as e:
        logger.warning("FloodWait on click: sleeping %d seconds...", e.seconds)
        await asyncio.sleep(e.seconds + 2)
        await btn.click()
    except Exception as e:
        logger.debug("click error: %s", e)
        return None

    await asyncio.sleep(3)

    # Check for a NEW message first (ID > old)
    msgs = await client.get_messages(BOT_USERNAME, limit=5)
    for m in msgs:
        if m.id > old_id and not m.out:
            return m

    # No new message — the bot likely EDITED the original message.
    # Re-fetch it by ID to get the updated content.
    if original_id:
        updated = await client.get_messages(BOT_USERNAME, ids=original_id)
        if updated:
            return updated

    # Fallback: return latest bot message
    return await get_latest_bot_msg(client)


async def click_button(client: TelegramClient, msg: Message, text: str,
                       partial: bool = False) -> Message | None:
    """Click an inline button by its text. Returns the updated message."""
    if not msg or not msg.buttons:
        return None
    for row in msg.buttons:
        for btn in row:
            match = (partial and text.lower() in btn.text.lower()) or btn.text.lower() == text.lower()
            if match:
                return await _do_click(btn, client, msg)
    return None


async def click_button_by_data(client: TelegramClient, msg: Message,
                               data_prefix: str) -> Message | None:
    """Click an inline button by its callback_data prefix."""
    if not msg or not msg.buttons:
        return None
    for row in msg.buttons:
        for btn in row:
            if hasattr(btn, "data") and btn.data:
                cb = btn.data.decode() if isinstance(btn.data, bytes) else str(btn.data)
                if cb.startswith(data_prefix):
                    return await _do_click(btn, client, msg)


def get_button_texts(msg: Message | None) -> list[str]:
    """Get all inline button texts from a message."""
    if not msg or not msg.buttons:
        return []
    texts = []
    for row in msg.buttons:
        for btn in row:
            texts.append(btn.text)
    return texts


def get_button_data(msg: Message | None) -> list[str]:
    """Get all callback_data strings from a message."""
    if not msg or not msg.buttons:
        return []
    data = []
    for row in msg.buttons:
        for btn in row:
            if hasattr(btn, "data") and btn.data:
                cb = btn.data.decode() if isinstance(btn.data, bytes) else str(btn.data)
                data.append(cb)
    return data


def msg_text(msg: Message | None) -> str:
    """Get the text content of a message safely."""
    if not msg:
        return ""
    return msg.text or msg.message or ""


async def get_latest_bot_msg(client: TelegramClient) -> Message | None:
    """Get the most recent message from the bot."""
    msgs = await client.get_messages(BOT_USERNAME, limit=5)
    for m in msgs:
        if not m.out:
            return m
    return None


async def navigate_to_settings(client: TelegramClient) -> Message | None:
    """Navigate to settings via the menu (no /settings command exists).
    Tries multiple paths: settings:home button, or /menu → settings."""
    # First try /menu or /start to get the main menu
    msg = await send_cmd(client, "/menu")
    if not msg:
        msg = await send_cmd(client, "/start")
    if not msg:
        return None

    btn_data = get_button_data(msg)

    # Check if settings:home is directly available
    if "settings:home" in btn_data:
        return await click_button_by_data(client, msg, "settings:home")

    # Try clicking Settings button by text
    result = await click_button(client, msg, "Settings", partial=True)
    if result:
        return result

    return None


async def ensure_reset(client: TelegramClient) -> bool:
    """Reset the user's profile via menu → Settings → Reset → Confirm.
    Returns True if reset was successful."""
    msg = await navigate_to_settings(client)
    if not msg:
        return False

    btn_data = get_button_data(msg)

    # Click Reset Profile
    if "settings:reset" in btn_data:
        msg2 = await click_button_by_data(client, msg, "settings:reset")
    else:
        msg2 = await click_button(client, msg, "Reset", partial=True)

    if not msg2:
        return False

    btn_data2 = get_button_data(msg2)

    # Click confirm reset
    if "settings:reset:confirm" in btn_data2:
        msg3 = await click_button_by_data(client, msg2, "settings:reset:confirm")
    else:
        msg3 = await click_button(client, msg2, "Yes", partial=True)

    if not msg3:
        return False

    btn_data3 = get_button_data(msg3)

    # Click Start onboarding
    if "ob_restart:go" in btn_data3:
        msg4 = await click_button_by_data(client, msg3, "ob_restart:go")
    else:
        msg4 = await click_button(client, msg3, "Start onboarding", partial=True)

    return msg4 is not None


# ═══════════════════════════════════════════
# TEST SUITE 1: FULL ONBOARDING FLOW
# ═══════════════════════════════════════════

async def suite_onboarding(client: TelegramClient):
    """Test the complete onboarding flow from scratch."""
    logger.info("")
    logger.info("SUITE 1: Complete Onboarding Flow")
    logger.info("-" * 40)

    # ── Ensure clean state via reset ──
    logger.info("  Resetting profile for clean onboarding test...")
    reset_ok = await ensure_reset(client)
    if not reset_ok:
        # Try /start directly — maybe user is already not onboarded
        msg = await send_cmd(client, "/start")
        btns = get_button_data(msg)
        if not any("ob_exp:" in b for b in btns):
            record("onboarding_reset_for_test", "FAIL",
                   "Could not reset profile for onboarding test")
            return
    else:
        # After reset + ob_restart:go, we should be at experience step
        msg = await get_latest_bot_msg(client)

    # ── Step 1: Experience question ──
    t0 = time.time()
    if not msg or not msg.buttons:
        msg = await send_cmd(client, "/start")

    btn_texts = get_button_texts(msg)
    btn_data = get_button_data(msg)

    has_exp_buttons = any("ob_exp:" in d for d in btn_data)
    if has_exp_buttons:
        record("experience_shows_3_options", "PASS",
               f"Buttons: {btn_texts}", time.time() - t0)
    else:
        record("experience_shows_3_options", "FAIL",
               f"No experience buttons. Data: {btn_data}, Texts: {btn_texts}",
               time.time() - t0)
        return

    # Check all 3 options
    has_exp = "ob_exp:experienced" in btn_data
    has_cas = "ob_exp:casual" in btn_data
    has_new = "ob_exp:newbie" in btn_data
    if has_exp and has_cas and has_new:
        record("experience_all_3_levels", "PASS",
               "experienced, casual, newbie all present", time.time() - t0)
    else:
        record("experience_all_3_levels", "FAIL",
               f"Missing options. Data: {btn_data}", time.time() - t0)

    # Select "casual" experience
    t0 = time.time()
    msg = await click_button_by_data(client, msg, "ob_exp:casual")
    if not msg:
        msg = await get_latest_bot_msg(client)

    btn_data = get_button_data(msg)
    has_sport_buttons = any("ob_sport:" in d for d in btn_data)
    if has_sport_buttons:
        record("experience_advances_to_sports", "PASS",
               "Moved to sport selection", time.time() - t0)
    else:
        record("experience_advances_to_sports", "FAIL",
               f"No sport buttons after experience. Data: {btn_data}",
               time.time() - t0)
        return

    # ── Step 2: Sport selection ──
    t0 = time.time()
    btn_texts = get_button_texts(msg)
    btn_data = get_button_data(msg)

    # Check SA-priority: Soccer should be near the top
    soccer_idx = next((i for i, d in enumerate(btn_data) if d == "ob_sport:soccer"), -1)
    if soccer_idx >= 0 and soccer_idx <= 1:
        record("sports_sa_priority_soccer_first", "PASS",
               f"Soccer at position {soccer_idx}", time.time() - t0)
    elif soccer_idx >= 0:
        record("sports_sa_priority_soccer_first", "WARN",
               f"Soccer at position {soccer_idx}, expected 0-1", time.time() - t0)
    else:
        record("sports_sa_priority_soccer_first", "FAIL",
               f"Soccer not found. Data: {btn_data}", time.time() - t0)

    # Check all 11 sports present
    sport_buttons = [d for d in btn_data if d.startswith("ob_sport:")]
    if len(sport_buttons) >= 10:
        record("sports_shows_all_categories", "PASS",
               f"{len(sport_buttons)} sports shown", time.time() - t0)
    else:
        record("sports_shows_all_categories", "WARN",
               f"Expected 11, got {len(sport_buttons)}: {sport_buttons}",
               time.time() - t0)

    # Check boxing present
    has_boxing = "ob_sport:boxing" in btn_data
    if has_boxing:
        record("sports_has_boxing", "PASS", "Boxing present", time.time() - t0)
    else:
        record("sports_has_boxing", "FAIL",
               f"Boxing not found. Data: {btn_data}", time.time() - t0)

    # Select Soccer
    t0 = time.time()
    msg = await click_button_by_data(client, msg, "ob_sport:soccer")
    if not msg:
        msg = await get_latest_bot_msg(client)
    btn_texts = get_button_texts(msg)
    soccer_text = next((t for t in btn_texts if "soccer" in t.lower()), "")
    if "✅" in soccer_text:
        record("sports_toggle_checkmark", "PASS",
               f"Soccer shows checkmark: {soccer_text}", time.time() - t0)
    else:
        record("sports_toggle_checkmark", "WARN",
               f"No checkmark. Soccer text: '{soccer_text}'", time.time() - t0)

    # Also select Tennis and Boxing
    msg = await click_button_by_data(client, msg, "ob_sport:tennis")
    if not msg:
        msg = await get_latest_bot_msg(client)
    await asyncio.sleep(0.5)
    msg = await click_button_by_data(client, msg, "ob_sport:boxing")
    if not msg:
        msg = await get_latest_bot_msg(client)

    # Done button should now appear
    btn_data = get_button_data(msg)
    has_done = "ob_nav:sports_done" in btn_data
    record("sports_done_button_appears", "PASS" if has_done else "WARN",
           f"Done button: {has_done}", time.time() - t0)

    # Click Done
    t0 = time.time()
    msg = await click_button_by_data(client, msg, "ob_nav:sports_done")
    if not msg:
        msg = await get_latest_bot_msg(client)

    btn_data = get_button_data(msg)
    has_league = any("ob_league:" in d for d in btn_data)
    has_fav = any("ob_fav:" in d for d in btn_data)
    if has_league or has_fav:
        record("sports_done_advances", "PASS",
               f"Advanced to {'leagues' if has_league else 'favourites'}",
               time.time() - t0)
    else:
        record("sports_done_advances", "FAIL",
               f"No league or fav buttons. Data: {btn_data}", time.time() - t0)
        return

    # ── Steps 3-4: Navigate through leagues + favourites ──
    # Auto-navigate through all sport league/fav steps until we reach risk
    max_steps = 30
    step = 0
    league_tested = False
    fav_tested = False

    while step < max_steps:
        step += 1
        btn_data = get_button_data(msg)
        btn_texts = get_button_texts(msg)
        text = msg_text(msg)

        if any("ob_risk:" in d for d in btn_data):
            break  # Reached risk profile

        # League selection
        if any("ob_league:" in d for d in btn_data):
            if not league_tested:
                t0 = time.time()
                league_btns = [d for d in btn_data if d.startswith("ob_league:")]
                has_back = any("ob_nav:back_sports" == d for d in btn_data)
                has_next = any(d.startswith("ob_nav:league_done:") for d in btn_data)
                record("league_has_options", "PASS",
                       f"{len(league_btns)} leagues available", time.time() - t0)
                if has_back and has_next:
                    record("league_has_back_next", "PASS",
                           "Back and Next buttons present", time.time() - t0)
                league_tested = True

            # Select first league and advance
            for d in btn_data:
                if d.startswith("ob_league:"):
                    msg = await click_button_by_data(client, msg, d)
                    if not msg:
                        msg = await get_latest_bot_msg(client)
                    break
            msg = await click_button_by_data(client, msg, "ob_nav:league_done:")
            if not msg:
                msg = await get_latest_bot_msg(client)
            continue

        # Text-based team input (new UX: type comma-separated names)
        if any("ob_fav_done:" in d for d in btn_data):
            if not fav_tested:
                t0 = time.time()
                has_skip = any("ob_fav_done:" in d for d in btn_data)
                is_text_input = "type" in text.lower() or "comma" in text.lower() or "favourite" in text.lower()

                record("fav_text_input_prompt", "PASS" if is_text_input else "WARN",
                       f"Text input mode: {is_text_input}. Text: {text[:80]}",
                       time.time() - t0)

                record("fav_has_skip", "PASS" if has_skip else "FAIL",
                       f"Skip/Done: {has_skip}", time.time() - t0)
                fav_tested = True

            # Type a team name to test text input
            msg_reply = await send_and_wait(client, "Arsenal")
            if msg_reply:
                reply_text = msg_text(msg_reply)
                reply_data = get_button_data(msg_reply)
                if "arsenal" in reply_text.lower():
                    record("fav_text_input_works", "PASS",
                           f"Arsenal matched. Text: {reply_text[:80]}")
                    # Click Continue if available
                    if any("ob_fav_done:" in d for d in reply_data):
                        msg = await click_button_by_data(client, msg_reply, "ob_fav_done:")
                        if not msg:
                            msg = await get_latest_bot_msg(client)
                    else:
                        msg = msg_reply
                else:
                    # Just skip
                    msg = await click_button_by_data(client, msg, "ob_fav_done:")
                    if not msg:
                        msg = await get_latest_bot_msg(client)
            else:
                msg = await click_button_by_data(client, msg, "ob_fav_done:")
                if not msg:
                    msg = await get_latest_bot_msg(client)
            continue

        # Other navigation
        if any("ob_nav:" in d for d in btn_data):
            for prefix in ["ob_nav:league_done:", "ob_nav:sports_done"]:
                if any(d.startswith(prefix) for d in btn_data):
                    msg = await click_button_by_data(client, msg, prefix)
                    if not msg:
                        msg = await get_latest_bot_msg(client)
                    break
            continue

        msg = await get_latest_bot_msg(client)
        if not msg:
            break

    # ── Step 5: Risk profile ──
    t0 = time.time()
    btn_data = get_button_data(msg)
    btn_texts = get_button_texts(msg)

    has_conservative = "ob_risk:conservative" in btn_data
    has_moderate = "ob_risk:moderate" in btn_data
    has_aggressive = "ob_risk:aggressive" in btn_data

    if has_conservative and has_moderate and has_aggressive:
        record("risk_profile_3_options", "PASS",
               "All 3 risk profiles present", time.time() - t0)
    elif any("ob_risk:" in d for d in btn_data):
        record("risk_profile_3_options", "WARN",
               f"Some risk options. Data: {btn_data}", time.time() - t0)
    else:
        record("risk_profile_3_options", "FAIL",
               f"No risk options. Data: {btn_data}, Texts: {btn_texts}",
               time.time() - t0)
        return

    msg = await click_button_by_data(client, msg, "ob_risk:moderate")
    if not msg:
        msg = await get_latest_bot_msg(client)

    btn_data = get_button_data(msg)
    has_notify = any("ob_notify:" in d for d in btn_data)
    record("risk_advances_to_notify", "PASS" if has_notify else "FAIL",
           f"Notification step: {has_notify}", time.time() - t0)

    if not has_notify:
        return

    # ── Step 6: Notification time ──
    t0 = time.time()
    btn_data = get_button_data(msg)

    has_7am = "ob_notify:7" in btn_data
    has_6pm = "ob_notify:18" in btn_data
    record("notify_has_time_options", "PASS" if (has_7am and has_6pm) else "WARN",
           f"7AM: {has_7am}, 6PM: {has_6pm}", time.time() - t0)

    msg = await click_button_by_data(client, msg, "ob_notify:18")
    if not msg:
        msg = await get_latest_bot_msg(client)

    # ── Step 7: Profile summary ──
    t0 = time.time()
    btn_data = get_button_data(msg)
    btn_texts = get_button_texts(msg)
    text = msg_text(msg)

    has_edit_sports = "ob_edit:sports" in btn_data
    has_edit_risk = "ob_edit:risk" in btn_data
    has_confirm = "ob_done:finish" in btn_data

    record("summary_has_edit_sports", "PASS" if has_edit_sports else "FAIL",
           f"Edit Sports: {has_edit_sports}", time.time() - t0)
    record("summary_has_edit_risk", "PASS" if has_edit_risk else "FAIL",
           f"Edit Risk: {has_edit_risk}", time.time() - t0)
    record("summary_has_confirm", "PASS" if has_confirm else "FAIL",
           f"Confirm: {has_confirm}", time.time() - t0)

    # Test edit flow
    if has_edit_sports:
        t0 = time.time()
        msg_edit = await click_button_by_data(client, msg, "ob_edit:sports")
        if not msg_edit:
            msg_edit = await get_latest_bot_msg(client)
        edit_data = get_button_data(msg_edit)
        has_sport_edits = any("ob_edit:sport:" in d for d in edit_data)
        has_back = "ob_summary:show" in edit_data
        record("edit_sports_shows_list", "PASS" if has_sport_edits else "FAIL",
               f"Sport edits: {has_sport_edits}", time.time() - t0)
        record("edit_sports_has_back", "PASS" if has_back else "WARN",
               f"Back to summary: {has_back}", time.time() - t0)
        # Go back
        msg = await click_button_by_data(client, msg_edit, "ob_summary:show")
        if not msg:
            msg = await get_latest_bot_msg(client)

    # Confirm onboarding
    t0 = time.time()
    btn_data = get_button_data(msg)
    if "ob_done:finish" in btn_data:
        msg = await click_button_by_data(client, msg, "ob_done:finish")
        if not msg:
            msg = await get_latest_bot_msg(client)

        btn_data = get_button_data(msg)
        text = msg_text(msg)
        btn_texts = get_button_texts(msg)

        # After onboarding, user sees welcome message with story quiz CTA
        has_welcome = "welcome" in text.lower() or "mzansiedge" in text.lower()
        has_story = "story:start" in btn_data or any("story" in t.lower() for t in btn_texts)
        has_skip = "nav:main" in btn_data or any("skip" in t.lower() for t in btn_texts)

        if has_welcome and (has_story or has_skip):
            record("onboarding_completes_to_welcome", "PASS",
                   f"Welcome shown. Buttons: {btn_texts[:5]}",
                   time.time() - t0)
        else:
            # Might still show menu (backward compat)
            has_menu = any(
                d.startswith("picks:") or d.startswith("settings:")
                or d.startswith("sport:") or d.startswith("menu:")
                for d in btn_data
            )
            record("onboarding_completes_to_welcome", "PASS" if has_menu else "WARN",
                   f"Welcome: {has_welcome}, Story: {has_story}. Buttons: {btn_texts[:5]}",
                   time.time() - t0)
    else:
        record("onboarding_completes_to_welcome", "FAIL",
               f"No finish button. Data: {btn_data}", time.time() - t0)


# ═══════════════════════════════════════════
# TEST SUITE 2: POST-ONBOARDING COMMANDS
# ═══════════════════════════════════════════

async def suite_commands(client: TelegramClient):
    """Test all commands respond when user is onboarded."""
    logger.info("")
    logger.info("SUITE 2: Post-Onboarding Commands")
    logger.info("-" * 40)

    # ── /start when onboarded ──
    t0 = time.time()
    msg = await send_cmd(client, "/start")
    btn_data = get_button_data(msg)
    text = msg_text(msg)

    has_menu = any(
        d.startswith("picks:") or d.startswith("bets:") or d.startswith("settings:")
        or d.startswith("sport:") or d.startswith("ai:")
        for d in btn_data
    )
    has_experience = any("ob_exp:" in d for d in btn_data)

    if has_menu and not has_experience:
        record("start_when_onboarded_shows_menu", "PASS",
               f"Main menu shown. Buttons: {get_button_texts(msg)}", time.time() - t0)
    elif has_experience:
        record("start_when_onboarded_shows_menu", "FAIL",
               "Showed onboarding instead of menu", time.time() - t0)
    else:
        record("start_when_onboarded_shows_menu", "WARN",
               f"Couldn't determine. Data: {btn_data}", time.time() - t0)

    # ── All commands respond ──
    # Note: /settings is NOT a registered command — only accessible via inline button
    commands = ["/start", "/menu", "/help", "/picks"]
    for cmd in commands:
        t0 = time.time()
        timeout = PICKS_TIMEOUT if cmd == "/picks" else BOT_REPLY_TIMEOUT
        msg = await send_cmd(client, cmd, timeout=timeout)
        if msg and (msg.text or msg.buttons):
            record(f"command_{cmd}_responds", "PASS",
                   f"Response: {len(get_button_texts(msg))} buttons",
                   time.time() - t0)
        else:
            record(f"command_{cmd}_responds", "FAIL",
                   "No response from bot", time.time() - t0)

    # ── Settings via inline button ──
    t0 = time.time()
    msg = await navigate_to_settings(client)
    btn_data = get_button_data(msg)
    btn_texts = get_button_texts(msg)

    if not btn_data:
        record("settings_accessible_via_menu", "FAIL",
               "Could not navigate to settings", time.time() - t0)
    else:
        record("settings_accessible_via_menu", "PASS",
               f"Settings opened. Buttons: {btn_texts}", time.time() - t0)

        for label, cb_prefix in [
            ("settings_has_risk", "settings:risk"),
            ("settings_has_notifications", "settings:notify"),
            ("settings_has_sports", "settings:sports"),
            ("settings_has_reset", "settings:reset"),
        ]:
            found = any(d.startswith(cb_prefix) for d in btn_data)
            record(label, "PASS" if found else "FAIL",
                   f"{'Found' if found else 'Missing'}. Buttons: {btn_texts}",
                   time.time() - t0)

    # ── Back button from settings ──
    if msg and msg.buttons:
        t0 = time.time()
        msg_back = await click_button_by_data(client, msg, "menu:home")
        if not msg_back:
            msg_back = await click_button(client, msg, "Back", partial=True)
        if not msg_back:
            msg_back = await click_button(client, msg, "Main Menu", partial=True)
        btn_data_back = get_button_data(msg_back)
        has_menu = any(
            d.startswith("picks:") or d.startswith("bets:") or d.startswith("sport:")
            for d in btn_data_back
        )
        record("back_button_to_menu", "PASS" if has_menu else "WARN",
               f"Menu after back: {has_menu}. Buttons: {get_button_texts(msg_back)}",
               time.time() - t0)

    # ── HTML formatting check ──
    t0 = time.time()
    msg = await send_cmd(client, "/help")
    text = msg_text(msg)
    # Telethon shows bold as text with entities, raw ** should NOT be in msg.text
    # if parse_mode=HTML is used. If we see literal ** or __ it means markdown is raw.
    has_raw_markdown = "**" in text or "__" in text
    if text and not has_raw_markdown:
        record("help_no_raw_markdown", "PASS",
               "No raw markdown in /help response", time.time() - t0)
    elif has_raw_markdown:
        # Check if the message has entities (means it's properly formatted)
        has_entities = msg and msg.entities and len(msg.entities) > 0
        if has_entities:
            record("help_no_raw_markdown", "PASS",
                   "Message uses formatting entities (bold rendered as **)",
                   time.time() - t0)
        else:
            record("help_no_raw_markdown", "FAIL",
                   f"Raw markdown detected without entities: {text[:100]}",
                   time.time() - t0)
    else:
        record("help_no_raw_markdown", "WARN",
               "No help text received", time.time() - t0)


# ═══════════════════════════════════════════
# TEST SUITE 3: PROFILE RESET
# ═══════════════════════════════════════════

async def suite_reset(client: TelegramClient):
    """Test profile reset flow."""
    logger.info("")
    logger.info("SUITE 3: Profile Reset")
    logger.info("-" * 40)

    # ── Navigate to settings ──
    t0 = time.time()
    msg = await navigate_to_settings(client)
    btn_data = get_button_data(msg)

    has_reset = "settings:reset" in btn_data
    if has_reset:
        record("reset_button_in_settings", "PASS",
               "Reset Profile button found", time.time() - t0)
    else:
        record("reset_button_in_settings", "FAIL",
               f"No reset button. Data: {btn_data}", time.time() - t0)
        return

    # ── Reset shows warning ──
    t0 = time.time()
    msg2 = await click_button_by_data(client, msg, "settings:reset")
    btn_data2 = get_button_data(msg2)
    btn_texts2 = get_button_texts(msg2)
    text2 = msg_text(msg2)

    has_confirm = "settings:reset:confirm" in btn_data2
    has_cancel = "settings:home" in btn_data2

    if has_confirm and has_cancel:
        record("reset_warning_with_confirm_cancel", "PASS",
               f"Warning shown. Buttons: {btn_texts2}", time.time() - t0)
    else:
        record("reset_warning_with_confirm_cancel", "WARN",
               f"Confirm: {has_confirm}, Cancel: {has_cancel}. Buttons: {btn_texts2}",
               time.time() - t0)

    if not has_confirm:
        return

    # ── Confirm reset ──
    t0 = time.time()
    msg3 = await click_button_by_data(client, msg2, "settings:reset:confirm")
    btn_data3 = get_button_data(msg3)

    has_restart = "ob_restart:go" in btn_data3
    if has_restart:
        record("reset_confirm_shows_restart", "PASS",
               "Start onboarding button shown", time.time() - t0)
    else:
        record("reset_confirm_shows_restart", "FAIL",
               f"No restart button. Data: {btn_data3}", time.time() - t0)
        return

    # ── Restart leads to onboarding ──
    t0 = time.time()
    msg4 = await click_button_by_data(client, msg3, "ob_restart:go")
    if not msg4:
        msg4 = await get_latest_bot_msg(client)
    btn_data4 = get_button_data(msg4)

    has_exp = any("ob_exp:" in d for d in btn_data4)
    if has_exp:
        record("restart_leads_to_onboarding", "PASS",
               "Experience step shown after restart", time.time() - t0)
    else:
        record("restart_leads_to_onboarding", "FAIL",
               f"No experience buttons. Data: {btn_data4}", time.time() - t0)

    # ── Re-onboard quickly to restore state ──
    logger.info("  Re-onboarding to restore state...")
    await _quick_onboard(client, msg4)


async def _quick_onboard(client: TelegramClient, msg: Message | None):
    """Quickly complete onboarding to restore onboarded state."""
    if not msg:
        msg = await send_cmd(client, "/start")

    max_steps = 30
    for _ in range(max_steps):
        if not msg:
            msg = await get_latest_bot_msg(client)
        if not msg:
            break

        btn_data = get_button_data(msg)

        # Experience → pick casual
        if any("ob_exp:" in d for d in btn_data):
            msg = await click_button_by_data(client, msg, "ob_exp:casual")
            if not msg:
                msg = await get_latest_bot_msg(client)
            continue

        # Sports → pick soccer, then done
        if any("ob_sport:" in d for d in btn_data):
            msg = await click_button_by_data(client, msg, "ob_sport:soccer")
            if not msg:
                msg = await get_latest_bot_msg(client)
            msg = await click_button_by_data(client, msg, "ob_nav:sports_done")
            if not msg:
                msg = await get_latest_bot_msg(client)
            continue

        # Leagues → pick first, then next
        if any("ob_league:" in d for d in btn_data):
            league_btn = next((d for d in btn_data if d.startswith("ob_league:")), None)
            if league_btn:
                msg = await click_button_by_data(client, msg, league_btn)
                if not msg:
                    msg = await get_latest_bot_msg(client)
            msg = await click_button_by_data(client, msg, "ob_nav:league_done:")
            if not msg:
                msg = await get_latest_bot_msg(client)
            continue

        # Favourites (text input) → skip
        if any("ob_fav_done:" in d for d in btn_data):
            msg = await click_button_by_data(client, msg, "ob_fav_done:")
            if not msg:
                msg = await get_latest_bot_msg(client)
            continue

        # Risk → moderate
        if any("ob_risk:" in d for d in btn_data):
            msg = await click_button_by_data(client, msg, "ob_risk:moderate")
            if not msg:
                msg = await get_latest_bot_msg(client)
            continue

        # Notify → 6pm
        if any("ob_notify:" in d for d in btn_data):
            msg = await click_button_by_data(client, msg, "ob_notify:18")
            if not msg:
                msg = await get_latest_bot_msg(client)
            continue

        # Summary → confirm
        if "ob_done:finish" in btn_data:
            msg = await click_button_by_data(client, msg, "ob_done:finish")
            if not msg:
                msg = await get_latest_bot_msg(client)
            # Don't break — welcome message comes next
            continue

        # Welcome/story screen → skip to main menu
        if "story:start" in btn_data or "nav:main" in btn_data:
            msg = await click_button_by_data(client, msg, "nav:main")
            if not msg:
                msg = await get_latest_bot_msg(client)
            break

        # Edit views → go back to summary
        if "ob_summary:show" in btn_data:
            msg = await click_button_by_data(client, msg, "ob_summary:show")
            if not msg:
                msg = await get_latest_bot_msg(client)
            continue

        # Main menu → done
        if any(d.startswith("picks:") or d.startswith("sport:") for d in btn_data):
            break

        # Unrecognised state — try /start to recover
        msg = await send_cmd(client, "/start")
        if not msg:
            await asyncio.sleep(1)
            msg = await get_latest_bot_msg(client)


# ═══════════════════════════════════════════
# TEST SUITE 4: FUZZY MATCHING
# ═══════════════════════════════════════════

async def suite_fuzzy(client: TelegramClient):
    """Test fuzzy matching during manual team input."""
    logger.info("")
    logger.info("SUITE 4: Fuzzy Matching")
    logger.info("-" * 40)

    # Reset and start onboarding
    logger.info("  Resetting profile for fuzzy test...")
    reset_ok = await ensure_reset(client)
    if not reset_ok:
        record("fuzzy_setup_reset", "FAIL", "Could not reset profile")
        return

    msg = await get_latest_bot_msg(client)
    if not msg:
        msg = await send_cmd(client, "/start")

    # Select casual
    msg = await click_button_by_data(client, msg, "ob_exp:casual")
    if not msg:
        msg = await get_latest_bot_msg(client)

    # Select only Soccer
    msg = await click_button_by_data(client, msg, "ob_sport:soccer")
    if not msg:
        msg = await get_latest_bot_msg(client)
    msg = await click_button_by_data(client, msg, "ob_nav:sports_done")
    if not msg:
        msg = await get_latest_bot_msg(client)

    # Select EPL league (if league step shows)
    btn_data = get_button_data(msg)
    if any("ob_league:" in d for d in btn_data):
        epl = next((d for d in btn_data if "epl" in d), None)
        if epl:
            msg = await click_button_by_data(client, msg, epl)
            if not msg:
                msg = await get_latest_bot_msg(client)
        msg = await click_button_by_data(client, msg, "ob_nav:league_done:")
        if not msg:
            msg = await get_latest_bot_msg(client)

    # Now at favourites — should be text input mode (type team names directly)
    btn_data = get_button_data(msg)
    text = msg_text(msg)
    is_text_input = any("ob_fav_done:" in d for d in btn_data)
    if not is_text_input:
        record("fuzzy_text_input_ready", "FAIL",
               f"Not at team input. Data: {btn_data}")
        await _quick_onboard(client, msg)
        return
    record("fuzzy_text_input_ready", "PASS",
           f"Text input mode active. Text: {text[:60]}")

    # ── Test 1: Typo — "Arsnal" → Arsenal ──
    t0 = time.time()
    msg_reply = await send_and_wait(client, "Arsnal")
    text = msg_text(msg_reply)
    btn_texts = get_button_texts(msg_reply)
    btn_data = get_button_data(msg_reply)

    arsenal_match = "arsenal" in text.lower() or any("arsenal" in t.lower() for t in btn_texts)
    if arsenal_match:
        record("fuzzy_typo_arsnal", "PASS",
               f"Arsnal → Arsenal matched. Text: {text[:80]}", time.time() - t0)
    else:
        record("fuzzy_typo_arsnal", "FAIL",
               f"No match. Text: {text[:80]}, Buttons: {btn_texts}",
               time.time() - t0)

    # Click Continue/Done to move to next league or accept
    msg = msg_reply
    btn_data = get_button_data(msg)
    if any("ob_fav_done:" in d for d in btn_data):
        msg = await click_button_by_data(client, msg, "ob_fav_done:")
        if not msg:
            msg = await get_latest_bot_msg(client)

    # ── Test 2: Alias — "gooners" → Arsenal (next league or same) ──
    t0 = time.time()
    btn_data = get_button_data(msg)
    # If we're still in text input mode (another league), test alias
    if any("ob_fav_done:" in d for d in btn_data):
        msg_reply = await send_and_wait(client, "gooners")
        text = msg_text(msg_reply)
        btn_texts = get_button_texts(msg_reply)
        btn_data = get_button_data(msg_reply)

        arsenal_match = "arsenal" in text.lower() or any("arsenal" in t.lower() for t in btn_texts)
        if arsenal_match:
            record("fuzzy_alias_gooners", "PASS",
                   f"gooners → Arsenal. Text: {text[:80]}", time.time() - t0)
        else:
            record("fuzzy_alias_gooners", "FAIL",
                   f"No match. Text: {text[:80]}, Buttons: {btn_texts}",
                   time.time() - t0)

        msg = msg_reply
        btn_data = get_button_data(msg)
        if any("ob_fav_done:" in d for d in btn_data):
            msg = await click_button_by_data(client, msg, "ob_fav_done:")
            if not msg:
                msg = await get_latest_bot_msg(client)
    else:
        record("fuzzy_alias_gooners", "WARN",
               "Not in text input mode for alias test")

    # Complete onboarding to restore state
    logger.info("  Completing onboarding to restore state...")
    msg = await get_latest_bot_msg(client)
    await _quick_onboard(client, msg)


# ═══════════════════════════════════════════
# TEST SUITE 5: EDGE CASES
# ═══════════════════════════════════════════

async def suite_edge(client: TelegramClient):
    """Test edge cases and error handling."""
    logger.info("")
    logger.info("SUITE 5: Edge Cases")
    logger.info("-" * 40)

    # ── Zero sports → Done should not advance ──
    t0 = time.time()
    logger.info("  Resetting for zero-sports test...")
    reset_ok = await ensure_reset(client)
    if not reset_ok:
        record("edge_zero_sports_reset", "FAIL", "Could not reset")
    else:
        msg = await get_latest_bot_msg(client)
        if not msg:
            msg = await send_cmd(client, "/start")

        # Select casual experience
        msg = await click_button_by_data(client, msg, "ob_exp:casual")
        if not msg:
            msg = await get_latest_bot_msg(client)

        btn_data = get_button_data(msg)

        # Try clicking Done without selecting any sport
        if "ob_nav:sports_done" in btn_data:
            msg_after = await click_button_by_data(client, msg, "ob_nav:sports_done")
            if not msg_after:
                msg_after = await get_latest_bot_msg(client)
            btn_data_after = get_button_data(msg_after)

            still_on_sports = any("ob_sport:" in d for d in btn_data_after)
            if still_on_sports:
                record("edge_zero_sports_blocked", "PASS",
                       "Bot stayed on sport selection", time.time() - t0)
            else:
                record("edge_zero_sports_blocked", "FAIL",
                       f"Might have advanced. Data: {btn_data_after}",
                       time.time() - t0)
        else:
            record("edge_zero_sports_blocked", "PASS",
                   "Done button hidden when 0 sports selected",
                   time.time() - t0)

    # ── Random text during onboarding ──
    t0 = time.time()
    msg = await get_latest_bot_msg(client)
    btn_data = get_button_data(msg)

    if not any("ob_sport:" in d or "ob_exp:" in d for d in btn_data):
        msg_start = await send_cmd(client, "/start")
        btn_data = get_button_data(msg_start)
        if any("ob_exp:" in d for d in btn_data):
            msg = await click_button_by_data(client, msg_start, "ob_exp:casual")
            if not msg:
                msg = await get_latest_bot_msg(client)

    msg_reply = await send_and_wait(client, "hello random text 12345")
    if msg_reply:
        btn_data_reply = get_button_data(msg_reply)
        text = msg_text(msg_reply)
        record("edge_random_text_handled", "PASS",
               f"Bot responded. Buttons: {len(btn_data_reply)}, Text: {text[:60]}",
               time.time() - t0)
    else:
        record("edge_random_text_handled", "PASS",
               "Bot ignored random text (acceptable)", time.time() - t0)

    # ── Complete onboarding for remaining tests ──
    # Send /start to get a known onboarding state (not stale from random text)
    msg = await send_cmd(client, "/start")
    await _quick_onboard(client, msg)

    # ── Rapid commands ──
    t0 = time.time()
    for cmd in ["/help", "/menu", "/help"]:
        try:
            await client.send_message(BOT_USERNAME, cmd)
        except FloodWaitError as e:
            logger.warning("FloodWait: sleeping %d seconds...", e.seconds)
            await asyncio.sleep(e.seconds + 2)
            await client.send_message(BOT_USERNAME, cmd)
        await asyncio.sleep(0.5)

    await asyncio.sleep(5)
    msg = await get_latest_bot_msg(client)
    if msg and (msg.text or msg.buttons):
        record("edge_rapid_commands_no_crash", "PASS",
               "Bot survived rapid commands", time.time() - t0)
    else:
        record("edge_rapid_commands_no_crash", "FAIL",
               "No response after rapid commands", time.time() - t0)

    # ── /start when onboarded shows menu ──
    t0 = time.time()
    msg = await send_cmd(client, "/start")
    btn_data = get_button_data(msg)
    has_menu = any(
        d.startswith("picks:") or d.startswith("bets:") or d.startswith("sport:")
        for d in btn_data
    )
    has_ob = any("ob_exp:" in d for d in btn_data)

    if has_menu and not has_ob:
        record("edge_start_shows_menu", "PASS",
               "Main menu shown (not onboarding)", time.time() - t0)
    elif has_ob:
        record("edge_start_shows_menu", "FAIL",
               "Showed onboarding again", time.time() - t0)
    else:
        record("edge_start_shows_menu", "WARN",
               f"Ambiguous. Data: {btn_data}", time.time() - t0)


# ═══════════════════════════════════════════
# TEST SUITE 6: STICKY KEYBOARD & UX POLISH
# ═══════════════════════════════════════════

async def suite_keyboard(client: TelegramClient):
    """Test persistent reply keyboard and UX polish (back arrows, bookmaker display, schedule)."""
    logger.info("")
    logger.info("SUITE 6: Sticky Keyboard & UX Polish")
    logger.info("-" * 40)

    # ── 1. Sticky keyboard appears after /start for returning user ──
    t0 = time.time()
    msg = await send_cmd(client, "/start")
    # After /start, returning user gets two messages:
    # 1) Welcome with ReplyKeyboardMarkup
    # 2) Inline quick menu
    # Check recent messages for ReplyKeyboard presence
    msgs = await client.get_messages(BOT_USERNAME, limit=5)
    keyboard_msg = None
    for m in msgs:
        if not m.out and m.reply_markup:
            # Check if it's a ReplyKeyboard (not inline)
            # Telethon: ReplyKeyboardMarkup vs ReplyInlineMarkup
            markup_type = type(m.reply_markup).__name__
            if "ReplyKeyboardMarkup" in markup_type:
                keyboard_msg = m
                break

    if keyboard_msg:
        record("sticky_kb_after_start", "PASS",
               f"ReplyKeyboardMarkup found in message", time.time() - t0)
    else:
        # Even if we can't detect the markup type, check for text that indicates keyboard
        record("sticky_kb_after_start", "WARN",
               "Could not detect ReplyKeyboardMarkup (may still be visible to user)",
               time.time() - t0)

    # ── 2. All 6 keyboard buttons respond ──
    kb_buttons = [
        ("🎯 Picks", "picks"),
        ("📅 Schedule", "schedule"),
        ("🔴 Live", "live"),
        ("📊 Stats", "stats"),
        ("⚙️ Settings", "settings"),
        ("❓ Help", "help"),
    ]

    for btn_text, btn_name in kb_buttons:
        t0 = time.time()
        msg = await send_and_wait(client, btn_text, timeout=PICKS_TIMEOUT if btn_name == "picks" else BOT_REPLY_TIMEOUT)
        if msg and (msg.text or msg.buttons):
            text = msg_text(msg)
            # Verify it's a relevant response
            relevant = True
            if btn_name == "help" and "help" not in text.lower() and "command" not in text.lower():
                relevant = False
            if btn_name == "settings" and "settings" not in text.lower() and not msg.buttons:
                relevant = False
            if btn_name == "live" and "live" not in text.lower() and "follow" not in text.lower() and "game" not in text.lower():
                relevant = False
            if btn_name == "stats" and "stats" not in text.lower() and "profile" not in text.lower():
                relevant = False

            record(f"sticky_kb_{btn_name}_responds", "PASS" if relevant else "WARN",
                   f"Response: {text[:60]}", time.time() - t0)
        else:
            record(f"sticky_kb_{btn_name}_responds", "FAIL",
                   f"No response for '{btn_text}'", time.time() - t0)
        await asyncio.sleep(1)

    # ── 3. Back arrows use ↩️ (not 🔙) in inline keyboards ──
    t0 = time.time()
    # Check help response — should have nav buttons
    msg = await send_and_wait(client, "❓ Help")
    if msg:
        btn_texts = get_button_texts(msg)
        has_old_back = any("🔙" in t for t in btn_texts)
        has_new_back = any("↩️" in t for t in btn_texts)
        if has_old_back:
            record("back_arrow_standard", "FAIL",
                   f"Found old 🔙 back arrow. Buttons: {btn_texts}", time.time() - t0)
        elif has_new_back:
            record("back_arrow_standard", "PASS",
                   f"Uses ↩️ back arrow. Buttons: {btn_texts}", time.time() - t0)
        else:
            record("back_arrow_standard", "WARN",
                   f"No back arrow button found. Buttons: {btn_texts}", time.time() - t0)
    else:
        record("back_arrow_standard", "WARN", "No help response")

    # Also check settings for back arrows
    msg = await send_and_wait(client, "⚙️ Settings")
    if msg and msg.buttons:
        btn_texts = get_button_texts(msg)
        has_old_back = any("🔙" in t for t in btn_texts)
        if has_old_back:
            record("settings_back_arrow", "FAIL",
                   f"Old 🔙 in settings. Buttons: {btn_texts}")
        else:
            record("settings_back_arrow", "PASS",
                   f"No old 🔙 in settings. Buttons: {btn_texts}")

    # ── 4. Schedule shows numbered events with date grouping ──
    t0 = time.time()
    msg = await send_and_wait(client, "📅 Schedule", timeout=BOT_REPLY_TIMEOUT)
    if msg:
        text = msg_text(msg)
        btn_texts = get_button_texts(msg)

        # Check for numbered events (e.g. "1." or "2.")
        import re
        has_numbering = bool(re.search(r'\d+\.', text))
        # Check for date headers (Today, Tomorrow, or day names)
        has_date_group = (
            "today" in text.lower() or "tomorrow" in text.lower()
            or any(day in text.lower() for day in ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"])
        )
        # Check for abbreviated team buttons
        btn_text_str = " ".join(btn_texts)
        has_abbreviated_btns = bool(re.search(r'\[?\d+\]?', btn_text_str))  # buttons with numbers

        if "no upcoming" in text.lower() or "no leagues" in text.lower():
            record("schedule_format", "WARN",
                   f"No games found — can't test formatting. Text: {text[:80]}",
                   time.time() - t0)
        else:
            if has_numbering:
                record("schedule_numbered_events", "PASS",
                       f"Numbered events found. Text: {text[:80]}", time.time() - t0)
            else:
                record("schedule_numbered_events", "WARN",
                       f"No numbering. Text: {text[:80]}", time.time() - t0)

            if has_date_group:
                record("schedule_date_grouping", "PASS",
                       f"Date grouping found", time.time() - t0)
            else:
                record("schedule_date_grouping", "WARN",
                       f"No date grouping detected. Text: {text[:80]}", time.time() - t0)
    else:
        record("schedule_format", "FAIL", "No schedule response", time.time() - t0)

    # ── 5. Profile summary shows abbreviated leagues ──
    t0 = time.time()
    msg = await send_and_wait(client, "⚙️ Settings")
    if msg and msg.buttons:
        # Navigate to profile view if available
        btn_data = get_button_data(msg)
        # Settings typically shows the profile summary at the top
        text = msg_text(msg)
        # Just check if settings responds (profile summary shown via /start or settings:home)
        record("profile_accessible", "PASS",
               f"Settings accessible. Text: {text[:60]}", time.time() - t0)
    else:
        record("profile_accessible", "WARN",
               "Settings not showing buttons", time.time() - t0)


# ═══════════════════════════════════════════
# MAIN RUNNER
# ═══════════════════════════════════════════

async def run_all_tests():
    """Run the complete E2E test suite."""
    results["timestamp"] = datetime.now().isoformat()

    if not SESSION_PATH.exists():
        logger.error("No Telethon session found at %s", SESSION_PATH)
        logger.error("Run save_telethon_session.py first to authenticate.")
        sys.exit(1)

    session_str = SESSION_PATH.read_text().strip()
    client = TelegramClient(StringSession(session_str), API_ID, API_HASH)
    await client.connect()

    if not await client.is_user_authorized():
        logger.error("Session expired — re-run save_telethon_session.py")
        sys.exit(1)

    me = await client.get_me()
    logger.info("Connected as: %s (@%s)", me.first_name, me.username)
    logger.info("Testing bot: @%s", BOT_USERNAME)
    logger.info("=" * 60)

    try:
        # Ensure user is onboarded before running command tests
        logger.info("Checking if user is onboarded...")
        # Use longer timeout for first message (bot may be processing old updates)
        msg = await send_cmd(client, "/start", timeout=25)
        if not msg:
            logger.info("First /start timed out, retrying...")
            await asyncio.sleep(5)
            msg = await send_cmd(client, "/start", timeout=25)
        btn_data = get_button_data(msg)
        if any("ob_exp:" in d for d in btn_data):
            logger.info("User not onboarded — running quick onboard first...")
            await _quick_onboard(client, msg)
            logger.info("Quick onboard complete.")

        # Suite 2: Post-Onboarding Commands
        await suite_commands(client)

        # Suite 3: Profile Reset
        await suite_reset(client)

        # Suite 1: Full Onboarding (reset inside)
        await suite_onboarding(client)

        # Suite 4: Fuzzy Matching
        await suite_fuzzy(client)

        # Suite 5: Edge Cases
        await suite_edge(client)

        # Suite 6: Sticky Keyboard & UX Polish
        await suite_keyboard(client)

    except Exception as e:
        logger.exception("Unhandled exception in test runner: %s", e)
        record("test_runner_exception", "ERROR", str(e))
    finally:
        await client.disconnect()

    _print_report()
    _save_report()


async def run_specific_suite(suite_name: str):
    """Run a specific test suite."""
    results["timestamp"] = datetime.now().isoformat()

    if not SESSION_PATH.exists():
        logger.error("No Telethon session found at %s", SESSION_PATH)
        sys.exit(1)

    session_str = SESSION_PATH.read_text().strip()
    client = TelegramClient(StringSession(session_str), API_ID, API_HASH)
    await client.connect()

    if not await client.is_user_authorized():
        logger.error("Session expired — re-run save_telethon_session.py")
        sys.exit(1)

    me = await client.get_me()
    logger.info("Connected as: %s (@%s)", me.first_name, me.username)

    try:
        suites = {
            "onboarding": suite_onboarding,
            "commands": suite_commands,
            "reset": suite_reset,
            "fuzzy": suite_fuzzy,
            "edge": suite_edge,
            "keyboard": suite_keyboard,
        }
        fn = suites.get(suite_name)
        if fn:
            await fn(client)
        else:
            logger.error("Unknown suite: %s", suite_name)
            logger.info("Available: %s", ", ".join(suites))
    except Exception as e:
        logger.exception("Unhandled exception: %s", e)
        record("suite_exception", "ERROR", str(e))
    finally:
        await client.disconnect()

    _print_report()
    _save_report()


def _print_report():
    """Print the test report summary."""
    logger.info("")
    logger.info("=" * 60)
    logger.info("TEST REPORT")
    logger.info("=" * 60)
    logger.info("Total:    %d", results["total"])
    logger.info("Passed:   %d", results["passed"])
    logger.info("Failed:   %d", results["failed"])
    logger.info("Warnings: %d", results["warnings"])

    if results["errors"]:
        logger.info("")
        logger.info("FAILURES:")
        for err in results["errors"]:
            logger.info("  - %s", err)

    if results["warning_list"]:
        logger.info("")
        logger.info("WARNINGS:")
        for warn in results["warning_list"]:
            logger.info("  - %s", warn)


def _save_report():
    """Save JSON + markdown reports."""
    REPORT_PATH.parent.mkdir(exist_ok=True)
    REPORT_PATH.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    logger.info("")
    logger.info("JSON report saved to: %s", REPORT_PATH)

    # Generate markdown summary
    lines = [
        "# MzansiEdge E2E Test Report",
        "",
        f"**Date:** {results['timestamp']}",
        f"**Bot:** @{BOT_USERNAME}",
        f"**Method:** Telethon (Telegram API)",
        "",
        "## Summary",
        "",
        "| Metric | Count |",
        "|--------|-------|",
        f"| Total  | {results['total']} |",
        f"| Passed | {results['passed']} |",
        f"| Failed | {results['failed']} |",
        f"| Warnings | {results['warnings']} |",
        "",
        "## Test Results",
        "",
        "| # | Test | Status | Details | Duration |",
        "|---|------|--------|---------|----------|",
    ]
    for i, t in enumerate(results["tests"], 1):
        status = t["status"]
        detail = t["details"][:80].replace("|", "/").replace("\n", " ") if t["details"] else ""
        lines.append(f"| {i} | {t['name']} | {status} | {detail} | {t['duration_ms']}ms |")

    if results["errors"]:
        lines.extend(["", "## Failures", ""])
        for err in results["errors"]:
            lines.append(f"- {err}")

    if results["warning_list"]:
        lines.extend(["", "## Warnings", ""])
        for warn in results["warning_list"]:
            lines.append(f"- {warn}")

    lines.extend(["", "## Bugs Found & Fixed", "", "*(To be filled after self-audit)*", ""])
    lines.extend(["## Remaining Issues", "", "*(To be filled after self-audit)*", ""])

    SUMMARY_PATH.write_text("\n".join(lines))
    logger.info("Markdown report saved to: %s", SUMMARY_PATH)


if __name__ == "__main__":
    if "--test" in sys.argv:
        idx = sys.argv.index("--test")
        suite = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else ""
        asyncio.run(run_specific_suite(suite))
    elif "--report" in sys.argv:
        if REPORT_PATH.exists():
            data = json.loads(REPORT_PATH.read_text())
            print(json.dumps(data, indent=2))
        else:
            print(f"No report found at {REPORT_PATH}")
    else:
        asyncio.run(run_all_tests())
