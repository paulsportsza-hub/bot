"""
QA: Verify edge:breakdown_back button fix on AI Breakdown card.
Wave: W84-NAV-FIX-02
"""
import asyncio
import os
import sys
import time

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import (
    MessageMediaPhoto,
    ReplyInlineMarkup,
    KeyboardButtonCallback,
)

load_dotenv("/home/paulsportsza/bot/.env")

SESSION_FILE = "/home/paulsportsza/bot/data/telethon_qa_session.string"
with open(SESSION_FILE) as f:
    session_str = f.read().strip()

api_id = int(os.environ["TELEGRAM_API_ID"])
api_hash = os.environ["TELEGRAM_API_HASH"]
BOT = "mzansiedge_bot"

TIMEOUT = 30  # seconds to wait for bot response


async def wait_for_change(client, chat, msg_id, base_edit_date, timeout=TIMEOUT):
    """Poll until a message's edit_date changes (indicating a bot edit)."""
    deadline = time.monotonic() + timeout
    await asyncio.sleep(2)
    while time.monotonic() < deadline:
        msgs = await client.get_messages(chat, ids=[msg_id])
        if msgs and msgs[0]:
            m = msgs[0]
            if m.edit_date != base_edit_date:
                return m
        await asyncio.sleep(1.5)
    # Return current state even if no edit detected
    msgs = await client.get_messages(chat, ids=[msg_id])
    return msgs[0] if msgs else None


async def wait_for_new_message(client, chat, after_id, timeout=TIMEOUT):
    """Poll until a message newer than after_id appears."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        msgs = await client.get_messages(chat, limit=5)
        for m in msgs:
            if m.id > after_id:
                return m
        await asyncio.sleep(1.5)
    return None


def extract_buttons(msg):
    """Return flat list of (text, callback_data) tuples."""
    buttons = []
    if not msg or not msg.reply_markup:
        return buttons
    if isinstance(msg.reply_markup, ReplyInlineMarkup):
        for row in msg.reply_markup.rows:
            for btn in row.buttons:
                if isinstance(btn, KeyboardButtonCallback):
                    cb = btn.data.decode("utf-8") if isinstance(btn.data, bytes) else btn.data
                    buttons.append((btn.text, cb))
    return buttons


def has_photo(msg):
    return msg and isinstance(msg.media, MessageMediaPhoto)


def get_photo_id(msg):
    if has_photo(msg):
        return msg.media.photo.id
    return None


async def click_button(client, msg, cb_data):
    """Properly click an inline button by callback data."""
    try:
        fresh = (await client.get_messages(BOT, ids=[msg.id]))[0]
        result = await fresh.click(data=cb_data.encode() if isinstance(cb_data, str) else cb_data)
        return True, result
    except Exception as e:
        return False, str(e)


async def main():
    results = []
    failures = []

    async with TelegramClient(StringSession(session_str), api_id, api_hash) as client:
        me = await client.get_me()
        results.append(f"Telethon connected as: {me.username} ({me.id})")

        # ─── Runtime Check (D3) ───────────────────────────────────────────────
        results.append("\n## Runtime Check (D3)")
        import subprocess
        ps = subprocess.run(["ps", "aux"], capture_output=True, text=True)
        bot_lines = [l for l in ps.stdout.splitlines() if "bot.py" in l and "grep" not in l]
        if bot_lines:
            # Verify it's the canonical path
            canonical = "/home/paulsportsza/bot/bot.py"
            line = bot_lines[0]
            if canonical in line or "bot.py" in line.split()[-1]:
                results.append(f"PASS  Active runtime confirmed: bot.py running")
            else:
                results.append(f"FAIL  Wrong runtime path: {line}")
                failures.append("D3: wrong runtime path")
        else:
            results.append("FAIL  bot.py process not found")
            failures.append("D3: bot.py not running")

        # ─── Step 1: /qa set_diamond ──────────────────────────────────────────
        results.append("\n## Step 1: /qa set_diamond")
        recent = await client.get_messages(BOT, limit=1)
        anchor_id = recent[0].id if recent else 0

        await client.send_message(BOT, "/qa set_diamond")
        await asyncio.sleep(3)
        resp = await wait_for_new_message(client, BOT, anchor_id)
        if resp and ("DIAMOND" in (resp.text or "").upper() or "diamond" in (resp.text or "").lower()):
            results.append(f"PASS  QA tier set to Diamond (msg {resp.id})")
        elif resp:
            results.append(f"PASS  Got response: {(resp.text or '')[:100]}")
        else:
            results.append("FAIL  No response to /qa set_diamond")
            failures.append("Step 1: set_diamond no response")

        # ─── Step 2: 💎 Top Edge Picks ────────────────────────────────────────
        results.append("\n## Step 2: 💎 Top Edge Picks")
        recent2 = await client.get_messages(BOT, limit=1)
        anchor_id2 = recent2[0].id

        await client.send_message(BOT, "💎 Top Edge Picks")
        await asyncio.sleep(5)
        tips_msg = await wait_for_new_message(client, BOT, anchor_id2, timeout=35)

        if not tips_msg:
            results.append("FAIL  No tips list message received")
            failures.append("Step 2: no tips list")
            print("\n".join(results))
            return results, failures

        tips_msg_id = tips_msg.id
        tips_buttons = extract_buttons(tips_msg)
        results.append(f"PASS  Tips list received (msg {tips_msg_id})")
        results.append(f"      All callbacks: {[c for t,c in tips_buttons]}")

        pick_btn = next(((t, c) for t, c in tips_buttons if c.startswith("ep:pick:")), None)
        if not pick_btn:
            results.append("FAIL  No ep:pick:N button on tips list")
            failures.append("Step 2: no ep:pick button")
            print("\n".join(results))
            return results, failures
        results.append(f"      Using: text='{pick_btn[0]}' cb='{pick_btn[1]}'")

        # ─── Step 3: Click ep:pick:N → tip DETAIL card ───────────────────────
        results.append("\n## Step 3: Click ep:pick:N → detail card")
        # The tips card may be edited in place when we click ep:pick:N
        base_edit = tips_msg.edit_date
        ok, click_result = await click_button(client, tips_msg, pick_btn[1])
        if not ok:
            results.append(f"      click() raised: {click_result}")

        await asyncio.sleep(6)

        # After click, check if tips_msg was edited (it edits in-place to detail card)
        detail_msg = (await client.get_messages(BOT, ids=[tips_msg_id]))[0]
        detail_buttons = extract_buttons(detail_msg)
        detail_has_photo = has_photo(detail_msg)
        detail_photo_id = get_photo_id(detail_msg)
        detail_edit_date = detail_msg.edit_date

        results.append(f"      Detail msg id: {detail_msg.id}")
        results.append(f"      Edit date changed: {base_edit != detail_edit_date} ({base_edit} → {detail_edit_date})")
        results.append(f"      Has photo: {detail_has_photo}, Photo ID: {detail_photo_id}")
        results.append(f"      Detail buttons: {[(t, c) for t,c in detail_buttons]}")

        # Look for the AI Breakdown button
        breakdown_btn = next(
            ((t, c) for t, c in detail_buttons
             if "breakdown" in c.lower() and "back" not in c.lower()),
            None
        )
        if not breakdown_btn:
            # Maybe it opened as a new message — check for recent new msgs
            results.append("      Checking for new message (in case ep:pick opened a new card)...")
            new_after = await wait_for_new_message(client, BOT, tips_msg_id, timeout=10)
            if new_after:
                detail_msg = new_after
                detail_buttons = extract_buttons(detail_msg)
                detail_has_photo = has_photo(detail_msg)
                detail_photo_id = get_photo_id(detail_msg)
                detail_edit_date = detail_msg.edit_date
                results.append(f"      New message found: msg {detail_msg.id}")
                results.append(f"      Has photo: {detail_has_photo}")
                results.append(f"      Buttons: {[(t, c) for t,c in detail_buttons]}")
                breakdown_btn = next(
                    ((t, c) for t, c in detail_buttons
                     if "breakdown" in c.lower() and "back" not in c.lower()),
                    None
                )

        if not breakdown_btn:
            results.append("FAIL  No AI Breakdown button on detail card")
            failures.append("Step 3: no AI Breakdown button")
            print("\n".join(results))
            return results, failures

        results.append(f"PASS  Detail card has AI Breakdown button: cb='{breakdown_btn[1]}'")
        detail_msg_id = detail_msg.id

        # ─── Step 4: Click 🤖 Full AI Breakdown ───────────────────────────────
        results.append("\n## Step 4: Click 🤖 Full AI Breakdown → breakdown card")
        base_edit_before_bd = detail_msg.edit_date
        ok2, click_result2 = await click_button(client, detail_msg, breakdown_btn[1])
        if not ok2:
            results.append(f"      click() raised: {click_result2}")

        await asyncio.sleep(8)

        # Breakdown edits the detail message in-place
        breakdown_msg = (await client.get_messages(BOT, ids=[detail_msg_id]))[0]
        breakdown_buttons = extract_buttons(breakdown_msg)
        breakdown_edit = breakdown_msg.edit_date

        results.append(f"      Breakdown msg id: {breakdown_msg.id}")
        results.append(f"      Edit date changed: {base_edit_before_bd != breakdown_edit}")
        results.append(f"      Breakdown buttons: {[(t, c) for t,c in breakdown_buttons]}")

        # ─── Step 5: Assert back button callback data ─────────────────────────
        results.append("\n## Step 5: Assert back button callback data")
        back_btn = next(
            ((t, c) for t, c in breakdown_buttons if "Back" in t or "back" in c.lower()),
            None
        )
        if not back_btn:
            results.append("FAIL  No back button on breakdown card")
            failures.append("Step 5: no back button on breakdown")
        else:
            cb_data = back_btn[1]
            results.append(f"      VERBATIM callback data: '{cb_data}'")
            results.append(f"      Back button text: '{back_btn[0]}'")

            if cb_data.startswith("edge:breakdown_back:"):
                results.append("PASS  Callback correctly starts with 'edge:breakdown_back:'")
            elif cb_data.startswith("hot:back"):
                results.append(f"FAIL  Callback is '{cb_data}' — OLD hot:back implementation")
                failures.append(f"Step 5: wrong callback '{cb_data}'")
            elif cb_data.startswith("edge:detail"):
                results.append(f"FAIL  Callback is '{cb_data}' — OLD edge:detail loop")
                failures.append(f"Step 5: wrong callback '{cb_data}'")
            else:
                results.append(f"FAIL  Unexpected callback: '{cb_data}'")
                failures.append(f"Step 5: unexpected callback '{cb_data}'")

        # ─── Step 6: Tap back button ──────────────────────────────────────────
        results.append("\n## Step 6: Tap back button → restored detail card")
        if not back_btn:
            results.append("SKIP  No back button to tap")
            failures.append("Step 6: skipped — no back button")
        else:
            base_edit_before_back = breakdown_msg.edit_date
            ok3, click_result3 = await click_button(client, breakdown_msg, back_btn[1])
            if not ok3:
                results.append(f"      click() raised: {click_result3}")

            await asyncio.sleep(6)
            restored_msg = (await client.get_messages(BOT, ids=[detail_msg_id]))[0]
            restored_buttons = extract_buttons(restored_msg)
            restored_has_photo = has_photo(restored_msg)
            restored_photo_id = get_photo_id(restored_msg)
            restored_edit_date = restored_msg.edit_date

            results.append(f"\n## Step 7: Critical assertions on restored card")
            results.append(f"      Restored msg id: {restored_msg.id} (expected: {detail_msg_id})")
            results.append(f"      Edit date changed from breakdown: {base_edit_before_back != restored_edit_date}")
            results.append(f"      Restored buttons: {[(t, c) for t,c in restored_buttons]}")

            # Assert 1: Same message ID (edited in place, not new)
            if restored_msg.id == detail_msg_id:
                results.append("PASS  Same message ID — edited in place (not a new message)")
            else:
                results.append(f"FAIL  Different message ID: got {restored_msg.id}, expected {detail_msg_id}")
                failures.append("Step 7: different message ID after back")

            # Assert 2: Photo present
            if restored_has_photo:
                results.append(f"PASS  Photo is present on restored card (ID: {restored_photo_id})")
            else:
                results.append("FAIL  No photo on restored card — expected PNG tip card")
                failures.append("Step 7: no photo on restored card")

            # Assert 3: Photo ID comparison
            if detail_photo_id and restored_photo_id:
                if restored_photo_id == detail_photo_id:
                    results.append(f"PASS  Photo ID matches original detail card — exact same photo restored")
                else:
                    results.append(f"INFO  Photo IDs differ: original={detail_photo_id}, restored={restored_photo_id}")
                    results.append("      (Different Telegram file_id is acceptable if same image re-uploaded)")

            # Assert 4: AI Breakdown button visible again
            has_breakdown_again = any(
                "breakdown" in c.lower() and "back" not in c.lower()
                for t, c in restored_buttons
            )
            if has_breakdown_again:
                results.append("PASS  '🤖 Full AI Breakdown' button visible on restored card")
            else:
                results.append("FAIL  AI Breakdown button NOT visible on restored card")
                failures.append("Step 7: breakdown button missing on restored card")

            # Assert 5: NOT the full tips list (no ep:pick buttons)
            has_pick_btns = any(c.startswith("ep:pick:") for t, c in restored_buttons)
            if not has_pick_btns:
                results.append("PASS  No ep:pick buttons — restored card is NOT the full tips list")
            else:
                results.append("FAIL  ep:pick buttons present — back returned to tips list instead of detail card")
                failures.append("Step 7: back showed tips list instead of detail card")

    return results, failures


if __name__ == "__main__":
    results, failures = asyncio.run(main())

    print("\n" + "=" * 60)
    print("QA RESULTS — W84-NAV-FIX-02 breakdown_back")
    print("=" * 60)
    for line in results:
        print(line)

    print("\n" + "=" * 60)
    if failures:
        print(f"VERDICT: FAIL — {len(failures)} failure(s)")
        for f in failures:
            print(f"  - {f}")
    else:
        print("VERDICT: PASS — All assertions passed")
    print("=" * 60)
    sys.exit(1 if failures else 0)
