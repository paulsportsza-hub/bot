"""Deep SS badge verification — downloads card images and checks channel pipeline end-to-end.

Usage:
    cd /home/paulsportsza/bot
    .venv/bin/python tests/telethon_ss_badge_deep.py
"""
from __future__ import annotations

import asyncio
import os
import re
import sys
import time
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
API_ID   = int(_ENV.get("TELEGRAM_API_ID")  or os.getenv("TELEGRAM_API_ID", "0"))
API_HASH =     _ENV.get("TELEGRAM_API_HASH") or os.getenv("TELEGRAM_API_HASH", "")
BOT_USERNAME = "mzansiedge_bot"

_BOT_DIR = Path(__file__).parent.parent
SESSION  = str(_BOT_DIR / "data" / "telethon_qa_session")

from telethon import TelegramClient
from telethon.tl.types import ReplyInlineMarkup, KeyboardButtonCallback, MessageMediaPhoto


async def _get_client() -> TelegramClient:
    client = TelegramClient(SESSION, API_ID, API_HASH)
    await client.connect()
    if not await client.is_user_authorized():
        print("ERROR: Not authorized")
        sys.exit(1)
    print(f"  ✔ Connected")
    return client


async def _send_and_collect(client, entity, text: str, wait: float = 20.0, limit: int = 15):
    sent    = await client.send_message(entity, text)
    sent_id = sent.id
    await asyncio.sleep(wait)
    msgs = await client.get_messages(entity, limit=limit)
    return list(reversed([m for m in msgs if m.id > sent_id]))


def _inline_buttons(msg) -> list[dict]:
    btns: list[dict] = []
    if not msg.reply_markup or not isinstance(msg.reply_markup, ReplyInlineMarkup):
        return btns
    for row in msg.reply_markup.rows:
        for btn in row.buttons:
            if isinstance(btn, KeyboardButtonCallback):
                btns.append({"text": btn.text, "data": btn.data.decode(), "url": None})
    return btns


async def run():
    sep = "=" * 72
    print(sep)
    print("  SuperSport SS Badge — Deep Verification")
    print(f"  {time.strftime('%Y-%m-%d %H:%M:%S SAST')}")
    print(sep)

    client = await _get_client()
    entity = await client.get_entity(BOT_USERNAME)

    out_dir = Path("/tmp/ss_badge_verify")
    out_dir.mkdir(exist_ok=True)

    # ── 1. Hot Tips: get cards + download them ─────────────────────────────────
    print("\n[1] Sending '💎 Top Edge Picks' …")
    msgs_ht = await _send_and_collect(client, entity, "💎 Top Edge Picks", wait=22)
    print(f"    → {len(msgs_ht)} messages")

    saved_cards = []
    edge_detail_btn = None
    edge_detail_msg = None

    for i, m in enumerate(msgs_ht):
        txt = (m.text or m.message or "").strip()
        btns = _inline_buttons(m)
        btn_labels = [b["text"] for b in btns]
        btn_datas  = [b["data"] for b in btns]

        if m.media and isinstance(m.media, MessageMediaPhoto):
            fpath = out_dir / f"ht_card_{i:02d}.jpg"
            await client.download_media(m, file=str(fpath))
            saved_cards.append(fpath)
            print(f"    [CARD {i}] saved → {fpath}")
            print(f"             caption: {(m.message or '')[:100]!r}")
            print(f"             buttons: {btn_labels}")
        elif txt:
            print(f"    [TEXT {i}] {txt[:120]!r}")
            print(f"             buttons: {btn_labels}")

        # Find first edge:detail button (in any message)
        if not edge_detail_btn:
            for b in btns:
                if b["data"] and b["data"].startswith("edge:detail:"):
                    edge_detail_btn = b
                    edge_detail_msg = m
                    break

    print(f"\n  Downloaded {len(saved_cards)} card images to {out_dir}")

    # ── 2. Click edge:detail ─────────────────────────────────────────────────
    if edge_detail_btn and edge_detail_msg:
        print(f"\n[2] Clicking: {edge_detail_btn['text']!r} → {edge_detail_btn['data']!r}")
        before_id = edge_detail_msg.id
        await edge_detail_msg.click(data=edge_detail_btn["data"].encode())
        await asyncio.sleep(22)
        detail_msgs = await client.get_messages(entity, limit=10)
        detail_msgs = list(reversed([m for m in detail_msgs if m.id > before_id]))
        print(f"    → {len(detail_msgs)} messages after click")

        for i, m in enumerate(detail_msgs):
            txt = (m.text or m.message or "").strip()
            btns = _inline_buttons(m)
            if m.media and isinstance(m.media, MessageMediaPhoto):
                fpath = out_dir / f"detail_card_{i:02d}.jpg"
                await client.download_media(m, file=str(fpath))
                saved_cards.append(fpath)
                print(f"    [DETAIL CARD {i}] saved → {fpath}")
                print(f"                    caption: {(m.message or '')[:200]!r}")
                print(f"                    buttons: {[b['text'] for b in btns]}")
            elif txt:
                print(f"    [DETAIL TEXT {i}] {txt[:200]!r}")
                print(f"                     buttons: {[b['text'] for b in btns]}")
    else:
        print("\n[2] No edge:detail button found in Hot Tips — trying mm:match path")

        # Look for mm:match buttons in Hot Tips messages
        for m in msgs_ht:
            btns = _inline_buttons(m)
            for b in btns:
                if b["data"] and b["data"].startswith("mm:match:"):
                    print(f"    Found mm:match button: {b['text']!r} → {b['data']!r}")
                    before_id = m.id
                    await m.click(data=b["data"].encode())
                    await asyncio.sleep(22)
                    fresh = await client.get_messages(entity, limit=10)
                    fresh = list(reversed([fm for fm in fresh if fm.id > before_id]))
                    for i, fm in enumerate(fresh):
                        txt = (fm.text or fm.message or "").strip()
                        if fm.media and isinstance(fm.media, MessageMediaPhoto):
                            fpath = out_dir / f"mm_detail_{i:02d}.jpg"
                            await client.download_media(fm, file=str(fpath))
                            saved_cards.append(fpath)
                            print(f"    [CARD] {fpath}")
                        elif txt:
                            print(f"    [TEXT] {txt[:200]!r}")
                    break
            else:
                continue
            break

    # ── 3. My Matches ─────────────────────────────────────────────────────────
    print("\n[3] Sending '⚽ My Matches' …")
    msgs_mm = await _send_and_collect(client, entity, "⚽ My Matches", wait=18)
    print(f"    → {len(msgs_mm)} messages")

    mm_card_msg = None
    for i, m in enumerate(msgs_mm):
        txt = (m.text or m.message or "").strip()
        btns = _inline_buttons(m)
        if m.media and isinstance(m.media, MessageMediaPhoto):
            fpath = out_dir / f"mm_card_{i:02d}.jpg"
            await client.download_media(m, file=str(fpath))
            saved_cards.append(fpath)
            if mm_card_msg is None:
                mm_card_msg = m
            print(f"    [CARD {i}] saved → {fpath}")
            print(f"             buttons: {[b['text'] for b in btns]}")
        elif txt:
            print(f"    [TEXT {i}] {txt[:120]!r}")
            print(f"             buttons: {[b['text'] for b in btns]}")

    # Click first My Matches card button (mm:match:*) to get detail card
    if mm_card_msg:
        btns = _inline_buttons(mm_card_msg)
        for b in btns:
            if b["data"] and b["data"].startswith("mm:match:"):
                print(f"\n[3b] Clicking My Matches detail: {b['text']!r} → {b['data']!r}")
                before_id = mm_card_msg.id
                await mm_card_msg.click(data=b["data"].encode())
                await asyncio.sleep(22)
                fresh = await client.get_messages(entity, limit=10)
                fresh = list(reversed([fm for fm in fresh if fm.id > before_id]))
                print(f"     → {len(fresh)} messages")
                for i2, fm in enumerate(fresh):
                    txt2 = (fm.text or fm.message or "").strip()
                    btns2 = _inline_buttons(fm)
                    if fm.media and isinstance(fm.media, MessageMediaPhoto):
                        fpath = out_dir / f"mm_detail_{i2:02d}.jpg"
                        await client.download_media(fm, file=str(fpath))
                        saved_cards.append(fpath)
                        print(f"     [DETAIL CARD] saved → {fpath}")
                        print(f"                   buttons: {[b2['text'] for b2 in btns2]}")
                    elif txt2:
                        print(f"     [DETAIL TEXT] {txt2[:200]!r}")
                        print(f"                   buttons: {[b2['text'] for b2 in btns2]}")
                break

    # ── 4. Unit-test the channel pipeline directly ─────────────────────────────
    print(f"\n{sep}")
    print("  CHANNEL PIPELINE UNIT TEST")
    print(sep)

    # Test _get_supersport_channel for current EPL match
    test_cases = [
        ("Arsenal", "Fulham",   "arsenal_vs_fulham_2026-04-19",     "epl"),
        ("Liverpool", "Chelsea", "liverpool_vs_chelsea_2026-04-19", "epl"),
        ("Sundowns", "Pirates", "sundowns_vs_pirates_2026-04-19",   "psl"),
    ]

    import sqlite3
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from scrapers.db_connect import connect_odds_db
    from scrapers.broadcast_matcher import fuzzy_match_broadcast
    from scrapers.edge.edge_config import DB_PATH
    # card_data is in bot dir — already on sys.path
    from card_data import _extract_dstv_num

    _LEAGUE_DEFAULTS = {
        "epl": ("SuperSport EPL", "203"),
        "psl": ("SuperSport PSL", "202"),
        "champions_league": ("SuperSport Football", "205"),
        "ucl": ("SuperSport Football", "205"),
        "urc": ("SuperSport Rugby", "211"),
        "ipl": ("SuperSport Cricket", "212"),
    }

    for home, away, match_key, league in test_cases:
        match_date_m = re.search(r"(\d{4}-\d{2}-\d{2})$", match_key)
        match_date = match_date_m.group(1) if match_date_m else ""

        conn = connect_odds_db(DB_PATH)
        conn.row_factory = sqlite3.Row

        # Pass 1
        rows1 = conn.execute('''
            SELECT * FROM broadcast_schedule
            WHERE source = "supersport_scraper"
              AND home_team IS NOT NULL AND away_team IS NOT NULL
              AND start_time IS NOT NULL
              AND DATE(start_time) = ?
        ''', (match_date,)).fetchall()
        m1 = fuzzy_match_broadcast(rows1, home, away) if rows1 else []

        # Pass 2
        rows2 = conn.execute('''
            SELECT * FROM broadcast_schedule
            WHERE home_team IS NOT NULL AND away_team IS NOT NULL
              AND start_time IS NOT NULL
              AND (dstv_number IS NOT NULL AND dstv_number != "")
              AND DATE(start_time) BETWEEN DATE(?,"-7 days") AND DATE(?,"+7 days")
            LIMIT 200
        ''', (match_date or "now", match_date or "now")).fetchall()
        m2 = fuzzy_match_broadcast(rows2, home, away) if rows2 else []

        conn.close()

        # Pass 3 (league default)
        pass3_result = None
        import os as _os
        for key, (def_label, def_dstv) in _LEAGUE_DEFAULTS.items():
            if key in league.lower():
                if _os.path.exists(f"/home/paulsportsza/assets/channels/{def_dstv}.png"):
                    pass3_result = f"{def_label} (DStv {def_dstv})"
                break

        # Final result
        if m1:
            bd = dict(m1[0])
            ch = (bd.get("channel_name") or bd.get("channel_short") or "").strip()
            dstv = (bd.get("dstv_number") or "").strip()
            final = f"{ch} (DStv {dstv})" if ch and dstv else ch
            path = "Pass 1"
        elif m2:
            bd = dict(m2[0])
            ch = (bd.get("channel_name") or bd.get("channel_short") or "").strip()
            dstv = (bd.get("dstv_number") or "").strip()
            final = f"{ch} (DStv {dstv})" if ch and dstv else ch
            path = "Pass 2"
        elif pass3_result:
            final = pass3_result
            path = "Pass 3 (league default)"
        else:
            final = ""
            path = "NONE"

        dstv_num = _extract_dstv_num(final)
        badge_renders = bool(dstv_num)

        status = "✔ BADGE" if badge_renders else "✖ FALLBACK/NONE"
        print(f"  {status}  {home} vs {away} [{league}]")
        print(f"           path={path}, channel={final!r}, dstv_num={dstv_num!r}")

    # ── 5. Summary ─────────────────────────────────────────────────────────────
    print(f"\n{sep}")
    print("  DOWNLOADED IMAGES")
    print(sep)
    for p in saved_cards:
        size_kb = p.stat().st_size // 1024 if p.exists() else 0
        print(f"  {p} ({size_kb}KB)")
    print(f"\n  To inspect: open {out_dir}/ and view the JPG files.")
    print("  The SS badge should appear as a green 'S NNN' box in the card meta bar.")

    await client.disconnect()
    print("\n  Done.")


if __name__ == "__main__":
    asyncio.run(run())
