#!/usr/bin/env python3
"""QA-BASELINE-21: Full Product Baseline After BUILD-P0-FIX-2 + BUILD-STALE-EV.

Captures verbatim text from all Hot Tips + My Matches cards via Telethon.
Verifies DEF-1 (team name resolution), DEF-2 (negative EV CTA), DEF-3 (stale EV).
Saves all captures to JSON for scoring and report generation.
"""

import asyncio
import json
import os
import re
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import (
    ReplyInlineMarkup,
    KeyboardButtonCallback,
    KeyboardButtonUrl,
)

API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "")
BOT = "mzansiedge_bot"
SESSION_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "telethon_qa_session")
STRING_SESSION_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "telethon_qa_session.string")

CAPTURE_FILE = "/home/paulsportsza/reports/qa-baseline-21-captures.json"
RESULTS = {
    "timestamp": datetime.now().isoformat(),
    "wave": "QA-BASELINE-21",
    "hot_tips_list": [],
    "hot_tips_details": [],
    "my_matches_list": [],
    "my_matches_details": [],
    "wall_times": {},
    "banned_phrase_scan": {},
    "def_verification": {
        "DEF-1": {"description": "CTA team = Edge section team", "issues": [], "pass": True},
        "DEF-2": {"description": "No Back CTA when ev_pct < 0", "issues": [], "pass": True},
        "DEF-3": {"description": "No negative EV tips in Hot Tips list", "issues": [], "pass": True},
    },
}

_entity = None

BANNED_PHRASES = [
    "the edge is carried by the pricing gap alone",
    "standard match-day variables apply",
    "no supporting indicators from any source",
    "no injury data was available",
    "limited data available for this match",
    "market data suggests",
    "based on available information",
]


async def get_client():
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
    global _entity
    if _entity is None:
        _entity = await client.get_entity(BOT)
    return _entity


async def send_and_wait(client, text, wait=25):
    ent = await entity(client)
    t0 = time.time()
    sent = await client.send_message(ent, text)
    deadline = t0 + wait
    bot_msgs = []
    last_check = []
    while time.time() < deadline:
        await asyncio.sleep(1.0)
        messages = await client.get_messages(ent, limit=30)
        new = [m for m in messages if m.id > sent.id and not m.out]
        if new:
            if len(new) == len(last_check):
                latest = new[0]
                if latest.text and len(latest.text) > 30:
                    if "Loading" not in (latest.text or "") and "..." not in (latest.text or "")[-10:]:
                        bot_msgs = list(reversed(new))
                        break
            last_check = new
    if not bot_msgs:
        messages = await client.get_messages(ent, limit=30)
        new = [m for m in messages if m.id > sent.id and not m.out]
        bot_msgs = list(reversed(new))
    return bot_msgs, time.time() - t0


async def click_button(client, msg, callback_data, wait=30):
    if not msg or not msg.reply_markup:
        return None, [], 0.0

    if isinstance(msg.reply_markup, ReplyInlineMarkup):
        for row in msg.reply_markup.rows:
            for btn in row.buttons:
                if isinstance(btn, KeyboardButtonCallback):
                    data = btn.data.decode("utf-8", errors="replace") if btn.data else ""
                    if data == callback_data:
                        t0 = time.time()
                        try:
                            await msg.click(data=btn.data)
                        except Exception as e:
                            print(f"    Click error: {e}")
                            return None, [], time.time() - t0

                        ent = await entity(client)
                        await asyncio.sleep(2)

                        deadline = t0 + wait
                        while time.time() < deadline:
                            edited = await client.get_messages(ent, ids=msg.id)
                            all_msgs = await client.get_messages(ent, limit=30)
                            new = [m for m in all_msgs if m.id > msg.id and not m.out]

                            if edited and edited.text and edited.text != msg.text:
                                elapsed = time.time() - t0
                                return edited, list(reversed(new)), elapsed

                            if new:
                                for nm in new:
                                    if nm.text and len(nm.text) > 50:
                                        elapsed = time.time() - t0
                                        return edited, list(reversed(new)), elapsed

                            await asyncio.sleep(1)

                        elapsed = time.time() - t0
                        edited = await client.get_messages(ent, ids=msg.id)
                        all_msgs = await client.get_messages(ent, limit=30)
                        new = [m for m in all_msgs if m.id > msg.id and not m.out]
                        return edited, list(reversed(new)), elapsed

    return None, [], 0.0


def get_buttons(msg):
    if not msg or not msg.reply_markup:
        return []
    buttons = []
    if isinstance(msg.reply_markup, ReplyInlineMarkup):
        for row in msg.reply_markup.rows:
            for btn in row.buttons:
                if isinstance(btn, KeyboardButtonCallback):
                    data = btn.data.decode("utf-8", errors="replace") if btn.data else ""
                    buttons.append({"text": btn.text, "data": data, "type": "callback"})
                elif isinstance(btn, KeyboardButtonUrl):
                    buttons.append({"text": btn.text, "url": btn.url, "type": "url"})
    return buttons


def extract_edge_buttons(msg):
    buttons = get_buttons(msg)
    edge_btns = [b for b in buttons if b.get("data", "").startswith("edge:detail:")]
    lock_btns = [b for b in buttons if b.get("data", "").startswith("hot:upgrade") or b.get("data", "").startswith("sub:plans")]
    return edge_btns, lock_btns


def extract_game_buttons(msg):
    buttons = get_buttons(msg)
    return [b for b in buttons if b.get("data", "").startswith("yg:game:")]


def scan_banned_phrases(text):
    hits = []
    text_lower = text.lower()
    for phrase in BANNED_PHRASES:
        if phrase.lower() in text_lower:
            hits.append(phrase)
    return hits


def extract_ev_from_text(text):
    """Extract EV percentage from detail card text."""
    ev_match = re.search(r"EV\s*[+\-]?\s*([\-+]?\d+\.?\d*)%", text)
    if ev_match:
        return float(ev_match.group(1))
    return None


def extract_edge_team_from_text(text):
    """Extract team referenced in Edge section."""
    edge_section = ""
    if "🎯" in text:
        start = text.index("🎯")
        # Find next section marker
        for marker in ["⚠️", "🏆"]:
            if marker in text[start+1:]:
                end = text.index(marker, start+1)
                edge_section = text[start:end]
                break
        if not edge_section:
            edge_section = text[start:start+500]
    return edge_section


# ── Main audit functions ──

async def audit_hot_tips(client):
    print("\n=== STEP 1: Hot Tips List ===")
    msgs, wall = await send_and_wait(client, "💎 Top Edge Picks", wait=25)
    RESULTS["wall_times"]["hot_tips_list"] = round(wall, 2)
    print(f"  Response time: {wall:.1f}s, Messages: {len(msgs)}")

    if not msgs:
        print("  ERROR: No response from Hot Tips")
        return None, [], []

    tips_msg = max(msgs, key=lambda m: len(m.text or ""))
    tips_text = tips_msg.text or ""
    print(f"  Tips text length: {len(tips_text)} chars")
    print(f"  === VERBATIM HOT TIPS LIST ===")
    print(tips_text)
    print(f"  === END VERBATIM ===")

    RESULTS["hot_tips_list"] = [{
        "text": tips_text,
        "buttons": get_buttons(tips_msg),
        "msg_id": tips_msg.id,
    }]

    for m in msgs:
        if m.id != tips_msg.id and m.text:
            RESULTS["hot_tips_list"].append({
                "text": m.text,
                "buttons": get_buttons(m),
                "msg_id": m.id,
            })

    edge_btns, lock_btns = extract_edge_buttons(tips_msg)
    print(f"  Edge buttons: {len(edge_btns)}, Lock buttons: {len(lock_btns)}")
    for b in edge_btns:
        print(f"    {b['text']} → {b['data']}")
    for b in lock_btns:
        print(f"    🔒 {b['text']} → {b['data']}")

    # DEF-3: Check for negative EV in list
    ev_matches = re.findall(r"EV\s*([+\-]?\d+\.?\d*)%", tips_text)
    for ev_str in ev_matches:
        ev_val = float(ev_str)
        if ev_val < 0:
            RESULTS["def_verification"]["DEF-3"]["issues"].append(
                f"Negative EV {ev_val}% found in Hot Tips list"
            )
            RESULTS["def_verification"]["DEF-3"]["pass"] = False

    # Check pagination
    page_btns = [b for b in get_buttons(tips_msg) if "hot:page:" in b.get("data", "")]
    if page_btns:
        print(f"\n  Pagination buttons: {[b['data'] for b in page_btns]}")
        for pb in page_btns:
            if "hot:page:1" in pb["data"]:
                print("  Clicking page 2...")
                edited, new_msgs, pw = await click_button(client, tips_msg, pb["data"], wait=10)
                if edited and edited.text:
                    p2_text = edited.text
                    print(f"  === VERBATIM PAGE 2 ===")
                    print(p2_text)
                    print(f"  === END VERBATIM ===")
                    RESULTS["hot_tips_list"].append({
                        "text": p2_text,
                        "buttons": get_buttons(edited),
                        "msg_id": edited.id if hasattr(edited, 'id') else 0,
                        "page": 2,
                    })
                    more_edge, more_lock = extract_edge_buttons(edited)
                    edge_btns.extend(more_edge)
                    lock_btns.extend(more_lock)
                    # DEF-3 on page 2
                    p2_ev_matches = re.findall(r"EV\s*([+\-]?\d+\.?\d*)%", p2_text)
                    for ev_str in p2_ev_matches:
                        ev_val = float(ev_str)
                        if ev_val < 0:
                            RESULTS["def_verification"]["DEF-3"]["issues"].append(
                                f"Negative EV {ev_val}% on page 2"
                            )
                            RESULTS["def_verification"]["DEF-3"]["pass"] = False
                    # Go back
                    p1_btns = [b for b in get_buttons(edited) if "hot:page:0" in b.get("data", "")]
                    if p1_btns:
                        await click_button(client, edited, p1_btns[0]["data"], wait=5)

    # Count Live Edges from header
    edge_count_match = re.search(r"(\d+)\s*Live\s*Edges?\s*Found", tips_text)
    if edge_count_match:
        print(f"  Live Edges Found: {edge_count_match.group(1)}")

    return tips_msg, edge_btns, lock_btns


async def audit_edge_details(client, tips_msg, edge_btns):
    print(f"\n=== STEP 2: Edge Detail Cards ({len(edge_btns)} edges) ===")

    for i, btn in enumerate(edge_btns):
        print(f"\n  --- Card {i+1}: {btn['text']} ---")
        edited, new_msgs, wall = await click_button(client, tips_msg, btn["data"], wait=35)
        RESULTS["wall_times"][f"edge_detail_{i+1}"] = round(wall, 2)

        detail_text = ""
        detail_buttons = []
        detail_msg = None

        if edited and edited.text and len(edited.text) > 100:
            detail_text = edited.text
            detail_buttons = get_buttons(edited)
            detail_msg = edited
        elif new_msgs:
            for nm in new_msgs:
                if nm.text and len(nm.text) > 100:
                    detail_text = nm.text
                    detail_buttons = get_buttons(nm)
                    detail_msg = nm
                    break

        if not detail_text:
            print(f"    WARNING: No detail content (wall: {wall:.1f}s)")
            RESULTS["hot_tips_details"].append({
                "card_index": i + 1,
                "button_text": btn["text"],
                "button_data": btn["data"],
                "text": "",
                "buttons": [],
                "wall_time": round(wall, 2),
                "status": "NO_RESPONSE",
            })
            continue

        print(f"    Wall time: {wall:.1f}s")
        print(f"  === VERBATIM CARD {i+1} ===")
        print(detail_text)
        print(f"  === BUTTONS ===")
        for b in detail_buttons:
            print(f"    [{b.get('type')}] {b.get('text')} → {b.get('data', b.get('url', ''))}")
        print(f"  === END CARD {i+1} ===")

        # Rendering path classification
        rendering_path = "UNKNOWN"
        if "📋" in detail_text and "🎯" in detail_text:
            rendering_path = "AI-ENRICHED"
        elif "📋" in detail_text:
            rendering_path = "BASELINE"
        elif "🔒" in detail_text:
            rendering_path = "LOCKED"

        # Template marker check (P0 if found)
        has_template = any(marker in detail_text for marker in [
            "TEMPLATE", "INSTANT BASELINE", "{{",
        ])

        # Extract CTA team from buttons
        cta_team = ""
        cta_badge = ""
        cta_has_url = False
        for b in detail_buttons:
            if b.get("type") == "url" and "Back " in b.get("text", ""):
                cta_has_url = True
                cta_match = re.search(r"Back\s+(.+?)\s+@", b["text"])
                if cta_match:
                    cta_team = cta_match.group(1).strip()
                for emoji in ["💎", "🥇", "🥈", "🥉"]:
                    if emoji in b["text"]:
                        cta_badge = emoji
                        break

        # Extract Edge section team
        edge_section = extract_edge_team_from_text(detail_text)

        # Extract verdict team
        verdict_team = ""
        verdict_match = re.search(r"🏆.*?(?:Back|back|Lean|lean)\s+(.+?)(?:\.|,|\n|$)", detail_text)
        if verdict_match:
            verdict_team = verdict_match.group(1).strip()

        # Extract EV for DEF-2 check
        ev_pct = extract_ev_from_text(detail_text)

        # DEF-1: CTA team vs Edge section team consistency
        if cta_team and edge_section:
            # Check if cta_team appears in edge section
            cta_words = set(cta_team.lower().split())
            if not any(w in edge_section.lower() for w in cta_words if len(w) > 2):
                issue = f"Card {i+1}: CTA team '{cta_team}' NOT in Edge section"
                RESULTS["def_verification"]["DEF-1"]["issues"].append(issue)
                RESULTS["def_verification"]["DEF-1"]["pass"] = False
                print(f"    ❌ DEF-1 FAIL: {issue}")

        # DEF-2: Negative EV should not have Back CTA
        if ev_pct is not None and ev_pct < 0 and cta_has_url:
            issue = f"Card {i+1}: EV {ev_pct}% < 0 but has Back CTA URL button"
            RESULTS["def_verification"]["DEF-2"]["issues"].append(issue)
            RESULTS["def_verification"]["DEF-2"]["pass"] = False
            print(f"    ❌ DEF-2 FAIL: {issue}")

        # Tier badge
        detail_tier = ""
        for emoji, tier in [("💎", "diamond"), ("🥇", "gold"), ("🥈", "silver"), ("🥉", "bronze")]:
            if emoji in detail_text[:200]:
                detail_tier = tier
                break

        RESULTS["hot_tips_details"].append({
            "card_index": i + 1,
            "button_text": btn["text"],
            "button_data": btn["data"],
            "text": detail_text,
            "buttons": detail_buttons,
            "wall_time": round(wall, 2),
            "rendering_path": rendering_path,
            "has_template_marker": has_template,
            "cta_team": cta_team,
            "cta_badge": cta_badge,
            "verdict_team": verdict_team,
            "detail_tier": detail_tier,
            "ev_pct": ev_pct,
            "status": "OK",
        })

        # Navigate back
        back_btns = [b for b in detail_buttons if b.get("data", "").startswith("hot:back")]
        if back_btns:
            await click_button(client, detail_msg or tips_msg, back_btns[0]["data"], wait=8)
            await asyncio.sleep(1)
        else:
            await asyncio.sleep(2)


async def audit_my_matches(client):
    print("\n=== STEP 3: My Matches List ===")
    msgs, wall = await send_and_wait(client, "⚽ My Matches", wait=20)
    RESULTS["wall_times"]["my_matches_list"] = round(wall, 2)
    print(f"  Response time: {wall:.1f}s, Messages: {len(msgs)}")

    if not msgs:
        print("  ERROR: No response from My Matches")
        return None

    mm_msg = max(msgs, key=lambda m: len(m.text or ""))
    mm_text = mm_msg.text or ""
    print(f"  === VERBATIM MY MATCHES LIST ===")
    print(mm_text)
    print(f"  === BUTTONS ===")
    for b in get_buttons(mm_msg):
        print(f"    [{b.get('type')}] {b.get('text')} → {b.get('data', b.get('url', ''))}")
    print(f"  === END VERBATIM ===")

    RESULTS["my_matches_list"] = [{
        "text": mm_text,
        "buttons": get_buttons(mm_msg),
        "msg_id": mm_msg.id,
    }]

    return mm_msg


async def audit_my_matches_details(client, mm_msg):
    if not mm_msg:
        return

    game_btns = extract_game_buttons(mm_msg)
    audit_count = min(len(game_btns), 3)  # Audit up to 3 MM cards
    print(f"\n=== STEP 4: My Matches Detail Cards ({len(game_btns)} games, auditing {audit_count}) ===")

    for i, btn in enumerate(game_btns[:audit_count]):
        print(f"\n  --- MM Card {i+1}: {btn['text']} ---")
        edited, new_msgs, wall = await click_button(client, mm_msg, btn["data"], wait=35)
        RESULTS["wall_times"][f"mm_detail_{i+1}"] = round(wall, 2)

        detail_text = ""
        detail_buttons = []

        if edited and edited.text and len(edited.text) > 100:
            detail_text = edited.text
            detail_buttons = get_buttons(edited)
        elif new_msgs:
            for nm in new_msgs:
                if nm.text and len(nm.text) > 100:
                    detail_text = nm.text
                    detail_buttons = get_buttons(nm)
                    break

        if not detail_text:
            print(f"    WARNING: No detail content (wall: {wall:.1f}s)")
            RESULTS["my_matches_details"].append({
                "card_index": i + 1,
                "button_text": btn["text"],
                "text": "",
                "wall_time": round(wall, 2),
                "status": "NO_RESPONSE",
            })
            continue

        print(f"    Wall time: {wall:.1f}s")
        print(f"  === VERBATIM MM CARD {i+1} ===")
        print(detail_text)
        print(f"  === BUTTONS ===")
        for b in detail_buttons:
            print(f"    [{b.get('type')}] {b.get('text')} → {b.get('data', b.get('url', ''))}")
        print(f"  === END MM CARD {i+1} ===")

        # Rendering path
        rendering_path = "UNKNOWN"
        if "📋" in detail_text and "🎯" in detail_text:
            rendering_path = "AI-ENRICHED"
        elif "📋" in detail_text:
            rendering_path = "BASELINE"

        RESULTS["my_matches_details"].append({
            "card_index": i + 1,
            "button_text": btn["text"],
            "button_data": btn["data"],
            "text": detail_text,
            "buttons": detail_buttons,
            "wall_time": round(wall, 2),
            "rendering_path": rendering_path,
            "status": "OK",
        })

        # Navigate back
        back_btns = [b for b in detail_buttons if "yg:all" in b.get("data", "")]
        if back_btns:
            await click_button(client, edited or mm_msg, back_btns[0]["data"], wait=8)
            await asyncio.sleep(1)


async def main():
    print("QA-BASELINE-21 — Full Product Baseline After BUILD-P0-FIX-2 + BUILD-STALE-EV")
    print(f"Timestamp: {RESULTS['timestamp']}")
    print("=" * 60)

    client = await get_client()
    print("Telethon connected.")

    try:
        # Step 1: Hot Tips list + pagination
        result = await audit_hot_tips(client)
        tips_msg, edge_btns, lock_btns = (None, [], [])
        if result:
            tips_msg, edge_btns, lock_btns = result

        # Step 2: All edge detail cards
        if edge_btns:
            await audit_edge_details(client, tips_msg, edge_btns)

        # Step 3: My Matches list
        mm_msg = await audit_my_matches(client)

        # Step 4: My Matches details (up to 3)
        await audit_my_matches_details(client, mm_msg)

        # Step 5: Banned phrase scan
        print("\n=== STEP 5: Banned Phrase Scan ===")
        all_verbatim = []
        for item in RESULTS["hot_tips_list"]:
            if item.get("text"):
                all_verbatim.append(("hot_tips_list", item["text"]))
        for item in RESULTS["hot_tips_details"]:
            if item.get("text"):
                all_verbatim.append((f"edge_detail_{item['card_index']}", item["text"]))
        for item in RESULTS["my_matches_list"]:
            if item.get("text"):
                all_verbatim.append(("my_matches_list", item["text"]))
        for item in RESULTS["my_matches_details"]:
            if item.get("text"):
                all_verbatim.append((f"mm_detail_{item['card_index']}", item["text"]))

        total_hits = 0
        for source, text in all_verbatim:
            hits = scan_banned_phrases(text)
            if hits:
                print(f"  ❌ BANNED PHRASE in {source}: {hits}")
                RESULTS["banned_phrase_scan"][source] = hits
                total_hits += len(hits)

        if total_hits == 0:
            print("  ✅ All 7 banned phrases CLEAR")
            RESULTS["banned_phrase_scan"]["result"] = "PASS"
        else:
            print(f"  ❌ FAIL: {total_hits} banned phrase hits")
            RESULTS["banned_phrase_scan"]["result"] = "FAIL"

        # Step 6: DEF verification summary
        print("\n=== STEP 6: DEF Verification Summary ===")
        for def_id, def_data in RESULTS["def_verification"].items():
            status = "✅ PASS" if def_data["pass"] else "❌ FAIL"
            print(f"  {def_id}: {status} — {def_data['description']}")
            for issue in def_data["issues"]:
                print(f"    → {issue}")

        # Save captures
        with open(CAPTURE_FILE, "w") as f:
            json.dump(RESULTS, f, indent=2, default=str)
        print(f"\nCaptures saved to {CAPTURE_FILE}")

    finally:
        await client.disconnect()
        print("Disconnected.")


if __name__ == "__main__":
    asyncio.run(main())
