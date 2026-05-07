"""W84-P1N Part 2: My Matches breakdown test only."""
import asyncio, time, json
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import ReplyInlineMarkup, KeyboardButtonCallback

API_ID = 32418601
API_HASH = "95e313a8ef5b998be0515dd8328fac57"
SESSION_FILE = "data/telethon_qa_session.string"

def all_btns(msg):
    out = []
    if msg.reply_markup and isinstance(msg.reply_markup, ReplyInlineMarkup):
        for row in msg.reply_markup.rows:
            for btn in row.buttons:
                if isinstance(btn, KeyboardButtonCallback):
                    d = btn.data.decode() if isinstance(btn.data, bytes) else btn.data
                    raw = btn.data if isinstance(btn.data, bytes) else btn.data.encode()
                    out.append((btn.text, d, raw))
    return out

async def wait_new(client, entity, after_id, timeout, me_id, min_len=30):
    t0 = time.time()
    deadline = t0 + timeout
    while time.time() < deadline:
        await asyncio.sleep(2)
        msgs = await client.get_messages(entity, limit=10)
        for m in msgs:
            if m.id > after_id and m.sender_id != me_id:
                if len(m.text or "") >= min_len:
                    return m, time.time() - t0
    return None, time.time() - t0

async def run():
    with open(SESSION_FILE) as f:
        ss = f.read().strip()
    async with TelegramClient(StringSession(ss), API_ID, API_HASH) as client:
        entity = await client.get_entity("mzansiedge_bot")
        me = await client.get_me()
        me_id = me.id
        print(f"[OK] Connected as {me.first_name}")

        # Ensure diamond
        await client.send_message(entity, "/qa set_diamond")
        await asyncio.sleep(4)

        # Try My Matches via sticky keyboard
        print("\n[1] ⚽ My Matches...")
        sent = await client.send_message(entity, "⚽ My Matches")
        sent_id = sent.id
        t0 = time.time()

        # Wait up to 60s
        mm_msg = None
        for poll in [5, 10, 20, 35, 50, 60]:
            wait = poll - (time.time() - t0)
            if wait > 0:
                await asyncio.sleep(wait)
            elapsed = time.time() - t0
            msgs = await client.get_messages(entity, limit=10)
            newer = [m for m in msgs if not m.out and m.id > sent_id]
            yg_total = sum(1 for m in newer for _, d, _ in all_btns(m) if d.startswith("yg:"))
            print(f"    {elapsed:.0f}s: {len(newer)} msgs, {yg_total} yg: buttons")
            if newer and len(newer[0].text or "") > 30:
                mm_msg = newer[0]
                mm_elapsed = elapsed
                break
            if elapsed >= 60:
                break

        if not mm_msg:
            print("  FAIL: No My Matches response")
            # Try /schedule as fallback
            print("\n[1b] Trying /schedule...")
            sent2 = await client.send_message(entity, "/schedule")
            mm_msg, mm_elapsed = await wait_new(client, entity, sent2.id, 30, me_id, 30)
            if not mm_msg:
                print("  FAIL: /schedule also failed")
                return

        print(f"\n  My Matches response ({mm_elapsed:.1f}s):")
        print(f"  {len(mm_msg.text or '')} chars")
        print(f"  Text: {(mm_msg.text or '')[:400]!r}")
        mm_btns = all_btns(mm_msg)
        game_btns = [(t, d, r) for t, d, r in mm_btns if d.startswith("yg:game:")]
        print(f"  Game buttons: {len(game_btns)}")
        for t, d, _ in game_btns[:5]:
            print(f"    {t!r} → {d}")

        breakdowns = []
        for i, (gbt, gbd, gbr) in enumerate(game_btns[:2], 1):
            event_id = gbd.replace("yg:game:", "")
            print(f"\n[{i+1}] Breakdown: {gbt!r} ({event_id})")

            # Re-fetch fresh message
            fresh_mm = await client.get_messages(entity, ids=mm_msg.id)
            latest = await client.get_messages(entity, limit=1)
            last_id = max(fresh_mm.id, latest[0].id if latest else 0)

            t0_bd = time.time()
            try:
                await fresh_mm.click(data=gbr)
            except Exception as e:
                print(f"  click error: {e}")
                # Try row/col
                for ri, row in enumerate(fresh_mm.reply_markup.rows if fresh_mm.reply_markup else []):
                    for bi, btn in enumerate(row.buttons):
                        if isinstance(btn, KeyboardButtonCallback):
                            raw2 = btn.data if isinstance(btn.data, bytes) else btn.data.encode()
                            if raw2 == gbr:
                                await fresh_mm.click(ri, bi)
                                break

            bd_msg = None
            for poll in [10, 20, 35, 55, 70]:
                wait = poll - (time.time() - t0_bd)
                if wait > 0:
                    await asyncio.sleep(wait)
                cur_elapsed = time.time() - t0_bd
                msgs = await client.get_messages(entity, limit=8)
                for m in msgs:
                    if m.id > last_id and m.sender_id != me_id and len(m.text or "") > 150:
                        bd_msg = m
                        bd_elapsed = cur_elapsed
                        break
                    # Also check if mm_msg was edited
                    try:
                        updated = await client.get_messages(entity, ids=mm_msg.id)
                        if updated and updated.text != (mm_msg.text or "") and len(updated.text or "") > 150:
                            bd_msg = updated
                            bd_elapsed = cur_elapsed
                            break
                    except Exception:
                        pass
                if bd_msg:
                    break

            if not bd_msg:
                print(f"  FAIL: No breakdown response in 70s")
                continue

            bd_text = bd_msg.text or ""
            bd_btns = all_btns(bd_msg)
            bd_btn_labels = [t for t, _, _ in bd_btns]

            print(f"\n  ✅ Breakdown {i} loaded ({bd_elapsed:.1f}s, {len(bd_text)} chars)")
            print(f"  Buttons: {bd_btn_labels}")
            print(f"\n  Full breakdown text:")
            print("  " + "─"*50)
            for line in bd_text.split("\n"):
                print(f"  {line}")
            print("  " + "─"*50)

            breakdowns.append({
                "index": i,
                "event_id": event_id,
                "btn_text": gbt,
                "elapsed_s": bd_elapsed,
                "text": bd_text,
                "text_length": len(bd_text),
                "buttons": bd_btn_labels,
            })

            # Navigate back
            back_bd = next(
                ((t, d, r) for t, d, r in bd_btns
                 if "back" in t.lower() and ("match" in t.lower() or "game" in t.lower()
                                             or "↩" in t)),
                None
            )
            if not back_bd:
                back_bd = next(((t, d, r) for t, d, r in bd_btns if "↩" in t), None)
            if back_bd:
                print(f"\n  → Back: {back_bd[0]!r}")
                t0_back = time.time()
                try:
                    await bd_msg.click(data=back_bd[2])
                except Exception as e:
                    print(f"    back click error: {e}")
                await asyncio.sleep(8)
                back_resp = await client.get_messages(entity, limit=3)
                for br in back_resp:
                    if not br.out and len(br.text or "") > 20:
                        print(f"    Back returned: {(br.text or '')[:80]!r}")
                        mm_msg = br
                        break

            await asyncio.sleep(4)

        # Write results
        results = {
            "my_matches_elapsed": mm_elapsed,
            "my_matches_text": (mm_msg.text or "")[:1000] if mm_msg else None,
            "breakdowns": breakdowns,
        }
        out = f"/tmp/w84_p1n_breakdown_{int(time.time())}.json"
        with open(out, "w") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print(f"\nResults saved: {out}")
        return results

if __name__ == "__main__":
    asyncio.run(run())
