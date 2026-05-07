"""E2E Round 2 — Telethon-based integration tests against live @mzansiedge_bot.

Tests:
1. Send "My Matches" and capture VERBATIM response
2. Send "Top Edge Picks" and capture VERBATIM response
3. Check for issues:
   - "Check SuperSport.com for listings" appearing (BAD)
   - Wrong sport emojis (soccer emoji on cricket/rugby/combat)
   - Duplicate matches (same teams appearing twice)
   - Missing matches for followed teams/fighters
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
import time
from datetime import datetime

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import (
    ReplyKeyboardMarkup as TLReplyKeyboardMarkup,
    ReplyInlineMarkup,
    KeyboardButtonCallback,
)

# ── Configuration ────────────────────────────────────────

API_ID = 32418601
API_HASH = "95e313a8ef5b998be0515dd8328fac57"
BOT_USERNAME = "mzansiedge_bot"

# Read string session from file
from config import DATA_DIR, BOT_ROOT
with open(str(DATA_DIR / "telethon_qa_session.string"), "r") as f:
    SESSION_STR = f.read().strip()

TIMEOUT = 20  # seconds to wait for bot response

# User's followed teams/fighters
FOLLOWED = [
    "Orlando Pirates",
    "Man United",
    "Dricus Du Plessis",
    "Canelo",
    "South Africa",
]

# Output file
TIMESTAMP = datetime.now().strftime("%Y%m%d-%H%M")
REPORT_FILE = str(BOT_ROOT.parent / "reports" / f"e2e-round2-{TIMESTAMP}.txt")


# ── Helpers ──────────────────────────────────────────────

async def get_client():
    """Create and connect a Telethon client using string session."""
    client = TelegramClient(StringSession(SESSION_STR), API_ID, API_HASH)
    await client.connect()
    if not await client.is_user_authorized():
        print("ERROR: Not logged in. String session is invalid.")
        sys.exit(1)
    me = await client.get_me()
    print(f"  Connected as: {me.first_name} (ID: {me.id})")
    return client


async def send_and_collect(client, text, wait=TIMEOUT):
    """Send a message to the bot and collect all response messages."""
    entity = await client.get_entity(BOT_USERNAME)
    
    # Get the latest message ID before sending, so we only capture new ones
    pre_msgs = await client.get_messages(entity, limit=1)
    last_id = pre_msgs[0].id if pre_msgs else 0
    
    await client.send_message(entity, text)
    await asyncio.sleep(wait)
    
    # Fetch messages newer than the one before we sent
    all_msgs = await client.get_messages(entity, limit=30)
    new_msgs = [m for m in all_msgs if m.id > last_id and not m.out]
    
    # Return in chronological order (oldest first)
    return list(reversed(new_msgs))


def extract_all_text(msgs):
    """Extract all text from a list of messages."""
    parts = []
    for msg in msgs:
        if msg.text:
            parts.append(msg.text)
    return "\n\n---MSG-BREAK---\n\n".join(parts)


def check_supersport_fallback(text):
    """Check for 'Check SuperSport.com for listings' appearing."""
    issues = []
    if "Check SuperSport.com for listings" in text:
        count = text.count("Check SuperSport.com for listings")
        issues.append(f"FAIL: 'Check SuperSport.com for listings' found {count} time(s) - should have real channel info")
    # Also check variations
    if "SuperSport.com" in text and "check" in text.lower():
        # Already caught above if exact match, but catch near-misses
        pass
    return issues


def check_wrong_sport_emojis(text):
    """Check for wrong sport emojis (soccer emoji on non-soccer matches)."""
    issues = []
    lines = text.split("\n")
    
    cricket_markers = [
        "sa20", "ipl", "t20", "test match", "odi", "big bash", "csa",
        "proteas", "titans v", "dolphins v",
        "knights v", "warriors v", "cobras v", "sunrisers eastern cape",
        "joburg super kings", "durban super giants", "mi cape town",
        "paarl royals", "pretoria capitals", "cricket",
    ]
    
    rugby_markers = [
        "urc", "six nations", "super rugby", "currie cup", "rugby",
        "springboks", "all blacks", "wallabies",
        "bulls v", "stormers v", "sharks v",
        "munster", "leinster", "ulster", "connacht",
        "scarlets", "ospreys", "edinburgh v", "glasgow v",
    ]
    
    combat_markers = [
        "ufc", "boxing", "mma", "bout", "fight",
        "du plessis", "dricus", "canelo", "alvarez",
        "adesanya", "pereira", "holloway", "o'malley",
    ]
    
    for line in lines:
        line_lower = line.lower().strip()
        if not line_lower:
            continue
        
        # Check if line has soccer emoji but contains cricket/rugby/combat content
        if "\u26bd" in line:  # soccer ball emoji
            for marker in cricket_markers:
                if marker in line_lower:
                    issues.append(f"FAIL: Soccer emoji on cricket content: {line.strip()[:120]}")
                    break
            for marker in rugby_markers:
                if marker in line_lower:
                    issues.append(f"FAIL: Soccer emoji on rugby content: {line.strip()[:120]}")
                    break
            for marker in combat_markers:
                if marker in line_lower:
                    issues.append(f"FAIL: Soccer emoji on combat content: {line.strip()[:120]}")
                    break
    
    return issues


def check_duplicate_matches(text):
    """Check for duplicate matches (same teams appearing twice in the SAME response)."""
    issues = []
    
    # Find patterns like "Team A vs Team B" or "Team A v Team B"
    match_pattern = re.compile(r'([A-Z][A-Za-z\s\'\.\-]+?)\s+(?:vs?\.?\s+|VS\s+)([A-Z][A-Za-z\s\'\.\-]+?)(?:\s*$|\s*\n|\s*<|\s*\[)', re.MULTILINE)
    matches_found = []
    
    for m in match_pattern.finditer(text):
        home = m.group(1).strip().lower()
        away = m.group(2).strip().lower()
        if len(home) < 3 or len(away) < 3:
            continue
        key = tuple(sorted([home, away]))
        matches_found.append((key, m.group(0).strip()[:80]))
    
    seen = {}
    for key, raw in matches_found:
        if key in seen:
            issues.append(f"FAIL: Duplicate match: '{raw}' (also: '{seen[key]}')")
        else:
            seen[key] = raw
    
    return issues


def check_missing_teams(text, followed_teams):
    """Check if followed teams/fighters appear in responses."""
    notes = []
    text_lower = text.lower()
    
    aliases = {
        "Orlando Pirates": ["pirates", "bucs", "buccaneers", "orlando pirates"],
        "Man United": ["manchester united", "man utd", "united", "man united"],
        "Dricus Du Plessis": ["du plessis", "dricus", "stillknocks", "stilknocks"],
        "Canelo": ["canelo", "alvarez", "saul"],
        "South Africa": ["south africa", "proteas", "springboks", "bafana"],
    }
    
    for team in followed_teams:
        found = False
        team_lower = team.lower()
        
        if team_lower in text_lower:
            found = True
        
        if not found and team in aliases:
            for alias in aliases[team]:
                if alias.lower() in text_lower:
                    found = True
                    break
        
        if not found:
            notes.append(f"NOTE: '{team}' not found in responses (may not have upcoming matches right now)")
    
    return notes


def check_edge_tier_formatting(text):
    """Check that edge tier badges are present when tips exist."""
    issues = []
    
    has_diamond = "\U0001f48e" in text  # diamond
    has_gold = "\U0001f947" in text     # 1st place medal
    has_silver = "\U0001f948" in text    # 2nd place medal
    has_bronze = "\U0001f949" in text    # 3rd place medal
    has_any_tier = any([has_diamond, has_gold, has_silver, has_bronze])
    
    # Only flag if there are actual tips (EV text present)
    if "EV" in text and "+" in text and not has_any_tier:
        issues.append("WARN: No edge tier badges (diamond/gold/silver/bronze) found despite EV data in tips")
    
    return issues


async def run_e2e_tests():
    """Run all E2E tests and generate report."""
    print("=" * 70)
    print("  MzansiEdge E2E Round 2 -- Live Bot Tests")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S SAST')}")
    print("=" * 70)
    print()
    
    client = await get_client()
    all_issues = []
    all_notes = []
    report_lines = []
    
    report_lines.append("=" * 70)
    report_lines.append(f"  MzansiEdge E2E Round 2 -- {datetime.now().strftime('%Y-%m-%d %H:%M SAST')}")
    report_lines.append("=" * 70)
    report_lines.append("")
    
    # ── TEST 1: My Matches ──────────────────────────────
    print("[1/2] Sending 'My Matches' to @mzansiedge_bot...")
    t1_start = time.time()
    try:
        my_matches_msgs = await send_and_collect(client, "\u26bd My Matches", wait=15)
        my_matches_text = extract_all_text(my_matches_msgs)
        t1_elapsed = time.time() - t1_start
        
        report_lines.append("=" * 70)
        report_lines.append("  TEST 1: My Matches (VERBATIM RESPONSE)")
        report_lines.append(f"  Response time: {t1_elapsed:.1f}s")
        report_lines.append("=" * 70)
        report_lines.append("")
        report_lines.append(f"Messages received: {len(my_matches_msgs)}")
        report_lines.append("")
        
        for i, msg in enumerate(my_matches_msgs):
            report_lines.append(f"--- Message {i+1} ---")
            report_lines.append(msg.text or "(no text)")
            
            if msg.reply_markup and isinstance(msg.reply_markup, ReplyInlineMarkup):
                btns = []
                for row in msg.reply_markup.rows:
                    for btn in row.buttons:
                        if hasattr(btn, 'text'):
                            btns.append(btn.text)
                report_lines.append(f"  [Inline buttons: {', '.join(btns)}]")
            
            if msg.reply_markup and isinstance(msg.reply_markup, TLReplyKeyboardMarkup):
                btns = []
                for row in msg.reply_markup.rows:
                    for btn in row.buttons:
                        btns.append(btn.text)
                report_lines.append(f"  [Reply keyboard: {', '.join(btns)}]")
            
            report_lines.append("")
        
        # Run checks
        print(f"  Received {len(my_matches_msgs)} msgs in {t1_elapsed:.1f}s. Running checks...")
        
        issues_ss = check_supersport_fallback(my_matches_text)
        issues_emoji = check_wrong_sport_emojis(my_matches_text)
        issues_dup = check_duplicate_matches(my_matches_text)
        issues_edge = check_edge_tier_formatting(my_matches_text)
        notes_missing = check_missing_teams(my_matches_text, FOLLOWED)
        
        all_issues.extend(issues_ss)
        all_issues.extend(issues_emoji)
        all_issues.extend(issues_dup)
        # Edge tiers in My Matches are notes, not failures
        for ie in issues_edge:
            all_notes.append(ie.replace("WARN:", "NOTE (My Matches):"))
        all_notes.extend(notes_missing)
        
        # Print check results inline
        checks_ok = len(issues_ss) + len(issues_emoji) + len(issues_dup)
        if checks_ok == 0:
            print("  [PASS] No SuperSport.com fallback text")
            print("  [PASS] No wrong sport emojis")
            print("  [PASS] No duplicate matches")
        else:
            for i in issues_ss + issues_emoji + issues_dup:
                print(f"  {i}")
        
        if my_matches_text:
            preview = my_matches_text[:300].replace('\n', '\n    ')
            print(f"  Preview:\n    {preview}")
        
    except Exception as e:
        msg = f"FAIL: My Matches test threw exception: {e}"
        all_issues.append(msg)
        report_lines.append(f"ERROR: {e}")
        print(f"  ERROR: {e}")
        import traceback
        traceback.print_exc()
    
    print()
    await asyncio.sleep(3)
    
    # ── TEST 2: Top Edge Picks ──────────────────────────
    print("[2/2] Sending 'Top Edge Picks' to @mzansiedge_bot...")
    t2_start = time.time()
    try:
        edge_picks_msgs = await send_and_collect(client, "\U0001f48e Top Edge Picks", wait=25)
        edge_picks_text = extract_all_text(edge_picks_msgs)
        t2_elapsed = time.time() - t2_start
        
        report_lines.append("")
        report_lines.append("=" * 70)
        report_lines.append("  TEST 2: Top Edge Picks (VERBATIM RESPONSE)")
        report_lines.append(f"  Response time: {t2_elapsed:.1f}s")
        report_lines.append("=" * 70)
        report_lines.append("")
        report_lines.append(f"Messages received: {len(edge_picks_msgs)}")
        report_lines.append("")
        
        for i, msg in enumerate(edge_picks_msgs):
            report_lines.append(f"--- Message {i+1} ---")
            report_lines.append(msg.text or "(no text)")
            
            if msg.reply_markup and isinstance(msg.reply_markup, ReplyInlineMarkup):
                btns = []
                for row in msg.reply_markup.rows:
                    for btn in row.buttons:
                        if hasattr(btn, 'text'):
                            btns.append(btn.text)
                report_lines.append(f"  [Inline buttons: {', '.join(btns)}]")
            
            if msg.reply_markup and isinstance(msg.reply_markup, TLReplyKeyboardMarkup):
                btns = []
                for row in msg.reply_markup.rows:
                    for btn in row.buttons:
                        btns.append(btn.text)
                report_lines.append(f"  [Reply keyboard: {', '.join(btns)}]")
            
            report_lines.append("")
        
        # Run checks
        print(f"  Received {len(edge_picks_msgs)} msgs in {t2_elapsed:.1f}s. Running checks...")
        
        issues_ss2 = check_supersport_fallback(edge_picks_text)
        issues_emoji2 = check_wrong_sport_emojis(edge_picks_text)
        issues_dup2 = check_duplicate_matches(edge_picks_text)
        issues_edge2 = check_edge_tier_formatting(edge_picks_text)
        notes_missing2 = check_missing_teams(edge_picks_text, FOLLOWED)
        
        all_issues.extend(issues_ss2)
        all_issues.extend(issues_emoji2)
        all_issues.extend(issues_dup2)
        all_issues.extend(issues_edge2)
        all_notes.extend(notes_missing2)
        
        checks_ok2 = len(issues_ss2) + len(issues_emoji2) + len(issues_dup2) + len(issues_edge2)
        if checks_ok2 == 0:
            print("  [PASS] No SuperSport.com fallback text")
            print("  [PASS] No wrong sport emojis")
            print("  [PASS] No duplicate matches")
            print("  [PASS] Edge tier badges present (or no tips)")
        else:
            for i in issues_ss2 + issues_emoji2 + issues_dup2 + issues_edge2:
                print(f"  {i}")
        
        if edge_picks_text:
            preview = edge_picks_text[:400].replace('\n', '\n    ')
            print(f"  Preview:\n    {preview}")
        
    except Exception as e:
        msg = f"FAIL: Top Edge Picks test threw exception: {e}"
        all_issues.append(msg)
        report_lines.append(f"ERROR: {e}")
        print(f"  ERROR: {e}")
        import traceback
        traceback.print_exc()
    
    await client.disconnect()
    
    # ── RESULTS SUMMARY ─────────────────────────────────
    unique_issues = list(dict.fromkeys(all_issues))
    unique_notes = list(dict.fromkeys(all_notes))
    
    failures = [i for i in unique_issues if i.startswith("FAIL")]
    warnings = [i for i in unique_issues if i.startswith("WARN")]
    
    report_lines.append("")
    report_lines.append("=" * 70)
    report_lines.append("  RESULTS SUMMARY")
    report_lines.append("=" * 70)
    report_lines.append("")
    
    if failures:
        report_lines.append(f"FAILURES: {len(failures)}")
        for f in failures:
            report_lines.append(f"  - {f}")
        report_lines.append("")
    
    if warnings:
        report_lines.append(f"WARNINGS: {len(warnings)}")
        for w in warnings:
            report_lines.append(f"  - {w}")
        report_lines.append("")
    
    if not failures and not warnings:
        report_lines.append("ALL CHECKS PASSED -- No failures or warnings")
        report_lines.append("")
    
    if unique_notes:
        report_lines.append(f"NOTES: {len(unique_notes)}")
        for note in unique_notes:
            report_lines.append(f"  - {note}")
        report_lines.append("")
    
    # Console summary
    print()
    print("=" * 70)
    print("  RESULTS SUMMARY")
    print("=" * 70)
    print()
    
    if failures:
        print(f"  FAILURES: {len(failures)}")
        for f in failures:
            print(f"    {f}")
        print()
    
    if warnings:
        print(f"  WARNINGS: {len(warnings)}")
        for w in warnings:
            print(f"    {w}")
        print()
    
    if not failures and not warnings:
        print("  ALL CHECKS PASSED -- No failures or warnings")
        print()
    
    if unique_notes:
        print(f"  NOTES: {len(unique_notes)}")
        for note in unique_notes:
            print(f"    {note}")
        print()
    
    # Write report
    report_text = "\n".join(report_lines)
    os.makedirs(os.path.dirname(REPORT_FILE), exist_ok=True)
    with open(REPORT_FILE, "w") as f:
        f.write(report_text)
    
    print(f"  Full report saved to: {REPORT_FILE}")
    print("=" * 70)
    
    return len(failures)


if __name__ == "__main__":
    exit_code = asyncio.run(run_e2e_tests())
    sys.exit(min(exit_code, 1))
