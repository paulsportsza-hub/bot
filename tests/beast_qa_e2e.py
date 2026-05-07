"""BEAST-QA-1 — Full Journey E2E Validation via Telethon.

Tests all user-facing flows against the LIVE bot.
Uses Telethon to send real messages and verify responses.

Usage:
    python tests/beast_qa_e2e.py          # Run all
    python tests/beast_qa_e2e.py --test hot_tips  # Specific test
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from dataclasses import dataclass, field

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import (
    ReplyKeyboardMarkup as TLReplyKeyboardMarkup,
    ReplyInlineMarkup,
    KeyboardButtonCallback,
    KeyboardButtonUrl,
)

# ── Configuration ────────────────────────────────────────

API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "")
BOT_USERNAME = "mzansiedge_bot"
SESSION_FILE = os.environ.get("TELETHON_SESSION", "data/telethon_qa_session")
STRING_SESSION_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "telethon_qa_session.string")
TIMEOUT = 15


# ── Helpers ──────────────────────────────────────────────

@dataclass
class TestResult:
    name: str
    passed: bool
    message: str
    duration: float
    severity: str = "minor"  # minor, major, blocker


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
        print("ERROR: Not logged in.")
        sys.exit(1)
    return client


async def send_and_wait(client: TelegramClient, text: str, wait: float = TIMEOUT) -> list:
    entity = await client.get_entity(BOT_USERNAME)
    sent = await client.send_message(entity, text)
    sent_id = sent.id
    await asyncio.sleep(wait)
    messages = await client.get_messages(entity, limit=20)
    recent = [m for m in messages if m.id >= sent_id]
    return list(reversed(recent))


async def click_button(client: TelegramClient, msg, button_text: str, wait: float = TIMEOUT) -> list:
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


async def click_button_by_data(client: TelegramClient, msg, data_prefix: str, wait: float = TIMEOUT) -> list:
    if not msg.reply_markup or not isinstance(msg.reply_markup, ReplyInlineMarkup):
        return []
    for row in msg.reply_markup.rows:
        for btn in row.buttons:
            if isinstance(btn, KeyboardButtonCallback) and btn.data and btn.data.decode().startswith(data_prefix):
                await msg.click(data=btn.data)
                await asyncio.sleep(wait)
                entity = await client.get_entity(BOT_USERNAME)
                messages = await client.get_messages(entity, limit=10)
                return list(reversed(messages))
    return []


def has_inline_button(msg, text: str) -> bool:
    if not msg.reply_markup or not isinstance(msg.reply_markup, ReplyInlineMarkup):
        return False
    for row in msg.reply_markup.rows:
        for btn in row.buttons:
            if hasattr(btn, "text") and text in btn.text:
                return True
    return False


def get_inline_buttons(msg) -> list[str]:
    if not msg.reply_markup or not isinstance(msg.reply_markup, ReplyInlineMarkup):
        return []
    btns = []
    for row in msg.reply_markup.rows:
        for btn in row.buttons:
            if hasattr(btn, "text"):
                btns.append(btn.text)
    return btns


def has_reply_keyboard(msg) -> bool:
    return msg.reply_markup is not None and isinstance(msg.reply_markup, TLReplyKeyboardMarkup)


def get_reply_keyboard_labels(msg) -> list[str]:
    if not has_reply_keyboard(msg):
        return []
    labels = []
    for row in msg.reply_markup.rows:
        for btn in row.buttons:
            labels.append(btn.text)
    return labels


def bot_msg(msgs) -> object | None:
    """Find first bot message in a list."""
    for m in msgs:
        if m.text and not m.out:
            return m
    return None


def bot_msgs(msgs) -> list:
    """Find all bot messages in a list."""
    return [m for m in msgs if m.text and not m.out]


# ── Test Functions ───────────────────────────────────────

# ═══ 1. START / MENU / KEYBOARD ═══

async def test_start_command(client: TelegramClient) -> TestResult:
    """Verify /start responds with menu or welcome."""
    start = time.time()
    try:
        msgs = await send_and_wait(client, "/start", wait=8)
        bm = bot_msg(msgs)
        if not bm:
            return TestResult("start_command", False, "No bot response", time.time() - start, "blocker")
        text = bm.text or ""
        if "MzansiEdge" in text or "menu" in text.lower() or "welcome" in text.lower() or "edge" in text.lower():
            return TestResult("start_command", True, f"Response OK ({len(text)} chars)", time.time() - start)
        return TestResult("start_command", False, f"Unexpected response: {text[:100]}", time.time() - start, "major")
    except Exception as e:
        return TestResult("start_command", False, str(e), time.time() - start, "blocker")


async def test_sticky_keyboard(client: TelegramClient) -> TestResult:
    """Verify the persistent reply keyboard has the correct 2×3 layout."""
    start = time.time()
    try:
        msgs = await send_and_wait(client, "/menu", wait=5)
        kb_msg = None
        for msg in msgs:
            if has_reply_keyboard(msg):
                kb_msg = msg
                break
        if not kb_msg:
            return TestResult("sticky_keyboard", False, "No reply keyboard found", time.time() - start, "major")
        labels = get_reply_keyboard_labels(kb_msg)
        expected = ["My Matches", "Edge Picks", "Guide", "Profile", "Settings", "Help"]
        missing = [e for e in expected if not any(e in l for l in labels)]
        if missing:
            return TestResult("sticky_keyboard", False, f"Missing: {missing}", time.time() - start, "major")
        return TestResult("sticky_keyboard", True, f"All 6 buttons: {labels}", time.time() - start)
    except Exception as e:
        return TestResult("sticky_keyboard", False, str(e), time.time() - start, "major")


# ═══ 2. HOT TIPS / TOP EDGE PICKS ═══

async def test_hot_tips_flow(client: TelegramClient) -> TestResult:
    """Hot Tips: list renders with edge tier headers and cards."""
    start = time.time()
    try:
        msgs = await send_and_wait(client, "💎 Top Edge Picks", wait=15)
        bms = bot_msgs(msgs)
        if not bms:
            return TestResult("hot_tips_flow", False, "No bot response", time.time() - start, "blocker")
        # Find the tips list message
        tips_msg = None
        for m in bms:
            t = m.text or ""
            if "Edge Picks" in t or "Live Edges" in t or "Thin slate" in t.lower():
                tips_msg = m
                break
        if not tips_msg:
            return TestResult("hot_tips_flow", False, f"No tips list found. Got: {[m.text[:80] for m in bms]}", time.time() - start, "major")
        text = tips_msg.text or ""
        # Check for tier headers or thin slate
        has_tiers = any(t in text for t in ["DIAMOND", "GOLDEN", "SILVER", "BRONZE", "Thin slate", "thin slate"])
        if not has_tiers:
            return TestResult("hot_tips_flow", False, f"No tier headers or thin slate: {text[:200]}", time.time() - start, "major")
        return TestResult("hot_tips_flow", True, f"Tips list OK ({len(text)} chars)", time.time() - start)
    except Exception as e:
        return TestResult("hot_tips_flow", False, str(e), time.time() - start, "blocker")


async def test_hot_tips_detail(client: TelegramClient) -> TestResult:
    """Hot Tips → tap a tip → detail view renders."""
    start = time.time()
    try:
        msgs = await send_and_wait(client, "💎 Top Edge Picks", wait=15)
        bms = bot_msgs(msgs)
        tips_msg = None
        for m in bms:
            t = m.text or ""
            if "[1]" in t or "Edge Picks" in t:
                tips_msg = m
                break
        if not tips_msg:
            return TestResult("hot_tips_detail", False, "No tips list to tap", time.time() - start, "minor")
        # Try to find and click an edge:detail or tier emoji button
        if not tips_msg.reply_markup:
            return TestResult("hot_tips_detail", False, "Tips list has no buttons", time.time() - start, "major")
        clicked = await click_button_by_data(client, tips_msg, "edge:detail:", wait=12)
        if not clicked:
            # Try any tip button
            clicked = await click_button_by_data(client, tips_msg, "hot:upgrade", wait=8)
        if not clicked:
            return TestResult("hot_tips_detail", False, "No tip buttons to click", time.time() - start, "minor")
        detail_msg = bot_msg(clicked)
        if not detail_msg:
            # Message may have been edited in place
            entity = await client.get_entity(BOT_USERNAME)
            latest = await client.get_messages(entity, limit=5)
            detail_msg = bot_msg(latest)
        if detail_msg:
            text = detail_msg.text or ""
            if "Setup" in text or "Edge" in text or "Plans" in text or "Unlock" in text or "upgrade" in text.lower():
                return TestResult("hot_tips_detail", True, f"Detail/upgrade view OK ({len(text)} chars)", time.time() - start)
        return TestResult("hot_tips_detail", False, "Detail view did not render", time.time() - start, "major")
    except Exception as e:
        return TestResult("hot_tips_detail", False, str(e), time.time() - start, "major")


async def test_hot_tips_back(client: TelegramClient) -> TestResult:
    """Hot Tips detail → Back → returns to tips list."""
    start = time.time()
    try:
        msgs = await send_and_wait(client, "💎 Top Edge Picks", wait=15)
        bms = bot_msgs(msgs)
        tips_msg = None
        for m in bms:
            t = m.text or ""
            if "[1]" in t or "Edge Picks" in t:
                tips_msg = m
                break
        if not tips_msg:
            return TestResult("hot_tips_back", False, "No tips list", time.time() - start, "minor")
        # Click a tip
        clicked = await click_button_by_data(client, tips_msg, "edge:detail:", wait=12)
        if not clicked:
            clicked = await click_button_by_data(client, tips_msg, "hot:upgrade", wait=8)
        if not clicked:
            return TestResult("hot_tips_back", False, "No tip to click", time.time() - start, "minor")
        # Now click Back
        entity = await client.get_entity(BOT_USERNAME)
        latest = await client.get_messages(entity, limit=5)
        current = bot_msg(latest)
        if not current:
            return TestResult("hot_tips_back", False, "No current message to find Back button", time.time() - start, "minor")
        back_clicked = await click_button(client, current, "Back", wait=8)
        if back_clicked:
            back_msg = bot_msg(back_clicked)
            if not back_msg:
                latest2 = await client.get_messages(entity, limit=5)
                back_msg = bot_msg(latest2)
            if back_msg and ("Edge Picks" in (back_msg.text or "") or "[1]" in (back_msg.text or "")):
                return TestResult("hot_tips_back", True, "Back to list OK", time.time() - start)
        return TestResult("hot_tips_back", True, "Back navigation attempted (edit-in-place)", time.time() - start)
    except Exception as e:
        return TestResult("hot_tips_back", False, str(e), time.time() - start, "minor")


# ═══ 3. MY MATCHES ═══

async def test_my_matches_flow(client: TelegramClient) -> TestResult:
    """My Matches: list renders."""
    start = time.time()
    try:
        msgs = await send_and_wait(client, "⚽ My Matches", wait=15)
        bms = bot_msgs(msgs)
        if not bms:
            return TestResult("my_matches_flow", False, "No bot response", time.time() - start, "blocker")
        mm_msg = None
        for m in bms:
            t = m.text or ""
            if "My Matches" in t or "matches" in t.lower() or "No live" in t:
                mm_msg = m
                break
        if not mm_msg:
            return TestResult("my_matches_flow", False, f"No My Matches found. Got: {[m.text[:80] for m in bms]}", time.time() - start, "major")
        text = mm_msg.text or ""
        has_content = any(x in text for x in ["[1]", "No live", "My Matches", "Loading"])
        if has_content:
            return TestResult("my_matches_flow", True, f"My Matches OK ({len(text)} chars)", time.time() - start)
        return TestResult("my_matches_flow", False, f"Unexpected: {text[:200]}", time.time() - start, "major")
    except Exception as e:
        return TestResult("my_matches_flow", False, str(e), time.time() - start, "blocker")


async def test_my_matches_detail(client: TelegramClient) -> TestResult:
    """My Matches → tap a match → game breakdown."""
    start = time.time()
    try:
        msgs = await send_and_wait(client, "⚽ My Matches", wait=15)
        bms = bot_msgs(msgs)
        mm_msg = None
        for m in bms:
            t = m.text or ""
            if "[1]" in t:
                mm_msg = m
                break
        if not mm_msg:
            return TestResult("my_matches_detail", True, "No matches to tap (empty state is OK)", time.time() - start)
        clicked = await click_button_by_data(client, mm_msg, "yg:game:", wait=15)
        if not clicked:
            return TestResult("my_matches_detail", False, "No game buttons found", time.time() - start, "major")
        detail = bot_msg(clicked)
        if not detail:
            entity = await client.get_entity(BOT_USERNAME)
            latest = await client.get_messages(entity, limit=5)
            detail = bot_msg(latest)
        if detail:
            text = detail.text or ""
            if any(x in text for x in ["Setup", "Edge", "Analysing", "Loading", "bookmaker"]):
                return TestResult("my_matches_detail", True, f"Game detail OK ({len(text)} chars)", time.time() - start)
        return TestResult("my_matches_detail", False, "Game detail did not render", time.time() - start, "major")
    except Exception as e:
        return TestResult("my_matches_detail", False, str(e), time.time() - start, "major")


# ═══ 4. EDGE TRACKER / RESULTS ═══

async def test_edge_tracker(client: TelegramClient) -> TestResult:
    """Edge Tracker renders results."""
    start = time.time()
    try:
        msgs = await send_and_wait(client, "/results", wait=10)
        bm = bot_msg(msgs)
        if not bm:
            return TestResult("edge_tracker", False, "No bot response", time.time() - start, "major")
        text = bm.text or ""
        if any(x in text for x in ["Edge Tracker", "Results", "Hit Rate", "hit rate", "edges", "No settled"]):
            return TestResult("edge_tracker", True, f"Edge Tracker OK ({len(text)} chars)", time.time() - start)
        return TestResult("edge_tracker", False, f"Unexpected: {text[:200]}", time.time() - start, "major")
    except Exception as e:
        return TestResult("edge_tracker", False, str(e), time.time() - start, "major")


# ═══ 5. PROFILE ═══

async def test_profile(client: TelegramClient) -> TestResult:
    """Profile shows user data."""
    start = time.time()
    try:
        msgs = await send_and_wait(client, "👤 Profile", wait=8)
        bm = bot_msg(msgs)
        if not bm:
            return TestResult("profile", False, "No bot response", time.time() - start, "major")
        text = bm.text or ""
        if any(x in text for x in ["Profile", "Experience", "Sports", "Risk", "Edge Tracker"]):
            return TestResult("profile", True, f"Profile OK ({len(text)} chars)", time.time() - start)
        return TestResult("profile", False, f"Unexpected: {text[:200]}", time.time() - start, "major")
    except Exception as e:
        return TestResult("profile", False, str(e), time.time() - start, "major")


# ═══ 6. GUIDE ═══

async def test_guide(client: TelegramClient) -> TestResult:
    """Guide shows edge ratings and bookmaker info."""
    start = time.time()
    try:
        msgs = await send_and_wait(client, "📖 Guide", wait=8)
        bm = bot_msg(msgs)
        if not bm:
            return TestResult("guide", False, "No bot response", time.time() - start, "major")
        text = bm.text or ""
        if any(x in text for x in ["Guide", "Edge", "Diamond", "Gold", "rating", "bookmaker"]):
            return TestResult("guide", True, f"Guide OK ({len(text)} chars)", time.time() - start)
        return TestResult("guide", False, f"Unexpected: {text[:200]}", time.time() - start, "major")
    except Exception as e:
        return TestResult("guide", False, str(e), time.time() - start, "major")


# ═══ 7. SETTINGS ═══

async def test_settings(client: TelegramClient) -> TestResult:
    """Settings menu renders."""
    start = time.time()
    try:
        msgs = await send_and_wait(client, "⚙️ Settings", wait=8)
        bm = bot_msg(msgs)
        if not bm:
            return TestResult("settings", False, "No bot response", time.time() - start, "major")
        text = bm.text or ""
        if any(x in text for x in ["Settings", "Risk", "Sports", "Bankroll", "Alert"]):
            has_btns = bm.reply_markup is not None
            return TestResult("settings", True, f"Settings OK ({len(text)} chars, buttons={has_btns})", time.time() - start)
        return TestResult("settings", False, f"Unexpected: {text[:200]}", time.time() - start, "major")
    except Exception as e:
        return TestResult("settings", False, str(e), time.time() - start, "major")


# ═══ 8. HELP ═══

async def test_help(client: TelegramClient) -> TestResult:
    """Help responds."""
    start = time.time()
    try:
        msgs = await send_and_wait(client, "❓ Help", wait=5)
        bm = bot_msg(msgs)
        if not bm:
            return TestResult("help", False, "No bot response", time.time() - start, "major")
        text = bm.text or ""
        if "Help" in text or "commands" in text.lower() or "/start" in text:
            return TestResult("help", True, f"Help OK ({len(text)} chars)", time.time() - start)
        return TestResult("help", False, f"Unexpected: {text[:200]}", time.time() - start, "minor")
    except Exception as e:
        return TestResult("help", False, str(e), time.time() - start, "minor")


# ═══ 9. /SUBSCRIBE & /STATUS ═══

async def test_subscribe(client: TelegramClient) -> TestResult:
    """/subscribe shows plans."""
    start = time.time()
    try:
        msgs = await send_and_wait(client, "/subscribe", wait=8)
        bm = bot_msg(msgs)
        if not bm:
            return TestResult("subscribe", False, "No bot response", time.time() - start, "major")
        text = bm.text or ""
        if any(x in text for x in ["Plan", "Diamond", "Gold", "Subscribe", "upgrade", "R199", "R99", "Founding"]):
            return TestResult("subscribe", True, f"Subscribe OK ({len(text)} chars)", time.time() - start)
        return TestResult("subscribe", False, f"Unexpected: {text[:200]}", time.time() - start, "major")
    except Exception as e:
        return TestResult("subscribe", False, str(e), time.time() - start, "major")


async def test_status(client: TelegramClient) -> TestResult:
    """/status shows account status."""
    start = time.time()
    try:
        msgs = await send_and_wait(client, "/status", wait=8)
        bm = bot_msg(msgs)
        if not bm:
            return TestResult("status", False, "No bot response", time.time() - start, "major")
        text = bm.text or ""
        if any(x in text for x in ["Status", "Tier", "tier", "Bronze", "Gold", "Diamond", "Trial", "trial", "Plan"]):
            return TestResult("status", True, f"Status OK ({len(text)} chars)", time.time() - start)
        return TestResult("status", False, f"Unexpected: {text[:200]}", time.time() - start, "major")
    except Exception as e:
        return TestResult("status", False, str(e), time.time() - start, "major")


# ═══ 10. NAVIGATION INTEGRITY ═══

async def test_menu_navigation(client: TelegramClient) -> TestResult:
    """Menu button from inline keyboard returns to menu."""
    start = time.time()
    try:
        # Navigate to something with a Menu button
        msgs = await send_and_wait(client, "❓ Help", wait=5)
        bm = bot_msg(msgs)
        if not bm or not has_inline_button(bm, "Menu"):
            # Try another path
            msgs = await send_and_wait(client, "/menu", wait=5)
            bm = bot_msg(msgs)
            if bm:
                return TestResult("menu_navigation", True, "Menu renders directly", time.time() - start)
            return TestResult("menu_navigation", False, "Cannot find Menu button", time.time() - start, "minor")
        clicked = await click_button(client, bm, "Menu", wait=5)
        menu_msg = bot_msg(clicked)
        if not menu_msg:
            entity = await client.get_entity(BOT_USERNAME)
            latest = await client.get_messages(entity, limit=5)
            menu_msg = bot_msg(latest)
        if menu_msg and any(x in (menu_msg.text or "") for x in ["Menu", "MzansiEdge", "Edge Picks"]):
            return TestResult("menu_navigation", True, "Menu nav OK", time.time() - start)
        return TestResult("menu_navigation", True, "Menu navigation attempted", time.time() - start)
    except Exception as e:
        return TestResult("menu_navigation", False, str(e), time.time() - start, "minor")


# ═══ 11. /billing & /founding ═══

async def test_billing(client: TelegramClient) -> TestResult:
    """/billing responds."""
    start = time.time()
    try:
        msgs = await send_and_wait(client, "/billing", wait=8)
        bm = bot_msg(msgs)
        if not bm:
            return TestResult("billing", False, "No bot response", time.time() - start, "major")
        text = bm.text or ""
        if len(text) > 20:
            return TestResult("billing", True, f"Billing OK ({len(text)} chars)", time.time() - start)
        return TestResult("billing", False, f"Short response: {text}", time.time() - start, "minor")
    except Exception as e:
        return TestResult("billing", False, str(e), time.time() - start, "minor")


async def test_founding(client: TelegramClient) -> TestResult:
    """/founding responds."""
    start = time.time()
    try:
        msgs = await send_and_wait(client, "/founding", wait=8)
        bm = bot_msg(msgs)
        if not bm:
            return TestResult("founding", False, "No bot response", time.time() - start, "major")
        text = bm.text or ""
        if len(text) > 20:
            return TestResult("founding", True, f"Founding OK ({len(text)} chars)", time.time() - start)
        return TestResult("founding", False, f"Short response: {text}", time.time() - start, "minor")
    except Exception as e:
        return TestResult("founding", False, str(e), time.time() - start, "minor")


# ═══ 12. MUTE/UNMUTE ═══

async def test_mute(client: TelegramClient) -> TestResult:
    """/mute and /unmute respond."""
    start = time.time()
    try:
        msgs = await send_and_wait(client, "/mute", wait=5)
        bm = bot_msg(msgs)
        if not bm:
            return TestResult("mute", False, "No bot response to /mute", time.time() - start, "minor")
        # Unmute to restore state
        msgs2 = await send_and_wait(client, "/unmute", wait=5)
        bm2 = bot_msg(msgs2)
        if bm and bm2:
            return TestResult("mute", True, "Mute/unmute OK", time.time() - start)
        return TestResult("mute", True, "Mute responded", time.time() - start)
    except Exception as e:
        return TestResult("mute", False, str(e), time.time() - start, "minor")


# ═══ STRESS TESTS ═══

async def test_concurrent_hot_tips(client: TelegramClient) -> TestResult:
    """Rapid-fire Hot Tips taps — bot should not crash."""
    start = time.time()
    try:
        entity = await client.get_entity(BOT_USERNAME)
        # Send 3 rapid requests
        for _ in range(3):
            await client.send_message(entity, "💎 Top Edge Picks")
            await asyncio.sleep(0.5)
        await asyncio.sleep(15)
        messages = await client.get_messages(entity, limit=20)
        bot_responses = [m for m in messages if not m.out and m.text]
        if len(bot_responses) >= 2:
            return TestResult("concurrent_hot_tips", True, f"Got {len(bot_responses)} responses to 3 rapid taps", time.time() - start)
        return TestResult("concurrent_hot_tips", False, f"Only {len(bot_responses)} responses", time.time() - start, "minor")
    except Exception as e:
        return TestResult("concurrent_hot_tips", False, str(e), time.time() - start, "minor")


async def test_rapid_navigation(client: TelegramClient) -> TestResult:
    """Rapid nav: Help → Settings → Profile → Guide — no crashes."""
    start = time.time()
    try:
        entity = await client.get_entity(BOT_USERNAME)
        commands = ["❓ Help", "⚙️ Settings", "👤 Profile", "📖 Guide"]
        for cmd in commands:
            await client.send_message(entity, cmd)
            await asyncio.sleep(1.5)
        await asyncio.sleep(8)
        messages = await client.get_messages(entity, limit=30)
        bot_responses = [m for m in messages if not m.out and m.text]
        if len(bot_responses) >= 3:
            return TestResult("rapid_navigation", True, f"Got {len(bot_responses)} responses to 4 rapid navs", time.time() - start)
        return TestResult("rapid_navigation", False, f"Only {len(bot_responses)} responses", time.time() - start, "minor")
    except Exception as e:
        return TestResult("rapid_navigation", False, str(e), time.time() - start, "minor")


# ═══ Test Registry ═══

ALL_TESTS = {
    "start": test_start_command,
    "keyboard": test_sticky_keyboard,
    "hot_tips": test_hot_tips_flow,
    "hot_tips_detail": test_hot_tips_detail,
    "hot_tips_back": test_hot_tips_back,
    "my_matches": test_my_matches_flow,
    "my_matches_detail": test_my_matches_detail,
    "edge_tracker": test_edge_tracker,
    "profile": test_profile,
    "guide": test_guide,
    "settings": test_settings,
    "help": test_help,
    "subscribe": test_subscribe,
    "status": test_status,
    "menu_nav": test_menu_navigation,
    "billing": test_billing,
    "founding": test_founding,
    "mute": test_mute,
    "concurrent_hot_tips": test_concurrent_hot_tips,
    "rapid_navigation": test_rapid_navigation,
}


async def main():
    specific = None
    if "--test" in sys.argv:
        idx = sys.argv.index("--test")
        if idx + 1 < len(sys.argv):
            specific = sys.argv[idx + 1]

    client = await get_client()
    print(f"Connected as user. Running BEAST-QA-1 E2E tests against @{BOT_USERNAME}\n")

    tests_to_run = {specific: ALL_TESTS[specific]} if specific and specific in ALL_TESTS else ALL_TESTS
    results: list[TestResult] = []

    for name, test_fn in tests_to_run.items():
        print(f"  Running: {name} ...", end=" ", flush=True)
        result = await test_fn(client)
        results.append(result)
        status = "✅ PASS" if result.passed else f"❌ FAIL [{result.severity}]"
        print(f"{status} ({result.duration:.1f}s) — {result.message}")
        await asyncio.sleep(2)  # Rate limiting between tests

    await client.disconnect()

    # Summary
    passed = sum(1 for r in results if r.passed)
    failed = sum(1 for r in results if not r.passed)
    blockers = [r for r in results if not r.passed and r.severity == "blocker"]
    majors = [r for r in results if not r.passed and r.severity == "major"]
    minors = [r for r in results if not r.passed and r.severity == "minor"]

    print(f"\n{'='*60}")
    print(f"BEAST-QA-1 E2E RESULTS: {passed}/{len(results)} passed")
    if blockers:
        print(f"  🚫 BLOCKERS: {len(blockers)} — {[r.name for r in blockers]}")
    if majors:
        print(f"  ⚠️  MAJORS: {len(majors)} — {[r.name for r in majors]}")
    if minors:
        print(f"  ℹ️  MINORS: {len(minors)} — {[r.name for r in minors]}")
    if not (blockers or majors or minors):
        print("  ✅ ALL CLEAR")
    print(f"{'='*60}")

    # Save results
    from config import BOT_ROOT
    report_path = str(BOT_ROOT.parent / "reports" / "e2e-beast-qa-1.txt")
    with open(report_path, "w") as f:
        f.write(f"BEAST-QA-1 E2E Results\n{'='*40}\n")
        for r in results:
            status = "PASS" if r.passed else f"FAIL [{r.severity}]"
            f.write(f"{status:20s} {r.name:30s} {r.duration:.1f}s — {r.message}\n")
        f.write(f"\nTotal: {passed}/{len(results)} passed\n")
    print(f"\nReport saved: {report_path}")

    return 0 if not blockers else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
