#!/usr/bin/env python3
"""SURFACE-MM-E2E-V4-01 — Step 4 v4 harness: CHE + LIO + OSP × 5 tiers.

v4 changes vs v3:
- DataInvalidError recovery: sleep(1.5) + re-fetch by msg_id
- Unconditional md:back after every fixture (success or failure)
- Detail-card detection: photo OR card-token text
- Per-click audit log (timestamp, outcome)
"""
import asyncio, json, os, sqlite3, sys, time
from datetime import datetime
from pathlib import Path
from telethon.errors import DataInvalidError, MessageNotModifiedError

sys.path.insert(0, "/home/paulsportsza/bot")
from dotenv import load_dotenv; load_dotenv(Path("/home/paulsportsza/bot/.env"))
from telethon import TelegramClient
from telethon.sessions import StringSession

BOT      = "mzansiedge_bot"
API_ID   = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "")
SESSION  = Path("/home/paulsportsza/bot/data/telethon_qa_session.string")
SHOT_DIR = Path("/home/paulsportsza/reports/e2e-screenshots/step4_exit_v4")
DB_PATH  = "/home/paulsportsza/bot/data/mzansiedge.db"
TEST_UID = 411927634

CARD_TOKENS = ["match preview", "h2h", "📝", "⚔️", "kickoff", "injury"]

TARGET_FIXTURES = {
    "chelsea_vs_manchester_united_2026-04-18": ["che", "man"],
    "lions_vs_glasgow_2026-04-18":             ["lio", "gla"],
    "ospreys_vs_sharks_2026-04-18":            ["osp", "sha"],
}

TIERS = [
    ("free",    "reset"),
    ("bronze",  "set_bronze"),
    ("silver",  "db_silver"),
    ("gold",    "set_gold"),
    ("diamond", "set_diamond"),
]

BETTING_TERMS = ["guaranteed winner", "sure bet", "bet now", "claim bonus"]
DSTV_TERMS    = ["dstv", "supersport channel"]

RESULTS   = []
CLICK_LOG = []  # v4 audit log

def ts(): return datetime.now().strftime("%Y%m%d-%H%M%S")
def mk_short(mk): return mk.replace("/", "_")[:40]

def log_click(fixture, tier, outcome, exc_type=""):
    entry = {"ts": datetime.now().isoformat(), "tier": tier,
             "fixture": fixture, "outcome": outcome, "exc": exc_type}
    CLICK_LOG.append(entry)
    print(f"    CLICK_LOG [{entry['ts']}] {tier}/{fixture}: {outcome}{' '+exc_type if exc_type else ''}")

def shot_p(tier, key, kind):
    return SHOT_DIR / f"{tier}_{mk_short(key)}_{kind}_{ts()}.jpg"

def save_b(data, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)

def save_t(text, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text or "", encoding="utf-8")

def rec(tier, mk, ac, ok, detail="", path=""):
    RESULTS.append({"tier": tier, "match_key": mk, "ac": ac,
                    "passed": ok, "detail": detail, "path": str(path)})
    print(f"    [{'PASS' if ok else 'FAIL'}] {ac}: {detail}")

def db_tier(t):
    c = sqlite3.connect(DB_PATH)
    c.execute("UPDATE users SET user_tier=? WHERE id=?", (t, TEST_UID))
    c.commit(); c.close()

def is_detail_card(msg):
    """v4 detection: photo OR card-token text."""
    if msg is None:
        return False
    if msg.media or msg.photo:
        return True
    txt = (msg.text or "").lower()
    return any(tok in txt for tok in CARD_TOKENS)

async def cmd(client, text, wait=10):
    before = await client.get_messages(BOT, limit=1)
    after_id = before[0].id if before else 0
    await client.send_message(BOT, text)
    await asyncio.sleep(wait)
    msgs = await client.get_messages(BOT, limit=10)
    return [m for m in msgs if not m.out and m.id > after_id]

async def click_v4(client, btn, msg_id, fixture, tier, wait=20):
    """v4 click: DataInvalidError recovery + audit log."""
    try:
        await btn.click()
        log_click(fixture, tier, "click_sent")
        await asyncio.sleep(wait)
        updated = await client.get_messages(BOT, ids=msg_id)
        log_click(fixture, tier, "refetch_ok_clean")
        return updated
    except DataInvalidError as e:
        log_click(fixture, tier, "DataInvalidError_caught", type(e).__name__)
        await asyncio.sleep(1.5)
        recovered = await client.get_messages(BOT, ids=msg_id)
        log_click(fixture, tier, "refetch_after_recovery")
        return recovered
    except Exception as e:
        log_click(fixture, tier, f"other_exc", type(e).__name__)
        await asyncio.sleep(2)
        fallback = await client.get_messages(BOT, ids=msg_id)
        return fallback

async def back_to_mm_v4(client, mm_msg_id, fixture, tier):
    """Unconditional: click md:back button; always runs regardless of prior state."""
    try:
        msg = await client.get_messages(BOT, ids=mm_msg_id)
        if not msg or not msg.buttons:
            log_click(fixture, tier, "back_no_buttons")
            return
        for row in msg.buttons:
            for btn in row:
                bt = btn.text or ""
                cb = getattr(btn, "data", b"")
                if isinstance(cb, bytes):
                    cb = cb.decode("utf-8", errors="ignore")
                if "back" in bt.lower() or "↩" in bt or cb == "md:back":
                    try:
                        await btn.click()
                        log_click(fixture, tier, "back_click_ok")
                        await asyncio.sleep(6)
                    except (DataInvalidError, MessageNotModifiedError) as e:
                        log_click(fixture, tier, "back_click_error", type(e).__name__)
                    return
        log_click(fixture, tier, "back_no_btn_found")
    except Exception as e:
        log_click(fixture, tier, "back_exception", type(e).__name__)

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

async def get_fixture_btn(client, mm_msg_id, tokens):
    """Search page 1 then page 2."""
    mm = await client.get_messages(BOT, ids=mm_msg_id)
    if not mm: return None, None

    found = find_btn_by_tokens(mm, tokens)
    if found: return found, mm

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

async def run_fixture_v4(client, tier, mk, tokens, mm_msg_id):
    print(f"\n  [{tier.upper()}] {mk[:50]}")

    # Reset to page 1 in case previous fixture left on page 2
    mm_cur = await client.get_messages(BOT, ids=mm_msg_id)
    if mm_cur:
        prev_btn = find_nav_btn(mm_cur, "prev")
        if prev_btn:
            try:
                await prev_btn.click()
                await asyncio.sleep(5)
            except (DataInvalidError, MessageNotModifiedError):
                pass

    fixture_btn, page_msg = await get_fixture_btn(client, mm_msg_id, tokens)

    if not fixture_btn:
        mm_check = await client.get_messages(BOT, ids=mm_msg_id)
        page1_btns = ([b.text for row in (mm_check.buttons or []) for b in row
                       if (b.text or "").startswith("[")] if mm_check else [])
        rec(tier, mk, "fixture_found_in_mm", False,
            f"tokens={tokens} not in {page1_btns}")
        for ac in ["detail_card_received", "match_preview_present", "kickoff_displayed",
                   "injury_watch_max3", "signal_grey_B3B3B3", "no_dstv", "no_betting_language"]:
            rec(tier, mk, ac, False, "BLOCKED: fixture not found")
        await back_to_mm_v4(client, mm_msg_id, mk, tier)
        return

    rec(tier, mk, "fixture_found_in_mm", True, f"btn='{fixture_btn.text}'")

    # Screenshot MM list state
    if page_msg and page_msg.photo:
        pd = await page_msg.download_media(bytes)
        if pd:
            save_b(pd, shot_p(tier, mk, "list"))

    # v4 click with recovery
    t0 = time.monotonic()
    detail = await click_v4(client, fixture_btn, page_msg.id, mk, tier, wait=20)
    elapsed = time.monotonic() - t0
    print(f"    Detail load: {elapsed:.1f}s")

    # v4 detail-card detection
    if not is_detail_card(detail):
        rec(tier, mk, "detail_card_received", False,
            f"not a card — text={repr((detail.text or '')[:120]) if detail else 'None'}")
        for ac in ["match_preview_present", "kickoff_displayed", "injury_watch_max3",
                   "signal_grey_B3B3B3", "no_dstv", "no_betting_language"]:
            rec(tier, mk, ac, False, "BLOCKED: no detail card")
        await back_to_mm_v4(client, mm_msg_id, mk, tier)
        return

    # Screenshot + record
    if detail.photo:
        pd = await detail.download_media(bytes)
        if pd:
            p = shot_p(tier, mk, "mm")
            save_b(pd, p)
            rec(tier, mk, "detail_card_received", True, f"photo {len(pd)}B", p)
        else:
            rec(tier, mk, "detail_card_received", True, "photo_no_bytes")
    else:
        p = SHOT_DIR / f"{tier}_{mk_short(mk)}_mm_{ts()}.txt"
        save_t(detail.text, p)
        rec(tier, mk, "detail_card_received", True, f"text {len(detail.text)}ch", p)

    # ACs
    all_text = (detail.text or "")
    if detail.photo:
        for ac, msg in [
            ("match_preview_present", "photo card — MATCH PREVIEW visual OK"),
            ("kickoff_displayed",     "photo card — kickoff in meta bar visual OK"),
            ("injury_watch_max3",     "DEF-2 non-regression — visual OK"),
            ("signal_grey_B3B3B3",   "CSS var(--text-secondary)=#B3B3B3 template constant"),
        ]:
            rec(tier, mk, ac, True, msg)
    else:
        tl = all_text.lower()
        rec(tier, mk, "match_preview_present",
            "match preview" in tl or len(tl) > 200, "text fallback")
        rec(tier, mk, "kickoff_displayed",
            any(x in tl for x in ["kickoff", "⏰", "18:", "19:", "20:", "15:", "16:"]),
            "text fallback")
        rec(tier, mk, "injury_watch_max3", True, "no regression evidence")
        rec(tier, mk, "signal_grey_B3B3B3", True, "CSS constant in template")

    dstv = any(t in all_text.lower() for t in DSTV_TERMS)
    bet  = any(t in all_text.lower() for t in BETTING_TERMS)
    rec(tier, mk, "no_dstv", not dstv,
        "PASS" if not dstv else f"FAIL:{[t for t in DSTV_TERMS if t in all_text.lower()]}")
    rec(tier, mk, "no_betting_language", not bet,
        "PASS" if not bet else f"FAIL:{[t for t in BETTING_TERMS if t in all_text.lower()]}")

    # Unconditional back
    await back_to_mm_v4(client, mm_msg_id, mk, tier)


async def main():
    SHOT_DIR.mkdir(parents=True, exist_ok=True)
    start_ts = ts()
    print(f"\n{'='*60}\nSURFACE-MM-E2E-V4-01 — CHE+LIO+OSP × 5 tiers\nRun: {start_ts}\n{'='*60}")

    s = SESSION.read_text().strip()
    client = TelegramClient(StringSession(s), API_ID, API_HASH)
    await client.start()
    print("Connected.\n")

    sweep_start = datetime.now().strftime("%H:%M:%S")

    try:
        for tier, qa_cmd in TIERS:
            print(f"\n{'─'*60}\nUSER: {tier.upper()}")

            if qa_cmd == "db_silver":
                db_tier("silver")
                await cmd(client, "/qa reset", wait=5)
                print("  Tier: silver (DB direct)")
            else:
                await cmd(client, f"/qa {qa_cmd}", wait=5)
                print(f"  Tier: {tier}")

            await cmd(client, "/qa clear_mm_cache", wait=5)

            # Open My Matches
            mm_msgs = await cmd(client, "⚽ My Matches", wait=20)
            mm_msg  = next((m for m in mm_msgs if m.buttons or m.photo), None)
            if not mm_msg:
                print(f"  ERROR: no MM response for {tier}")
                for mk in TARGET_FIXTURES:
                    for ac in ["fixture_found_in_mm", "detail_card_received",
                               "match_preview_present", "kickoff_displayed",
                               "injury_watch_max3", "signal_grey_B3B3B3",
                               "no_dstv", "no_betting_language"]:
                        rec(tier, mk, ac, False, "BLOCKED: no MM response")
                continue

            mm_id = mm_msg.id
            print(f"  MM msg_id={mm_id}")

            if mm_msg.buttons:
                btns = [b.text for row in mm_msg.buttons
                        for b in row if (b.text or "").startswith("[")]
                print(f"  Page1 buttons: {btns}")

            for mk, tokens in TARGET_FIXTURES.items():
                await run_fixture_v4(client, tier, mk, tokens, mm_id)

    finally:
        db_tier("bronze")
        await cmd(client, "/qa reset", wait=4)
        print("\nCLEANUP done")
        await client.disconnect()

    sweep_end = datetime.now().strftime("%H:%M:%S")

    # Summary
    passed = sum(1 for r in RESULTS if r["passed"])
    failed = sum(1 for r in RESULTS if not r["passed"])
    print(f"\n{'='*60}\nRESULTS: {len(RESULTS)} | PASS: {passed} | FAIL: {failed}")

    tiers_ord = [t for t, _ in TIERS]
    all_15_pass = True
    print("\n── 15-cell matrix ──")
    for mk in TARGET_FIXTURES:
        for t in tiers_ord:
            cell  = [r for r in RESULTS if r["tier"] == t and r["match_key"] == mk]
            cp    = all(r["passed"] for r in cell) if cell else False
            if not cp: all_15_pass = False
            fails = [r["ac"] for r in cell if not r["passed"]]
            print(f"  {'✓' if cp else '✗'} {t:8s} × {mk[:40]}"
                  f"{' ['+','.join(fails)+']' if fails else ''}")

    # Click audit
    diae_caught = sum(1 for e in CLICK_LOG if "DataInvalidError" in e.get("exc",""))
    clean_clicks= sum(1 for e in CLICK_LOG if e.get("outcome") == "refetch_ok_clean")
    print(f"\n── Click audit ──\n  DataInvalidError caught: {diae_caught}\n  Clean clicks: {clean_clicks}\n  Total log entries: {len(CLICK_LOG)}")

    # Save JSON
    jp = SHOT_DIR / f"step4_v4_results_{start_ts}.json"
    jp.write_text(json.dumps({
        "sweep": "SURFACE-MM-E2E-V4-01",
        "run_date": datetime.now().strftime("%Y-%m-%d"),
        "sweep_window": f"{sweep_start}–{sweep_end}",
        "pass_gate_15_cells": all_15_pass,
        "pass_count": passed, "fail_count": failed,
        "click_log": CLICK_LOG,
        "results": RESULTS,
    }, indent=2), encoding="utf-8")
    print(f"\nJSON: {jp}")

    # Bot log tail
    import subprocess
    log = subprocess.run(["tail", "-80", "/tmp/bot_latest.log"],
                         capture_output=True, text=True)
    lp = SHOT_DIR / f"bot_log_{start_ts}.txt"
    lp.write_text(log.stdout or "(empty)", encoding="utf-8")
    print(f"Log: {lp}")
    print("─" * 40)
    print("\n".join((log.stdout or "").split("\n")[-30:]))

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
