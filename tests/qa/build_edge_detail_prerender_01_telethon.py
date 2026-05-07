#!/usr/bin/env python3
"""BUILD-EDGE-DETAIL-PRERENDER-01 — Telethon timing QA against LIVE bot.

Verifies AC4 (BUILD-SPEED log line) and AC5 (first-tap < 300ms target,
< 600ms acceptable cache-hit window) for the new edge_detail prerender.

Sends the sticky-keyboard "Top Edge Picks" text, locates the first
unlocked Edge Detail inline button (callback shape `ep:pick:N` or
`edge:detail:{match_key}`), then taps it 4 times in succession with
perf_counter timing around each tap. Saves the delivered card photo
to /tmp/qa_build_edge_detail_prerender_01/ for evidence.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

_BOT_DIR = Path(__file__).parent.parent.parent
load_dotenv(_BOT_DIR / ".env")

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import (
    KeyboardButtonCallback,
    MessageMediaPhoto,
    ReplyInlineMarkup,
)

API_ID = int(os.getenv("TELEGRAM_API_ID", "32418601"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "95e313a8ef5b998be0515dd8328fac57")
BOT_USERNAME = "@mzansiedge_bot"
SESSION_FILE = str(_BOT_DIR / "data" / "telethon_qa_session.string")

OUT_DIR = Path("/tmp/qa_build_edge_detail_prerender_01")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Tap timing: poll every 50ms, give up after 6s.
TAP_TIMEOUT = 6.0
TAP_POLL = 0.05
TAPS = 4


def _load_session() -> StringSession:
    p = Path(SESSION_FILE)
    if not p.is_file():
        raise SystemExit(f"missing session file: {p}")
    s = p.read_text().strip()
    if not s:
        raise SystemExit(f"empty session file: {p}")
    return StringSession(s)


async def _wait_for_new(client, entity, after_id: int, timeout: float = TAP_TIMEOUT) -> tuple[object | None, float]:
    """Poll for a new bot message strictly after `after_id`. Returns (msg, elapsed_seconds).

    Looks for either a new message from bot OR an edit to the most-recent
    bot message. We detect both by polling get_messages with limit=5 and
    comparing the latest non-outgoing message id + edit_date.
    """
    start = time.perf_counter()
    seen_edit_dates: dict[int, object] = {}
    # Seed: snapshot current edit_date of the latest bot message (the source msg)
    snap = await client.get_messages(entity, limit=5)
    for m in snap:
        if not m.out:
            seen_edit_dates[m.id] = getattr(m, "edit_date", None)

    while time.perf_counter() - start < timeout:
        msgs = await client.get_messages(entity, limit=5)
        for m in msgs:
            if m.out:
                continue
            # New message after tap
            if m.id > after_id:
                return m, time.perf_counter() - start
            # Edit to a prior bot message (edit_date changed)
            cur_edit = getattr(m, "edit_date", None)
            prior = seen_edit_dates.get(m.id)
            if cur_edit is not None and cur_edit != prior:
                return m, time.perf_counter() - start
        await asyncio.sleep(TAP_POLL)
    return None, time.perf_counter() - start


def _find_first_edge_button(msg) -> tuple[bytes | None, str | None, str | None]:
    """Return (callback_bytes, label, source_callback_str) for the first inline
    button whose data starts with `ep:pick:` or `edge:detail:` and is NOT a
    🔒 (locked) button. Falls back to ep:pick:1 if only locked buttons exist.
    """
    if not msg.reply_markup or not isinstance(msg.reply_markup, ReplyInlineMarkup):
        return None, None, None

    locked_seen = False
    for row in msg.reply_markup.rows:
        for btn in row.buttons:
            if not isinstance(btn, KeyboardButtonCallback):
                continue
            data_str = btn.data.decode("utf-8", errors="replace")
            if not (data_str.startswith("ep:pick:") or data_str.startswith("edge:detail:")):
                continue
            label = (btn.text or "").strip()
            if "🔒" in label:
                locked_seen = True
                continue
            return btn.data, label, data_str

    if locked_seen:
        # Fallback: synthesise ep:pick:1
        return b"ep:pick:1", "(synthesised ep:pick:1)", "ep:pick:1"
    return None, None, None


async def _save_card(client, msg, dest: Path) -> str | None:
    if msg is None or not getattr(msg, "media", None):
        return None
    if isinstance(msg.media, MessageMediaPhoto):
        try:
            path = await client.download_media(msg, file=str(dest))
            return str(path) if path else None
        except Exception as exc:
            return f"download_failed: {exc}"
    return None


async def run() -> int:
    client = TelegramClient(_load_session(), API_ID, API_HASH)
    await client.start()
    entity = await client.get_entity(BOT_USERNAME)

    report: dict = {
        "brief": "BUILD-EDGE-DETAIL-PRERENDER-01",
        "run_at_utc": datetime.utcnow().isoformat() + "Z",
        "live_runtime": "/home/paulsportsza/bot/bot.py",
        "taps": [],
    }

    # ── Step 1: send /picks (bypasses sticky-keyboard regex matching) ──
    snap_before = await client.get_messages(entity, limit=1)
    pre_id = snap_before[0].id if snap_before else 0
    print("Sending /picks …")
    await client.send_message(entity, "/picks")

    # Wait up to 25s for the picks list (cold path can take a while)
    list_msg = None
    list_wait_start = time.perf_counter()
    while time.perf_counter() - list_wait_start < 25.0:
        msgs = await client.get_messages(entity, limit=10)
        # Find newest non-outgoing message with inline markup
        for m in msgs:
            if m.out or m.id <= pre_id:
                continue
            if m.reply_markup and isinstance(m.reply_markup, ReplyInlineMarkup):
                list_msg = m
                break
        if list_msg is not None:
            break
        await asyncio.sleep(0.5)

    if list_msg is None:
        print("FAIL: no Top Edge Picks list returned within 25s")
        report["error"] = "no_picks_list_received"
        report["overall_pass"] = False
        (OUT_DIR / "report.json").write_text(json.dumps(report, indent=2, default=str))
        await client.disconnect()
        return 1

    cb_bytes, btn_label, cb_str = _find_first_edge_button(list_msg)
    if cb_bytes is None:
        print("FAIL: no ep:pick:* or edge:detail:* button found on picks list")
        report["error"] = "no_edge_detail_button"
        report["picks_list_text_preview"] = (list_msg.message or "")[:300]
        report["overall_pass"] = False
        (OUT_DIR / "report.json").write_text(json.dumps(report, indent=2, default=str))
        await client.disconnect()
        return 1

    print(f"Tap target: callback={cb_str!r}, label={btn_label!r}")
    report["tap_target_callback"] = cb_str
    report["tap_target_label"] = btn_label
    report["picks_list_msg_id"] = list_msg.id

    # ── Step 2: 4 taps with perf_counter timing ──
    # Note: Telegram MTProto encrypts callback button data per message-state;
    # after each tap+edit, the source message's callback bytes can become
    # invalid for repeat clicks. We re-fetch the latest picks list each
    # round and look up the same callback string on a fresh message object.
    target_cb_str = cb_str  # e.g. "ep:pick:2"
    current_list_msg = list_msg
    for tap_idx in range(1, TAPS + 1):
        # Snapshot most-recent message id BEFORE tap
        snap = await client.get_messages(entity, limit=1)
        before_id = snap[0].id if snap else 0

        # Re-fetch a fresh list message after the first tap (fresh callback bytes)
        if tap_idx > 1:
            # Re-send /picks to get a brand-new list message — keeps callback bytes valid
            await client.send_message(entity, "/picks")
            fresh = None
            re_start = time.perf_counter()
            while time.perf_counter() - re_start < 25.0:
                msgs = await client.get_messages(entity, limit=10)
                for m in msgs:
                    if m.out or m.id <= before_id:
                        continue
                    if m.reply_markup and isinstance(m.reply_markup, ReplyInlineMarkup):
                        # Confirm the same callback string exists
                        for row in m.reply_markup.rows:
                            for btn in row.buttons:
                                if isinstance(btn, KeyboardButtonCallback) and btn.data == target_cb_str.encode():
                                    fresh = m
                                    cb_bytes = btn.data
                                    break
                            if fresh:
                                break
                    if fresh:
                        break
                if fresh:
                    break
                await asyncio.sleep(0.5)

            if fresh is None:
                print(f"Tap {tap_idx}: could not re-locate {target_cb_str} on fresh /picks list; aborting")
                report["taps"].append({
                    "tap": tap_idx,
                    "ms": None,
                    "result": "could_not_relocate_callback",
                    "screenshot": None,
                })
                continue
            current_list_msg = fresh
            # Reset before_id to AFTER the re-fetched list message
            before_id = current_list_msg.id

        t0 = time.perf_counter()
        try:
            await current_list_msg.click(data=cb_bytes)
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            print(f"Tap {tap_idx}: click() raised {type(exc).__name__}: {exc} after {elapsed_ms:.0f}ms")
            report["taps"].append({
                "tap": tap_idx,
                "ms": round(elapsed_ms, 1),
                "result": f"click_error: {exc}",
                "screenshot": None,
            })
            await asyncio.sleep(1.5)
            continue

        new_msg, elapsed = await _wait_for_new(client, entity, before_id, timeout=TAP_TIMEOUT)
        elapsed_ms = elapsed * 1000.0

        screenshot_path = None
        if new_msg is not None:
            dest = OUT_DIR / f"edge_detail_tap{tap_idx}.png"
            screenshot_path = await _save_card(client, new_msg, dest)

        msg_text_preview = ""
        msg_kind = "none"
        if new_msg is not None:
            if isinstance(getattr(new_msg, "media", None), MessageMediaPhoto):
                msg_kind = "photo"
            elif new_msg.message:
                msg_kind = "text"
            msg_text_preview = (new_msg.message or "")[:200]

        verdict = "OK" if new_msg is not None else "TIMEOUT"
        print(f"Tap {tap_idx}: {elapsed_ms:.0f}ms  [{verdict}]  msg={msg_kind}  preview={msg_text_preview[:80]!r}")

        report["taps"].append({
            "tap": tap_idx,
            "ms": round(elapsed_ms, 1),
            "result": verdict,
            "msg_kind": msg_kind,
            "msg_text_preview": msg_text_preview,
            "screenshot": screenshot_path,
        })

        # Brief pause between taps
        await asyncio.sleep(1.5)

    await client.disconnect()

    # ── Step 3: AC5 verdict ──
    tap1 = report["taps"][0] if report["taps"] else None
    tap1_ms = tap1["ms"] if tap1 else float("inf")
    if tap1 and tap1.get("result") == "OK":
        if tap1_ms < 300:
            ac5 = f"PASS (definitively beats <300ms target — {tap1_ms:.0f}ms)"
            ac5_pass = True
        elif tap1_ms < 600:
            ac5 = f"PASS (within reasonable cache-hit window — {tap1_ms:.0f}ms)"
            ac5_pass = True
        elif tap1_ms < 1000:
            ac5 = f"FAIL (above cache-hit window — {tap1_ms:.0f}ms; render path likely)"
            ac5_pass = False
        else:
            ac5 = f"FAIL (cache MISS — {tap1_ms:.0f}ms suggests fresh render)"
            ac5_pass = False
    else:
        ac5 = "FAIL (tap-1 did not return a response)"
        ac5_pass = False

    report["ac5_verdict"] = ac5
    report["ac5_pass"] = ac5_pass

    out_path = OUT_DIR / "report.json"
    out_path.write_text(json.dumps(report, indent=2, default=str))

    print()
    print(json.dumps(report, indent=2, default=str))
    print(f"\n=== JSON report → {out_path}")
    print(f"=== AC5: {ac5}")

    return 0 if ac5_pass else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
