#!/usr/bin/env python3
"""MzansiEdge — AI-powered sports betting Telegram bot for South Africa."""

from __future__ import annotations

import os
try:
    import sentry_sdk
except ImportError:
    sentry_sdk = None
from dotenv import load_dotenv
load_dotenv()
if sentry_sdk:
    sentry_sdk.init(dsn=os.getenv("SENTRY_DSN", ""))

import difflib
import logging
import os
import textwrap
from html import escape as h

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
    ConversationHandler,
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
from services.analytics import track as analytics_track
from services.stitch_service import stitch as stitch_service
from services.edge_rating import EdgeRating, calculate_edge_rating, calculate_edge_score
from services import odds_service as odds_svc
from services.affiliate_service import get_affiliate_url, select_best_bookmaker, get_runner_up_odds
from renderers.edge_renderer import render_edge_badge, render_tip_with_odds, render_tip_button_label, render_odds_comparison, EDGE_EMOJIS, EDGE_LABELS

# ── Logging setup (BUG-008: RotatingFileHandler so bot.log is always written) ──
from logging.handlers import RotatingFileHandler

_log_fmt = logging.Formatter("%(asctime)s | %(name)s | %(levelname)s | %(message)s")
_root = logging.getLogger()
_root.setLevel(logging.INFO)

_sh = logging.StreamHandler()
_sh.setFormatter(_log_fmt)
_root.addHandler(_sh)

_fh = RotatingFileHandler("bot.log", maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8")
_fh.setFormatter(_log_fmt)
_root.addHandler(_fh)

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

_KEYBOARD_LABELS = [
    "⚽ Your Games", "🔥 Hot Tips", "📖 Guide",
    "👤 Profile", "⚙️ Settings", "❓ Help",
]

# Legacy labels kept for transition — users with cached keyboards may still send these
_LEGACY_LABELS = {
    "🎯 Today's Picks": "hot_tips",         # old picks → Hot Tips
    "📅 Schedule": "your_games",             # old schedule → Your Games
    "🔴 Live Games": "live_games",           # old keyboard → Live Games
    "📊 My Stats": "stats",                  # old keyboard → Profile
    "📖 Betway Guide": "guide",              # old keyboard → Guide
}

def get_main_keyboard() -> ReplyKeyboardMarkup:
    """Return the persistent 2×3 reply keyboard."""
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("⚽ Your Games"), KeyboardButton("🔥 Hot Tips"), KeyboardButton("📖 Guide")],
            [KeyboardButton("👤 Profile"), KeyboardButton("⚙️ Settings"), KeyboardButton("❓ Help")],
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
        [
            InlineKeyboardButton("⚽ Your Games", callback_data="yg:all:0"),
            InlineKeyboardButton("🔥 Hot Tips", callback_data="hot:go"),
        ],
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
            f"📲 {active['short_name']} — Sign Up", url=website,
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
    analytics_track(user.id, "user_signed_up", {"returning": db_user.onboarding_done})
    if not db_user.onboarding_done:
        analytics_track(user.id, "onboarding_start")

    if db_user.onboarding_done:
        name = h(user.first_name or "")
        text = textwrap.dedent(f"""\
            <b>🇿🇦 Welcome back, {name}!</b>

            Your AI-powered sports betting assistant.
            Pick a sport or get an AI tip below.
        """)
        # Send sticky keyboard + inline menu in one message
        await update.message.reply_text(
            text, parse_mode=ParseMode.HTML,
            reply_markup=get_main_keyboard(),
        )
    else:
        # Start onboarding — hide sticky keyboard
        _onboarding_state.pop(user.id, None)  # reset
        ob = _get_ob(user.id)
        ob["step"] = "experience"
        name = h(user.first_name or "")
        # Remove persistent keyboard during onboarding
        await update.message.reply_text(
            "🇿🇦 Setting up your profile…",
            reply_markup=ReplyKeyboardRemove(),
        )
        text = textwrap.dedent(f"""\
            <b>🇿🇦 Welcome to MzansiEdge, {name}!</b>

            Let's set up your profile in a few quick steps.

            <b>Step 1/9:</b> What's your betting experience?
        """)
        await update.message.reply_text(
            text, parse_mode=ParseMode.HTML,
            reply_markup=kb_onboarding_experience(),
        )


# ── /menu ────────────────────────────────────────────────

async def cmd_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    name = h(user.first_name or "")
    text = textwrap.dedent(f"""\
        <b>🇿🇦 MzansiEdge — Main Menu</b>

        Hey {name}, pick a sport or get an AI tip.
    """)
    await update.message.reply_text(
        text, parse_mode=ParseMode.HTML, reply_markup=get_main_keyboard(),
    )


# ── /help ─────────────────────────────────────────────────

HELP_TEXT = textwrap.dedent("""\
    <b>MzansiEdge — Help</b>

    <b>Commands</b>
    /start — Onboarding / Main menu
    /menu — Main menu
    /picks — Hot tips (best value bets)
    /schedule — Your games (personalised schedule)
    /odds — Quick odds overview
    /tip — Get an AI prediction
    /help — This message

    <b>Bottom keyboard</b>
    ⚽ <b>Your Games</b> — Personalised 7-day schedule with AI edge markers
    🔥 <b>Hot Tips</b> — Top 5 value bets across all sports
    📖 <b>Guide</b> — Step-by-step Betway betting guide
    👤 <b>Profile</b> — Your sports, teams, and preferences
    ⚙️ <b>Settings</b> — Edit sports, risk, notifications
    ❓ <b>Help</b> — This message

    <b>How tips work</b>
    Our AI analyses live odds, recent form, and
    historical data to suggest value bets. Always
    gamble responsibly.
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
            # Legacy nav:schedule → redirect to Your Games
            user_id = query.from_user.id
            text, markup = await _render_your_games_all(user_id)
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
    elif prefix == "yg":
        user_id = query.from_user.id
        if action == "noop":
            return
        elif action.startswith("all:"):
            # yg:all:{page}
            pg = int(action.split(":")[1]) if ":" in action else 0
            text, markup = await _render_your_games_all(user_id, page=pg)
            await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
        elif action.startswith("sport:"):
            # yg:sport:{key}:{day}:{page}
            parts = action.split(":")
            sk = parts[1] if len(parts) > 1 else ""
            day_off = int(parts[2]) if len(parts) > 2 else 0
            pg = int(parts[3]) if len(parts) > 3 else 0
            text, markup = await _render_your_games_sport(user_id, sk, day_offset=day_off, page=pg)
            await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
        elif action.startswith("game:"):
            # yg:game:{event_id} — show AI game breakdown
            event_id = action.split(":", 1)[1]
            await _generate_game_tips(query, ctx, event_id, user_id)
    elif prefix == "hot":
        if action in ("go", "show", "back"):
            await _do_hot_tips_flow(query.message.chat_id, ctx.bot)
        elif action.startswith("page:"):
            try:
                page_num = int(action.split(":")[1])
            except (ValueError, IndexError):
                page_num = 0
            tips = _hot_tips_cache.get("global", {}).get("tips", [])
            if tips:
                text, markup = _build_hot_tips_page(tips, page_num)
                await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
            else:
                await _do_hot_tips_flow(query.message.chat_id, ctx.bot)
    elif prefix == "schedule":
        if action == "noop":
            return
        elif action.startswith("page:"):
            page_num = int(action.split(":", 1)[1])
            user_id = query.from_user.id
            games = _schedule_cache.get(user_id, [])
            if not games:
                games = await _fetch_schedule_games(user_id)
            prefs = await db.get_user_sport_prefs(user_id)
            user_teams = {p.team_name.lower() for p in prefs if p.team_name}
            text, markup = _render_schedule_page(games, user_teams, page=page_num)
            await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
        elif action.startswith("tips:"):
            event_id = action.split(":", 1)[1]
            await _generate_game_tips(query, ctx, event_id, query.from_user.id)
    elif prefix == "tip":
        if action == "affiliate_soon":
            await query.answer("🔗 Betway.co.za link coming soon! Check back tomorrow.", show_alert=True)
        else:
            await handle_tip_detail(query, ctx, action)
    elif prefix == "odds":
        if action.startswith("compare:"):
            event_id = action.split(":", 1)[1]
            await _handle_odds_comparison(query, event_id)
    elif prefix == "subscribe":
        await handle_subscribe(query, action)
    elif prefix == "unsubscribe":
        await handle_unsubscribe(query, action)
    elif prefix == "sub":
        if action.startswith("verify:"):
            reference = action.split(":", 1)[1]
            await _handle_sub_verify(query, reference)
        elif action == "cancel":
            await query.edit_message_text("❌ Subscription cancelled.", parse_mode=ParseMode.HTML)
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

            Hey {h(user.first_name or '')}, what would you like to do?
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
                    f"{icon} <b>{h(t.match)}</b>\n"
                    f"   {h(t.prediction)}"
                    + (f" @ {t.odds:.2f}" if t.odds else "")
                )
                lines.append("")
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

    # If no league had an API key, show a graceful message instead of calling AI with no data
    if not odds_context:
        await query.edit_message_text(
            f"⚠️ <b>{sport_label}</b>\n\n"
            "No odds data available for this sport right now.\n"
            "Try again later or pick a different sport.",
            parse_mode=ParseMode.HTML, reply_markup=kb_nav(),
        )
        return

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
        <b>Step 2/9: Select your sports</b>

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
        <b>Step 2/9: Select your sports</b>

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
        analytics_track(user_id, "onboarding_pick_sports", {"sports": list(ob["selected_sports"])})
        # Move to leagues — start with first sport
        ob["step"] = "leagues"
        ob["_league_idx"] = 0
        await _show_league_step(query, ob)

    elif action == "back_experience":
        ob["step"] = "experience"
        text = "<b>Step 1/9:</b> What's your betting experience?"
        await query.edit_message_text(
            text, parse_mode=ParseMode.HTML,
            reply_markup=kb_onboarding_experience(),
        )

    elif action == "back_sports":
        ob["step"] = "sports"
        text = "<b>Step 2/9: Select your sports</b>\n\nTap to toggle. Hit <b>Done</b> when ready."
        await query.edit_message_text(
            text, parse_mode=ParseMode.HTML,
            reply_markup=kb_onboarding_sports(ob["selected_sports"]),
        )

    elif action == "edge_done":
        # Edge explainer acknowledged — move to risk
        ob["step"] = "risk"
        text = "<b>Step 6/9: Risk profile</b>\n\nHow aggressive should your tips be?"
        await query.edit_message_text(
            text, parse_mode=ParseMode.HTML,
            reply_markup=kb_onboarding_risk(),
        )

    elif action == "back_risk":
        # Back from risk → edge explainer
        ob["step"] = "edge_explainer"
        await _show_edge_explainer(query, ob)

    elif action == "back_bankroll":
        # Back from bankroll → risk
        ob["step"] = "risk"
        text = "<b>Step 6/9: Risk profile</b>\n\nHow aggressive should your tips be?"
        await query.edit_message_text(
            text, parse_mode=ParseMode.HTML,
            reply_markup=kb_onboarding_risk(),
        )

    elif action == "back_notify":
        # Back from notify → bankroll
        ob["step"] = "bankroll"
        text = (
            "<b>Step 7/9: Weekly bankroll</b>\n\n"
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
        # Move to edge explainer
        ob["step"] = "edge_explainer"
        await _show_edge_explainer(query, ob)

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
        text = f"<b>Step 3/9: Select leagues for {sport.emoji} {sport.label}</b>\n\nTap to toggle."
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
        # All leagues done — show Edge explainer before risk
        ob["step"] = "edge_explainer"
        ob["_team_input_sport"] = None
        ob["_team_input_league"] = None
        await _show_edge_explainer(query, ob)
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
            f"<b>Step 4/9: {emoji} {league_label} — who do you follow?</b>\n\n"
            f"Type your {entity}s separated by commas.\n"
            f"Max 5 per league.{example_line}\n"
            f"Or type <b>skip</b> to move on."
        )
    else:
        sport_label = sport.label if sport else sport_key
        text = (
            f"<b>Step 4/9: {emoji} {sport_label} — who do you follow?</b>\n\n"
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
        f"<b>Step 4/9: Select your {label}s for {sport.emoji} {sport.label}</b>\n\n"
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
    text = f"<b>Step 3/9: Select leagues for {emoji} {label}</b>\n\nTap to toggle."
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
    text = _fav_step_text(sport) if sport else "<b>Step 4/9</b>"
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
        f"<b>Step 4/9: Type your {label} for {emoji} {sport_name}</b>\n\n"
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
    analytics_track(user_id, "onboarding_pick_teams", {"sport": sport_key})

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
    text = _fav_step_text(sport) if sport else "<b>Step 4/9</b>"
    await query.edit_message_text(
        text, parse_mode=ParseMode.HTML,
        reply_markup=kb_onboarding_favourites(sport_key, ob["favourites"][sport_key]),
    )


async def _show_edge_explainer(query, ob: dict) -> None:
    """Show the Edge Rating explainer screen during onboarding."""
    text = (
        "<b>Step 5/9: Understanding Your Edge</b>\n\n"
        "💎🥇🥈🥉 Every tip comes with an <b>Edge Rating</b> — "
        "our AI compares odds across 5+ SA bookmakers to find "
        "where the value is.\n\n"
        "💎 <b>Diamond Edge</b> — Rare. Exceptional value.\n"
        "   The bookmakers got this one wrong.\n\n"
        "🥇 <b>Gold Edge</b> — Strong find. Worth your attention.\n\n"
        "🥈 <b>Silver Edge</b> — Solid value. Good odds available.\n\n"
        "🥉 <b>Bronze Edge</b> — Slight edge. Positive value exists.\n\n"
        "Higher edge = bigger gap between what the "
        "bookmakers offer and what our AI thinks is fair."
    )
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("Got it ✅", callback_data="ob_nav:edge_done")],
    ])
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)


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
        "<b>Step 7/9: Weekly bankroll</b>\n\n"
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
            "<b>Step 7/9: Custom bankroll</b>\n\n"
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
            "<b>Step 7/9: Weekly bankroll</b>\n\n"
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
    text = "<b>Step 8/9: Daily picks notification</b>\n\nWhen do you want your daily tips?"
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
        "<b>Step 9/9: Your profile summary</b>\n\n"
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
    analytics_track(user_id, "onboarding_complete", {"experience": ob.get("experience", "casual")})
    experience = ob.get("experience", "casual")
    _onboarding_state.pop(user_id, None)

    user = query.from_user
    name = h(user.first_name or "champ")

    # Big welcome message with story quiz CTA
    text = (
        f"🎉 <b>Welcome to MzansiEdge, {name}!</b>\n\n"
        "You're in. Your edge is live.\n\n"
        "Here's what I can do for you:\n\n"
        "⚽ <b>Your Games</b> — Your personalised 7-day schedule with "
        "AI edge indicators on every game.\n\n"
        "🔥 <b>Hot Tips</b> — I scan odds across bookmakers, "
        "find value bets, and tell you exactly where the edge is.\n\n"
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
                "<b>Step 6/9: Risk profile</b>\n\nHow aggressive should your tips be?",
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
                    f"<b>Step 4/9: {emoji} {league_label} — who do you follow?</b>\n\n"
                    f"Type your {entity}s separated by commas.\n"
                    f"Max 5. Or type <b>skip</b> to move on."
                )
            else:
                sport_label = sport.label if sport else _sk
                text = (
                    f"<b>Step 4/9: {emoji} {sport_label} — who do you follow?</b>\n\n"
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
            lines.append(f"  ✅ {h(m)}")
    if unmatched:
        lines.append("")
        lines.append("<b>Couldn't match:</b>")
        for u in unmatched:
            lines.append(f"  ❌ {h(u)}")
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
        lines.append(f"  ✅ {h(m)}")
    if unmatched:
        lines.append("")
        for u in unmatched:
            lines.append(f"  ❌ {h(u)} (skipped)")

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

    # Handle legacy button labels from cached keyboards
    legacy = _LEGACY_LABELS.get(text)
    if legacy == "hot_tips":
        text = "🔥 Hot Tips"
    elif legacy == "your_games":
        text = "⚽ Your Games"
    elif legacy == "live_games":
        await _show_live_games(update, user_id)
        return
    elif legacy == "stats":
        await _show_stats_overview(update, user_id)
        return
    elif legacy == "guide":
        text = "📖 Guide"

    if text == "⚽ Your Games":
        db_user = await db.get_user(user_id)
        if not db_user or not db_user.onboarding_done:
            await update.message.reply_text(
                "🏟️ Complete your profile first!\n\nUse /start to get set up.",
                parse_mode=ParseMode.HTML,
            )
            return
        await _show_your_games(update, ctx, user_id)
    elif text == "🔥 Hot Tips":
        await _show_hot_tips(update, ctx, user_id)
    elif text == "📖 Guide":
        await _show_betway_guide(update)
    elif text == "👤 Profile":
        db_user = await db.get_user(user_id)
        if not db_user or not db_user.onboarding_done:
            await update.message.reply_text(
                "👤 Complete onboarding first!\n\nUse /start to get set up.",
                parse_mode=ParseMode.HTML,
            )
            return
        await _show_profile(update, user_id)
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
            "Use ⚽ <b>Your Games</b> to find games, tap one for tips, "
            "then hit <b>🔔 Follow this game</b> to get live updates.",
            parse_mode=ParseMode.HTML,
        )
        return

    lines = [f"🔴 <b>Live Games ({len(active)})</b>\n"]
    buttons = []
    for sub in active:
        hf, af = _get_flag_prefixes(sub.home_team, sub.away_team)
        lines.append(f"  ⚡ {hf}{h(sub.home_team)} vs {af}{h(sub.away_team)}")
        lines.append("")
        buttons.append([InlineKeyboardButton(
            f"🔕 Unfollow {sub.home_team} vs {sub.away_team}",
            callback_data=f"unsubscribe:{sub.event_id}",
        )])
    buttons.append([InlineKeyboardButton("⚽ Your Games", callback_data="yg:all:0")])

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


async def _show_profile(update: Update, user_id: int) -> None:
    """Show user profile summary from the sticky keyboard."""
    summary = await format_profile_summary(user_id)
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚙️ Edit Profile", callback_data="settings:home")],
        [InlineKeyboardButton("↩️ Menu", callback_data="nav:main")],
    ])
    await update.message.reply_text(summary, parse_mode=ParseMode.HTML, reply_markup=buttons)


async def _show_betway_guide(update: Update) -> None:
    """Show the betting guide with Edge Ratings section and Betway guide link."""
    active_bk = config.get_active_bookmaker()
    guide_url = active_bk.get("guide_url", "")

    # Edge Ratings section (always shown first)
    text = (
        "📊 <b>Edge Ratings Explained</b>\n\n"
        "Our AI compares odds from 5+ SA bookmakers and "
        "calculates the expected value (EV) of every bet. "
        "The Edge Rating tells you how strong the value is:\n\n"
        "💎 <b>Diamond Edge</b> (EV ≥15%)\n"
        "   Exceptional. The bookmakers have seriously\n"
        "   mispriced this. Rare — you might see 1-2 a week.\n\n"
        "🥇 <b>Gold Edge</b> (EV ≥8%)\n"
        "   Strong value. Our AI found a meaningful gap\n"
        "   between the odds offered and fair probability.\n\n"
        "🥈 <b>Silver Edge</b> (EV ≥4%)\n"
        "   Solid. Good odds available at one or more\n"
        "   SA bookmakers.\n\n"
        "🥉 <b>Bronze Edge</b> (EV ≥1%)\n"
        "   Marginal. A slight positive edge exists.\n"
        "   Proceed with smaller stakes.\n\n"
        "💡 <i>Tip: Focus on Gold and Diamond tips for "
        "the best risk-adjusted returns.</i>"
    )

    # Betway guide section
    if guide_url:
        text += (
            "\n\n─────────────────────\n\n"
            f"📖 <b>{active_bk['short_name']} Betting Guide</b>\n\n"
            f"New to {active_bk['short_name']}? Our step-by-step guide covers everything "
            "from creating your account to placing your first bet."
        )
        buttons = [[InlineKeyboardButton(f"📖 Open {active_bk['short_name']} Guide →", url=guide_url)]]
    else:
        text += (
            "\n\n─────────────────────\n\n"
            f"📖 <b>{active_bk['short_name']} Betting Guide</b>\n\n"
            f"Our step-by-step {active_bk['short_name']} guide is coming soon!"
        )
        buttons = [[InlineKeyboardButton(
            f"📲 Visit {active_bk['short_name']}.co.za →",
            url=active_bk.get("website_url", "https://www.betway.co.za"),
        )]]

    await update.message.reply_text(
        text, parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
        disable_web_page_preview=True,
    )


# ── Your Games — all-games default + sport-specific 7-day view ──


def _parse_date(commence_time: str):
    """Parse commence_time string to SAST datetime. Returns None on failure."""
    from datetime import datetime as dt_cls
    from zoneinfo import ZoneInfo
    try:
        ct = dt_cls.fromisoformat(commence_time.replace("Z", "+00:00"))
        return ct.astimezone(ZoneInfo(config.TZ))
    except Exception:
        return None


def _format_date_label(date_obj, now_dt=None) -> str:
    """Format a date as 'Today', 'Tomorrow', or 'Wednesday, 26 Feb'."""
    from datetime import datetime as dt_cls, timedelta
    from zoneinfo import ZoneInfo
    if now_dt is None:
        now_dt = dt_cls.now(ZoneInfo(config.TZ))
    today = now_dt.date() if hasattr(now_dt, "date") else now_dt
    if date_obj == today:
        return "Today"
    if date_obj == today + timedelta(days=1):
        return "Tomorrow"
    return date_obj.strftime("%A, %d %b")


def _get_sport_emoji_for_api_key(api_key: str) -> str:
    """Get sport emoji for an Odds API sport key."""
    for s in config.SPORTS:
        for lg in s.leagues:
            if lg.api_key == api_key:
                return s.emoji
    if api_key.startswith("soccer"): return "⚽"
    if api_key.startswith("rugby"): return "🏉"
    if api_key.startswith("cricket"): return "🏏"
    if api_key.startswith("basketball"): return "🏀"
    if api_key.startswith("american"): return "🏈"
    if api_key.startswith("tennis"): return "🎾"
    if api_key.startswith("mma") or api_key.startswith("boxing"): return "🥊"
    if api_key.startswith("golf"): return "⛳"
    return "🏅"


async def _show_your_games(update: Update, ctx: ContextTypes.DEFAULT_TYPE, user_id: int) -> None:
    """Show the default all-games view."""
    text, markup = await _render_your_games_all(user_id)
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)


async def _render_your_games_all(
    user_id: int, page: int = 0,
) -> tuple[str, InlineKeyboardMarkup]:
    """Default Your Games — all games sorted by edge, sport filter buttons below."""
    from datetime import datetime as dt_cls
    from zoneinfo import ZoneInfo

    sa_tz = ZoneInfo(config.TZ)
    now = dt_cls.now(sa_tz)

    games = _schedule_cache.get(user_id)
    if games is None:
        games = await _fetch_schedule_games(user_id)

    prefs = await db.get_user_sport_prefs(user_id)
    user_teams = {p.team_name.lower() for p in prefs if p.team_name}
    league_keys = {p.league for p in prefs if p.league}

    if not league_keys:
        text = (
            "⚽ <b>Your Games</b>\n\n"
            "No leagues selected! Set up your sports first."
        )
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("⚙️ Edit Sports", callback_data="settings:sports")],
            [InlineKeyboardButton("↩️ Menu", callback_data="nav:main")],
        ])
        return text, markup

    if not games:
        # Check if the user only follows leagues without API data
        keyless = [
            config.ALL_LEAGUES[lk].label
            for lk in league_keys
            if lk in config.ALL_LEAGUES and not config.SPORTS_MAP.get(lk)
        ]
        if keyless and len(keyless) == len(league_keys):
            extra = (
                "\n\nYour leagues (<i>" + ", ".join(keyless) + "</i>) "
                "don't have live odds data yet. "
                "Try adding a league like EPL, PSL, or NBA for full coverage."
            )
        elif keyless:
            extra = (
                "\n\n<i>Note: " + ", ".join(keyless) +
                " don't have live odds data yet.</i>"
            )
        else:
            extra = "\nCheck back later or add more teams in Settings."
        text = (
            "⚽ <b>Your Games</b>\n\n"
            "No upcoming games found for your teams."
            + extra
        )
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔥 Hot Tips", callback_data="hot:go")],
            [InlineKeyboardButton("⚙️ Edit Teams", callback_data="settings:sports")],
            [InlineKeyboardButton("↩️ Menu", callback_data="nav:main")],
        ])
        return text, markup

    # Check edges
    edge_events = await _check_edges_for_games(games)

    # Sort: edge games first, then by commence_time
    def sort_key(g):
        has_edge = 1 if edge_events.get(g.get("id", "")) else 0
        return (-has_edge, g.get("commence_time", ""))

    sorted_games = sorted(games, key=sort_key)

    # Paginate
    per_page = GAMES_PER_PAGE
    total_pages = max(1, (len(sorted_games) + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    page_games = sorted_games[page * per_page : (page + 1) * per_page]

    edge_count = sum(1 for eid in edge_events if edge_events[eid])
    total = len(sorted_games)

    lines = ["⚽ <b>Your Games</b>"]
    summary = [f"{total} game{'s' if total != 1 else ''}"]
    if edge_count:
        summary.append(f"🔥 {edge_count} with edge")
    lines.append(" · ".join(summary))
    lines.append("")

    # Group page games by date
    current_date_label = None
    for idx, event in enumerate(page_games, page * per_page + 1):
        ct_sa = _parse_date(event.get("commence_time", ""))
        if ct_sa:
            event_date = ct_sa.date()
            date_label = _format_date_label(event_date, now)
            if date_label != current_date_label:
                if current_date_label is not None:
                    lines.append("")
                current_date_label = date_label
                lines.append(f"<b>{date_label}</b>")
            event_time = ct_sa.strftime("%H:%M")
        else:
            event_time = ""
            if current_date_label != "TBC":
                current_date_label = "TBC"
                lines.append("<b>TBC</b>")

        home_raw = event.get("home_team", "?")
        away_raw = event.get("away_team", "?")
        home = h(home_raw)
        away = h(away_raw)
        emoji = event.get("sport_emoji", "🏅")
        event_id = event.get("id", "")
        hf, af = _get_flag_prefixes(home_raw, away_raw)
        home_display = f"<b>{hf}{home}</b>" if home.lower() in user_teams else f"{hf}{home}"
        away_display = f"<b>{af}{away}</b>" if away.lower() in user_teams else f"{af}{away}"
        edge_marker = " 🔥" if edge_events.get(event_id) else ""
        lines.append(f"<b>[{idx}]</b> {emoji} {event_time}  {home_display} vs {away_display}{edge_marker}")

    text = "\n".join(lines)

    # Build buttons
    buttons: list[list[InlineKeyboardButton]] = []

    # Game buttons
    for i, event in enumerate(page_games, page * per_page + 1):
        home = event.get("home_team", "?")
        away = event.get("away_team", "?")
        emoji = event.get("sport_emoji", "🏅")
        event_id = event.get("id", str(i))
        h_abbr = config.abbreviate_team(home)
        a_abbr = config.abbreviate_team(away)
        edge = " 🔥" if edge_events.get(event_id) else ""
        buttons.append([InlineKeyboardButton(
            f"[{i}] {emoji} {h_abbr} vs {a_abbr}{edge}",
            callback_data=f"yg:game:{event_id}",
        )])

    # Pagination
    if total_pages > 1:
        nav_row: list[InlineKeyboardButton] = []
        if page > 0:
            nav_row.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"yg:all:{page - 1}"))
        nav_row.append(InlineKeyboardButton(f"📄 {page + 1}/{total_pages}", callback_data="yg:noop"))
        if page < total_pages - 1:
            nav_row.append(InlineKeyboardButton("Next ➡️", callback_data=f"yg:all:{page + 1}"))
        buttons.append(nav_row)

    # Sport filter buttons (only if 2+ sports)
    user_sport_keys = set()
    for lk in league_keys:
        sk = config.LEAGUE_SPORT.get(lk)
        if sk:
            user_sport_keys.add(sk)
    if len(user_sport_keys) >= 2:
        sport_row: list[InlineKeyboardButton] = []
        for sk in sorted(user_sport_keys):
            sport_def = config.ALL_SPORTS.get(sk)
            if not sport_def:
                continue
            sport_row.append(InlineKeyboardButton(
                sport_def.emoji,
                callback_data=f"yg:sport:{sk}:0:0",
            ))
        buttons.append(sport_row[:6])

    # Bottom nav
    buttons.append([
        InlineKeyboardButton("🔥 Hot Tips", callback_data="hot:go"),
        InlineKeyboardButton("↩️ Menu", callback_data="nav:main"),
    ])

    return text, InlineKeyboardMarkup(buttons)


async def _render_your_games_sport(
    user_id: int, sport_key: str, day_offset: int = 0, page: int = 0,
) -> tuple[str, InlineKeyboardMarkup]:
    """Sport-specific Your Games view with 7-day navigation."""
    from datetime import datetime as dt_cls, timedelta
    from zoneinfo import ZoneInfo

    sa_tz = ZoneInfo(config.TZ)
    now = dt_cls.now(sa_tz)
    target_date = (now + timedelta(days=day_offset)).date()

    games = _schedule_cache.get(user_id)
    if games is None:
        games = await _fetch_schedule_games(user_id)

    prefs = await db.get_user_sport_prefs(user_id)
    user_teams = {p.team_name.lower() for p in prefs if p.team_name}

    sport_def = config.ALL_SPORTS.get(sport_key)
    sport_name = sport_def.label if sport_def else sport_key
    sport_emoji = sport_def.emoji if sport_def else "🏅"

    # Filter by sport and date
    day_games = []
    for event in games:
        sk = config.LEAGUE_SPORT.get(event.get("league_key", ""))
        if sk != sport_key:
            continue
        ct_sa = _parse_date(event.get("commence_time", ""))
        if ct_sa and ct_sa.date() == target_date:
            day_games.append({**event, "_ct_sa": ct_sa})

    edge_events = await _check_edges_for_games(day_games)

    date_label = _format_date_label(target_date, now)

    # Day navigation labels
    day_names = []
    for d in range(7):
        d_date = (now + timedelta(days=d)).date()
        if d == 0:
            day_names.append("Today")
        elif d == 1:
            day_names.append("Tmrw")
        else:
            day_names.append(d_date.strftime("%a"))

    # Check if this sport has any leagues with API data
    sport_leagues = sport_def.leagues if sport_def else []
    has_api_leagues = any(lg.api_key for lg in sport_leagues)

    # Build text
    lines = [f"{sport_emoji} <b>{sport_name} — {date_label}</b>"]
    if not day_games:
        if not has_api_leagues:
            lines.append(
                f"\n{sport_name} doesn't have live odds data yet.\n"
                "We're working on adding more sports — check back soon!"
            )
        else:
            lines.append(f"\nNo {sport_name.lower()} games on {date_label.lower()}.")
    else:
        total = len(day_games)
        edge_count = sum(1 for g in day_games if edge_events.get(g.get("id", "")))
        summary = [f"{total} game{'s' if total != 1 else ''}"]
        if edge_count:
            summary.append(f"🔥 {edge_count} with edge")
        lines.append(" · ".join(summary))
        lines.append("")

    # Paginate
    per_page = GAMES_PER_PAGE
    total_pages = max(1, (len(day_games) + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    page_games = day_games[page * per_page : (page + 1) * per_page]

    for idx, event in enumerate(page_games, page * per_page + 1):
        ct_sa = event.get("_ct_sa")
        event_time = ct_sa.strftime("%H:%M") if ct_sa else ""
        home = event.get("home_team", "?")
        away = event.get("away_team", "?")
        event_id = event.get("id", "")
        hf, af = _get_flag_prefixes(home, away)
        home_display = f"<b>{hf}{home}</b>" if home.lower() in user_teams else f"{hf}{home}"
        away_display = f"<b>{af}{away}</b>" if away.lower() in user_teams else f"{af}{away}"
        edge_marker = " 🔥" if edge_events.get(event_id) else ""
        lines.append(f"<b>[{idx}]</b> {sport_emoji} {event_time}  {home_display} vs {away_display}{edge_marker}")

    text = "\n".join(lines)

    # Build buttons
    buttons: list[list[InlineKeyboardButton]] = []

    # Day navigation tabs — 2 rows
    day_row1: list[InlineKeyboardButton] = []
    day_row2: list[InlineKeyboardButton] = []
    for d in range(7):
        label = day_names[d]
        if d == day_offset:
            label = f"[{label}]"
        cb = f"yg:sport:{sport_key}:{d}:0"
        btn = InlineKeyboardButton(label, callback_data=cb)
        if d < 4:
            day_row1.append(btn)
        else:
            day_row2.append(btn)
    buttons.append(day_row1)
    buttons.append(day_row2)

    # Game buttons
    for i, event in enumerate(page_games, page * per_page + 1):
        home = event.get("home_team", "?")
        away = event.get("away_team", "?")
        event_id = event.get("id", str(i))
        h_abbr = config.abbreviate_team(home)
        a_abbr = config.abbreviate_team(away)
        edge = " 🔥" if edge_events.get(event_id) else ""
        buttons.append([InlineKeyboardButton(
            f"[{i}] {sport_emoji} {h_abbr} vs {a_abbr}{edge}",
            callback_data=f"yg:game:{event_id}",
        )])

    # Pagination
    if total_pages > 1:
        nav_row: list[InlineKeyboardButton] = []
        if page > 0:
            nav_row.append(InlineKeyboardButton(
                "⬅️ Prev", callback_data=f"yg:sport:{sport_key}:{day_offset}:{page - 1}",
            ))
        nav_row.append(InlineKeyboardButton(f"📄 {page + 1}/{total_pages}", callback_data="yg:noop"))
        if page < total_pages - 1:
            nav_row.append(InlineKeyboardButton(
                "Next ➡️", callback_data=f"yg:sport:{sport_key}:{day_offset}:{page + 1}",
            ))
        buttons.append(nav_row)

    # Bottom nav
    buttons.append([
        InlineKeyboardButton("⬅️ All Games", callback_data="yg:all:0"),
        InlineKeyboardButton("↩️ Menu", callback_data="nav:main"),
    ])

    return text, InlineKeyboardMarkup(buttons)


async def _check_edges_for_games(games: list[dict]) -> dict[str, bool]:
    """Quick check if games have positive EV edges on SA bookmakers.

    Returns dict of event_id → has_edge (True if any outcome has EV > 2%).
    Uses cached odds when available to avoid extra API calls.
    """
    from scripts.odds_client import fetch_odds_cached, fair_probabilities, find_best_sa_odds, calculate_ev

    edge_map: dict[str, bool] = {}
    if not games:
        return edge_map

    # Group games by league to batch odds fetches
    by_league: dict[str, list[dict]] = {}
    for game in games:
        lk = game.get("league_key", "")
        by_league.setdefault(lk, []).append(game)

    for lk, lg_games in by_league.items():
        api_key = config.SPORTS_MAP.get(lk)
        if not api_key:
            for g in lg_games:
                edge_map[g.get("id", "")] = False
            continue

        try:
            result = await fetch_odds_cached(api_key, regions="eu,uk,au", markets="h2h")
            if not result["ok"]:
                for g in lg_games:
                    edge_map[g.get("id", "")] = False
                continue

            odds_by_id = {ev.get("id"): ev for ev in (result["data"] or [])}

            for game in lg_games:
                eid = game.get("id", "")
                event_odds = odds_by_id.get(eid)
                if not event_odds or not event_odds.get("bookmakers"):
                    edge_map[eid] = False
                    continue

                fair_probs = fair_probabilities(event_odds)
                best_entries = find_best_sa_odds(event_odds)
                has_edge = False
                for entry in best_entries:
                    prob = fair_probs.get(entry.outcome, 0)
                    if prob <= 0:
                        continue
                    ev_pct = calculate_ev(entry.price, prob)
                    if ev_pct > 2.0:
                        has_edge = True
                        break
                edge_map[eid] = has_edge
        except Exception:
            for g in lg_games:
                edge_map[g.get("id", "")] = False

    return edge_map


# ── Hot Tips — all-sports value bet scanner ───────────────

# Comprehensive list of Odds API sport keys to scan across all markets
HOT_TIPS_SCAN_SPORTS = [
    # Soccer
    "soccer_epl", "soccer_spain_la_liga", "soccer_germany_bundesliga",
    "soccer_italy_serie_a", "soccer_france_ligue_one", "soccer_uefa_champs_league",
    "soccer_south_africa_premier_league", "soccer_usa_mls",
    # Rugby
    "rugbyunion_super_rugby_pacific", "rugbyunion_urc",
    # Cricket
    "cricket_ipl", "cricket_test_match", "cricket_big_bash",
    # Basketball
    "basketball_nba", "basketball_euroleague",
    # American Football
    "americanfootball_nfl",
    # MMA & Boxing
    "mma_mixed_martial_arts", "boxing_boxing",
    # Tennis (Grand Slams)
    "tennis_atp_aus_open_singles", "tennis_atp_french_open_singles",
    "tennis_atp_us_open_singles", "tennis_atp_wimbledon_singles",
    # Golf
    "golf_pga_championship_winner", "golf_masters_tournament_winner",
]

_hot_tips_cache: dict[str, dict] = {}  # "global" → {"tips": [...], "ts": float}
HOT_TIPS_CACHE_TTL = 900  # 15 minutes

# Leagues available in our scrapers DB (odds.db)
DB_LEAGUES = ["psl", "epl", "champions_league"]

# Display name helpers for odds.db normalised keys
_LEAGUE_DISPLAY = {"psl": "PSL", "epl": "EPL", "champions_league": "Champions League"}
_BK_DISPLAY = {
    "hollywoodbets": "Hollywoodbets", "betway": "Betway",
    "supabets": "SupaBets", "sportingbet": "Sportingbet", "gbets": "GBets",
}


def _display_team_name(key: str) -> str:
    """Convert odds.db normalised key to display name: 'mamelodi_sundowns' → 'Mamelodi Sundowns'."""
    try:
        import sys
        if "/home/paulsportsza" not in sys.path:
            sys.path.insert(0, "/home/paulsportsza")
        from scrapers.odds_normaliser import display_name
        return display_name(key)
    except (ImportError, Exception):
        return key.replace("_", " ").title()


def _display_bookmaker_name(key: str) -> str:
    """Convert bookmaker key to display name."""
    return _BK_DISPLAY.get(key, key.title())


def _get_flag_prefixes(home: str, away: str) -> tuple[str, str]:
    """Return (home_flag, away_flag) with both-or-nothing rule.

    If BOTH teams have a flag → return both flags (with trailing space).
    If EITHER team has no flag → return ('', '') for both.
    """
    hf = config.get_country_flag(home)
    af = config.get_country_flag(away)
    if hf and af:
        return (hf + " ", af + " ")
    return ("", "")


HOT_TIPS_PAGE_SIZE = 5


def _assign_display_tiers(tips: list[dict]) -> None:
    """Assign percentile-based display tiers for UX diversity.

    Raw edge_score and edge_rating are preserved for analytics.
    display_tier is used for rendering badges.
    """
    if not tips:
        return
    tips.sort(key=lambda t: t.get("edge_score", 0), reverse=True)
    n = len(tips)
    for i, tip in enumerate(tips):
        pct = i / max(n - 1, 1)  # 0.0 = best, 1.0 = worst
        if pct <= 0.1:
            tip["display_tier"] = EdgeRating.DIAMOND
        elif pct <= 0.35:
            tip["display_tier"] = EdgeRating.GOLD
        elif pct <= 0.65:
            tip["display_tier"] = EdgeRating.SILVER
        else:
            tip["display_tier"] = EdgeRating.BRONZE


def _build_tip_narrative(tip: dict) -> str:
    """Build a compelling narrative explaining WHY this tip has value."""
    outcome = tip.get("predicted_outcome", "") or tip.get("outcome", "this team")
    best_bk = (
        tip.get("best_bookmaker_display", "")
        or tip.get("bookmaker", "")
        or _display_bookmaker_name(tip.get("best_bookmaker", ""))
        or "the best bookmaker"
    )
    best_odds = tip.get("best_odds", 0) or tip.get("odds", 0)
    ev = tip.get("ev_pct", 0) or tip.get("ev", 0)
    tier = tip.get("display_tier", tip.get("edge_rating", "GOLD"))
    odds_by_bk = tip.get("odds_by_bookmaker", {})
    # consensus_prob may be 0-1 or 0-100 (as "prob" percentage)
    consensus_prob = tip.get("consensus_prob", 0)
    if consensus_prob == 0 and tip.get("prob", 0) > 0:
        consensus_prob = tip["prob"] / 100.0

    # Calculate market average odds for the predicted outcome
    all_odds = [v for v in odds_by_bk.values() if v and v > 1]
    avg_odds = sum(all_odds) / len(all_odds) if all_odds else best_odds

    # Guard against zero/missing data
    if not best_odds or best_odds <= 1:
        return ""

    # How much above average is the best price?
    premium_pct = ((best_odds - avg_odds) / avg_odds * 100) if avg_odds > 0 else 0

    # How many bookmakers offer lower odds?
    cheaper_count = sum(1 for o in all_odds if o < best_odds)

    parts = []

    # Opening — unified "The Edge:" brand with tier-specific emoji
    if tier == "DIAMOND":
        parts.append("💎 <b>The Edge:</b>")
    elif tier == "GOLD":
        parts.append("🥇 <b>The Edge:</b>")
    elif tier == "SILVER":
        parts.append("🥈 <b>The Edge:</b>")
    else:
        parts.append("🥉 <b>The Edge:</b>")

    # Core insight — why the odds are good
    if premium_pct > 5:
        parts.append(
            f"No other SA bookmaker has {outcome} at these odds. "
            f"{best_bk} is offering <b>{best_odds:.2f}</b>, "
            f"well above the market average of {avg_odds:.2f}."
        )
    elif premium_pct > 2:
        parts.append(
            f"{best_bk} has {outcome} at <b>{best_odds:.2f}</b>, "
            f"above the {avg_odds:.2f} market average."
        )
    else:
        parts.append(
            f"Best price on {outcome} is <b>{best_odds:.2f}</b> at {best_bk}."
        )

    # Probability insight
    if consensus_prob > 0:
        prob_pct = consensus_prob * 100
        parts.append(
            f"Our model gives this a {prob_pct:.0f}% chance — "
            f"at these odds, that's a <b>+{ev:.1f}% edge</b>."
        )

    # Social proof — other bookmakers
    if cheaper_count >= 3:
        parts.append(
            f"{cheaper_count} other bookmakers have already shortened their prices."
        )
    elif cheaper_count >= 1:
        parts.append(
            "Other bookmakers are pricing this tighter, "
            f"making the {best_bk} price stand out."
        )

    return " ".join(parts)


def _format_freshness(minutes_ago: int) -> str:
    """Smart freshness display — only show when impressive."""
    if minutes_ago <= 5:
        return "<i>⚡ Live odds</i>"
    elif minutes_ago <= 20:
        return f"<i>Odds updated {minutes_ago} min ago</i>"
    else:
        return "<i>Live SA bookmaker odds</i>"


def _build_edge_snapshots_from_match(match: dict) -> list[dict]:
    """Convert odds_service match data into edge_rating odds_snapshots format.

    calculate_edge_rating() expects: [{bookmaker, outcome, odds, timestamp}, ...]
    get_best_odds() returns: {outcomes: {outcome_key: {all_bookmakers: {bk: odds}}}}
    """
    snapshots = []
    outcomes = match.get("outcomes", {})
    ts = match.get("last_updated", "")

    for outcome_key, outcome_data in outcomes.items():
        for bk_key, odds_val in outcome_data.get("all_bookmakers", {}).items():
            snapshots.append({
                "bookmaker": bk_key,
                "outcome": outcome_key,
                "odds": odds_val,
                "timestamp": ts,
            })

    return snapshots


def _build_model_from_consensus(match: dict) -> dict:
    """Build a model prediction from cross-bookmaker consensus.

    Without an external sharp line, average implied probabilities across
    bookmakers to create the reference model. The predicted outcome is
    the one with the highest consensus probability (the favourite).
    """
    outcomes = match.get("outcomes", {})
    if not outcomes:
        return {}

    # Calculate average implied probability for each outcome
    avg_probs: dict[str, float] = {}
    for outcome_key, outcome_data in outcomes.items():
        all_bk = outcome_data.get("all_bookmakers", {})
        probs = [1.0 / o for o in all_bk.values() if o and o > 1.0]
        if probs:
            avg_probs[outcome_key] = sum(probs) / len(probs)

    if not avg_probs:
        return {}

    # The favourite is the outcome with the highest implied probability
    best_outcome = max(avg_probs, key=avg_probs.get)
    best_prob = avg_probs[best_outcome]

    # Confidence based on number of bookmakers (5 = 100%)
    bk_count = match.get("bookmaker_count", 1)
    confidence = min(bk_count / 5.0, 1.0)

    return {
        "outcome": best_outcome,
        "confidence": confidence,
        "implied_prob": best_prob,
    }


async def _fetch_hot_tips_from_db() -> list[dict]:
    """Fetch hot tips from Dataminer's odds.db — no external API needed.

    Uses cross-bookmaker consensus as the model, then scores with edge rating.
    Returns tips in the same dict format as _fetch_hot_tips_all_sports().
    """
    import time

    cache_entry = _hot_tips_cache.get("global")
    if cache_entry and (time.time() - cache_entry["ts"]) < HOT_TIPS_CACHE_TTL:
        return cache_entry["tips"]

    all_tips: list[dict] = []

    for league in DB_LEAGUES:
        try:
            matches = await odds_svc.get_all_matches(market_type="1x2", league=league)

            for match in matches:
                # Need 2+ bookmakers for meaningful edge calculation
                if match.get("bookmaker_count", 0) < 2:
                    continue

                # Build inputs for edge rating
                snapshots = _build_edge_snapshots_from_match(match)
                model = _build_model_from_consensus(match)
                if not model or not model.get("outcome"):
                    continue

                # Try to get line movement for bonus scoring
                movement = await odds_svc.detect_line_movement(
                    match["match_id"], model["outcome"],
                )

                edge = calculate_edge_rating(snapshots, model, movement)
                if edge == EdgeRating.HIDDEN:
                    continue
                edge_score = calculate_edge_score(snapshots, model, movement)

                # Find best bookmaker for CTA
                predicted_outcome = model["outcome"]
                outcome_data = match["outcomes"].get(predicted_outcome, {})
                odds_by_bk = outcome_data.get("all_bookmakers", {})
                best_odds = outcome_data.get("best_odds", 0)
                best_bk_key = outcome_data.get("best_bookmaker", "")

                # Calculate EV: (consensus_prob * best_odds - 1) * 100
                consensus_prob = model["implied_prob"]
                ev_pct = round((consensus_prob * best_odds - 1) * 100, 1) if best_odds > 0 else 0

                if ev_pct < 1.0:
                    continue  # Minimum EV threshold

                # Build a match_id-based event_id for cache lookups
                event_id = match["match_id"]

                # Convert normalised keys to display names
                home_display = _display_team_name(match.get("home_team", "?"))
                away_display = _display_team_name(match.get("away_team", "?"))

                # Map outcome key to human-readable label
                _outcome_labels = {"home": home_display,
                                   "away": away_display,
                                   "draw": "Draw"}
                outcome_label = _outcome_labels.get(predicted_outcome, predicted_outcome)

                all_tips.append({
                    "event_id": event_id,
                    "match_id": match["match_id"],  # Original DB key for lookups
                    "sport_key": "soccer",
                    "home_team": home_display,
                    "away_team": away_display,
                    "commence_time": "",  # odds.db doesn't store kickoff times
                    "outcome": outcome_label,
                    "odds": best_odds,
                    "bookmaker": _display_bookmaker_name(best_bk_key),
                    "ev": ev_pct,
                    "prob": round(consensus_prob * 100),
                    "kelly": 0,  # Not calculated for DB tips
                    "edge_rating": edge,
                    "edge_score": edge_score,
                    "league": _LEAGUE_DISPLAY.get(league, league.upper()),
                    "odds_by_bookmaker": odds_by_bk,
                })
        except Exception as exc:
            log.warning("Hot tips DB scan error for %s: %s", league, exc)
            continue

    # Sort by edge score descending, take top 10, then assign display tiers
    all_tips.sort(key=lambda t: (-t.get("edge_score", 0), -t["ev"]))
    top_tips = all_tips[:10]
    _assign_display_tiers(top_tips)

    _hot_tips_cache["global"] = {"tips": top_tips, "ts": time.time()}
    return top_tips


def _format_kickoff_display(commence_time: str) -> str:
    """Format commence time as 'Today 19:30' or 'Wed 26 Feb, 15:00'."""
    ct_sa = _parse_date(commence_time)
    if not ct_sa:
        return "TBC"
    from datetime import datetime as dt_cls, timedelta
    from zoneinfo import ZoneInfo
    now = dt_cls.now(ZoneInfo(config.TZ))
    today = now.date()
    if ct_sa.date() == today:
        return f"Today {ct_sa.strftime('%H:%M')}"
    if ct_sa.date() == today + timedelta(days=1):
        return f"Tomorrow {ct_sa.strftime('%H:%M')}"
    return ct_sa.strftime("%a %d %b, %H:%M")


async def _fetch_hot_tips_all_sports() -> list[dict]:
    """Scan all major sports for value bets. Uses 15-min cache."""
    import time
    from scripts.odds_client import fetch_odds_cached, fair_probabilities, find_best_sa_odds, calculate_ev
    from scripts.odds_client import kelly_stake as calc_kelly

    cache_entry = _hot_tips_cache.get("global")
    if cache_entry and (time.time() - cache_entry["ts"]) < HOT_TIPS_CACHE_TTL:
        return cache_entry["tips"]

    all_tips: list[dict] = []

    for sport_key in HOT_TIPS_SCAN_SPORTS:
        try:
            result = await fetch_odds_cached(sport_key, regions="eu,uk,au", markets="h2h")
            if not result["ok"] or not result.get("data"):
                continue

            for event in result["data"]:
                if not event.get("bookmakers"):
                    continue

                fair_probs = fair_probabilities(event)
                best_entries = find_best_sa_odds(event)

                for entry in best_entries:
                    prob = fair_probs.get(entry.outcome, 0)
                    if prob <= 0:
                        continue
                    ev_pct = calculate_ev(entry.price, prob)
                    if ev_pct < 2.0:
                        continue

                    # Build odds snapshots from all bookmakers for edge rating
                    odds_snaps = []
                    for bk in event.get("bookmakers", []):
                        for market in bk.get("markets", []):
                            if market.get("key") != "h2h":
                                continue
                            for oc in market.get("outcomes", []):
                                odds_snaps.append({
                                    "bookmaker": bk.get("key", ""),
                                    "outcome": oc.get("name", ""),
                                    "odds": oc.get("price"),
                                    "timestamp": event.get("commence_time", ""),
                                })

                    model_pred = {
                        "outcome": entry.outcome,
                        "confidence": min(prob, 0.95),
                        "implied_prob": prob,
                    }

                    edge = calculate_edge_rating(odds_snaps, model_pred)
                    if edge == EdgeRating.HIDDEN:
                        continue  # Filter out low-confidence tips

                    all_tips.append({
                        "event_id": event.get("id", ""),
                        "sport_key": sport_key,
                        "home_team": event.get("home_team", "?"),
                        "away_team": event.get("away_team", "?"),
                        "commence_time": event.get("commence_time", ""),
                        "outcome": entry.outcome,
                        "odds": entry.price,
                        "bookmaker": entry.bookmaker,
                        "ev": round(ev_pct, 1),
                        "prob": round(prob * 100),
                        "kelly": round(calc_kelly(entry.price, prob, fraction=0.5) * 100, 1),
                        "edge_rating": edge,
                    })
        except Exception as exc:
            log.warning("Hot tips scan error for %s: %s", sport_key, exc)
            continue

    # Sort by edge rating (diamond first), then EV descending
    _rating_order = {EdgeRating.DIAMOND: 0, EdgeRating.GOLD: 1, EdgeRating.SILVER: 2, EdgeRating.BRONZE: 3}
    all_tips.sort(key=lambda t: (_rating_order.get(t.get("edge_rating", ""), 9), -t["ev"]))
    top_tips = all_tips[:10]

    _hot_tips_cache["global"] = {"tips": top_tips, "ts": time.time()}
    return top_tips


async def _show_hot_tips(update: Update, ctx: ContextTypes.DEFAULT_TYPE, user_id: int) -> None:
    """Entry point for Hot Tips from sticky keyboard."""
    await _do_hot_tips_flow(update.effective_chat.id, ctx.bot)


def _build_hot_tips_page(tips: list[dict], page: int = 0) -> tuple[str, InlineKeyboardMarkup]:
    """Build text + keyboard for a single page of hot tips (max 5 per page)."""
    total = len(tips)
    total_pages = max((total + HOT_TIPS_PAGE_SIZE - 1) // HOT_TIPS_PAGE_SIZE, 1)
    page = max(0, min(page, total_pages - 1))
    start = page * HOT_TIPS_PAGE_SIZE
    end = start + HOT_TIPS_PAGE_SIZE
    page_tips = tips[start:end]

    if not page_tips:
        return (
            "🔥 <b>Hot Tips</b>\n\nNo edges found right now — the market is efficient.\n"
            "Check back when more games open!",
            InlineKeyboardMarkup([
                [InlineKeyboardButton("⚽ Your Games", callback_data="yg:all:0")],
                [InlineKeyboardButton("↩️ Menu", callback_data="nav:main")],
            ]),
        )

    # Header with page info
    if total_pages > 1:
        header = f"🔥 <b>Hot Tips — Page {page + 1}/{total_pages} ({total} bet{'s' if total != 1 else ''} found)</b>"
    else:
        header = f"🔥 <b>Hot Tips — {total} Value Bet{'s' if total != 1 else ''}</b>"

    lines = [
        header,
        f"<i>Scanned {len(DB_LEAGUES)} leagues across 5 SA bookmakers.</i>",
        "",
    ]

    for i, tip in enumerate(page_tips, start + 1):
        sport_emoji = _get_sport_emoji_for_api_key(tip.get("sport_key", ""))
        home_raw = tip.get("home_team", "")
        away_raw = tip.get("away_team", "")
        home = h(home_raw)
        away = h(away_raw)
        outcome = h(tip.get("outcome", ""))
        bk_name = h(tip.get("bookmaker", ""))

        hf, af = _get_flag_prefixes(home_raw, away_raw)
        badge = render_edge_badge(tip.get("display_tier", tip.get("edge_rating", "")))
        badge_suffix = f" {badge}" if badge else ""

        league_display = tip.get("league", "")
        kickoff = _format_kickoff_display(tip["commence_time"]) if tip.get("commence_time") else ""
        time_line = f"     🏆 {league_display}"
        if kickoff and kickoff != "TBC":
            time_line += f" · ⏰ {kickoff}"

        bk_part = f" ({bk_name})" if bk_name else ""
        lines.append(
            f"<b>[{i}]</b> {sport_emoji} <b>{hf}{home} vs {af}{away}</b>{badge_suffix}\n"
            f"{time_line}\n"
            f"     💰 {outcome} @ <b>{tip['odds']:.2f}</b>{bk_part} · EV +{tip['ev']}%"
        )
        lines.append("")

    text = "\n".join(lines)

    # Build numbered tip buttons (max 5 per page)
    buttons: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for i, tip in enumerate(page_tips, start + 1):
        event_id = tip.get("event_id", "")
        row.append(InlineKeyboardButton(
            f"[{i}] 🔍",
            callback_data=f"tip:detail:{event_id}:{i - 1}",
        ))
        if len(row) == 5 or i == start + len(page_tips):
            buttons.append(row)
            row = []

    # Pagination row
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"hot:page:{page - 1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"hot:page:{page + 1}"))
    if nav:
        buttons.append(nav)

    # Action buttons
    buttons.append([InlineKeyboardButton("🔄 Refresh", callback_data="hot:go")])
    buttons.append([
        InlineKeyboardButton("⚽ Your Games", callback_data="yg:all:0"),
        InlineKeyboardButton("↩️ Menu", callback_data="nav:main"),
    ])

    return (text, InlineKeyboardMarkup(buttons))


async def _do_hot_tips_flow(chat_id: int, bot) -> None:
    """Core Hot Tips — fetch tips, cache, show first page."""
    import random

    verb = random.choice(LOADING_VERBS)
    loading = await bot.send_message(
        chat_id,
        f"🔥 <i>{verb} across all markets…</i>",
        parse_mode=ParseMode.HTML,
    )

    # Primary: our own scraped data from odds.db (free, fast, always available)
    tips = await _fetch_hot_tips_from_db()

    # Fallback: Odds API if odds.db returned nothing
    if not tips:
        try:
            tips = await _fetch_hot_tips_all_sports()
        except Exception as exc:
            log.warning("Odds API fallback also failed: %s", exc)
            tips = []

    # Store tips in game_tips_cache so tip detail can find them
    for tip in tips:
        eid = tip.get("event_id", "")
        if eid:
            _game_tips_cache[eid] = [tip]

    try:
        await loading.delete()
    except Exception:
        pass

    text, markup = _build_hot_tips_page(tips, page=0)
    await bot.send_message(chat_id, text, parse_mode=ParseMode.HTML, reply_markup=markup)


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
                "<b>Step 8/9: Daily picks notification</b>\n\nWhen do you want your daily tips?",
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
                f"✅ Added <b>{h(text_input)}</b>!",
                parse_mode=ParseMode.HTML,
            )
        return

    # Normal AI chat
    user_msg = update.message.text
    thinking_msg = await update.message.reply_text("🤖 <i>Thinking…</i>", parse_mode=ParseMode.HTML)

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

    # Edit the "Thinking..." message in-place with the response (no stale message)
    try:
        await thinking_msg.edit_text(reply, parse_mode=ParseMode.HTML, reply_markup=kb_nav())
    except Exception:
        # Fallback: delete thinking and send new if edit fails
        try:
            await thinking_msg.delete()
        except Exception:
            pass
        await update.message.reply_text(reply, parse_mode=ParseMode.HTML, reply_markup=kb_nav())


# ── /picks — Today's value bets ───────────────────────────

LOADING_VERBS = [
    "Scanning markets", "Crunching numbers", "Hunting value",
    "Analysing odds", "Finding edges",
]


async def cmd_picks(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Legacy /picks → redirects to Hot Tips."""
    await _show_hot_tips(update, ctx, update.effective_user.id)


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

    # Final footer with navigation
    await bot.send_message(
        chat_id,
        f"<i>{len(picks)} tips found.</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=kb_nav(),
    )


# ── /schedule — Upcoming games ───────────────────────────

async def cmd_schedule(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Legacy /schedule → redirects to Your Games."""
    user_id = update.effective_user.id
    db_user = await db.get_user(user_id)

    if not db_user or not db_user.onboarding_done:
        await update.message.reply_text(
            "🏟️ Complete your profile first!\n\nUse /start to get set up.",
            parse_mode=ParseMode.HTML,
        )
        return

    await _show_your_games(update, ctx, user_id)


async def _fetch_schedule_games(user_id: int) -> list[dict]:
    """Fetch and cache schedule events for a user. Returns sorted event list."""
    from scripts.sports_data import fetch_events_for_league

    prefs = await db.get_user_sport_prefs(user_id)
    user_teams: set[str] = set()
    league_keys: set[str] = set()
    for pref in prefs:
        if pref.team_name:
            user_teams.add(pref.team_name.lower())
        if pref.league:
            league_keys.add(pref.league)

    all_events: list[dict] = []
    for lk in league_keys:
        # Skip leagues without an Odds API key — no data to fetch
        if not config.SPORTS_MAP.get(lk):
            continue
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

    all_events.sort(key=lambda e: e.get("commence_time", ""))
    # Cache for pagination
    _schedule_cache[user_id] = all_events
    return all_events


def _render_schedule_page(
    games: list[dict], user_teams: set[str], page: int = 0,
) -> tuple[str, InlineKeyboardMarkup]:
    """Render a single page of the schedule with pagination."""
    from datetime import datetime as dt_cls
    from zoneinfo import ZoneInfo

    sa_tz = ZoneInfo(config.TZ)

    total_pages = max(1, (len(games) + GAMES_PER_PAGE - 1) // GAMES_PER_PAGE)
    page = max(0, min(page, total_pages - 1))

    start = page * GAMES_PER_PAGE
    end = start + GAMES_PER_PAGE
    page_games = games[start:end]

    today = dt_cls.now(sa_tz).date()
    tomorrow = today + __import__("datetime").timedelta(days=1)

    lines = [f"📅 <b>Upcoming Games ({len(games)})</b>\n"]
    current_date_str = None

    for idx, event in enumerate(page_games, start + 1):
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

        home_raw = event.get("home_team", "?")
        away_raw = event.get("away_team", "?")
        home = h(home_raw)
        away = h(away_raw)
        emoji = event.get("sport_emoji", "🏅")
        hf, af = _get_flag_prefixes(home_raw, away_raw)
        home_display = f"<b>{hf}{home}</b>" if home.lower() in user_teams else f"{hf}{home}"
        away_display = f"<b>{af}{away}</b>" if away.lower() in user_teams else f"{af}{away}"
        lines.append(f"<b>[{idx}]</b> {emoji} {event_time}  {home_display} vs {away_display}")

    text = "\n".join(lines)

    buttons: list[list[InlineKeyboardButton]] = []
    for i, event in enumerate(page_games, start + 1):
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

    # Pagination row — only show if more than one page
    if total_pages > 1:
        nav_row: list[InlineKeyboardButton] = []
        if page > 0:
            nav_row.append(InlineKeyboardButton(
                "⬅️ Prev", callback_data=f"schedule:page:{page - 1}",
            ))
        nav_row.append(InlineKeyboardButton(
            f"📄 {page + 1}/{total_pages}", callback_data="schedule:noop",
        ))
        if page < total_pages - 1:
            nav_row.append(InlineKeyboardButton(
                "Next ➡️", callback_data=f"schedule:page:{page + 1}",
            ))
        buttons.append(nav_row)

    buttons.append([InlineKeyboardButton("↩️ Menu", callback_data="nav:main")])

    return text, InlineKeyboardMarkup(buttons)


async def _build_schedule(user_id: int, page: int = 0) -> tuple[str, InlineKeyboardMarkup]:
    """Shared schedule logic for command + callback. Returns (text, markup)."""
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

    games = await _fetch_schedule_games(user_id)

    if not games:
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

    return _render_schedule_page(games, user_teams, page=page)


# ── Schedule pagination ───────────────────────────────────
GAMES_PER_PAGE = 5

# Cache for schedule games per user (user_id → list of event dicts)
_schedule_cache: dict[int, list[dict]] = {}

# Cache for game tips (event_id → list of tip dicts)
_game_tips_cache: dict[str, list[dict]] = {}

# Cache for full game analysis (event_id → (html, tips, timestamp))
# TTL: 1 hour. Avoids re-calling Claude on "Back to Game" navigation.
_ANALYSIS_CACHE_TTL = 3600
_analysis_cache: dict[str, tuple[str, list[dict], float]] = {}

GAME_ANALYSIS_PROMPT = textwrap.dedent("""\
    You are MzansiEdge, a sharp South African sports betting analyst with deep knowledge
    of form, matchups, and market dynamics. Given odds and probability data for an
    upcoming match, write a punchy ~150-word analysis using these EXACT section headers:

    📋 <b>The Setup</b>
    Recent form, key injuries/absences, head-to-head record, and venue factor.
    Mention specific stats where relevant (win streak, clean sheets, scoring form).

    🎯 <b>The Edge</b>
    Where the value is. Be specific about WHICH outcome and WHY the market has
    mispriced it. Reference the probability gap between fair odds and market odds.
    If there's no clear edge, say so honestly.

    ⚠️ <b>The Risk</b>
    One or two sentences on what could derail this pick. Be specific — name the
    scenario (e.g. key player rested, weather, fixture congestion).

    🏆 <b>Verdict</b>
    One bold sentence: your top pick. Do NOT include conviction levels (High/Medium/Low).
    The Edge Rating badge handles confidence display — never mention conviction.

    Rules:
    - Telegram HTML only (<b>, <i> tags)
    - Do NOT include odds numbers or bookmaker names (shown separately below)
    - No disclaimers, no "gamble responsibly" — we handle that elsewhere
    - Be direct, confident, conversational — like a mate at the braai who knows his stuff
    - South African tone: use "edge", "value", "sharp", "lekker"
    - Sport-specific language: "clean sheet" for soccer, "try line" for rugby, "strike rate" for cricket
    - If the data is thin, keep it shorter — don't pad with generic filler
""")


async def _generate_game_tips(query, ctx, event_id: str, user_id: int) -> None:
    """Generate AI betting tips for a specific game."""
    import time as _time
    from datetime import datetime as dt_cls
    from scripts.sports_data import fetch_events_for_league
    from scripts.odds_client import fetch_odds_cached, fair_probabilities, find_best_sa_odds, calculate_ev

    # ── Check analysis cache first (1-hour TTL) ──
    cached = _analysis_cache.get(event_id)
    if cached:
        cached_msg, cached_tips, cached_ts = cached
        if _time.time() - cached_ts < _ANALYSIS_CACHE_TTL:
            _game_tips_cache[event_id] = cached_tips
            buttons = _build_game_buttons(cached_tips, event_id, user_id)
            await query.edit_message_text(
                cached_msg, parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(buttons),
            )
            return

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

    home_raw = target_event.get("home_team", "?")
    away_raw = target_event.get("away_team", "?")
    home = h(home_raw)
    away = h(away_raw)
    hf, af = _get_flag_prefixes(home_raw, away_raw)

    await query.edit_message_text(
        f"🤖 <i>Analysing {hf}{home} vs {af}{away}…</i>",
        parse_mode=ParseMode.HTML,
    )

    # Try odds.db first (local scrapers — no API quota cost)
    tips: list[dict] = []
    commence_time = target_event.get("commence_time", "")
    db_match_id = odds_svc.build_match_id(home, away, commence_time)
    db_match = None
    if db_match_id:
        try:
            db_match = await odds_svc.get_best_odds(db_match_id, "1x2")
        except Exception:
            db_match = None

    if db_match and db_match.get("outcomes"):
        # Build tips from odds.db data
        for outcome_key, outcome_data in db_match["outcomes"].items():
            all_bk = outcome_data.get("all_bookmakers", {})
            if not all_bk:
                continue
            best_price = outcome_data.get("best_odds", 0)
            best_bk_key = outcome_data.get("best_bookmaker", "")
            # Compute consensus prob from all bookmakers
            implied_probs = [1.0 / o for o in all_bk.values() if o and o > 1]
            if not implied_probs:
                continue
            fair_prob = sum(implied_probs) / len(implied_probs)
            ev_pct = round((fair_prob * best_price - 1) * 100, 1) if best_price > 0 else 0
            _outcome_labels = {"home": home, "away": away, "draw": "Draw"}
            tips.append({
                "outcome": _outcome_labels.get(outcome_key, outcome_key),
                "odds": best_price,
                "bookie": _display_bookmaker_name(best_bk_key),
                "bookie_key": best_bk_key,
                "ev": ev_pct,
                "prob": round(fair_prob * 100),
                "event_id": event_id,
                "home_team": home,
                "away_team": away,
                "match_id": db_match_id,
                "odds_by_bookmaker": dict(all_bk),
            })

    # Fallback to Odds API if odds.db had no data
    if not tips:
        api_key = config.SPORTS_MAP.get(target_league)
        if api_key:
            odds_result = await fetch_odds_cached(api_key, regions="eu,uk,au", markets="h2h")
            if odds_result["ok"]:
                event_odds = None
                for ev in (odds_result["data"] or []):
                    if ev.get("id") == event_id:
                        event_odds = ev
                        break
                if event_odds and event_odds.get("bookmakers"):
                    fair_probs = fair_probabilities(event_odds)
                    best_entries = find_best_sa_odds(event_odds)
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

    # Sort and cache tips if we have any
    if tips:
        tips.sort(key=lambda t: t["ev"], reverse=True)
    _game_tips_cache[event_id] = tips

    # Parse kickoff time (needed for AI call regardless of odds)
    try:
        ct = dt_cls.fromisoformat(target_event["commence_time"].replace("Z", "+00:00"))
        kickoff = ct.strftime("%a %d %b, %H:%M")
    except Exception:
        kickoff = "TBC"

    # Build odds context for Claude
    if tips:
        odds_context = "\n".join(
            f"- {t['outcome']}: {t['odds']:.2f} ({t['bookie']}), "
            f"fair prob {t['prob']}%, EV {t['ev']:+.1f}%"
            for t in tips
        )
    else:
        odds_context = (
            "No odds data available for this match yet. "
            "Provide general analysis based on what you know about these teams."
        )

    # Get AI narrative — always call regardless of odds availability
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

    # ── Inject Edge Rating badge into Verdict header ──
    if narrative and tips:
        # Compute edge tier for the best positive-EV tip
        best_ev = max((t["ev"] for t in tips), default=0)
        if best_ev > 0:
            # EV-based tier assignment (recalibrated Wave 14A)
            if best_ev >= 15:
                tier = EdgeRating.DIAMOND
            elif best_ev >= 8:
                tier = EdgeRating.GOLD
            elif best_ev >= 4:
                tier = EdgeRating.SILVER
            else:
                tier = EdgeRating.BRONZE
            tier_emoji = EDGE_EMOJIS.get(tier, "")
            tier_label = EDGE_LABELS.get(tier, "")
            if tier_emoji and tier_label:
                badge = f" — {tier_emoji} {tier_label}"
                # Replace "🏆 Verdict" or "🏆 <b>Verdict</b>" with badge version
                import re
                narrative = re.sub(
                    r"(🏆\s*(?:<b>)?Verdict(?:</b>)?)",
                    rf"\1{badge}",
                    narrative,
                    count=1,
                )
    # Strip ALL conviction text from any AI response (replaced by Edge Rating badge)
    if narrative:
        import re
        narrative = re.sub(r"(?:with |— )?(?:High|Medium|Low) conviction:?\.?", "", narrative)
        narrative = re.sub(r"Conviction: (?:High|Medium|Low)\.?", "", narrative)
        narrative = re.sub(r"\s{2,}", " ", narrative)  # collapse double spaces from stripping

    # Build message — AI narrative first, then odds
    lines = [
        f"🎯 <b>{hf}{home} vs {af}{away}</b>",
        f"⏰ {kickoff}\n",
    ]

    if narrative:
        lines.append(narrative)
        lines.append("")

    if tips:
        # Show bookmaker odds section
        if db_match and db_match.get("outcomes"):
            lines.append("<b>SA Bookmaker Odds:</b>")
        else:
            lines.append(f"<b>{config.get_active_display_name()} Odds:</b>")
        for tip in tips:
            ev_ind = f"+{tip['ev']}%" if tip["ev"] > 0 else f"{tip['ev']}%"
            value_marker = " 💰" if tip["ev"] > 2 else ""
            lines.append(
                f"  {h(tip['outcome'])}: <b>{tip['odds']:.2f}</b> ({h(tip['bookie'])})\n"
                f"    {tip['prob']}% · EV: {ev_ind}{value_marker}"
            )
    else:
        lines.append("No SA bookmaker odds available for this match yet.")
        lines.append("Check back closer to kickoff for odds!")

    msg = "\n".join(lines)

    # ── Cache the full analysis (1-hour TTL) ──
    _analysis_cache[event_id] = (msg, tips, _time.time())

    # Build simplified buttons (North Star: 4 buttons max)
    buttons = _build_game_buttons(tips, event_id, user_id)

    await query.edit_message_text(
        msg, parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


def _build_game_buttons(
    tips: list[dict], event_id: str, user_id: int,
) -> list[list[InlineKeyboardButton]]:
    """Build simplified game breakdown buttons (North Star: recommend, compare, nav)."""
    buttons: list[list[InlineKeyboardButton]] = []

    if tips:
        # Button 1: Recommended bet CTA — highest positive-EV outcome
        best_ev_tip = max(
            (t for t in tips if t["ev"] > 0),
            key=lambda t: t["ev"],
            default=None,
        )
        if best_ev_tip:
            odds_by_bk = best_ev_tip.get("odds_by_bookmaker", {})
            match_id = best_ev_tip.get("match_id", "")
            best_bk = select_best_bookmaker(odds_by_bk, user_id, match_id) if odds_by_bk else {}

            # Determine edge tier for badge (recalibrated Wave 14A)
            ev = best_ev_tip["ev"]
            if ev >= 15:
                tier = EdgeRating.DIAMOND
            elif ev >= 8:
                tier = EdgeRating.GOLD
            elif ev >= 4:
                tier = EdgeRating.SILVER
            elif ev >= 1:
                tier = EdgeRating.BRONZE
            else:
                tier = EdgeRating.BRONZE
            tier_emoji = EDGE_EMOJIS.get(tier, "")

            bk_name = (best_bk or {}).get("bookmaker_name", config.get_active_display_name())
            aff_url = (best_bk or {}).get("affiliate_url", "") or config.get_affiliate_url(event_id)
            outcome = best_ev_tip["outcome"]
            odds_val = best_ev_tip["odds"]

            cta_text = f"{tier_emoji} Back {outcome} @ {odds_val:.2f} on {bk_name} →"
            if aff_url:
                buttons.append([InlineKeyboardButton(cta_text, url=aff_url)])
            else:
                buttons.append([InlineKeyboardButton(cta_text, callback_data="tip:affiliate_soon")])
        else:
            # No positive EV — generic fallback
            active_bk = config.get_active_bookmaker()
            bk_url = config.get_affiliate_url(event_id) or active_bk.get("website_url", "")
            buttons.append([InlineKeyboardButton(
                f"📲 View odds on {active_bk['short_name']} →", url=bk_url,
            )])

        # Button 2: Compare All Odds (only when multi-bookmaker data exists)
        has_multi_bk = any(t.get("odds_by_bookmaker") for t in tips)
        if has_multi_bk:
            buttons.append([InlineKeyboardButton(
                "📊 Compare All Odds", callback_data=f"odds:compare:{event_id}",
            )])

    # Buttons 3-4: Navigation
    buttons.append([InlineKeyboardButton("↩️ Back to Your Games", callback_data="yg:all:0")])
    buttons.append([InlineKeyboardButton("↩️ Menu", callback_data="nav:main")])

    return buttons


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
                [InlineKeyboardButton("↩️ Back to Your Games", callback_data="yg:all:0")],
            ]),
        )
        return

    tip = tips[tip_idx]
    user_id = query.from_user.id
    db_user = await db.get_user(user_id)
    experience = (db_user.experience_level if db_user else None) or "casual"
    bankroll = getattr(db_user, "bankroll", None) if db_user else None
    analytics_track(user_id, "tip_viewed", {
        "sport": tip.get("sport_key", ""),
        "match": f"{tip.get('home_team', '?')} vs {tip.get('away_team', '?')}",
        "outcome": tip.get("outcome", ""),
        "ev": tip.get("ev", 0),
    })

    # Check if tip already has multi-bookmaker data (DB-sourced tips)
    pre_fetched_odds = tip.get("odds_by_bookmaker", {})
    # Use stored match_id for DB tips, otherwise build from team names
    match_id = tip.get("match_id", "") or odds_svc.build_match_id(
        tip.get("home_team", ""), tip.get("away_team", ""),
        tip.get("commence_time", ""),
    )

    if pre_fetched_odds:
        # DB path: use pre-fetched odds, query DB only for freshness timestamp
        odds_by_bookmaker = pre_fetched_odds
        odds_result = await odds_svc.get_best_odds(match_id, "1x2") if match_id else {}
    else:
        # Legacy API path: query scrapers DB for multi-bookmaker data
        odds_result = await odds_svc.get_best_odds(match_id, "1x2") if match_id else {}
        outcome_key = tip.get("outcome", "").lower()
        _oc_map = {"home team": "home", "away team": "away", "draw": "draw"}
        mapped_key = _oc_map.get(outcome_key, outcome_key)
        outcome_data = odds_result.get("outcomes", {}).get(mapped_key, {})
        odds_by_bookmaker = outcome_data.get("all_bookmakers", {})

    if odds_by_bookmaker:
        # Multi-bookmaker: select best odds with affiliate link
        best_bk = select_best_bookmaker(odds_by_bookmaker, user_id, match_id)
        runner_ups = get_runner_up_odds(odds_by_bookmaker, best_bk.get("bookmaker_key", ""))
        edge = tip.get("display_tier", tip.get("edge_rating", ""))

        # Use edge renderer for rich tip card
        text = render_tip_with_odds(
            match=tip,
            odds_by_bookmaker=odds_by_bookmaker,
            edge_rating=edge,
            best_bookmaker=best_bk,
            runner_ups=runner_ups,
            predicted_outcome=tip.get("outcome", ""),
        )

        # AI narrative explaining why this tip has value
        narrative = _build_tip_narrative(tip)
        text += f"\n\n{narrative}"

        # Smart freshness indicator
        last_updated = odds_result.get("last_updated")
        if last_updated:
            from datetime import datetime, timezone
            try:
                ts = datetime.fromisoformat(last_updated.replace("Z", "+00:00"))
                mins_ago = int((datetime.now(timezone.utc) - ts).total_seconds() / 60)
                text += f"\n\n{_format_freshness(mins_ago)}"
            except (ValueError, TypeError):
                pass
    else:
        # Fallback: single-bookmaker display
        text = _format_tip_detail(tip, experience, bankroll)
        best_bk = None

    buttons: list[list[InlineKeyboardButton]] = []

    if best_bk and best_bk.get("affiliate_url"):
        # Dynamic CTA with best-odds bookmaker
        cta_label = render_tip_button_label(best_bk)
        buttons.append([InlineKeyboardButton(f"📲 {cta_label}", url=best_bk["affiliate_url"])])
    else:
        # Fallback to active bookmaker
        active_bk = config.get_active_bookmaker()
        affiliate_url = active_bk.get("affiliate_base_url", "")
        bk_url = affiliate_url or active_bk.get("website_url", "")
        if bk_url:
            buttons.append([InlineKeyboardButton(
                f"📲 Place on {active_bk['display_name']} →", url=bk_url,
            )])
        else:
            buttons.append([InlineKeyboardButton(
                f"📲 Place on {active_bk['display_name']} →",
                callback_data="tip:affiliate_soon",
            )])

    # Odds comparison button (only if multi-bookmaker data available)
    if odds_by_bookmaker and len(odds_by_bookmaker) > 1:
        buttons.append([InlineKeyboardButton(
            "📊 All Bookmaker Odds",
            callback_data=f"odds:compare:{event_id}",
        )])

    buttons.append([InlineKeyboardButton(
        "🔔 Follow this game",
        callback_data=f"subscribe:{event_id}",
    )])
    buttons.append([InlineKeyboardButton("🔥 Back to Hot Tips", callback_data="hot:back")])
    buttons.append([InlineKeyboardButton("↩️ Menu", callback_data="nav:main")])

    # First-time Edge Rating tooltip (shown once per user)
    db_user = await db.get_user(user_id)
    if db_user and not db_user.edge_tooltip_shown:
        edge = tip.get("display_tier", tip.get("edge_rating", ""))
        if edge:
            text += "\n\nℹ️ <i>New to Edge Ratings? Tap 📖 Guide to learn more.</i>"
            await db.set_edge_tooltip_shown(user_id)

    await query.edit_message_text(
        text, parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def _handle_odds_comparison(query, event_id: str) -> None:
    """Show all bookmaker odds for a match (odds:compare:{event_id})."""
    tips = _game_tips_cache.get(event_id, [])
    if not tips:
        await query.edit_message_text(
            "⚠️ Tip data expired. Try Hot Tips again.",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔥 Hot Tips", callback_data="hot:go")],
            ]),
        )
        return

    tip = tips[0]
    # Use stored match_id for DB tips, otherwise build from team names
    match_id = tip.get("match_id", "") or odds_svc.build_match_id(
        tip.get("home_team", ""), tip.get("away_team", ""),
        tip.get("commence_time", ""),
    )

    home_raw = tip.get("home_team", "")
    away_raw = tip.get("away_team", "")
    home = h(home_raw)
    away = h(away_raw)
    hf, af = _get_flag_prefixes(home_raw, away_raw)

    # Fetch full match data with all outcomes from odds.db
    db_match = await odds_svc.get_best_odds(match_id, "1x2") if match_id else {}
    outcomes = db_match.get("outcomes", {}) if db_match else {}

    if not outcomes:
        await query.answer("No multi-bookmaker data available for this match.", show_alert=True)
        return

    # Build all-markets comparison: Home / Draw / Away
    _outcome_labels = {
        "home": ("🏠", f"{home} (Home Win)"),
        "draw": ("🤝", "Draw"),
        "away": ("🏟️", f"{away} (Away Win)"),
    }
    lines = [
        f"📊 <b>Odds Comparison</b>",
        f"<b>{hf}{home} vs {af}{away}</b>",
        "",
    ]

    for oc_key in ("home", "draw", "away"):
        oc_data = outcomes.get(oc_key)
        if not oc_data:
            continue
        all_bk = oc_data.get("all_bookmakers", {})
        if not all_bk:
            continue
        emoji, label = _outcome_labels.get(oc_key, ("", oc_key))
        lines.append(f"{emoji} <b>{label}</b>")
        sorted_bk = sorted(all_bk.items(), key=lambda x: x[1], reverse=True)
        for i, (bk_key, odds_val) in enumerate(sorted_bk):
            name = _display_bookmaker_name(bk_key)
            marker = "⭐ " if i == 0 else "  "
            lines.append(f"{marker}{name}: <b>{odds_val:.2f}</b>")
        lines.append("")

    text = "\n".join(lines)

    # Build buttons: affiliate link per market (best bookmaker each) + nav
    buttons: list[list[InlineKeyboardButton]] = []

    _aff_labels = {"home": "Home Win", "draw": "Draw", "away": "Away Win"}
    for oc_key in ("home", "draw", "away"):
        oc_data = outcomes.get(oc_key)
        if not oc_data:
            continue
        best_bk_key = oc_data.get("best_bookmaker", "")
        best_odds = oc_data.get("best_odds", 0)
        if not best_bk_key:
            continue
        aff_url = get_affiliate_url(best_bk_key)
        if not aff_url:
            continue
        bk_name = _display_bookmaker_name(best_bk_key)
        label = _aff_labels.get(oc_key, oc_key)
        buttons.append([InlineKeyboardButton(
            f"📲 {bk_name} — Best for {label} →", url=aff_url,
        )])

    buttons.append([InlineKeyboardButton("↩️ Back to Game", callback_data=f"yg:game:{event_id}")])
    buttons.append([InlineKeyboardButton("↩️ Menu", callback_data="nav:main")])

    await query.edit_message_text(
        text, parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


def _format_tip_detail(tip: dict, experience: str, bankroll: float | None) -> str:
    """Format a detailed tip card based on experience level."""
    outcome = h(tip["outcome"])
    odds = tip["odds"]
    ev = tip["ev"]
    prob = tip["prob"]
    home_raw = tip["home_team"]
    away_raw = tip["away_team"]
    home = h(home_raw)
    away = h(away_raw)
    hf, af = _get_flag_prefixes(home_raw, away_raw)
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
            f"📊 <b>Tip Detail: {hf}{home} vs {af}{away}</b>\n\n"
            f"💰 <b>{outcome}</b> @ <b>{odds:.2f}</b> ({bookie})\n"
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
            f"📊 <b>Tip Detail: {hf}{home} vs {af}{away}</b>\n\n"
            f"📋 <b>What's the bet?</b>\n{bet_explain}\n\n"
            f"💵 <b>The odds: {odds:.2f}</b> on {bookie}\n"
            f"  Bet R20 → get <b>R{payout_20:.0f}</b> back\n"
            f"  Bet R50 → get <b>R{payout_50:.0f}</b> back\n\n"
            f"🎯 Our AI gives this a <b>{prob}%</b> chance — "
            f"that's a <b>+{ev}%</b> edge in your favour.\n\n"
            f"🔍 <i>Start small: R20-R50 bets are perfect while learning.</i>"
        )

    else:
        # Casual
        payout_100 = round(odds * 100, 0)
        stake_hint = ""
        if bankroll:
            suggested = round(min(bankroll * 0.05, 200), 0)
            stake_hint = f"\n🔍 Suggested stake: <b>R{suggested:.0f}</b>"
        return (
            f"📊 <b>Tip Detail: {hf}{home} vs {af}{away}</b>\n\n"
            f"💰 We like <b>{outcome}</b> @ {odds:.2f} ({bookie})\n\n"
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
            [InlineKeyboardButton("🔥 Show Me Hot Tips", callback_data="hot:go")],
            [InlineKeyboardButton("⚽ Your Games", callback_data="yg:all:0")],
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
                    f"{icon} <b>{h(t.match)}</b>\n"
                    f"   {h(t.prediction)}"
                    + (f" @ {t.odds:.2f}" if t.odds else "")
                )
                lines.append("")
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
        f"<b>{name} — Our Recommended Bookmaker</b>\n\n"
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
            ("live_scores", "⚡ Live Scores"),
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

        <b>Step 1/9:</b> What's your betting experience?
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
    text = _fav_step_text(sport) if sport else "<b>Step 4/9</b>"
    existing = ob["favourites"].get(sport_key, [])
    await query.edit_message_text(
        text, parse_mode=ParseMode.HTML,
        reply_markup=kb_onboarding_favourites(sport_key, existing),
    )


# ── /admin — admin dashboard with API quota ───────────────

async def cmd_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin-only command showing API quota, odds.db stats, and bot stats."""
    if update.effective_user.id not in config.ADMIN_IDS:
        return

    quota = get_quota()
    db_stats = await odds_svc.get_db_stats()
    count = await db.get_user_count()
    onboarded = await db.get_onboarded_count()
    tips = await db.get_recent_tips(limit=100)
    wins = sum(1 for t in tips if t.result == "win")
    losses = sum(1 for t in tips if t.result == "loss")
    pending = sum(1 for t in tips if t.result is None or t.result == "pending")

    # Format latest scrape time
    latest = db_stats.get("latest_scrape", "N/A")
    if latest and latest != "N/A":
        from datetime import datetime, timezone
        try:
            ts = datetime.fromisoformat(latest.replace("Z", "+00:00"))
            mins_ago = int((datetime.now(timezone.utc) - ts).total_seconds() / 60)
            latest_display = f"{mins_ago} min ago"
        except (ValueError, TypeError):
            latest_display = latest[:19]
    else:
        latest_display = "N/A"

    text = textwrap.dedent(f"""\
        <b>🔧 Admin Dashboard</b>

        <b>📦 Odds Database (PRIMARY)</b>
        📊 Rows: <code>{db_stats['total_rows']:,}</code>
        ⚽ Matches: <code>{db_stats['match_count']}</code>
        🏪 Bookmakers: <code>{db_stats['bookmaker_count']}</code>
        🔄 Last scrape: <code>{latest_display}</code>

        <b>📡 Odds API (fallback)</b>
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


# ── Morning Notification Teasers ──────────────────────────

async def _morning_teaser_job(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Scheduled job: send morning teaser to users whose notification_hour matches now."""
    from datetime import datetime as dt_cls
    from zoneinfo import ZoneInfo

    now = dt_cls.now(ZoneInfo(config.TZ))
    current_hour = now.hour
    log.info("Morning teaser job running for hour=%d (SAST)", current_hour)

    users = await db.get_users_for_notification(current_hour)
    if not users:
        log.info("No users to notify at hour=%d", current_hour)
        return

    # Fetch hot tips once for all users (uses 15-min cache)
    tips = await _fetch_hot_tips_all_sports()

    for user in users:
        try:
            if tips:
                top = tips[0]
                sport_emoji = _get_sport_emoji_for_api_key(top.get("sport_key", ""))
                kickoff = _format_kickoff_display(top["commence_time"])
                thf, taf = _get_flag_prefixes(top.get("home_team", ""), top.get("away_team", ""))
                teaser = (
                    f"☀️ <b>Good morning!</b>\n\n"
                    f"🔥 <b>{len(tips)} value bet{'s' if len(tips) != 1 else ''}</b> found today.\n\n"
                    f"Top pick: {sport_emoji} <b>{thf}{h(top['home_team'])} vs {taf}{h(top['away_team'])}</b>\n"
                    f"💰 {top['outcome']} @ {top['odds']:.2f} · EV +{top['ev']}%\n"
                    f"⏰ {kickoff}\n\n"
                    f"<i>Tap below to see all tips 👇</i>"
                )
            else:
                teaser = (
                    f"☀️ <b>Good morning!</b>\n\n"
                    f"No value bets found yet today — the market is tight.\n"
                    f"Check back later or browse your games!"
                )

            await ctx.bot.send_message(
                chat_id=user.id,
                text=teaser,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔥 See Hot Tips", callback_data="hot:go")],
                    [InlineKeyboardButton("⚽ Your Games", callback_data="yg:all:0")],
                ]),
            )
        except Exception as exc:
            log.warning("Failed to send morning teaser to user %s: %s", user.id, exc)


# ── Subscription (Stitch) ────────────────────────────────


async def _handle_sub_verify(query, payment_id: str) -> None:
    """Verify payment after user clicks 'I've Paid'."""
    user_id = query.from_user.id
    await query.edit_message_text(
        "⏳ <i>Verifying your payment…</i>", parse_mode=ParseMode.HTML,
    )

    try:
        result = await stitch_service.get_payment_status(payment_id)
        status = result.get("status", "")

        if status == "success":
            await db.activate_subscription(user_id, payment_id, "stitch_premium")
            analytics_track(user_id, "subscription_confirmed", {"plan": "premium", "method": "manual_verify"})

            await query.edit_message_text(
                "✅ <b>Payment confirmed!</b>\n\n"
                "Welcome to MzansiEdge Premium! "
                "You now get AI-powered tips daily.",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔥 Hot Tips", callback_data="hot:go")],
                    [InlineKeyboardButton("⚽ Your Games", callback_data="yg:all:0")],
                ]),
            )
        else:
            await query.edit_message_text(
                f"⏳ <b>Payment not yet confirmed</b>\n\n"
                f"Status: <code>{status or 'pending'}</code>\n\n"
                "If you've completed payment, wait a moment and try again.",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 Check Again", callback_data=f"sub:verify:{payment_id}")],
                    [InlineKeyboardButton("↩️ Menu", callback_data="nav:main")],
                ]),
            )
    except Exception as exc:
        log.error("Payment verification error: %s", exc)
        await query.edit_message_text(
            "⚠️ Couldn't verify payment right now. Try again in a moment.",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Try Again", callback_data=f"sub:verify:{payment_id}")],
                [InlineKeyboardButton("↩️ Menu", callback_data="nav:main")],
            ]),
        )


# ConversationHandler state for email collection
SUB_EMAIL = 0

# Per-user state: pending Stitch payment
_subscribe_state: dict[int, dict] = {}


async def cmd_subscribe(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Start subscription flow — check status, then prompt for email."""
    user_id = update.effective_user.id
    db_user = await db.get_user(user_id)

    if db.is_premium(db_user):
        await update.message.reply_text(
            "✅ <b>You're already a MzansiEdge Premium member!</b>\n\n"
            "Your subscription is active. Use /status to see details.",
            parse_mode=ParseMode.HTML,
        )
        return ConversationHandler.END

    text = (
        "💎 <b>MzansiEdge Premium — R49/month</b>\n\n"
        "Unlock daily AI-powered value bets, personalised alerts, "
        "and priority access to new features.\n\n"
        "To subscribe, please enter your <b>email address</b> below.\n"
        "<i>(Used for payment confirmation — never shared.)</i>"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)
    analytics_track(user_id, "subscription_started")
    analytics_track(user_id, "onboarding_subscribe")
    return SUB_EMAIL


async def _receive_email(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Receive email, create Stitch payment, send checkout link."""
    import re
    user_id = update.effective_user.id
    email = update.message.text.strip().lower()

    # Basic email validation
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        await update.message.reply_text(
            "⚠️ That doesn't look like a valid email. Please try again:",
            parse_mode=ParseMode.HTML,
        )
        return SUB_EMAIL

    await db.update_user_email(user_id, email)

    loading = await update.message.reply_text(
        "⏳ <i>Setting up your payment…</i>", parse_mode=ParseMode.HTML,
    )

    try:
        result = await stitch_service.create_payment(user_id)
        payment_url = result["payment_url"]
        payment_id = result["payment_id"]
        reference = result["reference"]
        _subscribe_state[user_id] = {"payment_id": payment_id, "reference": reference, "email": email}

        try:
            await loading.delete()
        except Exception:
            pass

        await update.message.reply_text(
            "💳 <b>Payment Ready!</b>\n\n"
            f"Tap below to complete your R49/month subscription.\n\n"
            f"<i>Reference: <code>{reference}</code></i>",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💳 Pay Now →", url=payment_url)],
                [InlineKeyboardButton("✅ I've Paid — Verify", callback_data=f"sub:verify:{payment_id}")],
                [InlineKeyboardButton("❌ Cancel", callback_data="sub:cancel")],
            ]),
        )
    except Exception as exc:
        log.error("Stitch payment init error: %s", exc)
        try:
            await loading.delete()
        except Exception:
            pass
        await update.message.reply_text(
            "⚠️ Something went wrong setting up payment. Please try again later.",
            parse_mode=ParseMode.HTML,
        )

    return ConversationHandler.END


async def cmd_subscribe_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel subscription flow."""
    await update.message.reply_text("❌ Subscription cancelled.", parse_mode=ParseMode.HTML)
    return ConversationHandler.END


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Show subscription status."""
    user_id = update.effective_user.id
    db_user = await db.get_user(user_id)

    if db.is_premium(db_user):
        started = ""
        if db_user.subscription_started_at:
            started = f"\n📅 Member since: <b>{db_user.subscription_started_at.strftime('%d %b %Y')}</b>"
        await update.message.reply_text(
            f"💎 <b>MzansiEdge Premium</b>\n\n"
            f"Status: ✅ <b>Active</b>{started}\n"
            f"Plan: R49/month\n\n"
            f"You're getting full access to AI-powered tips and alerts.",
            parse_mode=ParseMode.HTML,
        )
    else:
        await update.message.reply_text(
            "💎 <b>MzansiEdge Premium</b>\n\n"
            "Status: ❌ <b>Not subscribed</b>\n\n"
            "Use /subscribe to get started — R49/month.",
            parse_mode=ParseMode.HTML,
        )


# ── Webhook handler (aiohttp) ────────────────────────────

async def _run_webhook_server(app_instance) -> None:
    """Start a small aiohttp server to receive Stitch webhooks."""
    from aiohttp import web

    async def handle_stitch_webhook(request: web.Request) -> web.Response:
        body = await request.read()
        headers = dict(request.headers)

        if not stitch_service.verify_webhook(headers, body):
            log.warning("Invalid Stitch webhook signature")
            return web.Response(status=400)

        event = stitch_service.parse_webhook_event(body)
        event_type = event.get("type", "")
        data = event.get("data", {})

        log.info("Stitch webhook: %s", event_type)

        if event_type == "payment.complete":
            payment_id = data.get("id", "")
            external_ref = data.get("externalReference", "")

            # externalReference is the Telegram user_id (set during create_payment)
            user_id = int(external_ref) if external_ref and external_ref.isdigit() else None

            if user_id:
                await db.activate_subscription(user_id, payment_id, "stitch_premium")
                analytics_track(user_id, "subscription_confirmed", {"plan": "premium"})
                try:
                    await app_instance.bot.send_message(
                        chat_id=user_id,
                        text=(
                            "✅ <b>Welcome to MzansiEdge Premium!</b>\n\n"
                            "Your subscription is now active. "
                            "You get AI-powered tips daily.\n\n"
                            "Use 🔥 <b>Hot Tips</b> to see today's value bets!"
                        ),
                        parse_mode=ParseMode.HTML,
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("🔥 Hot Tips", callback_data="hot:go")],
                            [InlineKeyboardButton("⚽ Your Games", callback_data="yg:all:0")],
                        ]),
                    )
                except Exception as exc:
                    log.warning("Failed to notify user %s of subscription: %s", user_id, exc)

        elif event_type == "payment.cancelled":
            external_ref = data.get("externalReference", "")
            user_id = int(external_ref) if external_ref and external_ref.isdigit() else None
            if user_id:
                await db.deactivate_subscription(user_id)
                analytics_track(user_id, "subscription_cancelled", {"plan": "premium"})

        return web.Response(status=200, text="OK")

    webhook_app = web.Application()
    webhook_app.router.add_post("/webhook/stitch", handle_stitch_webhook)

    runner = web.AppRunner(webhook_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8443)
    await site.start()
    log.info("Stitch webhook server listening on port 8443")


# ── Main ──────────────────────────────────────────────────

def _seconds_until_next_hour() -> float:
    """Calculate seconds until the next whole hour (SAST)."""
    from datetime import datetime as dt_cls
    from zoneinfo import ZoneInfo
    now = dt_cls.now(ZoneInfo(config.TZ))
    seconds_past = now.minute * 60 + now.second
    return max(3600 - seconds_past, 60)  # at least 60s buffer


async def _post_init(app_instance) -> None:
    """Run on bot startup: init DB, publish guides, register commands, schedule jobs."""
    await db.init_db()

    # Pre-publish Betway Telegra.ph guide and wire URL into config
    try:
        from scripts.telegraph_guides import ensure_active_guide
        await ensure_active_guide()
    except Exception as exc:
        log.warning("Could not pre-publish guide: %s", exc)

    # Schedule morning teaser notifications — runs every hour on the hour
    # Checks SAST hour against each user's preferred notification_hour
    from datetime import time as dt_time
    job_queue = app_instance.job_queue
    if job_queue:
        job_queue.run_repeating(
            _morning_teaser_job,
            interval=3600,  # every hour
            first=_seconds_until_next_hour(),
            name="morning_teaser",
        )
        log.info("Scheduled morning teaser job (runs hourly)")

    # Start webhook listener for Stitch payment notifications
    if config.STITCH_CLIENT_ID or config.STITCH_MOCK_MODE:
        try:
            await _run_webhook_server(app_instance)
        except Exception as exc:
            log.warning("Webhook server failed to start: %s", exc)

    await app_instance.bot.set_my_commands([
        ("start", "Start the bot"),
        ("menu", "Main menu"),
        ("picks", "Hot tips — best value bets"),
        ("schedule", "Your games — personalised schedule"),
        ("subscribe", "Subscribe to Premium"),
        ("status", "Subscription status"),
        ("help", "How to use MzansiEdge"),
        ("settings", "Your preferences"),
    ])


def _acquire_pid_lock(path: str = "/tmp/mzansiedge.pid") -> None:
    """Ensure only one bot instance runs at a time via PID file lock."""
    import atexit
    import signal

    if os.path.exists(path):
        try:
            old_pid = int(open(path).read().strip())
            os.kill(old_pid, 0)  # check if process is alive
            log.error("Another instance is already running (PID %d). Exiting.", old_pid)
            raise SystemExit(1)
        except (ProcessLookupError, ValueError):
            # Stale PID file — previous process is dead
            log.warning("Removing stale PID file (PID was %s).", open(path).read().strip())
        except PermissionError:
            log.error("Permission denied checking PID file at %s. Exiting.", path)
            raise SystemExit(1)

    try:
        with open(path, "w") as f:
            f.write(str(os.getpid()))
    except PermissionError:
        log.error("Permission denied writing PID file at %s. Exiting.", path)
        raise SystemExit(1)

    def _cleanup_pid() -> None:
        try:
            os.remove(path)
        except FileNotFoundError:
            pass

    atexit.register(_cleanup_pid)

    def _signal_handler(signum: int, _frame: object) -> None:
        _cleanup_pid()
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)


def main() -> None:
    _acquire_pid_lock()
    log.info("Starting MzansiEdge bot…")
    app = Application.builder().token(config.BOT_TOKEN).build()

    # Initialise DB + register commands on startup
    app.post_init = _post_init

    # Subscribe conversation handler (must be before general command handlers)
    subscribe_conv = ConversationHandler(
        entry_points=[CommandHandler("subscribe", cmd_subscribe)],
        states={
            SUB_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, _receive_email)],
        },
        fallbacks=[CommandHandler("cancel", cmd_subscribe_cancel)],
    )
    app.add_handler(subscribe_conv)

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
    app.add_handler(CommandHandler("status", cmd_status))

    # Callback query handler (prefix:action routing)
    app.add_handler(CallbackQueryHandler(on_button))

    # Persistent reply keyboard taps (must be BEFORE freetext_handler)
    _kb_pattern = r"^(⚽ Your Games|🔥 Hot Tips|📖 Guide|👤 Profile|⚙️ Settings|❓ Help|🔴 Live Games|📊 My Stats|📖 Betway Guide|🎯 Today's Picks|📅 Schedule)$"
    app.add_handler(MessageHandler(filters.Regex(_kb_pattern), handle_keyboard_tap))

    # Free-text chat (also handles favourite input during onboarding)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, freetext_handler))

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
