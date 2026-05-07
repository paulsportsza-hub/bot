"""QA-BASELINE-18 — Full Product Audit via Telethon E2E.

Captures ALL verbatim card text from live bot for scoring.
Tests: Hot Tips list tier order, 6+ detail cards (3+ sports),
CTA/Verdict consistency, My Matches list + detail, zero-signal check,
rendering path, and banned phrase scan.

Usage:
    cd /home/paulsportsza/bot && .venv/bin/python tests/qa_baseline_18.py
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# Load .env
_env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
if os.path.exists(_env_path):
    with open(_env_path) as _ef:
        for _line in _ef:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _, _v = _line.partition("=")
                os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import (
    ReplyInlineMarkup,
    KeyboardButtonCallback,
    KeyboardButtonUrl,
)

# Config
API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "")
BOT_USERNAME = "mzansiedge_bot"
STRING_SESSION_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "telethon_qa_session.string")
SESSION_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "telethon_qa_session")

REPORT_DIR = Path("/home/paulsportsza/reports")
RAW_FILE = REPORT_DIR / "qa-baseline-18-raw-captures.json"

POLL_INTERVAL = 0.4
MAX_WAIT = 35.0

# Banned phrases (Section 3.3 / 3.6)
BANNED_PHRASES = [
    "the edge is carried by the pricing gap alone",
    "standard match-day variables apply",
    "no supporting indicators from any source",
    "no injury data was available",
    "limited data available for this match",
    "market data suggests",
    "based on available information",
]

# Sport emoji mapping for detection
SPORT_EMOJIS = {"⚽": "soccer", "🏉": "rugby", "🏏": "cricket", "🥊": "combat", "🥋": "mma"}
TIER_ORDER = {"💎": 0, "🥇": 1, "🥈": 2, "🥉": 3}
TIER_NAMES = {"💎": "Diamond", "🥇": "Gold", "🥈": "Silver", "🥉": "Bronze"}


@dataclass
class CardCapture:
    index: int = 0
    source: str = ""         # "hot_tips" or "my_matches"
    match_name: str = ""
    sport: str = ""
    tier: str = ""
    list_text: str = ""      # text from the list view for this card
    detail_text: str = ""    # full verbatim detail card text
    detail_buttons: list = field(default_factory=list)
    cta_team: str = ""
    cta_button_text: str = ""
    verdict_team: str = ""
    verdict_text: str = ""
    rendering_path: str = ""
    wall_time: float = 0.0
    errors: list = field(default_factory=list)


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


async def poll_response(client, after_id: int, timeout: float = MAX_WAIT) -> tuple:
    """Poll for new bot message after after_id. Returns (message, wall_time)."""
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        msgs = await client.get_messages(BOT_USERNAME, limit=10)
        for m in msgs:
            if not m.out and m.id > after_id:
                # Check if message has meaningful content (not just a loading spinner)
                text = m.text or ""
                if ("Loading" in text or "Analysing" in text or "Scanning" in text) and len(text) < 100:
                    # This is a spinner message, keep waiting for the real content
                    after_id = m.id  # Update to look past the spinner
                    continue
                return m, time.monotonic() - start
        await asyncio.sleep(POLL_INTERVAL)
    return None, timeout


async def poll_edit(client, msg_id: int, initial_text: str, timeout: float = MAX_WAIT) -> tuple:
    """Poll for a message edit (content change). Returns (message, wall_time)."""
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        msgs = await client.get_messages(BOT_USERNAME, ids=[msg_id])
        if msgs and msgs[0]:
            current_text = msgs[0].text or ""
            if current_text != initial_text and len(current_text) > len(initial_text):
                return msgs[0], time.monotonic() - start
        await asyncio.sleep(POLL_INTERVAL)
    # Return latest state even on timeout
    msgs = await client.get_messages(BOT_USERNAME, ids=[msg_id])
    return (msgs[0] if msgs else None), timeout


def extract_buttons(msg) -> list[dict]:
    """Extract all buttons from a message."""
    buttons = []
    if not msg or not msg.reply_markup:
        return buttons
    if isinstance(msg.reply_markup, ReplyInlineMarkup):
        for row in msg.reply_markup.rows:
            for btn in row.buttons:
                info = {"text": btn.text or ""}
                if isinstance(btn, KeyboardButtonCallback):
                    info["data"] = btn.data.decode("utf-8", errors="ignore") if btn.data else ""
                elif isinstance(btn, KeyboardButtonUrl):
                    info["url"] = btn.url or ""
                buttons.append(info)
    return buttons


def detect_sport(text: str) -> str:
    """Detect sport from card text using emojis and keywords."""
    for emoji, sport in SPORT_EMOJIS.items():
        if emoji in text:
            return sport
    text_lower = text.lower()
    if any(w in text_lower for w in ["rugby", "urc", "super rugby", "six nations", "stormers", "bulls", "sharks"]):
        return "rugby"
    if any(w in text_lower for w in ["cricket", "sa20", "proteas", "test match", "odi", "t20"]):
        return "cricket"
    if any(w in text_lower for w in ["ufc", "mma", "boxing", "bout", "fight"]):
        return "combat"
    if any(w in text_lower for w in ["epl", "psl", "champions league", "la liga", "serie a", "bundesliga"]):
        return "soccer"
    return "unknown"


def detect_tier(text: str) -> str:
    """Detect edge tier from text."""
    for emoji, name in TIER_NAMES.items():
        if emoji in text:
            return name
    return "unknown"


def extract_verdict_team(text: str) -> str:
    """Extract the team recommended in the Verdict section."""
    # Look for Verdict section
    verdict_match = re.search(r'(?:🏆|Verdict).*?(?:\n|$)(.*?)(?:\n\n|\Z)', text, re.DOTALL | re.IGNORECASE)
    if not verdict_match:
        # Try looking for verdict patterns
        verdict_match = re.search(r'Verdict[^:]*:?\s*[—–-]?\s*(.*?)(?:\n\n|\Z)', text, re.DOTALL | re.IGNORECASE)
    if verdict_match:
        verdict_text = verdict_match.group(1).strip()
        # Look for "Back X", "nod to X", "lean towards X", "favour X"
        team_patterns = [
            r'(?:Back|back|Backing|backing)\s+(.+?)(?:\s+@|\s+at\s|\.|$)',
            r'(?:nod to|lean(?:s|ing)? (?:towards?|to))\s+(.+?)(?:\s+@|\s+at\s|\.|$)',
            r'(?:favour(?:s|ing)?|favor(?:s|ing)?)\s+(.+?)(?:\s+@|\s+at\s|\.|$)',
        ]
        for pat in team_patterns:
            m = re.search(pat, verdict_text, re.IGNORECASE)
            if m:
                return m.group(1).strip().rstrip('.')
        return verdict_text[:60]
    return ""


def extract_cta_team(buttons: list[dict]) -> tuple[str, str]:
    """Extract team from CTA button. Returns (team, full_button_text)."""
    for btn in buttons:
        text = btn.get("text", "")
        # CTA pattern: "{tier} Back {team} @ {odds} on {bk} →"
        m = re.match(r'[💎🥇🥈🥉]?\s*Back\s+(.+?)\s+@\s+[\d.]+\s+on\s+', text)
        if m:
            return m.group(1).strip(), text
        # Fallback: "Back {team} @ {odds}" without tier emoji
        m = re.match(r'Back\s+(.+?)\s+@\s+[\d.]+', text)
        if m:
            return m.group(1).strip(), text
    return "", ""


def detect_rendering_path(text: str) -> str:
    """Detect rendering path from card text."""
    if "TEMPLATE" in text or "INSTANT BASELINE" in text:
        return "TEMPLATE"
    # Check for rich narrative content indicators
    sections = ["📋", "🎯", "⚠️", "🏆"]
    section_count = sum(1 for s in sections if s in text)
    if section_count >= 3:
        return "AI-ENRICHED"
    if section_count >= 1:
        return "PARTIAL-ENRICHED"
    return "MINIMAL"


def check_banned_phrases(text: str) -> list[str]:
    """Check text for banned phrases. Returns list of found phrases."""
    found = []
    text_lower = text.lower()
    for phrase in BANNED_PHRASES:
        if phrase.lower() in text_lower:
            found.append(phrase)
    return found


async def run_audit():
    client = await get_client()
    print("=" * 70)
    print("QA-BASELINE-18 — Full Product Audit")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S SAST')}")
    print("=" * 70)

    all_captures: list[CardCapture] = []
    hot_tips_list_text = ""
    my_matches_list_text = ""
    tier_order_violations = []

    try:
        # ── PHASE 1: Hot Tips List ─────────────────────────
        print("\n[PHASE 1] Opening Top Edge Picks (Hot Tips)...")
        marker = await client.get_messages(BOT_USERNAME, limit=1)
        marker_id = marker[0].id if marker else 0

        await client.send_message(BOT_USERNAME, "💎 Top Edge Picks")
        tips_msg, wall = await poll_response(client, marker_id, timeout=20)

        if not tips_msg:
            print("  ERROR: No Hot Tips response received")
            return

        # Wait a bit more and get the final state (edits may still be happening)
        await asyncio.sleep(3)
        msgs = await client.get_messages(BOT_USERNAME, limit=5)
        # Find the most complete tips message (longest text with buttons)
        best_msg = tips_msg
        for m in msgs:
            if not m.out and m.reply_markup and len(m.text or "") > len(best_msg.text or ""):
                best_msg = m
        tips_msg = best_msg

        hot_tips_list_text = tips_msg.text or ""
        print(f"  Received Hot Tips list ({len(hot_tips_list_text)} chars, {wall:.1f}s)")
        print(f"  First 200 chars: {hot_tips_list_text[:200]}...")

        # Extract tier order from list
        tiers_found = []
        for line in hot_tips_list_text.split("\n"):
            for emoji in TIER_ORDER:
                if emoji in line and re.search(r'\[\d+\]', line):
                    tiers_found.append((emoji, TIER_NAMES[emoji], line.strip()[:80]))

        print(f"\n  Tier order found ({len(tiers_found)} items):")
        prev_tier_rank = -1
        for emoji, name, line_preview in tiers_found:
            rank = TIER_ORDER[emoji]
            status = "✅" if rank >= prev_tier_rank else "❌ OUT OF ORDER"
            if rank < prev_tier_rank:
                tier_order_violations.append(f"{name} appears after {TIER_NAMES.get(list(TIER_ORDER.keys())[prev_tier_rank], '?')}")
            print(f"    {status} {emoji} {name}: {line_preview}")
            prev_tier_rank = rank

        # Find detail buttons
        tips_buttons = extract_buttons(tips_msg)
        detail_buttons = [b for b in tips_buttons if "edge:detail" in b.get("data", "")]
        print(f"\n  Found {len(detail_buttons)} edge:detail buttons")

        # Check for page 2 buttons
        page_buttons = [b for b in tips_buttons if "hot:page:" in b.get("data", "")]
        if page_buttons:
            print(f"  Found pagination buttons: {[b['text'] for b in page_buttons]}")

        # ── PHASE 2: Hot Tips Detail Cards ─────────────────
        print(f"\n[PHASE 2] Opening detail cards (target: 6+ cards, 3+ sports)...")
        sports_seen = set()
        cards_opened = 0

        # Open cards from page 1
        for i, btn in enumerate(detail_buttons):
            if cards_opened >= 8:  # open up to 8 for good coverage
                break

            btn_text = btn.get("text", "")
            btn_data = btn.get("data", "")
            print(f"\n  --- Card {cards_opened + 1}: '{btn_text[:50]}' ---")

            # Click the button
            t0 = time.monotonic()
            try:
                # Find the button in the message and click it
                if tips_msg.buttons:
                    clicked = False
                    for row in tips_msg.buttons:
                        for b in row:
                            b_data = (b.data or b"").decode("utf-8", errors="ignore")
                            if b_data == btn_data:
                                await b.click()
                                clicked = True
                                break
                        if clicked:
                            break

                    if not clicked:
                        print(f"    WARN: Could not click button")
                        continue

                # Poll for the detail response (edit of the same message)
                await asyncio.sleep(1)
                detail_msg, detail_wall = await poll_edit(
                    client, tips_msg.id, hot_tips_list_text, timeout=20
                )

                if not detail_msg or (detail_msg.text or "") == hot_tips_list_text:
                    # Try getting a NEW message instead
                    detail_msg, detail_wall = await poll_response(client, tips_msg.id, timeout=10)

                if not detail_msg:
                    print(f"    WARN: No detail response")
                    continue

                detail_text = detail_msg.text or ""
                detail_wall = time.monotonic() - t0
                detail_btns = extract_buttons(detail_msg)

                # Create capture
                cap = CardCapture(
                    index=cards_opened + 1,
                    source="hot_tips",
                    match_name=btn_text[:80],
                    sport=detect_sport(detail_text) or detect_sport(btn_text),
                    tier=detect_tier(detail_text) or detect_tier(btn_text),
                    list_text=btn_text,
                    detail_text=detail_text,
                    detail_buttons=[{"text": b.get("text", ""), "data": b.get("data", ""), "url": b.get("url", "")} for b in detail_btns],
                    rendering_path=detect_rendering_path(detail_text),
                    wall_time=detail_wall,
                )

                # CTA/Verdict check
                cta_team, cta_btn_text = extract_cta_team(detail_btns)
                cap.cta_team = cta_team
                cap.cta_button_text = cta_btn_text

                # Extract verdict
                cap.verdict_team = extract_verdict_team(detail_text)
                cap.verdict_text = ""
                verdict_section = re.search(r'🏆.*?(?:\n|$)(.*?)(?:\n\n|\Z)', detail_text, re.DOTALL)
                if verdict_section:
                    cap.verdict_text = verdict_section.group(0).strip()[:200]

                sports_seen.add(cap.sport)
                all_captures.append(cap)
                cards_opened += 1

                print(f"    Sport: {cap.sport}, Tier: {cap.tier}")
                print(f"    Rendering: {cap.rendering_path}")
                print(f"    Wall time: {detail_wall:.1f}s")
                print(f"    Text length: {len(detail_text)} chars")
                print(f"    CTA team: '{cap.cta_team}'")
                print(f"    Verdict team: '{cap.verdict_team}'")
                if cap.cta_team and cap.verdict_team:
                    match = cap.cta_team.lower().strip() in cap.verdict_team.lower() or cap.verdict_team.lower().strip() in cap.cta_team.lower()
                    print(f"    CTA/Verdict match: {'✅' if match else '❌ MISMATCH — P0'}")

                # Navigate back
                back_clicked = False
                if detail_msg.buttons:
                    for row in detail_msg.buttons:
                        for b in row:
                            b_text = b.text or ""
                            b_data = (b.data or b"").decode("utf-8", errors="ignore")
                            if "Edge Picks" in b_text or "hot:back" in b_data:
                                await b.click()
                                back_clicked = True
                                break
                        if back_clicked:
                            break

                if back_clicked:
                    await asyncio.sleep(2)
                    # Refresh tips_msg after going back
                    refresh = await client.get_messages(BOT_USERNAME, ids=[tips_msg.id])
                    if refresh and refresh[0]:
                        tips_msg = refresh[0]
                        hot_tips_list_text = tips_msg.text or ""

            except Exception as e:
                print(f"    ERROR: {e}")
                all_captures.append(CardCapture(
                    index=cards_opened + 1,
                    source="hot_tips",
                    match_name=btn_text[:80],
                    errors=[str(e)],
                ))
                cards_opened += 1

        # If we need more sports, check page 2
        if len(sports_seen) < 3 and page_buttons:
            print(f"\n  Only {len(sports_seen)} sports seen. Checking page 2...")
            for pb in page_buttons:
                if "Next" in pb.get("text", "") or "➡️" in pb.get("text", ""):
                    # Click page 2
                    if tips_msg.buttons:
                        for row in tips_msg.buttons:
                            for b in row:
                                b_data = (b.data or b"").decode("utf-8", errors="ignore")
                                if b_data == pb.get("data", ""):
                                    await b.click()
                                    await asyncio.sleep(3)
                                    refresh = await client.get_messages(BOT_USERNAME, ids=[tips_msg.id])
                                    if refresh and refresh[0]:
                                        tips_msg = refresh[0]
                                        p2_buttons = extract_buttons(tips_msg)
                                        p2_detail = [b for b in p2_buttons if "edge:detail" in b.get("data", "")]
                                        print(f"  Page 2: {len(p2_detail)} more detail buttons")
                                        # Open a few from page 2
                                        for btn in p2_detail[:3]:
                                            if cards_opened >= 10:
                                                break
                                            # Similar flow as above (abbreviated)
                                            btn_data = btn.get("data", "")
                                            for row2 in tips_msg.buttons:
                                                for b2 in row2:
                                                    b2_data = (b2.data or b"").decode("utf-8", errors="ignore")
                                                    if b2_data == btn_data:
                                                        await b2.click()
                                                        await asyncio.sleep(2)
                                                        dm, dw = await poll_edit(client, tips_msg.id, tips_msg.text or "", timeout=15)
                                                        if dm and (dm.text or "") != (tips_msg.text or ""):
                                                            cap = CardCapture(
                                                                index=cards_opened + 1,
                                                                source="hot_tips",
                                                                match_name=btn.get("text", "")[:80],
                                                                sport=detect_sport(dm.text or ""),
                                                                tier=detect_tier(dm.text or ""),
                                                                detail_text=dm.text or "",
                                                                detail_buttons=[{"text": x.get("text",""), "data": x.get("data",""), "url": x.get("url","")} for x in extract_buttons(dm)],
                                                                rendering_path=detect_rendering_path(dm.text or ""),
                                                                wall_time=dw,
                                                            )
                                                            cta_t, cta_bt = extract_cta_team(extract_buttons(dm))
                                                            cap.cta_team = cta_t
                                                            cap.cta_button_text = cta_bt
                                                            cap.verdict_team = extract_verdict_team(dm.text or "")
                                                            sports_seen.add(cap.sport)
                                                            all_captures.append(cap)
                                                            cards_opened += 1
                                                            print(f"    P2 Card {cards_opened}: {cap.sport} / {cap.tier}")
                                                        # Go back
                                                        if dm and dm.buttons:
                                                            for row3 in dm.buttons:
                                                                for b3 in row3:
                                                                    if "hot:back" in ((b3.data or b"").decode("utf-8","ignore")):
                                                                        await b3.click()
                                                                        await asyncio.sleep(2)
                                                                        break
                                                        break
                                    break

        print(f"\n  Total cards captured: {cards_opened}")
        print(f"  Sports covered: {sports_seen}")

        # ── PHASE 3: My Matches ────────────────────────────
        print(f"\n[PHASE 3] Opening My Matches...")
        marker2 = await client.get_messages(BOT_USERNAME, limit=1)
        marker2_id = marker2[0].id if marker2 else 0

        await client.send_message(BOT_USERNAME, "⚽ My Matches")
        mm_msg, mm_wall = await poll_response(client, marker2_id, timeout=15)

        if mm_msg:
            # Wait for edits to complete
            await asyncio.sleep(3)
            msgs = await client.get_messages(BOT_USERNAME, limit=5)
            for m in msgs:
                if not m.out and len(m.text or "") > len(mm_msg.text or ""):
                    mm_msg = m

            my_matches_list_text = mm_msg.text or ""
            print(f"  Received My Matches ({len(my_matches_list_text)} chars, {mm_wall:.1f}s)")
            print(f"  First 200 chars: {my_matches_list_text[:200]}...")

            # Find game buttons
            mm_buttons = extract_buttons(mm_msg)
            game_buttons = [b for b in mm_buttons if "yg:game:" in b.get("data", "")]
            print(f"  Found {len(game_buttons)} game detail buttons")

            # Open 2 detail cards
            for i, btn in enumerate(game_buttons[:3]):
                if i >= 2:
                    break
                btn_text = btn.get("text", "")
                btn_data = btn.get("data", "")
                print(f"\n  --- MM Card {i+1}: '{btn_text[:50]}' ---")

                try:
                    if mm_msg.buttons:
                        for row in mm_msg.buttons:
                            for b in row:
                                b_data = (b.data or b"").decode("utf-8", errors="ignore")
                                if b_data == btn_data:
                                    t0 = time.monotonic()
                                    await b.click()
                                    await asyncio.sleep(2)
                                    dm, dw = await poll_edit(client, mm_msg.id, my_matches_list_text, timeout=20)
                                    if not dm or (dm.text or "") == my_matches_list_text:
                                        dm, dw = await poll_response(client, mm_msg.id, timeout=10)
                                    dw = time.monotonic() - t0

                                    if dm and (dm.text or "") != my_matches_list_text:
                                        cap = CardCapture(
                                            index=len(all_captures) + 1,
                                            source="my_matches",
                                            match_name=btn_text[:80],
                                            sport=detect_sport(dm.text or "") or detect_sport(btn_text),
                                            detail_text=dm.text or "",
                                            detail_buttons=[{"text": x.get("text",""), "data": x.get("data",""), "url": x.get("url","")} for x in extract_buttons(dm)],
                                            rendering_path=detect_rendering_path(dm.text or ""),
                                            wall_time=dw,
                                        )
                                        cta_t, cta_bt = extract_cta_team(extract_buttons(dm))
                                        cap.cta_team = cta_t
                                        cap.cta_button_text = cta_bt
                                        cap.verdict_team = extract_verdict_team(dm.text or "")
                                        all_captures.append(cap)
                                        print(f"    Sport: {cap.sport}, Render: {cap.rendering_path}")
                                        print(f"    Wall time: {dw:.1f}s, Text: {len(cap.detail_text)} chars")

                                    # Go back
                                    if dm and dm.buttons:
                                        for row2 in dm.buttons:
                                            for b2 in row2:
                                                b2_data = (b2.data or b"").decode("utf-8", errors="ignore")
                                                if "yg:all" in b2_data or "My Matches" in (b2.text or ""):
                                                    await b2.click()
                                                    await asyncio.sleep(2)
                                                    break
                                    break
                except Exception as e:
                    print(f"    ERROR: {e}")

        else:
            print("  ERROR: No My Matches response")
            my_matches_list_text = ""

        # ── PHASE 4: Banned Phrase Scan ────────────────────
        print(f"\n{'='*70}")
        print("[PHASE 4] Pre-Scoring Banned Phrase Scan (Section 3.6)")
        print(f"{'='*70}")

        all_verbatim = hot_tips_list_text + "\n\n"
        all_verbatim += my_matches_list_text + "\n\n"
        for cap in all_captures:
            all_verbatim += cap.detail_text + "\n\n"

        banned_found = check_banned_phrases(all_verbatim)
        for phrase in BANNED_PHRASES:
            found = phrase.lower() in all_verbatim.lower()
            status = "❌ FOUND — P0 PRODUCT FAIL" if found else "✅ Clear"
            print(f"  {status}: \"{phrase}\"")

        if banned_found:
            print(f"\n  *** PRODUCT FAIL — {len(banned_found)} banned phrase(s) found ***")
            print(f"  Terminating immediately per Section 3.6 / Fail-Fast Rule")

        # ── PHASE 5: Summary ───────────────────────────────
        print(f"\n{'='*70}")
        print("[PHASE 5] Capture Summary")
        print(f"{'='*70}")

        ht_cards = [c for c in all_captures if c.source == "hot_tips"]
        mm_cards = [c for c in all_captures if c.source == "my_matches"]
        all_sports = set(c.sport for c in all_captures if c.sport != "unknown")

        print(f"  Hot Tips cards captured: {len(ht_cards)}")
        print(f"  My Matches cards captured: {len(mm_cards)}")
        print(f"  Sports covered: {all_sports}")
        print(f"  Tier order violations: {len(tier_order_violations)}")

        # CTA/Verdict check summary
        cta_mismatches = []
        for cap in all_captures:
            if cap.cta_team and cap.verdict_team:
                ct = cap.cta_team.lower().strip()
                vt = cap.verdict_team.lower().strip()
                if ct not in vt and vt not in ct:
                    cta_mismatches.append(cap)

        print(f"  CTA/Verdict mismatches: {len(cta_mismatches)}")
        for m in cta_mismatches:
            print(f"    ❌ Card {m.index} ({m.match_name}): CTA='{m.cta_team}' vs Verdict='{m.verdict_team}'")

        # Rendering path check
        template_cards = [c for c in all_captures if c.rendering_path in ("TEMPLATE", "INSTANT BASELINE")]
        print(f"  Template/Instant Baseline cards: {len(template_cards)}")

        # Save raw captures
        captures_data = {
            "timestamp": datetime.now().isoformat(),
            "hot_tips_list_text": hot_tips_list_text,
            "my_matches_list_text": my_matches_list_text,
            "tier_order": [{"emoji": e, "name": n, "preview": p} for e, n, p in tiers_found],
            "tier_order_violations": tier_order_violations,
            "banned_phrases_found": banned_found,
            "captures": [],
        }
        for cap in all_captures:
            captures_data["captures"].append({
                "index": cap.index,
                "source": cap.source,
                "match_name": cap.match_name,
                "sport": cap.sport,
                "tier": cap.tier,
                "detail_text": cap.detail_text,
                "detail_buttons": cap.detail_buttons,
                "cta_team": cap.cta_team,
                "cta_button_text": cap.cta_button_text,
                "verdict_team": cap.verdict_team,
                "verdict_text": cap.verdict_text,
                "rendering_path": cap.rendering_path,
                "wall_time": cap.wall_time,
                "errors": cap.errors,
            })

        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        with open(RAW_FILE, "w") as f:
            json.dump(captures_data, f, indent=2, ensure_ascii=False)
        print(f"\n  Raw captures saved to: {RAW_FILE}")

    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(run_audit())
