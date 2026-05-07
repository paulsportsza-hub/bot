#!/usr/bin/env python3
"""QA-BASELINE-14: Streamlined E2E capture.

Approach: Complete onboarding step-by-step with explicit waits,
then capture Hot Tips + My Matches + UX flows.
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
    ReplyKeyboardMarkup,
)

API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "")
BOT = "mzansiedge_bot"
SESS_FILE = Path(__file__).resolve().parent.parent / "data" / "telethon_qa_session.string"
FILE_SESS = Path(__file__).resolve().parent.parent / "data" / "telethon_qa_session"
OUT = Path("/home/paulsportsza/reports/qa-baseline-14")
OUT.mkdir(parents=True, exist_ok=True)
TS = datetime.now().strftime("%Y%m%d-%H%M")


async def get_client():
    if SESS_FILE.exists():
        s = SESS_FILE.read_text().strip()
        if s:
            c = TelegramClient(StringSession(s), API_ID, API_HASH)
            await c.connect()
            if await c.is_user_authorized():
                return c
            await c.disconnect()
    c = TelegramClient(str(FILE_SESS), API_ID, API_HASH)
    await c.connect()
    if not await c.is_user_authorized():
        sys.exit("Not logged in")
    return c


def txt(msg):
    return (msg.message or msg.text or "").strip()


def btns(msg):
    """Return (callback_buttons, url_buttons)."""
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


async def latest_bot(client, bot_ent, after_id=0, wait=3):
    """Get latest bot message after after_id."""
    await asyncio.sleep(wait)
    msgs = await client.get_messages(bot_ent, limit=10)
    for m in msgs:
        if m.sender_id == bot_ent.id and m.id > after_id:
            return m
    return None


async def click(msg, data_prefix):
    """Click callback button matching prefix."""
    if not msg.reply_markup:
        return False
    for row in msg.reply_markup.rows:
        for btn in row.buttons:
            if isinstance(btn, KeyboardButtonCallback):
                d = btn.data.decode("utf-8", errors="replace") if isinstance(btn.data, bytes) else str(btn.data)
                if d.startswith(data_prefix):
                    await msg.click(data=btn.data)
                    return True
    return False


async def click_exact(msg, data):
    """Click callback button with exact data match."""
    if not msg.reply_markup:
        return False
    for row in msg.reply_markup.rows:
        for btn in row.buttons:
            if isinstance(btn, KeyboardButtonCallback):
                d = btn.data.decode("utf-8", errors="replace") if isinstance(btn.data, bytes) else str(btn.data)
                if d == data:
                    await msg.click(data=btn.data)
                    return True
    return False


async def wait_for_content(client, bot_ent, after_id, timeout=60):
    """Wait for a bot message with real content (not loading/spinner)."""
    deadline = time.time() + timeout
    last_seen_id = after_id
    while time.time() < deadline:
        await asyncio.sleep(2)
        msgs = await client.get_messages(bot_ent, limit=10)
        candidates = []
        for m in msgs:
            if m.sender_id == bot_ent.id and m.id > after_id:
                t = txt(m)
                # Skip pure loading messages
                if t and not _is_loading(t):
                    candidates.append(m)
                last_seen_id = max(last_seen_id, m.id)
        if candidates:
            # Return the one with most content
            return max(candidates, key=lambda m: len(txt(m)))
    return None


def _is_loading(t):
    """Check if message is a loading/spinner message."""
    t_lower = t.lower().strip()
    # Short messages with spinner indicators
    if len(t) < 60 and ("..." in t or "loading" in t_lower or "scanning" in t_lower or "analysing" in t_lower):
        # But not if it also has substantial content
        if "\n" not in t or len(t) < 30:
            return True
    return False


def save(name, data):
    p = OUT / f"{name}_{TS}.json"
    with open(p, "w") as f:
        json.dump(data, f, indent=2, default=str, ensure_ascii=False)
    print(f"  -> {p}")
    return p


def save_txt(name, text):
    p = OUT / f"{name}_{TS}.txt"
    with open(p, "w") as f:
        f.write(text)
    print(f"  -> {p}")
    return p


# ──────────────────────────────────────────────────────────────
async def do_onboarding(client, bot_ent):
    """Complete full onboarding sequence."""
    print("\n=== PHASE 1+2: WIPE & REBUILD PROFILE ===")
    log = []

    # /start
    await client.send_message(bot_ent, "/start")
    m = await latest_bot(client, bot_ent, wait=4)
    if not m:
        return log, "ERROR: no /start response"
    log.append(f"/start: {txt(m)[:200]}")
    print(f"  /start → {txt(m)[:100]}")

    # Check if already onboarded → need reset
    t = txt(m)
    if "welcome back" in t.lower() or "edge picks" in t.lower() or "my matches" in t.lower():
        print("  Already onboarded — resetting via settings")
        await client.send_message(bot_ent, "⚙️ Settings")
        m = await latest_bot(client, bot_ent, wait=3)
        if m and await click(m, "settings:reset"):
            m2 = await latest_bot(client, bot_ent, m.id, wait=3)
            if m2 and await click(m2, "settings:reset:confirm"):
                await asyncio.sleep(3)
                m3 = await latest_bot(client, bot_ent, m2.id, wait=3)
                if m3:
                    log.append(f"Reset: {txt(m3)[:200]}")
                    print(f"  Reset done → {txt(m3)[:100]}")
                    # Now check if onboarding prompt appeared or we need /start
                    if await click(m3, "ob_restart:go"):
                        m = await latest_bot(client, bot_ent, m3.id, wait=3)
                    else:
                        await client.send_message(bot_ent, "/start")
                        m = await latest_bot(client, bot_ent, wait=4)
        else:
            print("  WARNING: Could not reset — continuing with /start")
            await client.send_message(bot_ent, "/start")
            m = await latest_bot(client, bot_ent, wait=4)

    if not m:
        return log, "ERROR: lost bot after reset"

    # Check for ob_restart button
    if await click(m, "ob_restart:go"):
        m = await latest_bot(client, bot_ent, m.id, wait=3)
    if not m:
        return log, "ERROR: lost bot after ob_restart"

    # Step 1: Experience
    print("  Step 1: Experience")
    if await click(m, "ob_exp:experienced"):
        m = await latest_bot(client, bot_ent, m.id, wait=3)
        if m:
            log.append(f"Experience: {txt(m)[:200]}")
    if not m:
        return log, "ERROR: lost bot after experience"

    # Step 2: Sports
    print("  Step 2: Sports (soccer, rugby, cricket, combat)")
    for sport in ["soccer", "rugby", "cricket", "combat"]:
        if await click(m, f"ob_sport:{sport}"):
            await asyncio.sleep(1)
            # Re-fetch message (it gets edited in place)
            msgs = await client.get_messages(bot_ent, limit=3)
            for mx in msgs:
                if mx.sender_id == bot_ent.id:
                    m = mx
                    break
            print(f"    Toggled {sport}")

    log.append(f"Sports selected: {txt(m)[:200]}")

    # Click Done
    if await click(m, "ob_nav:sports_done"):
        m = await latest_bot(client, bot_ent, m.id, wait=3)
    if not m:
        return log, "ERROR: lost bot after sports"

    # Step 3: Favourites — text input per sport
    TEAMS = {
        "soccer": "Man United, Arsenal, Kaizer Chiefs",
        "rugby": "Stormers, Bulls",
        "cricket": "South Africa",
        "combat": "Dricus Du Plessis, Naoya Inoue",
    }
    for sport, teams in TEAMS.items():
        print(f"  Teams for {sport}: {teams}")
        last_id = m.id
        await client.send_message(bot_ent, teams)
        m = await latest_bot(client, bot_ent, last_id, wait=5)
        if m:
            log.append(f"Teams {sport}: {txt(m)[:300]}")
            print(f"    → {txt(m)[:80]}")
            # Click "Done" for this sport
            if await click(m, f"ob_fav_done:{sport}"):
                m = await latest_bot(client, bot_ent, m.id, wait=3)
                if m:
                    print(f"    Done with {sport} → {txt(m)[:60]}")
        else:
            print(f"    WARNING: no response for {sport}")

    if not m:
        return log, "ERROR: lost bot after teams"

    # Experienced users skip edge explainer — go to risk
    print("  Step: Risk/Bankroll/Notify")
    t = txt(m)

    # Handle edge explainer if it appears
    if "edge" in t.lower() and "works" in t.lower():
        if await click(m, "ob_nav:edge_done"):
            m = await latest_bot(client, bot_ent, m.id, wait=3)
            t = txt(m) if m else ""

    # Risk
    if "risk" in t.lower() or "conservative" in t.lower() or "aggressive" in t.lower():
        if await click(m, "ob_risk:moderate"):
            m = await latest_bot(client, bot_ent, m.id, wait=3)
            t = txt(m) if m else ""
            print(f"    Risk → moderate. Next: {t[:60]}")
            log.append(f"Risk: moderate → {t[:200]}")

    # Bankroll
    if m and ("bankroll" in t.lower() or "budget" in t.lower() or "R50" in t or "R200" in t or "R500" in t):
        if await click(m, "ob_bankroll:R500"):
            m = await latest_bot(client, bot_ent, m.id, wait=3)
            t = txt(m) if m else ""
            print(f"    Bankroll → R500. Next: {t[:60]}")
            log.append(f"Bankroll: R500 → {t[:200]}")

    # Notification
    if m and ("notification" in t.lower() or "alert" in t.lower() or "PM" in t or "AM" in t or "18" in t):
        if await click(m, "ob_notify:18"):
            m = await latest_bot(client, bot_ent, m.id, wait=3)
            t = txt(m) if m else ""
            print(f"    Notify → 18:00. Next: {t[:60]}")
            log.append(f"Notify: 18:00 → {t[:200]}")

    # Summary / Done
    if m and ("summary" in t.lower() or "let's go" in t.lower() or "confirm" in t.lower() or "profile" in t.lower()):
        log.append(f"Summary: {t}")
        if await click(m, "ob_done:finish"):
            m = await latest_bot(client, bot_ent, m.id, wait=4)
            if m:
                log.append(f"Done: {txt(m)[:300]}")
                print(f"    Onboarding done → {txt(m)[:80]}")

    # Edge alerts quiz if it appears
    if m:
        t = txt(m)
        if "edge alert" in t.lower() or "set up" in t.lower():
            # Skip edge alerts
            if await click(m, "story:skip"):
                m = await latest_bot(client, bot_ent, m.id, wait=3)
            elif "skip" in t.lower():
                # Look for skip button
                cb, _ = btns(m)
                for b in cb:
                    if "skip" in b["text"].lower():
                        await click_exact(m, b["data"])
                        m = await latest_bot(client, bot_ent, m.id, wait=3)
                        break

    # Verify profile
    print("  Verifying profile...")
    await client.send_message(bot_ent, "👤 Profile")
    m = await latest_bot(client, bot_ent, wait=3)
    if m:
        profile = txt(m)
        log.append(f"Profile: {profile}")
        print(f"  Profile: {profile[:150]}")
    else:
        log.append("Profile: NO RESPONSE")

    return log, "OK"


# ──────────────────────────────────────────────────────────────
async def capture_hot_tips(client, bot_ent):
    """Capture all Hot Tips cards via live bot."""
    print("\n=== PHASE 3: HOT TIPS CAPTURE ===")
    result = {"list_pages": [], "details": [], "latency": {}}

    t0 = time.time()
    last_msgs = await client.get_messages(bot_ent, limit=1)
    after_id = last_msgs[0].id if last_msgs else 0

    await client.send_message(bot_ent, "💎 Top Edge Picks")

    # Wait for content (bot sends loading msg, then edits it)
    m = await wait_for_content(client, bot_ent, after_id, timeout=60)
    t1 = time.time()
    result["latency"]["list_load_s"] = round(t1 - t0, 2)

    if not m:
        # Try getting ALL recent messages — maybe the loading msg was edited
        await asyncio.sleep(5)
        msgs = await client.get_messages(bot_ent, limit=10)
        for mx in msgs:
            if mx.sender_id == bot_ent.id and mx.id > after_id:
                t = txt(mx)
                if len(t) > 50:
                    m = mx
                    break

    if not m:
        print("  ERROR: No Hot Tips response")
        return result

    page_text = txt(m)
    page_cb, page_url = btns(m)
    result["list_pages"].append({
        "text": page_text,
        "buttons_cb": page_cb,
        "buttons_url": page_url,
    })
    print(f"  List loaded ({t1-t0:.1f}s): {page_text[:100]}...")

    # Capture details for each tip
    edge_btns = [b for b in page_cb if b["data"].startswith("edge:detail:")]
    print(f"  Found {len(edge_btns)} edge detail buttons")

    for i, eb in enumerate(edge_btns):
        print(f"\n  [{i+1}] Detail: {eb['text'][:40]}")
        dt0 = time.time()
        before_id = (await client.get_messages(bot_ent, limit=1))[0].id

        await click_exact(m, eb["data"])

        dm = await wait_for_content(client, bot_ent, 0, timeout=40)
        dt1 = time.time()

        if dm:
            detail_text = txt(dm)
            dcb, durl = btns(dm)
            result["details"].append({
                "btn": eb["text"],
                "data": eb["data"],
                "text": detail_text,
                "cb_buttons": dcb,
                "url_buttons": durl,
                "latency_s": round(dt1 - dt0, 2),
            })
            print(f"      {dt1-dt0:.1f}s | {detail_text[:80]}...")

            # Navigate back
            if await click(dm, "hot:back"):
                await asyncio.sleep(3)
                # Re-fetch list page
                msgs = await client.get_messages(bot_ent, limit=5)
                for mx in msgs:
                    if mx.sender_id == bot_ent.id:
                        cb, _ = btns(mx)
                        if any(b["data"].startswith("edge:detail:") for b in cb):
                            m = mx
                            break
        else:
            print(f"      NO RESPONSE")
            result["details"].append({
                "btn": eb["text"],
                "data": eb["data"],
                "text": "NO_RESPONSE",
                "latency_s": round(dt1 - dt0, 2),
            })

        await asyncio.sleep(1)

    # Check for page 2
    next_btns = [b for b in page_cb if "hot:page:" in b["data"] and ("Next" in b.get("text", "") or "➡" in b.get("text", ""))]
    if next_btns:
        print("\n  Checking page 2...")
        await click_exact(m, next_btns[0]["data"])
        m2 = await wait_for_content(client, bot_ent, 0, timeout=15)
        if m2:
            p2_text = txt(m2)
            p2_cb, p2_url = btns(m2)
            result["list_pages"].append({
                "text": p2_text,
                "buttons_cb": p2_cb,
                "buttons_url": p2_url,
                "page": 2,
            })
            print(f"  Page 2: {p2_text[:100]}...")

            # Get details for page 2 tips too
            p2_edge = [b for b in p2_cb if b["data"].startswith("edge:detail:")]
            for eb in p2_edge:
                print(f"  [{eb['text'][:30]}] detail...")
                dt0 = time.time()
                await click_exact(m2, eb["data"])
                dm = await wait_for_content(client, bot_ent, 0, timeout=40)
                dt1 = time.time()
                if dm:
                    dcb, durl = btns(dm)
                    result["details"].append({
                        "btn": eb["text"],
                        "data": eb["data"],
                        "text": txt(dm),
                        "cb_buttons": dcb,
                        "url_buttons": durl,
                        "latency_s": round(dt1 - dt0, 2),
                    })
                    if await click(dm, "hot:back"):
                        await asyncio.sleep(3)
                        msgs = await client.get_messages(bot_ent, limit=5)
                        for mx in msgs:
                            if mx.sender_id == bot_ent.id:
                                cb2, _ = btns(mx)
                                if any(b["data"].startswith("edge:detail:") or "hot:page:" in b["data"] for b in cb2):
                                    m2 = mx
                                    break
                await asyncio.sleep(1)

    save("phase3_hot_tips", result)

    # Verbatim text export
    raw = f"HOT TIPS — FULL VERBATIM EXPORT\nCaptured: {datetime.now().isoformat()}\n{'='*60}\n\n"
    raw += "=== LIST VIEW ===\n\n"
    for p in result["list_pages"]:
        raw += p["text"] + "\n\n"
    raw += "\n=== DETAIL VIEWS ===\n\n"
    for d in result["details"]:
        raw += f"--- {d['btn']} ---\n{d['text']}\n"
        if d.get("url_buttons"):
            raw += f"URL buttons: {json.dumps(d['url_buttons'], ensure_ascii=False)}\n"
        raw += f"Latency: {d.get('latency_s', '?')}s\n{'─'*40}\n\n"
    save_txt("phase3_hot_tips_verbatim", raw)

    return result


# ──────────────────────────────────────────────────────────────
async def capture_my_matches(client, bot_ent):
    """Capture all My Matches cards via live bot."""
    print("\n=== PHASE 4: MY MATCHES CAPTURE ===")
    result = {"list_pages": [], "details": [], "latency": {}, "sports": []}

    t0 = time.time()
    last_msgs = await client.get_messages(bot_ent, limit=1)
    after_id = last_msgs[0].id if last_msgs else 0

    await client.send_message(bot_ent, "⚽ My Matches")

    m = await wait_for_content(client, bot_ent, after_id, timeout=60)
    t1 = time.time()
    result["latency"]["list_load_s"] = round(t1 - t0, 2)

    if not m:
        await asyncio.sleep(5)
        msgs = await client.get_messages(bot_ent, limit=10)
        for mx in msgs:
            if mx.sender_id == bot_ent.id and mx.id > after_id:
                if len(txt(mx)) > 50:
                    m = mx
                    break

    if not m:
        print("  ERROR: No My Matches response")
        return result

    page_text = txt(m)
    page_cb, page_url = btns(m)
    result["list_pages"].append({
        "text": page_text,
        "buttons_cb": page_cb,
        "buttons_url": page_url,
    })
    print(f"  List loaded ({t1-t0:.1f}s): {page_text[:100]}...")

    # Detect sports
    sport_map = {"⚽": "soccer", "🏉": "rugby", "🏏": "cricket", "🥊": "combat"}
    for emoji, sport in sport_map.items():
        if emoji in page_text:
            result["sports"].append(sport)

    # Capture game details
    game_btns = [b for b in page_cb if b["data"].startswith("yg:game:")]
    print(f"  Found {len(game_btns)} game buttons")

    for i, gb in enumerate(game_btns[:8]):
        print(f"\n  [{i+1}] Game: {gb['text'][:40]}")
        dt0 = time.time()

        await click_exact(m, gb["data"])
        dm = await wait_for_content(client, bot_ent, 0, timeout=50)
        dt1 = time.time()

        if dm:
            detail_text = txt(dm)
            dcb, durl = btns(dm)

            # Detect sport from detail
            for emoji, sport in sport_map.items():
                if emoji in detail_text or emoji in gb["text"]:
                    if sport not in result["sports"]:
                        result["sports"].append(sport)

            result["details"].append({
                "btn": gb["text"],
                "data": gb["data"],
                "text": detail_text,
                "cb_buttons": dcb,
                "url_buttons": durl,
                "latency_s": round(dt1 - dt0, 2),
            })
            print(f"      {dt1-dt0:.1f}s | {detail_text[:80]}...")

            # Go back
            if await click(dm, "yg:all"):
                await asyncio.sleep(3)
                msgs = await client.get_messages(bot_ent, limit=5)
                for mx in msgs:
                    if mx.sender_id == bot_ent.id:
                        cb, _ = btns(mx)
                        if any(b["data"].startswith("yg:game:") for b in cb):
                            m = mx
                            break
        else:
            print(f"      NO RESPONSE")
            result["details"].append({
                "btn": gb["text"],
                "data": gb["data"],
                "text": "NO_RESPONSE",
                "latency_s": round(dt1 - dt0, 2),
            })

        await asyncio.sleep(1)

    save("phase4_my_matches", result)

    raw = f"MY MATCHES — FULL VERBATIM EXPORT\nCaptured: {datetime.now().isoformat()}\nSports: {', '.join(result['sports'])}\n{'='*60}\n\n"
    raw += "=== LIST VIEW ===\n\n"
    for p in result["list_pages"]:
        raw += p["text"] + "\n\n"
    raw += "\n=== DETAIL VIEWS ===\n\n"
    for d in result["details"]:
        raw += f"--- {d['btn']} ---\n{d['text']}\n"
        if d.get("url_buttons"):
            raw += f"URL buttons: {json.dumps(d['url_buttons'], ensure_ascii=False)}\n"
        raw += f"Latency: {d.get('latency_s', '?')}s\n{'─'*40}\n\n"
    save_txt("phase4_my_matches_verbatim", raw)

    return result


# ──────────────────────────────────────────────────────────────
async def ux_audit(client, bot_ent):
    """Run UX probes across 14 dimensions."""
    print("\n=== PHASE 5: UX AUDIT ===")
    tests = []

    async def probe(name, send, wait=3):
        t0 = time.time()
        last = (await client.get_messages(bot_ent, limit=1))[0].id
        await client.send_message(bot_ent, send)
        m = await latest_bot(client, bot_ent, last, wait=wait)
        lat = round(time.time() - t0, 2)
        t = txt(m) if m else "NO_RESPONSE"
        cb_b, url_b = btns(m) if m else ([], [])
        tests.append({"test": name, "sent": send, "response": t, "latency_s": lat,
                       "cb_buttons": cb_b, "url_buttons": url_b,
                       "has_reply_kb": bool(m and isinstance(m.reply_markup, ReplyKeyboardMarkup))})
        print(f"  {name}: {lat}s | {t[:60]}")
        return m

    await probe("help", "/help")
    await probe("profile", "👤 Profile")
    settings_m = await probe("settings", "⚙️ Settings")
    await probe("guide", "📖 Guide")
    await probe("menu", "/menu")
    await probe("subscribe", "/subscribe")
    await probe("status", "/status")
    await probe("gibberish", "asdfjkl random 12345")
    await probe("start_when_onboarded", "/start", wait=4)

    # Back navigation from settings
    if settings_m:
        t0 = time.time()
        if await click(settings_m, "nav:main") or await click(settings_m, "menu:home"):
            m = await latest_bot(client, bot_ent, settings_m.id, wait=3)
            lat = round(time.time() - t0, 2)
            tests.append({"test": "back_nav", "latency_s": lat,
                           "response": txt(m)[:200] if m else "NO_RESPONSE"})
            print(f"  back_nav: {lat}s")

    save("phase5_ux_audit", tests)

    raw = f"UX AUDIT — RAW CAPTURES\nCaptured: {datetime.now().isoformat()}\n{'='*60}\n\n"
    for t in tests:
        raw += f"[{t['test']}] latency={t.get('latency_s','?')}s\n"
        raw += f"Sent: {t.get('sent','')}\n"
        raw += f"Response: {t.get('response','')}\n"
        if t.get("cb_buttons"):
            raw += f"Buttons: {[b['text'] for b in t['cb_buttons']]}\n"
        raw += "─"*40 + "\n\n"
    save_txt("phase5_ux_raw", raw)

    return tests


# ──────────────────────────────────────────────────────────────
async def main():
    print(f"QA-BASELINE-14 | {TS}")
    client = await get_client()
    bot_ent = await client.get_entity(BOT)
    print(f"Connected. Bot: {bot_ent.id}")

    all_results = {}

    # Phase 1+2: Onboarding
    ob_log, status = await do_onboarding(client, bot_ent)
    all_results["onboarding"] = {"log": ob_log, "status": status}
    save("phase1_2_onboarding", all_results["onboarding"])

    if status != "OK":
        print(f"\n  WARNING: Onboarding status: {status}")
        print("  Continuing with capture anyway...")

    # Phase 3: Hot Tips
    all_results["hot_tips"] = await capture_hot_tips(client, bot_ent)

    # Phase 4: My Matches
    all_results["my_matches"] = await capture_my_matches(client, bot_ent)

    # Phase 5: UX
    all_results["ux"] = await ux_audit(client, bot_ent)

    save("qa_b14_combined", all_results)

    print(f"\n{'='*60}")
    print("COLLECTION COMPLETE")
    print(f"  Hot Tips list pages: {len(all_results['hot_tips'].get('list_pages', []))}")
    print(f"  Hot Tips details: {len(all_results['hot_tips'].get('details', []))}")
    print(f"  My Matches list pages: {len(all_results['my_matches'].get('list_pages', []))}")
    print(f"  My Matches details: {len(all_results['my_matches'].get('details', []))}")
    print(f"  My Matches sports: {all_results['my_matches'].get('sports', [])}")
    print(f"  UX tests: {len(all_results['ux'])}")
    print(f"Output: {OUT}")

    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
