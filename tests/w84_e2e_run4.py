"""W84-E2E Run 4: Clean tap test. No intervening messages between get+tap."""
import asyncio, time, json
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import ReplyInlineMarkup, KeyboardButtonCallback
from telethon.tl.functions.messages import GetBotCallbackAnswerRequest
from telethon import events

API_ID = 32418601
API_HASH = "95e313a8ef5b998be0515dd8328fac57"
STRING_SESSION_FILE = "data/telethon_session.string"
RESULTS_FILE = f"/tmp/w84_e2e_run4_{int(time.time())}.json"

def get_all_buttons(msg):
    btns = []
    if msg.reply_markup and isinstance(msg.reply_markup, ReplyInlineMarkup):
        for row in msg.reply_markup.rows:
            for btn in row.buttons:
                if isinstance(btn, KeyboardButtonCallback):
                    d = btn.data.decode() if isinstance(btn.data, bytes) else btn.data
                    btns.append((btn.text, d, btn.data if isinstance(btn.data, bytes) else btn.data.encode()))
    return btns

def get_edge_buttons(msg):
    return [(t, d, raw) for t, d, raw in get_all_buttons(msg) if d.startswith("edge:detail:")]

async def click_callback(client, msg, data_bytes):
    """Click a button using direct API call."""
    peer = await client.get_input_entity(msg.peer_id)
    try:
        result = await client(GetBotCallbackAnswerRequest(
            peer=peer,
            msg_id=msg.id,
            data=data_bytes,
        ))
        return result
    except Exception as e:
        return e

async def run():
    string = open(STRING_SESSION_FILE).read().strip()
    client = TelegramClient(StringSession(string), API_ID, API_HASH)
    await client.connect()
    assert await client.is_user_authorized(), "Not authorized"
    entity = await client.get_entity("mzansiedge_bot")
    print("[OK] Connected")

    results = {}

    # ── Pre-setup: Reset QA, then set Diamond ──────────────────────
    print("\n[PRE] QA setup...")
    await client.send_message(entity, "/qa reset")
    await asyncio.sleep(3)
    await client.send_message(entity, "/qa set_diamond")
    await asyncio.sleep(5)
    setup_msgs = await client.get_messages(entity, limit=3)
    for m in setup_msgs:
        if not m.out and m.text and "DIAMOND" in m.text:
            print(f"    QA confirm: {m.text[:60]}")
            break

    # ── Step 1: Get Top Edge Picks ─────────────────────────────────
    print("\n[1] 💎 Top Edge Picks (waiting 100s for content)...")
    t0 = time.time()
    sent = await client.send_message(entity, "💎 Top Edge Picks")
    sent_id = sent.id

    tips_msg = None
    tips_elapsed = None

    for check_at in [15, 30, 45, 60, 75, 90, 100]:
        wait_for = check_at - (time.time() - t0)
        if wait_for > 0:
            await asyncio.sleep(wait_for)
        elapsed = time.time() - t0
        msgs = await client.get_messages(entity, limit=15)
        newer = [m for m in msgs if not m.out and m.id >= sent_id]
        edge_total = sum(len(get_edge_buttons(m)) for m in newer)
        print(f"    {elapsed:.0f}s: {len(newer)} msgs, {edge_total} edge buttons")
        if edge_total > 0:
            for m in newer:
                if get_edge_buttons(m):
                    tips_msg = m
                    break
            tips_elapsed = elapsed
            break
        if elapsed > 100:
            print("    Timeout — no edge buttons found")
            break

    if not tips_msg:
        # Show what we DID get
        for m in newer:
            txt_preview = repr(m.text[:80]) if m.text else "'no text'"
            btns_list = [(t,d) for t,d,_ in get_all_buttons(m)]
            print(f"    No edges. Msgs: {txt_preview} | btns: {btns_list}")
        results["error"] = "no_edge_buttons_after_100s"
        with open(RESULTS_FILE, "w") as f:
            json.dump(results, f, indent=2, default=str)
        await client.disconnect()
        return results

    print(f"\n    Tips message found ({tips_elapsed:.1f}s)!")
    print(f"    Text preview: {tips_msg.text[:200]!r}")
    edge_btns = get_edge_buttons(tips_msg)
    print(f"    Edge buttons ({len(edge_btns)}):")
    for t, d, _ in edge_btns:
        print(f"      {t!r} → {d}")

    results["tips_load"] = {
        "elapsed": tips_elapsed,
        "text": tips_msg.text[:600] if tips_msg.text else None,
        "edge_count": len(edge_btns),
    }

    # ── Step 2: Tap each edge:detail button ───────────────────────
    print(f"\n[2] Tapping {len(edge_btns)} edge buttons (NO intervening messages)...")
    tap_results = []

    for i, (btn_text, btn_data, btn_raw) in enumerate(edge_btns, 1):
        match_key = btn_data.replace("edge:detail:", "")
        print(f"\n  Tap {i}/{len(edge_btns)}: {btn_text!r}")
        print(f"    match_key: {match_key}")

        # Fetch FRESH message immediately before clicking
        fresh_msgs = await client.get_messages(entity, ids=tips_msg.id)
        fresh = fresh_msgs if not isinstance(fresh_msgs, list) else (fresh_msgs[0] if fresh_msgs else None)
        if not fresh:
            print("    ERROR: cannot get fresh message")
            tap_results.append({"tap_num": i, "match_key": match_key, "error": "no_fresh_msg"})
            continue

        # Click directly via API
        t0_tap = time.time()
        click_result = await click_callback(client, fresh, btn_raw)

        if isinstance(click_result, Exception):
            print(f"    CLICK ERROR: {click_result}")
            # Try via message.click() as fallback
            try:
                await fresh.click(data=btn_raw)
                print("    Fallback click succeeded")
            except Exception as e2:
                print(f"    Fallback also failed: {e2}")
                tap_results.append({"tap_num": i, "match_key": match_key, "error": str(click_result)})
                await asyncio.sleep(3)
                continue

        # Wait for response
        resp = None
        resp_elapsed = None
        for check_at in [4, 8, 15, 25]:
            wait_for = check_at - (time.time() - t0_tap)
            if wait_for > 0:
                await asyncio.sleep(wait_for)
            cur_elapsed = time.time() - t0_tap
            recent = await client.get_messages(entity, limit=8)
            bot_recent = [m for m in recent if not m.out]
            if bot_recent and bot_recent[0].text:
                txt = bot_recent[0].text
                if len(txt) > 80 and match_key[:10] in txt or "The Setup" in txt or "Edge" in txt or "📋" in txt:
                    resp = txt
                    resp_elapsed = cur_elapsed
                    break
                elif len(txt) > 50:
                    resp = txt
                    resp_elapsed = cur_elapsed

        if resp is None:
            recent = await client.get_messages(entity, limit=5)
            bot_recent = [m for m in recent if not m.out]
            resp = bot_recent[0].text if bot_recent else None
            resp_elapsed = time.time() - t0_tap

        resp_len = len(resp) if resp else 0
        status = "✅ CONTENT" if resp_len > 100 else "❌ EMPTY"
        print(f"    {status} | {resp_elapsed:.1f}s | {resp_len} chars")
        if resp:
            print(f"    Preview: {resp[:200]!r}")

        tap_results.append({
            "tap_num": i,
            "match_key": match_key,
            "btn_text": btn_text,
            "elapsed": resp_elapsed,
            "text": resp[:2000] if resp else None,
            "len": resp_len,
            "error": None,
        })

        await asyncio.sleep(5)

    # ── Step 3: Bronze locked tip tap ─────────────────────────────
    print("\n[3] Testing bronze locked tap (sub:plans flow)...")
    await client.send_message(entity, "/qa reset")
    await asyncio.sleep(5)
    # Get fresh hot tips as bronze
    t0 = time.time()
    sent_b = await client.send_message(entity, "💎 Top Edge Picks")
    sent_b_id = sent_b.id
    print("    Waiting 90s for bronze tips...")
    await asyncio.sleep(90)
    elapsed_b = time.time() - t0
    msgs_b = await client.get_messages(entity, limit=15)
    newer_b = [m for m in msgs_b if not m.out and m.id >= sent_b_id]

    bronze_tap_result = None
    for msg in newer_b:
        locked = [(t, d, raw) for t, d, raw in get_all_buttons(msg) if d == "sub:plans"]
        if locked:
            btn_text, btn_data, btn_raw = locked[0]
            print(f"    Tapping locked: {btn_text!r}")
            fresh_b = await client.get_messages(entity, ids=msg.id)
            fresh_b = fresh_b if not isinstance(fresh_b, list) else (fresh_b[0] if fresh_b else None)
            if fresh_b:
                t0_sub = time.time()
                sub_result = await click_callback(client, fresh_b, btn_raw)
                await asyncio.sleep(10)
                recent_sub = await client.get_messages(entity, limit=5)
                sub_text = next((m.text for m in recent_sub if not m.out), None)
                sub_elapsed = time.time() - t0_sub
                print(f"    sub:plans response ({sub_elapsed:.1f}s): {repr(sub_text[:150]) if sub_text else 'None'}")
                bronze_tap_result = {
                    "elapsed": sub_elapsed,
                    "text": sub_text[:500] if sub_text else None,
                    "ok": bool(sub_text),
                }
                break

    # ── Summary ────────────────────────────────────────────────────
    successes = [r for r in tap_results if r.get("len", 0) > 100]
    failures = [r for r in tap_results if r.get("len", 0) <= 100]
    errors = [r for r in tap_results if r.get("error")]
    valid_elapsed = [r["elapsed"] for r in tap_results if r.get("elapsed")]

    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"  Hot tips loaded: {tips_elapsed:.1f}s")
    print(f"  Total edge taps: {len(tap_results)}")
    print(f"  With content: {len(successes)}")
    print(f"  Empty/short: {len(failures)}")
    print(f"  Errors: {len(errors)}")
    if valid_elapsed:
        print(f"  Avg response: {sum(valid_elapsed)/len(valid_elapsed):.1f}s")
        print(f"  Min/Max: {min(valid_elapsed):.1f}s / {max(valid_elapsed):.1f}s")
    if bronze_tap_result:
        print(f"  Bronze locked tap: {'OK' if bronze_tap_result['ok'] else 'FAIL'} ({bronze_tap_result['elapsed']:.1f}s)")

    results.update({
        "taps": {"total": len(tap_results), "success": len(successes),
                 "failed": len(failures), "errors": len(errors), "results": tap_results},
        "bronze_locked_tap": bronze_tap_result,
    })

    with open(RESULTS_FILE, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults: {RESULTS_FILE}")

    await client.disconnect()
    return results

if __name__ == "__main__":
    asyncio.run(run())
