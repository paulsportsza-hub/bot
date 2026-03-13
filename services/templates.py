"""MzansiEdge — Message template registry.

All user-facing message strings centralised here for:
- Platform-agnostic rendering (Telegram HTML vs WhatsApp plain text)
- Future internationalisation (i18n)
- Consistent messaging across services

Templates use str.format() placeholders. HTML tags are only in 'telegram' variants.
"""

from __future__ import annotations

from typing import Any


# ── Template definitions ─────────────────────────────────
# Each key maps to a dict with 'telegram' (HTML) and 'whatsapp' (plain) variants.

TEMPLATES: dict[str, dict[str, str]] = {
    # ── Welcome & Start ──────────────────────────────────
    "welcome_new_user": {
        "telegram": (
            "\U0001f1ff\U0001f1e6 <b>Welcome to MzansiEdge, {name}!</b>\n\n"
            "Let's set up your profile in a few quick steps.\n\n"
            "<b>Step 1/8:</b> What's your betting experience?"
        ),
        "whatsapp": (
            "Welcome to MzansiEdge, {name}!\n\n"
            "Let's set up your profile in a few quick steps.\n\n"
            "Step 1/8: What's your betting experience?"
        ),
    },
    "welcome_returning": {
        "telegram": (
            "\U0001f1ff\U0001f1e6 <b>Welcome back, {name}!</b>\n\n"
            "Your AI-powered sports betting assistant.\n"
            "Pick a sport or get an AI tip below."
        ),
        "whatsapp": (
            "Welcome back, {name}!\n\n"
            "Your AI-powered sports betting assistant.\n"
            "Reply PICKS, SCHEDULE, or SETTINGS."
        ),
    },
    "welcome_onboarding_done": {
        "telegram": (
            "\U0001f389 <b>Welcome to MzansiEdge, {name}!</b>\n\n"
            "You're in. Your edge is live.\n\n"
            "Here's what I can do for you:\n\n"
            "\U0001f4ca <b>AI-Powered Picks</b> \u2014 I scan odds across bookmakers, "
            "find value bets, and tell you exactly where the edge is.\n\n"
            "\U0001f4c5 <b>Schedule & Tips</b> \u2014 See when your teams play and get "
            "instant AI analysis for any upcoming game.\n\n"
            "\U0001f4d6 <b>Your Betting Story</b> \u2014 MzansiEdge isn't just tips \u2014 "
            "it's a journey. Track your wins, learn as you go, and build "
            "your bankroll over time.\n\n"
            "\U0001f514 <b>But first \u2014 let's set up your story.</b>\n"
            "Choose what updates you want to receive so I know "
            "exactly how to keep you in the game."
        ),
        "whatsapp": (
            "Welcome to MzansiEdge, {name}!\n\n"
            "You're in. Your edge is live.\n\n"
            "I can help with:\n"
            "- AI-Powered Picks: value bets across bookmakers\n"
            "- Schedule & Tips: game analysis for your teams\n"
            "- Your Betting Story: track wins and grow\n\n"
            "Reply STORY to set up your notifications."
        ),
    },

    # ── Main Menu ────────────────────────────────────────
    "menu_main": {
        "telegram": (
            "\U0001f1ff\U0001f1e6 <b>MzansiEdge \u2014 Main Menu</b>\n\n"
            "Hey {name}, what would you like to do?"
        ),
        "whatsapp": (
            "MzansiEdge Menu\n\n"
            "Hey {name}! Reply with:\n"
            "PICKS - Today's value bets\n"
            "SCHEDULE - Upcoming games\n"
            "SETTINGS - Your preferences"
        ),
    },

    # ── Help ─────────────────────────────────────────────
    "help": {
        "telegram": (
            "\U0001f1ff\U0001f1e6 <b>MzansiEdge \u2014 Help</b>\n\n"
            "<b>Commands:</b>\n"
            "/start \u2014 Onboarding / main menu\n"
            "/picks \u2014 Today's AI value bets\n"
            "/schedule \u2014 Upcoming games for your teams\n"
            "/settings \u2014 Your preferences\n"
            "/help \u2014 This message\n"
            "/admin \u2014 Admin dashboard\n\n"
            "<b>How Tips Work:</b>\n"
            "I compare odds across 30+ bookmakers, calculate the "
            "true probability of each outcome, and find bets where "
            "the odds are higher than they should be \u2014 that's your edge."
        ),
        "whatsapp": (
            "MzansiEdge Help\n\n"
            "Commands:\n"
            "PICKS - Today's AI value bets\n"
            "SCHEDULE - Upcoming games\n"
            "SETTINGS - Your preferences\n"
            "HELP - This message\n\n"
            "How Tips Work:\n"
            "I compare odds across 30+ bookmakers, calculate true "
            "probability, and find bets where odds are higher than "
            "they should be."
        ),
    },

    # ── Picks ────────────────────────────────────────────
    "picks_loading": {
        "telegram": "\U0001f50d <i>{verb} across {count} league{s}\u2026</i>",
        "whatsapp": "{verb} across {count} league{s}...",
    },
    "picks_no_leagues": {
        "telegram": (
            "\U0001f3df\ufe0f You haven't selected any leagues yet!\n\n"
            "Tap below to set up your sports."
        ),
        "whatsapp": (
            "You haven't selected any leagues yet!\n"
            "Reply SETTINGS to set up your sports."
        ),
    },
    "picks_header": {
        "telegram": (
            "\U0001f4b0 <b>Found {count} value bet{s}!</b>\n\n"
            "\U0001f4ca Scanned {events} events | {markets} markets\n"
            "\u2696\ufe0f Risk: {risk}"
        ),
        "whatsapp": (
            "Found {count} value bet{s}!\n\n"
            "Scanned {events} events | {markets} markets\n"
            "Risk: {risk}"
        ),
    },
    "picks_empty_newbie": {
        "telegram": (
            "\U0001f4ed <b>No value bets found right now</b>\n\n"
            "Scanned {events} events across your leagues.\n\n"
            "Nothing cleared the board yet.\n"
            "Check back later - we keep scanning through the day."
        ),
        "whatsapp": (
            "No value bets found right now.\n\n"
            "Scanned {events} events. Bookmaker odds are fair today.\n"
            "Check back later!"
        ),
    },
    "picks_empty": {
        "telegram": (
            "\U0001f4ed <b>No value bets found right now</b>\n\n"
            "Scanned {events} events | {markets} markets\n\n"
            "Nothing clears your {risk} profile right now.\n"
            "Check back when more markets open or adjust your risk in /settings."
        ),
        "whatsapp": (
            "No value bets found right now.\n\n"
            "Scanned {events} events | {markets} markets.\n"
            "No edges meeting your {risk} profile.\n"
            "Check back when more markets open."
        ),
    },
    "picks_quota_exhausted": {
        "telegram": (
            "\u26a0\ufe0f <b>We've hit our daily data limit.</b>\n\n"
            "Picks will refresh tomorrow. Your bankroll is safe \u2014 "
            "no bets placed automatically."
        ),
        "whatsapp": (
            "We've hit our daily data limit.\n"
            "Picks will refresh tomorrow."
        ),
    },
    "picks_footer": {
        "telegram": "<i>Always gamble responsibly. \U0001f1ff\U0001f1e6</i>",
        "whatsapp": "Always gamble responsibly.",
    },

    # ── Schedule ─────────────────────────────────────────
    "schedule_no_leagues": {
        "telegram": (
            "\U0001f3df\ufe0f <b>No leagues selected!</b>\n\n"
            "Update your sports in /settings."
        ),
        "whatsapp": (
            "No leagues selected!\n"
            "Reply SETTINGS to update your sports."
        ),
    },
    "schedule_no_games": {
        "telegram": (
            "\U0001f4c5 <b>No upcoming games found</b>\n\n"
            "None of your followed teams have scheduled games right now. "
            "Check back later or add more teams in /settings."
        ),
        "whatsapp": (
            "No upcoming games found.\n"
            "Check back later or reply SETTINGS to add more teams."
        ),
    },
    "schedule_header": {
        "telegram": "\U0001f4c5 <b>Upcoming Games ({count})</b>\n",
        "whatsapp": "Upcoming Games ({count})\n",
    },
    "game_tips_loading": {
        "telegram": "\U0001f916 <i>Analysing {home} vs {away}\u2026</i>",
        "whatsapp": "Analysing {home} vs {away}...",
    },
    "game_tips_not_found": {
        "telegram": "\u26a0\ufe0f Couldn't find that game. It may have already started.",
        "whatsapp": "Couldn't find that game. It may have already started.",
    },
    "game_tips_no_odds": {
        "telegram": (
            "\U0001f4ca <b>{home} vs {away}</b>\n\n"
            "No odds available yet for this game. Check back closer to kickoff!"
        ),
        "whatsapp": (
            "{home} vs {away}\n\n"
            "No odds available yet. Check back closer to kickoff!"
        ),
    },

    # ── Onboarding Steps ─────────────────────────────────
    "ob_step_experience": {
        "telegram": "<b>Step 1/8:</b> What's your betting experience?",
        "whatsapp": "Step 1/8: What's your betting experience?\n\nReply: EXPERIENCED, CASUAL, or NEWBIE",
    },
    "ob_step_sports": {
        "telegram": "<b>Step 2/8:</b> Select your sports\n\nTap to toggle. Hit <b>Done</b> when ready.",
        "whatsapp": "Step 2/8: Select your sports\n\nReply with sport names (e.g. Soccer, Rugby, Cricket)",
    },
    "ob_step_risk": {
        "telegram": "<b>Step 5/8:</b> Risk profile\n\nHow aggressive should your tips be?",
        "whatsapp": "Step 5/8: Risk profile\n\nReply: CONSERVATIVE, MODERATE, or AGGRESSIVE",
    },
    "ob_step_bankroll": {
        "telegram": "<b>Step 6/8:</b> Weekly bankroll\n\nHow much do you set aside for betting each week?",
        "whatsapp": "Step 6/8: Weekly bankroll\n\nReply with an amount (e.g. R1000) or NOT SURE",
    },
    "ob_step_notify": {
        "telegram": "<b>Step 7/8:</b> When should we send daily picks?",
        "whatsapp": "Step 7/8: When should we send daily picks?\n\nReply: MORNING, MIDDAY, EVENING, or NIGHT",
    },
    "ob_no_sports": {
        "telegram": "\u26a0\ufe0f Please select at least one sport.",
        "whatsapp": "Please select at least one sport.",
    },

    # ── Settings ─────────────────────────────────────────
    "settings_risk_change": {
        "telegram": "\U0001f3af <b>Change Risk Profile</b>\n\nSelect your risk tolerance:",
        "whatsapp": "Change Risk Profile\n\nReply: CONSERVATIVE, MODERATE, or AGGRESSIVE",
    },
    "settings_notify_change": {
        "telegram": "\u23f0 <b>Change Notification Time</b>\n\nWhen do you want daily picks?",
        "whatsapp": "Change Notification Time\n\nReply: MORNING, MIDDAY, EVENING, or NIGHT",
    },
    "settings_bankroll": {
        "telegram": (
            "\U0001f4b0 <b>Bankroll</b>\n\n"
            "Current: {current}\n\nSelect a new weekly bankroll:"
        ),
        "whatsapp": (
            "Bankroll\n\n"
            "Current: {current}\n\n"
            "Reply with a new amount (e.g. R1000)"
        ),
    },
    "settings_bankroll_updated": {
        "telegram": "\u2705 Bankroll updated to R{amount}/week.",
        "whatsapp": "Bankroll updated to R{amount}/week.",
    },
    "settings_reset_warning": {
        "telegram": (
            "\u26a0\ufe0f <b>Reset your profile?</b>\n\n"
            "This will clear all your preferences, risk profile, "
            "favourite teams, and notification settings.\n\n"
            "Your betting history and stats will NOT be deleted.\n\n"
            "<i>This cannot be undone.</i>"
        ),
        "whatsapp": (
            "Reset your profile?\n\n"
            "This will clear all preferences.\n"
            "Your betting history will NOT be deleted.\n\n"
            "Reply YES to confirm or NO to cancel."
        ),
    },
    "settings_reset_done": {
        "telegram": (
            "\u2705 <b>Profile reset!</b>\n\n"
            "All preferences have been cleared.\n"
            "Tap below to start fresh."
        ),
        "whatsapp": (
            "Profile reset!\n\n"
            "All preferences cleared. Reply START to begin again."
        ),
    },

    # ── Errors ───────────────────────────────────────────
    "error_onboarding_required": {
        "telegram": "\u2699\ufe0f Complete onboarding first!\n\nUse /start to get set up.",
        "whatsapp": "Complete onboarding first!\n\nReply START to get set up.",
    },
    "error_odds_unavailable": {
        "telegram": "\u26a0\ufe0f Odds not available for {sport} right now.",
        "whatsapp": "Odds not available for {sport} right now.",
    },
    "error_ai_unavailable": {
        "telegram": "\u26a0\ufe0f AI analysis unavailable right now. Try again shortly.",
        "whatsapp": "AI analysis unavailable right now. Try again shortly.",
    },

    # ── Subscriptions ────────────────────────────────────
    "subscribe_ok": {
        "telegram": "\U0001f514 Following {home} vs {away}!",
        "whatsapp": "Following {home} vs {away}!",
    },
    "unsubscribe_ok": {
        "telegram": "\U0001f515 Unfollowed this game.",
        "whatsapp": "Unfollowed this game.",
    },
    "live_score_update": {
        "telegram": "\u26a1 <b>Live Update</b>\n\n{changes}",
        "whatsapp": "Live Update\n\n{changes}",
    },

    # ── Affiliate/Tip Placeholders ───────────────────────
    "tip_affiliate_soon": {
        "telegram": "\U0001f517 Affiliate link coming soon! Check back tomorrow.",
        "whatsapp": "Affiliate link coming soon!",
    },
    "tip_guide_soon": {
        "telegram": "\U0001f4d6 Betting guide coming soon! Check back tomorrow.",
        "whatsapp": "Betting guide coming soon!",
    },
}


def get_template(key: str, platform: str = "telegram") -> str:
    """Get a template string by key and platform.

    Falls back to 'telegram' if the platform variant doesn't exist.
    Raises KeyError if the template key doesn't exist.
    """
    tpl = TEMPLATES[key]
    return tpl.get(platform, tpl["telegram"])


def render(key: str, platform: str = "telegram", **kwargs: Any) -> str:
    """Get and format a template with the given variables.

    Usage:
        render("welcome_new_user", name="Paul")
        render("picks_header", platform="whatsapp", count=3, s="s", events=10, markets=30, risk="Moderate", quota="498")
    """
    tpl = get_template(key, platform)
    return tpl.format(**kwargs)
