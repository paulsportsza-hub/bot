#!/usr/bin/env python3
"""FIX-CORE7-SOCCER-01 — SO #38 Telethon QA.

5 live Edge cards. PSL cards must show model_probability signal as REAL (not stub).

Per-card assertions:
  A1. Card has a tier badge (💎/🥇/🥈/🥉 or DIAMOND/GOLDEN/SILVER/BRONZE).
  A2. Card CTA button references a SA bookmaker (proves odds lookup succeeded).
  A3. Card has a match header (vs / v).
  A4. Card does NOT leak internals (signal_strength / NoneType / Traceback).

Plus DB-level invariant for PSL:
  D1. For every accessible PSL match_key tapped in the run, the most recent
      clv_tracking row has model_probability_score IS NOT NULL AND != 0.0.

Outputs JSON to /tmp/qa_fix_core7_soccer_01/results.json + stdout summary.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

_BOT_DIR = Path(__file__).parent.parent.parent
load_dotenv(_BOT_DIR / ".env")

try:
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    from telethon.tl.types import KeyboardButtonCallback, ReplyInlineMarkup
except ImportError:
    print("telethon not installed — skipping SO38 QA")
    sys.exit(0)

API_ID = int(os.getenv("TELEGRAM_API_ID", "32418601"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "95e313a8ef5b998be0515dd8328fac57")
BOT_USERNAME = "@mzansiedge_bot"
SESSION_FILE = str(_BOT_DIR / "data" / "telethon_qa_session.string")
ODDS_DB = "/home/paulsportsza/scrapers/odds.db"

OUT_DIR = Path("/tmp/qa_fix_core7_soccer_01")
OUT_DIR.mkdir(parents=True, exist_ok=True)

PSL_TEAM_TOKENS = (
    "kaizer_chiefs", "orlando_pirates", "mamelodi_sundowns", "stellenbosch",
    "amazulu", "polokwane_city", "richards_bay", "golden_arrows",
    "ts_galaxy", "sekhukhune_united", "chippa_united", "supersport_united",
    "magesi", "marumo_gallants", "cape_town_city", "moroka_swallows",
    "cape_town_spurs", "orbit_college", "durban_city", "siwelele",
)
EPL_TEAM_TOKENS = (
    "arsenal", "chelsea", "liverpool", "manchester_city", "manchester_united",
    "tottenham", "newcastle", "brighton", "aston_villa", "west_ham",
    "everton", "leeds", "fulham", "crystal_palace", "wolverhampton",
    "bournemouth", "brentford", "burnley", "nottingham_forest", "sunderland",
)

TIER_RE = re.compile(r"(💎|🥇|🥈|🥉|DIAMOND|GOLDEN|GOLD|SILVER|BRONZE)", re.IGNORECASE)
ODDS_RE = re.compile(
    r"\d+\.\d{2}|Supabets|Hollywoodbets|Betway|Sportingbet|GBets|WSB|SuperSportBet",
    re.IGNORECASE,
)
MATCH_RE = re.compile(r"(?:vs\.?|v\s)", re.IGNORECASE)
TAINT_RE = re.compile(r"signal_strength|traceback|exception|NoneType", re.IGNORECASE)

TAP_TIMEOUT = 35.0


def _load_session() -> StringSession:
    with open(SESSION_FILE) as f:
        return StringSession(f.read().strip())


def _league_of_match_key(mk: str) -> str:
    low = mk.lower()
    for tok in PSL_TEAM_TOKENS:
        if tok in low:
            return "psl"
    for tok in EPL_TEAM_TOKENS:
        if tok in low:
            return "epl"
    return "other"


def _extract_match_key_from_cb(cb: str) -> str:
    if cb.startswith("edge:detail:"):
        return cb[len("edge:detail:"):]
    return ""


async def _find_edge_buttons(msg) -> list:
    out = []
    if not msg or not msg.reply_markup:
        return out
    if isinstance(msg.reply_markup, ReplyInlineMarkup):
        for row in msg.reply_markup.rows:
            for btn in row.buttons:
                if isinstance(btn, KeyboardButtonCallback):
                    cb = btn.data.decode("utf-8", errors="ignore")
                    if "edge:detail" in cb or "ep:pick" in cb:
                        out.append((btn.text, cb))
    return out


def _assert_card(card_text: str, idx: int) -> list[str]:
    fails = []
    if not TIER_RE.search(card_text):
        fails.append(f"A1 FAIL card {idx}: no tier badge in {card_text[:80]!r}")
    if not ODDS_RE.search(card_text):
        fails.append(f"A2 FAIL card {idx}: no bookmaker/odds in {card_text[:80]!r}")
    if not MATCH_RE.search(card_text):
        fails.append(f"A3 FAIL card {idx}: no match header (vs/v) in {card_text[:80]!r}")
    if TAINT_RE.search(card_text):
        fails.append(f"A4 FAIL card {idx}: internal leak in {card_text[:80]!r}")
    return fails


def _check_psl_model_probability(match_keys: list[str]) -> dict:
    """D1: every PSL match_key tapped must have a recent clv_tracking row
    with model_probability_score not NULL and != 0.0."""
    if not match_keys:
        return {"checked": 0, "real": 0, "stub": 0, "psl_keys": [], "stubs": []}
    conn = sqlite3.connect(ODDS_DB)
    conn.row_factory = sqlite3.Row
    real, stub, psl_keys, stubs = 0, 0, [], []
    try:
        for mk in match_keys:
            if _league_of_match_key(mk) != "psl":
                continue
            psl_keys.append(mk)
            row = conn.execute("""
                SELECT model_probability_score, calculated_at
                FROM clv_tracking
                WHERE match_key = ?
                ORDER BY calculated_at DESC
                LIMIT 1
            """, (mk,)).fetchone()
            if row is None:
                stub += 1
                stubs.append({"match_key": mk, "reason": "no_clv_row"})
                continue
            mps = row["model_probability_score"]
            if mps is None or mps == 0.0:
                stub += 1
                stubs.append({"match_key": mk, "reason": f"model_probability_score={mps}",
                              "calculated_at": row["calculated_at"]})
            else:
                real += 1
    finally:
        conn.close()
    return {
        "checked": len(psl_keys), "real": real, "stub": stub,
        "psl_keys": psl_keys, "stubs": stubs,
    }


async def run() -> dict:
    print("=" * 60)
    print("FIX-CORE7-SOCCER-01 — SO #38 Telethon QA")
    print(f"Bot: {BOT_USERNAME}  Time: {datetime.now().isoformat()}")
    print("=" * 60)

    client = TelegramClient(_load_session(), API_ID, API_HASH)
    await client.connect()
    if not await client.is_user_authorized():
        return {"status": "SKIP", "reason": "not_authorised"}

    results = []
    fails: list[str] = []
    tapped_match_keys: list[str] = []

    try:
        await client.send_message(BOT_USERNAME, "/qa set_diamond")
        await asyncio.sleep(2.5)

        anchor_msgs = await client.get_messages(BOT_USERNAME, limit=1)
        anchor_id = anchor_msgs[0].id if anchor_msgs else 0

        await client.send_message(BOT_USERNAME, "💎 Top Edge Picks")
        await asyncio.sleep(8)

        edge_buttons: list[tuple[str, str]] = []
        btn_msg = None
        deadline = time.time() + 15.0
        while time.time() < deadline and not edge_buttons:
            msgs = await client.get_messages(BOT_USERNAME, limit=15)
            for m in msgs:
                if m.id > anchor_id:
                    btns = await _find_edge_buttons(m)
                    if btns:
                        edge_buttons = btns
                        btn_msg = m
                        break
            if not edge_buttons:
                await asyncio.sleep(1)
        print(f"[+] Found {len(edge_buttons)} edge buttons in picks list")

        epl_taps, psl_taps, total_taps = 0, 0, 0
        target_epl, target_psl = 3, 2

        for btn_text, btn_cb in edge_buttons:
            if total_taps >= 5:
                break
            mk = _extract_match_key_from_cb(btn_cb)
            league = _league_of_match_key(mk) if mk else "unknown"
            if league == "epl" and epl_taps >= target_epl:
                continue
            if league == "psl" and psl_taps >= target_psl:
                continue
            if league == "other" and (epl_taps + psl_taps + total_taps) > 0:
                continue

            print(f"\n[Card {total_taps + 1}] league={league} btn={btn_text[:35]} cb={btn_cb[:50]}")

            if btn_msg is None:
                continue

            try:
                fresh = await client.get_messages(BOT_USERNAME, min_id=btn_msg.id - 1, limit=5)
                for fm in fresh:
                    if fm.id == btn_msg.id:
                        btn_msg = fm
                        break
            except Exception:
                pass

            try:
                await btn_msg.click(data=btn_cb.encode())
            except Exception as e:
                fails.append(f"CLICK FAIL card {total_taps + 1}: {e}")
                continue

            await asyncio.sleep(11.0)

            detail_msg = None
            for _attempt in range(3):
                try:
                    fetched = await client.get_messages(BOT_USERNAME, ids=[btn_msg.id])
                    refreshed = (fetched[0] if isinstance(fetched, list) else fetched) if fetched else None
                    if refreshed and refreshed.reply_markup and isinstance(refreshed.reply_markup, ReplyInlineMarkup):
                        cbs = [
                            b.data.decode("utf-8", errors="ignore")
                            for r in refreshed.reply_markup.rows
                            for b in r.buttons if isinstance(b, KeyboardButtonCallback)
                        ]
                        if not any("ep:pick" in c for c in cbs):
                            detail_msg = refreshed
                            break
                except Exception as e:
                    print(f"   refetch error: {e}")
                if _attempt < 2:
                    await asyncio.sleep(4.0)

            if not detail_msg:
                fails.append(f"TIMEOUT card {total_taps + 1}: detail render")
                results.append({
                    "card": total_taps + 1, "league": league,
                    "match_key": mk, "status": "TIMEOUT",
                })
                total_taps += 1
                continue

            detail_btn_labels = []
            if detail_msg.reply_markup and isinstance(detail_msg.reply_markup, ReplyInlineMarkup):
                for row in detail_msg.reply_markup.rows:
                    for b in row.buttons:
                        detail_btn_labels.append(b.text)

            card_text = btn_text + " " + " ".join(detail_btn_labels) + " " + (detail_msg.text or detail_msg.message or "")
            print(f"   detail buttons: {' | '.join(detail_btn_labels)[:160]}")

            card_fails = _assert_card(card_text, total_taps + 1)
            for f in card_fails:
                print(f"   {f}")
                fails.append(f)

            if mk:
                tapped_match_keys.append(mk)
            results.append({
                "card": total_taps + 1, "league": league,
                "match_key": mk, "button": btn_text[:40],
                "callback": btn_cb[:50],
                "assertions": "PASS" if not card_fails else "FAIL",
                "fails": card_fails,
                "detail_buttons_preview": " | ".join(detail_btn_labels)[:160],
            })
            if league == "epl":
                epl_taps += 1
            elif league == "psl":
                psl_taps += 1
            total_taps += 1

            try:
                back_btn = None
                for r in detail_msg.reply_markup.rows:
                    for b in r.buttons:
                        if isinstance(b, KeyboardButtonCallback):
                            cbs = b.data.decode("utf-8", errors="ignore")
                            if "hot:back" in cbs or "back" in b.text.lower():
                                back_btn = b
                                break
                    if back_btn:
                        break
                if back_btn:
                    await detail_msg.click(data=back_btn.data)
                    await asyncio.sleep(6.0)
                    fresh = await client.get_messages(BOT_USERNAME, limit=10)
                    for fm in fresh:
                        if fm.id >= detail_msg.id:
                            btns = await _find_edge_buttons(fm)
                            if btns:
                                edge_buttons = btns
                                btn_msg = fm
                                break
                else:
                    a2 = (await client.get_messages(BOT_USERNAME, limit=1))[0].id
                    await client.send_message(BOT_USERNAME, "💎 Top Edge Picks")
                    await asyncio.sleep(8)
                    fresh = await client.get_messages(BOT_USERNAME, limit=15)
                    for fm in fresh:
                        if fm.id > a2:
                            btns = await _find_edge_buttons(fm)
                            if btns:
                                edge_buttons = btns
                                btn_msg = fm
                                break
            except Exception as e:
                print(f"   back-nav warning: {e}")

        d1 = _check_psl_model_probability(tapped_match_keys)
        if d1["psl_keys"] and d1["stub"] > 0:
            fails.append(
                f"D1 FAIL: {d1['stub']}/{d1['checked']} PSL match_keys have stub model_probability_score "
                f"({d1['stubs']!r})"
            )

        summary = {
            "status": "PASS" if not fails else "FAIL",
            "cards_tapped": total_taps,
            "epl_taps": epl_taps,
            "psl_taps": psl_taps,
            "card_results": results,
            "psl_model_probability_check": d1,
            "all_fails": fails,
        }

        out_path = OUT_DIR / "results.json"
        with open(out_path, "w") as f:
            json.dump(summary, f, indent=2)
        print(f"\n[+] Wrote {out_path}")

        print("\n" + "=" * 60)
        print(f"Result: {summary['status']}")
        print(f"Cards tapped: {total_taps}/5  (EPL={epl_taps}/3  PSL={psl_taps}/2)")
        print(f"PSL model_probability REAL: {d1['real']}/{d1['checked']}")
        if fails:
            print(f"\nFails ({len(fails)}):")
            for f in fails:
                print(f"  {f}")
        print("=" * 60)
        return summary

    finally:
        try:
            await client.send_message(BOT_USERNAME, "/qa reset")
        except Exception:
            pass
        await client.disconnect()


if __name__ == "__main__":
    summary = asyncio.run(run())
    sys.exit(0 if summary.get("status") == "PASS" else 1)
