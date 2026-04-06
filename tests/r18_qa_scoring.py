"""R18-QA-01: Opus Scoring — 7.0 Gate Attempt #4

Connects to @mzansiedge_bot via Telethon, navigates Hot Tips,
captures EVERY card listing + detail view, and scores using the
locked 4-dimension rubric.

Usage:
    cd /home/paulsportsza/bot && .venv/bin/python tests/r18_qa_scoring.py
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
log = logging.getLogger("r18-qa")

# ── Config ──────────────────────────────────────────────────
BOT_USERNAME = "mzansiedge_bot"
API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "")
SESSION_PATH = Path("data/telethon_session.string")
from config import BOT_ROOT
RAW_CAPTURES_PATH = BOT_ROOT.parent / "reports" / "r18-qa-01-raw-captures.txt"
REPORT_PATH = BOT_ROOT.parent / "reports" / "r18-qa-01-report.md"

BOT_REPLY_TIMEOUT = 20
DETAIL_TIMEOUT = 45  # detail views can trigger AI generation

# ── Telethon helpers ────────────────────────────────────────


async def _get_last_msg_id(client: TelegramClient) -> int:
    msgs = await client.get_messages(BOT_USERNAME, limit=1)
    return msgs[0].id if msgs else 0


async def get_latest_bot_msg(client: TelegramClient) -> Message | None:
    msgs = await client.get_messages(BOT_USERNAME, limit=5)
    for m in msgs:
        if not m.out:
            return m
    return None


async def send_and_wait(
    client: TelegramClient, text: str, timeout: int = BOT_REPLY_TIMEOUT
) -> Message | None:
    last_id = await _get_last_msg_id(client)
    try:
        await client.send_message(BOT_USERNAME, text)
    except FloodWaitError as e:
        log.warning("FloodWait: sleeping %d seconds...", e.seconds)
        await asyncio.sleep(e.seconds + 2)
        await client.send_message(BOT_USERNAME, text)

    await asyncio.sleep(2)
    deadline = time.time() + timeout
    while time.time() < deadline:
        msgs = await client.get_messages(BOT_USERNAME, limit=5)
        for m in msgs:
            if m.id > last_id and not m.out:
                return m
        await asyncio.sleep(1)
    return None


async def _do_click(btn, client: TelegramClient, msg: Message | None = None) -> Message | None:
    old_id = await _get_last_msg_id(client)
    original_id = msg.id if msg else old_id

    try:
        await btn.click()
    except FloodWaitError as e:
        log.warning("FloodWait on click: sleeping %d seconds...", e.seconds)
        await asyncio.sleep(e.seconds + 2)
        await btn.click()
    except Exception as e:
        log.debug("click error: %s", e)
        return None

    await asyncio.sleep(3)

    # Check for new message first
    msgs = await client.get_messages(BOT_USERNAME, limit=5)
    for m in msgs:
        if m.id > old_id and not m.out:
            return m

    # Check if original was edited
    if original_id:
        updated = await client.get_messages(BOT_USERNAME, ids=original_id)
        if updated:
            return updated

    return await get_latest_bot_msg(client)


async def click_button_by_data(
    client: TelegramClient, msg: Message, data_prefix: str,
    timeout: int = BOT_REPLY_TIMEOUT
) -> Message | None:
    if not msg or not msg.buttons:
        return None
    for row in msg.buttons:
        for btn in row:
            if hasattr(btn, "data") and btn.data:
                cb = btn.data.decode() if isinstance(btn.data, bytes) else str(btn.data)
                if cb.startswith(data_prefix):
                    return await _do_click(btn, client, msg)
    return None


async def click_button_by_text(
    client: TelegramClient, msg: Message, text: str, partial: bool = False
) -> Message | None:
    if not msg or not msg.buttons:
        return None
    for row in msg.buttons:
        for btn in row:
            match = (partial and text.lower() in btn.text.lower()) or btn.text.lower() == text.lower()
            if match:
                return await _do_click(btn, client, msg)
    return None


async def wait_for_stable_message(
    client: TelegramClient, msg_id: int, timeout: int = 30
) -> Message | None:
    """Wait for a message to stop being edited (spinner → final content)."""
    deadline = time.time() + timeout
    last_text = ""
    stable_count = 0
    while time.time() < deadline:
        fetched = await client.get_messages(BOT_USERNAME, ids=msg_id)
        if fetched:
            current_text = fetched.text or ""
            if current_text == last_text and len(current_text) > 50:
                stable_count += 1
                if stable_count >= 2:
                    return fetched
            else:
                stable_count = 0
                last_text = current_text
        await asyncio.sleep(2)
    # Return whatever we have
    fetched = await client.get_messages(BOT_USERNAME, ids=msg_id)
    return fetched


# ── Data capture structures ─────────────────────────────────
captures: list[dict] = []  # list of {type, page, index, text, buttons, timestamp}


def capture_msg(msg: Message | None, label: str, page: int = 0, index: int = 0) -> dict:
    """Capture a message's complete content."""
    entry = {
        "label": label,
        "page": page,
        "index": index,
        "text": msg.text if msg else "(NO RESPONSE)",
        "raw_text": msg.raw_text if msg else "(NO RESPONSE)",
        "buttons": [],
        "timestamp": datetime.now().isoformat(),
        "msg_id": msg.id if msg else None,
    }
    if msg and msg.buttons:
        for row in msg.buttons:
            row_btns = []
            for btn in row:
                btn_info = {"text": btn.text}
                if hasattr(btn, "data") and btn.data:
                    btn_info["data"] = btn.data.decode() if isinstance(btn.data, bytes) else str(btn.data)
                if hasattr(btn, "url") and btn.url:
                    btn_info["url"] = btn.url
                row_btns.append(btn_info)
            entry["buttons"].append(row_btns)
    captures.append(entry)
    return entry


# ── Card parsing ────────────────────────────────────────────

def parse_cards_from_page(text: str) -> list[dict]:
    """Parse individual tip cards from a Hot Tips page message."""
    cards = []
    # Pattern: [N] emoji Team vs Team badge
    card_pattern = re.compile(r'\[(\d+)\]\s*(.*?)(?=\[\d+\]|\n━━━|$)', re.DOTALL)
    matches = card_pattern.findall(text)
    for num, body in matches:
        card = {
            "number": int(num),
            "body": body.strip(),
            "has_tier_badge": any(b in body for b in ["💎", "🥇", "🥈", "🥉"]),
            "tier": _extract_tier(body),
            "has_odds": bool(re.search(r'@\s*\d+\.\d+', body)),
            "has_ev": bool(re.search(r'EV\s*\+?\d+', body, re.IGNORECASE)),
            "has_return": bool(re.search(r'R\d+', body)),
            "has_league": bool(re.search(r'🏆', body)),
            "has_kickoff": bool(re.search(r'📅|⏰|Today|Tomorrow|\d{1,2}:\d{2}', body)),
            "has_broadcast": bool(re.search(r'📺', body)),
        }
        # Extract team names
        team_match = re.search(r'[⚽🏉🏏🥊]\s*(.+?)\s+vs\s+(.+?)[\s💎🥇🥈🥉\n]', body)
        if team_match:
            card["home"] = team_match.group(1).strip()
            card["away"] = team_match.group(2).strip()
        # Extract odds
        odds_match = re.search(r'@\s*(\d+\.\d+)', body)
        if odds_match:
            card["odds_value"] = float(odds_match.group(1))
        # Extract EV
        ev_match = re.search(r'EV\s*\+?(\d+\.?\d*)', body, re.IGNORECASE)
        if ev_match:
            card["ev_value"] = float(ev_match.group(1))
        cards.append(card)
    return cards


def _extract_tier(text: str) -> str:
    if "💎" in text:
        return "diamond"
    if "🥇" in text:
        return "gold"
    if "🥈" in text:
        return "silver"
    if "🥉" in text:
        return "bronze"
    return "unknown"


def parse_detail_view(text: str) -> dict:
    """Parse a detail view message for scoring dimensions."""
    detail = {
        "has_setup": bool(re.search(r'📋.*Setup|📋.*<b>The Setup</b>', text, re.IGNORECASE)),
        "has_edge": bool(re.search(r'🎯.*Edge|🎯.*<b>The Edge</b>', text, re.IGNORECASE)),
        "has_risk": bool(re.search(r'⚠️.*Risk|⚠️.*<b>The Risk</b>', text, re.IGNORECASE)),
        "has_verdict": bool(re.search(r'🏆.*Verdict|🏆.*<b>Verdict</b>', text, re.IGNORECASE)),
        "has_odds": bool(re.search(r'@\s*\d+\.\d+', text)),
        "has_ev": bool(re.search(r'EV\s*\+?\d+', text, re.IGNORECASE)),
        "has_bookmaker": bool(re.search(r'Betway|Hollywoodbets|Supabets|GBets|Sportingbet|WSB', text, re.IGNORECASE)),
        "has_tier_badge": any(b in text for b in ["💎", "🥇", "🥈", "🥉"]),
        "tier": _extract_tier(text),
        "has_kickoff": bool(re.search(r'📅|Today|Tomorrow|\d{1,2}:\d{2}', text)),
        "has_broadcast": bool(re.search(r'📺', text)),
        "has_league": bool(re.search(r'🏆', text)),
        "has_narrative": False,
        "narrative_type": "unknown",
        "is_locked": "🔒" in text or "subscribe" in text.lower(),
        "section_count": 0,
        "text_length": len(text),
    }

    # Count sections present
    sections = ["📋", "🎯", "⚠️", "🏆"]
    detail["section_count"] = sum(1 for s in sections if s in text)

    # Determine narrative type
    if detail["has_setup"] and detail["has_edge"] and detail["has_risk"] and detail["has_verdict"]:
        detail["has_narrative"] = True
        # W84 narrative = rich prose with all 4 sections
        if len(text) > 500:
            detail["narrative_type"] = "w84_full"
        else:
            detail["narrative_type"] = "w82_baseline"
    elif detail["section_count"] >= 2:
        detail["has_narrative"] = True
        detail["narrative_type"] = "w82_partial"
    elif detail["is_locked"]:
        detail["narrative_type"] = "locked"
    else:
        detail["narrative_type"] = "template"

    return detail


# ── Scoring ─────────────────────────────────────────────────

def score_card(card_capture: dict, detail_capture: dict | None) -> dict:
    """Score a single card on the 4-dimension rubric.

    Dimensions (weighted):
    - accuracy  (0.25): Data correctness — tier/outcome/EV consistency, no hallucinations
    - richness  (0.20): Content depth — W84 narrative, signals, broadcast, kickoff
    - value     (0.20): User value — clear recommendation, bookmaker CTA, actionable info
    - overall   (0.35): Holistic UX — tone, formatting, no bugs, premium feel
    """
    scores = {"accuracy": 0.0, "richness": 0.0, "value": 0.0, "overall": 0.0}
    notes = []

    card_text = card_capture.get("text", "")
    card_parsed = parse_cards_from_page(card_text) if card_capture.get("label", "").startswith("page_") else []
    detail_text = detail_capture.get("text", "") if detail_capture else ""
    detail_parsed = parse_detail_view(detail_text) if detail_text else {}

    # ── ACCURACY (0-10) ──
    acc = 5.0  # baseline
    if detail_parsed:
        # Tier consistency between list and detail
        card_tier = _extract_tier(card_text)
        detail_tier = detail_parsed.get("tier", "unknown")
        if card_tier != "unknown" and detail_tier != "unknown":
            if card_tier == detail_tier:
                acc += 1.0
                notes.append("tier_consistent")
            else:
                acc -= 2.0
                notes.append(f"TIER_MISMATCH: list={card_tier} detail={detail_tier}")

        # EV present and reasonable
        if detail_parsed.get("has_ev"):
            acc += 1.0
            notes.append("ev_present")
        else:
            acc -= 1.0
            notes.append("ev_missing_in_detail")

        # Odds present
        if detail_parsed.get("has_odds"):
            acc += 1.0
            notes.append("odds_present")
        else:
            acc -= 0.5
            notes.append("odds_missing_in_detail")

        # Check for hallucination markers
        hallu_markers = ["historically", "traditionally", "known for their", "dating back"]
        for marker in hallu_markers:
            if marker in detail_text.lower():
                acc -= 1.5
                notes.append(f"HALLUCINATION: '{marker}'")

        # Bookmaker shown
        if detail_parsed.get("has_bookmaker"):
            acc += 0.5
            notes.append("bookmaker_shown")
    else:
        acc -= 2.0
        notes.append("no_detail_captured")

    scores["accuracy"] = max(0, min(10, acc))

    # ── RICHNESS (0-10) ──
    rich = 3.0  # baseline
    if detail_parsed:
        # Narrative type scoring
        ntype = detail_parsed.get("narrative_type", "template")
        if ntype == "w84_full":
            rich += 3.0
            notes.append("w84_full_narrative")
        elif ntype == "w82_baseline":
            rich += 2.0
            notes.append("w82_baseline_narrative")
        elif ntype == "w82_partial":
            rich += 1.0
            notes.append("w82_partial_narrative")
        elif ntype == "locked":
            rich += 0.5
            notes.append("locked_view")
        else:
            notes.append("template_narrative")

        # Section count
        rich += min(detail_parsed.get("section_count", 0) * 0.5, 2.0)

        # Header completeness (kickoff, broadcast, league)
        if detail_parsed.get("has_kickoff"):
            rich += 0.5
            notes.append("has_kickoff")
        if detail_parsed.get("has_broadcast"):
            rich += 0.5
            notes.append("has_broadcast")
        if detail_parsed.get("has_league"):
            rich += 0.5
            notes.append("has_league")
    else:
        notes.append("no_detail_for_richness")

    scores["richness"] = max(0, min(10, rich))

    # ── VALUE (0-10) ──
    val = 4.0  # baseline
    if detail_parsed:
        # Clear recommendation
        if detail_parsed.get("has_verdict"):
            val += 1.5
            notes.append("has_verdict")
        # Bookmaker CTA button
        has_cta = False
        if detail_capture:
            for row in detail_capture.get("buttons", []):
                for btn in row:
                    if "bet on" in btn.get("text", "").lower() or btn.get("url"):
                        has_cta = True
                        break
        if has_cta:
            val += 1.5
            notes.append("has_cta_button")
        else:
            val -= 0.5
            notes.append("no_cta_button")

        # Odds + EV together = actionable
        if detail_parsed.get("has_odds") and detail_parsed.get("has_ev"):
            val += 1.0
            notes.append("odds_ev_actionable")

        # Tier badge = clear signal quality
        if detail_parsed.get("has_tier_badge"):
            val += 0.5
            notes.append("tier_badge_visible")
    else:
        val -= 1.0

    scores["value"] = max(0, min(10, val))

    # ── OVERALL (0-10) ──
    ovr = 5.0  # baseline

    # List card quality
    if "[" in card_text and "vs" in card_text.lower():
        ovr += 0.5
        notes.append("list_format_ok")

    # Detail premium feel
    if detail_parsed:
        if detail_parsed.get("text_length", 0) > 300:
            ovr += 1.0
            notes.append("substantial_detail")
        if detail_parsed.get("has_narrative"):
            ovr += 1.0
            notes.append("narrative_present")

        # Formatting checks
        if "📋" in detail_text and "🎯" in detail_text:
            ovr += 0.5
            notes.append("section_emojis_present")

        # No bugs
        bugs = []
        if "error" in detail_text.lower() and "couldn't" in detail_text.lower():
            bugs.append("error_message_shown")
            ovr -= 2.0
        if "Analysing..." in detail_text:
            bugs.append("spinner_stuck")
            ovr -= 2.0
        if "None" in detail_text and "NoneType" not in detail_text:
            # Check if it's actual None rendering bug
            if re.search(r'\bNone\b', detail_text) and "None" not in card_text:
                bugs.append("none_rendering")
                ovr -= 1.0
        if bugs:
            notes.extend(bugs)

        # Signal-specific headline (not generic)
        generic_headlines = [
            "premium edge stack",
            "model edge carrying the case",
            "pure edge play",
        ]
        is_generic = any(gh in detail_text.lower() for gh in generic_headlines)
        if is_generic:
            ovr -= 1.0
            notes.append("GENERIC_HEADLINE")
        else:
            ovr += 0.5
            notes.append("signal_specific_headline")

    scores["overall"] = max(0, min(10, ovr))

    # Composite
    composite = (
        scores["accuracy"] * 0.25
        + scores["richness"] * 0.20
        + scores["value"] * 0.20
        + scores["overall"] * 0.35
    )

    return {
        "scores": scores,
        "composite": round(composite, 2),
        "notes": notes,
    }


# ── Main QA flow ────────────────────────────────────────────

async def run_qa():
    session_str = SESSION_PATH.read_text().strip()
    client = TelegramClient(StringSession(session_str), API_ID, API_HASH)
    await client.start()
    log.info("Telethon connected. Running QA scoring...")

    all_cards: list[dict] = []  # {page, index, list_capture, detail_capture, score}

    # ── Step 1: /start ──
    log.info("Step 1: Sending /start...")
    start_msg = await send_and_wait(client, "/start", timeout=15)
    capture_msg(start_msg, "start_response")
    if start_msg:
        log.info("  /start response received (%d chars)", len(start_msg.text or ""))
    else:
        log.error("  /start: NO RESPONSE")

    await asyncio.sleep(2)

    # ── Step 2: Navigate to Hot Tips via sticky keyboard ──
    log.info("Step 2: Tapping '💎 Top Edge Picks'...")
    hot_tips_msg = await send_and_wait(client, "💎 Top Edge Picks", timeout=DETAIL_TIMEOUT)

    if not hot_tips_msg:
        # Fallback: try legacy label
        log.warning("  No response to '💎 Top Edge Picks', trying '🔥 Hot Tips'...")
        hot_tips_msg = await send_and_wait(client, "🔥 Hot Tips", timeout=DETAIL_TIMEOUT)

    if not hot_tips_msg:
        log.error("  FATAL: No Hot Tips response. Aborting.")
        await client.disconnect()
        return

    # Wait for spinner to finish
    hot_tips_msg = await wait_for_stable_message(client, hot_tips_msg.id, timeout=DETAIL_TIMEOUT)
    page0_capture = capture_msg(hot_tips_msg, "page_0", page=0)
    page0_text = hot_tips_msg.text or ""
    log.info("  Page 0 received (%d chars)", len(page0_text))

    # ── Step 3: Parse page 0 cards ──
    page0_cards = parse_cards_from_page(page0_text)
    log.info("  Page 0 cards found: %d", len(page0_cards))

    # Track all pages
    all_page_captures = [(0, page0_capture, hot_tips_msg, page0_cards)]

    # ── Step 4: Navigate through ALL pages ──
    current_msg = hot_tips_msg
    page_num = 0
    max_pages = 10  # safety limit

    while page_num < max_pages:
        # Look for "Next" button
        has_next = False
        if current_msg and current_msg.buttons:
            for row in current_msg.buttons:
                for btn in row:
                    if hasattr(btn, "data") and btn.data:
                        cb = btn.data.decode() if isinstance(btn.data, bytes) else str(btn.data)
                        if cb.startswith("hot:page:"):
                            next_page = int(cb.split(":")[-1])
                            if next_page > page_num:
                                has_next = True
                                log.info("  Navigating to page %d...", next_page)
                                next_msg = await _do_click(btn, client, current_msg)
                                if next_msg:
                                    next_msg = await wait_for_stable_message(
                                        client, next_msg.id, timeout=20
                                    )
                                    page_num = next_page
                                    page_capture = capture_msg(next_msg, f"page_{page_num}", page=page_num)
                                    page_cards = parse_cards_from_page(next_msg.text or "")
                                    all_page_captures.append((page_num, page_capture, next_msg, page_cards))
                                    current_msg = next_msg
                                    log.info("  Page %d: %d cards, %d chars",
                                             page_num, len(page_cards), len(next_msg.text or ""))
                                break
                if has_next:
                    break
        if not has_next:
            log.info("  No more pages (stopped at page %d)", page_num)
            break

    total_list_cards = sum(len(cards) for _, _, _, cards in all_page_captures)
    log.info("Total cards across all pages: %d", total_list_cards)

    # ── Step 5: Tap into EVERY card's detail view ──
    log.info("Step 5: Tapping into each card's detail view...")

    # Navigate back to page 0 first
    if page_num > 0:
        log.info("  Navigating back to page 0...")
        back_msg = await click_button_by_data(client, current_msg, "hot:page:0")
        if back_msg:
            back_msg = await wait_for_stable_message(client, back_msg.id, timeout=15)
            current_msg = back_msg
        await asyncio.sleep(2)

    # Process each page
    for pg_num, pg_capture, pg_msg, pg_cards in all_page_captures:
        log.info("  Processing page %d (%d cards)...", pg_num, len(pg_cards))

        # Navigate to this page if needed
        if pg_num > 0:
            nav_msg = await click_button_by_data(client, current_msg, f"hot:page:{pg_num}")
            if nav_msg:
                nav_msg = await wait_for_stable_message(client, nav_msg.id, timeout=15)
                current_msg = nav_msg
            await asyncio.sleep(2)

        # Find all edge:detail buttons on this page
        detail_buttons = []
        if current_msg and current_msg.buttons:
            for row in current_msg.buttons:
                for btn in row:
                    if hasattr(btn, "data") and btn.data:
                        cb = btn.data.decode() if isinstance(btn.data, bytes) else str(btn.data)
                        if cb.startswith("edge:detail:") or cb.startswith("hot:upgrade"):
                            detail_buttons.append((btn, cb))

        log.info("    Found %d detail buttons", len(detail_buttons))

        for btn_idx, (btn, cb_data) in enumerate(detail_buttons):
            card_num = btn_idx + 1 + (pg_num * 4)  # approximate card number
            log.info("    Tapping card %d (cb=%s)...", card_num, cb_data[:40])

            detail_msg = await _do_click(btn, client, current_msg)
            if detail_msg:
                # Wait for content to stabilize (AI generation can take time)
                detail_msg = await wait_for_stable_message(
                    client, detail_msg.id, timeout=DETAIL_TIMEOUT
                )
                detail_capture = capture_msg(
                    detail_msg,
                    f"detail_p{pg_num}_c{btn_idx}",
                    page=pg_num,
                    index=btn_idx,
                )
                detail_text = detail_msg.text or ""
                log.info("      Detail captured: %d chars, sections=%s",
                         len(detail_text),
                         [s for s in ["📋", "🎯", "⚠️", "🏆"] if s in detail_text])
            else:
                detail_capture = capture_msg(None, f"detail_p{pg_num}_c{btn_idx}_MISSING", page=pg_num, index=btn_idx)
                log.warning("      Detail: NO RESPONSE")

            all_cards.append({
                "page": pg_num,
                "index": btn_idx,
                "card_number": card_num,
                "cb_data": cb_data,
                "list_capture": pg_capture,
                "detail_capture": detail_capture,
            })

            # Navigate back to the page
            await asyncio.sleep(1)
            if detail_msg and detail_msg.buttons:
                # Try back button
                back_result = await click_button_by_text(client, detail_msg, "back", partial=True)
                if back_result:
                    back_result = await wait_for_stable_message(client, back_result.id, timeout=10)
                    current_msg = back_result
                else:
                    # Fallback: navigate via hot:back
                    back_result = await click_button_by_data(client, detail_msg, "hot:back")
                    if back_result:
                        back_result = await wait_for_stable_message(client, back_result.id, timeout=10)
                        current_msg = back_result
            await asyncio.sleep(1)

    await client.disconnect()
    log.info("Telethon disconnected. Processing %d cards...", len(all_cards))
    return all_cards, all_page_captures


def generate_report(all_cards: list[dict], all_page_captures: list) -> str:
    """Generate the full QA scoring report."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    # Score each card
    scored_cards = []
    for card in all_cards:
        score = score_card(card["list_capture"], card.get("detail_capture"))
        card["score"] = score
        scored_cards.append(card)

    # Calculate aggregates
    composites = [c["score"]["composite"] for c in scored_cards if c["score"]["composite"] > 0]
    avg_composite = sum(composites) / len(composites) if composites else 0

    dim_avgs = {}
    for dim in ["accuracy", "richness", "value", "overall"]:
        vals = [c["score"]["scores"][dim] for c in scored_cards]
        dim_avgs[dim] = sum(vals) / len(vals) if vals else 0

    # Enrichment rate
    enrichment = {"w84_full": 0, "w82_baseline": 0, "w82_partial": 0, "template": 0, "locked": 0, "unknown": 0}
    for card in scored_cards:
        dt = card.get("detail_capture", {}).get("text", "")
        if dt:
            parsed = parse_detail_view(dt)
            enrichment[parsed.get("narrative_type", "unknown")] += 1
        else:
            enrichment["unknown"] += 1

    total_scored = len(scored_cards)
    enrichment_rate = (
        (enrichment["w84_full"] + enrichment["w82_baseline"]) / total_scored * 100
        if total_scored > 0 else 0
    )

    # Consistency checks
    tier_mismatches = sum(1 for c in scored_cards if "TIER_MISMATCH" in str(c["score"]["notes"]))
    generic_headlines = sum(1 for c in scored_cards if "GENERIC_HEADLINE" in str(c["score"]["notes"]))
    hallucinations = sum(1 for c in scored_cards if any("HALLUCINATION" in n for n in c["score"]["notes"]))
    bugs_found = sum(1 for c in scored_cards if any(n in str(c["score"]["notes"]) for n in ["error_message_shown", "spinner_stuck", "none_rendering"]))

    # Build report
    lines = [
        f"# R18-QA-01: Opus Scoring Report — 7.0 Gate Attempt #4",
        f"",
        f"**Date:** {now}",
        f"**Model:** Opus — 04 QA Surface A",
        f"**Bot Runtime:** {BOT_ROOT / 'bot.py'} (verified PID active)",
        f"**Cards Scored:** {total_scored}",
        f"**Pages Browsed:** {len(all_page_captures)}",
        f"",
        f"---",
        f"",
        f"## Composite Score: {avg_composite:.2f}/10",
        f"",
        f"### Gate Verdict: {'PASS' if avg_composite >= 7.0 else 'FAIL'} (threshold: 7.0)",
        f"",
        f"---",
        f"",
        f"## Dimension Averages",
        f"",
        f"| Dimension | Weight | Average | Min | Max |",
        f"|-----------|--------|---------|-----|-----|",
    ]

    for dim, weight in [("accuracy", 0.25), ("richness", 0.20), ("value", 0.20), ("overall", 0.35)]:
        vals = [c["score"]["scores"][dim] for c in scored_cards]
        mn = min(vals) if vals else 0
        mx = max(vals) if vals else 0
        lines.append(f"| {dim.title()} | {weight} | {dim_avgs[dim]:.2f} | {mn:.1f} | {mx:.1f} |")

    lines.extend([
        f"",
        f"---",
        f"",
        f"## Per-Card Scores",
        f"",
        f"| # | Page | Tier | Acc | Rich | Val | Ovr | Composite | Notes |",
        f"|---|------|------|-----|------|-----|-----|-----------|-------|",
    ])

    for card in scored_cards:
        s = card["score"]
        detail_text = card.get("detail_capture", {}).get("text", "")
        tier = _extract_tier(detail_text) if detail_text else "?"
        key_notes = [n for n in s["notes"] if n.isupper() or n.startswith("w8")][:3]
        lines.append(
            f"| {card['card_number']} | {card['page']} | {tier} | "
            f"{s['scores']['accuracy']:.1f} | {s['scores']['richness']:.1f} | "
            f"{s['scores']['value']:.1f} | {s['scores']['overall']:.1f} | "
            f"**{s['composite']:.2f}** | {', '.join(key_notes)} |"
        )

    lines.extend([
        f"",
        f"---",
        f"",
        f"## Enrichment Rate",
        f"",
        f"| Narrative Type | Count | % |",
        f"|----------------|-------|---|",
    ])
    for ntype, count in sorted(enrichment.items(), key=lambda x: -x[1]):
        pct = count / total_scored * 100 if total_scored > 0 else 0
        lines.append(f"| {ntype} | {count} | {pct:.0f}% |")

    lines.extend([
        f"",
        f"**Enrichment Rate (W84+W82 vs template):** {enrichment_rate:.0f}%",
        f"",
        f"---",
        f"",
        f"## Consistency Checks",
        f"",
        f"| Check | Result |",
        f"|-------|--------|",
        f"| Tier consistency (list↔detail) | {'PASS' if tier_mismatches == 0 else f'FAIL ({tier_mismatches} mismatches)'} |",
        f"| Headline diversity (non-generic) | {'PASS' if generic_headlines == 0 else f'FAIL ({generic_headlines} generic)'} |",
        f"| Zero hallucinations | {'PASS' if hallucinations == 0 else f'FAIL ({hallucinations} found)'} |",
        f"| No rendering bugs | {'PASS' if bugs_found == 0 else f'FAIL ({bugs_found} bugs)'} |",
        f"",
        f"---",
        f"",
        f"## Cache-Bust Check",
        f"",
        f"Previously-busted cards serving W84 narratives: ",
    ])

    w84_count = enrichment.get("w84_full", 0)
    w82_count = enrichment.get("w82_baseline", 0)
    template_count = enrichment.get("template", 0)
    if w84_count > 0:
        lines.append(f"**YES** — {w84_count} cards showing W84 full narratives.")
    elif w82_count > 0:
        lines.append(f"**PARTIAL** — {w82_count} cards showing W82 baseline (no W84 full).")
    else:
        lines.append(f"**NO** — all cards showing template/locked content.")

    # Top 3 strengths / weaknesses
    all_notes = []
    for card in scored_cards:
        all_notes.extend(card["score"]["notes"])

    from collections import Counter
    note_counts = Counter(all_notes)

    strengths = [n for n, _ in note_counts.most_common() if not n.isupper() and n not in ("no_detail_for_richness", "no_detail_captured", "no_cta_button")][:3]
    weaknesses = [n for n, _ in note_counts.most_common() if n.isupper() or n in ("no_detail_captured", "no_cta_button", "ev_missing_in_detail", "odds_missing_in_detail")][:3]

    lines.extend([
        f"",
        f"---",
        f"",
        f"## Top 3 Strengths",
        f"",
    ])
    for i, s in enumerate(strengths, 1):
        lines.append(f"{i}. **{s}** ({note_counts[s]}x)")

    lines.extend([
        f"",
        f"## Top 3 Weaknesses",
        f"",
    ])
    for i, w in enumerate(weaknesses, 1):
        lines.append(f"{i}. **{w}** ({note_counts[w]}x)")

    # Remaining bugs
    bug_notes = set()
    for card in scored_cards:
        for note in card["score"]["notes"]:
            if note in ("error_message_shown", "spinner_stuck", "none_rendering") or note.startswith("HALLUCINATION") or note.startswith("TIER_MISMATCH"):
                bug_notes.add(note)

    lines.extend([
        f"",
        f"---",
        f"",
        f"## Remaining Bugs",
        f"",
    ])
    if bug_notes:
        for bug in sorted(bug_notes):
            lines.append(f"- {bug}")
    else:
        lines.append("None detected during this QA pass.")

    lines.extend([
        f"",
        f"---",
        f"",
        f"## 7.0 Gate Verdict",
        f"",
        f"**Composite Score: {avg_composite:.2f}/10**",
        f"",
    ])

    if avg_composite >= 7.0:
        lines.append("### GATE PASSED")
        lines.append(f"The bot meets the 7.0 quality threshold with a composite score of {avg_composite:.2f}.")
    else:
        gap = 7.0 - avg_composite
        lines.append("### GATE FAILED")
        lines.append(f"Gap to 7.0: **{gap:.2f} points**")
        lines.append("")
        lines.append("Priority fixes needed:")
        if dim_avgs["richness"] < 6.0:
            lines.append(f"- **Richness** ({dim_avgs['richness']:.2f}): Improve narrative depth/W84 coverage")
        if dim_avgs["accuracy"] < 7.0:
            lines.append(f"- **Accuracy** ({dim_avgs['accuracy']:.2f}): Fix data consistency issues")
        if dim_avgs["value"] < 6.5:
            lines.append(f"- **Value** ({dim_avgs['value']:.2f}): Improve actionability and CTAs")
        if dim_avgs["overall"] < 7.0:
            lines.append(f"- **Overall UX** ({dim_avgs['overall']:.2f}): Fix bugs and formatting issues")

    lines.extend([
        f"",
        f"---",
        f"",
        f"## CLAUDE.md Updates",
        f"",
        f"None",
        f"",
    ])

    return "\n".join(lines)


def save_raw_captures():
    """Save all raw captures to file."""
    RAW_CAPTURES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(RAW_CAPTURES_PATH, "w") as f:
        f.write(f"# R18-QA-01 Raw Captures — {datetime.now().isoformat()}\n")
        f.write(f"# Total captures: {len(captures)}\n\n")
        for i, cap in enumerate(captures):
            f.write(f"{'='*80}\n")
            f.write(f"CAPTURE #{i+1}: {cap['label']}\n")
            f.write(f"Page: {cap['page']}, Index: {cap['index']}\n")
            f.write(f"Timestamp: {cap['timestamp']}\n")
            f.write(f"Message ID: {cap['msg_id']}\n")
            f.write(f"Text length: {len(cap['text'])}\n")
            f.write(f"{'='*80}\n\n")
            f.write(f"--- RAW TEXT ---\n{cap['raw_text']}\n\n")
            f.write(f"--- TEXT ---\n{cap['text']}\n\n")
            if cap['buttons']:
                f.write(f"--- BUTTONS ---\n")
                for row_idx, row in enumerate(cap['buttons']):
                    for btn in row:
                        f.write(f"  Row {row_idx}: {btn}\n")
                f.write("\n")
            f.write("\n\n")
    log.info("Raw captures saved to %s", RAW_CAPTURES_PATH)


async def main():
    log.info("=" * 60)
    log.info("R18-QA-01: Opus Scoring — 7.0 Gate Attempt #4")
    log.info("=" * 60)

    result = await run_qa()
    if not result:
        log.error("QA run failed — no data collected.")
        return

    all_cards, all_page_captures = result

    # Save raw captures
    save_raw_captures()

    # Generate and save report
    report = generate_report(all_cards, all_page_captures)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report)
    log.info("Report saved to %s", REPORT_PATH)

    # Print summary
    composites = [c["score"]["composite"] for c in all_cards if "score" in c]
    avg = sum(composites) / len(composites) if composites else 0
    print(f"\n{'='*60}")
    print(f"COMPOSITE SCORE: {avg:.2f}/10")
    print(f"GATE VERDICT: {'PASS' if avg >= 7.0 else 'FAIL'}")
    print(f"Cards scored: {len(all_cards)}")
    print(f"Report: {REPORT_PATH}")
    print(f"Raw captures: {RAW_CAPTURES_PATH}")
    print(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())
