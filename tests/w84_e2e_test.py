"""W84-E2E: Comprehensive end-to-end test of the edge:detail tap flow.

Simulates Paul's exact flow:
1. Send /start
2. Tap Top Edge Picks
3. Record all visible edges
4. Tap EVERY edge button
5. Time each response
6. Record verbatim content
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
import json
from datetime import datetime

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import ReplyInlineMarkup, KeyboardButtonCallback

API_ID = int(os.getenv("TELEGRAM_API_ID", "32418601"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "95e313a8ef5b998be0515dd8328fac57")
BOT_USERNAME = "mzansiedge_bot"
from config import DATA_DIR
SESSION_FILE = str(DATA_DIR / "telethon_qa_session")
STRING_SESSION_FILE = str(DATA_DIR / "telethon_qa_session.string")
WAIT = 18  # seconds to wait for bot response on tap

results = []


async def get_client() -> TelegramClient:
    if os.path.exists(STRING_SESSION_FILE):
        string = open(STRING_SESSION_FILE).read().strip()
        if string:
            client = TelegramClient(StringSession(string), API_ID, API_HASH)
            await client.connect()
            if await client.is_user_authorized():
                print("[OK] Connected via string session")
                return client
            await client.disconnect()
    client = TelegramClient(SESSION_FILE, API_ID, API_HASH)
    await client.connect()
    if not await client.is_user_authorized():
        print("ERROR: Not logged in. Run save_telegram_session.py first.")
        sys.exit(1)
    print("[OK] Connected via file session")
    return client


async def send_msg(client, text, wait=10):
    entity = await client.get_entity(BOT_USERNAME)
    sent = await client.send_message(entity, text)
    await asyncio.sleep(wait)
    msgs = await client.get_messages(entity, limit=30)
    return [m for m in msgs if m.id >= sent.id and not m.out], sent.id


async def tap_button_by_data(client, msg, cb_data_prefix, wait=WAIT):
    """Tap a button whose callback_data starts with prefix."""
    if not msg.reply_markup or not isinstance(msg.reply_markup, ReplyInlineMarkup):
        return None, None

    for row in msg.reply_markup.rows:
        for btn in row.buttons:
            if isinstance(btn, KeyboardButtonCallback):
                data = btn.data.decode() if isinstance(btn.data, bytes) else btn.data
                if data.startswith(cb_data_prefix):
                    entity = await client.get_entity(BOT_USERNAME)
                    t0 = time.time()
                    try:
                        await msg.click(data=btn.data)
                    except Exception as e:
                        return None, str(e)
                    await asyncio.sleep(wait)
                    msgs = await client.get_messages(entity, limit=20)
                    elapsed = time.time() - t0
                    # Most recent bot msg
                    bot_msgs = [m for m in msgs if not m.out]
                    return bot_msgs, elapsed
    return None, None


async def tap_button_exact(client, msg, cb_data, wait=WAIT):
    """Tap a button with exact callback_data."""
    if not msg.reply_markup or not isinstance(msg.reply_markup, ReplyInlineMarkup):
        return None, None

    for row in msg.reply_markup.rows:
        for btn in row.buttons:
            if isinstance(btn, KeyboardButtonCallback):
                data = btn.data.decode() if isinstance(btn.data, bytes) else btn.data
                if data == cb_data:
                    entity = await client.get_entity(BOT_USERNAME)
                    t0 = time.time()
                    try:
                        await msg.click(data=btn.data)
                    except Exception as e:
                        return None, str(e)
                    await asyncio.sleep(wait)
                    msgs = await client.get_messages(entity, limit=20)
                    elapsed = time.time() - t0
                    bot_msgs = [m for m in msgs if not m.out]
                    return bot_msgs, elapsed
    return None, None


def get_inline_buttons(msg):
    """Extract all inline buttons as (text, data) tuples."""
    if not msg.reply_markup or not isinstance(msg.reply_markup, ReplyInlineMarkup):
        return []
    btns = []
    for row in msg.reply_markup.rows:
        for btn in row.buttons:
            if isinstance(btn, KeyboardButtonCallback):
                data = btn.data.decode() if isinstance(btn.data, bytes) else btn.data
                btns.append((btn.text, data))
    return btns


async def run_e2e():
    client = await get_client()
    entity = await client.get_entity(BOT_USERNAME)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")

    print(f"\n{'='*60}")
    print(f"W84-E2E: MzansiEdge Bot Tap Flow Test")
    print(f"Started: {ts}")
    print(f"{'='*60}\n")

    # ── Step 1: /start ────────────────────────────────────────────
    print("[1/4] Sending /start...")
    start_msgs, start_id = await send_msg(client, "/start", wait=8)
    print(f"      Got {len(start_msgs)} message(s)")
    for m in start_msgs:
        if m.text:
            print(f"      First 80 chars: {m.text[:80]!r}")
            break

    results.append({
        "step": "start",
        "messages_received": len(start_msgs),
        "first_text": start_msgs[0].text[:200] if start_msgs else None,
    })

    # ── Step 2: Top Edge Picks ────────────────────────────────────
    print("\n[2/4] Tapping '💎 Top Edge Picks'...")
    t0 = time.time()
    tips_msgs, tips_start_id = await send_msg(client, "💎 Top Edge Picks", wait=15)
    tips_elapsed = time.time() - t0
    print(f"      Got {len(tips_msgs)} message(s) in {tips_elapsed:.1f}s")

    # Find the header message and tip messages
    header_msg = None
    tip_cards = []  # (msg, edge_buttons)

    for m in tips_msgs:
        if not m.text:
            continue
        if "Top Edge Picks" in m.text or "Edge Picks" in m.text or "Live Edges" in m.text:
            header_msg = m
            print(f"      Header: {m.text[:150]!r}")
        if m.reply_markup:
            btns = get_inline_buttons(m)
            edge_btns = [(t, d) for t, d in btns if d.startswith("edge:detail:")]
            if edge_btns:
                tip_cards.append((m, edge_btns))
                print(f"      TipCard msg_id={m.id}: {m.text[:100]!r}")
                print(f"        Buttons: {edge_btns}")

    print(f"\n      Found {len(tip_cards)} tip cards with edge:detail buttons")

    results.append({
        "step": "top_edge_picks",
        "elapsed": tips_elapsed,
        "messages_received": len(tips_msgs),
        "header_text": header_msg.text[:500] if header_msg else None,
        "tip_cards_found": len(tip_cards),
        "all_message_texts": [m.text[:300] if m.text else None for m in tips_msgs],
    })

    if not tip_cards:
        # Check if "No edges" state
        for m in tips_msgs:
            if m.text and ("No edges" in m.text or "no edges" in m.text.lower()):
                print("      Bot shows 'No edges' state — no taps to perform")
                break
        else:
            print("      WARNING: No edge:detail buttons found in any message")
        await client.disconnect()
        return results

    # ── Step 3: Tap EVERY edge:detail button ─────────────────────
    print(f"\n[3/4] Tapping ALL {sum(len(eb) for _, eb in tip_cards)} edge buttons...")
    print()

    tap_results = []
    tap_num = 0

    for card_msg, edge_buttons in tip_cards:
        for btn_text, btn_data in edge_buttons:
            tap_num += 1
            match_key = btn_data.replace("edge:detail:", "")
            print(f"      Tap {tap_num}: {btn_text!r} → {btn_data}")
            print(f"        match_key: {match_key}")

            t0 = time.time()
            # Get fresh msg reference
            fresh_msgs = await client.get_messages(entity, ids=card_msg.id)
            fresh_msg = fresh_msgs if not isinstance(fresh_msgs, list) else (fresh_msgs[0] if fresh_msgs else None)

            if not fresh_msg:
                print(f"        ERROR: Could not fetch fresh msg for tap")
                tap_results.append({
                    "tap_num": tap_num,
                    "btn_text": btn_text,
                    "btn_data": btn_data,
                    "match_key": match_key,
                    "error": "Could not fetch fresh message",
                    "elapsed": None,
                    "response_text": None,
                })
                await asyncio.sleep(3)
                continue

            try:
                await fresh_msg.click(data=btn_data.encode() if isinstance(btn_data, str) else btn_data)
            except Exception as e:
                print(f"        CLICK ERROR: {e}")
                tap_results.append({
                    "tap_num": tap_num,
                    "btn_text": btn_text,
                    "btn_data": btn_data,
                    "match_key": match_key,
                    "error": str(e),
                    "elapsed": None,
                    "response_text": None,
                })
                await asyncio.sleep(3)
                continue

            # Wait for response
            await asyncio.sleep(WAIT)
            elapsed = time.time() - t0

            # Get most recent messages from bot
            recent = await client.get_messages(entity, limit=10)
            bot_recents = [m for m in recent if not m.out]

            # The response should be the most recent bot message
            response_text = bot_recents[0].text if bot_recents else None
            response_len = len(response_text) if response_text else 0

            # Detect content type
            content_type = "empty"
            if response_text:
                if "INSTANT BASELINE" in response_text or "The Setup" in response_text or "📋" in response_text:
                    content_type = "narrative"
                elif "Edge" in response_text and ("vs" in response_text or "Odds" in response_text):
                    content_type = "analysis"
                elif "No" in response_text and "data" in response_text.lower():
                    content_type = "no_data"
                elif len(response_text) > 100:
                    content_type = "content"
                else:
                    content_type = "short"

            status = "✅ CONTENT" if response_len > 50 else "❌ EMPTY/SHORT"
            print(f"        Elapsed: {elapsed:.1f}s | Length: {response_len} chars | {status} | Type: {content_type}")
            if response_text:
                print(f"        Response preview: {response_text[:150]!r}")

            tap_results.append({
                "tap_num": tap_num,
                "btn_text": btn_text,
                "btn_data": btn_data,
                "match_key": match_key,
                "elapsed": elapsed,
                "response_text": response_text[:2000] if response_text else None,
                "response_len": response_len,
                "content_type": content_type,
                "error": None,
            })

            # Small pause between taps
            await asyncio.sleep(4)

    results.append({
        "step": "tap_all_edges",
        "total_taps": tap_num,
        "tap_results": tap_results,
    })

    # ── Step 4: Summary ───────────────────────────────────────────
    print(f"\n[4/4] Summary:")
    successes = [r for r in tap_results if r["response_len"] and r["response_len"] > 50]
    failures = [r for r in tap_results if not r["response_len"] or r["response_len"] <= 50]
    errors = [r for r in tap_results if r.get("error")]

    print(f"      Total taps: {tap_num}")
    print(f"      With content (>50 chars): {len(successes)}")
    print(f"      Empty/short: {len(failures)}")
    print(f"      Click errors: {len(errors)}")

    if tap_results:
        valid_elapsed = [r["elapsed"] for r in tap_results if r["elapsed"]]
        if valid_elapsed:
            avg = sum(valid_elapsed) / len(valid_elapsed)
            print(f"      Avg response time: {avg:.1f}s")
            print(f"      Min: {min(valid_elapsed):.1f}s  Max: {max(valid_elapsed):.1f}s")

    await client.disconnect()
    return results


async def main():
    try:
        r = await run_e2e()
        # Save raw results
        out_path = f"/tmp/w84_e2e_results_{int(time.time())}.json"
        with open(out_path, "w") as f:
            json.dump(r, f, indent=2, default=str)
        print(f"\nRaw results saved to: {out_path}")
        return r
    except Exception as e:
        print(f"\nFATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        return []


if __name__ == "__main__":
    asyncio.run(main())
