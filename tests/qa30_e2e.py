#!/usr/bin/env python3
"""QA-30: Multi-Sport Telethon E2E Assessment.

Queries the live bot via Telegram for cards across all available sports,
captures verbatim responses, and scores them using the 10-point rubric.
"""
import asyncio
import json
import os
import re
import sys
import time
from datetime import datetime

# Add bot dir to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from telethon import TelegramClient
from telethon.tl.types import (
    ReplyInlineMarkup,
    KeyboardButtonCallback,
    KeyboardButtonUrl,
)

API_ID = int(os.environ["TELEGRAM_API_ID"])
API_HASH = os.environ["TELEGRAM_API_HASH"]
SESSION = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "telethon_qa_session")
BOT_USERNAME = "mzansiedge_bot"

# Template / banned phrases for AC-8
BANNED_PHRASES = [
    "[specific",
    "[team",
    "TBD",
    "pending",
    "placeholder",
    "generic",
    "template",
]

# Results storage
RESULTS = {
    "cards": [],
    "per_sport": {},
    "template_marker_hits": [],
    "cta_issues": [],
    "verdict_issues": [],
    "overall_score": 0,
    "timestamp": datetime.utcnow().isoformat(),
}


async def get_bot_response(client, bot_entity, timeout=30):
    """Send nothing, just wait for latest bot message."""
    await asyncio.sleep(2)
    messages = await client.get_messages(bot_entity, limit=5)
    for msg in messages:
        if msg.sender_id != (await client.get_me()).id:
            return msg
    return None


async def send_and_wait(client, bot_entity, text=None, click_data=None, timeout=45):
    """Send a message or click a button and wait for bot response."""
    me = await client.get_me()

    if text:
        await client.send_message(bot_entity, text)
    elif click_data:
        # Find the message with the button and click it
        messages = await client.get_messages(bot_entity, limit=10)
        for msg in messages:
            if msg.reply_markup and isinstance(msg.reply_markup, ReplyInlineMarkup):
                for row in msg.reply_markup.rows:
                    for btn in row.buttons:
                        if isinstance(btn, KeyboardButtonCallback) and btn.data == click_data:
                            await msg.click(data=click_data)
                            break

    # Wait for response
    start = time.time()
    last_msg_id = None
    messages = await client.get_messages(bot_entity, limit=1)
    if messages:
        last_msg_id = messages[0].id

    while time.time() - start < timeout:
        await asyncio.sleep(2)
        messages = await client.get_messages(bot_entity, limit=5)
        for msg in messages:
            if msg.sender_id != me.id:
                if last_msg_id is None or msg.id > last_msg_id:
                    return msg
                # Also check if existing message was edited
                if msg.id == last_msg_id and msg.edit_date:
                    return msg
        # If first message from bot changed, return it
        for msg in messages:
            if msg.sender_id != me.id:
                return msg

    return None


def extract_buttons(msg):
    """Extract button labels and data from a message."""
    buttons = []
    if msg and msg.reply_markup:
        if isinstance(msg.reply_markup, ReplyInlineMarkup):
            for row in msg.reply_markup.rows:
                for btn in row.buttons:
                    if isinstance(btn, KeyboardButtonCallback):
                        buttons.append({"label": btn.text, "data": btn.data.decode() if isinstance(btn.data, bytes) else btn.data})
                    elif isinstance(btn, KeyboardButtonUrl):
                        buttons.append({"label": btn.text, "url": btn.url})
    return buttons


def scan_banned_phrases(text):
    """Check for template markers / banned phrases."""
    hits = []
    text_lower = text.lower()
    for phrase in BANNED_PHRASES:
        if phrase.lower() in text_lower:
            hits.append(phrase)
    return hits


def classify_card_sport(text):
    """Classify a card's sport from its content."""
    text_lower = text.lower()
    # Cricket indicators
    cricket_teams = ["chennai", "mumbai", "kolkata", "rajasthan", "delhi", "sunrisers",
                     "punjab", "lucknow", "challengers", "titans", "knight riders",
                     "super kings", "ipl", "sa20", "proteas", "wicket", "innings"]
    if any(t in text_lower for t in cricket_teams):
        return "cricket"
    # Rugby indicators
    rugby_teams = ["bulls", "stormers", "sharks", "lions urc", "reds", "force",
                   "crusaders", "chiefs nz", "highlanders", "hurricanes",
                   "springboks", "all blacks", "six nations", "try", "lineout",
                   "super rugby", "urc"]
    if any(t in text_lower for t in rugby_teams):
        return "rugby"
    # MMA/Boxing
    mma_terms = ["ufc", "mma", "boxing", "bout", "round", "knockout", "ko"]
    if any(t in text_lower for t in mma_terms):
        return "mma"
    # Default to soccer
    return "soccer"


def score_card(text, buttons, sport, narrative_source="unknown"):
    """Score a single card on the 10-point rubric.

    1. Edge badge present (💎🥇🥈🥉)
    2. Team names present and correct
    3. Odds line with bookmaker
    4. EV% shown
    5. Narrative richness (w84=full, w82=max 3, template/baseline=max 2)
    6. Section structure (Setup/Edge/Risk/Verdict)
    7. CTA button present with bookmaker
    8. No template markers
    9. Sport-appropriate language
    10. Overall coherence
    """
    score = 0
    notes = []

    # 1. Edge badge
    if any(b in text for b in ["💎", "🥇", "🥈", "🥉"]):
        score += 1
        notes.append("✓ Edge badge present")
    else:
        notes.append("✗ No edge badge")

    # 2. Team names
    if " vs " in text or " v " in text:
        score += 1
        notes.append("✓ Team names present")
    else:
        notes.append("✗ No team names found")

    # 3. Odds line
    if re.search(r'\d+\.\d+', text) and any(b in text.lower() for b in ["hollywoodbets", "betway", "gbets", "supabets", "sportingbet", "playabets"]):
        score += 1
        notes.append("✓ Odds with bookmaker")
    elif re.search(r'\d+\.\d+', text):
        score += 0.5
        notes.append("~ Odds present but no bookmaker name")
    else:
        notes.append("✗ No odds line")

    # 4. EV%
    if re.search(r'EV\s*[+\-]?\d+', text) or re.search(r'\+\d+\.?\d*%', text):
        score += 1
        notes.append("✓ EV% shown")
    else:
        notes.append("✗ No EV%")

    # 5. Narrative richness
    has_setup = "📋" in text or "Setup" in text or "The Setup" in text
    has_edge = "🎯" in text or "The Edge" in text
    has_risk = "⚠️" in text or "The Risk" in text
    has_verdict = "🏆" in text or "Verdict" in text
    sections = sum([has_setup, has_edge, has_risk, has_verdict])

    if narrative_source == "w84" or sections >= 3:
        richness = min(sections, 4) / 4.0 * 2  # Up to 2 points
        notes.append(f"✓ Narrative richness: {sections}/4 sections (w84)")
    elif narrative_source == "w82":
        richness = min(sections, 4) / 4.0 * 1.5  # Max 1.5 for w82
        notes.append(f"~ Narrative richness: {sections}/4 sections (w82, capped at 1.5)")
    else:
        richness = min(sections, 4) / 4.0  # Max 1 for baseline
        notes.append(f"~ Narrative richness: {sections}/4 sections (baseline, capped at 1)")
    score += richness

    # 6. Section structure (already counted in richness, add bonus for completeness)
    if sections == 4:
        score += 1
        notes.append("✓ All 4 sections present")
    elif sections >= 2:
        score += 0.5
        notes.append(f"~ {sections}/4 sections")
    else:
        notes.append("✗ Poor section structure")

    # 7. CTA button
    has_cta = any("bet" in (b.get("label", "") + b.get("url", "")).lower() or
                   "back" in b.get("label", "").lower() or
                   "subscribe" in b.get("label", "").lower()
                   for b in buttons)
    if has_cta:
        score += 1
        notes.append("✓ CTA button present")
    else:
        notes.append("✗ No CTA button")

    # 8. No template markers
    banned_hits = scan_banned_phrases(text)
    if not banned_hits:
        score += 1
        notes.append("✓ No template markers")
    else:
        notes.append(f"✗ Template markers found: {banned_hits}")

    # 9. Sport-appropriate language
    wrong_sport = False
    if sport == "cricket":
        soccer_terms = ["clean sheet", "penalty kick", "offside", "corner kick"]
        if any(t in text.lower() for t in soccer_terms):
            wrong_sport = True
    elif sport == "soccer":
        rugby_terms = ["try line", "lineout", "scrum penalty", "maul"]
        if any(t in text.lower() for t in rugby_terms):
            wrong_sport = True
    if not wrong_sport:
        score += 1
        notes.append("✓ Sport-appropriate language")
    else:
        notes.append("✗ Wrong-sport terminology detected")

    # 10. Overall coherence (manual assessment proxy)
    if len(text) > 200 and sections >= 2 and not banned_hits:
        score += 1
        notes.append("✓ Overall coherence (sufficient length + structure)")
    elif len(text) > 100:
        score += 0.5
        notes.append("~ Moderate coherence")
    else:
        notes.append("✗ Too short or incoherent")

    return round(score, 1), notes


def check_cta_consistency(text, buttons):
    """Check CTA and verdict team consistency."""
    issues = []
    # Extract team names from the header
    teams_match = re.search(r'(?:🎯|⚽|🏉|🏏|🥊)\s*(.+?)\s*vs?\s*(.+?)(?:\n|$)', text)
    if teams_match:
        home = teams_match.group(1).strip()
        away = teams_match.group(2).strip()

        # Check verdict mentions a real team
        verdict_match = re.search(r'(?:🏆|Verdict).*?(?:Back|back)\s+(.+?)(?:\s+@|\s+→|$)', text)
        if verdict_match:
            verdict_team = verdict_match.group(1).strip()
            # Verdict team should be one of home/away or "Draw"
            if not any(t.lower() in verdict_team.lower() for t in [home, away, "draw", "home", "away"]):
                issues.append(f"Verdict team '{verdict_team}' doesn't match {home}/{away}")

        # Check CTA button references correct bookmaker
        for btn in buttons:
            label = btn.get("label", "")
            if "bet on" in label.lower() or "back" in label.lower():
                # Should have a bookmaker name
                bk_names = ["hollywoodbets", "betway", "gbets", "supabets", "sportingbet", "playabets"]
                if not any(bk in label.lower() for bk in bk_names):
                    if "subscribe" not in label.lower() and "plan" not in label.lower():
                        issues.append(f"CTA button '{label}' missing bookmaker name")

    return issues


async def run_qa():
    """Run full QA-30 E2E assessment."""
    print("=" * 60)
    print("QA-30: Multi-Sport Telethon E2E Assessment")
    print("=" * 60)

    client = TelegramClient(SESSION, API_ID, API_HASH)
    await client.start()
    bot_entity = await client.get_entity(BOT_USERNAME)
    print(f"\nConnected to @{BOT_USERNAME}")

    # ── Step 1: Get Hot Tips (Top Edge Picks) ──
    print("\n--- Step 1: Fetching Top Edge Picks ---")
    msg = await send_and_wait(client, bot_entity, text="💎 Top Edge Picks")
    if not msg:
        msg = await send_and_wait(client, bot_entity, text="🔥 Hot Tips")

    if msg:
        print(f"  Got response: {len(msg.text)} chars")
        tips_text = msg.text
        tips_buttons = extract_buttons(msg)

        # Store the list view
        RESULTS["hot_tips_list"] = {
            "text": tips_text,
            "buttons": [b.get("label", "") for b in tips_buttons],
            "char_count": len(tips_text),
        }

        # Find all edge:detail buttons to tap into individual cards
        detail_buttons = [b for b in tips_buttons if "edge:detail:" in b.get("data", "")]
        print(f"  Found {len(detail_buttons)} edge detail buttons")

        # Also check for pagination
        page_buttons = [b for b in tips_buttons if "hot:page:" in b.get("data", "")]
        if page_buttons:
            print(f"  Found {len(page_buttons)} pagination buttons")
    else:
        print("  WARNING: No response from Hot Tips")
        tips_text = ""
        detail_buttons = []

    # ── Step 2: Tap into each card ──
    print("\n--- Step 2: Tapping into individual cards ---")
    cards_assessed = []

    for i, btn in enumerate(detail_buttons[:10]):  # Cap at 10 cards
        match_key = btn.get("data", "").replace("edge:detail:", "")
        print(f"\n  [{i+1}] Tapping: {btn.get('label', 'unknown')[:50]}...")

        try:
            # Click the button
            messages = await client.get_messages(bot_entity, limit=10)
            clicked = False
            for m in messages:
                if m.reply_markup and isinstance(m.reply_markup, ReplyInlineMarkup):
                    for row in m.reply_markup.rows:
                        for b in row.buttons:
                            if isinstance(b, KeyboardButtonCallback):
                                btn_data = b.data.decode() if isinstance(b.data, bytes) else b.data
                                if btn_data == btn.get("data"):
                                    await m.click(data=b.data)
                                    clicked = True
                                    break
                        if clicked:
                            break
                if clicked:
                    break

            if not clicked:
                print(f"    Could not find button to click")
                continue

            # Wait for response
            await asyncio.sleep(5)
            messages = await client.get_messages(bot_entity, limit=5)
            detail_msg = None
            for m in messages:
                if m.sender_id != (await client.get_me()).id:
                    detail_msg = m
                    break

            if not detail_msg:
                print(f"    No response received")
                continue

            detail_text = detail_msg.text or ""
            detail_buttons_list = extract_buttons(detail_msg)

            # Classify sport
            sport = classify_card_sport(detail_text)

            # Detect narrative source
            if "📋" in detail_text and "🎯" in detail_text and "⚠️" in detail_text and "🏆" in detail_text:
                narrative_source = "w84"
            elif "📋" in detail_text or "🎯" in detail_text:
                narrative_source = "w82"
            else:
                narrative_source = "baseline"

            # Score the card
            card_score, card_notes = score_card(detail_text, detail_buttons_list, sport, narrative_source)

            # Check CTA consistency
            cta_issues = check_cta_consistency(detail_text, detail_buttons_list)

            # Check template markers
            banned_hits = scan_banned_phrases(detail_text)

            card = {
                "index": i + 1,
                "match_key": match_key,
                "sport": sport,
                "narrative_source": narrative_source,
                "score": card_score,
                "notes": card_notes,
                "text": detail_text,
                "buttons": [b.get("label", "") for b in detail_buttons_list],
                "char_count": len(detail_text),
                "banned_hits": banned_hits,
                "cta_issues": cta_issues,
            }

            cards_assessed.append(card)
            RESULTS["cards"].append(card)

            if banned_hits:
                RESULTS["template_marker_hits"].extend(banned_hits)
            if cta_issues:
                RESULTS["cta_issues"].extend(cta_issues)

            print(f"    Sport: {sport} | Source: {narrative_source} | Score: {card_score}/10 | Chars: {len(detail_text)}")

            # Navigate back
            await asyncio.sleep(2)
            back_btns = [b for b in detail_buttons_list if "back" in b.get("label", "").lower() or "hot:back" in b.get("data", "")]
            if back_btns:
                messages = await client.get_messages(bot_entity, limit=5)
                for m in messages:
                    if m.reply_markup and isinstance(m.reply_markup, ReplyInlineMarkup):
                        for row in m.reply_markup.rows:
                            for b in row.buttons:
                                if isinstance(b, KeyboardButtonCallback):
                                    bd = b.data.decode() if isinstance(b.data, bytes) else b.data
                                    if "hot:back" in bd or "edge" in bd:
                                        try:
                                            await m.click(data=b.data)
                                        except Exception:
                                            pass
                                        break
                await asyncio.sleep(3)

        except Exception as e:
            print(f"    ERROR: {e}")
            cards_assessed.append({
                "index": i + 1,
                "match_key": match_key,
                "sport": "unknown",
                "error": str(e),
                "score": 0,
            })

    # ── Step 3: Try My Matches for additional sport cards ──
    print("\n--- Step 3: Checking My Matches ---")
    msg = await send_and_wait(client, bot_entity, text="⚽ My Matches")
    if not msg:
        msg = await send_and_wait(client, bot_entity, text="⚽ Your Games")

    if msg:
        mm_text = msg.text or ""
        print(f"  My Matches response: {len(mm_text)} chars")
        RESULTS["my_matches"] = {
            "text": mm_text,
            "char_count": len(mm_text),
        }

    # ── Compile Results ──
    print("\n" + "=" * 60)
    print("QA-30 RESULTS SUMMARY")
    print("=" * 60)

    # Per-sport breakdown
    sport_breakdown = {}
    for card in cards_assessed:
        sport = card.get("sport", "unknown")
        if sport not in sport_breakdown:
            sport_breakdown[sport] = {"count": 0, "scores": [], "sources": {}}
        sport_breakdown[sport]["count"] += 1
        if "score" in card:
            sport_breakdown[sport]["scores"].append(card["score"])
        src = card.get("narrative_source", "unknown")
        sport_breakdown[sport]["sources"][src] = sport_breakdown[sport]["sources"].get(src, 0) + 1

    RESULTS["per_sport"] = sport_breakdown

    print("\nPer-Sport Breakdown:")
    print(f"  {'Sport':<12} | {'Cards':>5} | {'Avg Score':>9} | {'Sources'}")
    print(f"  {'-'*12}-+-{'-'*5}-+-{'-'*9}-+-{'-'*30}")
    for sport, data in sorted(sport_breakdown.items()):
        avg = sum(data["scores"]) / len(data["scores"]) if data["scores"] else 0
        sources_str = ", ".join(f"{k}:{v}" for k, v in data["sources"].items())
        print(f"  {sport:<12} | {data['count']:>5} | {avg:>8.1f} | {sources_str}")

    # Overall score
    all_scores = [c["score"] for c in cards_assessed if "score" in c]
    overall = sum(all_scores) / len(all_scores) if all_scores else 0
    RESULTS["overall_score"] = round(overall, 1)

    print(f"\nOverall QA-30 Score: {overall:.1f}/10")
    print(f"Total Cards Assessed: {len(cards_assessed)}")
    print(f"Template Marker Hits: {len(RESULTS['template_marker_hits'])}")
    print(f"CTA Issues: {len(RESULTS['cta_issues'])}")

    # Template ratio
    template_count = sum(1 for c in cards_assessed if c.get("narrative_source") in ("baseline", "w82"))
    if cards_assessed:
        template_pct = template_count / len(cards_assessed) * 100
        print(f"Template/Baseline Cards: {template_count}/{len(cards_assessed)} ({template_pct:.0f}%)")
        if template_pct > 10:
            print("  ⚠️ FLAG: >10% template-rendered cards — pipeline issue")

    await client.disconnect()
    return RESULTS


if __name__ == "__main__":
    results = asyncio.run(run_qa())

    # Save results
    outpath = "/home/paulsportsza/reports/qa30_results.json"
    with open(outpath, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to {outpath}")
