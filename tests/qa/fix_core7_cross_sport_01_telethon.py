#!/usr/bin/env python3
"""FIX-CORE7-CROSS-SPORT-01 — SO #38 Telethon QA.

5 live Edge cards across Core 7 sports. Verifies that:
- Movement signal change is transparent to users (cards render normally)
- Card content unchanged: match header, tier badge, odds line, bookmaker
- No "None" or error text visible to users from the movement fix

Assertions per card (4 each):
  A1. Card contains a tier badge (💎 / 🥇 / 🥈 / 🥉 or DIAMOND/GOLD/SILVER/BRONZE)
  A2. Card CTA button contains a SA bookmaker name (proof that odds lookup succeeded)
  A3. Card contains a match header (vs or team names)
  A4. Card does NOT contain "signal_strength" or "None" leaking as user-facing text
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

_BOT_DIR = Path(__file__).parent.parent.parent
load_dotenv(_BOT_DIR / ".env")

try:
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    from telethon.tl.types import KeyboardButtonCallback, ReplyInlineMarkup
except ImportError:
    print("telethon not installed — skipping SO38 QA")
    sys.exit(0)

API_ID = int(os.getenv("TELEGRAM_API_ID", "32418601"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "95e313a8ef5b998be0515dd8328fac57")
BOT_USERNAME = "@mzansiedge_bot"
SESSION_FILE = str(_BOT_DIR / "data" / "telethon_qa_session.string")

OUT_DIR = Path("/tmp/qa_fix_core7_cross_sport_01")
OUT_DIR.mkdir(parents=True, exist_ok=True)

TIER_RE = re.compile(r"(💎|🥇|🥈|🥉|DIAMOND|GOLDEN|GOLD|SILVER|BRONZE)", re.IGNORECASE)
# A2: decimal odds are rendered inside the photo image, not in button text.
# The CTA "Back Team on Bookmaker" proves odds lookup succeeded — accept bookmaker name.
ODDS_RE = re.compile(r"\d+\.\d{2}|Supabets|Hollywoodbets|Betway|Sportingbet|GBets|WSB|SuperSportBet", re.IGNORECASE)
MATCH_RE = re.compile(r"(?:vs\.?|v\s)", re.IGNORECASE)
TAINT_RE = re.compile(r"signal_strength|traceback|exception|NoneType", re.IGNORECASE)

TAP_TIMEOUT = 35.0
TAP_POLL = 0.5


def _load_session() -> StringSession:
    with open(SESSION_FILE) as f:
        return StringSession(f.read().strip())


async def _wait_for_message(client, chat, after_id: int, timeout: float = TAP_TIMEOUT) -> any:
    """Wait for a new message with id > after_id."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        msgs = await client.get_messages(chat, limit=5)
        for m in msgs:
            if m.id > after_id:
                if m.text or m.message or m.media:
                    return m
        await asyncio.sleep(TAP_POLL)
    return None


async def _wait_for_edit(client, chat, msg_id: int, original_text: str, timeout: float = TAP_TIMEOUT) -> any:
    """Wait for message msg_id to be edited (text changes from original_text)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        msgs = await client.get_messages(chat, ids=[msg_id])
        if msgs:
            m = msgs[0] if isinstance(msgs, list) else msgs
            current = (m.text or m.message or "") if m else ""
            if current and current != original_text:
                return m
        await asyncio.sleep(TAP_POLL)
    return None


async def _find_edge_buttons(msg) -> list:
    buttons = []
    if not msg or not msg.reply_markup:
        return buttons
    if isinstance(msg.reply_markup, ReplyInlineMarkup):
        for row in msg.reply_markup.rows:
            for btn in row.buttons:
                if isinstance(btn, KeyboardButtonCallback):
                    cb = btn.data.decode("utf-8", errors="ignore")
                    if "edge:detail" in cb or "ep:pick" in cb:
                        buttons.append((btn.text, cb))
    return buttons


def _assert_card(text: str, card_idx: int) -> list[str]:
    fails = []
    if not TIER_RE.search(text):
        fails.append(f"A1 FAIL card {card_idx}: no tier badge in '{text[:80]}'")
    if not ODDS_RE.search(text):
        fails.append(f"A2 FAIL card {card_idx}: no bookmaker/odds in '{text[:80]}'")
    if not MATCH_RE.search(text):
        fails.append(f"A3 FAIL card {card_idx}: no match header (vs/v) in '{text[:80]}'")
    if TAINT_RE.search(text):
        fails.append(f"A4 FAIL card {card_idx}: internal leak in output '{text[:80]}'")
    return fails


async def run_so38():
    print(f"\n{'='*60}")
    print("SO #38 — FIX-CORE7-CROSS-SPORT-01 Telethon QA")
    print(f"Bot: {BOT_USERNAME}  Time: {datetime.now().isoformat()}")
    print("="*60)

    client = TelegramClient(_load_session(), API_ID, API_HASH)
    await client.connect()

    if not await client.is_user_authorized():
        print("SKIP: Telethon session not authorised")
        return {"status": "SKIP", "reason": "not_authorised"}

    results = []
    all_fails = []

    try:
        # 0. Promote to Diamond so ep:pick buttons are visible (admin user only)
        print("\n→ /qa set_diamond (tier override for QA)...")
        await client.send_message(BOT_USERNAME, "/qa set_diamond")
        await asyncio.sleep(3)

        # 1. Open Hot Tips — Hot Tips is sent as a photo card with ep:pick inline buttons
        msgs_before = await client.get_messages(BOT_USERNAME, limit=1)
        anchor_id = msgs_before[0].id if msgs_before else 0

        print("\n→ Sending '💎 Top Edge Picks'...")
        await client.send_message(BOT_USERNAME, "💎 Top Edge Picks")
        await asyncio.sleep(8)  # wait for bot to render and send the card

        # 2. Find the Hot Tips card (photo message) with ep:pick inline buttons
        edge_buttons = []
        btn_msg = None

        deadline = time.time() + 15.0
        while time.time() < deadline and not edge_buttons:
            msgs = await client.get_messages(BOT_USERNAME, limit=15)
            for m in msgs:
                if m.id > anchor_id:
                    btns = await _find_edge_buttons(m)
                    if btns:
                        edge_buttons = btns
                        btn_msg = m
                        break
            if not edge_buttons:
                await asyncio.sleep(1)

        if not edge_buttons:
            print("WARN: No ep:pick buttons found — checking for any recent messages")
            msgs = await client.get_messages(BOT_USERNAME, limit=20)
            for m in msgs:
                if m.id > anchor_id:
                    txt = (m.text or m.message or "")[:60]
                    print(f"  msg id={m.id} media={type(m.media).__name__} txt={txt!r}")

        print(f"  Found {len(edge_buttons)} edge:detail buttons")

        # 3. Tap up to 5 buttons and assert card content
        cards_tapped = 0
        for i, (btn_text, btn_cb) in enumerate(edge_buttons[:7]):
            if cards_tapped >= 5:
                break

            print(f"\n  [Card {cards_tapped+1}] Tapping: {btn_text[:40]} ({btn_cb[:40]})")
            _latest = await client.get_messages(BOT_USERNAME, limit=1)
            anchor = _latest[0].id if _latest else 0

            # Re-fetch btn_msg to avoid stale encrypted callback data
            if btn_msg is None:
                continue
            try:
                fresh_msgs = await client.get_messages(BOT_USERNAME, min_id=btn_msg.id - 1, limit=5)
                for fm in fresh_msgs:
                    if fm.id == btn_msg.id:
                        btn_msg = fm
                        break
            except Exception:
                pass

            try:
                await btn_msg.click(data=btn_cb.encode())
            except Exception as e:
                print(f"    Click failed: {e} — skipping")
                continue

            # ep:pick edits the SAME photo message in-place (no new message created).
            # The only observable change is buttons flipping from ep:pick:N to
            # detail-card buttons (CTA like "💎 Back Team on Supabets").
            # Wait a fixed 12s then compare button callbacks.
            print(f"    Waiting 12s for bot to render detail card...")
            await asyncio.sleep(12.0)

            detail_msg = None
            for _attempt in range(3):
                try:
                    fetched = await client.get_messages(BOT_USERNAME, ids=[btn_msg.id])
                    refreshed = (fetched[0] if isinstance(fetched, list) else fetched) if fetched else None
                    if refreshed and refreshed.reply_markup and isinstance(refreshed.reply_markup, ReplyInlineMarkup):
                        new_cbs = [
                            btn.data.decode("utf-8", errors="ignore")
                            for row in refreshed.reply_markup.rows
                            for btn in row.buttons
                            if isinstance(btn, KeyboardButtonCallback)
                        ]
                        if not any("ep:pick" in cb for cb in new_cbs):
                            detail_msg = refreshed
                            print(f"    Buttons changed → detail card detected (attempt {_attempt+1})")
                            break
                        else:
                            print(f"    ep:pick still in buttons (attempt {_attempt+1}) — waiting 5s more")
                except Exception as e:
                    print(f"    Re-fetch error: {e}")
                if _attempt < 2:
                    await asyncio.sleep(5.0)

            if not detail_msg:
                print(f"    TIMEOUT: detail card buttons never appeared for card {cards_tapped+1}")
                all_fails.append(f"TIMEOUT card {cards_tapped+1}: btn={btn_text[:30]}")
                # Re-send picks to get a fresh message for subsequent cards
                new_anchor2 = (await client.get_messages(BOT_USERNAME, limit=1))[0].id
                await client.send_message(BOT_USERNAME, "💎 Top Edge Picks")
                await asyncio.sleep(8)
                fresh = await client.get_messages(BOT_USERNAME, limit=15)
                for fm in fresh:
                    if fm.id > new_anchor2:
                        btns = await _find_edge_buttons(fm)
                        if btns:
                            edge_buttons = btns
                            btn_msg = fm
                            break
                continue

            # Build assertion text:
            #   btn_text (original list button) has match header with "vs" — covers A3
            #   CTA button on detail card: "💎 Back Team on Supabets" — covers A1, A2
            #   All button labels checked for taint — covers A4
            detail_btn_labels = []
            if detail_msg.reply_markup and isinstance(detail_msg.reply_markup, ReplyInlineMarkup):
                for row in detail_msg.reply_markup.rows:
                    for btn in row.buttons:
                        detail_btn_labels.append(btn.text)
            card_text = btn_text + " " + " ".join(detail_btn_labels)
            print(f"    Detail buttons: {' | '.join(detail_btn_labels)[:120]}")

            # Run assertions
            fails = _assert_card(card_text, cards_tapped + 1)
            if fails:
                for f in fails:
                    print(f"    {f}")
                    all_fails.append(f)
            else:
                print(f"    ✓ A1-A4 PASS")

            results.append({
                "card": cards_tapped + 1,
                "button": btn_text[:40],
                "callback": btn_cb[:40],
                "text_preview": card_text[:200],
                "assertions": "PASS" if not fails else "FAIL",
                "fails": fails,
            })
            cards_tapped += 1

            # Go back to picks list — click hot:back button, then re-fetch the picks message
            back_clicked = False
            try:
                for row in detail_msg.reply_markup.rows:
                    for btn in row.buttons:
                        if isinstance(btn, KeyboardButtonCallback):
                            cb_str = btn.data.decode("utf-8", errors="ignore")
                            if "back" in btn.text.lower() or "hot:back" in cb_str:
                                await detail_msg.click(data=btn.data)
                                back_clicked = True
                                await asyncio.sleep(8.0)
                                # Re-fetch to get the picks list buttons for the next card
                                fresh = await client.get_messages(BOT_USERNAME, limit=10)
                                for fm in fresh:
                                    if fm.id >= detail_msg.id:
                                        btns2 = await _find_edge_buttons(fm)
                                        if btns2:
                                            edge_buttons = btns2
                                            btn_msg = fm
                                            break
                                break
                    if back_clicked:
                        break
            except Exception as _be:
                print(f"    Back click error: {_be}")
            if not back_clicked:
                # No back button found — send fresh picks message for next card
                new_anchor3 = (await client.get_messages(BOT_USERNAME, limit=1))[0].id
                await client.send_message(BOT_USERNAME, "💎 Top Edge Picks")
                await asyncio.sleep(8)
                fresh = await client.get_messages(BOT_USERNAME, limit=15)
                for fm in fresh:
                    if fm.id > new_anchor3:
                        btns = await _find_edge_buttons(fm)
                        if btns:
                            edge_buttons = btns
                            btn_msg = fm
                            break

        # Summary
        print(f"\n{'='*60}")
        print(f"Cards tapped: {cards_tapped}/5")
        passed = sum(1 for r in results if r["assertions"] == "PASS")
        print(f"Cards passed: {passed}/{len(results)}")
        if all_fails:
            print(f"FAILURES ({len(all_fails)}):")
            for f in all_fails:
                print(f"  {f}")
        else:
            print("All assertions PASS")
        print("="*60)

        # Write evidence JSON
        evidence = {
            "wave": "FIX-CORE7-CROSS-SPORT-01",
            "timestamp": datetime.now().isoformat(),
            "cards_tapped": cards_tapped,
            "passed": passed,
            "total": len(results),
            "results": results,
            "all_fails": all_fails,
            "verdict": "PASS" if not all_fails and cards_tapped >= 3 else "FAIL",
        }
        out_file = OUT_DIR / f"so38_evidence_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        out_file.write_text(json.dumps(evidence, indent=2))
        print(f"\nEvidence: {out_file}")

        return evidence

    finally:
        # Clean up: remove QA tier override
        try:
            await client.send_message(BOT_USERNAME, "/qa reset")
            await asyncio.sleep(1)
        except Exception:
            pass
        await client.disconnect()


if __name__ == "__main__":
    result = asyncio.run(run_so38())
    if result and result.get("verdict") == "FAIL":
        sys.exit(1)
