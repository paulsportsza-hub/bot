#!/usr/bin/env python3
"""FIX-TIER-TEXT-SWEEP-01 Telethon QA — verify breakdown_gate delivers tier_lock_upsell card.

AC6: As Gold member, tap "🔒 Full AI Breakdown" on a Diamond Edge card.
     Expected: rendered image card (tier_lock_upsell.html), NOT a text bubble.

Captures screenshots into /home/paulsportsza/reports/evidence/fix_tier_text_sweep_01/.
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

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from telethon import TelegramClient
from telethon.sessions import StringSession

API_ID = int(os.getenv("TELEGRAM_API_ID", "32418601"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "95e313a8ef5b998be0515dd8328fac57")
STRING_SESSION_FILE = str(Path(__file__).parent.parent.parent / "data" / "telethon_session.string")
BOT_USERNAME = "mzansiedge_bot"

EVIDENCE_DIR = Path("/home/paulsportsza/reports/evidence/fix_tier_text_sweep_01")
EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

results: dict = {
    "wave": "FIX-TIER-TEXT-SWEEP-01",
    "started_at": datetime.utcnow().isoformat() + "Z",
    "checks": [],
}


def _session() -> StringSession:
    with open(STRING_SESSION_FILE) as f:
        return StringSession(f.read().strip())


async def _wait_for_reply(client, last_id: int, timeout: float = 25.0):
    """Poll bot dialog for any new INCOMING message (not our own) after last_id."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        async for msg in client.iter_messages(BOT_USERNAME, limit=5):
            # out=True means we sent it. We want the bot's reply (out=False).
            if msg.id > last_id and not msg.out:
                return msg
        await asyncio.sleep(0.6)
    return None


async def _send_text(client, text: str):
    last = await client.get_messages(BOT_USERNAME, limit=1)
    last_id = last[0].id if last else 0
    await client.send_message(BOT_USERNAME, text)
    # extra wait for bot processing
    await asyncio.sleep(1.0)
    msg = await _wait_for_reply(client, last_id, timeout=30.0)
    return msg


async def _click_button_matching(client, message, pattern: str, timeout: float = 30.0):
    """Click first button whose text matches regex pattern. Returns the response message."""
    if not message or not message.buttons:
        return None
    for row in message.buttons:
        for btn in row:
            if re.search(pattern, btn.text or "", re.IGNORECASE):
                last = await client.get_messages(BOT_USERNAME, limit=1)
                last_id = last[0].id if last else 0
                await btn.click()
                await asyncio.sleep(1.5)
                # Look for new replies OR same-message edits — skip our own outgoing
                deadline = time.time() + timeout
                while time.time() < deadline:
                    msgs = await client.get_messages(BOT_USERNAME, limit=5)
                    for m in msgs:
                        if m.out:
                            continue
                        if m.id > last_id:
                            return m
                        if m.id == message.id and m.edit_date:
                            return m
                    await asyncio.sleep(0.5)
                return None
    return None


async def _save_message_evidence(msg, label: str) -> dict:
    """Save photo (if any) and metadata for a message."""
    record = {
        "label": label,
        "msg_id": msg.id if msg else None,
        "is_photo": bool(msg and msg.photo),
        "is_document": bool(msg and msg.document),
        "text_sample": (msg.text or msg.message or "")[:300] if msg else "",
        "button_count": sum(len(r) for r in (msg.buttons or [])) if msg and msg.buttons else 0,
        "button_labels": [b.text for r in (msg.buttons or []) for b in r] if msg and msg.buttons else [],
    }
    if msg and msg.photo:
        path = EVIDENCE_DIR / f"{label}.jpg"
        try:
            await msg.client.download_media(msg, file=str(path))
            record["screenshot"] = str(path)
        except Exception as e:
            record["screenshot_error"] = str(e)
    return record


async def main() -> int:
    print(f"\n=== FIX-TIER-TEXT-SWEEP-01 Telethon QA ===")
    print(f"Session: {STRING_SESSION_FILE}")
    print(f"Bot: @{BOT_USERNAME}")
    print(f"Evidence: {EVIDENCE_DIR}\n")

    async with TelegramClient(_session(), API_ID, API_HASH) as client:
        # Step 1: Set tier=gold via /qa override.
        # Gold user sees Diamond edges as locked (separate AC: lock card photo) AND
        # has full access to Gold edges with a "🔒 Full AI Breakdown" button on detail
        # (the actual AC6 button — clicking triggers breakdown_gate: callback).
        print("STEP 1 — /qa set_gold")
        m1 = await _send_text(client, "/qa set_gold")
        rec = await _save_message_evidence(m1, "01_qa_set_gold")
        results["checks"].append({"step": "qa_set_gold", **rec})
        if not m1:
            print("  FAIL: no response to /qa set_gold")
            return 1
        print(f"  ok — {rec['text_sample'][:80]}")

        # Step 2: Direct deeplink to a known-cached Gold match — guarantees the
        # '🔒 Full AI Breakdown' button is rendered (only shown when W82 narrative cached).
        # Skips fragile listing/pagination iteration.
        TARGET_MATCH = os.getenv("FTTS_TARGET_MATCH", "arsenal_vs_newcastle_2026-04-25")
        print(f"\nSTEP 2 — deeplink to known-cached match: {TARGET_MATCH}")
        m2 = await _send_text(client, f"/start card_{TARGET_MATCH}")
        rec = await _save_message_evidence(m2, "02_deeplink_response")
        results["checks"].append({"step": "deeplink_to_cached_match", **rec})
        if not m2:
            print("  FAIL: no response to deeplink")
            return 1
        print(f"  ok — is_photo={rec['is_photo']}, buttons={rec['button_count']}, labels={rec['button_labels'][:6]}")

        # Step 3: Detail card already loaded by deeplink (m2 IS the detail card).
        # Find the '🔒 Full AI Breakdown' button on the detail card markup.
        m3 = m2
        bd_btn_label = None
        if m3.buttons:
            for row in m3.buttons:
                for btn in row:
                    if "Full AI Breakdown" in (btn.text or "") and "🔒" in (btn.text or ""):
                        bd_btn_label = btn.text
                        break
                if bd_btn_label:
                    break

        results["checks"].append({"step": "detail_card_breakdown_button_found", "label": bd_btn_label})
        if not bd_btn_label:
            print("  FAIL: '🔒 Full AI Breakdown' button NOT on deeplinked detail card")
            print(f"  labels seen: {rec['button_labels']}")
            results["verdict"] = "INCOMPLETE"
            results["fail_reason"] = "deeplinked_detail_missing_breakdown_button"
            return 1
        print(f"\nSTEP 3 — detail card has '🔒 Full AI Breakdown' button: {bd_btn_label!r}")

        # If we found the locked button, tap it — this is the AC6 critical assertion
        if bd_btn_label:
            print(f"\nSTEP 4 — tap '🔒 Full AI Breakdown' (the AC6 critical action)")
            m4 = await _click_button_matching(client, m3, re.escape(bd_btn_label))
            rec = await _save_message_evidence(m4, "04_breakdown_gate_response")
            results["checks"].append({"step": "breakdown_gate_response", **rec})
            if not m4:
                print("  FAIL: no response to breakdown_gate tap")
                results["verdict"] = "FAIL"
                results["fail_reason"] = "no_response_to_breakdown_gate"
                return 1

            # CRITICAL ASSERTION: must be photo (card), not text
            if rec["is_photo"]:
                print(f"  PASS — response is image card (AC6 satisfied)")
                print(f"  screenshot: {rec.get('screenshot')}")
                results["verdict"] = "PASS"
            else:
                print(f"  FAIL — response is TEXT, not card!")
                print(f"  text: {rec['text_sample'][:200]}")
                results["verdict"] = "FAIL"
                results["fail_reason"] = "breakdown_gate_returned_text_not_card"
                return 1

            # Step 5: Test back navigation
            print(f"\nSTEP 5 — tap ↩️ Back from lock card")
            m5 = await _click_button_matching(client, m4, r"↩️.*Back")
            rec = await _save_message_evidence(m5, "05_back_to_detail")
            results["checks"].append({"step": "back_to_detail", **rec})
            if m5 and rec["is_photo"]:
                print(f"  ok — back returned to detail card")
            else:
                print(f"  WARN — back navigation didn't return to a photo card")
                results["back_warn"] = True

        # Step 6: cleanup
        print(f"\nSTEP 6 — /qa reset")
        m6 = await _send_text(client, "/qa reset")
        rec = await _save_message_evidence(m6, "06_qa_reset")
        results["checks"].append({"step": "qa_reset", **rec})

    results["finished_at"] = datetime.utcnow().isoformat() + "Z"
    if "verdict" not in results:
        results["verdict"] = "INCOMPLETE"
        results["fail_reason"] = "could_not_locate_locked_breakdown_button"

    # Save report
    report_path = EVIDENCE_DIR / "telethon_qa_report.json"
    report_path.write_text(json.dumps(results, indent=2, default=str))
    print(f"\n=== Report: {report_path} ===")
    print(f"=== Verdict: {results['verdict']} ===")
    return 0 if results["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
