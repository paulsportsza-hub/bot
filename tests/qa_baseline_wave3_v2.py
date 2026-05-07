#!/usr/bin/env python3
"""QA-BASELINE-WAVE3-01 v2 — targeted probe using correct callbacks.

ep:pick:N → Edge Detail
yg:all:0  → My Matches list
mm:match:N:e (edge) / mm:match:N:n (non-edge)
md:back   → back to My Matches
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from telethon import TelegramClient
from telethon.sessions import StringSession

API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "")
BOT_USERNAME = "mzansiedge_bot"
STRING_SESSION_FILE = ROOT / "data" / "telethon_qa_session.string"

OUT = Path("/tmp/qa_w3")
OUT.mkdir(parents=True, exist_ok=True)


async def get_client():
    s = STRING_SESSION_FILE.read_text().strip()
    c = TelegramClient(StringSession(s), API_ID, API_HASH)
    await c.connect()
    if not await c.is_user_authorized():
        raise SystemExit("not auth")
    return c


def strip_html(t):
    return re.sub(r"<[^>]+>", "", t or "")


def buttons(msg):
    out = []
    if not msg or not msg.reply_markup:
        return out
    for row in msg.reply_markup.rows:
        for b in row.buttons:
            cb = ""
            if hasattr(b, "data") and b.data:
                cb = b.data.decode("utf-8", "ignore") if isinstance(b.data, bytes) else str(b.data)
            out.append({"text": getattr(b, "text", ""), "data": cb})
    return out


async def send(c, text, wait=4.0):
    sent = await c.send_message(BOT_USERNAME, text)
    await asyncio.sleep(wait)
    msgs = await c.get_messages(BOT_USERNAME, limit=6)
    return [m for m in msgs if not m.out and m.id >= sent.id]


async def click_cb(c, msg, cb_substr, wait=6.0):
    """Click a button whose callback_data starts with or contains substring."""
    if not msg or not msg.reply_markup:
        return None
    target = None
    for row in msg.reply_markup.rows:
        for b in row.buttons:
            if hasattr(b, "data") and b.data:
                cb = b.data.decode("utf-8", "ignore") if isinstance(b.data, bytes) else str(b.data)
                if cb_substr in cb:
                    target = b
                    break
        if target:
            break
    if not target:
        return None
    try:
        await msg.click(data=target.data)
    except Exception as e:
        return {"_error": str(e)}
    await asyncio.sleep(wait)
    msgs = await c.get_messages(BOT_USERNAME, limit=4)
    return next((m for m in msgs if not m.out), None)


def card_text(msg):
    if not msg:
        return ""
    return msg.text or msg.message or ""


def count_chips(t):
    """Count bookmaker · odds chip lines."""
    plain = strip_html(t)
    pat = re.compile(r"^\s*[A-Za-z][A-Za-z\s\.\d]+?\s*[·\|]\s*\d+\.\d{1,2}\s*$", re.M)
    return len(pat.findall(plain))


def count_chip_alt(t):
    """Alternative: count Bookmaker odds rendered as text-button-like."""
    plain = strip_html(t)
    return len(re.findall(r"\b\d+\.\d{2}\b", plain))


def find_verdict(t):
    plain = strip_html(t)
    m = re.search(r"(?:Verdict|Bottom line|Take|My take|Edge:)[:\s]+(.+?)(?:\n\n|\Z)", plain, re.I | re.S)
    if m:
        return m.group(1).strip()
    lines = [l.strip() for l in plain.splitlines() if 60 < len(l.strip()) < 400]
    return max(lines, key=len) if lines else plain.strip()[:300]


async def main():
    ev = {}
    c = await get_client()
    try:
        # Reset to clean state then set Diamond
        await send(c, "/qa reset", wait=3)
        msgs = await send(c, "/qa set_diamond", wait=2)
        ev["set_diamond"] = strip_html((msgs[0].text or "")) if msgs else ""

        # Open Edge Picks
        msgs = await send(c, "/picks", wait=8)
        picks = msgs[0] if msgs else None
        ev["picks_text"] = strip_html(card_text(picks))[:500]
        ev["picks_buttons"] = buttons(picks)[:12]

        # Click ep:pick:0 → Edge Detail (Diamond, full content)
        detail = await click_cb(c, picks, "ep:pick:0", wait=8)
        det_text = card_text(detail)
        ev["edge_detail_text"] = strip_html(det_text)[:1500]
        ev["edge_detail_buttons"] = buttons(detail)[:12]
        # Photo? Check media
        ev["edge_detail_has_photo"] = bool(detail and detail.photo)
        ev["edge_detail_chip_strict"] = count_chips(det_text)
        ev["edge_detail_decimal_count"] = count_chip_alt(det_text)
        verdict = find_verdict(det_text)
        ev["edge_detail_verdict"] = verdict
        ev["edge_detail_verdict_chars"] = len(verdict)

        # Click Back from Edge Detail (hot:back:0)
        back_msg = await click_cb(c, detail, "hot:back", wait=6)
        ev["back_from_edge_text"] = strip_html(card_text(back_msg))[:300]
        ev["back_from_edge_buttons"] = [b["data"] for b in buttons(back_msg)][:8]

        # Open My Matches via yg:all:0 callback (need a button with that)
        # /picks should have main menu access; try direct callback by sending /start first
        msgs = await send(c, "/start", wait=4)
        start = msgs[0] if msgs else None
        ev["main_buttons"] = buttons(start)[:16]
        # Click yg:all:0 from main
        mm = await click_cb(c, start, "yg:all:0", wait=10)
        mm_text = card_text(mm)
        ev["mm_text"] = strip_html(mm_text)[:600]
        ev["mm_buttons"] = buttons(mm)[:16]
        ev["mm_has_photo"] = bool(mm and mm.photo)

        # Click first edge match (mm:match:N:e)
        mm_edge_btn = None
        for b in buttons(mm):
            if "mm:match:" in b["data"] and b["data"].endswith(":e"):
                mm_edge_btn = b["data"]
                break
        if mm_edge_btn:
            mm_edge = await click_cb(c, mm, mm_edge_btn, wait=8)
            ev["mm_edge_detail_text"] = strip_html(card_text(mm_edge))[:1200]
            ev["mm_edge_detail_buttons"] = buttons(mm_edge)[:12]
            ev["mm_edge_has_photo"] = bool(mm_edge and mm_edge.photo)
            # Click md:back (or ↩️)
            back_mm = await click_cb(c, mm_edge, "md:back", wait=6)
            ev["back_from_mm_edge_text"] = strip_html(card_text(back_mm))[:300]
            ev["back_from_mm_edge_buttons"] = [b["data"] for b in buttons(back_mm)][:6]
        else:
            ev["mm_edge_btn_missing"] = True

        # Click first non-edge match (mm:match:N:n) — for W3-5 injury suppression check
        # Re-fetch MM
        mm2 = await click_cb(c, start, "yg:all:0", wait=8)
        mm_neutral_btn = None
        for b in buttons(mm2):
            if "mm:match:" in b["data"] and b["data"].endswith(":n"):
                mm_neutral_btn = b["data"]
                break
        if mm_neutral_btn:
            mm_neutral = await click_cb(c, mm2, mm_neutral_btn, wait=8)
            text_neutral = card_text(mm_neutral)
            ev["mm_neutral_text"] = strip_html(text_neutral)[:1200]
            ev["mm_neutral_has_injury"] = bool(re.search(r"injur", text_neutral, re.I))
            ev["mm_neutral_buttons"] = buttons(mm_neutral)[:8]
            ev["mm_neutral_has_photo"] = bool(mm_neutral and mm_neutral.photo)
        else:
            ev["mm_neutral_btn_missing"] = True

        # Gold tier flash check — set gold then re-open picks
        await send(c, "/qa set_gold", wait=2)
        msgs = await send(c, "/picks", wait=8)
        gold_picks = msgs[0] if msgs else None
        ev["gold_picks_buttons"] = buttons(gold_picks)[:12]
        # Diamond cards locked = button text contains 🔒 OR callback starts hot:upgrade
        gold_locked = sum(1 for b in buttons(gold_picks)
                          if "🔒" in b["text"] or b["data"].startswith("hot:upgrade"))
        ev["gold_locked_count"] = gold_locked

        # Bronze tier
        await send(c, "/qa set_bronze", wait=2)
        msgs = await send(c, "/picks", wait=8)
        bronze_picks = msgs[0] if msgs else None
        ev["bronze_picks_buttons"] = buttons(bronze_picks)[:12]
        bronze_locked = sum(1 for b in buttons(bronze_picks)
                            if "🔒" in b["text"] or b["data"].startswith("hot:upgrade"))
        ev["bronze_locked_count"] = bronze_locked

        # Reset
        await send(c, "/qa reset", wait=2)
    finally:
        out_file = OUT / "evidence_v2.json"
        out_file.write_text(json.dumps(ev, indent=2, default=str))
        print(f"Wrote {out_file}")
        await c.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
