#!/usr/bin/env python3
"""PaulSportSA — AI-powered sports betting Telegram bot for South Africa."""

from __future__ import annotations

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
from scripts.odds_client import fetch_odds, format_odds_message

logging.basicConfig(
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("paulsportsza")

claude = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)

# ── Onboarding state machine ─────────────────────────────
# Steps: sports → leagues → teams → risk → notify → summary
ONBOARD_STEPS = ("sports", "leagues", "teams", "risk", "notify", "summary")

# Per-user in-memory onboarding state
_onboarding_state: dict[int, dict] = {}


def _get_ob(user_id: int) -> dict:
    """Get or create onboarding state for a user."""
    if user_id not in _onboarding_state:
        _onboarding_state[user_id] = {
            "step": "sports",
            "selected_sports": [],
            "selected_leagues": {},   # sport_key → [league, ...]
            "teams": {},              # sport_key → team_name
            "risk": None,
            "notify_hour": None,
        }
    return _onboarding_state[user_id]


# ── Keyboards ─────────────────────────────────────────────

MAIN_MENU_KB = InlineKeyboardMarkup(
    [
        [
            InlineKeyboardButton("⚽ Soccer/PSL", callback_data="sport:psl"),
            InlineKeyboardButton("🏉 Rugby", callback_data="sport:urc"),
        ],
        [
            InlineKeyboardButton("🏏 Cricket", callback_data="sport:csa_cricket"),
            InlineKeyboardButton("📊 All Odds", callback_data="sport:all"),
        ],
        [
            InlineKeyboardButton("🤖 AI Tip", callback_data="ai:tip"),
            InlineKeyboardButton("📜 History", callback_data="menu:history"),
        ],
        [
            InlineKeyboardButton("ℹ️ Help", callback_data="menu:help"),
        ],
    ]
)


def back_button(target: str = "menu:home") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("« Back", callback_data=target)]]
    )


def kb_onboarding_sports(selected: list[str] | None = None) -> InlineKeyboardMarkup:
    """Two-tier sport selection keyboard: SA first, then Global."""
    selected = selected or []
    rows: list[list[InlineKeyboardButton]] = []

    # SA header
    rows.append([InlineKeyboardButton("── 🇿🇦 South African Sports ──", callback_data="noop:header")])
    sa_row: list[InlineKeyboardButton] = []
    for s in config.SA_SPORTS:
        tick = "✅ " if s.key in selected else ""
        sa_row.append(InlineKeyboardButton(f"{tick}{s.emoji} {s.label}", callback_data=f"ob_sport:{s.key}"))
        if len(sa_row) == 2:
            rows.append(sa_row)
            sa_row = []
    if sa_row:
        rows.append(sa_row)

    # Global header
    rows.append([InlineKeyboardButton("── 🌍 Global Sports ──", callback_data="noop:header")])
    gl_row: list[InlineKeyboardButton] = []
    for s in config.GLOBAL_SPORTS:
        tick = "✅ " if s.key in selected else ""
        gl_row.append(InlineKeyboardButton(f"{tick}{s.emoji} {s.label}", callback_data=f"ob_sport:{s.key}"))
        if len(gl_row) == 2:
            rows.append(gl_row)
            gl_row = []
    if gl_row:
        rows.append(gl_row)

    # Done button
    if selected:
        rows.append([InlineKeyboardButton("✅ Done — Next step »", callback_data="ob_nav:sports_done")])

    return InlineKeyboardMarkup(rows)


def kb_onboarding_leagues(sport_key: str, selected: list[str] | None = None) -> InlineKeyboardMarkup:
    """League selection for a specific sport."""
    selected = selected or []
    sport = config.ALL_SPORTS.get(sport_key)
    if not sport:
        return back_button("ob_nav:back_sports")

    rows: list[list[InlineKeyboardButton]] = []
    for league in sport.leagues:
        tick = "✅ " if league in selected else ""
        rows.append([InlineKeyboardButton(f"{tick}{league}", callback_data=f"ob_league:{sport_key}:{league}")])

    rows.append([
        InlineKeyboardButton("« Back", callback_data="ob_nav:back_sports"),
        InlineKeyboardButton("Next »", callback_data=f"ob_nav:league_done:{sport_key}"),
    ])
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


def kb_onboarding_team_skip(sport_key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⏭ Skip", callback_data=f"ob_team_skip:{sport_key}")],
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
        await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=MAIN_MENU_KB)
    else:
        # Start onboarding
        _onboarding_state.pop(user.id, None)  # reset
        ob = _get_ob(user.id)
        ob["step"] = "sports"
        text = textwrap.dedent(f"""\
            <b>🇿🇦 Welcome to PaulSportSA, {user.first_name}!</b>

            Let's set up your profile in a few quick steps.

            <b>Step 1/6:</b> Which sports do you follow?
            Tap to select, then hit <b>Done</b>.
        """)
        await update.message.reply_text(
            text, parse_mode=ParseMode.HTML,
            reply_markup=kb_onboarding_sports(),
        )


# ── /menu ────────────────────────────────────────────────

async def cmd_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    text = textwrap.dedent(f"""\
        <b>🇿🇦 PaulSportSA — Main Menu</b>

        Hey {user.first_name}, pick a sport or get an AI tip.
    """)
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=MAIN_MENU_KB)


# ── /help ─────────────────────────────────────────────────

HELP_TEXT = textwrap.dedent("""\
    <b>PaulSportSA — Help</b>

    <b>Commands</b>
    /start — Onboarding / Main menu
    /menu — Main menu
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
    await update.message.reply_text(HELP_TEXT, parse_mode=ParseMode.HTML, reply_markup=back_button())


# ── /odds ─────────────────────────────────────────────────

async def cmd_odds(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for s in config.SA_SPORTS + config.GLOBAL_SPORTS:
        if s.api_key:
            row.append(InlineKeyboardButton(f"{s.emoji} {s.label}", callback_data=f"sport:{s.key}"))
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
    for s in config.SA_SPORTS + config.GLOBAL_SPORTS:
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
    elif prefix == "ob_team_skip":
        await handle_ob_team_skip(query, action)
    elif prefix == "ob_done":
        await handle_ob_done(query)
    else:
        await query.edit_message_text("Unknown action.", parse_mode=ParseMode.HTML)


# ── Menu handlers ─────────────────────────────────────────

async def handle_menu(query, action: str) -> None:
    if action == "home":
        user = query.from_user
        text = textwrap.dedent(f"""\
            <b>🇿🇦 PaulSportSA — Main Menu</b>

            Hey {user.first_name}, pick a sport or get an AI tip.
        """)
        await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=MAIN_MENU_KB)

    elif action == "help":
        await query.edit_message_text(HELP_TEXT, parse_mode=ParseMode.HTML, reply_markup=back_button())

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
        await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=back_button())


# ── Sport / odds handlers ────────────────────────────────

async def handle_sport(query, action: str) -> None:
    if action == "all":
        parts = []
        for key, api_key in config.SPORTS_MAP.items():
            sport = config.ALL_SPORTS.get(key)
            label = sport.label.upper() if sport else key.upper()
            try:
                events = await fetch_odds(api_key)
                parts.append(format_odds_message(events, label))
            except Exception:
                parts.append(f"<b>{label}</b>\n⚠️ Could not fetch odds.\n")
        text = "\n\n".join(parts) if parts else "No odds available."
    else:
        sport = config.ALL_SPORTS.get(action)
        if not sport or not sport.api_key:
            await query.edit_message_text(
                f"⚠️ Odds not available for <b>{action}</b> right now.",
                parse_mode=ParseMode.HTML, reply_markup=back_button(),
            )
            return
        try:
            events = await fetch_odds(sport.api_key)
            text = format_odds_message(events, sport.label.upper())
        except Exception as exc:
            log.error("Odds fetch error for %s: %s", action, exc)
            text = f"⚠️ Could not fetch <b>{sport.label}</b> odds. Try again later."

    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=back_button())


# ── AI tip handler ────────────────────────────────────────

SYSTEM_PROMPT = textwrap.dedent("""\
    You are PaulSportSA, an expert South African sports betting analyst.
    Given live odds data, provide a concise betting tip. Include:
    - The recommended bet (team/outcome)
    - Why it has value
    - A suggested stake level (low / medium / high confidence)
    Format your answer in Telegram HTML (use <b>, <i>, <code> tags).
    Keep it under 300 words. End with a responsible-gambling reminder.
""")


async def handle_ai(query, action: str) -> None:
    sport_key = action if action != "tip" else "epl"
    sport = config.ALL_SPORTS.get(sport_key)
    api_key = sport.api_key if sport else None

    await query.edit_message_text("🤖 <i>Analysing odds…</i>", parse_mode=ParseMode.HTML)

    odds_context = ""
    if api_key:
        try:
            events = await fetch_odds(api_key)
            label = sport.label.upper() if sport else sport_key.upper()
            odds_context = format_odds_message(events, label)
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

    await query.edit_message_text(tip_text, parse_mode=ParseMode.HTML, reply_markup=back_button())


# ── Onboarding handlers ──────────────────────────────────

async def handle_ob_sport(query, sport_key: str) -> None:
    """Toggle a sport selection during onboarding."""
    user_id = query.from_user.id
    ob = _get_ob(user_id)

    if sport_key in ob["selected_sports"]:
        ob["selected_sports"].remove(sport_key)
    else:
        ob["selected_sports"].append(sport_key)

    text = textwrap.dedent("""\
        <b>Step 1/6: Select your sports</b>

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
        # Move to leagues — show first sport
        ob["step"] = "leagues"
        ob["_league_idx"] = 0
        sport_key = ob["selected_sports"][0]
        sport = config.ALL_SPORTS.get(sport_key)
        label = sport.label if sport else sport_key
        text = f"<b>Step 2/6: Select leagues for {sport.emoji} {label}</b>\n\nTap to toggle."
        await query.edit_message_text(
            text, parse_mode=ParseMode.HTML,
            reply_markup=kb_onboarding_leagues(sport_key),
        )

    elif action == "back_sports":
        ob["step"] = "sports"
        text = "<b>Step 1/6: Select your sports</b>\n\nTap to toggle. Hit <b>Done</b> when ready."
        await query.edit_message_text(
            text, parse_mode=ParseMode.HTML,
            reply_markup=kb_onboarding_sports(ob["selected_sports"]),
        )

    elif action.startswith("league_done:"):
        sport_key = action.split(":", 1)[1]
        idx = ob.get("_league_idx", 0) + 1

        if idx < len(ob["selected_sports"]):
            # Next sport's leagues
            ob["_league_idx"] = idx
            next_key = ob["selected_sports"][idx]
            sport = config.ALL_SPORTS.get(next_key)
            label = sport.label if sport else next_key
            text = f"<b>Step 2/6: Select leagues for {sport.emoji} {label}</b>\n\nTap to toggle."
            await query.edit_message_text(
                text, parse_mode=ParseMode.HTML,
                reply_markup=kb_onboarding_leagues(next_key),
            )
        else:
            # Move to teams step
            ob["step"] = "teams"
            ob["_team_idx"] = 0
            await _show_team_prompt(query, ob)

    elif action == "teams_done":
        # Move to risk
        ob["step"] = "risk"
        text = "<b>Step 4/6: Risk profile</b>\n\nHow aggressive should your tips be?"
        await query.edit_message_text(
            text, parse_mode=ParseMode.HTML,
            reply_markup=kb_onboarding_risk(),
        )

    elif action == "notify_done":
        # Move to summary
        ob["step"] = "summary"
        await _show_summary(query, ob)


async def _show_team_prompt(query, ob: dict) -> None:
    """Show team input prompt for the current sport."""
    idx = ob.get("_team_idx", 0)
    sports = ob["selected_sports"]
    if idx >= len(sports):
        # All done, move to risk
        ob["step"] = "risk"
        text = "<b>Step 4/6: Risk profile</b>\n\nHow aggressive should your tips be?"
        await query.edit_message_text(
            text, parse_mode=ParseMode.HTML,
            reply_markup=kb_onboarding_risk(),
        )
        return

    sport_key = sports[idx]
    sport = config.ALL_SPORTS.get(sport_key)
    label = sport.label if sport else sport_key
    emoji = sport.emoji if sport else "🏅"

    text = textwrap.dedent(f"""\
        <b>Step 3/6: Favourite team for {emoji} {label}</b>

        Type your favourite team name, or tap <b>Skip</b>.
    """)
    await query.edit_message_text(
        text, parse_mode=ParseMode.HTML,
        reply_markup=kb_onboarding_team_skip(sport_key),
    )


async def handle_ob_team_skip(query, sport_key: str) -> None:
    """Skip team selection for a sport."""
    user_id = query.from_user.id
    ob = _get_ob(user_id)
    ob["_team_idx"] = ob.get("_team_idx", 0) + 1
    await _show_team_prompt(query, ob)


async def handle_ob_league(query, action: str) -> None:
    """Toggle a league selection."""
    user_id = query.from_user.id
    ob = _get_ob(user_id)

    parts = action.split(":", 1)
    sport_key = parts[0]
    league = parts[1] if len(parts) > 1 else ""

    if sport_key not in ob["selected_leagues"]:
        ob["selected_leagues"][sport_key] = []

    leagues = ob["selected_leagues"][sport_key]
    if league in leagues:
        leagues.remove(league)
    else:
        leagues.append(league)

    sport = config.ALL_SPORTS.get(sport_key)
    label = sport.label if sport else sport_key
    emoji = sport.emoji if sport else "🏅"
    text = f"<b>Step 2/6: Select leagues for {emoji} {label}</b>\n\nTap to toggle."
    await query.edit_message_text(
        text, parse_mode=ParseMode.HTML,
        reply_markup=kb_onboarding_leagues(sport_key, leagues),
    )


async def handle_ob_risk(query, risk_key: str) -> None:
    """Set risk profile during onboarding."""
    user_id = query.from_user.id
    ob = _get_ob(user_id)
    ob["risk"] = risk_key
    ob["step"] = "notify"

    text = "<b>Step 5/6: Daily picks notification</b>\n\nWhen do you want your daily tips?"
    await query.edit_message_text(
        text, parse_mode=ParseMode.HTML,
        reply_markup=kb_onboarding_notify(),
    )


async def handle_ob_notify(query, hour_str: str) -> None:
    """Set notification hour during onboarding."""
    user_id = query.from_user.id
    ob = _get_ob(user_id)
    ob["notify_hour"] = int(hour_str)
    ob["step"] = "summary"
    await _show_summary(query, ob)


async def _show_summary(query, ob: dict) -> None:
    """Show onboarding summary."""
    sports_lines = []
    for sk in ob["selected_sports"]:
        sport = config.ALL_SPORTS.get(sk)
        label = f"{sport.emoji} {sport.label}" if sport else sk
        leagues = ob["selected_leagues"].get(sk, [])
        team = ob["teams"].get(sk)
        line = f"  • {label}"
        if leagues:
            line += f" ({', '.join(leagues)})"
        if team:
            line += f" — ❤️ {team}"
        sports_lines.append(line)

    risk_label = config.RISK_PROFILES.get(ob["risk"], {}).get("label", ob["risk"] or "Not set")
    hour = ob.get("notify_hour")
    notify_str = f"{hour}:00" if hour is not None else "Not set"

    text = textwrap.dedent(f"""\
        <b>Step 6/6: Your profile summary</b>

        <b>Sports:</b>
    """) + "\n".join(sports_lines) + textwrap.dedent(f"""

        <b>Risk:</b> {risk_label}
        <b>Daily picks:</b> {notify_str}

        All good? Tap <b>Let's go!</b> to start.
    """)

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 Let's go!", callback_data="ob_done:finish")],
        [InlineKeyboardButton("« Redo", callback_data="ob_nav:back_sports")],
    ])
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)


async def handle_ob_done(query) -> None:
    """Persist onboarding data and show main menu."""
    user_id = query.from_user.id
    ob = _get_ob(user_id)

    # Save to DB
    await db.clear_user_sport_prefs(user_id)
    for sk in ob["selected_sports"]:
        leagues = ob["selected_leagues"].get(sk, [])
        team = ob["teams"].get(sk)
        if leagues:
            for lg in leagues:
                await db.save_sport_pref(user_id, sk, league=lg, team_name=team)
        else:
            await db.save_sport_pref(user_id, sk, team_name=team)

    if ob["risk"]:
        await db.update_user_risk(user_id, ob["risk"])
    if ob.get("notify_hour") is not None:
        await db.update_user_notification_hour(user_id, ob["notify_hour"])

    await db.set_onboarding_done(user_id)
    _onboarding_state.pop(user_id, None)

    user = query.from_user
    text = textwrap.dedent(f"""\
        <b>🇿🇦 You're all set, {user.first_name}!</b>

        Pick a sport below or tap <b>AI Tip</b> for a prediction.
    """)
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=MAIN_MENU_KB)


# ── Free-text handler ────────────────────────────────────

async def freetext_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle free text — either team input during onboarding or AI chat."""
    user = update.effective_user
    ob = _onboarding_state.get(user.id)

    # If in onboarding teams step, treat as team name input
    if ob and ob["step"] == "teams":
        idx = ob.get("_team_idx", 0)
        if idx < len(ob["selected_sports"]):
            sport_key = ob["selected_sports"][idx]
            ob["teams"][sport_key] = update.message.text.strip()
            ob["_team_idx"] = idx + 1

            # Show next team prompt or move to risk
            if ob["_team_idx"] < len(ob["selected_sports"]):
                next_key = ob["selected_sports"][ob["_team_idx"]]
                sport = config.ALL_SPORTS.get(next_key)
                label = sport.label if sport else next_key
                emoji = sport.emoji if sport else "🏅"
                text = textwrap.dedent(f"""\
                    <b>Step 3/6: Favourite team for {emoji} {label}</b>

                    Type your favourite team name, or tap <b>Skip</b>.
                """)
                await update.message.reply_text(
                    text, parse_mode=ParseMode.HTML,
                    reply_markup=kb_onboarding_team_skip(next_key),
                )
            else:
                # Move to risk
                ob["step"] = "risk"
                text = "<b>Step 4/6: Risk profile</b>\n\nHow aggressive should your tips be?"
                await update.message.reply_text(
                    text, parse_mode=ParseMode.HTML,
                    reply_markup=kb_onboarding_risk(),
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

    await update.message.reply_text(reply, parse_mode=ParseMode.HTML, reply_markup=back_button())


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
    log.info("Starting PaulSportSA bot…")
    app = Application.builder().token(config.BOT_TOKEN).build()

    # Initialise DB on startup
    app.post_init = lambda _app: db.init_db()

    # Command handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("menu", cmd_menu))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("odds", cmd_odds))
    app.add_handler(CommandHandler("tip", cmd_tip))
    app.add_handler(CommandHandler("stats", cmd_stats))

    # Callback query handler (prefix:action routing)
    app.add_handler(CallbackQueryHandler(on_button))

    # Free-text chat (also handles team input during onboarding)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, freetext_handler))

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
