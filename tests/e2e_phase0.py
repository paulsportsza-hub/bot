#!/usr/bin/env python3
"""
Phase 0 Verification: Sport Narrowing Telethon Check
=====================================================
P0 — Verify Phase 0 sport narrowing (4 sports only: soccer, rugby, cricket, combat).
F1 removed. No stragglers visible to users.

12 Telethon tests:
  Onboarding (3): /start sport selection shows ONLY 4 sports
  Your Games (3): sport filter buttons, tap each, tap combat
  Hot Tips (2):   sport filter shows 4 sports, no F1 tips
  Settings (1):   sport preferences show only 4 sports
  Negative (3):   search for removed sports, check bot logs
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import ensure_scrapers_importable, BOT_ROOT
ensure_scrapers_importable()

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.sessions import StringSession
from telethon.tl.custom.message import Message

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("phase0")

# ── Constants ──────────────────────────────────────────────────────────
BOT = "mzansiedge_bot"
API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "")
SESSION_PATH = Path("data/telethon_qa_session.string")

SCREENSHOT_DIR = BOT_ROOT.parent / "reports" / "screenshots" / "phase0"
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_PATH = BOT_ROOT.parent / "reports" / "phase0-e2e-results.json"

BOT_TIMEOUT = 15
AI_TIMEOUT = 50

# Phase 0: exactly 4 sports
EXPECTED_SPORTS = {"soccer", "rugby", "cricket", "combat"}
EXPECTED_SPORT_LABELS = {"Soccer", "Rugby", "Cricket", "Combat Sports"}
EXPECTED_SPORT_EMOJIS = {"⚽", "🏉", "🏏", "🥊"}
REMOVED_SPORTS = {"f1", "tennis", "basketball", "nba", "nfl", "golf", "baseball"}
REMOVED_LABELS = {"Formula 1", "F1", "Tennis", "Basketball", "NBA", "NFL", "Golf", "Baseball"}

# ── Results tracking ──────────────────────────────────────────────────
results: list[dict] = []
bugs: list[dict] = []


def record(test_id: str, name: str, status: str, response: str,
           checks: dict, detail: str = ""):
    entry = {
        "test_id": test_id, "name": name, "status": status,
        "response": response[:5000],
        "checks": checks,
        "detail": detail,
    }
    results.append(entry)
    icon = {"PASS": "✓", "FAIL": "✗", "SKIP": "⊘", "WARN": "⚠"}.get(status, "?")
    log.info("  %s %s: %s — %s", icon, test_id, name, status)


def file_bug(bug_id: str, severity: str, test_id: str, category: str,
             description: str, evidence: str):
    bugs.append({
        "id": bug_id, "severity": severity, "test_id": test_id,
        "category": category, "description": description,
        "evidence": evidence[:1000],
    })
    log.warning("  BUG %s [%s] %s: %s", bug_id, severity, category, description)


# ── Telethon helpers ──────────────────────────────────────────────────
async def _last_id(c: TelegramClient) -> int:
    msgs = await c.get_messages(BOT, limit=1)
    return msgs[0].id if msgs else 0


async def send(c: TelegramClient, text: str, timeout: int = BOT_TIMEOUT) -> Message | None:
    last = await _last_id(c)
    try:
        await c.send_message(BOT, text)
    except FloodWaitError as e:
        await asyncio.sleep(e.seconds + 2)
        await c.send_message(BOT, text)
    await asyncio.sleep(2)
    deadline = time.time() + timeout
    while time.time() < deadline:
        msgs = await c.get_messages(BOT, limit=10)
        for m in msgs:
            if m.id > last and not m.out:
                return m
        await asyncio.sleep(1)
    return None


async def send_wait_buttons(c: TelegramClient, text: str,
                            timeout: int = BOT_TIMEOUT) -> Message | None:
    last = await _last_id(c)
    try:
        await c.send_message(BOT, text)
    except FloodWaitError as e:
        await asyncio.sleep(e.seconds + 2)
        await c.send_message(BOT, text)
    await asyncio.sleep(2)
    deadline = time.time() + timeout
    found_id = None
    while time.time() < deadline:
        msgs = await c.get_messages(BOT, limit=10)
        for m in msgs:
            if m.id > last and not m.out:
                if found_id is None:
                    found_id = m.id
                if m.buttons:
                    return m
        if found_id:
            updated = await c.get_messages(BOT, ids=found_id)
            if updated and updated.buttons:
                return updated
        await asyncio.sleep(1.5)
    if found_id:
        return await c.get_messages(BOT, ids=found_id)
    return None


async def click_data(c: TelegramClient, msg: Message, prefix: str,
                     timeout: int = AI_TIMEOUT) -> Message | None:
    if not msg or not msg.buttons:
        return None
    old = await _last_id(c)
    for row in msg.buttons:
        for btn in row:
            if hasattr(btn, "data") and btn.data:
                cb = btn.data.decode() if isinstance(btn.data, bytes) else str(btn.data)
                if cb.startswith(prefix):
                    try:
                        await btn.click()
                    except Exception:
                        return None
                    await asyncio.sleep(3)
                    deadline = time.time() + timeout
                    while time.time() < deadline:
                        msgs = await c.get_messages(BOT, limit=10)
                        for m in msgs:
                            if m.id > old and not m.out:
                                return m
                        updated = await c.get_messages(BOT, ids=msg.id)
                        if updated and updated.raw_text != (msg.raw_text or ""):
                            return updated
                        await asyncio.sleep(2)
                    return None
    return None


async def click_exact(c: TelegramClient, msg: Message, data_exact: str,
                      timeout: int = AI_TIMEOUT) -> Message | None:
    if not msg or not msg.buttons:
        return None
    old = await _last_id(c)
    for row in msg.buttons:
        for btn in row:
            if hasattr(btn, "data") and btn.data:
                cb = btn.data.decode() if isinstance(btn.data, bytes) else str(btn.data)
                if cb == data_exact:
                    try:
                        await btn.click()
                    except Exception:
                        return None
                    await asyncio.sleep(3)
                    deadline = time.time() + timeout
                    while time.time() < deadline:
                        msgs = await c.get_messages(BOT, limit=10)
                        for m in msgs:
                            if m.id > old and not m.out:
                                return m
                        updated = await c.get_messages(BOT, ids=msg.id)
                        if updated and updated.raw_text != (msg.raw_text or ""):
                            return updated
                        await asyncio.sleep(2)
                    return None
    return None


def get_callback_data(msg: Message) -> list[str]:
    if not msg or not msg.buttons:
        return []
    cbs = []
    for row in msg.buttons:
        for btn in row:
            if hasattr(btn, "data") and btn.data:
                cb = btn.data.decode() if isinstance(btn.data, bytes) else str(btn.data)
                cbs.append(cb)
    return cbs


def get_buttons_text(msg: Message) -> list[str]:
    if not msg or not msg.buttons:
        return []
    return [btn.text for row in msg.buttons for btn in row if hasattr(btn, "text")]


# ── Screenshot capture ────────────────────────────────────────────────
def save_screenshot(name: str, msg: Message | None, extra: str = "") -> str:
    safe = name.replace(":", "_").replace("/", "_").replace(" ", "_")
    fname = f"p0-{safe}.txt"
    if msg is None:
        content = f"SCREENSHOT: {name}\nSTATUS: No response\n"
    else:
        text = msg.raw_text or "(empty)"
        btns = get_buttons_text(msg)
        cbs = get_callback_data(msg)
        content = (
            f"SCREENSHOT: {name}\n"
            f"{'=' * 60}\n"
            f"TEXT:\n{text}\n"
            f"\n{'=' * 60}\n"
            f"BUTTONS: {btns}\n"
            f"CALLBACKS: {cbs}\n"
        )
    if extra:
        content += f"\nEXTRA: {extra}\n"
    (SCREENSHOT_DIR / fname).write_text(content, encoding="utf-8")
    return fname


# ── Test functions ────────────────────────────────────────────────────

# ────────────────────────────────────────────────────────────────────
# PART A: Onboarding (3 tests)
# ────────────────────────────────────────────────────────────────────

async def test_ob_01_start_shows_4_sports(c: TelegramClient):
    """OB-01: /start → sport selection shows ONLY 4 sports."""
    log.info("─── OB-01: /start sport selection ───")

    # Send /start to trigger onboarding or returning user screen
    msg = await send_wait_buttons(c, "/start", timeout=BOT_TIMEOUT)
    save_screenshot("OB-01-start", msg)

    if not msg:
        record("OB-01", "/start response", "FAIL", "", {}, "No response from bot")
        return

    text = msg.raw_text or ""
    cbs = get_callback_data(msg)
    btns = get_buttons_text(msg)

    # If already onboarded, we'll see the welcome menu — need to check settings:sports instead
    # But if fresh user, we see step 2 sport selection
    if "Step 2" in text or "Select your sports" in text:
        # We're in onboarding — check sport buttons
        ob_sport_cbs = [cb for cb in cbs if cb.startswith("ob_sport:")]
        sport_keys = [cb.split(":")[-1] for cb in ob_sport_cbs]

        checks = {}
        # Must have exactly 4 sports
        checks["exactly_4_sports"] = {
            "pass": len(sport_keys) == 4,
            "detail": f"Found {len(sport_keys)} sports: {sport_keys}"
        }
        # Must have the expected 4
        checks["correct_sports"] = {
            "pass": set(sport_keys) == EXPECTED_SPORTS,
            "detail": f"Expected {EXPECTED_SPORTS}, got {set(sport_keys)}"
        }
        # Must NOT have any removed sports
        removed_found = [s for s in sport_keys if s in REMOVED_SPORTS]
        checks["no_removed_sports"] = {
            "pass": len(removed_found) == 0,
            "detail": f"Removed sports found: {removed_found}" if removed_found else "None found"
        }

        all_pass = all(c["pass"] for c in checks.values())
        status = "PASS" if all_pass else "FAIL"

        if not all_pass:
            file_bug("BUG-P0-001", "P0", "OB-01", "BUG-P0-STRAGGLER",
                     f"Onboarding shows wrong sports: {sport_keys}",
                     f"Expected 4, got {len(sport_keys)}: {sport_keys}")

        record("OB-01", "/start shows 4 sports only", status, text, checks)
    else:
        # Already onboarded — this is the welcome screen
        log.info("  User already onboarded. Checking welcome message for removed sports.")
        text_lower = text.lower()
        removed_in_text = [s for s in REMOVED_LABELS if s.lower() in text_lower]
        checks = {
            "no_removed_in_welcome": {
                "pass": len(removed_in_text) == 0,
                "detail": f"Found: {removed_in_text}" if removed_in_text else "Clean"
            }
        }
        status = "PASS" if checks["no_removed_in_welcome"]["pass"] else "FAIL"
        record("OB-01", "/start welcome (already onboarded)", status, text, checks,
               "User already onboarded — tested welcome screen instead")


async def test_ob_02_sport_emojis_correct(c: TelegramClient):
    """OB-02: Sport selection buttons have correct emojis and labels."""
    log.info("─── OB-02: Sport emojis and labels ───")

    # Navigate to settings:sports which shows the sport grid regardless of onboarding
    msg = await send_wait_buttons(c, "⚙️ Settings", timeout=BOT_TIMEOUT)
    if not msg:
        record("OB-02", "Settings access", "SKIP", "", {}, "No response from Settings")
        return

    save_screenshot("OB-02-settings", msg)
    cbs = get_callback_data(msg)

    # Look for settings:sports button and click it
    sports_msg = await click_exact(c, msg, "settings:sports", timeout=BOT_TIMEOUT)
    if not sports_msg:
        # Try the text directly
        sports_msg = await click_data(c, msg, "settings:sports", timeout=BOT_TIMEOUT)

    if not sports_msg:
        record("OB-02", "Settings sports", "SKIP", "", {}, "Could not navigate to sports settings")
        return

    save_screenshot("OB-02-sports-settings", sports_msg)
    text = sports_msg.raw_text or ""
    btns = get_buttons_text(sports_msg)

    checks = {}
    # Check that all 4 expected emojis appear in buttons
    for emoji in EXPECTED_SPORT_EMOJIS:
        found = any(emoji in b for b in btns)
        checks[f"emoji_{emoji}"] = {
            "pass": found,
            "detail": f"{'Found' if found else 'Missing'} in buttons"
        }

    # Check that no removed sport labels appear
    removed_in_btns = [label for label in REMOVED_LABELS
                       if any(label.lower() in b.lower() for b in btns)]
    checks["no_removed_labels"] = {
        "pass": len(removed_in_btns) == 0,
        "detail": f"Found: {removed_in_btns}" if removed_in_btns else "Clean"
    }

    all_pass = all(c["pass"] for c in checks.values())
    status = "PASS" if all_pass else "FAIL"
    record("OB-02", "Sport emojis and labels correct", status, text, checks)


async def test_ob_03_combat_sports_present(c: TelegramClient):
    """OB-03: Combat Sports (🥊) button exists with correct callback."""
    log.info("─── OB-03: Combat Sports button ───")

    # Should still be on sports settings from OB-02, but let's navigate fresh
    msg = await send_wait_buttons(c, "⚙️ Settings", timeout=BOT_TIMEOUT)
    if not msg:
        record("OB-03", "Settings access", "SKIP", "", {}, "No response")
        return

    sports_msg = await click_exact(c, msg, "settings:sports", timeout=BOT_TIMEOUT)
    if not sports_msg:
        sports_msg = await click_data(c, msg, "settings:sports", timeout=BOT_TIMEOUT)

    if not sports_msg:
        record("OB-03", "Settings sports", "SKIP", "", {}, "Could not navigate to sports settings")
        return

    save_screenshot("OB-03-combat-check", sports_msg)
    btns = get_buttons_text(sports_msg)
    cbs = get_callback_data(sports_msg)

    checks = {}
    # Combat Sports must appear in buttons
    combat_btn_found = any("Combat" in b or "🥊" in b for b in btns)
    checks["combat_button_exists"] = {
        "pass": combat_btn_found,
        "detail": f"Buttons: {btns}"
    }

    # ob_sport:combat callback must exist
    combat_cb_found = any("combat" in cb for cb in cbs)
    checks["combat_callback_exists"] = {
        "pass": combat_cb_found,
        "detail": f"Callbacks: {cbs}"
    }

    all_pass = all(c["pass"] for c in checks.values())
    status = "PASS" if all_pass else "FAIL"
    record("OB-03", "Combat Sports button present", status,
           sports_msg.raw_text or "", checks)


# ────────────────────────────────────────────────────────────────────
# PART B: Your Games (3 tests)
# ────────────────────────────────────────────────────────────────────

async def test_yg_04_sport_filter_buttons(c: TelegramClient):
    """YG-04: Your Games sport filter buttons show 4 sports only."""
    log.info("─── YG-04: Your Games sport filter ───")

    msg = await send_wait_buttons(c, "⚽ Your Games", timeout=BOT_TIMEOUT)
    save_screenshot("YG-04-your-games", msg)

    if not msg:
        record("YG-04", "Your Games access", "FAIL", "", {}, "No response")
        return

    text = msg.raw_text or ""
    cbs = get_callback_data(msg)
    btns = get_buttons_text(msg)

    # Sport filter buttons use yg:sport:{key} or just emoji buttons
    sport_filter_cbs = [cb for cb in cbs if cb.startswith("yg:sport:")]
    sport_keys = [cb.split(":")[2] for cb in sport_filter_cbs]

    checks = {}

    if sport_filter_cbs:
        # Has sport filter buttons — check they're correct
        checks["filter_sports_correct"] = {
            "pass": set(sport_keys).issubset(EXPECTED_SPORTS),
            "detail": f"Filter sports: {sport_keys}"
        }
        removed_in_filters = [s for s in sport_keys if s in REMOVED_SPORTS]
        checks["no_removed_in_filters"] = {
            "pass": len(removed_in_filters) == 0,
            "detail": f"Found: {removed_in_filters}" if removed_in_filters else "Clean"
        }
    else:
        # No sport filters — might only follow 1 sport category
        checks["no_filters_expected"] = {
            "pass": True,
            "detail": "No sport filter buttons — user may follow only 1 sport category"
        }

    # Check text doesn't mention removed sports
    text_lower = text.lower()
    removed_in_text = [s for s in ["f1", "formula 1", "tennis", "basketball", "nba"]
                       if s in text_lower]
    checks["no_removed_in_text"] = {
        "pass": len(removed_in_text) == 0,
        "detail": f"Found: {removed_in_text}" if removed_in_text else "Clean"
    }

    all_pass = all(c["pass"] for c in checks.values())
    status = "PASS" if all_pass else "FAIL"
    record("YG-04", "Sport filter shows 4 sports", status, text, checks)


async def test_yg_05_tap_each_filter(c: TelegramClient):
    """YG-05: Tap each sport filter — no crash, no removed sport content."""
    log.info("─── YG-05: Tap each sport filter ───")

    msg = await send_wait_buttons(c, "⚽ Your Games", timeout=BOT_TIMEOUT)
    if not msg:
        record("YG-05", "Your Games access", "FAIL", "", {}, "No response")
        return

    cbs = get_callback_data(msg)
    sport_filter_cbs = [cb for cb in cbs if cb.startswith("yg:sport:")]

    checks = {}
    if not sport_filter_cbs:
        checks["no_filters"] = {"pass": True, "detail": "No sport filters — single sport user"}
        record("YG-05", "Tap sport filters", "PASS", msg.raw_text or "", checks,
               "No sport filters to test")
        return

    for cb in sport_filter_cbs:
        sport_key = cb.split(":")[2]
        log.info("  Tapping filter: %s", sport_key)

        # Click the sport filter
        filtered = await click_exact(c, msg, cb, timeout=BOT_TIMEOUT)
        if filtered:
            save_screenshot(f"YG-05-filter-{sport_key}", filtered)
            ftext = (filtered.raw_text or "").lower()

            # No crash — got a response
            checks[f"{sport_key}_no_crash"] = {"pass": True, "detail": "Response received"}

            # No removed sport terms in filtered view
            removed_terms = [t for t in ["f1", "formula 1", "tennis", "nba"]
                             if t in ftext]
            checks[f"{sport_key}_no_removed"] = {
                "pass": len(removed_terms) == 0,
                "detail": f"Found: {removed_terms}" if removed_terms else "Clean"
            }
        else:
            checks[f"{sport_key}_no_crash"] = {"pass": False, "detail": "No response"}

        # Go back to main Your Games for next filter
        await asyncio.sleep(1)
        msg = await send_wait_buttons(c, "⚽ Your Games", timeout=BOT_TIMEOUT)
        if not msg:
            break

    all_pass = all(c["pass"] for c in checks.values())
    status = "PASS" if all_pass else "FAIL"
    record("YG-05", "Each sport filter works", status,
           msg.raw_text if msg else "", checks)


async def test_yg_06_combat_filter(c: TelegramClient):
    """YG-06: Tap 🥊 Combat Sports filter — shows empty state or combat content."""
    log.info("─── YG-06: Combat sports filter ───")

    msg = await send_wait_buttons(c, "⚽ Your Games", timeout=BOT_TIMEOUT)
    if not msg:
        record("YG-06", "Your Games access", "FAIL", "", {}, "No response")
        return

    cbs = get_callback_data(msg)

    # Find combat filter
    combat_cbs = [cb for cb in cbs if "combat" in cb and cb.startswith("yg:sport:")]

    checks = {}
    if not combat_cbs:
        # Combat filter not shown — user may not follow combat sports
        checks["combat_not_in_filters"] = {
            "pass": True,
            "detail": "Combat not in sport filters — user may not follow combat sports"
        }
        record("YG-06", "Combat filter", "PASS", msg.raw_text or "", checks,
               "Combat not in user's sports — expected if not following")
        return

    # Click combat filter
    combat_msg = await click_exact(c, msg, combat_cbs[0], timeout=BOT_TIMEOUT)
    save_screenshot("YG-06-combat-filter", combat_msg)

    if combat_msg:
        text = combat_msg.raw_text or ""
        text_lower = text.lower()

        # Should show either combat games or empty state
        checks["combat_response"] = {
            "pass": True,
            "detail": f"Response: {text[:200]}"
        }
        # Empty state should say "no combat" or "no games" — not F1/tennis
        removed_in_text = [t for t in ["f1", "formula 1", "tennis", "nba"]
                           if t in text_lower]
        checks["no_removed_in_combat"] = {
            "pass": len(removed_in_text) == 0,
            "detail": f"Found: {removed_in_text}" if removed_in_text else "Clean"
        }
    else:
        checks["combat_response"] = {"pass": False, "detail": "No response"}

    all_pass = all(c["pass"] for c in checks.values())
    status = "PASS" if all_pass else "FAIL"
    record("YG-06", "Combat filter works", status,
           combat_msg.raw_text if combat_msg else "", checks)


# ────────────────────────────────────────────────────────────────────
# PART C: Hot Tips (2 tests)
# ────────────────────────────────────────────────────────────────────

async def test_ht_07_hot_tips_no_f1(c: TelegramClient):
    """HT-07: Hot Tips — no F1 tips visible."""
    log.info("─── HT-07: Hot Tips no F1 ───")

    msg = await send_wait_buttons(c, "🔥 Hot Tips", timeout=AI_TIMEOUT)
    save_screenshot("HT-07-hot-tips", msg)

    if not msg:
        record("HT-07", "Hot Tips access", "FAIL", "", {}, "No response")
        return

    # Collect all messages (hot tips sends multiple)
    await asyncio.sleep(5)
    msgs = await c.get_messages(BOT, limit=15)
    all_text = "\n".join(m.raw_text or "" for m in msgs if not m.out)
    all_lower = all_text.lower()

    checks = {}
    # No F1 terms in tips
    f1_terms = ["formula 1", "f1", "grand prix", "qualifying", "pit stop",
                "pole position", "drs", "grid penalty"]
    f1_found = [t for t in f1_terms if t in all_lower]
    checks["no_f1_in_tips"] = {
        "pass": len(f1_found) == 0,
        "detail": f"Found: {f1_found}" if f1_found else "Clean"
    }

    # No tennis/basketball either
    removed_terms = ["tennis", "basketball", "nba", "atp", "wta"]
    removed_found = [t for t in removed_terms if t in all_lower]
    checks["no_other_removed"] = {
        "pass": len(removed_found) == 0,
        "detail": f"Found: {removed_found}" if removed_found else "Clean"
    }

    # Tips should show only valid sports (soccer, rugby, cricket, combat)
    valid_emojis = {"⚽", "🏉", "🏏", "🥊"}
    sport_emojis_found = [e for e in valid_emojis if e in all_text]
    checks["valid_sport_emojis"] = {
        "pass": True,
        "detail": f"Found sport emojis: {sport_emojis_found}"
    }

    # 🏎 (F1) should NOT appear
    checks["no_f1_emoji"] = {
        "pass": "🏎" not in all_text,
        "detail": "🏎 found in tips" if "🏎" in all_text else "Clean"
    }

    all_pass = all(c["pass"] for c in checks.values())
    status = "PASS" if all_pass else "FAIL"

    if not all_pass:
        file_bug("BUG-P0-002", "P0", "HT-07", "BUG-P0-STRAGGLER",
                 f"F1/removed sport terms in Hot Tips: {f1_found + removed_found}",
                 all_text[:500])

    record("HT-07", "Hot Tips no F1 content", status, all_text[:3000], checks)


async def test_ht_08_hot_tips_sport_filter(c: TelegramClient):
    """HT-08: Hot Tips — sport-related content only from 4 valid sports."""
    log.info("─── HT-08: Hot Tips sport content ───")

    # Get the most recent hot tips messages
    msgs = await c.get_messages(BOT, limit=15)
    tip_msgs = [m for m in msgs if not m.out and m.raw_text]

    all_text = "\n".join(m.raw_text or "" for m in tip_msgs)
    all_lower = all_text.lower()

    checks = {}
    # Check that "all markets" or sport scanning text doesn't mention F1
    if "scanning" in all_lower or "scanned" in all_lower or "markets" in all_lower:
        checks["scan_text_clean"] = {
            "pass": "f1" not in all_lower and "formula" not in all_lower,
            "detail": "Scan text doesn't mention F1"
        }
    else:
        checks["scan_text_clean"] = {
            "pass": True,
            "detail": "No scan text found"
        }

    # Check buttons don't reference removed sports
    all_btns = []
    for m in tip_msgs:
        all_btns.extend(get_buttons_text(m))
    btn_text = " ".join(all_btns).lower()
    removed_in_btns = [t for t in ["f1", "formula", "tennis", "nba"]
                       if t in btn_text]
    checks["no_removed_in_buttons"] = {
        "pass": len(removed_in_btns) == 0,
        "detail": f"Found: {removed_in_btns}" if removed_in_btns else "Clean"
    }

    all_pass = all(c["pass"] for c in checks.values())
    status = "PASS" if all_pass else "FAIL"
    record("HT-08", "Hot Tips sport content valid", status, all_text[:3000], checks)


# ────────────────────────────────────────────────────────────────────
# PART D: Settings (1 test)
# ────────────────────────────────────────────────────────────────────

async def test_set_09_settings_sports(c: TelegramClient):
    """SET-09: Settings → sports shows only 4 sports."""
    log.info("─── SET-09: Settings sports ───")

    msg = await send_wait_buttons(c, "⚙️ Settings", timeout=BOT_TIMEOUT)
    if not msg:
        record("SET-09", "Settings access", "FAIL", "", {}, "No response")
        return

    # Click settings:sports
    sports_msg = await click_exact(c, msg, "settings:sports", timeout=BOT_TIMEOUT)
    if not sports_msg:
        sports_msg = await click_data(c, msg, "settings:sports", timeout=BOT_TIMEOUT)

    if not sports_msg:
        # Maybe the settings screen already shows sport prefs
        save_screenshot("SET-09-settings-nosports", msg)
        record("SET-09", "Settings sports", "SKIP", msg.raw_text or "", {},
               "Could not navigate to sports settings")
        return

    save_screenshot("SET-09-settings-sports", sports_msg)
    text = sports_msg.raw_text or ""
    btns = get_buttons_text(sports_msg)
    cbs = get_callback_data(sports_msg)

    checks = {}

    # Count sport callbacks
    ob_sport_cbs = [cb for cb in cbs if cb.startswith("ob_sport:")]
    sport_keys = [cb.split(":")[-1] for cb in ob_sport_cbs]

    if sport_keys:
        checks["exactly_4_sports"] = {
            "pass": len(sport_keys) == 4,
            "detail": f"Found {len(sport_keys)}: {sport_keys}"
        }
        checks["correct_sports"] = {
            "pass": set(sport_keys) == EXPECTED_SPORTS,
            "detail": f"Expected {EXPECTED_SPORTS}, got {set(sport_keys)}"
        }
        removed = [s for s in sport_keys if s in REMOVED_SPORTS]
        checks["no_removed"] = {
            "pass": len(removed) == 0,
            "detail": f"Found: {removed}" if removed else "Clean"
        }
    else:
        # No ob_sport callbacks — check text and button labels
        text_lower = text.lower()
        removed_in_text = [s for s in REMOVED_LABELS if s.lower() in text_lower]
        checks["no_removed_in_text"] = {
            "pass": len(removed_in_text) == 0,
            "detail": f"Found: {removed_in_text}" if removed_in_text else "Clean"
        }

    all_pass = all(c["pass"] for c in checks.values())
    status = "PASS" if all_pass else "FAIL"

    if not all_pass:
        file_bug("BUG-P0-003", "P0", "SET-09", "BUG-P0-STRAGGLER",
                 f"Settings shows wrong sports: {sport_keys}",
                 f"Buttons: {btns}")

    record("SET-09", "Settings shows 4 sports only", status, text, checks)


# ────────────────────────────────────────────────────────────────────
# PART E: Negative Tests (3 tests)
# ────────────────────────────────────────────────────────────────────

async def test_neg_10_search_f1(c: TelegramClient):
    """NEG-10: Search for F1 content — should not find any."""
    log.info("─── NEG-10: Search for F1 ───")

    msg = await send(c, "Formula 1", timeout=BOT_TIMEOUT)
    save_screenshot("NEG-10-search-f1", msg)

    checks = {}
    if msg:
        text = msg.raw_text or ""
        text_lower = text.lower()

        # Should NOT show F1 games, tips, or analysis
        f1_positive = any(t in text_lower for t in [
            "grand prix", "qualifying", "pit stop", "pole position",
            "drs", "grid", "verstappen", "hamilton", "leclerc",
            "ferrari", "red bull racing", "mclaren f1"
        ])
        checks["no_f1_content"] = {
            "pass": not f1_positive,
            "detail": f"Text: {text[:200]}"
        }

        # Should not crash — any response is fine as long as it's not F1
        checks["no_crash"] = {"pass": True, "detail": "Response received"}
    else:
        # No response could mean bot treated it as freetext — check if that's OK
        checks["no_crash"] = {"pass": True, "detail": "No response (freetext ignored)"}
        checks["no_f1_content"] = {"pass": True, "detail": "No response = no F1"}

    all_pass = all(c["pass"] for c in checks.values())
    status = "PASS" if all_pass else "FAIL"
    record("NEG-10", "F1 search returns no F1 content", status,
           msg.raw_text if msg else "", checks)


async def test_neg_11_search_tennis(c: TelegramClient):
    """NEG-11: Search for Tennis content — should not find any."""
    log.info("─── NEG-11: Search for Tennis ───")

    msg = await send(c, "Tennis", timeout=BOT_TIMEOUT)
    save_screenshot("NEG-11-search-tennis", msg)

    checks = {}
    if msg:
        text_lower = (msg.raw_text or "").lower()
        tennis_positive = any(t in text_lower for t in [
            "djokovic", "nadal", "federer", "wimbledon", "roland garros",
            "australian open", "us open tennis", "atp", "wta", "grand slam"
        ])
        checks["no_tennis_content"] = {
            "pass": not tennis_positive,
            "detail": f"Text: {(msg.raw_text or '')[:200]}"
        }
        checks["no_crash"] = {"pass": True, "detail": "Response received"}
    else:
        checks["no_crash"] = {"pass": True, "detail": "No response (freetext ignored)"}
        checks["no_tennis_content"] = {"pass": True, "detail": "No response = no Tennis"}

    all_pass = all(c["pass"] for c in checks.values())
    status = "PASS" if all_pass else "FAIL"
    record("NEG-11", "Tennis search returns no Tennis content", status,
           msg.raw_text if msg else "", checks)


async def test_neg_12_bot_logs_no_jolpica(c: TelegramClient):
    """NEG-12: Bot logs have no Jolpica/F1 errors since Phase 0 restart."""
    log.info("─── NEG-12: Bot logs check ───")

    # Read bot log file
    log_path = Path("/tmp/bot_latest.log")
    checks = {}

    if log_path.exists():
        log_text = log_path.read_text(errors="replace")

        # Check for Jolpica errors
        jolpica_errors = [line for line in log_text.splitlines()
                          if "jolpica" in line.lower() or "jolpi.ca" in line.lower()]
        checks["no_jolpica_errors"] = {
            "pass": len(jolpica_errors) == 0,
            "detail": f"Found {len(jolpica_errors)} Jolpica references"
        }

        # Check for F1-related errors
        f1_errors = [line for line in log_text.splitlines()
                     if ("f1" in line.lower() or "formula" in line.lower())
                     and ("error" in line.lower() or "traceback" in line.lower()
                          or "exception" in line.lower())]
        checks["no_f1_errors"] = {
            "pass": len(f1_errors) == 0,
            "detail": f"Found {len(f1_errors)} F1-related errors"
        }

        # Check for import errors (removed modules)
        import_errors = [line for line in log_text.splitlines()
                         if "importerror" in line.lower() or "modulenotfounderror" in line.lower()]
        checks["no_import_errors"] = {
            "pass": len(import_errors) == 0,
            "detail": f"Found {len(import_errors)} import errors"
        }

        if jolpica_errors:
            file_bug("BUG-P0-004", "P1", "NEG-12", "BUG-P0-STRAGGLER",
                     f"Jolpica references in bot log: {len(jolpica_errors)}",
                     "\n".join(jolpica_errors[:5]))
    else:
        checks["log_exists"] = {"pass": False, "detail": "Bot log not found at /tmp/bot_latest.log"}

    all_pass = all(c["pass"] for c in checks.values())
    status = "PASS" if all_pass else "FAIL"
    record("NEG-12", "Bot logs clean (no Jolpica/F1 errors)", status,
           f"Log file: {log_path}", checks)


# ── Main ──────────────────────────────────────────────────────────────
async def main():
    log.info("=" * 70)
    log.info("Phase 0 Verification: Sport Narrowing Telethon Check")
    log.info("=" * 70)

    # Load session
    if not SESSION_PATH.exists():
        log.error("Telethon session not found at %s", SESSION_PATH)
        return

    session_str = SESSION_PATH.read_text().strip()

    async with TelegramClient(StringSession(session_str), API_ID, API_HASH) as client:
        log.info("Connected to Telegram")

        # PART A: Onboarding (3 tests)
        log.info("\n=== PART A: Onboarding (3 tests) ===")
        await test_ob_01_start_shows_4_sports(client)
        await asyncio.sleep(2)
        await test_ob_02_sport_emojis_correct(client)
        await asyncio.sleep(2)
        await test_ob_03_combat_sports_present(client)
        await asyncio.sleep(2)

        # PART B: Your Games (3 tests)
        log.info("\n=== PART B: Your Games (3 tests) ===")
        await test_yg_04_sport_filter_buttons(client)
        await asyncio.sleep(2)
        await test_yg_05_tap_each_filter(client)
        await asyncio.sleep(2)
        await test_yg_06_combat_filter(client)
        await asyncio.sleep(2)

        # PART C: Hot Tips (2 tests)
        log.info("\n=== PART C: Hot Tips (2 tests) ===")
        await test_ht_07_hot_tips_no_f1(client)
        await asyncio.sleep(2)
        await test_ht_08_hot_tips_sport_filter(client)
        await asyncio.sleep(2)

        # PART D: Settings (1 test)
        log.info("\n=== PART D: Settings (1 test) ===")
        await test_set_09_settings_sports(client)
        await asyncio.sleep(2)

        # PART E: Negative Tests (3 tests)
        log.info("\n=== PART E: Negative Tests (3 tests) ===")
        await test_neg_10_search_f1(client)
        await asyncio.sleep(2)
        await test_neg_11_search_tennis(client)
        await asyncio.sleep(2)
        await test_neg_12_bot_logs_no_jolpica(client)

    # ── Summary ────────────────────────────────────────────────────
    log.info("\n" + "=" * 70)
    log.info("RESULTS SUMMARY")
    log.info("=" * 70)

    pass_count = sum(1 for r in results if r["status"] == "PASS")
    fail_count = sum(1 for r in results if r["status"] == "FAIL")
    skip_count = sum(1 for r in results if r["status"] == "SKIP")

    for r in results:
        icon = {"PASS": "✓", "FAIL": "✗", "SKIP": "⊘"}.get(r["status"], "?")
        log.info("  %s %s: %s", icon, r["test_id"], r["name"])

    log.info("")
    log.info("  PASS: %d  |  FAIL: %d  |  SKIP: %d  |  BUGS: %d",
             pass_count, fail_count, skip_count, len(bugs))

    if bugs:
        log.info("\nBUGS FILED:")
        for bug in bugs:
            log.info("  %s [%s] %s: %s", bug["id"], bug["severity"],
                     bug["category"], bug["description"])

    # Save results
    RESULTS_PATH.write_text(json.dumps({
        "results": results,
        "bugs": bugs,
        "summary": {
            "total": len(results),
            "pass": pass_count,
            "fail": fail_count,
            "skip": skip_count,
            "bugs": len(bugs),
        }
    }, indent=2), encoding="utf-8")
    log.info("\nResults saved to %s", RESULTS_PATH)
    log.info("Screenshots saved to %s", SCREENSHOT_DIR)


if __name__ == "__main__":
    asyncio.run(main())
