"""PaulSportSA configuration — loads .env and exposes app-wide constants."""

import os
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
    "DATABASE_URL", "sqlite+aiosqlite:///data/paulsportsza.db"
)

# ── Timezone ───────────────────────────────────────────────
TZ: str = os.environ.get("TZ", "Africa/Johannesburg")

# ── Odds API settings ─────────────────────────────────────
ODDS_BASE_URL = "https://api.the-odds-api.com/v4"
# South-African-relevant sport keys on The Odds API
SPORTS_MAP: dict[str, str] = {
    "soccer":  "soccer_south_africa_first_division",
    "psl":     "soccer_south_africa_premier_league",
    "rugby":   "rugbyunion_super_rugby",
    "cricket": "cricket_international_t20",
}

# ── Paths ──────────────────────────────────────────────────
DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)
