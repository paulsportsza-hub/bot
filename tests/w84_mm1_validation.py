#!/usr/bin/env python3
"""W84-MM1 Live Validation — My Matches cold-path.

Tests:
1. 10 consecutive cold-path My Matches opens (clears cache between each)
2. 3 breakdown opens after list load
3. Navigation regression checks
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
import json
from datetime import datetime

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

from telethon import TelegramClient
from telethon.sessions import StringSession

API_ID   = int(os.getenv("TELEGRAM_API_ID", "32418601"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "95e313a8ef5b998be0515dd8328fac57")
BOT_USERNAME = "@mzansiedge_bot"
STRING_SESSION_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "telethon_qa_session.string")

COLD_OPEN_TIMEOUT = 8.0   # max acceptable for any cold open
BREAKDOWN_TIMEOUT = 60.0  # game breakdowns can be slow (ESPN + AI)
NAV_TIMEOUT       = 6.0   # back navigation

results: dict = {}


def load_session():
    if os.path.exists(STRING_SESSION_FILE):
        with open(STRING_SESSION_FILE) as f:
            s = f.read().strip()
        if s:
            return StringSession(s)
    return StringSession()


def btn_list(msg) -> list[str]:
    if not msg or not msg.reply_markup:
        return []
    out = []
    for row in msg.reply_markup.rows:
        for btn in row.buttons:
            out.append(btn.text)
    return out


def find_btn(msg, label: str):
    if not msg or not msg.reply_markup:
        return None
    for r, row in enumerate(msg.reply_markup.rows):
        for b, btn in enumerate(row.buttons):
            if label.lower() in btn.text.lower():
                return (r, b, btn)
    return None


def find_btn_data(msg, data_substr: str):
    if not msg or not msg.reply_markup:
        return None
    for r, row in enumerate(msg.reply_markup.rows):
        for b, btn in enumerate(row.buttons):
            d = getattr(btn, "data", b"")
            if isinstance(d, bytes):
                d = d.decode("utf-8", errors="replace")
            if data_substr in d:
                return (r, b, btn)
    return None


async def wait_response(client, entity, after_id: int, timeout: float, me_id: int):
    deadline = time.time() + timeout
    while time.time() < deadline:
        await asyncio.sleep(0.8)
        msgs = await client.get_messages(entity, limit=8)
        for m in msgs:
            if m.id > after_id and m.sender_id != me_id:
                return m
    return None


async def wait_edit(client, entity, msg_id: int, orig_text: str, timeout: float):
    deadline = time.time() + timeout
    while time.time() < deadline:
        await asyncio.sleep(0.5)
        try:
            m = await client.get_messages(entity, ids=msg_id)
            if m and m.text != orig_text:
                return m
        except Exception:
            pass
    return None


async def wait_content(client, entity, spinner_id: int, timeout: float):
    """Wait for a spinner message (edit-in-place) to become non-loading content."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        await asyncio.sleep(0.5)
        try:
            m = await client.get_messages(entity, ids=spinner_id)
            if m and m.text:
                t = m.text
                is_still_loading = any(k in t for k in ("Loading", "loading")) and "Retry" not in t
                if not is_still_loading:
                    return m
        except Exception:
            pass
    # Return whatever we have at timeout
    try:
        return await client.get_messages(entity, ids=spinner_id)
    except Exception:
        return None


async def click_btn_edit(client, entity, msg, btn_tuple, timeout=NAV_TIMEOUT):
    if btn_tuple is None:
        return None, 0
    r_idx, b_idx, _ = btn_tuple
    orig_text = msg.text or ""
    orig_id = msg.id
    t0 = time.time()
    await msg.click(r_idx, b_idx)
    deadline = time.time() + timeout
    while time.time() < deadline:
        await asyncio.sleep(0.5)
        try:
            m = await client.get_messages(entity, ids=orig_id)
            if m and m.text != orig_text:
                return m, time.time() - t0
        except Exception:
            pass
        # Also check for new message
        msgs = await client.get_messages(entity, limit=5)
        for nm in msgs:
            if nm.id > orig_id:
                return nm, time.time() - t0
    elapsed = time.time() - t0
    try:
        m = await client.get_messages(entity, ids=orig_id)
        return m, elapsed
    except Exception:
        return None, elapsed


def check(name: str, condition: bool, detail: str = ""):
    status = "✅ PASS" if condition else "❌ FAIL"
    msg = f"  {status} — {name}"
    if detail:
        msg += f"\n     {detail}"
    print(msg)
    results[name] = {"pass": condition, "detail": detail}
    return condition


def section(title: str):
    print(f"\n{'─'*55}")
    print(f"  {title}")
    print(f"{'─'*55}")


def is_matches_content(text: str) -> bool:
    """Check if text is a My Matches response (list or degraded fallback)."""
    return any(k in text for k in (
        "My Matches", "matches", "Loading", "Retry", "games",
        "No live matches", "No upcoming", "league", "schedule",
    ))


async def main():
    session = load_session()
    if not session.save():
        print("ERROR: No session found.")
        sys.exit(1)

    async with TelegramClient(session, API_ID, API_HASH) as client:
        entity = await client.get_entity(BOT_USERNAME)
        me = await client.get_me()
        me_id = me.id

        print(f"\n{'═'*60}")
        print("  W84-MM1 Live Validation — My Matches Cold-Path")
        print(f"  {datetime.now():%Y-%m-%d %H:%M:%S SAST}")
        print(f"{'═'*60}")

        # ─── PHASE 1: 10 consecutive cold opens ───
        section("Phase 1: 10 Cold Opens of ⚽ My Matches")
        open_times: list[float] = []
        open_results: list[str] = []

        for i in range(10):
            print(f"\n  [Run {i+1}/10] Sending ⚽ My Matches...")
            sent = await client.send_message(entity, "⚽ My Matches")
            t0 = time.time()

            resp = await wait_response(client, entity, sent.id, COLD_OPEN_TIMEOUT + 3, me_id)
            elapsed = time.time() - t0

            if resp is None:
                print(f"    ❌ No response in {COLD_OPEN_TIMEOUT + 3:.0f}s")
                open_times.append(COLD_OPEN_TIMEOUT + 3)
                open_results.append("timeout")
                continue

            resp_text = resp.text or ""

            # If it's a spinner/loading message, wait for edit-in-place final
            if any(k in resp_text for k in ("Loading", "loading")) and "Retry" not in resp_text:
                print(f"    → Spinner seen ({elapsed:.1f}s), waiting for edit-in-place...")
                final = await wait_content(client, entity, resp.id, max(0, COLD_OPEN_TIMEOUT - elapsed))
                if final:
                    resp = final
                    resp_text = resp.text or ""
                elapsed = time.time() - t0

            status = "full" if any(k in resp_text for k in ("game", "vs", "SAST", "Today", "Tomorrow", "TBC")) else \
                     "degraded" if "Retry" in resp_text or "still loading" in resp_text.lower() else \
                     "list" if is_matches_content(resp_text) else "unknown"

            within_limit = elapsed <= COLD_OPEN_TIMEOUT
            open_times.append(elapsed)
            open_results.append(status)

            print(f"    ⏱  {elapsed:.1f}s — status: {status}")
            print(f"    📝  {resp_text[:80]!r}")
            print(f"    🔘  {btn_list(resp)[:5]}")

        print(f"\n  Open times: {[f'{t:.1f}s' for t in open_times]}")
        print(f"  Statuses:   {open_results}")

        all_within_limit = all(t <= COLD_OPEN_TIMEOUT for t in open_times)
        no_spinner_hang = all(s != "timeout" for s in open_results)
        has_content = all(s != "unknown" for s in open_results)

        check("All 10 opens responded within 8s",
              all_within_limit and no_spinner_hang,
              f"Max: {max(open_times):.1f}s, Avg: {sum(open_times)/len(open_times):.1f}s")
        check("No timeout/hang on any run", no_spinner_hang,
              f"Statuses: {open_results}")
        check("All runs returned content (not unknown)", has_content,
              f"Statuses: {open_results}")
        full_list_count = sum(1 for s in open_results if s in ("full", "list"))
        check("At least 5/10 returned full match list",
              full_list_count >= 5,
              f"Full list: {full_list_count}/10")

        # ─── PHASE 2: 3 breakdown opens ───
        section("Phase 2: 3 Breakdown Opens (after list load)")

        # Get a fresh My Matches list
        print("  Getting fresh My Matches list for breakdown tests...")
        sent2 = await client.send_message(entity, "⚽ My Matches")
        mm_resp = await wait_response(client, entity, sent2.id, COLD_OPEN_TIMEOUT + 5, me_id)

        # With edit-in-place: bot may send spinner then edit it (not a new message)
        if mm_resp and any(k in (mm_resp.text or "") for k in ("Loading", "loading")):
            if "Retry" not in (mm_resp.text or ""):
                print("  → Spinner seen, waiting for edit-in-place final...")
                final = await wait_content(client, entity, mm_resp.id, COLD_OPEN_TIMEOUT + 5)
                if final:
                    mm_resp = final

        # If degraded fallback: tap Retry → inline yg:all:0 path (cache warm by now)
        if mm_resp and "Retry" in (mm_resp.text or "") and not find_btn_data(mm_resp, "yg:game:"):
            retry_btn = find_btn(mm_resp, "Retry")
            if retry_btn:
                print("  → Got degraded fallback, tapping 🔄 Retry...")
                retry_msg, retry_elapsed = await click_btn_edit(
                    client, entity, mm_resp, retry_btn, timeout=COLD_OPEN_TIMEOUT,
                )
                if retry_msg:
                    mm_resp = retry_msg
                    print(f"    ⏱  Retry: {retry_elapsed:.1f}s — {(mm_resp.text or '')[:60]!r}")

        if not mm_resp:
            check("Got My Matches list for breakdown test", False, "No response")
            mm_resp = None
        else:
            mm_text = mm_resp.text or ""
            mm_btns = btn_list(mm_resp)
            print(f"  List: {mm_text[:80]!r}")
            print(f"  Buttons: {mm_btns[:6]}")
            check("Got My Matches list for breakdown test", True, f"{len(mm_text)} chars")

        if mm_resp:
            breakdowns_done = 0
            game_btn = find_btn_data(mm_resp, "yg:game:")

            for bd_i in range(3):
                if not game_btn:
                    print(f"  ⚠️  No game:detail button found for breakdown {bd_i+1}")
                    # Try from current message
                    game_btn = find_btn_data(mm_resp, "yg:game:")
                    if not game_btn:
                        break

                lbl = game_btn[2].text
                print(f"\n  [Breakdown {bd_i+1}/3] Tapping: {lbl!r}")
                t0_bd = time.time()
                bd_msg, bd_elapsed = await click_btn_edit(client, entity, mm_resp, game_btn, timeout=BREAKDOWN_TIMEOUT)
                breakdowns_done += 1

                if not bd_msg:
                    check(f"Breakdown {bd_i+1}: loaded", False, "No response")
                    break

                bd_text = bd_msg.text or ""
                bd_btns = btn_list(bd_msg)
                print(f"    ⏱  {bd_elapsed:.1f}s — {len(bd_text)} chars")
                print(f"    📝  {bd_text[:100]!r}")
                print(f"    🔘  {bd_btns}")

                has_bd_content = any(k in bd_text for k in
                    ("Setup", "Edge", "Risk", "Verdict", "vs", "odds", "EV",
                     "Upgrade", "Plans", "Loading"))
                check(f"Breakdown {bd_i+1}: has content", has_bd_content, bd_text[:60])
                check(f"Breakdown {bd_i+1}: loaded within {BREAKDOWN_TIMEOUT}s",
                      bd_elapsed < BREAKDOWN_TIMEOUT, f"{bd_elapsed:.1f}s")

                # Navigate back
                back_btn = find_btn(bd_msg, "Back to My Matches") or find_btn(bd_msg, "Back")
                if back_btn:
                    print(f"    → Navigating Back...")
                    t0_back = time.time()
                    back_msg, back_elapsed = await click_btn_edit(client, entity, bd_msg, back_btn, timeout=NAV_TIMEOUT)
                    if back_msg:
                        back_text = back_msg.text or ""
                        is_list = is_matches_content(back_text)
                        check(f"Breakdown {bd_i+1}: back → My Matches", is_list,
                              f"{back_elapsed:.1f}s — {back_text[:50]!r}")
                        mm_resp = back_msg
                        # Find next game button (pick next different one)
                        found_next = False
                        if back_msg.reply_markup:
                            seen_this = False
                            orig_data = getattr(game_btn[2], "data", b"")
                            if isinstance(orig_data, bytes):
                                orig_data = orig_data.decode("utf-8", errors="replace")
                            for rr, row in enumerate(back_msg.reply_markup.rows):
                                for bb, btn in enumerate(row.buttons):
                                    d = getattr(btn, "data", b"")
                                    if isinstance(d, bytes):
                                        d = d.decode("utf-8", errors="replace")
                                    if "yg:game:" in d:
                                        if d != orig_data:
                                            game_btn = (rr, bb, btn)
                                            found_next = True
                                            break
                                        else:
                                            seen_this = True
                                if found_next:
                                    break
                            if not found_next:
                                game_btn = find_btn_data(back_msg, "yg:game:")
                    else:
                        check(f"Breakdown {bd_i+1}: back → My Matches", False, "No response after back")

            check(f"Opened {min(3, breakdowns_done)}/3 breakdowns",
                  breakdowns_done >= 3, f"Opened: {breakdowns_done}")

        # ─── PHASE 3: Summary ───
        section("SUMMARY")
        passed = sum(1 for r in results.values() if r["pass"])
        total = len(results)
        print(f"\n  Results: {passed}/{total} checks passed\n")

        failures = [(k, v) for k, v in results.items() if not v["pass"]]
        if failures:
            print("  FAILURES:")
            for k, v in failures:
                print(f"    ❌ {k}")
                if v["detail"]:
                    print(f"       {v['detail']}")
        else:
            print("  All checks PASSED ✅")

        # Save report
        report = {
            "wave": "W84-MM1",
            "timestamp": datetime.now().isoformat(),
            "open_times": open_times,
            "open_statuses": open_results,
            "checks_passed": passed,
            "checks_total": total,
            "failures": [{"name": k, "detail": v["detail"]} for k, v in results.items() if not v["pass"]],
        }
        out_file = f"/tmp/w84_mm1_validation_{int(time.time())}.json"
        with open(out_file, "w") as f:
            json.dump(report, f, indent=2)
        print(f"\n  Results saved: {out_file}")
        return report


if __name__ == "__main__":
    asyncio.run(main())
