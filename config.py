"""MzansiEdge configuration — loads .env and exposes app-wide constants."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BOT_ROOT = Path(__file__).resolve().parent


def _resolve_sqlite_url(raw_url: str | None) -> str:
    """Anchor relative SQLite URLs to the bot repo so DB resolution is cwd-safe."""
    default_path = BOT_ROOT / "data" / "mzansiedge.db"
    candidate = raw_url or f"sqlite+aiosqlite:///{default_path.as_posix()}"

    for prefix in ("sqlite+aiosqlite:///", "sqlite:///"):
        if not candidate.startswith(prefix):
            continue
        target = candidate[len(prefix):]
        path_part, sep, suffix = target.partition("?")
        if path_part == ":memory:" or path_part.startswith("/"):
            return candidate
        absolute_path = (BOT_ROOT / path_part).resolve()
        resolved_target = absolute_path.as_posix()
        if sep:
            resolved_target = f"{resolved_target}?{suffix}"
        return f"{prefix}{resolved_target}"

    return candidate


def _sqlite_path_from_url(db_url: str) -> Path | None:
    """Return the absolute SQLite path for file-backed SQLite URLs."""
    for prefix in ("sqlite+aiosqlite:///", "sqlite:///"):
        if not db_url.startswith(prefix):
            continue
        target = db_url[len(prefix):].partition("?")[0]
        if target == ":memory:":
            return None
        return Path(target)
    return None

# ── Telegram ───────────────────────────────────────────────
BOT_TOKEN: str = os.environ["BOT_TOKEN"]
ADMIN_IDS: list[int] = [int(i) for i in os.environ["ADMIN_IDS"].split(",")]

# ── External APIs ──────────────────────────────────────────
ODDS_API_KEY: str = os.environ["ODDS_API_KEY"]
ANTHROPIC_API_KEY: str = os.environ["ANTHROPIC_API_KEY"]
OPENROUTER_API_KEY: str = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENROUTER_MANAGEMENT_KEY", "")

# ── Stitch (subscriptions — active) ──────────────────────
STITCH_CLIENT_ID: str = os.environ.get("STITCH_CLIENT_ID", "")
STITCH_CLIENT_SECRET: str = os.environ.get("STITCH_CLIENT_SECRET", "")
STITCH_WEBHOOK_SECRET: str = os.environ.get("STITCH_WEBHOOK_SECRET", "")
STITCH_MOCK_MODE: bool = os.environ.get("STITCH_MOCK_MODE", "true").lower() == "true"
STITCH_REDIRECT_URI: str = os.environ.get("STITCH_REDIRECT_URI", "")
STITCH_WEBHOOK_ENDPOINT_ID: str = os.environ.get("STITCH_WEBHOOK_ENDPOINT_ID", "")

# ── Subscription Tiers ───────────────────────────────────
TIER_PRICES: dict[str, int] = {
    "bronze": 0,         # Free
    "gold": 9900,        # R99.00 in cents
    "diamond": 19900,    # R199.00 in cents
}
TIER_NAMES: dict[str, str] = {
    "bronze": "Bronze (Free)",
    "gold": "Gold",
    "diamond": "Diamond",
}
TIER_EMOJIS: dict[str, str] = {
    "bronze": "\U0001f949",   # 🥉
    "gold": "\U0001f947",     # 🥇
    "diamond": "\U0001f48e",  # 💎
}
FOUNDING_MEMBER_PRICE: int = 69900  # R699.00/year in cents
FOUNDING_MEMBER_SLOTS: int = 100
LAUNCH_DATE: str = "2026-04-27"
FOUNDING_REFUND_DEADLINE: str = LAUNCH_DATE
FOUNDING_TERMS_TITLE: str = os.environ.get(
    "FOUNDING_TERMS_TITLE",
    "MzansiEdge Founding Member Terms",
)
FOUNDING_TERMS_URL: str = os.environ.get("FOUNDING_TERMS_URL", "")

STITCH_PRODUCTS: dict[str, dict] = {
    "gold_monthly": {"id": os.environ.get("STITCH_GOLD_MONTHLY_ID", ""), "tier": "gold", "price": 9900, "period": "monthly"},
    "gold_annual": {"id": os.environ.get("STITCH_GOLD_ANNUAL_ID", ""), "tier": "gold", "price": 79900, "period": "annual"},
    "diamond_monthly": {"id": os.environ.get("STITCH_DIAMOND_MONTHLY_ID", ""), "tier": "diamond", "price": 19900, "period": "monthly"},
    "diamond_annual": {"id": os.environ.get("STITCH_DIAMOND_ANNUAL_ID", ""), "tier": "diamond", "price": 159900, "period": "annual"},
    "founding_diamond": {"id": os.environ.get("STITCH_FOUNDING_ID", ""), "tier": "diamond", "price": 69900, "period": "annual", "founding": True},
}

# ── PostHog (analytics) ──────────────────────────────────
POSTHOG_API_KEY: str = os.environ.get("POSTHOG_API_KEY", "")
POSTHOG_HOST: str = os.environ.get("POSTHOG_HOST", "https://us.i.posthog.com")
POSTHOG_PERSONAL_API_KEY: str = os.environ.get("POSTHOG_PERSONAL_API_KEY", "")

# ── Meta Conversions API ──────────────────────────────────
META_PIXEL_ID: str = os.environ.get("META_PIXEL_ID", "")
META_CAPI_ACCESS_TOKEN: str = os.environ.get("META_CAPI_ACCESS_TOKEN", "")

# ── Database ───────────────────────────────────────────────
DATABASE_URL: str = _resolve_sqlite_url(os.environ.get("DATABASE_URL"))
DATABASE_PATH: Path | None = _sqlite_path_from_url(DATABASE_URL)

# ── Timezone ───────────────────────────────────────────────
TZ: str = os.environ.get("TZ", "Africa/Johannesburg")

# ── Odds API settings ─────────────────────────────────────
ODDS_BASE_URL = "https://api.the-odds-api.com/v4"
ODDS_API_BASE = ODDS_BASE_URL  # alias used by scripts/sports_data.py

# ── Paths ──────────────────────────────────────────────────
DATA_DIR = BOT_ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

# Scrapers repo — env-var driven for CI; defaults to sibling of bot repo on server
SCRAPERS_ROOT = Path(os.environ.get("SCRAPERS_ROOT", str(BOT_ROOT.parent / "scrapers")))
ODDS_DB_PATH = SCRAPERS_ROOT / "odds.db"
ENRICHMENT_DB_PATH = SCRAPERS_ROOT / "enrichment.db"
TIPSTER_DB_PATH = SCRAPERS_ROOT / "tipsters" / "tipster_predictions.db"
COACHES_PATH = SCRAPERS_ROOT / "coaches.json"
KEY_PLAYERS_PATH = SCRAPERS_ROOT / "key_players.json"
SCRAPERS_ENV_PATH = SCRAPERS_ROOT / ".env"


def ensure_scrapers_importable() -> None:
    """Add SCRAPERS_ROOT (and its parent) to sys.path so scrapers modules
    can be imported.  Call once at bot startup — replaces all scattered
    sys.path.insert hacks."""
    import sys
    for p in (str(SCRAPERS_ROOT.parent), str(SCRAPERS_ROOT)):
        if p not in sys.path:
            sys.path.insert(0, p)


# ── Bankroll defaults ──────────────────────────────────────
DEFAULT_BANKROLL: float = 1000.0

# ── Risk profiles ─────────────────────────────────────────
RISK_PROFILES: dict[str, dict] = {
    "conservative": {"label": "🛡 Conservative", "kelly_fraction": 0.25, "max_stake_pct": 2, "min_ev": 5.0},
    "moderate":     {"label": "⚖️ Moderate",     "kelly_fraction": 0.50, "max_stake_pct": 5, "min_ev": 3.0},
    "aggressive":   {"label": "🚀 Aggressive",   "kelly_fraction": 1.00, "max_stake_pct": 10, "min_ev": 1.0},
}

# ── Bookmaker Affiliates (multi-bookmaker) ───────────────
# status: "active" = approved affiliate, "pending_approval" = applied but not yet approved
BOOKMAKER_AFFILIATES: dict[str, dict] = {
    "betway": {
        "name": "Betway",
        "affiliate_code": "BPA117074",
        "base_url": "https://www.betway.co.za",
        "status": "pending_approval",
        "deep_link_template": None,
    },
    "hollywoodbets": {
        "name": "Hollywoodbets",
        "affiliate_code": None,
        "base_url": "https://www.hollywoodbets.net",
        "status": "pending_approval",
        "deep_link_template": None,
    },
    "sportingbet": {
        "name": "Sportingbet",
        "affiliate_code": None,
        "base_url": "https://www.sportingbet.co.za",
        "status": "pending_approval",
        "deep_link_template": None,
    },
    "supabets": {
        "name": "SupaBets",
        "affiliate_code": None,
        "base_url": "https://www.supabets.co.za",
        "status": "pending_approval",
        "deep_link_template": None,
    },
    "gbets": {
        "name": "GBets",
        "affiliate_code": None,
        "base_url": "https://www.gbets.co.za",
        "status": "pending_approval",
        "deep_link_template": None,
    },
    "wsb": {
        "name": "WSB",
        "affiliate_code": None,
        "base_url": "https://www.wsb.co.za",
        "status": "pending_approval",
        "deep_link_template": None,
    },
    "supersportbet": {
        "name": "SuperSportBet",
        "affiliate_code": None,
        "base_url": "https://www.supersportbet.co.za",
        "status": "pending_approval",
        "deep_link_template": None,
    },
    "playabets": {
        "name": "PlayaBets",
        "affiliate_code": None,
        "base_url": "https://www.playabets.co.za",
        "status": "pending_approval",
        "deep_link_template": None,
    },
}

# ── SA Bookmakers (whitelisted for user-facing odds) ──────
ACTIVE_BOOKMAKER = "betway"
BETWAY_AFFILIATE_CODE = "BPA117074"

SA_BOOKMAKERS: dict[str, dict] = {
    "betway": {
        "display_name": "Betway.co.za",
        "short_name": "Betway",
        "website_url": "https://www.betway.co.za",
        "guide_url": "",
        "affiliate_base_url": f"https://www.betway.co.za/?btag={BETWAY_AFFILIATE_CODE}",
        "active": True,
    },
    "sportingbet": {
        "display_name": "SportingBet.co.za",
        "short_name": "SportingBet",
        "website_url": "https://www.sportingbet.co.za",
        "guide_url": "",
        "affiliate_base_url": "",
        "active": True,
    },
    "10bet": {
        "display_name": "10Bet.co.za",
        "short_name": "10Bet",
        "website_url": "https://www.10bet.co.za",
        "guide_url": "",
        "affiliate_base_url": "",
        "active": True,
    },
    "playabets": {
        "display_name": "PlayaBets.co.za",
        "short_name": "PlayaBets",
        "website_url": "https://www.playabets.co.za",
        "guide_url": "",
        "affiliate_base_url": "",
        "active": True,
    },
    "supabets": {
        "display_name": "SupaBets.co.za",
        "short_name": "SupaBets",
        "website_url": "https://www.supabets.co.za",
        "guide_url": "",
        "affiliate_base_url": "",
        "active": True,
    },
    "hollywoodbets": {
        "display_name": "Hollywoodbets.net",
        "short_name": "Hollywoodbets",
        "website_url": "https://www.hollywoodbets.net",
        "guide_url": "",
        "affiliate_base_url": "",
        "active": True,
    },
    "gbets": {
        "display_name": "GBets.co.za",
        "short_name": "GBets",
        "website_url": "https://www.gbets.co.za",
        "guide_url": "",
        "affiliate_base_url": "",
        "active": True,
    },
    "wsb": {
        "display_name": "WSB.co.za",
        "short_name": "WSB",
        "website_url": "https://www.wsb.co.za",
        "guide_url": "",
        "affiliate_base_url": "",
        "active": True,
    },
    "supersportbet": {
        "display_name": "SuperSportBet.co.za",
        "short_name": "SuperSportBet",
        "website_url": "https://www.supersportbet.co.za",
        "guide_url": "",
        "affiliate_base_url": "",
        "active": True,
    },
}


def sa_display_name(bk_key: str) -> str:
    """Get the .co.za display name for an SA bookmaker key."""
    bk = SA_BOOKMAKERS.get(bk_key)
    if bk:
        return bk["display_name"]
    return bk_key


def get_active_bookmaker() -> dict:
    """Get the active bookmaker config dict."""
    return SA_BOOKMAKERS[ACTIVE_BOOKMAKER]


def get_active_display_name() -> str:
    """Get the active bookmaker's short display name (e.g. 'Betway')."""
    return SA_BOOKMAKERS[ACTIVE_BOOKMAKER]["short_name"]


def get_active_website_url() -> str:
    """Get the active bookmaker's website URL."""
    return SA_BOOKMAKERS[ACTIVE_BOOKMAKER]["website_url"]


def get_affiliate_url(event_id: str | None = None) -> str:
    """Get the Betway affiliate URL. Deep links are pending — uses base affiliate URL for now."""
    bk = SA_BOOKMAKERS[ACTIVE_BOOKMAKER]
    base = bk.get("affiliate_base_url") or bk.get("website_url", "")
    # TODO: Wire deep links when Betway provides event-specific URL format
    # e.g. f"{base}&event={event_id}" once the deep link spec is available
    return base


# ── Sport & League definitions ────────────────────────────
# fav_type controls the onboarding favourite prompt:
#   "team"    → "favourite team"
#   "player"  → "favourite player"
#   "fighter" → "favourite fighter"

@dataclass
class LeagueDef:
    key: str                     # internal identifier (e.g. "epl")
    label: str                   # display name (e.g. "Premier League")
    api_key: str | None = None   # The Odds API sport key


@dataclass
class SportDef:
    key: str                     # category key (e.g. "soccer")
    label: str                   # display name (e.g. "Soccer")
    emoji: str
    fav_type: str = "team"       # team/player/fighter/driver/skip
    leagues: list[LeagueDef] = field(default_factory=list)


SPORTS: list[SportDef] = [
    # ── Soccer ⚽ ─────────────────────────────────────────
    SportDef(key="soccer", label="Soccer", emoji="⚽", fav_type="team", leagues=[
        LeagueDef(key="epl", label="Premier League", api_key="soccer_epl"),
        LeagueDef(key="psl", label="PSL", api_key=None),
        LeagueDef(key="la_liga", label="La Liga", api_key="soccer_spain_la_liga"),
        LeagueDef(key="bundesliga", label="Bundesliga", api_key="soccer_germany_bundesliga"),
        LeagueDef(key="serie_a", label="Serie A", api_key="soccer_italy_serie_a"),
        LeagueDef(key="ligue_1", label="Ligue 1", api_key="soccer_france_ligue_one"),
        LeagueDef(key="ucl", label="Champions League", api_key="soccer_uefa_champs_league"),
        LeagueDef(key="mls", label="MLS", api_key="soccer_usa_mls"),
    ]),
    # ── Rugby 🏉 ─────────────────────────────────────────
    SportDef(key="rugby", label="Rugby", emoji="🏉", fav_type="team", leagues=[
        LeagueDef(key="international_rugby", label="International Rugby"),
        LeagueDef(key="urc", label="URC"),
        LeagueDef(key="super_rugby", label="Super Rugby"),
        LeagueDef(key="currie_cup", label="Currie Cup"),
        LeagueDef(key="six_nations", label="Six Nations", api_key="rugbyunion_six_nations"),
        LeagueDef(key="rugby_champ", label="Rugby Championship"),
    ]),
    # ── Cricket 🏏 ────────────────────────────────────────
    SportDef(key="cricket", label="Cricket", emoji="🏏", fav_type="team", leagues=[
        LeagueDef(key="csa_cricket", label="CSA / SA20", api_key="cricket_international_t20"),
        LeagueDef(key="test_cricket", label="Test Matches"),
        LeagueDef(key="odis", label="ODIs"),
        LeagueDef(key="t20i", label="T20 Internationals"),
        LeagueDef(key="ipl", label="IPL", api_key="cricket_ipl"),
        LeagueDef(key="big_bash", label="Big Bash", api_key="cricket_big_bash"),
        LeagueDef(key="t20_wc", label="T20 World Cup", api_key="cricket_t20_world_cup"),
    ]),
    # ── Combat Sports 🥊 ─────────────────────────────────
    SportDef(key="combat", label="Combat Sports", emoji="🥊", fav_type="fighter", leagues=[
        LeagueDef(key="boxing_major", label="Major Bouts"),
        LeagueDef(key="ufc", label="UFC Events", api_key="mma_mixed_martial_arts"),
    ]),
]


# ── Lookup maps ──────────────────────────────────────────

# Category key → SportDef
ALL_SPORTS: dict[str, SportDef] = {s.key: s for s in SPORTS}

# League key → LeagueDef
ALL_LEAGUES: dict[str, LeagueDef] = {}
for _s in SPORTS:
    for _lg in _s.leagues:
        ALL_LEAGUES[_lg.key] = _lg

# League key → sport category key
LEAGUE_SPORT: dict[str, str] = {}
for _s in SPORTS:
    for _lg in _s.leagues:
        LEAGUE_SPORT[_lg.key] = _s.key

# Legacy: league_key → api_key (for picks / odds handlers)
SPORTS_MAP: dict[str, str] = {
    lg.key: lg.api_key for s in SPORTS for lg in s.leagues if lg.api_key
}


# ── Favourite prompt helpers ─────────────────────────────

def fav_label(sport: SportDef) -> str:
    """Return the appropriate label for the favourite prompt."""
    return {
        "team": "favourite team",
        "player": "favourite player",
        "fighter": "favourite fighter",
    }.get(sport.fav_type, "favourite")


def fav_label_plural(sport: SportDef) -> str:
    """Return the plural label for the favourite prompt."""
    return {
        "team": "favourite teams",
        "player": "favourite players",
        "fighter": "favourite fighters",
    }.get(sport.fav_type, "favourites")


# ── Top Teams / Players per league ───────────────────────
# Used for multi-select buttons in onboarding favourites step.

TOP_TEAMS: dict[str, list[str]] = {
    # ── Soccer ──
    "psl": [
        "Kaizer Chiefs", "Orlando Pirates", "Mamelodi Sundowns",
        "Cape Town City", "Stellenbosch", "AmaZulu",
        "SuperSport United", "Sekhukhune United",
    ],
    "epl": [
        "Arsenal", "Aston Villa", "Chelsea", "Liverpool",
        "Man City", "Man United", "Newcastle", "Spurs",
        "Brighton", "West Ham", "Crystal Palace", "Fulham",
    ],
    "la_liga": [
        "Real Madrid", "Barcelona", "Atletico Madrid",
        "Real Sociedad", "Athletic Bilbao", "Villarreal",
        "Sevilla", "Real Betis", "Valencia", "Girona",
    ],
    "bundesliga": [
        "Bayern Munich", "Borussia Dortmund", "RB Leipzig",
        "Bayer Leverkusen", "Eintracht Frankfurt", "Stuttgart",
        "Wolfsburg", "Freiburg",
    ],
    "serie_a": [
        "AC Milan", "Inter Milan", "Juventus", "Napoli",
        "Roma", "Lazio", "Atalanta", "Fiorentina",
    ],
    "ligue_1": [
        "PSG", "Marseille", "Lyon", "Monaco",
        "Lille", "Nice", "Lens", "Rennes",
    ],
    "ucl": [],  # uses teams from other soccer leagues
    "mls": [
        "Inter Miami", "LAFC", "LA Galaxy", "Atlanta United",
        "Columbus Crew", "Seattle Sounders", "Nashville SC",
    ],
    # ── Rugby ──
    "urc": [
        "Bulls", "Stormers", "Sharks", "Lions",
        "Munster", "Leinster", "Ulster", "Glasgow Warriors",
        "Edinburgh", "Connacht",
    ],
    "super_rugby": [
        "Crusaders", "Blues", "Hurricanes", "Chiefs",
        "Highlanders", "Brumbies", "Reds", "Waratahs",
        "Force", "Drua", "Moana Pasifika",
    ],
    "currie_cup": [
        "Bulls", "Stormers", "Sharks", "Lions",
        "Griquas", "Pumas", "Cheetahs",
    ],
    "six_nations": [
        "England", "France", "Ireland",
        "Scotland", "Wales", "Italy",
    ],
    "rugby_champ": [
        "South Africa", "New Zealand", "Australia", "Argentina",
    ],
    "international_rugby": [
        "South Africa", "New Zealand", "England", "France",
        "Ireland", "Australia", "Scotland", "Wales",
        "Argentina", "Italy", "Fiji", "Japan",
    ],
    # ── Cricket ──
    "csa_cricket": [
        "Proteas", "MI Cape Town", "Joburg Super Kings",
        "Durban Super Giants", "Pretoria Capitals",
        "Sunrisers Eastern Cape", "Paarl Royals",
    ],
    "test_cricket": [
        "South Africa", "India", "Australia",
        "England", "New Zealand", "Pakistan",
    ],
    "odis": [
        "South Africa", "India", "Australia",
        "England", "New Zealand", "Pakistan",
        "Sri Lanka", "Bangladesh", "West Indies", "Afghanistan",
    ],
    "t20i": [
        "South Africa", "India", "Australia",
        "England", "New Zealand", "Pakistan",
        "Sri Lanka", "West Indies", "Afghanistan",
    ],
    "ipl": [
        "Mumbai Indians", "Chennai Super Kings", "RCB",
        "Kolkata Knight Riders", "Delhi Capitals",
        "Rajasthan Royals", "Punjab Kings",
        "Sunrisers Hyderabad", "Lucknow Super Giants",
        "Gujarat Titans",
    ],
    "big_bash": [
        "Sydney Sixers", "Melbourne Stars", "Perth Scorchers",
        "Brisbane Heat", "Adelaide Strikers", "Hobart Hurricanes",
        "Sydney Thunder", "Melbourne Renegades",
    ],
    "t20_wc": [
        "South Africa", "India", "Australia",
        "England", "West Indies", "Pakistan",
    ],
    # ── Combat Sports ──
    "boxing_major": [
        "Canelo Alvarez", "Oleksandr Usyk", "Terence Crawford",
        "Naoya Inoue", "Artur Beterbiev", "Dmitry Bivol",
        "Gervonta Davis", "Shakur Stevenson",
        "Devin Haney", "Jesse Rodriguez",
    ],
    # ── MMA ──
    "ufc": [
        "Islam Makhachev", "Alex Pereira", "Jon Jones",
        "Leon Edwards", "Ilia Topuria", "Sean O'Malley",
        "Dricus Du Plessis", "Max Holloway",
        "Charles Oliveira", "Alexander Volkanovski",
        "Merab Dvalishvili",
    ],
}


# ── Reverse lookup: team name → list of league keys ─────
TEAM_TO_LEAGUES: dict[str, list[str]] = {}
for _lk, _ts in TOP_TEAMS.items():
    for _t in _ts:
        TEAM_TO_LEAGUES.setdefault(_t, []).append(_lk)


# ── National team → leagues (sport-aware) ────────────────
# National teams like "South Africa" appear in both rugby and cricket.
# This dict disambiguates by sport key.
NATIONAL_TEAM_LEAGUES: dict[str, dict[str, list[str]]] = {
    "rugby": {
        "South Africa": ["international_rugby", "rugby_champ"],
        "New Zealand": ["international_rugby", "rugby_champ"],
        "Australia": ["international_rugby", "rugby_champ"],
        "Argentina": ["international_rugby", "rugby_champ"],
        "England": ["international_rugby", "six_nations"],
        "France": ["international_rugby", "six_nations"],
        "Ireland": ["international_rugby", "six_nations"],
        "Scotland": ["international_rugby", "six_nations"],
        "Wales": ["international_rugby", "six_nations"],
        "Italy": ["international_rugby", "six_nations"],
        "Fiji": ["international_rugby"],
        "Japan": ["international_rugby"],
    },
    "cricket": {
        "South Africa": ["test_cricket", "odis", "t20i", "t20_wc"],
        "India": ["test_cricket", "odis", "t20i", "t20_wc"],
        "Australia": ["test_cricket", "odis", "t20i"],
        "England": ["test_cricket", "odis", "t20i"],
        "New Zealand": ["test_cricket", "odis", "t20i"],
        "Pakistan": ["test_cricket", "odis", "t20i"],
        "Sri Lanka": ["odis", "t20i"],
        "Bangladesh": ["odis"],
        "West Indies": ["test_cricket", "odis", "t20i", "t20_wc"],
        "Afghanistan": ["odis", "t20i"],
    },
}


# ── Bonus domestic leagues for national teams (Phase 0F) ──
# When a user follows a national team, also auto-add the domestic franchise
# league where that country's players compete at club level.
NATIONAL_TEAM_BONUS_LEAGUES: dict[str, dict[str, list[str]]] = {
    "rugby": {
        "South Africa": ["urc", "currie_cup"],
        "New Zealand": ["super_rugby"],
        "Australia": ["super_rugby"],
        "Argentina": ["super_rugby"],
        "Ireland": ["urc"],
        "Scotland": ["urc"],
        "Wales": ["urc"],
        "Italy": ["urc"],
    },
    "cricket": {
        "South Africa": ["csa_cricket"],
        "India": ["ipl"],
        "Australia": ["big_bash"],
    },
}


# ── Sport-level examples for team prompts (Phase 0D) ─────
SPORT_EXAMPLES: dict[str, str] = {
    "soccer": "e.g. Chiefs, Arsenal, Barcelona, Sundowns",
    "rugby": "e.g. South Africa, Bulls, Stormers, Ireland",
    "cricket": "e.g. South Africa, MI Cape Town, Mumbai Indians",
    "combat": "e.g. Dricus, Canelo, Islam, Pereira",
}


# ── Team / Player Aliases (for fuzzy matching) ──────────
# Maps lowercase alias → canonical name.

TEAM_ALIASES: dict[str, str] = {
    # SA Soccer
    "chiefs": "Kaizer Chiefs", "amakhosi": "Kaizer Chiefs", "kc": "Kaizer Chiefs",
    "pirates": "Orlando Pirates", "bucs": "Orlando Pirates", "buccaneers": "Orlando Pirates",
    "sundowns": "Mamelodi Sundowns", "brazilians": "Mamelodi Sundowns", "downs": "Mamelodi Sundowns",
    "cape town": "Cape Town City", "ctc": "Cape Town City",
    "stellies": "Stellenbosch",
    "supersport": "SuperSport United", "matsatsantsa": "SuperSport United",
    # EPL
    "man u": "Man United", "man utd": "Man United", "mufc": "Man United",
    "manchester united": "Man United", "red devils": "Man United",
    "man c": "Man City", "mcfc": "Man City", "manchester city": "Man City",
    "sky blues": "Man City", "cityzens": "Man City",
    "pool": "Liverpool", "lfc": "Liverpool", "reds": "Liverpool",
    "gunners": "Arsenal", "gooners": "Arsenal", "ars": "Arsenal", "afc": "Arsenal",
    "tottenham": "Spurs", "thfc": "Spurs",
    "toffees": "Everton",
    "magpies": "Newcastle", "nufc": "Newcastle", "toon": "Newcastle",
    "hammers": "West Ham", "whu": "West Ham",
    "blues": "Chelsea", "cfc": "Chelsea",
    "villans": "Aston Villa", "villa": "Aston Villa",
    "seagulls": "Brighton",
    "wolves": "Wolverhampton",
    "forest": "Nottingham Forest",
    "cherries": "Bournemouth",
    "foxes": "Leicester",
    "bees": "Brentford",
    "cottagers": "Fulham",
    "saints": "Southampton",
    # La Liga
    "barca": "Barcelona", "fcb": "Barcelona", "blaugrana": "Barcelona",
    "real": "Real Madrid", "madrid": "Real Madrid", "los blancos": "Real Madrid",
    "atleti": "Atletico Madrid", "atletico": "Atletico Madrid",
    # Bundesliga
    "bayern": "Bayern Munich",
    "bvb": "Borussia Dortmund", "dortmund": "Borussia Dortmund",
    "leipzig": "RB Leipzig",
    "leverkusen": "Bayer Leverkusen",
    # Serie A
    "juve": "Juventus",
    "inter": "Inter Milan", "nerazzurri": "Inter Milan",
    "milan": "AC Milan", "rossoneri": "AC Milan",
    # Ligue 1
    "paris": "PSG", "paris sg": "PSG", "paris saint-germain": "PSG",
    "om": "Marseille",
    # SA PSL (extended)
    "glamour boys": "Kaizer Chiefs",
    "usuthu": "AmaZulu",
    "masandawana": "Mamelodi Sundowns",
    # Rugby
    "springboks": "South Africa", "boks": "South Africa", "bokke": "South Africa",
    "all blacks": "New Zealand",
    "wallabies": "Australia",
    "pumas": "Argentina",
    "les bleus": "France",
    # Cricket
    "csk": "Chennai Super Kings",
    "mi": "Mumbai Indians",
    "rcb": "RCB",
    "kkr": "Kolkata Knight Riders",
    "dc": "Delhi Capitals",
    "rr": "Rajasthan Royals",
    "gt": "Gujarat Titans",
    "lsg": "Lucknow Super Giants",
    "srh": "Sunrisers Hyderabad",
    "pbks": "Punjab Kings",
    "proteas": "South Africa",
    "blackcaps": "New Zealand",
    "windies": "West Indies",
    # Boxing
    "canelo": "Canelo Alvarez",
    "tank": "Gervonta Davis",
    "fury": "Tyson Fury",
    # MMA
    "ddp": "Dricus Du Plessis", "dricus": "Dricus Du Plessis",
    "drikus": "Dricus Du Plessis", "dreikus": "Dricus Du Plessis",
    "drikus du plessis": "Dricus Du Plessis", "du plessis": "Dricus Du Plessis",
    "du plesis": "Dricus Du Plessis", "duplessis": "Dricus Du Plessis",
    "stillknocks": "Dricus Du Plessis", "stilknocks": "Dricus Du Plessis",
    "stillnocks": "Dricus Du Plessis",
    "poatan": "Alex Pereira", "pereira": "Alex Pereira",
    "bones": "Jon Jones", "jon jones": "Jon Jones",
    "do bronx": "Charles Oliveira",
    "blessed": "Max Holloway", "holloway": "Max Holloway",
    "suga": "Sean O'Malley", "omalley": "Sean O'Malley",
    "islam": "Islam Makhachev", "makhachev": "Islam Makhachev",
    # Common typos / SA slang extras
    "amakhosi": "Kaizer Chiefs", "khosi": "Kaizer Chiefs",
    "buccaneers": "Orlando Pirates", "bucs": "Orlando Pirates",
    "masandawana": "Mamelodi Sundowns", "downs": "Mamelodi Sundowns",
    "gooners": "Arsenal", "gunners": "Arsenal", "arse": "Arsenal",
    "the reds": "Liverpool", "pool": "Liverpool",
    "man u": "Manchester United", "united": "Manchester United",
    "man c": "Manchester City", "city": "Manchester City",
    "spurs": "Tottenham Hotspur", "tottenham": "Tottenham Hotspur",
    "chelsea fc": "Chelsea", "the blues": "Chelsea",
    "stormers": "DHL Stormers", "bulls": "Vodacom Bulls",
    "sharks": "Hollywoodbets Sharks", "lions": "Emirates Lions",
}


# ── Sport Display Config (maps Odds API group names) ─────

SPORT_DISPLAY: dict[str, dict[str, str]] = {
    "Soccer":               {"emoji": "⚽", "entity": "team",    "entities": "teams"},
    "Boxing":               {"emoji": "🥊", "entity": "fighter", "entities": "fighters"},
    "Mixed Martial Arts":   {"emoji": "🥋", "entity": "fighter", "entities": "fighters"},
    "Rugby Union":          {"emoji": "🏉", "entity": "team",    "entities": "teams"},
    "Rugby League":         {"emoji": "🏉", "entity": "team",    "entities": "teams"},
    "Cricket":              {"emoji": "🏏", "entity": "team",    "entities": "teams"},
}

SA_PRIORITY_GROUPS: list[str] = [
    "Soccer",
    "Rugby Union",
    "Cricket",
    "Boxing",
    "Mixed Martial Arts",
]


# ── League-specific examples for team input prompts ───────

LEAGUE_EXAMPLES: dict[str, str] = {
    # Soccer
    "psl": "e.g. Chiefs, Pirates, Sundowns",
    "epl": "e.g. Arsenal, Liverpool, Man City",
    "la_liga": "e.g. Real Madrid, Barcelona, Atletico",
    "bundesliga": "e.g. Bayern Munich, Dortmund, Leverkusen",
    "serie_a": "e.g. Juventus, AC Milan, Inter Milan",
    "ligue_1": "e.g. PSG, Marseille, Lyon",
    "ucl": "e.g. Real Madrid, Man City, Bayern",
    "mls": "e.g. Inter Miami, LAFC, LA Galaxy",
    # Rugby
    "urc": "e.g. Bulls, Stormers, Sharks, Leinster",
    "super_rugby": "e.g. Crusaders, Blues, Hurricanes",
    "currie_cup": "e.g. Bulls, Stormers, Sharks",
    "six_nations": "e.g. England, France, Ireland",
    "rugby_champ": "e.g. South Africa, New Zealand",
    "international_rugby": "e.g. South Africa, New Zealand, England, France",
    # Cricket
    "csa_cricket": "e.g. Proteas, MI Cape Town, Paarl Royals",
    "test_cricket": "e.g. South Africa, India, Australia",
    "odis": "e.g. South Africa, India, Australia, England",
    "t20i": "e.g. South Africa, India, England, Pakistan",
    "ipl": "e.g. Mumbai Indians, CSK, RCB",
    "big_bash": "e.g. Sydney Sixers, Perth Scorchers",
    "t20_wc": "e.g. South Africa, India, England",
    # Combat Sports
    "boxing_major": "e.g. Canelo, Usyk, Crawford",
    "ufc": "e.g. Islam, Pereira, Dricus, Jones",
}


# ── Team abbreviations (for compact button display) ───────

TEAM_ABBREVIATIONS: dict[str, str] = {
    # Soccer — SA PSL
    "Kaizer Chiefs": "KC", "Orlando Pirates": "OPI", "Mamelodi Sundowns": "SUN",
    "Cape Town City": "CTC", "Stellenbosch": "STL", "AmaZulu": "AMA",
    "SuperSport United": "SSU", "Sekhukhune United": "SEK",
    # Soccer — EPL
    "Arsenal": "ARS", "Aston Villa": "AVL", "Chelsea": "CHE",
    "Liverpool": "LIV", "Man City": "MCI", "Man United": "MUN",
    "Newcastle": "NEW", "Spurs": "TOT", "Brighton": "BHA",
    "West Ham": "WHU", "Crystal Palace": "CRY", "Fulham": "FUL",
    "Everton": "EVE", "Brentford": "BRE", "Wolves": "WOL",
    "Nottingham Forest": "NFO", "Bournemouth": "BOU",
    # Soccer — La Liga
    "Real Madrid": "RMA", "Barcelona": "BAR", "Atletico Madrid": "ATM",
    "Real Sociedad": "RSO", "Athletic Bilbao": "ATH", "Villarreal": "VIL",
    "Sevilla": "SEV", "Real Betis": "BET", "Valencia": "VAL", "Girona": "GIR",
    # Soccer — Bundesliga
    "Bayern Munich": "BAY", "Borussia Dortmund": "BVB", "RB Leipzig": "RBL",
    "Bayer Leverkusen": "LEV", "Eintracht Frankfurt": "SGE", "Stuttgart": "STU",
    # Soccer — Serie A
    "AC Milan": "ACM", "Inter Milan": "INT", "Juventus": "JUV",
    "Napoli": "NAP", "Roma": "ROM", "Lazio": "LAZ", "Atalanta": "ATA",
    # Soccer — other
    "PSG": "PSG", "Marseille": "OM", "Lyon": "LYO", "Monaco": "MON",
    "Inter Miami": "MIA", "LAFC": "LAFC", "LA Galaxy": "LAG",
    # Rugby
    "Bulls": "BUL", "Stormers": "STO", "Sharks": "SHA", "Lions": "LIO",
    "Crusaders": "CRU", "Blues": "BLU", "Hurricanes": "HUR",
    "South Africa": "RSA", "New Zealand": "NZL", "Australia": "AUS",
    "England": "ENG", "France": "FRA", "Ireland": "IRE",
    "Scotland": "SCO", "Wales": "WAL", "Italy": "ITA", "Argentina": "ARG",
    # Additional SA PSL
    "Richards Bay": "RBF", "TS Galaxy": "TSG", "Chippa United": "CPU",
    "Royal AM": "RAM", "Polokwane City": "POL", "Golden Arrows": "ARR",
    "Magesi": "MAG",
    # Cricket international
    "India": "IND", "Pakistan": "PAK", "West Indies": "WI",
    "Bangladesh": "BAN", "Sri Lanka": "SLK",
    # Rugby / Cricket franchises
    "Western Force": "WFO", "Highlanders": "HIG", "Dolphins": "DOL",
    "Titans": "TIT", "MI Cape Town": "MICT", "Paarl Royals": "PR",
}


def abbreviate_team(name: str, max_len: int = 3) -> str:
    """Get short team abbreviation for compact display."""
    if name in TEAM_ABBREVIATIONS:
        return TEAM_ABBREVIATIONS[name]
    return name[:max_len].upper()


# ── Country Flags (for international matches) ────────────
# Maps team/country names to flag emojis.
# Used with both-or-nothing rule: only show flags if BOTH teams have one.

COUNTRY_FLAGS: dict[str, str] = {
    # Africa
    "South Africa": "🇿🇦",
    "Nigeria": "🇳🇬",
    "Ghana": "🇬🇭",
    "Kenya": "🇰🇪",
    "Namibia": "🇳🇦",
    "Zimbabwe": "🇿🇼",
    # Europe
    "England": "🏴󠁧󠁢󠁥󠁮󠁧󠁿",
    "Scotland": "🏴󠁧󠁢󠁳󠁣󠁴󠁿",
    "Wales": "🏴󠁧󠁢󠁷󠁬󠁳󠁿",
    "Ireland": "🇮🇪",
    "France": "🇫🇷",
    "Italy": "🇮🇹",
    "Germany": "🇩🇪",
    "Spain": "🇪🇸",
    "Portugal": "🇵🇹",
    "Netherlands": "🇳🇱",
    "Georgia": "🇬🇪",
    "Romania": "🇷🇴",
    # Oceania
    "Australia": "🇦🇺",
    "New Zealand": "🇳🇿",
    "Fiji": "🇫🇯",
    "Samoa": "🇼🇸",
    "Tonga": "🇹🇴",
    # Americas
    "Argentina": "🇦🇷",
    "USA": "🇺🇸",
    "Canada": "🇨🇦",
    "Uruguay": "🇺🇾",
    "Chile": "🇨🇱",
    "Brazil": "🇧🇷",
    "West Indies": "🏝️",
    # Asia
    "India": "🇮🇳",
    "Pakistan": "🇵🇰",
    "Sri Lanka": "🇱🇰",
    "Bangladesh": "🇧🇩",
    "Afghanistan": "🇦🇫",
    "Japan": "🇯🇵",
}


def get_country_flag(team_name: str) -> str:
    """Get country flag emoji for a team name. Returns '' if not found."""
    return COUNTRY_FLAGS.get(team_name, "")


def get_sport_emoji(group: str) -> str:
    """Get emoji for a sport group."""
    return SPORT_DISPLAY.get(group, {}).get("emoji", "🏅")


def get_entity_label(group: str, plural: bool = False) -> str:
    """Get 'team', 'player', or 'fighter' for a sport group."""
    key = "entities" if plural else "entity"
    return SPORT_DISPLAY.get(group, {}).get(key, "teams" if plural else "team")
