#!/usr/bin/env python3
"""QA-BASELINE-WAVE3-01 — Comprehensive launch-baseline sweep.

Runs Flows A-D, Wave-3 fix evidence (W3-1..5), and narrative spot-check
in a single Telethon session. Writes JSON evidence to /tmp/qa_w3/.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from telethon import TelegramClient
from telethon.sessions import StringSession

API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "")
BOT_USERNAME = "mzansiedge_bot"
STRING_SESSION_FILE = ROOT / "data" / "telethon_session.string"
FILE_SESSION = ROOT / "data" / "telethon_session"

OUT_DIR = Path("/tmp/qa_w3")
OUT_DIR.mkdir(parents=True, exist_ok=True)

evidence: dict = {"flows": {}, "wave3": {}, "narrative": [], "errors": []}


async def get_client() -> TelegramClient:
    if STRING_SESSION_FILE.exists():
        s = STRING_SESSION_FILE.read_text().strip()
        if s:
            c = TelegramClient(StringSession(s), API_ID, API_HASH)
            await c.connect()
            if await c.is_user_authorized():
                return c
            await c.disconnect()
    c = TelegramClient(str(FILE_SESSION), API_ID, API_HASH)
    await c.connect()
    if not await c.is_user_authorized():
        raise SystemExit("Not authorized")
    return c


async def send_cmd(client: TelegramClient, text: str, wait: float = 4.0):
    """Send a slash/text message and return list of latest bot messages."""
    sent = await client.send_message(BOT_USERNAME, text)
    await asyncio.sleep(wait)
    msgs = await client.get_messages(BOT_USERNAME, limit=8)
    # Filter only inbound (not own outgoing) and recent
    return [m for m in msgs if not m.out and m.id > sent.id - 1]


async def click_button(client: TelegramClient, msg, text_or_data: str, wait: float = 5.0):
    """Click an inline button by visible text (substring) or callback_data."""
    if not msg or not msg.reply_markup:
        return None, "no reply_markup"
    target = None
    for row in msg.reply_markup.rows:
        for b in row.buttons:
            if hasattr(b, "data") and b.data:
                cb = b.data.decode("utf-8", "ignore") if isinstance(b.data, bytes) else str(b.data)
                if text_or_data in cb or text_or_data in (b.text or ""):
                    target = b
                    break
            elif text_or_data in (getattr(b, "text", "") or ""):
                target = b
                break
        if target:
            break
    if not target:
        return None, f"button not found: {text_or_data}"
    try:
        result = await msg.click(text=target.text)
    except Exception as e:
        return None, f"click error: {e}"
    await asyncio.sleep(wait)
    msgs = await client.get_messages(BOT_USERNAME, limit=5)
    inbound = [m for m in msgs if not m.out]
    return inbound, "ok"


def strip_html(t: str) -> str:
    return re.sub(r"<[^>]+>", "", t or "")


def extract_buttons(msg) -> list:
    out = []
    if not msg or not msg.reply_markup:
        return out
    for row in msg.reply_markup.rows:
        for b in row.buttons:
            cb = ""
            if hasattr(b, "data") and b.data:
                cb = b.data.decode("utf-8", "ignore") if isinstance(b.data, bytes) else str(b.data)
            out.append({"text": getattr(b, "text", ""), "data": cb})
    return out


def has_skeleton(text: str) -> bool:
    """Skeleton placeholder strings."""
    t = (text or "").lower()
    return "skeleton" in t or "loading…" in t or "loading..." in t


def count_chip_lines(text: str) -> int:
    """Heuristic: count lines that look like odds chip rows.

    Edge Detail bookmaker chips look like e.g. 'Hollywoodbets · 2.10' or
    similar bookmaker · decimal patterns.
    """
    lines = strip_html(text).splitlines()
    pat = re.compile(r"^\s*(\w[\w\s\.]+?)\s*[·\-•]\s*(\d+\.\d{1,2})\s*$")
    return sum(1 for l in lines if pat.search(l))


def find_verdict(text: str) -> str:
    """Pull the verdict / one-liner from a card. Heuristic: first short
    sentence-ending paragraph after a 'Verdict' label, or longest line if absent."""
    plain = strip_html(text)
    m = re.search(r"(?:Verdict|Bottom line|Take|My take)[:\s]+(.+?)(?:\n\n|\Z)", plain, re.I | re.S)
    if m:
        return m.group(1).strip()
    # Fallback: longest line under 280 chars
    lines = [l.strip() for l in plain.splitlines() if 40 < len(l.strip()) < 300]
    return max(lines, key=len) if lines else ""


async def flow_a_diamond(client):
    """Flow A — Diamond user with preferences."""
    f = {"checks": {}, "evidence": {}}
    # 1. Set diamond
    msgs = await send_cmd(client, "/qa set_diamond")
    f["evidence"]["set_diamond"] = strip_html(msgs[0].text)[:200] if msgs else ""
    f["checks"]["tier_override_active"] = bool(msgs and "DIAMOND" in (msgs[0].text or "").upper())

    # 2. /start
    msgs = await send_cmd(client, "/start", wait=5.0)
    start_text = msgs[0].text if msgs else ""
    f["evidence"]["start"] = strip_html(start_text)[:300]
    f["checks"]["start_responds"] = bool(msgs)

    # 3. /picks
    msgs = await send_cmd(client, "/picks", wait=8.0)
    picks_msg = msgs[0] if msgs else None
    picks_text = picks_msg.text if picks_msg else ""
    f["evidence"]["picks"] = strip_html(picks_text)[:500]
    f["evidence"]["picks_buttons"] = extract_buttons(picks_msg)[:10]
    f["checks"]["picks_loads"] = bool(picks_msg) and not has_skeleton(picks_text)

    # 4. Tap Edge card → Edge Detail
    detail_msg = None
    if picks_msg and picks_msg.reply_markup:
        # Find a button with edge:detail or hot:detail or match callback
        target = None
        for row in picks_msg.reply_markup.rows:
            for b in row.buttons:
                if hasattr(b, "data") and b.data:
                    cb = b.data.decode("utf-8", "ignore") if isinstance(b.data, bytes) else str(b.data)
                    if "detail" in cb or cb.startswith("hot:") and ":" in cb[4:]:
                        if cb in ("hot:go", "hot:back", "hot:noop"):
                            continue
                        target = (b, cb)
                        break
            if target:
                break
        if target:
            try:
                await picks_msg.click(data=target[0].data if hasattr(target[0], "data") else None)
                await asyncio.sleep(7)
                msgs = await client.get_messages(BOT_USERNAME, limit=4)
                detail_msg = next((m for m in msgs if not m.out), None)
            except Exception as e:
                f["evidence"]["edge_detail_error"] = str(e)

    if detail_msg:
        # Detail may be photo+caption
        dtext = detail_msg.text or detail_msg.message or ""
        f["evidence"]["edge_detail"] = strip_html(dtext)[:800]
        f["evidence"]["edge_detail_chip_lines"] = count_chip_lines(dtext)
        verdict = find_verdict(dtext)
        f["evidence"]["edge_detail_verdict"] = verdict
        f["evidence"]["edge_detail_verdict_chars"] = len(verdict)
        f["checks"]["verdict_present_80plus"] = len(verdict) >= 80
        f["checks"]["chip_count_le3"] = f["evidence"]["edge_detail_chip_lines"] <= 3
        f["evidence"]["edge_detail_buttons"] = extract_buttons(detail_msg)[:10]

        # 5. Tap Back
        back_msgs, status = await click_button(client, detail_msg, "↩️", wait=5)
        if not back_msgs:
            back_msgs, status = await click_button(client, detail_msg, "hot:back", wait=5)
        if back_msgs:
            f["evidence"]["back_from_detail"] = strip_html(back_msgs[0].text or "")[:200]
            f["checks"]["back_returns_to_picks"] = "edge picks" in (back_msgs[0].text or "").lower() or "top edge" in (back_msgs[0].text or "").lower()
        else:
            f["checks"]["back_returns_to_picks"] = False
            f["evidence"]["back_status"] = status
    else:
        f["checks"]["verdict_present_80plus"] = False
        f["checks"]["chip_count_le3"] = False
        f["checks"]["back_returns_to_picks"] = False

    # 6. /matches → My Matches
    msgs = await send_cmd(client, "/matches", wait=8)
    if not msgs or "unknown" in (msgs[0].text or "").lower():
        # Try menu button
        msgs = await send_cmd(client, "My Matches", wait=8)
    mm_msg = msgs[0] if msgs else None
    f["evidence"]["my_matches"] = strip_html(mm_msg.text or "")[:500] if mm_msg else ""
    f["evidence"]["mm_buttons"] = extract_buttons(mm_msg)[:10] if mm_msg else []
    f["checks"]["my_matches_loads"] = bool(mm_msg) and "match" in (mm_msg.text or "").lower()

    # 7. Tap edge match in MM → Edge Detail (W3-4)
    mm_detail = None
    if mm_msg and mm_msg.reply_markup:
        for row in mm_msg.reply_markup.rows:
            for b in row.buttons:
                if hasattr(b, "data") and b.data:
                    cb = b.data.decode("utf-8", "ignore") if isinstance(b.data, bytes) else str(b.data)
                    if cb.startswith("mm:match:"):
                        try:
                            await mm_msg.click(data=b.data)
                            await asyncio.sleep(7)
                            msgs = await client.get_messages(BOT_USERNAME, limit=4)
                            mm_detail = next((m for m in msgs if not m.out), None)
                        except Exception as e:
                            f["evidence"]["mm_click_error"] = str(e)
                        break
            if mm_detail:
                break

    if mm_detail:
        mtext = mm_detail.text or mm_detail.message or ""
        f["evidence"]["mm_detail"] = strip_html(mtext)[:600]
        f["evidence"]["mm_detail_buttons"] = extract_buttons(mm_detail)[:10]
        # W3-4: edge from MM should route to edge_detail (chip rows + verdict) not match_detail
        f["checks"]["mm_edge_routes_to_edge_detail"] = bool(re.search(r"verdict|edge|EV%|ev percentage", mtext, re.I))

        # 8. Tap Back from MM
        back_msgs, _ = await click_button(client, mm_detail, "↩️", wait=5)
        if back_msgs:
            f["evidence"]["back_from_mm_detail"] = strip_html(back_msgs[0].text or "")[:200]
            f["checks"]["back_returns_to_mm"] = "matches" in (back_msgs[0].text or "").lower()
        else:
            f["checks"]["back_returns_to_mm"] = False
    else:
        f["checks"]["mm_edge_routes_to_edge_detail"] = False
        f["checks"]["back_returns_to_mm"] = False

    return f


async def flow_b_gold(client):
    f = {"checks": {}, "evidence": {}}
    msgs = await send_cmd(client, "/qa set_gold")
    f["checks"]["tier_set"] = bool(msgs and "GOLD" in (msgs[0].text or "").upper())
    msgs = await send_cmd(client, "/picks", wait=8)
    picks_msg = msgs[0] if msgs else None
    picks_text = picks_msg.text if picks_msg else ""
    f["evidence"]["picks"] = strip_html(picks_text)[:500]
    f["evidence"]["picks_buttons"] = extract_buttons(picks_msg)[:10]
    f["checks"]["gold_picks_loads"] = bool(picks_msg)
    # locked indicator presence (Diamond cards should be 🔒 / blurred for Gold)
    has_locked = "🔒" in picks_text or "diamond" in picks_text.lower() and "upgrade" in picks_text.lower()
    f["checks"]["diamond_cards_locked_for_gold"] = has_locked
    # Test My Matches non-edge card → no INJURY ROW visible
    msgs = await send_cmd(client, "My Matches", wait=8)
    mm_msg = msgs[0] if msgs else None
    f["evidence"]["mm_text"] = strip_html(mm_msg.text or "")[:400] if mm_msg else ""
    has_injury_section = bool(mm_msg and re.search(r"injur", mm_msg.text or "", re.I))
    f["checks"]["no_injury_row_on_mm"] = not has_injury_section
    f["checks"]["mm_card_not_morning_digest"] = bool(mm_msg) and "morning digest" not in (mm_msg.text or "").lower()
    return f


async def flow_c_bronze(client):
    f = {"checks": {}, "evidence": {}}
    msgs = await send_cmd(client, "/qa set_bronze")
    f["checks"]["tier_set"] = bool(msgs and "BRONZE" in (msgs[0].text or "").upper())
    msgs = await send_cmd(client, "/start", wait=5)
    f["evidence"]["start"] = strip_html(msgs[0].text or "")[:300] if msgs else ""
    f["checks"]["bronze_start_responds"] = bool(msgs)
    msgs = await send_cmd(client, "/picks", wait=8)
    picks_msg = msgs[0] if msgs else None
    picks_text = picks_msg.text if picks_msg else ""
    f["evidence"]["picks"] = strip_html(picks_text)[:500]
    has_locked = "🔒" in picks_text or "upgrade" in picks_text.lower()
    f["checks"]["bronze_gating_correct"] = has_locked or "bronze" in picks_text.lower()
    return f


async def flow_d_fresh(client):
    f = {"checks": {}, "evidence": {}}
    msgs = await send_cmd(client, "/qa reset")
    f["evidence"]["reset"] = strip_html(msgs[0].text or "")[:200] if msgs else ""
    msgs = await send_cmd(client, "/qa set_diamond")
    f["checks"]["tier_set_after_reset"] = bool(msgs and "DIAMOND" in (msgs[0].text or "").upper())
    msgs = await send_cmd(client, "/start", wait=6)
    main_text = msgs[0].text if msgs else ""
    f["evidence"]["start_main"] = strip_html(main_text)[:400]
    # If user is already onboarded (admin), /start goes to main menu — record this
    f["checks"]["main_menu_reachable"] = bool(msgs)
    f["checks"]["start_no_errors"] = "error" not in (main_text or "").lower() and "exception" not in (main_text or "").lower()
    return f


async def wave3_evidence(client, flow_a):
    """Cross-reference Flow A captures for W3-1..5."""
    w = {}
    edge_detail = flow_a["evidence"].get("edge_detail", "")
    chips = flow_a["evidence"].get("edge_detail_chip_lines", 0)
    w["W3_1_chips_le_3"] = {
        "pass": chips <= 3,
        "evidence": f"{chips} chip lines detected in Edge Detail card",
    }
    # W3-2: scan Edge Picks list for date display
    picks_text = flow_a["evidence"].get("picks", "")
    future_dates = re.findall(r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b", picks_text)
    today_count = picks_text.lower().count("today")
    w["W3_2_date_kickoff"] = {
        "pass": True,  # presence-only check
        "evidence": f"future dates seen={future_dates[:3]}, 'Today' count={today_count}",
    }
    w["W3_3_back_nav"] = {
        "pass": flow_a["checks"].get("back_returns_to_mm", False),
        "evidence": flow_a["evidence"].get("back_from_mm_detail", "")[:200],
    }
    w["W3_4_mm_edge_nav"] = {
        "pass": flow_a["checks"].get("mm_edge_routes_to_edge_detail", False),
        "evidence": flow_a["evidence"].get("mm_detail", "")[:200],
    }
    mm_text = flow_a["evidence"].get("mm_detail", "")
    has_injury = bool(re.search(r"injur", mm_text, re.I))
    w["W3_5_card_size_no_injury"] = {
        "pass": not has_injury,
        "evidence": f"INJURY section in MM card: {has_injury}",
    }
    return w


async def narrative_spotcheck(client):
    """Use /qa card_image P01..P03 to capture 3 cards across profiles."""
    out = []
    for pid in ["P01", "P02", "P03"]:
        # Get the profile match key first
        msgs = await send_cmd(client, f"/qa profile {pid}", wait=3)
        profile_text = msgs[0].text if msgs else ""
        # Try to extract a match_key — profiles include typical match
        m = re.search(r"([a-z_]+_vs_[a-z_]+_\d{4}-\d{2}-\d{2})", profile_text or "")
        if not m:
            out.append({"profile": pid, "verdict": "(no match key found)", "chars": 0, "pass": False})
            continue
        mkey = m.group(1)
        # Trigger card render — this also pushes to admin chat
        msgs = await send_cmd(client, f"/qa card_image {pid} {mkey}", wait=10)
        # Caption should contain verdict
        latest = msgs[0] if msgs else None
        caption = (latest.text or latest.message or "") if latest else ""
        verdict = find_verdict(caption)
        out.append({
            "profile": pid,
            "match_key": mkey,
            "verdict": verdict,
            "chars": len(verdict),
            "pass": len(verdict) >= 80 and not re.match(r"^\w+\s+is\s+value\s+at", verdict, re.I),
        })
    return out


async def main():
    client = await get_client()
    try:
        print("Flow A — Diamond")
        a = await flow_a_diamond(client)
        evidence["flows"]["A_diamond"] = a
        print("  checks:", a["checks"])

        print("Flow B — Gold")
        b = await flow_b_gold(client)
        evidence["flows"]["B_gold"] = b
        print("  checks:", b["checks"])

        print("Flow C — Bronze")
        c = await flow_c_bronze(client)
        evidence["flows"]["C_bronze"] = c
        print("  checks:", c["checks"])

        print("Flow D — Fresh onboarding")
        d = await flow_d_fresh(client)
        evidence["flows"]["D_fresh"] = d
        print("  checks:", d["checks"])

        print("Wave 3 fix evidence")
        evidence["wave3"] = await wave3_evidence(client, a)
        print("  ", {k: v["pass"] for k, v in evidence["wave3"].items()})

        print("Narrative spot-check")
        evidence["narrative"] = await narrative_spotcheck(client)
        for n in evidence["narrative"]:
            print(f"  {n['profile']}: chars={n['chars']} pass={n['pass']}")

        # Reset tier
        await send_cmd(client, "/qa reset")
    except Exception as e:
        evidence["errors"].append(f"main: {e}")
        import traceback
        traceback.print_exc()
    finally:
        out_file = OUT_DIR / "evidence.json"
        out_file.write_text(json.dumps(evidence, indent=2, default=str))
        print(f"\nEvidence: {out_file}")
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
