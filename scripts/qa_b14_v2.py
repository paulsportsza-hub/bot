#!/usr/bin/env python3
"""QA-BASELINE-14 v2: Handles bot's edit_message pattern.

Key insight: Bot uses query.edit_message_text() for most responses.
This means the same message ID gets updated content. We must re-read
messages by position (limit=N) not just by ID comparison.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
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
SESS = Path(__file__).resolve().parent.parent / "data" / "telethon_qa_session.string"
FSESS = Path(__file__).resolve().parent.parent / "data" / "telethon_qa_session"
OUT = Path("/home/paulsportsza/reports/qa-baseline-14")
OUT.mkdir(parents=True, exist_ok=True)
TS = datetime.now().strftime("%Y%m%d-%H%M")


async def get_client():
    if SESS.exists():
        s = SESS.read_text().strip()
        if s:
            c = TelegramClient(StringSession(s), API_ID, API_HASH)
            await c.connect()
            if await c.is_user_authorized():
                return c
            await c.disconnect()
    c = TelegramClient(str(FSESS), API_ID, API_HASH)
    await c.connect()
    if not await c.is_user_authorized():
        sys.exit("Not logged in")
    return c


def txt(msg):
    return (msg.message or msg.text or "").strip() if msg else ""


def btns(msg):
    cb, url = [], []
    if not msg or not msg.reply_markup or not isinstance(msg.reply_markup, ReplyInlineMarkup):
        return cb, url
    for row in msg.reply_markup.rows:
        for btn in row.buttons:
            if isinstance(btn, KeyboardButtonCallback):
                d = btn.data.decode("utf-8", errors="replace") if isinstance(btn.data, bytes) else str(btn.data)
                cb.append({"text": btn.text, "data": d})
            elif isinstance(btn, KeyboardButtonUrl):
                url.append({"text": btn.text, "url": btn.url})
    return cb, url


async def get_latest(client, bot_ent, wait=3.0):
    """Get the latest bot message (handles edits)."""
    await asyncio.sleep(wait)
    msgs = await client.get_messages(bot_ent, limit=5)
    for m in msgs:
        if m.sender_id == bot_ent.id:
            return m
    return None


async def wait_stable(client, bot_ent, timeout=60, min_len=50):
    """Wait until the latest bot message stabilizes (stops being edited)."""
    deadline = time.time() + timeout
    prev_text = ""
    stable_count = 0
    while time.time() < deadline:
        await asyncio.sleep(2)
        m = await get_latest(client, bot_ent, wait=0)
        if not m:
            continue
        t = txt(m)
        if t == prev_text and len(t) >= min_len:
            stable_count += 1
            if stable_count >= 2:
                return m
        else:
            stable_count = 0
            prev_text = t
    # Return whatever we have
    return await get_latest(client, bot_ent, wait=0)


async def click(msg, data_prefix):
    if not msg or not msg.reply_markup:
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
    if not msg or not msg.reply_markup:
        return False
    for row in msg.reply_markup.rows:
        for btn in row.buttons:
            if isinstance(btn, KeyboardButtonCallback):
                d = btn.data.decode("utf-8", errors="replace") if isinstance(btn.data, bytes) else str(btn.data)
                if d == data:
                    await msg.click(data=btn.data)
                    return True
    return False


def save(name, data):
    p = OUT / f"{name}_{TS}.json"
    with open(p, "w") as f:
        json.dump(data, f, indent=2, default=str, ensure_ascii=False)
    print(f"  -> {p.name}")


def save_txt(name, text):
    p = OUT / f"{name}_{TS}.txt"
    with open(p, "w") as f:
        f.write(text)
    print(f"  -> {p.name}")


# ──────────────────────────────────────────────────────────────
async def onboarding(client, bot_ent):
    print("\n=== PHASE 1+2: WIPE & REBUILD ===")
    log = []

    # Start
    await client.send_message(bot_ent, "/start")
    m = await get_latest(client, bot_ent, wait=4)
    t = txt(m)
    log.append(f"/start: {t[:200]}")
    print(f"  /start → {t[:80]}")

    # If already onboarded, reset
    if m and ("welcome back" in t.lower() or "edge picks" in t.lower() or "my match" in t.lower() or "main menu" in t.lower()):
        print("  Resetting profile...")
        await client.send_message(bot_ent, "⚙️ Settings")
        await asyncio.sleep(3)
        m = await get_latest(client, bot_ent, wait=0)
        if await click(m, "settings:reset"):
            await asyncio.sleep(3)
            m = await get_latest(client, bot_ent, wait=0)
            if await click(m, "settings:reset:confirm"):
                await asyncio.sleep(3)
                m = await get_latest(client, bot_ent, wait=0)
                log.append(f"Reset: {txt(m)[:200]}")
                print(f"  Reset → {txt(m)[:80]}")
                if await click(m, "ob_restart:go"):
                    await asyncio.sleep(3)
                    m = await get_latest(client, bot_ent, wait=0)
        # If reset didn't work, /start fresh
        if not m or "step" not in txt(m).lower():
            await client.send_message(bot_ent, "/start")
            m = await get_latest(client, bot_ent, wait=4)

    # ob_restart button?
    if m and await click(m, "ob_restart:go"):
        await asyncio.sleep(3)
        m = await get_latest(client, bot_ent, wait=0)

    # EXPERIENCE
    print("  Step 1: Experience")
    if m and await click(m, "ob_exp:experienced"):
        await asyncio.sleep(3)
        m = await get_latest(client, bot_ent, wait=0)
        log.append(f"Exp: {txt(m)[:200]}")
        print(f"    → {txt(m)[:60]}")
    else:
        print("    WARNING: no experience button")

    # SPORTS
    print("  Step 2: Sports")
    for sport in ["soccer", "rugby", "cricket", "combat"]:
        if m and await click(m, f"ob_sport:{sport}"):
            await asyncio.sleep(1.5)
            m = await get_latest(client, bot_ent, wait=0)
            print(f"    ✓ {sport}")
    if m and await click(m, "ob_nav:sports_done"):
        await asyncio.sleep(3)
        m = await get_latest(client, bot_ent, wait=0)
        log.append(f"Sports done: {txt(m)[:200]}")
        print(f"    → {txt(m)[:60]}")

    # TEAMS
    TEAMS = {
        "soccer": "Man United, Arsenal, Kaizer Chiefs",
        "rugby": "Stormers, Bulls",
        "cricket": "South Africa",
        "combat": "Dricus Du Plessis, Naoya Inoue",
    }
    for sport, teams_str in TEAMS.items():
        print(f"  Teams for {sport}: {teams_str}")
        await client.send_message(bot_ent, teams_str)
        await asyncio.sleep(5)
        m = await get_latest(client, bot_ent, wait=0)
        resp = txt(m)
        log.append(f"Teams {sport}: {resp[:300]}")
        print(f"    → {resp[:80]}")

        if m and await click(m, f"ob_fav_done:{sport}"):
            await asyncio.sleep(3)
            m = await get_latest(client, bot_ent, wait=0)
            print(f"    Done → {txt(m)[:60]}")

    # EDGE EXPLAINER (experienced may skip)
    t = txt(m)
    if "edge" in t.lower() and "works" in t.lower():
        print("  Edge explainer — acknowledging")
        if await click(m, "ob_nav:edge_done"):
            await asyncio.sleep(3)
            m = await get_latest(client, bot_ent, wait=0)

    # RISK
    t = txt(m)
    if "risk" in t.lower() or "conservative" in t.lower():
        print("  Risk → moderate")
        if await click(m, "ob_risk:moderate"):
            await asyncio.sleep(3)
            m = await get_latest(client, bot_ent, wait=0)

    # BANKROLL
    t = txt(m)
    if "bankroll" in t.lower() or "budget" in t.lower() or "R50" in t or "R200" in t:
        print("  Bankroll → R500")
        if await click(m, "ob_bankroll:500"):
            await asyncio.sleep(3)
            m = await get_latest(client, bot_ent, wait=0)

    # NOTIFY
    t = txt(m)
    if "notification" in t.lower() or "alert" in t.lower() or "PM" in t or "AM" in t:
        print("  Notify → 18:00")
        if await click(m, "ob_notify:18"):
            await asyncio.sleep(3)
            m = await get_latest(client, bot_ent, wait=0)

    # SUMMARY → PLAN → DONE
    t = txt(m)
    log.append(f"Summary: {t[:300]}")
    print(f"  Summary: {t[:80]}")

    # Click "Next — Choose Plan"
    if await click(m, "ob_nav:plan"):
        await asyncio.sleep(3)
        m = await get_latest(client, bot_ent, wait=0)
        t = txt(m)
        log.append(f"Plan step: {t[:300]}")
        print(f"  Plan step → {t[:80]}")

    # Click "Continue with Bronze" (free tier)
    if await click(m, "ob_plan:bronze"):
        await asyncio.sleep(4)
        m = await get_latest(client, bot_ent, wait=0)
        log.append(f"Done: {txt(m)[:300]}")
        print(f"  Onboarding done → {txt(m)[:80]}")
    elif await click(m, "ob_done:finish"):
        await asyncio.sleep(4)
        m = await get_latest(client, bot_ent, wait=0)
        log.append(f"Done: {txt(m)[:300]}")
        print(f"  Done → {txt(m)[:80]}")

    # EDGE ALERTS — skip if offered
    t = txt(m)
    if "edge alert" in t.lower() or "set up" in t.lower():
        cb, _ = btns(m)
        for b in cb:
            if "skip" in b["text"].lower() or "later" in b["text"].lower():
                await click_exact(m, b["data"])
                await asyncio.sleep(3)
                m = await get_latest(client, bot_ent, wait=0)
                break

    # VERIFY
    print("  Verifying profile...")
    await client.send_message(bot_ent, "👤 Profile")
    await asyncio.sleep(3)
    m = await get_latest(client, bot_ent, wait=0)
    profile = txt(m)
    log.append(f"Profile: {profile}")
    print(f"  Profile: {profile[:150]}")

    status = "OK" if any(k in profile.lower() for k in ["arsenal", "man united", "stormers"]) else "PARTIAL"
    save("phase1_2_onboarding", {"log": log, "status": status, "profile": profile})
    return status


# ──────────────────────────────────────────────────────────────
async def hot_tips(client, bot_ent):
    print("\n=== PHASE 3: HOT TIPS ===")
    result = {"pages": [], "details": [], "latency": {}}

    t0 = time.time()
    await client.send_message(bot_ent, "💎 Top Edge Picks")

    # Wait for stable content (spinner → edit → final)
    m = await wait_stable(client, bot_ent, timeout=60, min_len=30)
    t1 = time.time()
    result["latency"]["list_s"] = round(t1 - t0, 2)

    if not m or len(txt(m)) < 30:
        print("  ERROR: No Hot Tips content")
        save("phase3_hot_tips", result)
        return result

    page_text = txt(m)
    cb, url = btns(m)
    result["pages"].append({"text": page_text, "cb": cb, "url": url})
    print(f"  List ({t1-t0:.1f}s): {page_text[:100]}...")

    # Get detail for each edge button
    edge_btns = [b for b in cb if b["data"].startswith("edge:detail:")]
    print(f"  {len(edge_btns)} detail buttons found")

    for i, eb in enumerate(edge_btns):
        print(f"\n  [{i+1}] {eb['text'][:35]}")
        dt0 = time.time()
        await click_exact(m, eb["data"])
        dm = await wait_stable(client, bot_ent, timeout=45, min_len=40)
        dt1 = time.time()

        if dm and txt(dm) != page_text:  # Content changed
            d_txt = txt(dm)
            d_cb, d_url = btns(dm)
            result["details"].append({
                "btn": eb["text"], "data": eb["data"],
                "text": d_txt, "cb": d_cb, "url": d_url,
                "lat_s": round(dt1 - dt0, 2),
            })
            print(f"      {dt1-dt0:.1f}s | {d_txt[:70]}...")

            # Back to list
            if await click(dm, "hot:back"):
                await asyncio.sleep(3)
                m = await get_latest(client, bot_ent, wait=0)
        else:
            result["details"].append({
                "btn": eb["text"], "data": eb["data"],
                "text": txt(dm) if dm else "NO_RESP",
                "lat_s": round(dt1 - dt0, 2),
            })
            print(f"      {dt1-dt0:.1f}s | NO CHANGE/RESPONSE")

        await asyncio.sleep(1)

    # Page 2?
    next_btns = [b for b in cb if "hot:page:" in b["data"] and ("➡" in b.get("text","") or "Next" in b.get("text",""))]
    if next_btns:
        print("\n  Page 2...")
        await click_exact(m, next_btns[0]["data"])
        m2 = await wait_stable(client, bot_ent, timeout=15, min_len=30)
        if m2:
            p2t = txt(m2)
            p2cb, p2url = btns(m2)
            result["pages"].append({"text": p2t, "cb": p2cb, "url": p2url, "page": 2})

            # Details for page 2
            p2_edge = [b for b in p2cb if b["data"].startswith("edge:detail:")]
            for eb in p2_edge:
                print(f"  P2 detail: {eb['text'][:30]}")
                dt0 = time.time()
                await click_exact(m2, eb["data"])
                dm2 = await wait_stable(client, bot_ent, timeout=45, min_len=40)
                dt1 = time.time()
                if dm2:
                    result["details"].append({
                        "btn": eb["text"], "data": eb["data"],
                        "text": txt(dm2), "lat_s": round(dt1-dt0, 2),
                    })
                    if await click(dm2, "hot:back"):
                        await asyncio.sleep(3)
                await asyncio.sleep(1)

    save("phase3_hot_tips", result)

    # Verbatim export
    raw = f"HOT TIPS VERBATIM\n{datetime.now().isoformat()}\n{'='*60}\n\n"
    raw += "=== LIST ===\n"
    for p in result["pages"]:
        raw += p["text"] + "\n\n"
    raw += "\n=== DETAILS ===\n"
    for d in result["details"]:
        raw += f"\n--- {d['btn']} (data={d['data']}) ---\n{d['text']}\n"
        if d.get("url"):
            raw += f"URLs: {json.dumps(d['url'], ensure_ascii=False)}\n"
        raw += f"Latency: {d.get('lat_s','?')}s\n"
    save_txt("phase3_verbatim", raw)
    return result


# ──────────────────────────────────────────────────────────────
async def my_matches(client, bot_ent):
    print("\n=== PHASE 4: MY MATCHES ===")
    result = {"pages": [], "details": [], "latency": {}, "sports": []}

    t0 = time.time()
    await client.send_message(bot_ent, "⚽ My Matches")

    m = await wait_stable(client, bot_ent, timeout=60, min_len=30)
    t1 = time.time()
    result["latency"]["list_s"] = round(t1 - t0, 2)

    if not m or len(txt(m)) < 20:
        print("  ERROR: No My Matches content")
        save("phase4_my_matches", result)
        return result

    page_text = txt(m)
    cb, url = btns(m)
    result["pages"].append({"text": page_text, "cb": cb, "url": url})
    print(f"  List ({t1-t0:.1f}s): {page_text[:100]}...")

    # Detect sports
    sports_map = {"⚽": "soccer", "🏉": "rugby", "🏏": "cricket", "🥊": "combat"}
    for e, s in sports_map.items():
        if e in page_text:
            result["sports"].append(s)

    # Game details
    game_btns = [b for b in cb if b["data"].startswith("yg:game:")]
    print(f"  {len(game_btns)} game buttons")

    for i, gb in enumerate(game_btns[:8]):
        print(f"\n  [{i+1}] {gb['text'][:35]}")
        dt0 = time.time()
        await click_exact(m, gb["data"])
        dm = await wait_stable(client, bot_ent, timeout=50, min_len=30)
        dt1 = time.time()

        if dm:
            d_txt = txt(dm)
            d_cb, d_url = btns(dm)

            for e, s in sports_map.items():
                if e in d_txt and s not in result["sports"]:
                    result["sports"].append(s)

            result["details"].append({
                "btn": gb["text"], "data": gb["data"],
                "text": d_txt, "cb": d_cb, "url": d_url,
                "lat_s": round(dt1-dt0, 2),
            })
            print(f"      {dt1-dt0:.1f}s | {d_txt[:70]}...")

            if await click(dm, "yg:all"):
                await asyncio.sleep(3)
                m = await get_latest(client, bot_ent, wait=0)
        else:
            result["details"].append({
                "btn": gb["text"], "data": gb["data"],
                "text": "NO_RESP", "lat_s": round(dt1-dt0, 2),
            })

        await asyncio.sleep(1)

    save("phase4_my_matches", result)

    raw = f"MY MATCHES VERBATIM\n{datetime.now().isoformat()}\nSports: {', '.join(result['sports'])}\n{'='*60}\n\n"
    raw += "=== LIST ===\n"
    for p in result["pages"]:
        raw += p["text"] + "\n\n"
    raw += "\n=== DETAILS ===\n"
    for d in result["details"]:
        raw += f"\n--- {d['btn']} (data={d['data']}) ---\n{d['text']}\n"
        raw += f"Latency: {d.get('lat_s','?')}s\n"
    save_txt("phase4_verbatim", raw)
    return result


# ──────────────────────────────────────────────────────────────
async def ux_audit(client, bot_ent):
    print("\n=== PHASE 5: UX AUDIT ===")
    tests = []

    async def probe(name, send, wait=3):
        t0 = time.time()
        await client.send_message(bot_ent, send)
        m = await get_latest(client, bot_ent, wait=wait)
        lat = round(time.time() - t0, 2)
        t = txt(m)
        c, u = btns(m)
        tests.append({"test": name, "sent": send, "response": t, "latency_s": lat,
                       "cb_btns": [b["text"] for b in c], "url_btns": [b["text"] for b in u],
                       "has_kb": bool(m and isinstance(m.reply_markup, ReplyKeyboardMarkup))})
        print(f"  {name}: {lat}s | {t[:60]}")
        return m

    await probe("help", "/help")
    await probe("profile", "👤 Profile")
    sm = await probe("settings", "⚙️ Settings")
    await probe("guide", "📖 Guide")
    await probe("menu", "/menu")
    await probe("subscribe", "/subscribe")
    await probe("status", "/status")
    await probe("gibberish", "asdf random 12345")
    await probe("start_onboarded", "/start", wait=4)

    # Back nav
    if sm:
        t0 = time.time()
        nav_ok = await click(sm, "nav:main") or await click(sm, "menu:home")
        if nav_ok:
            nm = await get_latest(client, bot_ent, wait=3)
            tests.append({"test": "back_nav", "latency_s": round(time.time()-t0,2),
                           "response": txt(nm)[:200]})

    save("phase5_ux", tests)
    raw = f"UX AUDIT\n{datetime.now().isoformat()}\n{'='*60}\n\n"
    for t in tests:
        raw += f"[{t['test']}] {t.get('latency_s','?')}s\nSent: {t.get('sent','')}\n{t.get('response','')}\n{'─'*40}\n\n"
    save_txt("phase5_ux_raw", raw)
    return tests


# ──────────────────────────────────────────────────────────────
async def main():
    print(f"QA-BASELINE-14 v2 | {TS}")
    client = await get_client()
    bot_ent = await client.get_entity(BOT)
    print(f"Bot: {bot_ent.id}")

    # Phase 1+2
    ob_status = await onboarding(client, bot_ent)
    print(f"\n  Onboarding: {ob_status}")

    # Phase 3
    ht = await hot_tips(client, bot_ent)

    # Phase 4
    mm = await my_matches(client, bot_ent)

    # Phase 5
    ux = await ux_audit(client, bot_ent)

    print(f"\n{'='*60}")
    print("DONE")
    print(f"  HT pages={len(ht.get('pages',[]))} details={len(ht.get('details',[]))}")
    print(f"  MM pages={len(mm.get('pages',[]))} details={len(mm.get('details',[]))} sports={mm.get('sports',[])}")
    print(f"  UX tests={len(ux)}")

    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
