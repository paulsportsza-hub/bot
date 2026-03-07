#!/usr/bin/env python3
"""W35-MONITOR: E2E tests for all 3 monitoring layers via Telethon.

Tests:
  1A: /qa health shows full status with 10 checks
  1B: (Simulated failure tested separately via CLI)
  2A: /qa morning produces the report
  3B: /qa validate runs on demand
"""

import asyncio
import os
import re
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from telethon import TelegramClient
from telethon.sessions import StringSession

API_ID = int(os.environ.get("TELEGRAM_API_ID", "0"))
API_HASH = os.environ.get("TELEGRAM_API_HASH", "")
SESSION_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "telethon_session")
STRING_SESSION_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "telethon_session.string")
BOT = "mzansiedge_bot"


async def get_client() -> TelegramClient:
    """Create and connect a Telethon client. Prefers string session."""
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

RESULTS: list[tuple[str, bool, str]] = []


def record(test_id: str, passed: bool, detail: str):
    RESULTS.append((test_id, passed, detail))
    emoji = "\u2705" if passed else "\u274c"
    print(f"{emoji} {test_id}: {detail}")


async def send_and_capture(client, text, wait=8, count=1):
    """Send text to bot and capture response(s)."""
    await client.send_message(BOT, text)
    await asyncio.sleep(wait)
    messages = await client.get_messages(BOT, limit=count + 2)
    # Filter to messages FROM the bot (not our own)
    bot_msgs = [m for m in messages if m.out is False]
    return bot_msgs[:count]


async def test_1a_qa_health(client):
    """Test 1A: /qa health shows full status with all checks."""
    msgs = await send_and_capture(client, "/qa health", wait=15, count=3)
    if not msgs:
        record("1A", False, "No response from /qa health")
        return

    # Find the health check message (contains "System Health" or "Health")
    text = None
    for m in msgs:
        t = m.text or ""
        if "System Health" in t or ("Health" in t and ("Sharp" in t or "bookmaker" in t.lower())):
            text = t
            break
    if text is None:
        # Fallback to most recent bot message
        text = msgs[0].text or ""

    # Must contain "System Health" header
    has_header = "System Health" in text
    record("1A-header", has_header, f"Header present: {has_header}")

    # Count check lines (lines with check/cross emoji)
    check_lines = [l for l in text.split("\n") if "\u2705" in l or "\u274c" in l]
    has_10 = len(check_lines) >= 10
    record("1A-count", has_10, f"{len(check_lines)} checks listed (need >= 10)")

    # Must include proxy check
    has_proxy = "proxy" in text.lower() or "Bright Data" in text
    record("1A-proxy", has_proxy, f"Proxy check: {'found' if has_proxy else 'NOT found'}")

    # Must include key checks
    key_checks = ["Sharp", "bookmaker", "edge", "Settlement", "Bot process", "Cron"]
    found = [k for k in key_checks if k.lower() in text.lower()]
    all_found = len(found) >= 5
    record("1A-keys", all_found, f"Key checks found: {', '.join(found)}")

    # Save capture
    capture_dir = os.path.expanduser("~/reports/screenshots/w35_monitor")
    os.makedirs(capture_dir, exist_ok=True)
    with open(os.path.join(capture_dir, "qa_health.txt"), "w") as f:
        f.write(text)


async def test_2a_qa_morning(client):
    """Test 2A: /qa morning produces the report."""
    msgs = await send_and_capture(client, "/qa morning", wait=15, count=1)
    if not msgs:
        record("2A", False, "No response from /qa morning")
        return

    text = msgs[0].text or ""

    # Must contain "Morning Report" header
    has_header = "Morning Report" in text
    record("2A-header", has_header, f"Header: {'found' if has_header else 'NOT found'}")

    # Required sections
    has_edges = "Edges:" in text or "edges" in text.lower()
    record("2A-edges", has_edges, f"Edge count: {'found' if has_edges else 'NOT found'}")

    has_sharp = "Sharp" in text
    record("2A-sharp", has_sharp, f"Sharp data: {'found' if has_sharp else 'NOT found'}")

    has_settlement = "Yesterday" in text or "settled" in text.lower()
    record("2A-settlement", has_settlement, f"Settlement: {'found' if has_settlement else 'NOT found'}")

    has_health = "healthy" in text.lower() or "\u26a0" in text or "\u2705" in text
    record("2A-health", has_health, f"Health status: {'found' if has_health else 'NOT found'}")

    has_uptime = "uptime" in text.lower() or "PID" in text
    record("2A-uptime", has_uptime, f"Bot uptime: {'found' if has_uptime else 'NOT found'}")

    has_factcheck = "Fact-checker" in text or "stripped" in text.lower()
    record("2A-factcheck", has_factcheck, f"Fact-checker: {'found' if has_factcheck else 'NOT found'}")

    # Line count (should be under 15 content lines)
    content_lines = [l for l in text.split("\n") if l.strip()]
    under_15 = len(content_lines) <= 15
    record("2A-compact", under_15, f"{len(content_lines)} content lines (max 15)")

    # Save capture
    capture_dir = os.path.expanduser("~/reports/screenshots/w35_monitor")
    os.makedirs(capture_dir, exist_ok=True)
    with open(os.path.join(capture_dir, "qa_morning.txt"), "w") as f:
        f.write(text)


async def test_3b_qa_validate(client):
    """Test 3B: /qa validate runs on demand."""
    msgs = await send_and_capture(client, "/qa validate", wait=25, count=2)
    if not msgs:
        record("3B", False, "No response from /qa validate")
        return

    # Get the final message (not the loading one)
    text = msgs[0].text or ""

    # Must contain validation results
    has_validation = "validation" in text.lower() or "PASS" in text or "FAIL" in text
    record("3B-result", has_validation, f"Validation result: {'found' if has_validation else 'NOT found'}")

    # Must show pass/fail count
    ratio_match = re.search(r"(\d+)/(\d+)", text)
    if ratio_match:
        passed = int(ratio_match.group(1))
        total = int(ratio_match.group(2))
        record("3B-count", total >= 20, f"{passed}/{total} checks (need >= 20 total)")
    else:
        record("3B-count", False, "No pass/fail ratio found")

    # If failures present, should have specific descriptions
    if "FAIL" in text:
        has_detail = "\u274c" in text
        record("3B-detail", has_detail, f"Failure details: {'present' if has_detail else 'NOT found'}")
    else:
        record("3B-detail", True, "All passed — no failure details needed")

    # Save capture
    capture_dir = os.path.expanduser("~/reports/screenshots/w35_monitor")
    os.makedirs(capture_dir, exist_ok=True)
    with open(os.path.join(capture_dir, "qa_validate.txt"), "w") as f:
        f.write(text)


async def main():
    client = await get_client()

    print("=" * 60)
    print("W35-MONITOR: E2E Monitoring Layer Tests")
    print("=" * 60)

    await test_1a_qa_health(client)
    print()
    await test_2a_qa_morning(client)
    print()
    await test_3b_qa_validate(client)

    await client.disconnect()

    print()
    print("=" * 60)
    passed = sum(1 for _, p, _ in RESULTS if p)
    total = len(RESULTS)
    print(f"RESULT: {passed}/{total} PASS")

    if passed < total:
        print("\nFAILURES:")
        for tid, p, d in RESULTS:
            if not p:
                print(f"  {tid}: {d}")

    return 0 if passed == total else 1


if __name__ == "__main__":
    rc = asyncio.run(main())
    sys.exit(rc)
