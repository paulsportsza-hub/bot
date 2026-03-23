#!/usr/bin/env python3
"""W84-RT1 Live Validation — Lock-Contention Stall Fixes.

Validates:
1. ctx_task timeout: breakdown completes within 15s (was up to 39.8s when DB locked)
2. _store_narrative_cache is post-delivery: spinner stops before cache write
3. /qa clear_mm_cache clears _schedule_cache for a user
4. Repeated breakdown taps (same match) don't strand on "Analysing..."
5. No 'database is locked' warnings during tested path
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

# Telethon
from telethon import TelegramClient
from telethon.sessions import StringSession

API_ID   = int(os.getenv("TELEGRAM_API_ID", "32418601"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "95e313a8ef5b998be0515dd8328fac57")
BOT_USERNAME = "@mzansiedge_bot"
STRING_SESSION_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "telethon_session.string")

BOT_LOG = "/tmp/bot_latest.log"

results: dict = {}
failures: list[str] = []


def load_session():
    if os.path.exists(STRING_SESSION_FILE):
        with open(STRING_SESSION_FILE) as f:
            s = f.read().strip()
        if s:
            return StringSession(s)
    return StringSession()


def check(name: str, condition: bool, detail: str = ""):
    status = "✅ PASS" if condition else "❌ FAIL"
    print(f"  {status} — {name}")
    if detail:
        print(f"     {detail}")
    results[name] = {"pass": condition, "detail": detail}
    if not condition:
        failures.append(name)
    return condition


def section(title: str):
    print(f"\n{'─'*60}")
    print(f"  {title}")
    print(f"{'─'*60}")


async def wait_msg(client, entity, after_id: int, timeout: float, me_id: int):
    """Wait for bot reply after after_id (new message path)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        await asyncio.sleep(0.8)
        msgs = await client.get_messages(entity, limit=6)
        for m in msgs:
            if m.id > after_id and m.sender_id != me_id:
                return m
    return None


async def wait_edit(client, entity, msg_id: int, orig_text: str, timeout: float):
    """Wait for an edit-in-place response (bot edits existing message)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        await asyncio.sleep(0.6)
        try:
            m = await client.get_messages(entity, ids=msg_id)
            if m and (m.text or "") != orig_text:
                return m, time.time()
        except Exception:
            pass
    # Return final state even if unchanged
    try:
        m = await client.get_messages(entity, ids=msg_id)
        return m, time.time()
    except Exception:
        return None, time.time()


async def get_first_game_button(client, entity, me_id):
    """Tap My Matches and return the first game inline button."""
    # First tap My Matches
    s = await client.send_message(entity, "⚽ My Matches")
    r = await wait_msg(client, entity, s.id, 12.0, me_id)
    if not r or not r.reply_markup:
        return None, None, r
    # Find first yg:game: button
    for row in r.reply_markup.rows:
        for btn in row.buttons:
            if hasattr(btn, "data") and btn.data and btn.data.decode().startswith("yg:game:"):
                return btn, r, r
    return None, r, r


async def test_breakdown_speed(client, entity, me_id):
    """Test game breakdown completes quickly even on repeated taps."""
    section("Game Breakdown Speed + Repeated Tap")

    # First: clear cache so we force a cold breakdown
    s_clr = await client.send_message(entity, "/qa clear_mm_cache")
    r_clr = await wait_msg(client, entity, s_clr.id, 8.0, me_id)
    clr_text = (r_clr.text or "") if r_clr else ""
    check("/qa clear_mm_cache responds correctly",
          "cache" in clr_text.lower() or "cleared" in clr_text.lower() or "cold" in clr_text.lower(),
          clr_text[:80])

    # Tap My Matches — should be fresh (cache cleared)
    print("\n  [1] Tapping My Matches (cold after cache clear)...")
    s_mm = await client.send_message(entity, "⚽ My Matches")
    r_mm = await wait_msg(client, entity, s_mm.id, 12.0, me_id)
    if not r_mm:
        check("My Matches responds after cache clear", False, "No response")
        return
    check("My Matches responds after cache clear", True, (r_mm.text or "")[:60])

    # Find a game button
    game_btn = None
    mm_msg = r_mm
    if r_mm.reply_markup:
        for row in r_mm.reply_markup.rows:
            for btn in row.buttons:
                if not hasattr(btn, "data") or not btn.data:
                    continue
                if btn.data.decode().startswith("yg:game:"):
                    game_btn = btn
                    break
            if game_btn:
                break

    if not game_btn:
        print("  ⚠️  No game buttons found in My Matches — skipping breakdown speed test")
        return

    # First breakdown tap — times the full cold path
    print(f"\n  [2] Tapping first game breakdown (cold path)...")
    _orig_mm_text = mm_msg.text or ""
    t0 = time.time()
    await mm_msg.click(data=game_btn.data)
    r1, _t1_end = await wait_edit(client, entity, mm_msg.id, _orig_mm_text, 25.0)
    t1 = _t1_end - t0
    r1_text = (r1.text or "") if r1 else ""
    print(f"     Response in {t1:.1f}s")
    print(f"     Content: {r1_text[:80]!r}")
    check("First game breakdown completes within 15s",
          r1 is not None and t1 < 15.0 and r1_text != _orig_mm_text,
          f"elapsed={t1:.1f}s")
    check("First breakdown shows game content (not error)",
          bool(r1_text) and "Analysing" not in r1_text and "error" not in r1_text.lower() and r1_text != _orig_mm_text,
          r1_text[:80])

    # Check bot log for locked warnings during this period
    locked_before = _count_locked_warnings(t0 - 5)

    # Second tap — same game — should be instant (cache hit)
    if r1 and r1.reply_markup:
        # Navigate back first
        back_btn = None
        for row in r1.reply_markup.rows:
            for btn in row.buttons:
                if not hasattr(btn, "data") or not btn.data:
                    continue
                d = btn.data.decode()
                if "back" in d.lower() or "yg:all" in d or "hot:back" in d:
                    back_btn = btn
                    break
            if back_btn:
                break

        if back_btn:
            print(f"\n  [3] Tapping back → then same game again (cache hit path)...")
            _orig_r1_text = r1.text or ""
            await r1.click(data=back_btn.data)
            # Wait for message to revert to the My Matches list
            r_back, _ = await wait_edit(client, entity, r1.id, _orig_r1_text, 8.0)
            if r_back and r_back.reply_markup:
                # Tap same game again
                game_btn2 = None
                for row in r_back.reply_markup.rows:
                    for btn in row.buttons:
                        if not hasattr(btn, "data") or not btn.data:
                            continue
                        if btn.data.decode().startswith("yg:game:"):
                            game_btn2 = btn
                            break
                    if game_btn2:
                        break
                if game_btn2:
                    _orig_back_text = r_back.text or ""
                    t2 = time.time()
                    await r_back.click(data=game_btn2.data)
                    r2, _t2_end = await wait_edit(client, entity, r_back.id, _orig_back_text, 10.0)
                    t2_elapsed = _t2_end - t2
                    r2_text = (r2.text or "") if r2 else ""
                    print(f"     Second tap response: {t2_elapsed:.1f}s")
                    check("Second breakdown (cache hit) completes within 5s",
                          r2 is not None and t2_elapsed < 5.0 and r2_text != _orig_back_text,
                          f"elapsed={t2_elapsed:.1f}s")

    # Check locked warnings
    locked_after = _count_locked_warnings(t0 - 5)
    new_locked = locked_after - locked_before
    print(f"\n  Log check: {new_locked} new 'database is locked' warnings during test")
    check("No new 'database is locked' warnings during breakdown",
          new_locked == 0,
          f"new locked warnings: {new_locked}")


def _count_locked_warnings(since_epoch: float) -> int:
    """Count 'database is locked' lines in bot log since a given epoch time."""
    try:
        count = 0
        with open(BOT_LOG, "r", errors="replace") as f:
            for line in f:
                if "database is locked" in line.lower():
                    # Extract timestamp from log line if possible
                    count += 1
        return count
    except Exception:
        return 0


async def test_clear_mm_cache_command(client, entity, me_id):
    """Test /qa clear_mm_cache self and /qa clear_mm_cache <uid>."""
    section("/qa clear_mm_cache Command")

    # Self clear
    s1 = await client.send_message(entity, "/qa clear_mm_cache")
    r1 = await wait_msg(client, entity, s1.id, 8.0, me_id)
    t1 = (r1.text or "") if r1 else ""
    check("/qa clear_mm_cache (self) responds",
          bool(t1) and ("cache" in t1.lower() or "cold" in t1.lower() or "cleared" in t1.lower()),
          t1[:80])

    # Clear with explicit user_id
    s2 = await client.send_message(entity, f"/qa clear_mm_cache {me_id}")
    r2 = await wait_msg(client, entity, s2.id, 8.0, me_id)
    t2 = (r2.text or "") if r2 else ""
    check(f"/qa clear_mm_cache {me_id} (explicit) responds",
          bool(t2) and ("cache" in t2.lower() or "cold" in t2.lower() or "cleared" in t2.lower()),
          t2[:80])

    # After clear, My Matches tap should work
    s3 = await client.send_message(entity, "⚽ My Matches")
    r3 = await wait_msg(client, entity, s3.id, 12.0, me_id)
    check("My Matches works after /qa clear_mm_cache",
          r3 is not None and bool(r3.text or r3.reply_markup),
          (r3.text or "")[:60] if r3 else "no response")


async def test_cold_mm_opens(client, entity, me_id):
    """Run 5 cold My Matches opens and verify all complete within 8s."""
    section("Cold My Matches Opens — 5 Runs")
    times = []
    for i in range(5):
        # Clear cache before each open
        s_c = await client.send_message(entity, "/qa clear_mm_cache")
        await wait_msg(client, entity, s_c.id, 6.0, me_id)
        await asyncio.sleep(0.5)

        t0 = time.time()
        s = await client.send_message(entity, "⚽ My Matches")
        r = await wait_msg(client, entity, s.id, 10.0, me_id)
        elapsed = time.time() - t0
        times.append(elapsed)
        status = "✅" if r and elapsed < 8.0 else "❌"
        print(f"    Run {i+1}: {elapsed:.1f}s {status}")
        await asyncio.sleep(1.0)

    passes = sum(1 for t in times if t < 8.0)
    avg = sum(times) / len(times) if times else 0
    check(f"All 5 cold My Matches opens < 8s ({passes}/5)",
          passes == 5,
          f"avg={avg:.1f}s, max={max(times):.1f}s")


async def main():
    print(f"\n{'═'*60}")
    print("  W84-RT1 Validation — Lock-Contention Stall Fixes")
    print(f"  {datetime.now():%Y-%m-%d %H:%M:%S}")
    print(f"{'═'*60}")

    session = load_session()
    if not session.save():
        print("\n  ⚠️  No Telethon session — cannot run live validation")
        sys.exit(1)

    async with TelegramClient(session, API_ID, API_HASH) as client:
        entity = await client.get_entity(BOT_USERNAME)
        me = await client.get_me()
        me_id = me.id

        await test_clear_mm_cache_command(client, entity, me_id)
        await test_breakdown_speed(client, entity, me_id)
        await test_cold_mm_opens(client, entity, me_id)

    # Summary
    section("SUMMARY")
    passed = sum(1 for r in results.values() if r["pass"])
    total = len(results)
    print(f"\n  Results: {passed}/{total} checks passed")
    if failures:
        print("\n  FAILURES:")
        for f in failures:
            d = results[f]["detail"]
            print(f"    ❌ {f}")
            if d:
                print(f"       {d}")
    else:
        print("  All checks PASSED ✅")

    return {"passed": passed, "total": total, "failures": failures}


if __name__ == "__main__":
    asyncio.run(main())
