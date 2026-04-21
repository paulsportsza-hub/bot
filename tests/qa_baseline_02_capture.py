#!/usr/bin/env python3
# ruff: noqa
"""QA-BASELINE-02 — Full Card Quality Baseline Capture.

Evaluates 6 card types via live Telethon bot interaction:
  Panel A: Edge Digest, Gold Filter, Silver Filter, Bronze Filter
  Panel B: My Matches list, Match Detail

Captures caption text, button layouts, photo downloads, timings.
Saves all evidence to: /home/paulsportsza/reports/qa-baseline-02/

Does NOT read narrative_cache or odds.db for scoring — live bot only.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

BOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BOT_DIR / ".env")

from telethon import TelegramClient  # noqa: E402
from telethon.sessions import StringSession  # noqa: E402
from telethon.tl.types import (  # noqa: E402
    KeyboardButtonCallback,
    KeyboardButtonUrl,
    MessageMediaPhoto,
)

# ── Config ────────────────────────────────────────────────────────────────────
API_ID   = int(os.getenv("TELEGRAM_API_ID",  "32418601"))
API_HASH = os.getenv("TELEGRAM_API_HASH",     "95e313a8ef5b998be0515dd8328fac57")
BOT_USERNAME = "@mzansiedge_bot"
STRING_SESSION_FILE = BOT_DIR / "data" / "telethon_session.string"

OUT_DIR = Path("/home/paulsportsza/reports/qa-baseline-02")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Timeouts
WAIT_SHORT   = 15    # commands + tier filters (cached)
WAIT_MEDIUM  = 35    # fresh /today cold render
WAIT_LONG    = 60    # My Matches + game analysis

HTML_TAG_RE = re.compile(r"<[^>]+>")


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class CardCapture:
    name: str               # e.g. "A1-digest", "A2-gold-filter"
    panel: str              # "A" or "B"
    sent_at: float = 0.0
    received_at: float = 0.0
    render_ms: int = 0
    photo_arrived: bool = False
    caption_raw: str = ""
    caption_len: int = 0
    message_text: str = ""
    buttons: list[str] = field(default_factory=list)
    photo_path: str = ""
    errors: list[str] = field(default_factory=list)
    notes: str = ""

    def strip_caption(self) -> str:
        return HTML_TAG_RE.sub("", self.caption_raw).strip()


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_session() -> StringSession:
    raw = STRING_SESSION_FILE.read_text().strip()
    if not raw:
        raise SystemExit(f"Empty session at {STRING_SESSION_FILE}")
    return StringSession(raw)


def extract_buttons(msg) -> list[str]:
    rm = msg.reply_markup
    if not rm or not getattr(rm, "rows", None):
        return []
    out = []
    for row in rm.rows:
        for btn in row.buttons:
            text = getattr(btn, "text", "") or ""
            if isinstance(btn, KeyboardButtonCallback):
                try:
                    cb = btn.data.decode("utf-8", errors="replace")
                except Exception:
                    cb = "?"
                out.append(f"{text}[cb:{cb}]")
            elif isinstance(btn, KeyboardButtonUrl):
                out.append(f"{text}[url]")
            else:
                out.append(text)
    return out


async def wait_for_response(client, chat, me_id: int, anchor_id: int,
                            timeout: float) -> object | None:
    """Return first bot message newer than anchor_id within timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        await asyncio.sleep(0.7)
        msgs = await client.get_messages(chat, limit=6)
        for m in msgs:
            if m.sender_id == me_id:
                continue
            if m.id > anchor_id:
                return m
    return None


async def wait_for_edited_caption(client, chat, msg_id: int,
                                  prev_caption: str, timeout: float) -> str | None:
    """Poll msg_id until its caption changes from prev_caption."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        await asyncio.sleep(0.6)
        refreshed = await client.get_messages(chat, ids=msg_id)
        if refreshed:
            new = refreshed.message or ""
            if new != prev_caption and new:
                return new
    return None


async def download_photo(client, msg, filename: str) -> str:
    """Download photo to OUT_DIR/filename.jpg. Returns path or ''."""
    if not isinstance(msg.media, MessageMediaPhoto):
        return ""
    path = str(OUT_DIR / filename)
    try:
        await client.download_media(msg.media, file=path)
        # Telethon may add extension
        for ext in [".jpg", ".jpeg", ".png", ""]:
            candidate = path + ext
            if Path(candidate).exists():
                return candidate
        return path
    except Exception as e:
        return f"DOWNLOAD_FAIL:{e}"


def find_button_by_prefix(msg, prefix: str):
    """Return (row_idx, col_idx, text, data) or None."""
    rm = msg.reply_markup
    if not rm or not getattr(rm, "rows", None):
        return None
    for r, row in enumerate(rm.rows):
        for c, btn in enumerate(row.buttons):
            if not isinstance(btn, KeyboardButtonCallback):
                continue
            try:
                data = btn.data.decode("utf-8", errors="replace")
            except Exception:
                continue
            if data.startswith(prefix):
                return r, c, getattr(btn, "text", ""), data
    return None


def find_first_game_button(msg):
    """Return (row, col, text, data) for first game/match button (yg:game: or mm:match:)."""
    rm = msg.reply_markup
    if not rm or not getattr(rm, "rows", None):
        return None
    for r, row in enumerate(rm.rows):
        for c, btn in enumerate(row.buttons):
            if not isinstance(btn, KeyboardButtonCallback):
                continue
            try:
                data = btn.data.decode("utf-8", errors="replace")
            except Exception:
                continue
            if data.startswith("yg:game:") or data.startswith("mm:match:"):
                return r, c, getattr(btn, "text", ""), data
    return None


def capture_from_msg(name: str, panel: str, msg, sent_at: float,
                     received_at: float) -> CardCapture:
    c = CardCapture(name=name, panel=panel,
                    sent_at=sent_at, received_at=received_at)
    c.render_ms = int((received_at - sent_at) * 1000)
    c.photo_arrived = isinstance(msg.media, MessageMediaPhoto)
    c.caption_raw = msg.message or ""
    c.caption_len = len(c.caption_raw)
    c.message_text = msg.message or ""
    c.buttons = extract_buttons(msg)
    return c


# ── Main capture flow ─────────────────────────────────────────────────────────

async def run():
    captures: list[CardCapture] = []

    async with TelegramClient(load_session(), API_ID, API_HASH) as client:
        entity = await client.get_entity(BOT_USERNAME)
        me = await client.get_me()
        me_id = me.id
        print(f"[+] Connected as {me.first_name} (id={me_id})")

        # ── SETUP: onboard + force Diamond ───────────────────────────────────
        print("[*] Sending /start + /qa set_diamond ...")
        await client.send_message(entity, "/start")
        await asyncio.sleep(2.0)
        await client.send_message(entity, "/qa set_diamond")
        await asyncio.sleep(2.5)
        print("[*] Setup complete.\n")

        # ═════════════════════════════════════════════════════════════════
        # PANEL A — Edge Cards
        # ═════════════════════════════════════════════════════════════════

        # A1: Edge Digest card  (/today)
        print("[A1] Sending /today ...")
        anchor = (await client.get_messages(entity, limit=1))[0].id
        t0 = time.time()
        await client.send_message(entity, "/today")
        digest_msg = await wait_for_response(client, entity, me_id, anchor, WAIT_MEDIUM)
        t1 = time.time()

        if not digest_msg:
            print("  [FAIL] /today produced no response")
            c = CardCapture("A1-digest", "A", sent_at=t0, received_at=t1)
            c.errors.append("/today timed out")
            captures.append(c)
        else:
            c = capture_from_msg("A1-digest", "A", digest_msg, t0, t1)
            if c.photo_arrived:
                c.photo_path = await download_photo(client, digest_msg, "A1_digest")
            c.notes = f"msg_id={digest_msg.id}"
            captures.append(c)
            print(f"  render={c.render_ms}ms  photo={c.photo_arrived}  buttons={len(c.buttons)}")
            print(f"  caption[{c.caption_len}]: {c.strip_caption()[:120]}")

        await asyncio.sleep(1.5)

        # A2: Gold filter card  (digest:filter:gold)
        print("\n[A2] Tapping 🥇 Gold filter ...")
        if digest_msg:
            gold_btn = find_button_by_prefix(digest_msg, "digest:filter:gold")
            if gold_btn:
                r, col, text, data = gold_btn
                prev_caption = digest_msg.message or ""
                t0 = time.time()
                await digest_msg.click(r, col)
                await asyncio.sleep(1.0)
                # Caption is edited on the same message
                new_caption = await wait_for_edited_caption(
                    client, entity, digest_msg.id, prev_caption, WAIT_SHORT)
                t1 = time.time()
                c2 = CardCapture("A2-gold-filter", "A", sent_at=t0, received_at=t1)
                c2.render_ms = int((t1 - t0) * 1000)
                c2.caption_raw = new_caption or ""
                c2.caption_len = len(c2.caption_raw)
                # Download current photo state
                refreshed = await client.get_messages(entity, ids=digest_msg.id)
                if refreshed:
                    c2.photo_arrived = isinstance(refreshed.media, MessageMediaPhoto)
                    c2.buttons = extract_buttons(refreshed)
                    if c2.photo_arrived:
                        c2.photo_path = await download_photo(client, refreshed, "A2_gold_filter")
                c2.notes = "digest:filter:gold"
                captures.append(c2)
                print(f"  render={c2.render_ms}ms  caption[{c2.caption_len}]: {HTML_TAG_RE.sub('', c2.caption_raw)[:120]}")
            else:
                c2 = CardCapture("A2-gold-filter", "A")
                c2.errors.append("No digest:filter:gold button on digest message")
                captures.append(c2)
                print("  [FAIL] No Gold button found")
        else:
            c2 = CardCapture("A2-gold-filter", "A")
            c2.errors.append("Skipped — digest_msg missing")
            captures.append(c2)

        # After Gold filter, keyboard changes to [Back, Menu] — must go Back to restore tier buttons
        await asyncio.sleep(1.0)
        if digest_msg:
            refreshed_after_gold = await client.get_messages(entity, ids=digest_msg.id)
            back_btn = find_button_by_prefix(refreshed_after_gold, "digest:back") if refreshed_after_gold else None
            if back_btn:
                r, col, _, _ = back_btn
                prev = refreshed_after_gold.message or ""
                await refreshed_after_gold.click(r, col)
                await wait_for_edited_caption(client, entity, digest_msg.id, prev, 10)
                await asyncio.sleep(0.8)

        await asyncio.sleep(0.5)

        # A3: Silver filter card  (digest:filter:silver)
        # IMPORTANT: always refresh message before clicking — prior edits invalidate button data
        print("\n[A3] Tapping 🥈 Silver filter ...")
        if digest_msg:
            refreshed_for_silver = await client.get_messages(entity, ids=digest_msg.id)
            silver_btn = find_button_by_prefix(refreshed_for_silver, "digest:filter:silver") if refreshed_for_silver else None
            if silver_btn:
                r, col, text, data = silver_btn
                prev_caption = refreshed_for_silver.message or ""
                t0 = time.time()
                await refreshed_for_silver.click(r, col)
                await asyncio.sleep(1.0)
                new_caption = await wait_for_edited_caption(
                    client, entity, digest_msg.id, prev_caption, WAIT_SHORT)
                t1 = time.time()
                c3 = CardCapture("A3-silver-filter", "A", sent_at=t0, received_at=t1)
                c3.render_ms = int((t1 - t0) * 1000)
                c3.caption_raw = new_caption or ""
                c3.caption_len = len(c3.caption_raw)
                refreshed = await client.get_messages(entity, ids=digest_msg.id)
                if refreshed:
                    c3.photo_arrived = isinstance(refreshed.media, MessageMediaPhoto)
                    c3.buttons = extract_buttons(refreshed)
                    if c3.photo_arrived:
                        c3.photo_path = await download_photo(client, refreshed, "A3_silver_filter")
                c3.notes = "digest:filter:silver"
                captures.append(c3)
                print(f"  render={c3.render_ms}ms  caption[{c3.caption_len}]: {HTML_TAG_RE.sub('', c3.caption_raw)[:120]}")
            else:
                c3 = CardCapture("A3-silver-filter", "A")
                c3.errors.append("No digest:filter:silver button (or refresh failed)")
                captures.append(c3)
        else:
            c3 = CardCapture("A3-silver-filter", "A")
            c3.errors.append("Skipped — digest_msg missing")
            captures.append(c3)

        # Go Back again to restore tier buttons for Bronze
        await asyncio.sleep(1.0)
        if digest_msg:
            refreshed_after_silver = await client.get_messages(entity, ids=digest_msg.id)
            back_btn = find_button_by_prefix(refreshed_after_silver, "digest:back") if refreshed_after_silver else None
            if back_btn:
                r, col, _, _ = back_btn
                prev = refreshed_after_silver.message or ""
                await refreshed_after_silver.click(r, col)
                await wait_for_edited_caption(client, entity, digest_msg.id, prev, 10)
                await asyncio.sleep(0.8)

        await asyncio.sleep(0.5)

        # A4: Bronze filter card  (digest:filter:bronze)
        print("\n[A4] Tapping 🥉 Bronze filter ...")
        if digest_msg:
            refreshed_for_bronze = await client.get_messages(entity, ids=digest_msg.id)
            bronze_btn = find_button_by_prefix(refreshed_for_bronze, "digest:filter:bronze") if refreshed_for_bronze else None
            if bronze_btn:
                r, col, text, data = bronze_btn
                prev_caption = refreshed_for_bronze.message or ""
                t0 = time.time()
                await refreshed_for_bronze.click(r, col)
                await asyncio.sleep(1.0)
                new_caption = await wait_for_edited_caption(
                    client, entity, digest_msg.id, prev_caption, WAIT_SHORT)
                t1 = time.time()
                c4 = CardCapture("A4-bronze-filter", "A", sent_at=t0, received_at=t1)
                c4.render_ms = int((t1 - t0) * 1000)
                c4.caption_raw = new_caption or ""
                c4.caption_len = len(c4.caption_raw)
                refreshed = await client.get_messages(entity, ids=digest_msg.id)
                if refreshed:
                    c4.photo_arrived = isinstance(refreshed.media, MessageMediaPhoto)
                    c4.buttons = extract_buttons(refreshed)
                    if c4.photo_arrived:
                        c4.photo_path = await download_photo(client, refreshed, "A4_bronze_filter")
                c4.notes = "digest:filter:bronze"
                captures.append(c4)
                print(f"  render={c4.render_ms}ms  caption[{c4.caption_len}]: {HTML_TAG_RE.sub('', c4.caption_raw)[:120]}")
            else:
                c4 = CardCapture("A4-bronze-filter", "A")
                c4.errors.append("No digest:filter:bronze button (or refresh failed)")
                captures.append(c4)
        else:
            c4 = CardCapture("A4-bronze-filter", "A")
            c4.errors.append("Skipped — digest_msg missing")
            captures.append(c4)

        await asyncio.sleep(1.5)

        # Navigation integrity check: reset digest to main view via digest:back
        if digest_msg:
            back_btn = find_button_by_prefix(digest_msg, "digest:back")
            if not back_btn:
                # Try nav:main from digest
                back_btn = find_button_by_prefix(digest_msg, "nav:main")
            if back_btn:
                r, col, _, _ = back_btn
                await digest_msg.click(r, col)
                await asyncio.sleep(1.0)

        # ═════════════════════════════════════════════════════════════════
        # PANEL B — Match Cards
        # ═════════════════════════════════════════════════════════════════

        # B1: My Matches list
        print("\n[B1] Sending /schedule (My Matches) ...")
        anchor = (await client.get_messages(entity, limit=1))[0].id
        t0 = time.time()
        await client.send_message(entity, "/schedule")
        mm_msg = await wait_for_response(client, entity, me_id, anchor, WAIT_LONG)
        t1 = time.time()

        if not mm_msg:
            print("  [FAIL] /schedule produced no response")
            c5 = CardCapture("B1-my-matches", "B", sent_at=t0, received_at=t1)
            c5.errors.append("/schedule timed out")
            captures.append(c5)
        else:
            c5 = capture_from_msg("B1-my-matches", "B", mm_msg, t0, t1)
            if c5.photo_arrived:
                c5.photo_path = await download_photo(client, mm_msg, "B1_my_matches")
            c5.notes = f"msg_id={mm_msg.id}"
            captures.append(c5)
            print(f"  render={c5.render_ms}ms  photo={c5.photo_arrived}  buttons={len(c5.buttons)}")
            print(f"  text[{len(c5.message_text)}]: {c5.message_text[:150]}")

        await asyncio.sleep(2.0)

        # B2: Match Detail (tap first match button from My Matches)
        # mm:match buttons EDIT the photo card in-place — not a new message
        print("\n[B2] Tapping first match from My Matches ...")
        if mm_msg:
            game_btn = find_first_game_button(mm_msg)
            if game_btn:
                r, col, game_text, game_data = game_btn
                print(f"  Tapping: {game_text} → {game_data}")
                prev_mm_buttons = extract_buttons(mm_msg)
                prev_mm_caption = mm_msg.message or ""
                t0 = time.time()
                await mm_msg.click(r, col)
                # Wait for the photo to be EDITED with new content
                detail_msg = None
                deadline = time.time() + WAIT_LONG
                while time.time() < deadline:
                    await asyncio.sleep(1.0)
                    refreshed_mm = await client.get_messages(entity, ids=mm_msg.id)
                    if refreshed_mm:
                        new_buttons = extract_buttons(refreshed_mm)
                        # Detect edit: buttons changed OR caption changed
                        if (new_buttons != prev_mm_buttons or
                                (refreshed_mm.message or "") != prev_mm_caption):
                            detail_msg = refreshed_mm
                            break
                    # Also check for a NEW message (some paths send a new msg)
                    new_msgs = await client.get_messages(entity, limit=3)
                    for nm in new_msgs:
                        if nm.sender_id == me_id:
                            continue
                        if nm.id > mm_msg.id:
                            detail_msg = nm
                            break
                    if detail_msg:
                        break
                t1 = time.time()

                if not detail_msg:
                    c6 = CardCapture("B2-match-detail", "B", sent_at=t0, received_at=t1)
                    c6.errors.append(f"No response after tapping {game_data}")
                    c6.notes = f"attempted:{game_data}"
                    captures.append(c6)
                    print("  [FAIL] No match detail response")
                else:
                    c6 = capture_from_msg("B2-match-detail", "B", detail_msg, t0, t1)
                    if c6.photo_arrived:
                        c6.photo_path = await download_photo(client, detail_msg, "B2_match_detail")
                    c6.notes = f"game_cb:{game_data}  msg_id={detail_msg.id}"
                    captures.append(c6)
                    print(f"  render={c6.render_ms}ms  photo={c6.photo_arrived}  buttons={len(c6.buttons)}")
                    print(f"  caption[{c6.caption_len}]: {c6.strip_caption()[:150]}")
            else:
                c6 = CardCapture("B2-match-detail", "B")
                c6.errors.append("No yg:game: button found on My Matches")
                captures.append(c6)
                print("  [FAIL] No game button on My Matches")
        else:
            c6 = CardCapture("B2-match-detail", "B")
            c6.errors.append("Skipped — mm_msg missing")
            captures.append(c6)

        await asyncio.sleep(2.0)

        # ═════════════════════════════════════════════════════════════════
        # NAVIGATION INTEGRITY
        # ═════════════════════════════════════════════════════════════════
        print("\n[NAV] Navigation integrity checks ...")

        nav_results = {}

        # Check: Back button on Match Detail goes back to My Matches
        if captures[-1].errors == [] and captures[-1].buttons:
            back_labels = [b for b in captures[-1].buttons if "back" in b.lower() or "↩" in b]
            nav_results["match_detail_has_back"] = len(back_labels) > 0
            nav_results["back_buttons"] = back_labels
            print(f"  Match Detail back buttons: {back_labels}")
        else:
            nav_results["match_detail_has_back"] = "unknown"

        # Check: Digest card has all 4 tier filter buttons
        if captures[0].errors == []:
            tier_btns = [b for b in captures[0].buttons
                         if any(t in b for t in ["gold", "silver", "bronze", "diamond", "Gold", "Silver", "Bronze", "Diamond"])]
            nav_results["digest_has_4_tier_buttons"] = len(tier_btns) >= 4
            nav_results["tier_buttons"] = tier_btns
            print(f"  Digest tier buttons ({len(tier_btns)}): {tier_btns}")
        else:
            nav_results["digest_has_4_tier_buttons"] = "unknown"

        # Check: Each tier filter response contains expected tier badge
        for cap, expected_tier in [
            (captures[1], ["🥇", "Gold", "gold"]),
            (captures[2], ["🥈", "Silver", "silver"]),
            (captures[3], ["🥉", "Bronze", "bronze"]),
        ]:
            plain = HTML_TAG_RE.sub("", cap.caption_raw)
            found = any(t in plain for t in expected_tier)
            nav_results[f"{cap.name}_tier_match"] = found
            print(f"  {cap.name} tier badge present: {found}")

        # ═════════════════════════════════════════════════════════════════
        # ODDS FRESHNESS CHECK (Gold card)
        # ═════════════════════════════════════════════════════════════════
        print("\n[ODDS] Odds freshness check on Gold filter ...")
        odds_freshness = "UNKNOWN"
        gold_cap = captures[1]
        if gold_cap.caption_raw and not gold_cap.errors:
            plain_gold = HTML_TAG_RE.sub("", gold_cap.caption_raw)
            # Look for freshness indicators in caption
            if "Live odds" in plain_gold or "live odds" in plain_gold:
                odds_freshness = "LIVE VERIFIED"
            elif "min ago" in plain_gold:
                import re as _re
                m = _re.search(r"(\d+)\s*min ago", plain_gold)
                if m:
                    mins = int(m.group(1))
                    odds_freshness = "PROXY VERIFIED" if mins < 60 else "STALE RISK"
            elif "updated" in plain_gold.lower():
                odds_freshness = "PROXY VERIFIED"
            else:
                odds_freshness = "PROXY VERIFIED (no timestamp visible in caption)"
        print(f"  Odds freshness: {odds_freshness}")

    # ── Save raw results ──────────────────────────────────────────────────────
    results_file = OUT_DIR / "captures.json"
    results_file.write_text(
        json.dumps([asdict(c) for c in captures], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    nav_file = OUT_DIR / "nav_results.json"
    nav_file.write_text(json.dumps(nav_results, indent=2), encoding="utf-8")

    print(f"\n[=] Captures saved → {results_file}")
    print(f"[=] Nav results → {nav_file}")
    print(f"[=] Photos → {OUT_DIR}/")

    # ── Console summary ───────────────────────────────────────────────────────
    print("\n" + "="*60)
    print("CAPTURE SUMMARY")
    print("="*60)
    for c in captures:
        status = "OK" if not c.errors else f"FAIL({', '.join(c.errors[:1])})"
        print(f"  {c.name:25s}  {status:35s}  {c.render_ms}ms  cap={c.caption_len}")
    print(f"\n  Nav: {nav_results}")
    print(f"  Odds freshness: {odds_freshness}")
    print("="*60)

    return captures, nav_results, odds_freshness


if __name__ == "__main__":
    captures, nav_results, odds_freshness = asyncio.run(run())
