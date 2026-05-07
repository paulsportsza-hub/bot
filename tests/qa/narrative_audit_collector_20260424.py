#!/usr/bin/env python3
"""Sub-agent A — Live Card Collector for INV-NARRATIVE-AUDIT-PRE-LAUNCH-01.

Captures user-reachable narrative surfaces (Hot Tips Edge card + AI Breakdown)
for a stratified sample of 15 cards via Telethon + Claude Vision OCR.

Pure collection — no scoring, no opinions.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv("/home/paulsportsza/bot/.env")

from telethon import TelegramClient  # noqa: E402
from telethon.sessions import StringSession  # noqa: E402

# OCR
from tests.qa.vision_ocr import ocr_card  # noqa: E402

API_ID = int(os.getenv("TELEGRAM_API_ID", "32418601"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "95e313a8ef5b998be0515dd8328fac57")
BOT_USERNAME = "@mzansiedge_bot"
SESSION_FILE = "/home/paulsportsza/bot/data/telethon_qa_session.string"
EVIDENCE_DIR = Path("/home/paulsportsza/reports/evidence/narrative_audit_20260424")
SAMPLE_FILE = Path("/tmp/strat_sample.json")

WAIT_LIST = 25.0
WAIT_CARD = 20.0
WAIT_BREAKDOWN = 35.0


def _session() -> StringSession:
    with open(SESSION_FILE) as f:
        s = f.read().strip()
    return StringSession(s)


def _btn_data(btn) -> str:
    d = getattr(btn, "data", None)
    if d is None:
        u = getattr(btn, "url", None)
        return u or ""
    if isinstance(d, bytes):
        return d.decode("utf-8", errors="replace")
    return d or ""


def _btn_rows(msg):
    if not msg or not msg.reply_markup or not hasattr(msg.reply_markup, "rows"):
        return []
    out = []
    for row in msg.reply_markup.rows:
        out.append([{"text": b.text, "data": _btn_data(b)} for b in row.buttons])
    return out


def _find_btn(msg, *, text_substr=None, data_substr=None):
    if not msg or not msg.reply_markup or not hasattr(msg.reply_markup, "rows"):
        return None
    for r, row in enumerate(msg.reply_markup.rows):
        for c, btn in enumerate(row.buttons):
            d = _btn_data(btn)
            if text_substr and text_substr.lower() in (btn.text or "").lower():
                return (r, c, btn, d)
            if data_substr and data_substr in d:
                return (r, c, btn, d)
    return None


async def _wait_new(client, entity, after_id, timeout, me_id, need_photo=False, need_markup=True):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        await asyncio.sleep(0.8)
        msgs = await client.get_messages(entity, limit=10)
        for m in msgs:
            if m.id > after_id and m.sender_id != me_id:
                last = m
                ok_photo = (not need_photo) or bool(m.photo)
                ok_markup = (not need_markup) or bool(m.reply_markup)
                if ok_photo and ok_markup:
                    return m
    return last


_TEAM_TOKEN_MAP = {
    "arsenal_vs_fulham_2026-05-02": ["ARS vs FUL", "Arsenal vs Fulham"],
    "aston_villa_vs_tottenham_2026-05-03": ["AVL vs TOT", "Aston Villa vs Tot", "Aston"],
    "edinburgh_vs_sharks_2026-04-24": ["Edinburgh", "Sharks"],
    "liverpool_vs_crystal_palace_2026-04-25": ["LIV vs CRY", "Liverpool"],
    "orlando_pirates_vs_kaizer_chiefs_2026-04-26": ["Pirates vs Chiefs", "ORL", "Pirates"],
    "zebre_vs_dragons_2026-04-24": ["Zebre vs Dragons", "Zebre"],
    "bournemouth_vs_crystal_palace_2026-05-03": ["BOU vs CRY", "Bournemouth"],
    "cardiff_vs_ospreys_2026-04-24": ["Cardiff", "Ospreys"],
    "delhi_capitals_vs_punjab_kings_2026-04-25": ["Delhi", "Punjab"],
    "lucknow_super_giants_vs_kolkata_knight_riders_2026-04-26": ["Lucknow", "Kolkata"],
    "manchester_united_vs_liverpool_2026-05-03": ["MUN vs LIV", "Man United"],
    "al_ahli_saudi_fc_vs_machida_zelvia_2026-04-25": ["Al Ahli", "Machida"],
    "bangladesh_vs_new_zealand_2026-04-27": ["BAN vs NZ", "Bangladesh"],
    "arsenal_wfc_vs_olympique_lyon_2026-04-26": ["Arsenal WFC", "Lyon"],
    "bangladesh_vs_sri_lanka_2026-04-25": ["Bangladesh", "Sri Lanka"],
}


async def _get_latest_list(client, entity, me_id):
    """Return the most recent bot message that has ep:pick: buttons."""
    msgs = await client.get_messages(entity, limit=15)
    for m in msgs:
        if m.sender_id == me_id:
            continue
        rows = _btn_rows(m)
        for row in rows:
            for b in row:
                if (b.get("data") or "").startswith("ep:pick:"):
                    return m
    return None


async def _find_card_in_list(client, entity, list_msg, match_id, me_id):
    """Iterate pages looking for a pick button whose text matches one of the
    tokens for this match_id. Tap ep:pick:N and wait for edge card.
    Uses latest-message lookup because bot sends new messages on pagination.
    """
    tokens = _TEAM_TOKEN_MAP.get(match_id, [match_id.split("_vs_")[0].replace("_", " ")[:10]])
    current = list_msg
    for page_try in range(5):
        if current is None:
            break
        rows = _btn_rows(current)
        btn_info = None
        for r_idx, row in enumerate(rows):
            for c_idx, b in enumerate(row):
                t = (b.get("text") or "").lower()
                d = b.get("data") or ""
                if not d.startswith("ep:pick:"):
                    continue
                for tok in tokens:
                    if tok.lower() in t:
                        btn_info = (r_idx, c_idx, d)
                        break
                if btn_info:
                    break
            if btn_info:
                break
        if btn_info:
            r_, c_, data = btn_info
            orig_id = current.id
            try:
                await current.click(r_, c_)
            except Exception as e:
                return None, f"click err: {e}"
            deadline = time.time() + WAIT_CARD
            while time.time() < deadline:
                await asyncio.sleep(0.8)
                msgs = await client.get_messages(entity, limit=8)
                new_msgs = [m for m in msgs if m.id > orig_id and m.sender_id != me_id]
                if new_msgs:
                    nm = new_msgs[-1]
                    if nm.photo or nm.media or (nm.text and "📋" in (nm.text or "")):
                        return nm, data
                try:
                    m_edit = await client.get_messages(entity, ids=orig_id)
                    if m_edit and (m_edit.photo or "📋" in (m_edit.text or "")):
                        return m_edit, data
                except Exception:
                    pass
            return None, "card timeout after tap"
        # Try to paginate: click Next → on CURRENT latest list message
        latest = await _get_latest_list(client, entity, me_id)
        if latest is None:
            break
        nxt = _find_btn(latest, data_substr="hot:page:")
        if nxt is None:
            break
        r_, c_, _b, _d = nxt
        try:
            await latest.click(r_, c_)
        except Exception:
            break
        await asyncio.sleep(3.0)
        current = await _get_latest_list(client, entity, me_id)
    return None, f"match not found in pages (tokens={tokens!r})"


async def _navigate_to_edge_picks(client, entity, me_id):
    """Send Edge Picks button text, wait for list with edge:detail: callbacks."""
    sent = await client.send_message(entity, "💎 Top Edge Picks")
    deadline = time.time() + WAIT_LIST
    while time.time() < deadline:
        await asyncio.sleep(1.0)
        msgs = await client.get_messages(entity, limit=10)
        for m in msgs:
            if m.id <= sent.id or m.sender_id == me_id:
                continue
            rows = _btn_rows(m)
            flat = [b for r in rows for b in r]
            if any((b.get("data") or "").startswith("ep:pick:") for b in flat):
                return m
    return None


async def _save_screenshot(msg, png_path: Path):
    """Download image, or render text into an image if no photo."""
    if msg.photo or msg.media:
        try:
            await msg.download_media(file=str(png_path))
            if png_path.exists() and png_path.stat().st_size > 0:
                return True, True  # (saved, has_photo)
        except Exception as e:
            with open(str(png_path) + ".error", "w") as f:
                f.write(str(e))
    # No photo -- save text as .txt alongside, write a tiny PNG with text summary
    txt = msg.text or msg.message or ""
    txt_path = png_path.with_suffix(".txt")
    with open(txt_path, "w") as f:
        f.write(txt)
    # Render plain-text screenshot using Pillow if available
    try:
        from PIL import Image, ImageDraw, ImageFont  # type: ignore
        img = Image.new("RGB", (900, 1400), "white")
        d = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
        except Exception:
            font = ImageFont.load_default()
        # wrap
        lines = []
        for para in (txt or "").split("\n"):
            while len(para) > 95:
                lines.append(para[:95])
                para = para[95:]
            lines.append(para)
        y = 10
        for ln in lines[:80]:
            d.text((10, y), ln, fill="black", font=font)
            y += 17
        img.save(png_path)
        return True, False
    except Exception:
        return False, False


async def main():
    sample = json.loads(SAMPLE_FILE.read_text())
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

    manifest_entries = []
    ocr_divergences = []

    print(f"== Collector start {datetime.now().isoformat()} — {len(sample)} cards ==")
    async with TelegramClient(_session(), API_ID, API_HASH) as client:
        entity = await client.get_entity(BOT_USERNAME)
        me = await client.get_me()
        me_id = me.id
        print(f"Account: {me.first_name} ({me_id})")

        # Set Diamond tier (test account) so all cards accessible
        r = await client.send_message(entity, "/qa set_diamond")
        await asyncio.sleep(2.0)
        # /start to reset state
        await client.send_message(entity, "/start")
        await asyncio.sleep(2.0)

        for idx, row in enumerate(sample):
            match_id = row["match_id"]
            tier = row["tier"]
            source = row["narrative_source"]
            db_narr = row["narrative_html"]
            db_verdict = row["verdict_html"]
            print(f"\n[{idx+1}/{len(sample)}] {tier:8s} {source:18s} {match_id}")

            # Each match: fresh navigation
            try:
                list_msg = await _navigate_to_edge_picks(client, entity, me_id)
                if list_msg is None:
                    e = {
                        "match_id": match_id, "surface": "edge", "tier": tier,
                        "narrative_source": source, "status": "error",
                        "error": "edge picks list did not render",
                        "captured_at": datetime.now().isoformat(),
                        "db_narrative_html": db_narr[:500], "db_verdict_html": db_verdict[:500],
                    }
                    manifest_entries.append(e)
                    continue
            except Exception as exc:
                manifest_entries.append({
                    "match_id": match_id, "surface": "edge", "tier": tier,
                    "narrative_source": source, "status": "error",
                    "error": f"navigate: {exc}",
                    "captured_at": datetime.now().isoformat(),
                    "db_narrative_html": db_narr[:500], "db_verdict_html": db_verdict[:500],
                })
                continue

            try:
                card_msg, card_cb = await _find_card_in_list(client, entity, list_msg, match_id, me_id)
            except Exception as _fc_err:
                card_msg, card_cb = None, f"helper err: {_fc_err}"

            # --- Edge card capture ---
            edge_png = EVIDENCE_DIR / f"card_{match_id}_edge.png"
            edge_ocr_path = EVIDENCE_DIR / f"card_{match_id}_edge.ocr.json"
            if card_msg is None:
                manifest_entries.append({
                    "match_id": match_id, "surface": "edge", "tier": tier,
                    "narrative_source": source, "status": "error",
                    "error": "card button not found or card not rendered",
                    "captured_at": datetime.now().isoformat(),
                    "png_path": "", "ocr_path": "",
                    "db_narrative_html": db_narr[:500], "db_verdict_html": db_verdict[:500],
                })
                continue

            saved, has_photo = await _save_screenshot(card_msg, edge_png)
            ocr_status = "skipped"
            ocr_err = None
            try:
                if saved:
                    ocr = ocr_card(edge_png)
                    ocr_json = {
                        "raw_text": ocr.raw_response,
                        "verdict_text": ocr.verdict_text,
                        "setup_text": "",
                        "edge_text": "",
                        "risk_text": "",
                        "home_team": ocr.home_team,
                        "away_team": ocr.away_team,
                        "tier_badge": ocr.tier_badge or "",
                        "button_labels": ocr.button_labels,
                    }
                    edge_ocr_path.write_text(json.dumps(ocr_json, indent=2))
                    ocr_status = "ok"
                    # simple divergence: verdict text OCR vs db_verdict stripped
                    if ocr.verdict_text and db_verdict:
                        import re as _re
                        db_v_plain = _re.sub(r"<[^>]+>", "", db_verdict).strip()
                        if db_v_plain and ocr.verdict_text.strip() and db_v_plain[:40].lower() not in ocr.verdict_text.lower() and ocr.verdict_text[:40].lower() not in db_v_plain.lower():
                            ocr_divergences.append(f"{match_id} edge: ocr_verdict={ocr.verdict_text[:80]!r} db_verdict={db_v_plain[:80]!r}")
            except Exception as e:
                ocr_err = str(e)
                ocr_status = f"ocr_error: {e}"[:200]

            manifest_entries.append({
                "match_id": match_id, "surface": "edge", "tier": tier,
                "narrative_source": source,
                "png_path": str(edge_png) if saved else "",
                "ocr_path": str(edge_ocr_path) if ocr_status == "ok" else "",
                "has_photo": has_photo,
                "captured_at": datetime.now().isoformat(),
                "status": "ok" if saved and ocr_status == "ok" else ("partial" if saved else "error"),
                "error": ocr_err,
                "db_narrative_html": db_narr[:500], "db_verdict_html": db_verdict[:500],
            })

            # --- AI Breakdown: tap "📊 AI Breakdown" button ---
            brk_png = EVIDENCE_DIR / f"card_{match_id}_breakdown.png"
            brk_ocr_path = EVIDENCE_DIR / f"card_{match_id}_breakdown.ocr.json"
            bb = _find_btn(card_msg, text_substr="AI Breakdown") or _find_btn(card_msg, text_substr="Breakdown")
            if bb is None:
                # Try match_detail → breakdown indirection ("View" button, callback mme: or md:breakdown)
                bb = _find_btn(card_msg, data_substr="mme:") or _find_btn(card_msg, data_substr="breakdown")
            if bb is None:
                manifest_entries.append({
                    "match_id": match_id, "surface": "breakdown", "tier": tier,
                    "narrative_source": source, "status": "error",
                    "error": "no AI Breakdown button found",
                    "captured_at": datetime.now().isoformat(),
                    "png_path": "", "ocr_path": "",
                    "db_narrative_html": db_narr[:500], "db_verdict_html": db_verdict[:500],
                })
                continue
            r_, c_, _b, bb_data = bb
            prev_id = card_msg.id
            try:
                await card_msg.click(r_, c_)
            except Exception as e:
                manifest_entries.append({
                    "match_id": match_id, "surface": "breakdown", "tier": tier,
                    "narrative_source": source, "status": "error",
                    "error": f"click: {e}",
                    "captured_at": datetime.now().isoformat(),
                    "png_path": "", "ocr_path": "",
                    "db_narrative_html": db_narr[:500], "db_verdict_html": db_verdict[:500],
                })
                continue
            brk_msg = await _wait_new(client, entity, prev_id, WAIT_BREAKDOWN, me_id, need_photo=False, need_markup=False)
            # Also check edit of prev
            if brk_msg is None:
                try:
                    m_edit = await client.get_messages(entity, ids=prev_id)
                    if m_edit:
                        brk_msg = m_edit
                except Exception:
                    pass
            if brk_msg is None:
                manifest_entries.append({
                    "match_id": match_id, "surface": "breakdown", "tier": tier,
                    "narrative_source": source, "status": "timeout",
                    "error": "breakdown did not render",
                    "captured_at": datetime.now().isoformat(),
                    "png_path": "", "ocr_path": "",
                    "db_narrative_html": db_narr[:500], "db_verdict_html": db_verdict[:500],
                })
                continue
            saved2, has_photo2 = await _save_screenshot(brk_msg, brk_png)
            ocr_status2 = "skipped"
            ocr_err2 = None
            try:
                if saved2:
                    ocr2 = ocr_card(brk_png)
                    ocr2_json = {
                        "raw_text": ocr2.raw_response,
                        "verdict_text": ocr2.verdict_text,
                        "setup_text": "",
                        "edge_text": "",
                        "risk_text": "",
                        "home_team": ocr2.home_team,
                        "away_team": ocr2.away_team,
                        "tier_badge": ocr2.tier_badge or "",
                        "button_labels": ocr2.button_labels,
                    }
                    brk_ocr_path.write_text(json.dumps(ocr2_json, indent=2))
                    ocr_status2 = "ok"
                    if ocr2.verdict_text and db_verdict:
                        import re as _re
                        db_v_plain = _re.sub(r"<[^>]+>", "", db_verdict).strip()
                        if db_v_plain and ocr2.verdict_text.strip() and db_v_plain[:40].lower() not in ocr2.verdict_text.lower() and ocr2.verdict_text[:40].lower() not in db_v_plain.lower():
                            ocr_divergences.append(f"{match_id} breakdown: ocr_verdict={ocr2.verdict_text[:80]!r} db_verdict={db_v_plain[:80]!r}")
            except Exception as e:
                ocr_err2 = str(e)
                ocr_status2 = f"ocr_error: {e}"[:200]

            manifest_entries.append({
                "match_id": match_id, "surface": "breakdown", "tier": tier,
                "narrative_source": source,
                "png_path": str(brk_png) if saved2 else "",
                "ocr_path": str(brk_ocr_path) if ocr_status2 == "ok" else "",
                "has_photo": has_photo2,
                "captured_at": datetime.now().isoformat(),
                "status": "ok" if saved2 and ocr_status2 == "ok" else ("partial" if saved2 else "error"),
                "error": ocr_err2,
                "db_narrative_html": db_narr[:500], "db_verdict_html": db_verdict[:500],
            })

    # Write manifest
    manifest_path = EVIDENCE_DIR / "manifest.json"
    manifest_path.write_text(json.dumps({
        "captured_at": datetime.now().isoformat(),
        "entries": manifest_entries,
        "ocr_divergences": ocr_divergences,
    }, indent=2))
    print(f"\nManifest: {manifest_path}")

    # Quick summary
    ok = sum(1 for e in manifest_entries if e.get("status") == "ok")
    part = sum(1 for e in manifest_entries if e.get("status") == "partial")
    err = sum(1 for e in manifest_entries if e.get("status") in ("error", "timeout"))
    edge_ok = sum(1 for e in manifest_entries if e.get("surface") == "edge" and e.get("status") == "ok")
    brk_ok = sum(1 for e in manifest_entries if e.get("surface") == "breakdown" and e.get("status") == "ok")
    print(f"\nSummary: ok={ok} partial={part} err={err} (edge_ok={edge_ok}, brk_ok={brk_ok})")
    return 0


if __name__ == "__main__":
    try:
        rc = asyncio.run(main())
        sys.exit(rc)
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"FATAL: {e}", file=sys.stderr)
        sys.exit(2)
