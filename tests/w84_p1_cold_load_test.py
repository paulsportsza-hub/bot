"""W84-P1: Cold-load Hot Tips serving path validation.

Tests that initial Hot Tips entry is fast, deterministic, and non-blocking.
Specifically validates:
1. Cold entry (no in-memory cache) serves from edge_results fast path
2. Warm entry (cache populated) serves instantly
3. hot:back still works
4. Locked tip upgrade/back flow still works
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
import json
from datetime import datetime

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import ReplyInlineMarkup, KeyboardButtonCallback

API_ID = int(os.getenv("TELEGRAM_API_ID", "32418601"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "95e313a8ef5b998be0515dd8328fac57")
BOT_USERNAME = "mzansiedge_bot"
from config import DATA_DIR
SESSION_FILE = str(DATA_DIR / "telethon_session")
STRING_SESSION_FILE = str(DATA_DIR / "telethon_session.string")

COLD_LOAD_TIMEOUT = 25  # seconds — must respond within this
WARM_LOAD_TIMEOUT = 10  # seconds — warm path should be much faster
RESPONSE_WAIT = 20  # seconds to wait for response


def load_session():
    if os.path.exists(STRING_SESSION_FILE):
        with open(STRING_SESSION_FILE) as f:
            s = f.read().strip()
        if s:
            return StringSession(s)
    return StringSession()


def get_buttons(msg):
    buttons = []
    if msg.reply_markup and hasattr(msg.reply_markup, "rows"):
        for row in msg.reply_markup.rows:
            for btn in row.buttons:
                buttons.append(btn)
    return buttons


async def wait_for_response(client, bot, timeout=RESPONSE_WAIT):
    """Wait for bot message after action, return (msg, elapsed)."""
    t0 = time.time()
    deadline = t0 + timeout
    await asyncio.sleep(1)
    while time.time() < deadline:
        msgs = await client.get_messages(bot, limit=3)
        for msg in msgs:
            if msg.sender_id != (await client.get_me()).id:
                return msg, time.time() - t0
        await asyncio.sleep(0.5)
    return None, time.time() - t0


async def run_tests():
    results = {}
    session = load_session()
    client = TelegramClient(session, API_ID, API_HASH)
    await client.start()

    bot = await client.get_entity(BOT_USERNAME)
    me = await client.get_me()

    print(f"\n{'='*60}")
    print("W84-P1: Cold-Load Hot Tips Test")
    print(f"Time: {datetime.now():%Y-%m-%d %H:%M:%S}")
    print(f"{'='*60}\n")

    # ─── TEST 1: Cold-load entry (simulated — tap Tips, measure time) ───
    print("TEST 1: Cold-load Hot Tips entry timing")
    print("  Tapping 💎 Top Edge Picks button...")
    await client.send_message(bot, "💎 Top Edge Picks")
    t_start = time.time()

    tips_msg = None
    deadline = time.time() + COLD_LOAD_TIMEOUT + 10
    while time.time() < deadline:
        await asyncio.sleep(0.5)
        msgs = await client.get_messages(bot, limit=5)
        for msg in msgs:
            if msg.sender_id != me.id and msg.text and "Edge" in (msg.text or ""):
                elapsed = time.time() - t_start
                tips_msg = msg
                break
        if tips_msg:
            break

    elapsed = time.time() - t_start
    if tips_msg:
        print(f"  ✅ Response received in {elapsed:.1f}s")
        if elapsed <= COLD_LOAD_TIMEOUT:
            print(f"  ✅ PASS: Within {COLD_LOAD_TIMEOUT}s cold-load budget")
            results["cold_load_timing"] = {"pass": True, "elapsed": elapsed}
        else:
            print(f"  ❌ FAIL: Too slow ({elapsed:.1f}s > {COLD_LOAD_TIMEOUT}s)")
            results["cold_load_timing"] = {"pass": False, "elapsed": elapsed}
        # Print first 200 chars of response
        preview = (tips_msg.text or "")[:200]
        print(f"\n  Bot response:\n{preview}\n")
    else:
        print(f"  ❌ FAIL: No response within {COLD_LOAD_TIMEOUT + 10}s")
        results["cold_load_timing"] = {"pass": False, "elapsed": elapsed}
        await client.disconnect()
        return results

    # ─── TEST 2: Warm-path entry (second tap, cache should be populated) ───
    print("\nTEST 2: Warm-path Hot Tips entry (cache populated)")
    await asyncio.sleep(2)
    await client.send_message(bot, "💎 Top Edge Picks")
    t_warm = time.time()

    warm_msg = None
    warm_deadline = time.time() + WARM_LOAD_TIMEOUT + 5
    while time.time() < warm_deadline:
        await asyncio.sleep(0.3)
        msgs = await client.get_messages(bot, limit=5)
        for msg in msgs:
            if msg.sender_id != me.id and msg.text and "Edge" in (msg.text or ""):
                warm_elapsed = time.time() - t_warm
                warm_msg = msg
                break
        if warm_msg:
            break

    warm_elapsed = time.time() - t_warm
    if warm_msg and warm_elapsed <= WARM_LOAD_TIMEOUT:
        print(f"  ✅ PASS: Warm response in {warm_elapsed:.1f}s (< {WARM_LOAD_TIMEOUT}s)")
        results["warm_load_timing"] = {"pass": True, "elapsed": warm_elapsed}
    elif warm_msg:
        print(f"  ⚠️  Warm response in {warm_elapsed:.1f}s (slow but responded)")
        results["warm_load_timing"] = {"pass": False, "elapsed": warm_elapsed, "note": "slow"}
    else:
        print(f"  ❌ FAIL: No warm response in {WARM_LOAD_TIMEOUT + 5}s")
        results["warm_load_timing"] = {"pass": False, "elapsed": warm_elapsed}

    # ─── TEST 3: hot:back works ───
    print("\nTEST 3: hot:back from tip detail returns to Hot Tips")
    await asyncio.sleep(2)
    # Find an edge:detail button
    btns = get_buttons(tips_msg or warm_msg)
    edge_btn = next((b for b in btns if hasattr(b, "data") and b.data and b"edge:detail:" in b.data), None)
    if edge_btn:
        print(f"  Tapping edge detail button: {edge_btn.data.decode()}")
        await (tips_msg or warm_msg).click(data=edge_btn.data)
        await asyncio.sleep(RESPONSE_WAIT)
        detail_msgs = await client.get_messages(bot, limit=5)
        detail_msg = next((m for m in detail_msgs if m.sender_id != me.id and "Edge" in (m.text or "")), None)
        if detail_msg:
            # Now find "Back to Edge Picks" button
            back_btns = get_buttons(detail_msg)
            back_btn = next(
                (b for b in back_btns if hasattr(b, "data") and b.data and b"hot:back" in b.data),
                None
            )
            if back_btn:
                print("  Found hot:back button — tapping...")
                await detail_msg.click(data=back_btn.data)
                await asyncio.sleep(RESPONSE_WAIT)
                back_msgs = await client.get_messages(bot, limit=5)
                back_msg = next((m for m in back_msgs if m.sender_id != me.id and "Edge" in (m.text or "")), None)
                if back_msg:
                    print("  ✅ PASS: hot:back returned to Hot Tips list")
                    results["hot_back"] = {"pass": True}
                else:
                    print("  ❌ FAIL: hot:back did not return to Hot Tips list")
                    results["hot_back"] = {"pass": False, "note": "no Tips response"}
            else:
                # Check for any back button
                print(f"  Back buttons found: {[b.data.decode() for b in back_btns if hasattr(b, 'data') and b.data]}")
                print("  ⚠️  No hot:back button found — checking alternative")
                results["hot_back"] = {"pass": False, "note": "no hot:back button", "buttons": [b.data.decode() if hasattr(b, "data") and b.data else "" for b in back_btns]}
        else:
            print("  ❌ No detail response found")
            results["hot_back"] = {"pass": False, "note": "no detail response"}
    else:
        print("  ⚠️  No edge:detail button found (may be locked for this user tier)")
        # Try hot:upgrade flow instead
        upgrade_btn = next((b for b in btns if hasattr(b, "data") and b.data and b"hot:upgrade" in b.data), None)
        if upgrade_btn:
            print("  Testing hot:upgrade flow (locked tier)")
            await (tips_msg or warm_msg).click(data=upgrade_btn.data)
            await asyncio.sleep(RESPONSE_WAIT)
            upgrade_msgs = await client.get_messages(bot, limit=5)
            upgrade_msg = next((m for m in upgrade_msgs if m.sender_id != me.id), None)
            if upgrade_msg:
                upgrade_btns = get_buttons(upgrade_msg)
                back_btn = next((b for b in upgrade_btns if hasattr(b, "data") and b.data and b"hot:back" in b.data), None)
                if back_btn:
                    print("  ✅ PASS: hot:upgrade has hot:back button")
                    results["hot_back"] = {"pass": True, "via": "upgrade_flow"}
                else:
                    print(f"  Upgrade buttons: {[b.data.decode() for b in upgrade_btns if hasattr(b, 'data') and b.data]}")
                    results["hot_back"] = {"pass": False, "note": "upgrade has no hot:back"}
        else:
            results["hot_back"] = {"pass": None, "note": "skipped — no edge:detail or hot:upgrade buttons"}

    # ─── TEST 4: Locked tip → upgrade → back ───
    print("\nTEST 4: Locked tip upgrade/back flow")
    await asyncio.sleep(2)
    upgrade_btn = next((b for b in get_buttons(tips_msg or warm_msg) if hasattr(b, "data") and b.data and b"hot:upgrade" in b.data), None)
    if upgrade_btn:
        await (tips_msg or warm_msg).click(data=upgrade_btn.data)
        await asyncio.sleep(RESPONSE_WAIT)
        upgrade_msgs = await client.get_messages(bot, limit=5)
        upgrade_msg = next((m for m in upgrade_msgs if m.sender_id != me.id), None)
        if upgrade_msg:
            print(f"  Upgrade screen text: {(upgrade_msg.text or '')[:100]}")
            back_btns = get_buttons(upgrade_msg)
            back_btn = next((b for b in back_btns if hasattr(b, "data") and b.data and b"hot:back" in b.data), None)
            if back_btn:
                print("  ✅ PASS: locked tip → upgrade screen has Back to Edge Picks")
                results["locked_upgrade_back"] = {"pass": True}
            else:
                print(f"  ❌ Back button missing. Buttons: {[b.data.decode() for b in back_btns if hasattr(b, 'data') and b.data]}")
                results["locked_upgrade_back"] = {"pass": False, "note": "no hot:back on upgrade screen"}
        else:
            print("  ❌ No upgrade response")
            results["locked_upgrade_back"] = {"pass": False, "note": "no response"}
    else:
        print("  ⚠️  No hot:upgrade buttons (user may have full access)")
        results["locked_upgrade_back"] = {"pass": None, "note": "skipped — no locked tips visible"}

    await client.disconnect()

    # ─── SUMMARY ───
    print(f"\n{'='*60}")
    print("RESULTS SUMMARY")
    print(f"{'='*60}")
    for test, result in results.items():
        if result is None:
            status = "SKIP"
        elif result.get("pass") is True:
            status = "✅ PASS"
        elif result.get("pass") is False:
            status = "❌ FAIL"
        else:
            status = "⚠️  SKIP"
        extras = ""
        if "elapsed" in result:
            extras = f" ({result['elapsed']:.1f}s)"
        if "note" in result:
            extras += f" — {result['note']}"
        print(f"  {test}: {status}{extras}")

    all_pass = all(r.get("pass") is not False for r in results.values())
    print(f"\nOverall: {'✅ ALL PASS' if all_pass else '❌ FAILURES DETECTED'}")
    return results


if __name__ == "__main__":
    results = asyncio.run(run_tests())
    failed = [k for k, v in results.items() if v.get("pass") is False]
    sys.exit(1 if failed else 0)
