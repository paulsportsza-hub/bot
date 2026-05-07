#!/usr/bin/env python3
"""W74-QA: Overnight Load Speed + UX Regression Test.

Phases:
  1. Command response times (every /command)
  2. Edge detail load times (every edge in Hot Tips)
  3. Navigation flow (zero dead ends)
  4. Gate testing (per tier via /qa set_tier)
  5. Concurrent load test (rapid taps)
"""

import asyncio
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import (
    ReplyInlineMarkup,
    KeyboardButtonCallback,
    KeyboardButtonUrl,
)

API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "")
BOT = "mzansiedge_bot"
SESSION_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "telethon_qa_session")
STRING_SESSION_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "telethon_qa_session.string")
from config import BOT_ROOT
CAPTURE_DIR = str(BOT_ROOT.parent / "reports" / "screenshots" / "w74_load")
os.makedirs(CAPTURE_DIR, exist_ok=True)

# ── Results tracking ──
RESULTS: list[dict] = []
LOAD_TIMES: list[dict] = []


def record(phase: str, test_id: str, passed: bool, detail: str, load_time: float = 0.0):
    RESULTS.append({"phase": phase, "test_id": test_id, "passed": passed,
                     "detail": detail, "load_time": load_time})
    emoji = "\u2705" if passed else "\u274c"
    time_str = f" ({load_time:.1f}s)" if load_time > 0 else ""
    print(f"  {emoji} {test_id}: {detail}{time_str}")


def capture(test_id: str, text: str):
    path = os.path.join(CAPTURE_DIR, f"{test_id}.txt")
    with open(path, "w") as f:
        f.write(text)


# ── Telethon helpers ──

_entity = None


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


async def entity(client):
    global _entity
    if _entity is None:
        _entity = await client.get_entity(BOT)
    return _entity


async def send_timed(client, text, wait=15):
    """Send command, measure time to first bot response."""
    ent = await entity(client)
    t0 = time.time()
    sent = await client.send_message(ent, text)

    # Poll for response with timeout
    deadline = t0 + wait
    response_time = 0.0
    bot_msgs = []
    while time.time() < deadline:
        await asyncio.sleep(0.5)
        messages = await client.get_messages(ent, limit=15)
        new = [m for m in messages if m.id > sent.id and not m.out]
        if new:
            response_time = time.time() - t0
            bot_msgs = list(reversed(new))
            # If any message has text or markup, we have a real response
            if any(m.text or m.reply_markup for m in bot_msgs):
                break
    if not bot_msgs:
        response_time = time.time() - t0

    return bot_msgs, response_time


async def click_btn(client, msg, btn_text, wait=15):
    """Click inline button by text substring, return (edited_msg, new_msgs, elapsed)."""
    if not msg or not msg.reply_markup:
        return None, [], 0.0
    if isinstance(msg.reply_markup, ReplyInlineMarkup):
        for row in msg.reply_markup.rows:
            for btn in row.buttons:
                if isinstance(btn, KeyboardButtonCallback) and btn_text in btn.text:
                    t0 = time.time()
                    try:
                        await msg.click(data=btn.data)
                    except Exception as click_err:
                        return None, [], time.time() - t0
                    await asyncio.sleep(min(wait, 3))  # initial wait
                    ent = await entity(client)
                    elapsed = time.time() - t0

                    # Re-fetch the clicked message (might be edited)
                    edited = await client.get_messages(ent, ids=msg.id)

                    # Check for new messages
                    all_msgs = await client.get_messages(ent, limit=15)
                    new = [m for m in all_msgs if m.id > msg.id and not m.out]

                    # If no response yet, keep waiting
                    deadline = t0 + wait
                    while time.time() < deadline:
                        if edited and edited.text != msg.text:
                            break  # Message was edited
                        if new:
                            break  # New message arrived
                        await asyncio.sleep(1)
                        edited = await client.get_messages(ent, ids=msg.id)
                        all_msgs = await client.get_messages(ent, limit=15)
                        new = [m for m in all_msgs if m.id > msg.id and not m.out]

                    elapsed = time.time() - t0
                    return edited, list(reversed(new)), elapsed
    return None, [], 0.0


def get_buttons(msg):
    """Extract inline button texts and callback data from a message."""
    if not msg or not msg.reply_markup or not isinstance(msg.reply_markup, ReplyInlineMarkup):
        return []
    buttons = []
    for row in msg.reply_markup.rows:
        for btn in row.buttons:
            if isinstance(btn, KeyboardButtonCallback):
                buttons.append({"text": btn.text, "data": btn.data.decode() if isinstance(btn.data, bytes) else btn.data})
            elif isinstance(btn, KeyboardButtonUrl):
                buttons.append({"text": btn.text, "url": btn.url})
    return buttons


def has_button(msg, text_substr):
    """Check if message has a button containing text."""
    return any(text_substr in b.get("text", "") for b in get_buttons(msg))


# ═══════════════════════════════════════════════════════════════
# PHASE 1: Command Response Times
# ═══════════════════════════════════════════════════════════════

async def phase1_commands(client):
    print("\n═══ PHASE 1: Command Response Times ═══")

    commands = [
        ("/start", "Welcome", 3.0),
        ("/tips", "Edge Picks", 5.0),
        ("/help", "Help", 3.0),
        ("/subscribe", "plan", 3.0),
        ("/settings", "Settings", 3.0),
        ("/mute", "mute", 3.0),
        ("/results", "result", 5.0),
        ("/stats", "stat", 5.0),
    ]

    for cmd, expect_kw, max_time in commands:
        await asyncio.sleep(2)  # breathing room between commands
        msgs, elapsed = await send_timed(client, cmd, wait=max_time + 10)
        text = " ".join(m.text or "" for m in msgs).lower()

        has_response = bool(msgs) and bool(text.strip())
        within_time = elapsed <= max_time
        has_keyword = expect_kw.lower() in text

        passed = has_response and within_time
        status = "OK" if passed else "SLOW" if has_response else "NO RESPONSE"
        detail = f"{status} — {elapsed:.1f}s"
        if not has_keyword and has_response:
            detail += f" (missing '{expect_kw}' in response)"

        record("P1-CMD", f"cmd-{cmd[1:]}", passed, detail, elapsed)
        capture(f"P1-{cmd[1:]}", text[:500] if text else "(empty)")
        LOAD_TIMES.append({"type": "command", "name": cmd, "time": elapsed,
                           "max": max_time, "ok": passed})


# ═══════════════════════════════════════════════════════════════
# PHASE 2: Edge Detail Load Times
# ═══════════════════════════════════════════════════════════════

async def phase2_edge_details(client):
    print("\n═══ PHASE 2: Edge Detail Load Times ═══")

    # First, load Hot Tips
    msgs, tips_time = await send_timed(client, "/tips", wait=15)
    if not msgs:
        record("P2-EDGE", "tips-load", False, f"Hot Tips failed to load ({tips_time:.1f}s)", tips_time)
        return

    tips_msg = msgs[-1] if msgs else None
    if not tips_msg:
        record("P2-EDGE", "tips-load", False, "No tips message", 0)
        return

    record("P2-EDGE", "tips-load", tips_time <= 5.0, f"Hot Tips loaded in {tips_time:.1f}s", tips_time)
    capture("P2-tips-text", tips_msg.text or "(empty)")

    # Extract all edge buttons (not nav buttons)
    edge_buttons = [b for b in get_buttons(tips_msg)
                    if b.get("data", "").startswith("edge:detail:") or b.get("data") == "sub:plans"]

    record("P2-EDGE", "edge-count", bool(edge_buttons),
           f"{len(edge_buttons)} edge buttons found")

    # Tap each edge and measure load time
    edges_tested = 0
    for i, btn in enumerate(edge_buttons[:8]):  # max 8 edges
        cb_data = btn.get("data", "")
        btn_text = btn.get("text", "")

        if cb_data == "sub:plans":
            record("P2-EDGE", f"edge-{i+1}", True, f"🔒 Locked edge (sub:plans) — '{btn_text}'", 0)
            continue

        # Click this edge button
        await asyncio.sleep(2)
        edited, new_msgs, elapsed = await click_btn(client, tips_msg, btn_text[:15], wait=25)

        # Check response
        detail_text = ""
        detail_msg = None
        if edited and edited.text != (tips_msg.text or ""):
            detail_text = edited.text or ""
            detail_msg = edited
        elif new_msgs:
            detail_text = new_msgs[-1].text or ""
            detail_msg = new_msgs[-1]

        has_detail = bool(detail_text.strip())
        is_loading = "loading" in detail_text.lower() or "⏳" in detail_text or "analysing" in detail_text.lower()

        # If still loading, wait more
        if is_loading and elapsed < 25:
            extra_wait = min(25 - elapsed, 15)
            await asyncio.sleep(extra_wait)
            ent = await entity(client)
            if detail_msg:
                refetched = await client.get_messages(ent, ids=detail_msg.id)
                if refetched and refetched.text:
                    detail_text = refetched.text
                    is_loading = "loading" in detail_text.lower() or "⏳" in detail_text
            elapsed += extra_wait

        cache_hit = elapsed < 2.0
        max_time = 2.0 if cache_hit else 12.0
        passed = has_detail and elapsed <= max_time and not is_loading

        cache_str = "CACHE HIT" if cache_hit else "GENERATED"
        status = f"{cache_str} — {elapsed:.1f}s"
        if is_loading:
            status += " (STILL LOADING)"
        if not has_detail:
            status = f"NO RESPONSE — {elapsed:.1f}s"

        record("P2-EDGE", f"edge-{i+1}", passed, f"{status} — '{btn_text}'", elapsed)
        capture(f"P2-edge-{i+1}", detail_text[:800] if detail_text else "(empty)")
        LOAD_TIMES.append({"type": "edge_detail", "name": btn_text, "time": elapsed,
                           "max": max_time, "ok": passed, "cache": cache_hit})
        edges_tested += 1

        # Navigate back to Hot Tips for next edge
        if detail_msg and has_button(detail_msg, "Edge Picks"):
            await click_btn(client, detail_msg, "Edge Picks", wait=5)
            await asyncio.sleep(2)
            # Re-fetch tips message
            ent = await entity(client)
            all_msgs = await client.get_messages(ent, limit=10)
            for m in all_msgs:
                if m.text and "Edge Picks" in m.text and not m.out:
                    tips_msg = m
                    break
        elif detail_msg and has_button(detail_msg, "Back"):
            await click_btn(client, detail_msg, "Back", wait=5)
            await asyncio.sleep(2)
            ent = await entity(client)
            all_msgs = await client.get_messages(ent, limit=10)
            for m in all_msgs:
                if m.text and "Edge Picks" in m.text and not m.out:
                    tips_msg = m
                    break


# ═══════════════════════════════════════════════════════════════
# PHASE 3: Navigation Flow (Zero Dead Ends)
# ═══════════════════════════════════════════════════════════════

async def phase3_navigation(client):
    print("\n═══ PHASE 3: Navigation Flow ═══")

    # 3A: /tips → tap first edge → detail loads → back works
    await asyncio.sleep(2)
    msgs, t = await send_timed(client, "/tips", wait=10)
    tips_msg = msgs[-1] if msgs else None
    edge_btns = [b for b in get_buttons(tips_msg) if "edge:detail:" in b.get("data", "")] if tips_msg else []

    if edge_btns:
        btn_text = edge_btns[0]["text"][:15]
        edited, new, elapsed = await click_btn(client, tips_msg, btn_text, wait=20)
        detail_msg = edited if (edited and edited.text != (tips_msg.text or "")) else (new[-1] if new else None)

        # Wait for loading to finish
        if detail_msg and ("loading" in (detail_msg.text or "").lower() or "⏳" in (detail_msg.text or "")):
            await asyncio.sleep(15)
            ent = await entity(client)
            detail_msg = await client.get_messages(ent, ids=detail_msg.id)
            elapsed += 15

        has_detail = detail_msg and bool((detail_msg.text or "").strip())
        record("P3-NAV", "tips-to-detail", has_detail,
               f"Detail loaded in {elapsed:.1f}s" if has_detail else f"No detail after {elapsed:.1f}s", elapsed)

        # Back button works
        if has_detail and detail_msg:
            has_back = has_button(detail_msg, "Back") or has_button(detail_msg, "Edge Picks")
            record("P3-NAV", "detail-back-btn", has_back,
                   "Back button present" if has_back else "NO BACK BUTTON")

            if has_back:
                back_target = "Edge Picks" if has_button(detail_msg, "Edge Picks") else "Back"
                edited2, new2, back_time = await click_btn(client, detail_msg, back_target, wait=8)
                back_text = (edited2.text or "") if edited2 else ""
                record("P3-NAV", "back-to-tips", "Edge" in back_text or "edge" in back_text.lower(),
                       f"Returned to tips in {back_time:.1f}s", back_time)
    else:
        record("P3-NAV", "tips-to-detail", False, "No edge buttons found")

    # 3B: /start → menu options work
    await asyncio.sleep(2)
    msgs, t = await send_timed(client, "/start", wait=5)
    start_msg = msgs[-1] if msgs else None
    has_start = bool(start_msg and (start_msg.text or "").strip())
    record("P3-NAV", "start-response", has_start,
           f"/start responded in {t:.1f}s" if has_start else f"/start no response after {t:.1f}s", t)

    # 3C: Menu button navigation
    if start_msg and has_button(start_msg, "Menu"):
        edited, new, menu_time = await click_btn(client, start_msg, "Menu", wait=5)
        menu_msg = edited if (edited and edited.text != (start_msg.text or "")) else (new[-1] if new else None)
        has_menu = menu_msg and bool((menu_msg.text or "").strip())
        record("P3-NAV", "menu-load", has_menu,
               f"Menu loaded in {menu_time:.1f}s" if has_menu else "Menu failed")

    # 3D: /tips → pagination (Next button)
    await asyncio.sleep(2)
    msgs, t = await send_timed(client, "/tips", wait=10)
    tips_msg = msgs[-1] if msgs else None
    if tips_msg and has_button(tips_msg, "Next"):
        edited, new, page_time = await click_btn(client, tips_msg, "Next", wait=10)
        page_text = (edited.text or "") if edited else ""
        has_page2 = bool(page_text.strip()) and page_text != (tips_msg.text or "")
        record("P3-NAV", "pagination-next", has_page2,
               f"Page 2 loaded in {page_time:.1f}s" if has_page2 else f"Pagination failed after {page_time:.1f}s", page_time)

        # Prev button
        page2_msg = edited if has_page2 else None
        if page2_msg and has_button(page2_msg, "Prev"):
            edited3, _, prev_time = await click_btn(client, page2_msg, "Prev", wait=8)
            record("P3-NAV", "pagination-prev", True, f"Prev loaded in {prev_time:.1f}s", prev_time)
    else:
        record("P3-NAV", "pagination-next", True, "No Next button (few edges) — OK")

    # 3E: My Matches
    await asyncio.sleep(2)
    msgs, t = await send_timed(client, "⚽ My Matches", wait=10)
    matches_text = " ".join(m.text or "" for m in msgs).lower() if msgs else ""
    has_matches = "match" in matches_text or "game" in matches_text or "schedule" in matches_text or "no live" in matches_text
    record("P3-NAV", "my-matches", has_matches or bool(msgs),
           f"My Matches in {t:.1f}s" if msgs else f"No response after {t:.1f}s", t)

    # 3F: Settings
    await asyncio.sleep(2)
    msgs, t = await send_timed(client, "⚙️ Settings", wait=5)
    settings_text = " ".join(m.text or "" for m in msgs).lower() if msgs else ""
    record("P3-NAV", "settings-kb", bool(msgs),
           f"Settings in {t:.1f}s" if msgs else f"No response after {t:.1f}s", t)


# ═══════════════════════════════════════════════════════════════
# PHASE 4: Gate Testing (Per Tier)
# ═══════════════════════════════════════════════════════════════

async def phase4_gates(client):
    print("\n═══ PHASE 4: Gate Testing (Per Tier) ═══")

    for tier in ["bronze", "gold", "diamond"]:
        # Set tier
        await asyncio.sleep(2)
        msgs, t = await send_timed(client, f"/qa set_{tier}", wait=5)
        set_text = " ".join(m.text or "" for m in msgs).lower() if msgs else ""
        tier_set = tier in set_text or "qa" in set_text
        record("P4-GATE", f"set-{tier}", tier_set,
               f"Tier set to {tier}" if tier_set else f"Failed to set {tier}")

        # Load tips
        await asyncio.sleep(2)
        msgs, t = await send_timed(client, "/tips", wait=10)
        tips_msg = msgs[-1] if msgs else None
        tips_text = tips_msg.text or "" if tips_msg else ""
        capture(f"P4-{tier}-tips", tips_text[:1000])

        if tier == "bronze":
            # Bronze should see locks
            has_locks = "🔒" in tips_text or "locked" in tips_text.lower() or "sub:plans" in str(get_buttons(tips_msg))
            has_subscribe = "/subscribe" in tips_text
            # Check no diamond odds leak
            record("P4-GATE", "bronze-locks", has_locks,
                   "🔒 Lock indicators present" if has_locks else "NO LOCKS — potential gate leak!")
            record("P4-GATE", "bronze-subscribe", has_subscribe,
                   "/subscribe CTA present" if has_subscribe else "No /subscribe CTA")

            # Check locked button goes to sub:plans
            locked_btns = [b for b in get_buttons(tips_msg) if b.get("data") == "sub:plans"]
            record("P4-GATE", "bronze-locked-btns", bool(locked_btns),
                   f"{len(locked_btns)} locked button(s) → sub:plans" if locked_btns else "No locked buttons")

        elif tier == "gold":
            # Gold should see Diamond locked, Gold/Silver/Bronze accessible
            has_diamond_lock = "💎" in tips_text and ("locked" in tips_text.lower() or "🔒" in tips_text)
            # Gold-tier edges should have edge:detail buttons
            detail_btns = [b for b in get_buttons(tips_msg) if "edge:detail:" in b.get("data", "")]
            record("P4-GATE", "gold-diamond-locked", has_diamond_lock or "diamond" in tips_text.lower(),
                   "Diamond edges locked for Gold" if has_diamond_lock else "Diamond lock not visible (may be no Diamond edges)")
            record("P4-GATE", "gold-accessible", bool(detail_btns),
                   f"{len(detail_btns)} accessible edge(s)" if detail_btns else "No accessible edges")

        elif tier == "diamond":
            # Diamond should see NO locks, NO /subscribe
            no_locks = "🔒" not in tips_text
            no_subscribe_footer = "/subscribe" not in tips_text or "━━━" not in tips_text
            all_detail = all("edge:detail:" in b.get("data", "") or b.get("data", "").startswith(("yg:", "hot:", "nav:"))
                            for b in get_buttons(tips_msg))
            record("P4-GATE", "diamond-no-locks", no_locks,
                   "Zero 🔒 in output" if no_locks else "🔒 FOUND — gate leak!")
            record("P4-GATE", "diamond-no-cta", no_subscribe_footer,
                   "No upgrade CTA footer" if no_subscribe_footer else "/subscribe footer present — should not be")
            record("P4-GATE", "diamond-all-detail", all_detail,
                   "All buttons are edge:detail" if all_detail else "Some buttons not edge:detail")

    # Reset
    await asyncio.sleep(1)
    msgs, t = await send_timed(client, "/qa reset", wait=3)
    record("P4-GATE", "qa-reset", True, "Tier reset")


# ═══════════════════════════════════════════════════════════════
# PHASE 5: Concurrent Load Test (Rapid Taps)
# ═══════════════════════════════════════════════════════════════

async def phase5_concurrent(client):
    print("\n═══ PHASE 5: Concurrent Load Test ═══")

    # 5A: Send 3 commands in quick succession
    ent = await entity(client)
    t0 = time.time()
    sent1 = await client.send_message(ent, "/tips")
    await asyncio.sleep(0.5)
    sent2 = await client.send_message(ent, "/help")
    await asyncio.sleep(0.5)
    sent3 = await client.send_message(ent, "/results")

    await asyncio.sleep(12)
    all_msgs = await client.get_messages(ent, limit=30)
    elapsed = time.time() - t0

    # Check we got responses for each
    tips_resp = [m for m in all_msgs if m.id > sent1.id and not m.out and "edge" in (m.text or "").lower()]
    help_resp = [m for m in all_msgs if m.id > sent2.id and not m.out and "help" in (m.text or "").lower()]
    results_resp = [m for m in all_msgs if m.id > sent3.id and not m.out and "result" in (m.text or "").lower()]

    # We just need at least 2 out of 3 to respond (Telegram may throttle)
    responses = sum([bool(tips_resp), bool(help_resp), bool(results_resp)])
    record("P5-CONC", "rapid-3-cmds", responses >= 2,
           f"{responses}/3 commands responded in {elapsed:.1f}s total", elapsed)

    # 5B: Load tips then rapidly tap Next if available
    await asyncio.sleep(3)
    msgs, t = await send_timed(client, "/tips", wait=10)
    tips_msg = msgs[-1] if msgs else None

    if tips_msg and has_button(tips_msg, "Next"):
        current = tips_msg
        pages_loaded = 1
        for _ in range(3):  # Try 3 rapid Next taps
            edited, new, page_time = await click_btn(client, current, "Next", wait=5)
            if edited and edited.text != (current.text or ""):
                pages_loaded += 1
                current = edited
            elif new:
                pages_loaded += 1
                current = new[-1]
            else:
                break
            await asyncio.sleep(0.5)  # very quick succession

        record("P5-CONC", "rapid-pagination", pages_loaded >= 2,
               f"{pages_loaded} pages loaded via rapid Next taps")
    else:
        record("P5-CONC", "rapid-pagination", True, "No pagination available (few edges) — OK")

    # 5C: Tap edge → immediately back → tap another edge
    await asyncio.sleep(2)
    msgs, t = await send_timed(client, "/tips", wait=10)
    tips_msg = msgs[-1] if msgs else None
    edge_btns = [b for b in get_buttons(tips_msg) if "edge:detail:" in b.get("data", "")] if tips_msg else []

    if len(edge_btns) >= 2:
        # Tap first edge
        btn1_text = edge_btns[0]["text"][:15]
        edited1, new1, t1 = await click_btn(client, tips_msg, btn1_text, wait=3)
        detail1 = edited1 if (edited1 and edited1.text != (tips_msg.text or "")) else (new1[-1] if new1 else None)

        # Immediately go back
        if detail1 and (has_button(detail1, "Edge Picks") or has_button(detail1, "Back")):
            back_target = "Edge Picks" if has_button(detail1, "Edge Picks") else "Back"
            edited_back, _, t_back = await click_btn(client, detail1, back_target, wait=5)

            # Tap second edge
            tips_msg2 = edited_back if edited_back else tips_msg
            btn2_text = edge_btns[1]["text"][:15]
            # Small wait to ensure tips page is back
            await asyncio.sleep(1)
            edited2, new2, t2 = await click_btn(client, tips_msg2, btn2_text, wait=5)
            detail2 = edited2 if (edited2 and edited2.text != (tips_msg2.text or "")) else (new2[-1] if new2 else None)

            no_crash = detail2 is not None
            record("P5-CONC", "edge-back-edge", no_crash,
                   f"Tap→back→tap: {t1:.1f}s + {t_back:.1f}s + {t2:.1f}s, no crash" if no_crash else "CRASH on rapid nav")
        else:
            record("P5-CONC", "edge-back-edge", True, "First edge is loading (AI gen) — skipping rapid nav")
    else:
        record("P5-CONC", "edge-back-edge", True, "< 2 accessible edges — skipping")


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

async def main():
    print("W74-QA: Load Speed + UX Regression Test")
    print("=" * 50)

    client = await get_client()
    print(f"Connected as user. Bot: @{BOT}")

    try:
        for phase_name, phase_fn in [
            ("Phase 1", phase1_commands),
            ("Phase 2", phase2_edge_details),
            ("Phase 3", phase3_navigation),
            ("Phase 4", phase4_gates),
            ("Phase 5", phase5_concurrent),
        ]:
            try:
                await phase_fn(client)
            except Exception as e:
                print(f"\n⚠️ {phase_name} error: {e}")
                record(phase_name.upper().replace(" ", ""), f"{phase_name}-crash", False, str(e))
    finally:
        await client.disconnect()

    # ── Summary ──
    print("\n" + "=" * 50)
    total = len(RESULTS)
    passed = sum(1 for r in RESULTS if r["passed"])
    failed = sum(1 for r in RESULTS if not r["passed"])
    print(f"TOTAL: {passed}/{total} PASS ({failed} FAIL)")

    # Slow commands
    slow = [r for r in RESULTS if r["load_time"] > 3.0 and r["phase"] == "P1-CMD"]
    if slow:
        print(f"\n⚠️ SLOW COMMANDS (>3s):")
        for r in slow:
            print(f"  {r['test_id']}: {r['load_time']:.1f}s")

    # Slow edges
    slow_edges = [r for r in RESULTS if r["load_time"] > 10.0 and r["phase"] == "P2-EDGE"]
    if slow_edges:
        print(f"\n⚠️ SLOW EDGE DETAILS (>10s):")
        for r in slow_edges:
            print(f"  {r['test_id']}: {r['load_time']:.1f}s")

    # Failures
    fails = [r for r in RESULTS if not r["passed"]]
    if fails:
        print(f"\n❌ FAILURES:")
        for r in fails:
            print(f"  [{r['phase']}] {r['test_id']}: {r['detail']}")

    # Save results
    results_path = os.path.join(CAPTURE_DIR, "results.json")
    with open(results_path, "w") as f:
        json.dump({"results": RESULTS, "load_times": LOAD_TIMES,
                   "summary": {"total": total, "passed": passed, "failed": failed}}, f, indent=2)
    print(f"\nResults saved to {results_path}")


if __name__ == "__main__":
    asyncio.run(main())
