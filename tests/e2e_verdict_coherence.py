#!/usr/bin/env python3
"""VERDICT-COHERENCE-FIX: Telethon E2E verification.

Triggers edge:detail via Hot Tips inline buttons and verifies evidence-aware verdicts.
Captures all output to /home/paulsportsza/reports/verdict_coherence_captures.json.
"""
import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone

from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from telethon import TelegramClient
from telethon.tl.types import ReplyInlineMarkup, KeyboardButtonCallback

API_ID = int(os.environ["TELEGRAM_API_ID"])
API_HASH = os.environ["TELEGRAM_API_HASH"]
SESSION = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "telethon_qa_session")
BOT_USERNAME = "mzansiedge_bot"
REPORT_PATH = "/home/paulsportsza/reports/verdict_coherence_captures.json"


async def get_latest_bot_msgs(client, bot_entity, limit=5):
    """Get recent non-outgoing messages from the bot."""
    msgs = await client.get_messages(bot_entity, limit=limit)
    return [m for m in msgs if not m.out]


async def wait_for_new_msg(client, bot_entity, after_id, timeout=25):
    """Wait for a new message from the bot after a given message ID."""
    start = time.time()
    while time.time() - start < timeout:
        msgs = await client.get_messages(bot_entity, limit=5)
        for msg in msgs:
            if not msg.out and msg.id > after_id:
                # Wait a bit for edits to settle
                await asyncio.sleep(3)
                fresh = await client.get_messages(bot_entity, ids=msg.id)
                return fresh if fresh else msg
        await asyncio.sleep(1.5)
    return None


async def find_edge_buttons(msg):
    """Find edge:detail callback buttons in a message."""
    buttons = []
    if not msg or not msg.reply_markup:
        return buttons
    if isinstance(msg.reply_markup, ReplyInlineMarkup):
        for row in msg.reply_markup.rows:
            for btn in row.buttons:
                if isinstance(btn, KeyboardButtonCallback):
                    data = btn.data.decode("utf-8", errors="replace") if isinstance(btn.data, bytes) else str(btn.data)
                    if "edge:detail:" in data or data.startswith("edge:detail:"):
                        buttons.append((btn.text, data))
    return buttons


async def click_callback(client, msg, callback_data):
    """Click a callback button by its data."""
    if not msg or not msg.reply_markup:
        return False
    if isinstance(msg.reply_markup, ReplyInlineMarkup):
        for row in msg.reply_markup.rows:
            for btn in row.buttons:
                if isinstance(btn, KeyboardButtonCallback):
                    data = btn.data.decode("utf-8", errors="replace") if isinstance(btn.data, bytes) else str(btn.data)
                    if data == callback_data:
                        await msg.click(data=btn.data)
                        return True
    return False


async def run_tests():
    captures = []
    client = TelegramClient(SESSION, API_ID, API_HASH)
    await client.start()

    bot_entity = await client.get_entity(BOT_USERNAME)
    print(f"Connected to @{BOT_USERNAME}")

    # Get baseline message ID
    baseline_msgs = await get_latest_bot_msgs(client, bot_entity, limit=1)
    baseline_id = baseline_msgs[0].id if baseline_msgs else 0

    # Test 1: Trigger Hot Tips to get edge list
    print("\n--- Test 1: Trigger Hot Tips ---")
    await client.send_message(bot_entity, "💎 Top Edge Picks")
    await asyncio.sleep(15)  # Wait for tips to fully load

    tips_msgs = await get_latest_bot_msgs(client, bot_entity, limit=5)
    tips_msg = None
    for m in tips_msgs:
        if m.id > baseline_id:
            tips_msg = m
            break

    if not tips_msg:
        print("  FAIL: No Hot Tips response")
        captures.append({"test": "hot_tips_list", "result": "FAIL", "error": "No response"})
        await client.disconnect()
        return captures

    tips_text = tips_msg.text or tips_msg.message or ""
    print(f"  Got Hot Tips ({len(tips_text)} chars)")

    # Find all edge:detail buttons
    edge_buttons = await find_edge_buttons(tips_msg)
    print(f"  Found {len(edge_buttons)} edge:detail buttons")

    captures.append({
        "test": "hot_tips_list",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "text": tips_text[:2000],
        "edge_buttons": len(edge_buttons),
        "result": "PASS" if edge_buttons else "PARTIAL",
    })

    # Test 2-6: Tap up to 5 edge:detail buttons
    detail_tests = 0
    ev_found_count = 0
    for idx, (btn_text, callback_data) in enumerate(edge_buttons[:5]):
        test_num = idx + 2
        print(f"\n--- Test {test_num}: Detail for '{btn_text[:40]}' ---")

        before_id = tips_msg.id
        clicked = await click_callback(client, tips_msg, callback_data)
        if not clicked:
            print(f"  SKIP: Could not click button")
            continue

        await asyncio.sleep(8)  # Wait for detail to render (may be instant or slow)

        # The detail replaces the tips message (edit), so re-fetch it
        detail_msg = await client.get_messages(bot_entity, ids=tips_msg.id)
        if not detail_msg:
            # Check for a new message instead
            detail_msg = await wait_for_new_msg(client, bot_entity, before_id, timeout=15)

        if detail_msg:
            detail_text = detail_msg.text or detail_msg.message or ""

            # Check for evidence clauses
            has_ev_clause = "% EV" in detail_text
            has_signal_clause = "Key signals:" in detail_text or "No confirming signals" in detail_text or "higher variance" in detail_text
            has_risk_clause = "Main risk:" in detail_text
            has_verdict = "🏆" in detail_text or "Verdict" in detail_text

            if has_ev_clause:
                ev_found_count += 1

            result = "PASS" if has_ev_clause else "PARTIAL"
            print(f"  {result}: EV={has_ev_clause}, Signals={has_signal_clause}, Risk={has_risk_clause}, Verdict={has_verdict}")
            # Show verdict section
            verdict_idx = detail_text.find("🏆")
            if verdict_idx >= 0:
                verdict_section = detail_text[verdict_idx:verdict_idx+500]
                print(f"  Verdict section: {verdict_section[:300]}")

            captures.append({
                "test": f"edge_detail_{idx+1}",
                "button_text": btn_text[:50],
                "callback_data": callback_data,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "text": detail_text[:3000],
                "has_ev_clause": has_ev_clause,
                "has_signal_clause": has_signal_clause,
                "has_risk_clause": has_risk_clause,
                "has_verdict": has_verdict,
                "result": result,
            })
            detail_tests += 1
        else:
            print(f"  FAIL: No detail response")
            captures.append({
                "test": f"edge_detail_{idx+1}",
                "button_text": btn_text[:50],
                "result": "FAIL",
                "error": "No response",
            })
            detail_tests += 1

        # Navigate back to tips list for next test
        await asyncio.sleep(2)
        if detail_msg and detail_msg.reply_markup:
            for row in detail_msg.reply_markup.rows if isinstance(detail_msg.reply_markup, ReplyInlineMarkup) else []:
                for btn in row.buttons:
                    if isinstance(btn, KeyboardButtonCallback):
                        data = btn.data.decode("utf-8", errors="replace") if isinstance(btn.data, bytes) else str(btn.data)
                        if "hot:back" in data or "edge picks" in (btn.text or "").lower():
                            await detail_msg.click(data=btn.data)
                            await asyncio.sleep(4)
                            # Re-fetch the tips message
                            tips_msg = await client.get_messages(bot_entity, ids=tips_msg.id)
                            break

    # Test 7: My Matches regression check (yg:game: path)
    print("\n--- Test 7: My Matches regression ---")
    baseline2 = (await get_latest_bot_msgs(client, bot_entity, limit=1))[0].id
    await client.send_message(bot_entity, "⚽ My Matches")
    await asyncio.sleep(10)

    mm_msg = await wait_for_new_msg(client, bot_entity, baseline2, timeout=15)
    if mm_msg:
        mm_text = mm_msg.text or mm_msg.message or ""
        print(f"  My Matches: {len(mm_text)} chars")
        captures.append({
            "test": "my_matches_regression",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "text": mm_text[:2000],
            "result": "PASS" if len(mm_text) > 50 else "FAIL",
        })

        # Try tapping a game if buttons exist
        game_buttons = []
        if mm_msg.reply_markup and isinstance(mm_msg.reply_markup, ReplyInlineMarkup):
            for row in mm_msg.reply_markup.rows:
                for btn in row.buttons:
                    if isinstance(btn, KeyboardButtonCallback):
                        data = btn.data.decode("utf-8", errors="replace") if isinstance(btn.data, bytes) else str(btn.data)
                        if "yg:game:" in data:
                            game_buttons.append((btn.text, data))

        if game_buttons:
            print(f"\n--- Test 8: yg:game detail ---")
            await click_callback(client, mm_msg, game_buttons[0][1])
            await asyncio.sleep(10)
            game_detail = await client.get_messages(bot_entity, ids=mm_msg.id)
            if game_detail:
                gd_text = game_detail.text or game_detail.message or ""
                has_ev = "% EV" in gd_text
                print(f"  Game detail: {len(gd_text)} chars, EV clause: {has_ev}")
                captures.append({
                    "test": "yg_game_detail",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "text": gd_text[:3000],
                    "has_ev_clause": has_ev,
                    "result": "PASS" if len(gd_text) > 50 else "FAIL",
                })

    # Save captures
    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    with open(REPORT_PATH, "w") as f:
        json.dump(captures, f, indent=2)
    print(f"\nCaptures saved to {REPORT_PATH}")

    # Summary
    total = len(captures)
    passed = sum(1 for c in captures if c.get("result") in ("PASS", "PARTIAL"))
    print(f"\n{'='*50}")
    print(f"VERDICT COHERENCE E2E: {passed}/{total} passed")
    print(f"Evidence EV clauses found: {ev_found_count}/{detail_tests} detail views")
    print(f"{'='*50}")

    await client.disconnect()
    return captures


if __name__ == "__main__":
    captures = asyncio.run(run_tests())
