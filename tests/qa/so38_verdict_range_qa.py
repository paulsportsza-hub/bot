#!/usr/bin/env python3
"""SO #38 — Telethon QA: Verify verdict_html 100–260 char range post-deploy.

FIX-NARRATIVE-CACHE-SCHEMA-200-260

Fetches the last 5 Edge cards from @MzansiEdgeAlerts (post-deploy priority),
downloads card images, runs Claude-vision OCR (ocr_card), then asserts:
  - verdict_in_range       : verdict_char_count in [100, 260]
  - not_stub_shape         : verdict does not match '— ? at 0.00.'
  - teams_populated        : home_team + away_team non-empty, not HOME/AWAY
  - tier_badge_present     : tier badge in allowed set

Evidence saved to: /home/paulsportsza/reports/evidence/so38_verdict_range_qa/
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import datetime
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
STRING_SESSION_FILE = str(Path(__file__).parent.parent.parent / "data" / "telethon_qa_session.string")
ALERTS_CHANNEL_ID = int(os.getenv("TELEGRAM_ALERTS_CHANNEL_ID", "-1003789410835"))

EVIDENCE_DIR = Path("/home/paulsportsza/reports/evidence/so38_verdict_range_qa")
EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

# Deploy timestamp: bot restarted at 05:42 SAST = 03:42 UTC on 2026-04-23
DEPLOY_TS = datetime.datetime(2026, 4, 23, 3, 42, 0, tzinfo=datetime.timezone.utc)

ASSERTION_NAMES = [
    "verdict_in_range",
    "not_stub_shape",
    "teams_populated",
    "tier_badge_present",
]

results: list[dict] = []


def _session() -> StringSession:
    with open(STRING_SESSION_FILE) as f:
        s = f.read().strip()
    if not s:
        raise RuntimeError(f"Empty session: {STRING_SESSION_FILE}")
    return StringSession(s)


async def run_qa() -> int:
    client = TelegramClient(_session(), API_ID, API_HASH)
    await client.start()

    print(f"\n[SO#38] Connecting to channel ID {ALERTS_CHANNEL_ID}...")
    channel = await client.get_entity(ALERTS_CHANNEL_ID)

    # Collect up to 15 recent messages to find 5 with card images
    card_messages = []
    async for msg in client.iter_messages(channel, limit=50):
        if msg.photo or msg.document:
            card_messages.append(msg)
        if len(card_messages) >= 5:
            break

    post_deploy = [m for m in card_messages if m.date >= DEPLOY_TS]
    pre_deploy = [m for m in card_messages if m.date < DEPLOY_TS]

    print(f"[SO#38] Found {len(card_messages)} card messages: "
          f"{len(post_deploy)} post-deploy, {len(pre_deploy)} pre-deploy")

    # Use post-deploy first, pad with pre-deploy if needed
    to_test = (post_deploy + pre_deploy)[:5]
    if not to_test:
        print("[SO#38] ERROR: No card messages found in channel")
        return 1

    for i, msg in enumerate(to_test, 1):
        label = f"card_{i:02d}_msg{msg.id}"
        img_path = EVIDENCE_DIR / f"{label}.jpg"
        txt_path = EVIDENCE_DIR / f"{label}_text.txt"
        ocr_path = EVIDENCE_DIR / f"{label}_ocr.json"
        result_path = EVIDENCE_DIR / f"{label}_assertions.json"

        age = "POST-deploy" if msg.date >= DEPLOY_TS else "PRE-deploy"
        print(f"\n[{i}/5] msg_id={msg.id} date={msg.date} [{age}]")

        # Download image
        try:
            await client.download_media(msg, file=str(img_path))
            print(f"  Downloaded: {img_path.name}")
        except Exception as e:
            print(f"  Download failed: {e}")
            results.append({"card": label, "error": f"download_failed: {e}"})
            continue

        # Save caption/text
        caption = getattr(msg, "message", "") or getattr(msg, "text", "") or ""
        txt_path.write_text(caption[:2000])

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
            print(f"  OCR: verdict={ocr.verdict_char_count}c, "
                  f"home={ocr.home_team!r}, away={ocr.away_team!r}, "
                  f"tier={ocr.tier_badge!r}")
        except Exception as e:
            print(f"  OCR failed: {e}")
            results.append({"card": label, "error": f"ocr_failed: {e}"})
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
            mark = "✓" if res == "PASS" else "✗"
            print(f"  {mark} {aname}: {res}")

        result_record = {
            "card": label,
            "msg_id": msg.id,
            "date": msg.date.isoformat(),
            "age": age,
            "verdict_char_count": ocr.verdict_char_count,
            "verdict_text_sample": ocr.verdict_text[:120],
            "home_team": ocr.home_team,
            "away_team": ocr.away_team,
            "tier_badge": ocr.tier_badge,
            "assertions": assertion_results,
            "all_pass": all(v == "PASS" for v in assertion_results.values()),
        }
        results.append(result_record)
        result_path.write_text(json.dumps(result_record, indent=2))

    await client.disconnect()

    # Summary
    total = len(results)
    passed = sum(1 for r in results if r.get("all_pass"))
    verdict_in_range_pass = sum(
        1 for r in results
        if r.get("assertions", {}).get("verdict_in_range") == "PASS"
    )

    print(f"\n{'='*60}")
    print(f"SO#38 RESULTS: {passed}/{total} cards all-assertions PASS")
    print(f"verdict_in_range (100-260): {verdict_in_range_pass}/{total} PASS")

    # Write summary JSON
    summary = {
        "run_ts": datetime.datetime.utcnow().isoformat(),
        "deploy_ts": DEPLOY_TS.isoformat(),
        "total_cards": total,
        "all_assertions_pass": passed,
        "verdict_in_range_pass": verdict_in_range_pass,
        "cards": results,
    }
    (EVIDENCE_DIR / "summary.json").write_text(json.dumps(summary, indent=2))
    print(f"Evidence saved to: {EVIDENCE_DIR}")

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(run_qa()))
