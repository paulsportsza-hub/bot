"""QA-BASELINE-13 — Full Hot Tips + My Matches Audit (7.0 Gate)

Telethon E2E audit. Captures all Hot Tips pages + all My Matches detail cards.
Scores every card using Rubric v2. Verbatim card text mandatory.

Primary checks:
  BUILD-10: EV consistency (list EV must match detail EV)
  BUILD-11: Edge section team name (no "Back away" / "Back home")
  BUILD-12: Tier variety (10 list items must NOT all show same tier)

Usage:
    cd /home/paulsportsza/bot && .venv/bin/python tests/qa_baseline_13.py
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

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import (
    ReplyInlineMarkup,
    KeyboardButtonCallback,
    KeyboardButtonUrl,
)

# ── Config ──────────────────────────────────────────────

_env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
if os.path.exists(_env_path):
    with open(_env_path) as _ef:
        for _line in _ef:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _, _v = _line.partition("=")
                os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "")
BOT_USERNAME = "mzansiedge_bot"
STRING_SESSION_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "telethon_qa_session.string")
SESSION_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "telethon_qa_session")

TIMEOUT = 18
DETAIL_TIMEOUT = 25

REPORT_DIR = Path("/home/paulsportsza/reports")
EXPORT_DIR = REPORT_DIR / "b13-card-exports"


# ── Data classes ────────────────────────────────────────

@dataclass
class CardScore:
    match_name: str = ""
    sport: str = ""
    league: str = ""
    source: str = ""           # "hot_tips" or "my_matches"
    rendering_path: str = ""
    data_layer: int = 0
    data_layer_notes: str = ""
    rendering: int = 0
    rendering_notes: str = ""
    verdict_coherence: int = 0
    verdict_notes: str = ""
    copy_quality: int = 0
    copy_notes: str = ""
    total: int = 0
    card_text: str = ""
    evidence_sources: list = field(default_factory=list)
    list_ev: str = ""
    detail_ev: str = ""
    list_tier: str = ""
    detail_tier: str = ""
    build10_pass: bool = True   # EV consistency
    build11_pass: bool = True   # no "Back away" / "Back home"
    note: str = ""


@dataclass
class ListItem:
    """Parsed item from the Hot Tips list view."""
    index: int = 0
    teams: str = ""
    tier_emoji: str = ""
    tier_label: str = ""
    ev_pct: str = ""
    odds: str = ""
    bookmaker: str = ""
    callback_data: str = ""
    raw_line: str = ""


# ── Client ──────────────────────────────────────────────

async def get_client() -> TelegramClient:
    if os.path.exists(STRING_SESSION_FILE):
        s = open(STRING_SESSION_FILE).read().strip()
        if s:
            c = TelegramClient(StringSession(s), API_ID, API_HASH)
            await c.connect()
            if await c.is_user_authorized():
                return c
            await c.disconnect()
    c = TelegramClient(SESSION_FILE, API_ID, API_HASH)
    await c.connect()
    if not await c.is_user_authorized():
        print("ERROR: Not logged in.")
        sys.exit(1)
    return c


async def send_cmd(client, text, wait=TIMEOUT):
    entity = await client.get_entity(BOT_USERNAME)
    sent = await client.send_message(entity, text)
    await asyncio.sleep(wait)
    msgs = await client.get_messages(entity, limit=30)
    return [m for m in msgs if m.id > sent.id and not m.out]


async def fresh_click(client, callback_data: str, wait=TIMEOUT):
    entity = await client.get_entity(BOT_USERNAME)
    msgs = await client.get_messages(entity, limit=15)
    for msg in msgs:
        if not msg.reply_markup or not isinstance(msg.reply_markup, ReplyInlineMarkup):
            continue
        for row in msg.reply_markup.rows:
            for btn in row.buttons:
                if not isinstance(btn, KeyboardButtonCallback):
                    continue
                data = btn.data.decode() if isinstance(btn.data, bytes) else btn.data
                if data == callback_data or data.startswith(callback_data):
                    try:
                        await msg.click(data=btn.data)
                        await asyncio.sleep(wait)
                        fresh = await client.get_messages(entity, limit=10)
                        return fresh
                    except Exception as e:
                        if "Encrypted" in str(e) or "not modified" in str(e).lower():
                            try:
                                refetched = await client.get_messages(entity, ids=[msg.id])
                                if refetched and refetched[0]:
                                    await refetched[0].click(data=btn.data)
                                    await asyncio.sleep(wait)
                                    return await client.get_messages(entity, limit=10)
                            except Exception:
                                pass
                        raise
    return []


def extract_buttons(msg):
    btns = []
    if not msg or not msg.reply_markup:
        return btns
    if not isinstance(msg.reply_markup, ReplyInlineMarkup):
        return btns
    for row in msg.reply_markup.rows:
        for btn in row.buttons:
            if isinstance(btn, KeyboardButtonCallback):
                data = btn.data.decode() if isinstance(btn.data, bytes) else btn.data
                btns.append({"text": btn.text, "data": data})
            elif isinstance(btn, KeyboardButtonUrl):
                btns.append({"text": btn.text, "url": btn.url})
    return btns


# ── List Parsing ────────────────────────────────────────

def parse_list_items(text: str) -> list[ListItem]:
    """Parse Hot Tips list view into structured items."""
    items = []
    # Pattern: [N] emoji Teams tier_badge
    # Next line(s): league/kickoff/odds
    lines = text.split("\n")
    current = None
    for line in lines:
        # Match [N] pattern
        m = re.match(r'\[(\d+)\]\s*(.*)', line.strip())
        if m:
            if current:
                items.append(current)
            current = ListItem(index=int(m.group(1)), raw_line=line.strip())
            rest = m.group(2).strip()
            # Extract tier emoji at end
            for emoji, label in [("💎", "diamond"), ("🥇", "gold"), ("🥈", "silver"), ("🥉", "bronze")]:
                if emoji in rest:
                    current.tier_emoji = emoji
                    current.tier_label = label
                    rest = rest.replace(emoji, "").strip()
                    break
            # Remove sport emoji prefix
            rest = re.sub(r'^[⚽🏉🏏🥊]\s*', '', rest).strip()
            current.teams = rest
        elif current and "EV" in line:
            # Extract EV percentage
            ev_m = re.search(r'EV\s*\+?([\d.]+)%', line)
            if ev_m:
                current.ev_pct = ev_m.group(1)
            # Extract odds
            odds_m = re.search(r'@\s*([\d.]+)', line)
            if odds_m:
                current.odds = odds_m.group(1)
            # Extract bookmaker in parens
            bk_m = re.search(r'\(([^)]+)\)', line)
            if bk_m:
                current.bookmaker = bk_m.group(1)
    if current:
        items.append(current)
    return items


def extract_detail_ev(text: str) -> str:
    """Extract EV% from a detail card."""
    m = re.search(r'EV\s*[:\s]*\+?([\d.]+)%', text)
    if m:
        return m.group(1)
    m = re.search(r'expected value[:\s]*\+?([\d.]+)%', text, re.IGNORECASE)
    if m:
        return m.group(1)
    return ""


def extract_detail_tier(text: str) -> str:
    """Extract tier from detail card."""
    for emoji, label in [("💎", "diamond"), ("🥇", "gold"), ("🥈", "silver"), ("🥉", "bronze")]:
        if emoji in text:
            return label
    for label in ["DIAMOND", "GOLDEN", "SILVER", "BRONZE"]:
        if label in text:
            return label.lower().replace("golden", "gold")
    return ""


# ── Scoring (Rubric v2) ────────────────────────────────

def detect_sport(text, league_hint=""):
    t = (text + " " + league_hint).lower()
    if any(w in t for w in ("cricket", "ipl", "sa20", "t20", "innings", "wicket")):
        return "cricket"
    if any(w in t for w in ("rugby", "urc", "super rugby", "six nations", "try ")):
        return "rugby"
    if any(w in t for w in ("ufc", "mma", "boxing", "bout", "knockout")):
        return "combat"
    if any(w in t for w in ("epl", "psl", "champions league", "premier league",
                            "la liga", "serie a", "bundesliga", "ligue 1")):
        return "football"
    return "unknown"


def detect_league(text):
    m = re.search(r'🏆\s*(.+?)(?:\n|$)', text)
    if m:
        return m.group(1).strip()
    for lg in ["EPL", "Premier League", "PSL", "Champions League", "URC",
               "Super Rugby", "Six Nations", "IPL", "SA20", "T20", "Test",
               "UFC", "Boxing", "La Liga", "Serie A"]:
        if lg.lower() in text.lower():
            return lg
    return "unknown"


def detect_rendering_path(text):
    sections = ["📋", "🎯", "⚠️", "🏆"]
    present = sum(1 for s in sections if s in text)
    if present == 4:
        return "w84"
    if present >= 2:
        return "w82"
    return "template"


def detect_evidence(text):
    sources = []
    t = text.lower()
    if any(w in t for w in ("form", "wwl", "wdl", "wlw", "last 5", "streak")):
        sources.append("form")
    if any(w in t for w in ("standings", "position", "sits", "table", "points", "placed")):
        sources.append("standings")
    if any(w in t for w in ("head to head", "h2h", "meetings", "head-to-head")):
        sources.append("h2h")
    if any(w in t for w in ("injury", "injuries", "injured", "absent", "doubtful")):
        sources.append("injuries")
    if any(w in t for w in ("elo", "rating", "rated at")):
        sources.append("elo")
    if any(w in t for w in ("coach", "manager")):
        sources.append("coach")
    if any(w in t for w in ("odds", "bookmaker", "ev", "expected value", "price", "implied")):
        sources.append("odds")
    return sources


def score_data_layer(sources):
    if not sources or sources == ["odds"]:
        if "odds" in sources:
            return 1, "Odds only, no context data"
        return 0, "Empty"
    ctx = [s for s in sources if s != "odds"]
    if len(ctx) >= 3:
        return 3, f"Full: {', '.join(sources)}"
    if len(ctx) >= 1:
        return 2, f"Partial: {', '.join(sources)}"
    return 1, f"Minimal: {', '.join(sources)}"


def score_rendering(text, path):
    sections = ["📋", "🎯", "⚠️", "🏆"]
    present = sum(1 for s in sections if s in text)
    if present == 4:
        return 2, "Clean 4-section rendering"
    if present >= 2:
        return 1, f"{present}/4 sections present"
    return 0, f"Only {present} section markers"


def score_verdict(text, data_layer):
    max_v = 1 if data_layer == 0 else 2
    v_match = re.search(r'🏆.*', text, re.DOTALL)
    if not v_match:
        return min(0, max_v), "No verdict section"
    verdict = v_match.group().lower()
    refs = any(w in verdict for w in ("form", "standings", "elo", "ev", "probability",
                                       "expected value", "pricing"))
    if refs and data_layer >= 2:
        return min(2, max_v), "Verdict follows logically from evidence"
    return min(1, max_v), "Verdict is generic/safe"


def score_copy(text, data_layer, sport):
    max_c = 1 if data_layer == 0 else 3
    boilerplate = ["no data available", "form data unavailable",
                   "limited pre-match context", "numbers-only play"]
    if any(m in text.lower() for m in boilerplate):
        return min(0, max_c), "Boilerplate detected"

    sport_lang = False
    if sport == "football":
        sport_lang = any(w in text.lower() for w in ("clean sheet", "goal", "league", "derby"))
    elif sport == "rugby":
        sport_lang = any(w in text.lower() for w in ("try", "territory", "pack", "set-piece"))
    elif sport == "cricket":
        sport_lang = any(w in text.lower() for w in ("wicket", "innings", "runs", "bowling"))
    elif sport == "combat":
        sport_lang = any(w in text.lower() for w in ("fight", "bout", "knockout", "round"))

    has_stats = bool(re.search(r'\d+%|\d+\.\d+|\d+ points|\d+ wins', text))
    has_flow = len(text) > 400 and "📋" in text
    has_insight = any(w in text.lower() for w in ("interesting", "gap", "mispriced",
                                                    "divergence", "suggests", "momentum",
                                                    "advantage", "pressure", "crucial",
                                                    "shaped by", "driven by"))

    if has_flow and has_stats and sport_lang and has_insight and data_layer >= 2:
        return min(3, max_c), "Publication-quality with insights"
    if has_flow and (has_stats or sport_lang):
        return min(2, max_c), "Match-specific with good flow"
    if sport_lang or has_stats:
        return min(1, max_c), "Some sport-specific language"
    return min(0, max_c), "Generic"


def score_card(text, sport="unknown", league="unknown", source="unknown") -> CardScore:
    card = CardScore(card_text=text, sport=sport, league=league, source=source)
    m = re.search(r'🎯\s*(?:\*\*|<b>)?(.+?)(?:\*\*|</b>)?(?:\n|$)', text)
    if m:
        card.match_name = re.sub(r'</?b>|\*\*', '', m.group(1)).strip()

    card.rendering_path = detect_rendering_path(text)
    card.evidence_sources = detect_evidence(text)
    card.data_layer, card.data_layer_notes = score_data_layer(card.evidence_sources)
    card.rendering, card.rendering_notes = score_rendering(text, card.rendering_path)
    card.verdict_coherence, card.verdict_notes = score_verdict(text, card.data_layer)
    card.copy_quality, card.copy_notes = score_copy(text, card.data_layer, sport)
    card.total = card.data_layer + card.rendering + card.verdict_coherence + card.copy_quality

    # BUILD-11 check: no "Back away" / "Back home" in edge section
    edge_match = re.search(r'🎯(.*?)(?=⚠️|\Z)', text, re.DOTALL)
    if edge_match:
        edge_text = edge_match.group(1).lower()
        if "back away" in edge_text or "back home" in edge_text:
            card.build11_pass = False
            card.note += "BUILD-11 FAIL: 'Back away/home' in edge section. "

    # Extract detail-level EV and tier
    card.detail_ev = extract_detail_ev(text)
    card.detail_tier = extract_detail_tier(text)

    return card


# ── Capture Flow ────────────────────────────────────────

async def capture_hot_tips(client, entity):
    """Capture all Hot Tips pages + detail cards."""
    print("\n══════════════════════════════════════════")
    print("  HOT TIPS CAPTURE")
    print("══════════════════════════════════════════")

    print("\n  ▶ Opening Top Edge Picks...")
    msgs = await send_cmd(client, "💎 Top Edge Picks", wait=TIMEOUT)

    if not msgs:
        print("    ⚠ No response")
        return [], "", []

    # Capture list view text
    list_text = ""
    list_msg = None
    for msg in msgs:
        if msg.text and ("Edge Picks" in msg.text or "Live Edges" in msg.text or
                         "🔥" in (msg.text or "")):
            list_text = msg.text
            list_msg = msg
            break
    if not list_text and msgs:
        list_text = msgs[0].text or ""
        list_msg = msgs[0]

    print(f"    List captured ({len(list_text)} chars)")

    # Parse list items
    list_items = parse_list_items(list_text)
    print(f"    Parsed {len(list_items)} list items")
    for li in list_items:
        print(f"      [{li.index}] {li.teams} | {li.tier_emoji} {li.tier_label} | EV +{li.ev_pct}%")

    # Find all detail buttons and page buttons
    detail_datas = []
    page_datas = []
    for msg in msgs:
        for btn in extract_buttons(msg):
            d = btn.get("data", "")
            if d.startswith("edge:detail:"):
                detail_datas.append(d)
            elif d.startswith("hot:page:"):
                page_datas.append(d)

    print(f"    {len(detail_datas)} detail buttons, {len(page_datas)} page buttons")

    cards = []
    all_list_items = list(list_items)

    # Click each detail button on page 1
    for i, dd in enumerate(detail_datas):
        match_key = dd.replace("edge:detail:", "")
        print(f"\n    ▶ [{i+1}/{len(detail_datas)}] {match_key[:50]}...")

        try:
            result = await fresh_click(client, dd, wait=DETAIL_TIMEOUT)
            if not result:
                print(f"      ⚠ No response after click")
                continue

            detail_text = ""
            for m in result:
                if m.text and not m.out and ("📋" in m.text or "🎯" in m.text or
                                              "Signal Check" in m.text or
                                              "SA Bookmaker" in m.text):
                    detail_text = m.text
                    break

            # Check if list message was edited to detail
            if not detail_text and list_msg:
                try:
                    edited = await client.get_messages(entity, ids=[list_msg.id])
                    if edited and edited[0] and edited[0].text:
                        t = edited[0].text
                        if "📋" in t or "🎯" in t or "Signal Check" in t:
                            detail_text = t
                except Exception:
                    pass

            if not detail_text:
                print(f"      ⚠ No detail captured")
                continue

            league = detect_league(detail_text)
            sport = detect_sport(detail_text, league)
            card = score_card(detail_text, sport=sport, league=league, source="hot_tips")
            if not card.match_name:
                card.match_name = match_key.replace("_", " ").title()

            # BUILD-10: Match list EV to detail EV
            for li in list_items:
                # Fuzzy match by team names
                teams_lower = li.teams.lower().replace("vs", "").split()
                mk_lower = match_key.lower().replace("_", " ").split("20")[0]  # strip date
                if any(t in mk_lower for t in teams_lower if len(t) > 3):
                    card.list_ev = li.ev_pct
                    card.list_tier = li.tier_label
                    break

            if card.list_ev and card.detail_ev:
                if card.list_ev != card.detail_ev:
                    card.build10_pass = False
                    card.note += f"BUILD-10 FAIL: List EV +{card.list_ev}% != Detail EV +{card.detail_ev}%. "

            cards.append(card)
            print(f"      ✓ {card.match_name} [{sport}/{league}] = {card.total}/10")
            if not card.build10_pass:
                print(f"        ⚠ {card.note}")
            if not card.build11_pass:
                print(f"        ⚠ BUILD-11: Back away/home in edge section")

        except Exception as e:
            print(f"      ✗ {e}")

        # Navigate back
        await asyncio.sleep(2)
        await send_cmd(client, "💎 Top Edge Picks", wait=8)
        await asyncio.sleep(1)

    # Page 2+ if available
    for pg_idx, pg_data in enumerate(page_datas):
        print(f"\n    ▶ Checking page {pg_idx + 2}...")
        try:
            page_result = await fresh_click(client, pg_data, wait=12)
            if page_result:
                page_text = ""
                for m in page_result:
                    if m.text and ("Edge Picks" in m.text or "[" in m.text):
                        page_text = m.text
                        break
                if not page_text and page_result:
                    # Check edited message
                    try:
                        edited = await client.get_messages(entity, ids=[list_msg.id])
                        if edited and edited[0]:
                            page_text = edited[0].text or ""
                    except Exception:
                        pass

                if page_text:
                    pg_items = parse_list_items(page_text)
                    all_list_items.extend(pg_items)
                    print(f"      {len(pg_items)} items on page {pg_idx + 2}")
                    for li in pg_items:
                        print(f"        [{li.index}] {li.teams} | {li.tier_emoji} {li.tier_label}")

                    # Grab detail buttons from this page
                    pg_detail_datas = []
                    for m in page_result:
                        for btn in extract_buttons(m):
                            d = btn.get("data", "")
                            if d.startswith("edge:detail:") and d not in detail_datas:
                                pg_detail_datas.append(d)

                    # Click details on page 2
                    for j, dd in enumerate(pg_detail_datas):
                        mk = dd.replace("edge:detail:", "")
                        print(f"      ▶ [p{pg_idx+2}/{j+1}] {mk[:50]}...")
                        try:
                            r = await fresh_click(client, dd, wait=DETAIL_TIMEOUT)
                            dt = ""
                            if r:
                                for m in r:
                                    if m.text and not m.out and ("📋" in m.text or "🎯" in m.text):
                                        dt = m.text
                                        break
                            if not dt and list_msg:
                                try:
                                    edited = await client.get_messages(entity, ids=[list_msg.id])
                                    if edited and edited[0]:
                                        dt = edited[0].text or ""
                                except Exception:
                                    pass

                            if dt and ("📋" in dt or "🎯" in dt):
                                lg = detect_league(dt)
                                sp = detect_sport(dt, lg)
                                c = score_card(dt, sport=sp, league=lg, source="hot_tips")
                                if not c.match_name:
                                    c.match_name = mk.replace("_", " ").title()

                                for li in pg_items:
                                    teams_lower = li.teams.lower().replace("vs", "").split()
                                    mk_lower = mk.lower().replace("_", " ").split("20")[0]
                                    if any(t in mk_lower for t in teams_lower if len(t) > 3):
                                        c.list_ev = li.ev_pct
                                        c.list_tier = li.tier_label
                                        break

                                if c.list_ev and c.detail_ev:
                                    if c.list_ev != c.detail_ev:
                                        c.build10_pass = False
                                        c.note += f"BUILD-10 FAIL: List +{c.list_ev}% != Detail +{c.detail_ev}%. "

                                cards.append(c)
                                print(f"        ✓ {c.match_name} [{sp}/{lg}] = {c.total}/10")
                        except Exception as e:
                            print(f"        ✗ {e}")

                        await asyncio.sleep(2)
                        # Navigate back to the page
                        await fresh_click(client, pg_data, wait=8)
                        await asyncio.sleep(1)

        except Exception as e:
            print(f"      ⚠ Page error: {e}")

    return cards, list_text, all_list_items


async def capture_my_matches(client, entity):
    """Capture My Matches + detail cards."""
    print("\n══════════════════════════════════════════")
    print("  MY MATCHES CAPTURE")
    print("══════════════════════════════════════════")

    print("\n  ▶ Opening My Matches...")
    msgs = await send_cmd(client, "⚽ My Matches", wait=15)

    if not msgs:
        print("    ⚠ No response")
        return [], ""

    list_text = ""
    list_msg = None
    for msg in msgs:
        if msg.text and ("Matches" in msg.text or "matches" in msg.text.lower() or
                         "[" in msg.text):
            list_text = msg.text
            list_msg = msg
            break
    if not list_text and msgs:
        list_text = msgs[0].text or ""
        list_msg = msgs[0]

    print(f"    List captured ({len(list_text)} chars)")

    game_datas = []
    for msg in msgs:
        for btn in extract_buttons(msg):
            d = btn.get("data", "")
            if d.startswith("yg:game:"):
                game_datas.append((d, btn.get("text", "")))

    print(f"    {len(game_datas)} game buttons")

    cards = []
    for i, (gd, btn_text) in enumerate(game_datas):
        event_id = gd.replace("yg:game:", "")
        print(f"\n    ▶ [{i+1}/{len(game_datas)}] {event_id[:50]}...")

        try:
            result = await fresh_click(client, gd, wait=DETAIL_TIMEOUT)
            if not result:
                print(f"      ⚠ No response")
                continue

            detail_text = ""
            for m in result:
                if m.text and not m.out and ("📋" in m.text or "🎯" in m.text or
                                              "SA Bookmaker" in m.text):
                    detail_text = m.text
                    break

            if not detail_text and list_msg:
                try:
                    edited = await client.get_messages(entity, ids=[list_msg.id])
                    if edited and edited[0] and edited[0].text:
                        t = edited[0].text
                        if "📋" in t or "🎯" in t:
                            detail_text = t
                except Exception:
                    pass

            if not detail_text:
                print(f"      ⚠ No detail captured")
                continue

            league = detect_league(detail_text)
            sport = detect_sport(detail_text, league)
            card = score_card(detail_text, sport=sport, league=league, source="my_matches")
            if not card.match_name:
                card.match_name = event_id.replace("_", " ").title()
            cards.append(card)
            print(f"      ✓ {card.match_name} [{sport}/{league}] = {card.total}/10")

        except Exception as e:
            print(f"      ✗ {e}")

        await asyncio.sleep(2)
        await send_cmd(client, "⚽ My Matches", wait=8)
        await asyncio.sleep(1)

    return cards, list_text


# ── Main ────────────────────────────────────────────────

async def main():
    ts = datetime.now().strftime("%Y%m%d-%H%M")

    print("=" * 60)
    print("  QA-BASELINE-13 — Full Hot Tips + My Matches Audit")
    print(f"  {datetime.now().isoformat()}")
    print("=" * 60)

    client = await get_client()
    entity = await client.get_entity(BOT_USERNAME)

    # Capture Hot Tips
    ht_cards, ht_list_text, ht_list_items = await capture_hot_tips(client, entity)

    # Capture My Matches
    mm_cards, mm_list_text = await capture_my_matches(client, entity)

    await client.disconnect()

    all_cards = ht_cards + mm_cards

    # ── BUILD-12 check: tier variety ──
    build12_pass = True
    build12_note = ""
    if ht_list_items:
        tiers = [li.tier_label for li in ht_list_items if li.tier_label]
        unique_tiers = set(tiers)
        if len(tiers) >= 4 and len(unique_tiers) <= 1:
            build12_pass = False
            build12_note = f"BUILD-12 FAIL: All {len(tiers)} list items show same tier '{tiers[0]}'"
        else:
            build12_note = f"BUILD-12 PASS: {len(unique_tiers)} unique tiers among {len(tiers)} items: {dict((t, tiers.count(t)) for t in unique_tiers)}"
    else:
        build12_note = "BUILD-12: No list items parsed"

    # ── Negative EV check ──
    neg_ev_note = ""
    for card in all_cards:
        name_lower = card.match_name.lower()
        if ("everton" in name_lower and "liverpool" in name_lower) or \
           ("real madrid" in name_lower and "bayern" in name_lower):
            if card.detail_ev:
                try:
                    ev_val = float(card.detail_ev)
                    if ev_val <= 0:
                        neg_ev_note += f"NEG-EV CHECK: {card.match_name} correctly suppressed (EV={ev_val}%). "
                    else:
                        neg_ev_note += f"NEG-EV WARNING: {card.match_name} showing with EV +{ev_val}% (should be suppressed if EV<=0). "
                except ValueError:
                    pass
    if not neg_ev_note:
        neg_ev_note = "NEG-EV: Everton vs Liverpool and Real Madrid vs Bayern not present in live edges — naturally suppressed."

    # ── Export cards ──
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)

    # Save list views
    (EXPORT_DIR / "list_view_hot_tips.txt").write_text(ht_list_text)
    (EXPORT_DIR / "list_view_my_matches.txt").write_text(mm_list_text)

    # Save individual cards
    for i, card in enumerate(all_cards, 1):
        safe_name = re.sub(r'[^a-zA-Z0-9_]', '_', card.match_name[:40])
        fname = f"card_{i:02d}_{card.source}_{safe_name}.txt"
        (EXPORT_DIR / fname).write_text(card.card_text)

    # ── Compute scores ──
    total_score = sum(c.total for c in all_cards)
    max_possible = len(all_cards) * 10
    avg_score = total_score / len(all_cards) if all_cards else 0

    build10_fails = [c for c in all_cards if not c.build10_pass]
    build11_fails = [c for c in all_cards if not c.build11_pass]

    # ── Print summary ──
    print("\n" + "=" * 60)
    print("  RESULTS")
    print("=" * 60)
    print(f"\n  Cards scored: {len(all_cards)}")
    print(f"    Hot Tips: {len(ht_cards)}")
    print(f"    My Matches: {len(mm_cards)}")
    print(f"\n  B13 Overall: {avg_score:.2f}/10 ({total_score}/{max_possible})")
    print(f"\n  BUILD-10 (EV consistency): {len(build10_fails)} failures")
    for c in build10_fails:
        print(f"    ⚠ {c.match_name}: List +{c.list_ev}% vs Detail +{c.detail_ev}%")
    print(f"\n  BUILD-11 (no 'Back away/home'): {len(build11_fails)} failures")
    for c in build11_fails:
        print(f"    ⚠ {c.match_name}")
    print(f"\n  BUILD-12 (tier variety): {'PASS' if build12_pass else 'FAIL'}")
    print(f"    {build12_note}")
    print(f"\n  Negative EV: {neg_ev_note}")

    # Per-card table
    print("\n  Per-Card Scores:")
    print(f"  {'#':>3} {'Match':<45} {'Source':<10} {'DL':>3} {'RN':>3} {'VC':>3} {'CQ':>3} {'Tot':>4}")
    print("  " + "-" * 80)
    for i, c in enumerate(all_cards, 1):
        print(f"  {i:>3} {c.match_name[:44]:<45} {c.source[:9]:<10} {c.data_layer:>3} {c.rendering:>3} {c.verdict_coherence:>3} {c.copy_quality:>3} {c.total:>4}")

    # ── Save JSON report ──
    report = {
        "audit": "QA-BASELINE-13",
        "timestamp": datetime.now().isoformat(),
        "overall_score": round(avg_score, 2),
        "total_cards": len(all_cards),
        "total_score": total_score,
        "max_possible": max_possible,
        "build10_pass": len(build10_fails) == 0,
        "build10_fails": len(build10_fails),
        "build11_pass": len(build11_fails) == 0,
        "build11_fails": len(build11_fails),
        "build12_pass": build12_pass,
        "build12_note": build12_note,
        "neg_ev_note": neg_ev_note,
        "cards": [],
    }
    for c in all_cards:
        report["cards"].append({
            "match": c.match_name,
            "sport": c.sport,
            "league": c.league,
            "source": c.source,
            "path": c.rendering_path,
            "DL": c.data_layer, "DL_notes": c.data_layer_notes,
            "RN": c.rendering, "RN_notes": c.rendering_notes,
            "VC": c.verdict_coherence, "VC_notes": c.verdict_notes,
            "CQ": c.copy_quality, "CQ_notes": c.copy_notes,
            "total": c.total,
            "list_ev": c.list_ev, "detail_ev": c.detail_ev,
            "list_tier": c.list_tier, "detail_tier": c.detail_tier,
            "build10_pass": c.build10_pass,
            "build11_pass": c.build11_pass,
            "evidence": c.evidence_sources,
            "note": c.note,
            "card_text": c.card_text,
        })

    report_path = REPORT_DIR / f"qa-baseline-13-{ts}.json"
    report_path.write_text(json.dumps(report, indent=2))
    print(f"\n  JSON report: {report_path}")

    # Return data for report generation
    return report, ht_list_text, mm_list_text, all_cards, ht_list_items


if __name__ == "__main__":
    report, ht_list, mm_list, cards, list_items = asyncio.run(main())
