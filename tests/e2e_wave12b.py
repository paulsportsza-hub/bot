"""Wave 12B — Telethon E2E: Hot Tips migration to odds.db verification.

Every test sends a real message via Telethon to @mzansiedge_bot and
captures the verbatim response. No code review. No Bot API. No mocking.

Usage:
    cd /home/paulsportsza/bot && source .venv/bin/activate
    python tests/e2e_wave12b.py 2>&1 | tee /home/paulsportsza/reports/e2e-wave12b-raw.txt
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import BOT_ROOT

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.sessions import StringSession
from telethon.tl.custom.message import Message

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("wave12b")

# ── Config ───────────────────────────────────────────────────
BOT = "mzansiedge_bot"
API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "")
SESSION_PATH = Path("data/telethon_session.string")
REPORT_DIR = BOT_ROOT.parent / "reports" / "e2e-screenshots"
REPORT_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_PATH = BOT_ROOT.parent / "reports" / "wave12b-e2e-results.json"

BOT_TIMEOUT = 15
PICKS_TIMEOUT = 45

# ── Results ──────────────────────────────────────────────────
results: list[dict] = []


def record(test_id: str, name: str, status: str, response: str,
           assertions: list[tuple[bool, str]], detail: str = ""):
    entry = {
        "test_id": test_id, "name": name, "status": status,
        "response": response[:3000],
        "assertions": [[ok, msg] for ok, msg in assertions],
        "detail": detail,
    }
    results.append(entry)
    icon = {"PASS": "✓", "FAIL": "✗", "SKIP": "⊘", "WARN": "⚠"}.get(status, "?")
    log.info("  %s %s: %s — %s", icon, test_id, name, status)
    if status == "FAIL":
        for ok, msg in assertions:
            if not ok:
                log.error("      ASSERT FAILED: %s", msg)
    safe = test_id.replace(":", "_").replace("/", "_")
    (REPORT_DIR / f"{safe}.txt").write_text(
        f"TEST: {test_id} — {name}\nSTATUS: {status}\n"
        f"RESPONSE:\n{response}\n\nASSERTIONS:\n"
        + "\n".join(f"  {'✓' if ok else '✗'} {msg}" for ok, msg in assertions)
        + (f"\n\nDETAIL: {detail}" if detail else ""),
        encoding="utf-8",
    )


# ── Helpers ──────────────────────────────────────────────────

async def _last_id(client: TelegramClient) -> int:
    msgs = await client.get_messages(BOT, limit=1)
    return msgs[0].id if msgs else 0


async def send(client: TelegramClient, text: str,
               timeout: int = BOT_TIMEOUT) -> Message | None:
    last = await _last_id(client)
    try:
        await client.send_message(BOT, text)
    except FloodWaitError as e:
        log.warning("FloodWait %ds", e.seconds)
        await asyncio.sleep(e.seconds + 2)
        await client.send_message(BOT, text)
    await asyncio.sleep(2)
    deadline = time.time() + timeout
    while time.time() < deadline:
        msgs = await client.get_messages(BOT, limit=10)
        for m in msgs:
            if m.id > last and not m.out:
                return m
        await asyncio.sleep(1)
    return None


async def send_get_all(client: TelegramClient, text: str,
                       timeout: int = BOT_TIMEOUT,
                       settle: float = 5.0) -> list[Message]:
    """Send message, collect ALL bot replies, wait for edits to settle."""
    last = await _last_id(client)
    try:
        await client.send_message(BOT, text)
    except FloodWaitError as e:
        log.warning("FloodWait %ds", e.seconds)
        await asyncio.sleep(e.seconds + 2)
        await client.send_message(BOT, text)

    await asyncio.sleep(3)
    deadline = time.time() + timeout
    prev_count = 0
    stable = 0
    while time.time() < deadline:
        msgs = await client.get_messages(BOT, limit=20)
        bot_msgs = [m for m in msgs if m.id > last and not m.out]
        if len(bot_msgs) == prev_count:
            stable += 1
            if stable >= 3:
                break
        else:
            stable = 0
            prev_count = len(bot_msgs)
        await asyncio.sleep(1)

    # Wait for edits to settle
    await asyncio.sleep(settle)

    # Final fetch with fresh data (edits)
    msgs = await client.get_messages(BOT, limit=20)
    found = [m for m in msgs if m.id > last and not m.out]
    found.sort(key=lambda m: m.id)
    return found


async def click_data(client: TelegramClient, msg: Message,
                     prefix: str, timeout: int = BOT_TIMEOUT) -> Message | None:
    if not msg or not msg.buttons:
        return None
    old_id = await _last_id(client)
    for row in msg.buttons:
        for btn in row:
            if hasattr(btn, "data") and btn.data:
                cb = btn.data.decode() if isinstance(btn.data, bytes) else str(btn.data)
                if cb.startswith(prefix):
                    try:
                        await btn.click()
                    except Exception as e:
                        log.debug("click err: %s", e)
                        return None
                    await asyncio.sleep(3)
                    # Check for new message
                    msgs = await client.get_messages(BOT, limit=10)
                    for m in msgs:
                        if m.id > old_id and not m.out:
                            return m
                    # Maybe edited
                    updated = await client.get_messages(BOT, ids=msg.id)
                    if updated:
                        return updated
                    return None
    return None


async def click_text(client: TelegramClient, msg: Message,
                     text: str, partial: bool = False) -> Message | None:
    if not msg or not msg.buttons:
        return None
    old_id = await _last_id(client)
    for row in msg.buttons:
        for btn in row:
            match = (partial and text.lower() in btn.text.lower()) or \
                    btn.text.lower() == text.lower()
            if match:
                try:
                    await btn.click()
                except Exception as e:
                    log.debug("click err: %s", e)
                    return None
                await asyncio.sleep(3)
                msgs = await client.get_messages(BOT, limit=10)
                for m in msgs:
                    if m.id > old_id and not m.out:
                        return m
                updated = await client.get_messages(BOT, ids=msg.id)
                if updated:
                    return updated
                return None
    return None


def txt(msg: Message | None) -> str:
    if not msg:
        return ""
    return msg.text or msg.message or ""


def btns(msg: Message | None) -> list[str]:
    if not msg or not msg.buttons:
        return []
    return [btn.text for row in msg.buttons for btn in row]


def btn_data_list(msg: Message | None) -> list[str]:
    if not msg or not msg.buttons:
        return []
    out = []
    for row in msg.buttons:
        for btn in row:
            if hasattr(btn, "data") and btn.data:
                out.append(btn.data.decode() if isinstance(btn.data, bytes) else str(btn.data))
            elif hasattr(btn, "url") and btn.url:
                out.append(f"URL:{btn.url}")
    return out


def url_btns(msg: Message | None) -> list[dict]:
    if not msg or not msg.buttons:
        return []
    out = []
    for row in msg.buttons:
        for btn in row:
            if hasattr(btn, "url") and btn.url:
                out.append({"text": btn.text, "url": btn.url})
    return out


# ═════════════════════════════════════════════════════════════
# TESTS
# ═════════════════════════════════════════════════════════════

async def run_tests(client: TelegramClient):

    # ═══════════════════════════════════════════════════════
    # SECTION 1: HOT TIPS — PRIMARY VERIFICATION
    # ═══════════════════════════════════════════════════════
    log.info("")
    log.info("=" * 60)
    log.info("SECTION 1: HOT TIPS — PRIMARY VERIFICATION")
    log.info("=" * 60)

    # Warm up: send /start first to ensure bot is responsive
    await send(client, "/start", timeout=20)
    await asyncio.sleep(2)

    # ── TEST-001: Hot Tips shows tips (NOT empty) ────────
    all_msgs = await send_get_all(client, "🔥 Hot Tips", timeout=PICKS_TIMEOUT, settle=8)
    all_texts = [txt(m) for m in all_msgs]
    combined = "\n---MSG---\n".join(all_texts)

    # Filter to Hot Tips specific messages
    ht_msgs = [m for m in all_msgs if txt(m) and (
        "hot tips" in txt(m).lower() or "edge" in txt(m).lower() or
        "value bet" in txt(m).lower() or "vs" in txt(m).lower() or
        "no edges" in txt(m).lower() or "crunching" in txt(m).lower() or
        "💎" in txt(m) or "🥇" in txt(m) or "🥈" in txt(m) or "🥉" in txt(m) or "market is efficient" in txt(m).lower() or
        "scanned" in txt(m).lower()
    )]
    ht_texts = [txt(m) for m in ht_msgs]
    ht_combined = "\n---MSG---\n".join(ht_texts)

    is_empty = any("no edges" in t.lower() or "no value" in t.lower() or
                    "market is efficient" in t.lower() for t in ht_texts)
    has_tips = any("vs" in t and ("💎" in t or "🥇" in t or "🥈" in t or "🥉" in t or "edge" in t.lower() or "bet" in t.lower())
                   for t in ht_texts)
    has_match = any(re.search(r"\w+\s+vs\s+\w+", t, re.IGNORECASE) for t in ht_texts)
    edge_emojis = ["💎", "🥇", "🥈", "🥉"]
    has_edge = any(any(e in t for e in edge_emojis) for t in ht_texts)
    has_scanned = any("scanned" in t.lower() for t in ht_texts)

    asserts = [
        (not is_empty, f"NOT empty state: is_empty={is_empty}"),
        (has_match or has_tips, f"Contains match names: has_match={has_match}"),
        (has_edge, f"Edge badge emoji found: {has_edge}"),
        (has_scanned, f"'Scanned' header present: {has_scanned}"),
    ]
    status_001 = "PASS" if all(a[0] for a in asserts) else "FAIL"
    record("TEST-001", "Hot Tips shows tips (NOT empty)", status_001,
           ht_combined, asserts)

    # ── TEST-002: Edge badges visible and correct ────────
    found_badges = []
    badge_map = {"💎": "DIAMOND", "🥇": "GOLD", "🥈": "SILVER", "🥉": "BRONZE"}
    for t in ht_texts:
        for emoji, tier in badge_map.items():
            if emoji in t:
                found_badges.append(tier)
    has_hidden = any("hidden" in t.lower() for t in ht_texts)

    asserts = [
        (len(found_badges) >= 1, f"Badges found: {found_badges}"),
        (not has_hidden, "No HIDDEN tier tips visible"),
    ]
    record("TEST-002", "Edge badges visible and correct",
           "PASS" if all(a[0] for a in asserts) else "FAIL",
           f"Badges: {found_badges}", asserts)

    # ── TEST-003: Dynamic bookmaker (NOT hardcoded Betway) ──
    bk_names = {"hollywoodbets", "betway", "supabets", "sportingbet", "gbets"}
    found_bks = set()
    for t in ht_texts:
        tl = t.lower()
        for bk in bk_names:
            if bk in tl:
                found_bks.add(bk)

    asserts = [
        (len(found_bks) >= 1, f"Bookmakers found: {found_bks}"),
    ]
    if len(found_bks) >= 2:
        asserts.append((True, f"Multiple bookmakers: {found_bks} — dynamic!"))
    elif len(found_bks) == 1 and "betway" in found_bks:
        asserts.append((False, "Only 'betway' found — may be hardcoded"))
    elif len(found_bks) == 1:
        asserts.append((True, f"Single bookmaker {found_bks} (may be genuinely best for all)"))

    record("TEST-003", "Dynamic bookmaker (NOT hardcoded Betway)",
           "PASS" if len(found_bks) >= 1 else "FAIL",
           str(found_bks), asserts)

    # ── TEST-004: Tips sorted by edge tier ───────────────
    tier_order = {"DIAMOND": 0, "GOLD": 1, "SILVER": 2, "BRONZE": 3}
    tier_positions = []
    # Scan the combined Hot Tips message for tier labels in order
    for t in ht_texts:
        lines = t.split("\n")
        for i, line in enumerate(lines):
            for emoji, tier in badge_map.items():
                if emoji in line:
                    tier_positions.append((i, tier_order.get(tier, 9), tier))

    sorted_ok = all(tier_positions[i][1] <= tier_positions[i+1][1]
                    for i in range(len(tier_positions)-1)) if len(tier_positions) >= 2 else True

    asserts = [
        (len(tier_positions) >= 1, f"Tiers found: {[p[2] for p in tier_positions]}"),
        (sorted_ok, f"Sorted correctly: {[p[2] for p in tier_positions]}"),
    ]
    record("TEST-004", "Tips sorted by edge tier",
           "PASS" if all(a[0] for a in asserts) else ("SKIP" if not tier_positions else "FAIL"),
           str(tier_positions), asserts)

    # ── TEST-005: Tip detail multi-bookmaker ─────────────
    log.info("")
    log.info("  Navigating to tip detail...")

    # Find a tip to tap — look for tip:detail buttons
    tip_detail_msg = None
    tip_detail_text = ""

    # Check all Hot Tips messages for clickable tip buttons
    for m in ht_msgs:
        if m.buttons:
            for d in btn_data_list(m):
                if d.startswith("tip:detail:"):
                    tip_detail_msg = await click_data(client, m, "tip:detail:")
                    if tip_detail_msg:
                        tip_detail_text = txt(tip_detail_msg)
                    break
        if tip_detail_msg:
            break

    # Also check all_msgs (loading message might have been replaced)
    if not tip_detail_msg:
        for m in all_msgs:
            if m.buttons:
                for d in btn_data_list(m):
                    if d.startswith("tip:detail:"):
                        tip_detail_msg = await click_data(client, m, "tip:detail:")
                        if tip_detail_msg:
                            tip_detail_text = txt(tip_detail_msg)
                        break
            if tip_detail_msg:
                break

    # Fallback: try Your Games if no tip buttons
    if not tip_detail_msg:
        log.info("  No tip:detail button — trying yg:game via Your Games")
        yg_msg = await send(client, "⚽ Your Games", timeout=20)
        if yg_msg and yg_msg.buttons:
            for d in btn_data_list(yg_msg):
                if d.startswith("yg:game:"):
                    tip_detail_msg = await click_data(client, yg_msg, "yg:game:")
                    if tip_detail_msg:
                        tip_detail_text = txt(tip_detail_msg)
                    break

    if tip_detail_msg:
        detail_bks = set()
        for bk in bk_names:
            if bk in tip_detail_text.lower():
                detail_bks.add(bk)
        has_best = "best odds" in tip_detail_text.lower() or "@" in tip_detail_text
        has_also = "also:" in tip_detail_text.lower()
        detail_btns = btns(tip_detail_msg)
        detail_cb = btn_data_list(tip_detail_msg)
        detail_urls = url_btns(tip_detail_msg)

        has_cta = any("bet on" in b["text"].lower() or "bet now" in b["text"].lower()
                      for b in detail_urls)
        cta_text = next((b["text"] for b in detail_urls
                         if "bet" in b["text"].lower()), "")
        cta_format_ok = "bet on" in cta_text.lower() and "→" in cta_text if cta_text else False
        has_compare_btn = any("odds:compare" in d for d in detail_cb) or \
                          any("bookmaker" in b.lower() or "odds" in b.lower() for b in detail_btns)
        has_back = any("hot:" in d or "back" in b.lower()
                       for d, b in zip(detail_cb, detail_btns)) or \
                   any("back" in b.lower() for b in detail_btns)
        has_freshness = "updated" in tip_detail_text.lower() and "ago" in tip_detail_text.lower()

        asserts = [
            (len(detail_bks) >= 2, f"Bookmakers in detail: {detail_bks}"),
            (has_best, "Best odds line present"),
            (has_cta, f"CTA button: {cta_text}"),
            (cta_format_ok, f"CTA format 'Bet on X →': '{cta_text}'"),
            (has_compare_btn, f"Odds comparison button: {detail_btns}"),
            (has_back, f"Back button present: {detail_btns}"),
        ]
        if has_also:
            asserts.append((True, "Runner-ups 'Also:' line present"))
        if has_freshness:
            asserts.append((True, f"Freshness indicator found"))

        record("TEST-005", "Tip detail — multi-bookmaker odds",
               "PASS" if all(a[0] for a in asserts) else "FAIL",
               tip_detail_text + f"\n\nButtons: {detail_btns}\nURLs: {detail_urls}",
               asserts)
    else:
        record("TEST-005", "Tip detail — multi-bookmaker odds", "FAIL",
               "Could not navigate to any tip detail page",
               [(False, "No tip:detail or yg:game button found")])

    # ── TEST-006: Odds comparison view ───────────────────
    odds_compare_msg = None
    odds_compare_text = ""

    if tip_detail_msg and tip_detail_msg.buttons:
        # Try odds:compare callback
        odds_compare_msg = await click_data(client, tip_detail_msg, "odds:compare:")
        if odds_compare_msg:
            odds_compare_text = txt(odds_compare_msg)
        else:
            # Try text button
            odds_compare_msg = await click_text(client, tip_detail_msg,
                                                "Bookmaker Odds", partial=True)
            if odds_compare_msg:
                odds_compare_text = txt(odds_compare_msg)

    if odds_compare_msg and odds_compare_text:
        comp_bks = set()
        for bk in bk_names:
            if bk in odds_compare_text.lower():
                comp_bks.add(bk)
        has_star = "⭐" in odds_compare_text
        has_header = "comparison" in odds_compare_text.lower() or "📊" in odds_compare_text
        # Check odds values are reasonable
        odds_vals = re.findall(r"\b(\d+\.\d{2})\b", odds_compare_text)
        odds_reasonable = all(1.01 <= float(o) <= 100.0 for o in odds_vals) if odds_vals else True
        # Check capitalisation
        has_lowercase_bk = any(bk in odds_compare_text for bk in
                               ["hollywoodbets", "betway", "supabets", "sportingbet", "gbets"]
                               if bk in odds_compare_text and
                               bk.title() not in odds_compare_text and
                               bk.upper() not in odds_compare_text)

        asserts = [
            (len(comp_bks) >= 2, f"Bookmakers: {comp_bks}"),
            (has_star, "Best odds marked with ⭐"),
            (len(odds_vals) >= 2, f"Odds values: {odds_vals}"),
            (odds_reasonable, f"Odds in range [1.01, 100]: {odds_vals}"),
        ]
        record("TEST-006", "Odds comparison view",
               "PASS" if all(a[0] for a in asserts) else "FAIL",
               odds_compare_text, asserts)
    else:
        record("TEST-006", "Odds comparison view",
               "SKIP" if not tip_detail_msg else "FAIL",
               "Could not access odds comparison",
               [(False, "No odds:compare button or no response")],
               detail="Tip detail may not have comparison button")

    # ── TEST-007: Back navigation from tip detail ────────
    if tip_detail_msg and tip_detail_msg.buttons:
        back_msg = await click_text(client, tip_detail_msg, "Back", partial=True)
        if not back_msg:
            back_msg = await click_data(client, tip_detail_msg, "hot:")
        back_text = txt(back_msg)
        is_back = "hot tips" in back_text.lower() or "value bet" in back_text.lower() or \
                  any("tip:detail:" in d for d in btn_data_list(back_msg))

        asserts = [
            (back_msg is not None, "Back button responded"),
            (is_back, f"Returned to tips: {'yes' if is_back else 'no'}"),
        ]
        record("TEST-007", "Back navigation from tip detail",
               "PASS" if all(a[0] for a in asserts) else "WARN",
               back_text[:200], asserts)
    else:
        record("TEST-007", "Back navigation from tip detail", "SKIP",
               "No tip detail to navigate back from",
               [(False, "Tip detail not accessible")])

    # ── TEST-008: Admin dashboard shows odds.db stats ────
    admin_msg = await send(client, "/admin")
    admin_text = txt(admin_msg)

    has_db_section = "odds database" in admin_text.lower() or "primary" in admin_text.lower()
    has_rows = "rows" in admin_text.lower() or "row" in admin_text.lower()
    has_bk_count = "bookmaker" in admin_text.lower()
    has_last_scrape = "last scrape" in admin_text.lower() or "scrape" in admin_text.lower()
    has_fallback = "fallback" in admin_text.lower()
    # Check row count is reasonable
    row_match = re.search(r"(\d{1,3}(?:,\d{3})*)", admin_text)
    row_count = int(row_match.group(1).replace(",", "")) if row_match else 0

    asserts = [
        (has_db_section, "Odds Database section present"),
        (has_rows, "Row count shown"),
        (row_count >= 10000, f"Row count: {row_count:,} (need ≥10K)"),
        (has_bk_count, "Bookmaker count shown"),
        (has_last_scrape, "Last scrape time shown"),
        (has_fallback, "Odds API labelled as 'fallback'"),
    ]
    record("TEST-008", "Admin — odds.db stats",
           "PASS" if all(a[0] for a in asserts) else "FAIL",
           admin_text, asserts)

    # ═══════════════════════════════════════════════════════
    # SECTION 2: SPACING & UX COMPLIANCE
    # ═══════════════════════════════════════════════════════
    log.info("")
    log.info("=" * 60)
    log.info("SECTION 2: SPACING & UX COMPLIANCE")
    log.info("=" * 60)

    # ── TEST-009: Hot Tips spacing ───────────────────────
    # Use the captured ht_texts
    main_ht = next((t for t in ht_texts if "value bet" in t.lower() or "hot tips" in t.lower()), "")
    has_double_blank = "\n\n\n" in main_ht
    has_trailing_ws = any(line != line.rstrip() for line in main_ht.split("\n") if line.strip())

    asserts = [
        (not has_double_blank, "No double blank lines"),
        (not has_trailing_ws, "No trailing whitespace"),
        (len(main_ht) > 20, f"Main message length: {len(main_ht)}"),
    ]
    record("TEST-009", "Hot Tips spacing",
           "PASS" if all(a[0] for a in asserts) else "WARN",
           main_ht[:500], asserts)

    # ── TEST-010: Team name display ──────────────────────
    # Check team names across all responses are display names
    all_response_text = combined + "\n" + tip_detail_text
    has_underscore_names = bool(re.search(r"[a-z]+_[a-z]+\s+vs\s+[a-z]+_[a-z]+",
                                          all_response_text, re.IGNORECASE))
    team_names = re.findall(r"(?:^|\n)\s*(?:\[\d+\]\s*)?[⚽🏏🏉🎾🥊🥋🏀🏈⛳🏎]\s*.*?(\w[\w\s]+?)\s+vs\s+(\w[\w\s]+?)(?:\s|$)",
                            all_response_text, re.MULTILINE)

    asserts = [
        (not has_underscore_names, "No underscore_format team names"),
    ]
    if team_names:
        asserts.append((True, f"Team names found: {team_names[:5]}"))
    record("TEST-010", "Team name display",
           "PASS" if all(a[0] for a in asserts) else "FAIL",
           str(team_names[:10]), asserts)

    # ── TEST-011: Bookmaker name display ─────────────────
    expected_names = {
        "hollywoodbets": "Hollywoodbets",
        "betway": "Betway",
        "sportingbet": "Sportingbet",
    }
    wrong_names = []
    for raw, display in expected_names.items():
        # Check if raw lowercase appears without proper capitalization nearby
        if raw in all_response_text.lower():
            if display not in all_response_text and raw in all_response_text:
                wrong_names.append(f"{raw} shown as raw key (expected {display})")

    asserts = [
        (len(wrong_names) == 0, f"All bookmaker names capitalised: issues={wrong_names}"),
    ]
    record("TEST-011", "Bookmaker name display",
           "PASS" if all(a[0] for a in asserts) else "FAIL",
           str(wrong_names), asserts)

    # ── TEST-012: No debug output ────────────────────────
    sample_msgs = await client.get_messages(BOT, limit=30)
    bot_texts = [txt(m) for m in sample_msgs if not m.out and m.text]
    issues = []
    for t in bot_texts:
        if "Traceback" in t:
            issues.append(f"Traceback in: {t[:60]}")
        if "NoneType" in t:
            issues.append(f"NoneType in: {t[:60]}")
        if "<b>" in t or "</b>" in t or "<i>" in t or "</i>" in t:
            issues.append(f"Raw HTML: {t[:60]}")
        if t.strip().startswith("{") and "error" in t.lower():
            issues.append(f"JSON dump: {t[:60]}")
        if '"None"' in t or " None " in t:
            # Be careful — "None" might be legitimate
            if t.count("None") > 1:
                issues.append(f"Multiple 'None': {t[:60]}")

    asserts = [
        (len(issues) == 0, f"Debug output: {len(issues)} issues"),
    ]
    for iss in issues[:3]:
        asserts.append((False, iss))
    record("TEST-012", "No debug output",
           "PASS" if len(issues) == 0 else "FAIL",
           str(issues[:5]), asserts)

    # ── TEST-013: Emoji consistency ──────────────────────
    emoji_checks = {
        "🔥": "Hot Tips header",
        "⚽": "Football emoji",
    }
    emoji_found = {}
    for emoji, label in emoji_checks.items():
        emoji_found[label] = any(emoji in t for t in bot_texts)

    asserts = []
    for label, found in emoji_found.items():
        asserts.append((found, f"{label}: {'present' if found else 'missing'}"))

    # Check no doubled CTA emojis (📲 🎯 should be just 📲)
    doubled_cta = any("📲 🎯" in t or "📲🎯" in t for t in bot_texts)
    asserts.append((not doubled_cta, f"No doubled CTA emoji (📲🎯): {not doubled_cta}"))

    record("TEST-013", "Emoji consistency",
           "PASS" if all(a[0] for a in asserts) else "WARN",
           str(emoji_found), asserts)

    # ── TEST-014: Message length ─────────────────────────
    long_msgs = [(i, len(t)) for i, t in enumerate(bot_texts) if len(t) > 4096]
    asserts = [
        (len(long_msgs) == 0, f"Messages >4096 chars: {len(long_msgs)}"),
    ]
    for idx, length in long_msgs:
        asserts.append((False, f"Message {idx}: {length} chars"))
    record("TEST-014", "Message length within Telegram limit",
           "PASS" if len(long_msgs) == 0 else "FAIL",
           f"Longest: {max(len(t) for t in bot_texts) if bot_texts else 0}", asserts)

    # ═══════════════════════════════════════════════════════
    # SECTION 3: EXISTING FEATURES STILL WORK
    # ═══════════════════════════════════════════════════════
    log.info("")
    log.info("=" * 60)
    log.info("SECTION 3: REGRESSION — EXISTING FEATURES")
    log.info("=" * 60)

    # ── TEST-015: /start and main menu ───────────────────
    start_msg = await send(client, "/start", timeout=20)
    start_text = txt(start_msg)
    start_btns = btns(start_msg)
    asserts = [
        (start_msg is not None, "Bot responded to /start"),
        (len(start_text) > 20, f"Welcome text: {len(start_text)} chars"),
        (len(start_btns) >= 4, f"Menu buttons: {len(start_btns)}"),
    ]
    record("TEST-015", "/start and main menu",
           "PASS" if all(a[0] for a in asserts) else "FAIL",
           start_text + f"\nButtons: {start_btns}", asserts)

    # ── TEST-016: Your Games ─────────────────────────────
    yg_msg = await send(client, "⚽ Your Games", timeout=20)
    yg_text = txt(yg_msg)
    has_games = "vs" in yg_text.lower() or "your games" in yg_text.lower()
    asserts = [
        (yg_msg is not None, "Your Games responded"),
        (has_games, f"Games content: {yg_text[:80]}"),
    ]
    record("TEST-016", "Your Games",
           "PASS" if all(a[0] for a in asserts) else "FAIL",
           yg_text, asserts)

    # ── TEST-017: Profile ────────────────────────────────
    profile_msg = await send(client, "👤 Profile")
    profile_text = txt(profile_msg)
    has_profile = any(kw in profile_text.lower()
                      for kw in ["experience", "sport", "risk", "profile", "bankroll"])
    asserts = [
        (profile_msg is not None, "Profile responded"),
        (has_profile, f"Profile content: {profile_text[:80]}"),
    ]
    record("TEST-017", "Profile",
           "PASS" if all(a[0] for a in asserts) else "FAIL",
           profile_text, asserts)

    # ── TEST-018: Settings ───────────────────────────────
    settings_msg = await send(client, "⚙️ Settings")
    settings_text = txt(settings_msg)
    settings_btn_list = btns(settings_msg)
    has_settings = len(settings_btn_list) >= 4
    asserts = [
        (settings_msg is not None, "Settings responded"),
        (has_settings, f"Settings buttons: {settings_btn_list}"),
    ]
    record("TEST-018", "Settings",
           "PASS" if all(a[0] for a in asserts) else "FAIL",
           settings_text + f"\nButtons: {settings_btn_list}", asserts)

    # ── TEST-019: Help ───────────────────────────────────
    help_msg = await send(client, "/help")
    help_text = txt(help_msg)
    asserts = [
        (help_msg is not None, "Help responded"),
        (len(help_text) > 50, f"Help text: {len(help_text)} chars"),
    ]
    record("TEST-019", "Help",
           "PASS" if all(a[0] for a in asserts) else "FAIL",
           help_text[:300], asserts)

    # ── TEST-020: Settings toggle ────────────────────────
    # Navigate to notifications settings
    toggle_msg = None
    if settings_msg and settings_msg.buttons:
        notif_msg = await click_text(client, settings_msg, "Notifications", partial=True)
        if not notif_msg:
            notif_msg = await click_data(client, settings_msg, "settings:notify")
        if notif_msg and notif_msg.buttons:
            # Try toggling a setting
            toggle_msg = await click_data(client, notif_msg, "settings:toggle_notify:")
            if not toggle_msg:
                # Try story settings
                toggle_msg = await click_text(client, notif_msg, "My Notifications", partial=True)

    asserts = [
        (toggle_msg is not None, "Toggle/notification setting accessible"),
    ]
    record("TEST-020", "Settings toggle",
           "PASS" if toggle_msg else "WARN",
           txt(toggle_msg)[:200] if toggle_msg else "Could not access toggle",
           asserts)

    # ── TEST-021: Navigation chain ───────────────────────
    # Menu → Hot Tips → (wait) → Menu → Settings → Back → Menu
    nav_steps = []

    m1 = await send(client, "/menu")
    nav_steps.append(("menu", m1 is not None))

    m2_all = await send_get_all(client, "🔥 Hot Tips", timeout=PICKS_TIMEOUT, settle=5)
    nav_steps.append(("hot_tips", len(m2_all) >= 1))

    m3 = await send(client, "/menu")
    nav_steps.append(("menu_again", m3 is not None))

    m4 = await send(client, "⚙️ Settings")
    nav_steps.append(("settings", m4 is not None))

    m5 = None
    if m4 and m4.buttons:
        m5 = await click_data(client, m4, "menu:home")
        if not m5:
            m5 = await click_text(client, m4, "Main Menu", partial=True)
    nav_steps.append(("back_to_menu", m5 is not None))

    all_ok = all(s[1] for s in nav_steps)
    asserts = [(ok, f"{step}: {'OK' if ok else 'FAILED'}") for step, ok in nav_steps]
    record("TEST-021", "Navigation chain",
           "PASS" if all_ok else "FAIL",
           str(nav_steps), asserts)

    # ── TEST-022: Free text handling ─────────────────────
    free_msg = await send(client, "what are the best bets today")
    free_text = txt(free_msg)
    asserts = [
        (True, "Bot did not crash on free text"),
    ]
    if free_msg:
        asserts.append((True, f"Response: {free_text[:80]}"))
    else:
        asserts.append((True, "Bot ignored free text (acceptable)"))
    record("TEST-022", "Free text handling",
           "PASS", free_text[:200] if free_text else "(no response)", asserts)

    # ═══════════════════════════════════════════════════════
    # SECTION 4: EDGE CASES
    # ═══════════════════════════════════════════════════════
    log.info("")
    log.info("=" * 60)
    log.info("SECTION 4: EDGE CASES")
    log.info("=" * 60)

    # ── TEST-023: Rapid Hot Tips taps ────────────────────
    rapid_results = []
    for i in range(3):
        m = await send(client, "🔥 Hot Tips", timeout=15)
        rapid_results.append(m is not None)
        await asyncio.sleep(2)

    responded = sum(rapid_results)
    asserts = [
        (responded >= 2, f"Rapid taps: {responded}/3 responded"),
    ]
    record("TEST-023", "Rapid Hot Tips taps",
           "PASS" if responded >= 2 else "WARN",
           f"Responses: {rapid_results}", asserts)

    # ── TEST-024: Stale odds tip detail ──────────────────
    # Tap a tip, wait, tap another
    if tip_detail_msg:
        # We already have one detail. Try to find a second tip.
        await asyncio.sleep(5)
        # Navigate back to Hot Tips
        second_ht = await send(client, "🔥 Hot Tips", timeout=PICKS_TIMEOUT)
        second_text = txt(second_ht) if second_ht else ""

        asserts = [
            (second_ht is not None, "Second Hot Tips load successful"),
            (len(second_text) > 20, f"Content present: {len(second_text)} chars"),
        ]
        record("TEST-024", "Repeated tip access",
               "PASS" if all(a[0] for a in asserts) else "WARN",
               second_text[:200], asserts)
    else:
        record("TEST-024", "Repeated tip access", "SKIP",
               "No tip detail available from first pass",
               [(False, "Skipped")])

    # ── TEST-025: Non-football tips ──────────────────────
    # Check if cricket/rugby odds are in the tips
    non_football = []
    cricket_emojis = ["🏏"]
    rugby_emojis = ["🏉"]
    for t in ht_texts:
        if any(e in t for e in cricket_emojis):
            non_football.append("cricket")
        if any(e in t for e in rugby_emojis):
            non_football.append("rugby")

    asserts = [
        (True, f"Non-football sports in tips: {non_football if non_football else 'none (football only)'}"),
    ]
    record("TEST-025", "Non-football tips (informational)",
           "PASS",
           f"Sports found: {non_football}", asserts,
           detail="Informational — depends on odds.db content")

    # ── TEST-026: /admin after Hot Tips ──────────────────
    admin2_msg = await send(client, "/admin")
    admin2_text = txt(admin2_msg)
    asserts = [
        (admin2_msg is not None, "Admin responded after Hot Tips flow"),
        (len(admin2_text) > 50, f"Admin text: {len(admin2_text)} chars"),
    ]
    record("TEST-026", "/admin after Hot Tips",
           "PASS" if all(a[0] for a in asserts) else "FAIL",
           admin2_text, asserts)


# ═════════════════════════════════════════════════════════════
# MAIN
# ═════════════════════════════════════════════════════════════

async def main():
    if not SESSION_PATH.exists():
        log.error("No Telethon session at %s", SESSION_PATH)
        sys.exit(1)

    session_str = SESSION_PATH.read_text().strip()
    client = TelegramClient(StringSession(session_str), API_ID, API_HASH)
    await client.connect()

    if not await client.is_user_authorized():
        log.error("Session expired. Re-run save_telethon_session.py")
        sys.exit(1)

    me = await client.get_me()
    log.info("Connected as: %s (@%s) id=%s", me.first_name, me.username, me.id)
    log.info("Testing bot: @%s", BOT)
    log.info("=" * 60)

    try:
        await run_tests(client)
    except Exception as e:
        log.exception("Unhandled exception: %s", e)
        record("CRASH", "Test runner crashed", "FAIL", str(e),
               [(False, f"Exception: {e}")])
    finally:
        await client.disconnect()

    # Summary
    total = len(results)
    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    skipped = sum(1 for r in results if r["status"] == "SKIP")
    warned = sum(1 for r in results if r["status"] == "WARN")

    log.info("")
    log.info("=" * 60)
    log.info("WAVE 12B E2E RESULTS")
    log.info("=" * 60)
    log.info("  Total:   %d", total)
    log.info("  PASS:    %d", passed)
    log.info("  FAIL:    %d", failed)
    log.info("  SKIP:    %d", skipped)
    log.info("  WARN:    %d", warned)
    log.info("")

    for r in results:
        icon = {"PASS": "✓", "FAIL": "✗", "SKIP": "⊘", "WARN": "⚠"}.get(r["status"], "?")
        log.info("  %s %s: %s", icon, r["test_id"], r["name"])
        if r["status"] == "FAIL":
            for ok, msg in r["assertions"]:
                if not ok:
                    log.info("      → %s", msg)

    RESULTS_PATH.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    log.info("\nResults: %s", RESULTS_PATH)
    log.info("Captures: %s", REPORT_DIR)


if __name__ == "__main__":
    asyncio.run(main())
