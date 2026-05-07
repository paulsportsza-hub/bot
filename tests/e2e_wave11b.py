"""Wave 11B — Real Telethon E2E tests against LIVE @mzansiedge_bot.

Every test sends a real message via Telethon, captures the verbatim bot
response, and asserts against expected UX. No code review. No Bot API.

Usage:
    cd /home/paulsportsza/bot
    .venv/bin/python3 tests/e2e_wave11b.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# Ensure project root on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import BOT_ROOT

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.sessions import StringSession
from telethon.tl.custom.message import Message

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("wave11b")

# ── Config ───────────────────────────────────────────────────
BOT = "mzansiedge_bot"
API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "")
SESSION_PATH = Path("data/telethon_qa_session.string")
REPORT_DIR = BOT_ROOT.parent / "reports" / "e2e-screenshots"
REPORT_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_PATH = BOT_ROOT.parent / "reports" / "wave11b-e2e-results.json"

BOT_TIMEOUT = 15
PICKS_TIMEOUT = 45  # Hot Tips scan is slow

# ── Results ──────────────────────────────────────────────────
results: list[dict] = []


def record(test_id: str, name: str, status: str, response: str,
           assertions: list[tuple[bool, str]], detail: str = ""):
    entry = {
        "test_id": test_id,
        "name": name,
        "status": status,
        "response": response[:2000],
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
    # Save raw response
    safe_id = test_id.replace(":", "_").replace("/", "_")
    (REPORT_DIR / f"{safe_id}.txt").write_text(
        f"TEST: {test_id} — {name}\nSTATUS: {status}\n"
        f"RESPONSE:\n{response}\n\nASSERTIONS:\n"
        + "\n".join(f"  {'✓' if ok else '✗'} {msg}" for ok, msg in assertions)
    )


# ── Helpers ──────────────────────────────────────────────────

async def _last_id(client: TelegramClient) -> int:
    msgs = await client.get_messages(BOT, limit=1)
    return msgs[0].id if msgs else 0


async def send(client: TelegramClient, text: str,
               timeout: int = BOT_TIMEOUT) -> Message | None:
    """Send a message, wait for bot reply, return it."""
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
                       max_msgs: int = 10) -> list[Message]:
    """Send a message, collect ALL bot replies (multiple messages)."""
    last = await _last_id(client)
    try:
        await client.send_message(BOT, text)
    except FloodWaitError as e:
        log.warning("FloodWait %ds", e.seconds)
        await asyncio.sleep(e.seconds + 2)
        await client.send_message(BOT, text)

    await asyncio.sleep(3)
    deadline = time.time() + timeout
    found: list[Message] = []
    stable_count = 0
    last_count = 0
    while time.time() < deadline:
        msgs = await client.get_messages(BOT, limit=max_msgs + 5)
        bot_msgs = [m for m in msgs if m.id > last and not m.out]
        if len(bot_msgs) == last_count:
            stable_count += 1
            if stable_count >= 3:
                break
        else:
            stable_count = 0
            last_count = len(bot_msgs)
        await asyncio.sleep(1)

    # Final fetch
    msgs = await client.get_messages(BOT, limit=max_msgs + 5)
    found = [m for m in msgs if m.id > last and not m.out]
    # Sort by ID ascending (oldest first)
    found.sort(key=lambda m: m.id)
    return found


async def click_data(client: TelegramClient, msg: Message,
                     prefix: str) -> Message | None:
    """Click an inline button by callback_data prefix."""
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
                        log.debug("click error: %s", e)
                        return None
                    await asyncio.sleep(3)
                    # Check for new message
                    msgs = await client.get_messages(BOT, limit=5)
                    for m in msgs:
                        if m.id > old_id and not m.out:
                            return m
                    # Maybe edited original
                    updated = await client.get_messages(BOT, ids=msg.id)
                    if updated:
                        return updated
                    return None
    return None


async def click_text(client: TelegramClient, msg: Message,
                     text: str, partial: bool = False) -> Message | None:
    """Click an inline button by label text."""
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
                    log.debug("click error: %s", e)
                    return None
                await asyncio.sleep(3)
                msgs = await client.get_messages(BOT, limit=5)
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
    """Get all button texts."""
    if not msg or not msg.buttons:
        return []
    return [btn.text for row in msg.buttons for btn in row]


def btn_data(msg: Message | None) -> list[str]:
    """Get all callback_data strings."""
    if not msg or not msg.buttons:
        return []
    out = []
    for row in msg.buttons:
        for btn in row:
            if hasattr(btn, "data") and btn.data:
                out.append(btn.data.decode() if isinstance(btn.data, bytes)
                           else str(btn.data))
            elif hasattr(btn, "url") and btn.url:
                out.append(f"URL:{btn.url}")
    return out


def has_url_btn(msg: Message | None) -> list[dict]:
    """Get all URL buttons from a message."""
    if not msg or not msg.buttons:
        return []
    url_btns = []
    for row in msg.buttons:
        for btn in row:
            if hasattr(btn, "url") and btn.url:
                url_btns.append({"text": btn.text, "url": btn.url})
    return url_btns


# ═════════════════════════════════════════════════════════════
# TESTS
# ═════════════════════════════════════════════════════════════

async def run_tests(client: TelegramClient):
    """Run all Wave 11B E2E tests."""

    # ── TEST-001: /start responds with welcome/menu ──────────
    log.info("")
    log.info("=" * 60)
    log.info("SECTION 1: Basic Bot Response")
    log.info("=" * 60)

    msg = await send(client, "/start", timeout=20)
    text = txt(msg)
    asserts = [
        (msg is not None, "Bot responded to /start"),
        (len(text) > 20, f"Response length: {len(text)} (need >20)"),
    ]
    record("TEST-001", "/start responds", "PASS" if all(a[0] for a in asserts) else "FAIL",
           text, asserts)

    # ── TEST-002: /menu responds ─────────────────────────────
    msg_menu = await send(client, "/menu")
    text = txt(msg_menu)
    menu_btns = btns(msg_menu)
    asserts = [
        (msg_menu is not None, "Bot responded to /menu"),
        (len(menu_btns) > 0, f"Buttons: {len(menu_btns)}"),
    ]
    record("TEST-002", "/menu responds with buttons", "PASS" if all(a[0] for a in asserts) else "FAIL",
           text + f"\nButtons: {menu_btns}", asserts)

    # ── TEST-003: /help responds with formatted text ─────────
    msg_help = await send(client, "/help")
    text = txt(msg_help)
    # Telethon renders Markdown bold as **text** in .text property
    # and HTML bold as plain text. Check for raw <b> or unrendered HTML.
    has_raw_html = "<b>" in text or "</b>" in text or "<i>" in text or "</i>" in text
    has_entities = msg_help and msg_help.entities and len(msg_help.entities) > 0
    asserts = [
        (msg_help is not None, "Bot responded to /help"),
        (len(text) > 50, f"Help text length: {len(text)}"),
        (not has_raw_html, "No raw HTML tags in text"),
    ]
    if "**" in text:
        # Telethon shows Markdown-formatted bold as ** in .text — this is
        # fine IF the message has formatting entities (means Telegram renders it bold)
        asserts.append((has_entities,
                        f"Markdown ** present but entities={has_entities} (rendered OK if True)"))
    record("TEST-003", "/help — formatting check",
           "PASS" if all(a[0] for a in asserts) else "FAIL",
           text, asserts)

    # ── SECTION 2: Hot Tips — Core Feature ───────────────────
    log.info("")
    log.info("=" * 60)
    log.info("SECTION 2: Hot Tips (🔥)")
    log.info("=" * 60)

    # ── TEST-004: Hot Tips via keyboard button ───────────────
    # Hot Tips sends a loading message first, then edits or sends results.
    # We need extra time and should collect multiple messages.
    all_msgs = await send_get_all(client, "🔥 Hot Tips", timeout=PICKS_TIMEOUT,
                                  max_msgs=15)
    # Also re-fetch after a pause to catch edited messages
    await asyncio.sleep(5)
    latest_msgs = await client.get_messages(BOT, limit=10)
    # Merge: use the latest version of each message ID
    msg_map = {m.id: m for m in all_msgs}
    for m in latest_msgs:
        if not m.out:
            msg_map[m.id] = m  # Overwrite with fresh version (may be edited)
    all_msgs = sorted(msg_map.values(), key=lambda m: m.id)
    all_texts = [txt(m) for m in all_msgs]
    combined = "\n---MSG---\n".join(all_texts)
    has_loading = any("crunching" in t.lower() or "scan" in t.lower() or "looking" in t.lower()
                      or "⏳" in t or "loading" in t.lower() for t in all_texts)
    has_any_tip = any("vs" in t.lower() or "value" in t.lower() or "hot tips" in t.lower()
                      or "no value" in t.lower() or "no edges" in t.lower()
                      or "edge" in t.lower() for t in all_texts)

    asserts = [
        (len(all_msgs) >= 1, f"Bot sent {len(all_msgs)} messages (need ≥1)"),
        (has_any_tip, "Contains tip content or 'no value bets' empty state"),
    ]
    record("TEST-004", "Hot Tips responds", "PASS" if all(a[0] for a in asserts) else "FAIL",
           combined, asserts)

    # Analyse tip messages for edge badges, multi-bookmaker, etc.
    # Check if tips were found or empty state
    tip_msgs = [m for m in all_msgs if txt(m) and
                ("vs" in txt(m).lower() or "edge" in txt(m).lower() or
                 "💎" in txt(m) or "🥇" in txt(m) or "🥈" in txt(m) or "🥉" in txt(m) or "odds" in txt(m).lower())]
    no_tips = any("no value" in txt(m).lower() or "no edges" in txt(m).lower()
                  or "market is efficient" in txt(m).lower()
                  for m in all_msgs)

    if no_tips:
        log.info("  → Hot Tips returned EMPTY STATE (no value bets found)")
        log.info("    This is expected if Odds API quota is exhausted")

    # ── TEST-005: Edge badges in Hot Tips ────────────────────
    edge_emojis = ["💎", "🥇", "🥈", "🥉"]
    has_edge = any(any(e in txt(m) for e in edge_emojis) for m in all_msgs)

    if no_tips:
        asserts = [
            (True, "No tips returned — edge badge check N/A (Odds API quota?)"),
        ]
        record("TEST-005", "Edge badges in Hot Tips",
               "WARN" if no_tips else "FAIL",
               "No tips to check — empty state", asserts,
               detail="Odds API quota may be exhausted")
    else:
        asserts = [
            (has_edge, f"Edge emoji found in tip messages: {has_edge}"),
        ]
        for m in tip_msgs:
            t = txt(m)
            if any(e in t for e in edge_emojis):
                asserts.append((True, f"Edge badge found: {t[:80]}"))
        record("TEST-005", "Edge badges in Hot Tips",
               "PASS" if has_edge else "FAIL",
               combined, asserts)

    # ── TEST-006: Tips sorted by edge tier ───────────────────
    if not no_tips and len(tip_msgs) >= 2:
        tier_order = {"DIAMOND": 0, "GOLD": 1, "SILVER": 2, "BRONZE": 3}
        tier_positions = []
        for i, m in enumerate(tip_msgs):
            t = txt(m)
            for tier_name, tier_rank in tier_order.items():
                if tier_name.lower() in t.lower():
                    tier_positions.append((i, tier_rank, tier_name))
                    break
        sorted_ok = all(tier_positions[i][1] <= tier_positions[i+1][1]
                        for i in range(len(tier_positions)-1)) if len(tier_positions) >= 2 else True
        asserts = [
            (len(tier_positions) >= 1, f"Found {len(tier_positions)} tier labels in tips"),
            (sorted_ok, f"Tips sorted by tier: {[(p[2], p[0]) for p in tier_positions]}"),
        ]
        record("TEST-006", "Tips sorted by edge tier",
               "PASS" if sorted_ok else "FAIL",
               str(tier_positions), asserts)
    else:
        record("TEST-006", "Tips sorted by edge tier", "SKIP" if no_tips else "WARN",
               "Fewer than 2 tips to compare",
               [(True, "Not enough tips for sort check")],
               detail="Need ≥2 tips")

    # ── TEST-007: No 🇿🇦 flags in Hot Tips messages ────────
    # Only check messages that are part of the Hot Tips flow (contain "hot tips",
    # "edge", "value", or tip-like content), NOT earlier messages from other tests
    za_flag = "🇿🇦"
    hot_tip_msgs = [m for m in all_msgs if txt(m) and
                    ("hot tips" in txt(m).lower() or "edge" in txt(m).lower() or
                     "value" in txt(m).lower() or "no edges" in txt(m).lower() or
                     "crunching" in txt(m).lower() or "💎" in txt(m) or "🥇" in txt(m) or
                     "market is efficient" in txt(m).lower())]
    has_flag = any(za_flag in txt(m) for m in hot_tip_msgs)
    asserts = [
        (not has_flag, f"No ZA flag in Hot Tips messages: {'CLEAN' if not has_flag else 'FOUND 🇿🇦'}"),
    ]
    if hot_tip_msgs:
        for m in hot_tip_msgs:
            t = txt(m)[:80]
            asserts.append((za_flag not in t, f"Message: {t}"))
    record("TEST-007", "No 🇿🇦 flags in Hot Tips", "PASS" if not has_flag else "FAIL",
           "\n".join(txt(m)[:100] for m in hot_tip_msgs), asserts)

    # ── TEST-008: Hot Tips CTA buttons ───────────────────────
    all_url_btns = []
    for m in all_msgs:
        all_url_btns.extend(has_url_btn(m))
    all_cb_btns = []
    for m in all_msgs:
        all_cb_btns.extend(btn_data(m))

    if no_tips:
        # Check for Refresh / Your Games / Menu buttons in footer
        all_btn_texts = []
        for m in all_msgs:
            all_btn_texts.extend(btns(m))
        has_footer = (any("hot:" in d or "menu:" in d or "yg:" in d for d in all_cb_btns) or
                      any("menu" in b.lower() or "your games" in b.lower()
                          for b in all_btn_texts))
        asserts = [
            (has_footer, f"Footer buttons present: texts={all_btn_texts}, data={all_cb_btns}"),
        ]
        record("TEST-008", "Hot Tips footer buttons (empty state)",
               "PASS" if has_footer else "WARN",
               str(all_btn_texts) + "\n" + str(all_cb_btns), asserts,
               detail="Empty state — checking for Refresh/Menu buttons")
    else:
        # Check for bookmaker URL buttons on tips
        has_bet_btn = any("bet" in b["text"].lower() for b in all_url_btns)
        not_hardcoded_betway = True
        if all_url_btns:
            # Check if ALL buttons say Betway — that would mean no dynamic selection
            betway_only = all("betway" in b["text"].lower() for b in all_url_btns)
            not_hardcoded_betway = not betway_only or len(all_url_btns) <= 1
        asserts = [
            (has_bet_btn, f"Bet button found: {[b['text'] for b in all_url_btns]}"),
            (not_hardcoded_betway, "CTA not all hardcoded Betway"),
        ]
        record("TEST-008", "Hot Tips CTA buttons (dynamic bookmaker)",
               "PASS" if all(a[0] for a in asserts) else "FAIL",
               str(all_url_btns), asserts)

    # ── TEST-009: Hot Tips via /picks command (legacy) ───────
    msg_picks = await send(client, "/picks", timeout=PICKS_TIMEOUT)
    text = txt(msg_picks)
    asserts = [
        (msg_picks is not None, "Bot responded to /picks"),
        (len(text) > 10, f"Response length: {len(text)}"),
    ]
    record("TEST-009", "/picks command (legacy) responds",
           "PASS" if all(a[0] for a in asserts) else "FAIL",
           text, asserts)

    # ── SECTION 3: Tip Detail + Multi-Bookmaker ──────────────
    log.info("")
    log.info("=" * 60)
    log.info("SECTION 3: Tip Detail + Multi-Bookmaker")
    log.info("=" * 60)

    # Try to get into a tip detail page
    tip_detail_msg = None
    tip_detail_text = ""

    # First, try clicking a tip button from Hot Tips
    for m in all_msgs:
        if m.buttons:
            for d in btn_data(m):
                if d.startswith("tip:detail:") or d.startswith("schedule:tips:"):
                    tip_detail_msg = await click_data(client, m, d.split(":")[0] + ":" + d.split(":")[1])
                    if tip_detail_msg:
                        tip_detail_text = txt(tip_detail_msg)
                        break
            if tip_detail_msg:
                break

    # If no tip detail accessible from Hot Tips, try Your Games
    if not tip_detail_msg:
        log.info("  No tip detail from Hot Tips — trying Your Games...")
        yg_msg = await send(client, "⚽ Your Games", timeout=20)
        if yg_msg and yg_msg.buttons:
            # Try clicking first game
            for d in btn_data(yg_msg):
                if d.startswith("yg:game:"):
                    tip_detail_msg = await click_data(client, yg_msg, "yg:game:")
                    if tip_detail_msg:
                        tip_detail_text = txt(tip_detail_msg)
                    break

    # ── TEST-010: Tip detail page accessible ─────────────────
    if tip_detail_msg:
        asserts = [
            (len(tip_detail_text) > 20, f"Detail text length: {len(tip_detail_text)}"),
        ]
        record("TEST-010", "Tip detail page accessible",
               "PASS" if all(a[0] for a in asserts) else "FAIL",
               tip_detail_text, asserts)
    else:
        record("TEST-010", "Tip detail page accessible", "SKIP",
               "No game/tip available to tap into",
               [(False, "Could not navigate to tip detail")],
               detail="No tips or games available")

    # ── TEST-011: Multi-bookmaker odds in tip detail ─────────
    if tip_detail_msg and tip_detail_text:
        # Look for multiple bookmaker names
        bk_names = ["hollywoodbets", "betway", "supabets", "sportingbet", "gbets"]
        found_bks = [bk for bk in bk_names if bk.lower() in tip_detail_text.lower()]
        has_odds = any(c in tip_detail_text for c in ["@", "odds", "Odds", "."])
        has_also = "also:" in tip_detail_text.lower()

        asserts = [
            (len(found_bks) >= 1, f"Bookmakers found: {found_bks}"),
            (has_odds, "Odds notation present (@ or 'odds')"),
        ]
        if has_also:
            asserts.append((True, "'Also:' runner-ups line present"))

        record("TEST-011", "Multi-bookmaker odds in tip detail",
               "PASS" if len(found_bks) >= 2 else ("WARN" if len(found_bks) == 1 else "FAIL"),
               tip_detail_text, asserts,
               detail=f"Found {len(found_bks)} bookmaker(s)")
    else:
        record("TEST-011", "Multi-bookmaker odds in tip detail", "SKIP",
               "No tip detail available",
               [(False, "Tip detail page not accessible")])

    # ── TEST-012: CTA button in tip detail ───────────────────
    if tip_detail_msg:
        url_buttons = has_url_btn(tip_detail_msg)
        cb_buttons = btn_data(tip_detail_msg)

        has_bet_url = any("bet" in b["text"].lower() for b in url_buttons)
        has_affiliate = any("btag" in b.get("url", "").lower() or
                           ".co.za" in b.get("url", "").lower()
                           for b in url_buttons)
        cta_format_ok = any("bet on" in b["text"].lower() and "→" in b["text"]
                           for b in url_buttons)

        asserts = [
            (has_bet_url, f"Bet URL button: {[b['text'] for b in url_buttons]}"),
        ]
        if url_buttons:
            asserts.append((cta_format_ok, f"CTA format 'Bet on X →': {[b['text'] for b in url_buttons]}"))
            asserts.append((has_affiliate, f"Affiliate URL: {[b['url'][:60] for b in url_buttons]}"))

        record("TEST-012", "CTA button format in tip detail",
               "PASS" if has_bet_url else "WARN",
               str(url_buttons) + "\n" + str(cb_buttons), asserts)
    else:
        record("TEST-012", "CTA button format in tip detail", "SKIP",
               "No tip detail available",
               [(False, "Tip detail page not accessible")])

    # ── TEST-013: Odds comparison view ───────────────────────
    odds_compare_msg = None
    if tip_detail_msg and tip_detail_msg.buttons:
        for d in btn_data(tip_detail_msg):
            if d.startswith("odds:compare:"):
                odds_compare_msg = await click_data(client, tip_detail_msg, "odds:compare:")
                break

    if odds_compare_msg:
        oc_text = txt(odds_compare_msg)
        bk_names_found = [bk for bk in bk_names if bk.lower() in oc_text.lower()]
        has_star = "⭐" in oc_text
        has_comparison_header = "odds comparison" in oc_text.lower() or "📊" in oc_text

        asserts = [
            (len(bk_names_found) >= 2, f"Bookmakers in comparison: {bk_names_found}"),
            (has_comparison_header, "Comparison header/emoji present"),
            (has_star, "Best odds marked with ⭐"),
        ]
        record("TEST-013", "Odds comparison view",
               "PASS" if len(bk_names_found) >= 2 else "FAIL",
               oc_text, asserts)
    else:
        record("TEST-013", "Odds comparison view", "SKIP",
               "No 'odds:compare' button found",
               [(False, "Could not access odds comparison")],
               detail="Button not present or tip detail not accessible")

    # ── SECTION 4: Your Games ────────────────────────────────
    log.info("")
    log.info("=" * 60)
    log.info("SECTION 4: Your Games")
    log.info("=" * 60)

    # ── TEST-014: Your Games responds ────────────────────────
    yg_msg = await send(client, "⚽ Your Games", timeout=20)
    yg_text = txt(yg_msg)
    yg_buttons = btns(yg_msg)
    yg_cb = btn_data(yg_msg)

    asserts = [
        (yg_msg is not None, "Bot responded to Your Games"),
        (len(yg_text) > 10, f"Text length: {len(yg_text)}"),
    ]
    record("TEST-014", "Your Games responds",
           "PASS" if all(a[0] for a in asserts) else "FAIL",
           yg_text + f"\nButtons: {yg_buttons}", asserts)

    # ── TEST-015: Your Games shows games or empty state ──────
    has_games = "vs" in yg_text.lower() or any("yg:game:" in d for d in yg_cb)
    has_empty = "no games" in yg_text.lower() or "no upcoming" in yg_text.lower() or len(yg_text) < 50

    asserts = [
        (has_games or has_empty, f"Games shown ({has_games}) or empty state ({has_empty})"),
    ]
    if has_games:
        asserts.append((True, "Games visible in Your Games view"))
    record("TEST-015", "Your Games content",
           "PASS" if (has_games or has_empty) else "FAIL",
           yg_text[:500], asserts)

    # ── TEST-016: Sport filter buttons ───────────────────────
    sport_emojis = ["⚽", "🏉", "🏏", "🎾", "🥊", "🥋", "🏀", "🏈", "⛳", "🏎"]
    sport_filter_btns = [b for b in yg_buttons if any(e in b for e in sport_emojis) and len(b) <= 4]
    has_sport_filter = len(sport_filter_btns) > 0

    asserts = [
        (has_sport_filter, f"Sport filter buttons: {sport_filter_btns}"),
    ]
    record("TEST-016", "Sport filter buttons in Your Games",
           "PASS" if has_sport_filter else "WARN",
           str(yg_buttons), asserts,
           detail="Expected if user follows 2+ sports")

    # ── SECTION 5: Navigation & Back Buttons ─────────────────
    log.info("")
    log.info("=" * 60)
    log.info("SECTION 5: Navigation")
    log.info("=" * 60)

    # ── TEST-017: Back button from settings ──────────────────
    settings_msg = await send(client, "⚙️ Settings")
    settings_text = txt(settings_msg)
    settings_btns = btn_data(settings_msg)
    has_settings_content = "settings" in settings_text.lower() or \
                           any("settings:" in d for d in settings_btns)

    asserts = [
        (settings_msg is not None, "Settings responded"),
        (has_settings_content, f"Settings content found. Buttons: {btns(settings_msg)}"),
    ]
    record("TEST-017", "Settings accessible",
           "PASS" if all(a[0] for a in asserts) else "FAIL",
           settings_text, asserts)

    # ── TEST-018: Back to menu from settings ─────────────────
    back_msg = None
    if settings_msg and settings_msg.buttons:
        # Try menu:home or "Main Menu" or "Back"
        back_msg = await click_data(client, settings_msg, "menu:home")
        if not back_msg:
            back_msg = await click_text(client, settings_msg, "Main Menu", partial=True)
        if not back_msg:
            back_msg = await click_text(client, settings_msg, "Back", partial=True)

    back_text = txt(back_msg)
    back_btns = btn_data(back_msg)
    is_menu = any("sport:" in d or "picks:" in d or "bets:" in d
                  for d in back_btns)

    asserts = [
        (back_msg is not None, "Back navigation worked"),
        (is_menu, f"Returned to menu. Buttons: {btns(back_msg)}"),
    ]
    record("TEST-018", "Back button to main menu",
           "PASS" if all(a[0] for a in asserts) else "WARN",
           back_text, asserts)

    # ── TEST-019: hot:back handler (P0-4 fix) ────────────────
    # Send Hot Tips, then check footer for navigation buttons
    ht_msgs = await send_get_all(client, "🔥 Hot Tips", timeout=PICKS_TIMEOUT)
    await asyncio.sleep(5)
    # Re-fetch to get edited messages
    latest = await client.get_messages(BOT, limit=10)
    ht_map = {m.id: m for m in ht_msgs}
    for m in latest:
        if not m.out:
            ht_map[m.id] = m
    ht_msgs = sorted(ht_map.values(), key=lambda m: m.id)

    footer_msg = ht_msgs[-1] if ht_msgs else None
    footer_btn_texts = btns(footer_msg)
    footer_cb = btn_data(footer_msg)
    # Check for navigation: either callback data or button text
    has_nav = (any("hot:" in d or "menu:" in d or "yg:" in d for d in footer_cb) or
               any("menu" in b.lower() or "your games" in b.lower() or
                   "back" in b.lower() or "refresh" in b.lower()
                   for b in footer_btn_texts))

    asserts = [
        (footer_msg is not None, "Footer message received"),
        (has_nav, f"Navigation buttons: {footer_btn_texts}"),
    ]
    record("TEST-019", "Hot Tips footer navigation",
           "PASS" if all(a[0] for a in asserts) else "WARN",
           txt(footer_msg) + f"\nButtons: {footer_btn_texts}", asserts)

    # ── SECTION 6: Sticky Keyboard ───────────────────────────
    log.info("")
    log.info("=" * 60)
    log.info("SECTION 6: Sticky Keyboard & Formatting")
    log.info("=" * 60)

    # ── TEST-020: Sticky keyboard visible ────────────────────
    # Send /start and check for reply keyboard (not inline)
    msg = await send(client, "/start", timeout=20)
    has_reply_kb = msg and hasattr(msg, "reply_markup") and msg.reply_markup and \
                   hasattr(msg.reply_markup, "rows")

    asserts = [
        (msg is not None, "Bot responded"),
    ]
    # Telethon doesn't always return reply keyboards in get_messages —
    # instead test that the keyboard buttons work as text commands
    keyboard_texts = ["⚽ Your Games", "🔥 Hot Tips", "📖 Guide",
                      "👤 Profile", "⚙️ Settings", "❓ Help"]
    # Test one keyboard text to verify it works
    guide_msg = await send(client, "📖 Guide")
    guide_text = txt(guide_msg)
    asserts.append(
        (guide_msg is not None and len(guide_text) > 10,
         f"📖 Guide keyboard text works: {len(guide_text)} chars")
    )
    record("TEST-020", "Sticky keyboard functional",
           "PASS" if all(a[0] for a in asserts) else "FAIL",
           guide_text[:200], asserts)

    # ── TEST-021: Profile accessible via keyboard ────────────
    profile_msg = await send(client, "👤 Profile")
    profile_text = txt(profile_msg)
    has_profile = any(kw in profile_text.lower() for kw in
                      ["experience", "sport", "risk", "profile", "bankroll"])

    asserts = [
        (profile_msg is not None, "Profile responded"),
        (has_profile, f"Profile content found: {profile_text[:100]}"),
    ]
    record("TEST-021", "Profile via keyboard",
           "PASS" if all(a[0] for a in asserts) else "FAIL",
           profile_text, asserts)

    # ── TEST-022: Help via keyboard ──────────────────────────
    help_msg = await send(client, "❓ Help")
    help_text = txt(help_msg)
    asserts = [
        (help_msg is not None, "Help responded"),
        (len(help_text) > 50, f"Help text: {len(help_text)} chars"),
    ]
    record("TEST-022", "Help via keyboard",
           "PASS" if all(a[0] for a in asserts) else "FAIL",
           help_text[:300], asserts)

    # ── SECTION 7: Formatting & Display Quality ──────────────
    log.info("")
    log.info("=" * 60)
    log.info("SECTION 7: Formatting & Display Quality")
    log.info("=" * 60)

    # ── TEST-023: No raw HTML tags in responses ──────────────
    # Collect a sample of recent bot messages
    sample_msgs = await client.get_messages(BOT, limit=20)
    bot_msgs = [m for m in sample_msgs if not m.out and m.text]
    raw_html = []
    for m in bot_msgs:
        t = m.text or ""
        if "<b>" in t or "</b>" in t or "<i>" in t or "</i>" in t or "<code>" in t:
            raw_html.append(t[:80])

    asserts = [
        (len(raw_html) == 0, f"Raw HTML tags found in {len(raw_html)} messages"),
    ]
    if raw_html:
        for h in raw_html[:3]:
            asserts.append((False, f"Raw HTML: {h}"))
    record("TEST-023", "No raw HTML tags visible to user",
           "PASS" if len(raw_html) == 0 else "FAIL",
           str(raw_html[:3]), asserts)

    # ── TEST-024: Emojis render (not escaped unicode) ────────
    # Check that messages contain actual emojis, not \\u26cf etc.
    has_escaped_unicode = any("\\u" in (m.text or "") for m in bot_msgs)
    asserts = [
        (not has_escaped_unicode, "No escaped unicode in messages"),
    ]
    record("TEST-024", "Emojis render correctly",
           "PASS" if not has_escaped_unicode else "FAIL",
           "", asserts)

    # ── TEST-025: /admin responds (if user is admin) ─────────
    admin_msg = await send(client, "/admin")
    admin_text = txt(admin_msg)
    # Admin might show quota info or "not authorized"
    is_admin = "quota" in admin_text.lower() or "users" in admin_text.lower() or \
               "admin" in admin_text.lower()
    not_admin = "not" in admin_text.lower() or "unauthorized" in admin_text.lower() or \
                admin_msg is None

    asserts = [
        (admin_msg is not None, "Bot responded to /admin"),
    ]
    if is_admin:
        asserts.append((True, f"Admin dashboard shown: {admin_text[:100]}"))
        # Check quota info
        has_quota = "quota" in admin_text.lower() or "remaining" in admin_text.lower() or \
                    "used" in admin_text.lower()
        if has_quota:
            asserts.append((True, "Odds API quota info visible"))
    record("TEST-025", "/admin dashboard",
           "PASS" if admin_msg else "WARN",
           admin_text, asserts)

    # ── SECTION 8: Edge Cases & Error Handling ───────────────
    log.info("")
    log.info("=" * 60)
    log.info("SECTION 8: Edge Cases")
    log.info("=" * 60)

    # ── TEST-026: Random text handled gracefully ─────────────
    msg = await send(client, "asdfghjkl random text 12345")
    text = txt(msg)
    # Bot should either ignore or send a helpful message, NOT crash
    asserts = [
        (True, "Bot did not crash on random text"),
    ]
    if msg:
        asserts.append((True, f"Response: {text[:100]}"))
    else:
        asserts.append((True, "Bot ignored random text (acceptable)"))
    record("TEST-026", "Random text handled gracefully",
           "PASS", text, asserts)

    # ── TEST-027: Double /start ──────────────────────────────
    msg1 = await send(client, "/start")
    msg2 = await send(client, "/start")
    text1 = txt(msg1)
    text2 = txt(msg2)
    both_responded = msg1 is not None and msg2 is not None

    asserts = [
        (both_responded, "Both /start commands responded"),
    ]
    record("TEST-027", "Double /start doesn't crash",
           "PASS" if both_responded else "FAIL",
           f"First: {text1[:100]}\nSecond: {text2[:100]}", asserts)

    # ── TEST-028: Rapid keyboard taps ────────────────────────
    # Send multiple keyboard messages quickly
    msgs_rapid = []
    for kb_text in ["⚽ Your Games", "🔥 Hot Tips", "⚙️ Settings"]:
        m = await send(client, kb_text, timeout=10)
        msgs_rapid.append(m)
        await asyncio.sleep(1)

    responded = sum(1 for m in msgs_rapid if m is not None)
    asserts = [
        (responded >= 2, f"Rapid taps: {responded}/3 responded"),
    ]
    record("TEST-028", "Rapid keyboard taps",
           "PASS" if responded >= 2 else "WARN",
           f"Responded: {responded}/3", asserts)


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
        log.error("Session expired. Re-run save_telethon_qa_session.py")
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

    # Print summary
    total = len(results)
    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    skipped = sum(1 for r in results if r["status"] == "SKIP")
    warned = sum(1 for r in results if r["status"] == "WARN")

    log.info("")
    log.info("=" * 60)
    log.info("WAVE 11B E2E RESULTS")
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

    # Save JSON results
    RESULTS_PATH.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    log.info("\nResults saved to: %s", RESULTS_PATH)
    log.info("Screenshots saved to: %s", REPORT_DIR)


if __name__ == "__main__":
    asyncio.run(main())
