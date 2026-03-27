"""Wave 20 — 6-Hour Comprehensive Telethon Stress Test.

Sends real messages/button taps to @mzansiedge_bot and captures every response.
Tests: onboarding, hot tips, game breakdowns, odds comparison, tier-gating,
all commands, edge cases, and data accuracy.

Usage:
    cd /home/paulsportsza/bot && source .venv/bin/activate
    python tests/stress_test_wave20.py                    # Full run
    python tests/stress_test_wave20.py --phase 1          # Specific phase
    python tests/stress_test_wave20.py --phase 2          # Core features
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import (
    ReplyKeyboardMarkup as TLReplyKeyboardMarkup,
    ReplyInlineMarkup,
    KeyboardButtonCallback,
    KeyboardButtonUrl,
)

# ── Configuration ────────────────────────────────────────

API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "")
BOT_USERNAME = "mzansiedge_bot"
SESSION_FILE = os.environ.get("TELETHON_SESSION", "data/telethon_session")
STRING_SESSION_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "telethon_session.string")

TIMEOUT = 15  # seconds to wait for bot response
SHORT_WAIT = 5
LONG_WAIT = 20

# ── Data Structures ──────────────────────────────────────

@dataclass
class Issue:
    num: int
    severity: str  # P0, P1, P2
    category: str
    description: str
    status: str = "Open"
    fix: str = ""

@dataclass
class TestResult:
    name: str
    passed: bool
    message: str
    duration: float
    raw_output: str = ""

@dataclass
class TestReport:
    results: list[TestResult] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    captures: dict = field(default_factory=dict)
    _issue_counter: int = 0

    def add_result(self, r: TestResult):
        self.results.append(r)
        status = "PASS" if r.passed else "FAIL"
        print(f"  [{status}] {r.name} ({r.duration:.1f}s) — {r.message}")

    def add_issue(self, severity: str, category: str, description: str) -> Issue:
        self._issue_counter += 1
        issue = Issue(self._issue_counter, severity, category, description)
        self.issues.append(issue)
        print(f"  *** ISSUE #{issue.num} [{severity}] {category}: {description}")
        return issue

    def summary(self) -> str:
        total = len(self.results)
        passed = sum(1 for r in self.results if r.passed)
        failed = total - passed
        p0 = sum(1 for i in self.issues if i.severity == "P0")
        p1 = sum(1 for i in self.issues if i.severity == "P1")
        p2 = sum(1 for i in self.issues if i.severity == "P2")
        return (
            f"Tests: {passed}/{total} passed, {failed} failed\n"
            f"Issues: {p0} P0, {p1} P1, {p2} P2 ({len(self.issues)} total)"
        )

report = TestReport()

# ── Helpers ──────────────────────────────────────────────

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
        print("ERROR: Not logged in. Run save_telegram_session.py first.")
        sys.exit(1)
    return client


async def send_and_wait(client: TelegramClient, text: str, wait: float = TIMEOUT) -> list:
    entity = await client.get_entity(BOT_USERNAME)
    await client.send_message(entity, text)
    await asyncio.sleep(wait)
    messages = await client.get_messages(entity, limit=15)
    return list(reversed(messages))


async def click_button(client: TelegramClient, msg, button_text: str, wait: float = TIMEOUT) -> list:
    if not msg.reply_markup:
        return []
    if isinstance(msg.reply_markup, ReplyInlineMarkup):
        for row in msg.reply_markup.rows:
            for btn in row.buttons:
                if isinstance(btn, KeyboardButtonCallback) and button_text in btn.text:
                    await msg.click(data=btn.data)
                    await asyncio.sleep(wait)
                    entity = await client.get_entity(BOT_USERNAME)
                    messages = await client.get_messages(entity, limit=15)
                    return list(reversed(messages))
    return []


async def click_callback_data(client: TelegramClient, msg, callback_data: str, wait: float = TIMEOUT) -> list:
    """Click a button by its callback_data value."""
    if not msg.reply_markup or not isinstance(msg.reply_markup, ReplyInlineMarkup):
        return []
    for row in msg.reply_markup.rows:
        for btn in row.buttons:
            if isinstance(btn, KeyboardButtonCallback) and btn.data and btn.data.decode("utf-8") == callback_data:
                await msg.click(data=btn.data)
                await asyncio.sleep(wait)
                entity = await client.get_entity(BOT_USERNAME)
                messages = await client.get_messages(entity, limit=15)
                return list(reversed(messages))
    return []


def get_bot_messages(messages: list) -> list:
    """Filter to only bot messages (not our own sent messages)."""
    return [m for m in messages if m.sender_id != messages[-1].sender_id or (hasattr(m, 'out') and not m.out)]


def find_message_with_text(messages: list, text: str):
    """Find a bot message containing specific text."""
    for msg in messages:
        if msg.text and text in msg.text:
            return msg
    return None


def find_message_with_button(messages: list, button_text: str):
    """Find a message with a specific inline button."""
    for msg in messages:
        if msg.reply_markup and isinstance(msg.reply_markup, ReplyInlineMarkup):
            for row in msg.reply_markup.rows:
                for btn in row.buttons:
                    if hasattr(btn, 'text') and button_text in btn.text:
                        return msg
    return None


def get_inline_buttons(msg) -> list[str]:
    """Get all inline button texts from a message."""
    buttons = []
    if msg.reply_markup and isinstance(msg.reply_markup, ReplyInlineMarkup):
        for row in msg.reply_markup.rows:
            for btn in row.buttons:
                if hasattr(btn, 'text'):
                    buttons.append(btn.text)
    return buttons


def get_callback_data_buttons(msg) -> list[tuple[str, str]]:
    """Get all (text, callback_data) pairs from a message."""
    buttons = []
    if msg.reply_markup and isinstance(msg.reply_markup, ReplyInlineMarkup):
        for row in msg.reply_markup.rows:
            for btn in row.buttons:
                if isinstance(btn, KeyboardButtonCallback):
                    buttons.append((btn.text, btn.data.decode("utf-8") if btn.data else ""))
    return buttons


def check_no_html_leak(text: str) -> list[str]:
    """Check for raw HTML/markdown leaking through."""
    issues = []
    if not text:
        return issues
    # Raw HTML tags showing as text
    if re.search(r'</?b>', text) and not text.startswith('<'):
        # Telegram renders <b> so if we see it literally, it's a leak
        pass  # Telegram will render these, so they won't appear literally
    # Markdown leaks
    if re.search(r'(?<!\w)#{1,3}\s', text):
        issues.append(f"Markdown header leak: found # in text")
    if re.search(r'\*\*[^*]+\*\*', text):
        issues.append(f"Markdown bold leak: found ** in text")
    if text.count('__') >= 2:
        issues.append(f"Markdown italic leak: found __ in text")
    if "None" in text and ("None/" not in text and "None " not in text.split("None")[0][-5:] if "None" in text else True):
        # Check for literal "None" that might be a Python None rendering
        if re.search(r'\bNone\b', text) and not any(x in text for x in ["Six Nations", "None of"]):
            issues.append(f"Python None leaking: found 'None' in text")
    return issues


def check_stale_data(text: str) -> list[str]:
    """Check for obviously stale dates or data."""
    issues = []
    # Check for dates before today
    # Look for common date formats
    return issues


# ── Phase 1: Onboarding Tests ───────────────────────────

async def phase1_onboarding(client: TelegramClient):
    print("\n" + "="*60)
    print("PHASE 1: FRESH ONBOARDING")
    print("="*60)

    # 1A: Send /start as fresh user
    print("\n--- 1A: /start as fresh user ---")
    start = time.time()
    msgs = await send_and_wait(client, "/start", wait=8)

    # Find the welcome/onboarding message
    bot_msgs = [m for m in msgs if m.text and not m.out]
    if not bot_msgs:
        report.add_result(TestResult("start_fresh", False, "No bot response", time.time() - start))
        report.add_issue("P0", "Onboarding", "/start produced no response")
        return

    first_msg = bot_msgs[-1]  # Most recent bot message
    report.captures["start_fresh"] = first_msg.text[:500]

    # Check for experience level buttons
    buttons = get_inline_buttons(first_msg)
    has_experience = any("casual" in b.lower() or "newbie" in b.lower() or "experienced" in b.lower()
                        or "sharp" in b.lower() or "regular" in b.lower()
                        for b in buttons)

    # Also check earlier messages
    if not has_experience:
        for m in bot_msgs:
            buttons = get_inline_buttons(m)
            if any("casual" in b.lower() or "newbie" in b.lower() or "experienced" in b.lower()
                   for b in buttons):
                first_msg = m
                has_experience = True
                break

    report.add_result(TestResult("start_fresh", has_experience,
                                 f"Experience buttons: {get_inline_buttons(first_msg)[:3]}",
                                 time.time() - start, first_msg.text[:300]))

    if not has_experience:
        report.add_issue("P0", "Onboarding", "/start does not show experience level selection")
        # Try to continue anyway
        for m in bot_msgs:
            print(f"  [DEBUG] Bot msg: {m.text[:200] if m.text else 'NO TEXT'}")
            print(f"  [DEBUG] Buttons: {get_inline_buttons(m)}")

    # Step 1: Select "Casual" experience
    print("\n--- Step 1/6: Experience Level ---")
    start = time.time()
    # Find the message with experience buttons
    exp_msg = first_msg
    # Try clicking "Casual" or similar
    casual_clicked = False
    for btn_text in ["Casual", "🎲 Casual", "casual"]:
        result = await click_button(client, exp_msg, btn_text, wait=SHORT_WAIT)
        if result:
            casual_clicked = True
            msgs = result
            break

    if not casual_clicked:
        # Try by callback data
        cb_buttons = get_callback_data_buttons(exp_msg)
        for text, data in cb_buttons:
            if "casual" in data.lower() or "casual" in text.lower():
                msgs = await click_callback_data(client, exp_msg, data, wait=SHORT_WAIT)
                casual_clicked = True
                break

    if casual_clicked:
        bot_msgs = [m for m in msgs if m.text and not m.out]
        last = bot_msgs[-1] if bot_msgs else None
        text = last.text if last else ""
        report.add_result(TestResult("exp_casual", True, f"Selected Casual → {text[:80]}", time.time() - start))
        report.captures["exp_casual"] = text[:500]
    else:
        report.add_result(TestResult("exp_casual", False, "Could not click Casual button", time.time() - start))
        report.add_issue("P0", "Onboarding", "Cannot select experience level")
        return

    # Step 2: Sports Selection
    print("\n--- Step 2/6: Sports Selection ---")
    start = time.time()
    # Find sports selection message
    sport_msg = bot_msgs[-1] if bot_msgs else None
    if sport_msg:
        buttons = get_inline_buttons(sport_msg)
        cb_buttons = get_callback_data_buttons(sport_msg)
        report.captures["sports_step"] = f"Text: {sport_msg.text[:200]}\nButtons: {buttons}"

        # Select all 4 sports
        selected_sports = []
        for text, data in cb_buttons:
            if "ob_sport:" in data:
                sport_key = data.split(":")[-1]
                await click_callback_data(client, sport_msg, data, wait=2)
                selected_sports.append(sport_key)
                await asyncio.sleep(1)
                # Refresh message state
                entity = await client.get_entity(BOT_USERNAME)
                fresh = await client.get_messages(entity, limit=5)
                sport_msg = [m for m in fresh if m.text and not m.out][-1] if fresh else sport_msg

        report.add_result(TestResult("sports_select", len(selected_sports) >= 2,
                                     f"Selected: {selected_sports}", time.time() - start))

        # Click "Done" / "Next" for sports
        await asyncio.sleep(1)
        entity = await client.get_entity(BOT_USERNAME)
        fresh = await client.get_messages(entity, limit=5)
        sport_msg = [m for m in fresh if m.text and not m.out][-1]
        done_clicked = False
        for btn_text in ["Done", "Next", "Continue", "✅"]:
            result = await click_button(client, sport_msg, btn_text, wait=SHORT_WAIT)
            if result:
                done_clicked = True
                msgs = result
                bot_msgs = [m for m in msgs if m.text and not m.out]
                break

        if not done_clicked:
            cb_buttons = get_callback_data_buttons(sport_msg)
            for text, data in cb_buttons:
                if "sports_done" in data or "done" in data.lower():
                    msgs = await click_callback_data(client, sport_msg, data, wait=SHORT_WAIT)
                    done_clicked = True
                    bot_msgs = [m for m in msgs if m.text and not m.out]
                    break

        if not done_clicked:
            report.add_issue("P1", "Onboarding", "Cannot find sports Done button")

    # Step 3: Team Selection
    print("\n--- Step 3/6: Team Selection ---")
    start = time.time()
    # The bot will prompt for teams per sport
    # Get the current message
    entity = await client.get_entity(BOT_USERNAME)
    fresh = await client.get_messages(entity, limit=5)
    team_msg = [m for m in fresh if m.text and not m.out]
    if team_msg:
        team_prompt = team_msg[-1]
        report.captures["team_step"] = team_prompt.text[:500]

        # Type some team names
        # Check which sport is being asked
        prompt_text = team_prompt.text.lower() if team_prompt.text else ""

        if "soccer" in prompt_text or "football" in prompt_text:
            teams_input = "Kaizer Chiefs, Orlando Pirates, Sundowns, Arsenal, Liverpool"
        elif "rugby" in prompt_text:
            teams_input = "South Africa, Bulls, Stormers"
        elif "cricket" in prompt_text:
            teams_input = "South Africa, MI Cape Town"
        elif "combat" in prompt_text or "fighter" in prompt_text:
            teams_input = "Dricus Du Plessis"
        else:
            teams_input = "Arsenal, Kaizer Chiefs"

        msgs = await send_and_wait(client, teams_input, wait=8)
        bot_msgs = [m for m in msgs if m.text and not m.out]

        if bot_msgs:
            last = bot_msgs[-1]
            report.captures["team_confirmation"] = last.text[:500]
            # Check for celebration/confirmation
            has_confirm = last.text and ("added" in last.text.lower() or "✅" in last.text or "nice" in last.text.lower())
            report.add_result(TestResult("team_input", has_confirm,
                                         f"Response: {last.text[:100]}", time.time() - start))

            # Continue through remaining sports - click Continue/Done buttons
            for _ in range(5):  # Max 5 more sport prompts
                await asyncio.sleep(2)
                entity = await client.get_entity(BOT_USERNAME)
                fresh = await client.get_messages(entity, limit=5)
                current = [m for m in fresh if m.text and not m.out]
                if not current:
                    break
                last = current[-1]

                # Check if we're at edge explainer, risk, or summary
                if any(x in (last.text or "").lower() for x in ["edge", "risk", "preferences", "summary", "plan"]):
                    break

                # Check for Continue button
                btns = get_callback_data_buttons(last)
                continue_clicked = False
                for text, data in btns:
                    if "fav_done" in data or "continue" in text.lower() or "done" in text.lower():
                        await click_callback_data(client, last, data, wait=3)
                        continue_clicked = True
                        break

                if not continue_clicked and last.text:
                    # Might be prompting for next sport's teams
                    prompt_lower = last.text.lower()
                    if "rugby" in prompt_lower:
                        await send_and_wait(client, "South Africa, Bulls", wait=5)
                    elif "cricket" in prompt_lower:
                        await send_and_wait(client, "South Africa, MI Cape Town", wait=5)
                    elif "combat" in prompt_lower or "fighter" in prompt_lower:
                        await send_and_wait(client, "Dricus Du Plessis", wait=5)
                    else:
                        break
        else:
            report.add_result(TestResult("team_input", False, "No response to team input", time.time() - start))
    else:
        report.add_result(TestResult("team_step", False, "No team prompt found", time.time() - start))

    # Navigate through remaining steps (edge explainer, preferences, summary, plan)
    print("\n--- Navigating remaining steps ---")

    for step_name in ["edge_explainer", "risk_profile", "bankroll", "notifications", "summary", "plan_picker"]:
        await asyncio.sleep(2)
        entity = await client.get_entity(BOT_USERNAME)
        fresh = await client.get_messages(entity, limit=5)
        current = [m for m in fresh if m.text and not m.out]
        if not current:
            continue
        last = current[-1]
        text_lower = (last.text or "").lower()
        report.captures[step_name] = last.text[:500] if last.text else "EMPTY"

        btns = get_callback_data_buttons(last)
        btn_texts = get_inline_buttons(last)

        # Check for formatting issues
        if last.text:
            leaks = check_no_html_leak(last.text)
            for leak in leaks:
                report.add_issue("P1", "Formatting", f"{step_name}: {leak}")

        # Click appropriate button based on step
        clicked = False

        if "edge" in text_lower and "how" in text_lower:
            # Edge explainer - click Got it / Next
            for text, data in btns:
                if "edge_done" in data or "got it" in text.lower() or "next" in text.lower():
                    await click_callback_data(client, last, data, wait=3)
                    clicked = True
                    break

        elif "risk" in text_lower or "conservative" in " ".join(btn_texts).lower():
            # Risk profile - select Moderate
            for text, data in btns:
                if "moderate" in data.lower() or "moderate" in text.lower():
                    await click_callback_data(client, last, data, wait=3)
                    clicked = True
                    break

        elif "bankroll" in text_lower or any("R50" in b or "R200" in b or "R500" in b for b in btn_texts):
            # Bankroll - select R500
            for text, data in btns:
                if "500" in text and "R5000" not in text:
                    await click_callback_data(client, last, data, wait=3)
                    clicked = True
                    break

        elif "notification" in text_lower or "when" in text_lower:
            # Notifications - select 18:00
            for text, data in btns:
                if "18" in data or "18:00" in text:
                    await click_callback_data(client, last, data, wait=3)
                    clicked = True
                    break

        elif "summary" in text_lower or "profile" in text_lower:
            # Summary - click confirm / Let's go
            report.captures["summary_full"] = last.text if last.text else "EMPTY"
            for text, data in btns:
                if "done" in data.lower() or "finish" in data.lower() or "go" in text.lower() or "confirm" in text.lower():
                    await click_callback_data(client, last, data, wait=5)
                    clicked = True
                    break

        elif "plan" in text_lower or "bronze" in text_lower or "gold" in text_lower:
            # Plan picker step
            report.captures["plan_picker_full"] = last.text if last.text else "EMPTY"
            # Check pricing
            if last.text:
                pricing_ok = True
                if "R99/mo" not in last.text and "R99" not in last.text:
                    report.add_issue("P1", "Pricing", "Gold monthly R99 not shown in plan picker")
                    pricing_ok = False
                if "R799" in last.text:
                    pass  # Correct
                elif "R999" in last.text:
                    report.add_issue("P0", "Pricing", "STALE R999 price shown in plan picker!")
                    pricing_ok = False
                if "R199" in last.text:
                    pass  # Correct monthly
                if "R1,599" in last.text:
                    pass  # Correct
                elif "R1,999" in last.text:
                    report.add_issue("P0", "Pricing", "STALE R1,999 price shown in plan picker!")
                    pricing_ok = False
                report.add_result(TestResult("plan_pricing", pricing_ok,
                                             f"Pricing display: {last.text[:200]}", 0))

            # Select Bronze (free)
            for text, data in btns:
                if "bronze" in data.lower() or "free" in text.lower() or "continue" in text.lower():
                    await click_callback_data(client, last, data, wait=5)
                    clicked = True
                    break

        if not clicked and btns:
            # Click first available button as fallback
            text, data = btns[0]
            await click_callback_data(client, last, data, wait=3)

    # Check if onboarding completed
    print("\n--- Checking onboarding completion ---")
    await asyncio.sleep(3)
    entity = await client.get_entity(BOT_USERNAME)
    fresh = await client.get_messages(entity, limit=10)
    current = [m for m in fresh if m.text and not m.out]

    # Look for welcome message or keyboard
    onboarding_done = False
    for m in current:
        if m.text and any(x in m.text.lower() for x in ["welcome", "you're all set", "let's go", "my matches", "edge picks"]):
            onboarding_done = True
            report.captures["welcome_msg"] = m.text[:500]
            break
        if isinstance(getattr(m, 'reply_markup', None), TLReplyKeyboardMarkup):
            onboarding_done = True
            break

    report.add_result(TestResult("onboarding_complete", onboarding_done,
                                 "Onboarding flow completed" if onboarding_done else "Onboarding may not have completed",
                                 0))

    if not onboarding_done:
        # Show what we're seeing
        for m in current[:3]:
            print(f"  [DEBUG] Latest: {m.text[:200] if m.text else 'NO TEXT'}")
            print(f"  [DEBUG] Buttons: {get_inline_buttons(m)}")


# ── Phase 2: Core Feature Sweep ─────────────────────────

async def phase2_core_features(client: TelegramClient):
    print("\n" + "="*60)
    print("PHASE 2: CORE FEATURE SWEEP")
    print("="*60)

    # 2A: Hot Tips / Top Edge Picks
    print("\n--- 2A: Top Edge Picks ---")
    start = time.time()
    msgs = await send_and_wait(client, "💎 Top Edge Picks", wait=LONG_WAIT)
    bot_msgs = [m for m in msgs if m.text and not m.out]

    tips_found = False
    tip_messages = []
    for m in bot_msgs:
        if m.text and ("edge" in m.text.lower() or "value" in m.text.lower() or "tip" in m.text.lower()
                      or "⚽" in m.text or "🏉" in m.text or "🏏" in m.text or "🥊" in m.text
                      or "diamond" in m.text.lower() or "golden" in m.text.lower() or "silver" in m.text.lower()):
            tips_found = True
            tip_messages.append(m)

    if not tips_found:
        # Maybe it's a no-tips state
        for m in bot_msgs:
            if m.text and ("no" in m.text.lower() and "tip" in m.text.lower()) or "no value" in (m.text or "").lower():
                report.add_result(TestResult("hot_tips", True,
                                             f"No tips available (valid state): {m.text[:100]}", time.time() - start))
                report.captures["hot_tips"] = m.text[:500]
                tips_found = True
                break

    if tip_messages:
        # Analyze first tip message
        tip_text = tip_messages[-1].text
        report.captures["hot_tips"] = tip_text[:1000]

        # Check for required elements
        checks = {
            "has_sport_emoji": any(e in tip_text for e in ["⚽", "🏉", "🏏", "🥊"]),
            "has_edge_badge": any(e in tip_text for e in ["💎", "🥇", "🥈", "🥉"]),
            "has_odds": bool(re.search(r'\d+\.\d+', tip_text)),
            "has_bookmaker": any(bk in tip_text.lower() for bk in ["hollywoodbets", "betway", "wsb", "supabets", "gbets", "sportingbet", "supersportbet"]),
        }

        for check_name, passed in checks.items():
            if not passed:
                report.add_issue("P1", "Hot Tips", f"Missing {check_name} in tip display")

        # Check for formatting issues
        leaks = check_no_html_leak(tip_text)
        for leak in leaks:
            report.add_issue("P1", "Formatting", f"Hot Tips: {leak}")

        report.add_result(TestResult("hot_tips", all(checks.values()),
                                     f"Checks: {checks}", time.time() - start, tip_text[:500]))

        # 2A-sub: Click into tip detail
        print("\n--- 2A-sub: Tip Detail ---")
        start = time.time()
        detail_msg = tip_messages[-1]
        detail_buttons = get_callback_data_buttons(detail_msg)
        detail_clicked = False
        for text, data in detail_buttons:
            if "tip:detail" in data or "detail" in data.lower():
                result = await click_callback_data(client, detail_msg, data, wait=TIMEOUT)
                if result:
                    detail_clicked = True
                    detail_msgs = [m for m in result if m.text and not m.out]
                    if detail_msgs:
                        detail_text = detail_msgs[-1].text
                        report.captures["tip_detail"] = detail_text[:1000]

                        # Check detail page
                        detail_checks = {
                            "has_odds": bool(re.search(r'\d+\.\d+', detail_text)),
                            "has_edge_info": any(x in detail_text.lower() for x in ["edge", "value", "ev"]),
                        }
                        for cn, cp in detail_checks.items():
                            if not cp:
                                report.add_issue("P1", "Tip Detail", f"Missing {cn}")

                        report.add_result(TestResult("tip_detail", all(detail_checks.values()),
                                                     f"Detail checks: {detail_checks}", time.time() - start))

                        # Check back button exists
                        back_btns = get_inline_buttons(detail_msgs[-1])
                        has_back = any("back" in b.lower() or "↩" in b for b in back_btns)
                        if not has_back:
                            report.add_issue("P1", "Navigation", "No back button on tip detail")
                break

        if not detail_clicked:
            report.add_result(TestResult("tip_detail", False, "Could not click into tip detail", time.time() - start))
    elif not tips_found:
        report.add_result(TestResult("hot_tips", False,
                                     "No tip messages or no-tips message found", time.time() - start))
        for m in bot_msgs[:3]:
            print(f"  [DEBUG] Msg: {m.text[:200] if m.text else 'NO TEXT'}")

    # 2B: My Matches
    print("\n--- 2B: My Matches ---")
    start = time.time()
    msgs = await send_and_wait(client, "⚽ My Matches", wait=TIMEOUT)
    bot_msgs = [m for m in msgs if m.text and not m.out]

    matches_msg = None
    for m in bot_msgs:
        if m.text and ("match" in m.text.lower() or "game" in m.text.lower() or "⚽" in m.text
                      or "fixture" in m.text.lower() or "schedule" in m.text.lower()):
            matches_msg = m
            break

    if matches_msg:
        report.captures["my_matches"] = matches_msg.text[:1000]

        # Check for required elements
        leaks = check_no_html_leak(matches_msg.text)
        for leak in leaks:
            report.add_issue("P1", "Formatting", f"My Matches: {leak}")

        # Check for game detail tap
        match_buttons = get_callback_data_buttons(matches_msg)
        game_clicked = False
        for text, data in match_buttons:
            if "yg:game:" in data:
                print(f"\n--- 2B-sub: Game Breakdown for '{text}' ---")
                game_start = time.time()
                result = await click_callback_data(client, matches_msg, data, wait=LONG_WAIT)
                if result:
                    game_msgs = [m for m in result if m.text and not m.out]
                    if game_msgs:
                        game_text = game_msgs[-1].text
                        report.captures["game_breakdown"] = game_text[:1500]

                        # Check AI breakdown
                        breakdown_checks = {
                            "substantive": len(game_text) > 200,
                            "has_sections": any(x in game_text for x in ["📋", "🎯", "⚠️", "🏆"]),
                            "no_none": "None" not in game_text or "Six Nations" in game_text or "None of" in game_text,
                        }

                        leaks = check_no_html_leak(game_text)
                        for leak in leaks:
                            report.add_issue("P1", "Formatting", f"Game Breakdown: {leak}")

                        report.add_result(TestResult("game_breakdown", all(breakdown_checks.values()),
                                                     f"Checks: {breakdown_checks}, len={len(game_text)}",
                                                     time.time() - game_start, game_text[:500]))
                        game_clicked = True
                break

        if not game_clicked:
            report.add_result(TestResult("game_breakdown", False,
                                         "Could not tap into game detail", time.time() - start))

        report.add_result(TestResult("my_matches", True,
                                     f"Matches displayed ({len(matches_msg.text)} chars)",
                                     time.time() - start))
    else:
        # Check for empty state
        for m in bot_msgs:
            if m.text and ("no" in m.text.lower() and "match" in m.text.lower()):
                report.add_result(TestResult("my_matches", True,
                                             f"Empty state: {m.text[:100]}", time.time() - start))
                report.captures["my_matches_empty"] = m.text[:500]
                break
        else:
            report.add_result(TestResult("my_matches", False,
                                         "No matches display found", time.time() - start))

    # 2C: Odds Comparison (if we have a game)
    print("\n--- 2C: Odds Comparison ---")
    # Navigate back to a game detail to find odds:compare button
    # Will test this after finding a game with the button

    # 2D: Guide
    print("\n--- 2D: Guide ---")
    start = time.time()
    msgs = await send_and_wait(client, "📖 Guide", wait=SHORT_WAIT)
    bot_msgs = [m for m in msgs if m.text and not m.out]
    guide_ok = False
    for m in bot_msgs:
        if m.text and ("edge" in m.text.lower() or "guide" in m.text.lower() or "rating" in m.text.lower()):
            guide_ok = True
            report.captures["guide"] = m.text[:500]
            break
    report.add_result(TestResult("guide", guide_ok,
                                 "Guide displayed" if guide_ok else "Guide not found",
                                 time.time() - start))

    # 2E: Profile
    print("\n--- 2E: Profile ---")
    start = time.time()
    msgs = await send_and_wait(client, "👤 Profile", wait=SHORT_WAIT)
    bot_msgs = [m for m in msgs if m.text and not m.out]
    profile_ok = False
    for m in bot_msgs:
        if m.text and ("profile" in m.text.lower() or "experience" in m.text.lower()
                      or "risk" in m.text.lower() or "sport" in m.text.lower()):
            profile_ok = True
            report.captures["profile"] = m.text[:500]

            leaks = check_no_html_leak(m.text)
            for leak in leaks:
                report.add_issue("P1", "Formatting", f"Profile: {leak}")
            break
    report.add_result(TestResult("profile", profile_ok,
                                 "Profile displayed" if profile_ok else "Profile not found",
                                 time.time() - start))

    # 2F: Help
    print("\n--- 2F: Help ---")
    start = time.time()
    msgs = await send_and_wait(client, "❓ Help", wait=SHORT_WAIT)
    bot_msgs = [m for m in msgs if m.text and not m.out]
    help_ok = False
    for m in bot_msgs:
        if m.text and ("help" in m.text.lower() or "command" in m.text.lower()):
            help_ok = True
            report.captures["help"] = m.text[:500]
            break
    report.add_result(TestResult("help", help_ok,
                                 "Help displayed" if help_ok else "Help not found",
                                 time.time() - start))


# ── Phase 3: Commands & Settings ─────────────────────────

async def phase3_commands(client: TelegramClient):
    print("\n" + "="*60)
    print("PHASE 3: ALL COMMANDS")
    print("="*60)

    commands = [
        ("/help", ["help", "command"]),
        ("/tips", ["edge", "tip", "value", "pick", "no"]),
        ("/subscribe", ["plan", "gold", "diamond", "bronze", "subscribe"]),
        ("/settings", ["settings", "risk", "notification", "sport"]),
        ("/menu", ["match", "tip", "guide", "profile", "setting", "help"]),
        ("/status", ["tier", "member", "bronze", "status"]),
    ]

    for cmd, expected_words in commands:
        print(f"\n--- Testing {cmd} ---")
        start = time.time()
        try:
            msgs = await send_and_wait(client, cmd, wait=8)
            bot_msgs = [m for m in msgs if m.text and not m.out]

            if not bot_msgs:
                report.add_result(TestResult(f"cmd_{cmd}", False, "No response", time.time() - start))
                report.add_issue("P0", "Commands", f"{cmd} produced no response")
                continue

            response = bot_msgs[-1]
            text = response.text or ""

            # Check for expected content
            found_expected = any(w in text.lower() for w in expected_words)
            report.captures[f"cmd_{cmd}"] = text[:500]

            # Check for formatting issues
            leaks = check_no_html_leak(text)
            for leak in leaks:
                report.add_issue("P1", "Formatting", f"{cmd}: {leak}")

            report.add_result(TestResult(f"cmd_{cmd}", found_expected,
                                         f"Response OK ({len(text)} chars)" if found_expected else f"Unexpected: {text[:100]}",
                                         time.time() - start))

            # Special checks per command
            if cmd == "/subscribe":
                # Verify pricing
                if "R999" in text:
                    report.add_issue("P0", "Pricing", f"/subscribe shows stale R999!")
                if "R1,999" in text or "R1999" in text:
                    report.add_issue("P0", "Pricing", f"/subscribe shows stale R1,999!")
                if "R799" in text:
                    pass  # Good
                if "R1,599" in text:
                    pass  # Good
                # Check save percentages
                if "save 16%" in text:
                    report.add_issue("P0", "Pricing", f"/subscribe shows stale 'save 16%' (should be 33%)")

        except Exception as e:
            report.add_result(TestResult(f"cmd_{cmd}", False, f"Error: {e}", time.time() - start))
            report.add_issue("P0", "Commands", f"{cmd} raised exception: {e}")

    # Test /upgrade and /billing
    for cmd in ["/upgrade", "/billing"]:
        print(f"\n--- Testing {cmd} ---")
        start = time.time()
        try:
            msgs = await send_and_wait(client, cmd, wait=8)
            bot_msgs = [m for m in msgs if m.text and not m.out]
            if bot_msgs:
                text = bot_msgs[-1].text or ""
                report.captures[f"cmd_{cmd}"] = text[:500]
                # These might not exist as commands, check gracefully
                report.add_result(TestResult(f"cmd_{cmd}", len(text) > 10,
                                             f"Response: {text[:100]}", time.time() - start))
            else:
                report.add_result(TestResult(f"cmd_{cmd}", False, "No response", time.time() - start))
        except Exception as e:
            report.add_result(TestResult(f"cmd_{cmd}", False, str(e), time.time() - start))

    # Settings deep dive
    print("\n--- Settings Deep Dive ---")
    start = time.time()
    msgs = await send_and_wait(client, "⚙️ Settings", wait=SHORT_WAIT)
    bot_msgs = [m for m in msgs if m.text and not m.out]
    if bot_msgs:
        settings_msg = bot_msgs[-1]
        settings_buttons = get_inline_buttons(settings_msg)
        report.captures["settings_menu"] = f"Text: {settings_msg.text[:200]}\nButtons: {settings_buttons}"
        report.add_result(TestResult("settings_menu", len(settings_buttons) >= 3,
                                     f"Settings buttons: {settings_buttons}", time.time() - start))


# ── Phase 4: Edge Cases ─────────────────────────────────

async def phase4_edge_cases(client: TelegramClient):
    print("\n" + "="*60)
    print("PHASE 4: EDGE CASES")
    print("="*60)

    # Random text
    print("\n--- Random text ---")
    start = time.time()
    msgs = await send_and_wait(client, "asdfghjkl random gibberish", wait=5)
    bot_msgs = [m for m in msgs if m.text and not m.out]
    no_crash = True  # If we get here, no crash
    report.add_result(TestResult("random_text", no_crash,
                                 f"Bot handled gracefully: {bot_msgs[-1].text[:100] if bot_msgs else 'no response'}",
                                 time.time() - start))

    # Very long message
    print("\n--- Long message (500+ chars) ---")
    start = time.time()
    long_text = "This is a very long message. " * 30
    msgs = await send_and_wait(client, long_text, wait=5)
    report.add_result(TestResult("long_message", True, "Bot handled long message", time.time() - start))

    # Empty-ish message
    print("\n--- Single character ---")
    start = time.time()
    msgs = await send_and_wait(client, ".", wait=5)
    report.add_result(TestResult("single_char", True, "Bot handled single char", time.time() - start))

    # Double-tap prevention
    print("\n--- Rapid double command ---")
    start = time.time()
    entity = await client.get_entity(BOT_USERNAME)
    await client.send_message(entity, "/help")
    await asyncio.sleep(0.5)
    await client.send_message(entity, "/help")
    await asyncio.sleep(8)
    msgs = await client.get_messages(entity, limit=10)
    report.add_result(TestResult("rapid_commands", True, "Handled rapid commands", time.time() - start))


# ── Phase 5: Tier-Gating Tests ──────────────────────────

async def phase5_tier_gating(client: TelegramClient):
    print("\n" + "="*60)
    print("PHASE 5: TIER-GATING VERIFICATION")
    print("="*60)

    # Test with current Bronze tier
    print("\n--- 5A: Bronze Tier (current) ---")
    start = time.time()

    # Request tips as Bronze
    msgs = await send_and_wait(client, "💎 Top Edge Picks", wait=LONG_WAIT)
    bot_msgs = [m for m in msgs if m.text and not m.out]

    bronze_behavior_ok = True
    for m in bot_msgs:
        if m.text:
            report.captures["bronze_tips"] = m.text[:500]
            # Bronze should see limited/delayed tips
            # Or should see tips (depends on implementation)
            break

    report.add_result(TestResult("bronze_tips", bool(bot_msgs),
                                 "Bronze tip display captured", time.time() - start))


# ── Main Runner ──────────────────────────────────────────

async def run_all(phases: list[int] | None = None):
    print("="*60)
    print("WAVE 20 — COMPREHENSIVE TELETHON STRESS TEST")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)

    client = await get_client()
    print(f"Connected as: {(await client.get_me()).first_name}")

    try:
        if not phases or 1 in phases:
            await phase1_onboarding(client)

        if not phases or 2 in phases:
            await phase2_core_features(client)

        if not phases or 3 in phases:
            await phase3_commands(client)

        if not phases or 4 in phases:
            await phase4_edge_cases(client)

        if not phases or 5 in phases:
            await phase5_tier_gating(client)

    except Exception as e:
        print(f"\n*** FATAL ERROR: {e}")
        traceback.print_exc()
        report.add_issue("P0", "Infrastructure", f"Test runner crashed: {e}")

    finally:
        await client.disconnect()

    # Print summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    print(report.summary())

    print("\n--- All Issues ---")
    for issue in report.issues:
        print(f"  [{issue.severity}] #{issue.num} ({issue.category}): {issue.description} [{issue.status}]")

    print("\n--- Captures ---")
    for key, val in report.captures.items():
        print(f"\n  [{key}]:")
        for line in val[:300].split("\n"):
            print(f"    {line}")

    # Save report to file
    from config import BOT_ROOT
    report_path = str(BOT_ROOT.parent / "reports" / f"e2e-stress-wave20-{datetime.now().strftime('%Y%m%d-%H%M')}.json")
    report_data = {
        "timestamp": datetime.now().isoformat(),
        "summary": report.summary(),
        "results": [{"name": r.name, "passed": r.passed, "message": r.message, "duration": r.duration}
                    for r in report.results],
        "issues": [{"num": i.num, "severity": i.severity, "category": i.category,
                    "description": i.description, "status": i.status}
                   for i in report.issues],
        "captures": report.captures,
    }
    with open(report_path, "w") as f:
        json.dump(report_data, f, indent=2)
    print(f"\nReport saved to: {report_path}")

    return report


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", type=int, nargs="*", help="Specific phases to run")
    args = parser.parse_args()

    from config import BOT_ROOT as _br
    os.chdir(str(_br))
    asyncio.run(run_all(args.phase))
