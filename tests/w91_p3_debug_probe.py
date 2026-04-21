#!/usr/bin/env python3
# ruff: noqa
"""Debug probe: figure out what the bot actually returns for three navigation paths.

Saves a JSON log to /tmp/w91_p3_debug_probe.json and prints a summary.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path

from dotenv import load_dotenv

BOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BOT_DIR / ".env")

from telethon import TelegramClient  # noqa: E402
from telethon.sessions import StringSession  # noqa: E402
from telethon.tl.types import (  # noqa: E402
    KeyboardButtonCallback,
    MessageMediaPhoto,
)

API_ID = int(os.getenv("TELEGRAM_API_ID", "32418601"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "95e313a8ef5b998be0515dd8328fac57")
BOT_USERNAME = "@mzansiedge_bot"
SESSION_STRING = (BOT_DIR / "data" / "telethon_session.string").read_text().strip()


def _describe_msg(m) -> dict:
    out: dict = {
        "id": m.id,
        "date": m.date.isoformat() if m.date else None,
        "from_id": getattr(m.sender_id, "user_id", m.sender_id),
        "has_photo": isinstance(m.media, MessageMediaPhoto),
        "text_head": (m.text or "")[:200],
        "message_head": (getattr(m, "message", "") or "")[:200],
    }
    rm = m.reply_markup
    if rm and getattr(rm, "rows", None):
        rows: list[list] = []
        for row in rm.rows:
            cells = []
            for btn in row.buttons:
                data = ""
                if isinstance(btn, KeyboardButtonCallback):
                    try:
                        data = btn.data.decode("utf-8", errors="replace")
                    except Exception:
                        data = str(btn.data)
                cells.append({
                    "type": type(btn).__name__,
                    "text": getattr(btn, "text", ""),
                    "data": data,
                })
            rows.append(cells)
        out["reply_markup_rows"] = rows
    else:
        out["reply_markup_rows"] = None
    return out


async def run() -> None:
    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
    await client.start()
    entity = await client.get_entity(BOT_USERNAME)
    me = await client.get_me()

    log: dict = {"me_id": me.id, "probes": []}

    async def probe(label: str, sender_coro, wait_s: float):
        t0 = time.time()
        msgs_before = await client.get_messages(entity, limit=1)
        anchor = msgs_before[0].id if msgs_before else 0
        await sender_coro
        # collect every bot msg that arrives within wait_s
        deadline = time.time() + wait_s
        seen: dict[int, dict] = {}
        while time.time() < deadline:
            await asyncio.sleep(0.5)
            msgs = await client.get_messages(entity, limit=8)
            for m in msgs:
                if m.sender_id == me.id:
                    continue
                if m.id <= anchor:
                    continue
                # always re-capture (messages can be edited) — overwrite
                seen[m.id] = _describe_msg(m)
        log["probes"].append({
            "label": label,
            "elapsed_s": round(time.time() - t0, 2),
            "messages": list(seen.values()),
        })

    # 1. /start (onboard / wake)
    await probe("/start", client.send_message(entity, "/start"), 6.0)

    # 2. tap "💎 Top Edge Picks" as text (sticky keyboard)
    await probe(
        "sticky_keyboard_text",
        client.send_message(entity, "💎 Top Edge Picks"),
        10.0,
    )

    # 3. /picks command
    await probe("/picks", client.send_message(entity, "/picks"), 10.0)

    # 4. /qa set_diamond (admin only)
    await probe("/qa set_diamond", client.send_message(entity, "/qa set_diamond"), 5.0)

    # 5. /picks after /qa set_diamond
    await probe("/picks post-qa", client.send_message(entity, "/picks"), 12.0)

    out_path = Path("/tmp/w91_p3_debug_probe.json")
    out_path.write_text(json.dumps(log, indent=2, ensure_ascii=False, default=str))
    print(f"debug log → {out_path}")

    # Summary
    for probe_entry in log["probes"]:
        print(f"\n=== {probe_entry['label']}  ({probe_entry['elapsed_s']}s) ===")
        for m in probe_entry["messages"]:
            cbcount = 0
            if m["reply_markup_rows"]:
                for row in m["reply_markup_rows"]:
                    cbcount += sum(1 for btn in row if btn.get("data"))
            print(f"  id={m['id']} photo={m['has_photo']} cb_btns={cbcount}  text={m['text_head'][:80]!r}")

    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(run())
