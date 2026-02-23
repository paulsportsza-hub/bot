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

# ── Keyboards ─────────────────────────────────────────────

MAIN_MENU_KB = InlineKeyboardMarkup(
    [
        [
            InlineKeyboardButton("⚽ Soccer/PSL", callback_data="sport:psl"),
            InlineKeyboardButton("🏉 Rugby", callback_data="sport:rugby"),
        ],
        [
            InlineKeyboardButton("🏏 Cricket", callback_data="sport:cricket"),
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


# ── /start ────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    await db.upsert_user(user.id, user.username, user.first_name)
    text = textwrap.dedent(f"""\
        <b>🇿🇦 Welcome to PaulSportSA, {user.first_name}!</b>

        Your AI-powered sports betting assistant for South Africa.

        Pick a sport below to see the latest odds, or tap
        <b>AI Tip</b> for a Claude-powered prediction.
    """)
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=MAIN_MENU_KB)


# ── /help ─────────────────────────────────────────────────

HELP_TEXT = textwrap.dedent("""\
    <b>PaulSportSA — Help</b>

    <b>Commands</b>
    /start — Main menu
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
    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("⚽ PSL", callback_data="sport:psl"),
                InlineKeyboardButton("🏉 Rugby", callback_data="sport:rugby"),
            ],
            [
                InlineKeyboardButton("🏏 Cricket", callback_data="sport:cricket"),
            ],
        ]
    )
    await update.message.reply_text(
        "<b>Choose a sport to view odds:</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=kb,
    )


# ── /tip ──────────────────────────────────────────────────

async def cmd_tip(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("⚽ Soccer/PSL", callback_data="ai:psl"),
                InlineKeyboardButton("🏉 Rugby", callback_data="ai:rugby"),
            ],
            [
                InlineKeyboardButton("🏏 Cricket", callback_data="ai:cricket"),
            ],
        ]
    )
    await update.message.reply_text(
        "<b>Choose a sport for an AI tip:</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=kb,
    )


# ── Callback router ──────────────────────────────────────

async def callback_router(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    data = query.data
    prefix, _, action = data.partition(":")

    if prefix == "menu":
        await handle_menu(query, action)
    elif prefix == "sport":
        await handle_sport(query, action)
    elif prefix == "ai":
        await handle_ai(query, action)
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
        for label, key in config.SPORTS_MAP.items():
            try:
                events = await fetch_odds(key)
                parts.append(format_odds_message(events, label.upper()))
            except Exception:
                parts.append(f"<b>{label.upper()}</b>\n⚠️ Could not fetch odds.\n")
        text = "\n\n".join(parts)
    else:
        sport_key = config.SPORTS_MAP.get(action)
        if not sport_key:
            await query.edit_message_text("Sport not found.", parse_mode=ParseMode.HTML, reply_markup=back_button())
            return
        try:
            events = await fetch_odds(sport_key)
            text = format_odds_message(events, action.upper())
        except Exception as exc:
            log.error("Odds fetch error for %s: %s", action, exc)
            text = f"⚠️ Could not fetch <b>{action.upper()}</b> odds. Try again later."

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
    sport = action if action != "tip" else "psl"
    sport_key = config.SPORTS_MAP.get(sport)

    await query.edit_message_text("🤖 <i>Analysing odds…</i>", parse_mode=ParseMode.HTML)

    odds_context = ""
    if sport_key:
        try:
            events = await fetch_odds(sport_key)
            odds_context = format_odds_message(events, sport.upper())
        except Exception:
            odds_context = "Could not fetch live odds."

    try:
        resp = await claude.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": f"Here are the latest {sport.upper()} odds:\n\n{odds_context}\n\nGive me your best tip.",
                }
            ],
        )
        tip_text = resp.content[0].text
    except Exception as exc:
        log.error("Claude API error: %s", exc)
        tip_text = "⚠️ AI analysis unavailable right now. Try again shortly."

    # Save tip to DB
    try:
        await db.save_tip(sport=sport, match="AI Analysis", prediction=tip_text)
    except Exception:
        pass

    await query.edit_message_text(tip_text, parse_mode=ParseMode.HTML, reply_markup=back_button())


# ── Free-text → AI chat ──────────────────────────────────

async def freetext_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Let users ask any sports betting question via Claude."""
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
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("odds", cmd_odds))
    app.add_handler(CommandHandler("tip", cmd_tip))
    app.add_handler(CommandHandler("stats", cmd_stats))

    # Callback query handler (prefix:action routing)
    app.add_handler(CallbackQueryHandler(callback_router))

    # Free-text chat
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, freetext_handler))

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
