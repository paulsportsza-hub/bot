"""SO #38 — Community CTA E2E Test (BUILD-COMMUNITY-CTA-01).

Verifies:
  A. Onboarding completion message contains "👥 Join the MzansiEdge Community" URL button.
  B. Main menu inline keyboard (kb_main) contains "🏠 Community" URL button.

Usage:
    cd /home/paulsportsza/bot
    python tests/test_so38_community_cta.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from datetime import datetime

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import (
    ReplyInlineMarkup,
    KeyboardButtonCallback,
    KeyboardButtonUrl,
)

# ── Config ────────────────────────────────────────────────
API_ID = int(os.getenv("TELEGRAM_API_ID", "32418601"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "95e313a8ef5b998be0515dd8328fac57")
BOT_USERNAME = "mzansiedge_bot"
SESSION_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "telethon_session")
STRING_SESSION_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "telethon_session.string")
SCREENSHOTS_DIR = "/home/paulsportsza/reports/e2e-screenshots"
STEP_WAIT = 6
LONG_WAIT = 10


# ── Client ────────────────────────────────────────────────
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


# ── Helpers ───────────────────────────────────────────────
async def send_text_and_wait(client, text: str, wait: float = STEP_WAIT) -> list:
    """Send a text message to the bot, wait, return recent bot messages."""
    entity = await client.get_entity(BOT_USERNAME)
    sent = await client.send_message(entity, text)
    await asyncio.sleep(wait)
    msgs = await client.get_messages(entity, limit=20)
    return list(reversed([m for m in msgs if m.id >= sent.id]))


async def click_inline_btn(client, msg, fragment: str, wait: float = STEP_WAIT) -> tuple[list, object | None]:
    """Click first inline callback button whose text contains fragment (case-insensitive).
    Returns (recent_messages, new_bot_message_with_markup)."""
    if not msg or not msg.reply_markup or not isinstance(msg.reply_markup, ReplyInlineMarkup):
        return [], None

    entity = await client.get_entity(BOT_USERNAME)
    for row in msg.reply_markup.rows:
        for btn in row.buttons:
            if isinstance(btn, KeyboardButtonCallback) and fragment.lower() in btn.text.lower():
                await msg.click(data=btn.data)
                await asyncio.sleep(wait)
                msgs = list(reversed(await client.get_messages(entity, limit=15)))
                # Find most recent message with inline keyboard from bot
                new_msg = next((m for m in reversed(msgs) if m.reply_markup and isinstance(m.reply_markup, ReplyInlineMarkup)), None)
                return msgs, new_msg

    # Button not found
    return [], None


def find_url_button(msg, fragment: str) -> str | None:
    """Return URL if a URL button containing fragment exists, else None."""
    if not msg or not msg.reply_markup or not isinstance(msg.reply_markup, ReplyInlineMarkup):
        return None
    for row in msg.reply_markup.rows:
        for btn in row.buttons:
            if isinstance(btn, KeyboardButtonUrl) and fragment.lower() in btn.text.lower():
                return btn.url
    return None


def dump_buttons(msg) -> str:
    """Return readable list of all inline buttons."""
    if not msg or not msg.reply_markup or not isinstance(msg.reply_markup, ReplyInlineMarkup):
        return "(no inline keyboard)"
    rows = []
    for row in msg.reply_markup.rows:
        btns = []
        for btn in row.buttons:
            if isinstance(btn, KeyboardButtonUrl):
                btns.append(f"[URL: {btn.text!r} → {btn.url}]")
            elif isinstance(btn, KeyboardButtonCallback):
                btns.append(f"[CB: {btn.text!r}]")
            else:
                btns.append(f"[?: {getattr(btn, 'text', '?')!r}]")
        rows.append(" | ".join(btns))
    return "\n    ".join(rows)


def save_screenshot(name: str, content: str) -> str:
    os.makedirs(SCREENSHOTS_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = os.path.join(SCREENSHOTS_DIR, f"so38_{name}_{ts}.txt")
    with open(path, "w") as f:
        f.write(content)
    return path


# ── Test B: Main Menu ─────────────────────────────────────
async def test_main_menu_community_button(client) -> dict:
    """Verify kb_main() (triggered by '🏠 Menu' sticky tap) has Community URL button."""
    print("\n[Test B] Main menu community button...")
    start = time.time()

    # Send "🏠 Menu" — handle_keyboard_tap sends kb_main() (InlineKeyboardMarkup)
    msgs = await send_text_and_wait(client, "🏠 Menu", wait=5)
    inline_msg = next((m for m in msgs if m.reply_markup and isinstance(m.reply_markup, ReplyInlineMarkup)), None)

    if not inline_msg:
        return {"name": "main_menu_community", "passed": False,
                "msg": "No inline keyboard in 🏠 Menu response", "duration": time.time() - start}

    url = find_url_button(inline_msg, "Community")
    buttons_str = dump_buttons(inline_msg)
    cap = (
        f"Test B — Main Menu Community Button\n{'='*55}\n"
        f"Trigger: '🏠 Menu'\n"
        f"Message text:\n{inline_msg.text or inline_msg.message or '(no text)'}\n\n"
        f"Buttons:\n    {buttons_str}\n\n"
        f"Community URL: {url}\n"
    )
    path = save_screenshot("main_menu", cap)
    print(f"  Buttons:\n    {buttons_str}")
    print(f"  Screenshot: {path}")

    if url and "t.me/MzansiEdge" in url:
        return {"name": "main_menu_community", "passed": True,
                "msg": f"Community URL button found: {url}", "duration": time.time() - start,
                "screenshot": path}
    return {"name": "main_menu_community", "passed": False,
            "msg": f"Community URL button NOT found. Buttons:\n    {buttons_str}",
            "duration": time.time() - start, "screenshot": path}


# ── Test A: Onboarding completion ────────────────────────
async def test_onboarding_community_button(client) -> dict:
    """Complete full onboarding flow and verify community button in completion message."""
    print("\n[Test A] Onboarding completion community button...")
    start = time.time()

    def step(label: str, msg) -> None:
        text = msg.text or msg.message or ""
        print(f"  [{label}] {text[:80]!r}")

    # ── 0. Reset profile ──────────────────────────────────
    print("  Resetting profile...")
    msgs = await send_text_and_wait(client, "/settings", wait=5)
    msg = next((m for m in msgs if m.reply_markup and isinstance(m.reply_markup, ReplyInlineMarkup)), None)
    if not msg:
        return {"name": "onboarding_community", "passed": False,
                "msg": "Could not open /settings", "duration": time.time() - start}

    _, msg = await click_inline_btn(client, msg, "Reset Profile", wait=5)
    if not msg:
        return {"name": "onboarding_community", "passed": False,
                "msg": "Could not find Reset Profile button", "duration": time.time() - start}

    _, msg = await click_inline_btn(client, msg, "Yes, reset", wait=5)
    if not msg:
        return {"name": "onboarding_community", "passed": False,
                "msg": "Could not confirm reset", "duration": time.time() - start}

    step("post-reset", msg)

    # ── 0b. Start onboarding ──────────────────────────────
    _, msg = await click_inline_btn(client, msg, "Start onboarding", wait=5)
    if not msg:
        # Try /start if reset didn't redirect automatically
        msgs = await send_text_and_wait(client, "/start", wait=5)
        msg = next((m for m in msgs if m.reply_markup and isinstance(m.reply_markup, ReplyInlineMarkup)), None)
    if not msg:
        return {"name": "onboarding_community", "passed": False,
                "msg": "Onboarding not started after reset", "duration": time.time() - start}
    step("ob-start", msg)

    # ── 1. Experience: Casual ─────────────────────────────
    print("  Step 1: Experience...")
    _, msg = await click_inline_btn(client, msg, "placed a few bets", wait=STEP_WAIT)
    if not msg:
        _, msg = await click_inline_btn(client, msg, "Casual", wait=STEP_WAIT)
    if not msg:
        return {"name": "onboarding_community", "passed": False,
                "msg": "Could not click experience button", "duration": time.time() - start}
    step("experience", msg)

    # ── 2. Sports: toggle Soccer, click Done ──────────────
    print("  Step 2: Sports...")
    _, msg = await click_inline_btn(client, msg, "Soccer", wait=4)
    if not msg:
        return {"name": "onboarding_community", "passed": False,
                "msg": "Could not click Soccer button", "duration": time.time() - start}
    _, msg2 = await click_inline_btn(client, msg, "Done", wait=STEP_WAIT)
    if msg2:
        msg = msg2
    step("sports", msg)

    # ── 3. Teams: send 'skip' ─────────────────────────────
    print("  Step 3: Teams (skip)...")
    msgs2 = await send_text_and_wait(client, "skip", wait=STEP_WAIT)
    new = next((m for m in msgs2 if m.reply_markup and isinstance(m.reply_markup, ReplyInlineMarkup)), None)
    if new:
        msg = new
    step("teams", msg)

    # ── 4. Edge explainer ─────────────────────────────────
    text_lower = (msg.text or msg.message or "").lower()
    if "edge" in text_lower or "how your edge" in text_lower or "got it" in dump_buttons(msg).lower():
        print("  Step 4: Edge explainer...")
        _, new = await click_inline_btn(client, msg, "Got it", wait=STEP_WAIT)
        if new:
            msg = new
        step("edge-explainer", msg)

    # ── 5. Risk: Moderate ─────────────────────────────────
    print("  Step 5: Risk...")
    _, new = await click_inline_btn(client, msg, "Moderate", wait=STEP_WAIT)
    if not new:
        return {"name": "onboarding_community", "passed": False,
                "msg": "Could not click Moderate risk", "duration": time.time() - start}
    msg = new
    step("risk", msg)

    # ── 6. Bankroll: skip ────────────────────────────────
    print("  Step 6: Bankroll...")
    _, new = await click_inline_btn(client, msg, "Not sure", wait=STEP_WAIT)
    if not new:
        _, new = await click_inline_btn(client, msg, "skip", wait=STEP_WAIT)
    if new:
        msg = new
    step("bankroll", msg)

    # ── 7. Notify: 18:00 ─────────────────────────────────
    print("  Step 7: Notify...")
    _, new = await click_inline_btn(client, msg, "18:00", wait=STEP_WAIT)
    if not new:
        _, new = await click_inline_btn(client, msg, "18", wait=STEP_WAIT)
    if new:
        msg = new
    step("notify", msg)

    # ── 8. Summary: Next ─────────────────────────────────
    print("  Step 8: Summary (Next)...")
    _, new = await click_inline_btn(client, msg, "Next", wait=STEP_WAIT)
    if new:
        msg = new
    step("summary", msg)

    # ── 9. Plan: Bronze (→ handle_ob_done) ───────────────
    print("  Step 9: Plan (Bronze)...")
    _, new = await click_inline_btn(client, msg, "Bronze", wait=LONG_WAIT)
    if not new:
        return {"name": "onboarding_community", "passed": False,
                "msg": "Could not click Bronze plan", "duration": time.time() - start}
    msg = new
    step("plan-bronze", msg)

    # ── 10. Verify community URL button ──────────────────
    url = find_url_button(msg, "Community")
    buttons_str = dump_buttons(msg)
    msg_text = msg.text or msg.message or "(no text)"
    cap = (
        f"Test A — Onboarding Completion Community Button\n{'='*55}\n"
        f"Message text:\n{msg_text[:600]}\n\n"
        f"Buttons:\n    {buttons_str}\n\n"
        f"Community URL: {url}\n"
    )
    path = save_screenshot("onboarding_completion", cap)
    print(f"  Buttons:\n    {buttons_str}")
    print(f"  Screenshot: {path}")

    if url and "t.me/MzansiEdge" in url:
        return {"name": "onboarding_community", "passed": True,
                "msg": f"Community URL button found: {url}", "duration": time.time() - start,
                "screenshot": path}
    return {"name": "onboarding_community", "passed": False,
            "msg": f"Community URL button NOT found. Buttons:\n    {buttons_str}",
            "duration": time.time() - start, "screenshot": path}


# ── Main ──────────────────────────────────────────────────
async def main():
    print(f"\nSO #38 — Community CTA E2E ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})")
    print("=" * 60)

    client = await get_client()
    results = []

    try:
        # Test B first (non-destructive)
        results.append(await test_main_menu_community_button(client))
        # Test A (full onboarding)
        results.append(await test_onboarding_community_button(client))
    finally:
        await client.disconnect()

    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)
    all_passed = True
    for r in results:
        icon = "✅" if r["passed"] else "❌"
        print(f"{icon} [{r['name']}] {r['msg']} ({r['duration']:.1f}s)")
        if "screenshot" in r:
            print(f"   Screenshot: {r['screenshot']}")
        if not r["passed"]:
            all_passed = False

    print()
    print("ALL TESTS PASSED" if all_passed else "TESTS FAILED")
    return results


if __name__ == "__main__":
    results = asyncio.run(main())
    sys.exit(0 if all(r["passed"] for r in results) else 1)
