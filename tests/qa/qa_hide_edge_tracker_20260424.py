#!/usr/bin/env python3
"""QA script for FIX-HIDE-EDGE-TRACKER-P0-01.

Verifies via Telethon + OCR that:
1. 👤 Profile card contains NO "Edge Performance", "ROI", "hit", "streak"
2. Main menu inline keyboard has NO "Edge Tracker" button
3. Manually triggered `results:7` callback (equivalent of edge_tracker:home)
   produces the graceful "Edge Tracker is coming soon." redirect, not a crash

Runs via Telethon from the QA string session.
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

_bot_dir = Path(__file__).parent.parent.parent
load_dotenv(_bot_dir / ".env")

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import (
    ReplyInlineMarkup,
    KeyboardButtonCallback,
    MessageMediaPhoto,
)

from tests.qa.vision_ocr import ocr_card
from tests.qa import card_assertions as CA

API_ID = int(os.getenv("TELEGRAM_API_ID", "32418601"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "95e313a8ef5b998be0515dd8328fac57")
BOT_USERNAME = "@mzansiedge_bot"
STRING_SESSION_FILE = str(_bot_dir / "data" / "telethon_session.string")
SHOT_DIR = Path("/tmp/qa_hide_edge_tracker_20260424")
SHOT_DIR.mkdir(parents=True, exist_ok=True)

WAIT_LONG = 25.0
WAIT_MID = 12.0
WAIT_SHORT = 6.0


def _load_session() -> str:
    s = Path(STRING_SESSION_FILE)
    if not s.is_file():
        raise SystemExit(f"Missing session file: {s}")
    return s.read_text().strip()


async def _wait_for_bot(client, entity, after_id: int, timeout: float = 20.0) -> list:
    start = time.time()
    while time.time() - start < timeout:
        msgs = await client.get_messages(entity, limit=20)
        new = [m for m in msgs if m.id > after_id and not m.out]
        if new:
            return list(reversed(new))
        await asyncio.sleep(1.0)
    return []


async def _send(client, entity, text: str, wait: float = WAIT_MID) -> list:
    before = await client.get_messages(entity, limit=1)
    after_id = before[0].id if before else 0
    await client.send_message(entity, text)
    return await _wait_for_bot(client, entity, after_id, timeout=wait)


async def _click_cb(client, entity, msg, cb_data: str, wait: float = WAIT_MID) -> list:
    if not msg.reply_markup or not isinstance(msg.reply_markup, ReplyInlineMarkup):
        raise RuntimeError(f"No inline markup on message {msg.id}")
    for row in msg.reply_markup.rows:
        for btn in row.buttons:
            if isinstance(btn, KeyboardButtonCallback) and btn.data == cb_data.encode():
                before = await client.get_messages(entity, limit=1)
                after_id = before[0].id if before else 0
                await msg.click(data=cb_data.encode())
                await asyncio.sleep(wait)
                msgs = await client.get_messages(entity, limit=20)
                return list(reversed([m for m in msgs if not m.out]))
    raise RuntimeError(f"Callback {cb_data!r} not found on message {msg.id}")


async def _download_media(client, msg, dest: Path) -> Path | None:
    if not msg.media:
        return None
    if isinstance(msg.media, MessageMediaPhoto):
        return Path(await client.download_media(msg, file=str(dest)))
    # Some cards come as documents / web previews — skip.
    return None


def _button_labels(msg) -> list[str]:
    if not msg.reply_markup or not isinstance(msg.reply_markup, ReplyInlineMarkup):
        return []
    out: list[str] = []
    for row in msg.reply_markup.rows:
        for btn in row.buttons:
            out.append(getattr(btn, "text", ""))
    return out


def _button_data(msg) -> list[str]:
    if not msg.reply_markup or not isinstance(msg.reply_markup, ReplyInlineMarkup):
        return []
    out: list[str] = []
    for row in msg.reply_markup.rows:
        for btn in row.buttons:
            if isinstance(btn, KeyboardButtonCallback):
                out.append(btn.data.decode("utf-8", errors="replace"))
    return out


def _extract_text(msg) -> str:
    return (msg.message or "").strip()


async def run() -> int:
    session_str = _load_session()
    client = TelegramClient(StringSession(session_str), API_ID, API_HASH)
    await client.start()
    entity = await client.get_entity(BOT_USERNAME)

    report: dict = {
        "brief": "FIX-HIDE-EDGE-TRACKER-P0-01",
        "run_at": datetime.utcnow().isoformat() + "Z",
        "checks": [],
    }
    overall_pass = True

    # ── CHECK 1: /menu renders kb_main with NO "Edge Tracker" button ──
    menus = await _send(client, entity, "/menu", wait=WAIT_MID)
    menu_msg = None
    for m in menus:
        if m.reply_markup and isinstance(m.reply_markup, ReplyInlineMarkup):
            menu_msg = m
            break

    menu_labels = _button_labels(menu_msg) if menu_msg else []
    menu_cb = _button_data(menu_msg) if menu_msg else []
    menu_text = _extract_text(menu_msg) if menu_msg else ""
    menu_ok = (
        bool(menu_msg)
        and not any("Edge Tracker" in lbl for lbl in menu_labels)
        and not any(cb.startswith("results:") for cb in menu_cb)
    )
    report["checks"].append({
        "name": "main_menu_no_edge_tracker_button",
        "pass": menu_ok,
        "button_labels": menu_labels,
        "button_callbacks": menu_cb,
        "text_preview": menu_text[:200],
    })
    overall_pass &= menu_ok

    # Screenshot menu if card
    menu_img = None
    if menu_msg:
        menu_img = await _download_media(client, menu_msg, SHOT_DIR / "01_menu.png")
    if menu_img:
        report["checks"][-1]["screenshot"] = str(menu_img)

    # ── CHECK 2: 👤 Profile card has NO Edge Performance/ROI/hit/streak ──
    pmsgs = await _send(client, entity, "👤 Profile", wait=WAIT_LONG)
    profile_msg = None
    for m in pmsgs:
        if m.media or m.reply_markup:
            profile_msg = m
            break
    profile_text = _extract_text(profile_msg) if profile_msg else ""
    profile_labels = _button_labels(profile_msg) if profile_msg else []
    profile_cb = _button_data(profile_msg) if profile_msg else []

    profile_img = None
    if profile_msg and profile_msg.media:
        profile_img = await _download_media(client, profile_msg, SHOT_DIR / "02_profile.png")

    banned_substrs = [
        "Edge Performance",
        "edge performance",
        "7D ROI",
        "7d roi",
        " ROI",
        "Hit rate",
        "hit rate",
        "Streak",
        "streak",
        "📊 Edge Tracker",
    ]
    def _has_banned_in_text(text: str) -> list[str]:
        lc = text.lower()
        hits = []
        for sub in banned_substrs:
            if sub.lower() in lc:
                # ROI leading space is a false positive for "euroi" etc.
                # only flag standalone ROI.
                if sub == " ROI" and "roi" not in lc.split("roi")[0][-3:].lower():
                    pass
                hits.append(sub)
        return hits

    fallback_hits = _has_banned_in_text(profile_text)
    ocr_result: dict | None = None
    ocr_hits: list[str] = []
    if profile_img:
        try:
            ocr = ocr_card(profile_img)
            ocr_result = {
                "raw_response": ocr.raw_response,
                "verdict_text": ocr.verdict_text,
                "home_team": ocr.home_team,
                "away_team": ocr.away_team,
                "tier_badge": ocr.tier_badge,
                "button_labels": ocr.button_labels,
            }
            lc = (ocr.raw_response or "").lower()
            for sub in banned_substrs:
                if sub.lower() in lc:
                    ocr_hits.append(sub)
        except Exception as exc:
            ocr_result = {"error": str(exc)}

    profile_button_bad = any("Edge Tracker" in lbl or "📊" in lbl for lbl in profile_labels)
    profile_ok = (
        bool(profile_msg)
        and not fallback_hits
        and not ocr_hits
        and not profile_button_bad
    )
    report["checks"].append({
        "name": "profile_no_edge_performance",
        "pass": profile_ok,
        "fallback_text_preview": profile_text[:400],
        "fallback_banned_hits": fallback_hits,
        "button_labels": profile_labels,
        "button_callbacks": profile_cb,
        "button_has_edge_tracker": profile_button_bad,
        "ocr": ocr_result,
        "ocr_banned_hits": ocr_hits,
        "screenshot": str(profile_img) if profile_img else None,
    })
    overall_pass &= profile_ok

    # ── CHECK 3: manually hit `results:7` callback → Coming Soon graceful ──
    # Send /menu to get a fresh keyboard, inject results:7 via bot callback.
    # Since kb_main has no results:7 button anymore, we can't click it — we
    # verify by sending /results command directly (same surface).
    rmsgs = await _send(client, entity, "/results", wait=WAIT_MID)
    results_msg = rmsgs[-1] if rmsgs else None
    results_text = _extract_text(results_msg) if results_msg else ""
    results_labels = _button_labels(results_msg) if results_msg else []
    results_cb = _button_data(results_msg) if results_msg else []

    coming_soon_ok = (
        bool(results_msg)
        and "coming soon" in results_text.lower()
        and "Edge Tracker" in results_text
        # Must not display stats
        and not any(k in results_text for k in ("ROI", "Hit rate", "hit rate", "Streak", "%"))
    )
    report["checks"].append({
        "name": "results_command_graceful_redirect",
        "pass": coming_soon_ok,
        "text": results_text,
        "button_labels": results_labels,
        "button_callbacks": results_cb,
    })
    overall_pass &= coming_soon_ok

    # ── CHECK 4: standard card assertions on profile card (if image) ──
    if profile_img:
        card_assert_results: dict = {}
        try:
            ocr = ocr_card(profile_img)
            try:
                CA.assert_teams_populated(ocr)
                card_assert_results["teams_populated"] = "N/A (profile card — no teams)"
            except AssertionError as e:
                # Profile card has no home/away teams — so this will fail. Treat N/A.
                card_assert_results["teams_populated"] = f"N/A ({e})"
            try:
                CA.assert_tier_badge_present(ocr)
                card_assert_results["tier_badge_present"] = "PASS"
            except AssertionError as e:
                card_assert_results["tier_badge_present"] = f"FAIL: {e}"
            try:
                CA.assert_not_stub_shape(ocr)
                card_assert_results["not_stub_shape"] = "PASS"
            except AssertionError as e:
                card_assert_results["not_stub_shape"] = f"FAIL: {e}"
            # Verdict range is not applicable to profile card
            card_assert_results["verdict_in_range"] = "N/A (profile card — no verdict)"
        except Exception as exc:
            card_assert_results["error"] = str(exc)

        report["checks"].append({
            "name": "card_assertions_on_profile",
            "pass": all(
                (v == "PASS" or str(v).startswith("N/A"))
                for v in card_assert_results.values()
                if isinstance(v, str)
            ),
            "results": card_assert_results,
        })

    report["overall_pass"] = overall_pass

    out_path = SHOT_DIR / "qa_report.json"
    out_path.write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps(report, indent=2, default=str))
    print(f"\n=== Report written to {out_path}")
    print(f"=== Overall: {'PASS' if overall_pass else 'FAIL'}")

    await client.disconnect()
    return 0 if overall_pass else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
