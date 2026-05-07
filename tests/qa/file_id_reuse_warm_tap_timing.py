#!/usr/bin/env python3
"""FIX-FILE-ID-REUSE-AC5-AC6-01 (AC6) — Telethon warm-tap timing.

End-to-end Telethon test against the LIVE bot. Validates that the persisted
Telegram file_id cache (BUILD-FILE-ID-REUSE-01 / RESCUE-01) actually short-
circuits Playwright render + photo upload on a repeat tap.

Sequence
--------
1. Send the sticky-keyboard "Top Edge Picks" text. Find the first unlocked
   Edge Detail inline button.
2. Tap it once — measure latency end-to-end (cold render: HTML → PNG → upload).
3. Wait 60s.
4. Tap the same button again — measure latency (warm tap: file_id reuse).
5. Assert:
     warm < 200 ms  (the AC6 SLO)
     cold / warm > 1.5  (sanity — confirms we are not just measuring a fast
                          network; cold path must be materially slower)

Skipped gracefully if no Edge card surfaces in the test window.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

_BOT_DIR = Path(__file__).parent.parent.parent
load_dotenv(_BOT_DIR / ".env")

from telethon import TelegramClient  # noqa: E402
from telethon.sessions import StringSession  # noqa: E402
from telethon.tl.types import (  # noqa: E402
    KeyboardButtonCallback,
    ReplyInlineMarkup,
)

API_ID = int(os.getenv("TELEGRAM_API_ID", "32418601"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "95e313a8ef5b998be0515dd8328fac57")
BOT_USERNAME = "@mzansiedge_bot"
SESSION_FILE = str(_BOT_DIR / "data" / "telethon_qa_session.string")

OUT_DIR = Path("/tmp/qa_file_id_reuse_warm_tap_timing")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Tap timing knobs
TAP_TIMEOUT = 8.0
TAP_POLL = 0.05
WARM_GAP_SECONDS = 60.0

WARM_SLO_MS = 200.0
COLD_WARM_RATIO_MIN = 1.5


def _load_session() -> StringSession:
    p = Path(SESSION_FILE)
    if not p.is_file():
        raise SystemExit(f"missing session file: {p}")
    s = p.read_text().strip()
    if not s:
        raise SystemExit(f"empty session file: {p}")
    return StringSession(s)


async def _wait_for_edit_or_new(client, entity, source_msg_id: int,
                                timeout: float = TAP_TIMEOUT
                                ) -> tuple[object | None, float]:
    """Return (msg, elapsed_seconds) once a new bot msg appears OR the source
    message is edited after our tap. Polls every TAP_POLL seconds.
    """
    start = time.perf_counter()
    snap = await client.get_messages(entity, limit=5)
    pre_edit_dates: dict[int, object] = {
        m.id: getattr(m, "edit_date", None) for m in snap if not m.out
    }
    pre_max_id = max((m.id for m in snap if not m.out), default=source_msg_id)

    while time.perf_counter() - start < timeout:
        msgs = await client.get_messages(entity, limit=5)
        for m in msgs:
            if m.out:
                continue
            if m.id > pre_max_id:
                return m, time.perf_counter() - start
            if m.id in pre_edit_dates:
                cur_ed = getattr(m, "edit_date", None)
                if cur_ed != pre_edit_dates[m.id]:
                    return m, time.perf_counter() - start
        await asyncio.sleep(TAP_POLL)
    return None, time.perf_counter() - start


def _find_edge_callback(msg) -> bytes | None:
    """Return the first inline-button callback whose data starts with
    'edge:detail:' or 'ep:pick:'. Skip locked entries (which carry 'sub:plans')."""
    rm = getattr(msg, "reply_markup", None)
    if not isinstance(rm, ReplyInlineMarkup):
        return None
    for row in rm.rows:
        for btn in row.buttons:
            if not isinstance(btn, KeyboardButtonCallback):
                continue
            data = btn.data or b""
            if data.startswith(b"edge:detail:") or data.startswith(b"ep:pick:"):
                return data
    return None


async def _find_edge_button_in_recent(client, entity, max_back: int = 12) -> tuple[bytes | None, int]:
    """Look back through recent bot messages for the first Edge inline button.
    Returns (callback_data, message_id) or (None, -1).
    """
    msgs = await client.get_messages(entity, limit=max_back)
    for m in msgs:
        if m.out:
            continue
        cb = _find_edge_callback(m)
        if cb:
            return cb, m.id
    return None, -1


async def main() -> int:
    client = TelegramClient(_load_session(), API_ID, API_HASH)
    await client.start()
    entity = await client.get_entity(BOT_USERNAME)

    result: dict = {
        "wave": "FIX-FILE-ID-REUSE-AC5-AC6-01",
        "test": "ac6_warm_tap_timing",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "warm_slo_ms": WARM_SLO_MS,
        "cold_warm_ratio_min": COLD_WARM_RATIO_MIN,
    }
    exit_code = 0

    try:
        # 1) Trigger Edge Picks list.
        await client.send_message(entity, "💎 Top Edge Picks")
        await asyncio.sleep(2.5)  # let the list render

        cb, src_id = await _find_edge_button_in_recent(client, entity)
        if cb is None:
            result["status"] = "skipped"
            result["reason"] = "no Edge inline button found — list empty in test window"
            print(json.dumps(result, indent=2))
            return 0

        result["callback_data"] = cb.decode("utf-8", errors="replace")

        # 2) COLD tap.
        t0 = time.perf_counter()
        await client(__import__(
            "telethon.tl.functions.messages", fromlist=["GetBotCallbackAnswerRequest"]
        ).GetBotCallbackAnswerRequest(peer=entity, msg_id=src_id, data=cb))
        cold_msg, _cold_elapsed = await _wait_for_edit_or_new(client, entity, src_id)
        cold_total = time.perf_counter() - t0
        if cold_msg is None:
            result["status"] = "fail"
            result["reason"] = f"cold tap produced no response within {TAP_TIMEOUT}s"
            print(json.dumps(result, indent=2))
            return 1
        result["cold_ms"] = round(cold_total * 1000, 1)

        # 3) Warm gap — give the bot's send_photo response time to land in
        #    Telegram's CDN so the file_id is fully usable.
        await asyncio.sleep(WARM_GAP_SECONDS)

        # 4) WARM tap (same callback, same source message).
        t1 = time.perf_counter()
        await client(__import__(
            "telethon.tl.functions.messages", fromlist=["GetBotCallbackAnswerRequest"]
        ).GetBotCallbackAnswerRequest(peer=entity, msg_id=src_id, data=cb))
        warm_msg, _warm_elapsed = await _wait_for_edit_or_new(client, entity, src_id)
        warm_total = time.perf_counter() - t1
        if warm_msg is None:
            result["status"] = "fail"
            result["reason"] = f"warm tap produced no response within {TAP_TIMEOUT}s"
            print(json.dumps(result, indent=2))
            return 1
        result["warm_ms"] = round(warm_total * 1000, 1)

        # 5) Assertions.
        ratio = (cold_total / warm_total) if warm_total > 0 else float("inf")
        result["cold_warm_ratio"] = round(ratio, 2)

        warm_ms = result["warm_ms"]
        ok_warm = warm_ms < WARM_SLO_MS
        ok_ratio = ratio > COLD_WARM_RATIO_MIN

        if ok_warm and ok_ratio:
            result["status"] = "pass"
        else:
            result["status"] = "fail"
            reasons = []
            if not ok_warm:
                reasons.append(f"warm {warm_ms} ms ≥ {WARM_SLO_MS} ms SLO")
            if not ok_ratio:
                reasons.append(
                    f"cold/warm ratio {ratio:.2f} ≤ {COLD_WARM_RATIO_MIN} (sanity)"
                )
            result["reason"] = "; ".join(reasons)
            exit_code = 1

        print(json.dumps(result, indent=2))
        out_path = OUT_DIR / f"timing_{int(time.time())}.json"
        out_path.write_text(json.dumps(result, indent=2))
        return exit_code
    finally:
        await client.disconnect()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
