#!/usr/bin/env python3
"""Comprehensive E2E test: full onboarding + every feature.

Resets user profile, re-onboards with all 4 sports and many teams,
then tests every major bot feature. Captures all responses and flags issues.
"""

import asyncio
import json
import os
import sys
import time
from datetime import datetime

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.messages import GetBotCallbackAnswerRequest

load_dotenv("/home/paulsportsza/bot/.env")

API_ID = int(os.getenv("TELEGRAM_API_ID") or os.getenv("API_ID", "0"))
API_HASH = os.getenv("TELEGRAM_API_HASH") or os.getenv("API_HASH", "")
BOT_USERNAME = "mzansiedge_bot"

# Read StringSession
SESSION_STR = open("/home/paulsportsza/bot/data/telethon_session.string").read().strip()

REPORT_DIR = "/home/paulsportsza/reports"
TIMESTAMP = datetime.now().strftime("%Y%m%d-%H%M")
REPORT_FILE = f"{REPORT_DIR}/e2e-comprehensive-{TIMESTAMP}.txt"

issues: list[dict] = []
passes: list[str] = []
all_responses: list[dict] = []


def log(msg: str):
    print(msg)


def record_issue(phase: str, description: str, response_text: str = ""):
    issues.append({"phase": phase, "description": description, "response": response_text[:500]})
    log(f"  ❌ ISSUE: {description}")


def record_pass(check: str):
    passes.append(check)
    log(f"  ✅ PASS: {check}")


_me_cache = None

async def get_me(client):
    global _me_cache
    if _me_cache is None:
        _me_cache = await client.get_me()
    return _me_cache


# Track the timestamp of when the test started to filter stale messages
_test_start_ts = None

async def get_bot_response(client, wait=6, limit=5):
    """Wait and get the latest bot response(s), newest first.
    Only returns messages sent after the test started."""
    global _test_start_ts
    await asyncio.sleep(wait)
    messages = await client.get_messages(BOT_USERNAME, limit=limit)
    me = await get_me(client)
    # Filter: only bot messages, only after our last send
    bot_msgs = [m for m in messages if m.sender_id != me.id]
    return bot_msgs


def find_msg_with_buttons(msgs):
    """Find the first message that has inline keyboard buttons (not reply keyboard)."""
    from telethon.tl.types import ReplyInlineMarkup
    for m in msgs:
        if isinstance(m.reply_markup, ReplyInlineMarkup) and m.reply_markup.rows:
            return m
    # Fallback: any message with rows that have data
    for m in msgs:
        if m.reply_markup and hasattr(m.reply_markup, 'rows') and m.reply_markup.rows:
            # Check if any button has callback_data (inline) vs plain text (reply keyboard)
            for row in m.reply_markup.rows:
                for btn in row.buttons:
                    if hasattr(btn, 'data') and btn.data:
                        return m
    return msgs[0] if msgs else None


def find_msg_with_text(msgs, keyword):
    """Find message containing a keyword (case-insensitive)."""
    kw = keyword.lower()
    for m in msgs:
        if m.text and kw in m.text.lower():
            return m
    return None


def get_all_btn_info(msg):
    """Get all button texts and callback_data from a message."""
    result = []
    if msg and msg.reply_markup and hasattr(msg.reply_markup, 'rows'):
        for row in msg.reply_markup.rows:
            for btn in row.buttons:
                text = btn.text or ""
                data = ""
                if hasattr(btn, 'data') and btn.data:
                    data = btn.data.decode('utf-8', errors='ignore')
                result.append({"text": text, "data": data})
    return result


async def send_and_capture(client, text: str, wait=6, label=""):
    """Send a message and capture the bot's response.
    Only returns bot messages with ID > our sent message (no stale messages)."""
    log(f"\n→ Sending: {text[:80]}")
    sent_msg = await client.send_message(BOT_USERNAME, text)
    sent_id = sent_msg.id
    await asyncio.sleep(wait)
    messages = await client.get_messages(BOT_USERNAME, limit=20)
    me = await get_me(client)
    # Only bot messages with ID > our sent message (responses to THIS message)
    msgs = [m for m in messages if m.sender_id != me.id and m.id > sent_id]
    if not msgs:
        # Debug: show what messages we DID get
        all_ids = [(m.id, 'ME' if m.sender_id == me.id else 'BOT', (m.text or '')[:40]) for m in messages[:5]]
        log(f"  ⚠️ No new bot messages after ID {sent_id}. Recent: {all_ids}")
    for m in msgs:
        raw = m.text or m.raw_text or ""
        all_responses.append({"sent": text, "label": label, "response": raw[:2000]})
        if raw:
            log(f"  ← ({len(raw)}ch): {raw[:200]}...")
    return msgs


async def click_button(client, msg, button_text: str, wait=5):
    """Click an inline button by partial text match.
    Returns only NEW messages (with ID > the clicked message)."""
    if not msg or not msg.reply_markup:
        log(f"  ⚠️ No buttons on msg for: {button_text}")
        return []

    for row in msg.reply_markup.rows:
        for btn in row.buttons:
            btn_label = btn.text or ""
            if button_text.lower() in btn_label.lower():
                log(f"  🔘 Click: {btn_label}")
                ref_id = msg.id
                try:
                    await client(GetBotCallbackAnswerRequest(
                        peer=BOT_USERNAME, msg_id=msg.id, data=btn.data,
                    ))
                except Exception:
                    pass
                await asyncio.sleep(wait)
                messages = await client.get_messages(BOT_USERNAME, limit=20)
                me = await get_me(client)
                return [m for m in messages if m.sender_id != me.id and m.id >= ref_id]

    log(f"  ⚠️ Button '{button_text}' not found")
    return []


async def click_callback(client, msg, callback_data: str, wait=5):
    """Click an inline button by exact callback_data match.
    Returns messages with ID >= the clicked message (includes edits)."""
    if not msg or not msg.reply_markup:
        log(f"  ⚠️ No buttons for callback: {callback_data}")
        return []

    for row in msg.reply_markup.rows:
        for btn in row.buttons:
            if hasattr(btn, 'data') and btn.data:
                if btn.data.decode('utf-8', errors='ignore') == callback_data:
                    log(f"  🔘 Callback: {callback_data} → {btn.text}")
                    ref_id = msg.id
                    try:
                        await client(GetBotCallbackAnswerRequest(
                            peer=BOT_USERNAME, msg_id=msg.id, data=btn.data,
                        ))
                    except Exception:
                        pass
                    await asyncio.sleep(wait)
                    messages = await client.get_messages(BOT_USERNAME, limit=20)
                    me = await get_me(client)
                    return [m for m in messages if m.sender_id != me.id and m.id >= ref_id]

    log(f"  ⚠️ Callback '{callback_data}' not found in buttons: {get_all_btn_info(msg)}")
    return []


def check_response(text: str, phase: str, checks: dict):
    """Run multiple checks on a response text."""
    for check_name, (should_contain, is_positive) in checks.items():
        if is_positive:
            if should_contain in text:
                record_pass(f"[{phase}] {check_name}")
            else:
                record_issue(phase, f"{check_name}: expected '{should_contain}' not found", text)
        else:
            if should_contain in text:
                record_issue(phase, f"{check_name}: unwanted '{should_contain}' found", text)
            else:
                record_pass(f"[{phase}] {check_name}")


# ─────────────────────────────────────────────────────
# PHASE 0: Reset profile
# ─────────────────────────────────────────────────────
async def phase_0_reset(client):
    log("\n" + "="*60)
    log("PHASE 0: RESET PROFILE")
    log("="*60)

    # Send /start first to make sure bot is responsive
    msgs = await send_and_capture(client, "/start", wait=5, label="start_check")
    if not msgs:
        record_issue("reset", "Bot not responding to /start")
        return False

    # Go to settings
    msgs = await send_and_capture(client, "⚙️ Settings", wait=5, label="settings")
    if not msgs:
        record_issue("reset", "Settings not responding")
        return False

    # Find message with settings buttons
    settings_msg = find_msg_with_buttons(msgs)
    if not settings_msg:
        record_issue("reset", "No settings buttons found")
        return False

    # Click Reset Profile by callback_data
    result = await click_callback(client, settings_msg, "settings:reset", wait=5)
    if not result:
        # Try text match
        result = await click_button(client, settings_msg, "Reset", wait=5)
    if not result:
        record_issue("reset", "Reset Profile button not found")
        return False

    # Confirm reset
    confirm_msg = find_msg_with_buttons(result)
    if confirm_msg:
        result2 = await click_callback(client, confirm_msg, "settings:reset:confirm", wait=5)
        if not result2:
            result2 = await click_button(client, confirm_msg, "Yes", wait=5)
        if result2:
            record_pass("[reset] Profile reset confirmed")
            await asyncio.sleep(3)
            return True

    record_issue("reset", "Could not confirm reset")
    return False


# ─────────────────────────────────────────────────────
# PHASE 1: Full onboarding (from existing state)
# ─────────────────────────────────────────────────────
async def phase_1_onboarding_from_state(client, initial_msgs):
    """Onboarding when user is already at Step 1/5 (experience selection)."""
    log("\n" + "="*60)
    log("PHASE 1: FULL ONBOARDING (from current state)")
    log("="*60)

    return await _do_onboarding(client, initial_msgs)


# ─────────────────────────────────────────────────────
# PHASE 1: Full onboarding (after reset)
# ─────────────────────────────────────────────────────
async def phase_1_onboarding(client):
    log("\n" + "="*60)
    log("PHASE 1: FULL ONBOARDING")
    log("="*60)

    # Step 1: /start → Welcome
    msgs = await send_and_capture(client, "/start", wait=5, label="onboard_start")
    if not msgs:
        record_issue("onboarding", "No response to /start after reset")
        return False

    return await _do_onboarding(client, msgs)


async def _do_onboarding(client, msgs):
    """Shared onboarding logic — starts from experience selection screen."""

    # Find the message with experience buttons
    all_text = " ".join(m.text or "" for m in msgs)
    check_response(all_text, "onboarding", {
        "Welcome message present": ("MzansiEdge", True),
    })

    exp_msg = find_msg_with_buttons(msgs)
    if not exp_msg:
        # Bot may still be editing the message — wait and re-fetch
        log("  ⚠️ No buttons yet — waiting for bot to finish editing...")
        await asyncio.sleep(4)
        msgs = await get_bot_response(client, wait=2, limit=10)
        exp_msg = find_msg_with_buttons(msgs)
    if not exp_msg:
        record_issue("onboarding", "No buttons on welcome message")
        return False

    btns = get_all_btn_info(exp_msg)
    log(f"  Buttons: {[b['text'][:30] for b in btns]}")

    # Step 2: Experience level → Casual (callback: ob_exp:casual)
    result = await click_callback(client, exp_msg, "ob_exp:casual", wait=5)
    if not result:
        record_issue("onboarding", "Could not select experience level (ob_exp:casual)")
        return False
    record_pass("[onboarding] Experience level set to Casual")

    # Step 3: Sports selection — select ALL 4 sports
    sport_msg = find_msg_with_buttons(result)
    if not sport_msg:
        record_issue("onboarding", "No sports selection message")
        return False

    for sport_key in ["soccer", "rugby", "cricket", "combat"]:
        cb = f"ob_sport:{sport_key}"
        result = await click_callback(client, sport_msg, cb, wait=3)
        if result:
            sport_msg = find_msg_with_buttons(result) or sport_msg
            record_pass(f"[onboarding] Selected {sport_key}")
        else:
            record_issue("onboarding", f"Could not select {sport_key}")

    # Click "Done — Next step" (callback: ob_nav:sports_done)
    result = await click_callback(client, sport_msg, "ob_nav:sports_done", wait=5)
    if result:
        record_pass("[onboarding] Sports selection done")
    else:
        record_issue("onboarding", "Could not proceed past sports selection")
        return False

    # Step 4: Team input per sport
    # After sports_done, bot EDITS the message to show a text-input prompt.
    # User types teams → bot sends NEW confirmation message with Continue button.
    # After Continue, bot EDITS to show next sport's text-input prompt.
    team_inputs = [
        ("soccer", "Arsenal, Liverpool, Man United, Kaizer Chiefs, Orlando Pirates"),
        ("rugby", "South Africa, New Zealand, Ireland, Bulls, Stormers"),
        ("cricket", "South Africa, India, Australia, MI Cape Town, Paarl Royals"),
        ("combat", "Dricus Du Plessis, Israel Adesanya, Canelo Alvarez, Alex Pereira"),
    ]

    for sport_key, teams in team_inputs:
        # The bot is now waiting for text input for this sport.
        # Just type the teams directly — no need to find buttons first.
        await asyncio.sleep(2)
        log(f"\n  Sending teams for {sport_key}: {teams[:60]}...")

        # Send teams as text
        result = await send_and_capture(client, teams, wait=8, label=f"teams_{sport_key}")
        if result:
            # Check all messages for confirmation (✅ markers, "added", "nice")
            all_text = " ".join(m.text or "" for m in result)
            if "✅" in all_text or "added" in all_text.lower() or "nice" in all_text.lower():
                record_pass(f"[onboarding] Teams accepted for {sport_key}")
            else:
                record_issue("onboarding", f"Teams may not have been accepted for {sport_key}", all_text[:300])

            # Click "✅ Continue" (callback: ob_fav_done:{sport_key})
            confirm_msg = find_msg_with_buttons(result)
            if confirm_msg:
                cont = await click_callback(client, confirm_msg, f"ob_fav_done:{sport_key}", wait=5)
                if cont:
                    record_pass(f"[onboarding] Continued past {sport_key} teams")
                else:
                    # Fallback: try text match
                    cont = await click_button(client, confirm_msg, "Continue", wait=5)
                    if not cont:
                        cont = await click_button(client, confirm_msg, "Skip", wait=5)
            else:
                log(f"  ⚠️ No Continue button found for {sport_key}")
        else:
            record_issue("onboarding", f"No response to team input for {sport_key}")

    # Step 5: Edge explainer (casual users see this)
    await asyncio.sleep(3)
    msgs = await get_bot_response(client, wait=3, limit=5)
    edge_msg = find_msg_with_buttons(msgs)
    if edge_msg:
        edge_text = edge_msg.text or ""
        if "edge" in edge_text.lower() or "ai" in edge_text.lower() or "how" in edge_text.lower():
            record_pass("[onboarding] Edge explainer shown")
            result = await click_callback(client, edge_msg, "ob_nav:edge_done", wait=5)
            if not result:
                result = await click_button(client, edge_msg, "Got it", wait=5)
            if result:
                record_pass("[onboarding] Edge explainer acknowledged")

    # Step 6: Risk profile → Moderate
    await asyncio.sleep(2)
    msgs = await get_bot_response(client, wait=3, limit=5)
    risk_msg = find_msg_with_buttons(msgs)
    if risk_msg:
        risk_text = risk_msg.text or ""
        log(f"  Risk screen: {risk_text[:100]}...")
        result = await click_callback(client, risk_msg, "ob_risk:moderate", wait=5)
        if not result:
            result = await click_button(client, risk_msg, "Moderate", wait=5)
        if result:
            record_pass("[onboarding] Risk profile set to Moderate")

    # Step 7: Bankroll → R500
    await asyncio.sleep(2)
    msgs = await get_bot_response(client, wait=3, limit=5)
    bank_msg = find_msg_with_buttons(msgs)
    if bank_msg:
        bank_text = bank_msg.text or ""
        log(f"  Bankroll screen: {bank_text[:100]}...")
        result = await click_callback(client, bank_msg, "ob_bankroll:500", wait=5)
        if not result:
            result = await click_button(client, bank_msg, "R500", wait=5)
        if result:
            record_pass("[onboarding] Bankroll set to R500")

    # Step 8: Notification time → 6 PM
    await asyncio.sleep(2)
    msgs = await get_bot_response(client, wait=3, limit=5)
    notify_msg = find_msg_with_buttons(msgs)
    if notify_msg:
        notify_text = notify_msg.text or ""
        log(f"  Notify screen: {notify_text[:100]}...")
        result = await click_callback(client, notify_msg, "ob_notify:18", wait=5)
        if not result:
            result = await click_button(client, notify_msg, "6 PM", wait=5)
        if result:
            record_pass("[onboarding] Notification time set")

    # Step 9: Summary → Confirm
    await asyncio.sleep(3)
    msgs = await get_bot_response(client, wait=3, limit=5)
    summary_msg = find_msg_with_buttons(msgs)
    if summary_msg:
        summary_text = summary_msg.text or ""
        log(f"\n  Summary: {summary_text[:400]}...")

        # Check summary content
        check_response(summary_text, "onboarding_summary", {
            "Has sports section": ("Soccer", True),
        })

        # Click "🚀 Let's go!" (callback: ob_done:finish)
        result = await click_callback(client, summary_msg, "ob_done:finish", wait=8)
        if not result:
            result = await click_button(client, summary_msg, "Let's go", wait=8)
        if result:
            record_pass("[onboarding] Onboarding confirmed")
            # Check welcome message
            all_text = " ".join(m.text or "" for m in result)
            check_response(all_text, "welcome", {
                "No HTML entity leak": ("&lt;", False),
                "No raw HTML tags": ("<b>", False),
            })

            # Handle Edge Alerts quiz if shown
            await asyncio.sleep(3)
            msgs = await get_bot_response(client, wait=3, limit=5)
            edge_alerts_msg = find_msg_with_buttons(msgs)
            if edge_alerts_msg:
                ea_text = edge_alerts_msg.text or ""
                if "alert" in ea_text.lower() or "story" in ea_text.lower() or "edge" in ea_text.lower():
                    # Skip edge alerts for now
                    skip = await click_button(client, edge_alerts_msg, "Skip", wait=5)
                    if skip:
                        log("  Skipped Edge Alerts setup")

    await asyncio.sleep(3)
    return True


# ─────────────────────────────────────────────────────
# PHASE 2: Test My Matches
# ─────────────────────────────────────────────────────
async def phase_2_my_matches(client):
    log("\n" + "="*60)
    log("PHASE 2: MY MATCHES")
    log("="*60)

    msgs = await send_and_capture(client, "⚽ My Matches", wait=25, label="my_matches")
    if not msgs:
        record_issue("my_matches", "No response to My Matches")
        return

    # Find the actual My Matches response (filter out onboarding/welcome messages)
    matches_msg = find_msg_with_text(msgs, "My Matches") or find_msg_with_text(msgs, "[1]")
    if matches_msg:
        all_text = matches_msg.text or ""
    else:
        all_text = "\n".join(m.text or "" for m in msgs)

    # Check if we're still in onboarding (bot didn't accept the command)
    if "Step 1/5" in all_text or "betting experience" in all_text:
        record_issue("my_matches", "Still in onboarding — My Matches not accessible")
        return

    # Basic checks
    check_response(all_text, "my_matches", {
        "Has match listings": ("[1]", True),
        "No Check SuperSport fallback": ("Check SuperSport.com", False),
        "No raw HTML tags": ("<b>", False),
        "No HTML entities": ("&lt;", False),
        "No triple blank lines": ("\n\n\n", False),
    })

    # Check for duplicate matches
    lines = all_text.split("\n")
    # Match lines start with [N] or **[N]** (bold numbered items)
    match_lines = [l for l in lines if l.strip().startswith("[") or l.strip().startswith("**[")]
    seen = set()
    for ml in match_lines:
        if " vs " in ml:
            # Normalise: strip numbering and emojis to compare team pairs
            parts = ml.split(" vs ")
            if len(parts) == 2:
                home = parts[0].split("]")[-1].strip()
                away = parts[1].strip().split("\n")[0].strip()
                key = f"{home} vs {away}"
                if key in seen:
                    record_issue("my_matches", f"Duplicate match: {key}")
                seen.add(key)

    if not any("Duplicate" in i["description"] for i in issues if i["phase"] == "my_matches"):
        record_pass("[my_matches] No duplicate matches")

    match_count = len(match_lines)
    log(f"  Match count: {match_count}")
    if match_count >= 3:
        record_pass(f"[my_matches] Good match count: {match_count}")
    else:
        record_issue("my_matches", f"Too few matches: {match_count} (expected 3+ with many teams)")

    # Check sport emojis are present
    has_soccer = "⚽" in all_text
    has_rugby = "🏉" in all_text
    has_cricket = "🏏" in all_text
    has_combat = "🥊" in all_text
    sport_count = sum([has_soccer, has_rugby, has_cricket, has_combat])
    log(f"  Sports shown: ⚽={has_soccer} 🏉={has_rugby} 🏏={has_cricket} 🥊={has_combat}")
    if sport_count >= 2:
        record_pass(f"[my_matches] Multiple sports shown ({sport_count})")

    # Check broadcast info
    if "📺" in all_text:
        record_pass("[my_matches] Broadcast info present")
    elif match_count > 0:
        record_issue("my_matches", "No broadcast info (📺) on any match")

    # Check for sport filter buttons
    main_msg = find_msg_with_buttons(msgs)
    if main_msg:
        btns = get_all_btn_info(main_msg)
        btn_texts = [b["text"] for b in btns]
        sport_filters = [t for t in btn_texts if t in ("⚽", "🏉", "🏏", "🥊")]
        if len(sport_filters) >= 2:
            record_pass(f"[my_matches] Sport filter buttons: {sport_filters}")

            # Test cricket filter (use callback to avoid matching match-detail buttons)
            if "🏏" in btn_texts:
                result = await click_callback(client, main_msg, "yg:sport:cricket", wait=5)
                if result:
                    cricket_text = " ".join(m.text or "" for m in result)
                    if "🏏" in cricket_text or "Cricket" in cricket_text:
                        record_pass("[my_matches] Cricket filter works")
                    else:
                        record_issue("my_matches", "Cricket filter didn't show cricket matches", cricket_text[:200])

        # Check for pagination
        has_next = any("next" in b["text"].lower() or "➡" in b["text"] for b in btns)
        if has_next:
            result = await click_button(client, main_msg, "➡", wait=5)
            if not result:
                result = await click_button(client, main_msg, "Next", wait=5)
            if result:
                p2_text = " ".join(m.text or "" for m in result)
                if "[" in p2_text:
                    record_pass("[my_matches] Pagination works")


# ─────────────────────────────────────────────────────
# PHASE 3: Test Top Edge Picks
# ─────────────────────────────────────────────────────
async def phase_3_edge_picks(client):
    log("\n" + "="*60)
    log("PHASE 3: TOP EDGE PICKS")
    log("="*60)

    # Edge picks may take time (spinner + DB queries)
    msgs = await send_and_capture(client, "💎 Top Edge Picks", wait=18, label="edge_picks")
    if not msgs:
        record_issue("edge_picks", "No response to Top Edge Picks")
        return

    # Combine all message texts
    all_text = "\n".join(m.text or "" for m in msgs)

    if "Step 1/5" in all_text:
        record_issue("edge_picks", "Still in onboarding")
        return

    check_response(all_text, "edge_picks", {
        "Has tip listings": ("[1]", True),
        "Has edge tier badge": ("EDGE", True),
        "No Check SuperSport fallback": ("Check SuperSport.com", False),
        "No raw HTML tags": ("<b>", False),
        "Has EV percentage": ("EV", True),
    })

    # Check sport emojis
    tip_lines = [l for l in all_text.split("\n") if l.strip().startswith("[") or l.strip().startswith("**[")]
    soccer_tips = [l for l in tip_lines if "⚽" in l]
    cricket_tips = [l for l in tip_lines if "🏏" in l]
    rugby_tips = [l for l in tip_lines if "🏉" in l]
    combat_tips = [l for l in tip_lines if "🥊" in l]
    generic_tips = [l for l in tip_lines if "🏅" in l]
    log(f"  Tips: ⚽{len(soccer_tips)} 🏉{len(rugby_tips)} 🏏{len(cricket_tips)} 🥊{len(combat_tips)} 🏅{len(generic_tips)}")

    if generic_tips:
        record_issue("edge_picks", f"{len(generic_tips)} tips have generic 🏅 emoji instead of sport-specific")

    # Check for duplicates
    seen_tips = set()
    for line in tip_lines:
        if " vs " in line:
            match_part = line.split("]")[-1].strip()
            if match_part in seen_tips:
                record_issue("edge_picks", f"Duplicate tip: {match_part}")
            seen_tips.add(match_part)
    if not any("Duplicate" in i["description"] for i in issues if i["phase"] == "edge_picks"):
        record_pass("[edge_picks] No duplicate tips")

    # Check bookmaker names on odds lines
    odds_lines = [l for l in all_text.split("\n") if "💰" in l or "@" in l]
    if odds_lines:
        record_pass(f"[edge_picks] Has {len(odds_lines)} odds lines")
    else:
        record_issue("edge_picks", "No odds lines found (💰 or @)")

    # Test pagination
    last_msg = find_msg_with_buttons(msgs)
    if last_msg:
        btns = get_all_btn_info(last_msg)
        has_next = any("next" in b["text"].lower() or "➡" in b["text"] for b in btns)
        if has_next:
            result = await click_button(client, last_msg, "➡", wait=8)
            if not result:
                result = await click_button(client, last_msg, "Next", wait=8)
            if result:
                p2_text = " ".join(m.text or "" for m in result)
                if "[" in p2_text:
                    record_pass("[edge_picks] Pagination works")

    # Test tapping a tip for detail
    tip_msg = find_msg_with_buttons(msgs)
    if tip_msg:
        btns = get_all_btn_info(tip_msg)
        # Find tip detail button (usually 🔍 or has tip:detail callback)
        tip_btn = None
        for b in btns:
            if b["data"].startswith("tip:detail:"):
                tip_btn = b
                break
            if "🔍" in b["text"]:
                tip_btn = b
                break

        if tip_btn:
            log(f"\n  Tapping tip: {tip_btn['text'][:50]}")
            if tip_btn["data"]:
                result = await click_callback(client, tip_msg, tip_btn["data"], wait=10)
            else:
                result = await click_button(client, tip_msg, tip_btn["text"][:15], wait=10)

            if result:
                detail_text = " ".join(m.text or "" for m in result)
                check_response(detail_text, "tip_detail", {
                    "Has odds info": ("@", True),
                    "No raw HTML tags": ("<b>", False),
                    "No HTML entities": ("&lt;", False),
                })

                # Check for buttons on detail
                detail_msg = find_msg_with_buttons(result)
                if detail_msg:
                    dbtns = get_all_btn_info(detail_msg)
                    has_compare = any("📊" in b["text"] or "odds" in b["text"].lower() for b in dbtns)
                    has_cta = any("📲" in b["text"] or "bet on" in b["text"].lower() for b in dbtns)
                    has_back = any("back" in b["text"].lower() or "↩" in b["text"] for b in dbtns)

                    if has_compare:
                        record_pass("[tip_detail] Has odds comparison button")
                    if has_cta:
                        record_pass("[tip_detail] Has CTA button")
                    if has_back:
                        record_pass("[tip_detail] Has back button")

                    # Test odds comparison
                    if has_compare:
                        comp_btn = next((b for b in dbtns if "📊" in b["text"] or b["data"].startswith("odds:compare:")), None)
                        if comp_btn and comp_btn["data"]:
                            comp_result = await click_callback(client, detail_msg, comp_btn["data"], wait=8)
                        else:
                            comp_result = await click_button(client, detail_msg, "📊", wait=8)

                        if comp_result:
                            comp_text = " ".join(m.text or "" for m in comp_result)
                            # Check multiple bookmakers shown
                            bk_count = sum(1 for bk in ["Hollywoodbets", "Betway", "Sportingbet", "GBets", "Supabets", "SuperSportBet", "WSB", "Playabets"]
                                          if bk in comp_text)
                            if bk_count >= 2:
                                record_pass(f"[odds_comparison] Shows {bk_count} bookmakers")
                            else:
                                record_issue("odds_comparison", f"Only {bk_count} bookmakers shown", comp_text[:300])

                            check_response(comp_text, "odds_comparison", {
                                "No raw HTML tags": ("<b>", False),
                            })

                            # Check back button works
                            comp_msg = find_msg_with_buttons(comp_result)
                            if comp_msg:
                                comp_btns = get_all_btn_info(comp_msg)
                                has_back = any("back" in b["text"].lower() or "↩" in b["text"] for b in comp_btns)
                                if has_back:
                                    record_pass("[odds_comparison] Has back button")
                                else:
                                    record_issue("odds_comparison", "No back button on odds comparison")


# ─────────────────────────────────────────────────────
# PHASE 4: Test Profile
# ─────────────────────────────────────────────────────
async def phase_4_profile(client):
    log("\n" + "="*60)
    log("PHASE 4: PROFILE")
    log("="*60)

    msgs = await send_and_capture(client, "👤 Profile", wait=5, label="profile")
    if not msgs:
        record_issue("profile", "No response to Profile")
        return

    all_text = " ".join(m.text or "" for m in msgs)

    if "Step 1/5" in all_text:
        record_issue("profile", "Still in onboarding")
        return

    check_response(all_text, "profile", {
        "Has experience label": ("Experience", True),
        "No raw HTML tags": ("<b>", False),
        "No HTML entities": ("&lt;", False),
    })

    # Check that teams are listed
    teams_to_check = ["Arsenal", "Liverpool", "Chiefs", "Pirates", "South Africa",
                       "India", "Dricus", "Bulls", "Barcelona", "Chelsea"]
    teams_found = [t for t in teams_to_check if t in all_text]
    log(f"  Teams found: {teams_found}")

    if len(teams_found) >= 5:
        record_pass(f"[profile] Teams shown ({len(teams_found)} found)")
    elif len(teams_found) >= 3:
        record_pass(f"[profile] Some teams shown ({len(teams_found)})")
    else:
        record_issue("profile", f"Too few teams: {len(teams_found)} ({teams_found})", all_text[:300])

    # Check sport sections
    for sport in ["Soccer", "Rugby", "Cricket", "Combat"]:
        if sport in all_text:
            record_pass(f"[profile] {sport} section present")

    # Check risk/bankroll shown
    if "Moderate" in all_text or "moderate" in all_text:
        record_pass("[profile] Risk profile shown")
    if "R500" in all_text or "500" in all_text:
        record_pass("[profile] Bankroll shown")


# ─────────────────────────────────────────────────────
# PHASE 5: Test Settings
# ─────────────────────────────────────────────────────
async def phase_5_settings(client):
    log("\n" + "="*60)
    log("PHASE 5: SETTINGS")
    log("="*60)

    msgs = await send_and_capture(client, "⚙️ Settings", wait=5, label="settings")
    if not msgs:
        record_issue("settings", "No response to Settings")
        return

    all_text = " ".join(m.text or "" for m in msgs)
    settings_msg = find_msg_with_buttons(msgs)

    check_response(all_text, "settings", {
        "Has settings content": ("Settings", True),
        "No raw HTML tags": ("<b>", False),
    })

    if settings_msg:
        btns = get_all_btn_info(settings_msg)
        btn_texts = [b["text"] for b in btns]
        log(f"  Settings buttons: {btn_texts}")

        # Test Edge Alerts
        alerts_btn = next((b for b in btns if "alert" in b["text"].lower() or "notif" in b["text"].lower()), None)
        if alerts_btn:
            if alerts_btn["data"]:
                result = await click_callback(client, settings_msg, alerts_btn["data"], wait=5)
            else:
                result = await click_button(client, settings_msg, alerts_btn["text"][:15], wait=5)

            if result:
                alerts_text = " ".join(m.text or "" for m in result)
                check_response(alerts_text, "settings_alerts", {
                    "Has notification types": ("daily", True),
                    "No raw HTML tags": ("<b>", False),
                })
                record_pass("[settings] Edge Alerts accessible")

                # Go back
                back_msg = find_msg_with_buttons(result)
                if back_msg:
                    await click_button(client, back_msg, "Back", wait=3)

        # Test Risk Profile button
        risk_btn = next((b for b in btns if "risk" in b["text"].lower()), None)
        if risk_btn:
            if risk_btn["data"]:
                result = await click_callback(client, settings_msg, risk_btn["data"], wait=5)
            else:
                result = await click_button(client, settings_msg, risk_btn["text"][:15], wait=5)

            if result:
                risk_text = " ".join(m.text or "" for m in result)
                if "Conservative" in risk_text or "Moderate" in risk_text or "Aggressive" in risk_text:
                    record_pass("[settings] Risk profile options shown")

                back_msg = find_msg_with_buttons(result)
                if back_msg:
                    await click_button(client, back_msg, "Back", wait=3)


# ─────────────────────────────────────────────────────
# PHASE 6: Test Guide
# ─────────────────────────────────────────────────────
async def phase_6_guide(client):
    log("\n" + "="*60)
    log("PHASE 6: GUIDE")
    log("="*60)

    msgs = await send_and_capture(client, "📖 Guide", wait=5, label="guide")
    if not msgs:
        record_issue("guide", "No response to Guide")
        return

    all_text = " ".join(m.text or "" for m in msgs)

    if "Step 1/5" in all_text:
        record_issue("guide", "Still in onboarding")
        return

    check_response(all_text, "guide", {
        "Has edge info": ("Edge", True),
        "No raw HTML tags": ("<b>", False),
    })

    # Check edge tiers explained
    if "Diamond" in all_text or "💎" in all_text:
        record_pass("[guide] Diamond tier explained")
    if "Gold" in all_text or "🥇" in all_text:
        record_pass("[guide] Gold tier explained")


# ─────────────────────────────────────────────────────
# PHASE 7: Test Help
# ─────────────────────────────────────────────────────
async def phase_7_help(client):
    log("\n" + "="*60)
    log("PHASE 7: HELP")
    log("="*60)

    msgs = await send_and_capture(client, "❓ Help", wait=5, label="help")
    if not msgs:
        record_issue("help", "No response to Help")
        return

    # Find the actual Help response (search more messages if needed)
    help_msg = find_msg_with_text(msgs, "Help")
    if not help_msg:
        # Try fetching more messages in case the help response is buried
        more = await get_bot_response(client, wait=2, limit=15)
        help_msg = find_msg_with_text(more, "Help")
    if not help_msg:
        help_msg = msgs[0]
    help_text = help_msg.text or ""

    if "Step 1/5" in help_text:
        record_issue("help", "Still in onboarding")
        return

    check_response(help_text, "help", {
        "Has help content": ("Help", True),
        "No raw HTML tags": ("<b>", False),
    })

    # Check commands listed
    for cmd in ["/start", "/menu", "/picks"]:
        if cmd in help_text:
            record_pass(f"[help] Lists {cmd}")


# ─────────────────────────────────────────────────────
# PHASE 8: Test legacy commands
# ─────────────────────────────────────────────────────
async def phase_8_commands(client):
    log("\n" + "="*60)
    log("PHASE 8: LEGACY COMMANDS")
    log("="*60)

    commands = [
        ("/menu", "MzansiEdge"),
        ("/help", "Help"),
        ("/admin", "Admin"),
    ]

    for cmd, expected in commands:
        msgs = await send_and_capture(client, cmd, wait=5, label=f"cmd_{cmd}")
        if msgs:
            all_text = " ".join(m.text or "" for m in msgs)
            if expected in all_text:
                record_pass(f"[commands] {cmd} responds correctly")
            else:
                record_issue("commands", f"{cmd} missing expected '{expected}'", all_text[:200])

            check_response(all_text, f"cmd_{cmd}", {
                f"No raw HTML in {cmd}": ("<b>", False),
            })
        else:
            record_issue("commands", f"No response to {cmd}")


# ─────────────────────────────────────────────────────
# PHASE 9: Game AI Breakdown
# ─────────────────────────────────────────────────────
async def phase_9_game_breakdown(client):
    log("\n" + "="*60)
    log("PHASE 9: GAME AI BREAKDOWN")
    log("="*60)

    # Load My Matches and tap a specific game
    msgs = await send_and_capture(client, "⚽ My Matches", wait=25, label="game_breakdown_setup")
    if not msgs:
        record_issue("game_breakdown", "No response to My Matches")
        return

    main_msg = find_msg_with_buttons(msgs)
    if not main_msg:
        record_issue("game_breakdown", "No buttons on My Matches")
        return

    btns = get_all_btn_info(main_msg)
    # Find a game button (yg:game:*)
    game_btn = next((b for b in btns if b["data"].startswith("yg:game:")), None)
    if not game_btn:
        record_issue("game_breakdown", "No game buttons found in My Matches")
        return

    log(f"  Tapping game: {game_btn['text'][:50]}")
    result = await click_callback(client, main_msg, game_btn["data"], wait=30)
    if not result:
        record_issue("game_breakdown", "No response to game tap")
        return

    game_text = " ".join(m.text or "" for m in result)

    # Check AI analysis content
    check_response(game_text, "game_breakdown", {
        "No raw HTML tags": ("<b>", False),
        "No HTML entities": ("&lt;", False),
    })

    if "Setup" in game_text or "Edge" in game_text or "Risk" in game_text or "Verdict" in game_text:
        record_pass("[game_breakdown] Has analysis sections")
    else:
        record_issue("game_breakdown", "Missing analysis sections (Setup/Edge/Risk/Verdict)", game_text[:200])

    # Check for buttons
    game_msg = find_msg_with_buttons(result)
    if game_msg:
        gbtns = get_all_btn_info(game_msg)
        has_back = any("back" in b["text"].lower() or "↩" in b["text"] for b in gbtns)
        has_cta = any("📲" in b["text"] or "bet on" in b["text"].lower() for b in gbtns)

        if has_back:
            record_pass("[game_breakdown] Has back button")
        else:
            record_issue("game_breakdown", "No back button on game breakdown")

        if has_cta:
            record_pass("[game_breakdown] Has CTA/bet button")

    log(f"  AI breakdown length: {len(game_text)} chars")


# ─────────────────────────────────────────────────────
# PHASE 10: Settings Persistence
# ─────────────────────────────────────────────────────
async def phase_10_settings_persist(client):
    log("\n" + "="*60)
    log("PHASE 10: SETTINGS PERSISTENCE")
    log("="*60)

    # Open settings
    msgs = await send_and_capture(client, "⚙️ Settings", wait=5, label="settings_persist")
    if not msgs:
        record_issue("settings_persist", "No settings response")
        return

    settings_msg = find_msg_with_buttons(msgs)
    if not settings_msg:
        record_issue("settings_persist", "No settings buttons")
        return

    # Change risk to Aggressive
    result = await click_callback(client, settings_msg, "settings:risk", wait=5)
    if result:
        risk_msg = find_msg_with_buttons(result)
        if risk_msg:
            # Click Aggressive
            agg_result = await click_callback(client, risk_msg, "settings:set_risk:aggressive", wait=5)
            if agg_result:
                agg_text = " ".join(m.text or "" for m in agg_result)
                if "Aggressive" in agg_text or "updated" in agg_text:
                    record_pass("[settings_persist] Risk changed to Aggressive")
                else:
                    record_issue("settings_persist", "Risk change not confirmed", agg_text[:200])
            else:
                record_issue("settings_persist", "No response to Aggressive selection")
        else:
            record_issue("settings_persist", "No risk options shown")
    else:
        record_issue("settings_persist", "No response to risk button")

    # Verify profile reflects the change
    await asyncio.sleep(2)
    prof_msgs = await send_and_capture(client, "👤 Profile", wait=5, label="settings_persist_verify")
    if prof_msgs:
        prof_text = " ".join(m.text or "" for m in prof_msgs)
        if "Aggressive" in prof_text:
            record_pass("[settings_persist] Profile shows new risk: Aggressive")
        elif "Moderate" in prof_text:
            record_issue("settings_persist", "Profile still shows Moderate (change didn't persist)")
        else:
            record_issue("settings_persist", "Risk not found in profile", prof_text[:200])

    # Change risk back to Moderate (restore original)
    msgs2 = await send_and_capture(client, "⚙️ Settings", wait=5, label="settings_restore")
    if msgs2:
        s2 = find_msg_with_buttons(msgs2)
        if s2:
            r2 = await click_callback(client, s2, "settings:risk", wait=5)
            if r2:
                rm = find_msg_with_buttons(r2)
                if rm:
                    await click_callback(client, rm, "settings:set_risk:moderate", wait=3)
                    record_pass("[settings_persist] Risk restored to Moderate")


# ─────────────────────────────────────────────────────
# PHASE 11: Additional Commands
# ─────────────────────────────────────────────────────
async def phase_11_extra_commands(client):
    log("\n" + "="*60)
    log("PHASE 11: ADDITIONAL COMMANDS")
    log("="*60)

    # /picks should redirect to Hot Tips
    msgs = await send_and_capture(client, "/picks", wait=18, label="cmd_picks")
    if msgs:
        picks_text = " ".join(m.text or "" for m in msgs)
        if "Edge" in picks_text or "[1]" in picks_text or "bets found" in picks_text:
            record_pass("[extra_cmd] /picks shows edge picks")
        elif "Scanning" in picks_text or "Loading" in picks_text:
            record_pass("[extra_cmd] /picks triggers loading (slow but working)")
        else:
            record_issue("extra_cmd", "/picks unexpected response", picks_text[:200])
    else:
        record_issue("extra_cmd", "No response to /picks")

    # /schedule should work
    msgs = await send_and_capture(client, "/schedule", wait=25, label="cmd_schedule")
    if msgs:
        sched_text = " ".join(m.text or "" for m in msgs)
        if "[1]" in sched_text or "Matches" in sched_text or "games" in sched_text.lower():
            record_pass("[extra_cmd] /schedule shows matches")
        elif "Loading" in sched_text:
            record_pass("[extra_cmd] /schedule triggers loading")
        else:
            record_issue("extra_cmd", "/schedule unexpected response", sched_text[:200])
    else:
        record_issue("extra_cmd", "No response to /schedule")

    # /start when already onboarded should show welcome back
    msgs = await send_and_capture(client, "/start", wait=5, label="cmd_start_onboarded")
    if msgs:
        start_text = " ".join(m.text or "" for m in msgs)
        if "Welcome back" in start_text or "Main Menu" in start_text:
            record_pass("[extra_cmd] /start shows welcome back")
        elif "Step 1" in start_text:
            record_issue("extra_cmd", "/start re-triggered onboarding unexpectedly")
        else:
            record_issue("extra_cmd", "/start unexpected response", start_text[:200])
    else:
        record_issue("extra_cmd", "No response to /start")


# ─────────────────────────────────────────────────────
# PHASE 12: Free Text + Edge Cases
# ─────────────────────────────────────────────────────
async def phase_12_free_text(client):
    log("\n" + "="*60)
    log("PHASE 12: FREE TEXT + EDGE CASES")
    log("="*60)

    # Send random text — bot should respond with freetext handler
    msgs = await send_and_capture(client, "hello what are the best bets today?", wait=15, label="free_text")
    if msgs:
        ft_text = " ".join(m.text or "" for m in msgs)
        if ft_text.strip():
            record_pass("[free_text] Bot responds to free text")
            check_response(ft_text, "free_text", {
                "No raw HTML tags": ("<b>", False),
            })
        else:
            record_issue("free_text", "Empty response to free text")
    else:
        record_issue("free_text", "No response to free text")

    # Send gibberish
    msgs = await send_and_capture(client, "asdfghjkl", wait=10, label="gibberish")
    if msgs:
        gib_text = " ".join(m.text or "" for m in msgs)
        if gib_text.strip():
            record_pass("[free_text] Bot handles gibberish gracefully")
        # Just checking it doesn't crash — any response is fine

    # Double-tap resilience: send My Matches twice quickly
    log("\n  Testing double-tap resilience...")
    await send_and_capture(client, "⚽ My Matches", wait=2, label="double_tap_1")
    msgs = await send_and_capture(client, "⚽ My Matches", wait=25, label="double_tap_2")
    if msgs:
        dt_text = " ".join(m.text or "" for m in msgs)
        if "Matches" in dt_text or "[1]" in dt_text or "Loading" in dt_text:
            record_pass("[free_text] Double-tap handled gracefully")
        else:
            record_issue("free_text", "Double-tap produced unexpected response", dt_text[:200])


# ─────────────────────────────────────────────────────
# PHASE 13: Cross-cutting checks
# ─────────────────────────────────────────────────────
async def phase_13_cross_cutting(client):
    log("\n" + "="*60)
    log("PHASE 13: CROSS-CUTTING CHECKS")
    log("="*60)

    # Check all captured responses for common issues
    html_leaks = 0
    entity_leaks = 0
    empty_responses = 0

    for resp in all_responses:
        text = resp["response"]
        if "<b>" in text or "<i>" in text or "</b>" in text or "</i>" in text:
            html_leaks += 1
        if "&lt;" in text or "&gt;" in text or "&amp;" in text:
            entity_leaks += 1
        if not text.strip():
            empty_responses += 1

    if html_leaks == 0:
        record_pass(f"[cross-cutting] No raw HTML tags in any response")
    else:
        record_issue("cross-cutting", f"{html_leaks} responses contain raw HTML tags")

    if entity_leaks == 0:
        record_pass(f"[cross-cutting] No HTML entities in any response")
    else:
        record_issue("cross-cutting", f"{entity_leaks} responses contain HTML entities")

    log(f"  Total responses captured: {len(all_responses)}")
    log(f"  Empty responses: {empty_responses}")


# ─────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────
async def main():
    log("=" * 60)
    log(f"COMPREHENSIVE E2E TEST — {TIMESTAMP}")
    log("=" * 60)

    client = TelegramClient(StringSession(SESSION_STR), API_ID, API_HASH)
    await client.start()
    me = await client.get_me()
    log(f"Connected as: {me.first_name} (ID: {me.id})")

    try:
        # Pre-check: send /start and detect user state
        test_msgs = await send_and_capture(client, "/start", wait=6, label="pre_check")
        all_pre_text = " ".join(m.text or "" for m in test_msgs)
        is_onboarded = "Welcome back" in all_pre_text or "Main Menu" in all_pre_text

        if is_onboarded:
            # Phase 0: Reset and re-onboard
            log("\n✅ User is onboarded — resetting profile for fresh test")
            reset_ok = await phase_0_reset(client)
            if reset_ok:
                onboard_ok = await phase_1_onboarding(client)
            else:
                log("\n⚠️ Reset failed, testing with existing profile")
                onboard_ok = True
        else:
            # Not onboarded — the /start we just sent started onboarding.
            # Use the pre-check messages directly (avoid sending /start again).
            log("\n⚠️ User not onboarded — proceeding with onboarding from current state")
            onboard_ok = await _do_onboarding(client, test_msgs)

        # Phase 2-13: Test all features
        await phase_2_my_matches(client)
        await phase_3_edge_picks(client)
        await phase_4_profile(client)
        await phase_5_settings(client)
        await phase_6_guide(client)
        await phase_7_help(client)
        await phase_8_commands(client)
        await phase_9_game_breakdown(client)
        await phase_10_settings_persist(client)
        await phase_11_extra_commands(client)
        await phase_12_free_text(client)
        await phase_13_cross_cutting(client)

    finally:
        await client.disconnect()

    # Write report
    log("\n" + "=" * 60)
    log("FINAL REPORT")
    log("=" * 60)
    log(f"\n✅ PASSES: {len(passes)}")
    for p in passes:
        log(f"  {p}")

    log(f"\n❌ ISSUES: {len(issues)}")
    for i, issue in enumerate(issues):
        log(f"  [{i+1}] [{issue['phase']}] {issue['description']}")
        if issue["response"]:
            log(f"      Response: {issue['response'][:200]}")

    # Save report
    os.makedirs(REPORT_DIR, exist_ok=True)
    with open(REPORT_FILE, "w") as f:
        f.write(f"COMPREHENSIVE E2E TEST — {TIMESTAMP}\n")
        f.write(f"{'='*60}\n\n")
        f.write(f"PASSES: {len(passes)}\n")
        for p in passes:
            f.write(f"  ✅ {p}\n")
        f.write(f"\nISSUES: {len(issues)}\n")
        for i, issue in enumerate(issues):
            f.write(f"  ❌ [{i+1}] [{issue['phase']}] {issue['description']}\n")
            if issue["response"]:
                f.write(f"      Response: {issue['response'][:500]}\n")
        f.write(f"\n\nALL RESPONSES:\n{'='*60}\n")
        for resp in all_responses:
            f.write(f"\n→ {resp['label']}: {resp['sent']}\n")
            f.write(f"← {resp['response']}\n")

    log(f"\nReport saved to: {REPORT_FILE}")

    return len(issues)


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(min(exit_code, 1) if exit_code > 0 else 0)
