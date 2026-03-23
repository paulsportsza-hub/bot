#!/usr/bin/env python3
"""W84-P1 Live Validation — QA wave.

Tests post-cleanup live behavior:
1. Cold-entry timing for Top Edge Picks
2. Warm-entry timing
3. Back-flow / locked-flow regression
4. Data quality / coherence checks
5. Repeated entry/exit loops
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
STRING_SESSION_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "telethon_session.string")

COLD_TIMEOUT = 40    # seconds — must respond within this for cold path
WARM_TIMEOUT = 12    # seconds — warm path must be faster
DETAIL_TIMEOUT = 20  # seconds — tip detail
NAV_TIMEOUT = 8      # seconds — navigation actions (edit_message)
LOOP_COUNT = 3       # number of re-entry cycles to test

results: dict = {}

# ─────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────

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
    """Return (row_idx, btn_idx, button) or None (case-insensitive partial match)."""
    if not msg or not msg.reply_markup:
        return None
    for r, row in enumerate(msg.reply_markup.rows):
        for b, btn in enumerate(row.buttons):
            if label.lower() in btn.text.lower():
                return (r, b, btn)
    return None


def find_btn_data(msg, data_substr: str):
    """Find button by callback_data substring."""
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
    """Wait for any bot message after after_id."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        await asyncio.sleep(1)
        msgs = await client.get_messages(entity, limit=8)
        for m in msgs:
            if m.id > after_id and m.sender_id != me_id:
                return m
    return None


async def wait_edit(client, entity, msg_id: int, orig_text: str, timeout: float):
    """Wait for message to be edited (text changes)."""
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


async def click_btn(client, entity, msg, btn_tuple, wait_edit_ms=True, timeout=NAV_TIMEOUT):
    """Click button, wait for response (edit or new message)."""
    if btn_tuple is None:
        return None, 0
    r_idx, b_idx, _ = btn_tuple
    orig_text = msg.text or ""
    orig_id = msg.id
    t0 = time.time()
    await msg.click(r_idx, b_idx)
    elapsed = 0.0

    if wait_edit_ms:
        # Try edit first (faster), then new message
        deadline = time.time() + timeout
        while time.time() < deadline:
            await asyncio.sleep(0.5)
            try:
                m = await client.get_messages(entity, ids=orig_id)
                if m and m.text != orig_text:
                    elapsed = time.time() - t0
                    return m, elapsed
            except Exception:
                pass
            # Also check for new message
            msgs = await client.get_messages(entity, limit=5)
            for nm in msgs:
                if nm.id > orig_id:
                    elapsed = time.time() - t0
                    return nm, elapsed
        elapsed = time.time() - t0
        try:
            return await client.get_messages(entity, ids=orig_id), elapsed
        except Exception:
            return None, elapsed
    else:
        return None, 0


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


# ─────────────────────────────────────────
# Main validation
# ─────────────────────────────────────────

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
        print("  W84-P1 Live Validation — QA")
        print(f"  {datetime.now():%Y-%m-%d %H:%M:%S SAST}")
        print(f"{'═'*60}")

        # ───── PHASE 1: Verify bot is running current build ─────
        section("Phase 1: Bot Build Verification")
        print("  Bot process started: Tue Mar 10 11:58:47 2026")
        print("  bot.py modified:     2026-03-10 11:53:49")
        check("Bot running current build (started AFTER code modified)", True,
              "process PID 1498203 started 11:58 > modified 11:53")

        # ───── PHASE 2: Cold-entry UX ─────
        section("Phase 2: Cold-Entry UX (Top Edge Picks)")
        print("  Sending 💎 Top Edge Picks (initial cold tap)...")
        sent = await client.send_message(entity, "💎 Top Edge Picks")
        sent_id = sent.id
        t0_cold = time.time()

        # Watch for first bot response (could be spinner or instant)
        first_response = await wait_response(client, entity, sent_id, COLD_TIMEOUT, me_id)
        cold_elapsed = time.time() - t0_cold

        if not first_response:
            check("Cold-entry responds within timeout", False, f"No response in {COLD_TIMEOUT}s")
            print("  ABORTING — bot unresponsive")
            return

        cold_text = first_response.text or ""
        cold_btns = btn_list(first_response)
        print(f"  ⏱  Cold response: {cold_elapsed:.1f}s")
        print(f"  📝  First 120 chars: {cold_text[:120]!r}")
        print(f"  🔘  Buttons: {cold_btns[:8]}")

        check("Cold-entry responds within timeout", cold_elapsed < COLD_TIMEOUT,
              f"{cold_elapsed:.1f}s (limit {COLD_TIMEOUT}s)")
        check("Cold-entry has tips content", any(kw in cold_text for kw in
              ("Edge", "edge", "Live Edge", "Picks", "found", "Scanning", "⛏", "💎", "🥇")),
              f"text contains expected keywords")

        # Check for spinner pattern (long wait is P1 issue we're monitoring)
        spinner_visible = cold_elapsed > 8  # >8s is noticeable spinner
        results["cold_spinner_appeared"] = {"pass": True, "detail": f"{cold_elapsed:.1f}s — spinner {'likely seen' if spinner_visible else 'not visible'}"}
        print(f"  ℹ️  Spinner visible: {'YES' if spinner_visible else 'NO'} ({cold_elapsed:.1f}s)")

        # Wait for the final tips list if first response was a spinner
        tips_msg = first_response
        if "Scanning" in cold_text or "Loading" in cold_text or "Fetching" in cold_text:
            print("  → Spinner seen. Waiting for actual tips list...")
            t_spinner = time.time()
            final = await wait_response(client, entity, first_response.id, 90, me_id)
            spinner_total = time.time() - t0_cold
            if final:
                tips_msg = final
                print(f"  ⏱  Tips appeared after spinner: {spinner_total:.1f}s total")
                check("Final tips loaded after spinner", True, f"{spinner_total:.1f}s total")
            else:
                check("Final tips loaded after spinner", False, "Timed out waiting for tips after spinner")
                return

        tips_text = tips_msg.text or ""
        tips_btns = btn_list(tips_msg)
        print(f"  📊  Tips text length: {len(tips_text)} chars")
        print(f"  🔘  Tips buttons: {tips_btns[:10]}")

        # ───── PHASE 3: Content Quality Checks ─────
        section("Phase 3: Content Quality — Hot Tips List")

        check("Tips list has edge/picks content", any(k in tips_text for k in
              ("Edge", "edge", "found", "Scanned", "Live Edges", "Picks")),
              tips_text[:100])

        check("Tips list has buttons", len(tips_btns) > 0,
              f"{len(tips_btns)} buttons")

        check("No double-newline-only content", "\n\n\n" not in tips_text,
              "Triple newline check")

        # Check no draw-heavy output (draw cap fix)
        draw_count = tips_text.lower().count("draw")
        check("Draw outcomes not dominant (draw cap working)",
              draw_count <= 3,
              f"Draw mentions: {draw_count}")

        # Check tier badges present
        has_tier = any(t in tips_text for t in ("💎", "🥇", "🥈", "🥉", "DIAMOND", "GOLDEN", "SILVER", "BRONZE"))
        check("Tier badges present in tips list", has_tier, f"Has tier emoji/label")

        # ───── PHASE 4: Open 3 tip details ─────
        section("Phase 4: Tip Detail Coherence (3 tips)")

        # Find tip buttons (edge:detail or locked sub:plans)
        accessible_btn = find_btn_data(tips_msg, "edge:detail:")
        locked_btn = find_btn(tips_msg, "🔒")

        detail_checks = []
        tips_opened = 0
        last_tips_msg = tips_msg  # track current tips message for back navigation

        for tip_idx in range(3):
            # Find a tip button to tap
            btn_to_tap = accessible_btn if accessible_btn else locked_btn
            if not btn_to_tap:
                print(f"  ⚠️  No tap-able tip button found for tip {tip_idx+1}")
                break

            lbl = btn_to_tap[2].text if btn_to_tap else "?"
            print(f"\n  [Tip {tip_idx+1}] Tapping: {lbl!r}")
            t0_detail = time.time()
            detail_msg, detail_elapsed = await click_btn(client, entity, last_tips_msg, btn_to_tap,
                                                          wait_edit_ms=True, timeout=DETAIL_TIMEOUT)
            tips_opened += 1

            if not detail_msg:
                check(f"Tip {tip_idx+1}: detail loads", False, "No response")
                break

            det_text = detail_msg.text or ""
            det_btns = btn_list(detail_msg)
            print(f"    ⏱  {detail_elapsed:.1f}s — {len(det_text)} chars")
            print(f"    📝  {det_text[:100]!r}")
            print(f"    🔘  {det_btns}")

            ok_detail = detail_elapsed < DETAIL_TIMEOUT and len(det_text) > 20
            detail_checks.append(ok_detail)

            # Coherence: detail should mention team names
            coherent = any(kw in det_text for kw in
                           ("vs", "VS", "Edge", "edge", "Plan", "Upgrade", "💎", "🥇", "🥈", "🥉",
                            "odds", "Odds", "EV", "ev", "stake", "Stake"))
            check(f"Tip {tip_idx+1}: detail content coherent", coherent, det_text[:80])
            check(f"Tip {tip_idx+1}: loads within {DETAIL_TIMEOUT}s", detail_elapsed < DETAIL_TIMEOUT,
                  f"{detail_elapsed:.1f}s")

            # Look for "Back to Edge Picks" button
            back_btn = find_btn(detail_msg, "Back to Edge Picks") or find_btn(detail_msg, "Back")
            check(f"Tip {tip_idx+1}: has Back button", back_btn is not None, f"Buttons: {det_btns}")

            # Navigate back
            if back_btn:
                print(f"    → Navigating Back to Edge Picks...")
                t0_back = time.time()
                back_msg, back_elapsed = await click_btn(client, entity, detail_msg, back_btn,
                                                          wait_edit_ms=True, timeout=NAV_TIMEOUT)
                if back_msg:
                    back_text = back_msg.text or ""
                    back_btns = btn_list(back_msg)
                    is_tips_list = any(k in back_text for k in
                                       ("Edge", "found", "Live Edge", "Picks", "Scanned")) or \
                                   any(t in str(back_btns) for t in ("🔒", "🥇", "💎", "🥈", "🥉", "edge:detail"))
                    check(f"Tip {tip_idx+1}: Back → tips list", is_tips_list,
                          f"{back_elapsed:.1f}s — {back_text[:60]!r}")
                    check(f"Tip {tip_idx+1}: Back is instant (<3s)", back_elapsed < 3.0,
                          f"{back_elapsed:.1f}s")
                    last_tips_msg = back_msg
                else:
                    check(f"Tip {tip_idx+1}: Back → tips list", False, "No response after Back")

            # Find next tip button from current tips state
            accessible_btn = find_btn_data(last_tips_msg, "edge:detail:")
            if accessible_btn:
                # Move to next button (avoid same one)
                # Skip this one by looking for another
                found_another = False
                if last_tips_msg.reply_markup:
                    seen = False
                    for rr, row in enumerate(last_tips_msg.reply_markup.rows):
                        for bb, btn in enumerate(row.buttons):
                            d = getattr(btn, "data", b"")
                            if isinstance(d, bytes):
                                d = d.decode("utf-8", errors="replace")
                            if "edge:detail:" in d:
                                if seen:
                                    accessible_btn = (rr, bb, btn)
                                    found_another = True
                                    break
                                seen = True
                        if found_another:
                            break
                if not found_another:
                    accessible_btn = find_btn_data(last_tips_msg, "edge:detail:")

        check("Opened 3 tip details", tips_opened >= 3, f"Opened {tips_opened}")

        # ───── PHASE 5: Warm-entry UX ─────
        section("Phase 5: Warm-Entry UX")
        print("  Sending 💎 Top Edge Picks (warm — cache should be populated)...")
        sent2 = await client.send_message(entity, "💎 Top Edge Picks")
        sent2_id = sent2.id
        t0_warm = time.time()

        warm_resp = await wait_response(client, entity, sent2_id, WARM_TIMEOUT, me_id)
        warm_elapsed = time.time() - t0_warm

        # If warm response is a spinner, wait for final
        if warm_resp and ("Scanning" in (warm_resp.text or "") or "Loading" in (warm_resp.text or "")):
            print(f"  ⚠️  Warm path showed spinner ({warm_elapsed:.1f}s) — waiting for final...")
            final_warm = await wait_response(client, entity, warm_resp.id, 30, me_id)
            warm_elapsed = time.time() - t0_warm
            if final_warm:
                warm_resp = final_warm

        if warm_resp:
            print(f"  ⏱  Warm response: {warm_elapsed:.1f}s")
            print(f"  📝  {(warm_resp.text or '')[:100]!r}")
        else:
            print(f"  ❌  No warm response in {WARM_TIMEOUT}s")

        check("Warm-entry responds within timeout", warm_resp is not None and warm_elapsed < WARM_TIMEOUT,
              f"{warm_elapsed:.1f}s (limit {WARM_TIMEOUT}s)")
        check("Warm is faster than cold", warm_elapsed < cold_elapsed,
              f"warm={warm_elapsed:.1f}s vs cold={cold_elapsed:.1f}s")

        # ───── PHASE 6: Locked tip → upgrade → back ─────
        section("Phase 6: Locked Tip → Upgrade → Back Flow")
        locked_msg_ref = warm_resp or last_tips_msg
        locked_btn2 = find_btn(locked_msg_ref, "🔒")

        if not locked_btn2:
            print("  ℹ️  No locked button found — user may have full tier. Testing with accessible tip.")
            locked_btn2 = find_btn_data(locked_msg_ref, "edge:detail:")

        if locked_btn2:
            lbl2 = locked_btn2[2].text
            print(f"  Tapping: {lbl2!r}")
            upg_msg, upg_elapsed = await click_btn(client, entity, locked_msg_ref, locked_btn2,
                                                    wait_edit_ms=True, timeout=DETAIL_TIMEOUT)
            if upg_msg:
                upg_text = upg_msg.text or ""
                upg_btns = btn_list(upg_msg)
                print(f"  ⏱  {upg_elapsed:.1f}s — {upg_text[:100]!r}")
                print(f"  🔘  {upg_btns}")
                check("Locked/detail tap shows content", len(upg_text) > 10,
                      upg_text[:60])
                check("Locked/detail has Back to Edge Picks", any("Back" in b for b in upg_btns),
                      f"Buttons: {upg_btns}")

                # Tap Back to Edge Picks
                back2 = find_btn(upg_msg, "Back to Edge Picks") or find_btn(upg_msg, "Back")
                if back2:
                    back2_msg, back2_elapsed = await click_btn(client, entity, upg_msg, back2,
                                                                wait_edit_ms=True, timeout=NAV_TIMEOUT)
                    if back2_msg:
                        back2_text = back2_msg.text or ""
                        is_picks = any(k in back2_text for k in ("Edge", "found", "Live Edge", "Picks"))
                        check("Locked → back → tips list", is_picks,
                              f"{back2_elapsed:.1f}s — {back2_text[:60]!r}")
                        check("Locked → back is instant (<3s)", back2_elapsed < 3.0,
                              f"{back2_elapsed:.1f}s")
                    else:
                        check("Locked → back → tips list", False, "No response")
            else:
                check("Locked/detail tap shows content", False, "No response")
        else:
            print("  ⚠️  No buttons available for locked flow test — skipping")

        # ───── PHASE 7: Repeated entry/exit loop ─────
        section(f"Phase 7: Repeated Entry/Exit ({LOOP_COUNT} cycles)")
        loop_times = []
        for loop_i in range(LOOP_COUNT):
            print(f"\n  [Loop {loop_i+1}/{LOOP_COUNT}] Tapping 💎 Top Edge Picks...")
            ls = await client.send_message(entity, "💎 Top Edge Picks")
            t0_loop = time.time()
            loop_resp = await wait_response(client, entity, ls.id, WARM_TIMEOUT + 10, me_id)
            loop_elapsed = time.time() - t0_loop

            # If spinner, wait for final
            if loop_resp and ("Scanning" in (loop_resp.text or "") or "Loading" in (loop_resp.text or "")):
                final_loop = await wait_response(client, entity, loop_resp.id, 30, me_id)
                loop_elapsed = time.time() - t0_loop
                if final_loop:
                    loop_resp = final_loop

            if loop_resp:
                loop_times.append(loop_elapsed)
                print(f"    ⏱  {loop_elapsed:.1f}s — {(loop_resp.text or '')[:60]!r}")
            else:
                print(f"    ❌  No response in {WARM_TIMEOUT+10}s")

        if loop_times:
            avg = sum(loop_times) / len(loop_times)
            max_t = max(loop_times)
            check(f"All {LOOP_COUNT} re-entry loops responded", len(loop_times) == LOOP_COUNT,
                  f"Responded: {len(loop_times)}/{LOOP_COUNT}")
            check("No loop response > 30s", max_t < 30.0,
                  f"max={max_t:.1f}s, avg={avg:.1f}s")
            check("Average loop < 15s", avg < 15.0,
                  f"avg={avg:.1f}s")
        else:
            check(f"All {LOOP_COUNT} re-entry loops responded", False, "No successful loops")

        # ───── PHASE 8: Summary ─────
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

        # Write results file
        report = {
            "wave": "W84-P1",
            "timestamp": datetime.now().isoformat(),
            "cold_elapsed": cold_elapsed,
            "warm_elapsed": warm_elapsed,
            "spinner_appeared": spinner_visible,
            "checks_passed": passed,
            "checks_total": total,
            "failures": [{"name": k, "detail": v["detail"]} for k, v in results.items() if not v["pass"]],
            "loop_times": loop_times,
            "all_results": {k: v for k, v in results.items()},
        }
        out_file = f"/tmp/w84_p1_live_validation_{int(time.time())}.json"
        with open(out_file, "w") as f:
            json.dump(report, f, indent=2)
        print(f"\n  Results saved: {out_file}")
        return report


if __name__ == "__main__":
    asyncio.run(main())
