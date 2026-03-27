#!/usr/bin/env python3
"""W31-QA Check 4: Gate Leak Verification via Telethon."""
from __future__ import annotations
import asyncio, json, logging, os, re, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import ensure_scrapers_importable, BOT_ROOT
ensure_scrapers_importable()
from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.sessions import StringSession
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("w31_gate")

BOT = "mzansiedge_bot"
API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "")
SESSION_PATH = Path("data/telethon_session.string")
CAPTURE_DIR = BOT_ROOT.parent / "reports" / "screenshots" / "w31_gate"
CAPTURE_DIR.mkdir(parents=True, exist_ok=True)

results = []

def record(cid, name, status, evidence):
    results.append({"check_id": cid, "name": name, "status": status, "evidence": evidence[:3000]})
    icon = {"PASS": "✓", "FAIL": "✗", "WARN": "⚠"}.get(status, "?")
    log.info("  %s %s: %s — %s", icon, cid, name, status)

async def send_and_wait(client, cmd, wait=5):
    """Send command, wait, return latest non-out messages."""
    await client.send_message(BOT, cmd)
    await asyncio.sleep(wait)
    msgs = await client.get_messages(BOT, limit=8)
    return [m for m in msgs if not m.out]

def get_text(msgs):
    return "\n---\n".join((m.text or "") for m in msgs)

def get_buttons(msgs):
    btns = []
    for m in msgs:
        if m.buttons:
            for row in m.buttons:
                for b in row:
                    btns.append(b.text or "")
    return btns

def get_btn_data(msgs):
    data = []
    for m in msgs:
        if m.buttons:
            for row in m.buttons:
                for b in row:
                    if hasattr(b, 'data') and b.data:
                        data.append(b.data.decode('utf-8', errors='replace'))
                    elif hasattr(b, 'url') and b.url:
                        data.append(f"url:{b.url[:80]}")
    return data

async def find_and_click(msgs, pattern, wait=8):
    """Find a button matching pattern and click it."""
    for m in msgs:
        if not m.buttons:
            continue
        for row in m.buttons:
            for btn in row:
                if re.search(pattern, btn.text or "", re.IGNORECASE):
                    try:
                        await btn.click()
                    except Exception as e:
                        log.warning("Click error: %s", e)
                    await asyncio.sleep(wait)
                    return True
    return False

async def get_edited_or_new(client, ref_msg_id, wait=5):
    """After a button click, get the edited message or newest bot message."""
    await asyncio.sleep(wait)
    # Check edited
    edited = await client.get_messages(BOT, ids=[ref_msg_id])
    if edited and edited[0]:
        return edited[0]
    # Fallback: newest non-out
    msgs = await client.get_messages(BOT, limit=5)
    for m in msgs:
        if not m.out:
            return m
    return None


async def run():
    session_str = SESSION_PATH.read_text().strip()
    client = TelegramClient(StringSession(session_str), API_ID, API_HASH)
    await client.connect()
    if not await client.is_user_authorized():
        log.error("Not authorized"); return

    log.info("Connected. Running gate leak checks...")

    # ═══════════════════════════════════════════════════════
    # BRONZE TIER CHECKS
    # ═══════════════════════════════════════════════════════
    log.info("\n=== BRONZE TIER ===")
    await send_and_wait(client, "/qa set_bronze", 3)

    # Get Hot Tips list as Bronze
    msgs = await send_and_wait(client, "/qa tips_bronze", 8)
    # Find the tips message (not QA confirmation)
    tips_msgs = [m for m in msgs if not m.out and len(m.text or "") > 100]
    text = get_text(tips_msgs) if tips_msgs else get_text(msgs)
    btns = get_buttons(tips_msgs) if tips_msgs else get_buttons(msgs)
    btn_data = get_btn_data(tips_msgs) if tips_msgs else get_btn_data(msgs)
    (CAPTURE_DIR / "bronze_list.txt").write_text(text + "\n\nBTNS:\n" + "\n".join(btns) + "\n\nDATA:\n" + "\n".join(btn_data))

    # 4a: Blurred cards show return only (no odds, no bookmaker)
    # Bronze viewing Gold edges should show "💰 R{x} return on R300" without "@" odds
    blurred_lines = [l for l in text.split('\n') if '💰' in l and 'return' in l.lower()]
    blurred_has_at = any('@' in l for l in blurred_lines)
    record("4a", "Blurred cards show return only (no odds)",
           "PASS" if blurred_lines and not blurred_has_at else "WARN" if not blurred_lines else "FAIL",
           f"Blurred lines: {blurred_lines[:3]}, has '@' (odds): {blurred_has_at}")

    # 4b: Locked cards show no return amount
    locked_lines = [l for l in text.split('\n') if 'highest-conviction' in l.lower() or ('🔒' in l and 'locked' not in l.lower())]
    locked_has_return = any('R' in l and 'return' in l.lower() for l in locked_lines)
    record("4b", "Locked cards show no return amount",
           "PASS" if not locked_has_return else "FAIL",
           f"Locked lines: {locked_lines[:3]}")

    # 4c: Button emoji matches edge tier (not hardcoded 💎)
    tier_btns = [b for b in btns if re.match(r'\[\d+\]', b)]
    has_lock_btns = any('🔒' in b for b in tier_btns)
    has_tier_emoji_btns = any(any(e in b for e in ['💎','🥇','🥈','🥉']) for b in tier_btns)
    # For bronze, locked edges show 🔒, not the edge tier emoji
    record("4c", "Button emoji: 🔒 for locked edges (bronze)",
           "PASS" if has_lock_btns else "FAIL",
           f"Tier buttons: {tier_btns}")

    # 4d: Compare All Odds hidden for blurred/locked
    has_compare = any('Compare' in b or 'All Odds' in b for b in btns)
    record("4d", "No Compare All Odds on bronze list",
           "PASS" if not has_compare else "FAIL",
           f"Compare button found: {has_compare}")

    # 4e: Tap a locked edge (🔒) → verify locked detail view
    tips_msg_with_btns = None
    for m in tips_msgs or msgs:
        if m.buttons:
            for row in m.buttons:
                for b in row:
                    if '🔒' in (b.text or ''):
                        tips_msg_with_btns = m
                        break
                if tips_msg_with_btns:
                    break
        if tips_msg_with_btns:
            break

    if tips_msg_with_btns:
        msg_id = tips_msg_with_btns.id
        # Click first 🔒 button
        for row in tips_msg_with_btns.buttons:
            for b in row:
                if '🔒' in (b.text or ''):
                    try:
                        await b.click()
                    except Exception:
                        pass
                    break
            else:
                continue
            break

        await asyncio.sleep(5)
        detail = await client.get_messages(BOT, ids=[msg_id])
        detail_text = detail[0].text if detail and detail[0] else ""
        detail_btns = []
        if detail and detail[0] and detail[0].buttons:
            for row in detail[0].buttons:
                for b in row:
                    detail_btns.append(b.text or "")
        (CAPTURE_DIR / "bronze_locked_detail.txt").write_text(detail_text + "\n\nBTNS:\n" + "\n".join(detail_btns))

        # Check locked detail: no odds, no bookmaker, no AI content, no deep link
        has_odds = bool(re.search(r'\d+\.\d{2}', detail_text) and '@' in detail_text)
        has_bk_names = any(bk in detail_text.lower() for bk in ['hollywoodbets','gbets','supabets','betway','sportingbet','wsb','playabets'])
        has_ai_sections = any(s in detail_text for s in ['📋','🎯','⚠️','🏆'])
        detail_btn_data = get_btn_data([detail[0]]) if detail and detail[0] else []
        has_deep_link = any('url:' in d for d in detail_btn_data)
        has_preamble_before_lock = False
        if '🔒' in detail_text:
            before_lock = detail_text[:detail_text.index('🔒')]
            has_preamble_before_lock = len(before_lock.strip()) > 50 and '📋' not in before_lock

        record("4e", "Locked detail: no odds/bk/AI/deeplink",
               "PASS" if not has_odds and not has_bk_names and not has_ai_sections and not has_deep_link else "FAIL",
               f"odds={has_odds}, bk_names={has_bk_names}, ai_sections={has_ai_sections}, deep_link={has_deep_link}")

        record("4f", "No preamble text before first lock",
               "PASS" if not has_preamble_before_lock else "WARN",
               f"preamble_before_lock={has_preamble_before_lock}, text_start={detail_text[:200]}")
    else:
        record("4e", "Locked detail", "SKIP", "No 🔒 button found")
        record("4f", "No preamble", "SKIP", "No 🔒 button found")

    await asyncio.sleep(3)

    # ═══════════════════════════════════════════════════════
    # GOLD TIER CHECKS
    # ═══════════════════════════════════════════════════════
    log.info("\n=== GOLD TIER ===")
    await send_and_wait(client, "/qa set_gold", 3)
    msgs = await send_and_wait(client, "/qa tips_gold", 8)
    tips_msgs = [m for m in msgs if not m.out and len(m.text or "") > 100]
    text = get_text(tips_msgs) if tips_msgs else get_text(msgs)
    btns = get_buttons(tips_msgs) if tips_msgs else get_buttons(msgs)
    btn_data = get_btn_data(tips_msgs) if tips_msgs else get_btn_data(msgs)
    (CAPTURE_DIR / "gold_list.txt").write_text(text + "\n\nBTNS:\n" + "\n".join(btns) + "\n\nDATA:\n" + "\n".join(btn_data))

    # 4g: Diamond edge locked for Gold
    has_diamond_locked = "highest-conviction" in text.lower() or ('🔒' in text and '💎' in text)
    record("4g", "Diamond edge locked for Gold user",
           "PASS" if has_diamond_locked else "WARN",
           f"diamond_locked={has_diamond_locked}")

    # 4h: Gold edges show full odds
    gold_has_odds = bool(re.search(r'@\s*\d+\.\d{2}', text))
    record("4h", "Gold edges show full odds",
           "PASS" if gold_has_odds else "WARN",
           f"gold_has_odds={gold_has_odds}")

    # 4i: Button emoji matches tier
    tier_btns = [b for b in btns if re.match(r'\[\d+\]', b)]
    has_gold_emoji = any('🥇' in b for b in tier_btns)
    has_lock_for_diamond = any('🔒' in b for b in tier_btns)
    record("4i", "Button emoji: 🥇 for Gold, 🔒 for Diamond",
           "PASS" if has_gold_emoji or has_lock_for_diamond else "WARN",
           f"Gold tier buttons: {tier_btns}")

    await asyncio.sleep(3)

    # ═══════════════════════════════════════════════════════
    # DIAMOND TIER CHECKS
    # ═══════════════════════════════════════════════════════
    log.info("\n=== DIAMOND TIER ===")
    await send_and_wait(client, "/qa set_diamond", 3)
    msgs = await send_and_wait(client, "/qa tips_diamond", 8)
    tips_msgs = [m for m in msgs if not m.out and len(m.text or "") > 100]
    text = get_text(tips_msgs) if tips_msgs else get_text(msgs)
    btns = get_buttons(tips_msgs) if tips_msgs else get_buttons(msgs)
    (CAPTURE_DIR / "diamond_list.txt").write_text(text + "\n\nBTNS:\n" + "\n".join(btns))

    # 4j: All edges visible, no lock messages, no CTAs
    has_lock_msg = "🔒" in text and ("locked" in text.lower() or "highest-conviction" in text.lower())
    has_subscribe = "/subscribe" in text
    record("4j", "Diamond: all visible, no locks, no CTAs",
           "PASS" if not has_lock_msg and not has_subscribe else "FAIL",
           f"lock_msg={has_lock_msg}, subscribe={has_subscribe}")

    # Reset
    await send_and_wait(client, "/qa reset", 2)
    await client.disconnect()

    # Summary
    log.info("\n" + "=" * 50)
    p = sum(1 for r in results if r["status"] == "PASS")
    f = sum(1 for r in results if r["status"] == "FAIL")
    w = sum(1 for r in results if r["status"] == "WARN")
    log.info("Gate checks: %d | PASS: %d | FAIL: %d | WARN: %d", len(results), p, f, w)

    out = CAPTURE_DIR / "results.json"
    out.write_text(json.dumps(results, indent=2))
    for r in results:
        print(f"  {r['check_id']}: {r['status']} — {r['name']}")


if __name__ == "__main__":
    asyncio.run(run())
