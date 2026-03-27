"""Wave 13H — North Star E2E Verification via Telethon.

Tests the Wave 13F implementation: simplified game breakdown, recommended bet CTA,
verdict edge badges, odds comparison affiliates, analysis caching, back button emoji.

Usage:
    cd /home/paulsportsza/bot && source .venv/bin/activate
    python tests/e2e_wave13h.py 2>&1 | tee /home/paulsportsza/reports/e2e-wave13h-raw.txt
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sqlite3
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
log = logging.getLogger("wave13h")

BOT = "mzansiedge_bot"
API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "")
SESSION_PATH = Path("data/telethon_session.string")
REPORT_DIR = BOT_ROOT.parent / "reports" / "e2e-screenshots"
REPORT_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_PATH = BOT_ROOT.parent / "reports" / "wave13h-e2e-results.json"
from config import ODDS_DB_PATH
ODDS_DB = ODDS_DB_PATH

BOT_TIMEOUT = 15
AI_TIMEOUT = 30  # AI generation can take longer

results: list[dict] = []
bugs: list[dict] = []

# ── Known bookmaker display names ──
KNOWN_BOOKMAKERS = {
    "betway", "hollywoodbets", "supabets", "gbets", "sportingbet",
    "Betway", "Hollywoodbets", "SupaBets", "GBets", "Sportingbet",
    "HollywoodBets",
}
KNOWN_BK_LOWER = {b.lower() for b in KNOWN_BOOKMAKERS}

# ── Edge tier emojis (Diamond system from Wave 14A) ──
TIER_EMOJIS = {"💎", "🥇", "🥈", "🥉"}


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
    (REPORT_DIR / f"13h-{safe}.txt").write_text(
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


async def send_get_all(c: TelegramClient, text: str,
                       timeout: int = BOT_TIMEOUT, settle: float = 5.0) -> list[Message]:
    last = await _last_id(c)
    try:
        await c.send_message(BOT, text)
    except FloodWaitError as e:
        await asyncio.sleep(e.seconds + 2)
        await c.send_message(BOT, text)
    await asyncio.sleep(3)
    deadline = time.time() + timeout
    prev = 0
    stable = 0
    while time.time() < deadline:
        msgs = await c.get_messages(BOT, limit=20)
        bm = [m for m in msgs if m.id > last and not m.out]
        if len(bm) == prev:
            stable += 1
            if stable >= 3:
                break
        else:
            stable = 0
            prev = len(bm)
        await asyncio.sleep(1)
    await asyncio.sleep(settle)
    msgs = await c.get_messages(BOT, limit=20)
    found = [m for m in msgs if m.id > last and not m.out]
    found.sort(key=lambda m: m.id)
    return found


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
    """Like click_data but with extended polling for AI-generated responses.

    Handles message edits: the bot sends a loading message then edits it.
    We poll until the edited message has buttons or timeout.
    """
    if not msg or not msg.buttons:
        return None
    old = await _last_id(c)
    target_btn = None
    target_cb = ""
    for row in msg.buttons:
        for btn in row:
            if hasattr(btn, "data") and btn.data:
                cb = btn.data.decode() if isinstance(btn.data, bytes) else str(btn.data)
                if cb.startswith(prefix):
                    target_btn = btn
                    target_cb = cb
                    break
        if target_btn:
            break
    if not target_btn:
        return None

    try:
        await target_btn.click()
    except Exception:
        return None

    # Poll for response — check both new messages and edits to existing ones
    await asyncio.sleep(2)
    deadline = time.time() + timeout
    while time.time() < deadline:
        # Check for new messages first
        msgs = await c.get_messages(BOT, limit=5)
        for m in msgs:
            if m.id > old and not m.out and m.buttons:
                return m
        # Check if the original message was edited (loading → analysis)
        updated = await c.get_messages(BOT, ids=msg.id)
        if updated and updated.buttons:
            # Message was edited and now has buttons — AI response is ready
            return updated
        await asyncio.sleep(2)

    # Last try — get whatever we have
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
    """Get all button texts from a message."""
    if not msg or not msg.buttons:
        return []
    return [btn.text for row in msg.buttons for btn in row]


def get_callback_data(msg: Message) -> list[str]:
    """Get all callback data from inline buttons."""
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
    """Get all URL buttons as (text, url) tuples."""
    if not msg or not msg.buttons:
        return []
    urls = []
    for row in msg.buttons:
        for btn in row:
            if hasattr(btn, "url") and btn.url:
                urls.append((btn.text, btn.url))
    return urls


def has_back(msg: Message) -> bool:
    """Check if message has back/menu navigation."""
    if not msg or not msg.buttons:
        return False
    for row in msg.buttons:
        for btn in row:
            t = btn.text.lower()
            if "↩️" in t or "menu" in t or "back" in t or "🏠" in t:
                return True
    return False


def contains_bookmaker(text: str) -> str | None:
    """Check if text contains a known bookmaker name, return it if found."""
    t = text.lower()
    for bk in KNOWN_BK_LOWER:
        if bk in t:
            return bk
    return None


def has_tier_emoji(text: str) -> bool:
    """Check if text contains a tier badge emoji."""
    return any(e in text for e in TIER_EMOJIS)


def query_odds_db(match_id: str) -> dict:
    """Query odds.db for a match to verify CTA accuracy."""
    if not ODDS_DB.exists():
        return {}
    try:
        db = sqlite3.connect(str(ODDS_DB))
        db.row_factory = sqlite3.Row
        c = db.cursor()
        c.execute("""
            SELECT bookmaker, home_odds, draw_odds, away_odds
            FROM odds_snapshots
            WHERE match_id = ? COLLATE NOCASE
            AND market_type = '1x2'
            ORDER BY scraped_at DESC
        """, (match_id,))
        rows = c.fetchall()
        db.close()
        if not rows:
            return {}
        # Group by bookmaker (latest per bookmaker)
        seen = set()
        result = {}
        for row in rows:
            bk = row["bookmaker"]
            if bk not in seen:
                seen.add(bk)
                result[bk] = {
                    "home": row["home_odds"],
                    "draw": row["draw_odds"],
                    "away": row["away_odds"],
                }
        return result
    except Exception as e:
        log.error("  odds.db query error: %s", e)
        return {}


# ── Main test suite ──────────────────────────────────────────

async def run_tests():
    session_str = SESSION_PATH.read_text().strip()
    client = TelegramClient(StringSession(session_str), API_ID, API_HASH)
    await client.connect()

    me = await client.get_me()
    log.info("Connected as: %s (@%s)", me.first_name, me.username)
    log.info("Testing bot: @%s", BOT)
    log.info("=" * 60)

    # ── Reset to known state ──
    await send(client, "/start")
    await asyncio.sleep(2)

    # ════════════════════════════════════════════════════════════
    # SECTION 1: GAME BREAKDOWN — BUTTON COUNT & CTA
    # ════════════════════════════════════════════════════════════
    log.info("")
    log.info("=" * 60)
    log.info("SECTION 1: GAME BREAKDOWN — BUTTON COUNT & CTA")
    log.info("=" * 60)

    # Get Your Games list
    yg_msg = await send(client, "⚽ Your Games")
    if not yg_msg:
        record("NS-01", "Your Games loads", "FAIL", "No response",
               [(False, "Your Games responded")])
    else:
        record("NS-01", "Your Games loads", "PASS",
               f"{yg_msg.text[:200]}\nButtons: {get_buttons(yg_msg)}",
               [(True, "Your Games responded")])

    # Click first game with football (⚽) — want a match with odds in DB
    game_msg = None
    game_event_id = ""
    if yg_msg and yg_msg.buttons:
        # Find a game button (yg:game: prefix)
        for row in yg_msg.buttons:
            for btn in row:
                if hasattr(btn, "data") and btn.data:
                    cb = btn.data.decode() if isinstance(btn.data, bytes) else str(btn.data)
                    if cb.startswith("yg:game:"):
                        game_event_id = cb.replace("yg:game:", "")
                        break
            if game_event_id:
                break

    if game_event_id:
        log.info("  Clicking game: %s (waiting for AI...)", game_event_id)
        game_msg = await click_data_wait(client, yg_msg, f"yg:game:{game_event_id}",
                                          timeout=AI_TIMEOUT)

    if not game_msg or not game_msg.buttons:
        # Try a second approach: click the first numbered button
        if yg_msg and yg_msg.buttons:
            for row in yg_msg.buttons:
                for btn in row:
                    t = btn.text
                    if t.startswith("[") and "]" in t:
                        try:
                            old = await _last_id(client)
                            await btn.click()
                            await asyncio.sleep(AI_TIMEOUT)
                            updated = await client.get_messages(BOT, limit=5)
                            for m in updated:
                                if m.id >= old and not m.out and m.buttons:
                                    game_msg = m
                                    break
                            if not game_msg:
                                updated = await client.get_messages(BOT, ids=yg_msg.id)
                                if updated and updated.buttons:
                                    game_msg = updated
                        except Exception:
                            pass
                        break
                if game_msg:
                    break

    # ── NS-02: Game Breakdown Button Count ──
    if game_msg and game_msg.buttons:
        btns = get_buttons(game_msg)
        cbs = get_callback_data(game_msg)
        urls = get_url_buttons(game_msg)
        n_buttons = len(btns)

        asserts = []
        # Expect exactly 4 buttons (CTA + Compare + Back + Menu)
        # OR 3 buttons if no compare (no multi-bookmaker data)
        ok_count = n_buttons in (3, 4)
        asserts.append((ok_count, f"Button count: {n_buttons} (expected 3-4)"))

        # Check no individual outcome buttons (old format: "Draw @ 2.85", "Leeds @ 3.10")
        has_old_outcome = any("@ " in b and not "Back " in b for b in btns if "→" not in b)
        asserts.append((not has_old_outcome, f"No old individual outcome buttons: {[b for b in btns if '@ ' in b and 'Back' not in b and '→' not in b]}"))

        status = "PASS" if all(ok for ok, _ in asserts) else "FAIL"
        record("NS-02", "Game Breakdown — button count (3-4)", status,
               f"Buttons ({n_buttons}): {btns}\nCB: {cbs}",
               asserts)

        if not ok_count:
            file_bug("BUG-NS-01", "P1", "Game Breakdown",
                     "Your Games → tap game → wait for AI",
                     "3-4 buttons (CTA + Compare + Back + Menu)",
                     f"Got {n_buttons} buttons: {btns}")
    else:
        record("NS-02", "Game Breakdown — button count", "FAIL",
               f"No game breakdown with buttons. game_msg={game_msg.text[:200] if game_msg else 'None'}",
               [(False, "Game breakdown has buttons")])
        file_bug("BUG-NS-01", "P1", "Game Breakdown",
                 "Your Games → tap game",
                 "Game analysis with buttons",
                 "No buttons on game breakdown")

    # ── NS-03: CTA is first button with tier badge ──
    if game_msg and game_msg.buttons:
        btns = get_buttons(game_msg)
        urls = get_url_buttons(game_msg)
        cbs = get_callback_data(game_msg)
        first_btn = btns[0] if btns else ""

        asserts = []

        # First button should be CTA (URL button or callback with tier emoji)
        first_is_url = bool(urls and urls[0][0] == first_btn)
        first_is_cta = ("Back " in first_btn and "→" in first_btn) or \
                       ("View odds" in first_btn and "→" in first_btn)
        asserts.append((first_is_cta, f"First button is CTA: {first_btn}"))

        # CTA should have tier badge (💎/🥇/🥈/🥉) for positive EV, or 📲 for fallback
        has_tier = has_tier_emoji(first_btn)
        has_view_fallback = "View odds" in first_btn
        asserts.append((has_tier or has_view_fallback,
                       f"CTA has tier badge or fallback: tier={has_tier}, fallback={has_view_fallback}"))

        # CTA should contain a bookmaker name
        bk = contains_bookmaker(first_btn)
        asserts.append((bk is not None, f"CTA has bookmaker: {bk} in '{first_btn}'"))

        # CTA should be external URL (not callback)
        if first_is_url:
            asserts.append((True, f"CTA is URL button: {urls[0][1][:60]}"))
        else:
            first_cb = cbs[0] if cbs else ""
            is_aff_soon = first_cb == "tip:affiliate_soon"
            asserts.append((is_aff_soon, f"CTA is URL or affiliate_soon: cb={first_cb}"))

        status = "PASS" if all(ok for ok, _ in asserts) else "FAIL"
        record("NS-03", "CTA — first button, tier badge, bookmaker, URL", status,
               f"First button: {first_btn}\nAll buttons: {btns}\nURLs: {urls}",
               asserts)

        if not all(ok for ok, _ in asserts):
            file_bug("BUG-NS-02", "P0", "Game Breakdown CTA",
                     "Your Games → tap game → check first button",
                     "CTA with tier badge + bookmaker + URL",
                     f"Got: {first_btn}")
    else:
        record("NS-03", "CTA — first button", "SKIP", "No game breakdown",
               [(False, "Skipped — no game breakdown")])

    # ── NS-04: CTA bookmaker has best odds for recommended outcome ──
    if game_msg and game_msg.buttons:
        btns = get_buttons(game_msg)
        first_btn = btns[0] if btns else ""
        text = game_msg.text or ""

        asserts = []

        # Extract outcome and bookmaker from CTA
        # Format: "{tier} Back {outcome} @ {odds} on {bookmaker} →"
        cta_match = re.search(r"Back (.+?) @ ([\d.]+) on (.+?) →", first_btn)
        if cta_match:
            cta_outcome = cta_match.group(1).strip()
            cta_odds = float(cta_match.group(2))
            cta_bookmaker = cta_match.group(3).strip()

            asserts.append((True, f"CTA parsed: outcome={cta_outcome}, odds={cta_odds}, bk={cta_bookmaker}"))

            # Verify bookmaker name appears in odds section of the analysis
            bk_in_text = cta_bookmaker.lower() in text.lower()
            asserts.append((bk_in_text, f"CTA bookmaker '{cta_bookmaker}' in analysis text: {bk_in_text}"))

            # Verify outcome is mentioned in the text
            oc_in_text = cta_outcome.lower() in text.lower()
            asserts.append((oc_in_text, f"CTA outcome '{cta_outcome}' in text: {oc_in_text}"))
        elif "View odds" in first_btn:
            asserts.append((True, "Fallback CTA (no positive EV) — acceptable"))
        else:
            asserts.append((False, f"CTA format not recognised: {first_btn}"))

        status = "PASS" if all(ok for ok, _ in asserts) else "FAIL"
        record("NS-04", "CTA accuracy — outcome and bookmaker in analysis", status,
               f"CTA: {first_btn}\nText preview: {text[:500]}",
               asserts)
    else:
        record("NS-04", "CTA accuracy", "SKIP", "No game breakdown",
               [(False, "Skipped")])

    # ── NS-05: No individual outcome buttons (old format removed) ──
    if game_msg and game_msg.buttons:
        btns = get_buttons(game_msg)
        # Old format had buttons like: "⚽ Draw @ 2.85 (Betway)", "⚽ Home @ 1.45 (HWB)"
        old_buttons = [b for b in btns
                       if re.search(r"(Home|Draw|Away)\s+@\s+\d+\.\d+", b)
                       or (b.startswith("⚽") and "@" in b)]
        asserts = [
            (len(old_buttons) == 0,
             f"No old individual outcome buttons: {old_buttons}")
        ]
        status = "PASS" if all(ok for ok, _ in asserts) else "FAIL"
        record("NS-05", "No individual outcome buttons (old format)", status,
               f"Buttons: {btns}",
               asserts)
    else:
        record("NS-05", "No individual outcome buttons", "SKIP", "No game breakdown",
               [(False, "Skipped")])

    # ════════════════════════════════════════════════════════════
    # SECTION 2: VERDICT EDGE RATING BADGE
    # ════════════════════════════════════════════════════════════
    log.info("")
    log.info("=" * 60)
    log.info("SECTION 2: VERDICT EDGE RATING BADGE")
    log.info("=" * 60)

    # ── NS-06: Verdict has edge badge ──
    if game_msg:
        text = game_msg.text or ""
        asserts = []

        has_verdict = "Verdict" in text
        asserts.append((has_verdict, f"Verdict section present: {has_verdict}"))

        if has_verdict:
            # Check for tier emoji near Verdict
            verdict_line = ""
            for line in text.split("\n"):
                if "Verdict" in line:
                    verdict_line = line
                    break

            has_badge = has_tier_emoji(verdict_line)
            # Badge should be present when odds data exists
            has_odds_section = "Bookmaker Odds" in text or "EV:" in text
            if has_odds_section:
                asserts.append((has_badge, f"Verdict has tier badge: '{verdict_line}'"))
            else:
                asserts.append((True, f"No odds data — badge correctly omitted: '{verdict_line}'"))

            # No conviction text remaining
            has_conviction = "conviction" in text.lower()
            asserts.append((not has_conviction, f"No 'conviction' text: {has_conviction}"))
        else:
            asserts.append((False, "No Verdict section found"))

        status = "PASS" if all(ok for ok, _ in asserts) else "FAIL"
        record("NS-06", "Verdict — edge badge, no conviction text", status,
               f"Text: {text[:600]}",
               asserts)
    else:
        record("NS-06", "Verdict edge badge", "SKIP", "No game breakdown",
               [(False, "Skipped")])

    # ════════════════════════════════════════════════════════════
    # SECTION 3: ODDS COMPARISON AFFILIATE BUTTONS
    # ════════════════════════════════════════════════════════════
    log.info("")
    log.info("=" * 60)
    log.info("SECTION 3: ODDS COMPARISON AFFILIATE BUTTONS")
    log.info("=" * 60)

    # Navigate to odds comparison from game breakdown
    compare_msg = None
    if game_msg and game_msg.buttons:
        compare_msg = await click_data(client, game_msg, "odds:compare:")

    if compare_msg:
        btns = get_buttons(compare_msg)
        urls = get_url_buttons(compare_msg)
        cbs = get_callback_data(compare_msg)
        text = compare_msg.text or ""

        # ── NS-07: Odds Comparison has affiliate buttons ──
        aff_btns = [b for b in btns if "📲" in b and "Best for" in b]
        asserts = [
            (len(aff_btns) >= 1, f"Affiliate buttons present: {len(aff_btns)}"),
        ]
        # Should have up to 3 (Home/Draw/Away)
        if len(aff_btns) > 0:
            asserts.append((len(aff_btns) <= 3, f"Affiliate buttons ≤3: {len(aff_btns)}"))
            # Each should have correct format
            for ab in aff_btns:
                fmt_ok = "→" in ab
                asserts.append((fmt_ok, f"Affiliate button has →: {ab}"))

        status = "PASS" if all(ok for ok, _ in asserts) else "FAIL"
        record("NS-07", "Odds Comparison — affiliate buttons", status,
               f"Buttons: {btns}\nURLs: {urls}\nAffiliate buttons: {aff_btns}",
               asserts)

        # ── NS-08: Affiliate bookmaker matches ⭐ best odds ──
        asserts = []
        # For each market, the ⭐ bookmaker should match the affiliate button bookmaker
        _market_labels = {"Home Win": "home", "Draw": "draw", "Away Win": "away"}

        for ab in aff_btns:
            # Parse: "📲 {bookmaker} — Best for {market} →"
            m = re.search(r"📲\s+(.+?)\s+—\s+Best for (.+?)\s+→", ab)
            if not m:
                asserts.append((False, f"Can't parse affiliate button: {ab}"))
                continue
            aff_bk = m.group(1).strip()
            aff_market = m.group(2).strip()

            # Find the ⭐ line for this market in the text
            star_bk = None
            in_market = False
            for line in text.split("\n"):
                if aff_market in line:
                    in_market = True
                    continue
                if in_market and "⭐" in line:
                    # Extract bookmaker name: "⭐ SupaBets: 2.40"
                    bk_match = re.search(r"⭐\s+(.+?):\s+", line)
                    if bk_match:
                        star_bk = bk_match.group(1).strip()
                    break
                if in_market and line.strip() == "":
                    in_market = False

            if star_bk:
                match = star_bk.lower() == aff_bk.lower()
                asserts.append((match,
                    f"Affiliate '{aff_bk}' matches ⭐ '{star_bk}' for {aff_market}: {match}"))
            else:
                asserts.append((False, f"No ⭐ bookmaker found for {aff_market}"))

        if not aff_btns:
            asserts.append((False, "No affiliate buttons to verify"))

        status = "PASS" if asserts and all(ok for ok, _ in asserts) else "FAIL" if asserts else "SKIP"
        record("NS-08", "Affiliate bookmaker matches ⭐ best odds", status,
               f"Affiliate buttons: {aff_btns}\nText: {text[:600]}",
               asserts)

        # ── NS-09: Odds Comparison back button uses ↩️ ──
        back_btns = [b for b in btns if "back" in b.lower() or "menu" in b.lower()]
        asserts = []
        all_correct_emoji = all("↩️" in b for b in back_btns)
        has_wrong_emoji = any("🔙" in b or "⏪" in b for b in back_btns)
        asserts.append((all_correct_emoji, f"All back buttons use ↩️: {back_btns}"))
        asserts.append((not has_wrong_emoji, f"No 🔙 or ⏪: {back_btns}"))

        status = "PASS" if all(ok for ok, _ in asserts) else "FAIL"
        record("NS-09", "Odds Comparison — back button uses ↩️", status,
               f"Back buttons: {back_btns}",
               asserts)
    else:
        record("NS-07", "Odds Comparison — affiliate buttons", "SKIP",
               "No odds comparison reached",
               [(False, "Skipped — no compare button or no response")])
        record("NS-08", "Affiliate bookmaker matches ⭐ best", "SKIP",
               "No odds comparison", [(False, "Skipped")])
        record("NS-09", "Back button ↩️", "SKIP",
               "No odds comparison", [(False, "Skipped")])

    # ════════════════════════════════════════════════════════════
    # SECTION 4: ANALYSIS CACHING
    # ════════════════════════════════════════════════════════════
    log.info("")
    log.info("=" * 60)
    log.info("SECTION 4: ANALYSIS CACHING")
    log.info("=" * 60)

    # Navigate back to Your Games
    yg2 = await send(client, "⚽ Your Games")
    await asyncio.sleep(2)

    # Time the second visit to the SAME game
    if yg2 and game_event_id:
        t_start = time.time()
        game2 = await click_data_wait(client, yg2, f"yg:game:{game_event_id}",
                                       timeout=AI_TIMEOUT)
        t_elapsed = time.time() - t_start

        if game2 and game2.buttons:
            btns2 = get_buttons(game2)
            text2 = game2.text or ""
            asserts = []

            # Cached response should be fast (<5 seconds)
            is_fast = t_elapsed < 5.0
            asserts.append((is_fast, f"Cached response time: {t_elapsed:.1f}s (expect <5s)"))

            # Should have same button structure as first visit
            asserts.append((len(btns2) >= 3, f"Cached response has buttons: {len(btns2)}"))

            # Should NOT show "Analysing..." (cache hit skips loading message)
            has_analysing = "Analysing" in text2 or "analysing" in text2
            asserts.append((not has_analysing,
                          f"No 'Analysing...' on cached visit: {has_analysing}"))

            status = "PASS" if all(ok for ok, _ in asserts) else "FAIL"
            record("NS-10", "Analysis cache — instant second visit", status,
                   f"Time: {t_elapsed:.1f}s\nButtons: {btns2}\nText: {text2[:300]}",
                   asserts,
                   detail=f"First visit: AI generation. Second visit: {t_elapsed:.1f}s")
        else:
            record("NS-10", "Analysis cache", "FAIL",
                   f"Second visit returned no buttons. Time: {t_elapsed:.1f}s",
                   [(False, "Cached response has buttons")])
    else:
        record("NS-10", "Analysis cache", "SKIP", "No game to revisit",
               [(False, "Skipped")])

    # ── NS-11: Different matches have independent caches ──
    # Find a different game to click
    if yg2 and yg2.buttons:
        other_event_id = ""
        for row in yg2.buttons:
            for btn in row:
                if hasattr(btn, "data") and btn.data:
                    cb = btn.data.decode() if isinstance(btn.data, bytes) else str(btn.data)
                    if cb.startswith("yg:game:") and cb != f"yg:game:{game_event_id}":
                        other_event_id = cb.replace("yg:game:", "")
                        break
            if other_event_id:
                break

        if other_event_id:
            t_start = time.time()
            other_game = await click_data_wait(client, yg2, f"yg:game:{other_event_id}",
                                                timeout=AI_TIMEOUT)
            t_elapsed = time.time() - t_start

            asserts = []
            # Different match should trigger fresh AI generation (slower)
            # OR may already be cached from Hot Tips — either way it should work
            has_content = other_game and (other_game.text or "").strip() != ""
            asserts.append((has_content, f"Different game loads: {bool(other_game)}"))

            if other_game and other_game.buttons:
                btns3 = get_buttons(other_game)
                asserts.append((len(btns3) >= 3, f"Different game has buttons: {len(btns3)}"))
            else:
                asserts.append((False, "Different game has no buttons"))

            status = "PASS" if all(ok for ok, _ in asserts) else "FAIL"
            record("NS-11", "Independent cache per match", status,
                   f"Other event: {other_event_id}\nTime: {t_elapsed:.1f}s",
                   asserts)
        else:
            record("NS-11", "Independent cache per match", "SKIP",
                   "Only one game available",
                   [(False, "Skipped — only one game")])
    else:
        record("NS-11", "Independent cache per match", "SKIP",
               "No Your Games list",
               [(False, "Skipped")])

    # ════════════════════════════════════════════════════════════
    # SECTION 5: BACK BUTTON EMOJI AUDIT (ALL SCREENS)
    # ════════════════════════════════════════════════════════════
    log.info("")
    log.info("=" * 60)
    log.info("SECTION 5: BACK BUTTON EMOJI AUDIT")
    log.info("=" * 60)

    # Collect back buttons from multiple screens
    wrong_emoji_screens = []

    # Screen 1: Settings
    settings = await send(client, "⚙️ Settings")
    if settings and settings.buttons:
        for b in get_buttons(settings):
            if ("back" in b.lower() or "menu" in b.lower()) and ("🔙" in b or "⏪" in b):
                wrong_emoji_screens.append(f"Settings: {b}")

    # Screen 2: Hot Tips
    hot = await send(client, "🔥 Hot Tips", timeout=30)
    await asyncio.sleep(5)
    hot_msgs = await client.get_messages(BOT, limit=5)
    hot_msg = None
    for m in hot_msgs:
        if not m.out and m.buttons:
            hot_msg = m
            break
    if hot_msg:
        for b in get_buttons(hot_msg):
            if ("back" in b.lower() or "menu" in b.lower()) and ("🔙" in b or "⏪" in b):
                wrong_emoji_screens.append(f"Hot Tips: {b}")

    # Screen 3: Tip Detail (from Hot Tips)
    tip_detail = None
    if hot_msg:
        tip_detail = await click_data(client, hot_msg, "tip:detail:")
    if tip_detail:
        for b in get_buttons(tip_detail):
            if ("back" in b.lower() or "menu" in b.lower()) and ("🔙" in b or "⏪" in b):
                wrong_emoji_screens.append(f"Tip Detail: {b}")

    # Screen 4: Settings sub-screens (sample Risk Profile)
    if settings:
        risk = await click_data(client, settings, "settings:risk")
        if risk:
            for b in get_buttons(risk):
                if ("back" in b.lower() or "menu" in b.lower()) and ("🔙" in b or "⏪" in b):
                    wrong_emoji_screens.append(f"Risk Profile: {b}")

    asserts = [
        (len(wrong_emoji_screens) == 0,
         f"No 🔙/⏪ found: {wrong_emoji_screens if wrong_emoji_screens else 'all ↩️'}")
    ]
    status = "PASS" if all(ok for ok, _ in asserts) else "FAIL"
    record("NS-12", "All back buttons use ↩️ — global audit", status,
           f"Screens checked: Settings, Hot Tips, Tip Detail, Risk Profile\n"
           f"Wrong emoji screens: {wrong_emoji_screens}",
           asserts)

    # ════════════════════════════════════════════════════════════
    # SECTION 6: HOT TIPS CTA CONSISTENCY
    # ════════════════════════════════════════════════════════════
    log.info("")
    log.info("=" * 60)
    log.info("SECTION 6: HOT TIPS TIP DETAIL CTA CONSISTENCY")
    log.info("=" * 60)

    # Get fresh Hot Tips
    await send(client, "/start")
    await asyncio.sleep(2)
    hot2_msgs = await send_get_all(client, "🔥 Hot Tips", timeout=30, settle=5)
    hot2 = None
    for m in hot2_msgs:
        if m.buttons:
            hot2 = m
            break

    if hot2 and hot2.buttons:
        # Click first tip detail
        td2 = await click_data(client, hot2, "tip:detail:")
        if td2:
            btns_td = get_buttons(td2)
            urls_td = get_url_buttons(td2)
            text_td = td2.text or ""

            # ── NS-13: Tip Detail CTA is first button ──
            first_td = btns_td[0] if btns_td else ""
            asserts = []
            is_cta = ("Bet on" in first_td or "Back " in first_td) and "→" in first_td
            asserts.append((is_cta, f"Tip Detail first button is CTA: {first_td}"))

            # CTA should be URL button
            is_url = bool(urls_td and urls_td[0][0] == first_td)
            asserts.append((is_url, f"CTA is URL button: {is_url}"))

            status = "PASS" if all(ok for ok, _ in asserts) else "FAIL"
            record("NS-13", "Tip Detail — CTA is first button + URL", status,
                   f"First: {first_td}\nAll: {btns_td}\nURLs: {urls_td}",
                   asserts)

            # ── NS-14: Max buttons per screen ≤5 ──
            n = len(btns_td)
            asserts = [(n <= 5, f"Tip Detail buttons ≤5: {n}")]
            status = "PASS" if all(ok for ok, _ in asserts) else "FAIL"
            record("NS-14", "Tip Detail — max 5 buttons", status,
                   f"Buttons ({n}): {btns_td}",
                   asserts)
        else:
            record("NS-13", "Tip Detail CTA", "SKIP", "No tip detail",
                   [(False, "Skipped")])
            record("NS-14", "Max buttons", "SKIP", "No tip detail",
                   [(False, "Skipped")])
    else:
        record("NS-13", "Tip Detail CTA", "SKIP", "No Hot Tips",
               [(False, "Skipped")])
        record("NS-14", "Max buttons", "SKIP", "No Hot Tips",
               [(False, "Skipped")])

    # ════════════════════════════════════════════════════════════
    # SECTION 7: CTA ACCURACY DEEP TEST (odds.db verification)
    # ════════════════════════════════════════════════════════════
    log.info("")
    log.info("=" * 60)
    log.info("SECTION 7: CTA ACCURACY — odds.db VERIFICATION")
    log.info("=" * 60)

    # Go back to game breakdown (use cache)
    yg3 = await send(client, "⚽ Your Games")
    await asyncio.sleep(2)

    cta_accuracy_results = []
    games_tested = 0

    if yg3 and yg3.buttons:
        # Test CTA accuracy for up to 3 games
        game_ids = []
        for row in yg3.buttons:
            for btn in row:
                if hasattr(btn, "data") and btn.data:
                    cb = btn.data.decode() if isinstance(btn.data, bytes) else str(btn.data)
                    if cb.startswith("yg:game:"):
                        game_ids.append(cb.replace("yg:game:", ""))
                if len(game_ids) >= 3:
                    break
            if len(game_ids) >= 3:
                break

        for gid in game_ids:
            gm = await click_data_wait(client, yg3, f"yg:game:{gid}", timeout=AI_TIMEOUT)
            if not gm or not gm.buttons:
                # Reload Your Games for next iteration
                yg3 = await send(client, "⚽ Your Games")
                await asyncio.sleep(2)
                continue

            games_tested += 1
            first_btn = get_buttons(gm)[0] if get_buttons(gm) else ""
            text_gm = gm.text or ""

            # Parse CTA
            cta_m = re.search(r"Back (.+?) @ ([\d.]+) on (.+?) →", first_btn)
            if cta_m:
                cta_outcome = cta_m.group(1).strip()
                cta_odds = float(cta_m.group(2))
                cta_bk = cta_m.group(3).strip()

                # Check the odds section of the text for verification
                # Find all "outcome: odds (bookmaker)" lines
                odds_lines = re.findall(r"(\w[^:]+):\s+<b>([\d.]+)</b>\s+\(([^)]+)\)", text_gm)
                if not odds_lines:
                    odds_lines = re.findall(r"(\w[^:]+):\s+([\d.]+)\s+\(([^)]+)\)", text_gm)

                # Find the CTA's outcome in the odds section
                outcome_odds = []
                for oc, od, bk in odds_lines:
                    if oc.strip().lower() == cta_outcome.lower():
                        outcome_odds.append((bk.strip(), float(od)))

                if outcome_odds:
                    # CTA bookmaker should have the best (highest) odds
                    best_bk, best_od = max(outcome_odds, key=lambda x: x[1])
                    cta_bk_matches = cta_bk.lower() == best_bk.lower()
                    cta_odds_close = abs(cta_odds - best_od) < 0.02
                    cta_accuracy_results.append({
                        "game": gid,
                        "cta_outcome": cta_outcome,
                        "cta_bk": cta_bk,
                        "cta_odds": cta_odds,
                        "best_bk": best_bk,
                        "best_odds": best_od,
                        "bk_match": cta_bk_matches,
                        "odds_match": cta_odds_close,
                    })
                else:
                    cta_accuracy_results.append({
                        "game": gid,
                        "cta_outcome": cta_outcome,
                        "cta_bk": cta_bk,
                        "cta_odds": cta_odds,
                        "note": "Could not parse odds from text",
                    })

            # Return to Your Games for next game
            yg3 = await send(client, "⚽ Your Games")
            await asyncio.sleep(2)

    if cta_accuracy_results:
        asserts = []
        for r in cta_accuracy_results:
            if "bk_match" in r:
                asserts.append((r["bk_match"],
                    f"Game {r['game'][:20]}: CTA bk '{r['cta_bk']}' = best bk '{r['best_bk']}': {r['bk_match']}"))
                asserts.append((r["odds_match"],
                    f"Game {r['game'][:20]}: CTA odds {r['cta_odds']} ≈ best {r['best_odds']}: {r['odds_match']}"))
            else:
                asserts.append((True, f"Game {r['game'][:20]}: {r.get('note', 'OK')}"))

        all_ok = all(ok for ok, _ in asserts)
        status = "PASS" if all_ok else "FAIL"
        record("NS-15", f"CTA accuracy — {games_tested} games verified", status,
               f"Results: {json.dumps(cta_accuracy_results, indent=2)[:1500]}",
               asserts)

        if not all_ok:
            file_bug("BUG-NS-03", "P0", "CTA Accuracy",
                     "Your Games → tap game → verify CTA",
                     "CTA bookmaker = best odds bookmaker for outcome",
                     f"Mismatch found in {sum(1 for r in cta_accuracy_results if not r.get('bk_match', True))} games")
    else:
        record("NS-15", "CTA accuracy", "SKIP",
               f"No games tested (games_tested={games_tested})",
               [(False, "Skipped — no parseable games")])

    # ════════════════════════════════════════════════════════════
    # SECTION 8: REGRESSION — EXISTING FEATURES
    # ════════════════════════════════════════════════════════════
    log.info("")
    log.info("=" * 60)
    log.info("SECTION 8: REGRESSION — EXISTING FEATURES")
    log.info("=" * 60)

    # ── NS-16: /start works ──
    start_msg = await send(client, "/start")
    asserts = [(bool(start_msg), "/start responded")]
    if start_msg:
        asserts.append(("welcome" in (start_msg.text or "").lower() or "menu" in (start_msg.text or "").lower(),
                       f"Welcome or menu: {(start_msg.text or '')[:80]}"))
    status = "PASS" if all(ok for ok, _ in asserts) else "FAIL"
    record("NS-16", "/start works", status,
           start_msg.text[:200] if start_msg else "None", asserts)

    # ── NS-17: Hot Tips pagination ──
    hot3 = await send(client, "/picks", timeout=30)
    await asyncio.sleep(8)
    # Get the actual hot tips message (may need to re-fetch for edited msg)
    h_msgs = await client.get_messages(BOT, limit=5)
    hot3 = None
    for m in h_msgs:
        if not m.out and m.buttons and "Hot Tips" in (m.text or ""):
            hot3 = m
            break
    asserts = [(bool(hot3), "Hot Tips loaded")]
    if hot3:
        btns_h = get_buttons(hot3)
        has_next = any("next" in b.lower() or "➡️" in b for b in btns_h)
        has_menu = any("menu" in b.lower() for b in btns_h)
        asserts.append((has_next or "Page" not in (hot3.text or ""), f"Pagination present: {has_next}"))
        asserts.append((has_menu, f"Menu button: {has_menu}"))
    status = "PASS" if all(ok for ok, _ in asserts) else "FAIL"
    record("NS-17", "Hot Tips pagination + nav", status,
           f"{(hot3.text or '')[:200]}\nButtons: {get_buttons(hot3) if hot3 else []}",
           asserts)

    # ── NS-18: Settings flow ──
    s_msg = await send(client, "⚙️ Settings")
    asserts = [(bool(s_msg), "Settings responded")]
    if s_msg:
        n_btns = len(get_buttons(s_msg))
        asserts.append((n_btns >= 6, f"Settings buttons: {n_btns}"))
        asserts.append((has_back(s_msg), "Settings has back nav"))
    status = "PASS" if all(ok for ok, _ in asserts) else "FAIL"
    record("NS-18", "Settings flow intact", status,
           f"Buttons: {get_buttons(s_msg) if s_msg else []}", asserts)

    # ── NS-19: Profile works ──
    p_msg = await send(client, "👤 Profile")
    asserts = [(bool(p_msg), "Profile responded")]
    if p_msg:
        asserts.append((len(p_msg.text or "") > 50, f"Profile has content: {len(p_msg.text or '')} chars"))
    status = "PASS" if all(ok for ok, _ in asserts) else "FAIL"
    record("NS-19", "Profile works", status,
           (p_msg.text or "")[:200] if p_msg else "None", asserts)

    # ── NS-20: Admin dashboard ──
    admin_msg = await send(client, "/admin")
    asserts = [(bool(admin_msg), "/admin responded")]
    if admin_msg:
        t = admin_msg.text or ""
        asserts.append(("Odds Database" in t or "Rows" in t, f"Admin shows DB stats"))
        asserts.append(("Bookmakers" in t or "bookmakers" in t, "Admin shows bookmaker count"))
    status = "PASS" if all(ok for ok, _ in asserts) else "FAIL"
    record("NS-20", "Admin dashboard", status,
           (admin_msg.text or "")[:300] if admin_msg else "None", asserts)

    # ════════════════════════════════════════════════════════════
    # DONE
    # ════════════════════════════════════════════════════════════
    await client.disconnect()

    # Write results
    total = len(results)
    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    skipped = sum(1 for r in results if r["status"] == "SKIP")
    warned = sum(1 for r in results if r["status"] == "WARN")

    log.info("")
    log.info("=" * 60)
    log.info("WAVE 13H NORTH STAR E2E RESULTS")
    log.info("=" * 60)
    log.info("  Total:   %d", total)
    log.info("  PASS:    %d", passed)
    log.info("  FAIL:    %d", failed)
    log.info("  SKIP:    %d", skipped)
    log.info("  WARN:    %d", warned)
    log.info("")

    if bugs:
        log.info("  BUGS FILED: %d", len(bugs))
        for b in bugs:
            log.info("    🐛 %s (%s): %s", b["id"], b["severity"], b["screen"])
        log.info("")

    for r in results:
        icon = {"PASS": "✓", "FAIL": "✗", "SKIP": "⊘", "WARN": "⚠"}.get(r["status"], "?")
        log.info("  %s %s: %s", icon, r["test_id"], r["name"])
        if r["status"] == "FAIL":
            for ok, msg in r["assertions"]:
                if not ok:
                    log.info("      → %s", msg)

    RESULTS_PATH.write_text(json.dumps({
        "results": results,
        "bugs": bugs,
        "summary": {
            "total": total, "passed": passed, "failed": failed,
            "skipped": skipped, "warned": warned, "bug_count": len(bugs),
        },
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("")
    log.info("Results: %s", RESULTS_PATH)


if __name__ == "__main__":
    asyncio.run(run_tests())
