"""W84-E2E Run 2: Extended wait to capture hot tips (takes 60-70s to load)."""
import asyncio, os, sys, time, json
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import ReplyInlineMarkup, KeyboardButtonCallback

API_ID = 32418601
API_HASH = "95e313a8ef5b998be0515dd8328fac57"
BOT_USERNAME = "mzansiedge_bot"
STRING_SESSION_FILE = "data/telethon_session.string"
RESULTS_FILE = f"/tmp/w84_e2e_run2_{int(time.time())}.json"

def get_edge_buttons(msg):
    btns = []
    if msg.reply_markup and isinstance(msg.reply_markup, ReplyInlineMarkup):
        for row in msg.reply_markup.rows:
            for btn in row.buttons:
                if isinstance(btn, KeyboardButtonCallback):
                    d = btn.data.decode() if isinstance(btn.data, bytes) else btn.data
                    if d.startswith("edge:detail:"):
                        btns.append((btn.text, d))
    return btns

def get_all_buttons(msg):
    btns = []
    if msg.reply_markup and isinstance(msg.reply_markup, ReplyInlineMarkup):
        for row in msg.reply_markup.rows:
            for btn in row.buttons:
                if isinstance(btn, KeyboardButtonCallback):
                    d = btn.data.decode() if isinstance(btn.data, bytes) else btn.data
                    btns.append((btn.text, d))
    return btns

async def run():
    string = open(STRING_SESSION_FILE).read().strip()
    client = TelegramClient(StringSession(string), API_ID, API_HASH)
    await client.connect()
    assert await client.is_user_authorized(), "Not authorized"
    entity = await client.get_entity(BOT_USERNAME)
    print("[OK] Connected")

    results = {}

    # ── Test 1: /start ─────────────────────────────────────────────
    print("\n[1] Sending /start...")
    t0 = time.time()
    sent = await client.send_message(entity, "/start")
    sent_id = sent.id
    await asyncio.sleep(8)
    msgs = await client.get_messages(entity, limit=10)
    bot_msgs = [m for m in msgs if not m.out and m.id >= sent_id]
    start_text = bot_msgs[0].text if bot_msgs else None
    print(f"    Got: {repr(start_text[:80]) if start_text else 'None'}")
    results["start"] = {"text": start_text, "elapsed": time.time() - t0}

    # ── Test 2: Top Edge Picks (wait up to 100s) ───────────────────
    print("\n[2] Sending Top Edge Picks...")
    t0 = time.time()
    sent = await client.send_message(entity, "💎 Top Edge Picks")
    sent_id = sent.id
    print(f"    Sent (msg_id={sent_id}). Waiting up to 100s for content...")

    hot_msgs = []
    found_edge_buttons = False
    for check_at in [15, 30, 45, 60, 75, 90, 100]:
        wait_for = check_at - (time.time() - t0)
        if wait_for > 0:
            await asyncio.sleep(wait_for)
        elapsed = time.time() - t0
        msgs = await client.get_messages(entity, limit=40)
        newer = [m for m in msgs if not m.out and m.id > sent_id - 2]
        edge_found = sum(len(get_edge_buttons(m)) for m in newer)
        print(f"    {elapsed:.0f}s: {len(newer)} bot msgs, {edge_found} edge buttons")
        for m in newer:
            if m.text:
                ebtns = get_edge_buttons(m)
                abtns = get_all_buttons(m)
                print(f"      [{m.id}] {repr(m.text[:100])} | edge:{len(ebtns)} all:{len(abtns)}")
        if edge_found > 0:
            hot_msgs = newer
            found_edge_buttons = True
            break
        if elapsed > 100:
            hot_msgs = newer
            break

    results["hot_tips"] = {
        "found_edge_buttons": found_edge_buttons,
        "elapsed": time.time() - t0,
        "messages": [{"id": m.id, "text": m.text, "buttons": get_all_buttons(m)} for m in hot_msgs],
    }

    if not found_edge_buttons:
        print("\n  WARNING: No edge buttons found in hot tips")
        await client.disconnect()
        return results

    # ── Test 3: Tap ALL visible edge buttons ───────────────────────
    print(f"\n[3] Tapping all edge buttons...")
    tap_results = []
    tap_num = 0

    for msg in hot_msgs:
        edge_btns = get_edge_buttons(msg)
        for btn_text, btn_data in edge_btns:
            tap_num += 1
            match_key = btn_data.replace("edge:detail:", "")
            print(f"\n  Tap {tap_num}: {repr(btn_text)} → {btn_data}")

            # Fetch fresh message
            fresh = await client.get_messages(entity, ids=msg.id)
            if isinstance(fresh, list):
                fresh = fresh[0] if fresh else None

            t0 = time.time()
            if not fresh:
                print(f"    ERROR: Could not get fresh message {msg.id}")
                tap_results.append({"tap_num": tap_num, "match_key": match_key,
                                    "error": "no_fresh_msg", "elapsed": None, "text": None})
                continue

            try:
                await fresh.click(data=btn_data.encode())
            except Exception as e:
                print(f"    CLICK ERROR: {e}")
                tap_results.append({"tap_num": tap_num, "match_key": match_key,
                                    "error": str(e), "elapsed": None, "text": None})
                await asyncio.sleep(3)
                continue

            # Wait and fetch response
            await asyncio.sleep(20)
            elapsed = time.time() - t0
            recent = await client.get_messages(entity, limit=5)
            bot_recent = [m for m in recent if not m.out]
            resp = bot_recent[0].text if bot_recent else None
            resp_len = len(resp) if resp else 0

            status = "OK" if resp_len > 50 else "EMPTY"
            print(f"    Elapsed: {elapsed:.1f}s | Length: {resp_len} | {status}")
            if resp:
                print(f"    Preview: {repr(resp[:150])}")

            tap_results.append({
                "tap_num": tap_num,
                "btn_text": btn_text,
                "btn_data": btn_data,
                "match_key": match_key,
                "elapsed": elapsed,
                "response_text": resp[:2000] if resp else None,
                "response_len": resp_len,
                "error": None,
            })
            await asyncio.sleep(5)

    results["taps"] = {"total": tap_num, "results": tap_results}

    await client.disconnect()

    # Save results
    with open(RESULTS_FILE, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved: {RESULTS_FILE}")
    return results


if __name__ == "__main__":
    asyncio.run(run())
