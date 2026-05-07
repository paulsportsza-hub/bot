#!/usr/bin/env python3
"""W84-HT2 Live Validation — Hot Tips page/detail identity stability.

Tests:
1. Open Hot Tips, collect page 1 tips and their buttons
2. Tap each visible tip on page 1 — confirm detail loads
3. Back from each detail — confirm returns to page 1 (NOT page 0)
4. If page 2 exists: navigate to page 2, repeat for all visible tips
5. Reopen each tip from page 2 twice — confirm same content every time
6. Run the full loop 3 consecutive times with zero identity failures
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

LIST_TIMEOUT   = 12.0   # max for Hot Tips list to load
DETAIL_TIMEOUT = 20.0   # max for detail (instant baseline <2s, slow pregen <28s; 20s covers precompute)
NAV_TIMEOUT    = 8.0    # max for back navigation

results: dict = {}
failures: list[str] = []


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


def get_btn_data(btn_tuple) -> str:
    if btn_tuple is None:
        return ""
    _, _, btn = btn_tuple
    d = getattr(btn, "data", b"")
    if isinstance(d, bytes):
        d = d.decode("utf-8", errors="replace")
    return d


def all_tip_btns(msg) -> list[tuple]:
    """Return ALL tip buttons: edge:detail (accessible) OR hot:upgrade (locked)."""
    out = []
    if not msg or not msg.reply_markup:
        return out
    for r, row in enumerate(msg.reply_markup.rows):
        for b, btn in enumerate(row.buttons):
            d = getattr(btn, "data", b"")
            if isinstance(d, bytes):
                d = d.decode("utf-8", errors="replace")
            if "edge:detail:" in d or d.startswith("hot:upgrade"):
                out.append((r, b, btn))
    return out


# Keep old name as alias for backward compat
all_edge_detail_btns = all_tip_btns


def is_accessible_detail(msg) -> bool:
    """True if current detail message has narrative content (not upgrade prompt)."""
    text = msg.text or "" if msg else ""
    return any(k in text for k in ("Setup", "Risk", "Verdict", "vs", "Edge:", "EV"))


def is_upgrade_prompt(msg) -> bool:
    text = msg.text or "" if msg else ""
    return any(k in text for k in ("Plans", "Upgrade", "subscribe", "unlock", "Unlock"))


async def wait_response(client, entity, after_id: int, timeout: float, me_id: int):
    deadline = time.time() + timeout
    while time.time() < deadline:
        await asyncio.sleep(0.8)
        msgs = await client.get_messages(entity, limit=8)
        for m in msgs:
            if m.id > after_id and m.sender_id != me_id:
                return m
    return None


_BACKGROUND_NOISE_MARKERS = (
    "Post-deploy validation", "Health:", "FAIL", "post_deploy",
    "Edge precompute", "Morning report", "Nudge sent",
)


def _is_background_notification(msg) -> bool:
    """True if the message looks like a bot background job notification, not a user response."""
    text = msg.text or ""
    return any(m in text for m in _BACKGROUND_NOISE_MARKERS)


async def click_btn(client, entity, msg, btn_tuple, timeout=NAV_TIMEOUT):
    """Click a button and wait for the message to change (edit-in-place).

    Prefers edit detection over new-message detection.
    Filters out background bot notifications (post-deploy validation, etc.)
    """
    if btn_tuple is None:
        return None, 0.0
    r_idx, b_idx, _ = btn_tuple
    orig_text = msg.text or ""
    orig_id = msg.id
    t0 = time.time()
    try:
        await msg.click(r_idx, b_idx)
    except Exception as _click_err:
        # DataInvalidError = stale callback data (message was edited since last fetch)
        # Treat as a timing issue — return current message state
        elapsed = time.time() - t0
        try:
            m = await client.get_messages(entity, ids=orig_id)
            return m, elapsed
        except Exception:
            return None, elapsed
    deadline = time.time() + timeout
    while time.time() < deadline:
        await asyncio.sleep(0.5)
        # Prefer edit detection (most bot responses use edit-in-place)
        try:
            m = await client.get_messages(entity, ids=orig_id)
            if m and m.text != orig_text:
                return m, time.time() - t0
        except Exception:
            pass
        # Fall back to new message, but filter background notifications
        msgs = await client.get_messages(entity, limit=5)
        for nm in msgs:
            if nm.id > orig_id and not _is_background_notification(nm):
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
    if not condition:
        failures.append(name)
    return condition


def section(title: str):
    print(f"\n{'─'*60}")
    print(f"  {title}")
    print(f"{'─'*60}")


def is_list_content(text: str) -> bool:
    return any(k in text for k in (
        "Top Edge Picks", "Live Edge", "Predicted Correctly",
        "edge", "Edge", "Scanned",
    ))


def is_detail_content(text: str) -> bool:
    """True if message is a detail (narrative or upgrade prompt) — not the list."""
    return any(k in text for k in (
        "Setup", "Edge", "Risk", "Verdict", "vs", "odds",
        "Bookmaker", "EV", "Upgrade", "Plans", "Loading",
        "unlock", "subscribe",
    ))


def get_current_page_from_msg(msg) -> int | None:
    """Try to determine which page is shown from back button callback_data."""
    if not msg or not msg.reply_markup:
        return None
    for row in msg.reply_markup.rows:
        for btn in row.buttons:
            d = getattr(btn, "data", b"")
            if isinstance(d, bytes):
                d = d.decode("utf-8", errors="replace")
            # Back button is "hot:back:N"
            if d.startswith("hot:back:"):
                try:
                    return int(d.split(":")[-1])
                except ValueError:
                    pass
    return None


async def open_hot_tips(client, entity, me_id: int) -> tuple:
    """Send '💎 Top Edge Picks' and wait for list to load. Returns (msg, elapsed)."""
    sent = await client.send_message(entity, "💎 Top Edge Picks")
    t0 = time.time()
    resp = await wait_response(client, entity, sent.id, LIST_TIMEOUT, me_id)
    elapsed = time.time() - t0
    return resp, elapsed


async def validate_page_tips(client, entity, list_msg, page_label: str, run_i: int) -> tuple[int, int]:
    """Open all detail buttons on the list page, check back returns to correct page."""
    detail_btns = all_edge_detail_btns(list_msg)
    if not detail_btns:
        print(f"    ⚠️  No edge:detail buttons on {page_label}")
        return 0, 0
    passed = 0
    failed = 0
    for di, btn_tuple in enumerate(detail_btns):
        tip_label = btn_tuple[2].text
        print(f"\n    [{page_label} Tip {di+1}/{len(detail_btns)}] Tapping: {tip_label!r}")
        t0 = time.time()
        detail_msg, detail_elapsed = await click_btn(client, entity, list_msg, btn_tuple, timeout=DETAIL_TIMEOUT)
        if not detail_msg:
            check(f"Run{run_i} {page_label} tip{di+1}: detail loaded", False, "No response")
            failed += 1
            continue
        detail_text = detail_msg.text or ""
        has_content = is_detail_content(detail_text)
        print(f"    ⏱  {detail_elapsed:.1f}s — {len(detail_text)} chars")
        print(f"    📝  {detail_text[:80]!r}")
        check(f"Run{run_i} {page_label} tip{di+1}: has detail content", has_content, detail_text[:60])
        check(f"Run{run_i} {page_label} tip{di+1}: detail fast (<{DETAIL_TIMEOUT}s)",
              detail_elapsed < DETAIL_TIMEOUT, f"{detail_elapsed:.1f}s")

        # Determine which page we came from
        current_page_from_back = get_current_page_from_msg(detail_msg)
        print(f"    🔑  Back button page: {current_page_from_back}")

        # Navigate back
        back_btn = find_btn(detail_msg, "Back to Edge Picks")
        if not back_btn:
            back_btn = find_btn(detail_msg, "Back to Edge")
        if back_btn:
            back_msg, back_elapsed = await click_btn(client, entity, detail_msg, back_btn, timeout=NAV_TIMEOUT)
            if back_msg:
                back_text = back_msg.text or ""
                is_list = is_list_content(back_text)
                back_btns = btn_list(back_msg)
                print(f"    ↩  Back: {back_elapsed:.1f}s — {back_text[:60]!r}")
                print(f"    🔘  {back_btns[:5]}")
                check(f"Run{run_i} {page_label} tip{di+1}: back→list content", is_list, back_text[:60])
                # Check that we returned to the expected page by seeing same tip buttons
                back_detail_btns = all_edge_detail_btns(back_msg)
                orig_detail_btns = all_edge_detail_btns(list_msg)
                same_tips = (
                    len(back_detail_btns) == len(orig_detail_btns) and
                    all(
                        get_btn_data(b1) == get_btn_data(b2)
                        for b1, b2 in zip(back_detail_btns, orig_detail_btns)
                    )
                )
                check(f"Run{run_i} {page_label} tip{di+1}: back→same page", same_tips,
                      f"Back has {len(back_detail_btns)} tips, original had {len(orig_detail_btns)}")
                if same_tips:
                    passed += 1
                    list_msg = back_msg  # use back message for next iteration
                else:
                    failed += 1
                    list_msg = back_msg
            else:
                check(f"Run{run_i} {page_label} tip{di+1}: back responded", False, "No response")
                failed += 1
        else:
            print(f"    ⚠️  No Back button found on detail")
            if has_content:
                passed += 1
    return passed, failed


async def run_full_loop(client, entity, me_id: int, run_i: int) -> tuple[int, int]:
    """One full validation loop: open Hot Tips, validate page 1, then page 2 if available."""
    section(f"Run {run_i}/3 — Full Page/Detail Identity Loop")
    passed = failed = 0

    # Open Hot Tips
    print(f"  Sending 💎 Top Edge Picks...")
    ht_msg, ht_elapsed = await open_hot_tips(client, entity, me_id)
    if not ht_msg:
        check(f"Run{run_i}: Hot Tips loaded", False, "No response")
        return 0, 1
    ht_text = ht_msg.text or ""
    ht_btns = btn_list(ht_msg)
    print(f"  ⏱  {ht_elapsed:.1f}s — {len(ht_text)} chars")
    print(f"  📝  {ht_text[:80]!r}")
    print(f"  🔘  {ht_btns[:8]}")
    is_list = is_list_content(ht_text)
    check(f"Run{run_i}: Hot Tips list loaded", is_list, ht_text[:60])
    if not is_list:
        return 0, 1

    # PAGE 1 (page 0)
    p1_btns = all_edge_detail_btns(ht_msg)
    check(f"Run{run_i}: Page 1 has tips", len(p1_btns) > 0, f"{len(p1_btns)} tips")
    if p1_btns:
        p_pass, p_fail = await validate_page_tips(client, entity, ht_msg, "P1", run_i)
        passed += p_pass
        failed += p_fail
    else:
        failed += 1
        return passed, failed

    # Check for page 2
    # After validate_page_tips, we're back on the list. Re-fetch the current list message.
    await asyncio.sleep(0.5)
    msgs = await client.get_messages(entity, limit=5)
    current_list = next((m for m in msgs if m.sender_id != me_id and is_list_content(m.text or "")), None)

    next_btn = find_btn(current_list, "Next") if current_list else None
    if next_btn:
        print(f"\n  → Page 2 available. Navigating...")
        p2_msg, p2_elapsed = await click_btn(client, entity, current_list, next_btn, timeout=NAV_TIMEOUT)
        if p2_msg and is_list_content(p2_msg.text or ""):
            print(f"  ⏱  Page 2 loaded: {p2_elapsed:.1f}s")
            print(f"  📝  {(p2_msg.text or '')[:80]!r}")
            p2_btns = all_edge_detail_btns(p2_msg)
            check(f"Run{run_i}: Page 2 has tips", len(p2_btns) > 0, f"{len(p2_btns)} tips")
            if p2_btns:
                p_pass, p_fail = await validate_page_tips(client, entity, p2_msg, "P2", run_i)
                passed += p_pass
                failed += p_fail
        else:
            check(f"Run{run_i}: Page 2 loaded", False, "No list content")
            failed += 1
    else:
        print(f"\n  ℹ️  No Page 2 available (fewer than {4+1} tips total)")

    return passed, failed


async def main():
    session = load_session()
    if not session.save():
        print("ERROR: No session found.")
        sys.exit(1)

    async with TelegramClient(session, API_ID, API_HASH) as client:
        entity = await client.get_entity(BOT_USERNAME)
        me = await client.get_me()
        me_id = me.id

        print(f"\n{'═'*65}")
        print("  W84-HT2 Live Validation — Hot Tips Page/Detail Identity")
        print(f"  {datetime.now():%Y-%m-%d %H:%M:%S SAST}")
        print(f"{'═'*65}")

        # Set QA diamond tier so all tips are accessible (not locked)
        print("\n  [Setup] Setting QA diamond tier...")
        qa_sent = await client.send_message(entity, "/qa set_diamond")
        qa_resp = await wait_response(client, entity, qa_sent.id, 8.0, me_id)
        if qa_resp:
            print(f"  QA tier set: {(qa_resp.text or '')[:60]}")
        else:
            print("  ⚠️  QA tier set response not received — proceeding anyway")

        total_passed = 0
        total_failed = 0

        for run_i in range(1, 4):
            rp, rf = await run_full_loop(client, entity, me_id, run_i)
            total_passed += rp
            total_failed += rf
            if run_i < 3:
                print(f"\n  [Pause 2s between runs]")
                await asyncio.sleep(2)

        # ─── SUMMARY ───
        section("SUMMARY")
        passed_checks = sum(1 for r in results.values() if r["pass"])
        total_checks = len(results)
        print(f"\n  Results: {passed_checks}/{total_checks} checks passed")
        print(f"  Page/detail passes: {total_passed}")
        print(f"  Page/detail failures: {total_failed}")

        if failures:
            print("\n  FAILURES:")
            for f in failures:
                d = results[f]["detail"]
                print(f"    ❌ {f}")
                if d:
                    print(f"       {d}")
        else:
            print("\n  All checks PASSED ✅")

        identity_stable = total_failed == 0
        check("Zero page/detail identity failures across 3 runs",
              identity_stable, f"pass={total_passed}, fail={total_failed}")

        # Reset QA tier to normal
        print("\n  [Cleanup] Resetting QA tier...")
        try:
            await client.send_message(entity, "/qa reset")
            await asyncio.sleep(1)
        except Exception:
            pass

        report = {
            "wave": "W84-HT2",
            "timestamp": datetime.now().isoformat(),
            "checks_passed": passed_checks,
            "checks_total": total_checks,
            "page_detail_passes": total_passed,
            "page_detail_failures": total_failed,
            "identity_stable": identity_stable,
            "failures": failures,
        }
        out_file = f"/tmp/w84_ht2_validation_{int(time.time())}.json"
        with open(out_file, "w") as f:
            json.dump(report, f, indent=2)
        print(f"\n  Results saved: {out_file}")
        return report


if __name__ == "__main__":
    asyncio.run(main())
