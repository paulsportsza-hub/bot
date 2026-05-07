#!/usr/bin/env python3
"""Telethon E2E tests for BUILD-WAVE1-SUB-01 — subscription card delivery.

Tests that all key subscription commands deliver rendered PNG cards (not plain text)
to a real Telegram user via the live bot.

Usage (from /home/paulsportsza/bot/):
    python scripts/e2e_wave1_sub.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from telethon import TelegramClient
from telethon.sessions import StringSession

API_ID   = int(os.getenv("TELEGRAM_API_ID", "32418601"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "95e313a8ef5b998be0515dd8328fac57")
BOT_USERNAME = "mzansiedge_bot"
SCREENSHOTS_DIR = Path("/home/paulsportsza/reports/e2e-screenshots")
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

SESSION_FILE = str(Path(__file__).parent.parent / "data" / "telethon_qa_session")
STRING_FILE  = Path(__file__).parent.parent / "data" / "telethon_qa_session.string"

TIMEOUT = 18  # seconds


@dataclass
class Result:
    name: str
    passed: bool
    msg: str
    duration: float
    screenshot: str = ""


async def get_client() -> TelegramClient:
    if STRING_FILE.exists():
        s = STRING_FILE.read_text().strip()
        if s:
            c = TelegramClient(StringSession(s), API_ID, API_HASH)
            await c.connect()
            if await c.is_user_authorized():
                return c
            await c.disconnect()
    c = TelegramClient(SESSION_FILE, API_ID, API_HASH)
    await c.connect()
    if not await c.is_user_authorized():
        print("ERROR: Not logged in. Run save_telegram_session.py first.")
        sys.exit(1)
    return c


async def send_cmd(client: TelegramClient, cmd: str, wait: float = TIMEOUT) -> list:
    entity = await client.get_entity(BOT_USERNAME)
    sent   = await client.send_message(entity, cmd)
    await asyncio.sleep(wait)
    msgs   = await client.get_messages(entity, limit=10)
    return [m for m in reversed(msgs) if m.id > sent.id]


async def _save_photo(client: TelegramClient, msg, name: str) -> str:
    if not msg.photo:
        return ""
    path = SCREENSHOTS_DIR / f"{name}.png"
    await client.download_media(msg, file=str(path))
    return str(path)


# ── Test cases ──────────────────────────────────────────────────────────────

async def test_status_bronze(client: TelegramClient) -> Result:
    """Bronze user /status → sub_status_bronze card."""
    t = time.time()
    try:
        msgs = await send_cmd(client, "/status", wait=TIMEOUT)
        photo_msg = next((m for m in msgs if m.photo), None)
        if not photo_msg:
            texts = [m.text or "" for m in msgs if not m.out]
            return Result("status_bronze", False,
                          f"No photo received. Bot replied: {texts[:2]}", time.time() - t)
        path = await _save_photo(client, photo_msg, "wave1_status_bronze")
        return Result("status_bronze", True,
                      f"Card received ({photo_msg.photo.sizes[-1].w}px wide)", time.time() - t,
                      screenshot=path)
    except Exception as e:
        return Result("status_bronze", False, str(e), time.time() - t)


async def test_upgrade_command(client: TelegramClient) -> Result:
    """/upgrade → sub_upgrade_bronze card (for bronze user)."""
    t = time.time()
    try:
        msgs = await send_cmd(client, "/upgrade", wait=TIMEOUT)
        photo_msg = next((m for m in msgs if m.photo), None)
        if not photo_msg:
            texts = [m.text or "" for m in msgs if not m.out]
            return Result("upgrade_command", False,
                          f"No photo received. Bot replied: {texts[:2]}", time.time() - t)
        path = await _save_photo(client, photo_msg, "wave1_upgrade_bronze")
        return Result("upgrade_command", True,
                      f"Card received ({photo_msg.photo.sizes[-1].w}px wide)", time.time() - t,
                      screenshot=path)
    except Exception as e:
        return Result("upgrade_command", False, str(e), time.time() - t)


async def test_billing_command(client: TelegramClient) -> Result:
    """/billing → sub_billing_inactive card (bronze user)."""
    t = time.time()
    try:
        msgs = await send_cmd(client, "/billing", wait=TIMEOUT)
        photo_msg = next((m for m in msgs if m.photo), None)
        if not photo_msg:
            texts = [m.text or "" for m in msgs if not m.out]
            return Result("billing_command", False,
                          f"No photo received. Bot replied: {texts[:2]}", time.time() - t)
        path = await _save_photo(client, photo_msg, "wave1_billing_inactive")
        return Result("billing_command", True,
                      f"Card received ({photo_msg.photo.sizes[-1].w}px wide)", time.time() - t,
                      screenshot=path)
    except Exception as e:
        return Result("billing_command", False, str(e), time.time() - t)


async def test_founding_command(client: TelegramClient) -> Result:
    """/founding → sub_founding_live card (if founding open)."""
    t = time.time()
    try:
        msgs = await send_cmd(client, "/founding", wait=TIMEOUT)
        photo_msg = next((m for m in msgs if m.photo), None)
        if not photo_msg:
            texts = [m.text or "" for m in msgs if not m.out]
            return Result("founding_command", False,
                          f"No photo received. Bot replied: {texts[:2]}", time.time() - t)
        path = await _save_photo(client, photo_msg, "wave1_founding_live")
        return Result("founding_command", True,
                      f"Card received ({photo_msg.photo.sizes[-1].w}px wide)", time.time() - t,
                      screenshot=path)
    except Exception as e:
        return Result("founding_command", False, str(e), time.time() - t)


async def test_subscribe_command(client: TelegramClient) -> Result:
    """/subscribe → sub_plans card."""
    t = time.time()
    try:
        msgs = await send_cmd(client, "/subscribe", wait=TIMEOUT)
        photo_msg = next((m for m in msgs if m.photo), None)
        if not photo_msg:
            texts = [m.text or "" for m in msgs if not m.out]
            return Result("subscribe_command", False,
                          f"No photo received. Bot replied: {texts[:2]}", time.time() - t)
        path = await _save_photo(client, photo_msg, "wave1_subscribe_plans")
        return Result("subscribe_command", True,
                      f"Card received ({photo_msg.photo.sizes[-1].w}px wide)", time.time() - t,
                      screenshot=path)
    except Exception as e:
        return Result("subscribe_command", False, str(e), time.time() - t)


# ── Runner ─────────────────────────────────────────────────────────────────

TESTS = [
    ("status_bronze",     test_status_bronze),
    ("upgrade_command",   test_upgrade_command),
    ("billing_command",   test_billing_command),
    ("founding_command",  test_founding_command),
    ("subscribe_command", test_subscribe_command),
]


async def main() -> int:
    client = await get_client()
    results: list[Result] = []
    print(f"\nBUILD-WAVE1-SUB-01 Telethon E2E — {len(TESTS)} tests\n{'─'*55}")
    try:
        for name, fn in TESTS:
            print(f"  {name} … ", end="", flush=True)
            r = await fn(client)
            icon = "✅" if r.passed else "❌"
            print(f"{icon}  {r.msg}  ({r.duration:.1f}s)")
            if r.screenshot:
                print(f"       Screenshot: {r.screenshot}")
            results.append(r)
            await asyncio.sleep(2)
    finally:
        await client.disconnect()

    passed = sum(1 for r in results if r.passed)
    total  = len(results)
    print(f"\n{'─'*55}")
    print(f"Result: {passed}/{total} passed\n")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
