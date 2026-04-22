#!/usr/bin/env python3
"""
FIX-NARRATIVE-CACHE-SILENT-DROP-01 QA (SO #38 separate-agent verifier).

For 5 fixtures: L1 channel preview (best-effort) + L2 deep-link detail + L3 AI
Breakdown tap. Evidence dir: /home/paulsportsza/reports/telethon-silentdrop-evidence.
"""
import asyncio
import os
import sys
import time

sys.path.insert(0, "/home/paulsportsza/bot")

from dotenv import load_dotenv
load_dotenv("/home/paulsportsza/bot/.env")

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import MessageMediaPhoto

SESSION_FILE = "/home/paulsportsza/bot/data/telethon_session.string"
BOT_USERNAME = "mzansiedge_bot"
EVIDENCE_DIR = "/home/paulsportsza/reports/telethon-silentdrop-evidence"

CHANNELS = ["MzansiEdgeAlerts", "MzansiEdge"]

FIXTURES = [
    # (shortkey, match_key, sport_label)
    ("astonvilla_tottenham",          "aston_villa_vs_tottenham_2026-05-03",                   "soccer/EPL"),
    ("pirates_chiefs",                "orlando_pirates_vs_kaizer_chiefs_2026-04-26",           "soccer/PSL"),
    ("arsenal_fulham",                "arsenal_vs_fulham_2026-05-04",                          "soccer/EPL"),
    ("lsg_rr",                        "lucknow_super_giants_vs_rajasthan_royals_2026-04-22",   "cricket/IPL"),
    ("cardiff_ospreys",               "cardiff_city_vs_ospreys_2026-04-24",                    "rugby/URC"),
]

with open(SESSION_FILE) as f:
    SESSION_STR = f.read().strip()

API_ID = int(os.environ["TELEGRAM_API_ID"])
API_HASH = os.environ["TELEGRAM_API_HASH"]

os.makedirs(EVIDENCE_DIR, exist_ok=True)

RESULTS: list[dict] = []
FILES: list[str] = []


def log(msg: str):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


async def latest_id(client) -> int:
    msgs = await client.get_messages(BOT_USERNAME, limit=1)
    return msgs[0].id if msgs else 0


async def wait_for_new(client, after_id: int, timeout: int = 35):
    deadline = time.time() + timeout
    while time.time() < deadline:
        msgs = await client.get_messages(BOT_USERNAME, limit=5)
        for m in reversed(msgs):
            if m.id > after_id:
                return m
        await asyncio.sleep(0.8)
    return None


def button_list(msg):
    btns = []
    if msg and msg.reply_markup is not None:
        for row in msg.reply_markup.rows:
            for b in row.buttons:
                btns.append(b)
    return btns


def btn_cb(btn) -> str:
    data = getattr(btn, "data", None)
    if data is None:
        return ""
    return data.decode() if isinstance(data, bytes) else str(data)


def content(msg) -> str:
    if msg is None:
        return ""
    out = []
    if msg.text:
        out.append(msg.text)
    if msg.media:
        cap = getattr(msg, "caption", None) or getattr(msg.media, "caption", "")
        if cap and cap not in out:
            out.append(cap)
    return "\n".join(out)


async def download_photo(msg, dest: str) -> bool:
    if msg is None or not isinstance(msg.media, MessageMediaPhoto):
        return False
    try:
        path = await msg.download_media(file=dest)
        if path:
            FILES.append(path)
            return True
    except Exception as e:
        log(f"  download error: {e}")
    return False


async def send_and_wait(client, text: str, timeout: int = 25):
    anchor = await latest_id(client)
    await client.send_message(BOT_USERNAME, text)
    return await wait_for_new(client, anchor, timeout=timeout)


async def tap_button(client, msg, btn, timeout: int = 35):
    before = await latest_id(client)
    before_msg = (await client.get_messages(BOT_USERNAME, limit=1))[0]
    before_edit = getattr(before_msg, "edit_date", None)
    try:
        await msg.click(data=btn.data)
    except Exception as e:
        log(f"  click error: {e}")
    deadline = time.time() + timeout
    while time.time() < deadline:
        await asyncio.sleep(1.0)
        msgs = await client.get_messages(BOT_USERNAME, limit=3)
        for m in msgs:
            if m.id > before:
                return m
        latest = msgs[0] if msgs else None
        if latest and latest.id == before:
            new_edit = getattr(latest, "edit_date", None)
            if new_edit and new_edit != before_edit:
                return latest
    msgs = await client.get_messages(BOT_USERNAME, limit=1)
    return msgs[0] if msgs else None


async def level1_channel_preview(client, shortkey: str, match_key: str) -> tuple[str, str]:
    """Best-effort — search last 50 messages in both channels for fixture references."""
    terms = match_key.split("_vs_")
    if len(terms) == 2:
        home = terms[0].replace("_", " ").lower()
        away_raw = terms[1].rsplit("_", 1)[0] if terms[1].count("_") >= 2 else terms[1]
        away = away_raw.replace("_", " ").lower()
    else:
        home = away = ""

    for ch in CHANNELS:
        try:
            msgs = await client.get_messages(ch, limit=50)
        except Exception as e:
            log(f"  L1 {ch}: {e}")
            continue
        for m in msgs:
            txt = (content(m) or "").lower()
            if home and away and home in txt and away in txt:
                if isinstance(m.media, MessageMediaPhoto):
                    path = os.path.join(EVIDENCE_DIR, f"level1_{shortkey}.jpg")
                    ok = await download_photo(m, path)
                    if ok:
                        return ("FOUND", f"channel={ch} msg_id={m.id}")
                return ("FOUND_NO_PHOTO", f"channel={ch} msg_id={m.id}")
    return ("NO_CHANNEL_PREVIEW", "")


async def level2_deeplink(client, shortkey: str, match_key: str):
    """Send /start card_<match_key>, wait for detail card, download, inspect."""
    anchor = await latest_id(client)
    await client.send_message(BOT_USERNAME, f"/start card_{match_key}")
    msg = await wait_for_new(client, anchor, timeout=35)
    if msg is None:
        return {"status": "FAIL", "reason": "no reply", "msg": None, "btns": []}

    # Wait a beat for full render
    await asyncio.sleep(1.5)
    latest = (await client.get_messages(BOT_USERNAME, limit=1))[0]
    text_body = content(latest)
    btns = button_list(latest)

    # Download if photo
    is_photo = isinstance(latest.media, MessageMediaPhoto)
    if is_photo:
        await download_photo(latest, os.path.join(EVIDENCE_DIR, f"level2_{shortkey}.jpg"))

    # Look for Full AI Breakdown button (either unlocked or gated)
    ai_btn_unlocked = None
    ai_btn_locked = None
    for b in btns:
        t = (b.text or "")
        if "Full AI Breakdown" in t:
            if "🤖" in t:
                ai_btn_unlocked = b
            elif "🔒" in t:
                ai_btn_locked = b
    any_breakdown_cb = None
    for b in btns:
        cb = btn_cb(b)
        if "edge:breakdown" in cb:
            any_breakdown_cb = b
            break

    # Evaluate
    if ai_btn_unlocked or ai_btn_locked or any_breakdown_cb:
        status = "PASS"
    elif "no current edge data" in text_body.lower() or "not available" in text_body.lower():
        status = "FAIL_NO_EDGE"
    else:
        status = "FAIL_NO_BUTTON"

    return {
        "status": status,
        "msg": latest,
        "btns": btns,
        "ai_unlocked": ai_btn_unlocked,
        "ai_locked": ai_btn_locked,
        "any_breakdown": any_breakdown_cb,
        "is_photo": is_photo,
        "text": text_body[:400],
    }


async def level3_tap_breakdown(client, shortkey: str, l2: dict):
    btn_to_tap = l2.get("ai_unlocked") or l2.get("any_breakdown")
    if btn_to_tap is None:
        return {"status": "SKIP", "reason": "no unlocked breakdown button"}

    bd_msg = await tap_button(client, l2["msg"], btn_to_tap, timeout=40)
    await asyncio.sleep(2.0)
    latest = (await client.get_messages(BOT_USERNAME, limit=1))[0]

    is_photo = isinstance(latest.media, MessageMediaPhoto)
    if is_photo:
        await download_photo(latest, os.path.join(EVIDENCE_DIR, f"level3_{shortkey}.jpg"))

    btns = button_list(latest)
    back_present = any(
        ("Back to Edge Picks" in (b.text or "")) or ("back" in btn_cb(b).lower() and "hot" in btn_cb(b).lower())
        for b in btns
    )
    text_body = content(latest)
    if (bool(text_body) or is_photo) and len(btns) > 0:
        status = "PASS" if back_present else "PASS_NO_BACK"
    else:
        status = "FAIL"

    return {
        "status": status,
        "is_photo": is_photo,
        "back_present": back_present,
        "btn_count": len(btns),
        "text": text_body[:300],
    }


async def run_fixture(client, shortkey: str, match_key: str, sport_label: str):
    log(f"\n=== {shortkey}  [{sport_label}]  match_key={match_key} ===")

    # ----- L1
    l1_status, l1_detail = await level1_channel_preview(client, shortkey, match_key)
    log(f"  L1: {l1_status} {l1_detail}")

    # ----- L2
    l2 = await level2_deeplink(client, shortkey, match_key)
    l2_text_preview = l2.get("text", "")[:100]
    log(f"  L2: {l2['status']} is_photo={l2.get('is_photo')} btns={len(l2.get('btns', []))} text={l2_text_preview!r}")
    # Log every button text+cb for audit
    for b in l2.get("btns", []):
        log(f"    btn: '{b.text}' cb={btn_cb(b)[:80]}")

    # ----- L3
    if l2["status"].startswith("PASS"):
        l3 = await level3_tap_breakdown(client, shortkey, l2)
    else:
        l3 = {"status": "SKIP", "reason": f"L2 was {l2['status']}"}
    log(f"  L3: {l3['status']}  {l3}")

    RESULTS.append({
        "shortkey": shortkey,
        "match_key": match_key,
        "sport_label": sport_label,
        "l1": l1_status,
        "l2": l2["status"],
        "l2_btn_count": len(l2.get("btns", [])),
        "l2_any_breakdown": bool(l2.get("ai_unlocked") or l2.get("any_breakdown")),
        "l2_text_preview": l2_text_preview,
        "l3": l3["status"],
        "l3_back": l3.get("back_present", False),
        "l3_is_photo": l3.get("is_photo", False),
    })


async def main():
    log(f"Connecting (API_ID={API_ID}) to QA evidence harness...")
    async with TelegramClient(StringSession(SESSION_STR), API_ID, API_HASH) as client:
        log("Connected.")

        # Pre-flight: diamond override
        log("Setting diamond tier override")
        ack = await send_and_wait(client, "/qa set_diamond", timeout=20)
        log(f"  ack: {(content(ack) or '').strip()[:140]}")
        await asyncio.sleep(1.5)

        for shortkey, match_key, sport_label in FIXTURES:
            try:
                await run_fixture(client, shortkey, match_key, sport_label)
            except Exception as e:
                log(f"  FIXTURE RAISE: {e}")
                RESULTS.append({
                    "shortkey": shortkey,
                    "match_key": match_key,
                    "sport_label": sport_label,
                    "l1": "ERROR",
                    "l2": "ERROR",
                    "l2_btn_count": 0,
                    "l2_any_breakdown": False,
                    "l2_text_preview": str(e)[:100],
                    "l3": "SKIP",
                    "l3_back": False,
                    "l3_is_photo": False,
                })
            await asyncio.sleep(1.5)

        # Reset
        log("\nResetting QA override")
        ack = await send_and_wait(client, "/qa reset", timeout=15)
        log(f"  ack: {(content(ack) or '').strip()[:140]}")

    # Print the evidence summary
    print("\n" + "=" * 70)
    print("EVIDENCE SUMMARY")
    print("=" * 70)
    print(f"{'shortkey':<22} {'L1':<22} {'L2':<14} {'btns':<4} {'L3':<14} {'bk':<3} {'ph':<3}")
    for r in RESULTS:
        print(f"{r['shortkey']:<22} {r['l1']:<22} {r['l2']:<14} {r['l2_btn_count']:<4} {r['l3']:<14} {'Y' if r['l3_back'] else 'N':<3} {'Y' if r['l3_is_photo'] else 'N':<3}")

    print("\nFiles written:")
    for f in FILES:
        print(f"  {f}")


if __name__ == "__main__":
    asyncio.run(main())
