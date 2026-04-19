#!/usr/bin/env python3
"""Telethon QA — My Matches edge bugfix (20260419).

Founder fix: My Matches button → always opens match_detail card (NOT edge card).
Edge access routed via the "View Edge" button which serves edge_detail with
back_cb_override → returns to match_detail.

Scenarios:
  S1 — Non-edge match tap (Diamond tier): match_detail card, no tier badge,
       no View Edge button.
  S2 — Edge match tap, accessible (Diamond tier): match_detail card with tier
       badge AND a "View <Tier> Edge" button.
  S3 — View Edge tap on accessible edge: edge_detail card served, Back button
       callback starts with "mm:match:" (not "hot:back:").
  S4 — Edge match tap, locked (Bronze tier): match_detail card with tier badge
       + 🔒 View <Tier> Edge locked button.
  S5 — View Edge tap on locked edge: upgrade prompt text, NOT edge card.

Saves evidence to /home/paulsportsza/tests/evidence/mm_edge_bugfix_20260419/:
  - S<N>_<desc>_image.jpg   (image if present)
  - S<N>_<desc>_buttons.txt (reply markup rows)
  - S<N>_<desc>_text.txt    (message text / caption)
  - S<N>_<desc>_meta.json   (metadata: msg_id, has_photo, verdict)
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from datetime import datetime

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env"))

from telethon import TelegramClient
from telethon.sessions import StringSession

API_ID = int(os.getenv("TELEGRAM_API_ID", "32418601"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "95e313a8ef5b998be0515dd8328fac57")
BOT_USERNAME = "@mzansiedge_bot"
STRING_SESSION_FILE = "/home/paulsportsza/bot/data/telethon_session.string"
EVIDENCE_DIR = "/home/paulsportsza/tests/evidence/mm_edge_bugfix_20260419"

WAIT_LONG = 25.0   # for matches loading / rendering
WAIT_MID = 12.0    # for simpler taps

os.makedirs(EVIDENCE_DIR, exist_ok=True)

results: dict = {}


def _session() -> StringSession:
    with open(STRING_SESSION_FILE) as f:
        s = f.read().strip()
    if not s:
        raise RuntimeError(f"Empty session: {STRING_SESSION_FILE}")
    return StringSession(s)


def _btn_rows(msg) -> list[list[dict]]:
    if not msg or not msg.reply_markup or not hasattr(msg.reply_markup, "rows"):
        return []
    out = []
    for row in msg.reply_markup.rows:
        row_list = []
        for btn in row.buttons:
            d = getattr(btn, "data", None)
            if isinstance(d, bytes):
                d = d.decode("utf-8", errors="replace")
            row_list.append({"text": btn.text, "data": d})
        out.append(row_list)
    return out


def _find_btn(msg, *, text_substr: str | None = None, data_substr: str | None = None):
    """Return (row_idx, col_idx, btn, data_str) or None."""
    if not msg or not msg.reply_markup or not hasattr(msg.reply_markup, "rows"):
        return None
    for r, row in enumerate(msg.reply_markup.rows):
        for c, btn in enumerate(row.buttons):
            d = getattr(btn, "data", b"") or b""
            if isinstance(d, bytes):
                d = d.decode("utf-8", errors="replace")
            if text_substr and text_substr.lower() in (btn.text or "").lower():
                return (r, c, btn, d)
            if data_substr and data_substr in d:
                return (r, c, btn, d)
    return None


async def _wait_new(client, entity, after_id: int, timeout: float, me_id: int):
    """Wait for a new message from the bot after `after_id`."""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        await asyncio.sleep(0.8)
        msgs = await client.get_messages(entity, limit=10)
        for m in msgs:
            if m.id > after_id and m.sender_id != me_id:
                last = m
                # prefer final message (one with buttons or a photo)
                if m.reply_markup or m.photo or m.media:
                    return m
        if last:
            # wait a touch more for markup to attach
            continue
    return last


async def _click_and_wait(client, entity, msg, *, text_substr=None, data_substr=None, timeout: float = WAIT_LONG, me_id: int):
    """Click a button and wait for EITHER message edit OR new message."""
    btn_info = _find_btn(msg, text_substr=text_substr, data_substr=data_substr)
    if btn_info is None:
        return None, None
    r, c, _btn, data = btn_info
    orig_text = msg.text or msg.message or ""
    orig_id = msg.id
    t0 = time.time()
    await msg.click(r, c)
    deadline = time.time() + timeout
    last_edit = None
    while time.time() < deadline:
        await asyncio.sleep(0.7)
        # Check edit-in-place
        try:
            m_edit = await client.get_messages(entity, ids=orig_id)
            if m_edit and ((m_edit.text or m_edit.message or "") != orig_text or m_edit.photo):
                last_edit = m_edit
        except Exception:
            pass
        # Also check for new messages after orig_id
        msgs = await client.get_messages(entity, limit=8)
        new_msgs = [m for m in msgs if m.id > orig_id and m.sender_id != me_id]
        if new_msgs:
            # return the newest one with buttons/photo if any, else just newest
            for nm in sorted(new_msgs, key=lambda x: x.id):
                if nm.reply_markup or nm.photo or nm.media:
                    return nm, data
            return new_msgs[-1], data
        if last_edit and (last_edit.reply_markup or last_edit.photo):
            return last_edit, data
    return last_edit, data


def _save_evidence(prefix: str, msg, verdict: str, notes: str = ""):
    """Save image, buttons, text, meta for a message."""
    paths = {}

    # Save image if present
    if msg and (msg.photo or (msg.media and hasattr(msg.media, "photo") and msg.media.photo)):
        try:
            img_path = os.path.join(EVIDENCE_DIR, f"{prefix}_image.jpg")
            # This is async-safe since called inside async context
            paths["_img_path"] = img_path  # caller will download
        except Exception:
            pass

    # Save text
    txt = (msg.text or msg.message or "") if msg else ""
    with open(os.path.join(EVIDENCE_DIR, f"{prefix}_text.txt"), "w") as f:
        f.write(txt)

    # Save buttons
    rows = _btn_rows(msg) if msg else []
    with open(os.path.join(EVIDENCE_DIR, f"{prefix}_buttons.txt"), "w") as f:
        for i, row in enumerate(rows):
            for j, b in enumerate(row):
                f.write(f"[{i}][{j}] text={b['text']!r} data={b['data']!r}\n")

    # Save meta
    meta = {
        "prefix": prefix,
        "verdict": verdict,
        "notes": notes,
        "msg_id": msg.id if msg else None,
        "has_photo": bool(msg and msg.photo) if msg else False,
        "text_len": len(txt),
        "text_preview": txt[:240],
        "button_rows": rows,
        "timestamp": datetime.now().isoformat(),
    }
    with open(os.path.join(EVIDENCE_DIR, f"{prefix}_meta.json"), "w") as f:
        json.dump(meta, f, indent=2)
    return paths


async def _dl_image(msg, path: str):
    try:
        await msg.download_media(file=path)
        return True
    except Exception as e:
        with open(path + ".error", "w") as f:
            f.write(str(e))
        return False


def _check(name: str, cond: bool, detail: str = ""):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {name}  {detail}")
    results[name] = {"pass": cond, "detail": detail}
    return cond


def _has_mme_button(msg) -> tuple[bool, str]:
    """Return (present, button_text)."""
    for row in (_btn_rows(msg) or []):
        for b in row:
            d = b.get("data") or ""
            if d.startswith("mme:"):
                return True, b.get("text") or ""
    return False, ""


def _mm_back_button_present(msg) -> bool:
    """Check md:back or mm:match:... callback is present."""
    for row in (_btn_rows(msg) or []):
        for b in row:
            d = b.get("data") or ""
            if d.startswith("md:back") or d.startswith("mm:match:"):
                return True
    return False


def _edge_back_goes_to_mm(msg) -> tuple[bool, str]:
    """Check that the Back button on the edge card goes to mm:match: (not hot:back:)."""
    back_cbs = []
    for row in (_btn_rows(msg) or []):
        for b in row:
            d = b.get("data") or ""
            txt = (b.get("text") or "").lower()
            if ("back" in txt or "↩" in txt) and d:
                back_cbs.append(d)
    if not back_cbs:
        return False, "no back button found"
    for cb in back_cbs:
        if cb.startswith("mm:match:"):
            return True, f"found mm:match: back → {cb}"
    return False, f"back callbacks: {back_cbs}"


async def _send(client, entity, text: str, me_id: int, wait: float = WAIT_LONG):
    sent = await client.send_message(entity, text)
    return await _wait_new(client, entity, sent.id, wait, me_id)


async def _open_my_matches(client, entity, me_id: int):
    """Send My Matches prompt, wait for rendered list message with mm:match: buttons."""
    sent = await client.send_message(entity, "⚽ My Matches")
    t0 = time.time()
    deadline = t0 + WAIT_LONG + 10
    final = None
    while time.time() < deadline:
        await asyncio.sleep(1.0)
        msgs = await client.get_messages(entity, limit=10)
        for m in msgs:
            if m.id <= sent.id:
                continue
            if m.sender_id == me_id:
                continue
            rows = _btn_rows(m)
            # A My Matches rendered message should have buttons where some callback contains "mm:match:"
            flat = []
            for r in rows:
                flat.extend(r)
            has_mm = any((b.get("data") or "").startswith("mm:match:") for b in flat)
            if has_mm:
                return m
            final = m
    return final


def _find_mm_match_buttons(msg) -> list[tuple[int, int, str, str]]:
    """Return list of (row, col, btn_text, callback_data) for each mm:match: button."""
    out = []
    rows = _btn_rows(msg)
    for r, row in enumerate(rows):
        for c, b in enumerate(row):
            d = b.get("data") or ""
            if d.startswith("mm:match:"):
                out.append((r, c, b.get("text") or "", d))
    return out


async def _tap_mm_match(client, entity, list_msg, card_n: int, me_id: int):
    """Tap the mm:match:{card_n}:n button on the list and wait for the match_detail card."""
    # Find button with data prefix mm:match:{card_n}:
    target_prefix = f"mm:match:{card_n}:"
    btn_info = _find_btn(list_msg, data_substr=target_prefix)
    if btn_info is None:
        return None, None
    r, c, _btn, data = btn_info
    orig_id = list_msg.id
    await list_msg.click(r, c)
    deadline = time.time() + WAIT_LONG
    while time.time() < deadline:
        await asyncio.sleep(1.0)
        msgs = await client.get_messages(entity, limit=8)
        for m in msgs:
            if m.id > orig_id and m.sender_id != me_id:
                # A detail card is a photo with buttons
                if m.photo and m.reply_markup:
                    return m, data
        # check edit
        try:
            m_edit = await client.get_messages(entity, ids=orig_id)
            if m_edit and m_edit.photo and m_edit.reply_markup:
                return m_edit, data
        except Exception:
            pass
    # Fallback — return whatever we see last
    msgs = await client.get_messages(entity, limit=5)
    for m in msgs:
        if m.id > orig_id and m.sender_id != me_id:
            return m, data
    return None, data


def _classify_edge_match(list_msg) -> dict:
    """Inspect list buttons to identify which card number has an edge.

    The card_markup for matches always emits mm:match:{N}:n (post-fix).
    Edge vs non-edge can only be distinguished by opening the card and checking
    for badge or mme button. So we just return card numbers available.
    """
    btns = _find_mm_match_buttons(list_msg)
    nums = sorted({int(d.split(":")[2]) for (_, _, _, d) in btns if d.count(":") >= 3})
    return {"cards": nums, "button_texts": [b for (_, _, b, _) in btns]}


async def _qa_reset(client, entity, me_id: int):
    return await _send(client, entity, "/qa reset", me_id, wait=WAIT_MID)


async def main():
    print("=" * 70)
    print(f"MM Edge Bugfix QA — {datetime.now():%Y-%m-%d %H:%M:%S}")
    print(f"Evidence: {EVIDENCE_DIR}")
    print("=" * 70)

    async with TelegramClient(_session(), API_ID, API_HASH) as client:
        entity = await client.get_entity(BOT_USERNAME)
        me = await client.get_me()
        me_id = me.id
        print(f"Account: {me.first_name} ({me_id})")

        # ── Confirm admin (needed for /qa)
        print("\n— Admin check: /qa set_diamond —")
        r = await _send(client, entity, "/qa set_diamond", me_id, wait=WAIT_MID)
        txt = (r.text or r.message or "") if r else ""
        print(f"  response: {txt[:200]!r}")
        if "unauthorized" in txt.lower() or "not admin" in txt.lower():
            print("  BLOCKER: account not in ADMIN_IDS — /qa rejected.")
            print("  Cannot run tier-switch scenarios. ABORTING.")
            return {"blocker": "not_admin", "response": txt}

        # ═══════════════════════════════════════════════════════════════
        # SCENARIOS S1–S3: DIAMOND TIER (accessible to all edge tiers)
        # ═══════════════════════════════════════════════════════════════

        print("\n— Open My Matches (Diamond tier) —")
        mm_list = await _open_my_matches(client, entity, me_id)
        if mm_list is None:
            print("  BLOCKER: My Matches did not render.")
            return {"blocker": "no_mm_list"}
        class_info = _classify_edge_match(mm_list)
        print(f"  cards found: {class_info['cards']}")
        _save_evidence("S0_mm_list_diamond", mm_list, "INFO", "list view")

        if not class_info["cards"]:
            print("  BLOCKER: no mm:match: buttons on list view.")
            return {"blocker": "no_cards"}

        # Scan each card to find one WITH edge and one WITHOUT.
        # "With edge" => opening returns a card whose markup contains mme: callback.
        # "Without edge" => no mme: callback.
        edge_card_info = None   # (n, detail_msg)
        noedge_card_info = None
        scanned_nums = []

        for n in class_info["cards"]:
            if edge_card_info and noedge_card_info:
                break
            print(f"\n  Probing card {n}…")
            # Re-fetch list to be safe (each tap may edit/delete it)
            mm_list = await _open_my_matches(client, entity, me_id)
            if mm_list is None:
                break
            detail_msg, cb_used = await _tap_mm_match(client, entity, mm_list, n, me_id)
            if detail_msg is None:
                print(f"    card {n}: no detail message returned")
                scanned_nums.append((n, "no_detail"))
                continue
            scanned_nums.append((n, "got_detail"))
            has_mme, mme_text = _has_mme_button(detail_msg)
            is_photo = bool(detail_msg.photo)
            print(f"    card {n}: photo={is_photo} mme={has_mme} text={mme_text!r} cb={cb_used!r}")
            if is_photo and has_mme and edge_card_info is None:
                edge_card_info = (n, detail_msg, mme_text)
            elif is_photo and not has_mme and noedge_card_info is None:
                noedge_card_info = (n, detail_msg, "")

        print(f"\n  Scan results: {scanned_nums}")
        print(f"  edge_card: {edge_card_info[0] if edge_card_info else None}")
        print(f"  noedge_card: {noedge_card_info[0] if noedge_card_info else None}")

        # ── S1: Non-edge match tap (Diamond tier)
        print("\n═══ S1 — Non-edge match (Diamond tier) ═══")
        if noedge_card_info is None:
            print("  SKIP: no non-edge card found in list; possible today.")
            _check("S1 non_edge: match_detail with no tier badge + no View Edge btn",
                   False, "no non-edge card available in today's list")
        else:
            n, dmsg, _ = noedge_card_info
            img_path = os.path.join(EVIDENCE_DIR, f"S1_noedge_card_image.jpg")
            await _dl_image(dmsg, img_path)
            _save_evidence("S1_noedge_card", dmsg, "pending")
            is_photo = bool(dmsg.photo)
            has_mme, _ = _has_mme_button(dmsg)
            has_mm_back = _mm_back_button_present(dmsg)
            _check(
                "S1 card is photo (match_detail)",
                is_photo,
                f"photo={is_photo}",
            )
            _check(
                "S1 NO View Edge (mme:) button (non-edge)",
                not has_mme,
                "mme button present!" if has_mme else "correct — no mme button",
            )
            _check(
                "S1 has My Matches back button (md:back/mm:match:)",
                has_mm_back,
                "",
            )

        # ── S2: Edge match tap, accessible tier (Diamond)
        print("\n═══ S2 — Edge match accessible (Diamond tier) ═══")
        if edge_card_info is None:
            print("  SKIP: no edge card found.")
            _check("S2 edge_accessible: match_detail + tier badge + View Edge btn",
                   False, "no edge card available in today's list")
        else:
            n, dmsg, mme_text = edge_card_info
            img_path = os.path.join(EVIDENCE_DIR, f"S2_edge_card_diamond_image.jpg")
            await _dl_image(dmsg, img_path)
            _save_evidence("S2_edge_card_diamond", dmsg, "pending",
                          notes=f"card #{n}  mme_text={mme_text!r}")
            is_photo = bool(dmsg.photo)
            has_mme, text = _has_mme_button(dmsg)
            has_mm_back = _mm_back_button_present(dmsg)
            # Tier-appropriate: Diamond user sees either 💎/🥇/🥈/🥉 "View <Tier> Edge ↗"
            # (not 🔒). S2 assumes Diamond user.
            is_accessible_button = (
                ("view" in text.lower() and "edge" in text.lower() and "↗" in text)
                or any(e in text for e in ("💎", "🥇", "🥈", "🥉"))
            ) and "🔒" not in text
            _check("S2 card is photo (match_detail)", is_photo, f"photo={is_photo}")
            _check("S2 has View Edge (mme:) button", has_mme, f"text={text!r}")
            _check("S2 button shows tier emoji + ↗ (accessible)",
                   is_accessible_button, f"text={text!r}")
            _check("S2 has My Matches back button", has_mm_back, "")

        # ── S3: Tap View Edge button → edge_detail card with Back → mm:match:
        print("\n═══ S3 — View Edge tap, accessible → edge_detail card ═══")
        if edge_card_info is None:
            _check("S3 edge_card_served_with_mm_back", False, "no edge card")
        else:
            n, dmsg, _ = edge_card_info
            # Re-fetch edge card (may have been modified)
            edge_resp, cb_used = await _click_and_wait(
                client, entity, dmsg,
                data_substr=f"mme:{n}",
                timeout=WAIT_LONG,
                me_id=me_id,
            )
            if edge_resp is None:
                _check("S3 edge card rendered after mme: tap", False, "no response")
            else:
                img_path = os.path.join(EVIDENCE_DIR, f"S3_edge_detail_diamond_image.jpg")
                await _dl_image(edge_resp, img_path)
                _save_evidence("S3_edge_detail_diamond", edge_resp, "pending",
                              notes=f"mme:{n} clicked")
                is_photo = bool(edge_resp.photo)
                back_ok, back_detail = _edge_back_goes_to_mm(edge_resp)
                # Edge card is photo with edge_detail template. We cannot confirm
                # template name from response; signal: has image + back → mm:match:
                _check("S3 edge card rendered as photo", is_photo, f"photo={is_photo}")
                _check("S3 Back button → mm:match: (not hot:back:)",
                       back_ok, back_detail)

        # ═══════════════════════════════════════════════════════════════
        # SCENARIOS S4–S5: BRONZE TIER (locked on Gold+/Diamond edges)
        # ═══════════════════════════════════════════════════════════════
        print("\n— Switching to Bronze tier —")
        r = await _send(client, entity, "/qa set_bronze", me_id, wait=WAIT_MID)
        print(f"  set_bronze: {(r.text or '')[:150]!r}")

        print("\n— Open My Matches (Bronze tier) —")
        mm_list_br = await _open_my_matches(client, entity, me_id)
        if mm_list_br is None:
            _check("S4/S5 my_matches rendered on Bronze", False, "no list")
            await _qa_reset(client, entity, me_id)
            return {"results": results}
        _save_evidence("S0_mm_list_bronze", mm_list_br, "INFO", "list view bronze")

        # Find an edge card on Bronze — the LOCKED icon may be visible inline on the list
        # but the fix is at the match_detail level. We scan cards the same way.
        class_info_br = _classify_edge_match(mm_list_br)
        edge_card_br = None
        locked_card_br = None
        for n in class_info_br["cards"]:
            if locked_card_br is not None:
                break
            mm_list_br = await _open_my_matches(client, entity, me_id)
            if mm_list_br is None:
                break
            detail_msg, cb_used = await _tap_mm_match(client, entity, mm_list_br, n, me_id)
            if detail_msg is None or not detail_msg.photo:
                continue
            has_mme, mme_text = _has_mme_button(detail_msg)
            if has_mme and "🔒" in mme_text:
                locked_card_br = (n, detail_msg, mme_text)
                break
            if has_mme and edge_card_br is None:
                edge_card_br = (n, detail_msg, mme_text)

        print("\n═══ S4 — Edge match, locked (Bronze tier) ═══")
        target_card = locked_card_br or edge_card_br
        if target_card is None:
            _check(
                "S4 locked_view_edge_button present on bronze",
                False,
                "no edge-bearing card found on bronze (may be all-Silver/Bronze in today's list)",
            )
        else:
            n, dmsg, text = target_card
            img_path = os.path.join(EVIDENCE_DIR, f"S4_edge_card_bronze_image.jpg")
            await _dl_image(dmsg, img_path)
            _save_evidence("S4_edge_card_bronze", dmsg, "pending",
                          notes=f"card #{n}  mme_text={text!r}")
            is_photo = bool(dmsg.photo)
            has_mme, _txt = _has_mme_button(dmsg)
            has_lock = "🔒" in text
            _check("S4 card is photo (match_detail)", is_photo, f"photo={is_photo}")
            _check("S4 has View Edge (mme:) button", has_mme, f"text={text!r}")
            _check(
                "S4 button shows 🔒 lock (tier-gated)",
                has_lock,
                f"text={text!r}" if not has_lock else "locked icon present",
            )

        print("\n═══ S5 — View Edge tap, locked → upgrade prompt ═══")
        if target_card is None or not locked_card_br:
            _check(
                "S5 upgrade prompt served on locked View Edge",
                False,
                "no locked card available to test",
            )
        else:
            n, dmsg, _ = locked_card_br
            up_resp, cb_used = await _click_and_wait(
                client, entity, dmsg,
                data_substr=f"mme:{n}",
                timeout=WAIT_LONG,
                me_id=me_id,
            )
            if up_resp is None:
                _check("S5 upgrade prompt rendered", False, "no response")
            else:
                _save_evidence("S5_upgrade_prompt_bronze", up_resp, "pending",
                              notes=f"mme:{n} clicked on locked")
                txt = (up_resp.text or up_resp.message or "") or ""
                txt_l = txt.lower()
                has_locked_text = ("locked" in txt_l) or ("🔒" in txt)
                has_upgrade = ("upgrade" in txt_l) or ("view plans" in txt_l)
                has_view_plans_btn = False
                has_back_btn = False
                for row in _btn_rows(up_resp):
                    for b in row:
                        bt = (b.get("text") or "").lower()
                        d = b.get("data") or ""
                        if "view plans" in bt or d.startswith("sub:plans"):
                            has_view_plans_btn = True
                        if "back" in bt and d.startswith("mm:match:"):
                            has_back_btn = True
                is_not_edge_card = not bool(up_resp.photo)
                _check("S5 response is text (not edge photo)", is_not_edge_card,
                       f"photo={bool(up_resp.photo)}")
                _check("S5 text contains 'locked' + upgrade cue",
                       has_locked_text and has_upgrade,
                       f"locked_text={has_locked_text} upgrade={has_upgrade} preview={txt[:120]!r}")
                _check("S5 has View Plans button", has_view_plans_btn, "")
                _check("S5 has Back → mm:match: button", has_back_btn, "")

        # ── Always reset QA overrides
        print("\n— /qa reset —")
        r = await _send(client, entity, "/qa reset", me_id, wait=WAIT_MID)
        print(f"  reset: {(r.text or '')[:150]!r}")

        # Summary
        print("\n" + "=" * 70)
        passed = sum(1 for v in results.values() if v["pass"])
        total = len(results)
        print(f"  Results: {passed}/{total} checks passed")
        for name, v in results.items():
            print(f"    {'PASS' if v['pass'] else 'FAIL'} — {name}")
            if v["detail"]:
                print(f"         {v['detail']}")
        print("=" * 70)

        # Save final summary
        summary_path = os.path.join(EVIDENCE_DIR, "SUMMARY.json")
        with open(summary_path, "w") as f:
            json.dump({
                "timestamp": datetime.now().isoformat(),
                "passed": passed,
                "total": total,
                "results": results,
            }, f, indent=2)
        print(f"\nSummary: {summary_path}")
        return {"passed": passed, "total": total, "results": results}


if __name__ == "__main__":
    try:
        out = asyncio.run(main())
        sys.exit(0 if (isinstance(out, dict) and out.get("passed", 0) == out.get("total", 1)) else 1)
    except Exception as e:
        print(f"FATAL: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(2)
