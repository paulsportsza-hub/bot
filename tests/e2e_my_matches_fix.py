"""E2E Telethon verification for MY-MATCHES-RELIABILITY-FIX wave.

Tests:
  Fix 1 (P0): yg:game:{id} callbacks return rendered content, NOT "Unable to load"
  Regression: edge:detail:{match_key} callbacks return rich narrative content

Usage:
    cd /home/paulsportsza/bot && .venv/bin/python tests/e2e_my_matches_fix.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.sessions import StringSession
from telethon.tl.types import (
    ReplyInlineMarkup,
    KeyboardButtonCallback,
    KeyboardButtonUrl,
)

# ---------- Config ----------
API_ID = 32418601
API_HASH = "95e313a8ef5b998be0515dd8328fac57"
BOT_USERNAME = "mzansiedge_bot"
SESSION_FILE = Path(__file__).resolve().parent.parent / "data" / "telethon_qa_session.session"
STRING_SESSION_FILE = Path(__file__).resolve().parent.parent / "data" / "telethon_qa_session.string"
REPORT_PATH = Path("/home/paulsportsza/reports/my_matches_fix_captures.json")

RESPONSE_TIMEOUT = 20  # seconds per callback wait
INITIAL_WAIT = 3       # seconds after send/click before polling

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("e2e_mm_fix")


# ---------- Report accumulator ----------
report: dict = {
    "timestamp": "",
    "fix1_my_matches": [],
    "regression_hot_tips": [],
}


# ---------- Helpers ----------

async def get_client() -> TelegramClient:
    """Connect using the SQLite session file directly (preferred), or string session fallback."""
    # Try string session first (more portable)
    if STRING_SESSION_FILE.exists():
        string = STRING_SESSION_FILE.read_text().strip()
        if string:
            client = TelegramClient(StringSession(string), API_ID, API_HASH)
            await client.connect()
            if await client.is_user_authorized():
                log.info("Connected via string session")
                return client
            await client.disconnect()

    # Fall back to SQLite session file
    session_path = str(SESSION_FILE).replace(".session", "")  # Telethon appends .session
    client = TelegramClient(session_path, API_ID, API_HASH)
    await client.connect()
    if not await client.is_user_authorized():
        log.error("Not authorised. Run save_telegram_session.py first.")
        sys.exit(1)
    log.info("Connected via SQLite session file")
    return client


async def get_latest_bot_msg_id(client: TelegramClient) -> int:
    """ID of the most recent message from the bot."""
    msgs = await client.get_messages(BOT_USERNAME, limit=1)
    return msgs[0].id if msgs else 0


async def send_text_and_wait(
    client: TelegramClient, text: str, timeout: float = RESPONSE_TIMEOUT
) -> "Message | None":
    """Send a text message to the bot and wait for the bot's reply."""
    last_id = await get_latest_bot_msg_id(client)

    try:
        await client.send_message(BOT_USERNAME, text)
    except FloodWaitError as e:
        log.warning("FloodWait %ds, sleeping...", e.seconds)
        await asyncio.sleep(e.seconds + 2)
        await client.send_message(BOT_USERNAME, text)

    await asyncio.sleep(INITIAL_WAIT)

    deadline = time.time() + timeout
    while time.time() < deadline:
        msgs = await client.get_messages(BOT_USERNAME, limit=10)
        for m in msgs:
            if m.id > last_id and not m.out:
                return m
        await asyncio.sleep(1)
    return None


async def click_callback_button(
    client: TelegramClient, msg, data_prefix: str, timeout: float = RESPONSE_TIMEOUT
) -> "Message | None":
    """Click an inline button whose callback_data starts with data_prefix.
    Returns the edited/new message after the click."""
    if not msg or not msg.reply_markup or not isinstance(msg.reply_markup, ReplyInlineMarkup):
        return None

    target_btn = None
    target_data = None
    for row in msg.reply_markup.rows:
        for btn in row.buttons:
            if isinstance(btn, KeyboardButtonCallback) and btn.data:
                cb = btn.data.decode("utf-8", errors="replace") if isinstance(btn.data, bytes) else str(btn.data)
                if cb.startswith(data_prefix):
                    target_btn = btn
                    target_data = cb
                    break
        if target_btn:
            break

    if not target_btn:
        return None

    old_id = await get_latest_bot_msg_id(client)
    original_id = msg.id

    try:
        await msg.click(data=target_btn.data)
    except FloodWaitError as e:
        log.warning("FloodWait on click %ds, sleeping...", e.seconds)
        await asyncio.sleep(e.seconds + 2)
        await msg.click(data=target_btn.data)
    except Exception as e:
        log.warning("click error for %s: %s", target_data, e)
        return None

    await asyncio.sleep(INITIAL_WAIT)

    deadline = time.time() + timeout
    while time.time() < deadline:
        # Check for NEW message first
        msgs = await client.get_messages(BOT_USERNAME, limit=10)
        for m in msgs:
            if m.id > old_id and not m.out:
                return m

        # Check if original was edited
        updated = await client.get_messages(BOT_USERNAME, ids=original_id)
        if updated and updated.text and updated.text != msg.text:
            return updated

        await asyncio.sleep(1.5)

    # Last resort: refetch original (may have been edited)
    updated = await client.get_messages(BOT_USERNAME, ids=original_id)
    return updated


def collect_callback_buttons(msg, prefix: str) -> list[tuple[str, str]]:
    """Return list of (callback_data, button_text) for buttons matching prefix."""
    results = []
    if not msg or not msg.reply_markup or not isinstance(msg.reply_markup, ReplyInlineMarkup):
        return results
    for row in msg.reply_markup.rows:
        for btn in row.buttons:
            if isinstance(btn, KeyboardButtonCallback) and btn.data:
                cb = btn.data.decode("utf-8", errors="replace") if isinstance(btn.data, bytes) else str(btn.data)
                if cb.startswith(prefix):
                    results.append((cb, btn.text))
    return results


def is_error_response(text: str) -> bool:
    """Check if the response is an error/failure message."""
    if not text:
        return True
    lower = text.lower()
    error_markers = [
        "unable to load",
        "try again",
        "something went wrong",
        "error loading",
        "couldn't fetch",
        "failed to load",
        "an error occurred",
    ]
    return any(marker in lower for marker in error_markers)


def is_rich_content(text: str) -> bool:
    """Check if the response contains meaningful rendered content."""
    if not text:
        return False
    # Game analysis markers
    rich_markers = [
        "\U0001f4cb",  # clipboard (Setup)
        "\U0001f3af",  # dart (match header or Edge)
        "\u26a0\ufe0f",  # warning (Risk)
        "\U0001f3c6",  # trophy (Verdict)
        "edge",
        "odds",
        "bookmaker",
        "@",       # odds format like "1.58"
        "vs",
        "EV",
    ]
    count = sum(1 for m in rich_markers if m.lower() in text.lower())
    return count >= 2


# ---------- Fix 1: My Matches yg:game callbacks ----------

async def test_my_matches_game_callbacks(client: TelegramClient) -> list[dict]:
    """Send 'My Matches', find game buttons, press up to 3, verify content."""
    results = []
    log.info("=" * 60)
    log.info("FIX 1: Testing My Matches game callbacks (yg:game:)")
    log.info("=" * 60)

    # Send My Matches
    log.info("Sending 'My Matches' to bot...")
    response = await send_text_and_wait(client, "\u26bd My Matches", timeout=RESPONSE_TIMEOUT)

    if not response:
        log.error("FAIL: No response to 'My Matches'")
        results.append({
            "fixture_id": "N/A",
            "success": False,
            "response_text": "",
            "error": "No response to My Matches command"
        })
        return results

    log.info("Got My Matches response (%d chars)", len(response.text or ""))

    # Find yg:game buttons
    game_buttons = collect_callback_buttons(response, "yg:game:")
    log.info("Found %d yg:game buttons", len(game_buttons))

    if not game_buttons:
        log.warning("No yg:game buttons found. Checking for edge:detail or other buttons...")
        # Check all buttons for diagnostic
        all_buttons = collect_callback_buttons(response, "")
        log.info("All buttons: %s", [(cb, txt) for cb, txt in all_buttons[:10]])
        results.append({
            "fixture_id": "N/A",
            "success": False,
            "response_text": response.text[:500] if response.text else "",
            "error": f"No yg:game buttons. Found {len(all_buttons)} other buttons."
        })
        return results

    # Test up to 3 game buttons
    test_count = min(3, len(game_buttons))
    for i in range(test_count):
        cb_data, btn_text = game_buttons[i]
        fixture_id = cb_data.replace("yg:game:", "")
        log.info("[%d/%d] Pressing button: %s (%s)", i + 1, test_count, btn_text.strip(), cb_data)

        t0 = time.time()
        detail_msg = await click_callback_button(client, response, cb_data, timeout=RESPONSE_TIMEOUT)
        elapsed = time.time() - t0

        if not detail_msg or not detail_msg.text:
            log.error("  FAIL: No response after pressing %s (%.1fs)", cb_data, elapsed)
            results.append({
                "fixture_id": fixture_id,
                "success": False,
                "response_text": "",
                "error": f"No response after pressing button ({elapsed:.1f}s)"
            })
        elif is_error_response(detail_msg.text):
            log.error("  FAIL: Error response for %s: %s", fixture_id, detail_msg.text[:200])
            results.append({
                "fixture_id": fixture_id,
                "success": False,
                "response_text": detail_msg.text[:2000],
                "error": "Error response: " + detail_msg.text[:200]
            })
        else:
            has_rich = is_rich_content(detail_msg.text)
            status = "PASS" if has_rich else "WARN"
            log.info("  %s: Got %d chars in %.1fs (rich=%s)", status, len(detail_msg.text), elapsed, has_rich)
            results.append({
                "fixture_id": fixture_id,
                "success": True,
                "response_text": detail_msg.text[:2000],
                "error": None if has_rich else "Response lacks rich content markers"
            })

        # Navigate back for the next button press
        if i < test_count - 1:
            log.info("  Navigating back to My Matches...")
            back_msg = await click_callback_button(client, detail_msg, "yg:all:", timeout=10)
            if back_msg:
                response = back_msg
                await asyncio.sleep(1)
            else:
                # Re-send My Matches if back button failed
                log.info("  Back failed, re-sending My Matches...")
                response = await send_text_and_wait(client, "\u26bd My Matches", timeout=RESPONSE_TIMEOUT)
                if not response:
                    log.error("  Could not re-navigate to My Matches")
                    break

    return results


# ---------- Regression: Hot Tips edge:detail callbacks ----------

async def test_hot_tips_detail_callbacks(client: TelegramClient) -> list[dict]:
    """Send 'Top Edge Picks', find edge:detail buttons, press up to 3, verify content."""
    results = []
    log.info("=" * 60)
    log.info("REGRESSION: Testing Hot Tips detail callbacks (edge:detail:)")
    log.info("=" * 60)

    # Send Top Edge Picks
    log.info("Sending 'Top Edge Picks' to bot...")
    response = await send_text_and_wait(client, "\U0001f48e Top Edge Picks", timeout=RESPONSE_TIMEOUT)

    if not response:
        log.error("FAIL: No response to 'Top Edge Picks'")
        results.append({
            "fixture_id": "N/A",
            "success": False,
            "response_text": "",
            "error": "No response to Top Edge Picks command"
        })
        return results

    log.info("Got Hot Tips response (%d chars)", len(response.text or ""))

    # Find edge:detail buttons
    detail_buttons = collect_callback_buttons(response, "edge:detail:")
    log.info("Found %d edge:detail buttons", len(detail_buttons))

    if not detail_buttons:
        # Also check for tier emoji buttons (they may use edge:detail as callback)
        all_buttons = collect_callback_buttons(response, "")
        log.info("All buttons: %s", [(cb, txt) for cb, txt in all_buttons[:10]])

        # Some buttons might use different prefix or be locked
        locked_buttons = collect_callback_buttons(response, "hot:upgrade")
        sub_buttons = collect_callback_buttons(response, "sub:")
        log.info("  locked/upgrade: %d, sub: %d", len(locked_buttons), len(sub_buttons))

        if not detail_buttons and not locked_buttons:
            results.append({
                "fixture_id": "N/A",
                "success": False,
                "response_text": response.text[:500] if response.text else "",
                "error": f"No edge:detail buttons. Found {len(all_buttons)} other buttons."
            })
            return results

    # Test up to 3 detail buttons
    test_count = min(3, len(detail_buttons))
    for i in range(test_count):
        cb_data, btn_text = detail_buttons[i]
        fixture_id = cb_data.replace("edge:detail:", "")
        log.info("[%d/%d] Pressing button: %s (%s)", i + 1, test_count, btn_text.strip(), cb_data)

        t0 = time.time()
        detail_msg = await click_callback_button(client, response, cb_data, timeout=RESPONSE_TIMEOUT)
        elapsed = time.time() - t0

        if not detail_msg or not detail_msg.text:
            log.error("  FAIL: No response after pressing %s (%.1fs)", cb_data, elapsed)
            results.append({
                "fixture_id": fixture_id,
                "success": False,
                "response_text": "",
                "error": f"No response after pressing button ({elapsed:.1f}s)"
            })
        elif is_error_response(detail_msg.text):
            log.error("  FAIL: Error response for %s: %s", fixture_id, detail_msg.text[:200])
            results.append({
                "fixture_id": fixture_id,
                "success": False,
                "response_text": detail_msg.text[:2000],
                "error": "Error response: " + detail_msg.text[:200]
            })
        else:
            has_rich = is_rich_content(detail_msg.text)
            status = "PASS" if has_rich else "WARN"
            log.info("  %s: Got %d chars in %.1fs (rich=%s)", status, len(detail_msg.text), elapsed, has_rich)
            results.append({
                "fixture_id": fixture_id,
                "success": True,
                "response_text": detail_msg.text[:2000],
                "error": None if has_rich else "Response lacks rich content markers"
            })

        # Navigate back for the next button press
        if i < test_count - 1:
            log.info("  Navigating back to Hot Tips...")
            back_msg = await click_callback_button(client, detail_msg, "hot:back", timeout=10)
            if back_msg:
                response = back_msg
                await asyncio.sleep(1)
            else:
                # Re-send Hot Tips if back button failed
                log.info("  Back failed, re-sending Top Edge Picks...")
                response = await send_text_and_wait(
                    client, "\U0001f48e Top Edge Picks", timeout=RESPONSE_TIMEOUT
                )
                if not response:
                    log.error("  Could not re-navigate to Top Edge Picks")
                    break

    return results


# ---------- Main ----------

async def main():
    log.info("Starting MY-MATCHES-RELIABILITY-FIX E2E verification")
    log.info("Bot: @%s | Session: %s", BOT_USERNAME, SESSION_FILE)

    client = await get_client()
    log.info("Telethon client connected")

    report["timestamp"] = datetime.now(timezone.utc).isoformat()

    try:
        # Fix 1: My Matches game callbacks
        report["fix1_my_matches"] = await test_my_matches_game_callbacks(client)

        # Brief pause between test suites
        await asyncio.sleep(3)

        # Regression: Hot Tips detail callbacks
        report["regression_hot_tips"] = await test_hot_tips_detail_callbacks(client)

    finally:
        await client.disconnect()
        log.info("Telethon client disconnected")

    # Save report
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(REPORT_PATH, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    log.info("Report saved to %s", REPORT_PATH)

    # Print summary
    print("\n" + "=" * 60)
    print("MY-MATCHES-RELIABILITY-FIX — E2E VERIFICATION SUMMARY")
    print("=" * 60)

    mm_total = len(report["fix1_my_matches"])
    mm_pass = sum(1 for r in report["fix1_my_matches"] if r["success"])
    mm_fail = mm_total - mm_pass

    ht_total = len(report["regression_hot_tips"])
    ht_pass = sum(1 for r in report["regression_hot_tips"] if r["success"])
    ht_fail = ht_total - ht_pass

    print(f"\nFix 1 — My Matches (yg:game:):  {mm_pass}/{mm_total} PASS, {mm_fail} FAIL")
    for r in report["fix1_my_matches"]:
        status = "PASS" if r["success"] else "FAIL"
        fixture = r["fixture_id"][:50]
        err = f" -- {r['error']}" if r["error"] else ""
        print(f"  [{status}] {fixture}{err}")

    print(f"\nRegression — Hot Tips (edge:detail:):  {ht_pass}/{ht_total} PASS, {ht_fail} FAIL")
    for r in report["regression_hot_tips"]:
        status = "PASS" if r["success"] else "FAIL"
        fixture = r["fixture_id"][:50]
        err = f" -- {r['error']}" if r["error"] else ""
        print(f"  [{status}] {fixture}{err}")

    overall = "PASS" if (mm_fail == 0 and ht_fail == 0 and mm_total > 0 and ht_total > 0) else "FAIL"
    print(f"\nOVERALL: {overall}")
    print(f"Report: {REPORT_PATH}")
    print("=" * 60)

    return 0 if overall == "PASS" else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
