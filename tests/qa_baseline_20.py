"""QA-BASELINE-20 — Full Product Baseline After BUILD-P0-FIX.

Telethon E2E capture for QA Protocol v1.3 compliance.
Verifies BUILD-P0-FIX (P0-1 away CTA, P0-2 yg:game CTA),
plus prior BUILDs (TIER-ORDER, EDGE-GATE, GATE-RELAX, BAN-PHRASES).

Usage:
    cd /home/paulsportsza/bot && .venv/bin/python tests/qa_baseline_20.py
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
RAW_FILE = REPORT_DIR / "qa-baseline-20-raw-captures.json"

POLL_INTERVAL = 0.3
MAX_WAIT = 35.0

BANNED_PHRASES = [
    "the edge is carried by the pricing gap alone",
    "standard match-day variables apply",
    "no supporting indicators from any source",
    "no injury data was available",
    "limited data available for this match",
    "market data suggests",
    "based on available information",
]

SPORT_EMOJIS = {"⚽": "soccer", "🏉": "rugby", "🏏": "cricket", "🥊": "combat", "🥋": "mma"}
TIER_ORDER = {"💎": 0, "🥇": 1, "🥈": 2, "🥉": 3}
TIER_NAMES = {"💎": "Diamond", "🥇": "Gold", "🥈": "Silver", "🥉": "Bronze"}


@dataclass
class CardCapture:
    index: int = 0
    source: str = ""
    match_name: str = ""
    sport: str = ""
    league: str = ""
    tier: str = ""
    list_text: str = ""
    detail_text: str = ""
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


async def send_and_wait_stable(client, text: str, timeout: float = 20.0, settle: float = 3.0):
    """Send a message and wait for the bot's FINAL response (after edits settle).

    Returns (final_message, wall_time_seconds).
    Strategy: find the first new non-outgoing message, then poll for edits until stable.
    """
    # Get marker
    before = await client.get_messages(BOT_USERNAME, limit=1)
    marker_id = before[0].id if before else 0

    t0 = time.monotonic()
    await client.send_message(BOT_USERNAME, text)

    # Phase 1: Wait for first new response
    first_msg = None
    while time.monotonic() - t0 < timeout:
        msgs = await client.get_messages(BOT_USERNAME, limit=5)
        for m in msgs:
            if not m.out and m.id > marker_id:
                first_msg = m
                break
        if first_msg:
            break
        await asyncio.sleep(POLL_INTERVAL)

    if not first_msg:
        return None, time.monotonic() - t0

    # Phase 2: Wait for edits to settle (message stops changing)
    last_text = first_msg.text or ""
    last_change = time.monotonic()
    msg_id = first_msg.id

    while time.monotonic() - last_change < settle and time.monotonic() - t0 < timeout:
        await asyncio.sleep(0.5)
        refresh = await client.get_messages(BOT_USERNAME, ids=[msg_id])
        if refresh and refresh[0]:
            cur_text = refresh[0].text or ""
            if cur_text != last_text:
                last_text = cur_text
                last_change = time.monotonic()
                first_msg = refresh[0]

    # Also check for newer messages that appeared after our first response
    msgs = await client.get_messages(BOT_USERNAME, limit=5)
    for m in msgs:
        if not m.out and m.id > msg_id:
            # A newer message appeared — might be the actual content
            first_msg = m
            msg_id = m.id

    # Final refresh
    refresh = await client.get_messages(BOT_USERNAME, ids=[msg_id])
    if refresh and refresh[0]:
        first_msg = refresh[0]

    return first_msg, time.monotonic() - t0


async def click_and_wait_edit(client, msg, btn_data: str, timeout: float = 25.0, settle: float = 2.5):
    """Click an inline button and wait for the message to be edited with new content.

    Returns (edited_message, wall_time_seconds).
    """
    initial_text = msg.text or ""
    msg_id = msg.id

    # Find and click the button
    t0 = time.monotonic()
    clicked = False
    if msg.buttons:
        for row in msg.buttons:
            for b in row:
                b_data = (b.data or b"").decode("utf-8", errors="ignore")
                if b_data == btn_data:
                    await b.click()
                    clicked = True
                    break
            if clicked:
                break

    if not clicked:
        return None, 0

    # Wait for edit
    await asyncio.sleep(0.5)
    last_text = initial_text
    last_change = time.monotonic()

    while time.monotonic() - t0 < timeout:
        refresh = await client.get_messages(BOT_USERNAME, ids=[msg_id])
        if refresh and refresh[0]:
            cur_text = refresh[0].text or ""
            if cur_text != initial_text:
                if cur_text != last_text:
                    last_text = cur_text
                    last_change = time.monotonic()
                # Content changed — wait for it to settle
                if time.monotonic() - last_change >= settle:
                    return refresh[0], time.monotonic() - t0
        await asyncio.sleep(POLL_INTERVAL)

    # Timeout — return whatever we have
    refresh = await client.get_messages(BOT_USERNAME, ids=[msg_id])
    if refresh and refresh[0] and (refresh[0].text or "") != initial_text:
        return refresh[0], time.monotonic() - t0
    return None, time.monotonic() - t0


def extract_buttons(msg) -> list[dict]:
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
    if any(w in text_lower for w in ["epl", "psl", "champions league", "la liga", "serie a", "bundesliga", "premier league"]):
        return "soccer"
    return "unknown"


def detect_league(text: str) -> str:
    text_lower = text.lower()
    for league in ["psl", "premier league", "epl", "champions league", "la liga", "serie a", "bundesliga",
                    "urc", "super rugby", "six nations", "currie cup",
                    "sa20", "ipl", "t20 world cup", "test", "odi",
                    "ufc", "boxing"]:
        if league in text_lower:
            return league
    return ""


def detect_tier(text: str) -> str:
    for emoji, name in TIER_NAMES.items():
        if emoji in text:
            return name
    return "unknown"


def extract_verdict_team(text: str) -> str:
    verdict_match = re.search(r'(?:🏆|Verdict).*?(?:\n|$)(.*?)(?:\n\n|\Z)', text, re.DOTALL | re.IGNORECASE)
    if not verdict_match:
        verdict_match = re.search(r'Verdict[^:]*:?\s*[—–-]?\s*(.*?)(?:\n\n|\Z)', text, re.DOTALL | re.IGNORECASE)
    if verdict_match:
        vtext = verdict_match.group(1).strip()
        patterns = [
            r'(?:Back|back|Backing|backing)\s+(.+?)(?:\s+@|\s+at\s|\.|,|\n|$)',
            r'(?:nod to|lean(?:s|ing)? (?:towards?|to))\s+(.+?)(?:\s+@|\s+at\s|\.|,|\n|$)',
            r'(?:favour(?:s|ing)?|favor(?:s|ing)?)\s+(.+?)(?:\s+@|\s+at\s|\.|,|\n|$)',
            r'(?:take|taking|go with)\s+(.+?)(?:\s+@|\s+at\s|\.|,|\n|$)',
        ]
        for pat in patterns:
            m = re.search(pat, vtext, re.IGNORECASE)
            if m:
                return m.group(1).strip().rstrip('.')
        return vtext[:80]
    return ""


def extract_cta_team(buttons: list[dict]) -> tuple[str, str]:
    for btn in buttons:
        text = btn.get("text", "")
        m = re.match(r'[💎🥇🥈🥉]?\s*Back\s+(.+?)\s+@\s+[\d.]+\s+on\s+', text)
        if m:
            return m.group(1).strip(), text
        m = re.match(r'Back\s+(.+?)\s+@\s+[\d.]+', text)
        if m:
            return m.group(1).strip(), text
    return "", ""


def detect_rendering_path(text: str) -> str:
    sections = ["📋", "🎯", "⚠️", "🏆"]
    section_count = sum(1 for s in sections if s in text)
    if section_count >= 3:
        return "AI-ENRICHED"
    if section_count >= 1:
        return "PARTIAL-ENRICHED"
    return "MINIMAL"


def check_banned_phrases(text: str) -> list[str]:
    found = []
    text_lower = text.lower()
    for phrase in BANNED_PHRASES:
        if phrase.lower() in text_lower:
            found.append(phrase)
    return found


async def run_audit():
    client = await get_client()
    print("=" * 70)
    print("QA-BASELINE-20 — Full Product Baseline After BUILD-P0-FIX")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S SAST')}")
    print("Method: Telethon E2E (mandatory)")
    print("=" * 70)

    all_captures: list[CardCapture] = []
    hot_tips_list_text = ""
    my_matches_list_text = ""
    tier_order_violations = []
    latency_log = []
    profile_text = ""
    ux_observations = []

    try:
        # ── PRE-FLIGHT ─────────────────────────────────────────
        print("\n[PRE-FLIGHT] Setting QA tier to diamond...")
        resp, _ = await send_and_wait_stable(client, "/qa set_diamond", timeout=10, settle=2)
        if resp:
            print(f"  {(resp.text or '')[:80]}")

        # ── PROFILE CHECK ──────────────────────────────────────
        print("\n[PROFILE] Checking current profile...")
        profile_msg, pw = await send_and_wait_stable(client, "👤 Profile", timeout=10, settle=2)
        if profile_msg:
            profile_text = profile_msg.text or ""
            print(f"  Profile ({pw:.1f}s):")
            for line in profile_text.split("\n")[:20]:
                if line.strip():
                    print(f"    {line.strip()}")
            latency_log.append(("Profile screen", pw, "PASS" if pw <= 2 else "WARNING" if pw <= 3 else "FAIL"))

        # ── PHASE 1: Hot Tips List ─────────────────────────────
        print(f"\n{'='*70}")
        print("[PHASE 1] Opening Top Edge Picks (Hot Tips)...")
        print(f"{'='*70}")

        ht_msg, ht_wall = await send_and_wait_stable(client, "💎 Top Edge Picks", timeout=25, settle=4)

        if not ht_msg:
            print("  FATAL: No Hot Tips response received")
            return

        hot_tips_list_text = ht_msg.text or ""
        ht_buttons = extract_buttons(ht_msg)
        print(f"  Hot Tips received ({len(hot_tips_list_text)} chars, {ht_wall:.1f}s)")
        latency_log.append(("Hot Tips list first render", ht_wall,
                           "PASS" if ht_wall <= 3 else "WARNING" if ht_wall <= 5 else "FAIL"))

        print(f"\n  === FULL HOT TIPS TEXT ===")
        for line in hot_tips_list_text.split("\n"):
            print(f"  | {line}")
        print(f"  === END ===\n")

        # List all buttons
        print(f"  Buttons ({len(ht_buttons)}):")
        for b in ht_buttons:
            print(f"    text='{b.get('text','')[:60]}' data='{b.get('data','')[:40]}' url={bool(b.get('url'))}")

        # Determine if this is a LIST view or a DETAIL view
        is_list_view = bool(any("edge:detail" in b.get("data", "") for b in ht_buttons))
        detail_buttons = [b for b in ht_buttons if "edge:detail" in b.get("data", "")]
        lock_buttons = [b for b in ht_buttons if "hot:upgrade" in b.get("data", "") or "sub:" in b.get("data", "")]
        page_buttons = [b for b in ht_buttons if "hot:page:" in b.get("data", "")]

        if is_list_view:
            print(f"  VIEW TYPE: LIST (has {len(detail_buttons)} detail btns, {len(lock_buttons)} locked)")
        else:
            print(f"  VIEW TYPE: DETAIL/SINGLE (no edge:detail buttons found)")
            # The whole response IS a card — capture it as a single Hot Tips card
            if "📋" in hot_tips_list_text or "🎯" in hot_tips_list_text:
                cap = CardCapture(
                    index=1,
                    source="hot_tips",
                    match_name="Single Hot Tips card",
                    sport=detect_sport(hot_tips_list_text),
                    league=detect_league(hot_tips_list_text),
                    tier=detect_tier(hot_tips_list_text),
                    detail_text=hot_tips_list_text,
                    detail_buttons=[{"text": b.get("text",""), "data": b.get("data",""), "url": b.get("url","")} for b in ht_buttons],
                    rendering_path=detect_rendering_path(hot_tips_list_text),
                    wall_time=ht_wall,
                )
                cta_t, cta_bt = extract_cta_team(ht_buttons)
                cap.cta_team = cta_t
                cap.cta_button_text = cta_bt
                cap.verdict_team = extract_verdict_team(hot_tips_list_text)
                verdict_section = re.search(r'🏆.*?(?:\n|$)(.*?)(?:\n\n|\Z)', hot_tips_list_text, re.DOTALL)
                if verdict_section:
                    cap.verdict_text = verdict_section.group(0).strip()[:300]
                all_captures.append(cap)
                print(f"  Captured as single card: sport={cap.sport}, tier={cap.tier}")
                print(f"  CTA='{cap.cta_team}' | Verdict='{cap.verdict_team}'")

        # ── PHASE 2: Detail Cards from List ────────────────────
        if is_list_view:
            # Tier order check
            tiers_found = []
            for line in hot_tips_list_text.split("\n"):
                for emoji in TIER_ORDER:
                    if emoji in line and re.search(r'\[\d+\]', line):
                        tiers_found.append((emoji, TIER_NAMES[emoji], line.strip()[:100]))

            print(f"\n  Tier order ({len(tiers_found)} items):")
            prev_rank = -1
            for emoji, name, preview in tiers_found:
                rank = TIER_ORDER[emoji]
                ok = rank >= prev_rank
                print(f"    {'✅' if ok else '❌ OUT OF ORDER'} {emoji} {name}: {preview}")
                if not ok:
                    tier_order_violations.append(f"{name} after prev")
                prev_rank = rank

            # Open each detail card
            print(f"\n{'='*70}")
            print(f"[PHASE 2] Opening {len(detail_buttons)} Hot Tips detail cards...")
            print(f"{'='*70}")

            tips_msg = ht_msg  # Track current message state
            for i, btn in enumerate(detail_buttons):
                btn_text = btn.get("text", "")
                btn_data = btn.get("data", "")
                card_num = len(all_captures) + 1
                print(f"\n  --- HT Card {card_num}: '{btn_text[:60]}' ---")

                try:
                    # Refresh message state
                    refresh = await client.get_messages(BOT_USERNAME, ids=[tips_msg.id])
                    if refresh and refresh[0]:
                        tips_msg = refresh[0]

                    detail_msg, detail_wall = await click_and_wait_edit(
                        client, tips_msg, btn_data, timeout=25, settle=2.5
                    )

                    if not detail_msg:
                        print(f"    WARN: No detail response after {detail_wall:.1f}s")
                        continue

                    detail_text = detail_msg.text or ""
                    detail_btns = extract_buttons(detail_msg)

                    cap = CardCapture(
                        index=card_num,
                        source="hot_tips",
                        match_name=btn_text[:100],
                        sport=detect_sport(detail_text) or detect_sport(btn_text),
                        league=detect_league(detail_text),
                        tier=detect_tier(detail_text) or detect_tier(btn_text),
                        list_text=btn_text,
                        detail_text=detail_text,
                        detail_buttons=[{"text": b.get("text",""), "data": b.get("data",""), "url": b.get("url","")} for b in detail_btns],
                        rendering_path=detect_rendering_path(detail_text),
                        wall_time=detail_wall,
                    )

                    cta_t, cta_bt = extract_cta_team(detail_btns)
                    cap.cta_team = cta_t
                    cap.cta_button_text = cta_bt
                    cap.verdict_team = extract_verdict_team(detail_text)
                    verdict_section = re.search(r'🏆.*?(?:\n|$)(.*?)(?:\n\n|\Z)', detail_text, re.DOTALL)
                    if verdict_section:
                        cap.verdict_text = verdict_section.group(0).strip()[:300]

                    all_captures.append(cap)

                    lat_label = "PASS" if detail_wall <= 2 else "WARNING" if detail_wall <= 4 else "FAIL"
                    latency_log.append((f"HT Card {card_num}: {btn_text[:40]}", detail_wall, lat_label))

                    print(f"    Sport: {cap.sport}, League: {cap.league}, Tier: {cap.tier}")
                    print(f"    Render: {cap.rendering_path}, Wall: {detail_wall:.1f}s [{lat_label}]")
                    print(f"    Text: {len(detail_text)} chars")
                    print(f"    CTA: '{cap.cta_team}' | Verdict: '{cap.verdict_team}'")
                    if cap.cta_team and cap.verdict_team:
                        ct = cap.cta_team.lower().strip()
                        vt = cap.verdict_team.lower().strip()
                        ok = ct in vt or vt in ct
                        print(f"    CTA/Verdict: {'✅' if ok else '❌ MISMATCH — P0'}")

                    # Navigate back to list
                    back_data = None
                    for b in detail_btns:
                        bd = b.get("data", "")
                        if "hot:back" in bd or "Edge Picks" in b.get("text", ""):
                            back_data = bd
                            break
                    if back_data:
                        back_msg, _ = await click_and_wait_edit(
                            client, detail_msg, back_data, timeout=8, settle=1.5
                        )
                        if back_msg:
                            tips_msg = back_msg

                except Exception as e:
                    print(f"    ERROR: {e}")

            # Check page 2
            if page_buttons:
                print(f"\n  Checking page 2...")
                for pb in page_buttons:
                    if "Next" in pb.get("text", "") or "➡️" in pb.get("text", ""):
                        refresh = await client.get_messages(BOT_USERNAME, ids=[tips_msg.id])
                        if refresh and refresh[0]:
                            tips_msg = refresh[0]
                        p2_msg, _ = await click_and_wait_edit(
                            client, tips_msg, pb.get("data", ""), timeout=10, settle=2
                        )
                        if p2_msg:
                            p2_text = p2_msg.text or ""
                            p2_btns = extract_buttons(p2_msg)
                            p2_detail = [b for b in p2_btns if "edge:detail" in b.get("data", "")]
                            print(f"  Page 2: {len(p2_detail)} detail buttons")
                            tips_msg = p2_msg

                            for btn in p2_detail:
                                card_num = len(all_captures) + 1
                                btn_data = btn.get("data", "")
                                btn_text = btn.get("text", "")
                                print(f"\n  --- HT Card {card_num} (P2): '{btn_text[:60]}' ---")

                                try:
                                    refresh = await client.get_messages(BOT_USERNAME, ids=[tips_msg.id])
                                    if refresh and refresh[0]:
                                        tips_msg = refresh[0]

                                    dm, dw = await click_and_wait_edit(
                                        client, tips_msg, btn_data, timeout=25, settle=2.5
                                    )
                                    if not dm:
                                        print(f"    WARN: No response")
                                        continue

                                    dt = dm.text or ""
                                    dbtns = extract_buttons(dm)
                                    cap = CardCapture(
                                        index=card_num, source="hot_tips",
                                        match_name=btn_text[:100],
                                        sport=detect_sport(dt) or detect_sport(btn_text),
                                        league=detect_league(dt), tier=detect_tier(dt) or detect_tier(btn_text),
                                        list_text=btn_text, detail_text=dt,
                                        detail_buttons=[{"text": b.get("text",""), "data": b.get("data",""), "url": b.get("url","")} for b in dbtns],
                                        rendering_path=detect_rendering_path(dt), wall_time=dw,
                                    )
                                    ct, cb = extract_cta_team(dbtns)
                                    cap.cta_team = ct; cap.cta_button_text = cb
                                    cap.verdict_team = extract_verdict_team(dt)
                                    vs = re.search(r'🏆.*?(?:\n|$)(.*?)(?:\n\n|\Z)', dt, re.DOTALL)
                                    if vs: cap.verdict_text = vs.group(0).strip()[:300]
                                    all_captures.append(cap)
                                    lat = "PASS" if dw <= 2 else "WARNING" if dw <= 4 else "FAIL"
                                    latency_log.append((f"HT Card {card_num}: {btn_text[:40]}", dw, lat))
                                    print(f"    Sport: {cap.sport}, Wall: {dw:.1f}s [{lat}], CTA: '{ct}'")

                                    # Back
                                    for b in dbtns:
                                        bd = b.get("data", "")
                                        if "hot:back" in bd:
                                            bm, _ = await click_and_wait_edit(client, dm, bd, timeout=8, settle=1.5)
                                            if bm: tips_msg = bm
                                            break
                                except Exception as e:
                                    print(f"    ERROR: {e}")
                        break

        # ── PHASE 3: My Matches ────────────────────────────────
        print(f"\n{'='*70}")
        print("[PHASE 3] Opening My Matches...")
        print(f"{'='*70}")

        mm_msg, mm_wall = await send_and_wait_stable(client, "⚽ My Matches", timeout=20, settle=4)

        if mm_msg:
            my_matches_list_text = mm_msg.text or ""
            mm_buttons = extract_buttons(mm_msg)
            print(f"  My Matches ({len(my_matches_list_text)} chars, {mm_wall:.1f}s)")
            latency_log.append(("My Matches list first render", mm_wall,
                               "PASS" if mm_wall <= 3 else "WARNING" if mm_wall <= 5 else "FAIL"))

            print(f"\n  === FULL MY MATCHES TEXT ===")
            for line in my_matches_list_text.split("\n"):
                print(f"  | {line}")
            print(f"  === END ===\n")

            print(f"  Buttons ({len(mm_buttons)}):")
            for b in mm_buttons:
                print(f"    text='{b.get('text','')[:60]}' data='{b.get('data','')[:40]}' url={bool(b.get('url'))}")

            game_buttons = [b for b in mm_buttons if "yg:game:" in b.get("data", "")]
            print(f"  Game detail buttons: {len(game_buttons)}")

            # Open each My Matches detail card
            for i, btn in enumerate(game_buttons):
                btn_text = btn.get("text", "")
                btn_data = btn.get("data", "")
                card_num = len(all_captures) + 1
                print(f"\n  --- MM Card {card_num}: '{btn_text[:60]}' ---")

                try:
                    refresh = await client.get_messages(BOT_USERNAME, ids=[mm_msg.id])
                    if refresh and refresh[0]:
                        mm_msg = refresh[0]

                    dm, dw = await click_and_wait_edit(
                        client, mm_msg, btn_data, timeout=25, settle=3
                    )

                    if not dm:
                        print(f"    WARN: No detail response")
                        continue

                    dt = dm.text or ""
                    dbtns = extract_buttons(dm)

                    cap = CardCapture(
                        index=card_num, source="my_matches",
                        match_name=btn_text[:100],
                        sport=detect_sport(dt) or detect_sport(btn_text),
                        league=detect_league(dt), tier=detect_tier(dt) or detect_tier(btn_text),
                        list_text=btn_text, detail_text=dt,
                        detail_buttons=[{"text": b.get("text",""), "data": b.get("data",""), "url": b.get("url","")} for b in dbtns],
                        rendering_path=detect_rendering_path(dt), wall_time=dw,
                    )
                    ct, cb = extract_cta_team(dbtns)
                    cap.cta_team = ct; cap.cta_button_text = cb
                    cap.verdict_team = extract_verdict_team(dt)
                    vs = re.search(r'🏆.*?(?:\n|$)(.*?)(?:\n\n|\Z)', dt, re.DOTALL)
                    if vs: cap.verdict_text = vs.group(0).strip()[:300]

                    all_captures.append(cap)
                    lat = "PASS" if dw <= 2 else "WARNING" if dw <= 4 else "FAIL"
                    latency_log.append((f"MM Card {card_num}: {btn_text[:40]}", dw, lat))

                    print(f"    Sport: {cap.sport}, League: {cap.league}")
                    print(f"    Render: {cap.rendering_path}, Wall: {dw:.1f}s [{lat}]")
                    print(f"    Text: {len(dt)} chars")
                    print(f"    CTA: '{cap.cta_team}' | Verdict: '{cap.verdict_team}'")
                    if cap.cta_team and cap.verdict_team:
                        ct_l = cap.cta_team.lower().strip()
                        vt_l = cap.verdict_team.lower().strip()
                        ok = ct_l in vt_l or vt_l in ct_l
                        print(f"    CTA/Verdict: {'✅' if ok else '❌ MISMATCH — P0'}")

                    # Navigate back
                    for b in dbtns:
                        bd = b.get("data", "")
                        if "yg:all" in bd or "My Matches" in b.get("text", ""):
                            bm, _ = await click_and_wait_edit(client, dm, bd, timeout=8, settle=1.5)
                            if bm: mm_msg = bm
                            break

                except Exception as e:
                    print(f"    ERROR: {e}")
        else:
            print("  ERROR: No My Matches response")

        # ── PHASE 4: UX Screens ───────────────────────────────
        print(f"\n{'='*70}")
        print("[PHASE 4] UX Screen Latency...")
        print(f"{'='*70}")
        for name, cmd in [("Settings", "⚙️ Settings"), ("Help", "❓ Help")]:
            resp, wall = await send_and_wait_stable(client, cmd, timeout=10, settle=2)
            lat = "PASS" if wall <= 2 else "WARNING" if wall <= 3 else "FAIL"
            latency_log.append((f"UX: {name}", wall, lat))
            print(f"  {name}: {wall:.1f}s [{lat}]")
            if resp:
                ux_observations.append(f"{name}: {wall:.1f}s, {len(resp.text or '')} chars")

        # ── PHASE 5: Banned Phrase Scan ───────────────────────
        print(f"\n{'='*70}")
        print("[PHASE 5] Pre-Scoring Banned Phrase Scan (Section 3.6)")
        print(f"{'='*70}")

        all_verbatim = hot_tips_list_text + "\n\n" + my_matches_list_text + "\n\n"
        for cap in all_captures:
            all_verbatim += cap.detail_text + "\n\n"

        banned_found = check_banned_phrases(all_verbatim)
        card_scan = {}
        for cap in all_captures:
            bans = check_banned_phrases(cap.detail_text)
            card_scan[f"Card {cap.index}: {cap.match_name[:50]}"] = bans

        print(f"\n  Phrases checked: {len(BANNED_PHRASES)}")
        print(f"  Cards scanned: {len(all_captures)}")
        for phrase in BANNED_PHRASES:
            found = phrase.lower() in all_verbatim.lower()
            print(f"  {'❌ FOUND' if found else '✅ Clear'}: \"{phrase}\"")

        print(f"\n  Per-card:")
        for name, bans in card_scan.items():
            print(f"  {'❌ '+str(bans) if bans else '✅ CLEAN'}: {name}")

        scan_verdict = "CLEAN" if not banned_found else f"PRODUCT FAIL — {len(banned_found)} banned"
        print(f"\n  Scan verdict: {scan_verdict}")

        # ── PHASE 6: Summary ──────────────────────────────────
        print(f"\n{'='*70}")
        print("[PHASE 6] Summary")
        print(f"{'='*70}")

        ht_cards = [c for c in all_captures if c.source == "hot_tips"]
        mm_cards = [c for c in all_captures if c.source == "my_matches"]
        all_sports = set(c.sport for c in all_captures if c.sport != "unknown")

        print(f"  Hot Tips cards: {len(ht_cards)}")
        print(f"  My Matches cards: {len(mm_cards)}")
        print(f"  Total: {len(all_captures)}")
        print(f"  Sports: {all_sports}")
        print(f"  Tier violations: {len(tier_order_violations)}")

        # CTA/Verdict
        mismatches = []
        for cap in all_captures:
            if cap.cta_team and cap.verdict_team:
                ct = cap.cta_team.lower().strip()
                vt = cap.verdict_team.lower().strip()
                if ct not in vt and vt not in ct:
                    mismatches.append(cap)
        print(f"  CTA/Verdict mismatches: {len(mismatches)}")
        for m in mismatches:
            print(f"    ❌ Card {m.index}: CTA='{m.cta_team}' vs Verdict='{m.verdict_team}'")

        # Latency
        fails = [l for l in latency_log if l[2] == "FAIL"]
        warns = [l for l in latency_log if l[2] == "WARNING"]
        passes = [l for l in latency_log if l[2] == "PASS"]
        print(f"\n  Latency: {len(passes)} PASS, {len(warns)} WARN, {len(fails)} FAIL")
        for n, w, s in latency_log:
            e = "✅" if s == "PASS" else "⚠️" if s == "WARNING" else "❌"
            print(f"    {e} {n}: {w:.1f}s")

        # Save
        data = {
            "timestamp": datetime.now().isoformat(),
            "wave": "QA-BASELINE-20",
            "method": "Telethon E2E",
            "profile_text": profile_text,
            "hot_tips_list_text": hot_tips_list_text,
            "my_matches_list_text": my_matches_list_text,
            "tier_order": [{"emoji": e, "name": n, "preview": p} for e, n, p in (tiers_found if is_list_view else [])],
            "tier_order_violations": tier_order_violations,
            "banned_phrases_found": banned_found,
            "latency_log": [{"name": n, "wall": w, "status": s} for n, w, s in latency_log],
            "ux_observations": ux_observations,
            "captures": [],
        }
        for cap in all_captures:
            data["captures"].append({
                "index": cap.index, "source": cap.source,
                "match_name": cap.match_name, "sport": cap.sport,
                "league": cap.league, "tier": cap.tier,
                "list_text": cap.list_text, "detail_text": cap.detail_text,
                "detail_buttons": cap.detail_buttons,
                "cta_team": cap.cta_team, "cta_button_text": cap.cta_button_text,
                "verdict_team": cap.verdict_team, "verdict_text": cap.verdict_text,
                "rendering_path": cap.rendering_path,
                "wall_time": cap.wall_time, "errors": cap.errors,
            })

        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        with open(RAW_FILE, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"\n  Saved: {RAW_FILE}")

    finally:
        try:
            await client.send_message(BOT_USERNAME, "/qa reset")
            await asyncio.sleep(2)
        except:
            pass
        await client.disconnect()

    print(f"\n{'='*70}")
    print("QA-BASELINE-20 capture complete.")
    print(f"{'='*70}")


if __name__ == "__main__":
    asyncio.run(run_audit())
