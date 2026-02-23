#!/usr/bin/env python3
"""MzansiEdge — AI-powered sports betting Telegram bot for South Africa."""

from __future__ import annotations

import difflib
import logging
import textwrap

import anthropic
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import config
import db
from scripts.odds_client import (
    fetch_odds, format_odds_message, format_pick_card,
    get_quota, scan_value_bets,
)

logging.basicConfig(
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("mzansiedge")

claude = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)

# ── Onboarding state machine ─────────────────────────────
# Steps: experience → sports → leagues → favourites → risk → notify → summary
ONBOARD_STEPS = ("experience", "sports", "leagues", "favourites", "risk", "notify", "summary")

# Per-user in-memory onboarding state
_onboarding_state: dict[int, dict] = {}


def _get_ob(user_id: int) -> dict:
    """Get or create onboarding state for a user."""
    if user_id not in _onboarding_state:
        _onboarding_state[user_id] = {
            "step": "experience",
            "experience": None,         # experienced / casual / newbie
            "selected_sports": [],      # category keys: ["soccer", "rugby"]
            "selected_leagues": {},     # sport_key → [league_key, ...]
            "favourites": {},           # sport_key → [name, ...]
            "risk": None,
            "notify_hour": None,
            "_league_idx": 0,
            "_fav_idx": 0,
            "_fav_manual": False,       # in manual input mode
            "_fav_manual_sport": None,  # which sport we're inputting for
            "_editing": None,           # None / "sports" / "risk" / "sport:{key}"
            "_suggestions": [],         # fuzzy match suggestions
        }
    return _onboarding_state[user_id]


# ── Fuzzy matching helpers ────────────────────────────────

def fuzzy_match_team(text: str, sport_key: str) -> tuple[str | None, list[str]]:
    """Match user input to a team/player name.

    Returns (exact_match_or_None, list_of_suggestions).
    Checks aliases first, then fuzzy matches against TOP_TEAMS.
    """
    text_lower = text.strip().lower()

    # 1. Check exact alias match
    if text_lower in config.TEAM_ALIASES:
        return config.TEAM_ALIASES[text_lower], []

    # 2. Build candidate list from all leagues in this sport
    sport = config.ALL_SPORTS.get(sport_key)
    candidates: list[str] = []
    if sport:
        for lg in sport.leagues:
            candidates.extend(config.TOP_TEAMS.get(lg.key, []))
    # Deduplicate preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            unique.append(c)
    candidates = unique

    # 3. Check exact match (case-insensitive)
    for c in candidates:
        if c.lower() == text_lower:
            return c, []

    # 4. Check partial match (input is substring of candidate)
    partials = [c for c in candidates if text_lower in c.lower()]
    if len(partials) == 1:
        return partials[0], []
    if partials:
        return None, partials[:3]

    # 5. Fuzzy match using difflib
    lower_candidates = [c.lower() for c in candidates]
    matches = difflib.get_close_matches(text_lower, lower_candidates, n=3, cutoff=0.55)
    suggestions = []
    for m in matches:
        idx = lower_candidates.index(m)
        suggestions.append(candidates[idx])

    if len(suggestions) == 1:
        return suggestions[0], []
    return None, suggestions


def _get_all_teams_for_sport(sport_key: str) -> list[str]:
    """Get all known team/player names for a sport category."""
    sport = config.ALL_SPORTS.get(sport_key)
    if not sport:
        return []
    candidates: list[str] = []
    for lg in sport.leagues:
        candidates.extend(config.TOP_TEAMS.get(lg.key, []))
    seen: set[str] = set()
    unique: list[str] = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            unique.append(c)
    return unique


# ── Keyboards ─────────────────────────────────────────────

def kb_main() -> InlineKeyboardMarkup:
    """Main persistent menu — every sub-screen navigates back here."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Daily Briefing", callback_data="picks:today")],
        [
            InlineKeyboardButton("💰 My Bets", callback_data="bets:active"),
            InlineKeyboardButton("🏟️ My Teams", callback_data="teams:view"),
        ],
        [
            InlineKeyboardButton("📈 Stats", callback_data="stats:overview"),
            InlineKeyboardButton("🎰 Bookmakers", callback_data="affiliate:compare"),
        ],
        [InlineKeyboardButton("⚙️ Settings", callback_data="settings:home")],
    ])


def kb_nav(back_target: str = "menu:home") -> InlineKeyboardMarkup:
    """Standard navigation row: Back + Main Menu."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔙 Back", callback_data=back_target),
            InlineKeyboardButton("🏠 Main Menu", callback_data="menu:home"),
        ],
    ])


def kb_bets() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Active Bets", callback_data="bets:active")],
        [InlineKeyboardButton("📜 Bet History", callback_data="bets:history")],
        [
            InlineKeyboardButton("🔙 Back", callback_data="menu:home"),
            InlineKeyboardButton("🏠 Main Menu", callback_data="menu:home"),
        ],
    ])


def kb_teams() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👀 View My Teams", callback_data="teams:view")],
        [InlineKeyboardButton("✏️ Edit Teams", callback_data="teams:edit")],
        [
            InlineKeyboardButton("🔙 Back", callback_data="menu:home"),
            InlineKeyboardButton("🏠 Main Menu", callback_data="menu:home"),
        ],
    ])


def kb_stats() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Overview", callback_data="stats:overview")],
        [InlineKeyboardButton("🏆 Leaderboard", callback_data="stats:leaderboard")],
        [
            InlineKeyboardButton("🔙 Back", callback_data="menu:home"),
            InlineKeyboardButton("🏠 Main Menu", callback_data="menu:home"),
        ],
    ])


def kb_bookmakers() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🇿🇦 SA Bookmakers", callback_data="affiliate:sa")],
        [InlineKeyboardButton("🌍 International", callback_data="affiliate:intl")],
        [
            InlineKeyboardButton("🔙 Back", callback_data="menu:home"),
            InlineKeyboardButton("🏠 Main Menu", callback_data="menu:home"),
        ],
    ])


def kb_settings() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎯 Risk Profile", callback_data="settings:risk")],
        [InlineKeyboardButton("⏰ Notifications", callback_data="settings:notify")],
        [InlineKeyboardButton("⚽ My Sports", callback_data="settings:sports")],
        [InlineKeyboardButton("🔄 Reset Profile", callback_data="settings:reset")],
        [
            InlineKeyboardButton("🔙 Back", callback_data="menu:home"),
            InlineKeyboardButton("🏠 Main Menu", callback_data="menu:home"),
        ],
    ])


def back_button(target: str = "menu:home") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("« Back", callback_data=target)]]
    )


# ── Onboarding keyboards ─────────────────────────────────

def kb_onboarding_experience() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎯 I bet regularly", callback_data="ob_exp:experienced")],
        [InlineKeyboardButton("🤔 I've placed a few bets", callback_data="ob_exp:casual")],
        [InlineKeyboardButton("🆕 I'm completely new", callback_data="ob_exp:newbie")],
    ])


def kb_onboarding_sports(selected: list[str] | None = None) -> InlineKeyboardMarkup:
    """Sport category selection keyboard."""
    selected = selected or []
    rows: list[list[InlineKeyboardButton]] = []

    row: list[InlineKeyboardButton] = []
    for s in config.SPORTS:
        tick = "✅ " if s.key in selected else ""
        row.append(InlineKeyboardButton(
            f"{tick}{s.emoji} {s.label}", callback_data=f"ob_sport:{s.key}",
        ))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    if selected:
        rows.append([InlineKeyboardButton("✅ Done — Next step »", callback_data="ob_nav:sports_done")])

    return InlineKeyboardMarkup(rows)


def kb_onboarding_leagues(sport_key: str, selected: list[str] | None = None) -> InlineKeyboardMarkup:
    """League selection for a specific sport category."""
    selected = selected or []
    sport = config.ALL_SPORTS.get(sport_key)
    if not sport:
        return back_button("ob_nav:back_sports")

    rows: list[list[InlineKeyboardButton]] = []
    for lg in sport.leagues:
        tick = "✅ " if lg.key in selected else ""
        rows.append([InlineKeyboardButton(
            f"{tick}{lg.label}", callback_data=f"ob_league:{sport_key}:{lg.key}",
        )])

    rows.append([
        InlineKeyboardButton("« Back", callback_data="ob_nav:back_sports"),
        InlineKeyboardButton("Next »", callback_data=f"ob_nav:league_done:{sport_key}"),
    ])
    return InlineKeyboardMarkup(rows)


def kb_onboarding_favourites(sport_key: str, selected: list[str] | None = None) -> InlineKeyboardMarkup:
    """Multi-select favourite teams/players for a sport."""
    selected = selected or []
    teams = _get_all_teams_for_sport(sport_key)

    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for i, name in enumerate(teams):
        tick = "✅ " if name in selected else ""
        # Truncate long names for button display
        display = name if len(name) <= 18 else name[:16] + "…"
        row.append(InlineKeyboardButton(
            f"{tick}{display}", callback_data=f"ob_fav:{sport_key}:{i}",
        ))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    rows.append([InlineKeyboardButton("✏️ Type manually", callback_data=f"ob_fav_manual:{sport_key}")])
    nav_row = [InlineKeyboardButton("⏭ Skip", callback_data=f"ob_fav_done:{sport_key}")]
    if selected:
        nav_row.append(InlineKeyboardButton("Next »", callback_data=f"ob_fav_done:{sport_key}"))
    rows.append(nav_row)

    return InlineKeyboardMarkup(rows)


def kb_onboarding_risk() -> InlineKeyboardMarkup:
    rows = []
    for key, prof in config.RISK_PROFILES.items():
        rows.append([InlineKeyboardButton(prof["label"], callback_data=f"ob_risk:{key}")])
    return InlineKeyboardMarkup(rows)


def kb_onboarding_notify() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🌅 7 AM", callback_data="ob_notify:7"),
            InlineKeyboardButton("☀️ 12 PM", callback_data="ob_notify:12"),
        ],
        [
            InlineKeyboardButton("🌆 6 PM", callback_data="ob_notify:18"),
            InlineKeyboardButton("🌙 9 PM", callback_data="ob_notify:21"),
        ],
    ])


# ── /start ────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    db_user = await db.upsert_user(user.id, user.username, user.first_name)

    if db_user.onboarding_done:
        text = textwrap.dedent(f"""\
            <b>🇿🇦 Welcome back, {user.first_name}!</b>

            Your AI-powered sports betting assistant.
            Pick a sport or get an AI tip below.
        """)
        await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb_main())
    else:
        # Start onboarding
        _onboarding_state.pop(user.id, None)  # reset
        ob = _get_ob(user.id)
        ob["step"] = "experience"
        text = textwrap.dedent(f"""\
            <b>🇿🇦 Welcome to MzansiEdge, {user.first_name}!</b>

            Let's set up your profile in a few quick steps.

            <b>Step 1/7:</b> What's your betting experience?
        """)
        await update.message.reply_text(
            text, parse_mode=ParseMode.HTML,
            reply_markup=kb_onboarding_experience(),
        )


# ── /menu ────────────────────────────────────────────────

async def cmd_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    text = textwrap.dedent(f"""\
        <b>🇿🇦 MzansiEdge — Main Menu</b>

        Hey {user.first_name}, pick a sport or get an AI tip.
    """)
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb_main())


# ── /help ─────────────────────────────────────────────────

HELP_TEXT = textwrap.dedent("""\
    <b>MzansiEdge — Help</b>

    <b>Commands</b>
    /start — Onboarding / Main menu
    /menu — Main menu
    /picks — Today's value bets (EV-based)
    /odds — Quick odds overview
    /tip — Get an AI prediction
    /help — This message

    <b>Inline buttons</b>
    Use the menu buttons to browse sports, view odds,
    and request AI-powered tips.

    <b>How tips work</b>
    Our AI analyses live odds, recent form, and
    historical data to suggest value bets. Always
    gamble responsibly. 🇿🇦
""")


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP_TEXT, parse_mode=ParseMode.HTML, reply_markup=kb_nav())


# ── /odds ─────────────────────────────────────────────────

async def cmd_odds(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for lg_key, api_key in config.SPORTS_MAP.items():
        lg = config.ALL_LEAGUES.get(lg_key)
        sport_key = config.LEAGUE_SPORT.get(lg_key)
        sport = config.ALL_SPORTS.get(sport_key) if sport_key else None
        emoji = sport.emoji if sport else "🏅"
        label = lg.label if lg else lg_key
        row.append(InlineKeyboardButton(f"{emoji} {label}", callback_data=f"sport:{lg_key}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    kb = InlineKeyboardMarkup(rows)
    await update.message.reply_text(
        "<b>Choose a sport to view odds:</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=kb,
    )


# ── /tip ──────────────────────────────────────────────────

async def cmd_tip(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for s in config.SPORTS:
        row.append(InlineKeyboardButton(f"{s.emoji} {s.label}", callback_data=f"ai:{s.key}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    kb = InlineKeyboardMarkup(rows)
    await update.message.reply_text(
        "<b>Choose a sport for an AI tip:</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=kb,
    )


# ── Callback router ──────────────────────────────────────

async def on_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    data = query.data or ""
    prefix, _, action = data.partition(":")

    if prefix == "noop":
        return
    elif prefix == "menu":
        await handle_menu(query, action)
    elif prefix == "sport":
        await handle_sport(query, action)
    elif prefix == "ai":
        await handle_ai(query, action)
    elif prefix == "ob_exp":
        await handle_ob_experience(query, action)
    elif prefix == "ob_sport":
        await handle_ob_sport(query, action)
    elif prefix == "ob_nav":
        await handle_ob_nav(query, action)
    elif prefix == "ob_league":
        await handle_ob_league(query, action)
    elif prefix == "ob_risk":
        await handle_ob_risk(query, action)
    elif prefix == "ob_notify":
        await handle_ob_notify(query, action)
    elif prefix == "ob_fav":
        await handle_ob_fav(query, action)
    elif prefix == "ob_fav_manual":
        await handle_ob_fav_manual(query, action)
    elif prefix == "ob_fav_done":
        await handle_ob_fav_done(query, action)
    elif prefix == "ob_fav_suggest":
        await handle_ob_fav_suggest(query, action)
    elif prefix == "ob_edit":
        await handle_ob_edit(query, action)
    elif prefix == "ob_summary":
        await handle_ob_summary(query, action)
    elif prefix == "picks":
        await handle_picks(query, action)
    elif prefix == "bets":
        await handle_bets(query, action)
    elif prefix == "teams":
        await handle_teams(query, action)
    elif prefix == "stats":
        await handle_stats_menu(query, action)
    elif prefix == "affiliate":
        await handle_affiliate(query, action)
    elif prefix == "settings":
        await handle_settings(query, action)
    elif prefix == "ob_done":
        await handle_ob_done(query)
    elif prefix == "ob_restart":
        await handle_ob_restart(query)
    elif prefix == "ob_fav_back":
        await handle_ob_fav_back(query, action)
    else:
        await query.edit_message_text("Unknown action.", parse_mode=ParseMode.HTML)


# ── Menu handlers ─────────────────────────────────────────

async def handle_menu(query, action: str) -> None:
    if action == "home":
        user = query.from_user
        text = textwrap.dedent(f"""\
            <b>🇿🇦 MzansiEdge — Main Menu</b>

            Hey {user.first_name}, what would you like to do?
        """)
        await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb_main())

    elif action == "help":
        await query.edit_message_text(HELP_TEXT, parse_mode=ParseMode.HTML, reply_markup=kb_nav())

    elif action == "history":
        tips = await db.get_recent_tips(limit=5)
        if not tips:
            text = "<b>📜 Tip History</b>\n\nNo tips recorded yet."
        else:
            lines = ["<b>📜 Recent Tips</b>\n"]
            for t in tips:
                icon = {"win": "✅", "loss": "❌"}.get(t.result, "⏳")
                lines.append(
                    f"{icon} <b>{t.match}</b>\n"
                    f"   {t.prediction}"
                    + (f" @ {t.odds:.2f}" if t.odds else "")
                )
            text = "\n".join(lines)
        await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb_nav())


# ── Sport / odds handlers ────────────────────────────────

async def handle_sport(query, action: str) -> None:
    if action == "all":
        parts = []
        for key, api_key in config.SPORTS_MAP.items():
            lg = config.ALL_LEAGUES.get(key)
            label = lg.label.upper() if lg else key.upper()
            try:
                events = await fetch_odds(api_key)
                parts.append(format_odds_message(events, label))
            except Exception:
                parts.append(f"<b>{label}</b>\n⚠️ Could not fetch odds.\n")
        text = "\n\n".join(parts) if parts else "No odds available."
    else:
        lg = config.ALL_LEAGUES.get(action)
        api_key = lg.api_key if lg else config.SPORTS_MAP.get(action)
        if not api_key:
            await query.edit_message_text(
                f"⚠️ Odds not available for <b>{action}</b> right now.",
                parse_mode=ParseMode.HTML, reply_markup=kb_nav(),
            )
            return
        label = lg.label.upper() if lg else action.upper()
        try:
            events = await fetch_odds(api_key)
            text = format_odds_message(events, label)
        except Exception as exc:
            log.error("Odds fetch error for %s: %s", action, exc)
            text = f"⚠️ Could not fetch <b>{label}</b> odds. Try again later."

    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb_nav())


# ── AI tip handler ────────────────────────────────────────

SYSTEM_PROMPT = textwrap.dedent("""\
    You are MzansiEdge, an expert South African sports betting analyst.
    Given live odds data, provide a concise betting tip. Include:
    - The recommended bet (team/outcome)
    - Why it has value
    - A suggested stake level (low / medium / high confidence)
    Format your answer in Telegram HTML (use <b>, <i>, <code> tags).
    Keep it under 300 words. End with a responsible-gambling reminder.
""")


async def handle_ai(query, action: str) -> None:
    sport_key = action if action != "tip" else "soccer"
    sport = config.ALL_SPORTS.get(sport_key)

    await query.edit_message_text("🤖 <i>Analysing odds…</i>", parse_mode=ParseMode.HTML)

    # Fetch odds from the first league that has an api_key
    odds_context = ""
    if sport:
        for lg in sport.leagues:
            if lg.api_key:
                try:
                    events = await fetch_odds(lg.api_key)
                    odds_context = format_odds_message(events, lg.label.upper())
                    break
                except Exception:
                    odds_context = "Could not fetch live odds."

    sport_label = sport.label if sport else sport_key
    try:
        resp = await claude.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": f"Here are the latest {sport_label} odds:\n\n{odds_context}\n\nGive me your best tip.",
                }
            ],
        )
        tip_text = resp.content[0].text
    except Exception as exc:
        log.error("Claude API error: %s", exc)
        tip_text = "⚠️ AI analysis unavailable right now. Try again shortly."

    try:
        await db.save_tip(sport=sport_key, match="AI Analysis", prediction=tip_text)
    except Exception:
        pass

    await query.edit_message_text(tip_text, parse_mode=ParseMode.HTML, reply_markup=kb_nav())


# ── Onboarding handlers ──────────────────────────────────

async def handle_ob_experience(query, level: str) -> None:
    """Set experience level during onboarding, then proceed to sports."""
    user_id = query.from_user.id
    ob = _get_ob(user_id)
    ob["experience"] = level
    ob["step"] = "sports"

    text = textwrap.dedent("""\
        <b>Step 2/7: Select your sports</b>

        Tap to toggle. Hit <b>Done</b> when ready.
    """)
    await query.edit_message_text(
        text, parse_mode=ParseMode.HTML,
        reply_markup=kb_onboarding_sports(),
    )


async def handle_ob_sport(query, sport_key: str) -> None:
    """Toggle a sport selection during onboarding."""
    user_id = query.from_user.id
    ob = _get_ob(user_id)

    if sport_key in ob["selected_sports"]:
        ob["selected_sports"].remove(sport_key)
    else:
        ob["selected_sports"].append(sport_key)

    text = textwrap.dedent("""\
        <b>Step 2/7: Select your sports</b>

        Tap to toggle. Hit <b>Done</b> when ready.
    """)
    await query.edit_message_text(
        text, parse_mode=ParseMode.HTML,
        reply_markup=kb_onboarding_sports(ob["selected_sports"]),
    )


async def handle_ob_nav(query, action: str) -> None:
    """Navigate between onboarding steps."""
    user_id = query.from_user.id
    ob = _get_ob(user_id)

    if action == "sports_done":
        if not ob["selected_sports"]:
            await query.edit_message_text(
                "⚠️ Please select at least one sport.",
                parse_mode=ParseMode.HTML,
                reply_markup=kb_onboarding_sports(),
            )
            return
        # Move to leagues — start with first sport
        ob["step"] = "leagues"
        ob["_league_idx"] = 0
        await _show_league_step(query, ob)

    elif action == "back_sports":
        ob["step"] = "sports"
        text = "<b>Step 2/7: Select your sports</b>\n\nTap to toggle. Hit <b>Done</b> when ready."
        await query.edit_message_text(
            text, parse_mode=ParseMode.HTML,
            reply_markup=kb_onboarding_sports(ob["selected_sports"]),
        )

    elif action.startswith("league_done:"):
        sport_key = action.split(":", 1)[1]
        await _advance_league_step(query, ob)

    elif action == "favourites_done":
        # Move to risk
        ob["step"] = "risk"
        text = "<b>Step 5/7: Risk profile</b>\n\nHow aggressive should your tips be?"
        await query.edit_message_text(
            text, parse_mode=ParseMode.HTML,
            reply_markup=kb_onboarding_risk(),
        )

    elif action == "notify_done":
        ob["step"] = "summary"
        await _show_summary(query, ob)


async def _show_league_step(query, ob: dict) -> None:
    """Show league selection for the current sport, auto-selecting single-league sports."""
    idx = ob.get("_league_idx", 0)
    sports = ob["selected_sports"]

    while idx < len(sports):
        sport_key = sports[idx]
        sport = config.ALL_SPORTS.get(sport_key)
        if not sport:
            idx += 1
            ob["_league_idx"] = idx
            continue

        # AUTO-SELECT: If sport has only 1 league, auto-select and skip
        if len(sport.leagues) == 1:
            ob["selected_leagues"][sport_key] = [sport.leagues[0].key]
            idx += 1
            ob["_league_idx"] = idx
            continue

        # Show league selection for this sport
        text = f"<b>Step 3/7: Select leagues for {sport.emoji} {sport.label}</b>\n\nTap to toggle."
        existing = ob["selected_leagues"].get(sport_key, [])
        await query.edit_message_text(
            text, parse_mode=ParseMode.HTML,
            reply_markup=kb_onboarding_leagues(sport_key, existing),
        )
        return

    # All leagues done — move to favourites
    ob["step"] = "favourites"
    ob["_fav_idx"] = 0
    await _show_fav_step(query, ob)


async def _advance_league_step(query, ob: dict) -> None:
    """Move to next sport's leagues or to favourites step."""
    ob["_league_idx"] = ob.get("_league_idx", 0) + 1

    # Check if editing a single sport
    editing = ob.get("_editing")
    if editing and editing.startswith("sport:"):
        edit_sport = editing.split(":", 1)[1]
        # After editing this sport's leagues, show its favourites
        sport = config.ALL_SPORTS.get(edit_sport)
        if sport and sport.fav_type != "skip":
            ob["_fav_manual"] = False
            ob["_fav_manual_sport"] = None
            text = _fav_step_text(sport)
            await query.edit_message_text(
                text, parse_mode=ParseMode.HTML,
                reply_markup=kb_onboarding_favourites(edit_sport, ob["favourites"].get(edit_sport, [])),
            )
            return
        # No favourites for this sport, return to summary
        ob["_editing"] = None
        ob["step"] = "summary"
        await _show_summary(query, ob)
        return

    await _show_league_step(query, ob)


async def _show_fav_step(query, ob: dict) -> None:
    """Show favourite selection for the current sport."""
    idx = ob.get("_fav_idx", 0)
    sports = ob["selected_sports"]

    while idx < len(sports):
        sport_key = sports[idx]
        sport = config.ALL_SPORTS.get(sport_key)
        if not sport:
            idx += 1
            ob["_fav_idx"] = idx
            continue

        # Skip sports with fav_type == "skip" (horse racing)
        if sport.fav_type == "skip":
            idx += 1
            ob["_fav_idx"] = idx
            continue

        # Check if there are any teams/players to show
        teams = _get_all_teams_for_sport(sport_key)
        if not teams:
            idx += 1
            ob["_fav_idx"] = idx
            continue

        # Show favourites selection
        text = _fav_step_text(sport)
        existing = ob["favourites"].get(sport_key, [])
        await query.edit_message_text(
            text, parse_mode=ParseMode.HTML,
            reply_markup=kb_onboarding_favourites(sport_key, existing),
        )
        return

    # All favourites done — move to risk
    ob["step"] = "risk"
    text = "<b>Step 5/7: Risk profile</b>\n\nHow aggressive should your tips be?"
    await query.edit_message_text(
        text, parse_mode=ParseMode.HTML,
        reply_markup=kb_onboarding_risk(),
    )


def _fav_step_text(sport: config.SportDef) -> str:
    """Build the text for the favourites step."""
    label = config.fav_label(sport)
    return (
        f"<b>Step 4/7: Select your {label}s for {sport.emoji} {sport.label}</b>\n\n"
        f"Tap to toggle, or type manually."
    )


async def handle_ob_league(query, action: str) -> None:
    """Toggle a league selection."""
    user_id = query.from_user.id
    ob = _get_ob(user_id)

    parts = action.split(":", 1)
    sport_key = parts[0]
    league_key = parts[1] if len(parts) > 1 else ""

    if sport_key not in ob["selected_leagues"]:
        ob["selected_leagues"][sport_key] = []

    leagues = ob["selected_leagues"][sport_key]
    if league_key in leagues:
        leagues.remove(league_key)
    else:
        leagues.append(league_key)

    sport = config.ALL_SPORTS.get(sport_key)
    label = sport.label if sport else sport_key
    emoji = sport.emoji if sport else "🏅"
    text = f"<b>Step 3/7: Select leagues for {emoji} {label}</b>\n\nTap to toggle."
    await query.edit_message_text(
        text, parse_mode=ParseMode.HTML,
        reply_markup=kb_onboarding_leagues(sport_key, leagues),
    )


async def handle_ob_fav(query, action: str) -> None:
    """Toggle a favourite team/player selection."""
    user_id = query.from_user.id
    ob = _get_ob(user_id)

    parts = action.split(":", 1)
    sport_key = parts[0]
    try:
        idx = int(parts[1]) if len(parts) > 1 else -1
    except ValueError:
        return

    teams = _get_all_teams_for_sport(sport_key)
    if idx < 0 or idx >= len(teams):
        return

    name = teams[idx]
    if sport_key not in ob["favourites"]:
        ob["favourites"][sport_key] = []

    favs = ob["favourites"][sport_key]
    if name in favs:
        favs.remove(name)
    else:
        favs.append(name)

    sport = config.ALL_SPORTS.get(sport_key)
    text = _fav_step_text(sport) if sport else "<b>Step 4/7</b>"
    await query.edit_message_text(
        text, parse_mode=ParseMode.HTML,
        reply_markup=kb_onboarding_favourites(sport_key, favs),
    )


async def handle_ob_fav_manual(query, sport_key: str) -> None:
    """Switch to manual text input mode for favourite."""
    user_id = query.from_user.id
    ob = _get_ob(user_id)
    ob["_fav_manual"] = True
    ob["_fav_manual_sport"] = sport_key

    sport = config.ALL_SPORTS.get(sport_key)
    label = config.fav_label(sport) if sport else "favourite"
    emoji = sport.emoji if sport else "🏅"
    sport_name = sport.label if sport else sport_key

    text = (
        f"<b>Step 4/7: Type your {label} for {emoji} {sport_name}</b>\n\n"
        f"Type a name and send it. I'll try to match it."
    )
    await query.edit_message_text(
        text, parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("« Back to list", callback_data=f"ob_fav_back:{sport_key}")],
        ]),
    )


async def handle_ob_fav_done(query, sport_key: str) -> None:
    """Done with favourites for this sport, advance to next."""
    user_id = query.from_user.id
    ob = _get_ob(user_id)
    ob["_fav_manual"] = False
    ob["_fav_manual_sport"] = None

    # Check if editing a single sport
    editing = ob.get("_editing")
    if editing and editing.startswith("sport:"):
        ob["_editing"] = None
        ob["step"] = "summary"
        await _show_summary(query, ob)
        return

    ob["_fav_idx"] = ob.get("_fav_idx", 0) + 1
    await _show_fav_step(query, ob)


async def handle_ob_fav_suggest(query, action: str) -> None:
    """Accept a fuzzy match suggestion."""
    user_id = query.from_user.id
    ob = _get_ob(user_id)

    parts = action.split(":", 1)
    sport_key = parts[0]
    try:
        idx = int(parts[1]) if len(parts) > 1 else -1
    except ValueError:
        return

    suggestions = ob.get("_suggestions", [])
    if idx < 0 or idx >= len(suggestions):
        return

    name = suggestions[idx]
    if sport_key not in ob["favourites"]:
        ob["favourites"][sport_key] = []
    if name not in ob["favourites"][sport_key]:
        ob["favourites"][sport_key].append(name)

    ob["_suggestions"] = []
    ob["_fav_manual"] = False
    ob["_fav_manual_sport"] = None

    # Show favourites with the new selection
    sport = config.ALL_SPORTS.get(sport_key)
    text = _fav_step_text(sport) if sport else "<b>Step 4/7</b>"
    await query.edit_message_text(
        text, parse_mode=ParseMode.HTML,
        reply_markup=kb_onboarding_favourites(sport_key, ob["favourites"][sport_key]),
    )


async def handle_ob_risk(query, risk_key: str) -> None:
    """Set risk profile during onboarding."""
    user_id = query.from_user.id
    ob = _get_ob(user_id)
    ob["risk"] = risk_key
    ob["step"] = "notify"

    text = "<b>Step 6/7: Daily picks notification</b>\n\nWhen do you want your daily tips?"
    await query.edit_message_text(
        text, parse_mode=ParseMode.HTML,
        reply_markup=kb_onboarding_notify(),
    )


async def handle_ob_notify(query, hour_str: str) -> None:
    """Set notification hour during onboarding."""
    user_id = query.from_user.id
    ob = _get_ob(user_id)
    ob["notify_hour"] = int(hour_str)

    # Check if editing risk+notify — go back to summary
    if ob.get("_editing") == "risk":
        ob["_editing"] = None
        ob["step"] = "summary"
        await _show_summary(query, ob)
        return

    ob["step"] = "summary"
    await _show_summary(query, ob)


async def _show_summary(query, ob: dict) -> None:
    """Show onboarding summary with edit buttons."""
    sports_lines = []
    for sk in ob["selected_sports"]:
        sport = config.ALL_SPORTS.get(sk)
        label = f"{sport.emoji} {sport.label}" if sport else sk
        leagues = ob["selected_leagues"].get(sk, [])
        favs = ob["favourites"].get(sk, [])

        league_labels = []
        if sport:
            for lg in sport.leagues:
                if lg.key in leagues:
                    league_labels.append(lg.label)

        line = f"  • {label}"
        if league_labels:
            line += f" ({', '.join(league_labels)})"
        if favs:
            line += f"\n    ❤️ {', '.join(favs)}"
        sports_lines.append(line)

    risk_label = config.RISK_PROFILES.get(ob["risk"], {}).get("label", ob["risk"] or "Not set")
    hour = ob.get("notify_hour")
    notify_str = f"{hour}:00" if hour is not None else "Not set"

    text = textwrap.dedent(f"""\
        <b>Step 7/7: Your profile summary</b>

        <b>Sports:</b>
    """) + "\n".join(sports_lines) + textwrap.dedent(f"""

        <b>Risk:</b> {risk_label}
        <b>Daily picks:</b> {notify_str}

        All good? Tap <b>Let's go!</b> to start.
    """)

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 Let's go!", callback_data="ob_done:finish")],
        [InlineKeyboardButton("✏️ Edit Sports & Favourites", callback_data="ob_edit:sports")],
        [InlineKeyboardButton("⚙️ Edit Risk & Notifications", callback_data="ob_edit:risk")],
    ])
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)


# ── Summary edit handlers ─────────────────────────────────

async def handle_ob_edit(query, action: str) -> None:
    """Handle edit actions from the summary screen."""
    user_id = query.from_user.id
    ob = _get_ob(user_id)

    if action == "sports":
        # Show list of selected sports as buttons for re-editing
        rows: list[list[InlineKeyboardButton]] = []
        for sk in ob["selected_sports"]:
            sport = config.ALL_SPORTS.get(sk)
            if sport:
                rows.append([InlineKeyboardButton(
                    f"{sport.emoji} {sport.label}",
                    callback_data=f"ob_edit:sport:{sk}",
                )])
        rows.append([InlineKeyboardButton("« Back to summary", callback_data="ob_summary:show")])
        text = "<b>✏️ Edit which sport?</b>\n\nTap a sport to re-edit its leagues and favourites."
        await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(rows))

    elif action.startswith("sport:"):
        # Re-edit a specific sport's leagues
        sport_key = action.split(":", 1)[1]
        ob["_editing"] = f"sport:{sport_key}"
        sport = config.ALL_SPORTS.get(sport_key)
        if not sport:
            ob["_editing"] = None
            await _show_summary(query, ob)
            return

        # If single league, skip to favourites
        if len(sport.leagues) == 1:
            ob["selected_leagues"][sport_key] = [sport.leagues[0].key]
            if sport.fav_type != "skip":
                text = _fav_step_text(sport)
                await query.edit_message_text(
                    text, parse_mode=ParseMode.HTML,
                    reply_markup=kb_onboarding_favourites(sport_key, ob["favourites"].get(sport_key, [])),
                )
            else:
                ob["_editing"] = None
                ob["step"] = "summary"
                await _show_summary(query, ob)
            return

        # Show league selection
        existing = ob["selected_leagues"].get(sport_key, [])
        text = f"<b>Edit leagues for {sport.emoji} {sport.label}</b>\n\nTap to toggle."
        await query.edit_message_text(
            text, parse_mode=ParseMode.HTML,
            reply_markup=kb_onboarding_leagues(sport_key, existing),
        )

    elif action == "risk":
        # Re-edit risk + notification
        ob["_editing"] = "risk"
        ob["step"] = "risk"
        text = "<b>🎯 Change Risk Profile</b>\n\nSelect your risk tolerance:"
        await query.edit_message_text(
            text, parse_mode=ParseMode.HTML,
            reply_markup=kb_onboarding_risk(),
        )


async def handle_ob_summary(query, action: str) -> None:
    """Return to summary from edit screens."""
    user_id = query.from_user.id
    ob = _get_ob(user_id)
    ob["_editing"] = None
    ob["step"] = "summary"
    await _show_summary(query, ob)


async def handle_ob_done(query) -> None:
    """Persist onboarding data and route by experience level."""
    user_id = query.from_user.id
    ob = _get_ob(user_id)

    # Save to DB
    await db.clear_user_sport_prefs(user_id)
    for sk in ob["selected_sports"]:
        leagues = ob["selected_leagues"].get(sk, [])
        favs = ob["favourites"].get(sk, [])
        fav_str = ", ".join(favs) if favs else None
        if leagues:
            for lg_key in leagues:
                await db.save_sport_pref(user_id, sk, league=lg_key, team_name=fav_str)
        else:
            await db.save_sport_pref(user_id, sk, team_name=fav_str)

    if ob["risk"]:
        await db.update_user_risk(user_id, ob["risk"])
    if ob.get("notify_hour") is not None:
        await db.update_user_notification_hour(user_id, ob["notify_hour"])
    if ob.get("experience"):
        await db.update_user_experience(user_id, ob["experience"])

    await db.set_onboarding_done(user_id)
    experience = ob.get("experience", "casual")
    _onboarding_state.pop(user_id, None)

    user = query.from_user

    if experience == "experienced":
        text = textwrap.dedent(f"""\
            <b>🇿🇦 You're all set, {user.first_name}!</b>

            Let's find today's value bets right away.
        """)
        await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb_main())
        await _do_picks(user_id=user_id, reply=query.edit_message_text)
    elif experience == "newbie":
        text = textwrap.dedent(f"""\
            <b>🇿🇦 Welcome aboard, {user.first_name}!</b>

            <b>🎓 Quick Lesson: How Odds Work</b>

            Decimal odds show your total payout per R1 bet.
            • Odds of <b>2.00</b> = bet R10, get R20 back (R10 profit)
            • Odds of <b>3.50</b> = bet R10, get R35 back (R25 profit)

            <b>Higher odds = less likely but bigger payout.</b>

            MzansiEdge finds bets where the odds are <i>better than they should be</i> — that's called <b>value</b>.

            Tap <b>📊 Daily Briefing</b> when you're ready!
        """)
        await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb_main())
    else:
        text = textwrap.dedent(f"""\
            <b>🇿🇦 You're all set, {user.first_name}!</b>

            Pick a sport below or tap <b>📊 Daily Briefing</b> for today's picks.
        """)
        await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb_main())


# ── Free-text handler ────────────────────────────────────

async def freetext_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle free text — favourite input during onboarding OR AI chat."""
    user = update.effective_user
    ob = _onboarding_state.get(user.id)

    # If in manual favourite input mode
    if ob and ob.get("_fav_manual") and ob.get("_fav_manual_sport"):
        sport_key = ob["_fav_manual_sport"]
        text_input = update.message.text.strip()

        match, suggestions = fuzzy_match_team(text_input, sport_key)

        if match:
            # Good match — add it
            if sport_key not in ob["favourites"]:
                ob["favourites"][sport_key] = []
            if match not in ob["favourites"][sport_key]:
                ob["favourites"][sport_key].append(match)

            ob["_fav_manual"] = False
            ob["_fav_manual_sport"] = None

            sport = config.ALL_SPORTS.get(sport_key)
            fav_text = _fav_step_text(sport) if sport else "<b>Step 4/7</b>"
            await update.message.reply_text(
                f"✅ Added <b>{match}</b>!\n\n{fav_text}",
                parse_mode=ParseMode.HTML,
                reply_markup=kb_onboarding_favourites(sport_key, ob["favourites"][sport_key]),
            )
        elif suggestions:
            # Ambiguous — show "Did you mean?" buttons
            ob["_suggestions"] = suggestions
            rows = []
            for i, s in enumerate(suggestions):
                rows.append([InlineKeyboardButton(s, callback_data=f"ob_fav_suggest:{sport_key}:{i}")])
            rows.append([InlineKeyboardButton("❌ None of these", callback_data=f"ob_fav_manual:{sport_key}")])

            await update.message.reply_text(
                f"🤔 Did you mean one of these?",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(rows),
            )
        else:
            # No match at all — add as-is
            if sport_key not in ob["favourites"]:
                ob["favourites"][sport_key] = []
            ob["favourites"][sport_key].append(text_input)

            ob["_fav_manual"] = False
            ob["_fav_manual_sport"] = None

            sport = config.ALL_SPORTS.get(sport_key)
            fav_text = _fav_step_text(sport) if sport else "<b>Step 4/7</b>"
            await update.message.reply_text(
                f"✅ Added <b>{text_input}</b>!\n\n{fav_text}",
                parse_mode=ParseMode.HTML,
                reply_markup=kb_onboarding_favourites(sport_key, ob["favourites"][sport_key]),
            )
        return

    # Normal AI chat
    user_msg = update.message.text
    await update.message.reply_text("🤖 <i>Thinking…</i>", parse_mode=ParseMode.HTML)

    try:
        resp = await claude.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
        reply = resp.content[0].text
    except Exception as exc:
        log.error("Claude chat error: %s", exc)
        reply = "⚠️ Couldn't process that. Try again or use the menu buttons."

    await update.message.reply_text(reply, parse_mode=ParseMode.HTML, reply_markup=kb_nav())


# ── /picks — Today's value bets ───────────────────────────

LOADING_VERBS = [
    "Scanning markets", "Crunching numbers", "Hunting value",
    "Analysing odds", "Finding edges",
]

async def cmd_picks(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Entry point for /picks command."""
    await _do_picks(
        user_id=update.effective_user.id,
        reply=update.message.reply_text,
    )


async def handle_picks(query, action: str) -> None:
    """Callback handler for picks:go and picks:today buttons."""
    if action in ("go", "today"):
        await _do_picks(
            user_id=query.from_user.id,
            reply=query.edit_message_text,
        )


async def _do_picks(user_id: int, reply) -> None:
    """Core picks logic — fetch odds for user's leagues, compute EV, display cards."""
    import random
    verb = random.choice(LOADING_VERBS)
    await reply(f"🎯 <i>{verb}…</i>", parse_mode=ParseMode.HTML)

    # Load user profile
    user = await db.get_user(user_id)
    risk_key = (user.risk_profile if user else None) or "moderate"
    profile = config.RISK_PROFILES.get(risk_key, config.RISK_PROFILES["moderate"])
    min_ev = profile["min_ev"]
    kelly_frac = profile["kelly_fraction"]
    experience = (user.experience_level if user else None) or "casual"

    # Get user's preferred leagues (fall back to all)
    prefs = await db.get_user_sport_prefs(user_id)
    if prefs:
        league_keys = list({p.league for p in prefs if p.league})
    else:
        league_keys = list(config.SPORTS_MAP.keys())

    # Fetch odds and scan for value
    all_picks = []
    for lk in league_keys:
        league = config.ALL_LEAGUES.get(lk)
        api_key = league.api_key if league else config.SPORTS_MAP.get(lk)
        if not api_key:
            continue
        sport_key = config.LEAGUE_SPORT.get(lk, lk)
        try:
            events = await fetch_odds(api_key)
            picks = scan_value_bets(
                events, sport_key=sport_key,
                min_ev=min_ev, kelly_fraction=kelly_frac,
            )
            all_picks.extend(picks)
        except Exception as exc:
            log.warning("Picks fetch error for %s: %s", lk, exc)

    # Sort by EV descending, take top 10
    all_picks.sort(key=lambda p: p.ev_pct, reverse=True)
    top_picks = all_picks[:10]

    if not top_picks:
        risk_label = profile["label"]
        if experience == "newbie":
            text = (
                "<b>🎯 Today's Picks</b>\n\n"
                "No value bets found right now.\n\n"
                "This means bookmaker odds are fair — no easy edges today.\n"
                "Check back later! We scan markets throughout the day."
            )
        else:
            text = (
                "<b>🎯 Today's Picks</b>\n\n"
                f"No value bets found above <b>{min_ev:.0f}% EV</b> "
                f"for your {risk_label} profile right now.\n\n"
                "Try again later or switch to a more aggressive profile."
            )
        await reply(text, parse_mode=ParseMode.HTML, reply_markup=kb_nav())
        return

    # Build header based on experience
    if experience == "newbie":
        header = (
            f"<b>🎯 Today's Picks</b> ({len(top_picks)} bet{'s' if len(top_picks) != 1 else ''})\n"
            f"We found bets where the odds are better than they should be!\n"
        )
    elif experience == "casual":
        header = (
            f"<b>🎯 Today's Picks</b> ({len(top_picks)} value bet{'s' if len(top_picks) != 1 else ''})\n"
            f"Profile: {profile['label']}\n"
        )
    else:
        header = (
            f"<b>🎯 Today's Picks</b> ({len(top_picks)} value bet{'s' if len(top_picks) != 1 else ''})\n"
            f"Profile: {profile['label']} | Min EV: {min_ev:.0f}%\n"
        )

    lines = [header]
    for pick in top_picks:
        lines.append(format_pick_card(pick, experience=experience))
        lines.append("")  # spacer

    lines.append("<i>Always gamble responsibly. 🇿🇦</i>")
    text = "\n".join(lines)

    # Chunked sending for long messages
    if len(text) > 4000:
        chunks = _chunk_message(text, 4000)
        for i, chunk in enumerate(chunks):
            if i == len(chunks) - 1:
                await reply(chunk, parse_mode=ParseMode.HTML, reply_markup=kb_nav())
            else:
                await reply(chunk, parse_mode=ParseMode.HTML)
    else:
        await reply(text, parse_mode=ParseMode.HTML, reply_markup=kb_nav())


def _chunk_message(text: str, max_len: int = 4000) -> list[str]:
    """Split a long message into chunks at line boundaries."""
    lines = text.split("\n")
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for line in lines:
        line_len = len(line) + 1
        if current_len + line_len > max_len and current:
            chunks.append("\n".join(current))
            current = [line]
            current_len = line_len
        else:
            current.append(line)
            current_len += line_len

    if current:
        chunks.append("\n".join(current))
    return chunks


# ── Sub-menu handlers ────────────────────────────────────

async def handle_bets(query, action: str) -> None:
    """Handle bets:* callbacks."""
    if action == "active":
        text = (
            "<b>💰 My Bets</b>\n\n"
            "No active bets yet.\n\n"
            "Tap <b>📊 Daily Briefing</b> to find today's value bets!"
        )
    elif action == "history":
        tips = await db.get_recent_tips(limit=5)
        if not tips:
            text = "<b>📜 Bet History</b>\n\nNo bets recorded yet."
        else:
            lines = ["<b>📜 Recent Bets</b>\n"]
            for t in tips:
                icon = {"win": "✅", "loss": "❌"}.get(t.result, "⏳")
                lines.append(
                    f"{icon} <b>{t.match}</b>\n"
                    f"   {t.prediction}"
                    + (f" @ {t.odds:.2f}" if t.odds else "")
                )
            text = "\n".join(lines)
    else:
        text = "<b>💰 My Bets</b>"
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb_bets())


async def handle_teams(query, action: str) -> None:
    """Handle teams:* callbacks."""
    user_id = query.from_user.id
    if action in ("view", "edit"):
        prefs = await db.get_user_sport_prefs(user_id)
        teams_with_names = [p for p in prefs if p.team_name]
        if not teams_with_names:
            text = (
                "<b>🏟️ My Teams</b>\n\n"
                "No favourite teams set yet.\n"
                "Use /start to redo onboarding and pick your teams."
            )
        else:
            lines = ["<b>🏟️ My Teams</b>\n"]
            seen: set[str] = set()
            for p in teams_with_names:
                key = f"{p.sport_key}:{p.team_name}"
                if key in seen:
                    continue
                seen.add(key)
                sport = config.ALL_SPORTS.get(p.sport_key)
                emoji = sport.emoji if sport else "🏅"
                label = sport.label if sport else p.sport_key
                lines.append(f"  {emoji} <b>{label}</b>: ❤️ {p.team_name}")
            text = "\n".join(lines)
    else:
        text = "<b>🏟️ My Teams</b>"
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb_teams())


async def handle_stats_menu(query, action: str) -> None:
    """Handle stats:* callbacks."""
    if action == "overview":
        tips = await db.get_recent_tips(limit=100)
        total = len(tips)
        wins = sum(1 for t in tips if t.result == "win")
        losses = sum(1 for t in tips if t.result == "loss")
        pending = sum(1 for t in tips if t.result is None or t.result == "pending")
        win_rate = f"{wins / (wins + losses) * 100:.0f}%" if (wins + losses) > 0 else "N/A"
        text = textwrap.dedent(f"""\
            <b>📈 Stats Overview</b>

            📝 Total tips: <b>{total}</b>
            ✅ Wins: <b>{wins}</b> | ❌ Losses: <b>{losses}</b>
            ⏳ Pending: <b>{pending}</b>
            🎯 Win rate: <b>{win_rate}</b>
        """)
    elif action == "leaderboard":
        text = (
            "<b>🏆 Leaderboard</b>\n\n"
            "Coming soon! Track your performance against other users."
        )
    else:
        text = "<b>📈 Stats</b>"
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb_stats())


async def handle_affiliate(query, action: str) -> None:
    """Handle affiliate:* callbacks (bookmaker comparison)."""
    if action in ("compare", "sa"):
        text = textwrap.dedent("""\
            <b>🎰 SA Bookmakers</b>

            🇿🇦 <b>Hollywoodbets</b> — Best for soccer & horse racing
            🇿🇦 <b>Betway</b> — Great odds, fast payouts
            🇿🇦 <b>Supabets</b> — Wide range of markets
            🇿🇦 <b>Sportingbet</b> — Reliable, good promos
            🇿🇦 <b>Sunbet</b> — Sun International backed
            🇿🇦 <b>GBets</b> — Growing fast, good value

            <i>Always gamble responsibly. 18+ only.</i>
        """)
    elif action == "intl":
        text = textwrap.dedent("""\
            <b>🌍 International Bookmakers</b>

            🌐 <b>Bet365</b> — Widest market coverage
            🌐 <b>1xBet</b> — High odds across sports
            🌐 <b>Pinnacle</b> — Best odds, low margins

            <i>Check local regulations. Gamble responsibly.</i>
        """)
    else:
        text = "<b>🎰 Bookmakers</b>"
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb_bookmakers())


async def handle_settings(query, action: str) -> None:
    """Handle settings:* callbacks."""
    user_id = query.from_user.id
    user = await db.get_user(user_id)

    if action == "home":
        risk_label = config.RISK_PROFILES.get(
            user.risk_profile if user else "moderate", {}
        ).get("label", "Not set")
        hour = user.notification_hour if user else None
        notify_str = f"{hour}:00" if hour is not None else "Not set"
        exp = (user.experience_level if user else None) or "Not set"

        text = textwrap.dedent(f"""\
            <b>⚙️ Settings</b>

            🎯 Risk profile: <b>{risk_label}</b>
            ⏰ Daily picks: <b>{notify_str}</b>
            🎓 Experience: <b>{exp.title()}</b>
        """)
        await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb_settings())
    elif action == "risk":
        text = "<b>🎯 Change Risk Profile</b>\n\nSelect your risk tolerance:"
        await query.edit_message_text(
            text, parse_mode=ParseMode.HTML,
            reply_markup=kb_onboarding_risk(),
        )
    elif action == "notify":
        text = "<b>⏰ Change Notification Time</b>\n\nWhen do you want daily picks?"
        await query.edit_message_text(
            text, parse_mode=ParseMode.HTML,
            reply_markup=kb_onboarding_notify(),
        )
    elif action == "sports":
        text = (
            "<b>⚽ Change Sports</b>\n\n"
            "Use /start to redo onboarding and update your sports."
        )
        await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb_settings())
    elif action == "reset":
        text = textwrap.dedent("""\
            <b>⚠️ Reset your profile?</b>

            This will clear all your preferences, sports selections,
            teams, and risk settings. You'll go through the onboarding
            quiz again from scratch.

            Your betting history and stats will <b>NOT</b> be deleted.
        """)
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⚠️ Yes, reset everything", callback_data="settings:reset:confirm")],
            [InlineKeyboardButton("🔙 Cancel", callback_data="settings:home")],
        ])
        await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
    elif action == "reset:confirm":
        await db.reset_user_profile(user_id)
        _onboarding_state.pop(user_id, None)
        text = textwrap.dedent("""\
            <b>✅ Profile reset!</b>

            All preferences have been cleared.
            Tap below to start fresh.
        """)
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🚀 Start onboarding", callback_data="ob_restart:go")],
        ])
        await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
    else:
        await query.edit_message_text("<b>⚙️ Settings</b>", parse_mode=ParseMode.HTML, reply_markup=kb_settings())


# ── Restart / back handlers ──────────────────────────────

async def handle_ob_restart(query) -> None:
    """Restart onboarding from scratch (after profile reset)."""
    user_id = query.from_user.id
    _onboarding_state.pop(user_id, None)
    ob = _get_ob(user_id)
    ob["step"] = "experience"
    text = textwrap.dedent(f"""\
        <b>🇿🇦 Let's set up your profile!</b>

        <b>Step 1/7:</b> What's your betting experience?
    """)
    await query.edit_message_text(
        text, parse_mode=ParseMode.HTML,
        reply_markup=kb_onboarding_experience(),
    )


async def handle_ob_fav_back(query, sport_key: str) -> None:
    """Return from manual input to the favourites button grid."""
    user_id = query.from_user.id
    ob = _get_ob(user_id)
    ob["_fav_manual"] = False
    ob["_fav_manual_sport"] = None

    sport = config.ALL_SPORTS.get(sport_key)
    text = _fav_step_text(sport) if sport else "<b>Step 4/7</b>"
    existing = ob["favourites"].get(sport_key, [])
    await query.edit_message_text(
        text, parse_mode=ParseMode.HTML,
        reply_markup=kb_onboarding_favourites(sport_key, existing),
    )


# ── /admin — admin dashboard with API quota ───────────────

async def cmd_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin-only command showing API quota and bot stats."""
    if update.effective_user.id not in config.ADMIN_IDS:
        return

    quota = get_quota()
    count = await db.get_user_count()
    tips = await db.get_recent_tips(limit=100)
    wins = sum(1 for t in tips if t.result == "win")
    losses = sum(1 for t in tips if t.result == "loss")
    pending = sum(1 for t in tips if t.result is None or t.result == "pending")

    text = textwrap.dedent(f"""\
        <b>🔧 Admin Dashboard</b>

        <b>📡 Odds API Quota</b>
        Requests used: <code>{quota['requests_used']}</code>
        Requests remaining: <code>{quota['requests_remaining']}</code>

        <b>📊 Bot Stats</b>
        👥 Users: <b>{count}</b>
        📝 Tips: <b>{len(tips)}</b>
        ✅ Wins: <b>{wins}</b> | ❌ Losses: <b>{losses}</b> | ⏳ Pending: <b>{pending}</b>
    """)
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


# ── Admin: /stats ─────────────────────────────────────────

async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in config.ADMIN_IDS:
        return
    count = await db.get_user_count()
    tips = await db.get_recent_tips(limit=100)
    wins = sum(1 for t in tips if t.result == "win")
    losses = sum(1 for t in tips if t.result == "loss")
    pending = sum(1 for t in tips if t.result is None or t.result == "pending")
    text = textwrap.dedent(f"""\
        <b>📊 Admin Stats</b>

        👥 Users: <b>{count}</b>
        📝 Tips: <b>{len(tips)}</b>
        ✅ Wins: <b>{wins}</b> | ❌ Losses: <b>{losses}</b> | ⏳ Pending: <b>{pending}</b>
    """)
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


# ── Main ──────────────────────────────────────────────────

def main() -> None:
    log.info("Starting MzansiEdge bot…")
    app = Application.builder().token(config.BOT_TOKEN).build()

    # Initialise DB on startup
    app.post_init = lambda _app: db.init_db()

    # Command handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("menu", cmd_menu))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("odds", cmd_odds))
    app.add_handler(CommandHandler("tip", cmd_tip))
    app.add_handler(CommandHandler("picks", cmd_picks))
    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(CommandHandler("stats", cmd_stats))

    # Callback query handler (prefix:action routing)
    app.add_handler(CallbackQueryHandler(on_button))

    # Free-text chat (also handles favourite input during onboarding)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, freetext_handler))

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
