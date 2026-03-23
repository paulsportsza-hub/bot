#!/usr/bin/env python3
"""W84-E2E: Tap every visible edge and record exactly what the user sees."""
import asyncio, os, sys, time, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import ReplyInlineMarkup, KeyboardButtonCallback

API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "")
BOT = "mzansiedge_bot"
STRING_SESSION_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "telethon_session.string")

RESULTS = []

async def main():
    string = open(STRING_SESSION_FILE).read().strip()
    client = TelegramClient(StringSession(string), API_ID, API_HASH)
    await client.connect()
    ent = await client.get_entity(BOT)

    # ── Step 1: Send /tips, record response ──
    print("=== Step 1: /tips ===")
    sent = await client.send_message(ent, "/tips")
    t0 = time.time()
    await asyncio.sleep(4)
    msgs = await client.get_messages(ent, limit=10)
    tips_msgs = [m for m in msgs if m.id > sent.id and not m.out]
    tips_msg = tips_msgs[-1] if tips_msgs else None
    print(f"Response time: {time.time()-t0:.1f}s, got {len(tips_msgs)} messages")
    if tips_msg:
        print(f"Tips text (first 300): {(tips_msg.text or '')[:300]}")

    # ── Step 2: Extract all edge buttons ──
    print("\n=== Step 2: Extract buttons ===")
    edge_buttons = []
    if tips_msg and tips_msg.reply_markup and isinstance(tips_msg.reply_markup, ReplyInlineMarkup):
        for row in tips_msg.reply_markup.rows:
            for btn in row.buttons:
                if isinstance(btn, KeyboardButtonCallback):
                    data = btn.data.decode("utf-8", errors="replace")
                    print(f"  Button: '{btn.text}' → '{data}'")
                    if data.startswith("edge:detail:"):
                        edge_buttons.append((btn.text, data, btn.data))
    print(f"Found {len(edge_buttons)} edge buttons")

    # ── Step 3: Tap each edge ──
    print("\n=== Step 3: Tap each edge ===")
    for i, (btn_text, cb_data, raw_data) in enumerate(edge_buttons, 1):
        print(f"\n--- Tapping edge {i}: '{btn_text}' (data='{cb_data}') ---")

        # Reload /tips fresh to get a clean message
        await asyncio.sleep(2)
        sent2 = await client.send_message(ent, "/tips")
        await asyncio.sleep(3)
        msgs2 = await client.get_messages(ent, limit=10)
        fresh_tips = [m for m in msgs2 if m.id > sent2.id and not m.out]
        fresh_msg = fresh_tips[-1] if fresh_tips else None

        if not fresh_msg:
            print("  ERROR: could not reload tips")
            RESULTS.append({"edge": btn_text, "data": cb_data, "status": "ERROR_NO_TIPS",
                             "load_time": 0, "analysing_seen": False, "content": "", "content_len": 0})
            continue

        # Find the matching button on fresh tips
        target_btn = None
        if fresh_msg.reply_markup and isinstance(fresh_msg.reply_markup, ReplyInlineMarkup):
            for row in fresh_msg.reply_markup.rows:
                for btn in row.buttons:
                    if isinstance(btn, KeyboardButtonCallback):
                        d = btn.data.decode("utf-8", errors="replace")
                        if d == cb_data:
                            target_btn = btn
                            break

        if not target_btn:
            print(f"  WARNING: button '{cb_data}' not found on fresh tips page, using original raw_data")
            # Try with original raw_data
            try:
                t_tap = time.time()
                await fresh_msg.click(data=raw_data)
            except Exception as e:
                print(f"  Click failed: {e}")
                RESULTS.append({"edge": btn_text, "data": cb_data, "status": f"CLICK_FAILED:{e}",
                                 "load_time": 0, "analysing_seen": False, "content": "", "content_len": 0})
                continue
        else:
            t_tap = time.time()
            try:
                await fresh_msg.click(data=target_btn.data)
            except Exception as e:
                print(f"  Click failed: {e}")
                RESULTS.append({"edge": btn_text, "data": cb_data, "status": f"CLICK_FAILED:{e}",
                                 "load_time": 0, "analysing_seen": False, "content": "", "content_len": 0})
                continue

        # Wait and poll for response
        deadline = t_tap + 35
        analysing_seen = False
        final_content = ""
        response_time = 0.0

        while time.time() < deadline:
            await asyncio.sleep(0.5)
            # Check if message was edited
            edited = await client.get_messages(ent, ids=fresh_msg.id)
            all_msgs = await client.get_messages(ent, limit=15)
            new_msgs = [m for m in all_msgs if m.id > fresh_msg.id and not m.out]

            # Check for "Analysing..." in edited message
            if edited and edited.text:
                if "analysing" in edited.text.lower() or "🔄" in edited.text or "⏳" in edited.text:
                    if not analysing_seen:
                        print(f"  'Analysing...' seen at {time.time()-t_tap:.1f}s")
                        analysing_seen = True
                if edited.text != fresh_msg.text and len(edited.text) > 50:
                    final_content = edited.text
                    response_time = time.time() - t_tap
                    if not analysing_seen or len(final_content) > 200:
                        break  # Got real content

            # Check new messages
            for nm in new_msgs:
                if nm.text and len(nm.text) > 100:
                    final_content = nm.text
                    response_time = time.time() - t_tap
                    break
            if final_content and response_time > 0:
                break

        if not final_content:
            response_time = time.time() - t_tap
            # One final check
            edited = await client.get_messages(ent, ids=fresh_msg.id)
            if edited and edited.text and edited.text != fresh_msg.text:
                final_content = edited.text
            else:
                final_content = ""

        status = "OK" if len(final_content) > 100 else "NO_RESPONSE"
        print(f"  Status: {status} | Time: {response_time:.1f}s | Len: {len(final_content)} chars")
        if final_content:
            print(f"  Content preview: {final_content[:200]}")
        else:
            print(f"  NO CONTENT RECEIVED after {response_time:.1f}s")

        RESULTS.append({
            "edge": btn_text,
            "data": cb_data,
            "status": status,
            "load_time": round(response_time, 1),
            "analysing_seen": analysing_seen,
            "content": final_content[:500],
            "content_len": len(final_content),
        })

    await client.disconnect()

    # Summary
    print("\n" + "=" * 60)
    print("W84-E2E RESULTS SUMMARY")
    print("=" * 60)
    for r in RESULTS:
        print(f"  [{r['status']:>12}] {r['edge'][:40]} → {r['load_time']}s, {r['content_len']} chars, analysing={r['analysing_seen']}")

    # Save
    os.makedirs(os.path.expanduser("~/reports/screenshots/w84_tap"), exist_ok=True)
    out = os.path.expanduser("~/reports/screenshots/w84_tap/results.json")
    with open(out, "w") as f:
        json.dump({"results": RESULTS}, f, indent=2)
    print(f"\nSaved: {out}")

asyncio.run(main())
