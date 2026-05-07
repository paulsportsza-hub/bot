"""UX Phase 0D-VERIFY: Onboarding Perfection Sweep.

Telethon-based E2E tests that run the full onboarding flow and capture
every message for human review.

Usage:
    cd /home/paulsportsza/bot
    source .venv/bin/activate
    python tests/test_onboarding_ux.py --walkthrough 1
    python tests/test_onboarding_ux.py --walkthrough 2
    python tests/test_onboarding_ux.py --walkthrough 3a
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import (
    ReplyKeyboardMarkup as TLReplyKeyboardMarkup,
    ReplyInlineMarkup,
    KeyboardButtonCallback,
    KeyboardButtonUrl,
)
try:
    from telethon.tl.types import ReplyKeyboardHide as ReplyKeyboardRemove
except ImportError:
    ReplyKeyboardRemove = None  # type: ignore

# ── Configuration ────────────────────────────────────────

API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "")
BOT_USERNAME = "mzansiedge_bot"

with open(os.path.join(os.path.dirname(__file__), "..", "data", "telethon_qa_session.string")) as f:
    SESSION_STR = f.read().strip()

WAIT_SHORT = 4  # seconds for quick responses
WAIT_MEDIUM = 8  # for AI-generated content
WAIT_LONG = 15  # for complex operations


# ── Data structures ──────────────────────────────────────

@dataclass
class CapturedMessage:
    """A single bot message captured during the flow."""
    text: str
    buttons: list[str] = field(default_factory=list)
    url_buttons: list[dict] = field(default_factory=list)
    has_reply_keyboard: bool = False
    reply_keyboard_labels: list[str] = field(default_factory=list)
    reply_keyboard_removed: bool = False
    raw_markup_type: str = ""
    timestamp: float = 0.0


@dataclass
class FlowStep:
    """A step in the onboarding flow: what we sent + what we got back."""
    action: str  # what we did
    action_detail: str = ""
    responses: list[CapturedMessage] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)  # observations
    bugs: list[str] = field(default_factory=list)  # bugs found


# ── Helpers ──────────────────────────────────────────────

async def get_client() -> TelegramClient:
    client = TelegramClient(StringSession(SESSION_STR), API_ID, API_HASH)
    await client.connect()
    if not await client.is_user_authorized():
        print("ERROR: Not logged in.")
        sys.exit(1)
    return client


def extract_message(msg) -> CapturedMessage:
    """Extract structured data from a Telethon message."""
    cm = CapturedMessage(
        text=msg.text or msg.message or "",
        timestamp=time.time(),
    )

    if msg.reply_markup:
        if isinstance(msg.reply_markup, ReplyInlineMarkup):
            cm.raw_markup_type = "inline"
            for row in msg.reply_markup.rows:
                for btn in row.buttons:
                    if isinstance(btn, KeyboardButtonCallback):
                        cm.buttons.append(btn.text)
                    elif isinstance(btn, KeyboardButtonUrl):
                        cm.url_buttons.append({"text": btn.text, "url": btn.url})
                    elif hasattr(btn, "text"):
                        cm.buttons.append(btn.text)
        elif isinstance(msg.reply_markup, TLReplyKeyboardMarkup):
            cm.raw_markup_type = "reply_keyboard"
            cm.has_reply_keyboard = True
            for row in msg.reply_markup.rows:
                for btn in row.buttons:
                    cm.reply_keyboard_labels.append(btn.text)
        elif isinstance(msg.reply_markup, ReplyKeyboardRemove):
            cm.raw_markup_type = "reply_keyboard_remove"
            cm.reply_keyboard_removed = True

    return cm


async def send_and_capture(client, text, wait=WAIT_SHORT) -> list[CapturedMessage]:
    """Send a message and capture bot responses."""
    entity = await client.get_entity(BOT_USERNAME)
    # Note the last message ID before sending
    before = await client.get_messages(entity, limit=1)
    before_id = before[0].id if before else 0

    await client.send_message(entity, text)
    await asyncio.sleep(wait)

    # Get all messages after our send
    msgs = await client.get_messages(entity, limit=20)
    results = []
    for m in reversed(msgs):
        if m.id > before_id and not m.out:  # bot messages only
            results.append(extract_message(m))

    return results


async def click_inline_button(client, entity, button_text, wait=WAIT_SHORT) -> list[CapturedMessage]:
    """Click an inline button and capture responses (handles both edits and new messages)."""
    msgs = await client.get_messages(entity, limit=5)
    # Snapshot current message texts to detect edits
    before_texts = {m.id: (m.text or "") for m in msgs if not m.out}
    latest_id = msgs[0].id if msgs else 0

    for msg in msgs:
        if msg.reply_markup and isinstance(msg.reply_markup, ReplyInlineMarkup):
            for row in msg.reply_markup.rows:
                for btn in row.buttons:
                    if isinstance(btn, KeyboardButtonCallback) and button_text in btn.text:
                        await msg.click(data=btn.data)
                        await asyncio.sleep(wait)
                        # Re-fetch: capture both edited messages and new ones
                        new_msgs = await client.get_messages(entity, limit=20)
                        results = []
                        for m in reversed(new_msgs):
                            if m.out:
                                continue
                            old_text = before_texts.get(m.id)
                            if m.id > latest_id:
                                # New message
                                results.append(extract_message(m))
                            elif old_text is not None and (m.text or "") != old_text:
                                # Edited message
                                results.append(extract_message(m))
                            elif m.id == msg.id:
                                # The clicked message itself (might have been edited)
                                results.append(extract_message(m))
                        return results
    print(f"  WARNING: Button '{button_text}' not found in recent messages")
    return []


async def reset_user(client):
    """Reset user profile via DB to force fresh onboarding."""
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
    from db import async_session, User, UserSportPref
    from sqlalchemy import select, delete

    me = await client.get_me()
    user_id = me.id

    async with async_session() as s:
        # Delete sport prefs
        await s.execute(delete(UserSportPref).where(UserSportPref.user_id == user_id))
        # Reset user
        result = await s.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user:
            user.onboarding_done = False
            user.experience_level = None
            user.risk_profile = None
            user.bankroll = None
            user.notification_hour = None
            user.archetype = None
            user.engagement_score = None
            user.notification_prefs = None
        await s.commit()

    print(f"  Reset user {user_id} ({me.first_name})")


# ── Walkthrough #1: SA Sports Fan ────────────────────────

async def walkthrough_1(client) -> list[FlowStep]:
    """Full onboarding: all 4 sports, SA teams."""
    entity = await client.get_entity(BOT_USERNAME)
    steps: list[FlowStep] = []

    # Step 0: Reset and /start
    step = FlowStep(action="Reset + /start")
    await reset_user(client)
    await asyncio.sleep(1)
    responses = await send_and_capture(client, "/start", wait=WAIT_SHORT)
    step.responses = responses
    for r in responses:
        print(f"  BOT: {r.text[:120]}...")
        if r.buttons:
            print(f"  BUTTONS: {r.buttons}")
    steps.append(step)

    # Step 1: Experience level — pick "Casual" (button text: "I've placed a few bets")
    step = FlowStep(action="Select experience: Casual")
    responses = await click_inline_button(client, entity, "placed a few", wait=WAIT_SHORT)
    step.responses = responses
    for r in responses:
        print(f"  BOT: {r.text[:120]}...")
        if r.buttons:
            print(f"  BUTTONS: {r.buttons}")
    steps.append(step)

    # Step 2: Sports selection — toggle all 4
    for sport in ["Soccer", "Rugby", "Cricket", "Combat"]:
        step = FlowStep(action=f"Toggle sport: {sport}")
        responses = await click_inline_button(client, entity, sport, wait=2)
        step.responses = responses
        for r in responses:
            if r.buttons:
                print(f"  Toggled {sport}: buttons={r.buttons}")
        steps.append(step)

    # Confirm sports
    step = FlowStep(action="Confirm sports: Done")
    responses = await click_inline_button(client, entity, "Done", wait=WAIT_SHORT)
    step.responses = responses
    for r in responses:
        print(f"  BOT: {r.text[:120]}...")
    steps.append(step)

    # Step 3a: Soccer teams
    step = FlowStep(action="Soccer teams: Chiefs, Man United, Liverpool")
    responses = await send_and_capture(client, "Chiefs, Man United, Liverpool", wait=WAIT_MEDIUM)
    step.responses = responses
    for r in responses:
        print(f"  BOT: {r.text}")
        if r.buttons:
            print(f"  BUTTONS: {r.buttons}")
    steps.append(step)

    # Continue to next sport
    step = FlowStep(action="Continue to Rugby")
    responses = await click_inline_button(client, entity, "Continue", wait=WAIT_SHORT)
    step.responses = responses
    for r in responses:
        print(f"  BOT: {r.text[:120]}...")
    steps.append(step)

    # Step 3b: Rugby teams
    step = FlowStep(action="Rugby teams: Springboks, Stormers")
    responses = await send_and_capture(client, "Springboks, Stormers", wait=WAIT_MEDIUM)
    step.responses = responses
    for r in responses:
        print(f"  BOT: {r.text}")
        if r.buttons:
            print(f"  BUTTONS: {r.buttons}")
    steps.append(step)

    # Continue to cricket
    step = FlowStep(action="Continue to Cricket")
    responses = await click_inline_button(client, entity, "Continue", wait=WAIT_SHORT)
    step.responses = responses
    for r in responses:
        print(f"  BOT: {r.text[:120]}...")
    steps.append(step)

    # Step 3c: Cricket teams
    step = FlowStep(action="Cricket teams: Proteas, India")
    responses = await send_and_capture(client, "Proteas, India", wait=WAIT_MEDIUM)
    step.responses = responses
    for r in responses:
        print(f"  BOT: {r.text}")
        if r.buttons:
            print(f"  BUTTONS: {r.buttons}")
    steps.append(step)

    # Continue to combat
    step = FlowStep(action="Continue to Combat")
    responses = await click_inline_button(client, entity, "Continue", wait=WAIT_SHORT)
    step.responses = responses
    for r in responses:
        print(f"  BOT: {r.text[:120]}...")
    steps.append(step)

    # Step 3d: Combat fighters
    step = FlowStep(action="Combat fighters: Dricus, Canelo")
    responses = await send_and_capture(client, "Dricus, Canelo", wait=WAIT_MEDIUM)
    step.responses = responses
    for r in responses:
        print(f"  BOT: {r.text}")
        if r.buttons:
            print(f"  BUTTONS: {r.buttons}")
    steps.append(step)

    # Continue to edge explainer (casual users see this)
    step = FlowStep(action="Continue to Edge Explainer")
    responses = await click_inline_button(client, entity, "Continue", wait=WAIT_SHORT)
    step.responses = responses
    for r in responses:
        print(f"  BOT: {r.text[:200]}...")
        if r.buttons:
            print(f"  BUTTONS: {r.buttons}")
    steps.append(step)

    # Edge explainer: Got it
    step = FlowStep(action="Edge Explainer: Got it")
    responses = await click_inline_button(client, entity, "Got it", wait=WAIT_SHORT)
    step.responses = responses
    for r in responses:
        print(f"  BOT: {r.text[:150]}...")
        if r.buttons:
            print(f"  BUTTONS: {r.buttons}")
    steps.append(step)

    # Step 4: Risk profile — Moderate
    step = FlowStep(action="Risk: Moderate")
    responses = await click_inline_button(client, entity, "Moderate", wait=WAIT_SHORT)
    step.responses = responses
    for r in responses:
        print(f"  BOT: {r.text[:150]}...")
        if r.buttons:
            print(f"  BUTTONS: {r.buttons}")
    steps.append(step)

    # Bankroll: R1000
    step = FlowStep(action="Bankroll: R1000")
    responses = await click_inline_button(client, entity, "R1,000", wait=WAIT_SHORT)
    step.responses = responses
    for r in responses:
        print(f"  BOT: {r.text[:150]}...")
        if r.buttons:
            print(f"  BUTTONS: {r.buttons}")
    steps.append(step)

    # Notify: 18:00
    step = FlowStep(action="Notify: 18:00")
    responses = await click_inline_button(client, entity, "18:00", wait=WAIT_SHORT)
    step.responses = responses
    for r in responses:
        print(f"  BOT: {r.text[:200]}...")
        if r.buttons:
            print(f"  BUTTONS: {r.buttons}")
    steps.append(step)

    # Step 5: Summary — Let's go!
    step = FlowStep(action="Confirm: Let's go!")
    responses = await click_inline_button(client, entity, "Let's go", wait=WAIT_LONG)
    step.responses = responses
    for r in responses:
        print(f"  BOT: {r.text[:200]}...")
        if r.buttons:
            print(f"  BUTTONS: {r.buttons}")
        if r.has_reply_keyboard:
            print(f"  REPLY KB: {r.reply_keyboard_labels}")
    steps.append(step)

    return steps


# ── Walkthrough #2: Casual Bettor ────────────────────────

async def walkthrough_2(client) -> list[FlowStep]:
    """Soccer + Combat only, skip combat teams."""
    entity = await client.get_entity(BOT_USERNAME)
    steps: list[FlowStep] = []

    # Reset and /start
    step = FlowStep(action="Reset + /start")
    await reset_user(client)
    await asyncio.sleep(1)
    responses = await send_and_capture(client, "/start", wait=WAIT_SHORT)
    step.responses = responses
    steps.append(step)

    # Experience: Experienced (button: "I bet regularly")
    step = FlowStep(action="Select experience: Experienced")
    responses = await click_inline_button(client, entity, "bet regularly", wait=WAIT_SHORT)
    step.responses = responses
    steps.append(step)

    # Toggle Soccer + Combat
    for sport in ["Soccer", "Combat"]:
        step = FlowStep(action=f"Toggle sport: {sport}")
        responses = await click_inline_button(client, entity, sport, wait=2)
        step.responses = responses
        steps.append(step)

    # Done
    step = FlowStep(action="Confirm sports: Done")
    responses = await click_inline_button(client, entity, "Done", wait=WAIT_SHORT)
    step.responses = responses
    for r in responses:
        print(f"  BOT: {r.text[:120]}...")
    steps.append(step)

    # Soccer teams: Barca, Arsenal
    step = FlowStep(action="Soccer teams: Barca, Arsenal")
    responses = await send_and_capture(client, "Barca, Arsenal", wait=WAIT_MEDIUM)
    step.responses = responses
    for r in responses:
        print(f"  BOT: {r.text}")
    steps.append(step)

    # Continue to Combat
    step = FlowStep(action="Continue to Combat")
    responses = await click_inline_button(client, entity, "Continue", wait=WAIT_SHORT)
    step.responses = responses
    for r in responses:
        print(f"  BOT: {r.text[:120]}...")
    steps.append(step)

    # Skip combat
    step = FlowStep(action="Skip combat teams")
    responses = await click_inline_button(client, entity, "Skip", wait=WAIT_SHORT)
    step.responses = responses
    for r in responses:
        print(f"  BOT: {r.text[:200]}...")
        if r.buttons:
            print(f"  BUTTONS: {r.buttons}")
    steps.append(step)

    # Experienced users skip edge explainer → go straight to risk
    step = FlowStep(action="Risk: Aggressive")
    responses = await click_inline_button(client, entity, "Aggressive", wait=WAIT_SHORT)
    step.responses = responses
    for r in responses:
        print(f"  BOT: {r.text[:150]}...")
    steps.append(step)

    # Bankroll: skip
    step = FlowStep(action="Bankroll: Skip")
    responses = await click_inline_button(client, entity, "Not sure", wait=WAIT_SHORT)
    step.responses = responses
    for r in responses:
        print(f"  BOT: {r.text[:150]}...")
    steps.append(step)

    # Notify: 07:00
    step = FlowStep(action="Notify: 07:00")
    responses = await click_inline_button(client, entity, "07:00", wait=WAIT_SHORT)
    step.responses = responses
    for r in responses:
        print(f"  BOT: {r.text[:200]}...")
        if r.buttons:
            print(f"  BUTTONS: {r.buttons}")
    steps.append(step)

    # Confirm
    step = FlowStep(action="Confirm: Let's go!")
    responses = await click_inline_button(client, entity, "Let's go", wait=WAIT_LONG)
    step.responses = responses
    for r in responses:
        print(f"  BOT: {r.text[:200]}...")
    steps.append(step)

    return steps


# ── Walkthrough #3a: Typos and nicknames ─────────────────

async def walkthrough_3a(client) -> list[FlowStep]:
    """Test typos and cross-sport nicknames."""
    entity = await client.get_entity(BOT_USERNAME)
    steps: list[FlowStep] = []

    # Reset and /start
    await reset_user(client)
    await asyncio.sleep(1)
    responses = await send_and_capture(client, "/start", wait=WAIT_SHORT)
    steps.append(FlowStep(action="Reset + /start", responses=responses))

    # Casual → Soccer only
    await click_inline_button(client, entity, "placed a few", wait=WAIT_SHORT)
    await click_inline_button(client, entity, "Soccer", wait=2)
    responses = await click_inline_button(client, entity, "Done", wait=WAIT_SHORT)
    steps.append(FlowStep(action="Casual → Soccer only", responses=responses))
    for r in responses:
        print(f"  BOT: {r.text[:120]}...")

    # Type: "manu, city, spurs, bokke"
    step = FlowStep(action="Soccer input: manu, city, spurs, bokke")
    responses = await send_and_capture(client, "manu, city, spurs, bokke", wait=WAIT_MEDIUM)
    step.responses = responses
    for r in responses:
        print(f"  BOT: {r.text}")
        if r.buttons:
            print(f"  BUTTONS: {r.buttons}")
    steps.append(step)

    return steps


# ── Walkthrough #3b: Single sport ────────────────────────

async def walkthrough_3b(client) -> list[FlowStep]:
    """Only rugby, type SA."""
    entity = await client.get_entity(BOT_USERNAME)
    steps: list[FlowStep] = []

    await reset_user(client)
    await asyncio.sleep(1)
    responses = await send_and_capture(client, "/start", wait=WAIT_SHORT)
    steps.append(FlowStep(action="Reset + /start", responses=responses))

    await click_inline_button(client, entity, "bet regularly", wait=WAIT_SHORT)
    await click_inline_button(client, entity, "Rugby", wait=2)
    responses = await click_inline_button(client, entity, "Done", wait=WAIT_SHORT)
    steps.append(FlowStep(action="Experienced → Rugby only", responses=responses))
    for r in responses:
        print(f"  BOT: {r.text[:120]}...")

    step = FlowStep(action="Rugby input: SA")
    responses = await send_and_capture(client, "SA", wait=WAIT_MEDIUM)
    step.responses = responses
    for r in responses:
        print(f"  BOT: {r.text}")
    steps.append(step)

    # Continue → should go to risk (experienced skips edge)
    step = FlowStep(action="Continue → Risk (experienced)")
    responses = await click_inline_button(client, entity, "Continue", wait=WAIT_SHORT)
    step.responses = responses
    for r in responses:
        print(f"  BOT: {r.text[:150]}...")
        if r.buttons:
            print(f"  BUTTONS: {r.buttons}")
    steps.append(step)

    return steps


# ── Walkthrough #3c: Skip everything ─────────────────────

async def walkthrough_3c(client) -> list[FlowStep]:
    """Select all sports, skip all team prompts."""
    entity = await client.get_entity(BOT_USERNAME)
    steps: list[FlowStep] = []

    await reset_user(client)
    await asyncio.sleep(1)
    await send_and_capture(client, "/start", wait=WAIT_SHORT)
    await click_inline_button(client, entity, "completely new", wait=WAIT_SHORT)

    for sport in ["Soccer", "Rugby", "Cricket", "Combat"]:
        await click_inline_button(client, entity, sport, wait=2)

    responses = await click_inline_button(client, entity, "Done", wait=WAIT_SHORT)
    steps.append(FlowStep(action="Newbie → All sports → Done", responses=responses))
    for r in responses:
        print(f"  BOT: {r.text[:120]}...")

    # Skip all team prompts
    for sport_name in ["Soccer", "Rugby", "Cricket", "Combat"]:
        step = FlowStep(action=f"Skip {sport_name} teams")
        responses = await click_inline_button(client, entity, "Skip", wait=WAIT_SHORT)
        step.responses = responses
        for r in responses:
            print(f"  BOT: {r.text[:120]}...")
            if r.buttons:
                print(f"  BUTTONS: {r.buttons}")
        steps.append(step)

    return steps


# ── Walkthrough #3d: Invalid input ───────────────────────

async def walkthrough_3d(client) -> list[FlowStep]:
    """Type garbage for soccer teams."""
    entity = await client.get_entity(BOT_USERNAME)
    steps: list[FlowStep] = []

    await reset_user(client)
    await asyncio.sleep(1)
    await send_and_capture(client, "/start", wait=WAIT_SHORT)
    await click_inline_button(client, entity, "Casual", wait=WAIT_SHORT)
    await click_inline_button(client, entity, "Soccer", wait=2)
    responses = await click_inline_button(client, entity, "Done", wait=WAIT_SHORT)
    steps.append(FlowStep(action="Casual → Soccer → Done", responses=responses))

    # Type garbage
    step = FlowStep(action="Invalid input: asdfghjkl, qwerty")
    responses = await send_and_capture(client, "asdfghjkl, qwerty", wait=WAIT_MEDIUM)
    step.responses = responses
    for r in responses:
        print(f"  BOT: {r.text}")
        if r.buttons:
            print(f"  BUTTONS: {r.buttons}")
    steps.append(step)

    return steps


# ── Walkthrough #3e: League name as input ────────────────

async def walkthrough_3e(client) -> list[FlowStep]:
    """Type 'Premier League' for soccer teams."""
    entity = await client.get_entity(BOT_USERNAME)
    steps: list[FlowStep] = []

    await reset_user(client)
    await asyncio.sleep(1)
    await send_and_capture(client, "/start", wait=WAIT_SHORT)
    await click_inline_button(client, entity, "placed a few", wait=WAIT_SHORT)
    await click_inline_button(client, entity, "Soccer", wait=2)
    await click_inline_button(client, entity, "Done", wait=WAIT_SHORT)

    step = FlowStep(action="League name input: Premier League")
    responses = await send_and_capture(client, "Premier League", wait=WAIT_MEDIUM)
    step.responses = responses
    for r in responses:
        print(f"  BOT: {r.text}")
    steps.append(step)

    return steps


# ── Walkthrough #3f: Mixed valid and invalid ─────────────

async def walkthrough_3f(client) -> list[FlowStep]:
    """Type 'Stormers, xyzabc, SA' for rugby."""
    entity = await client.get_entity(BOT_USERNAME)
    steps: list[FlowStep] = []

    await reset_user(client)
    await asyncio.sleep(1)
    await send_and_capture(client, "/start", wait=WAIT_SHORT)
    await click_inline_button(client, entity, "placed a few", wait=WAIT_SHORT)
    await click_inline_button(client, entity, "Rugby", wait=2)
    await click_inline_button(client, entity, "Done", wait=WAIT_SHORT)

    step = FlowStep(action="Mixed input: Stormers, xyzabc, SA")
    responses = await send_and_capture(client, "Stormers, xyzabc, SA", wait=WAIT_MEDIUM)
    step.responses = responses
    for r in responses:
        print(f"  BOT: {r.text}")
        if r.buttons:
            print(f"  BUTTONS: {r.buttons}")
    steps.append(step)

    return steps


# ── Main ─────────────────────────────────────────────────

async def main(walkthrough: str):
    client = await get_client()

    wt_map = {
        "1": ("Walkthrough #1: SA Sports Fan", walkthrough_1),
        "2": ("Walkthrough #2: Casual Bettor", walkthrough_2),
        "3a": ("Walkthrough #3a: Typos & Nicknames", walkthrough_3a),
        "3b": ("Walkthrough #3b: Single Sport", walkthrough_3b),
        "3c": ("Walkthrough #3c: Skip Everything", walkthrough_3c),
        "3d": ("Walkthrough #3d: Invalid Input", walkthrough_3d),
        "3e": ("Walkthrough #3e: League Name", walkthrough_3e),
        "3f": ("Walkthrough #3f: Mixed Valid/Invalid", walkthrough_3f),
    }

    if walkthrough == "all":
        for key in sorted(wt_map.keys()):
            label, fn = wt_map[key]
            print(f"\n{'='*60}")
            print(f"  {label}")
            print(f"{'='*60}\n")
            steps = await fn(client)
            # Save raw output
            _save_steps(key, steps)
            print(f"\n  Completed {label}: {len(steps)} steps")
            await asyncio.sleep(3)
    elif walkthrough in wt_map:
        label, fn = wt_map[walkthrough]
        print(f"\n{'='*60}")
        print(f"  {label}")
        print(f"{'='*60}\n")
        steps = await fn(client)
        _save_steps(walkthrough, steps)
        print(f"\n  Completed {label}: {len(steps)} steps")
    else:
        print(f"Unknown walkthrough: {walkthrough}")
        print(f"Available: {', '.join(sorted(wt_map.keys()))}, all")

    await client.disconnect()


def _save_steps(key: str, steps: list[FlowStep]):
    """Save steps to JSON for offline review."""
    out_dir = os.path.join(os.path.dirname(__file__), "..", "data", "ux_sweeps")
    os.makedirs(out_dir, exist_ok=True)
    out_file = os.path.join(out_dir, f"walkthrough_{key}_{datetime.now().strftime('%Y%m%d_%H%M')}.json")

    data = []
    for s in steps:
        data.append({
            "action": s.action,
            "action_detail": s.action_detail,
            "responses": [
                {
                    "text": r.text,
                    "buttons": r.buttons,
                    "url_buttons": r.url_buttons,
                    "has_reply_keyboard": r.has_reply_keyboard,
                    "reply_keyboard_labels": r.reply_keyboard_labels,
                    "reply_keyboard_removed": r.reply_keyboard_removed,
                }
                for r in s.responses
            ],
            "notes": s.notes,
            "bugs": s.bugs,
        })

    with open(out_file, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"  Saved to {out_file}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--walkthrough", "-w", default="1", help="Which walkthrough (1, 2, 3a-3f, all)")
    args = parser.parse_args()
    asyncio.run(main(args.walkthrough))
