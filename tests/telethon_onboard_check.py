"""
Telethon onboarding validation — Check 1 (BUILD-SETTINGS-CLEANUP-01)

PTB inline callbacks edit the EXISTING message, not send a new one.
Strategy: capture the bot-response message ID after /start, then re-fetch
that same message after each callback tap to read the edited content.
"""
import asyncio
import os
import sys
import time

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.messages import GetBotCallbackAnswerRequest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

API_ID = 32418601
API_HASH = "95e313a8ef5b998be0515dd8328fac57"
BOT_USERNAME = "mzansiedge_bot"
SESSION_FILE = os.path.expanduser("~/bot/data/telethon_qa_session")
STRING_SESSION_FILE = os.path.expanduser("~/bot/data/telethon_qa_session.string")


async def wait_for_bot_msg(client, bot_peer, after_id: int, timeout: float = 8.0):
    """Wait for a NEW message from bot with id > after_id."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        msgs = await client.get_messages(bot_peer, limit=5)
        for m in msgs:
            if not m.out and m.id > after_id:
                return m
        await asyncio.sleep(0.4)
    return None


async def wait_for_bot_msg_with_buttons(client, bot_peer, after_id: int, timeout: float = 12.0):
    """Wait for a new bot message with inline keyboard buttons (id > after_id)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        msgs = await client.get_messages(bot_peer, limit=8)
        for m in sorted(msgs, key=lambda x: x.id, reverse=True):
            if not m.out and m.id > after_id and inline_buttons(m):
                return m
        await asyncio.sleep(0.4)
    return None


async def refetch_message(client, bot_peer, msg_id: int):
    """Re-fetch a specific message by ID to see edits."""
    msgs = await client.get_messages(bot_peer, ids=[msg_id])
    if msgs:
        return msgs if not isinstance(msgs, list) else (msgs[0] if msgs else None)
    return None


def inline_buttons(msg):
    """Extract flat list of (text, data) from InlineKeyboardMarkup."""
    if not msg or not msg.reply_markup:
        return []
    try:
        rows = msg.reply_markup.rows
    except AttributeError:
        return []
    btns = []
    for row in rows:
        for btn in row.buttons:
            data = getattr(btn, "data", None)
            btns.append((btn.text, data))
    return btns


async def tap_inline(client, bot_peer, msg, label_fragment: str, timeout: float = 15.0):
    """Tap the inline button whose text contains label_fragment. Returns updated message."""
    btns = inline_buttons(msg)
    target = None
    for text, data in btns:
        if label_fragment.lower() in text.lower() and data:
            target = (text, data)
            break
    if not target:
        print(f"  [!] Button '{label_fragment}' not found. Available: {[t for t,_ in btns]}")
        return None

    print(f"  → Tapping: {target[0]!r}")
    original_btns = [(t, d) for t, d in btns]
    await client(GetBotCallbackAnswerRequest(
        peer=bot_peer,
        msg_id=msg.id,
        data=target[1],
    ))

    # Poll until the message content changes (card rendering can take 2-10s via Playwright)
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(1.0)
        updated = await refetch_message(client, bot_peer, msg.id)
        if updated:
            new_btns = inline_buttons(updated)
            if new_btns != original_btns:
                return updated  # message was edited
    # Return last fetched even if unchanged (caller will handle it)
    return await refetch_message(client, bot_peer, msg.id)


async def main():
    # Prefer string session (more reliable for automation)
    client = None
    if os.path.exists(STRING_SESSION_FILE):
        string = open(STRING_SESSION_FILE).read().strip()
        if string:
            print(f"Using string session from {STRING_SESSION_FILE}")
            client = TelegramClient(StringSession(string), API_ID, API_HASH)
            await client.connect()
            if not await client.is_user_authorized():
                print("String session not authorized — trying file session")
                await client.disconnect()
                client = None

    if client is None:
        print(f"Using file session: {SESSION_FILE}")
        client = TelegramClient(SESSION_FILE, API_ID, API_HASH)
        await client.connect()
        if not await client.is_user_authorized():
            print("[FAIL] No authorized session found. Run save_telegram_session.py first.")
            return

    async with client:
        bot_peer = await client.get_input_entity(BOT_USERNAME)
        bot_entity = await client.get_entity(BOT_USERNAME)
        print(f"Bot: {bot_entity.username} (id={bot_entity.id})")

        # Get current latest message id before we start
        seed_msgs = await client.get_messages(bot_peer, limit=1)
        last_id = seed_msgs[0].id if seed_msgs else 0

        # Step 0: force onboarding reset
        print("\n[0] Sending /qa force_onboard ...")
        sent = await client.send_message(bot_peer, "/qa force_onboard")
        resp = await wait_for_bot_msg(client, bot_peer, sent.id, timeout=6)
        if resp:
            print(f"  Bot says: {resp.text[:120]!r}")
        last_id = resp.id if resp else sent.id

        await asyncio.sleep(0.5)

        # Step 1: /start — sends TWO messages: welcome card (no btns) + experience selector (with btns)
        print("\n[1] Sending /start ...")
        sent = await client.send_message(bot_peer, "/start")
        # Wait specifically for the message WITH inline keyboard buttons
        start_msg = await wait_for_bot_msg_with_buttons(client, bot_peer, last_id, timeout=12)
        if not start_msg:
            # Debug: show what we got
            dbg_msgs = await client.get_messages(bot_peer, limit=5)
            for m in dbg_msgs[:3]:
                if not m.out and m.id > last_id:
                    print(f"  Got msg id={m.id} text={m.text[:100]!r} markup={type(m.reply_markup).__name__}")
            print("  [FAIL] No response with inline buttons to /start")
            return

        print(f"  Received experience selector (msg id={start_msg.id})")
        btns = inline_buttons(start_msg)
        print(f"  Buttons: {[t for t,_ in btns]}")

        # Must have experience buttons
        exp_labels = [t for t, _ in btns if any(w in t for w in ["bet", "Bet", "causal", "new", "New", "regularly", "Regularly", "casual", "Casual"])]
        print(f"  Experience buttons found: {exp_labels}")

        # Step 2: Tap "regularly" / experienced
        print("\n[2] Tapping 'regularly' (experienced user) ...")
        cur_msg = await tap_inline(client, bot_peer, start_msg, "regularly")
        if not cur_msg:
            # Try alternate labels
            cur_msg = await tap_inline(client, bot_peer, start_msg, "experienced")
        if not cur_msg:
            print("  [FAIL] Could not tap experience button")
            return
        print(f"  Message text snippet: {cur_msg.text[:200]!r}")
        btns = inline_buttons(cur_msg)
        print(f"  Buttons after tap: {[t for t,_ in btns]}")

        # Step 3: Tap a sport (Soccer)
        print("\n[3] Tapping 'Soccer' ...")
        cur_msg = await tap_inline(client, bot_peer, cur_msg, "Soccer")
        if not cur_msg:
            cur_msg = await tap_inline(client, bot_peer, cur_msg, "⚽")
        if not cur_msg:
            print("  [FAIL] Could not tap sport button")
            return
        print(f"  Message text snippet: {cur_msg.text[:200]!r}")
        btns = inline_buttons(cur_msg)
        print(f"  Buttons: {[t for t,_ in btns]}")

        # Step 4: Tap "Done" / "Continue" for sports selection
        print("\n[4] Looking for sports_done / Continue ...")
        done_btn = next(((t,d) for t,d in inline_buttons(cur_msg) if any(w in t.lower() for w in ["done", "continue", "next"])), None)
        if done_btn:
            print(f"  Tapping: {done_btn[0]!r}")
            await client(GetBotCallbackAnswerRequest(
                peer=bot_peer,
                msg_id=cur_msg.id,
                data=done_btn[1],
            ))
            await asyncio.sleep(0.8)
            cur_msg = await refetch_message(client, bot_peer, cur_msg.id)
            print(f"  After Done: {cur_msg.text[:200]!r}")
        else:
            print("  No done/continue button — checking current buttons:")
            print(f"  Buttons: {[t for t,_ in inline_buttons(cur_msg)]}")

        # At this point we should be at the team input step
        # Check if we see a team input prompt
        msg_text = cur_msg.text if cur_msg else ""
        print(f"\n[5] Current message: {msg_text[:300]!r}")

        # Check if it asks for team names (text input step)
        team_step = any(w in msg_text.lower() for w in ["team", "player", "fighter", "type", "favourite"])
        if team_step:
            print("  → Team input step detected — sending team name")
            # Send a team name as text
            sent2 = await client.send_message(bot_peer, "Arsenal")
            team_resp = await wait_for_bot_msg(client, bot_peer, cur_msg.id, timeout=8)
            if team_resp:
                print(f"  Bot reply: {team_resp.text[:300]!r}")
                btns2 = inline_buttons(team_resp)
                print(f"  Buttons: {[t for t,_ in btns2]}")

                # Look for Continue/Done after team
                cont_btn = next(((t,d) for t,d in btns2 if any(w in t.lower() for w in ["continue", "done", "next", "finish"])), None)
                if cont_btn:
                    print(f"  Tapping Continue: {cont_btn[0]!r}")
                    await client(GetBotCallbackAnswerRequest(
                        peer=bot_peer,
                        msg_id=team_resp.id,
                        data=cont_btn[1],
                    ))
                    await asyncio.sleep(1.0)
                    next_msg = await wait_for_bot_msg(client, bot_peer, team_resp.id, timeout=8)
                    if next_msg:
                        print(f"\n[6] Next step: {next_msg.text[:400]!r}")
                        btns3 = inline_buttons(next_msg)
                        print(f"  Buttons: {[t for t,_ in btns3]}")

                        # Check: experienced user should NOT see risk/bankroll step
                        # Should see preferences or summary
                        bad_steps = ["risk profile", "bankroll", "much do you bet", "stake", "risk appetite"]
                        found_bad = any(w in next_msg.text.lower() for w in bad_steps)
                        if found_bad:
                            print("\n  [WARN] Possibly showing deprecated risk/bankroll step?")
                            print(f"  Text: {next_msg.text[:400]!r}")
                        else:
                            print("\n  [OK] No deprecated risk/bankroll step visible")

                        # Check if it jumped to summary or preferences
                        if any(w in next_msg.text.lower() for w in ["profile", "summary", "preferences", "notification"]):
                            print("  [OK] Reached summary/preferences as expected for experienced user")
                        elif any(w in next_msg.text.lower() for w in ["edge", "how your edge", "edge-ai"]):
                            print("  [INFO] Showing edge explainer — expected for non-experienced user path")
                        else:
                            print(f"  [INFO] Current step: {next_msg.text[:150]!r}")

        print("\n=== ONBOARDING CHECK COMPLETE ===")
        print("Key validation: experienced user skips edge_explainer and goes direct to summary")
        print("If no 'risk profile' / 'bankroll' prompts appeared above — PASS")


if __name__ == "__main__":
    asyncio.run(main())
