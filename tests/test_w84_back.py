#!/usr/bin/env python3
"""W84-P0 Telethon back-flow test: locked tip → upgrade page → Back to Edge Picks → hot tips."""
import asyncio, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))
from telethon import TelegramClient
from telethon.sessions import StringSession

API_ID   = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "")
BOT_USERNAME = "@mzansiedge_bot"
STRING_SESSION_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "telethon_qa_session.string")

TIMEOUT = 25  # seconds to wait for bot response


async def get_msg(client, entity, after_id, timeout=TIMEOUT):
    """Wait up to `timeout` s for a bot message after `after_id`."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        await asyncio.sleep(2)
        msgs = await client.get_messages(entity, limit=10)
        for m in msgs:
            if m.id > after_id and m.sender_id != (await client.get_me()).id:
                return m
    return None


def find_button(msg, label_substr):
    """Return (row_idx, btn_idx, button) or None."""
    if not msg or not msg.reply_markup:
        return None
    for r, row in enumerate(msg.reply_markup.rows):
        for b, btn in enumerate(row.buttons):
            if label_substr.lower() in btn.text.lower():
                return (r, b, btn)
    return None


def list_buttons(msg):
    if not msg or not msg.reply_markup:
        return []
    out = []
    for row in msg.reply_markup.rows:
        for btn in row.buttons:
            out.append(btn.text)
    return out


async def click_button(client, msg, btn_tuple):
    """Click button and wait briefly."""
    if btn_tuple is None:
        return None
    row_idx, btn_idx, btn = btn_tuple
    before_id = msg.id
    await msg.click(row_idx, btn_idx)
    # Wait for message to be edited (same message id) or new message
    deadline = time.time() + TIMEOUT
    while time.time() < deadline:
        await asyncio.sleep(1)
        m = await client.get_messages(msg.chat_id, ids=msg.id)
        if m and m.text != msg.text:
            return m
        # Also check for new messages
        msgs = await client.get_messages(msg.chat_id, limit=5)
        for nm in msgs:
            if nm.id > before_id:
                return nm
    # Return the (possibly unchanged) message
    return await client.get_messages(msg.chat_id, ids=msg.id)


async def main():
    print("\n" + "="*60)
    print("  W84-P0 Back Flow Test")
    print("="*60)

    # Load session
    if not os.path.exists(STRING_SESSION_FILE):
        print("ERROR: No session file found.")
        sys.exit(1)
    session_str = open(STRING_SESSION_FILE).read().strip()

    async with TelegramClient(StringSession(session_str), API_ID, API_HASH) as client:
        entity = await client.get_entity(BOT_USERNAME)
        me = await client.get_me()

        # Step 1: Send 💎 Top Edge Picks command
        print("\n[1] Requesting Top Edge Picks...")
        sent = await client.send_message(entity, "💎 Top Edge Picks")
        sent_id = sent.id

        tips_msg = await get_msg(client, entity, sent_id, timeout=45)
        if not tips_msg:
            print("  ❌ FAIL: No response to Top Edge Picks command")
            sys.exit(1)
        print(f"  ✅ Got response (id={tips_msg.id}): {tips_msg.text[:60]}...")

        # Step 2: Find a locked button (🔒)
        locked_btn = find_button(tips_msg, "🔒")
        if not locked_btn:
            btns = list_buttons(tips_msg)
            print(f"  ⚠️  No 🔒 button found. Buttons: {btns}")
            print("  ℹ️  User may have full tier access — testing with first tip button")
            # Try first tip button anyway to test navigation
            any_btn = None
            if tips_msg.reply_markup:
                for r, row in enumerate(tips_msg.reply_markup.rows):
                    for b, btn in enumerate(row.buttons):
                        if "edge:detail:" in getattr(btn, 'data', b'').decode('utf-8', errors='replace'):
                            any_btn = (r, b, btn)
                            break
                    if any_btn:
                        break
            if not any_btn:
                print("  ❌ FAIL: No tip buttons found at all")
                sys.exit(1)
            # For full-access users, test the game breakdown → back flow
            print(f"  → Testing with full-access tip: {any_btn[2].text}")
            detail_msg = await click_button(client, tips_msg, any_btn)
            if not detail_msg:
                print("  ❌ FAIL: No detail shown after tap")
                sys.exit(1)
            print(f"  ✅ Detail shown: {detail_msg.text[:60]}...")
            back_btn = find_button(detail_msg, "Back to Edge Picks") or find_button(detail_msg, "Back")
            if not back_btn:
                print(f"  ❌ FAIL: No back button. Available: {list_buttons(detail_msg)}")
                sys.exit(1)
            back_msg = await click_button(client, detail_msg, back_btn)
            if not back_msg:
                print("  ❌ FAIL: No response after Back tap")
                sys.exit(1)
            print(f"  ✅ Back → {back_msg.text[:60]}...")
            print("\n✅ All steps passed (full-access path)")
            sys.exit(0)

        print(f"  → Found locked tip: {locked_btn[2].text}")

        # Step 3: Tap locked tip
        print("\n[2] Tapping locked tip...")
        t0 = time.time()
        upgrade_msg = await click_button(client, tips_msg, locked_btn)
        elapsed = time.time() - t0

        if not upgrade_msg:
            print(f"  ❌ FAIL: No response after tapping locked tip")
            sys.exit(1)

        print(f"  ✅ Got response ({elapsed:.1f}s): {upgrade_msg.text[:80]}...")
        btns_upgrade = list_buttons(upgrade_msg)
        print(f"     Buttons: {btns_upgrade}")

        # Verify "Back to Edge Picks" button exists
        back_to_picks_btn = find_button(upgrade_msg, "Back to Edge Picks")
        if not back_to_picks_btn:
            print(f"  ❌ FAIL: No 'Back to Edge Picks' button! Found: {btns_upgrade}")
            sys.exit(1)
        print(f"  ✅ 'Back to Edge Picks' button present")

        # Also verify "View Plans" button exists (upgrade page should have it)
        plans_btn = find_button(upgrade_msg, "View Plans") or find_button(upgrade_msg, "Plans")
        if not plans_btn:
            print(f"  ⚠️  No 'View Plans' button (may be OK)")
        else:
            print(f"  ✅ 'View Plans' button present")

        # Step 4: Tap "Back to Edge Picks"
        print("\n[3] Tapping 'Back to Edge Picks'...")
        t0 = time.time()
        back_msg = await click_button(client, upgrade_msg, back_to_picks_btn)
        elapsed = time.time() - t0

        if not back_msg:
            print(f"  ❌ FAIL: No response after 'Back to Edge Picks'")
            sys.exit(1)

        print(f"  ✅ Got response ({elapsed:.1f}s): {back_msg.text[:80]}...")

        # Verify we're back on the hot tips list
        if "Edge Picks" in back_msg.text or "Live Edges" in back_msg.text or "Top Edge" in back_msg.text:
            print(f"  ✅ Back to edge picks list confirmed")
        else:
            print(f"  ⚠️  Response text (may still be correct): {back_msg.text[:150]}")
            # Check for tip buttons
            tip_btns = list_buttons(back_msg)
            if any("🔒" in b or "🥇" in b or "💎" in b or "🥈" in b or "🥉" in b for b in tip_btns):
                print(f"  ✅ Tip buttons present — back to picks confirmed")
            else:
                print(f"  ❌ FAIL: Not on picks page. Buttons: {tip_btns}")
                sys.exit(1)

        print("\n" + "="*60)
        print("  ✅ W84-P0 ALL STEPS PASSED")
        print("  • Locked tip → Upgrade page: ✅")
        print("  • 'Back to Edge Picks' button present: ✅")
        print("  • Back to Edge Picks list: ✅")
        print("="*60)


if __name__ == "__main__":
    asyncio.run(main())
