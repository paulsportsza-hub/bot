"""W84-E2E Navigation: Proper back-and-forth for each edge tap.

After each edge:detail tap, the message is EDITED to show detail.
We must tap "Back to Edge Picks" → get fresh tips list → tap next edge.
"""
import asyncio, time, json
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import ReplyInlineMarkup, KeyboardButtonCallback
from telethon.tl.functions.messages import GetBotCallbackAnswerRequest

API_ID = 32418601
API_HASH = "95e313a8ef5b998be0515dd8328fac57"
STRING_SESSION_FILE = "data/telethon_session.string"
RESULTS_FILE = f"/tmp/w84_e2e_nav_{int(time.time())}.json"

def get_buttons(msg):
    btns = []
    if msg.reply_markup and isinstance(msg.reply_markup, ReplyInlineMarkup):
        for row in msg.reply_markup.rows:
            for btn in row.buttons:
                if isinstance(btn, KeyboardButtonCallback):
                    d = btn.data.decode() if isinstance(btn.data, bytes) else btn.data
                    raw = btn.data if isinstance(btn.data, bytes) else btn.data.encode()
                    btns.append((btn.text, d, raw))
    return btns

def get_edge_buttons(msg):
    return [(t, d, r) for t, d, r in get_buttons(msg) if d.startswith("edge:detail:")]

def get_back_buttons(msg):
    back_keys = ("hot:back", "hot:go", "hot:page:0")
    return [(t, d, r) for t, d, r in get_buttons(msg) if any(d == k for k in back_keys)]

async def api_click(client, msg, data_bytes):
    peer = await client.get_input_entity(msg.peer_id)
    return await client(GetBotCallbackAnswerRequest(peer=peer, msg_id=msg.id, data=data_bytes))

async def run():
    string = open(STRING_SESSION_FILE).read().strip()
    client = TelegramClient(StringSession(string), API_ID, API_HASH)
    await client.connect()
    assert await client.is_user_authorized(), "Not authorized"
    entity = await client.get_entity("mzansiedge_bot")
    print("[OK] Connected")

    results = {"taps": []}

    # ── Pre: Set Diamond QA ──────────────────────────────────────
    print("[PRE] Setting QA Diamond...")
    await client.send_message(entity, "/qa reset")
    await asyncio.sleep(3)
    await client.send_message(entity, "/qa set_diamond")
    await asyncio.sleep(5)

    # ── Load tips (diamond mode) ──────────────────────────────────
    print("[1] Loading Top Edge Picks...")
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
            break

    if not tips_msg:
        print("  ERROR: No tips loaded")
        await client.disconnect()
        return results

    all_edges = get_edge_buttons(tips_msg)
    print(f"    Found {len(all_edges)} edges in {tips_elapsed:.1f}s:")
    for t, d, _ in all_edges:
        print(f"      {t!r} → {d}")

    results["tips_load"] = {
        "elapsed": tips_elapsed,
        "edge_count": len(all_edges),
        "text": tips_msg.text[:500] if tips_msg.text else None,
    }

    # ── Tap each edge, navigate back, repeat ─────────────────────
    print(f"\n[2] Tapping {len(all_edges)} edges with back navigation...")

    current_msg_id = tips_msg.id
    tap_results = []

    for i, (btn_text, btn_data, btn_raw) in enumerate(all_edges, 1):
        match_key = btn_data.replace("edge:detail:", "")
        print(f"\n  Tap {i}/{len(all_edges)}: {btn_text!r} ({match_key})")

        # Get current state of the tips/detail message
        fresh = await client.get_messages(entity, ids=current_msg_id)
        fresh = fresh if not isinstance(fresh, list) else (fresh[0] if fresh else None)
        if not fresh:
            print("    ERROR: message lost")
            tap_results.append({"tap_num": i, "match_key": match_key, "error": "msg_lost"})
            continue

        # Check if we need to go back to tips first
        curr_btns = get_buttons(fresh)
        curr_edge_btns = [(t, d, r) for t, d, r in curr_btns if d.startswith("edge:detail:")]
        curr_back_btns = get_back_buttons(fresh)

        if not curr_edge_btns and curr_back_btns:
            # We're on a detail page, need to go back first
            back_t, back_d, back_r = curr_back_btns[0]
            print(f"    Currently on detail page, going back via {back_d!r}...")
            try:
                await api_click(client, fresh, back_r)
            except Exception as e:
                print(f"    Back click error: {e}")
                try:
                    await fresh.click(data=back_r)
                except Exception as e2:
                    print(f"    Back fallback error: {e2}")
            await asyncio.sleep(8)
            fresh = await client.get_messages(entity, ids=current_msg_id)
            fresh = fresh if not isinstance(fresh, list) else (fresh[0] if fresh else None)
            if fresh:
                curr_edge_btns = get_edge_buttons(fresh)
                print(f"    After back: {len(curr_edge_btns)} edge buttons available")

        # Now find the specific edge button we want
        target = next(((t, d, r) for t, d, r in get_edge_buttons(fresh) if d == btn_data), None)
        if not target:
            print(f"    WARNING: edge button {btn_data} not found in current tips list")
            # Get all edge buttons from fresh message
            curr_all_edges = get_edge_buttons(fresh) if fresh else []
            print(f"    Available edges: {[d for _,d,_ in curr_all_edges]}")
            # Try to tap by position
            if i - 1 < len(curr_all_edges):
                target = curr_all_edges[i - 1]
                print(f"    Using positional fallback: {target[1]}")
            else:
                tap_results.append({"tap_num": i, "match_key": match_key, "error": "button_not_found"})
                continue

        target_t, target_d, target_r = target

        # TAP IT
        t0_tap = time.time()
        try:
            await api_click(client, fresh, target_r)
        except Exception as e:
            print(f"    API click error: {e}")
            try:
                await fresh.click(data=target_r)
                print("    Fallback click OK")
            except Exception as e2:
                print(f"    Both clicks failed: {e2}")
                tap_results.append({"tap_num": i, "match_key": match_key, "error": str(e)})
                await asyncio.sleep(3)
                continue

        # Wait for response (edit of same message)
        resp = None
        resp_elapsed = None

        for check_at in [4, 8, 15, 25]:
            wait_for = check_at - (time.time() - t0_tap)
            if wait_for > 0:
                await asyncio.sleep(wait_for)
            cur_elapsed = time.time() - t0_tap
            # Fetch the message — it should now be the detail view
            edited = await client.get_messages(entity, ids=current_msg_id)
            edited = edited if not isinstance(edited, list) else (edited[0] if edited else None)
            if edited and edited.text:
                txt = edited.text
                # Check if we got detail content (different from tips list)
                if "The Setup" in txt or "📋" in txt or match_key.replace("_", " ") in txt.lower():
                    resp = txt
                    resp_elapsed = cur_elapsed
                    print(f"    Got detail content at {cur_elapsed:.1f}s")
                    break
                elif len(txt) > 200:
                    resp = txt
                    resp_elapsed = cur_elapsed

        if resp is None:
            edited = await client.get_messages(entity, ids=current_msg_id)
            edited = edited if not isinstance(edited, list) else (edited[0] if edited else None)
            resp = edited.text if edited else None
            resp_elapsed = time.time() - t0_tap

        resp_len = len(resp) if resp else 0
        status = "✅ CONTENT" if resp_len > 100 else "❌ EMPTY"
        print(f"    {status} | {resp_elapsed:.1f}s | {resp_len} chars")
        if resp:
            print(f"    Preview: {resp[:300]!r}")

        tap_results.append({
            "tap_num": i,
            "match_key": match_key,
            "btn_text": btn_text,
            "elapsed": resp_elapsed,
            "text": resp[:3000] if resp else None,
            "len": resp_len,
            "error": None,
        })

        await asyncio.sleep(5)

    # ── Bronze: test locked tap ───────────────────────────────────
    print("\n[3] Bronze locked tap test...")
    await client.send_message(entity, "/qa reset")
    await asyncio.sleep(4)
    t0 = time.time()
    sent_b = await client.send_message(entity, "💎 Top Edge Picks")
    sent_b_id = sent_b.id
    print("    Waiting 90s for bronze tips...")
    await asyncio.sleep(90)
    bronze_elapsed = time.time() - t0
    msgs_b = await client.get_messages(entity, limit=15)
    newer_b = [m for m in msgs_b if not m.out and m.id >= sent_b_id]

    bronze_result = {"elapsed_load": bronze_elapsed}
    for msg in newer_b:
        locked = [(t, d, r) for t, d, r in get_buttons(msg) if d == "sub:plans"]
        if locked:
            btn_text_b, btn_data_b, btn_raw_b = locked[0]
            print(f"    Tapping {btn_text_b!r}")
            fresh_b = await client.get_messages(entity, ids=msg.id)
            fresh_b = fresh_b if not isinstance(fresh_b, list) else (fresh_b[0] if fresh_b else None)
            if fresh_b:
                t0_sub = time.time()
                try:
                    await api_click(client, fresh_b, btn_raw_b)
                except Exception as e:
                    print(f"    sub:plans click err: {e}")
                    try:
                        await fresh_b.click(data=btn_raw_b)
                    except:
                        pass
                await asyncio.sleep(10)
                sub_elapsed = time.time() - t0_sub
                recent_sub = await client.get_messages(entity, limit=5)
                sub_text = next((m.text for m in recent_sub if not m.out), None)
                print(f"    sub:plans ({sub_elapsed:.1f}s): {repr(sub_text[:120]) if sub_text else 'None'}")
                bronze_result.update({
                    "tap_elapsed": sub_elapsed,
                    "text": sub_text[:400] if sub_text else None,
                    "ok": bool(sub_text and len(sub_text) > 50),
                })
            break

    # ── Final summary ─────────────────────────────────────────────
    successes = [r for r in tap_results if r.get("len", 0) > 100]
    errors = [r for r in tap_results if r.get("error")]
    valid_elapsed = [r["elapsed"] for r in tap_results if r.get("elapsed")]

    print(f"\n{'='*60}")
    print("FINAL SUMMARY (Diamond tier):")
    print(f"  Tips load time:   {tips_elapsed:.1f}s")
    print(f"  Total taps:       {len(tap_results)}")
    print(f"  Content received: {len(successes)}/{len(tap_results)}")
    print(f"  Errors:           {len(errors)}")
    if valid_elapsed:
        print(f"  Avg tap→content:  {sum(valid_elapsed)/len(valid_elapsed):.1f}s")
        print(f"  Min/Max:          {min(valid_elapsed):.1f}s / {max(valid_elapsed):.1f}s")
    print(f"\nBronze locked tap: {'OK' if bronze_result.get('ok') else 'FAIL'}")

    results.update({"taps": {"results": tap_results, "total": len(tap_results),
                             "success": len(successes), "errors": len(errors)},
                    "bronze": bronze_result})

    with open(RESULTS_FILE, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults: {RESULTS_FILE}")
    await client.disconnect()
    return results

if __name__ == "__main__":
    asyncio.run(run())
