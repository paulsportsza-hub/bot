"""Capture the ep:pick: edge detail card (which edits in-place).

The ep:pick callback edits the existing message in-place.
We need to read the message AFTER the edit to see the updated card.
"""
from __future__ import annotations

import asyncio, os, sys, time
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
API_ID   = int(_ENV.get("TELEGRAM_API_ID") or "0")
API_HASH =     _ENV.get("TELEGRAM_API_HASH") or ""
BOT_USERNAME = "mzansiedge_bot"
_BOT_DIR = Path(__file__).parent.parent
SESSION  = str(_BOT_DIR / "data" / "telethon_qa_session")

from telethon import TelegramClient
from telethon.tl.types import ReplyInlineMarkup, KeyboardButtonCallback, MessageMediaPhoto


async def _get_client():
    client = TelegramClient(SESSION, API_ID, API_HASH)
    await client.connect()
    assert await client.is_user_authorized()
    print("  ✔ Connected")
    return client


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
    print("  MzansiEdge — SS Badge: ep:pick detail card capture")
    print(f"  {time.strftime('%Y-%m-%d %H:%M:%S SAST')}")
    print(sep)

    client = await _get_client()
    entity = await client.get_entity(BOT_USERNAME)
    out_dir = Path("/tmp/ss_badge_verify")
    out_dir.mkdir(exist_ok=True)

    # Get Hot Tips
    print("\n[1] Sending '💎 Top Edge Picks'…")
    sent = await client.send_message(entity, "💎 Top Edge Picks")
    await asyncio.sleep(22)
    msgs = await client.get_messages(entity, limit=10)
    recent = list(reversed([m for m in msgs if m.id >= sent.id]))

    ht_card_msg_id = None
    target_ep_btn = None

    for m in recent:
        btns = _btns(m)
        if m.media and isinstance(m.media, MessageMediaPhoto):
            print(f"  HT card msg id={m.id}")
            for b in btns:
                print(f"    {b['text']!r} → {b['data']!r}")
            # Pick first Gold/Silver (non-locked) ep:pick: btn
            for b in btns:
                if b["data"].startswith("ep:pick:") and "🔒" not in b["text"]:
                    target_ep_btn = b
                    ht_card_msg_id = m.id
                    break

    if not target_ep_btn:
        print("  No ep:pick button found. Available buttons above.")
        await client.disconnect()
        return

    print(f"\n[2] Clicking in-place: {target_ep_btn['text']!r} → {target_ep_btn['data']!r}")
    # Get the message to click it
    ht_msg = await client.get_messages(entity, ids=ht_card_msg_id)
    await ht_msg.click(data=target_ep_btn["data"].encode())
    await asyncio.sleep(25)  # allow edit to complete

    # Fetch the SAME message id to see the edited version
    updated_msg = await client.get_messages(entity, ids=ht_card_msg_id)
    if updated_msg:
        m = updated_msg
        btns = _btns(m)
        print(f"  Updated message (id={m.id}):")
        print(f"    caption: {(m.message or '')[:200]!r}")
        print(f"    buttons: {[b['text'] for b in btns]}")
        if m.media and isinstance(m.media, MessageMediaPhoto):
            fpath = out_dir / "ep_detail_card.jpg"
            await client.download_media(m, file=str(fpath))
            print(f"  Saved card → {fpath} ({fpath.stat().st_size//1024}KB)")
        else:
            print("  No photo in updated message")
    else:
        print("  Could not retrieve updated message")

    # Also check for any NEW messages sent after our click
    print("\n[3] Checking for new messages after click…")
    fresh = await client.get_messages(entity, limit=10)
    new_msgs = [m for m in fresh if m.id > ht_card_msg_id]
    print(f"  {len(new_msgs)} new messages after click")
    for i, m in enumerate(new_msgs):
        txt = (m.text or m.message or "").strip()
        btns = _btns(m)
        if m.media and isinstance(m.media, MessageMediaPhoto):
            fpath = out_dir / f"after_click_{i:02d}.jpg"
            await client.download_media(m, file=str(fpath))
            print(f"  [CARD {i}] saved → {fpath} ({fpath.stat().st_size//1024}KB)")
            print(f"           caption: {(m.message or '')[:200]!r}")
            print(f"           buttons: {[b['text'] for b in btns]}")
        elif txt:
            print(f"  [TEXT {i}] {txt[:300]!r}")
            print(f"           buttons: {[b['text'] for b in btns]}")

    await client.disconnect()
    print("\n  Done.")


if __name__ == "__main__":
    asyncio.run(run())
