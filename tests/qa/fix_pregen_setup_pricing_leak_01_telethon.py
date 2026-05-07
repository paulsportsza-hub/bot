#!/usr/bin/env python3
"""FIX-PREGEN-SETUP-PRICING-LEAK-01 Telethon QA — capture verbatim AI Breakdown
text bubbles for two Premium-tier matches and assert Setup section is free of
banned bookmaker / odds / pricing vocabulary.

Targets:
  1. everton_vs_manchester_city_2026-05-04 (Gold tier)
  2. arsenal_vs_fulham_2026-05-02 (Diamond tier)

Strategy:
  - Use /qa set_diamond to ensure full breakdown access for both targets.
  - Deeplink each match via `/start card_<match_key>` — this lands on the detail
    card. Detail card has either a "Full AI Breakdown" / tier emoji button to
    open the breakdown.
  - Capture verbatim text. Save .txt dumps. Run banned-vocab check on Setup
    section (between 📋 and 🎯).
  - If detail card or breakdown does not render via Telethon path, fall back to
    direct narrative_cache HTML capture and document the substitution.

Outputs:
  - /home/paulsportsza/reports/e2e-screenshots/FIX-PREGEN-SETUP-PRICING-LEAK-01-<match>-<ts>.txt
  - /home/paulsportsza/reports/telethon-FIX-PREGEN-SETUP-PRICING-LEAK-01-<ts>.md (summary)
"""
from __future__ import annotations

import asyncio
import os
import re
import sqlite3
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
STRING_SESSION_FILE = "/home/paulsportsza/bot/data/telethon_qa_session.string"
BOT_USERNAME = "mzansiedge_bot"
ODDS_DB = "/home/paulsportsza/scrapers/odds.db"

EVIDENCE_DIR = Path("/home/paulsportsza/reports/e2e-screenshots")
REPORTS_DIR = Path("/home/paulsportsza/reports")
EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

TARGETS = [
    ("everton_vs_manchester_city_2026-05-04", "gold"),
    ("arsenal_vs_fulham_2026-05-02", "diamond"),
]

BANNED_TOKENS = [
    "bookmaker",
    "odds",
    "priced",
    "implied probability",
    "implied chance",
    "fair probability",
    "fair value",
    "expected value",
    "model reads",
]

# Decimal % matcher (e.g., 50%, 4.5%) but allowed inside "X per game" / "X.X goals/points/runs per game"
_DECIMAL_PCT_RE = re.compile(r"\b\d+(?:\.\d+)?\s*%")


def _session() -> StringSession:
    with open(STRING_SESSION_FILE) as f:
        return StringSession(f.read().strip())


async def _wait_for_reply(client, last_id: int, timeout: float = 30.0,
                          want_emoji: tuple[str, ...] = ()):
    """Wait for a NEW non-out message after last_id. If want_emoji set, keep
    polling until message text contains one of the emojis (skips loading bubbles).
    """
    deadline = time.time() + timeout
    last_seen_msg = None
    while time.time() < deadline:
        async for msg in client.iter_messages(BOT_USERNAME, limit=5):
            if msg.id > last_id and not msg.out:
                text = msg.text or msg.message or ""
                if want_emoji:
                    if any(e in text for e in want_emoji):
                        return msg
                else:
                    last_seen_msg = msg
                    break
        if last_seen_msg is not None and not want_emoji:
            return last_seen_msg
        await asyncio.sleep(0.6)
    return last_seen_msg


async def _send_text(client, text: str, timeout: float = 30.0):
    last = await client.get_messages(BOT_USERNAME, limit=1)
    last_id = last[0].id if last else 0
    await client.send_message(BOT_USERNAME, text)
    await asyncio.sleep(1.0)
    return await _wait_for_reply(client, last_id, timeout=timeout)


async def _click_button_matching(client, message, pattern: str, timeout: float = 45.0):
    """Click button and wait until either:
      - a NEW non-out message arrives with substantive content (📋/🎯/Setup), or
      - the original message is edited AND the edited content has substantive text.
    """
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
                    msgs = await client.get_messages(BOT_USERNAME, limit=8)
                    for m in msgs:
                        if m.out:
                            continue
                        text = m.text or m.message or ""
                        is_substantive = any(s in text for s in ("📋", "🎯", "The Setup", "The Edge"))
                        if m.id > last_id:
                            if is_substantive:
                                substantive_msg = m
                                break
                            elif fallback_msg is None:
                                fallback_msg = m
                        elif m.id == original_msg_id:
                            # Edited original — check edit_date changed AND text now substantive
                            if m.edit_date != original_edit_date:
                                if is_substantive:
                                    substantive_msg = m
                                    break
                                elif fallback_msg is None:
                                    fallback_msg = m
                    if substantive_msg is not None:
                        break
                    await asyncio.sleep(0.8)

                return substantive_msg or fallback_msg
    return None


def _strip_html(html: str) -> str:
    """Remove HTML tags but preserve newlines."""
    text = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    # Collapse > 2 newlines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _extract_setup(text: str) -> str:
    """Extract text between 📋 (Setup) and 🎯 (Edge / next section). Falls back to
    region between 📋 and the next emoji header (🎯/⚠️/🏆) — whichever appears first.
    """
    if "📋" not in text:
        return ""
    after_setup = text.split("📋", 1)[1]
    # Find earliest next section marker
    next_idx = len(after_setup)
    for marker in ("🎯", "⚠️", "🏆", "💰"):
        idx = after_setup.find(marker)
        if idx != -1 and idx < next_idx:
            next_idx = idx
    return after_setup[:next_idx].strip()


def _check_banned_vocab(setup_text: str) -> dict:
    setup_lower = setup_text.lower()
    hits = {}
    for token in BANNED_TOKENS:
        if token.lower() in setup_lower:
            # Capture context (50 chars around hit)
            idx = setup_lower.find(token.lower())
            context_start = max(0, idx - 30)
            context_end = min(len(setup_text), idx + len(token) + 30)
            hits[token] = setup_text[context_start:context_end]
    # Decimal % check (allowed only in "X per game" qualifier)
    pct_hits = []
    for m in _DECIMAL_PCT_RE.finditer(setup_text):
        # Look ahead 30 chars for an allowed qualifier
        tail = setup_text[m.end(): m.end() + 50].lower()
        if any(q in tail for q in ("goals per game", "points per game", "runs per game", "per game")):
            continue
        # Also allow if the % is part of a known phrase like "50%" with no decimal in pure context
        # — these slipped through but we'll list them.
        pct_hits.append({
            "match": m.group(0),
            "context": setup_text[max(0, m.start() - 30): min(len(setup_text), m.end() + 30)],
        })
    return {
        "banned_tokens": hits,
        "decimal_pct_outside_qualifier": pct_hits,
        "pass": (len(hits) == 0 and len(pct_hits) == 0),
    }


def _read_cache(match_id: str) -> dict | None:
    try:
        conn = sqlite3.connect(ODDS_DB, timeout=5.0)
        cur = conn.cursor()
        cur.execute(
            """
            SELECT narrative_html, edge_tier, narrative_source, quality_status,
                   setup_validated, verdict_validated, created_at
            FROM narrative_cache
            WHERE match_id = ?
            """,
            (match_id,),
        )
        row = cur.fetchone()
        conn.close()
        if not row:
            return None
        return {
            "match_id": match_id,
            "narrative_html": row[0],
            "edge_tier": row[1],
            "narrative_source": row[2],
            "quality_status": row[3],
            "setup_validated": row[4],
            "verdict_validated": row[5],
            "created_at": row[6],
        }
    except Exception as e:
        return {"error": str(e)}


async def _capture_via_telethon(client, match_key: str, ts: str, evidence: dict) -> dict:
    """Capture the AI Breakdown via deeplink.

    PRODUCT NOTE: The bot's `card_<match_key>` deeplink renders the AI Breakdown
    as a PNG photo CARD with the full Setup/Edge/Risk/Verdict text BAKED INTO
    THE IMAGE. There is no separate text bubble. After tapping
    "🤖 Full AI Breakdown", the bot just removes that button (since the content
    is already on-screen). Therefore the visual AI Breakdown content == the
    `narrative_cache.narrative_html` row at render time.

    We save the photo PNG for visual evidence and use the cache HTML for the
    banned-vocab assertion (functionally equivalent per the brief).
    """
    result = {"path": "telethon", "msg_text": "", "msg_id": None, "buttons": []}
    try:
        # Send deeplink, then wait for the loading bubble to be edited into the detail card.
        last = await client.get_messages(BOT_USERNAME, limit=1)
        last_id_pre = last[0].id if last else 0
        await client.send_message(BOT_USERNAME, f"/start card_{match_key}")

        # Wait up to 25s for the response message to land AND get edited into the detail card.
        m1 = None
        deadline = time.time() + 30.0
        while time.time() < deadline:
            async for msg in client.iter_messages(BOT_USERNAME, limit=5):
                if msg.id > last_id_pre and not msg.out:
                    text = msg.text or msg.message or ""
                    # The detail card has emoji headers. Loading bubble is just "⚡ Loading edge…"
                    has_buttons = bool(msg.buttons)
                    if has_buttons or "📋" in text or "🎯" in text:
                        m1 = msg
                        break
                    if m1 is None:
                        m1 = msg  # capture loading bubble in case nothing better arrives
            if m1 is not None and (m1.buttons or "📋" in (m1.text or "") or "🎯" in (m1.text or "")):
                break
            await asyncio.sleep(0.8)

        if not m1:
            result["error"] = "no_response_to_deeplink"
            return result
        result["deeplink_text"] = (m1.text or m1.message or "")[:1500]
        result["deeplink_msg_id"] = m1.id
        result["deeplink_is_photo"] = bool(m1.photo)
        result["deeplink_buttons"] = (
            [b.text for r in (m1.buttons or []) for b in r] if m1.buttons else []
        )

        # Save the photo card as PNG for visual evidence
        if m1.photo:
            png_path = EVIDENCE_DIR / f"FIX-PREGEN-SETUP-PRICING-LEAK-01-{match_key}-{ts}.png"
            try:
                await client.download_media(m1, file=str(png_path))
                result["png_path"] = str(png_path)
            except Exception as _png_err:
                result["png_error"] = f"{type(_png_err).__name__}: {_png_err}"

        # Find the AI Breakdown button — patterns from bot.py L14256:
        # - "🤖 Full AI Breakdown" — Diamond/accessible (callback: edge:breakdown:)
        # - "🔒 Full AI Breakdown" — locked tier (callback: edge:breakdown_gate:)
        breakdown_patterns = [
            r"🤖.*Full AI Breakdown",
            r"Full AI Breakdown",
            r"🔒.*Full AI Breakdown",
        ]
        m_breakdown = None
        for pat in breakdown_patterns:
            m_breakdown = await _click_button_matching(client, m1, pat, timeout=60.0)
            if m_breakdown is not None:
                result["clicked_pattern"] = pat
                break

        # Also save the POST-click photo (the actual breakdown card PNG) — the
        # bot edits the same message with `message_to_edit=query.message`,
        # so the PNG content changes from the detail card to the breakdown card.
        if m_breakdown and m_breakdown.photo:
            png_path_post = EVIDENCE_DIR / f"FIX-PREGEN-SETUP-PRICING-LEAK-01-{match_key}-{ts}-breakdown.png"
            try:
                await client.download_media(m_breakdown, file=str(png_path_post))
                result["png_path_breakdown"] = str(png_path_post)
            except Exception as _png_err2:
                result["png_breakdown_error"] = f"{type(_png_err2).__name__}: {_png_err2}"

        if m_breakdown is None:
            # The deeplink itself may BE the breakdown if it's a text bubble
            text = m1.text or m1.message or ""
            if "📋" in text or "🎯" in text:
                result["path"] = "telethon_deeplink_is_breakdown"
                result["msg_text"] = text
                result["msg_id"] = m1.id
                return result
            result["error"] = "no_breakdown_button_found"
            return result

        result["msg_text"] = m_breakdown.text or m_breakdown.message or ""
        result["msg_id"] = m_breakdown.id
        result["msg_is_photo"] = bool(m_breakdown.photo)
        result["msg_buttons"] = (
            [b.text for r in (m_breakdown.buttons or []) for b in r] if m_breakdown.buttons else []
        )
        return result
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"
        return result


async def main() -> int:
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    print(f"\n=== FIX-PREGEN-SETUP-PRICING-LEAK-01 Telethon Capture ({ts}) ===")
    print(f"Bot: @{BOT_USERNAME}")
    print(f"Evidence: {EVIDENCE_DIR}\n")

    # Get bot commit SHA
    import subprocess
    sha_out = subprocess.run(
        ["git", "-C", "/home/paulsportsza/bot", "rev-parse", "--short", "HEAD"],
        capture_output=True, text=True
    )
    bot_sha = sha_out.stdout.strip()

    # Verify bot runtime path
    ps_out = subprocess.run(
        ["bash", "-c", "ps aux | grep 'bot.py' | grep -v grep"],
        capture_output=True, text=True
    )
    runtime_lines = [
        l for l in ps_out.stdout.splitlines()
        if "bot.py" in l and "/home/paulsportsza/bot/bot.py" in l
    ]
    runtime_path_ok = len(runtime_lines) > 0

    captures: list[dict] = []

    async with TelegramClient(_session(), API_ID, API_HASH) as client:
        me = await client.get_me()
        print(f"Connected as: {me.first_name} (id={me.id})")

        # Set Diamond tier so all targets are accessible
        print("\nSTEP 0 — /qa set_diamond")
        m_qa = await _send_text(client, "/qa set_diamond", timeout=15.0)
        qa_response_text = (m_qa.text or m_qa.message or "")[:200] if m_qa else "(no reply)"
        print(f"  qa response: {qa_response_text}")

        for match_key, expected_tier in TARGETS:
            print(f"\n--- Capture: {match_key} (expected tier: {expected_tier}) ---")
            telethon_result = await _capture_via_telethon(client, match_key, ts, {})
            cache_result = _read_cache(match_key)

            captures.append({
                "match_key": match_key,
                "expected_tier": expected_tier,
                "telethon": telethon_result,
                "cache": cache_result,
            })

            await asyncio.sleep(2.0)

        # Cleanup
        print(f"\nSTEP X — /qa reset")
        await _send_text(client, "/qa reset", timeout=15.0)

    # Process captures and run assertions
    summary_rows = []
    for cap in captures:
        match_key = cap["match_key"]
        expected_tier = cap["expected_tier"]
        telethon = cap["telethon"]
        cache = cap["cache"]

        # Decide which captured text to use as "verbatim breakdown"
        verbatim_text = ""
        source_used = ""

        if telethon.get("msg_text") and ("📋" in telethon["msg_text"] or "🎯" in telethon["msg_text"]):
            verbatim_text = telethon["msg_text"]
            source_used = "telethon_breakdown_text"
        elif cache and cache.get("narrative_html"):
            verbatim_text = _strip_html(cache["narrative_html"])
            source_used = "narrative_cache_html_stripped"
        else:
            source_used = "NONE_AVAILABLE"

        # Save raw text dump
        dump_path = EVIDENCE_DIR / f"FIX-PREGEN-SETUP-PRICING-LEAK-01-{match_key}-{ts}.txt"
        with open(dump_path, "w") as f:
            f.write(f"# FIX-PREGEN-SETUP-PRICING-LEAK-01 — {match_key}\n")
            f.write(f"# Captured: {datetime.now().isoformat()}\n")
            f.write(f"# Expected tier: {expected_tier}\n")
            f.write(f"# Source used for assertion: {source_used}\n")
            f.write(f"# Bot SHA: {bot_sha}\n")
            f.write(f"# Runtime path verified at /home/paulsportsza/bot/bot.py: {runtime_path_ok}\n")
            f.write("\n")
            f.write("=" * 70 + "\n")
            f.write("TELETHON CAPTURE\n")
            f.write("=" * 70 + "\n")
            f.write(f"path: {telethon.get('path')}\n")
            f.write(f"clicked_pattern: {telethon.get('clicked_pattern')}\n")
            f.write(f"deeplink_msg_id: {telethon.get('deeplink_msg_id')}\n")
            f.write(f"deeplink_buttons: {telethon.get('deeplink_buttons')}\n")
            f.write(f"breakdown_msg_id: {telethon.get('msg_id')}\n")
            f.write(f"breakdown_buttons: {telethon.get('msg_buttons', [])}\n")
            f.write(f"error: {telethon.get('error')}\n")
            f.write("\n--- DEEPLINK_TEXT ---\n")
            f.write(telethon.get("deeplink_text") or "")
            f.write("\n\n--- BREAKDOWN_TEXT ---\n")
            f.write(telethon.get("msg_text") or "")
            f.write("\n")
            f.write("=" * 70 + "\n")
            f.write("CACHE FALLBACK (narrative_cache HTML, tags stripped)\n")
            f.write("=" * 70 + "\n")
            if cache and "error" not in cache:
                f.write(f"edge_tier: {cache.get('edge_tier')}\n")
                f.write(f"narrative_source: {cache.get('narrative_source')}\n")
                f.write(f"setup_validated: {cache.get('setup_validated')}\n")
                f.write(f"verdict_validated: {cache.get('verdict_validated')}\n")
                f.write(f"created_at: {cache.get('created_at')}\n\n")
                f.write("--- STRIPPED HTML ---\n")
                f.write(_strip_html(cache.get("narrative_html") or ""))
                f.write("\n\n--- RAW HTML ---\n")
                f.write(cache.get("narrative_html") or "")
            else:
                f.write(f"cache miss / error: {cache}\n")
            f.write("\n")

        # Banned-vocab check
        setup_text = _extract_setup(verbatim_text)
        check = _check_banned_vocab(setup_text)

        summary_rows.append({
            "match_key": match_key,
            "expected_tier": expected_tier,
            "source_used": source_used,
            "dump_path": str(dump_path),
            "setup_text": setup_text,
            "check": check,
            "telethon_path": telethon.get("path"),
            "telethon_error": telethon.get("error"),
            "cache_tier": (cache or {}).get("edge_tier"),
            "cache_source": (cache or {}).get("narrative_source"),
            "cache_validated": {
                "setup": (cache or {}).get("setup_validated"),
                "verdict": (cache or {}).get("verdict_validated"),
            },
        })

    # Write summary report
    summary_path = REPORTS_DIR / f"telethon-FIX-PREGEN-SETUP-PRICING-LEAK-01-{ts}.md"
    with open(summary_path, "w") as f:
        f.write("# FIX-PREGEN-SETUP-PRICING-LEAK-01 — Telethon QA Capture\n\n")
        f.write(f"- Captured: {datetime.now().isoformat()}\n")
        f.write(f"- Bot commit SHA: `{bot_sha}`\n")
        f.write(f"- Runtime at /home/paulsportsza/bot/bot.py: {'YES' if runtime_path_ok else 'NO'}\n")
        f.write(f"- Telethon session: `{STRING_SESSION_FILE}`\n")
        f.write(f"- Bot: `@{BOT_USERNAME}`\n\n")
        f.write("## Banned Vocabulary Tokens (asserted absent from Setup section)\n")
        for tok in BANNED_TOKENS:
            f.write(f"- `{tok}`\n")
        f.write("- Decimal-percentage outside `goals/points/runs per game` qualifier\n\n")

        all_pass = True
        for row in summary_rows:
            f.write(f"## {row['match_key']}\n\n")
            f.write(f"- Expected tier: **{row['expected_tier']}**\n")
            f.write(f"- Cache tier: `{row['cache_tier']}`\n")
            f.write(f"- Cache narrative_source: `{row['cache_source']}`\n")
            f.write(f"- Cache validated: setup={row['cache_validated']['setup']} verdict={row['cache_validated']['verdict']}\n")
            f.write(f"- Source used for assertion: `{row['source_used']}`\n")
            f.write(f"- Telethon path: `{row['telethon_path']}` "
                    f"{'(error: ' + row['telethon_error'] + ')' if row['telethon_error'] else ''}\n")
            f.write(f"- Text dump: `{row['dump_path']}`\n\n")

            verdict = "PASS" if row["check"]["pass"] else "FAIL"
            if not row["check"]["pass"]:
                all_pass = False
            f.write(f"### Banned-Vocab Check: **{verdict}**\n\n")
            if row["check"]["banned_tokens"]:
                f.write("Banned tokens found:\n")
                for tok, ctx in row["check"]["banned_tokens"].items():
                    f.write(f"- `{tok}` → context: `{ctx}`\n")
                f.write("\n")
            if row["check"]["decimal_pct_outside_qualifier"]:
                f.write("Decimal percentages outside qualifier:\n")
                for hit in row["check"]["decimal_pct_outside_qualifier"]:
                    f.write(f"- `{hit['match']}` → context: `{hit['context']}`\n")
                f.write("\n")

            f.write("### Setup Section (verbatim)\n\n")
            f.write("```\n")
            f.write(row["setup_text"][:2000])
            if len(row["setup_text"]) > 2000:
                f.write("\n[truncated]")
            f.write("\n```\n\n")

        f.write(f"## Overall Verdict: **{'PASS' if all_pass else 'FAIL'}**\n")

    print(f"\n=== Summary report: {summary_path} ===")
    for row in summary_rows:
        verdict = "PASS" if row["check"]["pass"] else "FAIL"
        print(f"  {row['match_key']}: {verdict} (source: {row['source_used']})")
    print(f"\n=== Overall: {'PASS' if all_pass else 'FAIL'} ===")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
