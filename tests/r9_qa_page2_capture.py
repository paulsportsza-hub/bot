"""R9-QA-02: Capture cards 5-8 from page 2."""
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


def extract_buttons(msg):
    buttons = []
    if not msg or not msg.buttons:
        return buttons
    for row_idx, row in enumerate(msg.buttons):
        for col_idx, btn in enumerate(row):
            data = (btn.data or b"").decode("utf-8", errors="ignore") if btn.data else ""
            buttons.append({
                "text": btn.text or "",
                "data": data,
                "url": btn.url or "",
                "row": row_idx,
                "col": col_idx,
            })
    return buttons


async def run():
    client = await get_client()
    print("Connected")
    try:
        # Step 1: Send Top Edge Picks
        print("Sending Top Edge Picks...")
        await client.send_message(BOT_USERNAME, "💎 Top Edge Picks")
        await asyncio.sleep(15)

        # Step 2: Find and click Next
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
            print("ERROR: No tips message found")
            return

        # Click Next
        next_btn = None
        for row in tips_msg.buttons:
            for btn in row:
                if "Next" in (btn.text or ""):
                    next_btn = btn
                    break
            if next_btn:
                break

        if not next_btn:
            print("ERROR: No Next button found")
            return

        print("Clicking Next to page 2...")
        await next_btn.click()
        await asyncio.sleep(8)

        # Step 3: Get page 2 message
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
            print("ERROR: No page 2 message found")
            return

        # Find detail buttons on page 2
        detail_buttons = []
        for row in page2_msg.buttons:
            for btn in row:
                data = (btn.data or b"").decode("utf-8", errors="ignore")
                if "edge:detail" in data:
                    detail_buttons.append(btn)

        print(f"Found {len(detail_buttons)} cards on page 2")

        # Step 4: Tap each card
        for i, btn in enumerate(detail_buttons):
            card_num = i + 5  # Page 2 starts at card 5
            print(f"\n--- Card {card_num}: '{btn.text}' ---")
            t0 = time.time()
            await btn.click()
            await asyncio.sleep(12)
            elapsed = time.time() - t0

            msgs = await client.get_messages(BOT_USERNAME, limit=5)
            detail_msg = None
            for m in msgs:
                if not m.out and m.buttons:
                    detail_msg = m
                    break
            if not detail_msg:
                for m in msgs:
                    if not m.out:
                        detail_msg = m
                        break

            if not detail_msg:
                print(f"  No response for card {card_num}")
                continue

            text = detail_msg.text or ""
            buttons = extract_buttons(detail_msg)

            # Save raw capture
            fname = os.path.join(CAPTURE_DIR, f"card_{card_num}_detail.txt")
            with open(fname, "w") as f:
                f.write(text)
                f.write("\n\n--- BUTTONS ---\n")
                for b in buttons:
                    f.write(f"  {b['text']} | data={b['data'][:50]} | url={b['url'][:60] if b['url'] else ''}\n")

            print(f"  Saved to {fname}")
            print(f"  Time: {elapsed:.1f}s")
            print(f"  Text: {text[:120]}...")

            # Print CTA
            for b in buttons:
                if b["url"] and "Back" in b["text"] and "@" in b["text"]:
                    print(f"  CTA: {b['text']}")
                    print(f"  URL: {b['url'][:70]}")
                elif b["url"] and not b["text"].startswith("↩"):
                    print(f"  URL btn: {b['text']} → {b['url'][:60]}")

            # Check Compare Odds
            has_compare = any("Compare" in b["text"] or "odds:compare" in b["data"] for b in buttons)
            print(f"  Compare Odds: {'✅' if has_compare else '❌'}")

            # Navigate back to page 2
            back_btn = None
            for row in detail_msg.buttons:
                for b in row:
                    bd = (b.data or b"").decode("utf-8", errors="ignore")
                    if "hot:back" in bd or "Edge Picks" in (b.text or ""):
                        back_btn = b
                        break
                if back_btn:
                    break

            if back_btn:
                await back_btn.click()
                await asyncio.sleep(5)
            else:
                # Resend and navigate to page 2
                await client.send_message(BOT_USERNAME, "💎 Top Edge Picks")
                await asyncio.sleep(12)
                msgs = await client.get_messages(BOT_USERNAME, limit=5)
                for m in msgs:
                    if m.buttons and not m.out:
                        for row in m.buttons:
                            for btn2 in row:
                                if "Next" in (btn2.text or ""):
                                    await btn2.click()
                                    await asyncio.sleep(8)
                                    break

        print("\nDone!")

    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(run())
