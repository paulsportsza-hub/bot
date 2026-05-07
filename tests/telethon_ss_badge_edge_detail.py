"""Get edge detail card for a specific match to verify SS badge.

The mm:match:1:e callback opens the match detail card (match_detail.html template).
The edge:detail: callback opens the edge detail card (edge_detail.html template).

Both templates have the SS badge in the meta bar.

We need to:
1. Find a match that IS accessible (Gold/Silver — not locked)
2. Click its detail button
3. Download and inspect the resulting card image
"""
from __future__ import annotations

import asyncio, os, re, sys, time
from pathlib import Path

def _load_env(path: str = "/home/paulsportsza/bot/.env") -> dict:
    env: dict[str, str] = {}
    try:
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    return env

_ENV = _load_env()
API_ID   = int(_ENV.get("TELEGRAM_API_ID")  or "0")
API_HASH =     _ENV.get("TELEGRAM_API_HASH") or ""
BOT_USERNAME = "mzansiedge_bot"
_BOT_DIR = Path(__file__).parent.parent
SESSION  = str(_BOT_DIR / "data" / "telethon_qa_session")

from telethon import TelegramClient
from telethon.tl.types import ReplyInlineMarkup, KeyboardButtonCallback, MessageMediaPhoto


async def _get_client() -> TelegramClient:
    client = TelegramClient(SESSION, API_ID, API_HASH)
    await client.connect()
    assert await client.is_user_authorized()
    print("  ✔ Connected")
    return client


async def _send_wait(client, entity, text: str, wait: float = 20.0):
    sent = await client.send_message(entity, text)
    await asyncio.sleep(wait)
    msgs = await client.get_messages(entity, limit=20)
    return list(reversed([m for m in msgs if m.id > sent.id]))


def _btns(msg) -> list[dict]:
    out = []
    if not msg.reply_markup or not isinstance(msg.reply_markup, ReplyInlineMarkup):
        return out
    for row in msg.reply_markup.rows:
        for btn in row.buttons:
            if isinstance(btn, KeyboardButtonCallback):
                out.append({"text": btn.text, "data": btn.data.decode()})
    return out


async def run():
    sep = "=" * 72
    print(sep)
    print("  MzansiEdge — SS Badge: Edge Detail Card Capture")
    print(f"  {time.strftime('%Y-%m-%d %H:%M:%S SAST')}")
    print(sep)

    client = await _get_client()
    entity = await client.get_entity(BOT_USERNAME)
    out_dir = Path("/tmp/ss_badge_verify")
    out_dir.mkdir(exist_ok=True)

    # Get Hot Tips
    print("\n[1] Getting Hot Tips (Edge Picks list card)…")
    msgs_ht = await _send_wait(client, entity, "💎 Top Edge Picks", wait=22)
    print(f"    → {len(msgs_ht)} messages")

    for i, m in enumerate(msgs_ht):
        btns = _btns(m)
        print(f"  msg {i}: text={bool(m.text)}, photo={isinstance(m.media, MessageMediaPhoto)}")
        for b in btns:
            print(f"    btn: {b['text']!r} → {b['data']!r}")

    # Find the HT list card and click the FIRST non-locked button
    # The HT card has buttons like "[2] ⚽ Man U vs LIV 🥇" -> "mm:match:2:e"
    ht_card_msg = None
    target_btn = None
    for m in msgs_ht:
        if m.media and isinstance(m.media, MessageMediaPhoto):
            btns = _btns(m)
            for b in btns:
                # Skip locked (🔒), Back (↩️), Next (→), Back→picks (hot:back)
                if "🔒" not in b["text"] and "↩️" not in b["text"] and "→" not in b["text"]:
                    if b["data"].startswith("mm:match:") or b["data"].startswith("edge:detail:") or b["data"].startswith("ed:") or b["data"].startswith("ep:pick:"):
                        target_btn = b
                        ht_card_msg = m
                        break
        if target_btn:
            break

    if not target_btn:
        print("\n  No accessible detail button found. Buttons on HT messages:")
        for m in msgs_ht:
            for b in _btns(m):
                print(f"    {b['text']!r} → {b['data']!r}")
        await client.disconnect()
        return

    print(f"\n[2] Clicking: {target_btn['text']!r} → {target_btn['data']!r}")
    before_id = ht_card_msg.id
    await ht_card_msg.click(data=target_btn["data"].encode())
    await asyncio.sleep(25)  # detail cards take longer

    fresh = await client.get_messages(entity, limit=15)
    detail_msgs = list(reversed([m for m in fresh if m.id > before_id]))
    print(f"    → {len(detail_msgs)} messages after click")

    saved_paths = []
    for i, dm in enumerate(detail_msgs):
        txt = (dm.text or dm.message or "").strip()
        btns = _btns(dm)
        if dm.media and isinstance(dm.media, MessageMediaPhoto):
            fpath = out_dir / f"edge_detail_{i:02d}.jpg"
            await client.download_media(dm, file=str(fpath))
            saved_paths.append(fpath)
            print(f"    [CARD {i}] saved → {fpath}")
            print(f"             caption: {(dm.message or '')[:200]!r}")
            print(f"             buttons: {[b['text'] for b in btns]}")
        elif txt:
            print(f"    [TEXT {i}] {txt[:300]!r}")
            print(f"             buttons: {[b['text'] for b in btns]}")

    # Also get My Matches → click ARS vs FUL detail
    print("\n[3] Getting My Matches + match detail…")
    msgs_mm = await _send_wait(client, entity, "⚽ My Matches", wait=18)
    mm_card = None
    mm_btn  = None
    for m in msgs_mm:
        if m.media and isinstance(m.media, MessageMediaPhoto):
            btns = _btns(m)
            for b in btns:
                if b["data"].startswith("mm:match:") and "🔒" not in b["text"]:
                    mm_card = m
                    mm_btn  = b
                    break
        if mm_btn:
            break

    if mm_btn:
        print(f"    Clicking: {mm_btn['text']!r} → {mm_btn['data']!r}")
        before_id2 = mm_card.id
        await mm_card.click(data=mm_btn["data"].encode())
        await asyncio.sleep(25)
        fresh2 = await client.get_messages(entity, limit=15)
        detail2 = list(reversed([m for m in fresh2 if m.id > before_id2]))
        print(f"    → {len(detail2)} messages")
        for i, dm in enumerate(detail2):
            txt = (dm.text or dm.message or "").strip()
            btns = _btns(dm)
            if dm.media and isinstance(dm.media, MessageMediaPhoto):
                fpath = out_dir / f"mm_detail2_{i:02d}.jpg"
                await client.download_media(dm, file=str(fpath))
                saved_paths.append(fpath)
                print(f"    [CARD {i}] saved → {fpath}")
                print(f"             buttons: {[b['text'] for b in btns]}")
            elif txt:
                print(f"    [TEXT {i}] {txt[:300]!r}")

    print(f"\n{sep}")
    print("  DOWNLOADED CARDS")
    print(sep)
    for p in saved_paths:
        sz = p.stat().st_size // 1024 if p.exists() else 0
        print(f"  {p} ({sz}KB)")

    await client.disconnect()
    print("\n  Done — check images for 'S NNN' green badge in meta bar.")


if __name__ == "__main__":
    asyncio.run(run())
