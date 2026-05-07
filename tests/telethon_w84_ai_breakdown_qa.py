#!/usr/bin/env python3
"""
W84 AI Breakdown QA Test — Full back-to-front Telethon verification.
Validates: w84 narrative serving, 4-section card, buttons, gate enforcement.

Callback patterns (from bot.py):
  - ep:pick:N    → Hot Tips list item → edge detail card
  - edge:breakdown:{key}      → Full AI Breakdown (Diamond)
  - edge:breakdown_gate:{key} → Locked AI Breakdown (non-Diamond)
  - hot:back:{page}           → Back to Hot Tips list
"""

import asyncio
import os
import sys
import time

sys.path.insert(0, "/home/paulsportsza/bot")

from dotenv import load_dotenv
load_dotenv("/home/paulsportsza/bot/.env")

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import MessageMediaPhoto

# --- Credentials ---
SESSION_FILE = "/home/paulsportsza/bot/data/telethon_qa_session.string"
BOT_USERNAME = "mzansiedge_bot"
WAIT_TIMEOUT = 45

with open(SESSION_FILE) as f:
    SESSION_STR = f.read().strip()

API_ID = int(os.environ["TELEGRAM_API_ID"])
API_HASH = os.environ["TELEGRAM_API_HASH"]

results = []
verbatim_log = []


def log(msg: str):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def record(name: str, passed: bool, detail: str = ""):
    status = "PASS" if passed else "FAIL"
    results.append((name, passed, detail))
    log(f"  [{status}] {name}" + (f": {detail[:120]}" if detail else ""))


def capture(label: str, text: str):
    verbatim_log.append((label, text))
    log(f"\n  --- VERBATIM: {label} ---\n{text[:1200]}\n  --- END ---")


async def get_latest_id(client) -> int:
    msgs = await client.get_messages(BOT_USERNAME, limit=1)
    return msgs[0].id if msgs else 0


async def wait_for_new_msg(client, after_id: int, timeout: int = WAIT_TIMEOUT):
    """Wait for ANY new message from bot after after_id."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        msgs = await client.get_messages(BOT_USERNAME, limit=5)
        for m in msgs:
            if m.id > after_id:
                return m
        await asyncio.sleep(0.8)
    return None


async def wait_for_msg_with_buttons(client, after_id: int, timeout: int = WAIT_TIMEOUT):
    """Wait for a message with inline buttons from bot after after_id."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        msgs = await client.get_messages(BOT_USERNAME, limit=5)
        for m in msgs:
            if m.id > after_id and m.reply_markup is not None:
                return m
        await asyncio.sleep(1.0)
    # Fallback: return latest new msg even without buttons
    msgs = await client.get_messages(BOT_USERNAME, limit=5)
    for m in msgs:
        if m.id > after_id:
            return m
    return None


async def get_buttons(msg) -> list:
    if msg is None or msg.reply_markup is None:
        return []
    btns = []
    for row in msg.reply_markup.rows:
        for btn in row.buttons:
            btns.append(btn)
    return btns


def btn_cb(btn) -> str:
    if hasattr(btn, "data") and btn.data:
        return btn.data.decode() if isinstance(btn.data, bytes) else str(btn.data)
    return ""


def btn_url(btn) -> str:
    return btn.url if hasattr(btn, "url") and btn.url else ""


async def find_btn(btns, text_frag: str = None, cb_frag: str = None):
    for btn in btns:
        if text_frag and text_frag.lower() in (btn.text or "").lower():
            return btn
        if cb_frag and cb_frag.lower() in btn_cb(btn).lower():
            return btn
    return None


async def tap(client, msg, btn, timeout: int = WAIT_TIMEOUT):
    """Tap a button and return resulting message (new or edited)."""
    before_id = (await client.get_messages(BOT_USERNAME, limit=1))[0].id
    before_msg = (await client.get_messages(BOT_USERNAME, limit=1))[0]
    before_edit = getattr(before_msg, "edit_date", None)

    try:
        await msg.click(data=btn.data if hasattr(btn, "data") else None)
    except Exception as e:
        log(f"  click() raised: {e}")

    deadline = time.time() + timeout
    while time.time() < deadline:
        await asyncio.sleep(1.2)
        msgs = await client.get_messages(BOT_USERNAME, limit=3)
        # New message?
        for m in msgs:
            if m.id > before_id:
                return m
        # Edited message?
        if msgs:
            latest = msgs[0]
            if latest.id == before_id:
                new_edit = getattr(latest, "edit_date", None)
                if new_edit and new_edit != before_edit:
                    return latest

    msgs = await client.get_messages(BOT_USERNAME, limit=1)
    return msgs[0] if msgs else None


def content(msg) -> str:
    if msg is None:
        return ""
    parts = []
    if msg.text:
        parts.append(msg.text)
    if msg.media:
        cap = getattr(msg.media, "caption", "")
        if cap:
            parts.append(cap)
    return "\n".join(parts)


async def send_and_wait(client, text: str, timeout: int = 20):
    """Send text and wait for any bot response."""
    anchor = await get_latest_id(client)
    await client.send_message(BOT_USERNAME, text)
    return await wait_for_new_msg(client, anchor, timeout=timeout)


async def send_and_wait_buttons(client, text: str, timeout: int = 50):
    """Send text and wait for bot response with inline buttons."""
    anchor = await get_latest_id(client)
    await client.send_message(BOT_USERNAME, text)
    return await wait_for_msg_with_buttons(client, anchor, timeout=timeout)


async def run_qa(client):
    log("=" * 60)
    log("W84 AI BREAKDOWN QA — TELETHON BACK-TO-FRONT TEST")
    log("=" * 60)

    # ----------------------------------------------------------------
    # PRE-FLIGHT: Set QA override to Diamond
    # ----------------------------------------------------------------
    log("\n--- PRE-FLIGHT: Set Diamond tier override ---")
    qa_set_resp = await send_and_wait(client, "/qa set_diamond", timeout=20)
    qa_text = content(qa_set_resp)
    capture("QA set_diamond", qa_text)
    record("QA set_diamond acknowledged", bool(qa_set_resp), qa_text[:150])
    await asyncio.sleep(2)

    # ----------------------------------------------------------------
    # STEP 1: Load Hot Tips list
    # ----------------------------------------------------------------
    log("\n--- STEP 1: Load Top Edge Picks (Diamond) ---")
    tips_msg = await send_and_wait_buttons(client, "💎 Top Edge Picks", timeout=60)
    tips_text = content(tips_msg)
    capture("Hot Tips list", tips_text)

    has_content = bool(tips_msg) and (bool(tips_text) or (tips_msg and tips_msg.media))
    record("Hot Tips list loads with content", has_content, tips_text[:200])

    # Check for edge tier badges in text
    has_badge = any(e in tips_text for e in ["💎", "🥇", "🥈", "🥉"])
    record("Edge tier badges in tips text", has_badge, tips_text[:300])

    # ----------------------------------------------------------------
    # STEP 2: Inspect buttons (ep:pick:N → detail cards)
    # ----------------------------------------------------------------
    log("\n--- STEP 2: Inspect tip list buttons ---")
    t_btns = await get_buttons(tips_msg)
    log(f"  {len(t_btns)} buttons found:")
    for btn in t_btns:
        log(f"    '{btn.text}' → cb={btn_cb(btn)} url={btn_url(btn)}")

    # ep:pick:N buttons are the tip entry points
    pick_buttons = [(btn, btn_cb(btn)) for btn in t_btns if btn_cb(btn).startswith("ep:pick:")]
    record("At least one ep:pick:N button present", len(pick_buttons) > 0, f"Found {len(pick_buttons)} pick buttons")

    if not pick_buttons:
        log("  FATAL: No ep:pick buttons found. Cannot test detail flow.")
        # Dump the whole message for debugging
        log(f"  Tips text (full): {tips_text}")
        # Try to get more messages
        recent = await client.get_messages(BOT_USERNAME, limit=5)
        for m in recent:
            log(f"  Recent msg id={m.id}: {content(m)[:200]}")
        # Record all remaining tests as fail and return
        for name in [
            "Edge detail card renders", "Section 📋 The Setup present",
            "Section 🎯 The Edge present", "Section ⚠️ The Risk present",
            "Section 🏆 The Verdict present",
            "🤖 Full AI Breakdown button visible (Diamond)",
            "🔒 Locked breakdown NOT shown for Diamond",
            "↩️ Back button on detail", "Bookmaker CTA on detail",
            "AI Breakdown photo card renders", "AI Breakdown is photo",
            "Bookmaker CTA on breakdown", "↩️ Back to Edge Picks on breakdown",
            "Back to Edge Picks returns to tips list",
            "Tip 1 detail", "Tip 2 detail", "Tip 3 detail", "3 tips tested",
            "Bronze: no 🤖 button", "Bronze: gate enforced",
        ]:
            record(name, False, "No pick buttons found")
        return results, "FAIL", verbatim_log

    # ----------------------------------------------------------------
    # STEP 3: Tap first ep:pick:0 → edge detail card
    # ----------------------------------------------------------------
    log("\n--- STEP 3: Tap ep:pick:0 → edge detail card ---")
    first_pick_btn = pick_buttons[0][0]
    log(f"  Tapping: '{first_pick_btn.text}'")

    detail_msg = await tap(client, tips_msg, first_pick_btn, timeout=40)
    await asyncio.sleep(1.5)

    # Re-fetch in case edited
    recent = await client.get_messages(BOT_USERNAME, limit=3)
    detail_msg = recent[0]

    detail_text = content(detail_msg)
    capture(f"Edge detail card ('{first_pick_btn.text}')", detail_text)

    record("Edge detail card renders", bool(detail_msg) and (bool(detail_text) or detail_msg.media), detail_text[:150])

    # Check 4 narrative sections
    has_setup   = "📋" in detail_text or "The Setup" in detail_text
    has_edge_s  = "🎯" in detail_text or "The Edge" in detail_text
    has_risk    = "⚠️" in detail_text or "The Risk" in detail_text
    has_verdict = "🏆" in detail_text or "The Verdict" in detail_text

    record("Section 📋 The Setup present",  has_setup,   "OK" if has_setup   else detail_text[:400])
    record("Section 🎯 The Edge present",   has_edge_s,  "OK" if has_edge_s  else detail_text[:400])
    record("Section ⚠️ The Risk present",   has_risk,    "OK" if has_risk    else detail_text[:400])
    record("Section 🏆 The Verdict present", has_verdict, "OK" if has_verdict else detail_text[:400])

    # ----------------------------------------------------------------
    # STEP 4: Check detail card buttons
    # ----------------------------------------------------------------
    log("\n--- STEP 4: Check detail card buttons ---")
    d_btns = await get_buttons(detail_msg)
    log(f"  {len(d_btns)} buttons on detail card:")
    for btn in d_btns:
        log(f"    '{btn.text}' → cb={btn_cb(btn)} url={btn_url(btn)}")

    # AI Breakdown button (Diamond: 🤖 Full AI Breakdown → edge:breakdown:)
    ai_btn = await find_btn(d_btns, cb_frag="edge:breakdown:")
    locked_ai_btn = await find_btn(d_btns, cb_frag="edge:breakdown_gate:")
    has_unlocked = ai_btn is not None and "🤖" in (ai_btn.text or "")
    has_locked_btn = locked_ai_btn is not None

    record("🤖 Full AI Breakdown button visible (Diamond)", has_unlocked,
           f"btn: {ai_btn.text if ai_btn else 'NOT FOUND'}")
    record("🔒 Locked breakdown NOT shown for Diamond", not has_locked_btn,
           "OK" if not has_locked_btn else "LOCKED BTN PRESENT")

    # Back button
    back_btn = await find_btn(d_btns, cb_frag="hot:back:")
    record("↩️ Back button on detail", back_btn is not None,
           f"btn: {back_btn.text if back_btn else 'NOT FOUND'}")

    # Bookmaker CTA (URL button)
    bk_btn = None
    for btn in d_btns:
        if btn_url(btn):
            bk_btn = btn
            break
    record("Bookmaker CTA (URL) on detail", bk_btn is not None,
           f"btn: {bk_btn.text if bk_btn else 'NOT FOUND'}")

    # ----------------------------------------------------------------
    # STEP 5: Tap 🤖 Full AI Breakdown → breakdown card
    # ----------------------------------------------------------------
    if has_unlocked and ai_btn is not None:
        log("\n--- STEP 5: Tap Full AI Breakdown ---")
        bd_result = await tap(client, detail_msg, ai_btn, timeout=50)
        await asyncio.sleep(2)

        recent = await client.get_messages(BOT_USERNAME, limit=3)
        bd_msg = recent[0]

        bd_text = content(bd_msg)
        is_photo = bd_msg is not None and isinstance(bd_msg.media, MessageMediaPhoto)
        capture("AI Breakdown card", f"[is_photo={is_photo}]\n{bd_text}")

        record("AI Breakdown card renders", bool(bd_msg) and (bool(bd_text) or bd_msg.media), bd_text[:100])
        record("AI Breakdown delivered as photo card", is_photo,
               f"media type: {type(bd_msg.media).__name__ if bd_msg and bd_msg.media else 'None'}")

        bd_btns = await get_buttons(bd_msg)
        log(f"  Breakdown has {len(bd_btns)} buttons:")
        for btn in bd_btns:
            log(f"    '{btn.text}' → cb={btn_cb(btn)} url={btn_url(btn)}")

        bd_bk = None
        for btn in bd_btns:
            if btn_url(btn):
                bd_bk = btn
                break
        record("Bookmaker CTA on breakdown card", bd_bk is not None,
               f"btn: {bd_bk.text if bd_bk else 'NOT FOUND'}")

        bd_back = await find_btn(bd_btns, text_frag="Back to Edge Picks")
        record("↩️ Back to Edge Picks on breakdown", bd_back is not None,
               f"btn: {bd_back.text if bd_back else 'NOT FOUND'}")

        # Step 5b: Tap Back to Edge Picks
        if bd_back is not None:
            log("\n--- STEP 5b: Back from breakdown to tips list ---")
            back_result = await tap(client, bd_msg, bd_back, timeout=25)
            await asyncio.sleep(1.5)
            recent = await client.get_messages(BOT_USERNAME, limit=3)
            back_msg = recent[0]
            back_text = content(back_msg)
            capture("After Back to Edge Picks", back_text)
            is_tips = any(x in back_text for x in ["💎", "🥇", "🥈", "🥉", "Edge Picks", "Live Edges", "Top Edge", "ep:pick"])
            if not is_tips:
                bk_btns = await get_buttons(back_msg)
                is_tips = any(btn_cb(b).startswith("ep:pick:") for b in bk_btns)
            record("Back to Edge Picks returns to tips list", is_tips, back_text[:200])
        else:
            record("Back to Edge Picks returns to tips list", False, "No back button on breakdown")
    else:
        log(f"  SKIP STEP 5 — {'no 🤖 button' if not ai_btn else 'button text: ' + (ai_btn.text or '')}")
        # Check if detail card loaded at all — if not, this may be a render failure
        detail_is_card = detail_msg and detail_msg.media and isinstance(detail_msg.media, MessageMediaPhoto)
        if detail_is_card and not has_unlocked:
            # Card loaded but button not present — possible: match has no w84 narrative
            log("  Detail card is a photo but no AI Breakdown button. Match may lack w84 narrative.")
            record("AI Breakdown card renders", False, "No 🤖 button — likely no w84 narrative for this match")
        else:
            record("AI Breakdown card renders", False, "No unlocked 🤖 button found on detail card")
        record("AI Breakdown delivered as photo card", False, "Skipped — no button")
        record("Bookmaker CTA on breakdown card", False, "Skipped — no button")
        record("↩️ Back to Edge Picks on breakdown", False, "Skipped — no button")
        record("Back to Edge Picks returns to tips list", False, "Skipped — no button")

    # ----------------------------------------------------------------
    # STEP 6: Multi-tip test — test 3 different tips
    # ----------------------------------------------------------------
    log("\n--- STEP 6: Multi-tip test (3 tips) ---")
    tips_msg2 = await send_and_wait_buttons(client, "💎 Top Edge Picks", timeout=55)
    tips_tested = 0

    if tips_msg2:
        btns2 = await get_buttons(tips_msg2)
        pick_btns2 = [(btn, btn_cb(btn)) for btn in btns2 if btn_cb(btn).startswith("ep:pick:")]

        current_tips_msg = tips_msg2
        for i, (p_btn, p_cb) in enumerate(pick_btns2[:3]):
            log(f"  Multi-tip {i+1}: '{p_btn.text}' → {p_cb}")
            t_result = await tap(client, current_tips_msg, p_btn, timeout=35)
            await asyncio.sleep(1.5)
            recent = await client.get_messages(BOT_USERNAME, limit=3)
            t_msg = recent[0]
            t_text = content(t_msg)

            has_card = bool(t_msg) and (bool(t_text) or t_msg.media)
            record(f"Tip {i+1} detail renders", has_card, t_text[:80])
            tips_tested += 1

            # Navigate back
            t_btns = await get_buttons(t_msg)
            t_back = await find_btn(t_btns, cb_frag="hot:back:")
            if t_back:
                back_r = await tap(client, t_msg, t_back, timeout=20)
                await asyncio.sleep(1.2)
                # Get new tips message
                recent2 = await client.get_messages(BOT_USERNAME, limit=5)
                for m in recent2:
                    bts = await get_buttons(m)
                    if any(btn_cb(b).startswith("ep:pick:") for b in bts):
                        current_tips_msg = m
                        break
            else:
                # Try sending tips text again
                log(f"  No back button on tip {i+1} — re-fetching tips list")
                current_tips_msg = await send_and_wait_buttons(client, "💎 Top Edge Picks", timeout=40)

        record("3 tips tested successfully", tips_tested >= 3, f"{tips_tested}/3")
    else:
        record("Tips reload for multi-test", False, "No response")
        record("3 tips tested successfully", False, "0/3")

    # ----------------------------------------------------------------
    # STEP 7: Bronze gate — no 🤖 button, gate enforced
    # ----------------------------------------------------------------
    log("\n--- STEP 7: Bronze gate enforcement ---")
    qa_bronze = await send_and_wait(client, "/qa set_bronze", timeout=15)
    bronze_ack = content(qa_bronze)
    capture("QA set_bronze", bronze_ack)
    record("QA set_bronze acknowledged", bool(qa_bronze), bronze_ack[:100])
    await asyncio.sleep(2)

    bronze_tips_msg = await send_and_wait_buttons(client, "💎 Top Edge Picks", timeout=55)
    bronze_tips_text = content(bronze_tips_msg)
    capture("Bronze Hot Tips list", bronze_tips_text)

    has_lock = "🔒" in bronze_tips_text
    record("🔒 Lock symbol in Bronze tips", has_lock, bronze_tips_text[:300])

    # Tap a pick button as Bronze
    b_btns = await get_buttons(bronze_tips_msg) if bronze_tips_msg else []
    b_pick_btns = [btn for btn in b_btns if btn_cb(btn).startswith("ep:pick:")]

    if b_pick_btns:
        b_d_result = await tap(client, bronze_tips_msg, b_pick_btns[0], timeout=30)
        await asyncio.sleep(1.5)
        recent = await client.get_messages(BOT_USERNAME, limit=3)
        b_d_msg = recent[0]
        b_d_text = content(b_d_msg)
        capture("Bronze detail view", b_d_text)

        b_d_btns = await get_buttons(b_d_msg)
        bronze_unlocked_ai = any(
            "🤖" in (btn.text or "") and "Breakdown" in (btn.text or "")
            for btn in b_d_btns
        )
        bronze_locked_ai = any(
            "🔒" in (btn.text or "") and "Breakdown" in (btn.text or "")
            for btn in b_d_btns
        )
        gate_text = "subscribe" in b_d_text.lower() or "upgrade" in b_d_text.lower() or "diamond" in b_d_text.lower() or bronze_locked_ai

        record("Bronze: 🤖 Unlocked AI Breakdown NOT shown", not bronze_unlocked_ai,
               f"unlocked: {bronze_unlocked_ai}")
        record("Bronze: gate enforced (🔒 or upgrade text)", gate_text, b_d_text[:200])
    else:
        # No pick buttons — may mean tips are fully locked for Bronze
        fully_locked = "🔒" in bronze_tips_text
        record("Bronze: 🤖 Unlocked AI Breakdown NOT shown", True,
               "No pick buttons — content gated at list level (OK)")
        record("Bronze: gate enforced (🔒 or upgrade text)", fully_locked, bronze_tips_text[:200])

    # ----------------------------------------------------------------
    # STEP 8: Reset QA tier
    # ----------------------------------------------------------------
    log("\n--- STEP 8: Reset QA tier ---")
    reset_resp = await send_and_wait(client, "/qa reset", timeout=15)
    reset_text = content(reset_resp)
    capture("QA reset", reset_text)
    record("QA reset acknowledged", bool(reset_resp), reset_text[:100])

    # ----------------------------------------------------------------
    # SUMMARY
    # ----------------------------------------------------------------
    log("\n" + "=" * 60)
    log("TEST RESULTS SUMMARY")
    log("=" * 60)
    passed = sum(1 for _, p, _ in results if p)
    total = len(results)
    for name, p, detail in results:
        status = "PASS" if p else "FAIL"
        log(f"  [{status}] {name}")
        if not p and detail:
            log(f"         → {detail[:150]}")

    log(f"\n  {passed}/{total} passed")
    verdict = "PASS" if passed == total else ("PARTIAL" if passed / total >= 0.8 else "FAIL")
    log(f"  Verdict: {verdict}")

    return results, verdict, verbatim_log


async def main():
    log(f"Connecting (API_ID={API_ID})...")
    async with TelegramClient(StringSession(SESSION_STR), API_ID, API_HASH) as client:
        log("Connected.")
        return await run_qa(client)


if __name__ == "__main__":
    out = asyncio.run(main())
    results_out, verdict, vl = out
    sys.exit(0 if verdict == "PASS" else 1)
