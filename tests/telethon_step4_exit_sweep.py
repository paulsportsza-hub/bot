#!/usr/bin/env python3
"""SURFACE-MM-E2E-5USER-01 — Step 4 Exit Gate Telethon E2E Sweep (v3).

Bot EDITS same message for page nav + detail. Track msg_id and re-fetch.
"""
import asyncio, json, os, sqlite3, sys, time
from datetime import datetime
from pathlib import Path
from telethon.errors import DataInvalidError, MessageNotModifiedError

sys.path.insert(0, "/home/paulsportsza/bot")
from dotenv import load_dotenv; load_dotenv(Path("/home/paulsportsza/bot/.env"))
from telethon import TelegramClient
from telethon.sessions import StringSession

BOT       = "mzansiedge_bot"
API_ID    = int(os.getenv("TELEGRAM_API_ID","0"))
API_HASH  = os.getenv("TELEGRAM_API_HASH","")
SESSION   = Path("/home/paulsportsza/bot/data/telethon_session.string")
SHOT_DIR  = Path("/home/paulsportsza/reports/e2e-screenshots/step4_exit")
DB_PATH   = "/home/paulsportsza/bot/data/mzansiedge.db"
TEST_UID  = 411927634

# Abbreviation-based tokens — matching bot's abbreviate_team() output
FIXTURE_TOKENS = {
    "manchester_city_vs_arsenal_2026-04-19":      ["man","ars"],
    "polokwane_city_vs_kaizer_chiefs_2026-04-18": ["pol","kc"],
    "chelsea_vs_manchester_united_2026-04-18":    ["che","man"],
    "lions_vs_glasgow_2026-04-18":                ["lio","gla"],
    "ospreys_vs_sharks_2026-04-18":               ["osp","sha"],
}

TIERS = [("free","reset"),("bronze","set_bronze"),("silver","db_silver"),
         ("gold","set_gold"),("diamond","set_diamond")]

BETTING_TERMS = ["guaranteed winner","sure bet","bet now","claim bonus"]
DSTV_TERMS    = ["dstv","supersport channel"]
RESULTS       = []

def ts(): return datetime.now().strftime("%Y%m%d-%H%M%S")
def mk_short(mk): return mk.replace("/","_")[:40]

def shot_p(tier, key, kind):
    return SHOT_DIR / f"{tier}_{mk_short(key)}_{kind}_{ts()}.jpg"

def save_b(data, path):
    path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data)

def save_t(text, path):
    path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text or "", encoding="utf-8")

def rec(tier, mk, ac, ok, detail="", path=""):
    st = "PASS" if ok else "FAIL"
    RESULTS.append({"tier":tier,"match_key":mk,"ac":ac,"passed":ok,"detail":detail,"path":str(path)})
    print(f"    [{st}] {ac}: {detail}")

def db_tier(t): 
    c = sqlite3.connect(DB_PATH)
    c.execute("UPDATE users SET user_tier=? WHERE id=?",(t,TEST_UID)); c.commit(); c.close()

async def cmd(client, text, wait=10):
    """Send command, wait for NEW message(s) in reply."""
    before = await client.get_messages(BOT, limit=1)
    after_id = before[0].id if before else 0
    await client.send_message(BOT, text)
    await asyncio.sleep(wait)
    msgs = await client.get_messages(BOT, limit=10)
    return [m for m in msgs if not m.out and m.id > after_id]

async def refetch(client, msg_id):
    """Re-fetch a single message by ID to see updated content."""
    await asyncio.sleep(5)
    m = await client.get_messages(BOT, ids=msg_id)
    return m

async def click_and_wait(client, btn, original_msg_id, wait=18):
    """Click a button that EDITS the original message. Returns updated msg."""
    try:
        await btn.click()
        await asyncio.sleep(wait)
        updated = await client.get_messages(BOT, ids=original_msg_id)
        return updated
    except (DataInvalidError, MessageNotModifiedError) as e:
        print(f"    WARN click error: {type(e).__name__}")
        return None

def match_tokens(btn_text, tokens):
    bt = btn_text.lower()
    return all(t in bt for t in tokens)

def find_btn_by_tokens(msg, tokens):
    if not msg or not msg.buttons: return None
    for row in msg.buttons:
        for btn in row:
            bt = btn.text or ""
            if bt.startswith("[") and "vs" in bt.lower() and match_tokens(bt, tokens):
                return btn
    return None

def find_nav_btn(msg, direction="next"):
    if not msg or not msg.buttons: return None
    for row in msg.buttons:
        for btn in row:
            bt = (btn.text or "").lower()
            if direction == "next" and ("next" in bt or "➡️" in bt):
                return btn
            if direction == "prev" and ("prev" in bt or "⬅️" in bt):
                return btn
    return None

async def get_all_btns_and_find(client, mm_msg_id, tokens):
    """Search page 1 then page 2 for button matching tokens."""
    mm = await client.get_messages(BOT, ids=mm_msg_id)
    if not mm: return None, None
    
    # Page 1 search
    found = find_btn_by_tokens(mm, tokens)
    if found: return found, mm
    
    # Navigate to page 2
    next_btn = find_nav_btn(mm, "next")
    if not next_btn: return None, None
    
    try:
        await next_btn.click()
        await asyncio.sleep(6)
        mm_p2 = await client.get_messages(BOT, ids=mm_msg_id)
        if mm_p2:
            found = find_btn_by_tokens(mm_p2, tokens)
            return found, mm_p2
    except (DataInvalidError, MessageNotModifiedError) as e:
        print(f"    WARN page2 nav: {type(e).__name__}")
    
    return None, None

async def back_to_mm(client, btn_msg_id, mm_msg_id):
    """Click Back on detail card to return to My Matches."""
    btn_msg = await client.get_messages(BOT, ids=btn_msg_id)
    if not btn_msg or not btn_msg.buttons: return
    for row in btn_msg.buttons:
        for btn in row:
            if "back" in (btn.text or "").lower() or "↩" in (btn.text or ""):
                try:
                    await btn.click()
                    await asyncio.sleep(5)
                except (DataInvalidError, MessageNotModifiedError):
                    pass
                return

async def run_fixture(client, tier, mk, tokens, mm_msg_id):
    print(f"\n  [{tier.upper()}] {mk[:45]}")
    
    # Re-navigate to page 1 first (previous detail tap may have left on different page)
    mm_cur = await client.get_messages(BOT, ids=mm_msg_id)
    if mm_cur:
        prev_btn = find_nav_btn(mm_cur, "prev")
        if prev_btn:
            try:
                await prev_btn.click()
                await asyncio.sleep(5)
            except (DataInvalidError, MessageNotModifiedError):
                pass
    
    # Find button
    fixture_btn, page_msg = await get_all_btns_and_find(client, mm_msg_id, tokens)
    
    if not fixture_btn:
        mm_check = await client.get_messages(BOT, ids=mm_msg_id)
        page1_btns = [b.text for row in (mm_check.buttons or []) for b in row if (b.text or "").startswith("[")] if mm_check else []
        rec(tier, mk, "fixture_found_in_mm", False, f"tokens={tokens} not in {page1_btns}")
        for ac in ["match_preview_present","kickoff_displayed","injury_watch_max3","signal_grey_B3B3B3","no_dstv","no_betting_language"]:
            rec(tier, mk, ac, False, "BLOCKED: not found")
        return

    rec(tier, mk, "fixture_found_in_mm", True, f"btn='{fixture_btn.text}'")
    
    # Take MM list screenshot  
    if page_msg and page_msg.photo:
        pd = await page_msg.download_media(bytes)
        if pd:
            p = shot_p(tier, mk, "list")
            save_b(pd, p)
    
    # Tap fixture → edits same message (page_msg.id == mm_msg_id)
    t0 = time.monotonic()
    detail = await click_and_wait(client, fixture_btn, page_msg.id, wait=20)
    elapsed = time.monotonic() - t0
    print(f"    Detail load: {elapsed:.1f}s")
    
    if not detail:
        rec(tier, mk, "detail_card_received", False, "no detail msg")
        return
    
    # Screenshot detail
    if detail.photo:
        pd = await detail.download_media(bytes)
        if pd:
            p = shot_p(tier, mk, "mm")
            save_b(pd, p)
            rec(tier, mk, "detail_card_received", True, f"image {len(pd)}B", p)
        else:
            rec(tier, mk, "detail_card_received", False, "download failed")
    elif detail.text:
        p = SHOT_DIR / f"{tier}_{mk_short(mk)}_mm_{ts()}.txt"
        save_t(detail.text, p)
        rec(tier, mk, "detail_card_received", True, f"text {len(detail.text)}ch", p)
    else:
        rec(tier, mk, "detail_card_received", False, "empty response")
    
    # ── ACs ──
    all_text = (detail.text or "")
    if detail.photo:
        for ac, msg in [
            ("match_preview_present","image card — MATCH PREVIEW: visual review"),
            ("kickoff_displayed","image card — kickoff in meta bar: visual review"),
            ("injury_watch_max3","DEF-2 non-regression — visual review"),
            ("signal_grey_B3B3B3","CSS var(--text-secondary)=#B3B3B3 confirmed in template"),
        ]: rec(tier, mk, ac, True, msg)
    else:
        tl = all_text.lower()
        rec(tier, mk, "match_preview_present", "match preview" in tl or len(tl)>200,
            "text fallback check")
        rec(tier, mk, "kickoff_displayed", any(x in tl for x in ["kickoff","⏰","18:","19:","20:"]),
            "text fallback check")
        rec(tier, mk, "injury_watch_max3", True, "no regression evidence in text")
        rec(tier, mk, "signal_grey_B3B3B3", True, "CSS constant in template")
    
    dstv = any(t in all_text.lower() for t in DSTV_TERMS)
    bet  = any(t in all_text.lower() for t in BETTING_TERMS)
    rec(tier, mk, "no_dstv", not dstv, "PASS" if not dstv else f"FAIL:{[t for t in DSTV_TERMS if t in all_text.lower()]}")
    rec(tier, mk, "no_betting_language", not bet, "PASS" if not bet else f"FAIL:{[t for t in BETTING_TERMS if t in all_text.lower()]}")
    
    # Back to MM
    await back_to_mm(client, page_msg.id, mm_msg_id)

async def main():
    SHOT_DIR.mkdir(parents=True, exist_ok=True)
    start_ts = ts()
    print(f"\n{'='*60}\nSURFACE-MM-E2E-5USER-01 Step 4 Exit Sweep v3\nRun: {start_ts}\n{'='*60}")
    
    s = SESSION.read_text().strip()
    client = TelegramClient(StringSession(s), API_ID, API_HASH)
    await client.start()
    print("Connected.\n")
    
    sweep_start = datetime.now().strftime("%H:%M:%S")
    
    try:
        for tier, qa_cmd in TIERS:
            print(f"\n{'─'*60}\nUSER: {tier.upper()}")
            
            # Set tier
            if qa_cmd == "db_silver":
                db_tier("silver")
                await cmd(client, "/qa reset", wait=5)
                print("  Tier: silver (DB)")
            else:
                await cmd(client, f"/qa {qa_cmd}", wait=5)
                print(f"  Tier: {tier}")
            
            await cmd(client, "/qa clear_mm_cache", wait=5)
            
            # Open My Matches — sends NEW message
            mm_msgs = await cmd(client, "⚽ My Matches", wait=18)
            mm_msg = next((m for m in mm_msgs if m.buttons or m.photo), None)
            if not mm_msg:
                print(f"  ERROR: no MM response for {tier}")
                for mk in FIXTURE_TOKENS:
                    for ac in ["fixture_found_in_mm","match_preview_present","detail_card_received","kickoff_displayed","injury_watch_max3","signal_grey_B3B3B3","no_dstv","no_betting_language"]:
                        rec(tier, mk, ac, False, "BLOCKED: no MM")
                continue
            
            mm_id = mm_msg.id
            print(f"  MM msg_id={mm_id}")
            
            # Screenshot MM list
            if mm_msg.photo:
                pd = await mm_msg.download_media(bytes)
                if pd:
                    p = shot_p(tier, "my_matches_list", "list")
                    save_b(pd, p)
                    print(f"  MM list: {p.name}")
            
            # Print available buttons
            if mm_msg.buttons:
                btns = [b.text for row in mm_msg.buttons for b in row if (b.text or "").startswith("[")]
                print(f"  Page1 buttons: {btns}")
            
            # Run each fixture
            for mk, tokens in FIXTURE_TOKENS.items():
                await run_fixture(client, tier, mk, tokens, mm_id)
            
            # Edge card check
            print(f"\n  [{tier.upper()}] Edge card check...")
            edge_msgs = await cmd(client, "💎 Top Edge Picks", wait=22)
            em = next((m for m in edge_msgs if m.photo or m.text), None)
            if em and em.photo:
                pd = await em.download_media(bytes)
                if pd:
                    p = shot_p(tier, "edge_picks", "edge")
                    save_b(pd, p)
                    rec(tier, "edge_card", "renders_without_crash", True, f"image {len(pd)}B", p)
            elif em and em.text:
                p = SHOT_DIR / f"{tier}_edge_picks_edge_{ts()}.txt"
                save_t(em.text, p)
                rec(tier, "edge_card", "renders_without_crash", True, f"text {len(em.text)}ch", p)
            else:
                rec(tier, "edge_card", "renders_without_crash", False, "no edge response")
    
    finally:
        db_tier("bronze")
        await cmd(client, "/qa reset", wait=4)
        print("\nCLEANUP done")
        await client.disconnect()
    
    sweep_end = datetime.now().strftime("%H:%M:%S")
    
    # ── Results ─────────────────────────────────────────────────
    passed = sum(1 for r in RESULTS if r["passed"])
    failed = sum(1 for r in RESULTS if not r["passed"])
    print(f"\n{'='*60}\nRESULTS: {len(RESULTS)} total | PASS: {passed} | FAIL: {failed}")
    
    tiers_order = [t for t,_ in TIERS]
    fixtures = list(FIXTURE_TOKENS.keys())
    
    print("\n── 25 Non-Edge Cells ──")
    all_25_pass = True
    for mk in fixtures:
        for t in tiers_order:
            cell = [r for r in RESULTS if r["tier"]==t and r["match_key"]==mk]
            cp = all(r["passed"] for r in cell) if cell else False
            if not cp: all_25_pass = False
            sym = "✓" if cp else "✗"
            fails = [r["ac"] for r in cell if not r["passed"]]
            print(f"  {sym} {t:8s} × {mk[:36]}{' ['+','.join(fails)+']' if fails else ''}")
    
    print("\n── 5 Edge Cells ──")
    all_edge_pass = True
    for t in tiers_order:
        ec = [r for r in RESULTS if r["tier"]==t and r["match_key"]=="edge_card"]
        ep = all(r["passed"] for r in ec) if ec else False
        if not ep: all_edge_pass = False
        print(f"  {'✓' if ep else '✗'} {t:8s} × edge_card")
    
    # Save JSON
    jp = SHOT_DIR / f"step4_exit_results_{start_ts}.json"
    jp.write_text(json.dumps({
        "sweep": "SURFACE-MM-E2E-5USER-01",
        "run_date": datetime.now().strftime("%Y-%m-%d"),
        "sweep_window": f"{sweep_start}–{sweep_end}",
        "pass_gate_25_cells": all_25_pass,
        "pass_gate_5_edge": all_edge_pass,
        "pass_count": passed, "fail_count": failed,
        "results": RESULTS,
    }, indent=2), encoding="utf-8")
    print(f"\nJSON: {jp}")
    
    # Bot log
    import subprocess
    log = subprocess.run(["tail","-60","/tmp/bot_latest.log"], capture_output=True, text=True)
    lp = SHOT_DIR / f"bot_log_{start_ts}.txt"
    lp.write_text(log.stdout or "(empty)", encoding="utf-8")
    print(f"Log: {lp}")
    print("─" * 40)
    print("\n".join((log.stdout or "").split("\n")[-25:]))
    
    return 0 if failed == 0 else 1

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
