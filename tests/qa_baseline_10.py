"""QA-BASELINE-10 — Full sport quality audit via Telethon E2E.

Connects as a real user to @mzansiedge_bot and captures narrative cards
across all sports. Outputs per-card scoresheets + full card exports.

Usage:
    cd /home/paulsportsza/bot && .venv/bin/python tests/qa_baseline_10.py
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
SESSION_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "telethon_qa_session")
STRING_SESSION_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "telethon_qa_session.string")

TIMEOUT = 18
DETAIL_TIMEOUT = 25

REPORT_DIR = Path("/home/paulsportsza/reports")
EXPORT_DIR = REPORT_DIR / "b10-card-exports"


# ── Data classes ────────────────────────────────────────

@dataclass
class CardScore:
    match_name: str = ""
    sport: str = ""
    league: str = ""
    source: str = ""
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
    note: str = ""


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
    """Send a text command and return bot responses."""
    entity = await client.get_entity(BOT_USERNAME)
    sent = await client.send_message(entity, text)
    await asyncio.sleep(wait)
    msgs = await client.get_messages(entity, limit=30)
    return [m for m in msgs if m.id > sent.id and not m.out]


async def fresh_click(client, callback_data: str, wait=TIMEOUT):
    """Click an inline button by callback data, using fresh message fetch.

    Avoids 'Encrypted data invalid' by always working with the latest
    message that contains the target button.
    """
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
                        # Re-fetch to get the edited/new message
                        fresh = await client.get_messages(entity, limit=10)
                        return fresh
                    except Exception as e:
                        if "Encrypted" in str(e) or "not modified" in str(e).lower():
                            # Try re-fetching the message by ID and clicking again
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
    """Extract inline buttons from a message."""
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


# ── Scoring ─────────────────────────────────────────────

def detect_sport(text, league_hint=""):
    t = (text + " " + league_hint).lower()
    # Cricket first (test cricket could match "test" in other sports)
    if any(w in t for w in ("cricket", "ipl", "sa20", "t20", "innings", "wicket",
                            "bowling", "batting", "over rate", "nrr", "run rate")):
        return "cricket"
    if any(w in t for w in ("rugby", "urc", "super rugby", "six nations", "try ",
                            "scrum", "lineout", "ruck", "maul")):
        return "rugby"
    if any(w in t for w in ("ufc", "mma", "boxing", "bout", "knockout", "fighter",
                            "round ", "octagon", "ring")):
        return "combat"
    if any(w in t for w in ("epl", "psl", "champions league", "soccer", "premier league",
                            "la liga", "serie a", "bundesliga", "ligue 1")):
        return "football"
    # Test series could be cricket
    if "test series" in t or "test match" in t:
        return "cricket"
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
    if "SA Bookmaker Odds:" in text or "Bookmaker Odds" in text:
        return "w84"
    return "template"


def detect_evidence(text):
    sources = []
    t = text.lower()
    if any(w in t for w in ("form", "wwl", "wdl", "wlw", "last 5", "streak", "consecutive")):
        sources.append("form")
    if any(w in t for w in ("standings", "position", "sits", "table", "points", "placed")):
        sources.append("standings")
    if any(w in t for w in ("head to head", "h2h", "meetings", "previous encounter",
                            "head-to-head")):
        sources.append("h2h")
    if any(w in t for w in ("injury", "injuries", "injured", "absent", "doubtful",
                            "questionable", "missing")):
        sources.append("injuries")
    if any(w in t for w in ("elo", "rating", "rated at")):
        sources.append("elo")
    if any(w in t for w in ("coach", "manager")):
        sources.append("coach")
    if any(w in t for w in ("tipster", "consensus", "prediction source")):
        sources.append("tipster")
    if any(w in t for w in ("odds", "bookmaker", "ev", "expected value", "price", "implied")):
        sources.append("odds")
    return sources


def score_data_layer(sources):
    if not sources or sources == ["odds"]:
        if "odds" in sources:
            return 1, "Odds only, no context data"
        return 0, "Empty — no match-specific data"
    ctx = [s for s in sources if s != "odds"]
    if len(ctx) >= 3:
        return 3, f"Full: {', '.join(sources)}"
    if len(ctx) >= 1:
        return 2, f"Partial: {', '.join(sources)}"
    return 1, f"Minimal: {', '.join(sources)}"


def score_rendering(text, path):
    if path == "template":
        if len(text) > 200 and "📋" not in text:
            return 0, "Wrong path — should use narrative renderer"
        return 1, "Template path, acceptable"
    sections = ["📋", "🎯", "⚠️", "🏆"]
    present = sum(1 for s in sections if s in text)
    if present == 4:
        if text.count("📋") > 1:
            return 1, "Correct path but duplicate headers"
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
    e_match = re.search(r'🎯.*?(?=⚠️|\Z)', text, re.DOTALL)
    edge = e_match.group().lower() if e_match else ""
    is_thin = any(w in edge for w in ("speculative", "thin", "limited", "no confirm",
                                       "no supporting"))
    has_speculative = "speculative" in verdict
    has_back = any(w in verdict for w in ("back", "punt", "bet on", "take the"))
    refs = any(w in verdict for w in ("form", "standings", "elo", "ev", "probability",
                                       "expected value", "pricing"))
    if refs and data_layer >= 2:
        return min(2, max_v), "Verdict follows logically from evidence"
    if has_back and is_thin and has_speculative:
        return min(1, max_v), "Speculative verdict, appropriate for thin data"
    if has_back and is_thin and not has_speculative:
        return min(1, max_v), "Backs bet but edge is thin"
    return min(1, max_v), "Verdict is generic/safe"


def score_copy(text, data_layer, sport):
    max_c = 1 if data_layer == 0 else 3
    boilerplate = ["no data available", "form data unavailable",
                   "limited pre-match context", "numbers-only play"]
    if any(m in text.lower() for m in boilerplate):
        return min(0, max_c), "Boilerplate detected"

    sport_lang = False
    if sport == "football":
        sport_lang = any(w in text.lower() for w in ("clean sheet", "goal", "league table"))
    elif sport == "rugby":
        sport_lang = any(w in text.lower() for w in ("try", "territory", "pack", "set-piece"))
    elif sport == "cricket":
        sport_lang = any(w in text.lower() for w in ("wicket", "innings", "runs", "bowling",
                                                       "batting", "over", "conditions", "tempo"))
    elif sport == "combat":
        sport_lang = any(w in text.lower() for w in ("fight", "bout", "knockout", "round",
                                                       "striking"))
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


def score_card(text, sport="unknown", league="unknown", source="unknown"):
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
    return card


# ── Audit Flow ──────────────────────────────────────────

async def capture_detail_from_tips(client, entity):
    """Open Hot Tips, then sequentially click each detail button."""
    print("\n  ▶ Opening Top Edge Picks...")
    msgs = await send_cmd(client, "💎 Top Edge Picks", wait=TIMEOUT)

    if not msgs:
        print("    ⚠ No response")
        return [], ""

    # Capture the list view text
    list_text = ""
    list_msg_id = None
    for msg in msgs:
        if msg.text and ("Edge Picks" in msg.text or "Live Edges" in msg.text):
            list_text = msg.text
            list_msg_id = msg.id
            break
    if not list_text and msgs:
        list_text = msgs[0].text or ""
        list_msg_id = msgs[0].id

    print(f"    List: {list_text[:80]}...")

    # Find detail button data from the list message
    detail_datas = []
    for msg in msgs:
        for btn in extract_buttons(msg):
            d = btn.get("data", "")
            if d.startswith("edge:detail:"):
                detail_datas.append(d)

    # Also check for paginated views (hot:page:)
    page_datas = []
    for msg in msgs:
        for btn in extract_buttons(msg):
            d = btn.get("data", "")
            if d.startswith("hot:page:"):
                page_datas.append(d)

    print(f"    Found {len(detail_datas)} detail buttons, {len(page_datas)} page buttons")

    cards = []

    # Click each detail button sequentially
    for i, dd in enumerate(detail_datas):
        match_key = dd.replace("edge:detail:", "")
        print(f"    ▶ [{i+1}/{len(detail_datas)}] {match_key[:50]}...")

        try:
            result = await fresh_click(client, dd, wait=DETAIL_TIMEOUT)
            if not result:
                print(f"      ⚠ No response after click")
                continue

            # Find the detail text in results
            detail_text = ""
            for m in result:
                if m.text and not m.out and ("📋" in m.text or "🎯" in m.text or
                                              "SA Bookmaker" in m.text or
                                              "Signal Check" in m.text):
                    detail_text = m.text
                    break

            # Also check if original message was edited
            if not detail_text and list_msg_id:
                try:
                    edited = await client.get_messages(entity, ids=[list_msg_id])
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
            cards.append(card)
            print(f"      ✓ {card.match_name} [{sport}/{league}] = {card.total}/10")

        except Exception as e:
            print(f"      ✗ {e}")

        # Navigate back by sending the command fresh
        await asyncio.sleep(2)
        await send_cmd(client, "💎 Top Edge Picks", wait=8)
        await asyncio.sleep(1)

    # Check additional pages
    if page_datas and len(cards) < 8:
        print(f"\n    ▶ Checking page 2...")
        try:
            page_result = await fresh_click(client, page_datas[0], wait=12)
            if page_result:
                for m in page_result:
                    for btn in extract_buttons(m):
                        d = btn.get("data", "")
                        if d.startswith("edge:detail:") and d not in detail_datas:
                            detail_datas.append(d)

                # Score additional page details
                for dd in detail_datas[len(cards):]:
                    mk = dd.replace("edge:detail:", "")
                    print(f"    ▶ [p2] {mk[:50]}...")
                    try:
                        r = await fresh_click(client, dd, wait=DETAIL_TIMEOUT)
                        dt = ""
                        if r:
                            for m in r:
                                if m.text and not m.out and ("📋" in m.text or "🎯" in m.text):
                                    dt = m.text
                                    break
                        if dt:
                            lg = detect_league(dt)
                            sp = detect_sport(dt, lg)
                            c = score_card(dt, sport=sp, league=lg, source="hot_tips")
                            if not c.match_name:
                                c.match_name = mk.replace("_", " ").title()
                            cards.append(c)
                            print(f"      ✓ {c.match_name} [{sp}/{lg}] = {c.total}/10")
                    except Exception as e:
                        print(f"      ✗ {e}")
                    await asyncio.sleep(2)
                    await send_cmd(client, "💎 Top Edge Picks", wait=8)
                    await asyncio.sleep(1)
        except Exception as e:
            print(f"    ⚠ Page 2 error: {e}")

    return cards, list_text


async def capture_detail_from_matches(client, entity):
    """Open My Matches and click game buttons for breakdowns."""
    print("\n  ▶ Opening My Matches...")
    msgs = await send_cmd(client, "⚽ My Matches", wait=15)

    if not msgs:
        print("    ⚠ No response")
        return [], ""

    list_text = ""
    list_msg_id = None
    for msg in msgs:
        if msg.text and ("My Matches" in msg.text or "matches" in msg.text.lower()):
            list_text = msg.text
            list_msg_id = msg.id
            break
    if not list_text and msgs:
        list_text = msgs[0].text or ""
        list_msg_id = msgs[0].id

    print(f"    List: {list_text[:100]}...")

    game_datas = []
    sport_filter_datas = []
    for msg in msgs:
        for btn in extract_buttons(msg):
            d = btn.get("data", "")
            if d.startswith("yg:game:"):
                game_datas.append((d, btn.get("text", "")))
            elif d.startswith("yg:sport:") or d.startswith("yg:all:"):
                sport_filter_datas.append((d, btn.get("text", "")))

    print(f"    Found {len(game_datas)} game buttons, {len(sport_filter_datas)} filter buttons")

    cards = []

    # Click game buttons from default view
    for i, (gd, gt) in enumerate(game_datas[:5]):
        print(f"    ▶ [{i+1}] {gt[:50]}...")
        try:
            result = await fresh_click(client, gd, wait=DETAIL_TIMEOUT)
            dt = ""
            if result:
                for m in result:
                    if m.text and not m.out and len(m.text) > 80:
                        dt = m.text
                        break
            if not dt and list_msg_id:
                try:
                    edited = await client.get_messages(entity, ids=[list_msg_id])
                    if edited and edited[0] and edited[0].text and len(edited[0].text) > 80:
                        dt = edited[0].text
                except Exception:
                    pass

            if dt:
                lg = detect_league(dt)
                sp = detect_sport(dt, lg)
                card = score_card(dt, sport=sp, league=lg, source="my_matches")
                if not card.match_name:
                    card.match_name = gt
                cards.append(card)
                print(f"      ✓ {card.match_name} [{sp}/{lg}] = {card.total}/10")
            else:
                print(f"      ⚠ No detail captured")

        except Exception as e:
            print(f"      ✗ {e}")

        await asyncio.sleep(2)
        # Navigate back by re-sending My Matches
        await send_cmd(client, "⚽ My Matches", wait=8)
        await asyncio.sleep(1)

    # Try sport filters to get cricket/rugby/combat cards
    for fd, ft in sport_filter_datas:
        if "yg:all:" in fd:
            continue
        sport_emoji = ft.strip()
        print(f"\n    ▶ Sport filter: {sport_emoji}")
        try:
            result = await fresh_click(client, fd, wait=12)
            sport_game_datas = []
            if result:
                for m in result:
                    for btn in extract_buttons(m):
                        d = btn.get("data", "")
                        if d.startswith("yg:game:") and d not in [g for g, _ in game_datas]:
                            sport_game_datas.append((d, btn.get("text", "")))

            if not sport_game_datas and result:
                # Check edited message
                for m in result:
                    if m.text and not m.out:
                        for btn in extract_buttons(m):
                            d = btn.get("data", "")
                            if d.startswith("yg:game:"):
                                sport_game_datas.append((d, btn.get("text", "")))

            print(f"      Found {len(sport_game_datas)} games in this sport")

            for j, (sgd, sgt) in enumerate(sport_game_datas[:3]):
                print(f"      ▶ [{j+1}] {sgt[:50]}...")
                try:
                    sr = await fresh_click(client, sgd, wait=DETAIL_TIMEOUT)
                    sdt = ""
                    if sr:
                        for m in sr:
                            if m.text and not m.out and len(m.text) > 80:
                                sdt = m.text
                                break
                    if sdt:
                        lg = detect_league(sdt)
                        sp = detect_sport(sdt, lg)
                        card = score_card(sdt, sport=sp, league=lg, source="my_matches")
                        if not card.match_name:
                            card.match_name = sgt
                        cards.append(card)
                        print(f"        ✓ {card.match_name} [{sp}/{lg}] = {card.total}/10")
                    else:
                        print(f"        ⚠ No detail captured")
                except Exception as e:
                    print(f"        ✗ {e}")
                await asyncio.sleep(2)
                await send_cmd(client, "⚽ My Matches", wait=8)
                await asyncio.sleep(1)

        except Exception as e:
            print(f"      ✗ Filter error: {e}")

        await asyncio.sleep(2)
        await send_cmd(client, "⚽ My Matches", wait=8)
        await asyncio.sleep(1)

    return cards, list_text


async def check_evidence_providers():
    """Check evidence provider status from DB."""
    import sqlite3
    conn = sqlite3.connect("/home/paulsportsza/scrapers/odds.db")
    cur = conn.cursor()

    results = {}

    # Check narrative cache for evidence_json
    cur.execute("""SELECT match_id, edge_tier, evidence_json, narrative_source, created_at
                   FROM narrative_cache ORDER BY rowid DESC LIMIT 20""")
    rows = cur.fetchall()
    for r in rows:
        match_id, tier, ev_json, source, created = r
        sport = "unknown"
        if any(w in match_id for w in ("rugby", "bulls", "sharks", "stormers")):
            sport = "rugby"
        elif any(w in match_id for w in ("ipl", "sa20", "cricket")):
            sport = "cricket"
        elif any(w in match_id for w in ("ufc", "boxing")):
            sport = "combat"
        else:
            sport = "football"

        ev_data = None
        if ev_json:
            try:
                ev_data = json.loads(ev_json)
            except Exception:
                pass

        results[match_id] = {
            "sport": sport,
            "tier": tier,
            "source": source,
            "has_evidence": ev_data is not None,
            "evidence_keys": list(ev_data.keys()) if ev_data and isinstance(ev_data, dict) else [],
            "created": created,
        }

    # Check odds coverage by sport
    cur.execute("""SELECT league, COUNT(DISTINCT match_id), COUNT(DISTINCT bookmaker)
                   FROM odds_snapshots WHERE scraped_at > datetime('now', '-24 hours')
                   GROUP BY league ORDER BY league""")
    odds_coverage = {}
    for r in cur.fetchall():
        odds_coverage[r[0]] = {"matches": r[1], "bookmakers": r[2]}

    conn.close()
    return results, odds_coverage


async def run_audit():
    """Main audit runner."""
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("  QA-BASELINE-10 — Full Sport Quality Audit")
    print(f"  Date: {datetime.now().strftime('%Y-%m-%d %H:%M SAST')}")
    print("  Method: Telethon E2E against live @mzansiedge_bot")
    print("=" * 60)

    client = await get_client()
    entity = await client.get_entity(BOT_USERNAME)
    all_cards: list[CardScore] = []

    # Phase 1: Hot Tips
    print("\n" + "─" * 60)
    print("  PHASE 1: Hot Tips Detail Cards")
    print("─" * 60)
    ht_cards, ht_list = await capture_detail_from_tips(client, entity)
    all_cards.extend(ht_cards)

    # Phase 2: My Matches
    print("\n" + "─" * 60)
    print("  PHASE 2: My Matches Game Breakdowns")
    print("─" * 60)
    mm_cards, mm_list = await capture_detail_from_matches(client, entity)
    all_cards.extend(mm_cards)

    # Phase 3: Evidence Providers
    print("\n" + "─" * 60)
    print("  PHASE 3: Evidence Provider Status")
    print("─" * 60)
    ev_results, odds_cov = await check_evidence_providers()

    for league, cov in sorted(odds_cov.items()):
        print(f"    {league:25s}: {cov['matches']:>3d} matches, {cov['bookmakers']:>2d} bookmakers")

    print(f"\n    Narrative cache (recent 20):")
    for mid, info in list(ev_results.items())[:10]:
        print(f"      [{info['sport']:10s}] {mid[:40]:40s} tier={info['tier']:<8s} "
              f"evidence={'yes' if info['has_evidence'] else 'no':3s} src={info['source']}")

    await client.disconnect()

    # ── Export cards ────────────────────────────────────
    for i, card in enumerate(all_cards):
        safe_name = re.sub(r'[^\w\s-]', '', card.match_name)[:30].replace(' ', '_')
        export_path = EXPORT_DIR / f"card_{i+1:02d}_{card.sport}_{safe_name}.txt"
        export_path.write_text(card.card_text, encoding="utf-8")

    # Save list views
    (EXPORT_DIR / "list_view_hot_tips.txt").write_text(ht_list or "(empty)", encoding="utf-8")
    (EXPORT_DIR / "list_view_my_matches.txt").write_text(mm_list or "(empty)", encoding="utf-8")

    # ── Score Summary ──────────────────────────────────
    print("\n" + "=" * 60)
    print("  SCORE SUMMARY")
    print("=" * 60)

    if not all_cards:
        print("  ⚠ No cards scored!")
        return {}

    overall = sum(c.total for c in all_cards) / len(all_cards)

    sport_groups = {}
    for c in all_cards:
        sport_groups.setdefault(c.sport, []).append(c)

    print(f"\n  B10 OVERALL: {overall:.2f}/10 ({len(all_cards)} cards)")
    print(f"\n  By sport:")
    for sport, cards in sorted(sport_groups.items()):
        avg = sum(c.total for c in cards) / len(cards)
        print(f"    {sport:20s}: {avg:.2f}/10 ({len(cards)} cards)")

    print(f"\n  B09 comparison: 8.82 → {overall:.2f} (delta: {overall - 8.82:+.2f})")

    # Per-card scoresheet
    print("\n" + "─" * 60)
    print("  PER-CARD SCORESHEET")
    print("─" * 60)
    hdr = f"  {'#':>3s} {'Match':40s} {'Sport':10s} {'League':15s} {'Path':6s} {'DL':>2s} {'RN':>2s} {'VC':>2s} {'CQ':>2s} {'TOT':>3s}"
    print(hdr)
    print("  " + "─" * len(hdr))
    for i, c in enumerate(all_cards):
        print(f"  {i+1:3d} {c.match_name[:40]:40s} {c.sport:10s} {c.league[:15]:15s} "
              f"{c.rendering_path:6s} {c.data_layer:2d} {c.rendering:2d} "
              f"{c.verdict_coherence:2d} {c.copy_quality:2d} {c.total:3d}")
        print(f"      DL: {c.data_layer_notes}")
        print(f"      RN: {c.rendering_notes}")
        print(f"      VC: {c.verdict_notes}")
        print(f"      CQ: {c.copy_notes}")
        print(f"      Evidence: {', '.join(c.evidence_sources) if c.evidence_sources else 'none'}")
        print()

    # Defect list
    print("─" * 60)
    print("  DEFECT LIST")
    print("─" * 60)
    defects = []
    for c in all_cards:
        if c.data_layer == 0:
            defects.append(("P0", c.match_name, "Empty data layer — no evidence"))
        if c.rendering == 0:
            defects.append(("P1", c.match_name, f"Wrong rendering path: {c.rendering_notes}"))
        if c.total <= 3:
            defects.append(("P1", c.match_name, f"Low quality score: {c.total}/10"))
        if c.copy_quality == 0:
            defects.append(("P2", c.match_name, f"Generic copy: {c.copy_notes}"))

    # Check sport coverage
    covered_sports = set(c.sport for c in all_cards)
    for req_sport in ["football", "rugby", "cricket", "combat"]:
        if req_sport not in covered_sports:
            defects.append(("P1", f"({req_sport})", f"No {req_sport} cards captured in audit"))

    if len(all_cards) < 15:
        defects.append(("P1", "(audit)", f"Only {len(all_cards)} cards scored (minimum: 15)"))

    for sev, match, desc in sorted(defects, key=lambda x: x[0]):
        print(f"    [{sev}] {match[:35]:35s} — {desc}")

    if not defects:
        print("    No defects found")

    # JSON export
    summary = {
        "baseline": "B10",
        "date": datetime.now().isoformat(),
        "method": "Telethon E2E",
        "overall_score": round(overall, 2),
        "card_count": len(all_cards),
        "b09_score": 8.82,
        "delta": round(overall - 8.82, 2),
        "by_sport": {
            sport: {"score": round(sum(c.total for c in cards) / len(cards), 2), "count": len(cards)}
            for sport, cards in sport_groups.items()
        },
        "evidence_providers": {
            league: {"matches": cov["matches"], "bookmakers": cov["bookmakers"]}
            for league, cov in odds_cov.items()
        },
        "cards": [
            {
                "match": c.match_name, "sport": c.sport, "league": c.league,
                "source": c.source, "path": c.rendering_path,
                "data_layer": c.data_layer, "rendering": c.rendering,
                "verdict": c.verdict_coherence, "copy": c.copy_quality,
                "total": c.total, "evidence": c.evidence_sources,
                "notes": {"dl": c.data_layer_notes, "rn": c.rendering_notes,
                           "vc": c.verdict_notes, "cq": c.copy_notes},
            }
            for c in all_cards
        ],
        "defects": [{"severity": s, "match": m, "description": d} for s, m, d in defects],
    }

    json_path = REPORT_DIR / "b10_summary.json"
    json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\n  JSON: {json_path}")
    print(f"  Exports: {EXPORT_DIR}/")

    return summary


if __name__ == "__main__":
    asyncio.run(run_audit())
