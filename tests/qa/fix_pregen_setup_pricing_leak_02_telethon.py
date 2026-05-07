#!/usr/bin/env python3
"""FIX-PREGEN-SETUP-PRICING-LEAK-02 Telethon QA — dual-source capture.

For each reference match:
  1. Live PNG card via deeplink /start card_<match_key> -> tap "🤖 Full AI Breakdown" -> save PNG.
  2. narrative_cache.narrative_html — strip HTML and extract Setup section.

Banned-vocab assertion (per FIX-02 AC-4) applied to BOTH sources independently:
  - Tokens (case-insensitive, word-boundary anchored where applicable):
      bookmaker, odds, priced, implied, implied probability, implied chance,
      fair probability, fair value, expected value, model reads
  - Integer-probability patterns: r"\\bX% probability", "probability of X%",
      "Elo-implied", "X%-implied"
  - Decimal-probability values OUTSIDE "goals/points/runs per game" qualifier

Yields a 2x2 PASS/FAIL matrix (live OCR vs cache HTML, per match).

Outputs:
  - PNG: /home/paulsportsza/reports/e2e-screenshots/FIX-PREGEN-SETUP-PRICING-LEAK-02-<key>-<ts>.png
  - PNG (post-tap breakdown): same prefix + "-breakdown.png"
  - TXT: same prefix + ".txt" (verbatim text dumps)
  - Final report: /home/paulsportsza/reports/telethon-FIX-PREGEN-SETUP-PRICING-LEAK-02-FINAL.md
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

# Word-boundary banned tokens. Note: "implied" alone is in the list; matches "implied"
# anywhere word-boundary-aligned, including "implied probability" / "implied chance" / "Elo-implied".
BANNED_TOKENS = [
    r"\bbookmaker(s)?\b",
    r"\bodds\b",
    r"\bpriced\b",
    r"\bimplied probability\b",
    r"\bimplied chance\b",
    r"\bimplied\b",
    r"\bfair probability\b",
    r"\bfair value\b",
    r"\bexpected value\b",
    r"\bmodel reads\b",
]

# Integer-probability patterns (case-insensitive)
INT_PCT_PATTERNS = [
    re.compile(r"\b\d{1,3}\s*%\s*probability\b", re.IGNORECASE),
    re.compile(r"\bprobability of\s*\d{1,3}\s*%", re.IGNORECASE),
    re.compile(r"\bElo-implied\b", re.IGNORECASE),
    re.compile(r"\b\d{1,3}\s*%\s*-?\s*implied\b", re.IGNORECASE),
]

# Decimal % matcher (e.g., 50%, 4.5%) but allowed inside "X per game" qualifier
_DECIMAL_PCT_RE = re.compile(r"\b\d+(?:\.\d+)?\s*%")
_ALLOWED_QUAL = ("goals per game", "points per game", "runs per game", "per game")


def _session() -> StringSession:
    with open(STRING_SESSION_FILE) as f:
        return StringSession(f.read().strip())


async def _wait_for_reply(client, last_id: int, timeout: float = 30.0,
                          want_emoji: tuple[str, ...] = ()):
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


async def _click_button_matching(client, message, pattern: str, timeout: float = 60.0):
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
    text = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    # Decode common HTML entities
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " ")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _extract_setup(text: str) -> str:
    if "📋" not in text:
        return ""
    after_setup = text.split("📋", 1)[1]
    next_idx = len(after_setup)
    for marker in ("🎯", "⚠️", "🏆", "💰"):
        idx = after_setup.find(marker)
        if idx != -1 and idx < next_idx:
            next_idx = idx
    return after_setup[:next_idx].strip()


def _check_banned_vocab(setup_text: str) -> dict:
    """Apply FIX-02 AC-4 banned-vocab assertion to a Setup section."""
    hits: dict[str, str] = {}

    # 1. Word-boundary banned tokens (case-insensitive)
    for pat_str in BANNED_TOKENS:
        pat = re.compile(pat_str, re.IGNORECASE)
        m = pat.search(setup_text)
        if m:
            idx = m.start()
            ctx_start = max(0, idx - 40)
            ctx_end = min(len(setup_text), idx + len(m.group(0)) + 40)
            hits[pat_str] = setup_text[ctx_start:ctx_end]

    # 2. Integer-probability patterns
    for pat in INT_PCT_PATTERNS:
        m = pat.search(setup_text)
        if m:
            idx = m.start()
            ctx_start = max(0, idx - 40)
            ctx_end = min(len(setup_text), idx + len(m.group(0)) + 40)
            hits[pat.pattern] = setup_text[ctx_start:ctx_end]

    # 3. Decimal-percentage outside "X per game" qualifier
    pct_hits = []
    for m in _DECIMAL_PCT_RE.finditer(setup_text):
        tail = setup_text[m.end(): m.end() + 50].lower()
        if any(q in tail for q in _ALLOWED_QUAL):
            continue
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
                   setup_validated, verdict_validated, created_at, expires_at
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
            "expires_at": row[7],
        }
    except Exception as e:
        return {"error": str(e)}


async def _capture_via_telethon(client, match_key: str, ts: str) -> dict:
    """Capture deeplink card + post-tap breakdown card. Save BOTH PNGs."""
    result: dict = {"path": "telethon", "msg_text": "", "msg_id": None}
    try:
        last = await client.get_messages(BOT_USERNAME, limit=1)
        last_id_pre = last[0].id if last else 0
        await client.send_message(BOT_USERNAME, f"/start card_{match_key}")

        m1 = None
        deadline = time.time() + 30.0
        while time.time() < deadline:
            async for msg in client.iter_messages(BOT_USERNAME, limit=5):
                if msg.id > last_id_pre and not msg.out:
                    text = msg.text or msg.message or ""
                    has_buttons = bool(msg.buttons)
                    if has_buttons or "📋" in text or "🎯" in text:
                        m1 = msg
                        break
                    if m1 is None:
                        m1 = msg
            if m1 is not None and (m1.buttons or "📋" in (m1.text or "") or "🎯" in (m1.text or "")):
                break
            await asyncio.sleep(0.8)

        if not m1:
            result["error"] = "no_response_to_deeplink"
            return result

        result["deeplink_text"] = (m1.text or m1.message or "")[:2000]
        result["deeplink_msg_id"] = m1.id
        result["deeplink_is_photo"] = bool(m1.photo)
        result["deeplink_buttons"] = (
            [b.text for r in (m1.buttons or []) for b in r] if m1.buttons else []
        )

        if m1.photo:
            png_path = EVIDENCE_DIR / f"FIX-PREGEN-SETUP-PRICING-LEAK-02-{match_key}-{ts}.png"
            try:
                await client.download_media(m1, file=str(png_path))
                result["png_path"] = str(png_path)
            except Exception as e:
                result["png_error"] = f"{type(e).__name__}: {e}"

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

        if m_breakdown and m_breakdown.photo:
            png_path_post = EVIDENCE_DIR / f"FIX-PREGEN-SETUP-PRICING-LEAK-02-{match_key}-{ts}-breakdown.png"
            try:
                await client.download_media(m_breakdown, file=str(png_path_post))
                result["png_path_breakdown"] = str(png_path_post)
            except Exception as e:
                result["png_breakdown_error"] = f"{type(e).__name__}: {e}"

        if m_breakdown is None:
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
    print(f"\n=== FIX-PREGEN-SETUP-PRICING-LEAK-02 Telethon Capture ({ts}) ===")
    print(f"Bot: @{BOT_USERNAME}")
    print(f"Evidence: {EVIDENCE_DIR}\n")

    sha_out = subprocess.run(
        ["git", "-C", "/home/paulsportsza/bot", "rev-parse", "--short", "HEAD"],
        capture_output=True, text=True
    )
    bot_sha = sha_out.stdout.strip()

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

        print("\nSTEP 0 — /qa set_diamond")
        m_qa = await _send_text(client, "/qa set_diamond", timeout=15.0)
        qa_response_text = (m_qa.text or m_qa.message or "")[:200] if m_qa else "(no reply)"
        print(f"  qa response: {qa_response_text}")

        for match_key, expected_tier in TARGETS:
            print(f"\n--- Capture: {match_key} (expected tier: {expected_tier}) ---")
            telethon_result = await _capture_via_telethon(client, match_key, ts)
            cache_result = _read_cache(match_key)

            captures.append({
                "match_key": match_key,
                "expected_tier": expected_tier,
                "telethon": telethon_result,
                "cache": cache_result,
            })

            await asyncio.sleep(2.0)

        print(f"\nSTEP X — /qa reset")
        await _send_text(client, "/qa reset", timeout=15.0)

    # Build per-layer assertion results
    summary_rows = []
    for cap in captures:
        match_key = cap["match_key"]
        expected_tier = cap["expected_tier"]
        telethon = cap["telethon"]
        cache = cap["cache"]

        live_text = telethon.get("msg_text") or telethon.get("deeplink_text") or ""
        live_setup = _extract_setup(live_text)
        live_check = _check_banned_vocab(live_setup) if live_setup else {
            "banned_tokens": {},
            "decimal_pct_outside_qualifier": [],
            "pass": False,
            "_reason": "no Setup section found in live capture text",
        }

        cache_html = (cache or {}).get("narrative_html") or ""
        cache_stripped = _strip_html(cache_html) if cache_html else ""
        cache_setup = _extract_setup(cache_stripped) if cache_stripped else ""
        cache_check = _check_banned_vocab(cache_setup) if cache_setup else {
            "banned_tokens": {},
            "decimal_pct_outside_qualifier": [],
            "pass": False,
            "_reason": "no Setup section found in cache HTML",
        }

        dump_path = EVIDENCE_DIR / f"FIX-PREGEN-SETUP-PRICING-LEAK-02-{match_key}-{ts}.txt"
        with open(dump_path, "w") as f:
            f.write(f"# FIX-PREGEN-SETUP-PRICING-LEAK-02 — {match_key}\n")
            f.write(f"# Captured: {datetime.now().isoformat()}\n")
            f.write(f"# Expected tier: {expected_tier}\n")
            f.write(f"# Bot SHA: {bot_sha}\n")
            f.write(f"# Runtime path /home/paulsportsza/bot/bot.py: {runtime_path_ok}\n")
            f.write("\n" + "=" * 70 + "\n")
            f.write("LAYER 1 — TELETHON LIVE CAPTURE\n")
            f.write("=" * 70 + "\n")
            f.write(f"path: {telethon.get('path')}\n")
            f.write(f"clicked_pattern: {telethon.get('clicked_pattern')}\n")
            f.write(f"deeplink_msg_id: {telethon.get('deeplink_msg_id')}\n")
            f.write(f"deeplink_is_photo: {telethon.get('deeplink_is_photo')}\n")
            f.write(f"deeplink_buttons: {telethon.get('deeplink_buttons')}\n")
            f.write(f"breakdown_msg_id: {telethon.get('msg_id')}\n")
            f.write(f"breakdown_is_photo: {telethon.get('msg_is_photo')}\n")
            f.write(f"breakdown_buttons: {telethon.get('msg_buttons', [])}\n")
            f.write(f"png_path: {telethon.get('png_path')}\n")
            f.write(f"png_path_breakdown: {telethon.get('png_path_breakdown')}\n")
            f.write(f"error: {telethon.get('error')}\n\n")
            f.write("--- LIVE DEEPLINK CARD TEXT ---\n")
            f.write(telethon.get("deeplink_text") or "(none)")
            f.write("\n\n--- LIVE BREAKDOWN MESSAGE TEXT ---\n")
            f.write(telethon.get("msg_text") or "(none)")
            f.write("\n\n--- LIVE SETUP (extracted) ---\n")
            f.write(live_setup or "(empty)")
            f.write("\n\n" + "=" * 70 + "\n")
            f.write("LAYER 2 — narrative_cache.narrative_html\n")
            f.write("=" * 70 + "\n")
            if cache and "error" not in cache:
                f.write(f"edge_tier: {cache.get('edge_tier')}\n")
                f.write(f"narrative_source: {cache.get('narrative_source')}\n")
                f.write(f"setup_validated: {cache.get('setup_validated')}\n")
                f.write(f"verdict_validated: {cache.get('verdict_validated')}\n")
                f.write(f"created_at (UTC): {cache.get('created_at')}\n")
                f.write(f"expires_at (UTC): {cache.get('expires_at')}\n\n")
                f.write("--- STRIPPED HTML ---\n")
                f.write(cache_stripped or "(empty)")
                f.write("\n\n--- RAW HTML ---\n")
                f.write(cache_html or "(empty)")
                f.write("\n\n--- CACHE SETUP (extracted) ---\n")
                f.write(cache_setup or "(empty)")
            else:
                f.write(f"cache miss / error: {cache}\n")
            f.write("\n")

        summary_rows.append({
            "match_key": match_key,
            "expected_tier": expected_tier,
            "dump_path": str(dump_path),
            "live": {
                "setup_text": live_setup,
                "check": live_check,
                "telethon_path": telethon.get("path"),
                "telethon_error": telethon.get("error"),
                "png_path": telethon.get("png_path"),
                "png_path_breakdown": telethon.get("png_path_breakdown"),
            },
            "cache": {
                "setup_text": cache_setup,
                "check": cache_check,
                "edge_tier": (cache or {}).get("edge_tier"),
                "narrative_source": (cache or {}).get("narrative_source"),
                "setup_validated": (cache or {}).get("setup_validated"),
                "verdict_validated": (cache or {}).get("verdict_validated"),
                "created_at": (cache or {}).get("created_at"),
                "expires_at": (cache or {}).get("expires_at"),
            },
        })

    # Final report
    final_path = REPORTS_DIR / "telethon-FIX-PREGEN-SETUP-PRICING-LEAK-02-FINAL.md"
    with open(final_path, "w") as f:
        f.write("# FIX-PREGEN-SETUP-PRICING-LEAK-02 — Telethon Final Report\n\n")
        f.write(f"- Captured: {datetime.now().isoformat()}\n")
        f.write(f"- Bot commit SHA in service: `{bot_sha}`\n")
        f.write(f"- Runtime canonical path /home/paulsportsza/bot/bot.py: "
                f"{'YES' if runtime_path_ok else 'NO'}\n")
        f.write(f"- Telethon session: `{STRING_SESSION_FILE}`\n")
        f.write(f"- Bot: `@{BOT_USERNAME}`\n\n")
        f.write("## Cache Row Status (per match)\n\n")
        for row in summary_rows:
            c = row["cache"]
            f.write(f"### {row['match_key']}\n")
            f.write(f"- created_at (UTC): `{c.get('created_at')}`\n")
            f.write(f"- expires_at (UTC): `{c.get('expires_at')}`\n")
            f.write(f"- edge_tier: `{c.get('edge_tier')}`\n")
            f.write(f"- narrative_source: `{c.get('narrative_source')}`\n")
            f.write(f"- setup_validated: `{c.get('setup_validated')}`\n")
            f.write(f"- verdict_validated: `{c.get('verdict_validated')}`\n\n")

        f.write("## Banned Vocabulary Assertion (per AC-4)\n\n")
        f.write("Tokens (word-boundary, case-insensitive):\n")
        for tok in BANNED_TOKENS:
            f.write(f"- `{tok}`\n")
        f.write("\nInteger-probability patterns:\n")
        for pat in INT_PCT_PATTERNS:
            f.write(f"- `{pat.pattern}`\n")
        f.write("\nDecimal-probability values outside `goals/points/runs per game`.\n\n")

        f.write("## 2x2 PASS/FAIL Matrix\n\n")
        f.write("| Match | Layer 1 (Live OCR/text) | Layer 2 (Cache HTML) |\n")
        f.write("|---|---|---|\n")
        all_pass = True
        for row in summary_rows:
            l1 = "PASS" if row["live"]["check"]["pass"] else "FAIL"
            l2 = "PASS" if row["cache"]["check"]["pass"] else "FAIL"
            if l1 != "PASS" or l2 != "PASS":
                all_pass = False
            f.write(f"| `{row['match_key']}` | **{l1}** | **{l2}** |\n")
        f.write("\n")

        for row in summary_rows:
            f.write(f"## {row['match_key']}\n\n")
            f.write(f"- Expected tier: **{row['expected_tier']}**\n")
            f.write(f"- Text dump: `{row['dump_path']}`\n")
            f.write(f"- Deeplink PNG: `{row['live']['png_path']}`\n")
            f.write(f"- Breakdown PNG: `{row['live']['png_path_breakdown']}`\n\n")

            for layer_name, layer in [("Layer 1 — Live", row["live"]),
                                       ("Layer 2 — Cache HTML", row["cache"])]:
                check = layer["check"]
                verdict = "PASS" if check["pass"] else "FAIL"
                f.write(f"### {layer_name}: **{verdict}**\n\n")
                if check.get("_reason"):
                    f.write(f"- Reason: `{check['_reason']}`\n\n")
                if check.get("banned_tokens"):
                    f.write("Banned tokens found:\n")
                    for tok, ctx in check["banned_tokens"].items():
                        f.write(f"- `{tok}` -> context: `{ctx}`\n")
                    f.write("\n")
                if check.get("decimal_pct_outside_qualifier"):
                    f.write("Decimal % outside qualifier:\n")
                    for hit in check["decimal_pct_outside_qualifier"]:
                        f.write(f"- `{hit['match']}` -> context: `{hit['context']}`\n")
                    f.write("\n")
                f.write("Verbatim Setup:\n```\n")
                txt = layer["setup_text"] or "(empty)"
                f.write(txt[:2500])
                if len(txt) > 2500:
                    f.write("\n[truncated]")
                f.write("\n```\n\n")

        f.write(f"## Overall Verdict: **{'PASS' if all_pass else 'FAIL'}**\n")

    print(f"\n=== Final report: {final_path} ===")
    for row in summary_rows:
        l1 = "PASS" if row["live"]["check"]["pass"] else "FAIL"
        l2 = "PASS" if row["cache"]["check"]["pass"] else "FAIL"
        print(f"  {row['match_key']}: live={l1} cache={l2}")
    print(f"\n=== Overall: {'PASS' if all_pass else 'FAIL'} ===")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
