#!/usr/bin/env python3
"""BUILD-TIER-COPY-01 Visual QA — 3 required screenshots."""
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

SESSION_FILE = "/home/paulsportsza/bot/data/telethon_session.string"
BOT_USERNAME = "mzansiedge_bot"
WAIT = 30
SCREENSHOTS_DIR = "/home/paulsportsza/reports/qa-tier-copy-01"

os.makedirs(SCREENSHOTS_DIR, exist_ok=True)

with open(SESSION_FILE) as f:
    SESSION_STR = f.read().strip()

API_ID = int(os.environ["TELEGRAM_API_ID"])
API_HASH = os.environ["TELEGRAM_API_HASH"]

results = []


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def record(name, passed, detail=""):
    results.append((name, passed, detail))
    status = "PASS" if passed else "FAIL"
    log(f"  [{status}] {name}" + (f": {detail[:200]}" if detail else ""))


async def get_latest_id(client):
    msgs = await client.get_messages(BOT_USERNAME, limit=1)
    return msgs[0].id if msgs else 0


async def wait_photo(client, after_id, timeout=WAIT):
    deadline = time.time() + timeout
    while time.time() < deadline:
        msgs = await client.get_messages(BOT_USERNAME, limit=8)
        for m in msgs:
            if m.id > after_id and m.media and isinstance(m.media, MessageMediaPhoto):
                return m
        await asyncio.sleep(1.0)
    return None


async def wait_text(client, after_id, timeout=WAIT):
    deadline = time.time() + timeout
    while time.time() < deadline:
        msgs = await client.get_messages(BOT_USERNAME, limit=5)
        for m in msgs:
            if m.id > after_id and m.text:
                return m
        await asyncio.sleep(0.8)
    return None


async def run_qa():
    async with TelegramClient(StringSession(SESSION_STR), API_ID, API_HASH) as client:
        log("Connected. Starting BUILD-TIER-COPY-01 visual QA.")

        # ── 1: sub_plans.html card (Bronze user sees all 3 plans) ──────────────
        log("== Test 1: sub_plans.html card ==")
        await client.send_message(BOT_USERNAME, "/qa set_bronze")
        await asyncio.sleep(2)
        last = await get_latest_id(client)
        await client.send_message(BOT_USERNAME, "/subscribe")
        card = await wait_photo(client, last)
        if card:
            path = f"{SCREENSHOTS_DIR}/1_sub_plans.jpg"
            await client.download_media(card, path)
            log(f"  Saved: {path}")
            record("sub_plans_card_received", True, "Photo card received")
        else:
            record("sub_plans_card_received", False, "No photo card within timeout")

        # ── 2: sub_upgrade_diamond_max.html card (Diamond user /upgrade) ────────
        log("== Test 2: sub_upgrade_diamond_max.html card ==")
        await client.send_message(BOT_USERNAME, "/qa set_diamond")
        await asyncio.sleep(3)
        last = await get_latest_id(client)
        await client.send_message(BOT_USERNAME, "/upgrade")
        card = await wait_photo(client, last)
        if card:
            path = f"{SCREENSHOTS_DIR}/2_sub_upgrade_diamond_max.jpg"
            await client.download_media(card, path)
            log(f"  Saved: {path}")
            record("diamond_max_card_received", True, "Photo card received")
        else:
            record("diamond_max_card_received", False, "No photo card within timeout")

        # ── 3: Bronze → Diamond locked-edge nudge (via upgrade command) ─────────
        log("== Test 3: Bronze locked-edge nudge via /upgrade ==")
        await client.send_message(BOT_USERNAME, "/qa set_bronze")
        await asyncio.sleep(2)
        last = await get_latest_id(client)
        # As a Bronze user, /upgrade shows a card comparing Gold vs Diamond
        # The nudge text fires when Bronze hits a Diamond edge — verify via text
        await client.send_message(BOT_USERNAME, "/upgrade")
        card = await wait_photo(client, last)
        if card:
            path = f"{SCREENSHOTS_DIR}/3_bronze_upgrade_card.jpg"
            await client.download_media(card, path)
            log(f"  Saved: {path}")
            record("bronze_upgrade_card_received", True, "Bronze upgrade card (sub_upgrade_bronze.html)")
        else:
            # fallback: check text response
            msg = await wait_text(client, last, timeout=5)
            if msg:
                text = msg.text or ""
                log(f"  Text response: {text[:200]}")
                record("bronze_upgrade_card_received", False, f"Got text instead of card: {text[:80]}")
            else:
                record("bronze_upgrade_card_received", False, "No response within timeout")

        # Also check the tier_gate nudge text directly via Python
        log("== Test 3b: tier_gate nudge copy verification ==")
        try:
            from tier_gate import get_upgrade_message
            bronze_diamond = get_upgrade_message("bronze", context="diamond_edge")
            gold_diamond = get_upgrade_message("gold")

            pillars = [
                "Every edge unlocked",
                "Full AI Breakdown",
                "Personalised alerts",
            ]
            bronze_ok = all(p in bronze_diamond for p in pillars)
            gold_ok = all(p in gold_diamond for p in pillars)

            record("bronze_diamond_nudge_has_pillars", bronze_ok,
                   "All 3 pillars present" if bronze_ok else f"Missing: {[p for p in pillars if p not in bronze_diamond]}")
            record("gold_diamond_nudge_has_pillars", gold_ok,
                   "All 3 pillars present" if gold_ok else f"Missing: {[p for p in pillars if p not in gold_diamond]}")

            log(f"\nBronze→Diamond nudge:\n{bronze_diamond}\n")
            log(f"Gold→Diamond nudge:\n{gold_diamond}\n")

            # Save for record
            with open(f"{SCREENSHOTS_DIR}/3b_bronze_diamond_nudge.txt", "w") as f:
                f.write(bronze_diamond)
            with open(f"{SCREENSHOTS_DIR}/3c_gold_diamond_nudge.txt", "w") as f:
                f.write(gold_diamond)

        except Exception as e:
            record("nudge_copy_check", False, str(e))

        # ── Reset QA tier ──────────────────────────────────────────────────────
        await client.send_message(BOT_USERNAME, "/qa reset")
        await asyncio.sleep(1)

    # ── Summary ────────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("BUILD-TIER-COPY-01 QA RESULTS")
    print("=" * 60)
    passed = sum(1 for _, p, _ in results if p)
    total = len(results)
    for name, p, detail in results:
        status = "✅ PASS" if p else "❌ FAIL"
        print(f"  {status}  {name}" + (f"\n         {detail}" if detail else ""))
    print(f"\n{passed}/{total} passed")
    print(f"Screenshots saved to: {SCREENSHOTS_DIR}/")
    return passed == total


if __name__ == "__main__":
    ok = asyncio.run(run_qa())
    sys.exit(0 if ok else 1)
