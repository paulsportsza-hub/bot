#!/usr/bin/env python3
"""Narrow S3 recheck — tap View Edge on an accessible edge match detail card,
then capture the actual response.

Saves: S3R_before_tap_*, S3R_after_tap_* evidence to the MM evidence dir.
"""
from __future__ import annotations
import asyncio, os, sys, json, time
from datetime import datetime
from dotenv import load_dotenv
load_dotenv("/home/paulsportsza/bot/.env")
from telethon import TelegramClient
from telethon.sessions import StringSession

API_ID = int(os.getenv("TELEGRAM_API_ID", "32418601"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "95e313a8ef5b998be0515dd8328fac57")
BOT_USERNAME = "@mzansiedge_bot"
SESSION_FILE = "/home/paulsportsza/bot/data/telethon_qa_session.string"
EVIDENCE_DIR = "/home/paulsportsza/tests/evidence/mm_edge_bugfix_20260419"
os.makedirs(EVIDENCE_DIR, exist_ok=True)


def _session():
    with open(SESSION_FILE) as f:
        return StringSession(f.read().strip())


def _btn_rows(msg):
    if not msg or not msg.reply_markup or not hasattr(msg.reply_markup, "rows"):
        return []
    out = []
    for row in msg.reply_markup.rows:
        r = []
        for btn in row.buttons:
            d = getattr(btn, "data", None)
            if isinstance(d, bytes):
                d = d.decode("utf-8", errors="replace")
            r.append({"text": btn.text, "data": d, "url": getattr(btn, "url", None)})
        out.append(r)
    return out


def _save(prefix, msg, extra=None):
    if not msg:
        return
    meta = {
        "prefix": prefix,
        "msg_id": msg.id,
        "date": msg.date.isoformat() if msg.date else None,
        "has_photo": bool(msg.photo),
        "has_media": bool(msg.media),
        "text": msg.text or msg.message or "",
        "buttons": _btn_rows(msg),
        "extra": extra or {},
    }
    with open(os.path.join(EVIDENCE_DIR, f"{prefix}_meta.json"), "w") as f:
        json.dump(meta, f, indent=2)
    with open(os.path.join(EVIDENCE_DIR, f"{prefix}_buttons.txt"), "w") as f:
        for i, row in enumerate(meta["buttons"]):
            for j, b in enumerate(row):
                f.write(f"[{i}][{j}] text={b['text']!r} data={b['data']!r} url={b['url']!r}\n")


async def _dl(msg, path):
    try:
        await msg.download_media(file=path)
    except Exception as e:
        open(path + ".error", "w").write(str(e))


async def main():
    print(f"S3 recheck at {datetime.now()}")
    async with TelegramClient(_session(), API_ID, API_HASH) as client:
        entity = await client.get_entity(BOT_USERNAME)
        me = await client.get_me()
        me_id = me.id

        # Force Diamond
        await client.send_message(entity, "/qa set_diamond")
        await asyncio.sleep(2)

        # Open My Matches fresh
        sent = await client.send_message(entity, "⚽ My Matches")
        deadline = time.time() + 30
        mm_list = None
        while time.time() < deadline:
            await asyncio.sleep(1.0)
            msgs = await client.get_messages(entity, limit=10)
            for m in msgs:
                if m.id > sent.id and m.sender_id != me_id:
                    rows = _btn_rows(m)
                    flat = []
                    for r in rows:
                        flat.extend(r)
                    if any((b.get("data") or "").startswith("mm:match:") for b in flat):
                        mm_list = m
                        break
            if mm_list:
                break
        assert mm_list, "no list"
        print(f"MM list msg id={mm_list.id}")
        _save("S3R_mm_list", mm_list)

        # Find first card with a tier badge → tap it
        # Card #1 worked before; try it
        card_n = 1
        # Re-fetch list buttons and click
        target_data = f"mm:match:{card_n}:n"
        btn_to_click = None
        for r, row in enumerate(mm_list.reply_markup.rows):
            for c, btn in enumerate(row.buttons):
                d = getattr(btn, "data", b"") or b""
                if isinstance(d, bytes):
                    d = d.decode()
                if d.startswith(f"mm:match:{card_n}:"):
                    btn_to_click = (r, c, btn)
                    break
            if btn_to_click:
                break
        assert btn_to_click, "no card 1 button"
        r, c, _ = btn_to_click
        list_id = mm_list.id
        await mm_list.click(r, c)

        # Wait for match_detail photo to appear (can be edit-in-place OR new message)
        deadline = time.time() + 30
        detail_msg = None
        while time.time() < deadline:
            await asyncio.sleep(1.0)
            # Check if list message was edited
            try:
                edited = await client.get_messages(entity, ids=list_id)
                if edited and edited.photo and edited.reply_markup:
                    # Check if buttons now have mme: (match_detail) instead of mm:match:N:
                    any_mme = False
                    for row in _btn_rows(edited):
                        for b in row:
                            if (b.get("data") or "").startswith(("mme:", "md:back")):
                                any_mme = True
                                break
                    if any_mme:
                        detail_msg = edited
                        break
            except Exception:
                pass
            msgs = await client.get_messages(entity, limit=8)
            for m in msgs:
                if m.id > list_id and m.sender_id != me_id and m.photo:
                    detail_msg = m
                    break
            if detail_msg:
                break
        assert detail_msg, "no detail"
        print(f"match_detail msg id={detail_msg.id}")
        _save("S3R_match_detail", detail_msg)
        await _dl(detail_msg, os.path.join(EVIDENCE_DIR, "S3R_match_detail.jpg"))

        # Find View Edge button (mme:N)
        mme_btn = None
        for r, row in enumerate(detail_msg.reply_markup.rows):
            for c, btn in enumerate(row.buttons):
                d = getattr(btn, "data", b"") or b""
                if isinstance(d, bytes):
                    d = d.decode()
                if d.startswith("mme:"):
                    mme_btn = (r, c, btn, d)
                    break
            if mme_btn:
                break
        if not mme_btn:
            print("FAIL: no mme: button on match_detail card")
            return
        r, c, btn, data = mme_btn
        print(f"Tapping View Edge button: text={btn.text!r} data={data!r}")

        # Snapshot all bot msg ids before tap
        before_msgs = await client.get_messages(entity, limit=5)
        before_max = max((m.id for m in before_msgs if m.sender_id != me_id), default=0)
        print(f"Max bot msg id before tap: {before_max}")

        await detail_msg.click(r, c)

        # Wait for NEW message after before_max (the edge_detail card)
        deadline = time.time() + 30
        edge_msg = None
        while time.time() < deadline:
            await asyncio.sleep(1.0)
            msgs = await client.get_messages(entity, limit=8)
            new_msgs = [m for m in msgs if m.id > before_max and m.sender_id != me_id]
            # Prefer one with photo + buttons
            for m in sorted(new_msgs, key=lambda x: x.id, reverse=True):
                if m.photo and m.reply_markup:
                    edge_msg = m
                    break
            if edge_msg:
                break
        if not edge_msg:
            print("FAIL: no edge msg after mme tap")
            return
        print(f"edge_msg id={edge_msg.id}")
        _save("S3R_edge_detail_after_mme", edge_msg, {"clicked_data": data})
        await _dl(edge_msg, os.path.join(EVIDENCE_DIR, "S3R_edge_detail_after_mme.jpg"))

        # Dump buttons
        print("\nEdge detail buttons:")
        for i, row in enumerate(_btn_rows(edge_msg)):
            for j, b in enumerate(row):
                print(f"  [{i}][{j}] text={b['text']!r} data={b['data']!r} url={b['url']!r}")

        # Check Back button callback
        back_cbs = []
        for row in _btn_rows(edge_msg):
            for b in row:
                t = (b["text"] or "").lower()
                d = b["data"] or ""
                if ("back" in t or "↩" in t) and d:
                    back_cbs.append((b["text"], d))
        print(f"\nBack callbacks: {back_cbs}")
        any_mm = any(d.startswith("mm:match:") for _, d in back_cbs)
        any_yg = any(d.startswith("yg:all") for _, d in back_cbs)
        any_md = any(d.startswith("md:back") for _, d in back_cbs)
        any_hot = any(d.startswith("hot:back") for _, d in back_cbs)
        print(f"mm:match: present={any_mm} | yg:all present={any_yg} | md:back={any_md} | hot:back={any_hot}")

        # Also tap Back and see where it lands
        if back_cbs:
            print("\n--- Clicking Back button ---")
            back_btn = None
            for r, row in enumerate(edge_msg.reply_markup.rows):
                for c, btn in enumerate(row.buttons):
                    d = getattr(btn, "data", b"") or b""
                    if isinstance(d, bytes):
                        d = d.decode()
                    t = (btn.text or "").lower()
                    if ("back" in t or "↩" in t) and d:
                        back_btn = (r, c, btn, d)
                        break
                if back_btn:
                    break
            if back_btn:
                before2 = edge_msg.id
                await edge_msg.click(back_btn[0], back_btn[1])
                deadline = time.time() + 20
                post_back = None
                while time.time() < deadline:
                    await asyncio.sleep(1.0)
                    msgs = await client.get_messages(entity, limit=8)
                    for m in msgs:
                        if m.id > before2 and m.sender_id != me_id:
                            post_back = m
                            break
                    if post_back:
                        break
                if post_back:
                    _save("S3R_after_back", post_back, {"clicked_data": back_btn[3]})
                    await _dl(post_back, os.path.join(EVIDENCE_DIR, "S3R_after_back.jpg"))
                    print(f"After Back: msg_id={post_back.id} photo={bool(post_back.photo)}")
                    for i, row in enumerate(_btn_rows(post_back)):
                        for j, b in enumerate(row):
                            print(f"  [{i}][{j}] {b['text']!r} {b['data']!r}")

        await client.send_message(entity, "/qa reset")
        await asyncio.sleep(2)


if __name__ == "__main__":
    asyncio.run(main())
