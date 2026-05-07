"""QA-BASELINE-24: Full Product Baseline After BUILD-QA23-FIX.

Telethon E2E capture — every card verbatim, every button, every CTA.
READ-ONLY test: captures bot output, scores nothing, modifies nothing.

Primary focus: P0-1 regression — away-win edge section must show outcome team, not home team.
Secondary: P0-2, P1-1, P1-2, consensus_prob fix verification.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
from datetime import datetime

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import (
    ReplyInlineMarkup,
    KeyboardButtonCallback,
    KeyboardButtonUrl,
)

# -- Configuration --
API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "")
BOT_USERNAME = "mzansiedge_bot"
SESSION_FILE = os.environ.get("TELETHON_SESSION", "data/telethon_qa_session")
STRING_SESSION_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "telethon_qa_session.string")

TIMEOUT = 15
DETAIL_TIMEOUT = 25


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
    entity = await client.get_entity(BOT_USERNAME)
    sent = await client.send_message(entity, text)
    sent_id = sent.id
    await asyncio.sleep(wait)
    messages = await client.get_messages(entity, limit=30)
    recent = [m for m in messages if m.id > sent_id and not m.out]
    return list(reversed(recent))


async def click_inline_button(client, msg, button_data_prefix, wait=TIMEOUT):
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


# -- BANNED PHRASES (QA Protocol v1.3 — 7 canonical) --
BANNED_PHRASES_V13 = [
    "statistical edge detected",
    "based on current form",
    "our algorithm suggests",
    "value opportunity identified",
    "edge detected in this market",
    "historical data indicates",
    "model confidence",
]

BANNED_PHRASES_LEGACY = [
    "the edge is carried by the pricing gap alone",
    "standard match-day variables apply",
    "no supporting indicators from any source",
    "no injury data was available",
    "limited data available for this match",
    "market data suggests",
    "based on available information",
]

ALL_BANNED = BANNED_PHRASES_V13 + BANNED_PHRASES_LEGACY


def check_banned_phrases(text: str) -> list[str]:
    if not text:
        return []
    lower = text.lower()
    return [p for p in ALL_BANNED if p in lower]


def extract_ev_pct(text: str) -> float | None:
    if not text:
        return None
    m = re.search(r'EV\s*([+-]?\d+\.?\d*)%', text)
    if m:
        return float(m.group(1))
    return None


# -- MAIN QA FLOW --

async def run_qa():
    results = {
        "timestamp": datetime.now().isoformat(),
        "qa_version": "QA-BASELINE-24",
        "hot_tips": {"list_text": "", "list_buttons": [], "cards": []},
        "my_matches": {"list_text": "", "list_buttons": [], "cards": []},
        "banned_phrase_hits": [],
        "regression_table": [],
    }

    client = await get_client()
    print("Connected to Telegram.\n")

    # == STEP 1: Hot Tips ==
    print("=" * 70)
    print("STEP 1: HOT TIPS (Top Edge Picks)")
    print("=" * 70)

    msgs = await send_and_capture(client, "\U0001f48e Top Edge Picks", wait=20)

    ht_msg = None
    all_ht_text = []
    all_ht_msgs = []
    for msg in msgs:
        if msg.text and not msg.out:
            all_ht_text.append(msg.text)
            all_ht_msgs.append(msg)
            print(f"\n--- Bot message (id={msg.id}) ---")
            print(msg.text[:1200])
            btns = extract_buttons(msg)
            if btns:
                print(f"  Buttons: {json.dumps(btns, indent=2)}")
            if ("Edge" in msg.text or "edge" in msg.text or "Live" in msg.text
                    or "Pick" in msg.text or "pick" in msg.text) and not msg.out:
                ht_msg = msg

    if ht_msg:
        results["hot_tips"]["list_text"] = ht_msg.text
        results["hot_tips"]["list_buttons"] = extract_buttons(ht_msg)

        for txt in all_ht_text:
            hits = check_banned_phrases(txt)
            if hits:
                results["banned_phrase_hits"].extend(
                    [{"location": "hot_tips_list", "phrase": h} for h in hits]
                )

        # Find ALL tip detail buttons
        tip_buttons = []
        for msg in all_ht_msgs:
            if not msg.out:
                btns = extract_buttons(msg)
                for btn in btns:
                    if btn.get("type") == "callback":
                        data = btn.get("data", "")
                        if data.startswith("edge:detail:"):
                            tip_buttons.append((msg, btn))

        print(f"\nFound {len(tip_buttons)} clickable tip detail buttons.")

        # == STEP 2: Open EVERY Hot Tips card ==
        print("\n" + "=" * 70)
        print("STEP 2: HOT TIPS DETAIL CARDS")
        print("=" * 70)

        for idx, (parent_msg, btn) in enumerate(tip_buttons):
            print(f"\n{'~'*60}")
            print(f"CARD {idx+1}/{len(tip_buttons)}: {btn['text']}")
            print(f"Callback: {btn['data']}")
            print(f"{'~'*60}")

            detail_msgs = await click_inline_button(
                client, parent_msg, btn["data"], wait=DETAIL_TIMEOUT
            )

            card = {
                "index": idx + 1,
                "button_text": btn["text"],
                "callback_data": btn["data"],
                "list_broadcast": "",
                "detail_text": "",
                "detail_buttons": [],
                "detail_broadcast": "",
                "banned_hits": [],
                "ev_pct": None,
                "has_back_cta": False,
                "has_setup": False,
                "has_edge": False,
                "has_risk": False,
                "has_verdict": False,
                "edge_team_mentioned": "",
                "cta_bookmaker_btn": "",
                "cta_odds_btn": "",
                "narrative_bookmaker": "",
            }

            # Extract list broadcast from parent message
            if parent_msg.text:
                for line in parent_msg.text.split("\n"):
                    if "\U0001f4fa" in line or "DStv" in line:
                        card["list_broadcast"] = line.strip()
                        break

            # Get the detail view message
            for dmsg in reversed(detail_msgs):
                if dmsg.text and not dmsg.out:
                    card["detail_text"] = dmsg.text
                    card["detail_buttons"] = extract_buttons(dmsg)

                    card["has_setup"] = "\U0001f4cb" in dmsg.text
                    card["has_edge"] = "\U0001f3af" in dmsg.text
                    card["has_risk"] = "\u26a0\ufe0f" in dmsg.text
                    card["has_verdict"] = "\U0001f3c6" in dmsg.text

                    for line in dmsg.text.split("\n"):
                        if "\U0001f4fa" in line or "DStv" in line:
                            card["detail_broadcast"] = line.strip()
                            break

                    card["ev_pct"] = extract_ev_pct(dmsg.text)

                    for b in card["detail_buttons"]:
                        btn_text = b.get("text", "")
                        if b.get("type") == "url":
                            if "Back" in btn_text or "@" in btn_text or "Bet" in btn_text:
                                card["has_back_cta"] = True
                                card["cta_bookmaker_btn"] = btn_text
                        elif b.get("type") == "callback":
                            if btn_text.startswith(("\U0001f48e", "\U0001f947", "\U0001f948", "\U0001f949")):
                                if "Back" in btn_text or "@" in btn_text:
                                    card["has_back_cta"] = True
                                    card["cta_bookmaker_btn"] = btn_text

                    text_lower = dmsg.text.lower()
                    for bk in ["hollywoodbets", "betway", "supabets", "sportingbet",
                               "gbets", "world sports betting", "playabets", "supersportbet"]:
                        if bk in text_lower:
                            card["narrative_bookmaker"] = bk
                            break

                    hits = check_banned_phrases(dmsg.text)
                    card["banned_hits"] = hits
                    if hits:
                        results["banned_phrase_hits"].extend(
                            [{"location": f"hot_tips_card_{idx+1}", "phrase": h} for h in hits]
                        )

                    print(f"\n=== VERBATIM DETAIL TEXT ===")
                    print(dmsg.text)
                    print(f"=== END VERBATIM ===\n")
                    print(f"BUTTONS: {json.dumps(card['detail_buttons'], indent=2)}")
                    print(f"Sections: Setup={card['has_setup']} Edge={card['has_edge']} "
                          f"Risk={card['has_risk']} Verdict={card['has_verdict']}")
                    print(f"EV: {card['ev_pct']}%  Back CTA: {card['has_back_cta']}")
                    if card["detail_broadcast"]:
                        print(f"Broadcast: {card['detail_broadcast']}")
                    break

            results["hot_tips"]["cards"].append(card)

            # Navigate back
            await asyncio.sleep(2)
            for dmsg in reversed(detail_msgs):
                if dmsg.text and not dmsg.out:
                    back_msgs = await click_button_by_text(client, dmsg, "Edge Picks", wait=5)
                    if not back_msgs:
                        await click_button_by_text(client, dmsg, "Back", wait=5)
                    break
            await asyncio.sleep(1)

    else:
        print("WARNING: No Hot Tips message found!")

    # == STEP 3: Check for page 2 ==
    print("\n" + "=" * 70)
    print("STEP 3: HOT TIPS PAGE 2 CHECK")
    print("=" * 70)

    page2_buttons = []
    for msg in all_ht_msgs:
        btns = extract_buttons(msg)
        for btn in btns:
            if btn.get("data", "").startswith("hot:page:"):
                page2_buttons.append((msg, btn))

    if page2_buttons:
        print(f"Found {len(page2_buttons)} page navigation buttons. Opening page 2...")
        p2_parent, p2_btn = page2_buttons[0]
        p2_msgs = await click_inline_button(client, p2_parent, p2_btn["data"], wait=15)

        for p2msg in reversed(p2_msgs):
            if p2msg.text and not p2msg.out:
                print(f"\n--- Page 2 message ---")
                print(p2msg.text[:1500])
                p2btns = extract_buttons(p2msg)
                print(f"Buttons: {json.dumps(p2btns, indent=2)}")

                # Click each edge:detail button on page 2
                for p2btn in p2btns:
                    if p2btn.get("data", "").startswith("edge:detail:"):
                        print(f"\n{'~'*60}")
                        print(f"PAGE 2 CARD: {p2btn['text']} -> {p2btn['data']}")
                        try:
                            await p2msg.click(data=p2btn["data"].encode())
                            await asyncio.sleep(DETAIL_TIMEOUT)
                            det_msgs = await client.get_messages(await client.get_entity(BOT_USERNAME), limit=15)
                            for dm in reversed(det_msgs):
                                if dm.text and not dm.out:
                                    card = {
                                        "index": len(results["hot_tips"]["cards"]) + 1,
                                        "button_text": p2btn["text"],
                                        "callback_data": p2btn["data"],
                                        "list_broadcast": "",
                                        "detail_text": dm.text,
                                        "detail_buttons": extract_buttons(dm),
                                        "detail_broadcast": "",
                                        "banned_hits": check_banned_phrases(dm.text),
                                        "ev_pct": extract_ev_pct(dm.text),
                                        "has_back_cta": False,
                                        "has_setup": "\U0001f4cb" in dm.text,
                                        "has_edge": "\U0001f3af" in dm.text,
                                        "has_risk": "\u26a0\ufe0f" in dm.text,
                                        "has_verdict": "\U0001f3c6" in dm.text,
                                        "edge_team_mentioned": "",
                                        "cta_bookmaker_btn": "",
                                        "cta_odds_btn": "",
                                        "narrative_bookmaker": "",
                                    }
                                    if card["banned_hits"]:
                                        results["banned_phrase_hits"].extend(
                                            [{"location": f"hot_tips_p2_card", "phrase": h} for h in card["banned_hits"]]
                                        )
                                    results["hot_tips"]["cards"].append(card)

                                    print(f"\n=== VERBATIM DETAIL TEXT ===")
                                    print(dm.text)
                                    print(f"=== END VERBATIM ===")
                                    print(f"BUTTONS: {json.dumps(card['detail_buttons'], indent=2)}")

                                    # Go back
                                    await asyncio.sleep(2)
                                    back_done = False
                                    if dm.reply_markup:
                                        for row in dm.reply_markup.rows:
                                            for b in row.buttons:
                                                if hasattr(b, "text") and "Edge Picks" in b.text and isinstance(b, KeyboardButtonCallback):
                                                    await dm.click(data=b.data)
                                                    await asyncio.sleep(5)
                                                    back_done = True
                                                    break
                                            if back_done:
                                                break
                                    if not back_done and dm.reply_markup:
                                        for row in dm.reply_markup.rows:
                                            for b in row.buttons:
                                                if hasattr(b, "text") and "Back" in b.text and isinstance(b, KeyboardButtonCallback):
                                                    await dm.click(data=b.data)
                                                    await asyncio.sleep(5)
                                                    break
                                    break
                        except Exception as p2_err:
                            print(f"  Page 2 card click error: {p2_err}")
                            continue
                break
    else:
        print("No page 2 navigation found.")

    # == STEP 4: My Matches ==
    print("\n\n" + "=" * 70)
    print("STEP 4: MY MATCHES")
    print("=" * 70)

    msgs = await send_and_capture(client, "\u26bd My Matches", wait=15)

    mm_msg = None
    all_mm_text = []
    all_mm_msgs = []
    for msg in msgs:
        if msg.text and not msg.out:
            all_mm_text.append(msg.text)
            all_mm_msgs.append(msg)
            print(f"\n--- Bot message (id={msg.id}) ---")
            print(msg.text[:1200])
            btns = extract_buttons(msg)
            if btns:
                print(f"  Buttons: {json.dumps(btns, indent=2)}")
            if "Match" in msg.text or "match" in msg.text or "Games" in msg.text:
                mm_msg = msg

    if mm_msg:
        results["my_matches"]["list_text"] = mm_msg.text
        results["my_matches"]["list_buttons"] = extract_buttons(mm_msg)

        for txt in all_mm_text:
            hits = check_banned_phrases(txt)
            if hits:
                results["banned_phrase_hits"].extend(
                    [{"location": "my_matches_list", "phrase": h} for h in hits]
                )

        game_buttons = []
        for msg in all_mm_msgs:
            if not msg.out:
                btns = extract_buttons(msg)
                for btn in btns:
                    if btn.get("type") == "callback":
                        data = btn.get("data", "")
                        if data.startswith("yg:game:") or data.startswith("edge:detail:"):
                            game_buttons.append((msg, btn))

        print(f"\nFound {len(game_buttons)} clickable game buttons.")

        # == STEP 5: Open up to 8 My Matches cards ==
        print("\n" + "=" * 70)
        print("STEP 5: MY MATCHES DETAIL CARDS")
        print("=" * 70)

        for idx, (parent_msg, btn) in enumerate(game_buttons[:8]):
            print(f"\n{'~'*60}")
            print(f"MATCH {idx+1}/{min(len(game_buttons), 8)}: {btn['text']}")
            print(f"Callback: {btn['data']}")
            print(f"{'~'*60}")

            detail_msgs = await click_inline_button(
                client, parent_msg, btn["data"], wait=DETAIL_TIMEOUT
            )

            card = {
                "index": idx + 1,
                "button_text": btn["text"],
                "callback_data": btn["data"],
                "detail_text": "",
                "detail_buttons": [],
                "banned_hits": [],
                "has_setup": False,
                "has_edge": False,
                "has_risk": False,
                "has_verdict": False,
                "broadcast_line": "",
            }

            for dmsg in reversed(detail_msgs):
                if dmsg.text and not dmsg.out:
                    card["detail_text"] = dmsg.text
                    card["detail_buttons"] = extract_buttons(dmsg)
                    card["has_setup"] = "\U0001f4cb" in dmsg.text
                    card["has_edge"] = "\U0001f3af" in dmsg.text
                    card["has_risk"] = "\u26a0\ufe0f" in dmsg.text
                    card["has_verdict"] = "\U0001f3c6" in dmsg.text

                    if "\U0001f4fa" in dmsg.text or "DStv" in dmsg.text:
                        for line in dmsg.text.split("\n"):
                            if "\U0001f4fa" in line or "DStv" in line:
                                card["broadcast_line"] = line.strip()
                                break

                    hits = check_banned_phrases(dmsg.text)
                    card["banned_hits"] = hits
                    if hits:
                        results["banned_phrase_hits"].extend(
                            [{"location": f"my_matches_card_{idx+1}", "phrase": h} for h in hits]
                        )

                    print(f"\n=== VERBATIM DETAIL TEXT ===")
                    print(dmsg.text)
                    print(f"=== END VERBATIM ===\n")
                    print(f"BUTTONS: {json.dumps(card['detail_buttons'], indent=2)}")
                    print(f"Sections: Setup={card['has_setup']} Edge={card['has_edge']} "
                          f"Risk={card['has_risk']} Verdict={card['has_verdict']}")
                    break

            results["my_matches"]["cards"].append(card)

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

    # == Save results ==
    output_path = os.path.join(os.path.dirname(__file__), "..", "data", "qa_baseline_24_results.json")
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n\nResults saved to {output_path}")

    # == Summary ==
    print("\n" + "=" * 70)
    print("QA-BASELINE-24 CAPTURE SUMMARY")
    print("=" * 70)
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
