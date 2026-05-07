#!/usr/bin/env python3
"""Targeted MM probe — open My Matches via reply-keyboard text."""
import asyncio, json, os, re, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv; load_dotenv(ROOT / ".env")
from telethon import TelegramClient
from telethon.sessions import StringSession

API_ID = int(os.getenv("TELEGRAM_API_ID","0"))
API_HASH = os.getenv("TELEGRAM_API_HASH","")
BOT = "mzansiedge_bot"
SF = ROOT/"data"/"telethon_qa_session.string"
OUT = Path("/tmp/qa_w3"); OUT.mkdir(parents=True, exist_ok=True)


def strip_html(t): return re.sub(r"<[^>]+>","",t or "")


def buttons(m):
    out = []
    if not m or not m.reply_markup: return out
    for row in m.reply_markup.rows:
        for b in row.buttons:
            cb = ""
            if hasattr(b,"data") and b.data:
                cb = b.data.decode("utf-8","ignore") if isinstance(b.data,bytes) else str(b.data)
            out.append({"text": getattr(b,"text",""),"data":cb})
    return out


async def send(c, txt, wait=5):
    sent = await c.send_message(BOT, txt)
    await asyncio.sleep(wait)
    msgs = await c.get_messages(BOT, limit=6)
    return [m for m in msgs if not m.out and m.id >= sent.id]


async def click(c, msg, cb_substr, wait=8):
    if not msg or not msg.reply_markup: return None
    target = None
    for row in msg.reply_markup.rows:
        for b in row.buttons:
            if hasattr(b,"data") and b.data:
                cb = b.data.decode("utf-8","ignore") if isinstance(b.data,bytes) else str(b.data)
                if cb_substr in cb:
                    target = b; break
        if target: break
    if not target: return None
    try: await msg.click(data=target.data)
    except Exception as e: return {"_error": str(e)}
    await asyncio.sleep(wait)
    msgs = await c.get_messages(BOT, limit=4)
    return next((m for m in msgs if not m.out), None)


async def main():
    ev = {}
    s = SF.read_text().strip()
    c = TelegramClient(StringSession(s), API_ID, API_HASH)
    await c.connect()
    await send(c, "/qa reset", wait=3)
    await send(c, "/qa set_diamond", wait=2)

    msgs = await send(c, "⚽ My Matches", wait=14)
    mm = msgs[0] if msgs else None
    ev["mm_text"] = strip_html(mm.text or mm.message or "")[:800] if mm else ""
    ev["mm_buttons"] = buttons(mm)[:16]
    ev["mm_has_photo"] = bool(mm and mm.photo)

    mm_e_btn = None; mm_n_btn = None
    for b in buttons(mm):
        if "mm:match:" in b["data"]:
            if b["data"].endswith(":e") and not mm_e_btn:
                mm_e_btn = b["data"]
            if b["data"].endswith(":n") and not mm_n_btn:
                mm_n_btn = b["data"]
    ev["mm_e_btn"] = mm_e_btn
    ev["mm_n_btn"] = mm_n_btn

    if mm_e_btn:
        edge = await click(c, mm, mm_e_btn, wait=10)
        ev["mm_edge_text"] = strip_html(edge.text or edge.message or "")[:1000] if edge else ""
        ev["mm_edge_buttons"] = buttons(edge)[:12] if edge else []
        ev["mm_edge_has_photo"] = bool(edge and edge.photo)
        back = await click(c, edge, "md:back", wait=8)
        ev["back_from_mm_edge_text"] = strip_html(back.text or back.message or "")[:300] if back else ""
        ev["back_from_mm_edge_btns"] = [b["data"] for b in buttons(back)][:8] if back else []
        ev["back_returns_to_mm"] = bool(back and any("mm:match:" in b["data"] for b in buttons(back)))

    if mm_n_btn:
        msgs = await send(c, "⚽ My Matches", wait=10)
        mm2 = msgs[0] if msgs else None
        neutral = await click(c, mm2, mm_n_btn, wait=10)
        text_n = (neutral.text or neutral.message or "") if neutral else ""
        ev["mm_neutral_text"] = strip_html(text_n)[:1200]
        ev["mm_neutral_has_injury"] = bool(re.search(r"injur", text_n, re.I))
        ev["mm_neutral_has_photo"] = bool(neutral and neutral.photo)
        ev["mm_neutral_buttons"] = buttons(neutral)[:8] if neutral else []

    await send(c, "/qa reset", wait=2)
    (OUT/"evidence_mm.json").write_text(json.dumps(ev, indent=2, default=str))
    print(f"Wrote {OUT/'evidence_mm.json'}")
    await c.disconnect()

asyncio.run(main())
