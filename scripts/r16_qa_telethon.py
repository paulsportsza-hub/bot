#!/usr/bin/env python3
"""R16-QA-01: Opus Live Bot Scoring — Post EV/Tier Fix + Pregen Refresh.

Captures ALL live Edge cards via Telethon for formal 4-dimension scoring.
Stores raw text, buttons, list-view tier, detail-view tier, timings.
ALL scoring from LIVE BOT interaction — NOT database reads.

Scoring Rubric (LOCKED):
  Composite = (accuracy_avg * 0.25) + (richness_avg * 0.20) + (value_avg * 0.20) + (overall * 0.35)

Key checks (7.0 gate attempt #2):
  - EV consistency: list EV vs detail EV — MUST be 8/8
  - Tier consistency: list tier vs detail tier — MUST be 8/8
  - Outcome consistency: list outcome vs detail outcome
  - Enrichment rate: genuinely enriched / total — target >75%
  - Hallucination check
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import re
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import (
    ReplyInlineMarkup,
    KeyboardButtonCallback,
    KeyboardButtonUrl,
)

API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "")
BOT_USERNAME = "mzansiedge_bot"
STRING_SESSION_FILE = Path(__file__).resolve().parent.parent / "data" / "telethon_session.string"
FILE_SESSION = Path(__file__).resolve().parent.parent / "data" / "telethon_session"
from config import BOT_ROOT
RAW_CAPTURES_FILE = BOT_ROOT.parent / "reports" / "r16-qa-01-raw-captures.txt"
OUTPUT_DIR = BOT_ROOT.parent / "reports" / "r16-qa-captures"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

TIER_EMOJIS = {"\U0001f48e": "diamond", "\U0001f947": "gold", "\U0001f948": "silver", "\U0001f949": "bronze"}


async def get_client() -> TelegramClient:
    if STRING_SESSION_FILE.exists():
        s = STRING_SESSION_FILE.read_text().strip()
        if s:
            c = TelegramClient(StringSession(s), API_ID, API_HASH)
            await c.connect()
            if await c.is_user_authorized():
                return c
            await c.disconnect()
    c = TelegramClient(str(FILE_SESSION), API_ID, API_HASH)
    await c.connect()
    if not await c.is_user_authorized():
        print("ERROR: Not logged in"); sys.exit(1)
    return c


def get_text(msg) -> str:
    return msg.message or msg.text or ""


def get_buttons(msg):
    cb, url = [], []
    if not msg.reply_markup or not isinstance(msg.reply_markup, ReplyInlineMarkup):
        return cb, url
    for row in msg.reply_markup.rows:
        for btn in row.buttons:
            if isinstance(btn, KeyboardButtonCallback):
                d = btn.data.decode("utf-8", errors="replace") if isinstance(btn.data, bytes) else str(btn.data)
                cb.append({"text": btn.text, "data": d})
            elif isinstance(btn, KeyboardButtonUrl):
                url.append({"text": btn.text, "url": btn.url})
    return cb, url


def extract_list_tier(btn_text: str) -> str:
    for emoji, tier in TIER_EMOJIS.items():
        if emoji in btn_text:
            return tier
    if "\U0001f512" in btn_text:
        return "locked"
    return "unknown"


def extract_detail_tier(text: str, cb_buttons: list, url_buttons: list) -> str:
    # Check URL buttons first (CTA buttons have tier emoji)
    for btn in url_buttons:
        for emoji, tier in TIER_EMOJIS.items():
            if emoji in btn.get("text", ""):
                return tier
    # Check callback buttons
    for btn in cb_buttons:
        for emoji, tier in TIER_EMOJIS.items():
            if emoji in btn.get("text", ""):
                return tier
    # Check text body
    for emoji, tier in TIER_EMOJIS.items():
        if emoji in text:
            return tier
    return "unknown"


def extract_list_outcome(btn_text: str) -> str:
    clean = btn_text.strip()
    for emoji in TIER_EMOJIS:
        clean = clean.replace(emoji, "").strip()
    clean = clean.replace("\U0001f512", "").strip()
    return clean


def extract_detail_outcome(text: str) -> str:
    outcome_match = re.search(r'(?:Back|Bet on|Recommended?:?)\s+(.+?)\s+@', text, re.I)
    if outcome_match:
        return outcome_match.group(1).strip()
    verdict_match = re.search(r'\U0001f3c6.*?(?:Back|back)\s+(.+?)(?:\.|,|\n|$)', text, re.I)
    if verdict_match:
        return verdict_match.group(1).strip()
    return ""


def extract_detail_ev(text: str) -> str:
    ev_match = re.search(r'EV[:\s]*\+?([\d.]+)%', text)
    if ev_match:
        return f"+{ev_match.group(1)}%"
    return ""


def extract_list_ev_for_card(page_text: str, card_index_str: str) -> str:
    """Extract EV from the page text near a card's line."""
    lines = page_text.split("\n")
    for li, line in enumerate(lines):
        if f"[{card_index_str}]" in line:
            for j in range(li, min(li + 5, len(lines))):
                ev_m = re.search(r'EV\s*\+?([\d.]+)%', lines[j])
                if ev_m:
                    return f"+{ev_m.group(1)}%"
            break
    return ""


def extract_list_outcome_for_card(page_text: str, card_index_str: str) -> str:
    """Extract outcome from the money line near a card."""
    lines = page_text.split("\n")
    for li, line in enumerate(lines):
        if f"[{card_index_str}]" in line:
            for j in range(li, min(li + 5, len(lines))):
                outcome_m = re.search(r'\U0001f4b0\s*(.*?)\s+@', lines[j])
                if outcome_m:
                    return outcome_m.group(1).strip()
            break
    return ""


def analyse_card(text: str, cb_buttons: list, url_buttons: list) -> dict:
    analysis = {
        "has_setup": "\U0001f4cb" in text or "The Setup" in text,
        "has_edge": "\U0001f3af" in text and "Edge" in text.lower(),
        "has_risk": "\u26a0\ufe0f" in text or "The Risk" in text,
        "has_verdict": "\U0001f3c6" in text or "Verdict" in text,
        "section_count": 0,
        "ev_pct": None,
        "fair_prob_pct": None,
        "has_kickoff": "\U0001f4c5" in text or bool(re.search(r'\d{1,2}:\d{2}', text)),
        "has_broadcast": "\U0001f4fa" in text or "DStv" in text,
        "has_league": "\U0001f3c6" in text,
        "has_compare_odds": False,
        "has_multiple_bookmakers": False,
        "bookmakers_in_detail": [],
        "cta_bookmaker_text": None,
        "cta_url": None,
        "is_locked": "\U0001f512" in text and ("Available on" in text or "Unlock" in text),
        "is_w84_enriched": False,
        "is_w82_template": False,
        "has_real_match_data": False,
        "claimed_facts": [],
        "staking_language": None,
        "detail_outcome": "",
        "detail_ev": "",
    }

    for s in ["\U0001f4cb", "\U0001f3af", "\u26a0\ufe0f", "\U0001f3c6"]:
        if s in text:
            analysis["section_count"] += 1

    ev_match = re.search(r'EV[:\s]*\+?([\d.]+)%', text)
    if ev_match:
        analysis["ev_pct"] = float(ev_match.group(1))

    prob_match = re.search(r'(\d+)%\s*\u00b7\s*EV', text)
    if prob_match:
        analysis["fair_prob_pct"] = int(prob_match.group(1))

    for btn in cb_buttons:
        if "Compare" in btn.get("text", "") or "compare" in btn.get("data", ""):
            analysis["has_compare_odds"] = True
            break

    bk_names = ["hollywoodbets", "betway", "supabets", "sportingbet", "gbets",
                "world sports betting", "wsb", "supersportbet", "playabets"]
    found_bks = []
    for bk in bk_names:
        if bk.lower() in text.lower():
            found_bks.append(bk)
    analysis["bookmakers_in_detail"] = found_bks
    analysis["has_multiple_bookmakers"] = len(found_bks) >= 2

    for btn in url_buttons:
        t = btn.get("text", "")
        if any(x in t.lower() for x in ["back", "bet on", "\u2192"]):
            analysis["cta_bookmaker_text"] = t
            analysis["cta_url"] = btn.get("url", "")
            break

    w84_indicators = [
        re.search(r'(form|recent results?).*[WDLNR]{2,}', text, re.I),
        re.search(r'(\d+)(st|nd|rd|th)\s+(in|place|position|on)', text, re.I),
        re.search(r'(coach|manager|head coach|under)\s*[:\s]*\w+', text, re.I),
        re.search(r'Elo\s*(rating)?[:\s]*\d+', text, re.I),
        re.search(r'(points?|pts)\s*[:\s]*\d+', text, re.I),
        re.search(r'\d+\s*(wins?|losses?|draws?)', text, re.I),
        re.search(r'(H2H|head.to.head|meetings?)', text, re.I),
        re.search(r'goals?\s*(per|/)\s*game', text, re.I),
        re.search(r'(last\s+\d+|recent\s+\d+)', text, re.I),
        re.search(r'(clean sheets?|conceded)', text, re.I),
        re.search(r'(position|placed?)\s+(1st|2nd|3rd|\d+th)', text, re.I),
        re.search(r'W\d+\s*D\d+\s*L\d+', text, re.I),
        re.search(r'[WDLNR]{3,5}\b', text),
    ]
    w84_count = sum(1 for ind in w84_indicators if ind)
    analysis["is_w84_enriched"] = w84_count >= 2
    analysis["w84_indicator_count"] = w84_count

    w82_indicators = [
        "price is doing most of the work" in text.lower(),
        "limited pre-match context" in text.lower(),
        "numbers-only play" in text.lower(),
        "form data isn't available" in text.lower(),
        "no data available" in text.lower(),
        "pure pricing" in text.lower(),
    ]
    analysis["is_w82_template"] = any(w82_indicators)

    facts = []
    for fm in re.finditer(r'(form|results?).*?([WDLNR]{3,})', text, re.I):
        facts.append({"type": "form", "claim": fm.group(0)})
    for pm in re.finditer(r'(\d+)(st|nd|rd|th)\s+(in|place|position|on)', text, re.I):
        facts.append({"type": "position", "claim": pm.group(0)})
    for hm in re.finditer(r'(H2H|head.to.head|meetings?).*?(\d+\s*(wins?|from|of))', text, re.I):
        facts.append({"type": "h2h", "claim": hm.group(0)})
    for em in re.finditer(r'Elo.*?(\d{3,4})', text, re.I):
        facts.append({"type": "elo", "claim": em.group(0)})
    for cm in re.finditer(r'(coach|manager|under)\s+(\w+\s*\w*)', text, re.I):
        facts.append({"type": "coach", "claim": cm.group(0)})
    analysis["claimed_facts"] = facts
    analysis["has_real_match_data"] = len(facts) >= 2

    staking_match = re.search(r'(Small stake|Tiny exposure|Minimal exposure|measured.exposure|'
                               r'normal sizing|confident|back this|strong|conviction|'
                               r'speculative|monitor|pass)', text, re.I)
    if staking_match:
        analysis["staking_language"] = staking_match.group(0)

    analysis["detail_outcome"] = extract_detail_outcome(text)
    analysis["detail_ev"] = extract_detail_ev(text)

    return analysis


async def navigate_to_picks(client, entity, page: int = 0) -> tuple:
    await client.send_message(entity, "\U0001f48e Top Edge Picks")
    await asyncio.sleep(15)

    msgs = await client.get_messages(entity, limit=10)
    target = None
    for m in msgs:
        if getattr(m, 'sender_id', None) == entity.id:
            t = get_text(m)
            if "Edge Picks" in t or "Live Edges" in t or "Scanned" in t or "Predicted" in t:
                target = m
                break
    if not target:
        for m in msgs:
            if getattr(m, 'sender_id', None) == entity.id:
                target = m
                break
    if not target:
        return None, "", [], []

    if page > 0:
        cb, _ = get_buttons(target)
        for btn in cb:
            if btn["data"] == f"hot:page:{page}":
                await target.click(data=btn["data"].encode())
                await asyncio.sleep(8)
                msgs = await client.get_messages(entity, limit=10)
                for m in msgs:
                    if getattr(m, 'sender_id', None) == entity.id:
                        t = get_text(m)
                        if "vs" in t or "Edge" in t:
                            target = m
                            break
                break

    text = get_text(target)
    cb, url = get_buttons(target)
    return target, text, cb, url


async def click_detail_and_capture(client, entity, list_msg, btn_data: str) -> dict:
    result = {"detail_text": "", "detail_cb_buttons": [], "detail_url_buttons": [],
              "load_time": 0, "error": None}
    t0 = time.time()
    try:
        await list_msg.click(data=btn_data.encode("utf-8") if isinstance(btn_data, str) else btn_data)
        await asyncio.sleep(15)
        result["load_time"] = time.time() - t0

        msgs = await client.get_messages(entity, limit=10)
        for m in msgs:
            if getattr(m, 'sender_id', None) == entity.id:
                t = get_text(m)
                if any(x in t for x in ["\U0001f4cb ", "\U0001f3c6 Verdict", "The Setup", "\U0001f512", "\U0001f4cb", "\U0001f3c6"]):
                    result["detail_text"] = t
                    cb, url = get_buttons(m)
                    result["detail_cb_buttons"] = cb
                    result["detail_url_buttons"] = url
                    break
                if re.search(r'\U0001f3af\s+\S+.*vs\s+\S+', t):
                    result["detail_text"] = t
                    cb, url = get_buttons(m)
                    result["detail_cb_buttons"] = cb
                    result["detail_url_buttons"] = url
                    break

        if not result["detail_text"]:
            for m in msgs:
                if getattr(m, 'sender_id', None) == entity.id:
                    t = get_text(m)
                    if "Edge Picks" not in t and "Live Edges" not in t and len(t) > 80:
                        result["detail_text"] = t
                        cb, url = get_buttons(m)
                        result["detail_cb_buttons"] = cb
                        result["detail_url_buttons"] = url
                        break
    except Exception as e:
        result["error"] = str(e)
        result["load_time"] = time.time() - t0
    return result


async def main():
    print("=" * 70)
    print("R16-QA-01: Opus Live Bot Scoring — Post EV/Tier Fix + Pregen Refresh")
    print(f"Date: {datetime.now().isoformat()}")
    print(f"Method: LIVE BOT INTERACTION via Telethon — NOT database reads")
    print(f"Model: Opus — 04 QA Surface A")
    print("=" * 70)

    raw_captures = []

    print("\n[CONNECT] Connecting to Telegram...")
    t0 = time.time()
    client = await get_client()
    me = await client.get_me()
    conn_time = time.time() - t0
    entity = await client.get_entity(BOT_USERNAME)
    print(f"  Connected as {me.first_name} (@{me.username}) in {conn_time:.1f}s")
    print(f"  Bot: @{BOT_USERNAME} (ID: {entity.id})")

    output = {
        "timestamp": datetime.now().isoformat(),
        "wave": "R16-QA-01",
        "qa_method": "Telethon live bot interaction",
        "model": "Opus — 04 QA Surface A",
        "connection": {"user": me.first_name, "username": me.username,
                       "user_id": me.id, "time": conn_time, "bot_id": entity.id},
        "pages": [],
        "cards": [],
    }

    # Step 1: Send /start
    print("\n[START] Sending /start...")
    await client.send_message(entity, "/start")
    await asyncio.sleep(5)
    start_msgs = await client.get_messages(entity, limit=5)
    start_response = ""
    for m in start_msgs:
        if getattr(m, 'sender_id', None) == entity.id:
            start_response = get_text(m)
            break
    print(f"  /start response: {len(start_response)} chars")
    output["start_response"] = start_response
    raw_captures.append(f"{'='*70}\n/start RESPONSE\n{'='*70}\n{start_response}\n")

    # Step 1.5: Set QA tier to Diamond for full access
    print("\n[QA] Setting tier to Diamond for QA access...")
    await client.send_message(entity, "/qa set_diamond")
    await asyncio.sleep(5)
    qa_msgs = await client.get_messages(entity, limit=5)
    qa_response = ""
    for m in qa_msgs:
        if getattr(m, 'sender_id', None) == entity.id:
            qa_response = get_text(m)
            break
    print(f"  QA response: {qa_response[:100]}")
    raw_captures.append(f"\n{'='*70}\n/qa set_diamond RESPONSE\n{'='*70}\n{qa_response}\n")
    output["qa_tier_set"] = qa_response

    # Step 2: Collect all Edge Pick pages
    print("\n[LIST] Loading Top Edge Picks pages...")
    all_card_buttons = []
    page_texts = {}

    list_msg_p0, p0_text, p0_cb, p0_url = await navigate_to_picks(client, entity, page=0)
    if p0_text:
        page_texts[0] = p0_text
        raw_captures.append(f"\n{'='*70}\nPAGE 0 — TOP EDGE PICKS LIST (AS DIAMOND)\n{'='*70}\n{p0_text}\n")
        raw_captures.append(f"\nBUTTONS (callback):\n")
        for btn in p0_cb:
            raw_captures.append(f"  {btn['text']} -> data:{btn['data']}\n")
        raw_captures.append(f"BUTTONS (url):\n")
        for btn in p0_url:
            raw_captures.append(f"  {btn['text']} -> {btn['url']}\n")

        page_file = OUTPUT_DIR / "page0_raw.txt"
        page_file.write_text(p0_text)
        output["pages"].append({"page": 0, "text": p0_text, "buttons": p0_cb, "url_buttons": p0_url})

        # Collect both edge:detail: and hot:upgrade: buttons
        for btn in p0_cb:
            if btn["data"].startswith("edge:detail:") or btn["data"].startswith("hot:upgrade:"):
                list_tier = extract_list_tier(btn["text"])
                all_card_buttons.append((0, btn["text"], btn["data"], list_tier))

        card_count_p0 = len([b for b in p0_cb if b["data"].startswith("edge:detail:") or b["data"].startswith("hot:upgrade:")])
        print(f"  Page 0: {card_count_p0} cards")

        # Discover more pages
        page_buttons = sorted(
            [b for b in p0_cb if b["data"].startswith("hot:page:")],
            key=lambda b: int(b["data"].split(":")[-1])
        )
        discovered_pages = set()
        for pb in page_buttons:
            pnum = int(pb["data"].split(":")[-1])
            if pnum > 0 and pnum not in discovered_pages:
                discovered_pages.add(pnum)
                print(f"  Navigating to page {pnum}...")
                _, pn_text, pn_cb, pn_url = await navigate_to_picks(client, entity, page=pnum)
                if pn_text:
                    page_texts[pnum] = pn_text
                    raw_captures.append(f"\n{'='*70}\nPAGE {pnum} — TOP EDGE PICKS LIST (AS DIAMOND)\n{'='*70}\n{pn_text}\n")
                    raw_captures.append(f"\nBUTTONS (callback):\n")
                    for btn in pn_cb:
                        raw_captures.append(f"  {btn['text']} -> data:{btn['data']}\n")

                    pf = OUTPUT_DIR / f"page{pnum}_raw.txt"
                    pf.write_text(pn_text)
                    output["pages"].append({"page": pnum, "text": pn_text, "buttons": pn_cb, "url_buttons": pn_url})

                    for btn in pn_cb:
                        if btn["data"].startswith("edge:detail:") or btn["data"].startswith("hot:upgrade:"):
                            lt = extract_list_tier(btn["text"])
                            all_card_buttons.append((pnum, btn["text"], btn["data"], lt))
                    cc = len([b for b in pn_cb if b["data"].startswith("edge:detail:") or b["data"].startswith("hot:upgrade:")])
                    print(f"  Page {pnum}: {cc} cards")

                    more = [b for b in pn_cb if b["data"].startswith("hot:page:")]
                    for mp in more:
                        mn = int(mp["data"].split(":")[-1])
                        if mn > pnum and mn not in discovered_pages:
                            discovered_pages.add(mn)
                            print(f"  Navigating to page {mn}...")
                            _, mn_text, mn_cb, mn_url = await navigate_to_picks(client, entity, page=mn)
                            if mn_text:
                                page_texts[mn] = mn_text
                                raw_captures.append(f"\n{'='*70}\nPAGE {mn} — TOP EDGE PICKS LIST (AS DIAMOND)\n{'='*70}\n{mn_text}\n")
                                raw_captures.append(f"\nBUTTONS (callback):\n")
                                for btn in mn_cb:
                                    raw_captures.append(f"  {btn['text']} -> data:{btn['data']}\n")
                                mf = OUTPUT_DIR / f"page{mn}_raw.txt"
                                mf.write_text(mn_text)
                                output["pages"].append({"page": mn, "text": mn_text, "buttons": mn_cb, "url_buttons": mn_url})
                                for btn in mn_cb:
                                    if btn["data"].startswith("edge:detail:") or btn["data"].startswith("hot:upgrade:"):
                                        lt2 = extract_list_tier(btn["text"])
                                        all_card_buttons.append((mn, btn["text"], btn["data"], lt2))
                                cc2 = len([b for b in mn_cb if b["data"].startswith("edge:detail:") or b["data"].startswith("hot:upgrade:")])
                                print(f"  Page {mn}: {cc2} cards")

    total_cards = len(all_card_buttons)
    print(f"\n  Total cards across all pages: {total_cards}")

    # Step 3: Tap each card for detail view
    print("\n[DETAILS] Tapping each card for detail view...")
    for i, (page_num, btn_text, btn_data, list_tier) in enumerate(all_card_buttons, 1):
        print(f"\n  Card {i}/{total_cards}: {btn_text} (list tier: {list_tier})")
        # Extract match_key from either edge:detail: or hot:upgrade: prefix
        if btn_data.startswith("edge:detail:"):
            match_key = btn_data.replace("edge:detail:", "")
        elif btn_data.startswith("hot:upgrade:"):
            match_key = btn_data.replace("hot:upgrade:", "")
        else:
            match_key = btn_data

        list_outcome = extract_list_outcome(btn_text)

        # Extract card number from button text like "[1] ⚽ PAR v LIV 🔒"
        card_num_match = re.search(r'\[(\d+)\]', btn_text)
        card_num_str = card_num_match.group(1) if card_num_match else str(i)

        page_text = page_texts.get(page_num, "")
        list_ev = extract_list_ev_for_card(page_text, card_num_str)
        list_outcome_from_page = extract_list_outcome_for_card(page_text, card_num_str)
        if list_outcome_from_page:
            list_outcome = list_outcome_from_page

        # Navigate back to list and click detail
        list_msg, _, _, _ = await navigate_to_picks(client, entity, page=page_num)
        if not list_msg:
            print("    ERROR: Could not navigate to list page")
            output["cards"].append({
                "index": i, "button_text": btn_text, "match_key": match_key,
                "page": page_num, "list_tier": list_tier, "error": "Could not navigate to list",
            })
            continue

        detail = await click_detail_and_capture(client, entity, list_msg, btn_data)
        text = detail["detail_text"]
        detail_tier = extract_detail_tier(text, detail["detail_cb_buttons"], detail["detail_url_buttons"])
        qa = analyse_card(text, detail["detail_cb_buttons"], detail["detail_url_buttons"])

        # Store COMPLETE raw text
        raw_captures.append(f"\n{'='*70}\nCARD {i}/{total_cards}: {btn_text}\n")
        raw_captures.append(f"Match key: {match_key}\n")
        raw_captures.append(f"List tier: {list_tier}\n")
        raw_captures.append(f"Detail tier: {detail_tier}\n")
        raw_captures.append(f"List outcome: {list_outcome}\n")
        raw_captures.append(f"Detail outcome: {qa['detail_outcome']}\n")
        raw_captures.append(f"List EV: {list_ev}\n")
        raw_captures.append(f"Detail EV: {qa['detail_ev']}\n")
        raw_captures.append(f"Load time: {detail['load_time']:.1f}s\n")
        raw_captures.append(f"{'='*70}\n")
        raw_captures.append(f"FULL DETAIL TEXT:\n{text}\n")
        raw_captures.append(f"\nCALLBACK BUTTONS:\n")
        for b in detail["detail_cb_buttons"]:
            raw_captures.append(f"  {b['text']} -> data:{b['data']}\n")
        raw_captures.append(f"URL BUTTONS:\n")
        for b in detail["detail_url_buttons"]:
            raw_captures.append(f"  {b['text']} -> {b['url']}\n")

        card_data = {
            "index": i,
            "button_text": btn_text,
            "match_key": match_key,
            "page": page_num,
            "list_tier": list_tier,
            "detail_tier": detail_tier,
            "tier_match": list_tier == detail_tier,
            "list_outcome": list_outcome,
            "detail_outcome": qa["detail_outcome"],
            "list_ev": list_ev,
            "detail_ev": qa["detail_ev"],
            "detail_text": text,
            "detail_cb_buttons": detail["detail_cb_buttons"],
            "detail_url_buttons": detail["detail_url_buttons"],
            "load_time": detail["load_time"],
            "error": detail["error"],
            **qa,
        }

        home, away = "", ""
        tm = re.search(r'\U0001f3af\s*(.*?)\s+vs\s+(.*?)(?:\n|$)', text)
        if tm:
            home, away = tm.group(1).strip(), tm.group(2).strip()
        if home:
            card_data["home_team"] = home
        if away:
            card_data["away_team"] = away

        lm = re.search(r'\U0001f3c6\s*(.*?)(?:\n|$)', text)
        if lm:
            card_data["league"] = lm.group(1).strip()
        km = re.search(r'\U0001f4c5\s*(.*?)(?:\n|$)', text)
        if km:
            card_data["kickoff"] = km.group(1).strip()
        bm = re.search(r'\U0001f4fa\s*(.*?)(?:\n|$)', text)
        if bm:
            card_data["broadcast"] = bm.group(1).strip()

        card_file = OUTPUT_DIR / f"card{i}_raw.txt"
        card_file.write_text(
            f"=== CARD {i}: {btn_text} ===\n"
            f"Match key: {match_key}\n"
            f"List tier: {list_tier}\n"
            f"Detail tier: {detail_tier}\n"
            f"Tier match: {card_data['tier_match']}\n"
            f"List outcome: {list_outcome}\n"
            f"Detail outcome: {qa['detail_outcome']}\n"
            f"List EV: {list_ev}\n"
            f"Detail EV: {qa['detail_ev']}\n"
            f"Load time: {detail['load_time']:.1f}s\n"
            f"{'='*60}\n\n"
            f"{text}\n\n"
            f"{'='*60}\n"
            f"CALLBACK BUTTONS:\n"
            + "\n".join(f"  {b['text']} -> data:{b['data']}" for b in detail["detail_cb_buttons"])
            + "\n\nURL BUTTONS:\n"
            + "\n".join(f"  {b['text']} -> {b['url']}" for b in detail["detail_url_buttons"])
            + f"\n\nANALYSIS:\n{json.dumps(qa, indent=2, default=str)}"
        )

        home_display = card_data.get('home_team', '?')
        away_display = card_data.get('away_team', '?')
        print(f"    {home_display} vs {away_display}")
        print(f"    League: {card_data.get('league', '?')}")
        print(f"    Tier: list={list_tier} detail={detail_tier} match={card_data['tier_match']}")
        print(f"    Outcome: list='{list_outcome}' detail='{qa['detail_outcome']}'")
        print(f"    EV: list={list_ev} detail={qa['detail_ev']}")
        print(f"    Enriched: W84={qa['is_w84_enriched']} ({qa['w84_indicator_count']} indicators)")
        print(f"    Sections: {qa['section_count']}/4 (Setup={qa['has_setup']} Edge={qa['has_edge']} Risk={qa['has_risk']} Verdict={qa['has_verdict']})")
        print(f"    Header: kickoff={qa['has_kickoff']} broadcast={qa['has_broadcast']} league={qa['has_league']}")
        print(f"    Claimed facts: {len(qa['claimed_facts'])}")
        print(f"    Load: {detail['load_time']:.1f}s | Text: {len(text)} chars")

        output["cards"].append(card_data)

    # Step 4: Reset QA tier
    print("\n[QA] Resetting QA tier override...")
    await client.send_message(entity, "/qa reset")
    await asyncio.sleep(3)

    # Save full output JSON
    out_file = OUTPUT_DIR / "r16_qa_results.json"
    out_file.write_text(json.dumps(output, indent=2, ensure_ascii=False, default=str))

    # Save raw captures file
    RAW_CAPTURES_FILE.write_text("".join(raw_captures))

    print(f"\n{'='*70}")
    print(f"Capture complete. Cards captured: {len(output['cards'])}")
    print(f"Output JSON: {out_file}")
    print(f"Raw captures: {RAW_CAPTURES_FILE}")
    print(f"Individual cards: {OUTPUT_DIR}/")
    print(f"{'='*70}")

    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
