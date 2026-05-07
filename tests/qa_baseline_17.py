"""QA-BASELINE-17 — Runtime Performance E2E via Telethon.

PRIMARY test for this QA wave. Measures wall-clock response times for every
user-facing interaction using response polling (NOT static sleeps).

Thresholds:
  Hot Tips list first render   <= 3s PASS, > 5s FAIL
  Hot Tips detail (cache hit)  <= 2s PASS, > 4s FAIL
  My Matches list first render <= 3s PASS, > 5s FAIL
  My Matches detail (cache hit)<= 2s PASS, > 4s FAIL
  UX screens (Settings/Help)   <= 2s PASS, > 3s FAIL
  Detail card (cache miss)     <= 5s PASS, > 8s FAIL

Cache hit rate: >50% misses = P0, >20% misses = P1.

Usage:
    cd /home/paulsportsza/bot && .venv/bin/python tests/qa_baseline_17.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# ── Load .env ───────────────────────────────────────────
_env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
if os.path.exists(_env_path):
    with open(_env_path) as _ef:
        for _line in _ef:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _, _v = _line.partition("=")
                os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import (
    ReplyInlineMarkup,
    ReplyKeyboardMarkup as TLReplyKeyboardMarkup,
    KeyboardButtonCallback,
    KeyboardButtonUrl,
)

# ── Configuration ───────────────────────────────────────
API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "")
BOT_USERNAME = "mzansiedge_bot"
STRING_SESSION_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "telethon_qa_session.string")
SESSION_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "telethon_qa_session")

# Paths
REPORT_DIR = Path("/home/paulsportsza/reports")
RESULTS_JSON = REPORT_DIR / "qa-baseline-17-results.json"
RAW_CAPTURES = REPORT_DIR / "qa-baseline-17-raw-captures.txt"

# Performance thresholds (seconds)
THRESHOLDS = {
    "hot_tips_list":   {"pass": 3.0, "fail": 5.0},
    "hot_detail_hit":  {"pass": 2.0, "fail": 4.0},
    "hot_detail_miss": {"pass": 5.0, "fail": 8.0},
    "my_matches_list": {"pass": 3.0, "fail": 5.0},
    "mm_detail_hit":   {"pass": 2.0, "fail": 4.0},
    "mm_detail_miss":  {"pass": 5.0, "fail": 8.0},
    "ux_screen":       {"pass": 2.0, "fail": 3.0},
}

POLL_INTERVAL = 0.3   # seconds between polls
MAX_TIMEOUT = 30.0    # max wait for any response


# ── Data classes ────────────────────────────────────────

@dataclass
class TimingResult:
    name: str
    wall_time: float
    verdict: str = ""          # PASS / WARN / FAIL / TIMEOUT
    category: str = ""         # which threshold category
    cache_hit: bool | None = None  # True/False for detail cards, None for lists/UX
    text_len: int = 0
    raw_text: str = ""
    buttons: list = field(default_factory=list)
    notes: str = ""


@dataclass
class TestResults:
    timings: list[TimingResult] = field(default_factory=list)
    cache_hits: int = 0
    cache_misses: int = 0
    errors: list[str] = field(default_factory=list)
    started_at: str = ""
    finished_at: str = ""


# ── Client ──────────────────────────────────────────────

async def get_client() -> TelegramClient:
    """Connect via string session (preferred) or file session."""
    if os.path.exists(STRING_SESSION_FILE):
        s = open(STRING_SESSION_FILE).read().strip()
        if s:
            c = TelegramClient(StringSession(s), API_ID, API_HASH)
            await c.connect()
            if await c.is_user_authorized():
                return c
            await c.disconnect()
    c = TelegramClient(SESSION_FILE, API_ID, API_HASH)
    await c.connect()
    if not await c.is_user_authorized():
        print("FATAL: Not logged in to Telegram.")
        sys.exit(1)
    return c


# ── Polling helpers ─────────────────────────────────────

async def wait_for_response(client, entity, before_id, timeout=MAX_TIMEOUT, check_fn=None):
    """Poll for new message from bot after before_id. Returns (msg, wall_time)."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        msgs = await client.get_messages(entity, limit=10)
        for m in msgs:
            if m.id > before_id and not m.out:
                if check_fn is None or check_fn(m):
                    return m, time.time() - t0
        await asyncio.sleep(POLL_INTERVAL)
    return None, time.time() - t0


async def wait_for_edit(client, entity, msg_id, original_text, timeout=MAX_TIMEOUT):
    """Poll for message edit (callback response that edits existing message)."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            msg = await client.get_messages(entity, ids=msg_id)
            if msg:
                current_text = msg.message or msg.text or ""
                if current_text != original_text:
                    return msg, time.time() - t0
        except Exception:
            pass
        await asyncio.sleep(POLL_INTERVAL)
    return None, time.time() - t0


async def send_and_poll(client, entity, text, timeout=MAX_TIMEOUT, check_fn=None):
    """Send a text message and poll for bot response. Returns (response_msg, wall_time)."""
    # Get current latest message ID
    latest = await client.get_messages(entity, limit=1)
    before_id = latest[0].id if latest else 0

    await client.send_message(entity, text)
    return await wait_for_response(client, entity, before_id, timeout, check_fn)


async def click_and_poll_edit(client, msg, btn_data, timeout=MAX_TIMEOUT):
    """Click an inline button and poll for message edit. Returns (edited_msg, wall_time)."""
    original_text = msg.message or msg.text or ""
    # Find and click the button
    if msg.reply_markup and isinstance(msg.reply_markup, ReplyInlineMarkup):
        for row in msg.reply_markup.rows:
            for btn in row.buttons:
                if isinstance(btn, KeyboardButtonCallback) and btn.data:
                    if btn.data.decode().startswith(btn_data) if isinstance(btn_data, str) else btn.data == btn_data:
                        await msg.click(data=btn.data)
                        return await wait_for_edit(client, msg.peer_id, msg.id, original_text, timeout)
    return None, 0.0


async def click_and_poll_new(client, entity, msg, btn_data, timeout=MAX_TIMEOUT):
    """Click inline button and poll for NEW message (not edit). Returns (new_msg, wall_time)."""
    before_id = msg.id
    if msg.reply_markup and isinstance(msg.reply_markup, ReplyInlineMarkup):
        for row in msg.reply_markup.rows:
            for btn in row.buttons:
                if isinstance(btn, KeyboardButtonCallback) and btn.data:
                    if btn.data.decode().startswith(btn_data) if isinstance(btn_data, str) else btn.data == btn_data:
                        await msg.click(data=btn.data)
                        return await wait_for_response(client, entity, before_id, timeout)
    return None, 0.0


def get_inline_buttons(msg):
    """Extract all inline buttons from a message."""
    buttons = []
    if not msg or not msg.reply_markup or not isinstance(msg.reply_markup, ReplyInlineMarkup):
        return buttons
    for row in msg.reply_markup.rows:
        for btn in row.buttons:
            if isinstance(btn, KeyboardButtonCallback):
                buttons.append({
                    "text": btn.text,
                    "data": btn.data.decode() if btn.data else "",
                    "type": "callback"
                })
            elif isinstance(btn, KeyboardButtonUrl):
                buttons.append({
                    "text": btn.text,
                    "url": btn.url,
                    "type": "url"
                })
    return buttons


def classify_verdict(wall_time, category):
    """Classify a timing as PASS / WARN / FAIL / TIMEOUT."""
    th = THRESHOLDS.get(category)
    if not th:
        return "UNKNOWN"
    if wall_time <= th["pass"]:
        return "PASS"
    elif wall_time <= th["fail"]:
        return "WARN"
    else:
        return "FAIL"


# ── Main Test Flow ──────────────────────────────────────

async def run_performance_test():
    results = TestResults()
    results.started_at = datetime.now().isoformat()
    raw_captures = []

    client = await get_client()
    print("Connected to Telegram via Telethon")
    entity = await client.get_entity(BOT_USERNAME)

    try:
        # ════════════════════════════════════════════
        # STEP 1: /start
        # ════════════════════════════════════════════
        print("\n{'='*60}")
        print("STEP 1: /start command")
        print("="*60)
        msg, wall = await send_and_poll(client, entity, "/start")
        v = classify_verdict(wall, "ux_screen")
        tr = TimingResult(name="/start", wall_time=round(wall, 2), verdict=v,
                          category="ux_screen", text_len=len(msg.text) if msg else 0,
                          raw_text=(msg.text or "")[:500] if msg else "NO RESPONSE")
        results.timings.append(tr)
        print(f"  /start: {wall:.2f}s [{v}]")
        if msg:
            raw_captures.append(f"=== /start ({wall:.2f}s) ===\n{msg.text}\n")
        await asyncio.sleep(1.0)

        # ════════════════════════════════════════════
        # STEP 2: /qa set_diamond
        # ════════════════════════════════════════════
        print("\n" + "="*60)
        print("STEP 2: /qa set_diamond (set QA tier)")
        print("="*60)
        msg, wall = await send_and_poll(client, entity, "/qa set_diamond")
        print(f"  /qa set_diamond: {wall:.2f}s")
        if msg:
            raw_captures.append(f"=== /qa set_diamond ({wall:.2f}s) ===\n{msg.text}\n")
            print(f"  Response: {(msg.text or '')[:200]}")
        await asyncio.sleep(1.0)

        # ════════════════════════════════════════════
        # STEP 3: Hot Tips list
        # ════════════════════════════════════════════
        print("\n" + "="*60)
        print("STEP 3: Hot Tips list (Top Edge Picks)")
        print("="*60)

        # The bot edits the loading message into the final list, so we need
        # to detect a substantive response. Try send + poll for a message
        # that has inline buttons (the final rendered list).
        def is_hot_tips_list(m):
            text = m.message or m.text or ""
            has_content = len(text) > 50
            has_edge_keyword = any(kw in text.lower() for kw in ["edge", "pick", "scanned", "live edges"])
            return has_content and has_edge_keyword

        msg_ht, wall_ht = await send_and_poll(client, entity, "\U0001f48e Top Edge Picks",
                                               timeout=MAX_TIMEOUT, check_fn=is_hot_tips_list)

        # The bot may first send a loading message then edit it. If we got
        # the loading message, wait for it to be edited into the full list.
        if msg_ht:
            ht_text = msg_ht.message or msg_ht.text or ""
            # Check if this is still a loading/spinner message
            if len(ht_text) < 100 or "loading" in ht_text.lower() or "scanning" in ht_text.lower():
                # Wait for edit into full list
                edited, edit_wall = await wait_for_edit(client, entity, msg_ht.id, ht_text, timeout=25.0)
                if edited:
                    msg_ht = edited
                    wall_ht += edit_wall

        v_ht = classify_verdict(wall_ht, "hot_tips_list")
        ht_text_final = (msg_ht.message or msg_ht.text or "") if msg_ht else ""
        tr_ht = TimingResult(
            name="Hot Tips list", wall_time=round(wall_ht, 2), verdict=v_ht,
            category="hot_tips_list", text_len=len(ht_text_final),
            raw_text=ht_text_final[:3000],
            buttons=get_inline_buttons(msg_ht) if msg_ht else []
        )
        results.timings.append(tr_ht)
        print(f"  Hot Tips list: {wall_ht:.2f}s [{v_ht}] ({len(ht_text_final)} chars)")
        raw_captures.append(f"=== Hot Tips List ({wall_ht:.2f}s) ===\n{ht_text_final}\n")

        # If first attempt missed, try legacy label
        if not msg_ht or len(ht_text_final) < 50:
            print("  Retrying with legacy label: Hot Tips")
            msg_ht, wall_ht = await send_and_poll(client, entity, "\U0001f525 Hot Tips",
                                                   timeout=MAX_TIMEOUT, check_fn=is_hot_tips_list)
            if msg_ht:
                ht_text = msg_ht.message or msg_ht.text or ""
                if len(ht_text) < 100:
                    edited, edit_wall = await wait_for_edit(client, entity, msg_ht.id, ht_text, timeout=25.0)
                    if edited:
                        msg_ht = edited
                        wall_ht += edit_wall
                ht_text_final = (msg_ht.message or msg_ht.text or "") if msg_ht else ""
                v_ht = classify_verdict(wall_ht, "hot_tips_list")
                tr_ht.wall_time = round(wall_ht, 2)
                tr_ht.verdict = v_ht
                tr_ht.raw_text = ht_text_final[:3000]
                tr_ht.text_len = len(ht_text_final)
                tr_ht.buttons = get_inline_buttons(msg_ht) if msg_ht else []
                print(f"  Hot Tips (retry): {wall_ht:.2f}s [{v_ht}] ({len(ht_text_final)} chars)")

        # ════════════════════════════════════════════
        # STEP 4: Hot Tips detail cards
        # ════════════════════════════════════════════
        print("\n" + "="*60)
        print("STEP 4: Hot Tips detail cards")
        print("="*60)

        if msg_ht:
            all_btns = get_inline_buttons(msg_ht)
            edge_btns = [b for b in all_btns if b.get("data", "").startswith("edge:detail:")]
            upgrade_btns = [b for b in all_btns if b.get("data", "").startswith("hot:upgrade:")]
            detail_btns = edge_btns + upgrade_btns
            print(f"  Found {len(edge_btns)} edge detail buttons, {len(upgrade_btns)} upgrade buttons")

            for i, btn in enumerate(detail_btns):
                btn_data = btn["data"]
                btn_text = btn["text"]
                print(f"\n  Card {i+1}: '{btn_text}' -> {btn_data}")

                # Click button - bot edits the message
                t0 = time.time()
                edited, wall_d = await click_and_poll_edit(client, msg_ht, btn_data, timeout=MAX_TIMEOUT)
                detail_text = (edited.message or edited.text or "") if edited else ""

                # If we got a loading/spinner, wait for the real edit
                if edited and (len(detail_text) < 100 or "\u26bd" in detail_text[:5]):
                    intermediate_text = detail_text
                    edited2, wall_d2 = await wait_for_edit(client, entity, msg_ht.id, intermediate_text, timeout=25.0)
                    if edited2:
                        edited = edited2
                        wall_d += wall_d2
                        detail_text = (edited.message or edited.text or "") if edited else ""

                is_cache_hit = wall_d < 2.0
                if is_cache_hit:
                    results.cache_hits += 1
                    cat = "hot_detail_hit"
                else:
                    results.cache_misses += 1
                    cat = "hot_detail_miss"

                v_d = classify_verdict(wall_d, cat)
                detail_buttons = get_inline_buttons(edited) if edited else []

                tr_d = TimingResult(
                    name=f"HT detail: {btn_text[:40]}", wall_time=round(wall_d, 2),
                    verdict=v_d, category=cat, cache_hit=is_cache_hit,
                    text_len=len(detail_text), raw_text=detail_text[:3000],
                    buttons=detail_buttons
                )
                results.timings.append(tr_d)

                hit_label = "HIT" if is_cache_hit else "MISS"
                print(f"  Detail {i+1}: {wall_d:.2f}s [{v_d}] cache={hit_label} ({len(detail_text)} chars)")
                raw_captures.append(
                    f"=== HT Detail {i+1}: {btn_text} ({wall_d:.2f}s, cache {hit_label}) ===\n"
                    f"{detail_text}\n"
                    f"Buttons: {json.dumps([b['text'] for b in detail_buttons])}\n"
                )

                # Navigate back (only callback buttons, not URL buttons)
                if edited:
                    back_btns = [b for b in detail_buttons
                                 if b.get("type") == "callback" and "data" in b
                                 and ("back" in b["data"].lower() or "edge picks" in b.get("text", "").lower()
                                      or b["data"].startswith("hot:back"))]
                    if back_btns:
                        back_data = back_btns[0]["data"]
                        print(f"  Clicking back: {back_data}")
                        t0_back = time.time()
                        back_msg, wall_back = await click_and_poll_edit(
                            client, edited, back_data, timeout=15.0
                        )
                        wall_back_total = time.time() - t0_back
                        print(f"  Back navigation: {wall_back_total:.2f}s")

                        # Update msg_ht reference if we got back the list
                        if back_msg:
                            msg_ht = back_msg

                        tr_back = TimingResult(
                            name=f"HT back from card {i+1}", wall_time=round(wall_back_total, 2),
                            verdict=classify_verdict(wall_back_total, "hot_detail_hit"),
                            category="hot_detail_hit"
                        )
                        results.timings.append(tr_back)
                    else:
                        print("  No back button found, continuing...")

                await asyncio.sleep(0.5)
        else:
            results.errors.append("Hot Tips list did not load - skipping detail cards")
            print("  SKIP: Hot Tips list did not load")

        # ════════════════════════════════════════════
        # STEP 5: My Matches list
        # ════════════════════════════════════════════
        print("\n" + "="*60)
        print("STEP 5: My Matches list")
        print("="*60)

        def is_my_matches(m):
            text = m.message or m.text or ""
            has_content = len(text) > 30
            has_keyword = any(kw in text.lower() for kw in ["match", "game", "schedule", "fixture", "no live"])
            return has_content and has_keyword

        msg_mm, wall_mm = await send_and_poll(client, entity, "\u26bd My Matches",
                                               timeout=MAX_TIMEOUT, check_fn=is_my_matches)

        # Check for loading message -> edit
        if msg_mm:
            mm_text = msg_mm.message or msg_mm.text or ""
            if len(mm_text) < 80 or "loading" in mm_text.lower():
                edited, edit_wall = await wait_for_edit(client, entity, msg_mm.id, mm_text, timeout=25.0)
                if edited:
                    msg_mm = edited
                    wall_mm += edit_wall

        mm_text_final = (msg_mm.message or msg_mm.text or "") if msg_mm else ""
        v_mm = classify_verdict(wall_mm, "my_matches_list")
        tr_mm = TimingResult(
            name="My Matches list", wall_time=round(wall_mm, 2), verdict=v_mm,
            category="my_matches_list", text_len=len(mm_text_final),
            raw_text=mm_text_final[:3000],
            buttons=get_inline_buttons(msg_mm) if msg_mm else []
        )
        results.timings.append(tr_mm)
        print(f"  My Matches list: {wall_mm:.2f}s [{v_mm}] ({len(mm_text_final)} chars)")
        raw_captures.append(f"=== My Matches List ({wall_mm:.2f}s) ===\n{mm_text_final}\n")

        # If first attempt missed, try legacy label
        if not msg_mm or len(mm_text_final) < 30:
            print("  Retrying with legacy label: Your Games")
            msg_mm, wall_mm = await send_and_poll(client, entity, "\u26bd Your Games",
                                                   timeout=MAX_TIMEOUT, check_fn=is_my_matches)
            if msg_mm:
                mm_text = msg_mm.message or msg_mm.text or ""
                if len(mm_text) < 80:
                    edited, edit_wall = await wait_for_edit(client, entity, msg_mm.id, mm_text, timeout=25.0)
                    if edited:
                        msg_mm = edited
                        wall_mm += edit_wall
                mm_text_final = (msg_mm.message or msg_mm.text or "") if msg_mm else ""
                v_mm = classify_verdict(wall_mm, "my_matches_list")
                tr_mm.wall_time = round(wall_mm, 2)
                tr_mm.verdict = v_mm
                tr_mm.raw_text = mm_text_final[:3000]
                tr_mm.text_len = len(mm_text_final)
                print(f"  My Matches (retry): {wall_mm:.2f}s [{v_mm}]")

        # ════════════════════════════════════════════
        # STEP 6: My Matches detail cards (up to 3)
        # ════════════════════════════════════════════
        print("\n" + "="*60)
        print("STEP 6: My Matches detail cards")
        print("="*60)

        if msg_mm:
            mm_btns = get_inline_buttons(msg_mm)
            # Game detail buttons use yg:game: pattern
            game_btns = [b for b in mm_btns if b.get("data", "").startswith("yg:game:")]
            print(f"  Found {len(game_btns)} game detail buttons")

            for i, btn in enumerate(game_btns[:3]):
                btn_data = btn["data"]
                btn_text = btn["text"]
                print(f"\n  Game {i+1}: '{btn_text}' -> {btn_data}")

                t0 = time.time()
                edited, wall_gd = await click_and_poll_edit(client, msg_mm, btn_data, timeout=MAX_TIMEOUT)
                detail_text = (edited.message or edited.text or "") if edited else ""

                # If spinner/loading, wait for real content
                if edited and len(detail_text) < 100:
                    intermediate = detail_text
                    edited2, wall_gd2 = await wait_for_edit(client, entity, msg_mm.id, intermediate, timeout=25.0)
                    if edited2:
                        edited = edited2
                        wall_gd += wall_gd2
                        detail_text = (edited.message or edited.text or "") if edited else ""

                is_cache_hit = wall_gd < 2.0
                if is_cache_hit:
                    results.cache_hits += 1
                    cat = "mm_detail_hit"
                else:
                    results.cache_misses += 1
                    cat = "mm_detail_miss"

                v_gd = classify_verdict(wall_gd, cat)
                detail_buttons = get_inline_buttons(edited) if edited else []

                tr_gd = TimingResult(
                    name=f"MM detail: {btn_text[:40]}", wall_time=round(wall_gd, 2),
                    verdict=v_gd, category=cat, cache_hit=is_cache_hit,
                    text_len=len(detail_text), raw_text=detail_text[:3000],
                    buttons=detail_buttons
                )
                results.timings.append(tr_gd)

                hit_label = "HIT" if is_cache_hit else "MISS"
                print(f"  Game {i+1}: {wall_gd:.2f}s [{v_gd}] cache={hit_label} ({len(detail_text)} chars)")
                raw_captures.append(
                    f"=== MM Detail {i+1}: {btn_text} ({wall_gd:.2f}s, cache {hit_label}) ===\n"
                    f"{detail_text}\n"
                    f"Buttons: {json.dumps([b['text'] for b in detail_buttons])}\n"
                )

                # Navigate back (only callback buttons, not URL buttons)
                if edited:
                    back_btns = [b for b in detail_buttons
                                 if b.get("type") == "callback" and "data" in b
                                 and ("back" in b["data"].lower() or "yg:all" in b["data"]
                                      or "my matches" in b.get("text", "").lower())]
                    if back_btns:
                        back_data = back_btns[0]["data"]
                        t0_back = time.time()
                        back_msg, _ = await click_and_poll_edit(client, edited, back_data, timeout=15.0)
                        wall_back_total = time.time() - t0_back
                        print(f"  Back: {wall_back_total:.2f}s")
                        if back_msg:
                            msg_mm = back_msg

                await asyncio.sleep(0.5)
        else:
            results.errors.append("My Matches list did not load - skipping detail cards")
            print("  SKIP: My Matches list did not load")

        # ════════════════════════════════════════════
        # STEP 7: Settings screen
        # ════════════════════════════════════════════
        print("\n" + "="*60)
        print("STEP 7: UX screens (Settings)")
        print("="*60)

        def is_settings(m):
            text = m.message or m.text or ""
            # Settings reply can be very short ("Settings") with inline buttons
            has_keyword = any(kw in text.lower() for kw in ["settings", "profile", "risk", "notification", "bankroll"])
            has_inline = m.reply_markup and isinstance(m.reply_markup, ReplyInlineMarkup)
            return has_keyword or (has_inline and len(text) > 5)

        msg_set, wall_set = await send_and_poll(client, entity, "\u2699\ufe0f Settings",
                                                 timeout=MAX_TIMEOUT, check_fn=is_settings)
        if not msg_set:
            # Fallback: try /settings
            msg_set, wall_set = await send_and_poll(client, entity, "/settings",
                                                     timeout=MAX_TIMEOUT, check_fn=is_settings)

        set_text = (msg_set.message or msg_set.text or "") if msg_set else ""
        v_set = classify_verdict(wall_set, "ux_screen")
        tr_set = TimingResult(
            name="Settings", wall_time=round(wall_set, 2), verdict=v_set,
            category="ux_screen", text_len=len(set_text),
            raw_text=set_text[:1000],
            buttons=get_inline_buttons(msg_set) if msg_set else []
        )
        results.timings.append(tr_set)
        print(f"  Settings: {wall_set:.2f}s [{v_set}] ({len(set_text)} chars)")
        raw_captures.append(f"=== Settings ({wall_set:.2f}s) ===\n{set_text}\n")
        await asyncio.sleep(0.5)

        # ════════════════════════════════════════════
        # STEP 8: Help screen
        # ════════════════════════════════════════════
        print("\n" + "="*60)
        print("STEP 8: UX screens (Help)")
        print("="*60)

        def is_help(m):
            text = m.message or m.text or ""
            return len(text) > 20 and any(kw in text.lower() for kw in ["help", "command", "guide", "how", "edge"])

        msg_help, wall_help = await send_and_poll(client, entity, "\u2753 Help",
                                                   timeout=MAX_TIMEOUT, check_fn=is_help)
        if not msg_help:
            msg_help, wall_help = await send_and_poll(client, entity, "/help",
                                                       timeout=MAX_TIMEOUT, check_fn=is_help)

        help_text = (msg_help.message or msg_help.text or "") if msg_help else ""
        v_help = classify_verdict(wall_help, "ux_screen")
        tr_help = TimingResult(
            name="Help", wall_time=round(wall_help, 2), verdict=v_help,
            category="ux_screen", text_len=len(help_text),
            raw_text=help_text[:1000],
            buttons=get_inline_buttons(msg_help) if msg_help else []
        )
        results.timings.append(tr_help)
        print(f"  Help: {wall_help:.2f}s [{v_help}] ({len(help_text)} chars)")
        raw_captures.append(f"=== Help ({wall_help:.2f}s) ===\n{help_text}\n")
        await asyncio.sleep(0.5)

        # ════════════════════════════════════════════
        # STEP 9: /qa reset
        # ════════════════════════════════════════════
        print("\n" + "="*60)
        print("STEP 9: /qa reset (cleanup)")
        print("="*60)
        msg_reset, wall_reset = await send_and_poll(client, entity, "/qa reset")
        print(f"  /qa reset: {wall_reset:.2f}s")
        if msg_reset:
            raw_captures.append(f"=== /qa reset ({wall_reset:.2f}s) ===\n{msg_reset.text}\n")

    except Exception as e:
        results.errors.append(f"Test error: {e}\n{traceback.format_exc()}")
        print(f"\nERROR: {e}")
        traceback.print_exc()

        # Try to clean up QA state
        try:
            await client.send_message(entity, "/qa reset")
            await asyncio.sleep(2)
        except Exception:
            pass
    finally:
        await client.disconnect()

    results.finished_at = datetime.now().isoformat()
    return results, raw_captures


# ── Output + Summary ────────────────────────────────────

def print_summary(results: TestResults):
    """Print a formatted summary table."""
    print("\n" + "="*80)
    print("QA-BASELINE-17 PERFORMANCE RESULTS")
    print("="*80)
    print(f"Started:  {results.started_at}")
    print(f"Finished: {results.finished_at}")
    print()

    # Timing table
    print(f"{'Interaction':<45} {'Time':>7} {'Verdict':>8} {'Cache':>6} {'Chars':>6}")
    print("-"*80)
    for t in results.timings:
        cache_str = ""
        if t.cache_hit is True:
            cache_str = "HIT"
        elif t.cache_hit is False:
            cache_str = "MISS"
        print(f"{t.name:<45} {t.wall_time:>6.2f}s {t.verdict:>8} {cache_str:>6} {t.text_len:>6}")

    # Cache statistics
    total_detail = results.cache_hits + results.cache_misses
    print()
    print("-"*80)
    print("CACHE STATISTICS:")
    if total_detail > 0:
        hit_rate = results.cache_hits / total_detail * 100
        miss_rate = results.cache_misses / total_detail * 100
        print(f"  Cache hits:   {results.cache_hits}/{total_detail} ({hit_rate:.0f}%)")
        print(f"  Cache misses: {results.cache_misses}/{total_detail} ({miss_rate:.0f}%)")
        if miss_rate > 50:
            print(f"  STATUS: P0 -- miss rate {miss_rate:.0f}% > 50%")
        elif miss_rate > 20:
            print(f"  STATUS: P1 -- miss rate {miss_rate:.0f}% > 20%")
        else:
            print(f"  STATUS: PASS -- miss rate {miss_rate:.0f}% <= 20%")
    else:
        print("  No detail cards tested.")

    # Count pass/warn/fail
    passes = sum(1 for t in results.timings if t.verdict == "PASS")
    warns = sum(1 for t in results.timings if t.verdict == "WARN")
    fails = sum(1 for t in results.timings if t.verdict == "FAIL")
    timeouts = sum(1 for t in results.timings if t.verdict == "TIMEOUT")

    print()
    print(f"VERDICTS: {passes} PASS, {warns} WARN, {fails} FAIL, {timeouts} TIMEOUT")

    if results.errors:
        print()
        print("ERRORS:")
        for e in results.errors:
            print(f"  - {e[:200]}")

    # Overall verdict
    print()
    if fails > 0 or timeouts > 0:
        print("OVERALL: FAIL")
    elif warns > 0:
        print("OVERALL: WARN (all within FAIL thresholds, some exceeded PASS targets)")
    else:
        print("OVERALL: PASS")
    print("="*80)


def save_results(results: TestResults, raw_captures: list[str]):
    """Save JSON results and raw captures."""
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    # JSON results
    json_data = {
        "wave": "QA-BASELINE-17",
        "test": "runtime_performance",
        "started_at": results.started_at,
        "finished_at": results.finished_at,
        "thresholds": THRESHOLDS,
        "cache": {
            "hits": results.cache_hits,
            "misses": results.cache_misses,
            "total": results.cache_hits + results.cache_misses,
            "hit_rate_pct": round(results.cache_hits / max(results.cache_hits + results.cache_misses, 1) * 100, 1),
        },
        "timings": [
            {
                "name": t.name,
                "wall_time_s": t.wall_time,
                "verdict": t.verdict,
                "category": t.category,
                "cache_hit": t.cache_hit,
                "text_len": t.text_len,
                "buttons": [b.get("text", "") for b in t.buttons] if t.buttons else [],
                "raw_text_preview": t.raw_text[:500],
            }
            for t in results.timings
        ],
        "errors": results.errors,
        "verdicts": {
            "pass": sum(1 for t in results.timings if t.verdict == "PASS"),
            "warn": sum(1 for t in results.timings if t.verdict == "WARN"),
            "fail": sum(1 for t in results.timings if t.verdict == "FAIL"),
            "timeout": sum(1 for t in results.timings if t.verdict == "TIMEOUT"),
        },
    }

    with open(RESULTS_JSON, "w") as f:
        json.dump(json_data, f, indent=2)
    print(f"\nResults JSON saved to: {RESULTS_JSON}")

    # Raw captures
    with open(RAW_CAPTURES, "w") as f:
        f.write(f"QA-BASELINE-17 Raw Captures\n")
        f.write(f"Generated: {results.started_at}\n")
        f.write("="*80 + "\n\n")
        for cap in raw_captures:
            f.write(cap)
            f.write("\n" + "-"*60 + "\n\n")
    print(f"Raw captures saved to: {RAW_CAPTURES}")


# ── Entry point ─────────────────────────────────────────

async def main():
    results, raw_captures = await run_performance_test()
    print_summary(results)
    save_results(results, raw_captures)


if __name__ == "__main__":
    asyncio.run(main())
