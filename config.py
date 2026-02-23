"""MzansiEdge configuration — loads .env and exposes app-wide constants."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ── Telegram ───────────────────────────────────────────────
BOT_TOKEN: str = os.environ["BOT_TOKEN"]
ADMIN_IDS: list[int] = [int(i) for i in os.environ["ADMIN_IDS"].split(",")]

# ── External APIs ──────────────────────────────────────────
ODDS_API_KEY: str = os.environ["ODDS_API_KEY"]
ANTHROPIC_API_KEY: str = os.environ["ANTHROPIC_API_KEY"]

# ── Database ───────────────────────────────────────────────
DATABASE_URL: str = os.environ.get(
    "DATABASE_URL", "sqlite+aiosqlite:///data/mzansiedge.db"
)

# ── Timezone ───────────────────────────────────────────────
TZ: str = os.environ.get("TZ", "Africa/Johannesburg")

# ── Odds API settings ─────────────────────────────────────
ODDS_BASE_URL = "https://api.the-odds-api.com/v4"

# ── Paths ──────────────────────────────────────────────────
DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

# ── Risk profiles ─────────────────────────────────────────
RISK_PROFILES: dict[str, dict] = {
    "conservative": {"label": "🛡 Conservative", "kelly_fraction": 0.25, "max_stake_pct": 2},
    "moderate":     {"label": "⚖️ Moderate",     "kelly_fraction": 0.50, "max_stake_pct": 5},
    "aggressive":   {"label": "🔥 Aggressive",   "kelly_fraction": 1.00, "max_stake_pct": 10},
}


# ── Sport definition ──────────────────────────────────────
@dataclass
class SportDef:
    key: str            # internal identifier (used in callback_data)
    label: str          # display name
    emoji: str
    api_key: str | None  # The Odds API sport key (None = not available)
    leagues: list[str] = field(default_factory=list)


# ── 🇿🇦 South African Sports ──────────────────────────────
SA_SPORTS: list[SportDef] = [
    SportDef(
        key="psl",
        label="PSL",
        emoji="⚽",
        api_key=None,  # not on The Odds API
        leagues=["DStv Premiership", "National First Division"],
    ),
    SportDef(
        key="bafana",
        label="Bafana Bafana",
        emoji="⚽",
        api_key="soccer_africa_cup_of_nations",
        leagues=["AFCON", "WC Qualifiers"],
    ),
    SportDef(
        key="urc",
        label="URC",
        emoji="🏉",
        api_key=None,
        leagues=["Bulls", "Stormers", "Sharks", "Lions"],
    ),
    SportDef(
        key="super_rugby",
        label="Super Rugby",
        emoji="🏉",
        api_key=None,
        leagues=["Super Rugby Pacific"],
    ),
    SportDef(
        key="currie_cup",
        label="Currie Cup",
        emoji="🏉",
        api_key=None,
        leagues=["Currie Cup Premier"],
    ),
    SportDef(
        key="csa_cricket",
        label="CSA Cricket",
        emoji="🏏",
        api_key="cricket_international_t20",
        leagues=["SA20", "CSA T20", "Test Matches"],
    ),
]

# ── 🌍 Global Sports ──────────────────────────────────────
GLOBAL_SPORTS: list[SportDef] = [
    # Soccer
    SportDef(key="epl",         label="EPL",                emoji="⚽", api_key="soccer_epl",               leagues=["English Premier League"]),
    SportDef(key="la_liga",     label="La Liga",            emoji="⚽", api_key="soccer_spain_la_liga",      leagues=["La Liga"]),
    SportDef(key="bundesliga",  label="Bundesliga",         emoji="⚽", api_key="soccer_germany_bundesliga", leagues=["Bundesliga"]),
    SportDef(key="serie_a",     label="Serie A",            emoji="⚽", api_key="soccer_italy_serie_a",      leagues=["Serie A"]),
    SportDef(key="ligue_1",     label="Ligue 1",            emoji="⚽", api_key="soccer_france_ligue_one",   leagues=["Ligue 1"]),
    SportDef(key="ucl",         label="Champions League",   emoji="⚽", api_key="soccer_uefa_champs_league", leagues=["UEFA Champions League"]),
    # Basketball
    SportDef(key="nba",         label="NBA",                emoji="🏀", api_key="basketball_nba",            leagues=["NBA"]),
    # American Football
    SportDef(key="nfl",         label="NFL",                emoji="🏈", api_key="americanfootball_ncaaf",     leagues=["NFL", "NCAAF"]),
    # Ice Hockey
    SportDef(key="nhl",         label="NHL",                emoji="🏒", api_key="icehockey_nhl",             leagues=["NHL"]),
    # Baseball
    SportDef(key="mlb",         label="MLB",                emoji="⚾", api_key="baseball_mlb_preseason",    leagues=["MLB"]),
    # Tennis
    SportDef(key="atp",         label="ATP Tennis",         emoji="🎾", api_key="tennis_atp_dubai",          leagues=["ATP Tour"]),
    SportDef(key="wta",         label="WTA Tennis",         emoji="🎾", api_key=None,                        leagues=["WTA Tour"]),
    # MMA
    SportDef(key="mma",         label="UFC / MMA",          emoji="🥊", api_key="mma_mixed_martial_arts",    leagues=["UFC", "MMA"]),
    # Golf
    SportDef(key="golf",        label="Golf Majors",        emoji="⛳", api_key="golf_masters_tournament_winner", leagues=["Masters", "PGA", "US Open", "The Open"]),
    # Cricket
    SportDef(key="ipl",         label="IPL",                emoji="🏏", api_key="cricket_ipl",               leagues=["IPL"]),
    SportDef(key="big_bash",    label="Big Bash",           emoji="🏏", api_key="cricket_big_bash",          leagues=["Big Bash League"]),
    SportDef(key="t20_wc",      label="T20 World Cup",      emoji="🏏", api_key="cricket_t20_world_cup",     leagues=["T20 World Cup"]),
    # Rugby
    SportDef(key="six_nations", label="Six Nations",        emoji="🏉", api_key="rugbyunion_six_nations",    leagues=["Six Nations"]),
    SportDef(key="rwc",         label="Rugby World Cup",    emoji="🏉", api_key=None,                        leagues=["Rugby World Cup"]),
]

# Combined lookup: key → SportDef
ALL_SPORTS: dict[str, SportDef] = {}
for _s in SA_SPORTS + GLOBAL_SPORTS:
    ALL_SPORTS[_s.key] = _s

# Legacy flat map for backward compat with odds handlers
SPORTS_MAP: dict[str, str] = {
    s.key: s.api_key for s in SA_SPORTS + GLOBAL_SPORTS if s.api_key
}
