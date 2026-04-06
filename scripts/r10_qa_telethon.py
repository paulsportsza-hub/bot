#!/usr/bin/env python3
"""R10-QA-01: Formal Scored Telethon QA Audit.

Captures ALL live Edge cards via Telethon for formal 5-dimension scoring.
Stores raw text, buttons, list-view tier, detail-view tier, timings.
Verifies 4 investigation-backed fixes from BUILD-01 + BUILD-02.
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
OUTPUT_DIR = BOT_ROOT.parent / "reports" / "r10-qa-captures"
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
        "has_model_only": "[MODEL ONLY]" in text,
        "has_sharp_reference": False,
        "staking_language": None,
        "ev_pct": None,
        "fair_prob_pct": None,
        "has_compare_odds": False,
        "has_multiple_bookmakers": False,
        "bookmakers_in_detail": [],
        "cta_bookmaker_text": None,
        "cta_url": None,
        "cta_url_domain": None,
        "is_locked": "🔒" in text and "Available on" in text,
        "has_kickoff": False,
        "has_broadcast": False,
        "has_league": False,
        "section_count": 0,
        "has_setup": "📋" in text or "The Setup" in text,
        "has_edge": "🎯" in text and "The Edge" in text,
        "has_risk": "⚠️" in text or "The Risk" in text,
        "has_verdict": "🏆" in text or "Verdict" in text,
    }

    # Count sections
    for s in ["📋", "🎯", "⚠️", "🏆"]:
        if s in text:
            analysis["section_count"] += 1

    # Sharp references
    sharp_patterns = ["sharp market", "sharp pricing", "pinnacle", "betfair exchange",
                      "matchbook", "smarkets"]
    for p in sharp_patterns:
        if p.lower() in text.lower():
            analysis["has_sharp_reference"] = True
            break

    # Staking language
    staking_match = re.search(r'(Small stake|Tiny exposure|Minimal exposure|measured.exposure|'
                               r'normal sizing|confident|back this|strong|conviction)', text, re.I)
    if staking_match:
        analysis["staking_language"] = staking_match.group(0)

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

    # CTA button (URL button)
    for btn in url_buttons:
        t = btn.get("text", "")
        if any(x in t.lower() for x in ["back", "bet on", "→"]):
            analysis["cta_bookmaker_text"] = t
            analysis["cta_url"] = btn.get("url", "")
            url_match = re.search(r'https?://(?:www\.)?([\w.-]+)', btn.get("url", ""))
            if url_match:
                analysis["cta_url_domain"] = url_match.group(1)
            break

    # Header completeness
    analysis["has_kickoff"] = "📅" in text or bool(re.search(r'\d{1,2}:\d{2}', text))
    analysis["has_broadcast"] = "📺" in text or "DStv" in text
    analysis["has_league"] = "🏆" in text

    # Check CTA URL mismatch (betway.co.za for non-Betway picks)
    if analysis["cta_url_domain"] and analysis["cta_bookmaker_text"]:
        cta_bk = analysis["cta_bookmaker_text"].lower()
        cta_domain = analysis["cta_url_domain"].lower()
        # Check if bookmaker name in CTA matches the domain
        if "betway" in cta_domain and "betway" not in cta_bk:
            analysis["cta_url_mismatch"] = True
        elif "hollywoodbets" in cta_domain and "hollywoodbets" not in cta_bk:
            analysis["cta_url_mismatch"] = True
        else:
            analysis["cta_url_mismatch"] = False
    else:
        analysis["cta_url_mismatch"] = None

    return analysis


async def main():
    print("=" * 60)
    print("R10-QA-01: Formal Scored Telethon QA — @mzansiedge_bot")
    print(f"Date: {datetime.now().isoformat()}")
    print(f"Commits: e78ca1d (BUILD-01) + 15e4cd0 (BUILD-02)")
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
        "wave": "R10-QA-01",
        "commits": ["e78ca1d (BUILD-01)", "15e4cd0 (BUILD-02)"],
        "connection": {"user": me.first_name, "username": me.username,
                       "user_id": me.id, "time": conn_time, "bot_id": entity.id},
        "pages": [],
        "cards": [],
    }

    # Collect all pages
    print("\n[LIST] Loading Top Edge Picks pages...")
    all_card_buttons = []

    # Page 0
    list_msg_p0, p0_text, p0_cb, p0_url = await navigate_to_picks(client, entity, page=0)
    if p0_text:
        page_file = OUTPUT_DIR / "page1_raw.txt"
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
                    pf = OUTPUT_DIR / f"page{pnum+1}_raw.txt"
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
                                mf = OUTPUT_DIR / f"page{mn+1}_raw.txt"
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

    # Tap each card
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
            + f"\n\nANALYSIS:\n{json.dumps(qa, indent=2)}"
        )

        # Print summary
        home = card_data.get('home_team', '?')
        away = card_data.get('away_team', '?')
        print(f"    {home} vs {away}")
        print(f"    League: {card_data.get('league', '?')}")
        print(f"    Tier: list={list_tier} detail={detail_tier} match={card_data['tier_match']}")
        print(f"    EV: {qa['ev_pct']}% | Prob: {qa['fair_prob_pct']}%")
        print(f"    Multi-BK: {qa['has_multiple_bookmakers']} ({', '.join(qa['bookmakers_in_detail'])})")
        print(f"    Compare: {qa['has_compare_odds']}")
        print(f"    CTA: {qa['cta_bookmaker_text']}")
        if qa['cta_url']:
            print(f"    CTA URL: {qa['cta_url_domain']} | Mismatch: {qa.get('cta_url_mismatch')}")
        print(f"    Sections: {qa['section_count']}/4 (Setup={qa['has_setup']} Edge={qa['has_edge']} Risk={qa['has_risk']} Verdict={qa['has_verdict']})")
        print(f"    Header: kickoff={qa['has_kickoff']} broadcast={qa['has_broadcast']} league={qa['has_league']}")
        print(f"    Load: {detail['load_time']:.1f}s | Text: {len(text)} chars")

        output["cards"].append(card_data)

    # Save full output
    out_file = OUTPUT_DIR / "qa_results.json"
    out_file.write_text(json.dumps(output, indent=2, ensure_ascii=False))
    print(f"\n{'='*60}")
    print(f"Audit complete. Cards captured: {len(output['cards'])}")
    print(f"Output: {out_file}")

    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
