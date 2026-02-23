"""MzansiEdge — WhatsApp menu definitions.

WhatsApp Business API limits interactive messages to 3 buttons.
This module defines WhatsApp-adapted menu structures that cascade
complex Telegram menus into 3-button-per-screen flows.

These are NOT used yet — they document the planned WhatsApp menu
architecture for when the WhatsApp integration is built.
"""

from __future__ import annotations

# ── Menu definitions ─────────────────────────────────────
# Each menu is a list of screens. Each screen has up to 3 buttons.
# Buttons can be actions or links to other screens.

MAIN_MENU = {
    "text": "Welcome to MzansiEdge! What would you like to do?",
    "buttons": [
        {"id": "picks:today", "title": "Today's Picks"},
        {"id": "schedule", "title": "Schedule"},
        {"id": "menu:more", "title": "More..."},
    ],
}

MAIN_MENU_MORE = {
    "text": "More options:",
    "buttons": [
        {"id": "teams:view", "title": "My Teams"},
        {"id": "settings:home", "title": "Settings"},
        {"id": "menu:home", "title": "Back"},
    ],
}

# ── Settings (8 buttons → 3 screens) ────────────────────

SETTINGS_MENU = {
    "text": "Settings:",
    "buttons": [
        {"id": "settings:risk", "title": "Risk Profile"},
        {"id": "settings:bankroll", "title": "Bankroll"},
        {"id": "settings:more", "title": "More..."},
    ],
}

SETTINGS_MORE = {
    "text": "More settings:",
    "buttons": [
        {"id": "settings:notify", "title": "Notifications"},
        {"id": "settings:sports", "title": "Sports"},
        {"id": "settings:reset", "title": "Reset Profile"},
    ],
}

# ── Onboarding ───────────────────────────────────────────
# Sports selection: paginated, 3 per screen

ONBOARDING_SPORTS_PAGES = [
    # Page 1
    {"buttons": [
        {"id": "ob_sport:soccer", "title": "Soccer"},
        {"id": "ob_sport:rugby", "title": "Rugby"},
        {"id": "ob_sport:cricket", "title": "Cricket"},
    ]},
    # Page 2
    {"buttons": [
        {"id": "ob_sport:tennis", "title": "Tennis"},
        {"id": "ob_sport:boxing", "title": "Boxing"},
        {"id": "ob_sport:mma", "title": "MMA"},
    ]},
    # Page 3
    {"buttons": [
        {"id": "ob_sport:basketball", "title": "Basketball"},
        {"id": "ob_sport:golf", "title": "Golf"},
        {"id": "ob_sport:motorsport", "title": "More..."},
    ]},
]

# Risk: 3 options = fits exactly
ONBOARDING_RISK = {
    "text": "What's your risk appetite?",
    "buttons": [
        {"id": "ob_risk:conservative", "title": "Conservative"},
        {"id": "ob_risk:moderate", "title": "Moderate"},
        {"id": "ob_risk:aggressive", "title": "Aggressive"},
    ],
}

# Bankroll: text input with presets
ONBOARDING_BANKROLL = {
    "text": "What's your weekly bankroll? Reply with an amount (e.g. R1000) or choose:",
    "buttons": [
        {"id": "ob_bankroll:1000", "title": "R1,000"},
        {"id": "ob_bankroll:2000", "title": "R2,000"},
        {"id": "ob_bankroll:skip", "title": "Not sure"},
    ],
}

# Notifications: 2 time slots per screen
ONBOARDING_NOTIFY = {
    "text": "When should we send daily picks?",
    "buttons": [
        {"id": "ob_notify:7", "title": "Morning (7 AM)"},
        {"id": "ob_notify:18", "title": "Evening (6 PM)"},
        {"id": "ob_notify:21", "title": "Night (9 PM)"},
    ],
}

# ── Compatibility matrix ─────────────────────────────────
# Documents which Telegram keyboards exceed WhatsApp's 3-button limit

TELEGRAM_KEYBOARD_AUDIT = {
    # function_name: (total_buttons, needs_wa_adaptation)
    "kb_main": (7, True),
    "kb_nav": (2, False),
    "kb_bets": (4, True),
    "kb_teams": (4, True),
    "kb_stats": (4, True),
    "kb_bookmakers": (4, True),
    "kb_settings": (8, True),
    "back_button": (1, False),
    "kb_onboarding_experience": (3, False),
    "kb_onboarding_sports": (12, True),
    "kb_onboarding_leagues": (8, True),
    "kb_onboarding_favourites": (10, True),
    "kb_onboarding_risk": (4, True),
    "kb_onboarding_notify": (5, True),
    "kb_onboarding_bankroll": (5, True),
}
