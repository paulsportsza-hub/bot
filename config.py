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
    "conservative": {"label": "🛡 Conservative", "kelly_fraction": 0.25, "max_stake_pct": 2, "min_ev": 5.0},
    "moderate":     {"label": "⚖️ Moderate",     "kelly_fraction": 0.50, "max_stake_pct": 5, "min_ev": 3.0},
    "aggressive":   {"label": "🔥 Aggressive",   "kelly_fraction": 1.00, "max_stake_pct": 10, "min_ev": 1.0},
}

# ── SA Bookmakers (highlighted in pick cards) ─────────────
SA_BOOKMAKERS: set[str] = {
    "betway", "hollywoodbets", "supabets", "sportingbet",
    "sunbet", "betxchange", "playabets", "gbets",
}


# ── Sport & League definitions ────────────────────────────
# fav_type controls the onboarding favourite prompt:
#   "team"    → "favourite team"
#   "player"  → "favourite player"
#   "fighter" → "favourite fighter"
#   "driver"  → "favourite driver or team"
#   "skip"    → skip favourite step entirely (e.g. horse racing)

@dataclass
class LeagueDef:
    key: str                     # internal identifier (e.g. "epl")
    label: str                   # display name (e.g. "EPL")
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
        LeagueDef(key="psl", label="PSL", api_key="soccer_south_africa_psl"),
        LeagueDef(key="epl", label="EPL", api_key="soccer_epl"),
        LeagueDef(key="la_liga", label="La Liga", api_key="soccer_spain_la_liga"),
        LeagueDef(key="bundesliga", label="Bundesliga", api_key="soccer_germany_bundesliga"),
        LeagueDef(key="serie_a", label="Serie A", api_key="soccer_italy_serie_a"),
        LeagueDef(key="ligue_1", label="Ligue 1", api_key="soccer_france_ligue_one"),
        LeagueDef(key="ucl", label="Champions League", api_key="soccer_uefa_champs_league"),
        LeagueDef(key="mls", label="MLS", api_key="soccer_usa_mls"),
    ]),
    # ── Rugby 🏉 ─────────────────────────────────────────
    SportDef(key="rugby", label="Rugby", emoji="🏉", fav_type="team", leagues=[
        LeagueDef(key="urc", label="URC"),
        LeagueDef(key="super_rugby", label="Super Rugby"),
        LeagueDef(key="currie_cup", label="Currie Cup"),
        LeagueDef(key="six_nations", label="Six Nations", api_key="rugbyunion_six_nations"),
        LeagueDef(key="rugby_champ", label="Rugby Championship"),
        LeagueDef(key="rwc", label="Rugby World Cup"),
    ]),
    # ── Cricket 🏏 ────────────────────────────────────────
    SportDef(key="cricket", label="Cricket", emoji="🏏", fav_type="team", leagues=[
        LeagueDef(key="csa_cricket", label="CSA / SA20", api_key="cricket_international_t20"),
        LeagueDef(key="test_cricket", label="Test Matches"),
        LeagueDef(key="ipl", label="IPL", api_key="cricket_ipl"),
        LeagueDef(key="big_bash", label="Big Bash", api_key="cricket_big_bash"),
        LeagueDef(key="t20_wc", label="T20 World Cup", api_key="cricket_t20_world_cup"),
    ]),
    # ── Tennis 🎾 ─────────────────────────────────────────
    SportDef(key="tennis", label="Tennis", emoji="🎾", fav_type="player", leagues=[
        LeagueDef(key="atp", label="ATP Tour"),
        LeagueDef(key="wta", label="WTA Tour"),
        LeagueDef(key="grand_slams", label="Grand Slams"),
    ]),
    # ── Boxing 🥊 ─────────────────────────────────────────
    SportDef(key="boxing", label="Boxing", emoji="🥊", fav_type="fighter", leagues=[
        LeagueDef(key="boxing_major", label="Major Bouts"),
    ]),
    # ── MMA / UFC 🥋 ─────────────────────────────────────
    SportDef(key="mma", label="UFC / MMA", emoji="🥋", fav_type="fighter", leagues=[
        LeagueDef(key="ufc", label="UFC Events", api_key="mma_mixed_martial_arts"),
    ]),
    # ── Basketball 🏀 ────────────────────────────────────
    SportDef(key="basketball", label="Basketball", emoji="🏀", fav_type="team", leagues=[
        LeagueDef(key="nba", label="NBA", api_key="basketball_nba"),
        LeagueDef(key="euroleague", label="EuroLeague", api_key="basketball_euroleague"),
    ]),
    # ── American Football 🏈 ─────────────────────────────
    SportDef(key="american_football", label="American Football", emoji="🏈", fav_type="team", leagues=[
        LeagueDef(key="nfl", label="NFL", api_key="americanfootball_nfl"),
    ]),
    # ── Golf ⛳ ───────────────────────────────────────────
    SportDef(key="golf", label="Golf", emoji="⛳", fav_type="player", leagues=[
        LeagueDef(key="pga", label="PGA Tour"),
        LeagueDef(key="dp_world", label="DP World Tour"),
        LeagueDef(key="golf_majors", label="Majors", api_key="golf_masters_tournament_winner"),
    ]),
    # ── Motorsport 🏎️ ────────────────────────────────────
    SportDef(key="motorsport", label="Motorsport", emoji="🏎️", fav_type="driver", leagues=[
        LeagueDef(key="f1", label="Formula 1"),
        LeagueDef(key="motogp", label="MotoGP"),
    ]),
    # ── Horse Racing 🐎 ──────────────────────────────────
    SportDef(key="horse_racing", label="Horse Racing", emoji="🐎", fav_type="skip", leagues=[
        LeagueDef(key="sa_horse_racing", label="SA Horse Racing"),
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
        "driver": "favourite driver or team",
    }.get(sport.fav_type, "favourite")


def fav_label_plural(sport: SportDef) -> str:
    """Return the plural label for the favourite prompt."""
    return {
        "team": "favourite teams",
        "player": "favourite players",
        "fighter": "favourite fighters",
        "driver": "favourite drivers or teams",
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
    "rwc": [
        "South Africa", "New Zealand", "England",
        "France", "Ireland", "Australia",
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
    # ── Tennis ──
    "atp": [
        "Djokovic", "Alcaraz", "Sinner", "Medvedev",
        "Zverev", "Rublev", "Ruud", "Fritz",
        "De Minaur", "Tsitsipas", "Draper", "Shelton",
    ],
    "wta": [
        "Sabalenka", "Swiatek", "Gauff", "Rybakina",
        "Pegula", "Zheng", "Jabeur", "Keys",
        "Ostapenko", "Muchova",
    ],
    "grand_slams": [],  # uses ATP + WTA players
    # ── Boxing ──
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
    # ── Basketball ──
    "nba": [
        "Lakers", "Celtics", "Warriors", "Nuggets",
        "Bucks", "76ers", "Heat", "Suns",
        "Knicks", "Mavericks", "Cavaliers", "Thunder",
    ],
    "euroleague": [
        "Real Madrid", "Barcelona", "Olympiacos",
        "Fenerbahce", "Panathinaikos", "Anadolu Efes",
    ],
    # ── American Football ──
    "nfl": [
        "Chiefs", "49ers", "Eagles", "Bills",
        "Cowboys", "Ravens", "Lions", "Dolphins",
        "Jets", "Packers", "Bengals", "Steelers",
    ],
    # ── Golf ──
    "pga": [
        "Scottie Scheffler", "Rory McIlroy", "Jon Rahm",
        "Xander Schauffele", "Collin Morikawa",
        "Viktor Hovland", "Patrick Cantlay",
        "Wyndham Clark", "Ludvig Aberg", "Brooks Koepka",
    ],
    "dp_world": [],  # uses PGA players
    "golf_majors": [],  # uses PGA players
    # ── Motorsport ──
    "f1": [
        "Max Verstappen", "Lewis Hamilton", "Charles Leclerc",
        "Lando Norris", "Carlos Sainz", "Oscar Piastri",
        "George Russell", "Fernando Alonso",
        "Red Bull", "Mercedes", "Ferrari", "McLaren",
    ],
    "motogp": [
        "Francesco Bagnaia", "Jorge Martin", "Marc Marquez",
        "Enea Bastianini", "Brad Binder",
        "Ducati", "Aprilia", "KTM",
    ],
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
    "manchester united": "Man United",
    "man c": "Man City", "mcfc": "Man City", "manchester city": "Man City",
    "pool": "Liverpool", "lfc": "Liverpool",
    "gooners": "Arsenal", "ars": "Arsenal", "afc": "Arsenal",
    "tottenham": "Spurs", "thfc": "Spurs",
    "toffees": "Everton",
    "magpies": "Newcastle", "nufc": "Newcastle", "toon": "Newcastle",
    "hammers": "West Ham", "whu": "West Ham",
    "blues": "Chelsea", "cfc": "Chelsea",
    "villans": "Aston Villa", "villa": "Aston Villa",
    "seagulls": "Brighton",
    # La Liga
    "barca": "Barcelona", "fcb": "Barcelona",
    "real": "Real Madrid", "madrid": "Real Madrid",
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
    # Rugby
    "springboks": "South Africa", "boks": "South Africa",
    "all blacks": "New Zealand",
    "wallabies": "Australia",
    "pumas": "Argentina",
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
    # Tennis
    "nole": "Djokovic", "novak": "Djokovic",
    "carlitos": "Alcaraz",
    "iga": "Swiatek",
    "coco": "Gauff",
    # MMA
    "ddp": "Dricus Du Plessis", "dricus": "Dricus Du Plessis",
    "bones": "Jon Jones",
    "do bronx": "Charles Oliveira",
    "blessed": "Max Holloway",
    "suga": "Sean O'Malley",
    # F1
    "max": "Max Verstappen", "verstappen": "Max Verstappen",
    "lewis": "Lewis Hamilton", "hamilton": "Lewis Hamilton",
    "charles": "Charles Leclerc", "leclerc": "Charles Leclerc",
    "lando": "Lando Norris", "norris": "Lando Norris",
}
