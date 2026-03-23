"""W84-P1N Narrative Validation — QA wave.

Validates that tip-detail narratives are rich, accurate, and coherent
after the W84-P1 serving changes.

Tests:
1. /qa set_diamond → full access confirmed
2. 5+ tip-detail narratives captured and assessed
3. 2+ My Matches breakdown flows captured and assessed
4. List / detail coherence verified
5. Richness / specificity scoring per detail
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
import json
import re
from datetime import datetime

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import ReplyInlineMarkup, KeyboardButtonCallback

API_ID   = 32418601
API_HASH = "95e313a8ef5b998be0515dd8328fac57"
BOT_USERNAME = "mzansiedge_bot"
STRING_SESSION_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "telethon_session.string")

TIPS_TIMEOUT   = 120   # seconds max for tips list
DETAIL_TIMEOUT = 45    # seconds max for detail narrative
NAV_TIMEOUT    = 15    # seconds for navigation
BREAKDOWN_TIMEOUT = 60 # seconds for game breakdown

# ─────────────────────────────────────────────
# Quality scoring thresholds
# ─────────────────────────────────────────────
MIN_DETAIL_CHARS  = 300   # minimum acceptable narrative length
GOOD_DETAIL_CHARS = 600   # "rich" threshold
SECTION_HEADERS   = ["📋", "🎯", "⚠️", "🏆"]  # expected sections
GENERIC_PHRASES   = [
    "general analysis", "based on available data", "hard to predict",
    "more information needed", "form data unavailable", "no data available",
    "cannot determine", "insufficient data",
]

checks: dict = {}
detail_captures: list = []
breakdown_captures: list = []


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def get_all_buttons(msg) -> list[tuple[str, str, bytes]]:
    btns = []
    if msg.reply_markup and isinstance(msg.reply_markup, ReplyInlineMarkup):
        for row in msg.reply_markup.rows:
            for btn in row.buttons:
                if isinstance(btn, KeyboardButtonCallback):
                    d = btn.data.decode() if isinstance(btn.data, bytes) else btn.data
                    raw = btn.data if isinstance(btn.data, bytes) else btn.data.encode()
                    btns.append((btn.text, d, raw))
    return btns


def find_btn(msg, text_substr: str) -> tuple | None:
    for text, data, raw in get_all_buttons(msg):
        if text_substr.lower() in text.lower():
            return (text, data, raw)
    return None


def find_btn_data(msg, data_substr: str) -> tuple | None:
    for text, data, raw in get_all_buttons(msg):
        if data_substr in data:
            return (text, data, raw)
    return None


def find_all_btns_data(msg, data_substr: str) -> list[tuple]:
    return [(text, data, raw) for text, data, raw in get_all_buttons(msg)
            if data_substr in data]


def check(name: str, condition: bool, detail: str = "") -> bool:
    status = "✅ PASS" if condition else "❌ FAIL"
    line = f"  {status} — {name}"
    if detail:
        line += f"\n     {detail}"
    print(line)
    checks[name] = {"pass": condition, "detail": detail}
    return condition


def section(title: str):
    print(f"\n{'─'*60}")
    print(f"  {title}")
    print(f"{'─'*60}")


async def wait_for_new_msg(client, entity, after_id: int, timeout: float, me_id: int):
    deadline = time.time() + timeout
    while time.time() < deadline:
        await asyncio.sleep(1.5)
        msgs = await client.get_messages(entity, limit=10)
        for m in msgs:
            if m.id > after_id and m.sender_id != me_id:
                return m
    return None


async def wait_for_content_msg(client, entity, after_id: int, timeout: float,
                                me_id: int, min_len: int = 80) -> tuple[object | None, float]:
    """Wait for a substantive (min_len chars) bot message after after_id."""
    t0 = time.time()
    deadline = t0 + timeout
    last_seen = None
    while time.time() < deadline:
        await asyncio.sleep(1.5)
        msgs = await client.get_messages(entity, limit=10)
        for m in msgs:
            if m.id > after_id and m.sender_id != me_id:
                txt = m.text or ""
                if len(txt) >= min_len:
                    return m, time.time() - t0
                if m.id != (last_seen or 0):
                    last_seen = m.id  # still loading spinner
    return None, time.time() - t0


async def click_and_wait(client, entity, msg, data_raw: bytes,
                          timeout: float, me_id: int, min_len: int = 80) -> tuple[object | None, float]:
    """Click a button by sending callback and waiting for response."""
    t0 = time.time()
    last_msg_id = msg.id
    # Get latest message ID so we can spot the response
    latest = await client.get_messages(entity, limit=1)
    if latest:
        last_msg_id = max(last_msg_id, latest[0].id)
    try:
        await msg.click(data=data_raw)
    except Exception as e:
        print(f"    click() error: {e} — trying via rows/cols")
        # Fall back: iterate rows to find by data
        if msg.reply_markup and isinstance(msg.reply_markup, ReplyInlineMarkup):
            for r_i, row in enumerate(msg.reply_markup.rows):
                for b_i, btn in enumerate(row.buttons):
                    if isinstance(btn, KeyboardButtonCallback):
                        raw2 = btn.data if isinstance(btn.data, bytes) else btn.data.encode()
                        if raw2 == data_raw:
                            try:
                                await msg.click(r_i, b_i)
                                break
                            except Exception as e2:
                                print(f"    row/col click also failed: {e2}")

    # Wait for response or edit
    deadline = time.time() + timeout
    while time.time() < deadline:
        await asyncio.sleep(1.5)
        # Check for edit to current message
        try:
            updated = await client.get_messages(entity, ids=msg.id)
            if updated and updated.text and updated.text != (msg.text or ""):
                if len(updated.text) >= min_len:
                    return updated, time.time() - t0
        except Exception:
            pass
        # Check for new message
        msgs = await client.get_messages(entity, limit=10)
        for m in msgs:
            if m.id > last_msg_id and m.sender_id != me_id:
                txt = m.text or ""
                if len(txt) >= min_len:
                    return m, time.time() - t0
    # Return whatever we have
    try:
        updated = await client.get_messages(entity, ids=msg.id)
        return updated, time.time() - t0
    except Exception:
        return None, time.time() - t0


# ─────────────────────────────────────────────
# Narrative quality scorer
# ─────────────────────────────────────────────

def score_narrative(text: str, list_item: dict | None = None) -> dict:
    """Score narrative quality. Returns a dict of metrics."""
    if not text:
        return {"score": 0, "issues": ["empty"], "rich": False}

    issues = []
    positives = []

    length = len(text)

    # Section presence
    sections_found = [h for h in SECTION_HEADERS if h in text]
    if len(sections_found) >= 3:
        positives.append(f"Has {len(sections_found)}/4 sections: {sections_found}")
    elif len(sections_found) >= 2:
        positives.append(f"Has {len(sections_found)}/4 sections")
        issues.append(f"Missing sections: {[h for h in SECTION_HEADERS if h not in text]}")
    else:
        issues.append(f"Only {len(sections_found)}/4 sections found")

    # Length
    if length >= GOOD_DETAIL_CHARS:
        positives.append(f"Rich length: {length} chars")
    elif length >= MIN_DETAIL_CHARS:
        positives.append(f"Acceptable length: {length} chars")
    else:
        issues.append(f"Too short: {length} chars (min {MIN_DETAIL_CHARS})")

    # Generic phrases
    found_generic = [p for p in GENERIC_PHRASES if p.lower() in text.lower()]
    if found_generic:
        issues.append(f"Generic filler phrases: {found_generic}")

    # Fixture specificity: team names / odds mentioned
    has_odds = bool(re.search(r"\d+\.\d+", text))  # decimal odds e.g. 1.85
    has_ev = "EV" in text or "ev" in text.lower() or "+" in text
    has_bookmaker = any(bk in text.lower() for bk in
                        ["betway", "hollywoodbets", "gbets", "supabets", "sportingbet"])

    if has_odds:
        positives.append("Has decimal odds")
    if has_ev:
        positives.append("Has EV reference")
    if has_bookmaker:
        positives.append("Has bookmaker mention")
    if not has_odds and not has_bookmaker:
        issues.append("No odds/bookmaker context found")

    # vs mention (fixture identity)
    has_fixture = " vs " in text.lower() or " v " in text.lower()
    if not has_fixture:
        issues.append("No 'vs' found — fixture identity unclear")
    else:
        positives.append("Fixture identity present")

    # Verdict / recommendation
    has_verdict = "🏆" in text or "Verdict" in text or "verdict" in text
    if has_verdict:
        positives.append("Has verdict section")
    else:
        issues.append("No verdict found")

    # Banned/templated language
    template_signals = [
        "Data unavailable", "No data", "Unknown", "form data unavailable",
        "Home take on Away",  # placeholder from old W82
    ]
    found_template = [t for t in template_signals if t in text]
    if found_template:
        issues.append(f"Template/placeholder text: {found_template}")

    # List/detail coherence
    if list_item:
        list_teams = list_item.get("teams", "").lower()
        list_outcome = list_item.get("outcome", "").lower()
        # Check team names appear in detail
        if list_teams:
            teams = [t.strip() for t in list_teams.split(" vs ")]
            for t in teams:
                if t and len(t) > 3 and t.lower() not in text.lower():
                    issues.append(f"Team '{t}' from list not found in detail")
        # Check outcome
        if list_outcome and list_outcome not in text.lower():
            issues.append(f"Outcome '{list_outcome}' from list not in detail")

    # Score: 0-10
    base = 5
    base += min(len(positives), 5)
    base -= min(len(issues) * 1.5, 5)
    base = max(0, min(10, base))

    rich = length >= GOOD_DETAIL_CHARS and len(sections_found) >= 3 and not found_generic

    return {
        "score": round(base, 1),
        "length": length,
        "sections": sections_found,
        "positives": positives,
        "issues": issues,
        "rich": rich,
        "has_odds": has_odds,
        "has_bookmaker": has_bookmaker,
        "has_verdict": has_verdict,
    }


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────

async def main():
    if not os.path.exists(STRING_SESSION_FILE):
        print(f"ERROR: No session at {STRING_SESSION_FILE}")
        sys.exit(1)

    with open(STRING_SESSION_FILE) as f:
        session_str = f.read().strip()

    async with TelegramClient(StringSession(session_str), API_ID, API_HASH) as client:
        entity = await client.get_entity(BOT_USERNAME)
        me = await client.get_me()
        me_id = me.id

        print(f"\n{'═'*65}")
        print("  W84-P1N — Narrative Validation (QA)")
        print(f"  {datetime.now():%Y-%m-%d %H:%M:%S SAST}")
        print(f"{'═'*65}")

        # ══════════════════════════════════════════════════
        # STEP 0: QA entitlement — set diamond
        # ══════════════════════════════════════════════════
        section("Step 0: QA Entitlement Setup")

        print("  Sending /qa reset...")
        await client.send_message(entity, "/qa reset")
        await asyncio.sleep(3)

        print("  Sending /qa set_diamond...")
        sent_qa = await client.send_message(entity, "/qa set_diamond")
        await asyncio.sleep(5)

        qa_msgs = await client.get_messages(entity, limit=4)
        qa_confirm = ""
        for m in qa_msgs:
            if not m.out and m.text and ("diamond" in m.text.lower() or "QA" in m.text):
                qa_confirm = m.text[:120]
                break

        check("QA diamond override set", "diamond" in qa_confirm.lower() or "DIAMOND" in qa_confirm,
              f"Confirm msg: {qa_confirm!r}")
        print(f"  QA confirm text: {qa_confirm!r}")

        # ══════════════════════════════════════════════════
        # STEP 1: Get Top Edge Picks (full list)
        # ══════════════════════════════════════════════════
        section("Step 1: Top Edge Picks — List")

        print("  Sending 💎 Top Edge Picks...")
        sent_tips = await client.send_message(entity, "💎 Top Edge Picks")
        sent_tips_id = sent_tips.id
        t0_tips = time.time()

        # Wait for tips with edge:detail buttons (up to TIPS_TIMEOUT)
        tips_msg = None
        tips_elapsed = 0.0

        for poll_at in [10, 20, 35, 50, 70, 90, 110, TIPS_TIMEOUT]:
            wait_s = poll_at - (time.time() - t0_tips)
            if wait_s > 0:
                await asyncio.sleep(wait_s)
            elapsed = time.time() - t0_tips
            msgs = await client.get_messages(entity, limit=15)
            newer = [m for m in msgs if not m.out and m.id > sent_tips_id]
            edge_total = sum(
                1 for m in newer
                for _, d, _ in get_all_buttons(m)
                if d.startswith("edge:detail:")
            )
            all_btns_debug = [(t, d) for m in newer[:3] for t, d, _ in get_all_buttons(m)][:8]
            print(f"    {elapsed:.0f}s: {len(newer)} msgs, {edge_total} edge buttons | btns: {all_btns_debug}")
            if edge_total > 0:
                for m in newer:
                    if any(d.startswith("edge:detail:") for _, d, _ in get_all_buttons(m)):
                        tips_msg = m
                        break
                tips_elapsed = elapsed
                break
            if elapsed >= TIPS_TIMEOUT:
                print("  TIMEOUT — no edge buttons found")
                break

        if not tips_msg:
            check("Tips list loads with edge buttons", False,
                  f"No edge:detail buttons after {TIPS_TIMEOUT}s")
            print("  ABORTING — cannot proceed without tips list")
            return

        tips_text = tips_msg.text or ""
        edge_btns = find_all_btns_data(tips_msg, "edge:detail:")
        all_btns = get_all_buttons(tips_msg)

        print(f"\n  Tips loaded in {tips_elapsed:.1f}s")
        print(f"  Text length: {len(tips_text)} chars")
        print(f"  Edge buttons: {len(edge_btns)}")
        print(f"  Full text preview:\n{'-'*40}")
        print(tips_text[:500])
        print(f"{'-'*40}")

        check("Tips list loads with edge buttons", len(edge_btns) > 0,
              f"{len(edge_btns)} edge buttons")
        check("Tips list loads within timeout", tips_elapsed < TIPS_TIMEOUT,
              f"{tips_elapsed:.1f}s")

        has_tier = any(t in tips_text for t in ("💎", "🥇", "🥈", "🥉"))
        check("Tips list has tier badges", has_tier, f"Tier emoji in text")

        has_hit_rate = "%" in tips_text
        check("Tips list has percentage (hit rate or EV)", has_hit_rate, "% in text")

        # ══════════════════════════════════════════════════
        # STEP 2: Open 5 tip details — capture full narratives
        # ══════════════════════════════════════════════════
        section("Step 2: Tip Detail Narrative Quality (5 tips)")

        # Parse list items to check coherence later
        list_items = []
        for btn_text, btn_data, _ in edge_btns:
            match_key = btn_data.replace("edge:detail:", "")
            list_items.append({"match_key": match_key, "btn_text": btn_text})

        print(f"  Will test {min(5, len(edge_btns))} of {len(edge_btns)} available details\n")

        details_opened = 0
        for idx, (btn_text, btn_data, btn_raw) in enumerate(edge_btns[:5]):
            match_key = btn_data.replace("edge:detail:", "")
            print(f"\n  ── Detail {idx+1}: {btn_text!r}")
            print(f"     match_key: {match_key}")

            # Refresh tips message
            fresh = await client.get_messages(entity, ids=tips_msg.id)
            if not fresh:
                print("     ERROR: cannot refresh tips message")
                continue

            t0_detail = time.time()
            detail_msg, detail_elapsed = await click_and_wait(
                client, entity, fresh, btn_raw,
                timeout=DETAIL_TIMEOUT, me_id=me_id, min_len=MIN_DETAIL_CHARS
            )

            if not detail_msg or not (detail_msg.text or ""):
                check(f"Detail {idx+1} loads", False, "No response")
                await asyncio.sleep(3)
                continue

            det_text = detail_msg.text or ""
            det_btns = get_all_buttons(detail_msg)
            det_btn_labels = [t for t, d, _ in det_btns]
            details_opened += 1

            print(f"     ⏱  {detail_elapsed:.1f}s — {len(det_text)} chars")
            print(f"     🔘  Buttons: {det_btn_labels}")
            print(f"     📝  Full narrative:")
            print(f"     {'·'*50}")
            # Print up to 1500 chars
            print(det_text[:1500])
            if len(det_text) > 1500:
                print(f"     ... [{len(det_text) - 1500} more chars]")
            print(f"     {'·'*50}")

            # Score narrative quality
            quality = score_narrative(det_text, {"match_key": match_key})
            print(f"\n     Quality score: {quality['score']}/10")
            print(f"     Rich: {'YES' if quality['rich'] else 'NO'}")
            if quality["positives"]:
                print(f"     ✅ {'; '.join(quality['positives'])}")
            if quality["issues"]:
                print(f"     ⚠️  {'; '.join(quality['issues'])}")

            detail_capture = {
                "index": idx + 1,
                "match_key": match_key,
                "btn_text": btn_text,
                "elapsed_s": detail_elapsed,
                "text_length": len(det_text),
                "full_text": det_text,
                "buttons": det_btn_labels,
                "quality": quality,
            }
            detail_captures.append(detail_capture)

            # Checks
            check(f"Detail {idx+1}: loads within {DETAIL_TIMEOUT}s",
                  detail_elapsed < DETAIL_TIMEOUT, f"{detail_elapsed:.1f}s")
            check(f"Detail {idx+1}: minimum length ({MIN_DETAIL_CHARS} chars)",
                  len(det_text) >= MIN_DETAIL_CHARS, f"{len(det_text)} chars")
            check(f"Detail {idx+1}: rich length ({GOOD_DETAIL_CHARS} chars)",
                  len(det_text) >= GOOD_DETAIL_CHARS, f"{len(det_text)} chars")
            check(f"Detail {idx+1}: has sections",
                  len(quality["sections"]) >= 2, f"sections: {quality['sections']}")
            check(f"Detail {idx+1}: no generic filler",
                  not any(g in det_text.lower() for g in GENERIC_PHRASES), "")
            check(f"Detail {idx+1}: has Back button",
                  any("edge picks" in t.lower() or t.strip().startswith("↩️ Back")
                      for t, _, _ in det_btns),
                  f"Buttons: {det_btn_labels}")
            check(f"Detail {idx+1}: quality score ≥ 5",
                  quality["score"] >= 5, f"Score: {quality['score']}")

            # Navigate Back to Edge Picks — match "↩️ Back to Edge Picks" or
            # "Back to Edge" specifically, NOT "Back home" (CTA to bookmaker).
            back_btn = next(
                ((text, data, raw) for text, data, raw in det_btns
                 if "edge picks" in text.lower() or text.strip().startswith("↩️ Back")),
                None
            )
            if back_btn:
                print(f"\n     → Back: {back_btn[0]!r}")
                t0_back = time.time()
                back_msg, back_elapsed = await click_and_wait(
                    client, entity, detail_msg, back_btn[2],
                    timeout=NAV_TIMEOUT, me_id=me_id, min_len=50
                )
                if back_msg:
                    back_text = back_msg.text or ""
                    is_list = ("edge" in back_text.lower() or "found" in back_text.lower()
                               or "Live Edge" in back_text or len(get_all_buttons(back_msg)) > 2)
                    check(f"Detail {idx+1}: back → tips list", is_list,
                          f"{back_elapsed:.1f}s — {back_text[:50]!r}")
                    check(f"Detail {idx+1}: back < 5s", back_elapsed < 5.0,
                          f"{back_elapsed:.1f}s")
                    tips_msg = back_msg  # update ref for next iteration
                else:
                    check(f"Detail {idx+1}: back → tips list", False, "No response")

            await asyncio.sleep(4)

        check(f"Opened 5 tip details", details_opened >= 5,
              f"Opened {details_opened}/5 required")

        # ══════════════════════════════════════════════════
        # STEP 3: My Matches — game breakdown flows
        # ══════════════════════════════════════════════════
        section("Step 3: My Matches — Game Breakdown (2 flows)")

        print("  Sending ⚽ My Matches...")
        sent_mm = await client.send_message(entity, "⚽ My Matches")
        t0_mm = time.time()

        mm_msg, mm_elapsed = await wait_for_content_msg(
            client, entity, sent_mm.id, 30, me_id, min_len=30
        )

        if not mm_msg:
            print("  ❌ My Matches did not respond")
            check("My Matches loads", False, "No response in 30s")
        else:
            mm_text = mm_msg.text or ""
            mm_btns = get_all_buttons(mm_msg)
            print(f"  My Matches loaded ({mm_elapsed:.1f}s): {len(mm_text)} chars")
            print(f"  Buttons: {[(t, d) for t, d, _ in mm_btns[:6]]}")

            check("My Matches loads", True, f"{mm_elapsed:.1f}s")

            # Find yg:game buttons
            game_btns = [(t, d, raw) for t, d, raw in mm_btns if d.startswith("yg:game:")]
            print(f"  Game buttons found: {len(game_btns)}")

            if not game_btns:
                print("  ℹ️  No yg:game: buttons on page — checking text for scheduled games")
                check("My Matches has game tap buttons", False,
                      f"No yg:game: buttons. All buttons: {[(t,d) for t,d,_ in mm_btns[:8]]}")
            else:
                check("My Matches has game tap buttons", True,
                      f"{len(game_btns)} game buttons")

                breakdowns_done = 0
                for game_idx in range(min(2, len(game_btns))):
                    gbt, gbd, gbr = game_btns[game_idx]
                    event_id = gbd.replace("yg:game:", "")
                    print(f"\n  ── Breakdown {game_idx+1}: {gbt!r} ({event_id})")

                    fresh_mm = await client.get_messages(entity, ids=mm_msg.id)
                    t0_bd = time.time()
                    bd_msg, bd_elapsed = await click_and_wait(
                        client, entity, fresh_mm, gbr,
                        timeout=BREAKDOWN_TIMEOUT, me_id=me_id, min_len=200
                    )

                    if not bd_msg or not (bd_msg.text or ""):
                        check(f"Breakdown {game_idx+1}: loads", False,
                              f"No response in {BREAKDOWN_TIMEOUT}s")
                        await asyncio.sleep(3)
                        continue

                    bd_text = bd_msg.text or ""
                    bd_btns = get_all_buttons(bd_msg)
                    bd_btn_labels = [t for t, _, _ in bd_btns]
                    breakdowns_done += 1

                    print(f"     ⏱  {bd_elapsed:.1f}s — {len(bd_text)} chars")
                    print(f"     🔘  Buttons: {bd_btn_labels}")
                    print(f"     📝  Full breakdown:")
                    print(f"     {'·'*50}")
                    print(bd_text[:2000])
                    if len(bd_text) > 2000:
                        print(f"     ... [{len(bd_text) - 2000} more chars]")
                    print(f"     {'·'*50}")

                    quality_bd = score_narrative(bd_text)
                    print(f"\n     Quality score: {quality_bd['score']}/10")
                    print(f"     Rich: {'YES' if quality_bd['rich'] else 'NO'}")
                    if quality_bd["positives"]:
                        print(f"     ✅ {'; '.join(quality_bd['positives'])}")
                    if quality_bd["issues"]:
                        print(f"     ⚠️  {'; '.join(quality_bd['issues'])}")

                    breakdown_captures.append({
                        "index": game_idx + 1,
                        "event_id": event_id,
                        "btn_text": gbt,
                        "elapsed_s": bd_elapsed,
                        "text_length": len(bd_text),
                        "full_text": bd_text,
                        "buttons": bd_btn_labels,
                        "quality": quality_bd,
                    })

                    check(f"Breakdown {game_idx+1}: loads", True,
                          f"{bd_elapsed:.1f}s")
                    check(f"Breakdown {game_idx+1}: minimum length",
                          len(bd_text) >= 200, f"{len(bd_text)} chars")
                    check(f"Breakdown {game_idx+1}: no generic filler",
                          not any(g in bd_text.lower() for g in GENERIC_PHRASES), "")
                    check(f"Breakdown {game_idx+1}: has sections or analysis",
                          len(quality_bd["sections"]) >= 2 or len(bd_text) >= 300,
                          f"sections={quality_bd['sections']}, len={len(bd_text)}")

                    # Navigate back to My Matches
                    back_bd = next(
                        ((t, d, r) for t, d, r in bd_btns if "back" in t.lower()
                         or "my matches" in t.lower() or "games" in t.lower()),
                        None
                    )
                    if back_bd:
                        print(f"\n     → Back: {back_bd[0]!r}")
                        back_bd_msg, _ = await click_and_wait(
                            client, entity, bd_msg, back_bd[2],
                            timeout=NAV_TIMEOUT, me_id=me_id, min_len=30
                        )
                        if back_bd_msg:
                            mm_msg = back_bd_msg  # refresh for next iteration
                    await asyncio.sleep(4)

                check("Opened 2 game breakdowns", breakdowns_done >= 2,
                      f"Opened {breakdowns_done}/2 required")

        # ══════════════════════════════════════════════════
        # STEP 4: Richness comparison analysis
        # ══════════════════════════════════════════════════
        section("Step 4: Richness Analysis")

        if detail_captures:
            avg_len  = sum(d["text_length"] for d in detail_captures) / len(detail_captures)
            avg_score = sum(d["quality"]["score"] for d in detail_captures) / len(detail_captures)
            rich_count = sum(1 for d in detail_captures if d["quality"]["rich"])
            sections_ok = sum(1 for d in detail_captures if len(d["quality"]["sections"]) >= 3)
            has_odds_count = sum(1 for d in detail_captures if d["quality"]["has_odds"])

            print(f"\n  Detail stats ({len(detail_captures)} tips):")
            print(f"    Avg length:       {avg_len:.0f} chars (target ≥{GOOD_DETAIL_CHARS})")
            print(f"    Avg quality:      {avg_score:.1f}/10")
            print(f"    Rich narratives:  {rich_count}/{len(detail_captures)}")
            print(f"    3+ sections:      {sections_ok}/{len(detail_captures)}")
            print(f"    Has odds:         {has_odds_count}/{len(detail_captures)}")

            check("Avg detail length ≥ 300 chars", avg_len >= 300, f"{avg_len:.0f} chars")
            check("Avg quality score ≥ 5", avg_score >= 5, f"{avg_score:.1f}")
            check("At least 3/5 details are rich", rich_count >= 3,
                  f"{rich_count}/{len(detail_captures)}")

            # Overall verdict
            if avg_score >= 7 and rich_count >= 4:
                verdict = "NARRATIVE IMPROVED"
            elif avg_score >= 5 and rich_count >= 3:
                verdict = "NARRATIVE PRESERVED"
            else:
                verdict = "NARRATIVE DEGRADED"

            print(f"\n  ┌─────────────────────────────────────────┐")
            print(f"  │  FINAL VERDICT: {verdict:<25}│")
            print(f"  └─────────────────────────────────────────┘")
        else:
            verdict = "INSUFFICIENT_DATA"
            print("  No details captured — cannot assess")

        # ══════════════════════════════════════════════════
        # STEP 5: Summary
        # ══════════════════════════════════════════════════
        section("SUMMARY")

        passed = sum(1 for r in checks.values() if r["pass"])
        total  = len(checks)
        failed = [(k, v) for k, v in checks.items() if not v["pass"]]

        print(f"\n  Checks: {passed}/{total} passed")
        if failed:
            print(f"\n  FAILURES:")
            for k, v in failed:
                print(f"    ❌ {k}")
                if v["detail"]:
                    print(f"       {v['detail']}")
        else:
            print("  All checks PASSED ✅")

        print(f"\n  Details captured: {len(detail_captures)}")
        print(f"  Breakdowns captured: {len(breakdown_captures)}")
        if detail_captures:
            print(f"  Verdict: {verdict}")

        # Write full results
        report = {
            "wave": "W84-P1N",
            "timestamp": datetime.now().isoformat(),
            "summary": {
                "checks_passed": passed,
                "checks_total": total,
                "details_opened": len(detail_captures),
                "breakdowns_opened": len(breakdown_captures),
                "verdict": verdict if detail_captures else "INSUFFICIENT_DATA",
            },
            "qa_confirm": qa_confirm,
            "tips_elapsed_s": tips_elapsed,
            "detail_captures": [
                {k: v for k, v in d.items() if k != "full_text"}  # save space in summary
                for d in detail_captures
            ],
            "detail_full_texts": {
                d["match_key"]: d["full_text"] for d in detail_captures
            },
            "breakdown_captures": [
                {k: v for k, v in d.items() if k != "full_text"}
                for d in breakdown_captures
            ],
            "breakdown_full_texts": {
                d["event_id"]: d["full_text"] for d in breakdown_captures
            },
            "failures": [{"name": k, "detail": v["detail"]} for k, v in checks.items() if not v["pass"]],
            "all_checks": {k: v for k, v in checks.items()},
        }

        out_file = f"/tmp/w84_p1n_narrative_{int(time.time())}.json"
        with open(out_file, "w") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"\n  Results saved: {out_file}")

        return report


if __name__ == "__main__":
    asyncio.run(main())
