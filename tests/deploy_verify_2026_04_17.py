#!/usr/bin/env python3
"""OPS-DEPLOY-VERIFY-01 — Surface probe script.

Probes 6 surfaces as Gold-tier QA user. Records:
- Photo sent? (y/n)
- Text before/after photo? (y/n)
- PNG dimensions
- Header text matches surface?
Saves PNGs to reports/deploy-verify-2026-04-17/.
"""
from __future__ import annotations

import asyncio
import io
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

from telethon import TelegramClient
from telethon.sessions import StringSession

API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "")
BOT_USERNAME = "@mzansiedge_bot"
STRING_SESSION_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "telethon_session.string")
OUT_DIR = Path(__file__).parent.parent / "reports" / "deploy-verify-2026-04-17"
OUT_DIR.mkdir(parents=True, exist_ok=True)

TIMEOUT_CMD = 30
TIMEOUT_NAV = 15

results: list[dict] = []


def load_session():
    p = Path(STRING_SESSION_FILE)
    if p.exists():
        s = p.read_text().strip()
        if s:
            return StringSession(s)
    return StringSession()


def btn_list(msg) -> list[str]:
    if not msg or not msg.reply_markup:
        return []
    out = []
    for row in msg.reply_markup.rows:
        for btn in row.buttons:
            out.append(btn.text)
    return out


def find_btn(msg, label: str):
    if not msg or not msg.reply_markup:
        return None
    for r, row in enumerate(msg.reply_markup.rows):
        for b, btn in enumerate(row.buttons):
            if label.lower() in btn.text.lower():
                return (r, b, btn)
    return None


async def drain_messages(client, entity, after_id: int, timeout: float, me_id: int) -> list:
    """Collect all bot messages arriving after after_id within timeout."""
    deadline = time.time() + timeout
    collected = []
    seen_ids: set[int] = set()
    while time.time() < deadline:
        await asyncio.sleep(1.5)
        msgs = await client.get_messages(entity, limit=20)
        for m in msgs:
            if m.id > after_id and m.sender_id != me_id and m.id not in seen_ids:
                seen_ids.add(m.id)
                collected.append(m)
        if collected:
            # Give 3s more to catch follow-up messages
            await asyncio.sleep(3)
            msgs2 = await client.get_messages(entity, limit=20)
            for m in msgs2:
                if m.id > after_id and m.sender_id != me_id and m.id not in seen_ids:
                    seen_ids.add(m.id)
                    collected.append(m)
            break
    return sorted(collected, key=lambda m: m.id)


async def click_first_btn(client, entity, msg, after_id: int, me_id: int, timeout=TIMEOUT_NAV):
    """Click first inline button that has callback_data, collect responses."""
    if not msg or not msg.reply_markup:
        return [], 0
    # Find first button with callback data (not URL)
    for r, row in enumerate(msg.reply_markup.rows):
        for b, btn in enumerate(row.buttons):
            data = getattr(btn, "data", None)
            if data is not None:
                t0 = time.time()
                await msg.click(r, b)
                msgs = await drain_messages(client, entity, after_id, timeout, me_id)
                # Also check if original message was edited
                elapsed = time.time() - t0
                return msgs, elapsed
    return [], 0


async def get_photo_dims(client, msg) -> tuple[int, int] | None:
    if not msg or not msg.photo:
        return None
    try:
        buf = io.BytesIO()
        await client.download_media(msg.photo, buf)
        buf.seek(0)
        # Parse PNG header
        data = buf.read()
        if data[:8] == b'\x89PNG\r\n\x1a\n':
            import struct
            w, h = struct.unpack('>II', data[16:24])
            return w, h
    except Exception as e:
        print(f"    [dim error: {e}]")
    return None


async def save_photo(client, msg, label: str) -> str:
    if not msg or not msg.photo:
        return ""
    fname = OUT_DIR / f"{label}.png"
    try:
        await client.download_media(msg.photo, str(fname))
        return str(fname)
    except Exception as e:
        return f"[save error: {e}]"


def log_surface(name: str, msgs: list, label: str):
    photo_msgs = [m for m in msgs if m and m.photo]
    text_msgs = [m for m in msgs if m and not m.photo and (m.text or "").strip()]
    has_photo = bool(photo_msgs)
    has_text = bool(text_msgs)

    # Caption on photo messages
    caption_strs = [(m.text or "").strip() for m in photo_msgs if (m.text or "").strip()]
    has_caption = bool(caption_strs)

    print(f"\n  Surface: {name}")
    print(f"    Photo sent:            {'YES' if has_photo else 'NO'}")
    print(f"    Caption on photo:      {'YES ⚠️' if has_caption else 'none'}")
    print(f"    Separate text msgs:    {'YES ⚠️' if has_text else 'none'} ({len(text_msgs)})")
    for tm in text_msgs:
        preview = (tm.text or "")[:80].replace('\n', ' ')
        print(f"      text: {preview!r}")
    if caption_strs:
        for cap in caption_strs:
            print(f"      caption: {cap[:80]!r}")

    result = {
        "surface": name,
        "label": label,
        "photo_sent": has_photo,
        "caption": has_caption,
        "caption_text": caption_strs,
        "text_msgs": has_text,
        "text_count": len(text_msgs),
        "text_previews": [(m.text or "")[:120] for m in text_msgs],
        "photo_count": len(photo_msgs),
        "dims": [],
        "png_path": [],
        "so34_gate": not has_caption and not has_text,
    }
    return result, photo_msgs


async def run_probe(client, entity, me_id: int):
    print("\n" + "="*60)
    print("  OPS-DEPLOY-VERIFY-01 — Surface Probe")
    print(f"  {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print("="*60)

    # Set Gold tier for QA
    print("\n[QA] Setting Gold tier...")
    last_msg = (await client.get_messages(entity, limit=1))
    last_id = last_msg[0].id if last_msg else 0
    await client.send_message(entity, "/qa set_gold")
    await asyncio.sleep(4)
    msgs = await client.get_messages(entity, limit=3)
    for m in msgs:
        if m.id > last_id and m.sender_id != me_id:
            print(f"    /qa response: {(m.text or '')[:80]}")
            break

    # ── Surface 1: /start ──────────────────────────────────
    print("\n[1] /start")
    last_id = (await client.get_messages(entity, limit=1))[0].id
    await client.send_message(entity, "/start")
    msgs = await drain_messages(client, entity, last_id, TIMEOUT_CMD, me_id)
    result, photos = log_surface("/start", msgs, "01_start")
    for pm in photos[:1]:
        dims = await get_photo_dims(client, pm)
        if dims:
            print(f"    Dims: {dims[0]}×{dims[1]}")
            result["dims"].append(dims)
        p = await save_photo(client, pm, "01_start")
        result["png_path"].append(p)
        print(f"    PNG: {p}")
    results.append(result)

    # ── Surface 2: /picks (list) ──────────────────────────
    print("\n[2] /picks (Edge Picks list)")
    last_id = (await client.get_messages(entity, limit=1))[0].id
    await client.send_message(entity, "/picks")
    msgs = await drain_messages(client, entity, last_id, 45, me_id)
    result, photos = log_surface("/picks list", msgs, "02_picks_list")
    for i, pm in enumerate(photos[:1]):
        dims = await get_photo_dims(client, pm)
        if dims:
            print(f"    Dims: {dims[0]}×{dims[1]}")
            result["dims"].append(dims)
        p = await save_photo(client, pm, f"02_picks_list_{i}")
        result["png_path"].append(p)
        print(f"    PNG: {p}")
    results.append(result)

    # ── Surface 3: First pick → Edge pick detail ──────────
    print("\n[3] Tap first Edge pick → detail")
    # Find last photo or text message with inline buttons
    last_id_before = (await client.get_messages(entity, limit=1))[0].id
    # Look for the tip list message with buttons
    recent = await client.get_messages(entity, limit=15)
    tip_msg = None
    for m in recent:
        if m.reply_markup and not m.photo:
            # Look for edge:detail or button with emoji like 💎🥇
            btns = btn_list(m)
            if any("edge" in b.lower() or "💎" in b or "🥇" in b or "🥈" in b or "🥉" in b for b in btns):
                tip_msg = m
                break
        if m.photo and m.reply_markup:
            tip_msg = m
            break

    if tip_msg:
        nav_msgs, elapsed = await click_first_btn(client, entity, tip_msg, last_id_before, me_id, TIMEOUT_NAV * 2)
        # Also check if original message was edited
        edited = await client.get_messages(entity, ids=tip_msg.id)
        all_msgs = nav_msgs
        if edited and edited.text != (tip_msg.text or ""):
            all_msgs = [edited] + nav_msgs
        result, photos = log_surface("Edge pick detail", all_msgs, "03_pick_detail")
        print(f"    Response time: {elapsed:.1f}s")
        for pm in photos[:1]:
            dims = await get_photo_dims(client, pm)
            if dims:
                print(f"    Dims: {dims[0]}×{dims[1]}")
                result["dims"].append(dims)
            p = await save_photo(client, pm, "03_pick_detail")
            result["png_path"].append(p)
            print(f"    PNG: {p}")
    else:
        result = {"surface": "Edge pick detail", "label": "03_pick_detail", "photo_sent": False,
                  "text_msgs": False, "so34_gate": True, "note": "no tip list message found"}
        print("    ⚠️  Could not find tip list message to tap")
    results.append(result)

    # ── Surface 4: /my_matches (list) ─────────────────────
    print("\n[4] /my_matches (list)")
    last_id = (await client.get_messages(entity, limit=1))[0].id
    await client.send_message(entity, "/my_matches")
    msgs = await drain_messages(client, entity, last_id, TIMEOUT_CMD, me_id)
    result, photos = log_surface("/my_matches list", msgs, "04_my_matches_list")
    for pm in photos[:1]:
        dims = await get_photo_dims(client, pm)
        if dims:
            print(f"    Dims: {dims[0]}×{dims[1]}")
            result["dims"].append(dims)
        p = await save_photo(client, pm, "04_my_matches_list")
        result["png_path"].append(p)
        print(f"    PNG: {p}")
    results.append(result)

    # ── Surface 5: First match → Match detail ─────────────
    print("\n[5] Tap first match → Match detail")
    last_id_before = (await client.get_messages(entity, limit=1))[0].id
    recent = await client.get_messages(entity, limit=10)
    match_msg = None
    for m in recent:
        if m.reply_markup:
            btns = btn_list(m)
            if any("yg:game" in str(getattr(b, "data", b"")) for row in (m.reply_markup.rows or []) for b in row.buttons):
                match_msg = m
                break
            # Fallback: any message with buttons that's not the tip list
            if not match_msg and btns:
                match_msg = m

    if match_msg:
        nav_msgs, elapsed = await click_first_btn(client, entity, match_msg, last_id_before, me_id, 30)
        edited = await client.get_messages(entity, ids=match_msg.id)
        all_msgs = nav_msgs
        if edited and edited.text != (match_msg.text or ""):
            all_msgs = [edited] + nav_msgs
        result, photos = log_surface("Match detail", all_msgs, "05_match_detail")
        print(f"    Response time: {elapsed:.1f}s")
        for pm in photos[:1]:
            dims = await get_photo_dims(client, pm)
            if dims:
                print(f"    Dims: {dims[0]}×{dims[1]}")
                result["dims"].append(dims)
            p = await save_photo(client, pm, "05_match_detail")
            result["png_path"].append(p)
            print(f"    PNG: {p}")
    else:
        result = {"surface": "Match detail", "label": "05_match_detail", "photo_sent": False,
                  "text_msgs": False, "so34_gate": True, "note": "no match list message found"}
        print("    ⚠️  Could not find match list message to tap")
    results.append(result)

    # ── Surface 6: /schedule ──────────────────────────────
    print("\n[6] /schedule")
    last_id = (await client.get_messages(entity, limit=1))[0].id
    await client.send_message(entity, "/schedule")
    msgs = await drain_messages(client, entity, last_id, TIMEOUT_CMD, me_id)
    result, photos = log_surface("/schedule", msgs, "06_schedule")
    for pm in photos[:1]:
        dims = await get_photo_dims(client, pm)
        if dims:
            print(f"    Dims: {dims[0]}×{dims[1]}")
            result["dims"].append(dims)
        p = await save_photo(client, pm, "06_schedule")
        result["png_path"].append(p)
        print(f"    PNG: {p}")
    results.append(result)

    # QA reset
    await client.send_message(entity, "/qa reset")
    await asyncio.sleep(2)

    # ── Summary ───────────────────────────────────────────
    print("\n" + "="*60)
    print("  SUMMARY")
    print("="*60)
    gate_pass = 0
    gate_total = 0
    for r in results:
        so34 = r.get("so34_gate", True)
        gate_total += 1
        if so34:
            gate_pass += 1
        status = "✅" if so34 else "❌"
        note = ""
        if r.get("caption"):
            note += f" [CAPTION LEAK]"
        if r.get("text_msgs"):
            note += f" [TEXT DUMP: {r['text_count']} msgs]"
        print(f"  {status} {r['surface']}{note}")
    print(f"\n  SO #34 gate: {gate_pass}/{gate_total}")

    return results


async def main():
    session = load_session()
    if not session.save():
        print("ERROR: No session string found at", STRING_SESSION_FILE)
        sys.exit(1)

    async with TelegramClient(session, API_ID, API_HASH) as client:
        entity = await client.get_entity(BOT_USERNAME)
        me = await client.get_me()
        print(f"Connected as: {me.first_name} (id={me.id})")
        await run_probe(client, entity, me.id)

    print(f"\nPNGs saved to: {OUT_DIR}")
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
