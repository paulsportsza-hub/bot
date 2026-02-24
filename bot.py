#!/usr/bin/env python3
"""MzansiEdge — AI-powered sports betting Telegram bot for South Africa."""

from __future__ import annotations

import difflib
import logging
import textwrap

import anthropic
from telegram import (
    InlineKeyboardButton, InlineKeyboardMarkup,
    KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove,
    Update,
)
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
    fetch_odds, format_odds_message,
    get_quota, scan_value_bets,
)
from scripts.picks_engine import (
    get_picks_for_user,
    format_pick_card as format_engine_pick_card,
)
from services.user_service import (
    classify_archetype,
    get_profile_data,
    persist_onboarding,
)
from services.picks_service import get_picks as svc_get_picks
from services.schedule_service import get_schedule, get_game_tips_data

logging.basicConfig(
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("mzansiedge")

claude = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)

# ── Onboarding state machine ─────────────────────────────
# Steps: experience → sports → leagues → favourites → risk → bankroll → notify → summary
ONBOARD_STEPS = ("experience", "sports", "leagues", "favourites", "risk", "bankroll", "notify", "summary")

# Per-user in-memory onboarding state
_onboarding_state: dict[int, dict] = {}

# Per-user story/notification quiz state
_story_state: dict[int, dict] = {}

# Per-user settings team edit state
_team_edit_state: dict[int, dict] = {}


# ── Persistent Reply Keyboard ──────────────────────────────
# Always-visible bottom keyboard (separate from inline keyboards)

_KEYBOARD_LABELS = ["🎯 Picks", "📅 Schedule", "🔴 Live", "📊 Stats", "⚙️ Settings", "❓ Help"]

def get_main_keyboard() -> ReplyKeyboardMarkup:
    """Return the persistent 2×3 reply keyboard."""
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("🎯 Picks"), KeyboardButton("📅 Schedule"), KeyboardButton("🔴 Live")],
            [KeyboardButton("📊 Stats"), KeyboardButton("⚙️ Settings"), KeyboardButton("❓ Help")],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


STORY_STEPS = ["daily_picks", "game_day_alerts", "weekly_recap", "edu_tips", "market_movers", "live_scores"]

STORY_PROMPTS: dict[str, dict] = {
    "daily_picks": {
        "title": "📊 <b>Daily Picks</b>",
        "body": (
            "Want me to send you AI-powered value bets every day?\n\n"
            "I'll scan your leagues each morning, find the edges,\n"
            "and send them straight to you."
        ),
        "yes": "✅ Yes — Send me daily picks",
        "no": "❌ No — I'll check manually",
    },
    "game_day_alerts": {
        "title": "🏟️ <b>Game Day Alerts</b>",
        "body": (
            "Get a heads-up when your followed teams are playing today?\n\n"
            "Includes kickoff times and quick pre-match tips."
        ),
        "yes": "✅ Yes — Alert me on game days",
        "no": "❌ No thanks",
    },
    "weekly_recap": {
        "title": "📈 <b>Weekly Recap</b>",
        "body": (
            "Every Sunday, I can send you a recap of the week:\n"
            "how your picks performed, bankroll movement, and\n"
            "what's coming up next week."
        ),
        "yes": "✅ Yes — Send weekly recaps",
        "no": "❌ Skip this one",
    },
    "edu_tips": {
        "title": "🎓 <b>Betting Education</b>",
        "body": (
            "I'll send you short, practical tips to level up\n"
            "your betting game. Things like:\n\n"
            "• How odds work\n"
            "• Reading form guides\n"
            "• Bankroll management basics\n"
            "• Spotting value vs. hype\n\n"
            "One tip every few days — no spam."
        ),
        "yes": "✅ Yes — Teach me",
        "no": "❌ I'm good",
    },
    "market_movers": {
        "title": "📉 <b>Market Movers</b>",
        "body": (
            "Get alerted when odds shift significantly on games\n"
            "you're watching. Big line movements often signal\n"
            "sharp money or breaking news."
        ),
        "yes": "✅ Yes — Alert me",
        "no": "❌ Not interested",
    },
    "live_scores": {
        "title": "⚡ <b>Live Score Updates</b>",
        "body": (
            "Get real-time score updates for games you're following.\n\n"
            "Goals, tries, wickets — I'll ping you as they happen\n"
            "so you never miss a moment."
        ),
        "yes": "✅ Yes — Send live updates",
        "no": "❌ No — I'll check myself",
    },
}


def _get_ob(user_id: int) -> dict:
    """Get or create onboarding state for a user."""
    if user_id not in _onboarding_state:
        _onboarding_state[user_id] = {
            "step": "experience",
            "experience": None,         # experienced / casual / newbie
            "selected_sports": [],      # category keys: ["soccer", "rugby"]
            "selected_leagues": {},     # sport_key → [league_key, ...]
            "favourites": {},           # sport_key → {league_key: [name, ...], ...}
            "risk": None,
            "bankroll": None,
            "notify_hour": None,
            "_league_idx": 0,
            "_fav_idx": 0,
            "_fav_manual": False,       # in manual input mode
            "_fav_manual_sport": None,  # which sport we're inputting for
            "_editing": None,           # None / "sports" / "risk" / "sport:{key}"
            "_suggestions": [],         # fuzzy match suggestions
            "_team_input_sport": None,  # sport key for text-based team input
            "_team_input_league": None, # league key for text-based team input
            "_fav_league_queue": [],    # leagues to prompt for teams
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


# ── League abbreviation helper ────────────────────────────

_LEAGUE_ABBREV: dict[str, str] = {
    "Champions League": "UCL",
    "Six Nations": "6N",
    "CSA / SA20": "SA20",
    "Rugby Championship": "RC",
    "Rugby World Cup": "RWC",
    "T20 World Cup": "T20 WC",
    "Grand Slams": "Slams",
    "Major Bouts": "Boxing",
    "UFC Events": "UFC",
    "DP World Tour": "DPWT",
    "Formula 1": "F1",
    "SA Horse Racing": "SA Racing",
    "Super Rugby": "Super",
    "Currie Cup": "CC",
    "Test Matches": "Tests",
}


def _abbreviate_league(label: str) -> str:
    """Shorten long league names for compact display."""
    return _LEAGUE_ABBREV.get(label, label)


# ── Keyboards ─────────────────────────────────────────────

def kb_main() -> InlineKeyboardMarkup:
    """Main persistent menu — every sub-screen navigates back here."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Daily Briefing", callback_data="picks:today")],
        [InlineKeyboardButton("📅 Schedule", callback_data="nav:schedule")],
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
            InlineKeyboardButton("↩️ Back", callback_data=back_target),
            InlineKeyboardButton("🏠 Main Menu", callback_data="menu:home"),
        ],
    ])


def kb_bets() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Active Bets", callback_data="bets:active")],
        [InlineKeyboardButton("📜 Bet History", callback_data="bets:history")],
        [
            InlineKeyboardButton("↩️ Back", callback_data="menu:home"),
            InlineKeyboardButton("🏠 Main Menu", callback_data="menu:home"),
        ],
    ])


def kb_teams() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👀 View My Teams", callback_data="teams:view")],
        [InlineKeyboardButton("✏️ Edit Teams", callback_data="teams:edit")],
        [
            InlineKeyboardButton("↩️ Back", callback_data="menu:home"),
            InlineKeyboardButton("🏠 Main Menu", callback_data="menu:home"),
        ],
    ])


def kb_stats() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Overview", callback_data="stats:overview")],
        [InlineKeyboardButton("🏆 Leaderboard", callback_data="stats:leaderboard")],
        [
            InlineKeyboardButton("↩️ Back", callback_data="menu:home"),
            InlineKeyboardButton("🏠 Main Menu", callback_data="menu:home"),
        ],
    ])


def kb_bookmakers() -> InlineKeyboardMarkup:
    active = config.get_active_bookmaker()
    website = active.get("website_url", "")
    guide = active.get("guide_url", "")
    buttons: list[list[InlineKeyboardButton]] = []
    if website:
        buttons.append([InlineKeyboardButton(
            f"🇿🇦 {active['short_name']} — Sign Up", url=website,
        )])
    if guide:
        buttons.append([InlineKeyboardButton(
            f"📖 How to Bet on {active['short_name']}", url=guide,
        )])
    buttons.append([
        InlineKeyboardButton("↩️ Back", callback_data="menu:home"),
        InlineKeyboardButton("🏠 Main Menu", callback_data="menu:home"),
    ])
    return InlineKeyboardMarkup(buttons)


def kb_settings() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎯 Risk Profile", callback_data="settings:risk")],
        [InlineKeyboardButton("💰 Bankroll", callback_data="settings:bankroll")],
        [InlineKeyboardButton("⏰ Notifications", callback_data="settings:notify")],
        [InlineKeyboardButton("📖 My Notifications", callback_data="settings:story")],
        [InlineKeyboardButton("⚽ My Sports", callback_data="settings:sports")],
        [InlineKeyboardButton("🔄 Reset Profile", callback_data="settings:reset")],
        [
            InlineKeyboardButton("↩️ Back", callback_data="menu:home"),
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
    rows.append([InlineKeyboardButton("↩️ Back", callback_data="ob_nav:back_experience")])

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
    rows.append([InlineKeyboardButton("↩️ Back", callback_data="ob_nav:back_risk")])
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
        [InlineKeyboardButton("↩️ Back", callback_data="ob_nav:back_notify")],
    ])


def kb_onboarding_bankroll() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("R500", callback_data="ob_bankroll:500"),
            InlineKeyboardButton("R1,000", callback_data="ob_bankroll:1000"),
        ],
        [
            InlineKeyboardButton("R2,000", callback_data="ob_bankroll:2000"),
            InlineKeyboardButton("R5,000", callback_data="ob_bankroll:5000"),
        ],
        [InlineKeyboardButton("🤷 Not sure — skip", callback_data="ob_bankroll:skip")],
        [InlineKeyboardButton("✏️ Custom amount", callback_data="ob_bankroll:custom")],
        [InlineKeyboardButton("↩️ Back", callback_data="ob_nav:back_bankroll")],
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
        # Send sticky keyboard + inline menu
        await update.message.reply_text(
            text, parse_mode=ParseMode.HTML, reply_markup=get_main_keyboard(),
        )
        await update.message.reply_text(
            "👇 <i>Quick menu:</i>", parse_mode=ParseMode.HTML, reply_markup=kb_main(),
        )
    else:
        # Start onboarding — hide sticky keyboard
        _onboarding_state.pop(user.id, None)  # reset
        ob = _get_ob(user.id)
        ob["step"] = "experience"
        # Remove persistent keyboard during onboarding
        await update.message.reply_text(
            "🇿🇦 Setting up your profile…",
            reply_markup=ReplyKeyboardRemove(),
        )
        text = textwrap.dedent(f"""\
            <b>🇿🇦 Welcome to MzansiEdge, {user.first_name}!</b>

            Let's set up your profile in a few quick steps.

            <b>Step 1/8:</b> What's your betting experience?
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
    await update.message.reply_text(
        text, parse_mode=ParseMode.HTML, reply_markup=get_main_keyboard(),
    )
    await update.message.reply_text(
        "👇 <i>Quick menu:</i>", parse_mode=ParseMode.HTML, reply_markup=kb_main(),
    )


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


# ── /settings ─────────────────────────────────────────────

async def cmd_settings(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Show settings menu directly via /settings command."""
    user = update.effective_user
    db_user = await db.upsert_user(user.id, user.username, user.first_name)

    if not db_user.onboarding_done:
        await update.message.reply_text(
            "⚙️ Complete onboarding first!\n\nUse /start to get set up.",
            parse_mode=ParseMode.HTML,
        )
        return
    await update.message.reply_text(
        "⚙️ <b>Settings</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=kb_settings(),
    )


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
    elif prefix == "nav":
        if action == "main":
            await handle_menu(query, "home")
        elif action == "schedule":
            user_id = query.from_user.id
            text, markup = await _build_schedule(user_id)
            await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
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
    elif prefix == "ob_bankroll":
        await handle_ob_bankroll(query, action)
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
        await handle_picks(query, ctx, action)
    elif prefix == "bets":
        await handle_bets(query, action)
    elif prefix == "teams":
        await handle_teams(query, action)
    elif prefix == "stats":
        await handle_stats_menu(query, action)
    elif prefix == "affiliate":
        await handle_affiliate(query, action)
    elif prefix == "story":
        chat_id = query.message.chat_id
        user_id = query.from_user.id
        if action == "start":
            _story_state[chat_id] = {"step": "daily_picks", "prefs": {}}
            await _show_story_step(query, chat_id)
        elif action.startswith("pref:"):
            parts = action.split(":")
            if len(parts) >= 3:
                pref_key = parts[1]
                value = parts[2] == "yes"
                state = _story_state.get(chat_id, {})
                state.setdefault("prefs", {})[pref_key] = value
                _story_state[chat_id] = state
                await _advance_story_quiz(query, chat_id, user_id)
    elif prefix == "schedule":
        if action.startswith("tips:"):
            event_id = action.split(":", 1)[1]
            await _generate_game_tips(query, ctx, event_id, query.from_user.id)
    elif prefix == "tip":
        if action == "affiliate_soon":
            await query.answer("🔗 Affiliate link coming soon! Check back tomorrow.", show_alert=True)
        elif action == "guide_soon":
            await query.answer("📖 Betting guide coming soon! Check back tomorrow.", show_alert=True)
        else:
            await handle_tip_detail(query, ctx, action)
    elif prefix == "subscribe":
        await handle_subscribe(query, action)
    elif prefix == "unsubscribe":
        await handle_unsubscribe(query, action)
    elif prefix == "settings":
        await handle_settings(query, action)
    elif prefix == "ob_done":
        await handle_ob_done(query, ctx)
    elif prefix == "ob_restart":
        await handle_ob_restart(query)
    elif prefix == "ob_fav_retry":
        # Re-prompt for team input for this sport/league
        user_id = query.from_user.id
        ob_state = _get_ob(user_id)
        sport_key = action
        league_key = ob_state.get("_team_input_league")
        ob_state["_team_input_sport"] = sport_key
        ob_state["_team_input_league"] = league_key
        sport = config.ALL_SPORTS.get(sport_key)
        emoji = sport.emoji if sport else "🏅"
        entity = config.fav_label(sport) if sport else "favourite"
        if league_key:
            lg = config.ALL_LEAGUES.get(league_key)
            league_label = lg.label if lg else league_key
            text = (
                f"<b>{emoji} {league_label} — try again</b>\n\n"
                f"Type your {entity}s separated by commas.\n"
                f"<i>Tip: Use full names or common nicknames.</i>"
            )
        else:
            sport_label = sport.label if sport else sport_key
            text = (
                f"<b>{emoji} {sport_label} — try again</b>\n\n"
                f"Type your {entity}s separated by commas.\n"
                f"<i>Tip: Use full names or common nicknames.</i>"
            )
        await query.edit_message_text(
            text, parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⏭ Skip", callback_data=f"ob_fav_done:{sport_key}")],
            ]),
        )
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
        <b>Step 2/8: Select your sports</b>

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
        <b>Step 2/8: Select your sports</b>

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

    elif action == "back_experience":
        ob["step"] = "experience"
        text = "<b>Step 1/8:</b> What's your betting experience?"
        await query.edit_message_text(
            text, parse_mode=ParseMode.HTML,
            reply_markup=kb_onboarding_experience(),
        )

    elif action == "back_sports":
        ob["step"] = "sports"
        text = "<b>Step 2/8: Select your sports</b>\n\nTap to toggle. Hit <b>Done</b> when ready."
        await query.edit_message_text(
            text, parse_mode=ParseMode.HTML,
            reply_markup=kb_onboarding_sports(ob["selected_sports"]),
        )

    elif action == "back_risk":
        # Back from risk → favourites (re-show last team prompt)
        ob["step"] = "favourites"
        queue = ob.get("_fav_league_queue", [])
        if queue:
            ob["_fav_idx"] = max(0, len(queue) - 1)
            await _show_next_team_prompt(query, ob)
        else:
            # No favourites queue — back to sports
            ob["step"] = "sports"
            text = "<b>Step 2/8: Select your sports</b>\n\nTap to toggle. Hit <b>Done</b> when ready."
            await query.edit_message_text(
                text, parse_mode=ParseMode.HTML,
                reply_markup=kb_onboarding_sports(ob["selected_sports"]),
            )

    elif action == "back_bankroll":
        # Back from bankroll → risk
        ob["step"] = "risk"
        text = "<b>Step 5/8: Risk profile</b>\n\nHow aggressive should your tips be?"
        await query.edit_message_text(
            text, parse_mode=ParseMode.HTML,
            reply_markup=kb_onboarding_risk(),
        )

    elif action == "back_notify":
        # Back from notify → bankroll
        ob["step"] = "bankroll"
        text = (
            "<b>Step 6/8: Weekly bankroll</b>\n\n"
            "How much do you set aside for betting each week?"
        )
        await query.edit_message_text(
            text, parse_mode=ParseMode.HTML,
            reply_markup=kb_onboarding_bankroll(),
        )

    elif action.startswith("league_done:"):
        sport_key = action.split(":", 1)[1]
        await _advance_league_step(query, ob)

    elif action == "favourites_done":
        # Move to risk
        ob["step"] = "risk"
        text = "<b>Step 5/8: Risk profile</b>\n\nHow aggressive should your tips be?"
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
        text = f"<b>Step 3/8: Select leagues for {sport.emoji} {sport.label}</b>\n\nTap to toggle."
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
        sport = config.ALL_SPORTS.get(edit_sport)
        if sport and sport.fav_type != "skip":
            # Build league queue for this sport and show text input
            leagues = ob["selected_leagues"].get(edit_sport, [])
            queue: list[tuple[str, str | None]] = [(edit_sport, lk) for lk in leagues] if leagues else [(edit_sport, None)]
            ob["_fav_league_queue"] = queue
            ob["_fav_idx"] = 0
            ob["step"] = "favourites"
            await _show_next_team_prompt(query, ob)
            return
        ob["_editing"] = None
        ob["step"] = "summary"
        await _show_summary(query, ob)
        return

    await _show_league_step(query, ob)


async def _show_fav_step(query, ob: dict) -> None:
    """Build queue of leagues to prompt for teams, then show first prompt."""
    # Build the full queue of (sport_key, league_key) pairs to prompt
    queue: list[tuple[str, str | None]] = []
    for sk in ob["selected_sports"]:
        sport = config.ALL_SPORTS.get(sk)
        if not sport or sport.fav_type == "skip":
            continue
        leagues = ob["selected_leagues"].get(sk, [])
        if leagues:
            for lk in leagues:
                queue.append((sk, lk))
        else:
            # Sports without league selection (shouldn't happen, but just in case)
            queue.append((sk, None))

    ob["_fav_league_queue"] = queue
    ob["_fav_idx"] = 0
    await _show_next_team_prompt(query, ob)


async def _show_next_team_prompt(query, ob: dict) -> None:
    """Show the text-input prompt for the next league in the queue."""
    queue = ob.get("_fav_league_queue", [])
    idx = ob.get("_fav_idx", 0)

    if idx >= len(queue):
        # All leagues done — move to risk
        ob["step"] = "risk"
        ob["_team_input_sport"] = None
        ob["_team_input_league"] = None
        text = "<b>Step 5/8: Risk profile</b>\n\nHow aggressive should your tips be?"
        await query.edit_message_text(
            text, parse_mode=ParseMode.HTML,
            reply_markup=kb_onboarding_risk(),
        )
        return

    sport_key, league_key = queue[idx]
    sport = config.ALL_SPORTS.get(sport_key)
    emoji = sport.emoji if sport else "🏅"
    entity = config.fav_label(sport) if sport else "favourite"

    # Set state for text input
    ob["step"] = "favourites"
    ob["_team_input_sport"] = sport_key
    ob["_team_input_league"] = league_key

    if league_key:
        lg = config.ALL_LEAGUES.get(league_key)
        league_label = lg.label if lg else league_key
        example = config.LEAGUE_EXAMPLES.get(league_key, "")
        example_line = f"\n<i>{example}</i>\n" if example else ""
        text = (
            f"<b>Step 4/8: {emoji} {league_label} — who do you follow?</b>\n\n"
            f"Type your {entity}s separated by commas.\n"
            f"Max 5 per league.{example_line}\n"
            f"Or type <b>skip</b> to move on."
        )
    else:
        sport_label = sport.label if sport else sport_key
        text = (
            f"<b>Step 4/8: {emoji} {sport_label} — who do you follow?</b>\n\n"
            f"Type your {entity}s separated by commas.\n"
            f"Max 5. Or type <b>skip</b> to move on."
        )

    await query.edit_message_text(
        text, parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⏭ Skip", callback_data=f"ob_fav_done:{sport_key}")],
        ]),
    )


def _fav_step_text(sport: config.SportDef) -> str:
    """Build the text for the favourites step."""
    label = config.fav_label(sport)
    return (
        f"<b>Step 4/8: Select your {label}s for {sport.emoji} {sport.label}</b>\n\n"
        f"Type names separated by commas, or tap Skip."
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
    text = f"<b>Step 3/8: Select leagues for {emoji} {label}</b>\n\nTap to toggle."
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
    text = _fav_step_text(sport) if sport else "<b>Step 4/8</b>"
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
        f"<b>Step 4/8: Type your {label} for {emoji} {sport_name}</b>\n\n"
        f"Type a name and send it. I'll try to match it."
    )
    await query.edit_message_text(
        text, parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("« Back to list", callback_data=f"ob_fav_back:{sport_key}")],
        ]),
    )


async def handle_ob_fav_done(query, sport_key: str) -> None:
    """Done with favourites for this sport/league, advance to next."""
    user_id = query.from_user.id
    ob = _get_ob(user_id)
    ob["_fav_manual"] = False
    ob["_fav_manual_sport"] = None
    ob["_team_input_sport"] = None
    ob["_team_input_league"] = None

    # Check if editing a single sport
    editing = ob.get("_editing")
    if editing and editing.startswith("sport:"):
        ob["_editing"] = None
        ob["step"] = "summary"
        await _show_summary(query, ob)
        return

    ob["_fav_idx"] = ob.get("_fav_idx", 0) + 1
    await _show_next_team_prompt(query, ob)


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
    text = _fav_step_text(sport) if sport else "<b>Step 4/8</b>"
    await query.edit_message_text(
        text, parse_mode=ParseMode.HTML,
        reply_markup=kb_onboarding_favourites(sport_key, ob["favourites"][sport_key]),
    )


async def handle_ob_risk(query, risk_key: str) -> None:
    """Set risk profile during onboarding."""
    user_id = query.from_user.id
    ob = _get_ob(user_id)
    ob["risk"] = risk_key

    # Check if editing risk+notify — go to notify directly
    if ob.get("_editing") == "risk":
        ob["step"] = "notify"
        text = "<b>⏰ Change Notification Time</b>\n\nWhen do you want daily picks?"
        await query.edit_message_text(
            text, parse_mode=ParseMode.HTML,
            reply_markup=kb_onboarding_notify(),
        )
        return

    ob["step"] = "bankroll"
    text = (
        "<b>Step 6/8: Weekly bankroll</b>\n\n"
        "How much do you set aside for betting each week?\n\n"
        "This helps me size my stake suggestions.\n"
        "<i>You can change this anytime in /settings.</i>"
    )
    await query.edit_message_text(
        text, parse_mode=ParseMode.HTML,
        reply_markup=kb_onboarding_bankroll(),
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


async def handle_ob_bankroll(query, value: str) -> None:
    """Set bankroll during onboarding."""
    user_id = query.from_user.id
    ob = _get_ob(user_id)

    if value == "skip":
        ob["bankroll"] = None
    elif value == "custom":
        ob["step"] = "bankroll_custom"
        ob["_bankroll_custom"] = True
        await query.edit_message_text(
            "<b>Step 6/8: Custom bankroll</b>\n\n"
            "Type your weekly bankroll amount in Rands.\n"
            "<i>e.g. 750 or 3000</i>",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("↩️ Back to presets", callback_data="ob_bankroll:back")],
            ]),
        )
        return
    elif value == "back":
        ob["step"] = "bankroll"
        ob.pop("_bankroll_custom", None)
        text = (
            "<b>Step 6/8: Weekly bankroll</b>\n\n"
            "How much do you set aside for betting each week?"
        )
        await query.edit_message_text(
            text, parse_mode=ParseMode.HTML,
            reply_markup=kb_onboarding_bankroll(),
        )
        return
    else:
        try:
            ob["bankroll"] = float(value)
        except ValueError:
            ob["bankroll"] = None

    ob["step"] = "notify"
    text = "<b>Step 7/8: Daily picks notification</b>\n\nWhen do you want your daily tips?"
    await query.edit_message_text(
        text, parse_mode=ParseMode.HTML,
        reply_markup=kb_onboarding_notify(),
    )


async def _show_summary(query, ob: dict) -> None:
    """Show onboarding summary with edit buttons — clean formatting, no heart emojis."""
    sports_lines = []
    for sk in ob["selected_sports"]:
        sport = config.ALL_SPORTS.get(sk)
        emoji = sport.emoji if sport else "🏅"
        sport_label = sport.label if sport else sk
        leagues = ob["selected_leagues"].get(sk, [])
        favs_dict = ob["favourites"].get(sk, {})

        # Flatten favourites: league_key → [names]
        if isinstance(favs_dict, list):
            # Legacy format: flat list
            all_teams = favs_dict
            league_teams: dict[str, list[str]] = {"": all_teams}
        else:
            league_teams = favs_dict

        league_labels_map: dict[str, str] = {}
        if sport:
            for lg in sport.leagues:
                league_labels_map[lg.key] = _abbreviate_league(lg.label)

        sports_lines.append(f"{emoji} <b>{sport_label}</b>")

        if len(leagues) <= 1 or not any(league_teams.values()):
            # Single league or no teams — compact format
            all_t: list[str] = []
            for teams in league_teams.values():
                all_t.extend(teams)
            if all_t:
                sports_lines.append(f"  {', '.join(all_t)}")
            elif leagues:
                league_names = [league_labels_map.get(lk, lk) for lk in leagues]
                sports_lines.append(f"  {', '.join(league_names)}")
        else:
            # Multiple leagues — show per-league
            for lk in leagues:
                lg_label = league_labels_map.get(lk, lk)
                teams = league_teams.get(lk, [])
                if teams:
                    sports_lines.append(f"  {lg_label}: {', '.join(teams)}")
                else:
                    sports_lines.append(f"  {lg_label}")
        sports_lines.append("")  # blank line between sports

    # Strip emoji from risk label — e.g. "⚖️ Moderate" → "Moderate"
    risk_raw = config.RISK_PROFILES.get(ob["risk"], {}).get("label", ob["risk"] or "Not set")
    risk_label = risk_raw.split(" ", 1)[-1] if " " in risk_raw else risk_raw
    hour = ob.get("notify_hour")
    notify_map = {7: "Morning (7 AM)", 12: "Midday (12 PM)", 18: "Evening (6 PM)", 21: "Night (9 PM)"}
    notify_str = notify_map.get(hour, f"{hour}:00") if hour is not None else "Not set"
    bankroll = ob.get("bankroll")
    bankroll_str = f"R{bankroll:,.0f}" if bankroll else "Not set"

    exp_labels = {
        "experienced": "I bet regularly",
        "casual": "I bet sometimes",
        "newbie": "I'm new to betting",
    }
    exp = ob.get("experience") or "casual"

    text = (
        "<b>Step 8/8: Your profile summary</b>\n\n"
        f"🎯 Experience: {exp_labels.get(exp, exp)}\n\n"
        + "\n".join(sports_lines)
        + f"\n⚖️ <b>Risk:</b> {risk_label}\n"
        f"💰 <b>Bankroll:</b> {bankroll_str}\n"
        f"🔔 <b>Daily picks:</b> {notify_str}\n\n"
        "All good? Tap <b>Let's go!</b> to start."
    )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 Let's go!", callback_data="ob_done:finish")],
        [InlineKeyboardButton("✏️ Edit Sports & Favourites", callback_data="ob_edit:sports")],
        [InlineKeyboardButton("⚙️ Edit Risk & Notifications", callback_data="ob_edit:risk")],
    ])
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)


# ── Profile summary helper ────────────────────────────────

async def format_profile_summary(user_id: int) -> str:
    """Build a clean, well-spaced profile summary string.

    Uses the service layer for data, renders as Telegram HTML.
    Used in: /settings home, My Teams view, after edits.
    """
    data = await get_profile_data(user_id)

    lines = ["📋 <b>Your MzansiEdge Profile</b>\n"]
    lines.append(f"🎯 Experience: {data['experience_label']}\n")

    for sport in data["sports"]:
        lines.append(f"{sport['emoji']} <b>{sport['label']}</b>")
        if len(sport["leagues"]) <= 1:
            all_t: list[str] = []
            for lg in sport["leagues"]:
                all_t.extend(lg["teams"])
            if all_t:
                lines.append(f"  {', '.join(all_t)}")
        else:
            for lg in sport["leagues"]:
                if lg["label"] and lg["teams"]:
                    lines.append(f"  {lg['label']}: {', '.join(lg['teams'])}")
                elif lg["label"]:
                    lines.append(f"  {lg['label']}")
                elif lg["teams"]:
                    lines.append(f"  {', '.join(lg['teams'])}")
        lines.append("")

    lines.append(f"⚖️ <b>Risk:</b> {data['risk_label']}")
    lines.append(f"💰 <b>Bankroll:</b> {data['bankroll_str']}")
    lines.append(f"🔔 <b>Daily picks:</b> {data['notify_str']}")

    return "\n".join(lines)


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
        # Re-edit a specific sport's leagues & teams
        sport_key = action.split(":", 1)[1]
        ob["_editing"] = f"sport:{sport_key}"
        sport = config.ALL_SPORTS.get(sport_key)
        if not sport:
            ob["_editing"] = None
            await _show_summary(query, ob)
            return

        # If single league, skip to team text input
        if len(sport.leagues) == 1:
            ob["selected_leagues"][sport_key] = [sport.leagues[0].key]
            if sport.fav_type != "skip":
                lk = sport.leagues[0].key
                ob["_team_input_sport"] = sport_key
                ob["_team_input_league"] = lk
                ob["step"] = "favourites"
                entity = config.fav_label(sport)
                lg = config.ALL_LEAGUES.get(lk)
                league_label = lg.label if lg else lk
                text = (
                    f"<b>{sport.emoji} {league_label} — who do you follow?</b>\n\n"
                    f"Type your {entity}s separated by commas.\n"
                    f"Max 5. Or type <b>skip</b> to move on."
                )
                await query.edit_message_text(
                    text, parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("⏭ Skip", callback_data=f"ob_fav_done:{sport_key}")],
                    ]),
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


async def handle_ob_done(query, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Persist onboarding data and route by experience level."""
    user_id = query.from_user.id
    ob = _get_ob(user_id)

    # Delegate persistence to service layer
    await persist_onboarding(user_id, ob)
    experience = ob.get("experience", "casual")
    _onboarding_state.pop(user_id, None)

    user = query.from_user
    name = user.first_name or "champ"

    # Big welcome message with story quiz CTA
    text = (
        f"🎉 <b>Welcome to MzansiEdge, {name}!</b>\n\n"
        "You're in. Your edge is live.\n\n"
        "Here's what I can do for you:\n\n"
        "📊 <b>AI-Powered Picks</b> — I scan odds across bookmakers, "
        "find value bets, and tell you exactly where the edge is.\n\n"
        "📅 <b>Schedule & Tips</b> — See when your teams play and get "
        "instant AI analysis for any upcoming game.\n\n"
        "📖 <b>Your Betting Story</b> — MzansiEdge isn't just tips — "
        "it's a journey. Track your wins, learn as you go, and build "
        "your bankroll over time.\n\n"
        "🔔 <b>But first — let's set up your story.</b>\n"
        "Choose what updates you want to receive so I know "
        "exactly how to keep you in the game."
    )
    await query.edit_message_text(
        text, parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📖 Set Up My Story", callback_data="story:start")],
            [InlineKeyboardButton("⏭️ Skip for Now", callback_data="nav:main")],
        ]),
    )
    # Activate the persistent reply keyboard
    await ctx.bot.send_message(
        query.message.chat_id,
        "⌨️ <i>Your quick-access keyboard is now active!</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=get_main_keyboard(),
    )


# ── Team text input handler ──────────────────────────────

async def _handle_team_text_input(update: Update, ctx, ob: dict) -> None:
    """Process typed team names with comma separation during onboarding."""
    from scripts.sports_data import fuzzy_match_team as sd_fuzzy, ALIASES as SD_ALIASES

    sport_key = ob["_team_input_sport"]
    league_key = ob["_team_input_league"]
    raw = update.message.text.strip()

    # Handle skip
    if raw.lower() in ("skip", "none", "n/a"):
        ob["_team_input_sport"] = None
        ob["_team_input_league"] = None
        ob["_fav_idx"] = ob.get("_fav_idx", 0) + 1
        # Need to send a new message since we can't edit user's text message
        queue = ob.get("_fav_league_queue", [])
        idx = ob["_fav_idx"]
        if idx >= len(queue):
            ob["step"] = "risk"
            await update.message.reply_text(
                "<b>Step 5/8: Risk profile</b>\n\nHow aggressive should your tips be?",
                parse_mode=ParseMode.HTML,
                reply_markup=kb_onboarding_risk(),
            )
        else:
            _sk, _lk = queue[idx]
            ob["_team_input_sport"] = _sk
            ob["_team_input_league"] = _lk
            sport = config.ALL_SPORTS.get(_sk)
            emoji = sport.emoji if sport else "🏅"
            entity = config.fav_label(sport) if sport else "favourite"
            if _lk:
                lg = config.ALL_LEAGUES.get(_lk)
                league_label = lg.label if lg else _lk
                text = (
                    f"<b>Step 4/8: {emoji} {league_label} — who do you follow?</b>\n\n"
                    f"Type your {entity}s separated by commas.\n"
                    f"Max 5. Or type <b>skip</b> to move on."
                )
            else:
                sport_label = sport.label if sport else _sk
                text = (
                    f"<b>Step 4/8: {emoji} {sport_label} — who do you follow?</b>\n\n"
                    f"Type your {entity}s separated by commas.\n"
                    f"Max 5. Or type <b>skip</b> to move on."
                )
            await update.message.reply_text(
                text, parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⏭ Skip", callback_data=f"ob_fav_done:{_sk}")],
                ]),
            )
        return

    # Split by comma, clean each entry
    raw_names = [name.strip() for name in raw.split(",") if name.strip()]
    if not raw_names:
        await update.message.reply_text(
            "Didn't catch that. Type team names separated by commas, or <b>skip</b>.",
            parse_mode=ParseMode.HTML,
        )
        return

    # Enforce max 5 per league
    if len(raw_names) > 5:
        await update.message.reply_text(
            "⚠️ Max 5 per league! I'll use your first 5.",
            parse_mode=ParseMode.HTML,
        )
        raw_names = raw_names[:5]

    # Build known names list: TOP_TEAMS for this league + curated lists
    known_names: list[str] = []
    if league_key:
        known_names = list(config.TOP_TEAMS.get(league_key, []))
    if not known_names:
        known_names = _get_all_teams_for_sport(sport_key)

    # Also include alias targets in the known names
    alias_names = set(SD_ALIASES.values())

    matched: list[str] = []
    unmatched: list[str] = []

    for name in raw_names:
        name_lower = name.lower().strip()
        # 1. Check alias first
        if name_lower in SD_ALIASES:
            matched.append(SD_ALIASES[name_lower])
            continue
        if name_lower in config.TEAM_ALIASES:
            matched.append(config.TEAM_ALIASES[name_lower])
            continue

        # 2. Fuzzy match against known names
        if known_names:
            results = sd_fuzzy(name, known_names)
            if results and results[0]["confidence"] >= 70:
                matched.append(results[0]["name"])
                continue

        # 3. Try fuzzy against all alias targets
        all_names = list(alias_names | set(known_names))
        if all_names:
            results = sd_fuzzy(name, all_names)
            if results and results[0]["confidence"] >= 70:
                matched.append(results[0]["name"])
                continue

        unmatched.append(name)

    # Build confirmation message
    lines: list[str] = []
    if matched:
        lines.append("<b>Matched:</b>")
        for m in matched:
            lines.append(f"  ✅ {m}")
    if unmatched:
        lines.append("")
        lines.append("<b>Couldn't match:</b>")
        for u in unmatched:
            lines.append(f"  ❌ {u}")
        lines.append("")
        lines.append("<i>These will be skipped. You can add them later in /settings.</i>")

    if not matched:
        await update.message.reply_text(
            "Couldn't match any of those names. Try again?\n\n"
            "<i>Tip: Use full names like \"Manchester United\" or common "
            "nicknames like \"Chiefs\", \"Barca\", \"Spurs\".</i>",
            parse_mode=ParseMode.HTML,
        )
        return

    # Save matched teams to favourites
    if sport_key not in ob["favourites"]:
        ob["favourites"][sport_key] = {}
    fav_key = league_key or "_general"
    ob["favourites"][sport_key][fav_key] = matched

    # Show confirmation with buttons
    msg = "\n".join(lines)
    await update.message.reply_text(
        f"{msg}\n\n"
        f"<b>{len(matched)} {'team' if len(matched) == 1 else 'teams'} added.</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Continue", callback_data=f"ob_fav_done:{sport_key}")],
            [InlineKeyboardButton("🔄 Try Again", callback_data=f"ob_fav_retry:{sport_key}")],
        ]),
    )


# ── Free-text handler ────────────────────────────────────

async def _handle_settings_team_edit(update: Update, ctx) -> bool:
    """Process typed team names for settings team editing. Returns True if handled."""
    from scripts.sports_data import fuzzy_match_team as sd_fuzzy, ALIASES as SD_ALIASES

    user_id = update.effective_user.id
    state = _team_edit_state.get(user_id)
    if not state:
        return False

    raw = update.message.text.strip()
    if raw.lower() in ("cancel", "back"):
        _team_edit_state.pop(user_id, None)
        await update.message.reply_text(
            "Cancelled. Use the menu to continue.",
            parse_mode=ParseMode.HTML, reply_markup=kb_teams(),
        )
        return True

    sk = state["sport_key"]
    lk = state["league_key"]

    raw_names = [name.strip() for name in raw.split(",") if name.strip()]
    if not raw_names:
        await update.message.reply_text(
            "Didn't catch that. Type team names separated by commas, or <b>cancel</b>.",
            parse_mode=ParseMode.HTML,
        )
        return True

    if len(raw_names) > 5:
        await update.message.reply_text("⚠️ Max 5 per league! Using first 5.", parse_mode=ParseMode.HTML)
        raw_names = raw_names[:5]

    known_names = list(config.TOP_TEAMS.get(lk, []))
    if not known_names:
        known_names = _get_all_teams_for_sport(sk)
    alias_names = set(SD_ALIASES.values())

    matched: list[str] = []
    unmatched: list[str] = []

    for name in raw_names:
        name_lower = name.lower().strip()
        if name_lower in SD_ALIASES:
            matched.append(SD_ALIASES[name_lower])
            continue
        if name_lower in config.TEAM_ALIASES:
            matched.append(config.TEAM_ALIASES[name_lower])
            continue
        if known_names:
            results = sd_fuzzy(name, known_names)
            if results and results[0]["confidence"] >= 70:
                matched.append(results[0]["name"])
                continue
        all_names = list(alias_names | set(known_names))
        if all_names:
            results = sd_fuzzy(name, all_names)
            if results and results[0]["confidence"] >= 70:
                matched.append(results[0]["name"])
                continue
        unmatched.append(name)

    if not matched:
        await update.message.reply_text(
            "Couldn't match any of those names. Try again?\n\n"
            "<i>Tip: Use full names or common nicknames.</i>",
            parse_mode=ParseMode.HTML,
        )
        return True

    # Clear old teams for this league and save new ones
    await db.clear_user_league_teams(user_id, sk, lk)
    for team in matched:
        await db.save_sport_pref(user_id, sk, league=lk, team_name=team)

    _team_edit_state.pop(user_id, None)

    lines: list[str] = ["<b>Updated!</b>\n"]
    for m in matched:
        lines.append(f"  ✅ {m}")
    if unmatched:
        lines.append("")
        for u in unmatched:
            lines.append(f"  ❌ {u} (skipped)")

    await update.message.reply_text(
        "\n".join(lines), parse_mode=ParseMode.HTML, reply_markup=kb_teams(),
    )
    return True


async def handle_keyboard_tap(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle taps on the persistent reply keyboard buttons."""
    text = update.message.text.strip()
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    # Ignore during active onboarding — shouldn't happen but be safe
    ob = _onboarding_state.get(user_id)
    if ob and not ob.get("done"):
        return

    if text == "🎯 Picks":
        await _do_picks_flow(chat_id=chat_id, bot=ctx.bot, user_id=user_id)
    elif text == "📅 Schedule":
        db_user = await db.get_user(user_id)
        if not db_user or not db_user.onboarding_done:
            await update.message.reply_text(
                "🏟️ Complete your profile first!\n\nUse /start to get set up.",
                parse_mode=ParseMode.HTML,
            )
            return
        sched_text, markup = await _build_schedule(user_id)
        await update.message.reply_text(sched_text, parse_mode=ParseMode.HTML, reply_markup=markup)
    elif text == "🔴 Live":
        await _show_live_games(update, user_id)
    elif text == "📊 Stats":
        await _show_stats_overview(update, user_id)
    elif text == "⚙️ Settings":
        db_user = await db.get_user(user_id)
        if not db_user or not db_user.onboarding_done:
            await update.message.reply_text(
                "⚙️ Complete onboarding first!\n\nUse /start to get set up.",
                parse_mode=ParseMode.HTML,
            )
            return
        await update.message.reply_text(
            "⚙️ <b>Settings</b>", parse_mode=ParseMode.HTML, reply_markup=kb_settings(),
        )
    elif text == "❓ Help":
        await update.message.reply_text(HELP_TEXT, parse_mode=ParseMode.HTML, reply_markup=kb_nav())


async def _show_live_games(update: Update, user_id: int) -> None:
    """Show user's active game subscriptions."""
    subs = await db.get_user_subscriptions(user_id)
    active = [s for s in subs if s.is_active]

    if not active:
        await update.message.reply_text(
            "🔴 <b>Live Games</b>\n\n"
            "You're not following any live games yet.\n\n"
            "Use 📅 <b>Schedule</b> to find games, tap one for tips, "
            "then hit <b>🔔 Follow this game</b> to get live updates.",
            parse_mode=ParseMode.HTML,
        )
        return

    lines = [f"🔴 <b>Live Games ({len(active)})</b>\n"]
    buttons = []
    for sub in active:
        lines.append(f"  ⚡ {sub.home_team} vs {sub.away_team}")
        buttons.append([InlineKeyboardButton(
            f"🔕 Unfollow {sub.home_team} vs {sub.away_team}",
            callback_data=f"unsubscribe:{sub.event_id}",
        )])
    buttons.append([InlineKeyboardButton("📅 Schedule", callback_data="nav:schedule")])

    await update.message.reply_text(
        "\n".join(lines), parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def _show_stats_overview(update: Update, user_id: int) -> None:
    """Show user-facing stats overview."""
    db_user = await db.get_user(user_id)
    if not db_user or not db_user.onboarding_done:
        await update.message.reply_text(
            "📊 Complete onboarding first!\n\nUse /start to get set up.",
            parse_mode=ParseMode.HTML,
        )
        return

    archetype = db_user.archetype or "casual_fan"
    exp = db_user.experience_level or "casual"
    score = db_user.engagement_score or 5.0
    bankroll = db_user.bankroll

    lines = ["📊 <b>Your Stats</b>\n"]
    lines.append(f"🎯 Profile: <b>{archetype.replace('_', ' ').title()}</b>")
    lines.append(f"📈 Engagement: <b>{score:.0f}/10</b>")
    if bankroll:
        lines.append(f"💰 Bankroll: <b>R{bankroll:,.0f}/week</b>")

    await update.message.reply_text(
        "\n".join(lines), parse_mode=ParseMode.HTML, reply_markup=kb_nav(),
    )


async def freetext_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle free text — team input during onboarding OR AI chat."""
    user = update.effective_user
    ob = _onboarding_state.get(user.id)

    # Settings team edit (check before onboarding)
    if user.id in _team_edit_state:
        handled = await _handle_settings_team_edit(update, ctx)
        if handled:
            return

    # Custom bankroll input during onboarding
    if ob and ob.get("_bankroll_custom"):
        raw = update.message.text.strip().replace("R", "").replace("r", "").replace(",", "").replace(" ", "")
        try:
            amount = float(raw)
            if amount < 50:
                await update.message.reply_text(
                    "⚠️ Minimum R50. Try again or tap Back to use a preset.",
                    parse_mode=ParseMode.HTML,
                )
                return
            ob["bankroll"] = amount
            ob.pop("_bankroll_custom", None)
            ob["step"] = "notify"
            await update.message.reply_text(
                "<b>Step 7/8: Daily picks notification</b>\n\nWhen do you want your daily tips?",
                parse_mode=ParseMode.HTML,
                reply_markup=kb_onboarding_notify(),
            )
        except ValueError:
            await update.message.reply_text(
                "Please enter a number, e.g. <b>750</b> or <b>3000</b>.",
                parse_mode=ParseMode.HTML,
            )
        return

    # Text-based team input (comma-separated)
    if ob and ob.get("_team_input_sport"):
        await _handle_team_text_input(update, ctx, ob)
        return

    # Legacy manual favourite input mode (single name)
    if ob and ob.get("_fav_manual") and ob.get("_fav_manual_sport"):
        sport_key = ob["_fav_manual_sport"]
        text_input = update.message.text.strip()
        match, suggestions = fuzzy_match_team(text_input, sport_key)

        if match:
            if sport_key not in ob["favourites"]:
                ob["favourites"][sport_key] = {}
            ob["favourites"].setdefault(sport_key, {}).setdefault("_manual", [])
            if match not in ob["favourites"][sport_key].get("_manual", []):
                ob["favourites"][sport_key].setdefault("_manual", []).append(match)
            ob["_fav_manual"] = False
            ob["_fav_manual_sport"] = None
            await update.message.reply_text(
                f"✅ Added <b>{match}</b>!",
                parse_mode=ParseMode.HTML,
            )
        elif suggestions:
            ob["_suggestions"] = suggestions
            rows = []
            for i, s in enumerate(suggestions):
                rows.append([InlineKeyboardButton(s, callback_data=f"ob_fav_suggest:{sport_key}:{i}")])
            rows.append([InlineKeyboardButton("❌ None of these", callback_data=f"ob_fav_manual:{sport_key}")])
            await update.message.reply_text(
                "🤔 Did you mean one of these?",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(rows),
            )
        else:
            if sport_key not in ob["favourites"]:
                ob["favourites"][sport_key] = {}
            ob["favourites"].setdefault(sport_key, {}).setdefault("_manual", [])
            ob["favourites"][sport_key]["_manual"].append(text_input)
            ob["_fav_manual"] = False
            ob["_fav_manual_sport"] = None
            await update.message.reply_text(
                f"✅ Added <b>{text_input}</b>!",
                parse_mode=ParseMode.HTML,
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
    await _do_picks_flow(
        chat_id=update.effective_chat.id,
        bot=ctx.bot,
        user_id=update.effective_user.id,
    )


async def handle_picks(query, ctx: ContextTypes.DEFAULT_TYPE, action: str) -> None:
    """Callback handler for picks:go and picks:today buttons."""
    if action in ("go", "today"):
        await _do_picks_flow(
            chat_id=query.message.chat_id,
            bot=ctx.bot,
            user_id=query.from_user.id,
        )


async def _do_picks_flow(chat_id: int, bot, user_id: int) -> None:
    """Core picks logic — fetch cached odds, compute EV, display pick cards."""
    import random
    verb = random.choice(LOADING_VERBS)

    # Load user profile
    user = await db.get_user(user_id)
    risk_key = (user.risk_profile if user else None) or "moderate"
    profile = config.RISK_PROFILES.get(risk_key, config.RISK_PROFILES["moderate"])
    experience = (user.experience_level if user else None) or "casual"

    # Get user's preferred leagues (fall back to all mapped leagues)
    prefs = await db.get_user_sport_prefs(user_id)
    if prefs:
        league_keys = list({p.league for p in prefs if p.league})
    else:
        league_keys = list(config.SPORTS_MAP.keys())

    if not league_keys:
        await bot.send_message(
            chat_id,
            "🏟️ You haven't selected any leagues yet!\n\n"
            "Tap below to set up your sports.",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⚽ Set Up Sports", callback_data="settings:sports")],
            ]),
        )
        return

    # Send loading message
    loading_msg = await bot.send_message(
        chat_id,
        f"🔍 <i>{verb} across {len(league_keys)} league{'s' if len(league_keys) != 1 else ''}…</i>",
        parse_mode=ParseMode.HTML,
    )

    # Fetch picks via the engine
    user_bankroll = getattr(user, "bankroll", None) if user else None
    try:
        result = await get_picks_for_user(
            league_keys=league_keys,
            risk_profile=risk_key,
            max_picks=5,
            bankroll=user_bankroll,
        )
    except Exception as exc:
        log.error("Picks engine error: %s", exc)
        result = {"ok": False, "picks": [], "total_events": 0, "total_markets": 0,
                  "quota_remaining": "?", "errors": [str(exc)]}

    # Delete loading message
    try:
        await loading_msg.delete()
    except Exception:
        pass

    # Handle quota exhausted
    if result.get("errors") and any("quota_exhausted" in str(e) for e in result["errors"]):
        await bot.send_message(
            chat_id,
            "⚠️ <b>We've hit our daily data limit.</b>\n\n"
            "Picks will refresh tomorrow. Your bankroll is safe — "
            "no bets placed automatically.",
            parse_mode=ParseMode.HTML,
            reply_markup=kb_nav(),
        )
        return

    # No picks found
    if not result["ok"] or not result["picks"]:
        risk_label = profile["label"]
        if experience == "newbie":
            text = (
                "📭 <b>No value bets found right now</b>\n\n"
                f"Scanned {result['total_events']} events across your leagues.\n\n"
                "This means bookmaker odds are fair — no easy edges today.\n"
                "Check back later! We scan markets throughout the day.\n\n"
                f"<i>API quota: {result.get('quota_remaining', '?')} remaining</i>"
            )
        else:
            text = (
                "📭 <b>No value bets found right now</b>\n\n"
                f"Scanned {result['total_events']} events | "
                f"{result['total_markets']} markets\n\n"
                f"No edges meeting your {risk_label} profile.\n"
                "This is the AI protecting your bankroll — "
                "check back when more markets open or adjust your risk in /settings.\n\n"
                f"<i>API quota: {result.get('quota_remaining', '?')} remaining</i>"
            )
        await bot.send_message(
            chat_id, text, parse_mode=ParseMode.HTML,
            reply_markup=kb_nav(),
        )
        return

    picks = result["picks"]

    # Send header
    await bot.send_message(
        chat_id,
        f"💰 <b>Found {len(picks)} value bet{'s' if len(picks) != 1 else ''}!</b>\n\n"
        f"📊 Scanned {result['total_events']} events | "
        f"{result['total_markets']} markets\n"
        f"⚖️ Risk: {profile['label']}\n"
        f"<i>API quota: {result.get('quota_remaining', '?')} remaining</i>",
        parse_mode=ParseMode.HTML,
    )

    # Send individual pick cards
    for i, pick in enumerate(picks, 1):
        card = format_engine_pick_card(pick, i, experience)
        await bot.send_message(
            chat_id, card, parse_mode=ParseMode.HTML,
        )

    # Final footer
    await bot.send_message(
        chat_id,
        "<i>Always gamble responsibly. 🇿🇦</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=kb_nav(),
    )


# ── /schedule — Upcoming games ───────────────────────────

async def cmd_schedule(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Show upcoming games for user's followed teams."""
    user_id = update.effective_user.id
    db_user = await db.get_user(user_id)

    if not db_user or not db_user.onboarding_done:
        await update.message.reply_text(
            "🏟️ Complete your profile first!\n\nUse /start to get set up.",
            parse_mode=ParseMode.HTML,
        )
        return

    text, markup = await _build_schedule(user_id)

    await update.message.reply_text(
        text, parse_mode=ParseMode.HTML, reply_markup=markup,
    )


async def _build_schedule(user_id: int) -> tuple[str, InlineKeyboardMarkup]:
    """Shared schedule logic for command + callback. Returns (text, markup)."""
    from datetime import datetime as dt_cls, date as date_cls
    from zoneinfo import ZoneInfo
    from scripts.sports_data import fetch_events_for_league

    sa_tz = ZoneInfo(config.TZ)

    prefs = await db.get_user_sport_prefs(user_id)
    user_teams: set[str] = set()
    league_keys: set[str] = set()
    for pref in prefs:
        if pref.team_name:
            user_teams.add(pref.team_name.lower())
        if pref.league:
            league_keys.add(pref.league)

    if not league_keys:
        text = (
            "🏟️ <b>No leagues selected!</b>\n\n"
            "Update your sports in /settings."
        )
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("⚙️ Edit Sports", callback_data="settings:sports")],
            [InlineKeyboardButton("↩️ Menu", callback_data="nav:main")],
        ])
        return text, markup

    all_events: list[dict] = []
    for lk in league_keys:
        sport_key = config.LEAGUE_SPORT.get(lk, "")
        sport = config.ALL_SPORTS.get(sport_key)
        sport_emoji = sport.emoji if sport else "🏅"
        events = await fetch_events_for_league(lk)
        for event in events:
            home = event.get("home_team", "")
            away = event.get("away_team", "")
            is_relevant = (
                home.lower() in user_teams
                or away.lower() in user_teams
                or not user_teams
            )
            if is_relevant:
                all_events.append({**event, "league_key": lk, "sport_emoji": sport_emoji})

    if not all_events:
        text = (
            "📅 <b>No upcoming games found</b>\n\n"
            "None of your followed teams have scheduled games right now. "
            "Check back later or add more teams in /settings."
        )
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("⚙️ Edit Teams", callback_data="settings:sports")],
            [InlineKeyboardButton("↩️ Menu", callback_data="nav:main")],
        ])
        return text, markup

    all_events.sort(key=lambda e: e.get("commence_time", ""))
    upcoming = all_events[:10]

    today = dt_cls.now(sa_tz).date()
    tomorrow = today + __import__("datetime").timedelta(days=1)

    lines = [f"📅 <b>Upcoming Games ({len(upcoming)})</b>\n"]
    current_date_str = None

    for idx, event in enumerate(upcoming, 1):
        try:
            ct = dt_cls.fromisoformat(event["commence_time"].replace("Z", "+00:00"))
            ct_sa = ct.astimezone(sa_tz)
            event_date = ct_sa.date()
            event_time = ct_sa.strftime("%H:%M")

            if event_date == today:
                date_header = "Today"
            elif event_date == tomorrow:
                date_header = "Tomorrow"
            else:
                date_header = ct_sa.strftime("%A, %d %b")
        except Exception:
            date_header = "TBC"
            event_time = ""

        if date_header != current_date_str:
            current_date_str = date_header
            lines.append(f"\n<b>{date_header}</b>")

        home = event.get("home_team", "?")
        away = event.get("away_team", "?")
        emoji = event.get("sport_emoji", "🏅")
        home_display = f"<b>{home}</b>" if home.lower() in user_teams else home
        away_display = f"<b>{away}</b>" if away.lower() in user_teams else away
        lines.append(f"{idx}. {emoji} {event_time}  {home_display} vs {away_display}")

    text = "\n".join(lines)

    buttons: list[list[InlineKeyboardButton]] = []
    for i, event in enumerate(upcoming[:5], 1):
        home = event.get("home_team", "?")
        away = event.get("away_team", "?")
        emoji = event.get("sport_emoji", "🏅")
        event_id = event.get("id", str(i))
        h_abbr = config.abbreviate_team(home)
        a_abbr = config.abbreviate_team(away)
        buttons.append([InlineKeyboardButton(
            f"[{i}] {emoji} {h_abbr} vs {a_abbr}",
            callback_data=f"schedule:tips:{event_id}",
        )])
    buttons.append([InlineKeyboardButton("↩️ Menu", callback_data="nav:main")])

    return text, InlineKeyboardMarkup(buttons)


# Cache for game tips (event_id → list of tip dicts)
_game_tips_cache: dict[str, list[dict]] = {}

GAME_ANALYSIS_PROMPT = textwrap.dedent("""\
    You are MzansiEdge, a sharp South African sports betting analyst.
    Given odds and probability data for an upcoming match, write a punchy
    ~150-word analysis using these EXACT section headers:

    📋 <b>The Setup</b>
    One paragraph on recent form, head-to-head context, and what to expect.

    🎯 <b>The Edge</b>
    Where the value is. Be specific about which outcome and why the market
    has mispriced it.

    ⚠️ <b>The Risk</b>
    One sentence on what could go wrong.

    🏆 <b>Verdict</b>
    One bold sentence: your top pick with conviction level.

    Rules:
    - Telegram HTML only (<b>, <i> tags)
    - Do NOT include odds numbers or bookmaker names (shown separately)
    - No disclaimers, no "gamble responsibly" — we handle that elsewhere
    - Be direct, confident, conversational — like a mate who knows his stuff
    - South African tone: use "edge", "value", "sharp"
""")


async def _generate_game_tips(query, ctx, event_id: str, user_id: int) -> None:
    """Generate AI betting tips for a specific game."""
    from datetime import datetime as dt_cls
    from scripts.sports_data import fetch_events_for_league
    from scripts.odds_client import fetch_odds_cached, fair_probabilities, find_best_sa_odds, calculate_ev

    db_user = await db.get_user(user_id)
    prefs = await db.get_user_sport_prefs(user_id)
    league_keys = list({p.league for p in prefs if p.league})

    target_event = None
    target_league = None
    for lk in league_keys:
        events = await fetch_events_for_league(lk)
        for event in events:
            if event.get("id") == event_id:
                target_event = event
                target_league = lk
                break
        if target_event:
            break

    if not target_event:
        await query.edit_message_text(
            "⚠️ Couldn't find that game. It may have already started.",
            parse_mode=ParseMode.HTML,
        )
        return

    home = target_event.get("home_team", "?")
    away = target_event.get("away_team", "?")

    await query.edit_message_text(
        f"🤖 <i>Analysing {home} vs {away}…</i>",
        parse_mode=ParseMode.HTML,
    )

    # Fetch odds for this league
    api_key = config.SPORTS_MAP.get(target_league, target_league)
    odds_result = await fetch_odds_cached(api_key, regions="eu,uk,au", markets="h2h")

    if not odds_result["ok"]:
        await query.edit_message_text(
            f"⚠️ Couldn't fetch odds for {home} vs {away}. Try again later.",
            parse_mode=ParseMode.HTML,
        )
        return

    event_odds = None
    for ev in (odds_result["data"] or []):
        if ev.get("id") == event_id:
            event_odds = ev
            break

    if not event_odds or not event_odds.get("bookmakers"):
        await query.edit_message_text(
            f"📊 <b>{home} vs {away}</b>\n\n"
            "No odds available yet for this game. Check back closer to kickoff!",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("↩️ Back to Schedule", callback_data="nav:schedule")],
            ]),
        )
        return

    # Compute fair probabilities and find best SA odds per outcome
    fair_probs = fair_probabilities(event_odds)
    best_entries = find_best_sa_odds(event_odds)

    tips: list[dict] = []
    for entry in best_entries:
        prob = fair_probs.get(entry.outcome, 0)
        if prob <= 0:
            continue
        ev_pct = calculate_ev(entry.price, prob)
        implied = round(prob * 100)
        tips.append({
            "outcome": entry.outcome,
            "odds": entry.price,
            "bookie": entry.bookmaker,
            "bookie_key": getattr(entry, "bookmaker", "").lower().replace(" ", ""),
            "ev": round(ev_pct, 1),
            "prob": implied,
            "event_id": event_id,
            "home_team": home,
            "away_team": away,
        })

    tips.sort(key=lambda t: t["ev"], reverse=True)
    _game_tips_cache[event_id] = tips

    try:
        ct = dt_cls.fromisoformat(target_event["commence_time"].replace("Z", "+00:00"))
        kickoff = ct.strftime("%a %d %b, %H:%M")
    except Exception:
        kickoff = "TBC"

    # Build odds context for Claude
    odds_context = "\n".join(
        f"- {t['outcome']}: {t['odds']:.2f} ({t['bookie']}), "
        f"fair prob {t['prob']}%, EV {t['ev']:+.1f}%"
        for t in tips
    ) if tips else "No Betway odds available."

    # Get AI narrative
    narrative = ""
    try:
        resp = await claude.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            system=GAME_ANALYSIS_PROMPT,
            messages=[{
                "role": "user",
                "content": f"Match: {home} vs {away}\nKickoff: {kickoff}\n\nOdds:\n{odds_context}",
            }],
        )
        narrative = resp.content[0].text
    except Exception as exc:
        log.error("Claude game analysis error: %s", exc)
        narrative = ""

    lines = [
        f"🎯 <b>{home} vs {away}</b>",
        f"⏰ {kickoff}\n",
    ]

    if narrative:
        lines.append(narrative)
        lines.append("")

    if not tips:
        lines.append("No odds available on Betway for this game yet.")
    else:
        lines.append(f"<b>🇿🇦 {config.get_active_display_name()} Odds:</b>")
        for tip in tips:
            ev_ind = f"+{tip['ev']}%" if tip["ev"] > 0 else f"{tip['ev']}%"
            value_marker = " 💰" if tip["ev"] > 2 else ""
            lines.append(
                f"  {tip['outcome']}: <b>{tip['odds']:.2f}</b> "
                f"({tip['prob']}% | EV: {ev_ind}){value_marker}"
            )

    msg = "\n".join(lines)

    # Build tip detail buttons for positive EV tips
    buttons: list[list[InlineKeyboardButton]] = []
    for i, tip in enumerate(tips[:3]):
        if tip["ev"] > 0:
            buttons.append([InlineKeyboardButton(
                f"💰 {tip['outcome']} @ {tip['odds']:.2f} (EV: +{tip['ev']}%)",
                callback_data=f"tip:detail:{event_id}:{i}",
            )])
    buttons.append([InlineKeyboardButton("📊 Full Picks Scan", callback_data="picks:today")])
    buttons.append([InlineKeyboardButton("↩️ Back to Schedule", callback_data="nav:schedule")])

    await query.edit_message_text(
        msg, parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def handle_subscribe(query, event_id: str) -> None:
    """Subscribe user to live score updates for a game."""
    user_id = query.from_user.id
    tips = _game_tips_cache.get(event_id, [])

    home = tips[0]["home_team"] if tips else "?"
    away = tips[0]["away_team"] if tips else "?"
    sport_key = None

    # Try to determine sport_key from user's leagues
    prefs = await db.get_user_sport_prefs(user_id)
    league_keys = list({p.league for p in prefs if p.league})
    for lk in league_keys:
        sport_key = config.LEAGUE_SPORT.get(lk)
        if sport_key:
            break

    await db.subscribe_to_game(
        user_id=user_id,
        event_id=event_id,
        sport_key=sport_key,
        home_team=home,
        away_team=away,
    )

    await query.answer(f"🔔 Following {home} vs {away}!", show_alert=True)


async def handle_unsubscribe(query, event_id: str) -> None:
    """Unsubscribe user from live score updates."""
    user_id = query.from_user.id
    await db.unsubscribe_from_game(user_id, event_id)
    await query.answer("🔕 Unfollowed this game.", show_alert=True)


async def handle_tip_detail(query, ctx, action: str) -> None:
    """Handle tip:detail:{event_id}:{index} — show detailed tip info."""
    parts = action.split(":")
    if len(parts) < 3 or parts[0] != "detail":
        return

    event_id = parts[1]
    try:
        tip_idx = int(parts[2])
    except ValueError:
        return

    tips = _game_tips_cache.get(event_id, [])
    if tip_idx < 0 or tip_idx >= len(tips):
        await query.edit_message_text(
            "⚠️ Tip data expired. Tap the game again for fresh analysis.",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("↩️ Back to Schedule", callback_data="nav:schedule")],
            ]),
        )
        return

    tip = tips[tip_idx]
    user_id = query.from_user.id
    db_user = await db.get_user(user_id)
    experience = (db_user.experience_level if db_user else None) or "casual"
    bankroll = getattr(db_user, "bankroll", None) if db_user else None

    text = _format_tip_detail(tip, experience, bankroll)

    # Build buttons — always use the active bookmaker (Betway for MVP)
    buttons: list[list[InlineKeyboardButton]] = []
    active_bk = config.get_active_bookmaker()
    active_name = active_bk["short_name"]

    # Affiliate button
    affiliate_url = active_bk.get("affiliate_base_url", "")
    if affiliate_url:
        buttons.append([InlineKeyboardButton(
            f"📲 Bet on {active_name} →",
            url=affiliate_url,
        )])
    else:
        website_url = active_bk.get("website_url", "")
        if website_url:
            buttons.append([InlineKeyboardButton(
                f"📲 Bet on {active_name} →",
                url=website_url,
            )])
        else:
            buttons.append([InlineKeyboardButton(
                f"📲 Bet on {active_name} →",
                callback_data="tip:affiliate_soon",
            )])

    # Guide button
    guide_url = active_bk.get("guide_url", "")
    if not guide_url:
        from scripts.telegraph_guides import get_guide_url as _get_guide
        try:
            guide_url = await _get_guide(config.ACTIVE_BOOKMAKER) or ""
        except Exception:
            guide_url = ""

    if guide_url:
        buttons.append([InlineKeyboardButton(
            f"📖 How to bet on {active_name}",
            url=guide_url,
        )])
    else:
        buttons.append([InlineKeyboardButton(
            f"📖 How to bet on {active_name}",
            callback_data="tip:guide_soon",
        )])

    buttons.append([InlineKeyboardButton(
        "🔔 Follow this game",
        callback_data=f"subscribe:{event_id}",
    )])
    buttons.append([InlineKeyboardButton(
        "↩️ Back",
        callback_data=f"schedule:tips:{event_id}",
    )])

    await query.edit_message_text(
        text, parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


def _format_tip_detail(tip: dict, experience: str, bankroll: float | None) -> str:
    """Format a detailed tip card based on experience level."""
    outcome = tip["outcome"]
    odds = tip["odds"]
    ev = tip["ev"]
    prob = tip["prob"]
    home = tip["home_team"]
    away = tip["away_team"]
    bookie = config.get_active_display_name()

    if experience == "experienced":
        from scripts.odds_client import kelly_stake as calc_kelly
        ks = calc_kelly(odds, prob / 100.0, fraction=0.5)
        stake_str = ""
        if bankroll:
            stake = round(ks * bankroll, 2)
            pot_return = round(stake * odds, 2)
            stake_str = f"\n💵 Stake R{stake:,.0f} → R{pot_return:,.0f}"
        return (
            f"📊 <b>Tip Detail: {home} vs {away}</b>\n\n"
            f"💰 <b>{outcome}</b> @ <b>{odds:.2f}</b> ({bookie} 🇿🇦)\n"
            f"📈 EV: <b>+{ev}%</b> | Fair prob: {prob}%\n"
            f"🎯 Kelly fraction: <code>{ks:.1%}</code>{stake_str}\n\n"
            f"<i>EV = (odds × true_prob - 1). Positive = edge in your favour.</i>"
        )

    elif experience == "newbie":
        payout_20 = round(odds * 20, 0)
        payout_50 = round(odds * 50, 0)
        if outcome == "Draw":
            bet_explain = "You're betting the match ends in a draw."
        elif outcome == home:
            bet_explain = f"You're betting <b>{outcome}</b> (home team) wins."
        else:
            bet_explain = f"You're betting <b>{outcome}</b> (away team) wins."

        return (
            f"📊 <b>Tip Detail: {home} vs {away}</b>\n\n"
            f"📋 <b>What's the bet?</b>\n{bet_explain}\n\n"
            f"💵 <b>The odds: {odds:.2f}</b> on {bookie} 🇿🇦\n"
            f"  Bet R20 → get <b>R{payout_20:.0f}</b> back\n"
            f"  Bet R50 → get <b>R{payout_50:.0f}</b> back\n\n"
            f"🎯 Our AI gives this a <b>{prob}%</b> chance — "
            f"that's a <b>+{ev}%</b> edge in your favour.\n\n"
            f"💡 <i>Start small: R20-R50 bets are perfect while learning.</i>"
        )

    else:
        # Casual
        payout_100 = round(odds * 100, 0)
        stake_hint = ""
        if bankroll:
            suggested = round(min(bankroll * 0.05, 200), 0)
            stake_hint = f"\n💡 Suggested stake: <b>R{suggested:.0f}</b>"
        return (
            f"📊 <b>Tip Detail: {home} vs {away}</b>\n\n"
            f"💰 We like <b>{outcome}</b> @ {odds:.2f} ({bookie} 🇿🇦)\n\n"
            f"The AI found a <b>+{ev}%</b> edge here.\n"
            f"Fair probability: {prob}% — odds suggest less.\n\n"
            f"💵 R100 bet pays <b>R{payout_100:.0f}</b>{stake_hint}\n\n"
            f"<i>Edge = difference between true odds and bookmaker odds.</i>"
        )


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


# ── Story / notification quiz ─────────────────────────────

async def _show_story_step(query, chat_id: int) -> None:
    """Display the current story quiz question."""
    state = _story_state.get(chat_id)
    if not state:
        return

    step = state["step"]
    prompt = STORY_PROMPTS.get(step)
    if not prompt:
        return

    text = f"{prompt['title']}\n\n{prompt['body']}"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(prompt["yes"], callback_data=f"story:pref:{step}:yes")],
        [InlineKeyboardButton(prompt["no"], callback_data=f"story:pref:{step}:no")],
    ])
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)


async def _advance_story_quiz(query, chat_id: int, user_id: int) -> None:
    """Move to the next story quiz step."""
    state = _story_state.get(chat_id)
    if not state:
        return

    db_user = await db.get_user(user_id)
    experience = (db_user.experience_level if db_user else None) or "casual"

    current_step = state["step"]
    current_idx = STORY_STEPS.index(current_step) if current_step in STORY_STEPS else -1

    next_idx = current_idx + 1
    while next_idx < len(STORY_STEPS):
        next_step = STORY_STEPS[next_idx]
        if next_step == "edu_tips" and experience == "experienced":
            next_idx += 1
            continue
        if next_step == "market_movers" and experience == "newbie":
            next_idx += 1
            continue
        if next_step == "live_scores" and experience == "newbie":
            next_idx += 1
            continue
        break

    if next_idx >= len(STORY_STEPS):
        await _save_story_prefs(query, chat_id, user_id)
        return

    state["step"] = STORY_STEPS[next_idx]
    await _show_story_step(query, chat_id)


async def _save_story_prefs(query, chat_id: int, user_id: int) -> None:
    """Save story preferences and show confirmation."""
    state = _story_state.get(chat_id, {})
    prefs = state.get("prefs", {})

    # Fill in defaults for skipped steps
    defaults = {
        "daily_picks": True, "game_day_alerts": True,
        "weekly_recap": True, "edu_tips": True,
        "market_movers": False, "bankroll_updates": True,
        "live_scores": False,
    }
    full_prefs = {**defaults, **prefs}

    await db.update_notification_prefs(user_id, full_prefs)
    _story_state.pop(chat_id, None)

    # Build summary
    labels = {
        "daily_picks": "Daily AI picks",
        "game_day_alerts": "Game day alerts",
        "weekly_recap": "Weekly recaps",
        "edu_tips": "Education tips",
        "market_movers": "Market movers",
        "bankroll_updates": "Bankroll updates",
        "live_scores": "Live score updates",
    }
    pref_lines = []
    for key, label in labels.items():
        icon = "✅" if full_prefs.get(key, False) else "❌"
        pref_lines.append(f"  {icon} {label}")

    text = (
        "📖 <b>Your Story is Set!</b>\n\n"
        "Here's what you'll receive:\n\n"
        + "\n".join(pref_lines)
        + "\n\nYou can change these anytime in /settings.\n\n"
        "Ready to start? 🚀"
    )
    await query.edit_message_text(
        text, parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🎯 Show Me Today's Picks", callback_data="picks:today")],
            [InlineKeyboardButton("📅 Check the Schedule", callback_data="nav:schedule")],
            [InlineKeyboardButton("🏠 Main Menu", callback_data="nav:main")],
        ]),
    )


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
    if action == "view":
        prefs = await db.get_user_sport_prefs(user_id)
        teams_with_names = [p for p in prefs if p.team_name]
        if not teams_with_names:
            text = (
                "<b>🏟️ My Teams</b>\n\n"
                "No favourite teams set yet.\n"
                "Use /start to redo onboarding and pick your teams."
            )
        else:
            from collections import defaultdict
            sport_league_teams: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
            for p in teams_with_names:
                lg_label = ""
                if p.league:
                    lg = config.ALL_LEAGUES.get(p.league)
                    lg_label = _abbreviate_league(lg.label) if lg else p.league
                sport_league_teams[p.sport_key][lg_label].append(p.team_name)

            lines = ["<b>🏟️ My Teams</b>\n"]
            for sk, league_dict in sport_league_teams.items():
                sport = config.ALL_SPORTS.get(sk)
                emoji = sport.emoji if sport else "🏅"
                label = sport.label if sport else sk
                lines.append(f"{emoji} <b>{label}</b>")
                if len(league_dict) <= 1:
                    all_t: list[str] = []
                    for teams in league_dict.values():
                        all_t.extend(teams)
                    lines.append(f"  {', '.join(all_t)}")
                else:
                    for lg_name, teams in league_dict.items():
                        if lg_name and teams:
                            lines.append(f"  {lg_name}: {', '.join(teams)}")
                        elif teams:
                            lines.append(f"  {', '.join(teams)}")
                lines.append("")
            text = "\n".join(lines)
        await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb_teams())
    elif action == "edit":
        # Show league picker for editing
        prefs = await db.get_user_sport_prefs(user_id)
        leagues_with_prefs: list[tuple[str, str]] = []
        seen: set[str] = set()
        for p in prefs:
            if p.league and p.league not in seen:
                seen.add(p.league)
                leagues_with_prefs.append((p.sport_key, p.league))

        if not leagues_with_prefs:
            await query.edit_message_text(
                "<b>✏️ Edit Teams</b>\n\nNo leagues set up yet. Use /start to get set up.",
                parse_mode=ParseMode.HTML, reply_markup=kb_teams(),
            )
            return

        rows: list[list[InlineKeyboardButton]] = []
        for sk, lk in leagues_with_prefs:
            sport = config.ALL_SPORTS.get(sk)
            emoji = sport.emoji if sport else "🏅"
            lg = config.ALL_LEAGUES.get(lk)
            lg_label = lg.label if lg else lk
            rows.append([InlineKeyboardButton(
                f"{emoji} {lg_label}",
                callback_data=f"teams:edit_league:{sk}:{lk}",
            )])
        rows.append([
            InlineKeyboardButton("↩️ Back", callback_data="teams:view"),
            InlineKeyboardButton("🏠 Main Menu", callback_data="menu:home"),
        ])
        await query.edit_message_text(
            "<b>✏️ Edit Teams</b>\n\nSelect a league to update your teams:",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(rows),
        )
    elif action.startswith("edit_league:"):
        # Enter text input mode for a specific league
        parts = action.split(":", 2)
        if len(parts) < 3:
            return
        sk, lk = parts[1], parts[2]
        sport = config.ALL_SPORTS.get(sk)
        emoji = sport.emoji if sport else "🏅"
        entity = config.fav_label(sport) if sport else "favourite"
        lg = config.ALL_LEAGUES.get(lk)
        lg_label = lg.label if lg else lk
        example = config.LEAGUE_EXAMPLES.get(lk, "")
        example_line = f"\n<i>{example}</i>\n" if example else ""

        _team_edit_state[user_id] = {"sport_key": sk, "league_key": lk}

        text = (
            f"<b>✏️ {emoji} {lg_label} — edit {entity}s</b>\n\n"
            f"Type your {entity}s separated by commas.{example_line}\n"
            f"This will replace your current selections.\n"
            f"Or type <b>cancel</b> to go back."
        )
        await query.edit_message_text(
            text, parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("↩️ Cancel", callback_data="teams:edit")],
            ]),
        )
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
    """Handle affiliate:* callbacks (bookmaker info)."""
    active = config.get_active_bookmaker()
    name = active["short_name"]
    website = active.get("website_url", "betway.co.za")
    text = (
        f"<b>🇿🇦 {name} — Our Recommended Bookmaker</b>\n\n"
        f"✅ Licensed in South Africa\n"
        f"✅ Fast deposits & withdrawals\n"
        f"✅ Great odds across all sports\n"
        f"✅ Easy sign-up with SA ID\n\n"
        f"🌐 <b>{website}</b>\n\n"
        f"<i>Always gamble responsibly. 18+ only.</i>"
    )
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb_bookmakers())


async def handle_settings(query, action: str) -> None:
    """Handle settings:* callbacks."""
    user_id = query.from_user.id
    user = await db.get_user(user_id)

    if action == "home":
        text = await format_profile_summary(user_id)
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
    elif action == "bankroll":
        current = getattr(user, "bankroll", None)
        current_str = f"R{current:,.0f}" if current else "Not set"
        text = (
            f"<b>💰 Bankroll</b>\n\n"
            f"Current: <b>{current_str}</b>\n\n"
            f"Select a new weekly bankroll:"
        )
        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("R500", callback_data="settings:set_bankroll:500"),
                InlineKeyboardButton("R1,000", callback_data="settings:set_bankroll:1000"),
            ],
            [
                InlineKeyboardButton("R2,000", callback_data="settings:set_bankroll:2000"),
                InlineKeyboardButton("R5,000", callback_data="settings:set_bankroll:5000"),
            ],
            [InlineKeyboardButton("↩️ Back", callback_data="settings:home")],
        ])
        await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
    elif action.startswith("set_bankroll:"):
        amount = float(action.split(":", 1)[1])
        await db.update_user_bankroll(user_id, amount)
        await query.edit_message_text(
            f"✅ Bankroll updated to <b>R{amount:,.0f}</b>/week.",
            parse_mode=ParseMode.HTML, reply_markup=kb_settings(),
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
            [InlineKeyboardButton("↩️ Cancel", callback_data="settings:home")],
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
    elif action == "story":
        # Notification preferences toggle view
        notify_prefs = db.get_notification_prefs(user)
        lines_text = "📖 <b>Your Notifications</b>\n\nTap to toggle:\n"
        buttons: list[list[InlineKeyboardButton]] = []
        for key, label in [
            ("daily_picks", "📊 Daily AI Picks"),
            ("game_day_alerts", "🏟️ Game Day Alerts"),
            ("weekly_recap", "📈 Weekly Recap"),
            ("edu_tips", "🎓 Education Tips"),
            ("market_movers", "📉 Market Movers"),
            ("bankroll_updates", "💰 Bankroll Updates"),
            ("live_scores", "⚡ Live Scores"),
        ]:
            status = "✅" if notify_prefs.get(key, False) else "❌"
            buttons.append([InlineKeyboardButton(
                f"{status} {label}",
                callback_data=f"settings:toggle_notify:{key}",
            )])
        buttons.append([InlineKeyboardButton("↩️ Back", callback_data="settings:home")])
        await query.edit_message_text(
            lines_text, parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(buttons),
        )
    elif action.startswith("toggle_notify:"):
        key = action.split(":", 1)[1]
        notify_prefs = db.get_notification_prefs(user)
        notify_prefs[key] = not notify_prefs.get(key, False)
        await db.update_notification_prefs(user_id, notify_prefs)
        # Re-show the notification settings
        lines_text = "📖 <b>Your Notifications</b>\n\nTap to toggle:\n"
        buttons_list: list[list[InlineKeyboardButton]] = []
        for k, label in [
            ("daily_picks", "📊 Daily AI Picks"),
            ("game_day_alerts", "🏟️ Game Day Alerts"),
            ("weekly_recap", "📈 Weekly Recap"),
            ("edu_tips", "🎓 Education Tips"),
            ("market_movers", "📉 Market Movers"),
            ("bankroll_updates", "💰 Bankroll Updates"),
        ]:
            status = "✅" if notify_prefs.get(k, False) else "❌"
            buttons_list.append([InlineKeyboardButton(
                f"{status} {label}",
                callback_data=f"settings:toggle_notify:{k}",
            )])
        buttons_list.append([InlineKeyboardButton("↩️ Back", callback_data="settings:home")])
        await query.edit_message_text(
            lines_text, parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(buttons_list),
        )
    else:
        await query.edit_message_text("<b>⚙️ Settings</b>", parse_mode=ParseMode.HTML, reply_markup=kb_settings())


# ── Restart / back handlers ──────────────────────────────

async def handle_ob_restart(query) -> None:
    """Restart onboarding from scratch (after profile reset)."""
    user_id = query.from_user.id
    _onboarding_state.pop(user_id, None)
    ob = _get_ob(user_id)
    ob["step"] = "experience"
    # Remove sticky keyboard during onboarding
    await query.message.chat.send_message(
        "🇿🇦 Setting up your profile…",
        reply_markup=ReplyKeyboardRemove(),
    )
    text = textwrap.dedent(f"""\
        <b>🇿🇦 Let's set up your profile!</b>

        <b>Step 1/8:</b> What's your betting experience?
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
    text = _fav_step_text(sport) if sport else "<b>Step 4/8</b>"
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
    onboarded = await db.get_onboarded_count()
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
        👥 Users: <b>{count}</b> (onboarded: {onboarded})
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

async def _post_init(app_instance) -> None:
    """Run on bot startup: init DB, publish guides, register commands."""
    await db.init_db()

    # Pre-publish Betway Telegra.ph guide and wire URL into config
    try:
        from scripts.telegraph_guides import ensure_active_guide
        await ensure_active_guide()
    except Exception as exc:
        log.warning("Could not pre-publish guide: %s", exc)

    await app_instance.bot.set_my_commands([
        ("start", "Start the bot"),
        ("menu", "Main menu"),
        ("picks", "Today's picks"),
        ("schedule", "Upcoming games"),
        ("help", "How to use MzansiEdge"),
        ("settings", "Your preferences"),
    ])


def main() -> None:
    log.info("Starting MzansiEdge bot…")
    app = Application.builder().token(config.BOT_TOKEN).build()

    # Initialise DB + register commands on startup
    app.post_init = _post_init

    # Command handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("menu", cmd_menu))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("odds", cmd_odds))
    app.add_handler(CommandHandler("tip", cmd_tip))
    app.add_handler(CommandHandler("picks", cmd_picks))
    app.add_handler(CommandHandler("schedule", cmd_schedule))
    app.add_handler(CommandHandler("settings", cmd_settings))
    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(CommandHandler("stats", cmd_stats))

    # Callback query handler (prefix:action routing)
    app.add_handler(CallbackQueryHandler(on_button))

    # Persistent reply keyboard taps (must be BEFORE freetext_handler)
    _kb_pattern = r"^(🎯 Picks|📅 Schedule|🔴 Live|📊 Stats|⚙️ Settings|❓ Help)$"
    app.add_handler(MessageHandler(filters.Regex(_kb_pattern), handle_keyboard_tap))

    # Free-text chat (also handles favourite input during onboarding)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, freetext_handler))

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
