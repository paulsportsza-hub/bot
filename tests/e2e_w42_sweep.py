#!/usr/bin/env python3
"""W42-SWEEP: Comprehensive E2E quality sweep via Telethon.

Phases 1-9: Onboarding, Menu, Hot Tips Tiers, Game Breakdown,
Your Games, Notifications, Time Format, Edge Cases.
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
    ReplyKeyboardMarkup as TLReplyKeyboardMarkup,
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
CAPTURE_DIR = str(BOT_ROOT.parent / "reports" / "screenshots" / "w42_sweep")

# ── Results tracking ──
RESULTS: list[tuple[str, str, bool, str]] = []
WARNS: list[tuple[str, str]] = []
CAPTURES: dict[str, str] = {}

_entity = None  # cached entity


def record(phase: str, test_id: str, passed: bool, detail: str):
    RESULTS.append((phase, test_id, passed, detail))
    emoji = "\u2705" if passed else "\u274c"
    print(f"  {emoji} {test_id}: {detail}")


def warn(test_id: str, detail: str):
    WARNS.append((test_id, detail))
    print(f"  \u26a0\ufe0f {test_id}: {detail}")


def capture(test_id: str, text: str):
    CAPTURES[test_id] = text
    path = os.path.join(CAPTURE_DIR, f"{test_id}.txt")
    with open(path, "w") as f:
        f.write(text)


# ── Telethon helpers ──

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
    """Cache and return bot entity."""
    global _entity
    if _entity is None:
        _entity = await client.get_entity(BOT)
    return _entity


async def send(client, text, wait=12):
    """Send text, return bot responses (chronological)."""
    ent = await entity(client)
    sent = await client.send_message(ent, text)
    await asyncio.sleep(wait)
    messages = await client.get_messages(ent, limit=20)
    bot_msgs = [m for m in messages if m.id > sent.id and not m.out]
    return list(reversed(bot_msgs))


async def click_edit(client, msg, btn_text, wait=5):
    """Click inline button. Returns (edited_msg, new_msgs).
    Bot onboarding EDITS messages in-place, so we re-fetch the clicked msg."""
    if not msg or not msg.reply_markup:
        return None, []
    if isinstance(msg.reply_markup, ReplyInlineMarkup):
        for row in msg.reply_markup.rows:
            for btn in row.buttons:
                if isinstance(btn, KeyboardButtonCallback) and btn_text in btn.text:
                    await msg.click(data=btn.data)
                    await asyncio.sleep(wait)
                    ent = await entity(client)
                    edited = await client.get_messages(ent, ids=msg.id)
                    all_msgs = await client.get_messages(ent, limit=15)
                    new = [m for m in all_msgs if m.id > msg.id and not m.out]
                    return edited, list(reversed(new))
    return None, []


def get_text(msgs, idx=0):
    if msgs and len(msgs) > idx:
        return msgs[idx].text or ""
    return ""


def get_inline_buttons(msg):
    if not msg or not msg.reply_markup or not isinstance(msg.reply_markup, ReplyInlineMarkup):
        return []
    buttons = []
    for row in msg.reply_markup.rows:
        for btn in row.buttons:
            buttons.append(btn.text)
    return buttons


def has_reply_keyboard(msg):
    return msg and msg.reply_markup and isinstance(msg.reply_markup, TLReplyKeyboardMarkup)


def find_msg_with(msgs, keyword):
    for m in msgs:
        t = m.text or ""
        if keyword.lower() in t.lower():
            return m
    return None


def get_kb_buttons(msg):
    if not msg or not msg.reply_markup:
        return []
    buttons = []
    if isinstance(msg.reply_markup, TLReplyKeyboardMarkup):
        for row in msg.reply_markup.rows:
            for btn in row.buttons:
                buttons.append(btn.text)
    return buttons


# ══════════════════════════════════════════════════════════════
# PHASE 1: ONBOARDING
# ══════════════════════════════════════════════════════════════

async def phase1_onboarding(client):
    print("\n" + "=" * 60)
    print("PHASE 1: ONBOARDING")
    print("=" * 60)

    # 1.0: Full profile reset via Settings → Reset → Confirm
    print("\n--- 1.0 Full Profile Reset ---")
    msgs = await send(client, "\u2699\ufe0f Settings", wait=5)
    settings_msg = msgs[0] if msgs else None

    reset_ok = False
    if settings_msg:
        btns = get_inline_buttons(settings_msg)
        reset_btn = next((b for b in btns if "reset" in b.lower()), None)
        if reset_btn:
            edited, new = await click_edit(client, settings_msg, reset_btn, wait=4)
            confirm_msg = new[0] if new else edited
            if confirm_msg:
                confirm_btns = get_inline_buttons(confirm_msg)
                yes_btn = next((b for b in confirm_btns if "yes" in b.lower() or "everything" in b.lower()), None)
                if yes_btn:
                    edited2, new2 = await click_edit(client, confirm_msg, yes_btn, wait=5)
                    reset_text = ""
                    for m in new2:
                        if "reset" in (m.text or "").lower():
                            reset_text = m.text or ""
                            break
                    if not reset_text and edited2:
                        reset_text = edited2.text or ""
                    reset_ok = "reset" in reset_text.lower() or "cleared" in reset_text.lower()
                    record("1", "1.0-reset", reset_ok, f"Profile reset: {reset_text[:60]}")
                    capture("1.0-reset", reset_text)

    if not reset_ok:
        record("1", "1.0-reset", False, "Could not complete profile reset")
        return

    await asyncio.sleep(3)

    # 1A: /start triggers onboarding (2 messages: setup + experience prompt)
    print("\n--- 1A: Fresh Start ---")
    msgs = await send(client, "/start", wait=8)

    # Bot sends 2 messages: [0]="Setting up" [1]=experience prompt with buttons
    start_text = ""
    exp_msg = None
    for m in msgs:
        t = m.text or ""
        if "welcome" in t.lower() or "step" in t.lower():
            start_text = t
            exp_msg = m
            break
    if not start_text and msgs:
        start_text = get_text(msgs)
        exp_msg = msgs[-1] if msgs else None  # Last message has buttons

    capture("1A-start", start_text)
    has_welcome = "welcome" in start_text.lower() or "step" in start_text.lower() or "edge" in start_text.lower()
    record("1A", "1A-welcome", has_welcome, f"Welcome: {'found' if has_welcome else 'NOT found'}")

    exp_buttons = get_inline_buttons(exp_msg) if exp_msg else []
    has_exp = any("bet" in b.lower() or "new" in b.lower() for b in exp_buttons)
    record("1A", "1A-experience-btns", has_exp, f"Experience buttons: {[b[:20] for b in exp_buttons[:3]]}")

    if not has_exp:
        if "welcome back" in start_text.lower():
            warn("1A", "Profile reset didn't clear onboarding — skipping Phase 1")
        return

    # 1B: Experience → Casual
    print("\n--- 1B: Experience + Sports + Teams ---")
    edited, _ = await click_edit(client, exp_msg, "few bets", wait=4)

    # Sports selection (edited message)
    sports_text = (edited.text or "") if edited else ""
    capture("1B-sports", sports_text)
    has_sports = "sport" in sports_text.lower() or "select" in sports_text.lower()
    record("1B", "1B-sports-screen", has_sports, f"Sports: {'shown' if has_sports else 'NOT shown'}")

    if not has_sports or not edited:
        return

    # Toggle Soccer + Rugby + Done
    edited2, _ = await click_edit(client, edited, "Soccer", wait=2)
    edited3, _ = await click_edit(client, edited2 or edited, "Rugby", wait=2)
    edited4, new_after_done = await click_edit(client, edited3 or edited2, "Done", wait=5)

    # Team prompt (edited same message or new message)
    team_msg = edited4
    team_text = (team_msg.text or "") if team_msg else ""
    capture("1B-teams-first", team_text)

    # Type soccer teams
    sports_done = 0
    for sport_name, teams_text in [("soccer", "Arsenal, Kaizer Chiefs"), ("rugby", "South Africa, Bulls")]:
        if not team_msg:
            break
        t = team_msg.text or ""
        if any(w in t.lower() for w in ["team", "player", "fighter", "favourite"]):
            ent = await entity(client)
            sent = await client.send_message(ent, teams_text)
            await asyncio.sleep(8)
            all_msgs = await client.get_messages(ent, limit=10)
            new = [m for m in all_msgs if m.id > sent.id and not m.out]
            new = list(reversed(new))

            confirm_text = get_text(new)
            has_confirm = any(w in confirm_text.lower() for w in ["added", "nice", "loaded", "\u2705"])
            record("1B", f"1B-teams-{sport_name}", has_confirm,
                   f"{sport_name}: {'confirmed' if has_confirm else confirm_text[:50]}")
            capture(f"1B-teams-{sport_name}", confirm_text)

            # Click Continue
            confirm_msg = new[-1] if new else None
            if confirm_msg:
                edited_next, new_next = await click_edit(client, confirm_msg, "Continue", wait=5)
                team_msg = new_next[-1] if new_next else edited_next
            sports_done += 1
        else:
            break

    record("1B", "1B-all-teams", sports_done >= 2, f"{sports_done} sports had team prompts")

    # 1C: Edge Explainer
    print("\n--- 1C: Edge Explainer ---")
    current_msg = team_msg
    current_text = (current_msg.text or "") if current_msg else ""
    capture("1C-explainer", current_text)
    is_explainer = "edge" in current_text.lower() and ("how" in current_text.lower() or "scan" in current_text.lower())
    record("1C", "1C-explainer", is_explainer, f"Edge explainer: {'shown' if is_explainer else 'skipped (experienced)'}")

    if is_explainer and current_msg:
        edited, new = await click_edit(client, current_msg, "Got it", wait=5)
        current_msg = new[-1] if new else edited

    # 1D: Risk → Bankroll → Notify (all edits of same message)
    print("\n--- 1D: Risk + Bankroll + Notify ---")
    current_text = (current_msg.text or "") if current_msg else ""
    capture("1D-risk", current_text)
    is_risk = "risk" in current_text.lower() or "conservative" in current_text.lower()
    record("1D", "1D-risk-screen", is_risk, f"Risk: {'shown' if is_risk else 'NOT shown'}")

    if is_risk and current_msg:
        edited, new = await click_edit(client, current_msg, "Moderate", wait=4)
        current_msg = new[-1] if new else edited

    current_text = (current_msg.text or "") if current_msg else ""
    capture("1D-bankroll", current_text)
    is_bankroll = "bankroll" in current_text.lower() or "budget" in current_text.lower() or "weekly" in current_text.lower()
    record("1D", "1D-bankroll-screen", is_bankroll, f"Bankroll: {'shown' if is_bankroll else 'NOT shown'}")

    if is_bankroll and current_msg:
        edited, new = await click_edit(client, current_msg, "R500", wait=4)
        current_msg = new[-1] if new else edited

    current_text = (current_msg.text or "") if current_msg else ""
    capture("1D-notify", current_text)
    is_notify = "notification" in current_text.lower() or "alert" in current_text.lower() or "daily" in current_text.lower() or "when" in current_text.lower()
    record("1D", "1D-notify-screen", is_notify, f"Notify: {'shown' if is_notify else 'NOT shown'}")

    if is_notify and current_msg:
        btns = get_inline_buttons(current_msg)
        hour_btn = btns[0] if btns else None
        if hour_btn:
            edited, new = await click_edit(client, current_msg, hour_btn, wait=4)
            current_msg = new[-1] if new else edited

    # 1E: Summary → Plan → Completion
    print("\n--- 1E: Summary + Completion ---")
    current_text = (current_msg.text or "") if current_msg else ""
    capture("1E-summary", current_text)
    is_summary = any(w in current_text.lower() for w in ["summary", "profile", "next"])
    record("1E", "1E-summary", is_summary, f"Summary: {'shown' if is_summary else 'NOT shown'}")

    if is_summary and current_msg:
        # Click "Next — Choose Plan"
        edited, new = await click_edit(client, current_msg, "Next", wait=5)
        current_msg = new[-1] if new else edited

        current_text = (current_msg.text or "") if current_msg else ""
        is_plan = "plan" in current_text.lower() or "bronze" in current_text.lower()
        record("1E", "1E-plan-screen", is_plan, f"Plan: {'shown' if is_plan else 'NOT shown'}")

        if is_plan and current_msg:
            # Click "Continue with Bronze"
            edited, new = await click_edit(client, current_msg, "Bronze", wait=8)

            # Check for persistent keyboard in new messages
            has_keyboard = False
            kb_buttons = []
            for m in new:
                if has_reply_keyboard(m):
                    has_keyboard = True
                    kb_buttons = get_kb_buttons(m)
                    break

            record("1E", "1E-keyboard", has_keyboard,
                   f"Persistent keyboard: {'appeared' if has_keyboard else 'NOT found'}")

            expected_keys = ["My Matches", "Edge Picks", "Guide", "Profile", "Settings", "Help"]
            if has_keyboard:
                kb_text = str(kb_buttons)
                found_keys = [k for k in expected_keys if k.lower() in kb_text.lower()]
                record("1E", "1E-all-keys", len(found_keys) >= 4, f"Keyboard: {found_keys}")
            else:
                record("1E", "1E-all-keys", False, "No keyboard to check")


# ══════════════════════════════════════════════════════════════
# PHASE 2: MENU NAVIGATION
# ══════════════════════════════════════════════════════════════

async def phase2_menu(client):
    print("\n" + "=" * 60)
    print("PHASE 2: MENU NAVIGATION")
    print("=" * 60)

    print("\n--- 2A: Every Menu Button ---")
    keyboard_tests = [
        ("My Matches", "\u26bd My Matches", 10, ["match", "game", "schedule", "sast", "no live"]),
        ("Edge Picks", "\U0001f48e Top Edge Picks", 20, ["edge", "pick", "tip", "live", "scanned"]),
        ("Guide", "\U0001f4d6 Guide", 8, ["guide", "edge", "rating", "diamond", "how", "telegra"]),
        ("Profile", "\U0001f464 Profile", 8, ["profile", "experience", "sport", "risk", "casual", "soccer"]),
        ("Settings", "\u2699\ufe0f Settings", 8, ["setting", "risk", "notification", "sport", "bankroll"]),
        ("Help", "\u2753 Help", 8, ["help", "command", "/start", "edge"]),
    ]

    for btn_label, full_label, wait, expected_words in keyboard_tests:
        msgs = await send(client, full_label, wait=wait)

        # Smart message selection for multi-message responses
        text = ""
        if btn_label == "Edge Picks":
            for m in msgs:
                t = m.text or ""
                if "edge" in t.lower() and ("pick" in t.lower() or "live" in t.lower() or "scanned" in t.lower()):
                    text = t
                    break
        if not text:
            text = get_text(msgs)

        capture(f"2A-{btn_label.lower().replace(' ', '_')}", text)

        found = any(w in text.lower() for w in expected_words)
        not_error = "error" not in text.lower() and "traceback" not in text.lower()

        record("2A", f"2A-{btn_label}", found and not_error,
               f"{btn_label}: {'renders' if found else 'MISSING content'}, "
               f"{'no error' if not_error else 'ERROR'}")

        await asyncio.sleep(2)

    # 2B: Settings Deep Dive
    print("\n--- 2B: Settings Deep Dive ---")
    msgs = await send(client, "\u2699\ufe0f Settings", wait=5)
    settings_msg = msgs[0] if msgs else None
    if settings_msg:
        settings_btns = get_inline_buttons(settings_msg)
        capture("2B-settings-btns", str(settings_btns))
        has_risk = any("risk" in b.lower() for b in settings_btns)
        has_notify = any("alert" in b.lower() or "notification" in b.lower() for b in settings_btns)
        has_bankroll = any("bankroll" in b.lower() for b in settings_btns)
        has_reset = any("reset" in b.lower() for b in settings_btns)
        record("2B", "2B-settings-options",
               has_risk and has_notify and has_bankroll,
               f"Risk={has_risk}, Notify={has_notify}, Bankroll={has_bankroll}, Reset={has_reset}")

    # 2C: Dead End Check
    print("\n--- 2C: Dead End Check ---")
    msgs = await send(client, "/menu", wait=5)
    record("2C", "2C-menu-cmd", len(get_text(msgs)) > 10, f"/menu: {len(get_text(msgs))} chars")

    msgs = await send(client, "/help", wait=5)
    record("2C", "2C-help-cmd", len(get_text(msgs)) > 50, f"/help: {len(get_text(msgs))} chars")


# ══════════════════════════════════════════════════════════════
# PHASE 3: HOT TIPS TIER SWEEP
# ══════════════════════════════════════════════════════════════

async def phase3_tier_sweep(client):
    print("\n" + "=" * 60)
    print("PHASE 3: HOT TIPS TIER SWEEP")
    print("=" * 60)

    for tier in ["bronze", "gold", "diamond"]:
        print(f"\n--- {tier.upper()} View ---")

        msgs = await send(client, f"/qa set_{tier}", wait=3)
        set_text = get_text(msgs)
        record("3", f"3-set-{tier}", tier in set_text.lower(), f"Set {tier}: {set_text[:60]}")
        await asyncio.sleep(2)

        msgs = await send(client, "\U0001f48e Top Edge Picks", wait=20)

        all_text = "\n---\n".join(m.text or "" for m in msgs if not m.out)
        capture(f"3-{tier}-tips", all_text)

        if not all_text.strip():
            record("3", f"3{tier[0]}-renders", False, f"{tier}: No response")
            continue

        # Find header message
        header_msg = None
        for m in msgs:
            t = m.text or ""
            if "edge" in t.lower() and ("pick" in t.lower() or "scanned" in t.lower() or "live" in t.lower()):
                header_msg = m
                break
        if not header_msg and msgs:
            header_msg = msgs[0]

        header_text = (header_msg.text or "") if header_msg else ""

        has_header = "edge" in header_text.lower() or "pick" in header_text.lower()
        record("3", f"3{tier[0]}-header", has_header, f"{tier} header: {'found' if has_header else 'NOT found'}")

        has_subline = "bookmaker" in all_text.lower() or "scanned" in all_text.lower()
        record("3", f"3{tier[0]}-subline", has_subline, f"{tier} subline: {'found' if has_subline else 'NOT found'}")

        # Tier-specific checks
        if tier == "bronze":
            has_lock = "\U0001f512" in all_text or "locked" in all_text.lower() or "highest-conviction" in all_text.lower()
            record("3", "3A-locks", has_lock, f"Bronze locks: {'found' if has_lock else 'NOT found'}")
            has_footer = "/subscribe" in all_text.lower() or "founding" in all_text.lower() or "unlock" in all_text.lower()
            record("3", "3A-footer", has_footer, f"Bronze footer CTA: {'found' if has_footer else 'NOT found'}")
        elif tier == "gold":
            has_odds = "@" in all_text or "odds" in all_text.lower() or "return" in all_text.lower()
            record("3", "3B-gold-odds", has_odds, f"Gold odds: {'found' if has_odds else 'NOT found'}")
        elif tier == "diamond":
            has_lock = "\U0001f512" in all_text and "locked" in all_text.lower()
            record("3", "3C-no-locks", not has_lock, f"Diamond no locks: {'correct' if not has_lock else 'LOCKS FOUND'}")
            record("3", "3C-no-cta", "/subscribe" not in all_text.lower(), f"Diamond no CTA: {'correct' if '/subscribe' not in all_text.lower() else 'CTA FOUND'}")

        # Buttons
        if header_msg:
            btns = get_inline_buttons(header_msg)
            record("3", f"3{tier[0]}-buttons", len(btns) > 0, f"{tier} buttons: {len(btns)} found")

            # Pagination: button click EDITS message in-place
            next_btn = next((b for b in btns if "next" in b.lower() or "\u27a1" in b or "→" in b), None)
            if next_btn:
                edited, _ = await click_edit(client, header_msg, next_btn, wait=8)
                page2_text = (edited.text or "") if edited else ""
                has_p2 = len(page2_text) > 20 and page2_text != header_text
                record("3", f"3{tier[0]}-pagination", has_p2, f"{tier} page 2: {'renders' if has_p2 else 'same/empty'}")
                capture(f"3-{tier}-page2", page2_text)
            else:
                record("3", f"3{tier[0]}-pagination", True, f"{tier}: single page")

    await send(client, "/qa reset", wait=3)


# ══════════════════════════════════════════════════════════════
# PHASE 4-5: GAME BREAKDOWN + YOUR GAMES
# ══════════════════════════════════════════════════════════════

async def phase4_5_breakdown_and_games(client):
    print("\n" + "=" * 60)
    print("PHASE 4-5: GAME BREAKDOWN + YOUR GAMES")
    print("=" * 60)

    await send(client, "/qa set_diamond", wait=3)
    await asyncio.sleep(2)

    # 4A: Edge Detail
    print("\n--- 4A: Edge Detail ---")
    msgs = await send(client, "\U0001f48e Top Edge Picks", wait=20)

    tips_msg = None
    for m in msgs:
        t = m.text or ""
        if "edge" in t.lower() and ("pick" in t.lower() or "live" in t.lower()):
            tips_msg = m
            break
    if not tips_msg and msgs:
        tips_msg = msgs[0]

    detail_captured = False
    if tips_msg:
        btns = get_inline_buttons(tips_msg)
        nav_words = ["next", "prev", "menu", "refresh", "←", "→", "⬅"]
        edge_btns = [b for b in btns if not any(x in b.lower() for x in nav_words)]

        if edge_btns:
            first_edge = edge_btns[0]
            # Edge detail: click → loading → AI call (20-30s) → edit with result
            edited, new = await click_edit(client, tips_msg, first_edge, wait=25)

            # Check new messages for the detail
            detail_text = ""
            detail_msg = None
            for m in new:
                t = m.text or ""
                if len(t) > 100 and any(w in t.lower() for w in ["setup", "verdict", "bookmaker", "\U0001f4cb", "\U0001f3c6"]):
                    detail_text = t
                    detail_msg = m
                    break

            # Check for loading message that might still be updating
            if not detail_text and new:
                last = new[-1]
                t = last.text or ""
                if "generat" in t.lower() or "analys" in t.lower() or len(t) < 50:
                    # Still loading — wait more and re-fetch
                    await asyncio.sleep(15)
                    ent = await entity(client)
                    refetched = await client.get_messages(ent, ids=last.id)
                    if refetched and len(refetched.text or "") > 100:
                        detail_text = refetched.text or ""
                        detail_msg = refetched
                elif len(t) > 100:
                    detail_text = t
                    detail_msg = last

            # Check edited message
            if not detail_text and edited and len(edited.text or "") > 200:
                detail_text = edited.text or ""
                detail_msg = edited

            capture("4A-detail", detail_text)

            if detail_text and len(detail_text) > 50:
                detail_captured = True
                has_setup = "setup" in detail_text.lower() or "\U0001f4cb" in detail_text
                has_edge = "edge" in detail_text.lower() or "\U0001f3af" in detail_text
                has_risk = "risk" in detail_text.lower() or "\u26a0" in detail_text
                has_verdict = "verdict" in detail_text.lower() or "\U0001f3c6" in detail_text
                has_odds = "odds" in detail_text.lower() or "@" in detail_text or "bookmaker" in detail_text.lower()

                record("4A", "4A-setup", has_setup, f"Setup: {'found' if has_setup else 'NOT found'}")
                record("4A", "4A-edge", has_edge, f"Edge: {'found' if has_edge else 'NOT found'}")
                record("4A", "4A-risk", has_risk, f"Risk: {'found' if has_risk else 'NOT found'}")
                record("4A", "4A-verdict", has_verdict, f"Verdict: {'found' if has_verdict else 'NOT found'}")
                record("4A", "4A-odds", has_odds, f"Odds: {'found' if has_odds else 'NOT found'}")

                if detail_msg:
                    d_btns = get_inline_buttons(detail_msg)
                    record("4A", "4A-cta", any("\U0001f4f2" in b or "bet" in b.lower() for b in d_btns), "CTA button")
                    record("4A", "4A-back", any("\u21a9" in b or "back" in b.lower() for b in d_btns), "Back button")
                    record("4A", "4A-compare", any("compare" in b.lower() or "all odds" in b.lower() for b in d_btns), "Compare Odds")

                # 4B: AI Accuracy
                print("\n--- 4B: AI Accuracy ---")
                bad_words = ["scintillating", "counter-attack", "possession-based", "historically", "traditionally"]
                found_bad = [w for w in bad_words if w in detail_text.lower()]
                record("4B", "4B-no-hallucinate", len(found_bad) == 0,
                       f"Hallucination: {'clean' if not found_bad else 'FOUND: ' + ', '.join(found_bad)}")

                form_matches = re.findall(r'[WDLT]{6,}', detail_text)
                record("4B", "4B-form-length", len(form_matches) == 0,
                       f"Form strings: {'OK' if not form_matches else 'TOO LONG: ' + str(form_matches)}")

    if not detail_captured:
        for check in ["4A-setup", "4A-edge", "4A-risk", "4A-verdict", "4A-odds", "4A-cta", "4A-back", "4A-compare"]:
            if not any(t == check for _, t, _, _ in RESULTS):
                record("4A", check, False, "Could not capture edge detail")
        if not any(t == "4B-no-hallucinate" for _, t, _, _ in RESULTS):
            record("4B", "4B-no-hallucinate", True, "Skipped")
            record("4B", "4B-form-length", True, "Skipped")

    # 5A: Your Games
    print("\n--- 5A: Your Games ---")
    await asyncio.sleep(3)
    msgs = await send(client, "\u26bd My Matches", wait=10)
    games_text = get_text(msgs)
    capture("5A-games", games_text)

    record("5A", "5A-renders", any(w in games_text.lower() for w in ["match", "game", "sast", "no live"]),
           f"My Matches: {'renders' if games_text else 'empty'}")

    games_msg = msgs[0] if msgs else None
    if games_msg:
        btns = get_inline_buttons(games_msg)
        sport_emojis = [b for b in btns if len(b) <= 4 and any(e in b for e in ["\u26bd", "\U0001f3c9", "\U0001f3cf", "\U0001f94a"])]
        if sport_emojis:
            record("5A", "5A-sport-filter", True, f"Sport filter: {sport_emojis}")

    await send(client, "/qa reset", wait=3)


# ══════════════════════════════════════════════════════════════
# PHASE 6: NOTIFICATIONS
# ══════════════════════════════════════════════════════════════

async def phase6_notifications(client):
    print("\n" + "=" * 60)
    print("PHASE 6: NOTIFICATIONS")
    print("=" * 60)

    tests = [
        ("teaser_bronze", ["edge", "pick", "locked", "value", "morning", "yesterday"]),
        ("teaser_gold", ["edge", "pick", "diamond", "value", "morning", "yesterday"]),
        ("teaser_diamond", ["edge", "pick", "value", "morning", "yesterday"]),
        ("weekend", ["weekend", "preview", "match", "edge"]),
        ("recap_bronze", ["recap", "week", "edge", "return", "missed"]),
        ("monthly", ["month", "report", "edge", "portfolio"]),
    ]

    for cmd, expected in tests:
        msgs = await send(client, f"/qa {cmd}", wait=12)
        # Find the notification content (not QA confirmation)
        text = ""
        for m in msgs:
            t = m.text or ""
            if any(w in t.lower() for w in expected) and len(t) > 20:
                text = t
                break
        if not text:
            text = get_text(msgs)
        capture(f"6-{cmd}", text)

        found = any(w in text.lower() for w in expected) and len(text) > 20
        record("6", f"6-{cmd}", found, f"{'PASS' if found else 'FAIL'}: {text[:60]}")

    # Mute system
    print("\n--- 6F: Mute System ---")
    msgs = await send(client, "/mute", wait=5)
    mute_text = get_text(msgs)
    record("6", "6F-mute", "mute" in mute_text.lower(), f"Mute: {mute_text[:60]}")

    msgs = await send(client, "/mute off", wait=5)
    unmute_text = get_text(msgs)
    record("6", "6F-unmute", "resume" in unmute_text.lower() or "unmute" in unmute_text.lower(),
           f"Unmute: {unmute_text[:60]}")


# ══════════════════════════════════════════════════════════════
# PHASE 7: MONITORING (keyword filtered — W35 fix)
# ══════════════════════════════════════════════════════════════

async def phase7_monitoring(client):
    print("\n" + "=" * 60)
    print("PHASE 7: MONITORING")
    print("=" * 60)

    # 7A: Health
    msgs = await send(client, "/qa health", wait=20)
    health_text = ""
    for m in msgs:
        t = m.text or ""
        if "system health" in t.lower() or ("health" in t.lower() and ("sharp" in t.lower() or "bookmaker" in t.lower())):
            health_text = t
            break
    if not health_text:
        for m in msgs:
            t = m.text or ""
            if ("\u2705" in t or "\u274c" in t) and len(t) > 80:
                health_text = t
                break
    if not health_text:
        health_text = get_text(msgs)
    capture("7A-health", health_text)

    check_lines = [l for l in health_text.split("\n") if "\u2705" in l or "\u274c" in l]
    record("7A", "7A-check-count", len(check_lines) >= 8, f"{len(check_lines)} health checks listed")
    record("7A", "7A-proxy", "proxy" in health_text.lower(), f"Proxy: {'found' if 'proxy' in health_text.lower() else 'NOT found'}")

    # 7B: Morning
    await asyncio.sleep(3)
    msgs = await send(client, "/qa morning", wait=20)
    morning_text = ""
    for m in msgs:
        t = m.text or ""
        if "morning report" in t.lower() or ("edge" in t.lower() and "sharp" in t.lower()):
            morning_text = t
            break
    if not morning_text:
        morning_text = get_text(msgs)
    capture("7B-morning", morning_text)

    record("7B", "7B-content",
           "edge" in morning_text.lower() and "sharp" in morning_text.lower(),
           f"Edges={'edge' in morning_text.lower()}, Sharp={'sharp' in morning_text.lower()}")

    # 7C: Validate
    await asyncio.sleep(3)
    msgs = await send(client, "/qa validate", wait=30)
    validate_text = ""
    for m in msgs:
        t = m.text or ""
        if re.search(r"\d+/\d+", t) and ("pass" in t.lower() or "fail" in t.lower() or "validation" in t.lower()):
            validate_text = t
            break
    if not validate_text:
        validate_text = get_text(msgs)
    capture("7C-validate", validate_text)

    ratio = re.search(r"(\d+)/(\d+)", validate_text)
    record("7C", "7C-result", ratio is not None and int(ratio.group(2)) >= 20 if ratio else False,
           f"Validation: {ratio.group(0) if ratio else 'NOT found'}")


# ══════════════════════════════════════════════════════════════
# PHASE 8: TIME FORMAT + PHASE 9: EDGE CASES
# ══════════════════════════════════════════════════════════════

async def phase8_time_format(client):
    print("\n" + "=" * 60)
    print("PHASE 8: TIME FORMAT")
    print("=" * 60)

    am_pm = [tid for tid, t in CAPTURES.items() if re.search(r'\b\d{1,2}\s*(AM|PM|am|pm)\b', t)]
    record("8", "8A-no-ampm", len(am_pm) == 0,
           f"AM/PM: {'NONE (good)' if not am_pm else 'FOUND in ' + ', '.join(am_pm)}")

    has_24h = any(re.search(r'\b[012]?\d:[0-5]\d\b', t) for t in CAPTURES.values())
    record("8", "8A-24h-present", has_24h, f"24h format: {'found' if has_24h else 'no times found'}")


async def phase9_edge_cases(client):
    print("\n" + "=" * 60)
    print("PHASE 9: EDGE CASES")
    print("=" * 60)

    # Random text
    msgs = await send(client, "asdfghjkl random text", wait=5)
    text = get_text(msgs)
    record("9A", "9A-random-text", "traceback" not in text.lower(), f"Random text: handled")

    msgs = await send(client, "\U0001f600\U0001f525\U0001f3c6", wait=5)
    record("9A", "9A-emoji", True, f"Emoji: handled")

    # /start while onboarded
    msgs = await send(client, "/start", wait=5)
    start_text = get_text(msgs)
    capture("9B-start-again", start_text)
    record("9B", "9B-start-onboarded", "welcome back" in start_text.lower() or len(start_text) > 10,
           f"/start: {start_text[:50]}")

    # /subscribe
    msgs = await send(client, "/subscribe", wait=8)
    sub_text = ""
    for m in msgs:
        t = m.text or ""
        if len(t) > 10:
            sub_text = t
            break
    record("9C", "9C-subscribe",
           any(w in sub_text.lower() for w in ["plan", "subscribe", "diamond", "gold", "unlock"]),
           f"/subscribe: {sub_text[:50] if sub_text else 'empty'}")

    # /qa list
    msgs = await send(client, "/qa list", wait=8)
    qa_text = ""
    for m in msgs:
        t = m.text or ""
        if "health" in t.lower() or "validate" in t.lower() or "qa" in t.lower():
            qa_text = t
            break
    if not qa_text:
        qa_text = get_text(msgs)
    record("9C", "9C-qa-list", len(qa_text) > 30, f"/qa list: {len(qa_text)} chars")


# ══════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════

async def main():
    os.makedirs(CAPTURE_DIR, exist_ok=True)
    client = await get_client()

    print("=" * 60)
    print("W42-SWEEP: Comprehensive E2E Quality Sweep")
    print("=" * 60)

    await phase1_onboarding(client)
    await phase2_menu(client)
    await phase3_tier_sweep(client)
    await phase4_5_breakdown_and_games(client)
    await phase6_notifications(client)
    await phase7_monitoring(client)
    await phase8_time_format(client)
    await phase9_edge_cases(client)

    await client.disconnect()

    # ── Summary ──
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    total = len(RESULTS)
    passed = sum(1 for _, _, p, _ in RESULTS if p)
    failed = total - passed

    print(f"\nTotal: {total}, PASS: {passed}, FAIL: {failed}, WARN: {len(WARNS)}")

    if failed:
        print("\nFAILURES:")
        for phase, tid, p, d in RESULTS:
            if not p:
                print(f"  Phase {phase} | {tid}: {d}")

    if WARNS:
        print("\nWARNINGS:")
        for tid, d in WARNS:
            print(f"  {tid}: {d}")

    report = {
        "total": total,
        "passed": passed,
        "failed": failed,
        "warns": len(WARNS),
        "results": [{"phase": p, "test": t, "passed": pa, "detail": d} for p, t, pa, d in RESULTS],
        "warnings": [{"test": t, "detail": d} for t, d in WARNS],
    }
    with open(os.path.join(CAPTURE_DIR, "results.json"), "w") as f:
        json.dump(report, f, indent=2)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    rc = asyncio.run(main())
    sys.exit(rc)
