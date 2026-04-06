"""R9-QA-01 Part 2: Capture cards 5-8 from page 2."""
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from telethon import TelegramClient
from telethon.sessions import StringSession

API_ID = int(os.environ.get("TELEGRAM_API_ID", "32418601"))
API_HASH = os.environ.get("TELEGRAM_API_HASH", "95e313a8ef5b998be0515dd8328fac57")
SESSION_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "telethon_session")
STRING_SESSION_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "telethon_session.string")
BOT_USERNAME = "mzansiedge_bot"
from config import BOT_ROOT
CAPTURE_DIR = str(BOT_ROOT.parent / "reports" / "r9-qa-captures")


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


async def run():
    client = await get_client()
    print("Connected")
    try:
        # Navigate to page 2
        print("Sending Top Edge Picks...")
        await client.send_message(BOT_USERNAME, "💎 Top Edge Picks")
        await asyncio.sleep(12)

        msgs = await client.get_messages(BOT_USERNAME, limit=5)
        tips_msg = None
        for m in msgs:
            if m.buttons and not m.out:
                for row in m.buttons:
                    for btn in row:
                        data = (btn.data or b"").decode("utf-8", errors="ignore")
                        if "edge:detail" in data:
                            tips_msg = m
                            break
                    if tips_msg:
                        break
            if tips_msg:
                break

        if not tips_msg:
            print("No tips message found")
            return

        # Go to page 2
        next_btn = None
        for row in tips_msg.buttons:
            for btn in row:
                if "Next" in (btn.text or ""):
                    next_btn = btn
                    break
            if next_btn:
                break

        if not next_btn:
            print("No Next button found")
            return

        print("Going to page 2...")
        await next_btn.click()
        await asyncio.sleep(8)

        msgs = await client.get_messages(BOT_USERNAME, limit=5)
        page2_msg = None
        for m in msgs:
            if m.buttons and not m.out:
                for row in m.buttons:
                    for btn in row:
                        data = (btn.data or b"").decode("utf-8", errors="ignore")
                        if "edge:detail" in data:
                            page2_msg = m
                            break
                    if page2_msg:
                        break
            if page2_msg:
                break

        if not page2_msg:
            print("No page 2 message found")
            return

        # Get detail buttons
        detail_buttons = []
        for row in page2_msg.buttons:
            for btn in row:
                data = (btn.data or b"").decode("utf-8", errors="ignore")
                if "edge:detail" in data:
                    detail_buttons.append(btn)

        print(f"Found {len(detail_buttons)} detail buttons on page 2")

        # Tap each card
        for i, btn in enumerate(detail_buttons):
            card_num = i + 5  # Cards 5-8
            print(f"\n--- Card {card_num}: '{btn.text}' ---")

            t0 = time.time()
            await btn.click()
            await asyncio.sleep(12)
            elapsed = time.time() - t0

            msgs = await client.get_messages(BOT_USERNAME, limit=5)
            detail_msg = None
            for m in msgs:
                if not m.out and (m.buttons or (m.text and "📋" in (m.text or ""))):
                    detail_msg = m
                    break

            if not detail_msg:
                print(f"  No detail response (elapsed {elapsed:.1f}s)")
                continue

            text = detail_msg.text or ""
            print(f"  Time: {elapsed:.1f}s")
            print(f"  Text length: {len(text)}")

            # Save capture
            with open(os.path.join(CAPTURE_DIR, f"card_{card_num}_detail.txt"), "w") as f:
                f.write(text)
                f.write("\n\n--- BUTTONS ---\n")
                if detail_msg.buttons:
                    for row in detail_msg.buttons:
                        for b in row:
                            bd = (b.data or b"").decode("utf-8", errors="ignore")
                            f.write(f"  {b.text} | data={bd[:50]} | url={b.url or ''}\n")

            # Extract key info
            if detail_msg.buttons:
                for row in detail_msg.buttons:
                    for b in row:
                        if b.url and "Back" in (b.text or ""):
                            print(f"  CTA: {b.text[:60]}")
                            print(f"  URL: {b.url[:60]}")
                            # Check match
                            if " on " in (b.text or ""):
                                bk = b.text.split(" on ")[-1].rstrip(" →").strip()
                                url_lower = b.url.lower()
                                matched = any(x in url_lower for x in [bk.lower().replace(" ", ""), bk.lower().split(".")[0] if "." in bk.lower() else bk.lower()])
                                print(f"  BK match: {'✅' if matched else '❌'}")
                        elif b.url:
                            print(f"  URL btn: {b.text[:40]} → {b.url[:60]}")

            # Check for Compare Odds
            has_compare = False
            if detail_msg.buttons:
                for row in detail_msg.buttons:
                    for b in row:
                        bd = (b.data or b"").decode("utf-8", errors="ignore")
                        if "Compare" in (b.text or "") or "odds:compare" in bd:
                            has_compare = True
            print(f"  Compare Odds: {'✅' if has_compare else '❌'}")

            # Extract edge/verdict lines
            for line in text.split("\n"):
                if "sits on" in line.lower() or ("EV" in line and "%" in line):
                    print(f"  Edge: {line.strip()[:80]}")
                if "0%" in line and "·" in line:
                    print(f"  ⚠️ ZERO PROB: {line.strip()[:80]}")

            # Navigate back
            back_clicked = False
            if detail_msg.buttons:
                for row in detail_msg.buttons:
                    for b in row:
                        bd = (b.data or b"").decode("utf-8", errors="ignore")
                        if "hot:back" in bd or "Edge Picks" in (b.text or ""):
                            await b.click()
                            await asyncio.sleep(4)
                            back_clicked = True
                            break
                    if back_clicked:
                        break

            if not back_clicked:
                await client.send_message(BOT_USERNAME, "💎 Top Edge Picks")
                await asyncio.sleep(8)
                # Navigate to page 2 again
                msgs = await client.get_messages(BOT_USERNAME, limit=5)
                for m in msgs:
                    if m.buttons and not m.out:
                        for row in m.buttons:
                            for btn2 in row:
                                if "Next" in (btn2.text or ""):
                                    await btn2.click()
                                    await asyncio.sleep(5)
                                    break

    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(run())
