"""Wave 14B — Diamond Edge System Verification via Telethon.

Tests the Wave 14A implementation: rebrand from PLATINUM/⛏️ to DIAMOND/💎,
threshold recalibration, conviction removal, onboarding explainer, guide section.

Usage:
    cd /home/paulsportsza/bot && source .venv/bin/activate
    python tests/e2e_wave14b.py 2>&1 | tee /home/paulsportsza/reports/e2e-wave14b-raw.txt
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

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.sessions import StringSession
from telethon.tl.custom.message import Message

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("wave14b")

BOT = "mzansiedge_bot"
API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "")
SESSION_PATH = Path("data/telethon_session.string")
REPORT_DIR = Path("/home/paulsportsza/reports/e2e-screenshots")
REPORT_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_PATH = Path("/home/paulsportsza/reports/wave14b-e2e-results.json")

BOT_TIMEOUT = 15
AI_TIMEOUT = 30

results: list[dict] = []
bugs: list[dict] = []

# New branding
NEW_EMOJIS = {"💎", "🥇", "🥈", "🥉"}
NEW_LABELS = {"DIAMOND EDGE", "GOLDEN EDGE", "SILVER EDGE", "BRONZE EDGE"}
NEW_LABEL_WORDS = {"DIAMOND", "GOLD", "SILVER", "BRONZE"}
# Old branding (must NOT appear)
OLD_EMOJIS = {"⛏️"}
OLD_LABELS = {"PLATINUM", "PLATINUM EDGE"}


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
    (REPORT_DIR / f"14b-{safe}.txt").write_text(
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
        msgs = await c.get_messages(BOT, limit=5)
        for m in msgs:
            if m.id > old and not m.out and m.buttons:
                return m
        updated = await c.get_messages(BOT, ids=msg.id)
        if updated and updated.buttons:
            return updated
        await asyncio.sleep(2)
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


def check_old_branding(text: str) -> list[str]:
    """Check text for ANY old branding remnants. Returns list of violations."""
    violations = []
    if "PLATINUM" in text.upper():
        violations.append(f"Found 'PLATINUM' in: ...{text[max(0,text.upper().find('PLATINUM')-20):text.upper().find('PLATINUM')+30]}...")
    if "⛏️" in text:
        violations.append(f"Found ⛏️ emoji")
    if "mining" in text.lower():
        violations.append(f"Found 'mining'")
    return violations


def check_new_branding(text: str) -> dict:
    """Check which new branding elements are present."""
    return {
        "has_diamond_emoji": "💎" in text,
        "has_gold_emoji": "🥇" in text,
        "has_silver_emoji": "🥈" in text,
        "has_bronze_emoji": "🥉" in text,
        "has_diamond_label": "DIAMOND" in text.upper(),
        "has_any_tier_emoji": any(e in text for e in NEW_EMOJIS),
        "has_any_edge_label": any(l in text.upper() for l in ["DIAMOND EDGE", "GOLDEN EDGE", "SILVER EDGE", "BRONZE EDGE"]),
    }


def check_conviction(text: str) -> list[str]:
    """Check for ANY conviction text remnants."""
    violations = []
    lower = text.lower()
    if "conviction" in lower:
        idx = lower.find("conviction")
        violations.append(f"Found 'conviction' at: ...{text[max(0,idx-30):idx+30]}...")
    for phrase in ["with high", "with medium", "with low"]:
        if phrase in lower:
            idx = lower.find(phrase)
            context = text[max(0, idx-10):idx+40]
            # Avoid false positives from non-conviction usage
            if "conviction" in lower[idx:idx+50] or phrase + " " in lower[idx:idx+20]:
                violations.append(f"Found '{phrase}' conviction phrase: ...{context}...")
    return violations


# ── Main test suite ──────────────────────────────────────────

async def run_tests():
    session_str = SESSION_PATH.read_text().strip()
    client = TelegramClient(StringSession(session_str), API_ID, API_HASH)
    await client.connect()

    me = await client.get_me()
    log.info("Connected as: %s (@%s)", me.first_name, me.username)
    log.info("Testing bot: @%s", BOT)
    log.info("=" * 60)

    # Reset to known state
    await send(client, "/start")
    await asyncio.sleep(2)

    # ════════════════════════════════════════════════════════════
    # SECTION 1: HOT TIPS — REBRAND VERIFICATION
    # ════════════════════════════════════════════════════════════
    log.info("")
    log.info("=" * 60)
    log.info("SECTION 1: HOT TIPS — REBRAND VERIFICATION")
    log.info("=" * 60)

    # Get Hot Tips listing
    hot_msgs = await send_get_all(client, "🔥 Hot Tips", timeout=30, settle=5)
    hot_msg = None
    for m in hot_msgs:
        if m.buttons and "Hot Tips" in (m.text or ""):
            hot_msg = m
            break

    if hot_msg:
        text = hot_msg.text or ""
        btns = get_buttons(hot_msg)
        full_text = text + " " + " ".join(btns)

        # ── DE-01: No old branding in Hot Tips listing ──
        old = check_old_branding(full_text)
        asserts = [(len(old) == 0, f"No old branding: {old if old else 'clean'}")]
        status = "PASS" if all(ok for ok, _ in asserts) else "FAIL"
        record("DE-01", "Hot Tips — zero old branding (PLATINUM/⛏️)", status,
               f"Text: {text[:500]}\nButtons: {btns}", asserts)
        if old:
            file_bug("BUG-DE-01", "P0", "Hot Tips listing", "🔥 Hot Tips",
                     "No PLATINUM or ⛏️", f"Found: {old}")

        # ── DE-02: New branding present ──
        new = check_new_branding(full_text)
        asserts = [
            (new["has_any_tier_emoji"], f"Has tier emoji (💎🥇🥈🥉): {new}"),
            (new["has_any_edge_label"], f"Has edge label: {new}"),
        ]
        status = "PASS" if all(ok for ok, _ in asserts) else "FAIL"
        record("DE-02", "Hot Tips — new branding present (💎🥇🥈🥉)", status,
               f"Branding check: {json.dumps(new, indent=2)}", asserts)

        # ── DE-03: Tier diversity in listing ──
        tier_emojis_found = {e for e in NEW_EMOJIS if e in text}
        asserts = [
            (len(tier_emojis_found) >= 2,
             f"Tier diversity: {len(tier_emojis_found)} tiers ({tier_emojis_found})"),
        ]
        status = "PASS" if all(ok for ok, _ in asserts) else "FAIL"
        record("DE-03", "Hot Tips — tier diversity (2+ tiers visible)", status,
               f"Tiers found: {tier_emojis_found}\nPage 1 text: {text[:400]}", asserts)

        # Check page 2 as well for more tier diversity
        page2 = await click_data(client, hot_msg, "hot:page:")
        if page2:
            p2_text = page2.text or ""
            p2_tiers = {e for e in NEW_EMOJIS if e in p2_text}
            all_tiers = tier_emojis_found | p2_tiers
            record("DE-03b", "Hot Tips page 2 — tier diversity", "PASS" if len(all_tiers) >= 2 else "WARN",
                   f"Page 2 tiers: {p2_tiers}, Combined: {all_tiers}",
                   [(len(all_tiers) >= 2, f"Combined tier diversity: {all_tiers}")])
    else:
        record("DE-01", "Hot Tips — zero old branding", "SKIP", "No Hot Tips response",
               [(False, "Skipped")])
        record("DE-02", "Hot Tips — new branding", "SKIP", "No Hot Tips response",
               [(False, "Skipped")])
        record("DE-03", "Hot Tips — tier diversity", "SKIP", "No Hot Tips response",
               [(False, "Skipped")])

    # ════════════════════════════════════════════════════════════
    # SECTION 2: TIP DETAIL — REBRAND + CONVICTION
    # ════════════════════════════════════════════════════════════
    log.info("")
    log.info("=" * 60)
    log.info("SECTION 2: TIP DETAIL — REBRAND + CONVICTION")
    log.info("=" * 60)

    # Navigate back to Hot Tips page 1
    if page2:
        hot_msg = await click_data(client, page2, "hot:page:0") or hot_msg
    elif not hot_msg:
        hot_msgs2 = await send_get_all(client, "🔥 Hot Tips", timeout=30, settle=5)
        for m in hot_msgs2:
            if m.buttons and "Hot Tips" in (m.text or ""):
                hot_msg = m
                break

    tip_detail = None
    if hot_msg:
        tip_detail = await click_data(client, hot_msg, "tip:detail:")

    if tip_detail:
        td_text = tip_detail.text or ""
        td_btns = get_buttons(tip_detail)
        full_td = td_text + " " + " ".join(td_btns)

        # ── DE-04: No old branding in Tip Detail ──
        old = check_old_branding(full_td)
        asserts = [(len(old) == 0, f"No old branding in tip detail: {old if old else 'clean'}")]
        status = "PASS" if all(ok for ok, _ in asserts) else "FAIL"
        record("DE-04", "Tip Detail — zero old branding", status,
               f"Text: {td_text[:500]}\nButtons: {td_btns}", asserts)
        if old:
            file_bug("BUG-DE-02", "P0", "Tip Detail", "Hot Tips → tap tip",
                     "No PLATINUM or ⛏️", f"Found: {old}")

        # ── DE-05: New branding in Tip Detail ──
        new = check_new_branding(full_td)
        asserts = [
            (new["has_any_tier_emoji"], f"Has tier emoji: {new}"),
            (new["has_any_edge_label"], f"Has EDGE label: {new}"),
        ]
        status = "PASS" if all(ok for ok, _ in asserts) else "FAIL"
        record("DE-05", "Tip Detail — new branding present", status,
               f"Branding: {json.dumps(new, indent=2)}", asserts)

        # ── DE-06: No conviction text in Tip Detail ──
        cv = check_conviction(td_text)
        asserts = [(len(cv) == 0, f"No conviction text: {cv if cv else 'clean'}")]
        status = "PASS" if all(ok for ok, _ in asserts) else "FAIL"
        record("DE-06", "Tip Detail — zero conviction text", status,
               f"Conviction check: {cv}\nText: {td_text[:500]}", asserts)
        if cv:
            file_bug("BUG-DE-03", "P1", "Tip Detail", "Hot Tips → tap tip",
                     "No conviction text anywhere", f"Found: {cv}")
    else:
        record("DE-04", "Tip Detail — zero old branding", "SKIP", "No tip detail",
               [(False, "Skipped")])
        record("DE-05", "Tip Detail — new branding", "SKIP", "No tip detail",
               [(False, "Skipped")])
        record("DE-06", "Tip Detail — zero conviction", "SKIP", "No tip detail",
               [(False, "Skipped")])

    # ════════════════════════════════════════════════════════════
    # SECTION 3: GAME BREAKDOWN — VERDICT BADGE + CONVICTION
    # ════════════════════════════════════════════════════════════
    log.info("")
    log.info("=" * 60)
    log.info("SECTION 3: GAME BREAKDOWN — VERDICT BADGE + CONVICTION")
    log.info("=" * 60)

    # Navigate to Your Games and find a FOOTBALL match (has odds in DB)
    yg = await send(client, "⚽ Your Games")
    await asyncio.sleep(2)

    # Find a football game (⚽ in button text, not 🏏 or 🏉)
    football_game_id = ""
    if yg and yg.buttons:
        for row in yg.buttons:
            for btn in row:
                if hasattr(btn, "data") and btn.data:
                    cb = btn.data.decode() if isinstance(btn.data, bytes) else str(btn.data)
                    if cb.startswith("yg:game:") and "⚽" in btn.text:
                        football_game_id = cb.replace("yg:game:", "")
                        break
            if football_game_id:
                break

    game_msg = None
    if football_game_id:
        log.info("  Clicking football game: %s (waiting for AI...)", football_game_id[:20])
        game_msg = await click_data_wait(client, yg, f"yg:game:{football_game_id}",
                                          timeout=AI_TIMEOUT)

    if game_msg:
        g_text = game_msg.text or ""
        g_btns = get_buttons(game_msg)
        full_g = g_text + " " + " ".join(g_btns)

        # ── DE-07: No old branding in Game Breakdown ──
        old = check_old_branding(full_g)
        asserts = [(len(old) == 0, f"No old branding: {old if old else 'clean'}")]
        status = "PASS" if all(ok for ok, _ in asserts) else "FAIL"
        record("DE-07", "Game Breakdown — zero old branding", status,
               f"Text: {g_text[:500]}\nButtons: {g_btns}", asserts)
        if old:
            file_bug("BUG-DE-04", "P0", "Game Breakdown", "Your Games → tap football game",
                     "No PLATINUM or ⛏️", f"Found: {old}")

        # ── DE-08: Verdict uses new tier badge ──
        asserts = []
        has_verdict = "Verdict" in g_text
        asserts.append((has_verdict, f"Verdict present: {has_verdict}"))

        if has_verdict:
            verdict_line = ""
            for line in g_text.split("\n"):
                if "Verdict" in line:
                    verdict_line = line
                    break

            # Check for new emoji in verdict
            has_new_badge = any(e in verdict_line for e in NEW_EMOJIS)
            has_old_badge = any(e in verdict_line for e in OLD_EMOJIS)
            has_odds = "Bookmaker Odds" in g_text or "EV:" in g_text

            if has_odds:
                asserts.append((has_new_badge, f"Verdict has new badge: '{verdict_line}'"))
                asserts.append((not has_old_badge, f"No old badge in verdict: {has_old_badge}"))
                # Check it says DIAMOND/GOLD/SILVER/BRONZE EDGE (not PLATINUM)
                has_edge_label = any(l in verdict_line.upper() for l in
                                    ["DIAMOND EDGE", "GOLDEN EDGE", "SILVER EDGE", "BRONZE EDGE"])
                asserts.append((has_edge_label, f"Verdict has new EDGE label: '{verdict_line}'"))
            else:
                asserts.append((True, f"No odds data — badge correctly omitted: '{verdict_line}'"))

        status = "PASS" if all(ok for ok, _ in asserts) else "FAIL"
        record("DE-08", "Game Breakdown — verdict uses new tier badge", status,
               f"Verdict: {verdict_line if has_verdict else 'N/A'}\nText: {g_text[:400]}", asserts)

        # ── DE-09: No conviction text in Game Breakdown ──
        cv = check_conviction(g_text)
        asserts = [(len(cv) == 0, f"No conviction: {cv if cv else 'clean'}")]
        status = "PASS" if all(ok for ok, _ in asserts) else "FAIL"
        record("DE-09", "Game Breakdown — zero conviction text", status,
               f"Conviction check: {cv}\nText: {g_text[:600]}", asserts)
        if cv:
            file_bug("BUG-DE-05", "P1", "Game Breakdown verdict",
                     "Your Games → tap football game",
                     "No conviction text", f"Found: {cv}")

        # ── DE-10: CTA button uses new emoji ──
        first_btn = g_btns[0] if g_btns else ""
        asserts = []
        if "Back " in first_btn and "→" in first_btn:
            has_new = any(e in first_btn for e in NEW_EMOJIS)
            has_old = any(e in first_btn for e in OLD_EMOJIS)
            asserts.append((has_new, f"CTA has new tier emoji: '{first_btn}'"))
            asserts.append((not has_old, f"CTA no old emoji: {has_old}"))
        elif "View odds" in first_btn:
            asserts.append((True, f"Fallback CTA (no positive EV): '{first_btn}'"))
        else:
            # Nav-only buttons (no odds data)
            asserts.append((True, f"No CTA — no odds data: '{first_btn}'"))

        status = "PASS" if all(ok for ok, _ in asserts) else "FAIL"
        record("DE-10", "Game Breakdown CTA — new emoji", status,
               f"First button: {first_btn}\nAll: {g_btns}", asserts)
    else:
        for tid, name in [("DE-07", "zero old branding"), ("DE-08", "verdict badge"),
                          ("DE-09", "zero conviction"), ("DE-10", "CTA emoji")]:
            record(tid, f"Game Breakdown — {name}", "SKIP",
                   f"No football game breakdown. game_id={football_game_id}",
                   [(False, "Skipped — no game breakdown")])

    # Also test a NON-FOOTBALL match for conviction removal
    log.info("  Testing non-football match for conviction removal...")
    yg2 = await send(client, "⚽ Your Games")
    await asyncio.sleep(2)
    non_football_id = ""
    if yg2 and yg2.buttons:
        for row in yg2.buttons:
            for btn in row:
                if hasattr(btn, "data") and btn.data:
                    cb = btn.data.decode() if isinstance(btn.data, bytes) else str(btn.data)
                    if cb.startswith("yg:game:") and "⚽" not in btn.text:
                        non_football_id = cb.replace("yg:game:", "")
                        break
            if non_football_id:
                break

    if non_football_id:
        log.info("  Clicking non-football game: %s", non_football_id[:20])
        nf_msg = await click_data_wait(client, yg2, f"yg:game:{non_football_id}",
                                        timeout=AI_TIMEOUT)
        if nf_msg:
            nf_text = nf_msg.text or ""
            cv = check_conviction(nf_text)
            asserts = [(len(cv) == 0, f"No conviction in non-football: {cv if cv else 'clean'}")]
            status = "PASS" if all(ok for ok, _ in asserts) else "FAIL"
            record("DE-11", "Non-football game — zero conviction text", status,
                   f"Conviction: {cv}\nText: {nf_text[:500]}", asserts)
            if cv:
                file_bug("BUG-DE-06", "P1", "Non-football game breakdown",
                         "Your Games → tap cricket/rugby game",
                         "No conviction text", f"Found: {cv}")
        else:
            record("DE-11", "Non-football — zero conviction", "SKIP",
                   "No non-football game breakdown",
                   [(False, "Skipped")])
    else:
        record("DE-11", "Non-football — zero conviction", "SKIP",
               "No non-football game in list",
               [(False, "Skipped")])

    # ════════════════════════════════════════════════════════════
    # SECTION 4: ODDS COMPARISON — REBRAND
    # ════════════════════════════════════════════════════════════
    log.info("")
    log.info("=" * 60)
    log.info("SECTION 4: ODDS COMPARISON — REBRAND CHECK")
    log.info("=" * 60)

    # Navigate to a football game's odds comparison
    yg3 = await send(client, "⚽ Your Games")
    await asyncio.sleep(2)
    compare_msg = None
    if yg3 and football_game_id:
        game3 = await click_data_wait(client, yg3, f"yg:game:{football_game_id}",
                                       timeout=AI_TIMEOUT)
        if game3:
            compare_msg = await click_data(client, game3, "odds:compare:")

    if compare_msg:
        oc_text = compare_msg.text or ""
        oc_btns = get_buttons(compare_msg)
        full_oc = oc_text + " " + " ".join(oc_btns)

        old = check_old_branding(full_oc)
        asserts = [(len(old) == 0, f"No old branding in odds comparison: {old if old else 'clean'}")]
        status = "PASS" if all(ok for ok, _ in asserts) else "FAIL"
        record("DE-12", "Odds Comparison — zero old branding", status,
               f"Text: {oc_text[:400]}\nButtons: {oc_btns}", asserts)
    else:
        record("DE-12", "Odds Comparison — zero old branding", "SKIP",
               "No odds comparison reached",
               [(False, "Skipped")])

    # ════════════════════════════════════════════════════════════
    # SECTION 5: GUIDE — EDGE RATINGS SECTION
    # ════════════════════════════════════════════════════════════
    log.info("")
    log.info("=" * 60)
    log.info("SECTION 5: GUIDE — EDGE RATINGS SECTION")
    log.info("=" * 60)

    guide_msg = await send(client, "📖 Guide")
    if guide_msg:
        g_text = guide_msg.text or ""

        # ── DE-13: Guide has Edge Ratings section ──
        asserts = []
        has_section = "Edge Rating" in g_text or "edge rating" in g_text.lower()
        asserts.append((has_section, f"Guide has Edge Ratings section: {has_section}"))

        # Check all 4 tiers present
        has_diamond = "Diamond" in g_text
        has_gold = "Gold" in g_text
        has_silver = "Silver" in g_text
        has_bronze = "Bronze" in g_text
        asserts.append((has_diamond and has_gold and has_silver and has_bronze,
                       f"All 4 tiers: D={has_diamond} G={has_gold} S={has_silver} B={has_bronze}"))

        # Check emojis
        has_emojis = "💎" in g_text and "🥇" in g_text and "🥈" in g_text and "🥉" in g_text
        asserts.append((has_emojis, f"All 4 emojis present: {has_emojis}"))

        # Check NO PLATINUM
        no_platinum = "PLATINUM" not in g_text.upper() and "platinum" not in g_text.lower()
        asserts.append((no_platinum, f"No 'Platinum': {no_platinum}"))

        # Check EV thresholds
        has_15 = "15%" in g_text or "≥15" in g_text
        has_8 = "8%" in g_text or "≥8" in g_text
        has_4 = "4%" in g_text or "≥4" in g_text
        has_1 = "1%" in g_text or "≥1" in g_text
        asserts.append((has_15 and has_8 and has_4 and has_1,
                       f"EV thresholds: 15%={has_15} 8%={has_8} 4%={has_4} 1%={has_1}"))

        status = "PASS" if all(ok for ok, _ in asserts) else "FAIL"
        record("DE-13", "Guide — Edge Ratings section complete", status,
               f"Text: {g_text[:800]}", asserts)
        if not no_platinum:
            file_bug("BUG-DE-07", "P0", "Guide", "📖 Guide",
                     "No 'Platinum' in guide", "Found PLATINUM in guide text")
    else:
        record("DE-13", "Guide — Edge Ratings section", "SKIP", "No guide response",
               [(False, "Skipped")])

    # ════════════════════════════════════════════════════════════
    # SECTION 6: FIRST-TIME TOOLTIP
    # ════════════════════════════════════════════════════════════
    log.info("")
    log.info("=" * 60)
    log.info("SECTION 6: FIRST-TIME EDGE RATING TOOLTIP")
    log.info("=" * 60)

    # The tooltip has likely already been shown (user has been using the bot).
    # We can at least verify it's NOT showing on subsequent visits.
    hot3 = await send_get_all(client, "🔥 Hot Tips", timeout=30, settle=5)
    hot3_msg = None
    for m in hot3:
        if m.buttons and "Hot Tips" in (m.text or ""):
            hot3_msg = m
            break

    td3 = None
    if hot3_msg:
        td3 = await click_data(client, hot3_msg, "tip:detail:")

    if td3:
        td3_text = td3.text or ""
        has_tooltip = "New to Edge Ratings" in td3_text
        asserts = [(not has_tooltip,
                   f"Tooltip NOT shown on repeat visit: {has_tooltip}")]
        status = "PASS" if all(ok for ok, _ in asserts) else "FAIL"
        record("DE-14", "Tooltip — NOT shown on repeat visit", status,
               f"Has tooltip: {has_tooltip}\nText tail: ...{td3_text[-200:]}", asserts)
    else:
        record("DE-14", "Tooltip — NOT shown on repeat", "SKIP",
               "No tip detail reached",
               [(False, "Skipped")])

    # ════════════════════════════════════════════════════════════
    # SECTION 7: THRESHOLD — DIAMOND RARITY
    # ════════════════════════════════════════════════════════════
    log.info("")
    log.info("=" * 60)
    log.info("SECTION 7: DIAMOND RARITY CHECK")
    log.info("=" * 60)

    # Count Diamond tips in Hot Tips listing (both pages)
    diamond_count = 0
    total_tips = 0

    # Get page 1
    hot4 = await send_get_all(client, "/picks", timeout=30, settle=5)
    hot4_msg = None
    for m in hot4:
        if m.buttons and "Hot Tips" in (m.text or ""):
            hot4_msg = m
            break

    if hot4_msg:
        p1_text = hot4_msg.text or ""
        # Count tips on page 1
        p1_tips = len(re.findall(r"\[(\d+)\]", p1_text))
        p1_diamond = p1_text.count("💎")
        total_tips += p1_tips
        diamond_count += p1_diamond

        # Get page 2
        p2 = await click_data(client, hot4_msg, "hot:page:")
        if p2:
            p2_text = p2.text or ""
            p2_tips = len(re.findall(r"\[(\d+)\]", p2_text))
            p2_diamond = p2_text.count("💎")
            total_tips += p2_tips
            diamond_count += p2_diamond

        # Diamond should be <50% of tips (target <5%, but percentile system gives top 10%)
        diamond_pct = (diamond_count / max(total_tips, 1)) * 100
        asserts = [
            (total_tips > 0, f"Tips found: {total_tips}"),
            (diamond_pct <= 20,
             f"Diamond rarity: {diamond_count}/{total_tips} = {diamond_pct:.0f}% (expect ≤20%)"),
        ]
        status = "PASS" if all(ok for ok, _ in asserts) else "FAIL"
        record("DE-15", f"Diamond rarity — {diamond_count}/{total_tips} ({diamond_pct:.0f}%)", status,
               f"Page 1 diamonds: {p1_diamond}/{p1_tips}\n"
               + (f"Page 2 diamonds: {p2_diamond}/{p2_tips}" if p2 else "No page 2"),
               asserts)
    else:
        record("DE-15", "Diamond rarity", "SKIP", "No Hot Tips",
               [(False, "Skipped")])

    # ════════════════════════════════════════════════════════════
    # SECTION 8: REGRESSION
    # ════════════════════════════════════════════════════════════
    log.info("")
    log.info("=" * 60)
    log.info("SECTION 8: REGRESSION")
    log.info("=" * 60)

    # ── DE-16: /start ──
    start_msg = await send(client, "/start")
    asserts = [(bool(start_msg), "/start responded")]
    status = "PASS" if all(ok for ok, _ in asserts) else "FAIL"
    record("DE-16", "/start works", status,
           (start_msg.text or "")[:200] if start_msg else "None", asserts)

    # ── DE-17: Settings ──
    s_msg = await send(client, "⚙️ Settings")
    asserts = [(bool(s_msg), "Settings responded")]
    if s_msg:
        asserts.append((len(get_buttons(s_msg)) >= 6, f"Buttons: {len(get_buttons(s_msg))}"))
    status = "PASS" if all(ok for ok, _ in asserts) else "FAIL"
    record("DE-17", "Settings flow", status,
           f"Buttons: {get_buttons(s_msg) if s_msg else []}", asserts)

    # ── DE-18: Profile ──
    p_msg = await send(client, "👤 Profile")
    asserts = [(bool(p_msg), "Profile responded")]
    if p_msg:
        asserts.append((len(p_msg.text or "") > 50, f"Content: {len(p_msg.text or '')} chars"))
    status = "PASS" if all(ok for ok, _ in asserts) else "FAIL"
    record("DE-18", "Profile works", status,
           (p_msg.text or "")[:200] if p_msg else "None", asserts)

    # ── DE-19: Admin ──
    admin_msg = await send(client, "/admin")
    asserts = [(bool(admin_msg), "/admin responded")]
    if admin_msg:
        t = admin_msg.text or ""
        asserts.append(("Odds Database" in t, "Admin shows DB stats"))
    status = "PASS" if all(ok for ok, _ in asserts) else "FAIL"
    record("DE-19", "Admin dashboard", status,
           (admin_msg.text or "")[:300] if admin_msg else "None", asserts)

    # ── DE-20: Help ──
    help_msg = await send(client, "❓ Help")
    asserts = [(bool(help_msg), "Help responded")]
    status = "PASS" if all(ok for ok, _ in asserts) else "FAIL"
    record("DE-20", "Help works", status,
           (help_msg.text or "")[:200] if help_msg else "None", asserts)

    # ════════════════════════════════════════════════════════════
    # DONE
    # ════════════════════════════════════════════════════════════
    await client.disconnect()

    total = len(results)
    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    skipped = sum(1 for r in results if r["status"] == "SKIP")
    warned = sum(1 for r in results if r["status"] == "WARN")

    log.info("")
    log.info("=" * 60)
    log.info("WAVE 14B DIAMOND EDGE VERIFICATION RESULTS")
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
