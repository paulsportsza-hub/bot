"""R9-QA-01: Formal Scored QA Round — Post-BUILD-01 Verification.

Telethon E2E test against live bot. Captures all edge cards, detail views,
scores each on 5 dimensions: Accuracy, Narrative, Value, Runtime, UX.

Focuses on verifying R8 P0 defects:
- P0-OUTCOME-DIVERGE: List-detail outcome alignment
- P0-CTA-URL-WRONG: CTA bookmaker URL correctness
- P0-ZERO-PROB: Zero probability on draw outcomes
"""
import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from telethon import TelegramClient
from telethon.sessions import StringSession

API_ID = int(os.environ.get("TELEGRAM_API_ID", "32418601"))
API_HASH = os.environ.get("TELEGRAM_API_HASH", "95e313a8ef5b998be0515dd8328fac57")
SESSION_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "telethon_session")
STRING_SESSION_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "telethon_session.string")
BOT_USERNAME = "mzansiedge_bot"
from config import BOT_ROOT
CAPTURE_DIR = str(BOT_ROOT.parent / "reports" / "r9-qa-captures")


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
    await client.send_message(BOT_USERNAME, text)
    await asyncio.sleep(wait)
    messages = await client.get_messages(BOT_USERNAME, limit=10)
    return [m for m in messages if not m.out]


def extract_buttons(msg):
    """Extract all buttons with their text, callback data, and URLs."""
    buttons = []
    if not msg or not msg.buttons:
        return buttons
    for row_idx, row in enumerate(msg.buttons):
        for col_idx, btn in enumerate(row):
            data = (btn.data or b"").decode("utf-8", errors="ignore") if btn.data else ""
            buttons.append({
                "text": btn.text or "",
                "data": data,
                "url": btn.url or "",
                "row": row_idx,
                "col": col_idx,
            })
    return buttons


def parse_list_card(text, buttons):
    """Parse a list view to extract per-card info."""
    cards = []
    lines = text.split("\n")
    current_card = {}

    for line in lines:
        # Card line: [N] emoji Team vs Team badge
        if line.strip().startswith("[") and "]" in line and " vs " in line.lower():
            if current_card:
                cards.append(current_card)
            num = line.split("]")[0].replace("[", "").strip()
            # Extract tier badge
            tier = "unknown"
            for emoji, t in [("💎", "diamond"), ("🥇", "gold"), ("🥈", "silver"), ("🥉", "bronze")]:
                if emoji in line:
                    tier = t
                    break
            # Extract teams
            rest = line.split("]", 1)[1].strip()
            # Remove sport emoji at start
            for e in ("⚽", "🏉", "🏏", "🥊"):
                rest = rest.lstrip(e).strip()
            # Remove tier badge
            for e in ("💎", "🥇", "🥈", "🥉"):
                rest = rest.replace(e, "").strip()
            teams = rest
            current_card = {"num": num, "teams": teams, "tier": tier, "lines": [line]}
        elif current_card:
            current_card["lines"].append(line)
            # Extract outcome + odds + EV from the 💰 line
            if "💰" in line or "@" in line:
                current_card["odds_line"] = line.strip()
                # Try to extract outcome
                if "@" in line:
                    parts = line.split("@")
                    outcome_part = parts[0].replace("💰", "").strip()
                    current_card["list_outcome"] = outcome_part
                # Extract EV
                if "EV" in line:
                    ev_parts = line.split("EV")
                    if len(ev_parts) > 1:
                        ev_str = ev_parts[0].split("+")[-1].split("·")[-1].strip()
                        if "%" in line:
                            for part in line.split():
                                if "%" in part and "+" in part:
                                    current_card["list_ev"] = part
    if current_card:
        cards.append(current_card)

    # Map edge:detail buttons to cards
    detail_buttons = [b for b in buttons if "edge:detail" in b["data"]]
    for i, btn in enumerate(detail_buttons):
        if i < len(cards):
            cards[i]["detail_btn"] = btn

    return cards


async def capture_detail(client, btn_obj, card_num, wait=12):
    """Click a detail button and capture the response."""
    t0 = time.time()
    try:
        await btn_obj.click()
        await asyncio.sleep(wait)
        elapsed = time.time() - t0

        messages = await client.get_messages(BOT_USERNAME, limit=5)
        detail_msg = None
        for m in messages:
            if not m.out and m.buttons:
                detail_msg = m
                break
        if not detail_msg:
            for m in messages:
                if not m.out:
                    detail_msg = m
                    break

        if not detail_msg:
            return {"card": card_num, "error": "no response", "elapsed": elapsed}

        text = detail_msg.text or ""
        buttons = extract_buttons(detail_msg)

        result = {
            "card": card_num,
            "text": text,
            "buttons": buttons,
            "elapsed": elapsed,
        }

        # Extract detail outcome
        for line in text.split("\n"):
            if "🎯" in line and ("Edge" in line or "sits on" in line or "edge" in line.lower()):
                result["detail_edge_line"] = line.strip()
            if "🏆" in line and "Verdict" in line:
                result["verdict_line"] = line.strip()

        # Extract detail tier
        for emoji, t in [("💎", "diamond"), ("🥇", "gold"), ("🥈", "silver"), ("🥉", "bronze")]:
            if emoji in text:
                result["detail_tier"] = t
                break

        # Extract CTA button
        for b in buttons:
            if "Back" in b["text"] and "@" in b["text"] and " on " in b["text"]:
                result["cta_text"] = b["text"]
                result["cta_url"] = b["url"]
                bk = b["text"].split(" on ")[-1].rstrip(" →").strip()
                result["cta_bookmaker"] = bk
                # Check URL matches
                bk_lower = bk.lower().replace(" ", "")
                url_lower = b["url"].lower()
                result["cta_match"] = any(x in url_lower for x in [
                    bk_lower, bk_lower.replace(".", ""),
                    bk_lower.split(".")[0] if "." in bk_lower else bk_lower
                ])
            elif b["url"] and not b["text"].startswith("↩"):
                # URL button that might be CTA
                result.setdefault("cta_url_buttons", []).append(b)

        # Check for Compare Odds
        result["has_compare_odds"] = any("Compare" in b["text"] or "odds:compare" in b["data"] for b in buttons)

        # Check for probability
        for line in text.split("\n"):
            if "%" in line and ("prob" in line.lower() or "fair" in line.lower()):
                result["prob_line"] = line.strip()
            # Check for 0% probability
            if "0%" in line and ("prob" in line.lower() or "EV" in line):
                result["zero_prob"] = True

        # Extract SA Bookmaker Odds section
        if "SA Bookmaker Odds" in text or "Bookmaker Odds" in text:
            result["has_bookmaker_odds"] = True

        # Check for detail outcome
        for line in text.split("\n"):
            stripped = line.strip()
            if stripped.startswith("🎯") and "The Edge" in stripped:
                continue  # section header
            if "sits on" in stripped.lower():
                # Extract what outcome sits on
                parts = stripped.split("sits on")
                if len(parts) > 1:
                    detail_out = parts[1].strip().split(" because")[0].split(" at ")[0].strip()
                    result["detail_outcome"] = detail_out
            elif "@ " in stripped and ("Back" in stripped or "back" in stripped.lower()):
                # CTA-style line in text
                pass

        # Extract outcome from CTA button text
        if "cta_text" in result:
            cta = result["cta_text"]
            # "🥇 Back Sundowns @ 1.48 on Hollywoodbets →"
            if "Back " in cta:
                parts = cta.split("Back ", 1)[1]
                outcome = parts.split(" @")[0].split(" at ")[0].strip()
                result["detail_outcome_from_cta"] = outcome

        return result

    except Exception as e:
        return {"card": card_num, "error": str(e), "elapsed": time.time() - t0}


async def run_qa():
    os.makedirs(CAPTURE_DIR, exist_ok=True)
    client = await get_client()
    print("Connected to Telegram")
    all_results = {"pre_checks": {}, "list_view": {}, "cards": [], "pages": []}

    try:
        # ── Pre-QA Checks ──
        me = await client.get_me()
        all_results["pre_checks"]["user_id"] = me.id
        all_results["pre_checks"]["timestamp"] = time.strftime("%Y-%m-%d %H:%M:%S UTC")
        print(f"User: {me.id} ({me.first_name})")

        # ── Step 1: Send Top Edge Picks ──
        print("\n[1] Sending '💎 Top Edge Picks'...")
        t0 = time.time()
        responses = await send_and_wait(client, "💎 Top Edge Picks", wait=15)
        list_elapsed = time.time() - t0

        # Find the tips message
        tips_msg = None
        for msg in responses:
            if msg.buttons and not msg.out:
                for row in msg.buttons:
                    for btn in row:
                        data = (btn.data or b"").decode("utf-8", errors="ignore")
                        if "edge:detail" in data:
                            tips_msg = msg
                            break
                    if tips_msg:
                        break
            if tips_msg:
                break

        if not tips_msg:
            print("ERROR: No tips message found")
            for msg in responses[:5]:
                print(f"  [{msg.id}] buttons={bool(msg.buttons)} text={(msg.text or '')[:100]}")
            return

        all_results["list_view"]["text"] = tips_msg.text or ""
        all_results["list_view"]["elapsed"] = list_elapsed
        all_results["list_view"]["buttons"] = extract_buttons(tips_msg)

        print(f"  List loaded in {list_elapsed:.1f}s")
        print(f"  Text length: {len(tips_msg.text or '')}")

        # Save raw list capture
        with open(os.path.join(CAPTURE_DIR, "list_page1.txt"), "w") as f:
            f.write(tips_msg.text or "")
            f.write("\n\n--- BUTTONS ---\n")
            for b in extract_buttons(tips_msg):
                f.write(f"  {b['text']} | data={b['data'][:50]} | url={b['url'][:60] if b['url'] else ''}\n")

        # Parse list cards
        list_buttons = extract_buttons(tips_msg)
        cards = parse_list_card(tips_msg.text or "", list_buttons)
        print(f"  Found {len(cards)} cards")

        # ── Step 2: Check pagination / additional pages ──
        next_btn = None
        for b in list_buttons:
            if "Next" in b["text"] or "hot:page:" in b["data"]:
                next_btn_data = b
                break
        else:
            next_btn_data = None

        page_count = 1
        if next_btn_data:
            print("\n[2] Checking page 2...")
            # Find the actual button object
            for row in tips_msg.buttons:
                for btn in row:
                    if "Next" in (btn.text or ""):
                        next_btn = btn
                        break
                if next_btn:
                    break

            if next_btn:
                await next_btn.click()
                await asyncio.sleep(8)
                page2_msgs = await client.get_messages(BOT_USERNAME, limit=5)
                for m in page2_msgs:
                    if not m.out and m.buttons:
                        page2_text = m.text or ""
                        page2_buttons = extract_buttons(m)
                        page2_cards = parse_list_card(page2_text, page2_buttons)
                        cards.extend(page2_cards)
                        page_count = 2
                        all_results["pages"].append({"page": 2, "text": page2_text, "card_count": len(page2_cards)})

                        with open(os.path.join(CAPTURE_DIR, "list_page2.txt"), "w") as f:
                            f.write(page2_text)

                        # Go back to page 1 for card tapping
                        for row2 in m.buttons:
                            for btn2 in row2:
                                if "Prev" in (btn2.text or "") or "hot:page:0" in ((btn2.data or b"").decode("utf-8", errors="ignore")):
                                    await btn2.click()
                                    await asyncio.sleep(5)
                                    break
                        break

        print(f"  Total cards across {page_count} page(s): {len(cards)}")

        # ── Step 3: Tap each card and capture detail ──
        print(f"\n[3] Tapping {min(10, len(cards))} cards for detail capture...")

        # Re-fetch the current message state
        current_msgs = await client.get_messages(BOT_USERNAME, limit=5)
        current_tips = None
        for m in current_msgs:
            if not m.out and m.buttons:
                for row in m.buttons:
                    for btn in row:
                        data = (btn.data or b"").decode("utf-8", errors="ignore")
                        if "edge:detail" in data:
                            current_tips = m
                            break
                    if current_tips:
                        break
            if current_tips:
                break

        if not current_tips:
            print("  WARN: Can't find tips message for tapping, using original")
            current_tips = tips_msg

        detail_buttons = []
        for row in current_tips.buttons:
            for btn in row:
                data = (btn.data or b"").decode("utf-8", errors="ignore")
                if "edge:detail" in data:
                    detail_buttons.append(btn)

        card_results = []
        for i, btn in enumerate(detail_buttons[:10]):
            card_num = i + 1
            print(f"\n  --- Card {card_num}: '{btn.text[:40]}' ---")
            detail = await capture_detail(client, btn, card_num, wait=12)
            card_results.append(detail)

            # Save raw capture
            with open(os.path.join(CAPTURE_DIR, f"card_{card_num}_detail.txt"), "w") as f:
                f.write(detail.get("text", "NO TEXT"))
                f.write("\n\n--- BUTTONS ---\n")
                for b in detail.get("buttons", []):
                    f.write(f"  {b['text']} | data={b['data'][:50]} | url={b['url'][:60] if b['url'] else ''}\n")

            elapsed = detail.get("elapsed", 0)
            print(f"  Time: {elapsed:.1f}s")
            if "cta_text" in detail:
                match_icon = "✅" if detail.get("cta_match") else "❌"
                print(f"  CTA: {detail['cta_text'][:60]}")
                print(f"  URL: {detail.get('cta_url', 'N/A')[:60]} {match_icon}")
            elif detail.get("cta_url_buttons"):
                for ub in detail["cta_url_buttons"]:
                    print(f"  URL btn: '{ub['text'][:40]}' → {ub['url'][:60]}")
            else:
                print(f"  NO CTA found")

            if detail.get("detail_outcome"):
                print(f"  Detail outcome: {detail['detail_outcome']}")
            if detail.get("detail_outcome_from_cta"):
                print(f"  CTA outcome: {detail['detail_outcome_from_cta']}")
            if detail.get("zero_prob"):
                print(f"  ⚠️ ZERO PROBABILITY detected")
            if detail.get("has_compare_odds"):
                print(f"  ✅ Compare Odds present")
            else:
                print(f"  ❌ No Compare Odds")

            # Navigate back
            back_btn = None
            if detail.get("buttons"):
                for b_info in detail["buttons"]:
                    if "Edge Picks" in b_info["text"] or "hot:back" in b_info["data"]:
                        # Find the actual button
                        msgs = await client.get_messages(BOT_USERNAME, limit=3)
                        for m in msgs:
                            if m.buttons and not m.out:
                                for row in m.buttons:
                                    for b in row:
                                        bd = (b.data or b"").decode("utf-8", errors="ignore")
                                        if "hot:back" in bd or "Edge Picks" in (b.text or ""):
                                            back_btn = b
                                            break
                                    if back_btn:
                                        break
                            if back_btn:
                                break
                        break

            if back_btn:
                await back_btn.click()
                await asyncio.sleep(4)
            else:
                # Send command to get back to list
                await client.send_message(BOT_USERNAME, "💎 Top Edge Picks")
                await asyncio.sleep(8)
                # Re-find the tips message
                current_msgs = await client.get_messages(BOT_USERNAME, limit=5)
                for m in current_msgs:
                    if not m.out and m.buttons:
                        for row in m.buttons:
                            for btn2 in row:
                                data2 = (btn2.data or b"").decode("utf-8", errors="ignore")
                                if "edge:detail" in data2:
                                    current_tips = m
                                    break
                            if current_tips == m:
                                break

        all_results["cards"] = card_results

        # ── Step 4: Match list outcomes with detail outcomes ──
        print("\n\n" + "=" * 70)
        print("R9-QA-01 CAPTURE SUMMARY")
        print("=" * 70)

        print(f"\nCards captured: {len(card_results)}")
        print(f"Pages: {page_count}")

        # Outcome divergence check
        print("\n--- OUTCOME DIVERGENCE CHECK (R8 P0-OUTCOME-DIVERGE) ---")
        divergence_count = 0
        for i, card in enumerate(cards[:len(card_results)]):
            detail = card_results[i] if i < len(card_results) else {}
            list_out = card.get("list_outcome", "?").strip()
            detail_out = detail.get("detail_outcome_from_cta") or detail.get("detail_outcome", "?")
            if list_out and detail_out and list_out != "?" and detail_out != "?":
                # Fuzzy comparison
                list_lower = list_out.lower().strip()
                detail_lower = detail_out.lower().strip()
                match = (list_lower in detail_lower or detail_lower in list_lower
                         or list_lower.split()[0] == detail_lower.split()[0])
                status = "✅" if match else "❌ DIVERGE"
                if not match:
                    divergence_count += 1
                print(f"  Card {i+1}: List='{list_out}' Detail='{detail_out}' {status}")
            else:
                print(f"  Card {i+1}: List='{list_out}' Detail='{detail_out}' (incomplete data)")

        # CTA URL check
        print("\n--- CTA URL CHECK (R8 P0-CTA-URL-WRONG) ---")
        cta_correct = 0
        cta_total = 0
        for detail in card_results:
            if "cta_text" in detail:
                cta_total += 1
                match = detail.get("cta_match", False)
                status = "✅" if match else "❌ MISMATCH"
                bk = detail.get("cta_bookmaker", "?")
                url_short = (detail.get("cta_url", "")[:50]) if detail.get("cta_url") else "N/A"
                print(f"  Card {detail['card']}: {bk} → {url_short} {status}")
                if match:
                    cta_correct += 1
            elif detail.get("cta_url_buttons"):
                for ub in detail["cta_url_buttons"]:
                    print(f"  Card {detail['card']}: URL btn '{ub['text'][:30]}' → {ub['url'][:50]}")

        # Zero prob check
        print("\n--- ZERO PROBABILITY CHECK (R8 P0-ZERO-PROB) ---")
        zero_prob_count = sum(1 for d in card_results if d.get("zero_prob"))
        print(f"  Cards with 0% probability: {zero_prob_count}")

        # Tier mismatch check
        print("\n--- TIER MISMATCH CHECK (R8 P1-TIER-MISMATCH) ---")
        tier_mismatch = 0
        for i, card in enumerate(cards[:len(card_results)]):
            detail = card_results[i] if i < len(card_results) else {}
            list_tier = card.get("tier", "?")
            detail_tier = detail.get("detail_tier", "?")
            if list_tier != "?" and detail_tier != "?" and list_tier != detail_tier:
                tier_mismatch += 1
                print(f"  Card {i+1}: List={list_tier} Detail={detail_tier} ❌")
            elif list_tier != "?" and detail_tier != "?":
                print(f"  Card {i+1}: List={list_tier} Detail={detail_tier} ✅")

        # Compare Odds check
        print("\n--- COMPARE ODDS CHECK (R8 P2-NO-COMPARE) ---")
        compare_count = sum(1 for d in card_results if d.get("has_compare_odds"))
        print(f"  Cards with Compare Odds: {compare_count}/{len(card_results)}")

        # Performance check
        print("\n--- PERFORMANCE ---")
        for detail in card_results:
            elapsed = detail.get("elapsed", 0)
            status = "✅" if elapsed < 5 else ("⚠️" if elapsed < 10 else "❌")
            print(f"  Card {detail['card']}: {elapsed:.1f}s {status}")

        # Save full results
        # Convert non-serializable types
        def sanitize(obj):
            if isinstance(obj, bytes):
                return obj.decode("utf-8", errors="ignore")
            if isinstance(obj, dict):
                return {k: sanitize(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [sanitize(v) for v in obj]
            return obj

        with open(os.path.join(CAPTURE_DIR, "r9_qa_results.json"), "w") as f:
            json.dump(sanitize(all_results), f, indent=2, default=str)

        print(f"\n\nCaptures saved to {CAPTURE_DIR}/")
        print(f"Results JSON: {CAPTURE_DIR}/r9_qa_results.json")

    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(run_qa())
