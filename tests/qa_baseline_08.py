"""QA-BASELINE-08 — Telethon E2E Scoring (7.5 Gate).

Connects to @mzansiedge_bot via Telethon, triggers edge:detail and yg:game:
callbacks, captures FULL HTML output, and scores each card against the rubric.

Usage:
    cd /home/paulsportsza/bot
    .venv/bin/python tests/qa_baseline_08.py
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import ReplyInlineMarkup, KeyboardButtonCallback, KeyboardButtonUrl
from telethon.tl.functions.messages import GetBotCallbackAnswerRequest

API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "")
BOT_USERNAME = "mzansiedge_bot"
SESSION_FILE = str(Path(__file__).resolve().parent.parent / "data" / "telethon_qa_session")
STRING_SESSION_FILE = str(Path(__file__).resolve().parent.parent / "data" / "telethon_qa_session.string")

TIMEOUT = 20
SHORT_TIMEOUT = 10


# ── Data class ──────────────────────────────────────────

@dataclass
class CardScore:
    fixture: str
    source_path: str
    rendering_path: str
    tier_badge: str
    has_setup: bool = False
    has_edge: bool = False
    has_risk: bool = False
    has_verdict: bool = False
    has_ev_pct: bool = False
    has_specific_signals: bool = False
    has_risk_factors: bool = False
    copy_quality: float = 0.0
    verdict_coherence: float = 0.0
    richness: float = 0.0
    freshness_ok: bool = True
    html_ok: bool = True
    pick_identity_ok: bool = True
    error_text: str = ""
    raw_html: str = ""
    total_score: float = 0.0
    source_confirmed: str = "Telethon"
    penalties: list = field(default_factory=list)

    def compute_score(self):
        score = 0.0
        if self.has_setup: score += 1.0
        if self.has_edge: score += 1.0
        if self.has_risk: score += 1.0
        if self.has_verdict: score += 1.0

        self.richness = 0.0
        if self.has_ev_pct: self.richness += 0.7
        if self.has_specific_signals: self.richness += 0.7
        if self.has_risk_factors: self.richness += 0.6
        self.richness = min(self.richness, 2.0)
        score += self.richness
        score += self.copy_quality
        score += self.verdict_coherence

        if not self.freshness_ok:
            score -= 1.0
            self.penalties.append("-1 stale data")
        if not self.html_ok:
            score -= 1.0
            self.penalties.append("-1 broken HTML")
        if not self.pick_identity_ok:
            score -= 1.0
            self.penalties.append("-1 wrong pick")

        if self.rendering_path == "template":
            score = min(score, 3.0)
            self.penalties.append("template cap 3/10")
        elif self.rendering_path == "w82":
            score = min(score, 5.0)
            self.penalties.append("w82 cap 5/10")

        if self.error_text:
            score = min(score, 1.0)
            self.penalties.append(f"error: {self.error_text[:50]}")

        self.total_score = max(0.0, min(10.0, score))
        return self.total_score


# ── Telethon helpers ────────────────────────────────────

async def get_client() -> TelegramClient:
    if os.path.exists(STRING_SESSION_FILE):
        string = open(STRING_SESSION_FILE).read().strip()
        if string:
            client = TelegramClient(StringSession(string), API_ID, API_HASH)
            await client.connect()
            if await client.is_user_authorized():
                return client
            await client.disconnect()
    client = TelegramClient(SESSION_FILE, API_ID, API_HASH)
    await client.connect()
    if not await client.is_user_authorized():
        print("ERROR: Not logged in.")
        sys.exit(1)
    return client


async def get_latest_bot_msg(client, entity, after_id: int = 0):
    """Get the latest bot message after a given message ID."""
    messages = await client.get_messages(entity, limit=15)
    for m in messages:
        if not m.out and m.id > after_id:
            return m
    # Fallback: return latest non-outgoing
    for m in messages:
        if not m.out:
            return m
    return None


async def send_text_and_wait(client, entity, text: str, wait: float = SHORT_TIMEOUT):
    """Send a text message and wait for the bot's reply."""
    sent = await client.send_message(entity, text)
    await asyncio.sleep(wait)
    return await get_latest_bot_msg(client, entity, sent.id)


async def press_callback(client, entity, msg, callback_data: bytes, wait: float = TIMEOUT):
    """Press an inline callback button via raw API. Returns the updated message."""
    try:
        await client(GetBotCallbackAnswerRequest(
            peer=entity,
            msg_id=msg.id,
            data=callback_data,
        ))
    except Exception:
        pass  # Bot may not send callback answer; that's OK
    await asyncio.sleep(wait)
    # Re-fetch the message (it may have been edited)
    msgs = await client.get_messages(entity, ids=[msg.id])
    if msgs and msgs[0]:
        return msgs[0]
    # Fallback: get latest bot message
    return await get_latest_bot_msg(client, entity)


def extract_callbacks(msg) -> list[tuple[str, bytes]]:
    """Extract (text, data) for all callback buttons."""
    result = []
    if not msg or not msg.reply_markup or not isinstance(msg.reply_markup, ReplyInlineMarkup):
        return result
    for row in msg.reply_markup.rows:
        for btn in row.buttons:
            if isinstance(btn, KeyboardButtonCallback):
                result.append((btn.text, btn.data))
    return result


# ── Scoring logic ───────────────────────────────────────

def score_card(text: str, source_path: str, fixture_name: str) -> CardScore:
    card = CardScore(fixture=fixture_name, source_path=source_path,
                     rendering_path="unknown", tier_badge="")
    card.raw_html = text or ""

    if not text:
        card.error_text = "Empty response"
        card.compute_score()
        return card

    for pat in ["Unable to load analysis", "Something went wrong", "Couldn't fetch",
                "No SA bookmaker odds", "Error loading"]:
        if pat.lower() in text.lower():
            card.error_text = pat
            break

    section_count = 0
    if "📋" in text or "The Setup" in text:
        card.has_setup = True; section_count += 1
    if "🎯" in text and ("The Edge" in text or "Edge" in text):
        card.has_edge = True; section_count += 1
    if "⚠️" in text or "The Risk" in text:
        card.has_risk = True; section_count += 1
    if "🏆" in text or "Verdict" in text:
        card.has_verdict = True; section_count += 1

    for badge in ["💎", "🥇", "🥈", "🥉"]:
        if badge in text:
            card.tier_badge = badge; break

    if re.search(r'(?:EV|expected value)[:\s]+\+?[\d.]+%', text, re.I):
        card.has_ev_pct = True
    elif re.search(r'\d+\.\d+%\s*(?:EV|expected value|edge)', text, re.I):
        card.has_ev_pct = True
    elif re.search(r'(?:fair|implied|model)\s+(?:probability|prob)', text, re.I):
        card.has_ev_pct = True

    signal_words = ["tipster", "movement", "consensus", "sharp", "signal", "indicator",
                    "confirming", "bookmaker", "diverge", "gap", "mispricing"]
    card.has_specific_signals = sum(1 for w in signal_words if w.lower() in text.lower()) >= 2

    risk_words = ["risk", "away", "home advantage", "crowd", "form", "injury",
                  "rotation", "fatigue", "variable", "uncertainty", "speculative"]
    card.has_risk_factors = sum(1 for w in risk_words if w.lower() in text.lower()) >= 1

    if card.error_text:
        card.rendering_path = "error"
    elif section_count >= 4:
        prose_indicators = 0
        paragraphs = [p for p in text.split("\n\n") if len(p) > 100]
        if len(paragraphs) >= 2: prose_indicators += 1
        analytical = ["diverge", "mispricing", "calibration", "exposure",
                      "implied probability", "base-rate", "speculative"]
        if sum(1 for w in analytical if w in text.lower()) >= 1: prose_indicators += 1
        colour = ["clean sheet", "try line", "strike rate", "match day", "kickoff",
                  "squad", "formation", "fixture", "bookmaker", "edge"]
        if sum(1 for w in colour if w in text.lower()) >= 1: prose_indicators += 1
        card.rendering_path = "w84" if prose_indicators >= 2 else "w82"
    elif section_count >= 2:
        card.rendering_path = "w82"
    else:
        card.rendering_path = "template"

    clinical = ["Standard match variance", "Numbers-only play", "Limited pre-match context",
                "pure price edge with no supporting data", "thin on supporting signals"]
    clinical_count = sum(1 for c in clinical if c.lower() in text.lower())
    if clinical_count == 0 and len(text) > 200:
        card.copy_quality = 2.0
    elif clinical_count == 0:
        card.copy_quality = 1.5
    elif clinical_count <= 1:
        card.copy_quality = 1.0
    else:
        card.copy_quality = 0.5

    verdict_text = ""
    verdict_idx = text.find("🏆")
    if verdict_idx >= 0:
        verdict_text = text[verdict_idx:]
    elif "Verdict" in text:
        verdict_text = text[text.find("Verdict"):]

    if verdict_text:
        coh_words = ["back", "punt", "speculative", "monitor", "pass", "stake", "unit",
                     "exposure", "measured", "confident", "conviction", "size", "lean", "edge"]
        coh = sum(1 for w in coh_words if w.lower() in verdict_text.lower())
        if coh >= 3: card.verdict_coherence = 2.0
        elif coh >= 2: card.verdict_coherence = 1.5
        elif coh >= 1: card.verdict_coherence = 1.0
        else: card.verdict_coherence = 0.5
    elif card.has_verdict:
        card.verdict_coherence = 0.5

    broken = ["&lt;b&gt;", "&lt;/b&gt;", "<b><b>", "</b></b>", "```"]
    if any(bh in (text or "") for bh in broken):
        card.html_ok = False

    if "48h" in text.lower() and "stale" in text.lower():
        card.freshness_ok = False

    card.compute_score()
    return card


# ── Main flow ───────────────────────────────────────────

async def run_qa_baseline():
    print("=" * 60)
    print("QA-BASELINE-08 — Telethon E2E Score (7.5 Gate)")
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M SAST')}")
    print("=" * 60)

    client = await get_client()
    print("[OK] Telethon client connected")

    entity = await client.get_entity(BOT_USERNAME)

    # Verify bot responds
    menu_msg = await send_text_and_wait(client, entity, "/menu", wait=5)
    if not menu_msg:
        print("[FAIL] Bot not responding. ABORTING.")
        await client.disconnect()
        return
    print("[OK] Bot responding")

    hot_tips_cards: list[CardScore] = []
    my_matches_cards: list[CardScore] = []
    template_count = 0

    # ── Hot Tips (edge:detail) ──────────────────────────
    print("\n--- Hot Tips Path (edge:detail) ---")

    tips_msg = await send_text_and_wait(client, entity, "💎 Top Edge Picks", wait=15)
    if not tips_msg or not tips_msg.text:
        print("[WARN] No Hot Tips response, trying /picks...")
        tips_msg = await send_text_and_wait(client, entity, "/picks", wait=15)

    if tips_msg and tips_msg.text:
        print(f"[OK] Hot Tips list received ({len(tips_msg.text)} chars)")

        # Collect edge:detail button data across pages
        all_detail_data: list[tuple[str, bytes]] = []  # (label, callback_data)

        def _collect_details(msg):
            for text, data in extract_callbacks(msg):
                ds = data.decode("utf-8", errors="replace")
                if "edge:detail:" in ds:
                    all_detail_data.append((text, data))

        _collect_details(tips_msg)
        page1_count = len(all_detail_data)
        print(f"[INFO] Page 1: {page1_count} detail buttons")

        # Paginate to collect more
        current_msg = tips_msg
        for page_num in range(2, 5):
            if len(all_detail_data) >= 12:
                break
            page_btns = [(t, d) for t, d in extract_callbacks(current_msg)
                        if b"hot:page:" in d and "Next" in t]
            if not page_btns:
                break
            print(f"[INFO] Navigating to page {page_num}...")
            current_msg = await press_callback(client, entity, current_msg, page_btns[0][1], wait=8)
            if current_msg and current_msg.text:
                before = len(all_detail_data)
                _collect_details(current_msg)
                print(f"[INFO] Page {page_num}: {len(all_detail_data) - before} detail buttons")

        print(f"[INFO] Total detail buttons found: {len(all_detail_data)}")

        # Now go back to page 1 to start clicking
        tips_msg = await send_text_and_wait(client, entity, "💎 Top Edge Picks", wait=12)

        # Click each detail button one at a time
        # Pattern: click detail → capture → click back → click next detail
        current_list_msg = tips_msg
        current_page = 0  # Track which page we're on
        buttons_on_page = [(t, d) for t, d in extract_callbacks(current_list_msg)
                          if b"edge:detail:" in d]
        page_idx = 0

        for i, (label, cb_data) in enumerate(all_detail_data):
            if len(hot_tips_cards) >= 10:
                break

            fixture_name = label.strip()
            for badge in ["💎", "🥇", "🥈", "🥉", "🔒"]:
                fixture_name = fixture_name.replace(badge, "").strip()
            print(f"  [{len(hot_tips_cards)+1}] {fixture_name[:60]}...")

            # If we've exhausted buttons on current page, navigate to next
            if page_idx >= len(buttons_on_page):
                nav = [(t, d) for t, d in extract_callbacks(current_list_msg)
                      if b"hot:page:" in d and "Next" in t]
                if nav:
                    current_list_msg = await press_callback(client, entity, current_list_msg, nav[0][1], wait=8)
                    buttons_on_page = [(t, d) for t, d in extract_callbacks(current_list_msg)
                                      if b"edge:detail:" in d]
                    page_idx = 0
                    current_page += 1

            if page_idx >= len(buttons_on_page):
                print(f"      SKIP: no more buttons on current page")
                continue

            # Click the detail button
            btn_label, btn_data = buttons_on_page[page_idx]
            try:
                detail_msg = await press_callback(client, entity, current_list_msg, btn_data, wait=TIMEOUT)
                if detail_msg and detail_msg.text:
                    card = score_card(detail_msg.text, "edge:detail", fixture_name)
                    hot_tips_cards.append(card)
                    print(f"      {card.total_score:.1f}/10 | {card.rendering_path} | {card.tier_badge}")
                    if card.rendering_path == "template":
                        template_count += 1

                    # Click "Back to Edge Picks" to return to list
                    back_btns = [(t, d) for t, d in extract_callbacks(detail_msg)
                                if b"hot:back:" in d or "Edge Picks" in t or "Back" in t]
                    if back_btns:
                        current_list_msg = await press_callback(client, entity, detail_msg, back_btns[0][1], wait=6)
                        # Re-gather buttons after returning
                        buttons_on_page = [(t, d) for t, d in extract_callbacks(current_list_msg)
                                          if b"edge:detail:" in d]
                        page_idx += 1
                    else:
                        # No back button — re-send Hot Tips
                        current_list_msg = await send_text_and_wait(client, entity, "💎 Top Edge Picks", wait=12)
                        buttons_on_page = [(t, d) for t, d in extract_callbacks(current_list_msg)
                                          if b"edge:detail:" in d]
                        page_idx = min(page_idx + 1, len(buttons_on_page))
                else:
                    card = CardScore(fixture=fixture_name, source_path="edge:detail",
                                   rendering_path="error", tier_badge="",
                                   error_text="No response")
                    card.compute_score()
                    hot_tips_cards.append(card)
                    print(f"      {card.total_score:.1f}/10 | ERROR: No response")
                    page_idx += 1
            except Exception as e:
                err_str = str(e)[:100]
                card = CardScore(fixture=fixture_name, source_path="edge:detail",
                               rendering_path="error", tier_badge="",
                               error_text=err_str)
                card.compute_score()
                hot_tips_cards.append(card)
                print(f"      {card.total_score:.1f}/10 | EXCEPTION: {err_str}")
                # Re-fetch list on error
                current_list_msg = await send_text_and_wait(client, entity, "💎 Top Edge Picks", wait=12)
                buttons_on_page = [(t, d) for t, d in extract_callbacks(current_list_msg)
                                  if b"edge:detail:" in d]
                page_idx = min(page_idx + 1, len(buttons_on_page))

            await asyncio.sleep(1)

    else:
        print("[FAIL] Could not get Hot Tips list")

    # ── My Matches (yg:game:) ───────────────────────────
    print(f"\n--- My Matches Path (yg:game:) ---")

    mm_msg = await send_text_and_wait(client, entity, "⚽ My Matches", wait=15)
    if not mm_msg or not mm_msg.text:
        print("[WARN] No My Matches response, retrying...")
        mm_msg = await send_text_and_wait(client, entity, "/schedule", wait=15)

    if mm_msg and mm_msg.text:
        print(f"[OK] My Matches list received ({len(mm_msg.text)} chars)")

        if "Unable to load" in mm_msg.text:
            print("[FAIL] My Matches shows 'Unable to load' error!")

        # Collect yg:game: buttons
        game_data: list[tuple[str, bytes]] = []
        for text, data in extract_callbacks(mm_msg):
            ds = data.decode("utf-8", errors="replace")
            if "yg:game:" in ds:
                game_data.append((text, data))

        # Check for pagination
        current_mm = mm_msg
        for p in range(2, 5):
            if len(game_data) >= 8:
                break
            nav = [(t, d) for t, d in extract_callbacks(current_mm)
                  if b"yg:all:" in d and "Next" in t]
            if not nav:
                break
            current_mm = await press_callback(client, entity, current_mm, nav[0][1], wait=8)
            if current_mm and current_mm.text:
                for t, d in extract_callbacks(current_mm):
                    ds = d.decode("utf-8", errors="replace")
                    if "yg:game:" in ds:
                        game_data.append((t, d))

        print(f"[INFO] Total yg:game: buttons: {len(game_data)}")

        # Go back to page 1
        mm_msg = await send_text_and_wait(client, entity, "⚽ My Matches", wait=12)
        current_mm = mm_msg
        mm_buttons = [(t, d) for t, d in extract_callbacks(current_mm) if b"yg:game:" in d]
        mm_idx = 0

        for i, (label, cb_data) in enumerate(game_data):
            if len(my_matches_cards) >= 8:
                break

            fixture_name = label.strip()
            print(f"  [{len(my_matches_cards)+1}] {fixture_name[:60]}...")

            if mm_idx >= len(mm_buttons):
                nav = [(t, d) for t, d in extract_callbacks(current_mm)
                      if b"yg:all:" in d and "Next" in t]
                if nav:
                    current_mm = await press_callback(client, entity, current_mm, nav[0][1], wait=8)
                    mm_buttons = [(t, d) for t, d in extract_callbacks(current_mm) if b"yg:game:" in d]
                    mm_idx = 0

            if mm_idx >= len(mm_buttons):
                print(f"      SKIP: no more game buttons")
                continue

            _, btn_data = mm_buttons[mm_idx]
            try:
                detail_msg = await press_callback(client, entity, current_mm, btn_data, wait=TIMEOUT)
                if detail_msg and detail_msg.text:
                    if "Unable to load analysis" in detail_msg.text:
                        card = CardScore(fixture=fixture_name, source_path="yg:game",
                                       rendering_path="error", tier_badge="",
                                       error_text="Unable to load analysis")
                        card.compute_score()
                        my_matches_cards.append(card)
                        print(f"      {card.total_score:.1f}/10 | ERROR: Unable to load analysis")
                    else:
                        card = score_card(detail_msg.text, "yg:game", fixture_name)
                        my_matches_cards.append(card)
                        print(f"      {card.total_score:.1f}/10 | {card.rendering_path} | {card.tier_badge}")
                        if card.rendering_path == "template":
                            template_count += 1

                    # Click back to return to list
                    back = [(t, d) for t, d in extract_callbacks(detail_msg)
                           if b"yg:all:" in d or "My Matches" in t or "Back" in t]
                    if back:
                        current_mm = await press_callback(client, entity, detail_msg, back[0][1], wait=6)
                        mm_buttons = [(t, d) for t, d in extract_callbacks(current_mm) if b"yg:game:" in d]
                        mm_idx += 1
                    else:
                        current_mm = await send_text_and_wait(client, entity, "⚽ My Matches", wait=12)
                        mm_buttons = [(t, d) for t, d in extract_callbacks(current_mm) if b"yg:game:" in d]
                        mm_idx = min(mm_idx + 1, len(mm_buttons))
                else:
                    card = CardScore(fixture=fixture_name, source_path="yg:game",
                                   rendering_path="error", tier_badge="",
                                   error_text="No response")
                    card.compute_score()
                    my_matches_cards.append(card)
                    print(f"      {card.total_score:.1f}/10 | ERROR")
                    mm_idx += 1
            except Exception as e:
                card = CardScore(fixture=fixture_name, source_path="yg:game",
                               rendering_path="error", tier_badge="",
                               error_text=str(e)[:100])
                card.compute_score()
                my_matches_cards.append(card)
                print(f"      {card.total_score:.1f}/10 | EXCEPTION: {e}")
                current_mm = await send_text_and_wait(client, entity, "⚽ My Matches", wait=12)
                mm_buttons = [(t, d) for t, d in extract_callbacks(current_mm) if b"yg:game:" in d]
                mm_idx = min(mm_idx + 1, len(mm_buttons))

            await asyncio.sleep(1)
    else:
        print("[FAIL] No My Matches response")

    await client.disconnect()

    # ── Aggregates ──────────────────────────────────────
    all_cards = hot_tips_cards + my_matches_cards
    print("\n" + "=" * 60)
    print("SCORING RESULTS")
    print("=" * 60)

    if not all_cards:
        print("[FAIL] No cards scored.")
        return

    ht_scores = [c.total_score for c in hot_tips_cards]
    mm_scores = [c.total_score for c in my_matches_cards]
    ht_mean = sum(ht_scores) / len(ht_scores) if ht_scores else 0
    mm_mean = sum(mm_scores) / len(mm_scores) if mm_scores else 0
    combined_mean = sum(c.total_score for c in all_cards) / len(all_cards)
    vc_scores = [c.verdict_coherence for c in all_cards if c.verdict_coherence > 0]
    vc_mean = sum(vc_scores) / len(vc_scores) if vc_scores else 0
    unable_count = sum(1 for c in all_cards if "Unable to load" in c.error_text)
    template_pct = (template_count / len(all_cards) * 100) if all_cards else 0

    print(f"\n{'#':<3} {'Source':<13} {'Fixture':<45} {'Path':<10} {'Tier':<4} {'Score':<6} {'Penalties'}")
    print("-" * 120)
    for i, c in enumerate(all_cards, 1):
        pen = "; ".join(c.penalties) if c.penalties else "-"
        print(f"{i:<3} {c.source_path:<13} {c.fixture[:44]:<45} {c.rendering_path:<10} {c.tier_badge:<4} {c.total_score:<6.1f} {pen}")

    print(f"\n{'AGGREGATES':=^60}")
    print(f"Hot Tips cards:     {len(hot_tips_cards)} (need >= 10)")
    print(f"My Matches cards:   {len(my_matches_cards)} (need >= 5)")
    print(f"Total cards:        {len(all_cards)} (need >= 15)")
    print(f"")
    print(f"Hot Tips mean:      {ht_mean:.2f}")
    print(f"My Matches mean:    {mm_mean:.2f}")
    print(f"Combined mean:      {combined_mean:.2f}")
    print(f"")
    print(f"Verdict coherence:  {vc_mean:.2f} (need >= 1.7)")
    print(f"Unable to load:     {unable_count} (need = 0)")
    print(f"Template cards:     {template_count}/{len(all_cards)} ({template_pct:.0f}%, need <= 10%)")

    # ── Regression checks ───────────────────────────────
    print(f"\n{'REGRESSION CHECKS':=^60}")
    regressions = []

    if vc_mean < 1.7:
        regressions.append(f"Verdict coherence {vc_mean:.2f} < 1.7")
        print(f"[FAIL] Verdict coherence: {vc_mean:.2f} < 1.7")
    else:
        print(f"[PASS] Verdict coherence: {vc_mean:.2f} >= 1.7")

    if unable_count > 0:
        regressions.append(f"{unable_count} 'Unable to load' errors")
        print(f"[FAIL] Unable to load errors: {unable_count}")
    else:
        print(f"[PASS] Zero 'Unable to load' errors")

    if ht_mean < 6.5:
        regressions.append(f"Hot Tips mean {ht_mean:.2f} < 6.5")
        print(f"[FAIL] Hot Tips mean: {ht_mean:.2f} < 6.5")
    else:
        print(f"[PASS] Hot Tips mean: {ht_mean:.2f} >= 6.5")

    if template_pct > 10:
        regressions.append(f"Template cards {template_pct:.0f}% > 10%")
        print(f"[FAIL] Template cards: {template_pct:.0f}% > 10%")
    else:
        print(f"[PASS] Template cards: {template_pct:.0f}% <= 10%")

    gate_pass = combined_mean >= 7.5
    print(f"\n{'GATE RESULT':=^60}")
    print(f"Combined mean: {combined_mean:.2f}")
    print(f"Threshold:     7.5")
    print(f"Result:        {'PASS' if gate_pass else 'FAIL'}")
    if regressions:
        print(f"\nRegressions:")
        for r in regressions:
            print(f"  - {r}")

    # Save raw data
    report_data = {
        "wave": "QA-BASELINE-08",
        "date": datetime.now().isoformat(),
        "hot_tips_count": len(hot_tips_cards),
        "my_matches_count": len(my_matches_cards),
        "total_count": len(all_cards),
        "hot_tips_mean": round(ht_mean, 2),
        "my_matches_mean": round(mm_mean, 2),
        "combined_mean": round(combined_mean, 2),
        "verdict_coherence_mean": round(vc_mean, 2),
        "unable_to_load_count": unable_count,
        "template_count": template_count,
        "template_pct": round(template_pct, 1),
        "gate_pass": gate_pass,
        "regressions": regressions,
        "cards": [
            {
                "fixture": c.fixture,
                "source_path": c.source_path,
                "rendering_path": c.rendering_path,
                "tier_badge": c.tier_badge,
                "score": c.total_score,
                "has_setup": c.has_setup, "has_edge": c.has_edge,
                "has_risk": c.has_risk, "has_verdict": c.has_verdict,
                "has_ev_pct": c.has_ev_pct,
                "copy_quality": c.copy_quality,
                "verdict_coherence": c.verdict_coherence,
                "richness": c.richness,
                "penalties": c.penalties,
                "error_text": c.error_text,
                "raw_html_len": len(c.raw_html),
            }
            for c in all_cards
        ],
    }

    json_path = Path("/home/paulsportsza/reports/qa-baseline-08-data.json")
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report_data, indent=2))
    print(f"\n[INFO] Raw data saved to {json_path}")
    return report_data


if __name__ == "__main__":
    asyncio.run(run_qa_baseline())
