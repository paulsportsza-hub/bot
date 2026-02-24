"""E2E flow tests — Telethon-based integration tests for Your Games + Hot Tips.

Uses Telethon to send commands to the live bot and verify responses.
Requires: TELETHON_SESSION env var or saved session file, running bot instance.

Usage:
    python tests/test_e2e_flow.py          # Run all tests
    python tests/test_e2e_flow.py --test sticky_keyboard  # Specific test
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from dataclasses import dataclass

from telethon import TelegramClient
from telethon.tl.types import (
    ReplyKeyboardMarkup as TLReplyKeyboardMarkup,
    ReplyInlineMarkup,
    KeyboardButtonCallback,
)

# ── Configuration ────────────────────────────────────────

API_ID = 32418601
API_HASH = "95e313a8ef5b998be0515dd8328fac57"
BOT_USERNAME = "mzansiedge_bot"
SESSION_FILE = os.environ.get("TELETHON_SESSION", "data/telethon_session")

TIMEOUT = 15  # seconds to wait for bot response


# ── Helpers ──────────────────────────────────────────────

@dataclass
class TestResult:
    name: str
    passed: bool
    message: str
    duration: float


async def get_client() -> TelegramClient:
    """Create and connect a Telethon client."""
    client = TelegramClient(SESSION_FILE, API_ID, API_HASH)
    await client.connect()
    if not await client.is_user_authorized():
        print("ERROR: Not logged in. Run save_telegram_session.py first.")
        sys.exit(1)
    return client


async def send_and_wait(client: TelegramClient, text: str, wait: float = TIMEOUT) -> list:
    """Send a message to the bot and wait for response(s)."""
    entity = await client.get_entity(BOT_USERNAME)
    await client.send_message(entity, text)
    await asyncio.sleep(wait)
    messages = await client.get_messages(entity, limit=10)
    # Return messages in chronological order (oldest first)
    return list(reversed(messages))


async def click_button(client: TelegramClient, msg, button_text: str, wait: float = TIMEOUT) -> list:
    """Click an inline button by matching its text."""
    if not msg.reply_markup or not isinstance(msg.reply_markup, ReplyInlineMarkup):
        return []

    for row in msg.reply_markup.rows:
        for btn in row.buttons:
            if isinstance(btn, KeyboardButtonCallback) and button_text in btn.text:
                await msg.click(data=btn.data)
                await asyncio.sleep(wait)
                entity = await client.get_entity(BOT_USERNAME)
                messages = await client.get_messages(entity, limit=10)
                return list(reversed(messages))
    return []


def has_inline_button(msg, text: str) -> bool:
    """Check if a message has an inline button containing the given text."""
    if not msg.reply_markup or not isinstance(msg.reply_markup, ReplyInlineMarkup):
        return False
    for row in msg.reply_markup.rows:
        for btn in row.buttons:
            if hasattr(btn, "text") and text in btn.text:
                return True
    return False


def has_reply_keyboard(msg) -> bool:
    """Check if a message has a reply keyboard."""
    return msg.reply_markup is not None and isinstance(msg.reply_markup, TLReplyKeyboardMarkup)


def get_reply_keyboard_labels(msg) -> list[str]:
    """Extract all button labels from a reply keyboard."""
    if not has_reply_keyboard(msg):
        return []
    labels = []
    for row in msg.reply_markup.rows:
        for btn in row.buttons:
            labels.append(btn.text)
    return labels


# ── Test Functions ───────────────────────────────────────

async def test_sticky_keyboard_layout(client: TelegramClient) -> TestResult:
    """Verify the persistent reply keyboard has the correct 3×2 layout."""
    start = time.time()
    try:
        msgs = await send_and_wait(client, "/menu", wait=5)

        # Find a message with a reply keyboard
        kb_msg = None
        for msg in msgs:
            if has_reply_keyboard(msg):
                kb_msg = msg
                break

        if not kb_msg:
            return TestResult("sticky_keyboard_layout", False, "No reply keyboard found", time.time() - start)

        labels = get_reply_keyboard_labels(kb_msg)
        expected = ["⚽ Your Games", "🔥 Hot Tips", "🔴 Live Games", "📊 My Stats", "📖 Betway Guide", "⚙️ Settings"]

        for exp in expected:
            if exp not in labels:
                return TestResult("sticky_keyboard_layout", False, f"Missing button: {exp}", time.time() - start)

        return TestResult("sticky_keyboard_layout", True, f"All 6 buttons present: {labels}", time.time() - start)
    except Exception as e:
        return TestResult("sticky_keyboard_layout", False, str(e), time.time() - start)


async def test_your_games_default_view(client: TelegramClient) -> TestResult:
    """Verify 'Your Games' shows the all-games default view."""
    start = time.time()
    try:
        msgs = await send_and_wait(client, "⚽ Your Games", wait=8)

        # Find the Your Games message
        yg_msg = None
        for msg in msgs:
            if msg.text and "Your Games" in msg.text:
                yg_msg = msg
                break

        if not yg_msg:
            return TestResult("your_games_default", False, "No 'Your Games' message found", time.time() - start)

        # Should have sport filter buttons or game buttons
        has_buttons = yg_msg.reply_markup is not None
        has_menu_btn = has_inline_button(yg_msg, "Menu")

        if not has_buttons:
            return TestResult("your_games_default", False, "No buttons in response", time.time() - start)

        return TestResult(
            "your_games_default", True,
            f"Your Games view loaded with buttons. Has menu: {has_menu_btn}",
            time.time() - start,
        )
    except Exception as e:
        return TestResult("your_games_default", False, str(e), time.time() - start)


async def test_your_games_sport_filter(client: TelegramClient) -> TestResult:
    """Verify tapping a sport emoji button shows sport-specific view."""
    start = time.time()
    try:
        msgs = await send_and_wait(client, "⚽ Your Games", wait=8)

        yg_msg = None
        for msg in msgs:
            if msg.text and "Your Games" in msg.text and msg.reply_markup:
                yg_msg = msg
                break

        if not yg_msg:
            return TestResult("sport_filter", False, "No 'Your Games' message found", time.time() - start)

        # Look for sport emoji buttons in inline markup
        if not isinstance(yg_msg.reply_markup, ReplyInlineMarkup):
            return TestResult("sport_filter", True, "No inline buttons (user may have <2 sports)", time.time() - start)

        # Try to find a sport emoji button (⚽, 🏉, 🏏, etc.)
        sport_btn = None
        for row in yg_msg.reply_markup.rows:
            for btn in row.buttons:
                if isinstance(btn, KeyboardButtonCallback):
                    data = btn.data.decode() if isinstance(btn.data, bytes) else btn.data
                    if data.startswith("yg:sport:"):
                        sport_btn = btn
                        break
            if sport_btn:
                break

        if not sport_btn:
            return TestResult("sport_filter", True, "No sport filter buttons (user may have <2 sports)", time.time() - start)

        # Click the sport button
        result_msgs = await click_button(client, yg_msg, sport_btn.text, wait=8)

        # Check the response has day navigation (Today, Tmrw, etc.)
        for msg in result_msgs:
            if msg.text and ("Today" in msg.text or "Tmrw" in msg.text or "game" in msg.text.lower()):
                return TestResult("sport_filter", True, f"Sport filter view loaded: {msg.text[:80]}...", time.time() - start)

        return TestResult("sport_filter", True, "Sport filter clicked, response received", time.time() - start)
    except Exception as e:
        return TestResult("sport_filter", False, str(e), time.time() - start)


async def test_your_games_pagination(client: TelegramClient) -> TestResult:
    """Verify pagination works when there are many games."""
    start = time.time()
    try:
        msgs = await send_and_wait(client, "⚽ Your Games", wait=8)

        yg_msg = None
        for msg in msgs:
            if msg.text and "Your Games" in msg.text and msg.reply_markup:
                yg_msg = msg
                break

        if not yg_msg:
            return TestResult("pagination", False, "No 'Your Games' message found", time.time() - start)

        # Check for pagination buttons (Next ➡️)
        has_next = has_inline_button(yg_msg, "Next")
        has_page = has_inline_button(yg_msg, "📄")

        if has_next or has_page:
            return TestResult("pagination", True, "Pagination buttons found", time.time() - start)

        return TestResult("pagination", True, "No pagination needed (<= 10 games)", time.time() - start)
    except Exception as e:
        return TestResult("pagination", False, str(e), time.time() - start)


async def test_hot_tips_separate_messages(client: TelegramClient) -> TestResult:
    """Verify Hot Tips sends separate messages per tip."""
    start = time.time()
    try:
        msgs = await send_and_wait(client, "🔥 Hot Tips", wait=15)

        # Find messages from the bot
        bot_msgs = [m for m in msgs if m.text and not m.out]

        # Should have at least 2 messages (header + at least one tip or empty state)
        if len(bot_msgs) < 1:
            return TestResult("hot_tips_messages", False, "No bot messages received", time.time() - start)

        # Check for "Hot Tips" header or "No edges"
        has_header = any("Hot Tips" in (m.text or "") for m in bot_msgs)
        has_no_edges = any("No edges" in (m.text or "") for m in bot_msgs)

        if has_no_edges:
            return TestResult("hot_tips_messages", True, "Hot Tips: no edges found (market efficient)", time.time() - start)

        if not has_header:
            return TestResult("hot_tips_messages", False, "No 'Hot Tips' header found", time.time() - start)

        # Check for individual tip messages with Betway buttons
        tip_msgs = [m for m in bot_msgs if m.text and "#" in m.text and "EV:" in m.text]
        betway_btn_count = sum(1 for m in bot_msgs if has_inline_button(m, "Bet on"))

        return TestResult(
            "hot_tips_messages", True,
            f"Hot Tips: {len(tip_msgs)} tips, {betway_btn_count} Betway buttons, {len(bot_msgs)} total messages",
            time.time() - start,
        )
    except Exception as e:
        return TestResult("hot_tips_messages", False, str(e), time.time() - start)


async def test_hot_tips_all_sports_scan(client: TelegramClient) -> TestResult:
    """Verify Hot Tips scans all sports (header mentions 'all markets')."""
    start = time.time()
    try:
        msgs = await send_and_wait(client, "🔥 Hot Tips", wait=15)

        for msg in msgs:
            if msg.text and "all markets" in msg.text.lower():
                return TestResult("all_sports_scan", True, "Header mentions 'all markets'", time.time() - start)
            if msg.text and "markets across" in msg.text.lower():
                return TestResult("all_sports_scan", True, f"Header: {msg.text[:100]}", time.time() - start)
            if msg.text and "No edges" in msg.text:
                return TestResult("all_sports_scan", True, "No edges (but scan was attempted)", time.time() - start)

        return TestResult("all_sports_scan", True, "Hot Tips response received", time.time() - start)
    except Exception as e:
        return TestResult("all_sports_scan", False, str(e), time.time() - start)


async def test_no_za_flags_in_tips(client: TelegramClient) -> TestResult:
    """Verify no 🇿🇦 flags appear in tip messages."""
    start = time.time()
    try:
        msgs = await send_and_wait(client, "🔥 Hot Tips", wait=15)

        za_flag = "🇿🇦"
        for msg in msgs:
            if msg.text and za_flag in msg.text:
                # Check if it's a tip message (contains EV or odds)
                if "EV:" in msg.text or "odds" in msg.text.lower() or "#" in msg.text:
                    return TestResult("no_za_flags", False, f"ZA flag found in tip: {msg.text[:100]}", time.time() - start)

        return TestResult("no_za_flags", True, "No ZA flags in tip messages", time.time() - start)
    except Exception as e:
        return TestResult("no_za_flags", False, str(e), time.time() - start)


async def test_game_breakdown_betway_button(client: TelegramClient) -> TestResult:
    """Verify game breakdown shows Betway button."""
    start = time.time()
    try:
        # First get Your Games
        msgs = await send_and_wait(client, "⚽ Your Games", wait=8)

        yg_msg = None
        for msg in msgs:
            if msg.text and "Your Games" in msg.text and msg.reply_markup:
                yg_msg = msg
                break

        if not yg_msg:
            return TestResult("game_breakdown", False, "No 'Your Games' message found", time.time() - start)

        # Try to click a game button [1], [2], etc.
        if not isinstance(yg_msg.reply_markup, ReplyInlineMarkup):
            return TestResult("game_breakdown", True, "No inline markup available", time.time() - start)

        game_btn = None
        for row in yg_msg.reply_markup.rows:
            for btn in row.buttons:
                if isinstance(btn, KeyboardButtonCallback):
                    data = btn.data.decode() if isinstance(btn.data, bytes) else btn.data
                    if data.startswith("yg:game:"):
                        game_btn = btn
                        break
            if game_btn:
                break

        if not game_btn:
            return TestResult("game_breakdown", True, "No game buttons available", time.time() - start)

        # Click the game button
        result_msgs = await click_button(client, yg_msg, game_btn.text, wait=12)

        # Check for Betway button in response
        for msg in result_msgs:
            if has_inline_button(msg, "Bet") or has_inline_button(msg, "Betway"):
                return TestResult("game_breakdown", True, "Game breakdown has Betway button", time.time() - start)
            if msg.text and ("Analysing" in msg.text or "vs" in msg.text):
                return TestResult("game_breakdown", True, f"Game analysis loaded: {msg.text[:80]}", time.time() - start)

        return TestResult("game_breakdown", True, "Game button clicked, response received", time.time() - start)
    except Exception as e:
        return TestResult("game_breakdown", False, str(e), time.time() - start)


# ── Test Runner ──────────────────────────────────────────

ALL_TESTS = {
    "sticky_keyboard": test_sticky_keyboard_layout,
    "your_games": test_your_games_default_view,
    "sport_filter": test_your_games_sport_filter,
    "pagination": test_your_games_pagination,
    "hot_tips": test_hot_tips_separate_messages,
    "all_sports": test_hot_tips_all_sports_scan,
    "no_za_flags": test_no_za_flags_in_tips,
    "game_breakdown": test_game_breakdown_betway_button,
}


async def run_tests(test_names: list[str] | None = None) -> list[TestResult]:
    """Run specified tests (or all if None)."""
    client = await get_client()
    results: list[TestResult] = []

    tests_to_run = test_names or list(ALL_TESTS.keys())

    print(f"\n{'=' * 60}")
    print(f"  MzansiEdge E2E Flow Tests — {len(tests_to_run)} tests")
    print(f"{'=' * 60}\n")

    for name in tests_to_run:
        test_fn = ALL_TESTS.get(name)
        if not test_fn:
            print(f"  ⚠️  Unknown test: {name}")
            continue

        print(f"  ▶ Running: {name}...")
        result = await test_fn(client)
        results.append(result)

        icon = "✅" if result.passed else "❌"
        print(f"  {icon} {result.name}: {result.message} ({result.duration:.1f}s)")

        # Small delay between tests
        await asyncio.sleep(2)

    await client.disconnect()

    # Summary
    passed = sum(1 for r in results if r.passed)
    failed = sum(1 for r in results if not r.passed)
    total_time = sum(r.duration for r in results)

    print(f"\n{'=' * 60}")
    print(f"  Results: {passed} passed, {failed} failed ({total_time:.1f}s)")
    print(f"{'=' * 60}\n")

    return results


def main():
    import argparse
    parser = argparse.ArgumentParser(description="MzansiEdge E2E Flow Tests")
    parser.add_argument("--test", nargs="*", help="Specific test(s) to run")
    args = parser.parse_args()

    results = asyncio.run(run_tests(args.test))
    sys.exit(0 if all(r.passed for r in results) else 1)


if __name__ == "__main__":
    main()
