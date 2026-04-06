#!/usr/bin/env python3
"""QA-BASELINE-19: Full Product Audit Post BUILD-GATE-RELAX.

Captures verbatim text from all Hot Tips + My Matches cards via Telethon.
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
SESSION_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "telethon_session")
STRING_SESSION_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "telethon_session.string")

CAPTURE_FILE = "/home/paulsportsza/reports/qa-baseline-19-captures.json"
RESULTS = {
    "timestamp": datetime.now().isoformat(),
    "hot_tips_list": [],
    "hot_tips_details": [],
    "my_matches_list": [],
    "my_matches_details": [],
    "wall_times": {},
    "banned_phrase_scan": {},
}

_entity = None


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


async def send_and_wait(client, text, wait=20):
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
            # Wait for content to stabilize (spinner → final)
            if len(new) == len(last_check):
                # Check if latest message has substantive content
                latest = new[0]  # newest first from get_messages
                if latest.text and len(latest.text) > 30:
                    # Not a spinner/loading message
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

    # Find button in inline markup
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
    """Extract edge:detail buttons from a Hot Tips list message."""
    buttons = get_buttons(msg)
    edge_btns = [b for b in buttons if b.get("data", "").startswith("edge:detail:")]
    lock_btns = [b for b in buttons if b.get("data", "").startswith("hot:upgrade") or b.get("data", "").startswith("sub:plans")]
    return edge_btns, lock_btns


def extract_game_buttons(msg):
    """Extract yg:game buttons from My Matches list."""
    buttons = get_buttons(msg)
    return [b for b in buttons if b.get("data", "").startswith("yg:game:")]


# ── Banned phrase scan ──
BANNED_PHRASES = [
    "the edge is carried by the pricing gap alone",
    "standard match-day variables apply",
    "no supporting indicators from any source",
    "no injury data was available",
    "limited data available for this match",
    "market data suggests",
    "based on available information",
]


def scan_banned_phrases(text):
    hits = []
    text_lower = text.lower()
    for phrase in BANNED_PHRASES:
        if phrase.lower() in text_lower:
            hits.append(phrase)
    return hits


# ── Main audit ──

async def audit_hot_tips(client):
    print("\n=== STEP 1: Hot Tips List ===")
    msgs, wall = await send_and_wait(client, "💎 Top Edge Picks", wait=25)
    RESULTS["wall_times"]["hot_tips_list"] = round(wall, 2)
    print(f"  Response time: {wall:.1f}s, Messages: {len(msgs)}")

    if not msgs:
        print("  ERROR: No response from Hot Tips")
        return

    # Find the main tips message (longest one with edge content)
    tips_msg = max(msgs, key=lambda m: len(m.text or ""))
    tips_text = tips_msg.text or ""

    print(f"  Tips text length: {len(tips_text)} chars")
    print(f"  First 500 chars:\n{tips_text[:500]}")

    RESULTS["hot_tips_list"] = [{
        "text": tips_text,
        "buttons": get_buttons(tips_msg),
        "msg_id": tips_msg.id,
    }]

    # Also capture any additional messages (pagination messages, etc.)
    for m in msgs:
        if m.id != tips_msg.id and m.text:
            RESULTS["hot_tips_list"].append({
                "text": m.text,
                "buttons": get_buttons(m),
                "msg_id": m.id,
            })

    # Get edge detail buttons
    edge_btns, lock_btns = extract_edge_buttons(tips_msg)
    print(f"  Edge buttons: {len(edge_btns)}, Lock buttons: {len(lock_btns)}")
    for b in edge_btns:
        print(f"    {b['text']} → {b['data']}")
    for b in lock_btns:
        print(f"    🔒 {b['text']} → {b['data']}")

    # Check for pagination — if there's a next page button, get it too
    page_btns = [b for b in get_buttons(tips_msg) if "hot:page:" in b.get("data", "")]
    if page_btns:
        print(f"\n  Pagination buttons found: {[b['data'] for b in page_btns]}")
        for pb in page_btns:
            if "hot:page:1" in pb["data"]:
                print("  Clicking page 2...")
                edited, new_msgs, pw = await click_button(client, tips_msg, pb["data"], wait=10)
                if edited and edited.text:
                    p2_text = edited.text
                    RESULTS["hot_tips_list"].append({
                        "text": p2_text,
                        "buttons": get_buttons(edited),
                        "msg_id": edited.id if hasattr(edited, 'id') else 0,
                        "page": 2,
                    })
                    # Get more edge buttons from page 2
                    more_edge, more_lock = extract_edge_buttons(edited)
                    edge_btns.extend(more_edge)
                    lock_btns.extend(more_lock)
                    print(f"  Page 2 edge buttons: {len(more_edge)}")
                    # Go back to page 1
                    p1_btns = [b for b in get_buttons(edited) if "hot:page:0" in b.get("data", "")]
                    if p1_btns:
                        await click_button(client, edited, p1_btns[0]["data"], wait=5)

    return tips_msg, edge_btns, lock_btns


async def audit_edge_details(client, tips_msg, edge_btns):
    print(f"\n=== STEP 2: Edge Detail Cards ({len(edge_btns)} edges) ===")

    for i, btn in enumerate(edge_btns):
        print(f"\n  --- Card {i+1}: {btn['text']} ---")
        edited, new_msgs, wall = await click_button(client, tips_msg, btn["data"], wait=30)
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
            print(f"    WARNING: No detail content received (wall: {wall:.1f}s)")
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
        print(f"    Text length: {len(detail_text)} chars")
        print(f"    Text preview:\n{detail_text[:300]}")

        # Identify rendering path
        rendering_path = "UNKNOWN"
        if "📋" in detail_text and "🎯" in detail_text:
            rendering_path = "AI-ENRICHED"
        elif "📋" in detail_text:
            rendering_path = "BASELINE"
        elif "🔒" in detail_text:
            rendering_path = "LOCKED"

        # Check for template markers
        has_template = any(marker in detail_text for marker in [
            "TEMPLATE", "INSTANT BASELINE", "{", "{{",
        ])

        # Extract CTA team from buttons
        cta_team = ""
        cta_badge = ""
        for b in detail_buttons:
            if b.get("type") == "url" and "Back " in b.get("text", ""):
                # CTA like "🥇 Back Arsenal @ 1.58 on Betway →"
                cta_match = re.search(r"Back\s+(.+?)\s+@", b["text"])
                if cta_match:
                    cta_team = cta_match.group(1).strip()
                # Badge from CTA
                for emoji in ["💎", "🥇", "🥈", "🥉"]:
                    if emoji in b["text"]:
                        cta_badge = emoji
                        break

        # Extract verdict team from text
        verdict_team = ""
        verdict_match = re.search(r"🏆.*?(?:Back|back|Lean|lean)\s+(.+?)(?:\.|,|\n|$)", detail_text)
        if verdict_match:
            verdict_team = verdict_match.group(1).strip()

        # Check tier badge in detail
        detail_tier = ""
        for emoji, tier in [("💎", "diamond"), ("🥇", "gold"), ("🥈", "silver"), ("🥉", "bronze")]:
            if emoji in detail_text[:200]:
                detail_tier = tier
                break

        # Check for conviction language (banned on zero-signal)
        conviction_phrases = ["solid case", "strong value", "clear signals", "strong evidence",
                             "compelling", "convincing", "high conviction"]
        has_conviction = any(p in detail_text.lower() for p in conviction_phrases)

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
            "has_conviction_language": has_conviction,
            "status": "OK",
        })

        # Go back to tips list
        back_btns = [b for b in detail_buttons if b.get("data", "").startswith("hot:back")]
        if back_btns:
            await click_button(client, detail_msg or tips_msg, back_btns[0]["data"], wait=8)
            await asyncio.sleep(1)
        else:
            # Try sending the keyboard tap again
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
    print(f"  Text length: {len(mm_text)} chars")
    print(f"  First 500 chars:\n{mm_text[:500]}")

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
    print(f"\n=== STEP 4: My Matches Detail Cards ({len(game_btns)} games, auditing 2) ===")

    for i, btn in enumerate(game_btns[:2]):
        print(f"\n  --- MM Card {i+1}: {btn['text']} ---")
        edited, new_msgs, wall = await click_button(client, mm_msg, btn["data"], wait=30)
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
        print(f"    Text length: {len(detail_text)} chars")

        RESULTS["my_matches_details"].append({
            "card_index": i + 1,
            "button_text": btn["text"],
            "button_data": btn["data"],
            "text": detail_text,
            "buttons": detail_buttons,
            "wall_time": round(wall, 2),
            "status": "OK",
        })

        # Navigate back
        back_btns = [b for b in detail_buttons if "yg:all" in b.get("data", "")]
        if back_btns:
            await click_button(client, edited or mm_msg, back_btns[0]["data"], wait=8)
            await asyncio.sleep(1)


async def main():
    print("QA-BASELINE-19 — Full Product Audit")
    print(f"Timestamp: {RESULTS['timestamp']}")
    print("=" * 60)

    client = await get_client()
    print("Telethon connected.")

    try:
        # Step 1: Hot Tips list
        result = await audit_hot_tips(client)
        if result:
            tips_msg, edge_btns, lock_btns = result

            # Step 2: Edge details (all accessible edges)
            if edge_btns:
                await audit_edge_details(client, tips_msg, edge_btns)

        # Step 3: My Matches list
        mm_msg = await audit_my_matches(client)

        # Step 4: My Matches details (2 cards)
        await audit_my_matches_details(client, mm_msg)

        # Step 5: Banned phrase scan on ALL captured text
        print("\n=== STEP 5: Banned Phrase Scan ===")
        all_verbatim = []

        # Collect all text
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
            print("  ✅ All 7 banned phrases CLEAR across all verbatim text")
            RESULTS["banned_phrase_scan"]["result"] = "PASS"
        else:
            print(f"  ❌ FAIL: {total_hits} banned phrase hits")
            RESULTS["banned_phrase_scan"]["result"] = "FAIL"

        # Save captures
        with open(CAPTURE_FILE, "w") as f:
            json.dump(RESULTS, f, indent=2, default=str)
        print(f"\nCaptures saved to {CAPTURE_FILE}")

    finally:
        await client.disconnect()

    print("\n" + "=" * 60)
    print("QA-BASELINE-19 E2E capture complete.")


if __name__ == "__main__":
    asyncio.run(main())
