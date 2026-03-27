"""UX Wave 26A-REVIEW — Telethon E2E Design Compliance Audit.

Sends /qa commands to the live bot, captures verbatim output,
verifies against approved Wave 26A templates.

Usage:
    cd /home/paulsportsza/bot && source .venv/bin/activate
    python tests/qa_ux_audit.py
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
from datetime import datetime

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import (
    ReplyInlineMarkup,
    KeyboardButtonCallback,
    KeyboardButtonUrl,
)

# ── Config ──────────────────────────────────────────────
API_ID = int(os.getenv("TELEGRAM_API_ID", "32418601"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "95e313a8ef5b998be0515dd8328fac57")
BOT_USERNAME = "mzansiedge_bot"
SESSION_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
STRING_SESSION_FILE = os.path.join(SESSION_DIR, "telethon_session.string")
FILE_SESSION = os.path.join(SESSION_DIR, "telethon_session")

WAIT_TIPS = 18
WAIT_TEASER = 12
WAIT_DETAIL = 18

BOT_ID = 8635022348  # Known bot ID from debug


# ── Helpers ─────────────────────────────────────────────

async def get_client() -> TelegramClient:
    if os.path.exists(STRING_SESSION_FILE):
        s = open(STRING_SESSION_FILE).read().strip()
        if s:
            c = TelegramClient(StringSession(s), API_ID, API_HASH)
            await c.connect()
            if await c.is_user_authorized():
                return c
            await c.disconnect()
    c = TelegramClient(FILE_SESSION, API_ID, API_HASH)
    await c.connect()
    if not await c.is_user_authorized():
        print("ERROR: Not logged in.")
        sys.exit(1)
    return c


def msg_to_dict(m) -> dict:
    """Convert a Telethon message to a serialisable dict."""
    entry = {
        "id": m.id,
        "text": m.raw_text or "",
        "sender_id": m.sender_id,
        "buttons": [],
    }
    if m.reply_markup and isinstance(m.reply_markup, ReplyInlineMarkup):
        for row in m.reply_markup.rows:
            row_btns = []
            for btn in row.buttons:
                b = {"text": getattr(btn, "text", "")}
                if isinstance(btn, KeyboardButtonUrl):
                    b["url"] = btn.url
                elif isinstance(btn, KeyboardButtonCallback):
                    b["callback"] = btn.data.decode() if isinstance(btn.data, bytes) else str(btn.data)
                row_btns.append(b)
            entry["buttons"].append(row_btns)
    return entry


async def send_and_get_bot_msgs(client, text: str, wait: float) -> list[dict]:
    """Send text, wait, return all bot messages after our sent message."""
    entity = await client.get_entity(BOT_USERNAME)
    sent = await client.send_message(entity, text)
    sent_id = sent.id
    await asyncio.sleep(wait)
    msgs = await client.get_messages(entity, limit=20)
    results = []
    for m in reversed(msgs):
        if m.id <= sent_id:
            continue
        if m.sender_id != BOT_ID:
            continue
        results.append(msg_to_dict(m))
    return results


def filter_qa_confirmation(msgs: list[dict]) -> list[dict]:
    """Remove QA confirmation and reset messages, keep actual content."""
    return [m for m in msgs if not m["text"].startswith("✅ QA:") and not m["text"].startswith("✅ Reset:")]


def count_lines(text: str) -> int:
    return len(text.strip().split("\n")) if text.strip() else 0


def has_button_text(msgs: list[dict], needle: str) -> bool:
    for m in msgs:
        for row in m.get("buttons", []):
            for btn in row:
                if needle in btn.get("text", ""):
                    return True
    return False


def has_url_button(msgs: list[dict]) -> bool:
    for m in msgs:
        for row in m.get("buttons", []):
            for btn in row:
                if "url" in btn:
                    return True
    return False


def all_text(msgs: list[dict]) -> str:
    return "\n---MSG---\n".join(m["text"] for m in msgs if m["text"])


# ── Audit checks ────────────────────────────────────────

TIER_EMOJIS = {"💎", "🥇", "🥈", "🥉"}
SECTION_HEADERS = {"DIAMOND EDGE", "GOLDEN EDGE", "SILVER EDGE", "BRONZE EDGE"}


def check_no_section_headers(text: str) -> list[str]:
    issues = []
    for line in text.split("\n"):
        stripped = line.strip()
        for hdr in SECTION_HEADERS:
            if stripped == f"💎 {hdr}" or stripped == f"🥇 {hdr}" or stripped == f"🥈 {hdr}" or stripped == f"🥉 {hdr}":
                issues.append(f"Section header found: '{stripped}'")
    return issues


def check_3_line_cards(text: str) -> list[str]:
    issues = []
    lines = text.split("\n")
    card_lines = []
    card_num = 0
    in_card = False
    for line in lines:
        stripped = line.strip()
        if re.match(r"^\[\d+\]", stripped):
            if in_card and len(card_lines) > 3:
                issues.append(f"Card [{card_num}] has {len(card_lines)} lines (max 3): {card_lines}")
            card_num = int(re.match(r"^\[(\d+)\]", stripped).group(1))
            card_lines = [stripped]
            in_card = True
        elif in_card and stripped and not stripped.startswith("━") and not stripped.startswith("🔒") and not stripped.startswith("📈") and not stripped.startswith("Unlock"):
            card_lines.append(stripped)
        elif not stripped or stripped.startswith("━"):
            if in_card and len(card_lines) > 3:
                issues.append(f"Card [{card_num}] has {len(card_lines)} lines (max 3): {card_lines}")
            in_card = False
    if in_card and len(card_lines) > 3:
        issues.append(f"Card [{card_num}] has {len(card_lines)} lines (max 3): {card_lines}")
    return issues


def check_single_footer_cta(text: str) -> list[str]:
    issues = []
    count = text.count("/subscribe")
    if count > 1:
        issues.append(f"/subscribe appears {count} times (max 1)")
    return issues


def check_no_signal_counts(text: str) -> list[str]:
    if re.search(r"\d/\d+ signals?", text):
        return ["Signal count found on list view"]
    return []


def check_tier_badges(text: str) -> list[str]:
    issues = []
    for line in text.split("\n"):
        s = line.strip()
        if re.match(r"^\[\d+\]", s) and "vs" in s:
            if not any(e in s for e in TIER_EMOJIS):
                issues.append(f"Card missing tier badge: '{s[:60]}'")
    return issues


def check_sport_emoji(text: str) -> list[str]:
    sport = {"⚽", "🏉", "🏏", "🥊", "🏅"}
    issues = []
    for line in text.split("\n"):
        s = line.strip()
        if re.match(r"^\[\d+\]", s) and "vs" in s:
            if not any(e in s for e in sport):
                issues.append(f"Card missing sport emoji: '{s[:60]}'")
    return issues


# ── Screen Tests ────────────────────────────────────────

async def audit_tips_bronze(client) -> dict:
    print("  [1/8] /qa tips_bronze ...")
    raw = await send_and_get_bot_msgs(client, "/qa tips_bronze", WAIT_TIPS)
    msgs = filter_qa_confirmation(raw)
    text = all_text(msgs)

    issues = []
    if not text.strip():
        issues.append("No content received")
        return {"screen": "tips_bronze", "pass": False, "issues": issues, "raw_text": "", "msg_count": 0, "buttons": [], "checks": {}}

    issues.extend(check_no_section_headers(text))
    issues.extend(check_3_line_cards(text))
    issues.extend(check_single_footer_cta(text))
    issues.extend(check_no_signal_counts(text))
    issues.extend(check_tier_badges(text))
    issues.extend(check_sport_emoji(text))

    checks = {
        "has_footer": "━" in text,
        "has_locked_count": "locked" in text.lower() or "🔒" in text,
        "has_portfolio": "R100" in text or "top" in text.lower(),
        "all_bronze_buttons_locked": all(
            "🔒" in btn.get("text", "") or "sub:plans" in btn.get("callback", "")
            for m in msgs for row in m.get("buttons", []) for btn in row
            if re.match(r"^\[\d+\]", btn.get("text", ""))
        ),
    }

    return {"screen": "tips_bronze", "pass": len(issues) == 0, "issues": issues, "raw_text": text, "msg_count": len(msgs), "buttons": [m.get("buttons", []) for m in msgs], "checks": checks}


async def audit_tips_gold(client) -> dict:
    print("  [2/8] /qa tips_gold ...")
    raw = await send_and_get_bot_msgs(client, "/qa tips_gold", WAIT_TIPS)
    msgs = filter_qa_confirmation(raw)
    text = all_text(msgs)

    issues = []
    if not text.strip():
        issues.append("No content received")
        return {"screen": "tips_gold", "pass": False, "issues": issues, "raw_text": "", "msg_count": 0, "buttons": [], "checks": {}}

    issues.extend(check_no_section_headers(text))
    issues.extend(check_3_line_cards(text))
    issues.extend(check_no_signal_counts(text))
    issues.extend(check_tier_badges(text))

    checks = {
        "has_odds": "@" in text,
        "diamond_locked": any("🔒" in btn.get("text", "") for m in msgs for row in m.get("buttons", []) for btn in row),
        "footer_light_or_none": text.count("/subscribe") <= 1,
    }

    return {"screen": "tips_gold", "pass": len(issues) == 0, "issues": issues, "raw_text": text, "msg_count": len(msgs), "buttons": [m.get("buttons", []) for m in msgs], "checks": checks}


async def audit_tips_diamond(client) -> dict:
    print("  [3/8] /qa tips_diamond ...")
    raw = await send_and_get_bot_msgs(client, "/qa tips_diamond", WAIT_TIPS)
    msgs = filter_qa_confirmation(raw)
    text = all_text(msgs)

    issues = []
    if not text.strip():
        issues.append("No content received")
        return {"screen": "tips_diamond", "pass": False, "issues": issues, "raw_text": "", "msg_count": 0, "buttons": [], "checks": {}}

    issues.extend(check_no_section_headers(text))
    issues.extend(check_3_line_cards(text))
    issues.extend(check_no_signal_counts(text))
    issues.extend(check_tier_badges(text))
    if "/subscribe" in text:
        issues.append("/subscribe found in Diamond view (no footer expected)")
    if "upgrade" in text.lower() or "unlock" in text.lower():
        issues.append("Upgrade/unlock CTA in Diamond view")

    checks = {
        "all_edges_full": "@" in text,
        "no_locked_buttons": not any("🔒" in btn.get("text", "") for m in msgs for row in m.get("buttons", []) for btn in row),
    }

    return {"screen": "tips_diamond", "pass": len(issues) == 0, "issues": issues, "raw_text": text, "msg_count": len(msgs), "buttons": [m.get("buttons", []) for m in msgs], "checks": checks}


async def audit_teaser_bronze(client) -> dict:
    print("  [4/8] /qa teaser_bronze ...")
    # Send /qa reset first to clear state
    await send_and_get_bot_msgs(client, "/qa reset", 3)
    await asyncio.sleep(2)

    raw = await send_and_get_bot_msgs(client, "/qa teaser_bronze", WAIT_TEASER)
    msgs = filter_qa_confirmation(raw)
    text = all_text(msgs)

    issues = []
    if not text.strip():
        issues.append("No content received")

    checks = {
        "has_morning_greeting": "morning" in text.lower() or "☀" in text,
        "has_yesterday_stats": "yesterday" in text.lower() or "%" in text,
        "has_free_picks": "🥈" in text or "🥉" in text or "@" in text,
        "has_locked_count": "locked" in text.lower() or "🔒" in text,
        "button_count": sum(len(btn) for m in msgs for btn in m.get("buttons", [])),
    }

    return {"screen": "teaser_bronze", "pass": len(issues) == 0, "issues": issues, "raw_text": text, "msg_count": len(msgs), "buttons": [m.get("buttons", []) for m in msgs], "checks": checks}


async def audit_teaser_gold(client) -> dict:
    print("  [5/8] /qa teaser_gold ...")
    await asyncio.sleep(2)

    raw = await send_and_get_bot_msgs(client, "/qa teaser_gold", WAIT_TEASER)
    msgs = filter_qa_confirmation(raw)
    text = all_text(msgs)

    issues = []
    if not text.strip():
        issues.append("No content received")

    checks = {
        "has_morning_greeting": "morning" in text.lower() or "☀" in text,
        "has_top_pick": "vs" in text or "@" in text,
        "has_diamond_fomo": "diamond" in text.lower() or "💎" in text,
        "no_view_plans": not has_button_text(msgs, "View Plans"),
        "button_count": sum(len(btn) for m in msgs for btn in m.get("buttons", [])),
    }

    return {"screen": "teaser_gold", "pass": len(issues) == 0, "issues": issues, "raw_text": text, "msg_count": len(msgs), "buttons": [m.get("buttons", []) for m in msgs], "checks": checks}


async def audit_teaser_diamond(client) -> dict:
    print("  [6/8] /qa teaser_diamond ...")
    await asyncio.sleep(2)

    raw = await send_and_get_bot_msgs(client, "/qa teaser_diamond", WAIT_TEASER)
    msgs = filter_qa_confirmation(raw)
    text = all_text(msgs)

    issues = []
    if not text.strip():
        issues.append("No content received")
    if "upgrade" in text.lower() or "/subscribe" in text:
        issues.append("Upgrade CTA found in Diamond teaser")

    checks = {
        "has_morning_greeting": "morning" in text.lower() or "☀" in text,
        "no_upgrade_cta": "upgrade" not in text.lower() and "/subscribe" not in text,
        "button_count": sum(len(btn) for m in msgs for btn in m.get("buttons", [])),
    }

    return {"screen": "teaser_diamond", "pass": len(issues) == 0, "issues": issues, "raw_text": text, "msg_count": len(msgs), "buttons": [m.get("buttons", []) for m in msgs], "checks": checks}


async def audit_detail_locked(client) -> dict:
    print("  [7/8] Detail locked (bronze buttons check) ...")
    await asyncio.sleep(2)

    raw = await send_and_get_bot_msgs(client, "/qa tips_bronze", WAIT_TIPS)
    msgs = filter_qa_confirmation(raw)
    text = all_text(msgs)

    # Check locked buttons exist and route to sub:plans
    has_locked = False
    locked_to_plans = False
    for m in msgs:
        for row in m.get("buttons", []):
            for btn in row:
                t = btn.get("text", "")
                if "🔒" in t:
                    has_locked = True
                    if btn.get("callback", "") == "sub:plans":
                        locked_to_plans = True

    issues = []
    if not has_locked:
        issues.append("No locked (🔒) buttons found in Bronze tips")
    if has_locked and not locked_to_plans:
        issues.append("Locked buttons don't route to sub:plans")

    checks = {
        "has_locked_buttons": has_locked,
        "locked_to_plans": locked_to_plans,
        "footer_has_subscribe": "/subscribe" in text,
        "no_bookmaker_link": not has_url_button(msgs),
    }

    return {"screen": "detail_locked", "pass": len(issues) == 0, "issues": issues, "raw_text": text, "msg_count": len(msgs), "buttons": [m.get("buttons", []) for m in msgs], "checks": checks}


async def audit_detail_accessible(client) -> dict:
    print("  [8/8] Detail accessible (tap edge from diamond) ...")
    await asyncio.sleep(2)

    entity = await client.get_entity(BOT_USERNAME)
    # Send tips_diamond and wait
    sent = await client.send_message(entity, "/qa tips_diamond")
    await asyncio.sleep(WAIT_TIPS)

    # Get recent messages
    recent = await client.get_messages(entity, limit=15)

    # Find an edge detail button (tier emoji + "v" for "vs")
    clicked = False
    detail_msgs = []
    for msg in recent:
        if not msg.reply_markup or not isinstance(msg.reply_markup, ReplyInlineMarkup):
            continue
        for row in msg.reply_markup.rows:
            for btn in row.buttons:
                if not isinstance(btn, KeyboardButtonCallback):
                    continue
                t = getattr(btn, "text", "")
                cb = btn.data.decode() if isinstance(btn.data, bytes) else str(btn.data)
                if cb.startswith("edge:detail:"):
                    try:
                        await msg.click(data=btn.data)
                        await asyncio.sleep(WAIT_DETAIL)
                        after = await client.get_messages(entity, limit=15)
                        for dm in reversed(after):
                            if dm.id > sent.id and dm.sender_id == BOT_ID:
                                d = msg_to_dict(dm)
                                if d["text"] and not d["text"].startswith("✅ QA:"):
                                    detail_msgs.append(d)
                        clicked = True
                    except Exception as e:
                        detail_msgs = [{"text": f"Click error: {e}", "buttons": [], "id": 0, "sender_id": 0}]
                        clicked = True
                    break
            if clicked:
                break
        if clicked:
            break

    text = all_text(detail_msgs) if detail_msgs else ""
    issues = []
    if not clicked:
        issues.append("Could not find/click an edge:detail button")
    if not text.strip():
        issues.append("No detail content received after click")

    checks = {
        "clicked": clicked,
        "has_setup": "Setup" in text or "📋" in text,
        "has_edge_section": "Edge" in text or "🎯" in text,
        "has_verdict": "Verdict" in text or "🏆" in text,
        "has_bookmaker_link": has_url_button(detail_msgs),
        "has_compare_odds": has_button_text(detail_msgs, "Odds") or has_button_text(detail_msgs, "odds"),
        "has_back_btn": has_button_text(detail_msgs, "Back") or has_button_text(detail_msgs, "↩"),
    }

    return {"screen": "detail_accessible", "pass": len(issues) == 0, "issues": issues, "raw_text": text[:3000], "msg_count": len(detail_msgs), "buttons": [m.get("buttons", []) for m in detail_msgs], "checks": checks}


# ── Main ────────────────────────────────────────────────

async def main():
    print("=" * 60)
    print("UX Wave 26A-REVIEW — Telethon E2E Design Compliance Audit")
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)

    client = await get_client()
    print(f"Connected. Testing @{BOT_USERNAME}\n")

    results = []
    for fn in [
        audit_tips_bronze,
        audit_tips_gold,
        audit_tips_diamond,
        audit_teaser_bronze,
        audit_teaser_gold,
        audit_teaser_diamond,
        audit_detail_locked,
        audit_detail_accessible,
    ]:
        try:
            r = await fn(client)
        except Exception as e:
            r = {"screen": fn.__name__.replace("audit_", ""), "pass": False, "issues": [f"Exception: {e}"], "raw_text": "", "msg_count": 0, "buttons": [], "checks": {}}
        results.append(r)
        s = "PASS" if r["pass"] else "FAIL"
        print(f"    {'✅' if r['pass'] else '❌'} {s} — {r['screen']} ({len(r['issues'])} issues)")

    await client.disconnect()

    from config import BOT_ROOT
    out = str(BOT_ROOT.parent / "reports" / "e2e-captures-26a-review.json")
    with open(out, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nRaw captures: {out}")

    # Summary
    print("\n" + "=" * 60)
    passed = sum(1 for r in results if r["pass"])
    print(f"RESULT: {passed}/{len(results)} screens passed")
    print("=" * 60)

    for r in results:
        print(f"\n{'─' * 50}")
        print(f"{'✅' if r['pass'] else '❌'} {r['screen']} — {'PASS' if r['pass'] else 'FAIL'}")
        if r["issues"]:
            for i in r["issues"]:
                print(f"  ⚠ {i}")
        if r.get("checks"):
            for k, v in r["checks"].items():
                print(f"  {k}: {v}")
        preview = r["raw_text"][:800]
        if preview:
            print(f"  --- Captured ({count_lines(r['raw_text'])} lines) ---")
            for line in preview.split("\n")[:20]:
                print(f"  | {line}")
            if len(r["raw_text"]) > 800:
                print(f"  | ... ({len(r['raw_text'])} total chars)")

    return results


if __name__ == "__main__":
    asyncio.run(main())
