#!/usr/bin/env python3
"""SO #38 — BUILD-PREGEN-WINDOW-VERIFY-01 Telethon QA
Watches MzansiEdge Alerts channel over 4 checkpoints (T+15, T+30, T+45, T+60 min).
At each checkpoint: retrieve 3 most recent cards, download, run OCR, run 4 assertions.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import datetime
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from telethon import TelegramClient
from telethon.sessions import StringSession

from tests.qa.vision_ocr import ocr_card, CardOCR
from tests.qa.card_assertions import (
    assert_verdict_in_range,
    assert_not_stub_shape,
    assert_teams_populated,
    assert_tier_badge_present,
)

API_ID = int(os.getenv("TELEGRAM_API_ID", "32418601"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "95e313a8ef5b998be0515dd8328fac57")
STRING_SESSION_FILE = str(Path(__file__).parent.parent.parent / "data" / "telethon_session.string")
ALERTS_CHANNEL_ID = int(os.getenv("TELEGRAM_ALERTS_CHANNEL_ID", "-1003789410835"))

EVIDENCE_DIR = Path("/home/paulsportsza/reports/evidence/build_pregen_window_verify_01")
EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

CHECKPOINTS_MINUTES = [15, 30, 45, 60]
CARDS_PER_CHECKPOINT = 3

ASSERTION_NAMES = [
    "verdict_in_range",
    "not_stub_shape",
    "teams_populated",
    "tier_badge_present",
]

all_results: list[dict] = []
checkpoint_summaries: list[dict] = []


def _session() -> StringSession:
    with open(STRING_SESSION_FILE) as f:
        s = f.read().strip()
    if not s:
        raise RuntimeError(f"Empty session: {STRING_SESSION_FILE}")
    return StringSession(s)


async def check_cards(client, channel, checkpoint_label: str, checkpoint_num: int) -> dict:
    print(f"\n{'='*60}")
    print(f"CHECKPOINT {checkpoint_label} — {datetime.datetime.utcnow().isoformat()}Z")
    print(f"{'='*60}")

    card_messages = []
    async for msg in client.iter_messages(channel, limit=50):
        if msg.photo or msg.document:
            card_messages.append(msg)
        if len(card_messages) >= CARDS_PER_CHECKPOINT:
            break

    card_count = len(card_messages)
    print(f"  card_count={card_count} (need > 0)")

    if card_count == 0:
        print(f"  FAIL: card_count=0 at checkpoint {checkpoint_label}")
        return {
            "checkpoint": checkpoint_label,
            "timestamp": datetime.datetime.utcnow().isoformat(),
            "card_count": 0,
            "cards": [],
            "card_count_pass": False,
        }

    cards_evidence = []
    for i, msg in enumerate(card_messages, 1):
        label = f"cp{checkpoint_num:02d}_{checkpoint_label}_card{i:02d}_msg{msg.id}"
        img_path = EVIDENCE_DIR / f"{label}.jpg"
        ocr_path = EVIDENCE_DIR / f"{label}_ocr.json"
        result_path = EVIDENCE_DIR / f"{label}_assertions.json"

        print(f"\n  Card [{i}/{CARDS_PER_CHECKPOINT}] msg_id={msg.id} date={msg.date.isoformat()}")

        # Download image
        try:
            await client.download_media(msg, file=str(img_path))
            print(f"    Downloaded: {img_path.name}")
        except Exception as e:
            print(f"    Download FAILED: {e}")
            cards_evidence.append({"card": label, "error": f"download_failed: {e}"})
            continue

        # Run OCR
        try:
            ocr = ocr_card(img_path)
            ocr_path.write_text(json.dumps({
                "verdict_text": ocr.verdict_text,
                "verdict_char_count": ocr.verdict_char_count,
                "home_team": ocr.home_team,
                "away_team": ocr.away_team,
                "tier_badge": ocr.tier_badge,
                "button_count": ocr.button_count,
                "button_labels": ocr.button_labels,
            }, indent=2))
            print(f"    OCR: verdict={ocr.verdict_char_count}c, "
                  f"home={ocr.home_team!r}, away={ocr.away_team!r}, "
                  f"tier={ocr.tier_badge!r}")
        except Exception as e:
            print(f"    OCR FAILED: {e}")
            cards_evidence.append({"card": label, "error": f"ocr_failed: {e}"})
            continue

        # Run 4 assertions
        assertion_results: dict[str, str] = {}
        for aname in ASSERTION_NAMES:
            try:
                if aname == "verdict_in_range":
                    assert_verdict_in_range(ocr, min_chars=100, max_chars=260)
                elif aname == "not_stub_shape":
                    assert_not_stub_shape(ocr)
                elif aname == "teams_populated":
                    assert_teams_populated(ocr)
                elif aname == "tier_badge_present":
                    assert_tier_badge_present(ocr)
                assertion_results[aname] = "PASS"
            except AssertionError as ae:
                assertion_results[aname] = f"FAIL: {ae}"

        for aname, res in assertion_results.items():
            mark = "PASS" if res == "PASS" else "FAIL"
            print(f"    [{mark}] {aname}: {res[:80]}")

        record = {
            "card": label,
            "msg_id": msg.id,
            "date": msg.date.isoformat(),
            "verdict_char_count": ocr.verdict_char_count,
            "verdict_text_sample": ocr.verdict_text[:120],
            "home_team": ocr.home_team,
            "away_team": ocr.away_team,
            "tier_badge": ocr.tier_badge,
            "assertions": assertion_results,
            "all_pass": all(v == "PASS" for v in assertion_results.values()),
        }
        cards_evidence.append(record)
        result_path.write_text(json.dumps(record, indent=2))

    passes = sum(1 for c in cards_evidence if c.get("all_pass"))
    total = len(cards_evidence)
    print(f"\n  Checkpoint {checkpoint_label} summary: {passes}/{total} cards all-pass")

    return {
        "checkpoint": checkpoint_label,
        "timestamp": datetime.datetime.utcnow().isoformat(),
        "card_count": card_count,
        "cards": cards_evidence,
        "card_count_pass": card_count > 0,
        "all_assertions_pass": passes == total and total > 0,
    }


async def run_qa() -> int:
    start_time = time.time()

    client = TelegramClient(_session(), API_ID, API_HASH)
    await client.start()

    print(f"\n[SO#38-VERIFY] Connecting to channel ID {ALERTS_CHANNEL_ID}...")
    channel = await client.get_entity(ALERTS_CHANNEL_ID)
    print(f"[SO#38-VERIFY] Connected. Start time: {datetime.datetime.utcnow().isoformat()}Z")
    print(f"[SO#38-VERIFY] Checkpoints at: {CHECKPOINTS_MINUTES} minutes")

    for cp_idx, cp_min in enumerate(CHECKPOINTS_MINUTES, 1):
        elapsed = (time.time() - start_time) / 60.0
        wait_min = cp_min - elapsed
        if wait_min > 0:
            print(f"\n[SO#38-VERIFY] Waiting {wait_min:.1f} min for checkpoint T+{cp_min}...")
            await asyncio.sleep(wait_min * 60)

        cp_label = f"T+{cp_min}min"
        result = await check_cards(client, channel, cp_label, cp_idx)
        checkpoint_summaries.append(result)

    await client.disconnect()

    # Final summary
    print(f"\n{'='*60}")
    print("FINAL SUMMARY — BUILD-PREGEN-WINDOW-VERIFY-01 SO#38")
    print(f"{'='*60}")
    all_card_count_pass = all(c["card_count_pass"] for c in checkpoint_summaries)
    all_assertions_pass = all(c.get("all_assertions_pass", False) for c in checkpoint_summaries)

    for cs in checkpoint_summaries:
        cc_status = "PASS" if cs["card_count_pass"] else "FAIL"
        a_status = "PASS" if cs.get("all_assertions_pass") else "FAIL/PARTIAL"
        print(f"  {cs['checkpoint']}: card_count={cs['card_count']} [{cc_status}] | assertions [{a_status}]")

    print(f"\ncard_count > 0 at all 4 checkpoints: {'PASS' if all_card_count_pass else 'FAIL'}")
    print(f"All 4 assertions PASS at all checkpoints: {'PASS' if all_assertions_pass else 'FAIL/PARTIAL'}")

    # Write JSON evidence
    summary_path = EVIDENCE_DIR / "summary.json"
    summary_path.write_text(json.dumps({
        "wave": "BUILD-PREGEN-WINDOW-VERIFY-01",
        "so38": True,
        "checkpoints": checkpoint_summaries,
        "all_card_count_pass": all_card_count_pass,
        "all_assertions_pass": all_assertions_pass,
    }, indent=2))
    print(f"\n[SO#38-VERIFY] Evidence saved to: {EVIDENCE_DIR}/")

    return 0 if (all_card_count_pass and all_assertions_pass) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(run_qa()))
