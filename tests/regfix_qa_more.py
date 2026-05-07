"""REGFIX-QA-01 Part 3: Capture remaining Diamond card details."""
from __future__ import annotations
import asyncio, json, os, time
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

async def last_id(client):
    msgs = await client.get_messages(BOT, limit=1)
    return msgs[0].id if msgs else 0

async def send_wait(client, text, timeout=20):
    lid = await last_id(client)
    await client.send_message(BOT, text)
    await asyncio.sleep(2)
    deadline = time.time() + timeout
    while time.time() < deadline:
        msgs = await client.get_messages(BOT, limit=5)
        for m in msgs:
            if m.id > lid and not m.out: return m
        await asyncio.sleep(1)
    return None

async def click_and_get(client, msg, data_str):
    """Click a button by data and return updated message."""
    if not msg or not msg.buttons: return None
    for row in msg.buttons:
        for btn in row:
            if btn.data and btn.data.decode() == data_str:
                await btn.click()
                await asyncio.sleep(4)
                msgs = await client.get_messages(BOT, ids=[msg.id])
                return msgs[0] if msgs else None
    return None

async def stable_content(client, msg_id, timeout=60):
    """Wait until message content stabilizes."""
    deadline = time.time() + timeout
    last_t = ""
    stable = 0
    while time.time() < deadline:
        msgs = await client.get_messages(BOT, ids=[msg_id])
        if msgs and msgs[0]:
            t = msgs[0].text or ""
            if t == last_t and len(t) > 100:
                stable += 1
                if stable >= 2: return msgs[0]
            else:
                stable = 0
            last_t = t
        await asyncio.sleep(2.5)
    msgs = await client.get_messages(BOT, ids=[msg_id])
    return msgs[0] if msgs else None

def btns(msg):
    r = []
    if msg and msg.buttons:
        for row in msg.buttons:
            for b in row:
                r.append({"text": b.text, "data": b.data.decode() if b.data else None, "url": b.url if hasattr(b,"url") and b.url else None})
    return r

async def run():
    session_str = SESSION_PATH.read_text().strip()
    client = TelegramClient(StringSession(session_str), API_ID, API_HASH)
    await client.start()
    captures = []

    print("REGFIX-QA Part 3: Remaining Diamond details")
    print("=" * 50)

    # Set Diamond
    r = await send_wait(client, "/qa set_diamond")
    print(f"QA set: {(r.text if r else 'no response')[:60]}")
    await asyncio.sleep(1)

    # Get Edge Picks
    msg = await send_wait(client, "💎 Top Edge Picks", timeout=30)
    if not msg:
        print("FATAL: no response")
        await client.disconnect()
        return
    msg = await stable_content(client, msg.id, timeout=30)
    pid = msg.id
    print(f"Page 0: {len(msg.text or '')} chars")

    # Cards to capture from page 0
    targets_p0 = [
        "edge:detail:bulls_vs_munster_2026-03-28",
        "edge:detail:brentford_vs_everton_2026-04-11",
        "edge:detail:paris_saint_germain_vs_liverpool_2026-04-07",
        "edge:detail:chelsea_vs_manchester_united_2026-04-18",
    ]

    for i, target in enumerate(targets_p0):
        mk = target.replace("edge:detail:", "")
        print(f"\n[{i+1}] {mk}...")

        # Make sure we're on page 0
        if i > 0:
            r2 = await click_and_get(client, msg, "hot:page:0")
            if r2:
                msg = r2
                await asyncio.sleep(1)
            else:
                # Try re-fetching
                msgs = await client.get_messages(BOT, ids=[pid])
                if msgs and msgs[0]: msg = msgs[0]

        # Click detail
        r = await click_and_get(client, msg, target)
        if not r:
            print(f"  Click failed — trying direct")
            # Try clicking directly
            if msg.buttons:
                for row in msg.buttons:
                    for btn in row:
                        if btn.data and target in btn.data.decode():
                            await btn.click()
                            await asyncio.sleep(4)
                            break
            r = await stable_content(client, pid, timeout=30)

        if r:
            r = await stable_content(client, pid, timeout=45)
            txt = r.text or ""
            b = btns(r)
            captures.append(f"=== DIAMOND CARD: {mk} ===\nFULL DETAIL:\n{txt}\n\nBUTTONS:\n{json.dumps(b, indent=2)}")
            print(f"  {len(txt)} chars")
            msg = r

            # Back
            for bb in b:
                if bb["data"] and "hot:back" in bb["data"]:
                    r2 = await click_and_get(client, r, bb["data"])
                    if r2: msg = r2
                    break
            await asyncio.sleep(1)

    # Page 1 cards
    print("\nNavigating to page 1...")
    r = await click_and_get(client, msg, "hot:page:1")
    if r:
        msg = r
        msg = await stable_content(client, pid, timeout=15)
        print(f"Page 1: {len(msg.text or '')} chars")

    targets_p1 = [
        "edge:detail:everton_vs_liverpool_2026-04-19",
        "edge:detail:brentford_vs_fulham_2026-04-18",
        "edge:detail:west_ham_vs_wolves_2026-04-10",
        "edge:detail:crystal_palace_vs_west_ham_2026-04-20",
    ]

    for i, target in enumerate(targets_p1):
        mk = target.replace("edge:detail:", "")
        print(f"\n[{i+5}] {mk}...")

        if i > 0:
            r2 = await click_and_get(client, msg, "hot:page:1")
            if r2:
                msg = r2
                await asyncio.sleep(1)

        r = await click_and_get(client, msg, target)
        if r:
            r = await stable_content(client, pid, timeout=45)
            txt = r.text or ""
            b = btns(r)
            captures.append(f"=== DIAMOND CARD: {mk} ===\nFULL DETAIL:\n{txt}\n\nBUTTONS:\n{json.dumps(b, indent=2)}")
            print(f"  {len(txt)} chars")
            msg = r

            for bb in b:
                if bb["data"] and "hot:back" in bb["data"]:
                    r2 = await click_and_get(client, r, bb["data"])
                    if r2: msg = r2
                    break
            await asyncio.sleep(1)

    # Reset
    await send_wait(client, "/qa reset", timeout=10)
    await client.disconnect()

    # Append captures
    existing = RAW_PATH.read_text() if RAW_PATH.exists() else ""
    RAW_PATH.write_text(
        existing + "\n\n" +
        f"{'='*60}\nPART 3 — REMAINING DIAMOND DETAILS\n{'='*60}\n\n" +
        "\n\n".join(captures)
    )
    print(f"\nSaved {len(captures)} card captures")

if __name__ == "__main__":
    asyncio.run(run())
