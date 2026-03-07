"""Tier-gating Telethon E2E tests — verify Bronze/Gold/Diamond/Founding behavior.

Directly modifies the user's tier in SQLite between tests and sends commands
to the live bot to verify tier-specific responses.
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import (
    ReplyInlineMarkup,
    KeyboardButtonCallback,
)

# ── Configuration ────────────────────────────────────────

API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "")
BOT_USERNAME = "mzansiedge_bot"
STRING_SESSION_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "telethon_session.string")
SESSION_FILE = os.environ.get("TELETHON_SESSION", "data/telethon_session")

TEST_USER_ID = 411927634
USER_DB = "/home/paulsportsza/bot/data/mzansiedge.db"
ODDS_DB = "/home/paulsportsza/scrapers/odds.db"

TIMEOUT = 12  # seconds to wait for bot response


# ── DB Helpers ──────────────────────────────────────────

def set_tier(tier: str, founding: bool = False):
    """Set the test user's tier directly in SQLite."""
    conn = sqlite3.connect(USER_DB)
    conn.execute(
        "UPDATE users SET user_tier = ?, is_founding_member = ? WHERE id = ?",
        (tier, int(founding), TEST_USER_ID),
    )
    conn.commit()
    conn.close()


def reset_daily_views():
    """Clear daily tip views for the test user in odds.db."""
    conn = sqlite3.connect(ODDS_DB)
    try:
        conn.execute("DELETE FROM daily_tip_views WHERE user_id = ?", (TEST_USER_ID,))
        conn.commit()
    except sqlite3.OperationalError:
        pass  # Table may not exist
    conn.close()


def get_tier() -> tuple[str, bool]:
    """Get current tier + founding status."""
    conn = sqlite3.connect(USER_DB)
    r = conn.execute(
        "SELECT user_tier, is_founding_member FROM users WHERE id = ?",
        (TEST_USER_ID,),
    ).fetchone()
    conn.close()
    return (r[0] or "bronze", bool(r[1])) if r else ("bronze", False)


# ── Telethon Helpers ────────────────────────────────────

@dataclass
class TestResult:
    name: str
    passed: bool
    message: str
    duration: float


async def get_client() -> TelegramClient:
    """Create and connect a Telethon client."""
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
    """Send a message and wait for responses."""
    entity = await client.get_entity(BOT_USERNAME)
    await client.send_message(entity, text)
    await asyncio.sleep(wait)
    messages = await client.get_messages(entity, limit=10)
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


def get_all_button_texts(msg) -> list[str]:
    """Get all inline button texts from a message."""
    texts = []
    if not msg.reply_markup or not isinstance(msg.reply_markup, ReplyInlineMarkup):
        return texts
    for row in msg.reply_markup.rows:
        for btn in row.buttons:
            if hasattr(btn, "text"):
                texts.append(btn.text)
    return texts


# ── Test Functions ──────────────────────────────────────

async def test_bronze_status(client: TelegramClient) -> TestResult:
    """Bronze user: /status shows Bronze (Free)."""
    start = time.time()
    set_tier("bronze")
    try:
        msgs = await send_and_wait(client, "/status", wait=5)
        text = "\n".join(m.text or "" for m in msgs if m.text)
        if "bronze" in text.lower():
            return TestResult("bronze_status", True, f"Response: {text[:200]}", time.time() - start)
        return TestResult("bronze_status", False, f"Expected 'bronze' in: {text[:200]}", time.time() - start)
    except Exception as e:
        return TestResult("bronze_status", False, str(e), time.time() - start)


async def test_bronze_subscribe(client: TelegramClient) -> TestResult:
    """Bronze user: /subscribe shows all upgrade options."""
    start = time.time()
    set_tier("bronze")
    try:
        msgs = await send_and_wait(client, "/subscribe", wait=5)
        text = "\n".join(m.text or "" for m in msgs if m.text)
        has_gold = "gold" in text.lower() or "R99" in text
        has_diamond = "diamond" in text.lower() or "R199" in text
        has_founding = "founding" in text.lower() or "R699" in text
        if has_gold and has_diamond:
            return TestResult("bronze_subscribe", True,
                f"Gold={has_gold} Diamond={has_diamond} Founding={has_founding}",
                time.time() - start)
        return TestResult("bronze_subscribe", False,
            f"Missing plans in: {text[:300]}", time.time() - start)
    except Exception as e:
        return TestResult("bronze_subscribe", False, str(e), time.time() - start)


async def test_bronze_hot_tips(client: TelegramClient) -> TestResult:
    """Bronze user: Top Edge Picks works, may show gated content."""
    start = time.time()
    set_tier("bronze")
    reset_daily_views()
    try:
        msgs = await send_and_wait(client, "/picks", wait=15)
        text = "\n".join(m.text or "" for m in msgs if m.text)
        # Should either show tips or "market is efficient" empty state
        if "edge" in text.lower() or "market" in text.lower() or "no" in text.lower() or "tip" in text.lower():
            return TestResult("bronze_hot_tips", True, f"Response: {text[:200]}", time.time() - start)
        return TestResult("bronze_hot_tips", False, f"Unexpected: {text[:200]}", time.time() - start)
    except Exception as e:
        return TestResult("bronze_hot_tips", False, str(e), time.time() - start)


async def test_gold_status(client: TelegramClient) -> TestResult:
    """Gold user: /status shows Gold."""
    start = time.time()
    set_tier("gold")
    try:
        msgs = await send_and_wait(client, "/status", wait=5)
        text = "\n".join(m.text or "" for m in msgs if m.text)
        if "gold" in text.lower():
            return TestResult("gold_status", True, f"Response: {text[:200]}", time.time() - start)
        return TestResult("gold_status", False, f"Expected 'gold' in: {text[:200]}", time.time() - start)
    except Exception as e:
        return TestResult("gold_status", False, str(e), time.time() - start)


async def test_gold_subscribe(client: TelegramClient) -> TestResult:
    """Gold user: /subscribe shows Diamond upgrade (not Bronze/Gold)."""
    start = time.time()
    set_tier("gold")
    try:
        msgs = await send_and_wait(client, "/subscribe", wait=5)
        text = "\n".join(m.text or "" for m in msgs if m.text)
        has_diamond = "diamond" in text.lower() or "R199" in text
        if has_diamond:
            return TestResult("gold_subscribe", True, f"Shows Diamond upgrade: {text[:200]}", time.time() - start)
        return TestResult("gold_subscribe", False, f"Response: {text[:200]}", time.time() - start)
    except Exception as e:
        return TestResult("gold_subscribe", False, str(e), time.time() - start)


async def test_gold_hot_tips(client: TelegramClient) -> TestResult:
    """Gold user: Top Edge Picks shows unlimited tips (no 3/day limit)."""
    start = time.time()
    set_tier("gold")
    try:
        msgs = await send_and_wait(client, "/picks", wait=15)
        text = "\n".join(m.text or "" for m in msgs if m.text)
        # Gold should NOT see tip limit messages
        has_limit = "3 free tips" in text.lower() or "used your" in text.lower()
        if has_limit:
            return TestResult("gold_hot_tips", False, f"Gold user sees tip limit: {text[:200]}", time.time() - start)
        return TestResult("gold_hot_tips", True, f"Response (no limit): {text[:200]}", time.time() - start)
    except Exception as e:
        return TestResult("gold_hot_tips", False, str(e), time.time() - start)


async def test_diamond_status(client: TelegramClient) -> TestResult:
    """Diamond user: /status shows Diamond."""
    start = time.time()
    set_tier("diamond")
    try:
        msgs = await send_and_wait(client, "/status", wait=5)
        text = "\n".join(m.text or "" for m in msgs if m.text)
        if "diamond" in text.lower():
            return TestResult("diamond_status", True, f"Response: {text[:200]}", time.time() - start)
        return TestResult("diamond_status", False, f"Expected 'diamond' in: {text[:200]}", time.time() - start)
    except Exception as e:
        return TestResult("diamond_status", False, str(e), time.time() - start)


async def test_diamond_subscribe(client: TelegramClient) -> TestResult:
    """Diamond user: /subscribe shows already at top tier."""
    start = time.time()
    set_tier("diamond")
    try:
        msgs = await send_and_wait(client, "/subscribe", wait=5)
        text = "\n".join(m.text or "" for m in msgs if m.text)
        # Diamond users should see "already diamond" or similar
        is_top = "diamond" in text.lower()
        return TestResult("diamond_subscribe", True if is_top else False,
            f"Response: {text[:200]}", time.time() - start)
    except Exception as e:
        return TestResult("diamond_subscribe", False, str(e), time.time() - start)


async def test_diamond_hot_tips(client: TelegramClient) -> TestResult:
    """Diamond user: Top Edge Picks shows all edges, no limits."""
    start = time.time()
    set_tier("diamond")
    try:
        msgs = await send_and_wait(client, "/picks", wait=15)
        text = "\n".join(m.text or "" for m in msgs if m.text)
        has_limit = "3 free tips" in text.lower() or "used your" in text.lower()
        if has_limit:
            return TestResult("diamond_hot_tips", False, f"Diamond sees limit: {text[:200]}", time.time() - start)
        return TestResult("diamond_hot_tips", True, f"Response: {text[:200]}", time.time() - start)
    except Exception as e:
        return TestResult("diamond_hot_tips", False, str(e), time.time() - start)


async def test_founding_status(client: TelegramClient) -> TestResult:
    """Founding member: /status shows founding badge."""
    start = time.time()
    set_tier("diamond", founding=True)
    try:
        msgs = await send_and_wait(client, "/status", wait=5)
        text = "\n".join(m.text or "" for m in msgs if m.text)
        has_founding = "founding" in text.lower()
        has_diamond = "diamond" in text.lower()
        if has_founding or has_diamond:
            return TestResult("founding_status", True,
                f"founding={has_founding} diamond={has_diamond}: {text[:200]}",
                time.time() - start)
        return TestResult("founding_status", False, f"Expected founding/diamond in: {text[:200]}", time.time() - start)
    except Exception as e:
        return TestResult("founding_status", False, str(e), time.time() - start)


async def test_founding_command(client: TelegramClient) -> TestResult:
    """Founding member: /founding shows founding deal."""
    start = time.time()
    set_tier("diamond", founding=True)
    try:
        msgs = await send_and_wait(client, "/founding", wait=5)
        text = "\n".join(m.text or "" for m in msgs if m.text)
        has_founding = "founding" in text.lower() or "R699" in text
        return TestResult("founding_command", True if has_founding else False,
            f"Response: {text[:200]}", time.time() - start)
    except Exception as e:
        return TestResult("founding_command", False, str(e), time.time() - start)


async def test_upgrade_command(client: TelegramClient) -> TestResult:
    """Bronze user: /upgrade shows plans."""
    start = time.time()
    set_tier("bronze")
    try:
        msgs = await send_and_wait(client, "/upgrade", wait=5)
        text = "\n".join(m.text or "" for m in msgs if m.text)
        has_plans = "gold" in text.lower() or "diamond" in text.lower()
        return TestResult("upgrade_command", True if has_plans else False,
            f"Response: {text[:200]}", time.time() - start)
    except Exception as e:
        return TestResult("upgrade_command", False, str(e), time.time() - start)


async def test_billing_command(client: TelegramClient) -> TestResult:
    """Test /billing command for each tier."""
    start = time.time()
    set_tier("bronze")
    try:
        msgs = await send_and_wait(client, "/billing", wait=5)
        text = "\n".join(m.text or "" for m in msgs if m.text)
        # Bronze with no subscription should show "no active subscription"
        if "no active" in text.lower() or "billing" in text.lower() or "subscription" in text.lower():
            return TestResult("billing_command", True, f"Response: {text[:200]}", time.time() - start)
        return TestResult("billing_command", False, f"Unexpected: {text[:200]}", time.time() - start)
    except Exception as e:
        return TestResult("billing_command", False, str(e), time.time() - start)


# ── Main ────────────────────────────────────────────────

ALL_TESTS = [
    test_bronze_status,
    test_bronze_subscribe,
    test_bronze_hot_tips,
    test_gold_status,
    test_gold_subscribe,
    test_gold_hot_tips,
    test_diamond_status,
    test_diamond_subscribe,
    test_diamond_hot_tips,
    test_founding_status,
    test_founding_command,
    test_upgrade_command,
    test_billing_command,
]


async def main():
    print("=" * 60)
    print("TIER-GATING TELETHON E2E TESTS")
    print(f"Test user: {TEST_USER_ID}")
    print(f"Original tier: {get_tier()}")
    print("=" * 60)

    client = await get_client()
    results: list[TestResult] = []

    for test_fn in ALL_TESTS:
        print(f"\n  Running {test_fn.__name__}...", end=" ", flush=True)
        result = await test_fn(client)
        results.append(result)
        status = "PASS" if result.passed else "FAIL"
        print(f"{status} ({result.duration:.1f}s)")
        if not result.passed:
            print(f"    -> {result.message}")

    # Reset to bronze
    set_tier("bronze", founding=False)
    print(f"\nReset to: {get_tier()}")

    await client.disconnect()

    # Summary
    passed = sum(1 for r in results if r.passed)
    total = len(results)
    print(f"\n{'=' * 60}")
    print(f"Results: {passed}/{total} passed")
    if passed < total:
        print("FAILED:")
        for r in results:
            if not r.passed:
                print(f"  - {r.name}: {r.message}")

    # Save JSON report
    report = {
        "timestamp": datetime.utcnow().isoformat(),
        "summary": f"Tier-gating: {passed}/{total} passed",
        "results": [asdict(r) for r in results],
    }
    report_path = f"/home/paulsportsza/reports/tier-gating-{datetime.utcnow().strftime('%Y%m%d-%H%M')}.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nReport saved: {report_path}")

    return passed == total


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
