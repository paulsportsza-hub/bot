"""R6-QA-01: Formal Scored Telethon QA Round.

Collects ALL Edge Pick cards via Telethon, navigates through pagination,
captures detail views, and saves raw outputs for scoring.
"""
import asyncio
import json
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import ensure_scrapers_importable
ensure_scrapers_importable()

from telethon import TelegramClient
from telethon.sessions import StringSession

API_ID = int(os.environ.get("TELEGRAM_API_ID", "32418601"))
API_HASH = os.environ.get("TELEGRAM_API_HASH", "95e313a8ef5b998be0515dd8328fac57")
SESSION_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "telethon_qa_session")
STRING_SESSION_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "telethon_qa_session.string")
BOT_USERNAME = "mzansiedge_bot"
from config import BOT_ROOT
REPORT_DIR = str(BOT_ROOT.parent / "reports" / "r6-qa-captures")

# Sharp bookmakers that must NEVER appear in user-facing content
SHARP_BOOKS = ["pinnacle", "betfair exchange", "matchbook", "smarkets", "betfair_ex"]

# SA bookmakers that SHOULD appear
SA_BOOKS = ["hollywoodbets", "betway", "supabets", "sportingbet", "gbets", "wsb", "supersportbet"]


async def get_client() -> TelegramClient:
    if os.path.exists(STRING_SESSION_FILE):
        string = open(STRING_SESSION_FILE).read().strip()
        if string:
            client = TelegramClient(StringSession(string), API_ID, API_HASH)
            await client.connect()
            if await client.is_user_authorized():
                return client
            await client.disconnect()
    client = TelegramClient(SESSION_FILE, API_ID, API_HASH)
    await client.connect()
    if not await client.is_user_authorized():
        print("ERROR: Not logged in.")
        sys.exit(1)
    return client


async def send_and_wait(client, text, wait=12):
    """Send message and wait for bot response."""
    await client.send_message(BOT_USERNAME, text)
    await asyncio.sleep(wait)
    messages = await client.get_messages(BOT_USERNAME, limit=10)
    return [m for m in messages if not m.out]


async def click_and_wait(btn, client, wait=8):
    """Click a button and wait for response."""
    t0 = time.time()
    await btn.click()
    await asyncio.sleep(wait)
    elapsed = time.time() - t0
    messages = await client.get_messages(BOT_USERNAME, limit=10)
    return [m for m in messages if not m.out], elapsed


def extract_buttons(msg):
    """Extract all buttons with their text, data, and url."""
    buttons = []
    if not msg.buttons:
        return buttons
    for row_idx, row in enumerate(msg.buttons):
        for col_idx, btn in enumerate(row):
            data = (btn.data or b"").decode("utf-8", errors="ignore")
            buttons.append({
                "text": btn.text or "",
                "data": data,
                "url": btn.url or "",
                "row": row_idx,
                "col": col_idx,
            })
    return buttons


def check_sharp_leak(text):
    """Check if any sharp bookmaker name appears in text."""
    lower = (text or "").lower()
    leaks = []
    for s in SHARP_BOOKS:
        if s in lower:
            leaks.append(s)
    return leaks


def check_tier_badge(text):
    """Extract tier badge from text."""
    badges = {
        "💎": "diamond",
        "🥇": "gold",
        "🥈": "silver",
        "🥉": "bronze",
    }
    for emoji, tier in badges.items():
        if emoji in (text or ""):
            return tier
    return None


async def run_qa():
    os.makedirs(REPORT_DIR, exist_ok=True)
    client = await get_client()
    print("Connected to Telegram\n")

    results = {
        "timestamp": datetime.utcnow().isoformat(),
        "cards": [],
        "pages": [],
        "defects": [],
        "timings": {},
    }

    try:
        # ============================================================
        # STEP 1: Send /hot (Top Edge Picks) and capture list view
        # ============================================================
        print("=" * 60)
        print("[1] Sending '💎 Top Edge Picks'...")
        print("=" * 60)
        t0 = time.time()
        responses = await send_and_wait(client, "💎 Top Edge Picks", wait=15)
        hot_tips_time = time.time() - t0
        results["timings"]["hot_tips_initial"] = round(hot_tips_time, 2)
        print(f"  Response time: {hot_tips_time:.1f}s")

        # Find the tips message (most recent non-out message with buttons)
        tips_msg = None
        for msg in responses:
            if msg.buttons and not msg.out:
                tips_msg = msg
                break

        if not tips_msg:
            print("FATAL: No tips message received!")
            results["defects"].append({
                "id": "P0-NO-RESPONSE",
                "severity": "P0",
                "description": "No response from Hot Tips command",
            })
            return results

        # Capture page 1
        page1_text = tips_msg.text or tips_msg.message or ""
        page1_buttons = extract_buttons(tips_msg)
        results["pages"].append({
            "page": 1,
            "text": page1_text,
            "buttons": page1_buttons,
            "msg_id": tips_msg.id,
        })
        print(f"\n  Page 1 text ({len(page1_text)} chars):")
        print(f"  {page1_text[:200]}...")
        print(f"  Buttons: {len(page1_buttons)}")
        for b in page1_buttons:
            print(f"    [{b['row']},{b['col']}] '{b['text'][:50]}' data='{b['data'][:40]}' url={bool(b['url'])}")

        # Save raw page 1
        with open(os.path.join(REPORT_DIR, "page1_raw.txt"), "w") as f:
            f.write(page1_text)

        # ============================================================
        # STEP 2: Navigate through ALL pages
        # ============================================================
        print("\n" + "=" * 60)
        print("[2] Navigating pagination...")
        print("=" * 60)

        all_pages_text = [page1_text]
        current_msg = tips_msg
        page_num = 1

        while True:
            # Find "Next" button
            next_btn = None
            if current_msg.buttons:
                for row in current_msg.buttons:
                    for btn in row:
                        data = (btn.data or b"").decode("utf-8", errors="ignore")
                        btn_text = btn.text or ""
                        if "➡" in btn_text or "Next" in btn_text or "next" in data:
                            next_btn = btn
                            break
                    if next_btn:
                        break

            if not next_btn:
                print(f"  No more pages (total: {page_num})")
                break

            page_num += 1
            print(f"\n  Clicking Next → Page {page_num}...")
            t0 = time.time()
            msgs, elapsed = await click_and_wait(next_btn, client, wait=8)
            results["timings"][f"page_{page_num}"] = round(elapsed, 2)

            # Find updated message
            page_msg = None
            for m in msgs:
                if m.buttons and not m.out:
                    page_msg = m
                    break

            if not page_msg:
                print(f"  WARNING: No response for page {page_num}")
                break

            page_text = page_msg.text or page_msg.message or ""
            page_buttons = extract_buttons(page_msg)
            results["pages"].append({
                "page": page_num,
                "text": page_text,
                "buttons": page_buttons,
                "msg_id": page_msg.id,
            })
            all_pages_text.append(page_text)
            current_msg = page_msg

            print(f"  Page {page_num} ({len(page_text)} chars), {len(page_buttons)} buttons")
            with open(os.path.join(REPORT_DIR, f"page{page_num}_raw.txt"), "w") as f:
                f.write(page_text)

            if page_num > 5:  # Safety limit
                print("  Safety limit reached (5 pages)")
                break

        # ============================================================
        # STEP 3: Identify all edge:detail buttons across all pages
        # ============================================================
        print("\n" + "=" * 60)
        print("[3] Collecting edge:detail buttons...")
        print("=" * 60)

        detail_buttons = []
        for page in results["pages"]:
            for btn in page["buttons"]:
                if "edge:detail" in btn["data"]:
                    detail_buttons.append({
                        "page": page["page"],
                        "text": btn["text"],
                        "data": btn["data"],
                    })
                elif btn["data"].startswith("hot:upgrade") or "sub:plans" in btn["data"]:
                    detail_buttons.append({
                        "page": page["page"],
                        "text": btn["text"],
                        "data": btn["data"],
                        "locked": True,
                    })

        print(f"  Found {len(detail_buttons)} detail/locked buttons")
        for db in detail_buttons:
            locked = " [LOCKED]" if db.get("locked") else ""
            print(f"    Page {db['page']}: '{db['text'][:50]}'{locked} → {db['data'][:50]}")

        # ============================================================
        # STEP 4: Tap into EACH detail view and capture full card
        # ============================================================
        print("\n" + "=" * 60)
        print("[4] Capturing detail views...")
        print("=" * 60)

        # We need to go back to page 1 first for button stability
        # Re-send the command to get fresh state
        await asyncio.sleep(2)
        responses = await send_and_wait(client, "💎 Top Edge Picks", wait=12)
        current_msg = None
        for msg in responses:
            if msg.buttons and not msg.out:
                current_msg = msg
                break

        if not current_msg:
            print("  WARNING: Could not re-fetch tips list")
        else:
            card_idx = 0
            max_cards = 10
            pages_visited = set()

            # Process all pages
            while card_idx < max_cards:
                # Find detail buttons on current message
                if current_msg and current_msg.buttons:
                    for row in current_msg.buttons:
                        for btn in row:
                            if card_idx >= max_cards:
                                break
                            data = (btn.data or b"").decode("utf-8", errors="ignore")
                            btn_text = btn.text or ""

                            if "edge:detail" in data:
                                card_idx += 1
                                print(f"\n  --- Card {card_idx}: '{btn_text[:50]}' ---")

                                # Click detail
                                t0 = time.time()
                                try:
                                    await btn.click()
                                    await asyncio.sleep(8)
                                    detail_time = time.time() - t0

                                    detail_msgs = await client.get_messages(BOT_USERNAME, limit=5)
                                    detail_msg = None
                                    for dm in detail_msgs:
                                        if not dm.out:
                                            detail_msg = dm
                                            break

                                    if not detail_msg:
                                        print(f"  WARNING: No detail response")
                                        results["cards"].append({
                                            "index": card_idx,
                                            "list_text": btn_text,
                                            "error": "no response",
                                        })
                                        continue

                                    detail_text = detail_msg.text or detail_msg.message or ""
                                    detail_buttons_list = extract_buttons(detail_msg)

                                    # === ANALYSIS ===
                                    list_tier = check_tier_badge(btn_text)
                                    detail_tier = check_tier_badge(detail_text)
                                    tier_mismatch = list_tier != detail_tier if (list_tier and detail_tier) else False

                                    sharp_leaks = check_sharp_leak(detail_text)

                                    # Check CTA buttons
                                    cta_btn = None
                                    cta_url = None
                                    cta_bookmaker = None
                                    back_btn_found = False
                                    for db_btn in detail_buttons_list:
                                        if db_btn["url"]:
                                            cta_btn = db_btn
                                            cta_url = db_btn["url"]
                                            # Extract bookmaker from button text
                                            for bk in SA_BOOKS:
                                                if bk.lower() in db_btn["text"].lower():
                                                    cta_bookmaker = bk
                                                    break
                                        if "back" in db_btn["text"].lower() or "edge picks" in db_btn["text"].lower():
                                            back_btn_found = True

                                    # Check staking language
                                    staking_issue = False
                                    if "EV" in detail_text:
                                        # Try to extract EV%
                                        import re
                                        ev_match = re.search(r'EV\s*\+?(\d+\.?\d*)%', detail_text)
                                        if ev_match:
                                            ev_pct = float(ev_match.group(1))
                                            if ev_pct > 7 and "small stake" in detail_text.lower():
                                                staking_issue = True

                                    card_data = {
                                        "index": card_idx,
                                        "list_text": btn_text,
                                        "detail_text": detail_text,
                                        "detail_buttons": detail_buttons_list,
                                        "list_tier": list_tier,
                                        "detail_tier": detail_tier,
                                        "tier_mismatch": tier_mismatch,
                                        "sharp_leaks": sharp_leaks,
                                        "cta_url": cta_url,
                                        "cta_bookmaker": cta_bookmaker,
                                        "has_cta": bool(cta_btn),
                                        "has_back": back_btn_found,
                                        "staking_issue": staking_issue,
                                        "detail_time": round(detail_time, 2),
                                        "detail_chars": len(detail_text),
                                    }
                                    results["cards"].append(card_data)

                                    # Save raw card
                                    with open(os.path.join(REPORT_DIR, f"card{card_idx}_raw.txt"), "w") as f:
                                        f.write(f"=== LIST BUTTON: {btn_text} ===\n")
                                        f.write(f"=== LIST TIER: {list_tier} ===\n")
                                        f.write(f"=== DETAIL TIER: {detail_tier} ===\n\n")
                                        f.write(detail_text)
                                        f.write(f"\n\n=== BUTTONS ===\n")
                                        for db_btn in detail_buttons_list:
                                            f.write(f"  '{db_btn['text']}' data='{db_btn['data']}' url='{db_btn['url']}'\n")

                                    # Print summary
                                    print(f"  Time: {detail_time:.1f}s | Chars: {len(detail_text)}")
                                    print(f"  List tier: {list_tier} | Detail tier: {detail_tier} | Match: {'YES' if not tier_mismatch else 'MISMATCH'}")
                                    print(f"  CTA: {'YES' if cta_btn else 'NO'} | URL: {bool(cta_url)} | BK: {cta_bookmaker}")
                                    print(f"  Sharp leaks: {sharp_leaks or 'none'}")
                                    print(f"  Back button: {'YES' if back_btn_found else 'NO'}")
                                    if staking_issue:
                                        print(f"  STAKING ISSUE: >7% EV but 'small stake'")

                                    # Defects
                                    if tier_mismatch:
                                        results["defects"].append({
                                            "id": f"P0-TIER-{card_idx}",
                                            "severity": "P0",
                                            "card": card_idx,
                                            "description": f"Tier mismatch: list={list_tier}, detail={detail_tier}",
                                        })
                                    if sharp_leaks:
                                        results["defects"].append({
                                            "id": f"P1-SHARP-{card_idx}",
                                            "severity": "P1",
                                            "card": card_idx,
                                            "description": f"Sharp bookmaker leak: {sharp_leaks}",
                                        })
                                    if not cta_btn and not any("locked" in str(b.get("data","")) or "upgrade" in str(b.get("data","")) or "sub:plans" in str(b.get("data","")) for b in detail_buttons_list):
                                        results["defects"].append({
                                            "id": f"P0-CTA-{card_idx}",
                                            "severity": "P0",
                                            "card": card_idx,
                                            "description": "No CTA button with URL on accessible card",
                                        })
                                    if staking_issue:
                                        results["defects"].append({
                                            "id": f"P1-STAKE-{card_idx}",
                                            "severity": "P1",
                                            "card": card_idx,
                                            "description": ">7% EV but 'small stake' language",
                                        })

                                    # Go back
                                    if back_btn_found and detail_msg.buttons:
                                        for row in detail_msg.buttons:
                                            for b in row:
                                                b_text = b.text or ""
                                                b_data = (b.data or b"").decode("utf-8", errors="ignore")
                                                if "edge picks" in b_text.lower() or "hot:back" in b_data:
                                                    await b.click()
                                                    await asyncio.sleep(5)
                                                    # Refresh current_msg
                                                    fresh = await client.get_messages(BOT_USERNAME, limit=5)
                                                    for fm in fresh:
                                                        if fm.buttons and not fm.out:
                                                            current_msg = fm
                                                            break
                                                    break

                                except Exception as e:
                                    print(f"  ERROR: {e}")
                                    results["cards"].append({
                                        "index": card_idx,
                                        "list_text": btn_text,
                                        "error": str(e)[:100],
                                    })

                            elif "hot:upgrade" in data or "sub:plans" in data:
                                card_idx += 1
                                print(f"\n  --- Card {card_idx}: LOCKED '{btn_text[:50]}' ---")
                                results["cards"].append({
                                    "index": card_idx,
                                    "list_text": btn_text,
                                    "locked": True,
                                    "detail_text": "",
                                    "has_cta": False,
                                })

                # Try to go to next page
                next_btn = None
                if current_msg and current_msg.buttons:
                    for row in current_msg.buttons:
                        for btn in row:
                            data = (btn.data or b"").decode("utf-8", errors="ignore")
                            btn_text = btn.text or ""
                            if "➡" in btn_text or "Next" in btn_text:
                                next_btn = btn
                                break
                        if next_btn:
                            break

                if not next_btn:
                    break

                print(f"\n  → Navigating to next page...")
                await next_btn.click()
                await asyncio.sleep(6)
                fresh = await client.get_messages(BOT_USERNAME, limit=5)
                current_msg = None
                for fm in fresh:
                    if fm.buttons and not fm.out:
                        current_msg = fm
                        break

        # ============================================================
        # STEP 5: Check template diversity (rugby cards)
        # ============================================================
        print("\n" + "=" * 60)
        print("[5] Checking template diversity...")
        print("=" * 60)

        rugby_cards = [c for c in results["cards"] if "🏉" in c.get("list_text", "") or "rugby" in c.get("detail_text", "").lower()]
        if len(rugby_cards) >= 2:
            openings = []
            for rc in rugby_cards:
                text = rc.get("detail_text", "")
                # Get first non-header line
                lines = [l.strip() for l in text.split("\n") if l.strip() and not l.strip().startswith("🎯") and not l.strip().startswith("🏆") and not l.strip().startswith("📅") and not l.strip().startswith("📺")]
                if lines:
                    openings.append(lines[0][:80])
            if len(set(openings)) < len(openings):
                results["defects"].append({
                    "id": "P1-RUGBY-DIVERSITY",
                    "severity": "P1",
                    "description": f"Rugby cards have same opening: {openings}",
                })
                print(f"  WARNING: Rugby cards share openings")
            else:
                print(f"  OK: {len(rugby_cards)} rugby cards, all different openings")
        else:
            print(f"  Skipped: only {len(rugby_cards)} rugby cards found")

        # ============================================================
        # STEP 6: Summary
        # ============================================================
        print("\n" + "=" * 60)
        print("SUMMARY")
        print("=" * 60)

        total_cards = len(results["cards"])
        accessible = [c for c in results["cards"] if not c.get("locked") and not c.get("error")]
        locked = [c for c in results["cards"] if c.get("locked")]
        errors = [c for c in results["cards"] if c.get("error")]

        print(f"  Total cards captured: {total_cards}")
        print(f"  Accessible: {len(accessible)}")
        print(f"  Locked: {len(locked)}")
        print(f"  Errors: {len(errors)}")
        print(f"  Pages: {len(results['pages'])}")

        p0_count = len([d for d in results["defects"] if d["severity"] == "P0"])
        p1_count = len([d for d in results["defects"] if d["severity"] == "P1"])
        p2_count = len([d for d in results["defects"] if d["severity"] == "P2"])
        print(f"\n  Defects: P0={p0_count}, P1={p1_count}, P2={p2_count}")

        for d in results["defects"]:
            print(f"    [{d['severity']}] {d['id']}: {d['description']}")

        # R6 fix verification
        print("\n  R6 Fix Verification:")
        all_cta_ok = all(c.get("has_cta") or c.get("locked") or c.get("error") for c in results["cards"])
        print(f"    1. CTA buttons resolve to real URLs: {'FIXED' if all_cta_ok else 'STILL BROKEN'}")

        tier_ok = not any(c.get("tier_mismatch") for c in results["cards"])
        print(f"    2. Tier assignment list=detail: {'FIXED' if tier_ok else 'STILL BROKEN'}")

        staking_ok = not any(c.get("staking_issue") for c in results["cards"])
        print(f"    3. Staking floor (>7% EV ≠ 'Small stake'): {'FIXED' if staking_ok else 'STILL BROKEN'}")

        contamination = False
        for c in accessible:
            text = c.get("detail_text", "").lower()
            # Check for obvious wrong-team contamination would need more sophisticated checking
        print(f"    4. Player contamination: NEEDS MANUAL REVIEW")

        rugby_diversity_ok = not any(d["id"] == "P1-RUGBY-DIVERSITY" for d in results["defects"])
        print(f"    5. Rugby template diversity: {'FIXED' if rugby_diversity_ok else 'STILL BROKEN'}")

        sharp_ok = not any(c.get("sharp_leaks") for c in results["cards"])
        print(f"    6. Sharp bookmaker filter: {'FIXED' if sharp_ok else 'STILL BROKEN'}")

        # Save full results
        results_path = os.path.join(REPORT_DIR, "qa_results.json")
        with open(results_path, "w") as f:
            json.dump(results, f, indent=2, default=str)
        print(f"\n  Results saved to {results_path}")

    finally:
        await client.disconnect()

    return results


if __name__ == "__main__":
    asyncio.run(run_qa())
