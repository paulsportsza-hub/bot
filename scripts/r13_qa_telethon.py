#!/usr/bin/env python3
"""R13-QA-01: Independent Live Bot QA via Telethon.

Captures ALL live Edge cards via Telethon for formal 3-dimension scoring.
Stores raw text, buttons, list-view tier, detail-view tier, timings.
ALL scoring from LIVE BOT interaction — NOT database reads.
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
OUTPUT_DIR = BOT_ROOT.parent / "reports" / "r13-qa-captures"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

TIER_EMOJIS = {"💎": "diamond", "🥇": "gold", "🥈": "silver", "🥉": "bronze"}


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
    if "🔒" in btn_text:
        return "locked"
    return "unknown"


def extract_detail_tier(text: str, cb_buttons: list, url_buttons: list) -> str:
    for btn in url_buttons:
        for emoji, tier in TIER_EMOJIS.items():
            if emoji in btn.get("text", ""):
                return tier
    for btn in cb_buttons:
        for emoji, tier in TIER_EMOJIS.items():
            if emoji in btn.get("text", ""):
                return tier
    for emoji, tier in TIER_EMOJIS.items():
        if emoji in text:
            return tier
    return "unknown"


async def navigate_to_picks(client, entity, page: int = 0) -> tuple:
    await client.send_message(entity, "💎 Top Edge Picks")
    await asyncio.sleep(15)

    msgs = await client.get_messages(entity, limit=10)
    target = None
    for m in msgs:
        if getattr(m, 'sender_id', None) == entity.id:
            t = get_text(m)
            if "Edge Picks" in t or "Live Edges" in t or "Scanned" in t:
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
                        if "[" in t and "vs" in t:
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
                if any(x in t for x in ["📋 ", "🏆 Verdict", "The Setup", "🔒"]):
                    result["detail_text"] = t
                    cb, url = get_buttons(m)
                    result["detail_cb_buttons"] = cb
                    result["detail_url_buttons"] = url
                    break
                if re.search(r'🎯\s+\S+.*vs\s+\S+', t):
                    result["detail_text"] = t
                    cb, url = get_buttons(m)
                    result["detail_cb_buttons"] = cb
                    result["detail_url_buttons"] = url
                    break

        if not result["detail_text"]:
            for m in msgs:
                if getattr(m, 'sender_id', None) == entity.id:
                    t = get_text(m)
                    if "Edge Picks" not in t and "Live Edges" not in t and len(t) > 100:
                        result["detail_text"] = t
                        cb, url = get_buttons(m)
                        result["detail_cb_buttons"] = cb
                        result["detail_url_buttons"] = url
                        break
    except Exception as e:
        result["error"] = str(e)
        result["load_time"] = time.time() - t0
    return result


def analyse_card(text: str, cb_buttons: list, url_buttons: list) -> dict:
    analysis = {
        "has_setup": "📋" in text or "The Setup" in text,
        "has_edge": "🎯" in text and "Edge" in text,
        "has_risk": "⚠️" in text or "The Risk" in text,
        "has_verdict": "🏆" in text or "Verdict" in text,
        "section_count": 0,
        "ev_pct": None,
        "fair_prob_pct": None,
        "has_kickoff": "📅" in text or bool(re.search(r'\d{1,2}:\d{2}', text)),
        "has_broadcast": "📺" in text or "DStv" in text,
        "has_league": "🏆" in text,
        "has_compare_odds": False,
        "has_multiple_bookmakers": False,
        "bookmakers_in_detail": [],
        "cta_bookmaker_text": None,
        "cta_url": None,
        "is_locked": "🔒" in text and ("Available on" in text or "Unlock" in text),
        "is_w84_enriched": False,
        "is_w82_template": False,
        "has_real_match_data": False,
        "claimed_facts": [],
        "staking_language": None,
    }

    # Count sections
    for s in ["📋", "🎯", "⚠️", "🏆"]:
        if s in text:
            analysis["section_count"] += 1

    # EV percentage
    ev_match = re.search(r'EV[:\s]*\+?([\d.]+)%', text)
    if ev_match:
        analysis["ev_pct"] = float(ev_match.group(1))

    # Fair probability
    prob_match = re.search(r'(\d+)%\s*·\s*EV', text)
    if prob_match:
        analysis["fair_prob_pct"] = int(prob_match.group(1))

    # Compare Odds button
    for btn in cb_buttons:
        if "Compare" in btn.get("text", "") or "compare" in btn.get("data", ""):
            analysis["has_compare_odds"] = True
            break

    # Multiple bookmakers in text
    bk_names = ["hollywoodbets", "betway", "supabets", "sportingbet", "gbets",
                "world sports betting", "wsb", "supersportbet", "playabets"]
    found_bks = []
    for bk in bk_names:
        if bk.lower() in text.lower():
            found_bks.append(bk)
    analysis["bookmakers_in_detail"] = found_bks
    analysis["has_multiple_bookmakers"] = len(found_bks) >= 2

    # CTA button
    for btn in url_buttons:
        t = btn.get("text", "")
        if any(x in t.lower() for x in ["back", "bet on", "→"]):
            analysis["cta_bookmaker_text"] = t
            analysis["cta_url"] = btn.get("url", "")
            break

    # Enrichment detection: W84 = real match data, W82 = template
    # W84 indicators: specific form strings, league positions, coach names, Elo
    w84_indicators = [
        re.search(r'(form|recent results?).*[WDLNR]{2,}', text, re.I),
        re.search(r'(\d+)(st|nd|rd|th)\s+(in|place|position)', text, re.I),
        re.search(r'(coach|manager|head coach)\s*[:\s]*\w+', text, re.I),
        re.search(r'Elo\s*(rating)?[:\s]*\d+', text, re.I),
        re.search(r'(points?|pts)\s*[:\s]*\d+', text, re.I),
        re.search(r'\d+\s*(wins?|losses?|draws?)', text, re.I),
        re.search(r'(H2H|head.to.head|meetings?)', text, re.I),
        re.search(r'goals?\s*(per|/)\s*game', text, re.I),
        re.search(r'(last\s+\d+|recent\s+\d+)', text, re.I),
        re.search(r'(clean sheets?|conceded)', text, re.I),
    ]
    w84_count = sum(1 for ind in w84_indicators if ind)
    analysis["is_w84_enriched"] = w84_count >= 2
    analysis["w84_indicator_count"] = w84_count

    # W82 template indicators
    w82_indicators = [
        "price is doing most of the work" in text.lower(),
        "limited pre-match context" in text.lower(),
        "numbers-only play" in text.lower(),
        "form data isn't available" in text.lower(),
        "no data available" in text.lower(),
        "pure pricing" in text.lower(),
    ]
    analysis["is_w82_template"] = any(w82_indicators)

    # Extract claimed facts for hallucination checking
    facts = []
    # Form strings
    for fm in re.finditer(r'(form|results?).*?([WDLNR]{3,})', text, re.I):
        facts.append({"type": "form", "claim": fm.group(0)})
    # League positions
    for pm in re.finditer(r'(\d+)(st|nd|rd|th)\s+(in|place|position|on)', text, re.I):
        facts.append({"type": "position", "claim": pm.group(0)})
    # H2H records
    for hm in re.finditer(r'(H2H|head.to.head|meetings?).*?(\d+\s*(wins?|from|of))', text, re.I):
        facts.append({"type": "h2h", "claim": hm.group(0)})
    # Elo ratings
    for em in re.finditer(r'Elo.*?(\d{3,4})', text, re.I):
        facts.append({"type": "elo", "claim": em.group(0)})
    # Coach names
    for cm in re.finditer(r'(coach|manager|under)\s+(\w+\s*\w*)', text, re.I):
        facts.append({"type": "coach", "claim": cm.group(0)})
    analysis["claimed_facts"] = facts
    analysis["has_real_match_data"] = len(facts) >= 2

    # Staking language
    staking_match = re.search(r'(Small stake|Tiny exposure|Minimal exposure|measured.exposure|'
                               r'normal sizing|confident|back this|strong|conviction|'
                               r'speculative|monitor|pass)', text, re.I)
    if staking_match:
        analysis["staking_language"] = staking_match.group(0)

    return analysis


async def main():
    print("=" * 60)
    print("R13-QA-01: Independent Live Bot QA via Telethon")
    print(f"Date: {datetime.now().isoformat()}")
    print(f"Method: LIVE BOT INTERACTION — NOT database reads")
    print("=" * 60)

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
        "wave": "R13-QA-01",
        "qa_method": "Telethon live bot interaction",
        "connection": {"user": me.first_name, "username": me.username,
                       "user_id": me.id, "time": conn_time, "bot_id": entity.id},
        "pages": [],
        "cards": [],
    }

    # Step 1: Send /start to verify bot responds
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
    output["start_response"] = start_response[:500]

    # Step 2: Collect all Edge Pick pages
    print("\n[LIST] Loading Top Edge Picks pages...")
    all_card_buttons = []

    list_msg_p0, p0_text, p0_cb, p0_url = await navigate_to_picks(client, entity, page=0)
    if p0_text:
        page_file = OUTPUT_DIR / "page0_raw.txt"
        page_file.write_text(p0_text)
        output["pages"].append({"page": 0, "text": p0_text, "buttons": p0_cb, "url_buttons": p0_url})
        for btn in p0_cb:
            if btn["data"].startswith("edge:detail:"):
                list_tier = extract_list_tier(btn["text"])
                all_card_buttons.append((0, btn["text"], btn["data"], list_tier))
        card_count_p0 = len([b for b in p0_cb if b["data"].startswith("edge:detail:")])
        print(f"  Page 0: {card_count_p0} cards")

        # Check for more pages
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
                    pf = OUTPUT_DIR / f"page{pnum}_raw.txt"
                    pf.write_text(pn_text)
                    output["pages"].append({"page": pnum, "text": pn_text, "buttons": pn_cb, "url_buttons": pn_url})
                    for btn in pn_cb:
                        if btn["data"].startswith("edge:detail:"):
                            lt = extract_list_tier(btn["text"])
                            all_card_buttons.append((pnum, btn["text"], btn["data"], lt))
                    cc = len([b for b in pn_cb if b["data"].startswith("edge:detail:")])
                    print(f"  Page {pnum}: {cc} cards")

                    more = [b for b in pn_cb if b["data"].startswith("hot:page:")]
                    for mp in more:
                        mn = int(mp["data"].split(":")[-1])
                        if mn > pnum and mn not in discovered_pages:
                            discovered_pages.add(mn)
                            print(f"  Navigating to page {mn}...")
                            _, mn_text, mn_cb, mn_url = await navigate_to_picks(client, entity, page=mn)
                            if mn_text:
                                mf = OUTPUT_DIR / f"page{mn}_raw.txt"
                                mf.write_text(mn_text)
                                output["pages"].append({"page": mn, "text": mn_text, "buttons": mn_cb, "url_buttons": mn_url})
                                for btn in mn_cb:
                                    if btn["data"].startswith("edge:detail:"):
                                        lt2 = extract_list_tier(btn["text"])
                                        all_card_buttons.append((mn, btn["text"], btn["data"], lt2))
                                cc2 = len([b for b in mn_cb if b["data"].startswith("edge:detail:")])
                                print(f"  Page {mn}: {cc2} cards")

    total_cards = len(all_card_buttons)
    print(f"\n  Total cards across all pages: {total_cards}")

    # Step 3: Tap each card for detail view
    print("\n[DETAILS] Tapping each card for detail view...")
    for i, (page_num, btn_text, btn_data, list_tier) in enumerate(all_card_buttons, 1):
        print(f"\n  Card {i}/{total_cards}: {btn_text} (list tier: {list_tier})")
        match_key = btn_data.replace("edge:detail:", "")

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

        card_data = {
            "index": i,
            "button_text": btn_text,
            "match_key": match_key,
            "page": page_num,
            "list_tier": list_tier,
            "detail_tier": detail_tier,
            "tier_match": list_tier == detail_tier,
            "detail_text": text,
            "detail_cb_buttons": detail["detail_cb_buttons"],
            "detail_url_buttons": detail["detail_url_buttons"],
            "load_time": detail["load_time"],
            "error": detail["error"],
            **qa,
        }

        # Parse teams
        tm = re.search(r'🎯\s*(.*?)\s+vs\s+(.*?)(?:\n|$)', text)
        if tm:
            card_data["home_team"] = tm.group(1).strip()
            card_data["away_team"] = tm.group(2).strip()

        lm = re.search(r'🏆\s*(.*?)(?:\n|$)', text)
        if lm:
            card_data["league"] = lm.group(1).strip()

        km = re.search(r'📅\s*(.*?)(?:\n|$)', text)
        if km:
            card_data["kickoff"] = km.group(1).strip()

        bm = re.search(r'📺\s*(.*?)(?:\n|$)', text)
        if bm:
            card_data["broadcast"] = bm.group(1).strip()

        # Save raw card text
        card_file = OUTPUT_DIR / f"card{i}_raw.txt"
        card_file.write_text(
            f"=== CARD {i}: {btn_text} ===\n"
            f"List tier: {list_tier}\n"
            f"Detail tier: {detail_tier}\n"
            f"Tier match: {card_data['tier_match']}\n"
            f"Load time: {detail['load_time']:.1f}s\n"
            f"{'='*60}\n\n"
            f"{text}\n\n"
            f"{'='*60}\n"
            f"CALLBACK BUTTONS:\n"
            + "\n".join(f"  {b['text']} → data:{b['data']}" for b in detail["detail_cb_buttons"])
            + "\n\nURL BUTTONS:\n"
            + "\n".join(f"  {b['text']} → {b['url']}" for b in detail["detail_url_buttons"])
            + f"\n\nANALYSIS:\n{json.dumps(qa, indent=2, default=str)}"
        )

        # Print summary
        home = card_data.get('home_team', '?')
        away = card_data.get('away_team', '?')
        print(f"    {home} vs {away}")
        print(f"    League: {card_data.get('league', '?')}")
        print(f"    Tier: list={list_tier} detail={detail_tier} match={card_data['tier_match']}")
        print(f"    EV: {qa['ev_pct']}% | Prob: {qa['fair_prob_pct']}%")
        print(f"    Multi-BK: {qa['has_multiple_bookmakers']} ({', '.join(qa['bookmakers_in_detail'])})")
        print(f"    Enriched: W84={qa['is_w84_enriched']} ({qa['w84_indicator_count']} indicators) | W82={qa['is_w82_template']}")
        print(f"    Sections: {qa['section_count']}/4 (Setup={qa['has_setup']} Edge={qa['has_edge']} Risk={qa['has_risk']} Verdict={qa['has_verdict']})")
        print(f"    Header: kickoff={qa['has_kickoff']} broadcast={qa['has_broadcast']} league={qa['has_league']}")
        print(f"    Claimed facts: {len(qa['claimed_facts'])}")
        print(f"    Load: {detail['load_time']:.1f}s | Text: {len(text)} chars")

        output["cards"].append(card_data)

    # Save full output
    out_file = OUTPUT_DIR / "r13_qa_results.json"
    out_file.write_text(json.dumps(output, indent=2, ensure_ascii=False, default=str))
    print(f"\n{'='*60}")
    print(f"Audit complete. Cards captured: {len(output['cards'])}")
    print(f"Output: {out_file}")

    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
