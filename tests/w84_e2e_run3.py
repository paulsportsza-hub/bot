"""W84-E2E Run 3: Full E2E test with QA Diamond tier + tap all edges.

Steps:
1. /qa set_diamond  — set QA override for Diamond tier
2. /start           — verify welcome
3. 💎 Top Edge Picks — verify tips list loads (with wait)
4. Tap EVERY edge:detail button — record timings
5. /qa reset        — restore to bronze
"""
import asyncio, time, json
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import ReplyInlineMarkup, KeyboardButtonCallback

API_ID = 32418601
API_HASH = "95e313a8ef5b998be0515dd8328fac57"
STRING_SESSION_FILE = "data/telethon_qa_session.string"
RESULTS_FILE = f"/tmp/w84_e2e_run3_{int(time.time())}.json"

def get_all_buttons(msg):
    btns = []
    if msg.reply_markup and isinstance(msg.reply_markup, ReplyInlineMarkup):
        for row in msg.reply_markup.rows:
            for btn in row.buttons:
                if isinstance(btn, KeyboardButtonCallback):
                    d = btn.data.decode() if isinstance(btn.data, bytes) else btn.data
                    btns.append((btn.text, d))
    return btns

def get_edge_buttons(msg):
    return [(t, d) for t, d in get_all_buttons(msg) if d.startswith("edge:detail:")]

async def wait_for_response(client, entity, since_id, timeout=90, check_interval=5):
    """Poll for bot response, return (msgs, elapsed)."""
    t0 = time.time()
    for check_at in range(check_interval, timeout + check_interval, check_interval):
        wait_for = check_at - (time.time() - t0)
        if wait_for > 0:
            await asyncio.sleep(wait_for)
        msgs = await client.get_messages(entity, limit=20)
        newer = [m for m in msgs if not m.out and m.id > since_id]
        if newer:
            return newer, time.time() - t0
    return [], time.time() - t0

async def run():
    string = open(STRING_SESSION_FILE).read().strip()
    client = TelegramClient(StringSession(string), API_ID, API_HASH)
    await client.connect()
    assert await client.is_user_authorized(), "Not authorized"
    entity = await client.get_entity("mzansiedge_bot")
    print("[OK] Connected")

    results = {}
    all_edge_results = []

    # ── Step 0: Reset and set Diamond QA tier ─────────────────────
    print("\n[0] Setting QA Diamond tier...")
    sent = await client.send_message(entity, "/qa reset")
    await asyncio.sleep(4)
    sent = await client.send_message(entity, "/qa set_diamond")
    await asyncio.sleep(4)
    msgs = await client.get_messages(entity, limit=3)
    for m in msgs:
        if not m.out and m.text:
            print(f"    QA: {m.text[:80]}")
            break

    # ── Step 1: /start ─────────────────────────────────────────────
    print("\n[1] Sending /start...")
    sent = await client.send_message(entity, "/start")
    sent_id = sent.id
    await asyncio.sleep(6)
    msgs = await client.get_messages(entity, limit=5)
    newer = [m for m in msgs if not m.out and m.id >= sent_id]
    start_text = newer[0].text if newer else None
    print(f"    Got: {repr(start_text[:80]) if start_text else 'None'}")
    results["start"] = {"ok": bool(start_text), "text": start_text[:200] if start_text else None}

    # ── Step 2: Top Edge Picks (hot tips list) ─────────────────────
    print("\n[2] Sending 💎 Top Edge Picks (waiting up to 100s)...")
    t0 = time.time()
    sent = await client.send_message(entity, "💎 Top Edge Picks")
    sent_id = sent.id

    all_tip_pages = {}  # page_num -> msg
    found_tips = False
    hot_tips_elapsed = None

    for check_at in [15, 30, 45, 60, 75, 90, 100]:
        wait_for = check_at - (time.time() - t0)
        if wait_for > 0:
            await asyncio.sleep(wait_for)
        elapsed = time.time() - t0
        msgs = await client.get_messages(entity, limit=30)
        newer = [m for m in msgs if not m.out and m.id >= sent_id]
        edge_total = sum(len(get_edge_buttons(m)) for m in newer)
        print(f"    {elapsed:.0f}s: {len(newer)} msgs, {edge_total} edge buttons")
        for m in newer:
            ebtns = get_edge_buttons(m)
            abtns = get_all_buttons(m)
            if m.text:
                print(f"      [msg {m.id}] edge:{len(ebtns)} all:{len(abtns)} text: {m.text[:80]!r}")
        if edge_total > 0:
            for m in newer:
                if get_edge_buttons(m):
                    all_tip_pages[0] = m
            found_tips = True
            hot_tips_elapsed = elapsed
            break
        if elapsed > 100:
            break

    if not found_tips:
        print("    WARNING: No edge buttons found even after 100s")
        results["hot_tips"] = {"ok": False, "elapsed": time.time() - t0, "error": "no_edge_buttons"}
        await client.disconnect()
        return results

    results["hot_tips"] = {
        "ok": True,
        "elapsed": hot_tips_elapsed,
        "message_text": all_tip_pages[0].text[:600] if all_tip_pages.get(0) else None,
        "edge_buttons_page0": get_edge_buttons(all_tip_pages[0]) if all_tip_pages.get(0) else [],
    }
    print(f"    Loaded in {hot_tips_elapsed:.1f}s with {len(get_edge_buttons(all_tip_pages[0]))} edge buttons")

    # Collect edge buttons across all pages
    all_edge_buttons = []
    msg_by_edge = {}

    for msg in [all_tip_pages[0]]:
        for btn_text, btn_data in get_edge_buttons(msg):
            all_edge_buttons.append((btn_text, btn_data, msg))
            msg_by_edge[btn_data] = msg

    # Navigate to next pages to collect all edges
    print("\n[2b] Collecting edges from all pages...")
    last_msg = all_tip_pages[0]
    for page_attempt in range(1, 5):  # up to page 4
        next_btn = None
        for t, d in get_all_buttons(last_msg):
            if d.startswith("hot:page:"):
                page_num = int(d.split(":")[-1])
                if page_num == page_attempt:
                    next_btn = (t, d)
                    break

        if not next_btn:
            print(f"    No Next button for page {page_attempt} — done collecting")
            break

        print(f"    Tapping page {page_attempt}: {next_btn[1]}")
        fresh = await client.get_messages(entity, ids=last_msg.id)
        if isinstance(fresh, list):
            fresh = fresh[0] if fresh else None

        if not fresh:
            break

        sent_page = await client.send_message(entity, f"/qa set_diamond")  # keep diamond active
        await asyncio.sleep(2)

        t0_page = time.time()
        try:
            await fresh.click(data=next_btn[1].encode())
        except Exception as e:
            print(f"    Page click error: {e}")
            break
        await asyncio.sleep(10)
        page_elapsed = time.time() - t0_page

        msgs = await client.get_messages(entity, limit=10)
        newer_page = [m for m in msgs if not m.out and m.id > last_msg.id]
        for m in newer_page:
            ebtns = get_edge_buttons(m)
            if ebtns:
                print(f"    Page {page_attempt}: {len(ebtns)} edge buttons")
                for btn_text, btn_data in ebtns:
                    all_edge_buttons.append((btn_text, btn_data, m))
                    msg_by_edge[btn_data] = m
                last_msg = m
                all_tip_pages[page_attempt] = m
                break
        else:
            print(f"    Page {page_attempt}: no edge buttons, stopping")
            break

    print(f"\n    Total edge buttons collected: {len(all_edge_buttons)}")
    for btn_text, btn_data, _ in all_edge_buttons:
        mk = btn_data.replace("edge:detail:", "")
        print(f"      {btn_text!r} → {mk}")

    # ── Step 3: Tap EVERY edge button ─────────────────────────────
    print(f"\n[3] Tapping all {len(all_edge_buttons)} edge buttons...")

    for i, (btn_text, btn_data, src_msg) in enumerate(all_edge_buttons, 1):
        match_key = btn_data.replace("edge:detail:", "")
        print(f"\n  Tap {i}/{len(all_edge_buttons)}: {btn_text!r}")
        print(f"    match_key: {match_key}")

        # Fetch fresh message
        fresh = await client.get_messages(entity, ids=src_msg.id)
        if isinstance(fresh, list):
            fresh = fresh[0] if fresh else None

        if not fresh:
            print("    ERROR: cannot fetch source msg")
            all_edge_results.append({
                "tap_num": i, "match_key": match_key, "btn_text": btn_text,
                "error": "no_fresh_msg", "elapsed": None, "text": None, "len": 0,
            })
            continue

        ref_id = fresh.id
        t0_tap = time.time()
        try:
            await fresh.click(data=btn_data.encode())
        except Exception as e:
            print(f"    CLICK ERROR: {e}")
            all_edge_results.append({
                "tap_num": i, "match_key": match_key, "btn_text": btn_text,
                "error": str(e), "elapsed": None, "text": None, "len": 0,
            })
            await asyncio.sleep(3)
            continue

        # Wait for response: check at 5s, 10s, 20s, 30s
        resp = None
        resp_elapsed = None
        for check_at in [5, 10, 20, 30]:
            wait_for = check_at - (time.time() - t0_tap)
            if wait_for > 0:
                await asyncio.sleep(wait_for)
            cur_elapsed = time.time() - t0_tap
            recent = await client.get_messages(entity, limit=5)
            # Most recent bot msg
            bot_recent = [m for m in recent if not m.out]
            if bot_recent and bot_recent[0].text and len(bot_recent[0].text) > 50:
                resp = bot_recent[0].text
                resp_elapsed = cur_elapsed
                break

        if resp is None:
            recent = await client.get_messages(entity, limit=5)
            bot_recent = [m for m in recent if not m.out]
            resp = bot_recent[0].text if bot_recent else None
            resp_elapsed = time.time() - t0_tap

        resp_len = len(resp) if resp else 0
        status = "✅ OK" if resp_len > 100 else "❌ SHORT/EMPTY"
        print(f"    {status} | {resp_elapsed:.1f}s | {resp_len} chars")
        if resp:
            print(f"    Preview: {resp[:200]!r}")

        all_edge_results.append({
            "tap_num": i,
            "match_key": match_key,
            "btn_text": btn_text,
            "elapsed": resp_elapsed,
            "text": resp[:2000] if resp else None,
            "len": resp_len,
            "error": None,
        })

        # Brief pause between taps
        await asyncio.sleep(5)

    # ── Step 4: Also test sub:plans tap (bronze locked) ───────────
    print("\n[4] Testing sub:plans tap (what bronze user sees)...")
    sent = await client.send_message(entity, "/qa reset")
    await asyncio.sleep(4)
    sent = await client.send_message(entity, "💎 Top Edge Picks")
    sent_id = sent.id
    await asyncio.sleep(90)  # Wait 90s for fresh tips (now on bronze)
    msgs = await client.get_messages(entity, limit=20)
    newer = [m for m in msgs if not m.out and m.id >= sent_id]
    sub_plans_btns = []
    tips_msg_bronze = None
    for m in newer:
        abtns = get_all_buttons(m)
        locked = [(t, d) for t, d in abtns if d == "sub:plans"]
        if locked:
            sub_plans_btns = locked
            tips_msg_bronze = m
            print(f"    Bronze tips msg found: {len(locked)} locked buttons")
            break

    if tips_msg_bronze and sub_plans_btns:
        # Tap first locked button
        btn_text, btn_data = sub_plans_btns[0]
        print(f"    Tapping locked: {btn_text!r}")
        fresh = await client.get_messages(entity, ids=tips_msg_bronze.id)
        if isinstance(fresh, list):
            fresh = fresh[0] if fresh else None
        if fresh:
            t0_sub = time.time()
            try:
                await fresh.click(data=btn_data.encode())
            except Exception as e:
                print(f"    sub:plans click error: {e}")
            await asyncio.sleep(10)
            recent = await client.get_messages(entity, limit=5)
            bot_recent = [m for m in recent if not m.out]
            sub_text = bot_recent[0].text if bot_recent else None
            sub_elapsed = time.time() - t0_sub
            print(f"    sub:plans response ({sub_elapsed:.1f}s): {repr(sub_text[:150]) if sub_text else 'None'}")
            results["sub_plans_tap"] = {
                "elapsed": sub_elapsed,
                "text": sub_text[:500] if sub_text else None,
                "ok": bool(sub_text),
            }

    # ── Summary ────────────────────────────────────────────────────
    successes = [r for r in all_edge_results if r.get("len", 0) > 100]
    failures = [r for r in all_edge_results if r.get("len", 0) <= 100]
    errors = [r for r in all_edge_results if r.get("error")]
    valid_elapsed = [r["elapsed"] for r in all_edge_results if r.get("elapsed")]

    print(f"\n{'='*60}")
    print(f"SUMMARY")
    print(f"  Hot tips loaded in: {hot_tips_elapsed:.1f}s")
    print(f"  Total edge taps: {len(all_edge_results)}")
    print(f"  With content (>100 chars): {len(successes)}")
    print(f"  Empty/short: {len(failures)}")
    print(f"  Errors: {len(errors)}")
    if valid_elapsed:
        print(f"  Avg tap response: {sum(valid_elapsed)/len(valid_elapsed):.1f}s")
        print(f"  Min: {min(valid_elapsed):.1f}s  Max: {max(valid_elapsed):.1f}s")

    results["taps"] = {
        "total": len(all_edge_results),
        "success": len(successes),
        "failed": len(failures),
        "errors": len(errors),
        "results": all_edge_results,
    }

    # Save
    with open(RESULTS_FILE, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults: {RESULTS_FILE}")

    await client.disconnect()
    return results

if __name__ == "__main__":
    asyncio.run(run())
