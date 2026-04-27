#!/usr/bin/env python3
"""FIX-NARRATIVE-MMA-LORE-01 Telethon QA — combat-lore phrase scan.

Validates that polish-time gate 8e (combat-sport lore phrase ban) is enforced
on regenerated narratives for invalidated combat-sport cache rows.

Steps:
  1. /qa set_diamond (admin unlock)
  2. /qa reset cache state (defensive)
  3. Send /start with deeplink card_<match_key> -> tap "🤖 Full AI Breakdown"
     (or alternatively tap edge:detail:<match_key> button after /picks)
  4. Capture VERBATIM message body (Setup, Edge, Risk, Verdict)
  5. Save PNG (if photo) + TXT dump to /home/paulsportsza/reports/e2e-screenshots/
  6. Dump regenerated narrative_html from narrative_cache for dual-source evidence
  7. Scan all 23 banned phrases (case-insensitive, word-boundary where applicable)
  8. PASS iff zero banned-phrase hits
"""
from __future__ import annotations

import asyncio
import os
import re
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv("/home/paulsportsza/bot/.env")
sys.path.insert(0, "/home/paulsportsza/bot")

from telethon import TelegramClient
from telethon.sessions import StringSession

API_ID = int(os.getenv("TELEGRAM_API_ID", "32418601"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "95e313a8ef5b998be0515dd8328fac57")
STRING_SESSION_FILE = "/home/paulsportsza/bot/data/telethon_session.string"
BOT_USERNAME = "mzansiedge_bot"
ODDS_DB = "/home/paulsportsza/scrapers/odds.db"

EVIDENCE_DIR = Path("/home/paulsportsza/reports/e2e-screenshots")
EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

# Target match (active combat fixture, cache invalidated 2026-04-27 13:32 UTC)
TARGET_MATCH_KEY = "gaziev_shamil_vs_pericic_brando_2026-05-02"
TARGET_COMMENCE = "2026-05-02"

# All 23 banned phrases per FIX-NARRATIVE-MMA-LORE-01 brief.
# Word-boundary anchored where applicable (case-insensitive).
BANNED_PHRASES = [
    "historically",
    "in combat sports",
    "psychological and logistical advantages",
    "championship-level mma",
    "inherent unpredictability of mma",
    "challenger's mentality",
    "the promotion's ruleset",
    "submission vulnerability",
    "fight-night adjustments",
    "double-edged sword",
    "the fight game",
    "warrior spirit",
    "warrior's heart",
    "the heart of a champion",
    "bread and butter",
    "check the ledger",
    "the division reads",
    "in his prime",
    "in their prime",
    "prime years",
    "old guard",
    "changing of the guard",
    "in the fight business",
]


def _build_phrase_pattern(phrase: str) -> re.Pattern:
    """Build case-insensitive word-boundary regex for a banned phrase.

    Apostrophes inside contractions (e.g. "challenger's") are matched literally.
    Hyphens and spaces are matched as-is (no \b around hyphens since \b
    treats hyphen as boundary).
    """
    # Escape special chars then anchor with word boundaries on alpha sides
    escaped = re.escape(phrase)
    return re.compile(rf"\b{escaped}\b", re.IGNORECASE)


_PHRASE_PATTERNS = [(p, _build_phrase_pattern(p)) for p in BANNED_PHRASES]


def _session() -> StringSession:
    with open(STRING_SESSION_FILE) as f:
        return StringSession(f.read().strip())


def _strip_html(html: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " ")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _scan_banned(text: str) -> dict[str, int]:
    """Return per-phrase hit count (case-insensitive, word-boundary)."""
    hits: dict[str, int] = {}
    for phrase, pattern in _PHRASE_PATTERNS:
        matches = pattern.findall(text)
        hits[phrase] = len(matches)
    return hits


async def _wait_for_new_message(client, last_id: int, timeout: float = 90.0,
                                require_section_marker: bool = False):
    """Wait for a NEW non-outgoing message from the bot after last_id."""
    deadline = time.time() + timeout
    candidate = None
    while time.time() < deadline:
        async for msg in client.iter_messages(BOT_USERNAME, limit=10):
            if msg.id > last_id and not msg.out:
                text = msg.text or msg.message or ""
                if require_section_marker:
                    if any(s in text for s in ("📋", "🎯", "The Setup", "The Edge", "🏆")):
                        return msg
                else:
                    if candidate is None or msg.id > candidate.id:
                        candidate = msg
        if candidate is not None and not require_section_marker:
            return candidate
        await asyncio.sleep(0.8)
    return candidate


async def _send_text(client, text: str, timeout: float = 30.0,
                     require_section_marker: bool = False):
    last = await client.get_messages(BOT_USERNAME, limit=1)
    last_id = last[0].id if last else 0
    await client.send_message(BOT_USERNAME, text)
    await asyncio.sleep(1.5)
    return await _wait_for_new_message(client, last_id, timeout=timeout,
                                       require_section_marker=require_section_marker)


async def _click_button_matching(client, message, pattern: str, timeout: float = 120.0):
    """Click first button whose text matches `pattern`, return resulting message."""
    if not message or not message.buttons:
        return None
    for row in message.buttons:
        for btn in row:
            if re.search(pattern, btn.text or "", re.IGNORECASE):
                last = await client.get_messages(BOT_USERNAME, limit=1)
                last_id = last[0].id if last else 0
                original_msg_id = message.id
                original_edit_date = message.edit_date
                await btn.click()
                await asyncio.sleep(2.0)

                deadline = time.time() + timeout
                substantive_msg = None
                fallback_msg = None
                while time.time() < deadline:
                    msgs = await client.get_messages(BOT_USERNAME, limit=10)
                    for m in msgs:
                        if m.out:
                            continue
                        text = m.text or m.message or ""
                        is_substantive = any(s in text for s in
                                             ("📋", "🎯", "The Setup", "The Edge", "🏆"))
                        if m.id > last_id:
                            if is_substantive:
                                substantive_msg = m
                                break
                            elif fallback_msg is None:
                                fallback_msg = m
                        elif m.id == original_msg_id:
                            if m.edit_date != original_edit_date:
                                if is_substantive:
                                    substantive_msg = m
                                    break
                                elif fallback_msg is None:
                                    fallback_msg = m
                    if substantive_msg is not None:
                        break
                    await asyncio.sleep(1.0)
                return substantive_msg or fallback_msg
    return None


def _read_cache(match_id: str) -> dict | None:
    try:
        conn = sqlite3.connect(ODDS_DB, timeout=5.0)
        cur = conn.cursor()
        cur.execute(
            "SELECT narrative_html, expires_at, created_at, narrative_source "
            "FROM narrative_cache WHERE match_id = ?",
            (match_id,),
        )
        row = cur.fetchone()
        conn.close()
        if not row:
            return None
        return {
            "narrative_html": row[0],
            "expires_at": row[1],
            "created_at": row[2],
            "narrative_source": row[3],
        }
    except Exception as e:
        return {"error": str(e)}


async def main() -> int:
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    print(f"\n=== FIX-NARRATIVE-MMA-LORE-01 Telethon QA ({ts}) ===")
    print(f"Bot: @{BOT_USERNAME}")
    print(f"Match: {TARGET_MATCH_KEY}")
    print(f"Evidence: {EVIDENCE_DIR}\n")

    # Pre-check cache invalidation
    pre_cache = _read_cache(TARGET_MATCH_KEY)
    if pre_cache and "error" not in pre_cache:
        print(f"Pre-tap cache row exists. expires_at={pre_cache.get('expires_at')}")

    # Bot runtime sanity
    ps_out = subprocess.run(
        ["bash", "-c", "ps aux | grep '[b]ot.py' | head -3"],
        capture_output=True, text=True
    )
    print(f"Runtime ps: {ps_out.stdout.strip()}\n")

    captured_text = ""
    captured_path_png = None
    captured_msg_id = None
    used_path = ""

    async with TelegramClient(_session(), API_ID, API_HASH) as client:
        me = await client.get_me()
        print(f"Connected as: {me.first_name} (id={me.id})\n")

        # Step 1: Set diamond tier (full unlocked access)
        print("STEP 1 — /qa set_diamond")
        m_qa = await _send_text(client, "/qa set_diamond", timeout=15.0)
        print(f"  qa response (first 150): {((m_qa.text or m_qa.message or '')[:150]) if m_qa else '(none)'}\n")

        # Step 2: Try deeplink card flow
        print(f"STEP 2 — /start card_{TARGET_MATCH_KEY}")
        last = await client.get_messages(BOT_USERNAME, limit=1)
        last_id = last[0].id if last else 0
        await client.send_message(BOT_USERNAME, f"/start card_{TARGET_MATCH_KEY}")
        await asyncio.sleep(2.0)

        m_card = await _wait_for_new_message(client, last_id, timeout=60.0,
                                             require_section_marker=False)

        if m_card:
            text_card = m_card.text or m_card.message or ""
            print(f"  card response msg_id={m_card.id} is_photo={bool(m_card.photo)} "
                  f"len={len(text_card)} buttons={bool(m_card.buttons)}")

            # Save card PNG if photo
            if m_card.photo:
                png_path = EVIDENCE_DIR / f"FIX-NARRATIVE-MMA-LORE-01-{TARGET_MATCH_KEY}-{ts}.png"
                try:
                    await client.download_media(m_card, file=str(png_path))
                    captured_path_png = str(png_path)
                    print(f"  card png saved: {png_path}")
                except Exception as e:
                    print(f"  card png error: {e}")

            # If card already has narrative sections, capture it
            if any(s in text_card for s in ("📋", "🎯", "🏆")):
                captured_text = text_card
                captured_msg_id = m_card.id
                used_path = "deeplink_direct"
                print(f"  Card response itself is the narrative — captured.")
            else:
                # Tap "Full AI Breakdown" button
                print(f"  Tapping AI Breakdown button...")
                m_bd = await _click_button_matching(
                    client, m_card,
                    r"(Full AI Breakdown|AI Breakdown|🤖)",
                    timeout=120.0
                )
                if m_bd:
                    captured_text = m_bd.text or m_bd.message or ""
                    captured_msg_id = m_bd.id
                    used_path = "deeplink_then_breakdown"
                    print(f"  breakdown msg_id={m_bd.id} is_photo={bool(m_bd.photo)} "
                          f"len={len(captured_text)}")
                    if m_bd.photo:
                        png_path = EVIDENCE_DIR / f"FIX-NARRATIVE-MMA-LORE-01-{TARGET_MATCH_KEY}-{ts}-breakdown.png"
                        try:
                            await client.download_media(m_bd, file=str(png_path))
                            if not captured_path_png:
                                captured_path_png = str(png_path)
                            print(f"  breakdown png saved: {png_path}")
                        except Exception as e:
                            print(f"  breakdown png error: {e}")
                else:
                    print("  No breakdown response within 120s.")
        else:
            print("  No card response within 60s.")

        # Reset QA tier
        print(f"\nSTEP 3 — /qa reset")
        await _send_text(client, "/qa reset", timeout=15.0)

    # Always save TXT dump (even if empty)
    txt_path = EVIDENCE_DIR / f"FIX-NARRATIVE-MMA-LORE-01-{TARGET_MATCH_KEY}-{ts}.txt"
    with open(txt_path, "w") as f:
        f.write(f"# FIX-NARRATIVE-MMA-LORE-01 — {TARGET_MATCH_KEY}\n")
        f.write(f"# Captured: {datetime.now().isoformat()}\n")
        f.write(f"# Path: {used_path}\n")
        f.write(f"# Msg ID: {captured_msg_id}\n")
        f.write(f"# PNG: {captured_path_png}\n")
        f.write(f"\n--- VERBATIM TELETHON CAPTURE ---\n")
        f.write(captured_text or "(EMPTY — no narrative captured)")
        f.write("\n")
    print(f"\nTXT dump: {txt_path}")

    # Pull post-tap narrative_cache row
    post_cache = _read_cache(TARGET_MATCH_KEY)
    cache_html = (post_cache or {}).get("narrative_html") or ""
    cache_dump_path = EVIDENCE_DIR / f"FIX-NARRATIVE-MMA-LORE-01-{TARGET_MATCH_KEY}-cache-dump.html"
    with open(cache_dump_path, "w") as f:
        f.write(cache_html or "(EMPTY)")
    print(f"Cache HTML dump: {cache_dump_path}")
    print(f"Cache state post-tap: expires_at={post_cache.get('expires_at') if post_cache else 'N/A'} "
          f"created_at={post_cache.get('created_at') if post_cache else 'N/A'} "
          f"source={post_cache.get('narrative_source') if post_cache else 'N/A'}")

    # Build the canonical scan target: prefer Telethon capture; fall back to cache HTML
    cache_stripped = _strip_html(cache_html) if cache_html else ""

    scan_targets = []
    if captured_text.strip():
        scan_targets.append(("telethon_live", captured_text))
    if cache_stripped.strip():
        scan_targets.append(("cache_html", cache_stripped))

    if not scan_targets:
        print("\n=== FAIL: No narrative captured AND no cache HTML present ===")
        return 1

    # Per-source scan
    overall_hits: dict[str, int] = {p: 0 for p in BANNED_PHRASES}
    per_source: dict[str, dict[str, int]] = {}
    for src_name, src_text in scan_targets:
        hits = _scan_banned(src_text)
        per_source[src_name] = hits
        for p, c in hits.items():
            if c > overall_hits[p] is None or c > overall_hits.get(p, 0):
                overall_hits[p] = max(overall_hits[p], c)

    total_hits = sum(overall_hits.values())
    pass_verdict = (total_hits == 0)

    # Print per-source table
    print(f"\n=== PER-SOURCE SCAN ({len(scan_targets)} sources) ===")
    for src_name, hits in per_source.items():
        src_total = sum(hits.values())
        print(f"  [{src_name}] total banned hits: {src_total}")
        for p, c in hits.items():
            if c > 0:
                print(f"    HIT: {p!r} x {c}")

    # Final verdict
    print(f"\n=== Banned-phrase total hits across all sources: {total_hits} ===")
    print(f"=== Verdict: {'PASS' if pass_verdict else 'FAIL'} ===")
    print(f"\nEvidence files:")
    print(f"  TXT: {txt_path}")
    print(f"  Cache HTML: {cache_dump_path}")
    if captured_path_png:
        print(f"  PNG: {captured_path_png}")

    return 0 if pass_verdict else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
