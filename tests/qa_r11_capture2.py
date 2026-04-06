"""R11-QA-02 — Capture remaining 6 cards (page 1 + page 2)."""
from __future__ import annotations
import asyncio, json, os, time
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.sessions import StringSession

load_dotenv()
BOT = "mzansiedge_bot"
API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "")
SESSION_PATH = Path("data/telethon_session.string")
from config import BOT_ROOT
REPORT_DIR = BOT_ROOT.parent / "reports" / "r11-qa-02"

CARDS_TO_CAPTURE = [
    # Page 1 cards
    ("hot:page:1", "edge:detail:crystal_palace_vs_west_ham_2026-04-20"),
    ("hot:page:1", "edge:detail:west_ham_vs_wolves_2026-04-10"),
    ("hot:page:1", "edge:detail:chelsea_vs_manchester_united_2026-04-18"),
    ("hot:page:1", "edge:detail:chelsea_vs_manchester_city_2026-04-12"),
    # Page 2 cards
    ("hot:page:2", "edge:detail:everton_vs_liverpool_2026-04-19"),
    ("hot:page:2", "edge:detail:zebre_vs_ulster_2026-03-28"),
]


async def _last_id(client):
    msgs = await client.get_messages(BOT, limit=1)
    return msgs[0].id if msgs else 0


async def send_wait(client, text, timeout=30):
    last_id = await _last_id(client)
    await client.send_message(BOT, text)
    await asyncio.sleep(2)
    deadline = time.time() + timeout
    while time.time() < deadline:
        msgs = await client.get_messages(BOT, limit=5)
        for m in msgs:
            if m.id > last_id and not m.out:
                return m
        await asyncio.sleep(1)
    return None


async def click_data(client, msg, data_prefix, timeout=30):
    if not msg or not msg.buttons:
        return None
    old_id = await _last_id(client)
    orig_id = msg.id

    for row in msg.buttons:
        for btn in row:
            if hasattr(btn, "data") and btn.data:
                cb = btn.data.decode() if isinstance(btn.data, bytes) else str(btn.data)
                if cb == data_prefix or cb.startswith(data_prefix):
                    try:
                        await btn.click()
                    except Exception as e:
                        print(f"  Click err: {e}")
                        return None

                    await asyncio.sleep(3)
                    deadline = time.time() + timeout
                    prev_text = ""
                    while time.time() < deadline:
                        # Check edited original
                        updated = await client.get_messages(BOT, ids=orig_id)
                        if updated and updated.text:
                            cur = updated.text
                            if cur != prev_text and not any(x in cur.lower() for x in ["loading", "analysing"]):
                                return updated
                            prev_text = cur
                        # Check new message
                        msgs = await client.get_messages(BOT, limit=5)
                        for m in msgs:
                            if m.id > old_id and not m.out:
                                if not any(x in (m.text or "").lower() for x in ["loading", "analysing"]):
                                    return m
                        await asyncio.sleep(2)
                    # Final
                    return await client.get_messages(BOT, ids=orig_id) or None
    return None


def extract_btns(msg):
    btns = []
    if msg and msg.buttons:
        for row in msg.buttons:
            for btn in row:
                cb = ""
                if hasattr(btn, "data") and btn.data:
                    cb = btn.data.decode() if isinstance(btn.data, bytes) else str(btn.data)
                elif hasattr(btn, "url") and btn.url:
                    cb = f"URL:{btn.url}"
                btns.append({"text": btn.text, "data": cb})
    return btns


async def main():
    session_str = SESSION_PATH.read_text().strip()
    client = TelegramClient(StringSession(session_str), API_ID, API_HASH)
    await client.start()
    print(f"Connected as: {(await client.get_me()).first_name}")

    # Set QA tier
    await send_wait(client, "/qa set_diamond")
    await asyncio.sleep(1)

    results = []

    for page_cb, card_cb in CARDS_TO_CAPTURE:
        match_key = card_cb.replace("edge:detail:", "")
        print(f"\n--- Capturing: {match_key} ---")

        # 1. Fresh list trigger
        list_msg = await send_wait(client, "💎 Top Edge Picks", timeout=30)
        if not list_msg:
            print("  ERROR: No list response")
            results.append({"match_key": match_key, "text": None, "error": "no list"})
            continue
        await asyncio.sleep(1)

        # 2. Navigate to correct page
        print(f"  Navigating to {page_cb}...")
        page_msg = await click_data(client, list_msg, page_cb, timeout=15)
        if not page_msg:
            print("  ERROR: Failed to navigate to page")
            results.append({"match_key": match_key, "text": None, "error": "page nav failed"})
            continue
        await asyncio.sleep(1)

        # 3. Tap the card
        print(f"  Tapping {card_cb}...")
        detail = await click_data(client, page_msg, card_cb, timeout=30)
        if detail and detail.text:
            print(f"  OK: {len(detail.text)} chars")
            print(f"  Preview: {detail.text[:120]}...")
            results.append({
                "match_key": match_key,
                "text": detail.text,
                "buttons": extract_btns(detail),
            })
        else:
            print("  FAILED to get detail")
            results.append({"match_key": match_key, "text": None, "error": "detail tap failed"})

        await asyncio.sleep(2)

    # Reset QA
    await send_wait(client, "/qa reset")

    # Append to existing captures
    existing = json.loads((REPORT_DIR / "captures.json").read_text())
    for r in results:
        if r.get("text"):
            # Replace failed entry or append
            found = False
            for i, ec in enumerate(existing["detail_cards"]):
                if ec.get("match_key") == r["match_key"]:
                    existing["detail_cards"][i] = r
                    found = True
                    break
            if not found:
                existing["detail_cards"].append(r)

    with open(REPORT_DIR / "captures.json", "w") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)

    # Append to raw text
    with open(REPORT_DIR / "raw_captures_p2.txt", "w") as f:
        f.write(f"R11-QA-02 Additional Card Captures — {datetime.now().isoformat()}\n")
        f.write("=" * 80 + "\n")
        for r in results:
            f.write(f"\n{'='*60}\n")
            f.write(f"Card: {r['match_key']}\n")
            f.write(f"{'='*60}\n")
            f.write(r.get("text") or f"(FAILED: {r.get('error', 'unknown')})")
            f.write("\n\nButtons:\n")
            for btn in r.get("buttons", []):
                f.write(f"  [{btn['text']}] → {btn['data']}\n")
            f.write("\n")

    print(f"\nDone. {sum(1 for r in results if r.get('text'))} of {len(results)} captured.")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
