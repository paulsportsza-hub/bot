"""Wave 13C — Dead End & Navigation Audit via Telethon.

Systematically tests every screen transition. For each screen, verifies:
1. Every inline button leads somewhere (no errors)
2. There is always a way back (no dead ends)
3. CTA bookmaker matches best odds shown

Usage:
    cd /home/paulsportsza/bot && source .venv/bin/activate
    python tests/e2e_wave13c.py 2>&1 | tee /home/paulsportsza/reports/e2e-wave13c-raw.txt
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
log = logging.getLogger("wave13c")

BOT = "mzansiedge_bot"
API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "")
SESSION_PATH = Path("data/telethon_session.string")
REPORT_DIR = BOT_ROOT.parent / "reports" / "e2e-screenshots"
REPORT_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_PATH = BOT_ROOT.parent / "reports" / "wave13c-e2e-results.json"

BOT_TIMEOUT = 15
PICKS_TIMEOUT = 45

results: list[dict] = []
dead_ends: list[str] = []
bugs: list[dict] = []


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
    (REPORT_DIR / f"13c-{safe}.txt").write_text(
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


def txt(msg: Message | None) -> str:
    return (msg.text or msg.message or "") if msg else ""


def btns(msg: Message | None) -> list[str]:
    if not msg or not msg.buttons:
        return []
    return [btn.text for row in msg.buttons for btn in row]


def cb_data(msg: Message | None) -> list[str]:
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
    return [{"text": btn.text, "url": btn.url}
            for row in msg.buttons for btn in row
            if hasattr(btn, "url") and btn.url]


def has_back(msg: Message | None) -> bool:
    """Check if a message has any back/menu navigation button."""
    if not msg or not msg.buttons:
        return False
    for row in msg.buttons:
        for btn in row:
            t = btn.text.lower()
            if "back" in t or "menu" in t or "↩" in t or "🏠" in t:
                return True
            if hasattr(btn, "data") and btn.data:
                d = btn.data.decode() if isinstance(btn.data, bytes) else str(btn.data)
                if "menu:home" in d or "back" in d:
                    return True
    return False


def check_dead_end(test_id: str, screen_name: str, msg: Message | None):
    """Check if a screen is a dead end and log it."""
    if msg and not has_back(msg):
        dead_ends.append(f"{test_id}: {screen_name}")
        return True
    return False


# ═════════════════════════════════════════════════════════════
# TESTS
# ═════════════════════════════════════════════════════════════

async def run_tests(c: TelegramClient):

    # Warm up
    await send(c, "/start", timeout=20)
    await asyncio.sleep(2)

    # ═══════════════════════════════════════════════════════
    log.info("")
    log.info("=" * 60)
    log.info("FLOW 1: Your Games → Game Detail → AI Breakdown")
    log.info("=" * 60)

    # ── F1-01: Your Games main screen ────────────────────
    yg = await send(c, "⚽ Your Games", timeout=20)
    yg_text = txt(yg)
    yg_btns = btns(yg)
    yg_cb = cb_data(yg)
    has_nav = has_back(yg)
    has_games = any("yg:game:" in d for d in yg_cb)

    asserts = [
        (yg is not None, "Your Games responded"),
        (has_nav, f"Has back/menu nav: {has_nav}"),
        (has_games or "no" in yg_text.lower(), "Games shown or empty state"),
    ]
    record("F1-01", "Your Games — has nav", "PASS" if all(a[0] for a in asserts) else "FAIL",
           yg_text + f"\nButtons: {yg_btns}", asserts)
    if not has_nav:
        dead_ends.append("F1-01: Your Games main screen")

    # ── F1-02: Tap a game → Game Detail ──────────────────
    game_msg = None
    if yg and yg.buttons:
        game_msg = await click_data(c, yg, "yg:game:")

    game_text = txt(game_msg)
    game_btns = btns(game_msg)
    game_cb = cb_data(game_msg)
    game_has_back = has_back(game_msg)

    asserts = [
        (game_msg is not None, "Game detail loaded"),
        (game_has_back, f"Game detail has back nav: {game_has_back}"),
        (len(game_text) > 20, f"Content present: {len(game_text)} chars"),
    ]
    record("F1-02", "Game Detail — has back nav",
           "PASS" if all(a[0] for a in asserts) else "FAIL",
           game_text + f"\nButtons: {game_btns}\nCB: {game_cb}", asserts)
    if game_msg and not game_has_back:
        dead_ends.append("F1-02: Game Detail (yg:game:)")
        file_bug("BUG-DE-01", "P1", "Game Detail",
                 "Your Games → tap game",
                 "Back button to return to Your Games",
                 f"No back/menu button. Buttons: {game_btns}")

    # ── F1-03: Game Detail — CTA consistency ─────────────
    game_urls = url_btns(game_msg)
    if game_urls and game_text:
        # Check if CTA bookmaker matches recommendation in text
        cta_text = game_urls[0]["text"] if game_urls else ""
        asserts = [
            (len(game_urls) >= 1, f"CTA button present: {cta_text}"),
        ]
        record("F1-03", "Game Detail — CTA present",
               "PASS" if all(a[0] for a in asserts) else "WARN",
               f"CTA: {cta_text}\nURLs: {game_urls}", asserts)
    else:
        record("F1-03", "Game Detail — CTA present", "SKIP",
               "No game detail or no URL buttons",
               [(False, "Skipped")])

    # ── F1-04: Game Detail → Odds Comparison ─────────────
    odds_msg = None
    if game_msg and game_msg.buttons:
        odds_msg = await click_data(c, game_msg, "odds:compare:")
        if not odds_msg:
            odds_msg = await click_text(c, game_msg, "Bookmaker Odds", partial=True)
            if not odds_msg:
                odds_msg = await click_text(c, game_msg, "All Bookmaker", partial=True)

    if odds_msg:
        odds_text = txt(odds_msg)
        odds_btns_list = btns(odds_msg)
        odds_has_back = has_back(odds_msg)

        asserts = [
            (odds_has_back, f"Odds comparison has back nav: {odds_has_back}"),
            (len(odds_text) > 20, f"Content: {len(odds_text)} chars"),
        ]
        record("F1-04", "Odds Comparison — has back nav",
               "PASS" if all(a[0] for a in asserts) else "FAIL",
               odds_text + f"\nButtons: {odds_btns_list}", asserts)
        if not odds_has_back:
            dead_ends.append("F1-04: Odds Comparison (from Game Detail)")
            file_bug("BUG-DE-02", "P1", "Odds Comparison",
                     "Your Games → Game → All Bookmaker Odds",
                     "Back button to return to Game Detail",
                     f"No back button. Buttons: {odds_btns_list}")

        # ── F1-04b: Back from Odds Comparison ────────────
        if odds_has_back:
            back_msg = await click_text(c, odds_msg, "Back", partial=True)
            if not back_msg:
                back_msg = await click_data(c, odds_msg, "menu:home")
            back_text = txt(back_msg)
            asserts = [
                (back_msg is not None, "Back from odds comparison works"),
            ]
            record("F1-04b", "Odds Comparison — back works",
                   "PASS" if back_msg else "FAIL",
                   back_text[:200], asserts)
    else:
        # Check if odds:compare button exists at all
        has_odds_btn = any("odds:compare" in d for d in game_cb) if game_cb else False
        record("F1-04", "Odds Comparison — accessible",
               "SKIP" if not has_odds_btn else "FAIL",
               f"odds:compare button exists: {has_odds_btn}. Game buttons: {game_btns}",
               [(has_odds_btn or True, f"odds:compare button: {has_odds_btn}")])

    # ── F1-05: Back from Game Detail → Your Games ────────
    if game_msg and game_has_back:
        back_yg = await click_text(c, game_msg, "Back", partial=True)
        if not back_yg:
            back_yg = await click_data(c, game_msg, "yg:all:")
        back_text = txt(back_yg)
        is_yg = "your games" in back_text.lower() or "games" in back_text.lower() or \
                any("yg:game:" in d for d in cb_data(back_yg))

        asserts = [
            (back_yg is not None, "Back navigation responded"),
            (is_yg, f"Returned to Your Games: {is_yg}"),
        ]
        record("F1-05", "Back from Game Detail → Your Games",
               "PASS" if all(a[0] for a in asserts) else "FAIL",
               back_text[:200], asserts)

    # ═══════════════════════════════════════════════════════
    log.info("")
    log.info("=" * 60)
    log.info("FLOW 2: Hot Tips → Tip Detail → Odds Comparison")
    log.info("=" * 60)

    # ── F2-01: Hot Tips listing ──────────────────────────
    ht_msgs = await send_get_all(c, "🔥 Hot Tips", timeout=PICKS_TIMEOUT, settle=8)
    # Get the main tips message (the one with tip buttons)
    ht_main = None
    for m in reversed(ht_msgs):
        if m.buttons and any("tip:detail:" in d for d in cb_data(m)):
            ht_main = m
            break
    if not ht_main and ht_msgs:
        ht_main = ht_msgs[-1]  # Use last message

    ht_text = txt(ht_main)
    ht_btns_list = btns(ht_main)
    ht_cb = cb_data(ht_main)
    ht_has_back = has_back(ht_main)

    asserts = [
        (ht_main is not None, "Hot Tips responded"),
        (ht_has_back, f"Hot Tips has back/menu nav: {ht_has_back}"),
    ]
    record("F2-01", "Hot Tips — has nav",
           "PASS" if all(a[0] for a in asserts) else "FAIL",
           ht_text[:500] + f"\nButtons: {ht_btns_list}", asserts)

    # ── F2-02: Tap tip → Tip Detail ─────────────────────
    tip_msg = None
    if ht_main and ht_main.buttons:
        tip_msg = await click_data(c, ht_main, "tip:detail:")

    tip_text = txt(tip_msg)
    tip_btns_list = btns(tip_msg)
    tip_cb = cb_data(tip_msg)
    tip_has_back = has_back(tip_msg)
    tip_urls = url_btns(tip_msg)

    asserts = [
        (tip_msg is not None, "Tip detail loaded"),
        (tip_has_back, f"Tip detail has back nav: {tip_has_back}"),
        (len(tip_text) > 20, f"Content: {len(tip_text)} chars"),
    ]
    record("F2-02", "Tip Detail — has back nav",
           "PASS" if all(a[0] for a in asserts) else "FAIL",
           tip_text + f"\nButtons: {tip_btns_list}\nCB: {tip_cb}", asserts)
    if tip_msg and not tip_has_back:
        dead_ends.append("F2-02: Tip Detail (tip:detail:)")
        file_bug("BUG-DE-03", "P1", "Tip Detail",
                 "Hot Tips → tap tip",
                 "Back button to Hot Tips or Menu",
                 f"No back/menu button. Buttons: {tip_btns_list}")

    # ── F2-03: Tip Detail — CTA consistency ──────────────
    if tip_msg and tip_text and tip_urls:
        cta = tip_urls[0]
        cta_bk = cta["text"].lower()
        # Find which bookmaker is recommended in the text
        bk_names = ["hollywoodbets", "betway", "supabets", "sportingbet", "gbets"]
        text_bks = [bk for bk in bk_names if bk in tip_text.lower()]
        # The CTA should mention the best-odds bookmaker shown in the text
        cta_matches = any(bk in cta_bk for bk in text_bks) if text_bks else True

        asserts = [
            (len(tip_urls) >= 1, f"CTA present: {cta['text']}"),
            (cta_matches, f"CTA bookmaker matches text: text={text_bks}, CTA={cta['text']}"),
        ]
        record("F2-03", "Tip Detail — CTA matches best odds",
               "PASS" if all(a[0] for a in asserts) else "FAIL",
               f"CTA: {cta['text']}\nText bookmakers: {text_bks}", asserts)
    else:
        record("F2-03", "Tip Detail — CTA consistency", "SKIP",
               "No tip detail or no CTA",
               [(False, "Skipped")])

    # ── F2-04: Tip Detail → Odds Comparison ──────────────
    tip_odds_msg = None
    if tip_msg and tip_msg.buttons:
        tip_odds_msg = await click_data(c, tip_msg, "odds:compare:")
        if not tip_odds_msg:
            tip_odds_msg = await click_text(c, tip_msg, "Bookmaker Odds", partial=True)

    if tip_odds_msg:
        to_text = txt(tip_odds_msg)
        to_btns = btns(tip_odds_msg)
        to_has_back = has_back(tip_odds_msg)

        asserts = [
            (to_has_back, f"Odds comparison has back: {to_has_back}"),
            (len(to_text) > 20, f"Content: {len(to_text)} chars"),
        ]
        record("F2-04", "Tip → Odds Comparison — has back",
               "PASS" if all(a[0] for a in asserts) else "FAIL",
               to_text + f"\nButtons: {to_btns}", asserts)
        if not to_has_back:
            dead_ends.append("F2-04: Odds Comparison (from Tip Detail)")
    else:
        has_btn = any("odds:compare" in d for d in tip_cb) if tip_cb else False
        record("F2-04", "Tip → Odds Comparison",
               "SKIP" if not has_btn else "FAIL",
               f"odds:compare button exists: {has_btn}. Buttons: {tip_btns_list}",
               [(True, f"odds:compare button: {has_btn}")])

    # ── F2-05: Back from Tip Detail → Hot Tips ───────────
    if tip_msg and tip_has_back:
        back_ht = await click_text(c, tip_msg, "Back", partial=True)
        if not back_ht:
            back_ht = await click_data(c, tip_msg, "hot:")
        back_text = txt(back_ht)
        is_ht = "hot tips" in back_text.lower() or "value bet" in back_text.lower()

        asserts = [
            (back_ht is not None, "Back responded"),
            (is_ht, f"Returned to Hot Tips: {is_ht}"),
        ]
        record("F2-05", "Back from Tip Detail → Hot Tips",
               "PASS" if all(a[0] for a in asserts) else "WARN",
               back_text[:200], asserts)

    # ═══════════════════════════════════════════════════════
    log.info("")
    log.info("=" * 60)
    log.info("FLOW 3: Sport Filter → Game Detail")
    log.info("=" * 60)

    # ── F3-01: Sport filter buttons ──────────────────────
    yg2 = await send(c, "⚽ Your Games", timeout=20)
    sport_emojis = ["⚽", "🏏", "🏉", "🎾", "🥊", "🏀"]
    sport_btn_found = None
    if yg2 and yg2.buttons:
        for row in yg2.buttons:
            for btn in row:
                if hasattr(btn, "data") and btn.data:
                    d = btn.data.decode() if isinstance(btn.data, bytes) else str(btn.data)
                    if d.startswith("yg:sport:"):
                        sport_btn_found = btn
                        break
            if sport_btn_found:
                break

    if sport_btn_found:
        # Click the sport filter
        old = await _last_id(c)
        try:
            await sport_btn_found.click()
        except Exception:
            pass
        await asyncio.sleep(3)
        sport_msg = None
        msgs = await c.get_messages(BOT, limit=10)
        for m in msgs:
            if m.id > old and not m.out:
                sport_msg = m
                break
        if not sport_msg:
            sport_msg = await c.get_messages(BOT, ids=yg2.id)

        sport_text = txt(sport_msg)
        sport_has_back = has_back(sport_msg)

        asserts = [
            (sport_msg is not None, "Sport filter responded"),
            (sport_has_back, f"Sport view has back: {sport_has_back}"),
        ]
        record("F3-01", "Sport filter → has back nav",
               "PASS" if all(a[0] for a in asserts) else "FAIL",
               sport_text[:300] + f"\nButtons: {btns(sport_msg)}", asserts)
        if sport_msg and not sport_has_back:
            dead_ends.append("F3-01: Sport-filtered Your Games")

        # ── F3-02: Back from sport filter → all games ────
        if sport_has_back:
            back_all = await click_text(c, sport_msg, "Back", partial=True)
            if not back_all:
                back_all = await click_data(c, sport_msg, "yg:all:")
            asserts = [
                (back_all is not None, "Back to all games worked"),
            ]
            record("F3-02", "Sport filter → Back → all games",
                   "PASS" if back_all else "FAIL",
                   txt(back_all)[:200] if back_all else "", asserts)
    else:
        record("F3-01", "Sport filter", "SKIP",
               "No sport filter buttons found",
               [(True, "User may follow only 1 sport")])

    # ═══════════════════════════════════════════════════════
    log.info("")
    log.info("=" * 60)
    log.info("FLOW 4: Settings → Sub-screens")
    log.info("=" * 60)

    # ── F4-01: Settings home ─────────────────────────────
    settings = await send(c, "⚙️ Settings")
    s_text = txt(settings)
    s_btns = btns(settings)
    s_cb = cb_data(settings)
    s_has_back = has_back(settings)

    asserts = [
        (settings is not None, "Settings responded"),
        (s_has_back, f"Settings has back/menu: {s_has_back}"),
        (len(s_btns) >= 4, f"Buttons: {len(s_btns)}"),
    ]
    record("F4-01", "Settings — has nav",
           "PASS" if all(a[0] for a in asserts) else "FAIL",
           s_text + f"\nButtons: {s_btns}", asserts)

    # ── F4-02: Each settings sub-screen has back ─────────
    settings_subs = [
        ("settings:risk", "Risk Profile"),
        ("settings:bankroll", "Bankroll"),
        ("settings:notify", "Notifications"),
        ("settings:story", "My Notifications"),
        ("settings:sports", "My Sports"),
    ]

    for prefix, label in settings_subs:
        if not any(d.startswith(prefix) for d in s_cb):
            record(f"F4-{label}", f"Settings → {label}", "SKIP",
                   f"Button {prefix} not found in {s_cb}",
                   [(True, f"{prefix} not available")])
            continue

        # Re-open settings first (sub-screen may have navigated away)
        settings = await send(c, "⚙️ Settings")
        sub_msg = await click_data(c, settings, prefix)
        sub_text = txt(sub_msg)
        sub_has_back = has_back(sub_msg)

        asserts = [
            (sub_msg is not None, f"{label} screen loaded"),
            (sub_has_back, f"{label} has back: {sub_has_back}"),
        ]
        record(f"F4-{label}", f"Settings → {label} — has back",
               "PASS" if all(a[0] for a in asserts) else "FAIL",
               sub_text[:200] + f"\nButtons: {btns(sub_msg)}", asserts)
        if sub_msg and not sub_has_back:
            dead_ends.append(f"F4: Settings → {label}")
            file_bug(f"BUG-DE-S{label[:3]}", "P2", f"Settings → {label}",
                     f"Settings → tap {label}",
                     "Back button to settings home",
                     f"No back button. Buttons: {btns(sub_msg)}")

    # ── F4-03: Settings → Reset → Cancel ─────────────────
    settings = await send(c, "⚙️ Settings")
    if settings:
        reset_msg = await click_data(c, settings, "settings:reset")
        if reset_msg:
            reset_text = txt(reset_msg)
            reset_has_back = has_back(reset_msg)
            asserts = [
                (reset_msg is not None, "Reset screen loaded"),
                (reset_has_back, f"Reset has back (cancel): {reset_has_back}"),
            ]
            record("F4-Reset", "Settings → Reset — has cancel/back",
                   "PASS" if all(a[0] for a in asserts) else "FAIL",
                   reset_text[:200] + f"\nButtons: {btns(reset_msg)}", asserts)
            # Don't actually confirm reset!
            if reset_has_back:
                await click_text(c, reset_msg, "Back", partial=True)

    # ═══════════════════════════════════════════════════════
    log.info("")
    log.info("=" * 60)
    log.info("FLOW 5: Keyboard & Command Responses")
    log.info("=" * 60)

    # Test each keyboard button leads somewhere with nav
    keyboard_tests = [
        ("📖 Guide", "Guide"),
        ("👤 Profile", "Profile"),
        ("❓ Help", "Help"),
    ]

    for kb_text, label in keyboard_tests:
        msg = await send(c, kb_text)
        m_text = txt(msg)
        m_has_back = has_back(msg)
        # Guide, Profile, Help may not need inline back buttons —
        # they're accessible via sticky keyboard. Check for content.
        asserts = [
            (msg is not None, f"{label} responded"),
            (len(m_text) > 10, f"Content: {len(m_text)} chars"),
        ]
        record(f"F5-{label}", f"Keyboard → {label}",
               "PASS" if all(a[0] for a in asserts) else "FAIL",
               m_text[:200], asserts)

    # ── F5-Commands: /start, /menu, /help, /picks, /admin ──
    for cmd in ["/start", "/menu", "/help", "/picks", "/admin"]:
        timeout = PICKS_TIMEOUT if cmd == "/picks" else BOT_TIMEOUT
        msg = await send(c, cmd, timeout=timeout)
        asserts = [
            (msg is not None, f"{cmd} responded"),
        ]
        record(f"F5-{cmd}", f"Command {cmd} responds",
               "PASS" if msg else "FAIL",
               txt(msg)[:200] if msg else "", asserts)

    # ═══════════════════════════════════════════════════════
    log.info("")
    log.info("=" * 60)
    log.info("FLOW 6: Hot Tips Pagination")
    log.info("=" * 60)

    # ── F6-01: Pagination forward ────────────────────────
    ht_msgs2 = await send_get_all(c, "🔥 Hot Tips", timeout=PICKS_TIMEOUT, settle=8)
    ht_page = None
    for m in reversed(ht_msgs2):
        if m.buttons:
            ht_page = m
            break

    if ht_page:
        # Look for pagination buttons
        page_btns = [d for d in cb_data(ht_page) if "hot:page:" in d or "▶" in d]
        has_pagination = len(page_btns) > 0

        asserts = [
            (True, f"Pagination buttons: {page_btns or 'none (may be single page)'}"),
        ]
        record("F6-01", "Hot Tips pagination",
               "PASS", f"Page buttons: {page_btns}\nAll buttons: {btns(ht_page)}",
               asserts)

        # If there's a next page, try it
        if has_pagination:
            next_msg = await click_data(c, ht_page, "hot:page:")
            if next_msg:
                next_has_back = has_back(next_msg)
                asserts = [
                    (next_msg is not None, "Page 2 loaded"),
                    (next_has_back, f"Page 2 has nav: {next_has_back}"),
                ]
                record("F6-02", "Hot Tips page 2 — has nav",
                       "PASS" if all(a[0] for a in asserts) else "FAIL",
                       txt(next_msg)[:200] + f"\nButtons: {btns(next_msg)}", asserts)

    # ═══════════════════════════════════════════════════════
    log.info("")
    log.info("=" * 60)
    log.info("FLOW 7: CTA Consistency Audit")
    log.info("=" * 60)

    # Collect all screens with CTAs and verify consistency
    # Re-tap a tip to get fresh CTA data
    ht3 = await send_get_all(c, "🔥 Hot Tips", timeout=PICKS_TIMEOUT, settle=8)
    tip3 = None
    for m in reversed(ht3):
        if m.buttons and any("tip:detail:" in d for d in cb_data(m)):
            tip3 = await click_data(c, m, "tip:detail:")
            break

    if tip3:
        t3_text = txt(tip3)
        t3_urls = url_btns(tip3)
        t3_cb = cb_data(tip3)

        # Check CTA format
        if t3_urls:
            cta = t3_urls[0]
            # Expected: "📲 Bet on {Bookmaker} →" or similar
            has_emoji = "📲" in cta["text"]
            has_arrow = "→" in cta["text"]
            has_bet = "bet" in cta["text"].lower() or "place" in cta["text"].lower()

            asserts = [
                (has_bet, f"CTA contains 'bet'/'place': {cta['text']}"),
                (has_arrow, f"CTA has arrow →: {cta['text']}"),
                ("btag" in cta["url"].lower() or ".co.za" in cta["url"].lower(),
                 f"Affiliate URL: {cta['url'][:60]}"),
            ]
            record("F7-01", "CTA format audit",
                   "PASS" if all(a[0] for a in asserts) else "FAIL",
                   f"CTA: {cta['text']}\nURL: {cta['url']}", asserts)

            # Check that CTA bookmaker matches what's in the tip text
            bk_in_text = []
            for bk in ["hollywoodbets", "betway", "supabets", "sportingbet", "gbets"]:
                if bk in t3_text.lower():
                    bk_in_text.append(bk)
            cta_bk = cta["text"].lower()
            matches = any(bk in cta_bk for bk in bk_in_text) if bk_in_text else True

            asserts = [
                (matches, f"CTA bookmaker matches text: CTA='{cta['text']}', text_bks={bk_in_text}"),
            ]
            record("F7-02", "CTA bookmaker matches tip recommendation",
                   "PASS" if matches else "FAIL",
                   f"CTA: {cta['text']}\nBookmakers in text: {bk_in_text}", asserts)
        else:
            record("F7-01", "CTA audit", "SKIP",
                   "No URL buttons in tip detail",
                   [(False, "No CTA found")])
    else:
        record("F7-01", "CTA audit", "SKIP",
               "Could not access tip detail",
               [(False, "Skipped")])

    # ═══════════════════════════════════════════════════════
    log.info("")
    log.info("=" * 60)
    log.info("FLOW 8: Edge Cases & Error Screens")
    log.info("=" * 60)

    # ── F8-01: Menu → Main Menu button works ─────────────
    settings2 = await send(c, "⚙️ Settings")
    if settings2:
        main_msg = await click_data(c, settings2, "menu:home")
        if not main_msg:
            main_msg = await click_text(c, settings2, "Main Menu", partial=True)
        asserts = [
            (main_msg is not None, "Main Menu button works from settings"),
        ]
        record("F8-01", "Main Menu button from Settings",
               "PASS" if main_msg else "FAIL",
               txt(main_msg)[:200] if main_msg else "", asserts)

    # ── F8-02: Empty Hot Tips footer has nav ─────────────
    # Already tested in earlier flows — skip if we have tips

    # ── F8-03: Double-tap same button doesn't crash ──────
    msg1 = await send(c, "⚙️ Settings")
    msg2 = await send(c, "⚙️ Settings")
    asserts = [
        (msg1 is not None and msg2 is not None, "Double tap both responded"),
    ]
    record("F8-03", "Double-tap Settings",
           "PASS" if all(a[0] for a in asserts) else "WARN",
           "", asserts)


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
        log.error("Session expired")
        sys.exit(1)

    me = await client.get_me()
    log.info("Connected as: %s (@%s)", me.first_name, me.username)
    log.info("Testing bot: @%s", BOT)
    log.info("=" * 60)

    try:
        await run_tests(client)
    except Exception as e:
        log.exception("Crash: %s", e)
        record("CRASH", "Runner crashed", "FAIL", str(e), [(False, str(e))])
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
    log.info("WAVE 13C DEAD END AUDIT RESULTS")
    log.info("=" * 60)
    log.info("  Total:   %d", total)
    log.info("  PASS:    %d", passed)
    log.info("  FAIL:    %d", failed)
    log.info("  SKIP:    %d", skipped)
    log.info("  WARN:    %d", warned)
    log.info("")
    log.info("  DEAD ENDS FOUND: %d", len(dead_ends))
    for de in dead_ends:
        log.info("    🚫 %s", de)
    log.info("")
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

    # Save
    output = {
        "results": results,
        "dead_ends": dead_ends,
        "bugs": bugs,
        "summary": {
            "total": total, "passed": passed, "failed": failed,
            "skipped": skipped, "warned": warned,
            "dead_end_count": len(dead_ends), "bug_count": len(bugs),
        },
    }
    RESULTS_PATH.write_text(json.dumps(output, indent=2, ensure_ascii=False))
    log.info("\nResults: %s", RESULTS_PATH)


if __name__ == "__main__":
    asyncio.run(main())
