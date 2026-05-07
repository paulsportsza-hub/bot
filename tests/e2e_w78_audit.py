#!/usr/bin/env python3
"""W78-INVESTIGATE: Live Bot UX Audit — Tap every edge, document what users see."""

import asyncio
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import (
    ReplyInlineMarkup,
    KeyboardButtonCallback,
)

API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "")
BOT = "mzansiedge_bot"
SESSION_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "telethon_qa_session")
STRING_SESSION_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "telethon_qa_session.string")
from config import BOT_ROOT
CAPTURE_DIR = str(BOT_ROOT.parent / "reports" / "screenshots" / "w78_audit")
os.makedirs(CAPTURE_DIR, exist_ok=True)

# Meta leak patterns
META_LEAK_PATTERNS = [
    r"(?i)based on (?:my |the )?web search",
    r"(?i)I have current updates that contradict",
    r"(?i)the searches also reveal",
    r"(?i)let me search for",
    r"(?i)based on (?:the )?(?:web )?search results",
    r"(?i)according to (?:my |the )?search",
    r"(?i)web search (?:findings|results|shows)",
    r"(?i)I (?:found|searched|looked up)",
    r"(?i)my research (?:shows|indicates|suggests)",
    r"(?i)upon (?:searching|researching)",
]

# Robotic patterns
ROBOTIC_PATTERNS = [
    r"with .{3,30}'s side",  # "with Slot's side"
    r"Their record reads \d",
    r"They're scoring [\d.]+ goals per game",
    r"Recent form reads [WDLNR]{3,}",
    r"Form: [WDLNR]{3,}",
]

# ── Results ──
EDGE_RESULTS = []


# ── Telethon helpers ──

_entity = None


async def get_client():
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


async def entity(client):
    global _entity
    if _entity is None:
        _entity = await client.get_entity(BOT)
    return _entity


async def send_and_wait(client, text, wait=15):
    """Send command, wait for bot response, return (messages, response_time)."""
    ent = await entity(client)
    t0 = time.time()
    sent = await client.send_message(ent, text)
    deadline = t0 + wait
    bot_msgs = []
    while time.time() < deadline:
        await asyncio.sleep(0.5)
        messages = await client.get_messages(ent, limit=20)
        new = [m for m in messages if m.id > sent.id and not m.out]
        if new and any(m.text or m.reply_markup for m in new):
            bot_msgs = list(reversed(new))
            break
    return bot_msgs, time.time() - t0


async def click_callback_data(client, msg, callback_data, wait=30):
    """Click inline button by exact callback_data, wait for response."""
    if not msg or not msg.reply_markup or not isinstance(msg.reply_markup, ReplyInlineMarkup):
        return None, [], 0.0

    for row in msg.reply_markup.rows:
        for btn in row.buttons:
            if isinstance(btn, KeyboardButtonCallback):
                if btn.data and btn.data.decode("utf-8", errors="replace") == callback_data:
                    t0 = time.time()
                    try:
                        await msg.click(data=btn.data)
                    except Exception as e:
                        print(f"    Click error: {e}")
                        return None, [], time.time() - t0

                    # Wait for response (edited message or new message)
                    ent = await entity(client)
                    await asyncio.sleep(2)  # initial settle

                    deadline = t0 + wait
                    while time.time() < deadline:
                        # Check for edited message
                        edited = await client.get_messages(ent, ids=msg.id)
                        # Check for new messages
                        all_msgs = await client.get_messages(ent, limit=20)
                        new = [m for m in all_msgs if m.id > msg.id and not m.out]

                        # If the message was edited with new content, that's our response
                        if edited and edited.text and edited.text != msg.text:
                            elapsed = time.time() - t0
                            return edited, list(reversed(new)), elapsed

                        # If new messages appeared, check for substantive content
                        if new:
                            for nm in new:
                                if nm.text and len(nm.text) > 50:
                                    elapsed = time.time() - t0
                                    return edited, list(reversed(new)), elapsed

                        await asyncio.sleep(1)

                    elapsed = time.time() - t0
                    edited = await client.get_messages(ent, ids=msg.id)
                    all_msgs = await client.get_messages(ent, limit=20)
                    new = [m for m in all_msgs if m.id > msg.id and not m.out]
                    return edited, list(reversed(new)), elapsed

    return None, [], 0.0


def get_inline_buttons(msg):
    """Extract inline buttons as list of {text, data}."""
    if not msg or not msg.reply_markup or not isinstance(msg.reply_markup, ReplyInlineMarkup):
        return []
    buttons = []
    for row in msg.reply_markup.rows:
        for btn in row.buttons:
            if isinstance(btn, KeyboardButtonCallback):
                data = btn.data.decode("utf-8", errors="replace") if btn.data else ""
                buttons.append({"text": btn.text, "data": data})
    return buttons


def classify_narrative(text):
    """Classify the narrative type based on content patterns."""
    if not text or len(text) < 30:
        return "NO_RESPONSE"

    # Check for error messages
    if any(x in text.lower() for x in ["error", "couldn't", "could not", "failed to", "no sa bookmaker"]):
        if len(text) < 200:
            return "ERROR"

    # Check for minimal content
    if len(text) < 200:
        return "MINIMAL"

    # Check for programmatic (bullet-point, formulaic)
    programmatic_signals = 0
    if re.search(r"with .{3,30}'s side", text):
        programmatic_signals += 2
    if text.count("•") >= 3:
        programmatic_signals += 1
    if re.search(r"Their record reads", text):
        programmatic_signals += 2
    if re.search(r"Form: [WDLNR]", text):
        programmatic_signals += 1
    lines = text.split("\n")
    short_lines = sum(1 for l in lines if 10 < len(l.strip()) < 80)
    if short_lines > 5 and short_lines > len(lines) * 0.5:
        programmatic_signals += 1

    if programmatic_signals >= 2:
        return "PROGRAMMATIC"

    # Rich content — likely AI
    if len(text) > 500:
        return "AI_CACHED"  # Can't distinguish cached vs live from content alone

    return "AI_CACHED"


def check_meta_leaks(text):
    """Check for AI meta-commentary leaking into output."""
    if not text:
        return False, []
    found = []
    for pattern in META_LEAK_PATTERNS:
        matches = re.findall(pattern, text)
        if matches:
            found.extend(matches)
    return bool(found), found


def check_robotic(text):
    """Check for robotic/formulaic patterns."""
    if not text:
        return False, []
    found = []
    for pattern in ROBOTIC_PATTERNS:
        matches = re.findall(pattern, text)
        if matches:
            found.extend(matches)
    return bool(found), found


def extract_match_info(btn_text):
    """Extract match name and sport from button text like '[1] ⚽ RMA v MAN 💎'."""
    # Remove numbering
    clean = re.sub(r'^\[\d+\]\s*', '', btn_text)

    # Detect sport from emoji
    sport = "unknown"
    if "⚽" in clean:
        sport = "soccer"
    elif "🏉" in clean:
        sport = "rugby"
    elif "🏏" in clean:
        sport = "cricket"
    elif "🥊" in clean:
        sport = "combat"

    # Extract match name (everything between sport emoji and tier emoji)
    match_name = re.sub(r'[⚽🏉🏏🥊💎🥇🥈🥉]', '', clean).strip()

    # Detect tier
    tier = "unknown"
    if "💎" in btn_text:
        tier = "diamond"
    elif "🥇" in btn_text:
        tier = "gold"
    elif "🥈" in btn_text:
        tier = "silver"
    elif "🥉" in btn_text:
        tier = "bronze"

    return match_name, sport, tier


async def main():
    print("=" * 60)
    print("W78-INVESTIGATE: Live Bot UX Audit")
    print("=" * 60)

    client = await get_client()
    print(f"Connected. Bot: @{BOT}\n")

    try:
        # ── Step 1: Load /tips and get all edges ──
        print("─── Loading /tips ───")
        tips_msgs, tips_time = await send_and_wait(client, "/tips", wait=15)
        if not tips_msgs:
            print("ERROR: /tips returned no response!")
            return

        tips_msg = tips_msgs[-1]
        tips_text = tips_msg.text or ""
        print(f"Tips loaded in {tips_time:.1f}s")

        # Save tips page
        capture_path = os.path.join(CAPTURE_DIR, "tips_page_1.txt")
        with open(capture_path, "w") as f:
            f.write(tips_text)
        print(f"Saved: {capture_path}")

        # Find all edge buttons
        all_edge_buttons = []
        buttons = get_inline_buttons(tips_msg)
        for btn in buttons:
            if btn["data"].startswith("edge:detail:"):
                all_edge_buttons.append(btn)

        print(f"Found {len(all_edge_buttons)} edge buttons on page 1")

        # Check for pagination — load all pages
        page = 1
        current_msg = tips_msg
        while True:
            nav_btns = [b for b in get_inline_buttons(current_msg) if "hot:page:" in b["data"]]
            next_btn = [b for b in nav_btns if "Next" in b["text"] or "➡" in b["text"] or "▶" in b["text"]]
            if not next_btn:
                break
            page += 1
            print(f"\n─── Loading page {page} ───")
            await asyncio.sleep(2)
            edited, new_msgs, pg_time = await click_callback_data(client, current_msg, next_btn[0]["data"], wait=15)

            # The response is in the edited message
            pg_msg = edited if edited and edited.text != current_msg.text else (new_msgs[-1] if new_msgs else None)
            if pg_msg:
                pg_text = pg_msg.text or ""
                capture_path = os.path.join(CAPTURE_DIR, f"tips_page_{page}.txt")
                with open(capture_path, "w") as f:
                    f.write(pg_text)
                pg_buttons = get_inline_buttons(pg_msg)
                new_edges = [b for b in pg_buttons if b["data"].startswith("edge:detail:")]
                all_edge_buttons.extend(new_edges)
                print(f"Page {page}: {len(new_edges)} edges, loaded in {pg_time:.1f}s")
                current_msg = pg_msg
            else:
                print(f"Page {page}: no response")
                break

        total_edges = len(all_edge_buttons)
        print(f"\n{'=' * 60}")
        print(f"TOTAL EDGES TO TAP: {total_edges}")
        print(f"{'=' * 60}\n")

        # ── Step 2: Tap EVERY edge ──
        for i, edge_btn in enumerate(all_edge_buttons, 1):
            match_name, sport, tier = extract_match_info(edge_btn["text"])
            print(f"\n─── Edge {i}/{total_edges}: {edge_btn['text']} ───")

            # We need to navigate back to tips first (except first one)
            if i > 1:
                # Send /tips again to reset position
                await asyncio.sleep(2)
                tips_msgs, _ = await send_and_wait(client, "/tips", wait=10)
                if tips_msgs:
                    current_msg = tips_msgs[-1]
                else:
                    print(f"  ERROR: Could not reload tips for edge {i}")
                    EDGE_RESULTS.append({
                        "num": i, "match": match_name, "sport": sport, "tier": tier,
                        "load_time": 0, "narrative_type": "ERROR",
                        "meta_leak": False, "meta_leak_detail": [],
                        "robotic": False, "robotic_detail": [],
                        "full_text": "", "btn_text": edge_btn["text"],
                        "callback_data": edge_btn["data"],
                    })
                    continue

                # Navigate to correct page if needed
                page_for_edge = (i - 1) // 4  # HOT_TIPS_PAGE_SIZE = 4
                nav_msg = current_msg
                for pg in range(page_for_edge):
                    await asyncio.sleep(1)
                    nav_btns = get_inline_buttons(nav_msg)
                    next_btn = [b for b in nav_btns if "hot:page:" in b["data"] and ("Next" in b["text"] or "➡" in b["text"] or "▶" in b["text"])]
                    if next_btn:
                        edited, new_msgs, _ = await click_callback_data(client, nav_msg, next_btn[0]["data"], wait=10)
                        nav_msg = edited if edited and edited.text else nav_msg
                    else:
                        break
                current_msg = nav_msg
            else:
                current_msg = tips_msg

            # Click the edge button
            t0 = time.time()
            edited, new_msgs, elapsed = await click_callback_data(client, current_msg, edge_btn["data"], wait=35)

            # Find the response text
            response_text = ""
            if new_msgs:
                # Check new messages for the narrative
                for nm in new_msgs:
                    if nm.text and len(nm.text) > len(response_text):
                        response_text = nm.text
            if edited and edited.text and len(edited.text) > len(response_text):
                response_text = edited.text

            # Classify
            narrative_type = classify_narrative(response_text)
            meta_leak, meta_details = check_meta_leaks(response_text)
            robotic, robotic_details = check_robotic(response_text)

            # If load time is very short and content is substantial, likely cached
            if elapsed < 2.0 and len(response_text) > 300:
                narrative_type = "AI_CACHED"
            elif elapsed > 8.0 and len(response_text) > 300:
                narrative_type = "AI_LIVE"

            result = {
                "num": i,
                "match": match_name,
                "sport": sport,
                "tier": tier,
                "load_time": round(elapsed, 1),
                "narrative_type": narrative_type,
                "meta_leak": meta_leak,
                "meta_leak_detail": meta_details,
                "robotic": robotic,
                "robotic_detail": robotic_details,
                "full_text": response_text,
                "btn_text": edge_btn["text"],
                "callback_data": edge_btn["data"],
                "text_length": len(response_text),
            }
            EDGE_RESULTS.append(result)

            # Print result
            status = "OK" if narrative_type not in ("NO_RESPONSE", "ERROR", "MINIMAL") else "FAIL"
            leak_flag = " META_LEAK!" if meta_leak else ""
            robo_flag = " ROBOTIC!" if robotic else ""
            print(f"  {elapsed:.1f}s | {narrative_type} | {len(response_text)} chars{leak_flag}{robo_flag}")

            # Save full capture
            capture_path = os.path.join(CAPTURE_DIR, f"edge_{i}_{match_name.replace(' ', '_')[:30]}.txt")
            with open(capture_path, "w") as f:
                f.write(f"Button: {edge_btn['text']}\n")
                f.write(f"Callback: {edge_btn['data']}\n")
                f.write(f"Load time: {elapsed:.1f}s\n")
                f.write(f"Narrative type: {narrative_type}\n")
                f.write(f"Meta leak: {meta_leak} {meta_details}\n")
                f.write(f"Robotic: {robotic} {robotic_details}\n")
                f.write(f"Text length: {len(response_text)} chars\n")
                f.write("=" * 60 + "\n")
                f.write(response_text or "(empty)")

    finally:
        await client.disconnect()

    # ── Summary ──
    print("\n" + "=" * 60)
    print("RESULTS SUMMARY")
    print("=" * 60)

    # Load time distribution
    buckets = {"<1s": 0, "1-3s": 0, "3-10s": 0, "10-30s": 0, "30s+": 0, "No response": 0}
    for r in EDGE_RESULTS:
        t = r["load_time"]
        if r["narrative_type"] == "NO_RESPONSE":
            buckets["No response"] += 1
        elif t < 1:
            buckets["<1s"] += 1
        elif t < 3:
            buckets["1-3s"] += 1
        elif t < 10:
            buckets["3-10s"] += 1
        elif t < 30:
            buckets["10-30s"] += 1
        else:
            buckets["30s+"] += 1

    print("\nLoad Time Distribution:")
    for bucket, count in buckets.items():
        bar = "█" * count
        print(f"  {bucket:>12}: {count} {bar}")

    # Narrative type distribution
    print("\nNarrative Types:")
    type_counts = {}
    for r in EDGE_RESULTS:
        t = r["narrative_type"]
        type_counts[t] = type_counts.get(t, 0) + 1
    for t, c in sorted(type_counts.items()):
        print(f"  {t}: {c}")

    # Meta leaks
    leaks = [r for r in EDGE_RESULTS if r["meta_leak"]]
    print(f"\nMeta Leaks: {len(leaks)}/{len(EDGE_RESULTS)}")
    for r in leaks:
        print(f"  Edge {r['num']} ({r['match']}): {r['meta_leak_detail']}")

    # Robotic patterns
    robos = [r for r in EDGE_RESULTS if r["robotic"]]
    print(f"\nRobotic Patterns: {len(robos)}/{len(EDGE_RESULTS)}")
    for r in robos:
        print(f"  Edge {r['num']} ({r['match']}): {r['robotic_detail']}")

    # Full edge table
    print(f"\n{'=' * 60}")
    print("EDGE TABLE")
    print(f"{'=' * 60}")
    print(f"{'#':>2} | {'Match':<30} | {'Sport':<8} | {'Time':>5} | {'Type':<14} | {'Leak':>4} | {'Robo':>4} | {'Chars':>5}")
    print("-" * 90)
    for r in EDGE_RESULTS:
        leak = "YES" if r["meta_leak"] else "no"
        robo = "YES" if r["robotic"] else "no"
        print(f"{r['num']:>2} | {r['match']:<30} | {r['sport']:<8} | {r['load_time']:>5.1f} | {r['narrative_type']:<14} | {leak:>4} | {robo:>4} | {r['text_length']:>5}")

    # Save full results JSON
    results_path = os.path.join(CAPTURE_DIR, "w78_results.json")
    # Strip full_text from JSON (too large), save separately
    json_results = []
    for r in EDGE_RESULTS:
        jr = dict(r)
        jr["full_text_preview"] = r["full_text"][:200] if r["full_text"] else ""
        del jr["full_text"]
        json_results.append(jr)
    with open(results_path, "w") as f:
        json.dump({"edges": json_results, "load_distribution": buckets,
                    "narrative_types": type_counts, "total_edges": len(EDGE_RESULTS)}, f, indent=2)
    print(f"\nResults saved to {results_path}")


if __name__ == "__main__":
    asyncio.run(main())
