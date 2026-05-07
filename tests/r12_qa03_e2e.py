"""R12-QA-03 — PROPER Scored QA: 10 Cards, 3 Substance Dimensions, Full HTML Exports.

Strategy: For each card, trigger a fresh Hot Tips list, navigate to the right page,
tap the card, capture detail. This avoids fragile back-navigation.

Usage:
    cd /home/paulsportsza/bot && .venv/bin/python tests/r12_qa03_e2e.py
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from telethon import TelegramClient, functions
from telethon.sessions import StringSession
from telethon.tl.types import ReplyInlineMarkup, KeyboardButtonCallback, KeyboardButtonUrl

API_ID = int(os.getenv("TELEGRAM_API_ID", "32418601"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "95e313a8ef5b998be0515dd8328fac57")
BOT_USERNAME = "mzansiedge_bot"
STRING_SESSION_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "telethon_qa_session.string")
SESSION_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "telethon_qa_session")
from config import BOT_ROOT
CAPTURES_DIR = BOT_ROOT.parent / "reports" / "r12-qa03-captures"
CAPTURES_DIR.mkdir(parents=True, exist_ok=True)

TIER_EMOJIS = {"💎": "diamond", "🥇": "gold", "🥈": "silver", "🥉": "bronze"}
CARDS_PER_PAGE = 4


async def get_client() -> TelegramClient:
    if os.path.exists(STRING_SESSION_FILE):
        s = open(STRING_SESSION_FILE).read().strip()
        if s:
            c = TelegramClient(StringSession(s), API_ID, API_HASH)
            await c.connect()
            if await c.is_user_authorized():
                return c
            await c.disconnect()
    c = TelegramClient(SESSION_FILE, API_ID, API_HASH)
    await c.connect()
    if not await c.is_user_authorized():
        print("ERROR: Not logged in."); sys.exit(1)
    return c


def get_buttons(msg):
    if not msg or not msg.reply_markup or not isinstance(msg.reply_markup, ReplyInlineMarkup):
        return []
    out = []
    for row in msg.reply_markup.rows:
        for btn in row.buttons:
            d = {"text": getattr(btn, "text", "?")}
            if isinstance(btn, KeyboardButtonCallback):
                d["type"] = "callback"; d["data"] = btn.data.decode() if btn.data else ""
            elif isinstance(btn, KeyboardButtonUrl):
                d["type"] = "url"; d["url"] = btn.url or ""
            else:
                d["type"] = "other"
            out.append(d)
    return out


async def click(client, entity, msg_id, data):
    try:
        await client(functions.messages.GetBotCallbackAnswerRequest(
            peer=entity, msg_id=msg_id, data=data.encode("utf-8")))
    except Exception:
        pass  # Bot processes callback even if answer fails


async def fresh(client, entity, msg_id):
    return await client.get_messages(entity, ids=msg_id)


def tier(text):
    for e, t in TIER_EMOJIS.items():
        if e in text: return t
    return ""


def ev(text):
    m = re.search(r'\+(\d+(?:\.\d+)?)\s*%', text)
    return m.group(1) + "%" if m else ""


def outcome(text):
    m = re.search(r'💰\s*(.*?)\s*@\s*[\d.]+', text)
    return m.group(1).strip() if m else ""


def odds_bk(text):
    m = re.search(r'@\s*([\d.]+)\s*\(([^)]+)\)', text)
    return (m.group(1), m.group(2).strip()) if m else ("", "")


def sport(text):
    for e, s in [("⚽", "Soccer"), ("🏉", "Rugby"), ("🏏", "Cricket"), ("🥊", "Combat")]:
        if e in text: return s
    return "Unknown"


def parse_cards(text):
    cards = []
    parts = re.split(r'\n*\[(\d+)\]', text)
    for i in range(1, len(parts), 2):
        cards.append({"num": int(parts[i]), "text": parts[i+1].strip() if i+1 < len(parts) else ""})
    return cards


async def trigger_list(client, entity):
    """Send Hot Tips command and return (msg, text, cards)."""
    sent = await client.send_message(entity, "💎 Top Edge Picks")
    await asyncio.sleep(18)
    msgs = await client.get_messages(entity, limit=30)
    for m in msgs:
        if m.id >= sent.id and m.text and not m.out:
            if "[1]" in m.text or "Live Edges" in m.text:
                return m, m.text, parse_cards(m.text)
    return None, "", []


async def run_qa():
    ts = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    print("=" * 70)
    print("R12-QA-03 — PROPER Scored QA: 10 Cards, 3 Substance Dimensions")
    print(f"Time: {ts}")
    print("=" * 70)

    client = await get_client()
    print("\n✅ Telethon connected")

    entity = await client.get_entity(BOT_USERNAME)
    all_defects = []
    all_cards = []
    tiers_found = set()

    # ── Phase 1: Capture full list ──
    print("\n─── Phase 1: Full List Capture ───")
    list_msg, list_text, p1_cards = await trigger_list(client, entity)
    if not list_msg:
        print("  ❌ No list!"); await client.disconnect(); return

    all_list_cards = list(p1_cards)
    (CAPTURES_DIR / "page1_list.txt").write_text(list_text)
    print(f"  Page 1: {len(p1_cards)} cards")

    # Page 2
    btns = get_buttons(list_msg)
    nxt = next((b for b in btns if "Next" in b.get("text", "")), None)
    if nxt:
        await click(client, entity, list_msg.id, nxt["data"])
        await asyncio.sleep(12)
        p2 = await fresh(client, entity, list_msg.id)
        if p2 and p2.text and p2.text != list_text:
            p2_cards = parse_cards(p2.text)
            all_list_cards.extend(p2_cards)
            (CAPTURES_DIR / "page2_list.txt").write_text(p2.text)
            print(f"  Page 2: {len(p2_cards)} cards")
            # Page 3
            btns2 = get_buttons(p2)
            nxt2 = next((b for b in btns2 if "Next" in b.get("text", "")), None)
            if nxt2:
                await click(client, entity, list_msg.id, nxt2["data"])
                await asyncio.sleep(12)
                p3 = await fresh(client, entity, list_msg.id)
                if p3 and p3.text and p3.text != p2.text:
                    p3_cards = parse_cards(p3.text)
                    all_list_cards.extend(p3_cards)
                    (CAPTURES_DIR / "page3_list.txt").write_text(p3.text)
                    print(f"  Page 3: {len(p3_cards)} cards")

    print(f"  Total: {len(all_list_cards)} cards")
    for c in all_list_cards:
        t = tier(c["text"])
        if t: tiers_found.add(t)
    print(f"  Tiers: {tiers_found or '{none}'}")

    # ── Phase 2: Tap each card (fresh list per card) ──
    print("\n─── Phase 2: Detail Captures (1 per fresh list trigger) ───")

    for card_idx, card_data in enumerate(all_list_cards):
        cnum = card_data["num"]
        ctxt = card_data["text"]
        target_page = card_idx // CARDS_PER_PAGE
        btn_slot = card_idx % CARDS_PER_PAGE

        print(f"\n  Card [{cnum}] (page {target_page+1}, slot {btn_slot})")

        # Get a fresh list
        lm, lt, _ = await trigger_list(client, entity)
        if not lm:
            print(f"    ❌ Failed to get list"); continue

        # Navigate to target page
        if target_page > 0:
            for pg in range(target_page):
                await asyncio.sleep(1)
                b = get_buttons(lm if pg == 0 else await fresh(client, entity, lm.id))
                nx = next((x for x in (b or []) if "Next" in x.get("text", "")), None)
                if nx:
                    await click(client, entity, lm.id, nx["data"])
                    await asyncio.sleep(10)
                else:
                    print(f"    ⚠️ No Next button for page {pg+2}")
                    break

        # Refresh message to get current buttons
        cur = await fresh(client, entity, lm.id)
        detail_btns = [b for b in get_buttons(cur) if b.get("data", "").startswith("edge:detail:")]

        if btn_slot >= len(detail_btns):
            print(f"    ❌ No button at slot {btn_slot} (available: {len(detail_btns)})")
            continue

        match_key = detail_btns[btn_slot]["data"].replace("edge:detail:", "")
        list_tier = tier(ctxt)
        list_out = outcome(ctxt)
        list_ev = ev(ctxt)
        list_o, list_bk = odds_bk(ctxt)
        sp = sport(ctxt)

        print(f"    {match_key}")
        print(f"    List: {sp} | {list_tier} | '{list_out}' @ {list_o} ({list_bk}) | EV {list_ev}")

        # Tap detail
        await click(client, entity, lm.id, detail_btns[btn_slot]["data"])
        await asyncio.sleep(14)

        # Read detail (edited in place)
        det = await fresh(client, entity, lm.id)
        dtxt = ""
        if det and det.text:
            if any(k in det.text for k in ["Setup", "Edge", "Verdict", "📋", "🏆"]):
                dtxt = det.text

        if not dtxt:
            # Check new messages
            latest = await client.get_messages(entity, limit=5)
            for m in latest:
                if m.text and not m.out and m.id != lm.id:
                    if any(k in m.text for k in ["Setup", "Edge", "Verdict"]):
                        dtxt = m.text; det = m; break

        if not dtxt:
            print(f"    ❌ No detail captured")
            all_defects.append(f"P0-NO-DETAIL: [{cnum}] {match_key}")
            continue

        # Save HTML
        (CAPTURES_DIR / f"card{cnum}_{match_key[:50]}.html").write_text(dtxt)

        # Extract detail data
        det_tier = tier(dtxt)
        det_ev = ev(dtxt)
        dbtns = get_buttons(det)
        det_out = ""
        cta_txt = ""
        cta_url = ""
        has_cmp = False
        for db in dbtns:
            t2 = db.get("text", "")
            m2 = re.search(r'(?:Back|back)\s+(.*?)\s*@\s*([\d.]+)\s+on\s+(.*?)(?:\s*→|$)', t2)
            if m2:
                det_out = m2.group(1).strip()
                cta_txt = t2; cta_url = db.get("url", "")
            if "compare" in t2.lower():
                has_cmp = True

        if not det_out:
            for pat in [r'nod to\s+(.*?)\s+(?:win\s+)?at', r'(?:back|backing)\s+(.*?)\s+at\s+[\d.]',
                        r'green light.*?:\s+(.*?)\s+(?:win\s+)?at', r'lean on\s+(.*?)\s+at']:
                m3 = re.search(pat, dtxt, re.I)
                if m3: det_out = m3.group(1).strip(); break

        if not det_out:
            m3 = re.search(r'(?:SA )?Bookmaker Odds.*?\n\s*(\w[\w\s]*?):\s*\*\*([\d.]+)\*\*', dtxt, re.S)
            if m3: det_out = m3.group(1).strip()

        # Section checks
        secs = {
            "setup": bool(re.search(r'📋.*Setup|The Setup', dtxt)),
            "edge": bool(re.search(r'🎯.*Edge|The Edge', dtxt)),
            "risk": bool(re.search(r'⚠️.*Risk|The Risk', dtxt)),
            "verdict": bool(re.search(r'🏆.*Verdict', dtxt)),
        }
        has_sig = "Signal" in dtxt or "Composite" in dtxt
        has_trk = "track record" in dtxt.lower() or "7D" in dtxt
        has_bko = bool(re.search(r'SA Bookmaker|Bookmaker Odds', dtxt))
        has_ko = bool(re.search(r'📅|Today|Tomorrow|Mon |Tue |Wed |Thu |Fri |Sat |Sun |\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)', dtxt))
        has_lg = "🏆" in dtxt
        has_tv = "📺" in dtxt

        # CTA validation
        cta_ok = False
        _BKD = {"SuperSportBet":"supersportbet","Hollywoodbets":"hollywoodbets","Betway":"betway",
                "World Sports Betting":"worldsportsbetting","PlayaBets":"playabets","SupaBets":"supabets",
                "Sportingbet":"sportingbet","GBets":"gbets"}
        if cta_txt and cta_url:
            for bn, bd in _BKD.items():
                if bn in cta_txt:
                    if bd in cta_url.lower(): cta_ok = True
                    elif "betway" in cta_url.lower():
                        all_defects.append(f"P0-CTA-MISMATCH: [{cnum}] CTA={bn} URL→betway")
                    break

        # Alignment checks
        outcome_aligned = False
        if list_out and det_out:
            lo, do = list_out.lower(), det_out.lower()
            outcome_aligned = lo == do or lo in do or do in lo
            if not outcome_aligned:
                all_defects.append(f"P0-OUTCOME-DIVERGE: [{cnum}] list='{list_out}' det='{det_out}'")
        tier_ok = list_tier == det_tier if (list_tier and det_tier) else True
        if not tier_ok:
            all_defects.append(f"P1-TIER-MISMATCH: [{cnum}] {list_tier}→{det_tier}")

        print(f"    Detail: {det_tier} | '{det_out}' | EV {det_ev}")
        print(f"    Sections: S={'✅' if secs['setup'] else '❌'} E={'✅' if secs['edge'] else '❌'} "
              f"R={'✅' if secs['risk'] else '❌'} V={'✅' if secs['verdict'] else '❌'}")
        print(f"    Header: date={'✅' if has_ko else '❌'} league={'✅' if has_lg else '❌'} TV={'✅' if has_tv else '⚠️'}")
        print(f"    CTA: {'✅' if cta_ok else '❌'} {cta_txt[:55] if cta_txt else '(none)'}")
        print(f"    Compare={'✅' if has_cmp else '❌'} | Signal={'✅' if has_sig else '❌'} | BK Odds={'✅' if has_bko else '❌'}")
        print(f"    Outcome={'✅' if outcome_aligned else '❌'} | Tier={'✅' if tier_ok else '❌'}")

        all_cards.append({
            "card_num": cnum, "match": match_key, "sport": sp,
            "tier_in_list": list_tier, "outcome_in_list": list_out, "ev_in_list": list_ev,
            "odds_in_list": list_o, "bookmaker_in_list": list_bk,
            "tier_in_detail": det_tier, "outcome_in_detail": det_out, "ev_in_detail": det_ev,
            "has_kickoff": has_ko, "has_league": has_lg, "has_broadcast": has_tv,
            **{f"has_{k}": v for k, v in secs.items()},
            "has_signal_breakdown": has_sig, "has_track_record": has_trk,
            "has_bookmaker_odds": has_bko, "cta_button_text": cta_txt, "cta_url": cta_url,
            "cta_bookmaker_match": cta_ok, "has_compare_odds": has_cmp,
            "detail_html": dtxt, "list_text": ctxt, "outcome_aligned": outcome_aligned,
            "tier_consistent": tier_ok,
            "buttons": [{"text":b.get("text",""),"url":b.get("url",""),"data":b.get("data","")} for b in dbtns],
        })

    print("\n" + "=" * 70)
    print(f"CAPTURE COMPLETE: {len(all_cards)}/{len(all_list_cards)} cards")
    print("=" * 70)

    results = {
        "timestamp": ts, "commit": "74339ae", "build": "R12-BUILD-02",
        "total_list_cards": len(all_list_cards), "total_detail_captures": len(all_cards),
        "tiers_found": sorted(tiers_found), "defects": all_defects, "cards": all_cards,
    }
    out = CAPTURES_DIR / "r12_qa03_results.json"
    out.write_text(json.dumps(results, indent=2, default=str))
    print(f"\nResults → {out}")
    await client.disconnect()
    return results


if __name__ == "__main__":
    asyncio.run(run_qa())
