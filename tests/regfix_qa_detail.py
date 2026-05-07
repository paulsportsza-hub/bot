"""REGFIX-QA-01 Part 2: Detail capture with Diamond override + upgrade flow."""
from __future__ import annotations
import asyncio, json, os, re, time
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.sessions import StringSession
load_dotenv()

BOT = "mzansiedge_bot"
API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "")
SESSION_PATH = Path("data/telethon_qa_session.string")
from config import BOT_ROOT
RAW_PATH = BOT_ROOT.parent / "reports" / "REGFIX-QA-01-raw-captures.txt"
RESULTS_PATH = BOT_ROOT.parent / "reports" / "REGFIX-QA-01-results.json"
REPLY_TIMEOUT = 20

async def last_id(client):
    msgs = await client.get_messages(BOT, limit=1)
    return msgs[0].id if msgs else 0

async def send_wait(client, text, timeout=REPLY_TIMEOUT):
    lid = await last_id(client)
    await client.send_message(BOT, text)
    await asyncio.sleep(2)
    deadline = time.time() + timeout
    while time.time() < deadline:
        msgs = await client.get_messages(BOT, limit=5)
        for m in msgs:
            if m.id > lid and not m.out:
                return m
        await asyncio.sleep(1)
    return None

async def click_btn(client, msg, data_str, timeout=10):
    if msg and msg.buttons:
        for row in msg.buttons:
            for btn in row:
                if btn.data and btn.data.decode() == data_str:
                    await btn.click()
                    await asyncio.sleep(3)
                    msgs = await client.get_messages(BOT, ids=[msg.id])
                    return msgs[0] if msgs else None
    return None

async def wait_content(client, msg_id, timeout=60):
    deadline = time.time() + timeout
    spinners = ["Loading", "Scanning", "Analysing", "⚽ .", "🏉 .", "🏏 ."]
    last_t = ""
    stable = 0
    while time.time() < deadline:
        msgs = await client.get_messages(BOT, ids=[msg_id])
        if msgs and msgs[0]:
            t = msgs[0].text or ""
            if len(t) > 100 and not any(s in t for s in spinners):
                return msgs[0]
            if t == last_t and len(t) > 50:
                stable += 1
                if stable >= 3: return msgs[0]
            else:
                stable = 0
            last_t = t
        await asyncio.sleep(2)
    msgs = await client.get_messages(BOT, ids=[msg_id])
    return msgs[0] if msgs else None

def get_buttons(msg):
    btns = []
    if msg and msg.buttons:
        for row in msg.buttons:
            for btn in row:
                btns.append({"text": btn.text, "data": btn.data.decode() if btn.data else None, "url": btn.url if hasattr(btn,"url") and btn.url else None})
    return btns

async def run():
    session_str = SESSION_PATH.read_text().strip()
    client = TelegramClient(StringSession(session_str), API_ID, API_HASH)
    await client.start()

    captures = []
    cards = []

    print("=" * 60)
    print("REGFIX-QA-01 Part 2: Detail Captures")
    print(f"Started: {datetime.now().isoformat()}")
    print("=" * 60)

    # ── A. Tap upgrade button to see upgrade flow (Gold tier) ──
    print("\n[A] Testing upgrade flow (Gold tier)...")
    msg = await send_wait(client, "💎 Top Edge Picks", timeout=30)
    if msg:
        msg = await wait_content(client, msg.id)
        picks_id = msg.id

        # Tap first locked button
        btns = get_buttons(msg)
        upgrade_btn = None
        for b in btns:
            if b["data"] and "hot:upgrade:" in b["data"]:
                upgrade_btn = b
                break

        if upgrade_btn:
            print(f"  Tapping upgrade: {upgrade_btn['text']}")
            r = await click_btn(client, msg, upgrade_btn["data"])
            if r:
                r = await wait_content(client, picks_id, timeout=15)
                captures.append(f"=== UPGRADE FLOW (Gold tapping Diamond) ===\n{r.text}\n\nBUTTONS:\n{json.dumps(get_buttons(r), indent=2)}")
                print(f"  Upgrade screen: {len(r.text or '')} chars")

                # Go back
                for b in get_buttons(r):
                    if b["data"] and "hot:back" in b["data"]:
                        await click_btn(client, r, b["data"])
                        break

    await asyncio.sleep(2)

    # ── B. My Matches game breakdown ──
    print("\n[B] My Matches game breakdown...")
    msg = await send_wait(client, "⚽ My Matches", timeout=20)
    if msg:
        msg = await wait_content(client, msg.id, timeout=20)
        mm_id = msg.id
        btns = get_buttons(msg)

        for b in btns:
            if b["data"] and "yg:game:" in b["data"]:
                print(f"  Tapping: {b['text']}")
                r = await click_btn(client, msg, b["data"])
                if r:
                    r = await wait_content(client, mm_id, timeout=60)
                    detail_text = r.text or ""
                    detail_btns = get_buttons(r)
                    captures.append(f"=== MY MATCHES DETAIL: {b['text']} ===\n{detail_text}\n\nBUTTONS:\n{json.dumps(detail_btns, indent=2)}")
                    print(f"    {len(detail_text)} chars")

                    cards.append({
                        "source": "my_matches",
                        "btn_text": b["text"],
                        "detail_text": detail_text,
                        "buttons": detail_btns,
                    })

                    # Go back
                    for bb in detail_btns:
                        if bb["data"] and ("yg:all" in bb["data"] or "hot:back" in bb["data"]):
                            await click_btn(client, r, bb["data"])
                            await asyncio.sleep(2)
                            break

                    # Re-fetch
                    msgs = await client.get_messages(BOT, ids=[mm_id])
                    if msgs and msgs[0]:
                        msg = msgs[0]
                await asyncio.sleep(2)

    await asyncio.sleep(2)

    # ── C. Set Diamond tier via /qa and re-run Edge Picks ──
    print("\n[C] Setting Diamond tier via /qa set_diamond...")
    qa_msg = await send_wait(client, "/qa set_diamond", timeout=15)
    if qa_msg:
        captures.append(f"=== /qa set_diamond ===\n{qa_msg.text}")
        print(f"  Response: {(qa_msg.text or '')[:100]}")

    await asyncio.sleep(2)

    print("\n[D] Re-running Edge Picks as Diamond...")
    msg = await send_wait(client, "💎 Top Edge Picks", timeout=30)
    if msg:
        msg = await wait_content(client, msg.id)
        picks_id = msg.id

        page0_text = msg.text or ""
        page0_btns = get_buttons(msg)
        captures.append(f"=== DIAMOND EDGE PICKS PAGE 0 ===\n{page0_text}\n\nBUTTONS:\n{json.dumps(page0_btns, indent=2)}")
        print(f"  Page 0: {len(page0_text)} chars, {len(page0_btns)} buttons")

        # Browse pages
        all_detail_btns = []
        pages = [{"page": 0, "btns": page0_btns}]

        for btn in page0_btns:
            if btn["data"] and "edge:detail:" in btn["data"]:
                all_detail_btns.append(btn)

        # Navigate pages
        page_num = 1
        while page_num < 10:
            next_data = f"hot:page:{page_num}"
            has_next = any(b["data"] == next_data for b in page0_btns)
            if not has_next:
                break

            r = await click_btn(client, msg, next_data)
            if r:
                r = await wait_content(client, picks_id, timeout=15)
                msg = r
                ptext = msg.text or ""
                pbtns = get_buttons(msg)
                captures.append(f"=== DIAMOND EDGE PICKS PAGE {page_num} ===\n{ptext}\n\nBUTTONS:\n{json.dumps(pbtns, indent=2)}")
                pages.append({"page": page_num, "btns": pbtns})
                print(f"  Page {page_num}: {len(ptext)} chars, {len(pbtns)} buttons")

                for btn in pbtns:
                    if btn["data"] and "edge:detail:" in btn["data"]:
                        all_detail_btns.append(btn)

                page0_btns = pbtns  # for next iteration
                page_num += 1
            else:
                break

        print(f"\n  Found {len(all_detail_btns)} detail buttons as Diamond")

        # Go back to page 0
        if page_num > 1:
            await click_btn(client, msg, "hot:page:0")
            await asyncio.sleep(2)
            msgs = await client.get_messages(BOT, ids=[picks_id])
            if msgs and msgs[0]:
                msg = msgs[0]

        # Tap into each detail
        for i, btn in enumerate(all_detail_btns):
            mk = btn["data"].replace("edge:detail:", "")
            print(f"\n  [{i+1}/{len(all_detail_btns)}] {mk[:60]}...")

            r = await click_btn(client, msg, btn["data"])
            if r:
                r = await wait_content(client, picks_id, timeout=60)
                detail_text = r.text or ""
                detail_btns = get_buttons(r)

                captures.append(f"=== DIAMOND CARD {i+1}: {mk} ===\n"
                              f"LIST BUTTON: {btn['text']}\n\n"
                              f"FULL DETAIL:\n{detail_text}\n\n"
                              f"BUTTONS:\n{json.dumps(detail_btns, indent=2)}")

                cards.append({
                    "index": i+1,
                    "source": "edge_picks_diamond",
                    "match_key": mk,
                    "btn_text": btn["text"],
                    "detail_text": detail_text,
                    "detail_length": len(detail_text),
                    "buttons": detail_btns,
                    "has_setup": "📋" in detail_text or "Setup" in detail_text,
                    "has_edge": "🎯" in detail_text or "The Edge" in detail_text,
                    "has_risk": "⚠" in detail_text or "Risk" in detail_text,
                    "has_verdict": "🏆" in detail_text or "Verdict" in detail_text,
                    "has_kickoff": "📅" in detail_text,
                    "has_broadcast": "📺" in detail_text,
                    "has_cta": any(b.get("url") for b in detail_btns),
                    "has_back": any("back" in (b.get("data") or "").lower() for b in detail_btns),
                    "locked": "🔒" in detail_text,
                    "tier": "diamond" if "💎" in detail_text else "gold" if "🥇" in detail_text else "silver" if "🥈" in detail_text else "bronze" if "🥉" in detail_text else "unknown",
                })

                secs = f"S={'Y' if '📋' in detail_text else 'N'} E={'Y' if '🎯' in detail_text else 'N'} R={'Y' if '⚠' in detail_text else 'N'} V={'Y' if '🏆' in detail_text else 'N'}"
                print(f"    {len(detail_text)} chars | {secs}")

                # Go back
                back_found = False
                for bb in detail_btns:
                    if bb["data"] and "hot:back" in bb["data"]:
                        await click_btn(client, r, bb["data"])
                        await asyncio.sleep(1)
                        back_found = True
                        break

                if not back_found:
                    await click_btn(client, r, "hot:page:0")
                    await asyncio.sleep(1)

                msgs = await client.get_messages(BOT, ids=[picks_id])
                if msgs and msgs[0]:
                    msg = msgs[0]

            await asyncio.sleep(1)

    # ── E. Reset QA tier ──
    print("\n[E] Resetting QA tier...")
    reset_msg = await send_wait(client, "/qa reset", timeout=10)
    if reset_msg:
        print(f"  {(reset_msg.text or '')[:80]}")

    await client.disconnect()

    # ── Save ──
    print(f"\n[F] Saving {len(captures)} captures...")

    # Append to existing captures
    existing = RAW_PATH.read_text() if RAW_PATH.exists() else ""
    RAW_PATH.write_text(
        existing + "\n\n" +
        f"{'='*60}\nPART 2 — DETAIL CAPTURES (Diamond Override)\n{'='*60}\n\n" +
        "\n\n".join(captures)
    )

    # Update results
    existing_results = json.loads(RESULTS_PATH.read_text()) if RESULTS_PATH.exists() else {}
    existing_results["diamond_cards"] = cards
    existing_results["diamond_detail_count"] = len([c for c in cards if c.get("source") == "edge_picks_diamond"])
    RESULTS_PATH.write_text(json.dumps(existing_results, indent=2, default=str))

    print(f"\n{'='*60}")
    print(f"DETAIL CAPTURE COMPLETE")
    print(f"Diamond cards: {len([c for c in cards if c.get('source') == 'edge_picks_diamond'])}")
    print(f"My Matches cards: {len([c for c in cards if c.get('source') == 'my_matches'])}")
    print(f"{'='*60}")

    return cards

if __name__ == "__main__":
    asyncio.run(run())
