#!/usr/bin/env python3
"""W84-ACC1 Live Validation — Account Truth, QA Reset, View Accounting.

Tests:
1. Entitlement truth: subscription_status=active + plan_code=stitch_premium → shows Gold tier
2. /qa reset non-destructive: paid user's real tier preserved after QA reset
3. View accounting idempotency: same fixture same day = 1 view counted
4. View accounting integrity: different fixture = additional view counted
"""
from __future__ import annotations

import asyncio
import os
import sys
import sqlite3
import time
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

# ── DB access ──────────────────────────────────────────────────────────
BOT_DB = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "mzansiedge.db")
ODDS_DB = "/home/paulsportsza/scrapers/odds.db"

# ── Telethon ──────────────────────────────────────────────────────────
from telethon import TelegramClient
from telethon.sessions import StringSession

API_ID   = int(os.getenv("TELEGRAM_API_ID", "32418601"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "95e313a8ef5b998be0515dd8328fac57")
BOT_USERNAME = "@mzansiedge_bot"
STRING_SESSION_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "telethon_session.string")

SAST = timezone(timedelta(hours=2))

results: dict = {}
failures: list[str] = []


def load_session():
    if os.path.exists(STRING_SESSION_FILE):
        with open(STRING_SESSION_FILE) as f:
            s = f.read().strip()
        if s:
            return StringSession(s)
    return StringSession()


def check(name: str, condition: bool, detail: str = ""):
    status = "✅ PASS" if condition else "❌ FAIL"
    print(f"  {status} — {name}")
    if detail:
        print(f"     {detail}")
    results[name] = {"pass": condition, "detail": detail}
    if not condition:
        failures.append(name)
    return condition


def section(title: str):
    print(f"\n{'─'*60}")
    print(f"  {title}")
    print(f"{'─'*60}")


async def wait_response(client, entity, after_id: int, timeout: float, me_id: int):
    deadline = time.time() + timeout
    while time.time() < deadline:
        await asyncio.sleep(0.8)
        msgs = await client.get_messages(entity, limit=6)
        for m in msgs:
            if m.id > after_id and m.sender_id != me_id:
                return m
    return None


# ── Unit-level tests (no Telegram needed) ─────────────────────────────

def test_view_accounting():
    """Test record_tip_view idempotency and check_tip_limit DISTINCT counting."""
    section("View Accounting — Idempotency")

    # Add project to path
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
    sys.path.insert(0, "/home/paulsportsza")
    from scrapers.edge.edge_v2_helper import record_tip_view, check_tip_limit

    conn = sqlite3.connect(":memory:")
    # Create table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS daily_tip_views (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            match_key TEXT NOT NULL,
            viewed_at TIMESTAMP NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tip_views_user_date ON daily_tip_views(user_id, viewed_at)")
    conn.commit()

    TEST_USER = 999999
    MATCH_A = "arsenal_vs_chelsea_2026-03-10"
    MATCH_B = "liverpool_vs_everton_2026-03-10"

    # Record MATCH_A once
    record_tip_view(TEST_USER, MATCH_A, conn)
    row_count = conn.execute("SELECT COUNT(*) FROM daily_tip_views WHERE user_id=?", (TEST_USER,)).fetchone()[0]
    check("First view of MATCH_A creates 1 row", row_count == 1, f"rows={row_count}")

    # Record MATCH_A again (same day) — must be idempotent
    record_tip_view(TEST_USER, MATCH_A, conn)
    row_count = conn.execute("SELECT COUNT(*) FROM daily_tip_views WHERE user_id=?", (TEST_USER,)).fetchone()[0]
    check("Second view of MATCH_A does NOT create another row", row_count == 1, f"rows={row_count}")

    # check_tip_limit should show 1 of 3 used (DISTINCT count)
    can_view, remaining = check_tip_limit(TEST_USER, "bronze", conn)
    check("After 1 fixture: remaining=2, can_view=True", can_view and remaining == 2, f"can_view={can_view}, remaining={remaining}")

    # Record MATCH_B (different fixture)
    record_tip_view(TEST_USER, MATCH_B, conn)
    can_view, remaining = check_tip_limit(TEST_USER, "bronze", conn)
    check("After 2 fixtures: remaining=1, can_view=True", can_view and remaining == 1, f"can_view={can_view}, remaining={remaining}")

    # Record MATCH_B again — idempotent, limit unchanged
    record_tip_view(TEST_USER, MATCH_B, conn)
    can_view2, remaining2 = check_tip_limit(TEST_USER, "bronze", conn)
    check("Re-opening MATCH_B does not change limit", remaining2 == 1, f"remaining={remaining2}")

    conn.close()


def test_tier_reconciliation():
    """Test that get_user_tier reconciles subscription_status=active + plan_code=stitch_premium → gold."""
    section("Entitlement Truth — Tier Reconciliation (unit)")

    # Mock the User object
    class FakeUser:
        user_tier = "bronze"
        subscription_status = "active"
        plan_code = "stitch_premium"

    # Import the function directly
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
    import db as db_module
    result = db_module._resolve_tier_from_subscription(FakeUser())
    check("stitch_premium + active → derives 'gold'", result == "gold", f"derived={result!r}")

    # Test gold_monthly
    class FakeUser2:
        user_tier = "bronze"
        subscription_status = "active"
        plan_code = "gold_monthly"
    result2 = db_module._resolve_tier_from_subscription(FakeUser2())
    check("gold_monthly + active → derives 'gold'", result2 == "gold", f"derived={result2!r}")

    # Test diamond_annual
    class FakeUser3:
        user_tier = "bronze"
        subscription_status = "active"
        plan_code = "diamond_annual"
    result3 = db_module._resolve_tier_from_subscription(FakeUser3())
    check("diamond_annual + active → derives 'diamond'", result3 == "diamond", f"derived={result3!r}")

    # Test inactive subscription — should NOT reconcile
    class FakeUser4:
        user_tier = "bronze"
        subscription_status = "cancelled"
        plan_code = "stitch_premium"
    result4 = db_module._resolve_tier_from_subscription(FakeUser4())
    check("cancelled subscription → no reconciliation (None)", result4 is None, f"derived={result4!r}")

    # Test no subscription — should NOT reconcile
    class FakeUser5:
        user_tier = "bronze"
        subscription_status = None
        plan_code = None
    result5 = db_module._resolve_tier_from_subscription(FakeUser5())
    check("no subscription → no reconciliation (None)", result5 is None, f"derived={result5!r}")


# ── Telethon live tests ────────────────────────────────────────────────

async def test_status_billing_and_qa_reset(client, entity, me_id: int):
    """Test /status and /billing via Telethon, and verify /qa reset is non-destructive."""
    section("Entitlement Truth + QA Reset — Live Bot Tests")

    # Step 1: Set QA to diamond, run /status → should show Diamond
    print("\n  [1] Setting QA diamond tier...")
    s1 = await client.send_message(entity, "/qa set_diamond")
    r1 = await wait_response(client, entity, s1.id, 8.0, me_id)
    if r1:
        print(f"     QA set: {(r1.text or '')[:50]!r}")

    s2 = await client.send_message(entity, "/status")
    r2 = await wait_response(client, entity, s2.id, 8.0, me_id)
    status_text = r2.text or "" if r2 else ""
    print(f"     /status: {status_text[:80]!r}")
    check("/status shows Diamond tier when QA=diamond",
          "Diamond" in status_text or "diamond" in status_text.lower(),
          status_text[:80])

    # Step 2: /billing → should show Diamond
    s3 = await client.send_message(entity, "/billing")
    r3 = await wait_response(client, entity, s3.id, 8.0, me_id)
    billing_text = r3.text or "" if r3 else ""
    print(f"     /billing: {billing_text[:80]!r}")
    check("/billing shows Diamond tier when QA=diamond",
          "Diamond" in billing_text or "diamond" in billing_text.lower(),
          billing_text[:80])

    # Step 3: /qa reset — should clear ONLY the override, NOT set bronze in DB
    print("\n  [3] Running /qa reset...")
    s4 = await client.send_message(entity, "/qa reset")
    r4 = await wait_response(client, entity, s4.id, 8.0, me_id)
    reset_text = r4.text or "" if r4 else ""
    print(f"     /qa reset: {reset_text[:80]!r}")
    check("/qa reset says subscription preserved",
          "preserved" in reset_text.lower() or "override cleared" in reset_text.lower(),
          reset_text[:60])

    # Step 4: /status after reset — should show REAL DB tier (not the QA override, not Bronze if paid)
    await asyncio.sleep(1)
    s5 = await client.send_message(entity, "/status")
    r5 = await wait_response(client, entity, s5.id, 8.0, me_id)
    post_reset_text = r5.text or "" if r5 else ""
    print(f"     /status after reset: {post_reset_text[:80]!r}")
    # Key assertion: must NOT show Diamond (the QA override). Real tier is shown.
    # Also must NOT be a background notification (post-deploy report, etc.)
    is_noise = any(k in post_reset_text for k in ("Post-deploy", "Health:", "FAIL", "precompute"))
    check("/status after /qa reset shows real tier (NOT the QA Diamond override)",
          not is_noise and "Diamond" not in post_reset_text,
          post_reset_text[:80])
    # Log what tier it actually is (Gold if test user has active sub, Bronze if not)
    if "Gold" in post_reset_text:
        print("     → Real tier is Gold (test user has active Gold subscription) ✅ ACC1 works correctly")
    elif "Bronze" in post_reset_text or "Free" in post_reset_text:
        print("     → Real tier is Bronze (test user has no active subscription)")

    # Step 5: Verify reset doesn't corrupt — set QA to silver, reset, status must show real tier
    print("\n  [5] Verifying /qa set_gold → /qa reset preserves real tier...")
    s6a = await client.send_message(entity, "/qa set_gold")
    r6a = await wait_response(client, entity, s6a.id, 6.0, me_id)
    await asyncio.sleep(1)
    s6 = await client.send_message(entity, "/qa reset")
    r6 = await wait_response(client, entity, s6.id, 8.0, me_id)
    await asyncio.sleep(1.5)
    s7 = await client.send_message(entity, "/status")
    r7 = await wait_response(client, entity, s7.id, 10.0, me_id)
    after_gold_reset = r7.text or "" if r7 else ""
    # Filter background notifications
    if any(k in after_gold_reset for k in ("Post-deploy", "Health:", "FAIL", "precompute")):
        print(f"     ⚠️  Background noise received — retrying /status...")
        await asyncio.sleep(2)
        s7b = await client.send_message(entity, "/status")
        r7b = await wait_response(client, entity, s7b.id, 8.0, me_id)
        after_gold_reset = r7b.text or "" if r7b else ""
    print(f"     /status after gold-override→reset: {after_gold_reset[:80]!r}")
    is_noise2 = any(k in after_gold_reset for k in ("Post-deploy", "Health:", "FAIL", "precompute"))
    check("/qa reset preserves real tier (no DB corruption)",
          not is_noise2 and "Status:" in after_gold_reset,
          after_gold_reset[:80])


async def main():
    print(f"\n{'═'*60}")
    print("  W84-ACC1 Validation — Account Truth + View Accounting")
    print(f"  {datetime.now():%Y-%m-%d %H:%M:%S SAST}")
    print(f"{'═'*60}")

    # ── Unit tests (no Telethon) ──────────────────────────────
    test_tier_reconciliation()
    test_view_accounting()

    # ── Live Telethon tests ──────────────────────────────────
    session = load_session()
    if not session.save():
        print("\n  ⚠️  No Telethon session — skipping live bot tests")
    else:
        async with TelegramClient(session, API_ID, API_HASH) as client:
            entity = await client.get_entity(BOT_USERNAME)
            me = await client.get_me()
            await test_status_billing_and_qa_reset(client, entity, me.id)

    # ── Summary ───────────────────────────────────────────────
    section("SUMMARY")
    passed = sum(1 for r in results.values() if r["pass"])
    total = len(results)
    print(f"\n  Results: {passed}/{total} checks passed")
    if failures:
        print("\n  FAILURES:")
        for f in failures:
            d = results[f]["detail"]
            print(f"    ❌ {f}")
            if d:
                print(f"       {d}")
    else:
        print("  All checks PASSED ✅")

    return {"passed": passed, "total": total, "failures": failures}


if __name__ == "__main__":
    asyncio.run(main())
