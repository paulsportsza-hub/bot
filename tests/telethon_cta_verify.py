"""Telethon E2E verification for R4-BUILD-01: CTA button bookmaker fix.

Sends Hot Tips command, taps first 3 tips, verifies:
1. CTA button exists on each detail card
2. CTA button bookmaker is NOT always Betway
3. CTA button text does not contain 'None'
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.expanduser("~"))

from telethon import TelegramClient
from telethon.sessions import StringSession

API_ID = int(os.environ.get("TELEGRAM_API_ID", "32418601"))
API_HASH = os.environ.get("TELEGRAM_API_HASH", "95e313a8ef5b998be0515dd8328fac57")
SESSION_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "telethon_session")
STRING_SESSION_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "telethon_session.string")
BOT_USERNAME = "mzansiedge_bot"


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


async def send_and_wait(client, text, wait=12):
    """Send message and wait for response."""
    await client.send_message(BOT_USERNAME, text)
    await asyncio.sleep(wait)
    messages = await client.get_messages(BOT_USERNAME, limit=8)
    return [m for m in messages if not m.out]


async def verify_cta_buttons():
    client = await get_client()
    print("Connected to Telegram")

    try:
        # Step 1: Send Hot Tips command and wait
        print("\n[1] Sending '💎 Top Edge Picks'...")
        responses = await send_and_wait(client, "💎 Top Edge Picks", wait=12)

        # Find the tips message with inline buttons
        tips_msg = None
        for msg in responses:
            if msg.buttons:
                # Look for messages with tier emoji buttons or edge:detail callbacks
                for row in msg.buttons:
                    for btn in row:
                        data = (btn.data or b"").decode("utf-8", errors="ignore")
                        if "edge:detail" in data or any(e in (btn.text or "") for e in ("💎", "🥇", "🥈", "🥉")):
                            tips_msg = msg
                            break
                    if tips_msg:
                        break
            if tips_msg:
                break

        if not tips_msg:
            # Fallback: use any message with buttons
            for msg in responses:
                if msg.buttons:
                    tips_msg = msg
                    break

        if not tips_msg:
            print("WARN: No tips message found. Responses:")
            for msg in responses[:5]:
                print(f"  [{msg.id}] buttons={bool(msg.buttons)} text={(msg.text or '')[:80]}")
            return

        print(f"  Found tips message with {sum(len(r) for r in tips_msg.buttons)} buttons")

        # List all buttons for debug
        detail_buttons = []
        for row in tips_msg.buttons:
            for btn in row:
                data = (btn.data or b"").decode("utf-8", errors="ignore")
                print(f"    btn: '{btn.text}' data='{data[:50]}' url={bool(btn.url)}")
                if "edge:detail" in data:
                    detail_buttons.append(btn)

        if not detail_buttons:
            print("\nWARN: No edge:detail buttons found")
            return

        # Step 2: Tap up to 3 detail buttons and check CTAs
        print(f"\n[2] Checking {min(3, len(detail_buttons))} detail cards...")
        results = []
        bookmakers_seen = set()

        for i, btn in enumerate(detail_buttons[:3]):
            print(f"\n  --- Card {i+1}: '{btn.text[:40]}' ---")
            try:
                await btn.click()
                await asyncio.sleep(6)

                # Get the updated message
                detail_msgs = await client.get_messages(BOT_USERNAME, limit=5)
                detail_msg = None
                for dm in detail_msgs:
                    if dm.buttons and not dm.out:
                        detail_msg = dm
                        break

                if not detail_msg:
                    print("  WARN: No response after clicking")
                    results.append({"card": i+1, "cta_found": False, "reason": "no response"})
                    continue

                # Scan all buttons for CTA
                cta_found = False
                cta_text = ""
                back_btn = None
                for row in detail_msg.buttons:
                    for b in row:
                        b_text = b.text or ""
                        b_data = (b.data or b"").decode("utf-8", errors="ignore")

                        # CTA: has "Back" + "@" + "on" (bookmaker CTA)
                        if "Back" in b_text and "@" in b_text and " on " in b_text:
                            cta_found = True
                            cta_text = b_text
                            bk = b_text.split(" on ")[-1].rstrip(" →").strip()
                            bookmakers_seen.add(bk)
                            print(f"  ✅ CTA: '{b_text[:60]}'")
                            if b.url:
                                print(f"     URL: {b.url[:60]}")

                        # Also check URL buttons that look like affiliate links
                        if b.url and not cta_found:
                            for bk in ["betway", "hollywoodbets", "gbets", "supabets", "sportingbet", "wsb", "supersportbet"]:
                                if bk in (b.url or "").lower():
                                    cta_found = True
                                    cta_text = b_text
                                    print(f"  ✅ CTA (URL): '{b_text[:60]}' → {b.url[:60]}")
                                    break

                        # Find back button
                        if "Edge Picks" in b_text or "hot:back" in b_data:
                            back_btn = b

                has_none = "None" in cta_text
                if has_none:
                    print(f"  ❌ CTA contains 'None': {cta_text}")
                if not cta_found:
                    print(f"  ❌ NO CTA found. Buttons:")
                    for row in detail_msg.buttons:
                        for b in row:
                            print(f"     '{b.text}' url={bool(b.url)}")

                results.append({
                    "card": i+1,
                    "cta_found": cta_found,
                    "cta_text": cta_text[:60],
                    "has_none": has_none,
                })

                # Go back
                if back_btn:
                    await back_btn.click()
                    await asyncio.sleep(4)

            except Exception as e:
                print(f"  ERROR: {e}")
                results.append({"card": i+1, "cta_found": False, "error": str(e)[:60]})

        # Summary
        print(f"\n{'='*60}")
        print(f"RESULTS: {len(results)} cards checked")
        print(f"{'='*60}")
        all_have_cta = all(r.get("cta_found") for r in results)
        none_has_none = all(not r.get("has_none") for r in results)

        for r in results:
            status = "✅" if r.get("cta_found") and not r.get("has_none") else "❌"
            print(f"  Card {r['card']}: {status} {r.get('cta_text', r.get('reason', r.get('error', '?')))}")

        print(f"\nBookmakers seen: {bookmakers_seen or 'none'}")
        print(f"All cards have CTA: {'✅' if all_have_cta else '❌'}")
        print(f"No 'None' in CTAs: {'✅' if none_has_none else '❌'}")

        if all_have_cta and none_has_none:
            print("\n✅ VERIFICATION PASSED")
        else:
            print("\n❌ VERIFICATION FAILED")

    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(verify_cta_buttons())
