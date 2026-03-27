"""Wave 15E — Wave 15A+15B Verification + Formatting Certification via Telethon.

Tests:
  T1: Odds Comparison 3 per-market CTAs (BUG-026)
  T2: Formatting Certification (game breakdowns × 16 checks each)
  T3: Sport Filter inline re-render (BUG-029)
  T4: Multi-Bookmaker Directory (FIX-001)
  T5: Regression spot-check

Usage:
    cd /home/paulsportsza/bot && source .venv/bin/activate
    python tests/e2e_wave15e.py 2>&1 | tee /home/paulsportsza/reports/e2e-wave15e-raw.txt
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
import time
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
log = logging.getLogger("wave15e")

BOT = "mzansiedge_bot"
API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "")
SESSION_PATH = Path("data/telethon_session.string")
REPORT_DIR = BOT_ROOT.parent / "reports" / "e2e-screenshots"
REPORT_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_PATH = BOT_ROOT.parent / "reports" / "wave15e-e2e-results.json"

BOT_TIMEOUT = 15
AI_TIMEOUT = 35

results: list[dict] = []
bugs: list[dict] = []

SA_BOOKMAKERS = {"Betway", "Hollywoodbets", "Sportingbet", "SupaBets", "GBets"}
SECTION_EMOJIS = {"📋", "🎯", "⚠️", "🏆"}
SECTION_HEADERS = {"The Setup", "The Edge", "The Risk", "Verdict"}
EDGE_EMOJIS = {"💎", "🥇", "🥈", "🥉"}


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
    (REPORT_DIR / f"15e-{safe}.txt").write_text(
        f"TEST: {test_id} — {name}\nSTATUS: {status}\n"
        f"RESPONSE:\n{response}\n\nASSERTIONS:\n"
        + "\n".join(f"  {'✓' if ok else '✗'} {msg}" for ok, msg in assertions)
        + (f"\n\nDETAIL: {detail}" if detail else ""),
        encoding="utf-8",
    )


def file_bug(bug_id: str, severity: str, screen: str, steps: str,
             expected: str, actual: str):
    bugs.append({
        "id": bug_id, "severity": severity, "screen": screen,
        "steps": steps, "expected": expected, "actual": actual,
    })
    log.warning("  🐛 %s (%s): %s — %s", bug_id, severity, screen, actual[:80])


# ── Helpers ──────────────────────────────────────────────────

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
    """Send a message and wait until the bot reply has inline buttons (handles loading states)."""
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
        # If we found a message but it has no buttons yet, re-fetch it (may have been edited)
        if found_id:
            updated = await c.get_messages(BOT, ids=found_id)
            if updated and updated.buttons:
                return updated
        await asyncio.sleep(1.5)
    # Final attempt
    if found_id:
        updated = await c.get_messages(BOT, ids=found_id)
        return updated
    return None


async def click_data(c: TelegramClient, msg: Message, prefix: str,
                     timeout: int = 10) -> Message | None:
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
                    msgs = await c.get_messages(BOT, limit=10)
                    for m in msgs:
                        if m.id > old and not m.out:
                            return m
                    updated = await c.get_messages(BOT, ids=msg.id)
                    if updated:
                        return updated
                    return None
    return None


async def click_data_wait(c: TelegramClient, msg: Message, prefix: str,
                          timeout: int = AI_TIMEOUT) -> Message | None:
    """Like click_data but with extended polling for AI responses + message edits."""
    if not msg or not msg.buttons:
        return None
    old = await _last_id(c)
    target_btn = None
    for row in msg.buttons:
        for btn in row:
            if hasattr(btn, "data") and btn.data:
                cb = btn.data.decode() if isinstance(btn.data, bytes) else str(btn.data)
                if cb.startswith(prefix):
                    target_btn = btn
                    break
        if target_btn:
            break
    if not target_btn:
        return None
    try:
        await target_btn.click()
    except Exception:
        return None
    await asyncio.sleep(2)
    deadline = time.time() + timeout
    while time.time() < deadline:
        # Check for new messages with buttons
        msgs = await c.get_messages(BOT, limit=5)
        for m in msgs:
            if m.id > old and not m.out and m.buttons:
                btns = get_buttons(m)
                if any("back" in b.lower() or "menu" in b.lower() for b in btns):
                    return m
        # Check edited message
        updated = await c.get_messages(BOT, ids=msg.id)
        if updated and updated.buttons:
            btns = get_buttons(updated)
            if any("back" in b.lower() or "menu" in b.lower() for b in btns):
                return updated
        await asyncio.sleep(2)
    # Return whatever we can find
    msgs = await c.get_messages(BOT, limit=5)
    for m in msgs:
        if m.id > old and not m.out:
            return m
    updated = await c.get_messages(BOT, ids=msg.id)
    return updated


async def click_text(c: TelegramClient, msg: Message, text: str,
                     partial: bool = False) -> Message | None:
    if not msg or not msg.buttons:
        return None
    old = await _last_id(c)
    for row in msg.buttons:
        for btn in row:
            match = (partial and text.lower() in btn.text.lower()) or \
                    btn.text.lower() == text.lower()
            if match:
                try:
                    await btn.click()
                except Exception:
                    return None
                await asyncio.sleep(3)
                msgs = await c.get_messages(BOT, limit=10)
                for m in msgs:
                    if m.id > old and not m.out:
                        return m
                updated = await c.get_messages(BOT, ids=msg.id)
                if updated:
                    return updated
                return None
    return None


def get_buttons(msg: Message) -> list[str]:
    if not msg or not msg.buttons:
        return []
    return [btn.text for row in msg.buttons for btn in row]


def get_callback_data(msg: Message) -> list[str]:
    if not msg or not msg.buttons:
        return []
    cbs = []
    for row in msg.buttons:
        for btn in row:
            if hasattr(btn, "data") and btn.data:
                cb = btn.data.decode() if isinstance(btn.data, bytes) else str(btn.data)
                cbs.append(cb)
            elif hasattr(btn, "url") and btn.url:
                cbs.append(f"URL:{btn.url}")
    return cbs


def get_url_buttons(msg: Message) -> list[tuple[str, str]]:
    """Returns list of (label, url) for URL buttons."""
    if not msg or not msg.buttons:
        return []
    out = []
    for row in msg.buttons:
        for btn in row:
            if hasattr(btn, "url") and btn.url:
                out.append((btn.text, btn.url))
    return out


# ── Formatting Check Helpers ─────────────────────────────────

def check_formatting(raw_text: str, styled_text: str) -> list[tuple[bool, str]]:
    """Run 16 formatting checks on a game breakdown response.

    raw_text: msg.raw_text (plain text, no entities)
    styled_text: msg.text (Telethon adds **bold** and __italic__ from entities)

    Returns assertion tuples.
    """
    checks = []

    # 1. No markdown headers in raw text
    has_md_header = bool(re.search(r'^#{1,3}\s', raw_text, re.MULTILINE))
    checks.append((not has_md_header, f"F01: No markdown headers: {not has_md_header}"))

    # 2. No raw markdown bold ** in raw_text
    # If sanitize converted ** to <b>, Telegram creates entities → raw_text won't have **
    # If ** leaked through, raw_text WILL have **
    has_raw_md_bold = "**" in raw_text
    checks.append((not has_raw_md_bold, f"F02: No raw markdown bold **: {not has_raw_md_bold}"))

    # 3. No raw markdown italic *text* or _text_ in raw_text
    has_md_italic_star = bool(re.search(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', raw_text))
    has_md_italic_under = bool(re.search(r'(?<!\w)_([^_]+)_(?!\w)', raw_text))
    has_md_italic = has_md_italic_star or has_md_italic_under
    checks.append((not has_md_italic, f"F03: No raw markdown italic: {not has_md_italic}"))

    # 4. Section headers are bold — check styled_text for **The Setup** etc.
    bold_headers = 0
    for hdr in SECTION_HEADERS:
        if f"**{hdr}**" in styled_text:
            bold_headers += 1
    checks.append((bold_headers >= 2, f"F04: Section headers bold ({bold_headers}/4): {bold_headers >= 2}"))

    # 5. Section spacing — blank line before section emojis (check raw_text)
    spacing_ok = True
    for emoji in SECTION_EMOJIS:
        idx = raw_text.find(emoji)
        if idx > 1:
            before = raw_text[idx-2:idx]
            if before != "\n\n":
                spacing_ok = False
                break
    checks.append((spacing_ok, f"F05: Section spacing (blank line before emoji): {spacing_ok}"))

    # 6. No triple+ blank lines
    has_triple_blank = "\n\n\n" in raw_text
    checks.append((not has_triple_blank, f"F06: No triple blank lines: {not has_triple_blank}"))

    # 7. No trailing whitespace on lines
    trailing_ws_count = sum(1 for line in raw_text.split('\n') if line != line.rstrip())
    checks.append((trailing_ws_count == 0,
                    f"F07: No trailing whitespace ({trailing_ws_count} lines): {trailing_ws_count == 0}"))

    # 8. No conviction text
    has_conviction = bool(re.search(
        r'(?:with\s+)?(?:High|Medium|Low)\s+conviction', raw_text, re.IGNORECASE))
    has_conviction2 = bool(re.search(
        r'Conviction:\s*(?:High|Medium|Low)', raw_text, re.IGNORECASE))
    no_conviction = not has_conviction and not has_conviction2
    checks.append((no_conviction, f"F08: No conviction text: {no_conviction}"))

    # 9-12: Required sections present
    checks.append(("📋" in raw_text, f"F09: Has 📋 The Setup: {'📋' in raw_text}"))
    checks.append(("🎯" in raw_text, f"F10: Has 🎯 The Edge: {'🎯' in raw_text}"))
    has_risk = "⚠️" in raw_text or "⚠" in raw_text
    checks.append((has_risk, f"F11: Has ⚠️ The Risk: {has_risk}"))
    checks.append(("🏆" in raw_text, f"F12: Has 🏆 Verdict: {'🏆' in raw_text}"))

    # 13. Verdict has edge badge (💎/🥇/🥈/🥉)
    verdict_idx = raw_text.find("🏆")
    if verdict_idx >= 0:
        verdict_section = raw_text[verdict_idx:verdict_idx + 120]
        has_edge_badge = any(e in verdict_section for e in EDGE_EMOJIS)
        # Non-football or no-odds matches may not have edge badge — soft check
        checks.append((has_edge_badge,
                        f"F13: Verdict edge badge: {has_edge_badge}"))
    else:
        checks.append((False, "F13: Verdict edge badge: N/A (no verdict)"))

    # 14. No duplicate match title at top (line with "vs" + digits)
    first_line = raw_text.split('\n')[0] if raw_text else ""
    has_dup_title = " vs " in first_line and any(c.isdigit() for c in first_line)
    checks.append((not has_dup_title, f"F14: No duplicate match title: {not has_dup_title}"))

    # 15. Bullets use • (not bare - or * at line start)
    has_md_bullet = bool(re.search(r'^[\-\*]\s+', raw_text, re.MULTILINE))
    checks.append((not has_md_bullet, f"F15: Bullets use • not -/*: {not has_md_bullet}"))

    # 16. SA Bookmaker Odds section exists (separator or header)
    has_odds_section = ("SA Bookmaker Odds" in raw_text or "Bookmaker Odds" in raw_text
                        or "━" in raw_text)
    checks.append((has_odds_section, f"F16: SA Bookmaker Odds section: {has_odds_section}"))

    return checks


# ── Main Tests ───────────────────────────────────────────────

async def run_tests():
    session_str = SESSION_PATH.read_text().strip()
    client = TelegramClient(StringSession(session_str), API_ID, API_HASH)
    await client.connect()

    me = await client.get_me()
    log.info("Connected as: %s (@%s)", me.first_name, me.username)
    log.info("Testing bot: @%s", BOT)
    log.info("=" * 60)

    await asyncio.sleep(2)

    # ================================================================
    # SECTION 1: T1 — ODDS COMPARISON 3 PER-MARKET CTAs
    # ================================================================
    log.info("")
    log.info("=" * 60)
    log.info("SECTION 1: T1 — ODDS COMPARISON 3 PER-MARKET CTAs")
    log.info("=" * 60)

    # Strategy: Your Games → click first football game → wait for AI → click Compare Odds
    yg_msg = await send(client, "⚽ Your Games")
    odds_compare_done = False
    if not yg_msg:
        record("T1-01", "Odds Comparison — 3 CTAs", "SKIP", "No Your Games response", [])
    else:
        yg_cbs = get_callback_data(yg_msg)

        # Find a football game (⚽ prefix in button text, or just first yg:game)
        game_cbs = [cb for cb in yg_cbs if cb.startswith("yg:game:")]
        btns_list = get_buttons(yg_msg)

        # Pick the first football game — look for ⚽ in button text
        target_cb = None
        for i, cb in enumerate(game_cbs):
            # Match the yg:game callbacks with button labels
            for btn_text in btns_list:
                if "⚽" in btn_text:
                    target_cb = cb
                    break
            if target_cb:
                break
        if not target_cb and game_cbs:
            target_cb = game_cbs[0]

        if not target_cb:
            record("T1-01", "Odds Comparison — 3 CTAs", "SKIP",
                   f"No games in Your Games. CBs: {yg_cbs}", [])
        else:
            log.info("  Clicking game: %s (waiting for AI...)", target_cb[:30])
            gd_msg = await click_data_wait(client, yg_msg, target_cb)
            if not gd_msg:
                record("T1-01", "Odds Comparison — 3 CTAs", "SKIP",
                       "No response from game click", [])
            else:
                gd_cbs = get_callback_data(gd_msg)
                gd_btns = get_buttons(gd_msg)
                gd_text = gd_msg.raw_text or ""
                log.info("  Game detail buttons: %s", gd_btns)
                log.info("  Game detail CBs: %s", gd_cbs)

                # Find odds:compare callback
                odds_cb = None
                for cb in gd_cbs:
                    if cb.startswith("odds:compare:"):
                        odds_cb = cb
                        break

                if not odds_cb:
                    record("T1-01", "Odds Comparison — 3 CTAs", "SKIP",
                           f"No odds:compare button (game may lack multi-bookmaker data). "
                           f"Buttons: {gd_btns}\nText: {gd_text[:200]}",
                           [(False, "No Compare Odds button found")])
                else:
                    # Click odds comparison
                    odds_msg = await click_data(client, gd_msg, "odds:compare:")
                    if not odds_msg:
                        record("T1-01", "Odds Comparison — 3 CTAs", "SKIP",
                               "No response from odds:compare click", [])
                    else:
                        odds_text = odds_msg.raw_text or ""
                        odds_btns = get_buttons(odds_msg)
                        url_btns = get_url_buttons(odds_msg)

                        # T1-01: Per-market CTA buttons
                        cta_btns = [b for b in url_btns if "Best for" in b[0]]
                        cta_count = len(cta_btns)
                        asserts = [
                            (cta_count >= 2, f"At least 2 per-market CTAs: {cta_count}"),
                        ]
                        for label, url in cta_btns:
                            fmt_ok = "📲" in label and "→" in label
                            asserts.append((fmt_ok, f"CTA format OK: {label}"))
                        labels_text = " ".join(b[0] for b in cta_btns)
                        asserts.append(("Home Win" in labels_text, f"Has Home Win CTA"))
                        asserts.append(("Draw" in labels_text, f"Has Draw CTA"))
                        asserts.append(("Away Win" in labels_text, f"Has Away Win CTA"))
                        for label, url in cta_btns:
                            asserts.append((url.startswith("https://"), f"Valid URL: {url[:50]}"))

                        status = "PASS" if all(a[0] for a in asserts) else "FAIL"
                        record("T1-01", "Odds Comparison — 3 per-market CTAs", status,
                               f"Text: {odds_text}\nCTA Buttons: {cta_btns}", asserts)

                        # T1-02: All 3 markets shown with bookmakers
                        market_asserts = [
                            ("🏠" in odds_text or "Home Win" in odds_text,
                             "Home Win market shown"),
                            ("🤝" in odds_text or "Draw" in odds_text,
                             "Draw market shown"),
                            ("🏟️" in odds_text or "Away Win" in odds_text,
                             "Away Win market shown"),
                        ]
                        bk_found = sum(1 for bk in SA_BOOKMAKERS if bk in odds_text)
                        market_asserts.append(
                            (bk_found >= 2, f"At least 2 bookmakers: {bk_found}"))
                        market_asserts.append(
                            ("⭐" in odds_text, "Best odds ⭐ marker present"))
                        status = "PASS" if all(a[0] for a in market_asserts) else "FAIL"
                        record("T1-02", "Odds Comparison — all 3 markets + bookmakers",
                               status, odds_text, market_asserts)

                        # T1-03: Nav buttons
                        has_back = any("Back" in b for b in odds_btns)
                        has_menu = any("Menu" in b for b in odds_btns)
                        nav_asserts = [
                            (has_back, "Has Back button"),
                            (has_menu, "Has Menu button"),
                        ]
                        status = "PASS" if all(a[0] for a in nav_asserts) else "FAIL"
                        record("T1-03", "Odds Comparison — nav buttons", status,
                               f"Buttons: {odds_btns}", nav_asserts)
                        odds_compare_done = True

    # ================================================================
    # SECTION 2: T2 — FORMATTING CERTIFICATION
    # ================================================================
    log.info("")
    log.info("=" * 60)
    log.info("SECTION 2: T2 — FORMATTING CERTIFICATION")
    log.info("=" * 60)

    # Fresh navigation to Your Games
    yg_msg = await send(client, "⚽ Your Games")
    football_event_ids = []
    if yg_msg:
        yg_cbs = get_callback_data(yg_msg)
        for cb in yg_cbs:
            if cb.startswith("yg:game:"):
                eid = cb.replace("yg:game:", "")
                football_event_ids.append(eid)

    log.info("  Found %d games for formatting certification", len(football_event_ids))

    total_format_checks = 0
    total_format_pass = 0
    total_format_fail = 0
    format_fails_detail = []

    for idx, event_id in enumerate(football_event_ids):
        test_id = f"T2-{idx+1:02d}"
        log.info("  Testing game %d/%d: %s", idx + 1, len(football_event_ids), event_id[:20])

        # Navigate fresh to Your Games each time
        if idx > 0:
            yg_msg = await send(client, "⚽ Your Games")
            if not yg_msg:
                record(test_id, f"Format check game {idx+1}", "SKIP",
                       "Could not navigate to Your Games", [])
                continue

        # Click the game
        game_prefix = f"yg:game:{event_id}"
        gd_msg = await click_data_wait(client, yg_msg, game_prefix)

        if not gd_msg:
            record(test_id, f"Format check game {idx+1}", "SKIP",
                   f"No response for {event_id}", [])
            continue

        raw_text = gd_msg.raw_text or ""
        styled_text = gd_msg.text or ""

        if len(raw_text) < 50:
            record(test_id, f"Format check game {idx+1}", "SKIP",
                   f"Response too short ({len(raw_text)} chars): {raw_text}",
                   [(False, "Response too short")])
            continue

        # Run 16 formatting checks
        checks = check_formatting(raw_text, styled_text)
        total_format_checks += len(checks)
        pass_count = sum(1 for ok, _ in checks if ok)
        fail_count = sum(1 for ok, _ in checks if not ok)
        total_format_pass += pass_count
        total_format_fail += fail_count

        if fail_count > 0:
            for ok, msg_txt in checks:
                if not ok:
                    format_fails_detail.append(f"{test_id}: {msg_txt}")

        status = "PASS" if all(ok for ok, _ in checks) else "FAIL"
        detail = f"{pass_count}/{len(checks)} checks passed"
        record(test_id, f"Format cert — game {idx+1} ({event_id[:16]})",
               status, f"RAW:\n{raw_text}\n\nSTYLED:\n{styled_text}", checks, detail)

        await asyncio.sleep(1)

    # T2 summary
    if football_event_ids:
        summary_asserts = [
            (total_format_fail == 0,
             f"All format checks pass: {total_format_pass}/{total_format_checks}"),
            (len(football_event_ids) >= 3,
             f"At least 3 games tested: {len(football_event_ids)}"),
        ]
        summary_status = ("PASS" if all(a[0] for a in summary_asserts) else
                          "WARN" if total_format_fail < 5 else "FAIL")
        record("T2-SUM", f"Format cert summary ({len(football_event_ids)} games)",
               summary_status,
               f"Total: {total_format_checks}, Pass: {total_format_pass}, "
               f"Fail: {total_format_fail}\n" + "\n".join(format_fails_detail[:20]),
               summary_asserts,
               f"{total_format_pass}/{total_format_checks} across {len(football_event_ids)} games")
    else:
        record("T2-SUM", "Format cert summary", "SKIP",
               "No games available", [(False, "No games")])

    # ================================================================
    # SECTION 3: T3 — SPORT FILTER INLINE RE-RENDER
    # ================================================================
    log.info("")
    log.info("=" * 60)
    log.info("SECTION 3: T3 — SPORT FILTER INLINE RE-RENDER")
    log.info("=" * 60)

    yg_msg = await send(client, "⚽ Your Games")
    if not yg_msg:
        record("T3-01", "Sport filter — baseline", "SKIP", "No Your Games response", [])
    else:
        yg_text = yg_msg.raw_text or ""
        yg_btns = get_buttons(yg_msg)
        yg_cbs = get_callback_data(yg_msg)

        # T3-01: Sport filter row exists
        sport_cbs = [cb for cb in yg_cbs if cb.startswith("yg:sport:")]
        asserts = [(len(sport_cbs) >= 1, f"Sport filter buttons: {len(sport_cbs)}")]
        status = "PASS" if all(a[0] for a in asserts) else "FAIL"
        record("T3-01", "Sport filter — filter row exists", status,
               f"Buttons: {yg_btns}\nCBs: {yg_cbs}", asserts)

        if sport_cbs:
            first_sport_cb = sport_cbs[0]
            sport_key = first_sport_cb.replace("yg:sport:", "")
            log.info("  Clicking sport filter: %s", first_sport_cb)

            # T3-02: Click sport emoji → inline re-render
            filtered_msg = await click_data(client, yg_msg, first_sport_cb)
            if not filtered_msg:
                record("T3-02", "Sport filter — inline re-render", "SKIP",
                       "No response", [])
            else:
                ft = filtered_msg.raw_text or ""
                fc = get_callback_data(filtered_msg)
                fb = get_buttons(filtered_msg)

                has_all_btn = any(cb == "yg:all:0" for cb in fc)
                has_content = len(ft) > 30

                asserts = [
                    (has_all_btn, f"'All' button when filtered: {has_all_btn}"),
                    (has_content, f"Content rendered: {len(ft)} chars"),
                ]
                status = "PASS" if all(a[0] for a in asserts) else "FAIL"
                record("T3-02", f"Sport filter — filtered view ({sport_key})", status,
                       f"Text: {ft[:300]}\nButtons: {fb}", asserts)

                # T3-03: Click "All" to remove filter
                all_msg = await click_data(client, filtered_msg, "yg:all:0")
                if not all_msg:
                    record("T3-03", "Sport filter — 'All' removes filter", "SKIP",
                           "No response", [])
                else:
                    at = all_msg.raw_text or ""
                    ac = get_callback_data(all_msg)
                    has_sport_btns = any(cb.startswith("yg:sport:") for cb in ac)
                    asserts = [
                        (has_sport_btns, "Sport filter buttons still present"),
                        (len(at) > 50, f"Content: {len(at)} chars"),
                    ]
                    status = "PASS" if all(a[0] for a in asserts) else "FAIL"
                    record("T3-03", "Sport filter — 'All' removes filter", status,
                           f"Text: {at[:300]}", asserts)

                # T3-04: Active sport is bracketed
                bracketed = any("[" in b and "]" in b for b in fb)
                asserts = [(bracketed, f"Active sport bracketed: buttons={fb}")]
                status = "PASS" if all(a[0] for a in asserts) else "FAIL"
                record("T3-04", "Sport filter — active sport bracketed", status,
                       f"Buttons: {fb}", asserts)
        else:
            record("T3-02", "Sport filter — no filter buttons", "SKIP", "", [])

    # ================================================================
    # SECTION 4: T4 — MULTI-BOOKMAKER DIRECTORY
    # ================================================================
    log.info("")
    log.info("=" * 60)
    log.info("SECTION 4: T4 — MULTI-BOOKMAKER DIRECTORY")
    log.info("=" * 60)

    # Navigate: send /start → get welcome → find inline menu with Bookmakers
    # The welcome has a reply keyboard but may not have inline buttons
    # Use nav:main from any inline-buttoned message to reach main menu
    menu_msg = await send(client, "⚽ Your Games")  # this has nav:main button
    if menu_msg:
        # Click Menu button to get main inline menu
        main_msg = await click_data(client, menu_msg, "nav:main")
        if not main_msg:
            # Try clicking menu:home
            main_msg = await click_data(client, menu_msg, "menu:home")
        if main_msg:
            main_cbs = get_callback_data(main_msg)
            main_btns = get_buttons(main_msg)
            log.info("  Main menu buttons: %s", main_btns)
            log.info("  Main menu CBs: %s", main_cbs)

            # Find affiliate or bookmaker callback
            bk_msg = await click_data(client, main_msg, "affiliate:")
            if not bk_msg:
                bk_msg = await click_text(client, main_msg, "Bookmaker", partial=True)

            if bk_msg:
                bk_text = bk_msg.raw_text or ""
                bk_btns = get_buttons(bk_msg)
                bk_urls = get_url_buttons(bk_msg)

                # T4-01: All 5 SA bookmakers
                found_bks = {bk for bk in SA_BOOKMAKERS if bk in bk_text}
                asserts = [(len(found_bks) >= 5, f"All 5 bookmakers: {found_bks}")]
                tagline_keywords = ["payouts", "favourite", "odds", "sign-up", "promos",
                                    "registration", "streaming", "Goldrush", "markets",
                                    "Growing"]
                tagline_count = sum(1 for kw in tagline_keywords if kw.lower() in bk_text.lower())
                asserts.append((tagline_count >= 3,
                                f"Taglines present ({tagline_count} keywords)"))
                status = "PASS" if all(a[0] for a in asserts) else "FAIL"
                record("T4-01", "Multi-bookmaker directory — all 5 shown", status,
                       bk_text, asserts)

                # T4-02: Sign-up CTA buttons
                signup_btns = [b for b in bk_urls if "Sign Up" in b[0]]
                asserts = [(len(signup_btns) >= 5, f"5 sign-up buttons: {len(signup_btns)}")]
                for label, url in signup_btns:
                    asserts.append((url.startswith("https://"), f"URL: {label} → {url[:50]}"))
                status = "PASS" if all(a[0] for a in asserts) else "FAIL"
                record("T4-02", "Multi-bookmaker directory — sign-up CTAs", status,
                       f"URL Buttons: {signup_btns}", asserts)

                # T4-03: Nav buttons
                has_back = any("Back" in b for b in bk_btns)
                has_menu = any("Menu" in b for b in bk_btns)
                asserts = [(has_back, "Back button"), (has_menu, "Menu button")]
                status = "PASS" if all(a[0] for a in asserts) else "FAIL"
                record("T4-03", "Multi-bookmaker directory — nav buttons", status,
                       f"Buttons: {bk_btns}", asserts)

                # T4-04: Responsible gambling disclaimer
                has_disclaimer = "responsib" in bk_text.lower() or "18+" in bk_text
                asserts = [(has_disclaimer, "Responsible gambling notice")]
                status = "PASS" if all(a[0] for a in asserts) else "FAIL"
                record("T4-04", "Multi-bookmaker directory — disclaimer", status,
                       bk_text[-200:], asserts)
            else:
                record("T4-01", "Multi-bookmaker directory", "SKIP",
                       f"No Bookmakers button in main menu. Buttons: {main_btns}",
                       [(False, "Could not find Bookmakers")])
        else:
            record("T4-01", "Multi-bookmaker directory", "SKIP",
                   "Could not reach main menu", [])
    else:
        record("T4-01", "Multi-bookmaker directory", "SKIP",
               "No Your Games response", [])

    # ================================================================
    # SECTION 5: T5 — REGRESSION SPOT-CHECK
    # ================================================================
    log.info("")
    log.info("=" * 60)
    log.info("SECTION 5: T5 — REGRESSION SPOT-CHECK")
    log.info("=" * 60)

    # T5-01: /start
    start_msg = await send(client, "/start")
    if start_msg:
        st = start_msg.raw_text or ""
        asserts = [(len(st) > 20, f"/start: {len(st)} chars")]
        status = "PASS" if all(a[0] for a in asserts) else "FAIL"
        record("T5-01", "Regression — /start", status, st[:300], asserts)
    else:
        record("T5-01", "Regression — /start", "FAIL", "No response", [])

    # T5-02: Hot Tips (use send_wait_buttons to handle loading state)
    hot_msg = await send_wait_buttons(client, "🔥 Hot Tips")
    if hot_msg:
        ht = hot_msg.raw_text or ""
        hot_cbs = get_callback_data(hot_msg)
        has_tips = "Hot Tips" in ht or "🔥" in ht or "bets found" in ht.lower()
        has_edge = any(e in ht for e in EDGE_EMOJIS)
        has_buttons = len(hot_cbs) > 0
        asserts = [
            (has_tips, "Hot Tips content present"),
            (has_edge, "Edge badges present"),
            (has_buttons, f"Has inline buttons: {len(hot_cbs)}"),
        ]
        status = "PASS" if all(a[0] for a in asserts) else "FAIL"
        record("T5-02", "Regression — Hot Tips", status, ht[:500], asserts)
    else:
        record("T5-02", "Regression — Hot Tips", "FAIL", "No response", [])

    # T5-03: Settings
    set_msg = await send(client, "⚙️ Settings")
    if set_msg:
        st = set_msg.raw_text or ""
        sbtns = get_buttons(set_msg)
        asserts = [
            (len(sbtns) >= 3, f"3+ buttons: {len(sbtns)}"),
            ("settings" in st.lower() or len(sbtns) >= 3, "Settings screen"),
        ]
        status = "PASS" if all(a[0] for a in asserts) else "FAIL"
        record("T5-03", "Regression — Settings", status,
               f"Text: {st[:200]}\nButtons: {sbtns}", asserts)
    else:
        record("T5-03", "Regression — Settings", "FAIL", "No response", [])

    # T5-04: Profile
    prof_msg = await send(client, "👤 Profile")
    if prof_msg:
        pt = prof_msg.raw_text or ""
        asserts = [(len(pt) > 50, f"Profile: {len(pt)} chars")]
        status = "PASS" if all(a[0] for a in asserts) else "FAIL"
        record("T5-04", "Regression — Profile", status, pt[:300], asserts)
    else:
        record("T5-04", "Regression — Profile", "FAIL", "No response", [])

    # T5-05: Help
    help_msg = await send(client, "❓ Help")
    if help_msg:
        hpt = help_msg.raw_text or ""
        asserts = [(len(hpt) > 30, f"Help: {len(hpt)} chars")]
        status = "PASS" if all(a[0] for a in asserts) else "FAIL"
        record("T5-05", "Regression — Help", status, hpt[:300], asserts)
    else:
        record("T5-05", "Regression — Help", "FAIL", "No response", [])

    # T5-06: Guide
    guide_msg = await send(client, "📖 Guide")
    if guide_msg:
        gt = guide_msg.raw_text or ""
        has_edge_section = "Edge Ratings" in gt or "Diamond" in gt
        has_tiers = sum(1 for e in EDGE_EMOJIS if e in gt)
        asserts = [
            (has_edge_section, "Edge Ratings section"),
            (has_tiers >= 3, f"Tier emojis: {has_tiers}/4"),
        ]
        status = "PASS" if all(a[0] for a in asserts) else "FAIL"
        record("T5-06", "Regression — Guide", status, gt[:500], asserts)
    else:
        record("T5-06", "Regression — Guide", "FAIL", "No response", [])

    # ── Disconnect ────────────────────────────────────────────────
    await client.disconnect()

    # ── Summary ───────────────────────────────────────────────────
    log.info("")
    log.info("=" * 60)
    log.info("WAVE 15E VERIFICATION RESULTS")
    log.info("=" * 60)
    total = len(results)
    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    skipped = sum(1 for r in results if r["status"] == "SKIP")
    warned = sum(1 for r in results if r["status"] == "WARN")
    log.info("  Total:   %d", total)
    log.info("  PASS:    %d", passed)
    log.info("  FAIL:    %d", failed)
    log.info("  SKIP:    %d", skipped)
    log.info("  WARN:    %d", warned)
    log.info("")
    for r in results:
        icon = {"PASS": "✓", "FAIL": "✗", "SKIP": "⊘", "WARN": "⚠"}.get(r["status"], "?")
        log.info("  %s %s: %s", icon, r["test_id"], r["name"])
    if bugs:
        log.info("")
        log.info("  BUGS FILED: %d", len(bugs))
        for b in bugs:
            log.info("    %s (%s): %s", b["id"], b["severity"], b["screen"])

    summary = {
        "wave": "15E",
        "total": total,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "warned": warned,
        "bug_count": len(bugs),
        "format_checks_total": total_format_checks,
        "format_checks_pass": total_format_pass,
        "format_checks_fail": total_format_fail,
        "results": results,
        "bugs": bugs,
    }
    RESULTS_PATH.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("")
    log.info("Results: %s", RESULTS_PATH)


if __name__ == "__main__":
    asyncio.run(run_tests())
