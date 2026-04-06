"""QA-BASELINE-22: Full Product Baseline After CTA Fix + API-Football Live Path.

Telethon E2E capture — every card verbatim, every button, every CTA.
READ-ONLY test: captures bot output, scores nothing, modifies nothing.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
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
DETAIL_TIMEOUT = 20  # longer timeout for detail views (may trigger AI)

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
        print("ERROR: Not logged in.")
        sys.exit(1)
    return client


def extract_buttons(msg) -> list[dict]:
    """Extract all inline buttons with text, callback data, and URLs."""
    buttons = []
    if not msg.reply_markup or not isinstance(msg.reply_markup, ReplyInlineMarkup):
        return buttons
    for row_idx, row in enumerate(msg.reply_markup.rows):
        for btn_idx, btn in enumerate(row.buttons):
            info = {"row": row_idx, "col": btn_idx, "text": getattr(btn, "text", "")}
            if isinstance(btn, KeyboardButtonCallback):
                info["type"] = "callback"
                info["data"] = btn.data.decode("utf-8", errors="replace") if btn.data else ""
            elif isinstance(btn, KeyboardButtonUrl):
                info["type"] = "url"
                info["url"] = btn.url
            else:
                info["type"] = type(btn).__name__
            buttons.append(info)
    return buttons


async def send_and_capture(client, text, wait=TIMEOUT):
    """Send message, wait, return all bot responses after our message."""
    entity = await client.get_entity(BOT_USERNAME)
    sent = await client.send_message(entity, text)
    sent_id = sent.id
    await asyncio.sleep(wait)
    messages = await client.get_messages(entity, limit=30)
    recent = [m for m in messages if m.id > sent_id and not m.out]
    return list(reversed(recent))


async def click_inline_button(client, msg, button_data_prefix, wait=TIMEOUT):
    """Click an inline button by callback data prefix. Returns new messages."""
    if not msg.reply_markup or not isinstance(msg.reply_markup, ReplyInlineMarkup):
        return []
    for row in msg.reply_markup.rows:
        for btn in row.buttons:
            if isinstance(btn, KeyboardButtonCallback):
                data = btn.data.decode("utf-8", errors="replace") if btn.data else ""
                if data.startswith(button_data_prefix):
                    await msg.click(data=btn.data)
                    await asyncio.sleep(wait)
                    entity = await client.get_entity(BOT_USERNAME)
                    messages = await client.get_messages(entity, limit=15)
                    return list(reversed(messages))
    return []


async def click_button_by_text(client, msg, button_text_contains, wait=TIMEOUT):
    """Click an inline button by matching text substring. Returns new messages."""
    if not msg.reply_markup or not isinstance(msg.reply_markup, ReplyInlineMarkup):
        return []
    for row in msg.reply_markup.rows:
        for btn in row.buttons:
            if hasattr(btn, "text") and button_text_contains in btn.text:
                if isinstance(btn, KeyboardButtonCallback):
                    await msg.click(data=btn.data)
                    await asyncio.sleep(wait)
                    entity = await client.get_entity(BOT_USERNAME)
                    messages = await client.get_messages(entity, limit=15)
                    return list(reversed(messages))
    return []


# ── BANNED PHRASES ───────────────────────────────────────
BANNED_PHRASES = [
    "the edge is carried by the pricing gap alone",
    "standard match-day variables apply",
    "no supporting indicators from any source",
    "no injury data was available",
    "limited data available for this match",
    "market data suggests",
    "based on available information",
]


def check_banned_phrases(text: str) -> list[str]:
    """Return list of any banned phrases found in text."""
    if not text:
        return []
    lower = text.lower()
    return [p for p in BANNED_PHRASES if p in lower]


# ── MAIN QA FLOW ────────────────────────────────────────

async def run_qa():
    results = {
        "timestamp": datetime.now().isoformat(),
        "hot_tips": {"list_text": "", "list_buttons": [], "cards": []},
        "my_matches": {"list_text": "", "list_buttons": [], "cards": []},
        "banned_phrase_hits": [],
        "cta_checks": [],
        "apifootball_checks": [],
        "defect_checks": [],
    }

    client = await get_client()
    print("Connected to Telegram.\n")

    # ── STEP 1: Hot Tips ─────────────────────────────────
    print("=" * 60)
    print("STEP 1: HOT TIPS")
    print("=" * 60)

    msgs = await send_and_capture(client, "💎 Top Edge Picks", wait=18)

    # Find the main hot tips message (the one with tips content)
    ht_msg = None
    all_ht_text = []
    for msg in msgs:
        if msg.text:
            all_ht_text.append(msg.text)
            print(f"\n--- Bot message (id={msg.id}) ---")
            print(msg.text[:500])
            btns = extract_buttons(msg)
            if btns:
                print(f"  Buttons: {json.dumps(btns, indent=2)}")
            # Main tips message has edge picks content
            if ("Edge" in msg.text or "edge" in msg.text or "Live" in msg.text) and not msg.out:
                ht_msg = msg

    if ht_msg:
        results["hot_tips"]["list_text"] = ht_msg.text
        results["hot_tips"]["list_buttons"] = extract_buttons(ht_msg)

        # Check for banned phrases in list
        for txt in all_ht_text:
            hits = check_banned_phrases(txt)
            if hits:
                results["banned_phrase_hits"].extend(
                    [{"location": "hot_tips_list", "phrase": h} for h in hits]
                )

        # Count edge picks and find clickable buttons
        print(f"\n\nHot Tips list captured. Finding clickable tip buttons...")

        # Find ALL messages with tip buttons (could be paginated)
        tip_buttons = []
        for msg in msgs:
            if not msg.out:
                btns = extract_buttons(msg)
                for btn in btns:
                    if btn.get("type") == "callback":
                        data = btn.get("data", "")
                        if data.startswith("edge:detail:"):
                            tip_buttons.append((msg, btn))

        print(f"Found {len(tip_buttons)} clickable tip detail buttons.")

        # ── STEP 2: Open EVERY Hot Tips card ─────────────
        print("\n" + "=" * 60)
        print("STEP 2: HOT TIPS DETAIL CARDS")
        print("=" * 60)

        for idx, (parent_msg, btn) in enumerate(tip_buttons):
            print(f"\n--- Opening card {idx+1}/{len(tip_buttons)}: {btn['text']} ---")
            print(f"    Callback data: {btn['data']}")

            detail_msgs = await click_inline_button(
                client, parent_msg, btn["data"], wait=DETAIL_TIMEOUT
            )

            card_info = {
                "index": idx + 1,
                "button_text": btn["text"],
                "callback_data": btn["data"],
                "detail_text": "",
                "detail_buttons": [],
                "banned_hits": [],
                "cta_bookmaker": "",
                "cta_odds": "",
                "narrative_bookmaker": "",
                "narrative_odds": "",
                "broadcast_line": "",
                "has_setup_section": False,
                "has_edge_section": False,
                "has_risk_section": False,
                "has_verdict_section": False,
            }

            # Get the latest non-outgoing message (the detail view)
            for dmsg in reversed(detail_msgs):
                if dmsg.text and not dmsg.out:
                    card_info["detail_text"] = dmsg.text
                    card_info["detail_buttons"] = extract_buttons(dmsg)

                    # Check sections
                    card_info["has_setup_section"] = "📋" in dmsg.text
                    card_info["has_edge_section"] = "🎯" in dmsg.text
                    card_info["has_risk_section"] = "⚠️" in dmsg.text
                    card_info["has_verdict_section"] = "🏆" in dmsg.text

                    # Check broadcast
                    if "📺" in dmsg.text or "DStv" in dmsg.text or "SuperSport" in dmsg.text:
                        for line in dmsg.text.split("\n"):
                            if "📺" in line or "DStv" in line:
                                card_info["broadcast_line"] = line.strip()
                                break

                    # Check banned phrases
                    hits = check_banned_phrases(dmsg.text)
                    card_info["banned_hits"] = hits
                    if hits:
                        results["banned_phrase_hits"].extend(
                            [{"location": f"hot_tips_card_{idx+1}", "phrase": h} for h in hits]
                        )

                    # Extract CTA bookmaker/odds from buttons
                    for b in card_info["detail_buttons"]:
                        if b.get("type") == "url" and ("Bet" in b.get("text", "") or "Back" in b.get("text", "") or "@" in b.get("text", "")):
                            card_info["cta_bookmaker"] = b["text"]
                        elif b.get("type") == "callback" and ("Back" in b.get("text", "") and "@" in b.get("text", "")):
                            card_info["cta_bookmaker"] = b["text"]

                    # Extract narrative bookmaker mention
                    text_lower = dmsg.text.lower()
                    for bk in ["hollywoodbets", "betway", "supabets", "sportingbet", "gbets", "world sports betting", "playabets", "supersportbet"]:
                        if bk in text_lower:
                            card_info["narrative_bookmaker"] = bk
                            break

                    print(f"    TEXT (first 600 chars):")
                    print(f"    {dmsg.text[:600]}")
                    print(f"    BUTTONS: {json.dumps(card_info['detail_buttons'], indent=4)}")
                    print(f"    Sections: Setup={card_info['has_setup_section']} Edge={card_info['has_edge_section']} Risk={card_info['has_risk_section']} Verdict={card_info['has_verdict_section']}")
                    if card_info["broadcast_line"]:
                        print(f"    Broadcast: {card_info['broadcast_line']}")
                    break

            results["hot_tips"]["cards"].append(card_info)

            # Navigate back
            await asyncio.sleep(2)
            # Try clicking "Back to Edge Picks" or similar
            for dmsg in reversed(detail_msgs):
                if dmsg.text and not dmsg.out:
                    back_msgs = await click_button_by_text(client, dmsg, "Edge Picks", wait=5)
                    if not back_msgs:
                        await click_button_by_text(client, dmsg, "Back", wait=5)
                    break
            await asyncio.sleep(1)

    else:
        print("WARNING: No Hot Tips message found!")

    # ── STEP 3: My Matches ───────────────────────────────
    print("\n\n" + "=" * 60)
    print("STEP 3: MY MATCHES")
    print("=" * 60)

    msgs = await send_and_capture(client, "⚽ My Matches", wait=15)

    mm_msg = None
    all_mm_text = []
    for msg in msgs:
        if msg.text and not msg.out:
            all_mm_text.append(msg.text)
            print(f"\n--- Bot message (id={msg.id}) ---")
            print(msg.text[:500])
            btns = extract_buttons(msg)
            if btns:
                print(f"  Buttons: {json.dumps(btns, indent=2)}")
            if "My Matches" in msg.text or "Matches" in msg.text:
                mm_msg = msg

    if mm_msg:
        results["my_matches"]["list_text"] = mm_msg.text
        results["my_matches"]["list_buttons"] = extract_buttons(mm_msg)

        # Check banned phrases
        for txt in all_mm_text:
            hits = check_banned_phrases(txt)
            if hits:
                results["banned_phrase_hits"].extend(
                    [{"location": "my_matches_list", "phrase": h} for h in hits]
                )

        # Find game buttons
        game_buttons = []
        for msg in msgs:
            if not msg.out:
                btns = extract_buttons(msg)
                for btn in btns:
                    if btn.get("type") == "callback":
                        data = btn.get("data", "")
                        if data.startswith("yg:game:") or data.startswith("edge:detail:"):
                            game_buttons.append((msg, btn))

        print(f"\nFound {len(game_buttons)} clickable game buttons.")

        # ── STEP 4: Open EVERY My Matches card ───────────
        print("\n" + "=" * 60)
        print("STEP 4: MY MATCHES DETAIL CARDS")
        print("=" * 60)

        for idx, (parent_msg, btn) in enumerate(game_buttons[:8]):  # Cap at 8 to avoid timeout
            print(f"\n--- Opening match {idx+1}/{min(len(game_buttons), 8)}: {btn['text']} ---")
            print(f"    Callback data: {btn['data']}")

            detail_msgs = await click_inline_button(
                client, parent_msg, btn["data"], wait=DETAIL_TIMEOUT
            )

            card_info = {
                "index": idx + 1,
                "button_text": btn["text"],
                "callback_data": btn["data"],
                "detail_text": "",
                "detail_buttons": [],
                "banned_hits": [],
                "has_setup_section": False,
                "has_edge_section": False,
                "has_risk_section": False,
                "has_verdict_section": False,
                "broadcast_line": "",
            }

            for dmsg in reversed(detail_msgs):
                if dmsg.text and not dmsg.out:
                    card_info["detail_text"] = dmsg.text
                    card_info["detail_buttons"] = extract_buttons(dmsg)
                    card_info["has_setup_section"] = "📋" in dmsg.text
                    card_info["has_edge_section"] = "🎯" in dmsg.text
                    card_info["has_risk_section"] = "⚠️" in dmsg.text
                    card_info["has_verdict_section"] = "🏆" in dmsg.text

                    if "📺" in dmsg.text or "DStv" in dmsg.text:
                        for line in dmsg.text.split("\n"):
                            if "📺" in line or "DStv" in line:
                                card_info["broadcast_line"] = line.strip()
                                break

                    hits = check_banned_phrases(dmsg.text)
                    card_info["banned_hits"] = hits
                    if hits:
                        results["banned_phrase_hits"].extend(
                            [{"location": f"my_matches_card_{idx+1}", "phrase": h} for h in hits]
                        )

                    print(f"    TEXT (first 600 chars):")
                    print(f"    {dmsg.text[:600]}")
                    print(f"    BUTTONS: {json.dumps(card_info['detail_buttons'], indent=4)}")
                    print(f"    Sections: Setup={card_info['has_setup_section']} Edge={card_info['has_edge_section']} Risk={card_info['has_risk_section']} Verdict={card_info['has_verdict_section']}")
                    break

            results["my_matches"]["cards"].append(card_info)

            # Navigate back
            await asyncio.sleep(2)
            for dmsg in reversed(detail_msgs):
                if dmsg.text and not dmsg.out:
                    back_msgs = await click_button_by_text(client, dmsg, "My Matches", wait=5)
                    if not back_msgs:
                        await click_button_by_text(client, dmsg, "Back", wait=5)
                    break
            await asyncio.sleep(1)

    else:
        print("WARNING: No My Matches message found!")

    # ── Save results ─────────────────────────────────────
    output_path = os.path.join(os.path.dirname(__file__), "..", "data", "qa_baseline_22_results.json")
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n\nResults saved to {output_path}")

    # ── Summary ──────────────────────────────────────────
    print("\n" + "=" * 60)
    print("QA-BASELINE-22 CAPTURE SUMMARY")
    print("=" * 60)
    print(f"Hot Tips cards captured: {len(results['hot_tips']['cards'])}")
    print(f"My Matches cards captured: {len(results['my_matches']['cards'])}")
    print(f"Banned phrase hits: {len(results['banned_phrase_hits'])}")
    if results["banned_phrase_hits"]:
        for h in results["banned_phrase_hits"]:
            print(f"  !! {h['location']}: '{h['phrase']}'")

    await client.disconnect()
    return results


if __name__ == "__main__":
    results = asyncio.run(run_qa())
