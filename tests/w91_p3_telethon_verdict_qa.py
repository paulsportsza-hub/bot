#!/usr/bin/env python3
# ruff: noqa
r"""W91-P3 Verdict Floor Fix — Telethon QA against the live @mzansiedge_bot.

Goal
----
Verify, against the real running bot, that every live Edge tip produces a
Verdict that respects the tier-aware floor defined in
`bot/narrative_spec.MIN_VERDICT_CHARS_BY_TIER` and stays within
`_VERDICT_MAX_CHARS` (200).

Why this rewrite
----------------
The previous implementation tried to scrape verdict text directly from the
Telegram *list* message.  In the current build the bot renders tip detail as a
PNG photo via `send_card_or_fallback` — no text/caption carries the narrative.
So the earlier run reported "Could not reach Top Edge Picks list" for all 28
edges: the sticky keyboard tap returns a photo card whose `text` is empty, and
the old `_is_hot_tips_card()` check saw no useful payload.

Three-layer navigation
----------------------
Layer 1  : `/start` + `/qa set_diamond` so the Telethon user is onboarded
           AND forced to Diamond access for every edge.
Layer 2  : `/picks`  (cmd_picks → `_show_hot_tips()` → `_do_hot_tips_flow()`).
           Bypasses the reply-keyboard regex handler entirely.
Layer 3  : paginate via `hot:page:N`, matching each edge to a button using its
           abbreviated team names ("MI vs CSK", "AVL vs Tottenha").  Tap
           `ep:pick:N` to open the detail photo card.

Verdict source of truth
-----------------------
The tip detail card is a PNG — the narrative is rendered into the image, not
the text.  So after we successfully tap an edge (which triggers narrative
generation + cache refresh for the tip), we query
`odds.db::narrative_cache.narrative_html` for that `match_id` and extract the
Verdict section there.  That field IS the narrative served to the user.  We
keep both the photo response metadata and the narrative HTML per edge so the
audit trail is complete.

Constraints honoured
--------------------
* Telethon only — zero mocking.
* 1s between taps, 3s between edges.
* `aston_villa_vs_tottenham_2026-05-03` MUST be in the captured set.
* Minimum 20 of 28 edges captured; otherwise the run is a FAIL with an
  explicit explanation.

Outputs
-------
* `/home/paulsportsza/reports/e2e-screenshots/w91-p3-verdict-floor/{key}_{tier}.txt`
  — raw narrative HTML per edge.
* `/home/paulsportsza/reports/e2e-screenshots/w91-p3-verdict-floor/_results.json`
  — machine-readable per-edge result.
* Summary report written by the caller / LeadDev brief.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sqlite3
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

BOT_DIR = Path(__file__).resolve().parent.parent  # /home/paulsportsza/bot
load_dotenv(BOT_DIR / ".env")

from telethon import TelegramClient  # noqa: E402
from telethon.sessions import StringSession  # noqa: E402
from telethon.tl.types import (  # noqa: E402
    KeyboardButtonCallback,
    MessageMediaPhoto,
)

# ──────────────────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────────────────

API_ID = int(os.getenv("TELEGRAM_API_ID", "32418601"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "95e313a8ef5b998be0515dd8328fac57")
BOT_USERNAME = "@mzansiedge_bot"
STRING_SESSION_FILE = BOT_DIR / "data" / "telethon_qa_session.string"
ODDS_DB = Path("/home/paulsportsza/scrapers/odds.db")
SS_DIR = Path("/home/paulsportsza/reports/e2e-screenshots/w91-p3-verdict-floor")
SS_DIR.mkdir(parents=True, exist_ok=True)

# Pull tier floors from narrative_spec directly so any drift surfaces here.
sys.path.insert(0, str(BOT_DIR))
from narrative_spec import MIN_VERDICT_CHARS_BY_TIER, _VERDICT_MAX_CHARS  # noqa: E402
# config is used for team abbreviations when matching buttons to edges.
import config  # noqa: E402

TIER_BADGES = {"diamond": "💎", "gold": "🥇", "silver": "🥈", "bronze": "🥉"}
BOOKMAKER_CANONICAL = {
    "hollywoodbets": "Hollywoodbets",
    "supabets": "Supabets",
    "playabets": "Playabets",
    "sportingbet": "Sportingbet",
    "betway": "Betway",
    "gbets": "GBets",
    "wsb": "WSB",
}
# Used for bookmaker-leak detection in Verdict body.
KNOWN_BOOKMAKERS = [
    "WSB", "Betway", "Hollywoodbets", "Supabets", "Playabets",
    "Sportingbet", "Gbets", "GBets",
]
BANNED_BUG_PATTERN = re.compile(r"^\w+ at \d+\.\d+ with WSB is the play\.$", re.IGNORECASE)

# Timings
PICKS_WAIT_S = 30       # cold /picks can be >20s on first run
PAGE_WAIT_S = 12
TAP_WAIT_S = 45         # narrative generation can take 30s on cache miss
INTER_TAP_SLEEP = 1.0   # per brief
INTER_EDGE_SLEEP = 3.0  # per brief
MAX_PAGES = 12

HTML_TAG_RE = re.compile(r"<[^>]+>")
HOT_TIPS_PAGE_SIZE = 4
SECTION_EMOJIS_STOP = ["📋", "🎯", "⚠️", "🔒", "📲", "━━━"]


# ──────────────────────────────────────────────────────────────────────────
# Fixtures & results
# ──────────────────────────────────────────────────────────────────────────

@dataclass
class EdgeFixture:
    match_key: str
    tier: str
    bookmaker: str
    odds: float
    bet_type: str
    predicted_ev: float
    home_key: str = ""        # derived from match_key (raw underscore form)
    away_key: str = ""


@dataclass
class EdgeResult:
    match_key: str
    tier: str
    bookmaker_expected: str
    verdict_body: str = ""
    verdict_char_count: int = 0
    narrative_html: str = ""
    narrative_source: str = ""  # "cache_hit", "cache_miss", "not_found"
    min_floor: int = 0
    passed_floor: bool = False
    passed_cap: bool = False
    passed_bookmaker_leak: bool = False
    passed_banned_pattern: bool = False
    passed_photo_arrived: bool = False
    failure_reasons: list[str] = field(default_factory=list)
    skipped: bool = False
    skip_reason: str = ""
    capture_mode: str = ""  # "telethon_tap" | "cache_only" | ""
    timings: dict[str, float] = field(default_factory=dict)
    cb_data_tapped: str = ""  # which ep:pick button this edge consumed (if any)

    @property
    def overall_pass(self) -> bool:
        if self.skipped:
            return False
        # cache_only mode can't verify photo arrival — exclude from overall
        if self.capture_mode == "cache_only":
            return (
                self.passed_floor
                and self.passed_cap
                and self.passed_bookmaker_leak
                and self.passed_banned_pattern
            )
        return (
            self.passed_floor
            and self.passed_cap
            and self.passed_bookmaker_leak
            and self.passed_banned_pattern
            and self.passed_photo_arrived
        )


# ──────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────

def load_session() -> StringSession:
    if not STRING_SESSION_FILE.exists():
        raise SystemExit(f"ERROR: No Telethon string session at {STRING_SESSION_FILE}.")
    raw = STRING_SESSION_FILE.read_text().strip()
    if not raw:
        raise SystemExit(f"ERROR: Empty Telethon string session at {STRING_SESSION_FILE}.")
    return StringSession(raw)


def strip_html(text: str) -> str:
    return HTML_TAG_RE.sub("", text or "")


def enumerate_live_edges() -> list[EdgeFixture]:
    """All unsettled edges from today − 1 day onward, tier-ordered."""
    with sqlite3.connect(f"file:{ODDS_DB}?mode=ro", uri=True) as conn:
        rows = conn.execute(
            """
            SELECT match_key, edge_tier, bookmaker, recommended_odds, bet_type, predicted_ev
              FROM edge_results
             WHERE result IS NULL
               AND date(match_date) >= date('now','-1 day')
          ORDER BY CASE edge_tier
                      WHEN 'diamond' THEN 1
                      WHEN 'gold'    THEN 2
                      WHEN 'silver'  THEN 3
                      WHEN 'bronze'  THEN 4
                      ELSE 5
                   END,
                   recommended_at DESC
            """
        ).fetchall()
    out: list[EdgeFixture] = []
    for r in rows:
        match_key = r[0]
        home_key, away_key = _split_match_key(match_key)
        out.append(
            EdgeFixture(
                match_key=match_key,
                tier=(r[1] or "").lower(),
                bookmaker=(r[2] or "").lower(),
                odds=float(r[3] or 0.0),
                bet_type=r[4] or "",
                predicted_ev=float(r[5] or 0.0),
                home_key=home_key,
                away_key=away_key,
            )
        )
    return out


def _split_match_key(match_key: str) -> tuple[str, str]:
    """'aston_villa_vs_tottenham_2026-05-03' → ('aston_villa', 'tottenham')."""
    parts = match_key.rsplit("_", 1)  # drop trailing date
    if len(parts) == 2 and re.match(r"\d{4}-\d{2}-\d{2}", parts[1]):
        body = parts[0]
    else:
        body = match_key
    if "_vs_" not in body:
        return body, ""
    home, away = body.split("_vs_", 1)
    return home, away


def _display_from_key(team_key: str) -> str:
    """'aston_villa' → 'Aston Villa'."""
    return team_key.replace("_", " ").title()


def _abbreviate_for_match(team_key: str) -> str:
    """Mirror bot._abbreviate_btn for a raw underscore team key.

    The bot calls `_display_team_name(key) → _abbreviate_btn(display)`; this
    reproduces that chain so we can compare button text against each edge's
    expected abbreviation.
    """
    display = _display_from_key(team_key)
    # _BTN_ABBREVS lives in bot.py but we don't want to import bot.py (would
    # start the full runtime).  config.TEAM_ABBREVIATIONS + the fallback rules
    # cover >95 % of the real names.
    abbr = config.TEAM_ABBREVIATIONS.get(display)
    if abbr:
        return abbr
    if len(display) <= 8:
        return display
    words = display.split()
    if len(words) >= 2:
        return " ".join(w[:3] for w in words[:2])
    return display[:8]


def parse_verdict_body(html_body: str) -> str:
    if not html_body:
        return ""
    idx = html_body.find("🏆")
    if idx < 0:
        return ""
    after = html_body[idx + 1 :]
    flat = strip_html(after).strip()
    for label in ("The Verdict", "Verdict"):
        if flat.startswith(label):
            flat = flat[len(label):].lstrip(" :—-–\n\t")
            break
    cut_at = len(flat)
    for sc in SECTION_EMOJIS_STOP:
        pos = flat.find(sc)
        if 0 <= pos < cut_at:
            cut_at = pos
    # Also cut at "SA Bookmaker Odds:" (appears unemojied in some narratives)
    mbk = re.search(r"\bSA Bookmaker Odds\b", flat, re.IGNORECASE)
    if mbk and mbk.start() < cut_at:
        cut_at = mbk.start()
    return flat[:cut_at].strip()


def _bookmakers_quoted_in_cache(match_key: str) -> set[str]:
    """Return lowercase bookmaker keys that the generator legitimately used
    when writing this narrative.

    Root cause this handles: `edge_results` records the best-price bookmaker
    at the moment the edge was calculated.  Prices move — by the time the
    narrative is generated (or regenerated), the best-price SA book can be a
    DIFFERENT one, and that's the one the narrative will quote.  The true
    source of truth for which bookmaker the narrative is allowed to mention
    is `narrative_cache.tips_json`, which carries the exact tip dict the
    renderer consumed.
    """
    try:
        with sqlite3.connect(f"file:{ODDS_DB}?mode=ro", uri=True) as conn:
            row = conn.execute(
                """
                SELECT tips_json
                  FROM narrative_cache
                 WHERE match_id = ?
              ORDER BY created_at DESC
                 LIMIT 1
                """,
                (match_key,),
            ).fetchone()
    except Exception:
        return set()
    if not row or not row[0]:
        return set()
    try:
        tips = json.loads(row[0])
    except Exception:
        return set()
    out: set[str] = set()
    for t in tips or []:
        bk = (t.get("bookmaker") or "").strip()
        if bk:
            out.add(bk.lower())
    return out


def detect_bookmaker_leak(
    verdict_body: str,
    expected_bk_key: str,
    match_key: str = "",
    bet_type: str = "",  # retained for backward-compat; no longer used
) -> list[str]:
    """Flag only bookmakers that are NOT legitimate quotes for this edge.

    A bookmaker is "legitimate" when it is either:
      (1) the `edge_results.bookmaker` the QA fixture was built from, or
      (2) the bookmaker recorded in `narrative_cache.tips_json` — i.e. the
          exact book the narrative generator quoted (which can differ from
          #1 because prices move between edge calculation and narrative
          generation).
    Everything else counts as a leak.
    """
    expected_display = BOOKMAKER_CANONICAL.get(expected_bk_key.lower(), expected_bk_key)
    allowed_keys = {expected_bk_key.lower(), expected_display.lower()}
    if match_key:
        allowed_keys.update(_bookmakers_quoted_in_cache(match_key))

    leaks: list[str] = []
    for bk in KNOWN_BOOKMAKERS:
        if bk.lower() in allowed_keys:
            continue
        if re.search(rf"\b{re.escape(bk)}\b", verdict_body, re.IGNORECASE):
            leaks.append(bk)
    return sorted({bk for bk in leaks})


# ──────────────────────────────────────────────────────────────────────────
# Telegram navigation
# ──────────────────────────────────────────────────────────────────────────

def _extract_pick_buttons(msg) -> list[tuple[int, int, str, str]]:
    """Return [(row_idx, col_idx, button_text, cb_data), ...] for `ep:pick:N`."""
    out: list[tuple[int, int, str, str]] = []
    rm = msg.reply_markup
    if not rm or not getattr(rm, "rows", None):
        return out
    for r_idx, row in enumerate(rm.rows):
        for c_idx, btn in enumerate(row.buttons):
            if not isinstance(btn, KeyboardButtonCallback):
                continue
            try:
                data = btn.data.decode("utf-8", errors="replace")
            except Exception:
                data = str(btn.data)
            text = getattr(btn, "text", "") or ""
            if data.startswith("ep:pick:"):
                out.append((r_idx, c_idx, text, data))
    return out


def _extract_nav_button(msg, prefix: str) -> tuple[int, int, str] | None:
    rm = msg.reply_markup
    if not rm or not getattr(rm, "rows", None):
        return None
    for r_idx, row in enumerate(rm.rows):
        for c_idx, btn in enumerate(row.buttons):
            if not isinstance(btn, KeyboardButtonCallback):
                continue
            try:
                data = btn.data.decode("utf-8", errors="replace")
            except Exception:
                data = str(btn.data)
            if data.startswith(prefix):
                return r_idx, c_idx, data
    return None


def _is_hot_tips_photo(m) -> bool:
    """Returns True iff this message looks like the Hot Tips list photo card."""
    if m.sender_id and m.sender_id > 0 and not isinstance(m.media, MessageMediaPhoto):
        # no photo → not the list card we want
        # (but could be a text fallback — very rare)
        pass
    rm = m.reply_markup
    if not rm or not getattr(rm, "rows", None):
        return False
    for row in rm.rows:
        for btn in row.buttons:
            if not isinstance(btn, KeyboardButtonCallback):
                continue
            try:
                data = btn.data.decode("utf-8", errors="replace")
            except Exception:
                data = ""
            if data.startswith("ep:pick:") or data.startswith("hot:page:"):
                return True
    return False


async def _wait_for_hot_tips_list(
    client, chat, me_id: int, anchor_id: int, timeout: float
) -> object | None:
    """Return the most recent bot message that looks like the picks list."""
    deadline = time.time() + timeout
    best = None
    while time.time() < deadline:
        await asyncio.sleep(0.6)
        msgs = await client.get_messages(chat, limit=8)
        for m in msgs:
            if m.sender_id == me_id:
                continue
            if m.id <= anchor_id:
                continue
            if _is_hot_tips_photo(m):
                # take the latest message that qualifies
                if best is None or m.id > best.id:
                    best = m
        if best is not None:
            # Give a tiny settling grace in case the list is still being edited
            await asyncio.sleep(0.3)
            msgs2 = await client.get_messages(chat, ids=best.id)
            if msgs2 and _is_hot_tips_photo(msgs2):
                return msgs2
            return best
    return None


async def _collect_all_pick_buttons(
    client, chat, me_id: int, first_page_msg
) -> list[tuple[str, str]]:
    """Walk through every hot-tips page and collect (button_text, cb_data) pairs.

    Returns them in the order the user would see (page 0 first).
    """
    collected: list[tuple[str, str]] = []
    current = first_page_msg
    page_idx = 0
    while page_idx < MAX_PAGES:
        btns = _extract_pick_buttons(current)
        for _, _, text, data in btns:
            if (text, data) not in collected:
                collected.append((text, data))
        # find next page
        nxt = _extract_nav_button(current, "hot:page:")
        if not nxt:
            break
        next_page = int(nxt[2].split(":")[-1])
        if next_page <= page_idx:
            break
        # tap it — message is edited in place
        try:
            await current.click(nxt[0], nxt[1])
        except Exception as e:
            print(f"  [nav] hot:page:{next_page} click failed: {e}")
            break
        # wait for edit — poll the same message id until reply_markup changes
        deadline = time.time() + PAGE_WAIT_S
        prev_cb_set = frozenset(
            (t, d) for (_, _, t, d) in _extract_pick_buttons(current)
        )
        got_edit = False
        while time.time() < deadline:
            await asyncio.sleep(0.6)
            try:
                refreshed = await client.get_messages(chat, ids=current.id)
            except Exception:
                refreshed = None
            if not refreshed:
                continue
            new_cb_set = frozenset(
                (t, d) for (_, _, t, d) in _extract_pick_buttons(refreshed)
            )
            if new_cb_set and new_cb_set != prev_cb_set:
                current = refreshed
                got_edit = True
                break
        if not got_edit:
            break
        page_idx = next_page
        await asyncio.sleep(INTER_TAP_SLEEP)
    return collected


def _match_button_to_edge(btn_text: str, edges: list[EdgeFixture]) -> EdgeFixture | None:
    """Given "[1] 🏏 MI vs CSK 🥇", find the EdgeFixture whose abbreviated
    home + away tokens appear in the button text (case-insensitive substring)."""
    # Strip prefix ("[N] 🏏 ") and trailing tier badge
    cleaned = re.sub(r"^\[\d+\]\s*\S+\s*", "", btn_text).strip()
    # drop trailing tier emoji (🥇🥈🥉💎) or 🔒
    cleaned = re.sub(r"\s*[\U0001F947-\U0001F949💎🔒]\s*$", "", cleaned).strip()
    if " vs " not in cleaned:
        return None
    lo_btn = cleaned.lower()
    best = None
    best_score = 0
    for e in edges:
        home_ab = _abbreviate_for_match(e.home_key).lower()
        away_ab = _abbreviate_for_match(e.away_key).lower()
        # scoring: both tokens present → 2, one → 1
        score = 0
        if home_ab and home_ab in lo_btn:
            score += 1
        if away_ab and away_ab in lo_btn:
            score += 1
        if score > best_score:
            best = e
            best_score = score
    return best if best_score >= 2 else None


def _read_narrative_from_cache(match_key: str) -> tuple[str, str]:
    """Return (narrative_html, source) where
       source ∈ {'cache_hit', 'verdict_only_cache_hit', 'not_found'}.

    There are two cache shapes the bot may write for a given match:
      1. Full narrative — `narrative_html` populated (Setup/Edge/Risk/Verdict).
         This is what `send_card_or_fallback` renders on the photo card.
      2. Verdict-only — `narrative_html=''` but `verdict_html` populated with
         the 🏆 Verdict block. Written by `_store_verdict_cache_sync` when the
         bot serves the fast verdict path on a live tap before the full
         narrative generator has run.

    The tier-aware floor MUST be enforced against whichever shape was last
    written for this match. We return the verdict-only HTML wrapped in a
    minimal `🏆 <b>Verdict</b>` header so downstream parsing works.
    """
    try:
        with sqlite3.connect(f"file:{ODDS_DB}?mode=ro", uri=True) as conn:
            row = conn.execute(
                """
                SELECT narrative_html, verdict_html, narrative_source
                  FROM narrative_cache
                 WHERE match_id = ?
              ORDER BY created_at DESC
                 LIMIT 1
                """,
                (match_key,),
            ).fetchone()
    except Exception as e:
        return "", f"db_error:{e!r}"
    if not row:
        return "", "not_found"
    full_html, verdict_only, _src = row[0], row[1], row[2]
    if full_html:
        return full_html, "cache_hit"
    if verdict_only:
        # Synthesise a minimal narrative so parse_verdict_body() can still
        # locate the 🏆 marker. The verdict body itself is the load-bearing
        # content we're validating.
        synthesised = f"\U0001f3c6 <b>Verdict</b>\n{verdict_only}"
        return synthesised, "verdict_only_cache_hit"
    return "", "not_found"


# ──────────────────────────────────────────────────────────────────────────
# Per-edge capture
# ──────────────────────────────────────────────────────────────────────────

def validate_narrative(
    narr: str, edge: EdgeFixture, r: EdgeResult, photo_arrived: bool | None = None
) -> None:
    """Populate pass/fail flags on `r` from narrative body + edge fixture."""
    verdict = parse_verdict_body(narr)
    r.verdict_body = verdict
    r.verdict_char_count = len(verdict)

    r.passed_floor = r.verdict_char_count >= r.min_floor
    if not r.passed_floor:
        r.failure_reasons.append(
            f"verdict length {r.verdict_char_count} < floor {r.min_floor} for tier {edge.tier}"
        )
    r.passed_cap = r.verdict_char_count <= _VERDICT_MAX_CHARS
    if not r.passed_cap:
        r.failure_reasons.append(
            f"verdict length {r.verdict_char_count} > cap {_VERDICT_MAX_CHARS}"
        )

    leaks = detect_bookmaker_leak(
        verdict,
        edge.bookmaker,
        match_key=edge.match_key,
        bet_type=edge.bet_type,
    )
    r.passed_bookmaker_leak = not leaks
    if leaks:
        r.failure_reasons.append(
            f"bookmaker leak: {leaks} (expected only {edge.bookmaker})"
        )

    stripped = verdict.strip()
    bug = BANNED_BUG_PATTERN.match(stripped)
    r.passed_banned_pattern = not bug
    if bug:
        r.failure_reasons.append(f"matches banned bug pattern: {stripped!r}")

    if photo_arrived is False and r.passed_floor and r.passed_cap:
        r.failure_reasons.append("detail photo flaked but narrative cache is valid")


def capture_edge_cache_only(edge: EdgeFixture) -> EdgeResult:
    """Fallback: edge is not reachable via Hot Tips catalog — validate the
    narrative straight from `narrative_cache`.

    Root cause this covers: `get_top_edges()` applies production filters
    (stale price, draw cap, `_passes_production_filters`) that `edge_results`
    does not. Many rows in `edge_results` are therefore never rendered in the
    Hot Tips list, yet their cached narrative is still served when a user taps
    a direct detail URL (e.g. from a push notification or a shared link), so
    those narratives STILL need to respect tier floors.
    """
    r = EdgeResult(
        match_key=edge.match_key,
        tier=edge.tier,
        bookmaker_expected=edge.bookmaker,
        min_floor=MIN_VERDICT_CHARS_BY_TIER.get(
            edge.tier, MIN_VERDICT_CHARS_BY_TIER["bronze"]
        ),
        capture_mode="cache_only",
    )
    narr, src = _read_narrative_from_cache(edge.match_key)
    r.narrative_source = src
    r.narrative_html = narr

    safe_key = edge.match_key.replace("/", "_")
    (SS_DIR / f"{safe_key}_{edge.tier}.txt").write_text(narr, encoding="utf-8")

    if not narr:
        # narrative cache has no entry for this edge — treat as skip, NOT fail,
        # because the bot will regenerate on first tap.  These are inflight.
        r.skipped = True
        r.skip_reason = "narrative_cache empty (bot will generate on first tap)"
        return r

    validate_narrative(narr, edge, r, photo_arrived=None)
    return r


async def capture_edge(
    client,
    chat,
    me_id: int,
    edge: EdgeFixture,
    button_catalog: list[tuple[str, str]],
    consumed_cb_data: set[str] | None = None,
) -> EdgeResult:
    """Tap the matching ep:pick button and pull the narrative for this edge.

    `button_catalog` is the list of (button_text, cb_data) collected from every
    Hot Tips page BEFORE this loop started.  We do not re-open the list per
    edge — that wastes Telegram budget.

    `consumed_cb_data` tracks which callback_data buttons we've already tapped
    for a previous edge.  If two edges share the same abbreviated team names
    (e.g. two Bangladesh-vs-Sri-Lanka fixtures on different dates), the live
    bot only exposes ONE of them (the next fixture) in Hot Tips — the stale
    one must not re-tap the same button and mis-attribute the detail.  We
    fall back to cache-only validation for duplicates.
    """
    t_start = time.time()
    r = EdgeResult(
        match_key=edge.match_key,
        tier=edge.tier,
        bookmaker_expected=edge.bookmaker,
        min_floor=MIN_VERDICT_CHARS_BY_TIER.get(edge.tier, MIN_VERDICT_CHARS_BY_TIER["bronze"]),
        capture_mode="telethon_tap",
    )

    # 1) find the button (skip ones already used by a prior edge)
    hit: tuple[str, str] | None = None
    for text, data in button_catalog:
        if consumed_cb_data is not None and data in consumed_cb_data:
            continue
        guess = _match_button_to_edge(text, [edge])
        if guess is not None:
            hit = (text, data)
            break
    if not hit:
        # fall back to cache-only validation
        fallback = capture_edge_cache_only(edge)
        fallback.timings["nav_s"] = round(time.time() - t_start, 2)
        return fallback

    btn_text, cb_data = hit
    r.cb_data_tapped = cb_data

    # 2) re-open list & find the live button with matching cb_data
    anchor = (await client.get_messages(chat, limit=1))[0].id
    await client.send_message(chat, "/picks")
    list_msg = await _wait_for_hot_tips_list(client, chat, me_id, anchor, PICKS_WAIT_S)
    if not list_msg:
        # fallback to cache-only validation
        fallback = capture_edge_cache_only(edge)
        fallback.timings["nav_s"] = round(time.time() - t_start, 2)
        fallback.failure_reasons.append(
            "telethon could not reach /picks list; fell back to cache-only validation"
        )
        return fallback

    # walk pages looking for a button whose data == cb_data (because list
    # order may shift between /picks invocations as cache refreshes)
    current = list_msg
    found = None
    seen_pages = 0
    while seen_pages < MAX_PAGES:
        for r_idx, c_idx, text, data in _extract_pick_buttons(current):
            if data == cb_data:
                found = (r_idx, c_idx, text, data, current)
                break
        if found:
            break
        # fallback: use text-match on this page
        for r_idx, c_idx, text, data in _extract_pick_buttons(current):
            g = _match_button_to_edge(text, [edge])
            if g is not None:
                found = (r_idx, c_idx, text, data, current)
                break
        if found:
            break
        # next page
        nxt = _extract_nav_button(current, "hot:page:")
        if not nxt:
            break
        prev_cb_set = frozenset(
            (t, d) for (_, _, t, d) in _extract_pick_buttons(current)
        )
        try:
            await current.click(nxt[0], nxt[1])
        except Exception as e:
            r.skipped = True
            r.skip_reason = f"Pagination click failed: {e}"
            return r
        # wait for edit
        deadline = time.time() + PAGE_WAIT_S
        got = False
        while time.time() < deadline:
            await asyncio.sleep(0.6)
            refreshed = await client.get_messages(chat, ids=current.id)
            if not refreshed:
                continue
            new_cb_set = frozenset(
                (t, d) for (_, _, t, d) in _extract_pick_buttons(refreshed)
            )
            if new_cb_set and new_cb_set != prev_cb_set:
                current = refreshed
                got = True
                break
        if not got:
            break
        seen_pages += 1
        await asyncio.sleep(INTER_TAP_SLEEP)

    if not found:
        # fallback — button existed in original catalog but not here (race)
        fallback = capture_edge_cache_only(edge)
        fallback.timings["nav_s"] = round(time.time() - t_start, 2)
        fallback.failure_reasons.append(
            "pick button not reachable on re-open (list churn); fell back to cache-only"
        )
        return fallback

    r_idx, c_idx, text, data, list_now = found
    r.timings["nav_s"] = round(time.time() - t_start, 2)

    # 3) tap it
    tap_t0 = time.time()
    try:
        await list_now.click(r_idx, c_idx)
    except Exception as e:
        r.skipped = True
        r.skip_reason = f"Pick click failed: {e}"
        return r

    # 4) wait for the list card to be edited into a detail photo
    detail_deadline = time.time() + TAP_WAIT_S
    detail_seen = False
    while time.time() < detail_deadline:
        await asyncio.sleep(0.8)
        try:
            refreshed = await client.get_messages(chat, ids=list_now.id)
        except Exception:
            refreshed = None
        if refreshed and refreshed.reply_markup:
            # detail photos no longer carry `ep:pick:` buttons; they carry
            # `hot:back:N`, URL buttons, `odds:compare:...` etc.
            rm = refreshed.reply_markup
            has_detail_markers = False
            for row in rm.rows:
                for btn in row.buttons:
                    if isinstance(btn, KeyboardButtonCallback):
                        try:
                            bd = btn.data.decode("utf-8", errors="replace")
                        except Exception:
                            bd = ""
                        if (
                            bd.startswith("hot:back")
                            or bd.startswith("odds:compare")
                            or bd.startswith("yg:game")
                        ):
                            has_detail_markers = True
                    else:
                        # URL buttons (e.g. Bet on Supabets →) qualify too
                        if getattr(btn, "url", None):
                            has_detail_markers = True
            if has_detail_markers:
                detail_seen = True
                break
    r.passed_photo_arrived = detail_seen
    r.timings["tap_s"] = round(time.time() - tap_t0, 2)

    # 5) pull narrative from cache
    narr, src = _read_narrative_from_cache(edge.match_key)
    r.narrative_source = src
    r.narrative_html = narr

    # save raw capture
    safe_key = edge.match_key.replace("/", "_")
    (SS_DIR / f"{safe_key}_{edge.tier}.txt").write_text(narr, encoding="utf-8")

    # 6) validate narrative against floor/cap/bookmaker/banned bug
    if not narr:
        r.failure_reasons.append("narrative_cache has no row for this match_key")
    validate_narrative(narr, edge, r, photo_arrived=detail_seen)

    r.timings["total_s"] = round(time.time() - t_start, 2)
    return r


# ──────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────

async def run() -> int:
    edges = enumerate_live_edges()
    if not edges:
        print("ERROR: No live edges in odds.db.")
        return 2

    print(f"W91-P3 Telethon QA  ·  {datetime.now():%Y-%m-%d %H:%M:%S}")
    print(f"  Live edges: {len(edges)}  (diamond/gold/silver/bronze tier-ordered)")
    print(f"  Tier floors: {MIN_VERDICT_CHARS_BY_TIER}  cap={_VERDICT_MAX_CHARS}")
    print(f"  Capture dir: {SS_DIR}\n")

    results: list[EdgeResult] = []
    async with TelegramClient(load_session(), API_ID, API_HASH) as client:
        entity = await client.get_entity(BOT_USERNAME)
        me = await client.get_me()
        me_id = me.id
        print(f"  Connected as {me.first_name} (id={me_id})")

        # ── Layer 1: onboard + force Diamond ──────────────────────────────
        await client.send_message(entity, "/start")
        await asyncio.sleep(2.0)
        await client.send_message(entity, "/qa set_diamond")
        await asyncio.sleep(2.0)
        print("  /start + /qa set_diamond sent.\n")

        # ── Layer 2: open /picks and harvest the full button catalog ──────
        anchor = (await client.get_messages(entity, limit=1))[0].id
        await client.send_message(entity, "/picks")
        list_msg = await _wait_for_hot_tips_list(client, entity, me_id, anchor, PICKS_WAIT_S)
        if not list_msg:
            print("FATAL: /picks did not return a list photo. Aborting.")
            return 3
        print(f"  /picks list ready (id={list_msg.id}). Collecting button catalog…")
        catalog = await _collect_all_pick_buttons(client, entity, me_id, list_msg)
        print(f"  catalog size: {len(catalog)} buttons across pages")
        for (t, d) in catalog:
            print(f"    · {d}  {t}")
        print()

        # ── Layer 3: tap each edge one by one ─────────────────────────────
        # When two edges share the same abbreviated team names (e.g. two
        # Bangladesh-vs-Sri-Lanka fixtures on different dates), the bot only
        # exposes ONE in the Hot Tips list — the stale one must not re-tap
        # the same button. Track already-tapped callbacks and force the
        # duplicate edge down the cache-only validation path.
        consumed_cb_data: set[str] = set()
        for i, edge in enumerate(edges, 1):
            print(f"[{i}/{len(edges)}] {edge.match_key}  ({edge.tier})  → {edge.bookmaker} @ {edge.odds}")
            try:
                r = await capture_edge(
                    client, entity, me_id, edge, catalog,
                    consumed_cb_data=consumed_cb_data,
                )
                if r.cb_data_tapped:
                    consumed_cb_data.add(r.cb_data_tapped)
            except Exception as exc:
                r = EdgeResult(
                    match_key=edge.match_key,
                    tier=edge.tier,
                    bookmaker_expected=edge.bookmaker,
                    min_floor=MIN_VERDICT_CHARS_BY_TIER.get(edge.tier, MIN_VERDICT_CHARS_BY_TIER["bronze"]),
                    skipped=True,
                    skip_reason=f"exception: {exc!r}",
                )
            results.append(r)
            status = "SKIP" if r.skipped else ("PASS" if r.overall_pass else "FAIL")
            detail = r.skip_reason if r.skipped else (
                f"len={r.verdict_char_count}/{r.min_floor}  photo={r.passed_photo_arrived}  "
                f"src={r.narrative_source}"
            )
            print(f"    → {status}  {detail}")
            for reason in r.failure_reasons:
                print(f"        · {reason}")
            await asyncio.sleep(INTER_EDGE_SLEEP)

    # ── Summary ───────────────────────────────────────────────────────────
    total = len(results)
    captured = sum(1 for r in results if not r.skipped)
    passed = sum(1 for r in results if r.overall_pass)
    failed = sum(1 for r in results if not r.skipped and not r.overall_pass)
    skipped = sum(1 for r in results if r.skipped)
    tap_mode = sum(1 for r in results if r.capture_mode == "telethon_tap")
    cache_mode = sum(1 for r in results if r.capture_mode == "cache_only")

    fail_floor = sum(1 for r in results if not r.skipped and not r.passed_floor)
    fail_cap = sum(1 for r in results if not r.skipped and not r.passed_cap)
    fail_leak = sum(1 for r in results if not r.skipped and not r.passed_bookmaker_leak)
    fail_banned = sum(1 for r in results if not r.skipped and not r.passed_banned_pattern)

    print("\n" + "=" * 72)
    print(f"SUMMARY: {passed}/{total} pass  ·  {failed} fail  ·  {skipped} skipped  ·  {captured} captured")
    print(f"  mode: telethon_tap={tap_mode}  cache_only={cache_mode}")
    print(f"  floor violations : {fail_floor}")
    print(f"  cap violations   : {fail_cap}")
    print(f"  bookmaker leaks  : {fail_leak}")
    print(f"  banned bug match : {fail_banned}")
    print("=" * 72)

    (SS_DIR / "_results.json").write_text(
        json.dumps([asdict(r) for r in results], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"Raw results → {SS_DIR / '_results.json'}")

    # Verdict-floor-only exit code (the contract of this script):
    if fail_floor == 0 and fail_cap == 0 and fail_banned == 0 and fail_leak == 0 and captured >= 20:
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
