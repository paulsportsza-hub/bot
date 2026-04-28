"""Reel card team-name display map (FIX-REEL-KIT-RENDERING-01).

Canonical short forms for user-facing team names on reel cards. The reel card
template is geometry-tuned for short uppercase tokens — long match-key forms
(``punjab_kings``) overflow and crash the rosette layout.

This module is the single source of truth for short forms across the codebase.
Other surfaces that need a short team name should import ``display_team_name``
rather than rolling their own abbreviation logic.
"""
from __future__ import annotations

# IPL — 10 franchises
IPL_DISPLAY: dict[str, str] = {
    "chennai_super_kings":          "CSK",
    "delhi_capitals":               "DC",
    "gujarat_titans":               "GT",
    "kolkata_knight_riders":        "KKR",
    "lucknow_super_giants":         "LSG",
    "mumbai_indians":               "MI",
    "punjab_kings":                 "PBKS",
    "rajasthan_royals":             "RR",
    "royal_challengers_bangalore":  "RCB",
    "royal_challengers_bengaluru":  "RCB",
    "sunrisers_hyderabad":          "SRH",
}

# PSL — 16 clubs (current + recent appearances)
PSL_DISPLAY: dict[str, str] = {
    "amazulu":              "AMAZULU",
    "cape_town_city":       "CT CITY",
    "cape_town_spurs":      "CT SPURS",
    "chippa_united":        "CHIPPA",
    "golden_arrows":        "ARROWS",
    "kaizer_chiefs":        "CHIEFS",
    "magesi":               "MAGESI",
    "mamelodi_sundowns":    "SUNDOWNS",
    "marumo_gallants":      "GALLANTS",
    "orbit_college":        "ORBIT",
    "orlando_pirates":      "PIRATES",
    "polokwane_city":       "POLOKWANE",
    "richards_bay":         "RICHARDS BAY",
    "royal_am":             "ROYAL AM",
    "sekhukhune_united":    "SEKHUKHUNE",
    "stellenbosch":         "STELLIES",
    "supersport_united":    "SUPERSPORT",
    "ts_galaxy":            "TS GALAXY",
}

# EPL — 20 clubs (2025/26 season)
EPL_DISPLAY: dict[str, str] = {
    "arsenal":              "ARSENAL",
    "aston_villa":          "ASTON VILLA",
    "bournemouth":          "BOURNEMOUTH",
    "brentford":            "BRENTFORD",
    "brighton":             "BRIGHTON",
    "burnley":              "BURNLEY",
    "chelsea":              "CHELSEA",
    "crystal_palace":       "PALACE",
    "everton":              "EVERTON",
    "fulham":               "FULHAM",
    "ipswich":              "IPSWICH",
    "leeds":                "LEEDS",
    "leicester":            "LEICESTER",
    "liverpool":            "LIVERPOOL",
    "luton":                "LUTON",
    "manchester_city":      "MAN CITY",
    "manchester_united":    "MAN UTD",
    "newcastle":            "NEWCASTLE",
    "nottingham_forest":    "FOREST",
    "sheffield_united":     "SHEFFIELD",
    "southampton":          "SOTON",
    "sunderland":           "SUNDERLAND",
    "tottenham":            "SPURS",
    "west_ham":             "WEST HAM",
    "wolves":               "WOLVES",
}

# URC — 16 franchises
URC_DISPLAY: dict[str, str] = {
    "benetton":             "BENETTON",
    "benetton_treviso":     "BENETTON",
    "bulls":                "BULLS",
    "vodacom_bulls":        "BULLS",
    "cardiff":              "CARDIFF",
    "cardiff_rugby":        "CARDIFF",
    "connacht":             "CONNACHT",
    "dragons":              "DRAGONS",
    "edinburgh":            "EDINBURGH",
    "glasgow":              "GLASGOW",
    "glasgow_warriors":     "GLASGOW",
    "leinster":             "LEINSTER",
    "lions":                "LIONS",
    "emirates_lions":       "LIONS",
    "munster":              "MUNSTER",
    "ospreys":              "OSPREYS",
    "scarlets":             "SCARLETS",
    "sharks":               "SHARKS",
    "hollywoodbets_sharks": "SHARKS",
    "stormers":             "STORMERS",
    "dhl_stormers":         "STORMERS",
    "ulster":               "ULSTER",
    "zebre":                "ZEBRE",
}

# Super Rugby Pacific — 12 franchises
SUPER_RUGBY_DISPLAY: dict[str, str] = {
    "blues":                "BLUES",
    "brumbies":             "BRUMBIES",
    "chiefs":               "CHIEFS",
    "crusaders":            "CRUSADERS",
    "fijian_drua":          "DRUA",
    "highlanders":          "HIGHLANDERS",
    "hurricanes":           "HURRICANES",
    "moana_pasifika":       "MOANA",
    "queensland_reds":      "REDS",
    "reds":                 "REDS",
    "rebels":               "REBELS",
    "waratahs":             "WARATAHS",
    "western_force":        "FORCE",
}

# International rugby
INTL_RUGBY_DISPLAY: dict[str, str] = {
    "south_africa":         "BOKS",
    "new_zealand":          "ALL BLACKS",
    "australia":            "WALLABIES",
    "argentina":             "PUMAS",
    "england":              "ENGLAND",
    "ireland":              "IRELAND",
    "scotland":             "SCOTLAND",
    "wales":                "WALES",
    "france":               "FRANCE",
    "italy":                "ITALY",
    "fiji":                 "FIJI",
    "samoa":                "SAMOA",
    "tonga":                "TONGA",
    "japan":                "JAPAN",
}

# International cricket
INTL_CRICKET_DISPLAY: dict[str, str] = {
    "south_africa":             "PROTEAS",
    "south_africa_women":       "PROTEAS W",
    "new_zealand":              "BLACKCAPS",
    "new_zealand_women":        "WHITE FERNS",
    "australia":                "AUSSIES",
    "australia_women":          "AUSSIES W",
    "england":                  "ENGLAND",
    "england_women":            "ENGLAND W",
    "india":                    "INDIA",
    "india_women":              "INDIA W",
    "pakistan":                 "PAKISTAN",
    "pakistan_women":           "PAKISTAN W",
    "sri_lanka":                "SL",
    "bangladesh":               "BAN",
    "afghanistan":              "AFG",
    "west_indies":              "WI",
    "ireland":                  "IRELAND",
    "zimbabwe":                 "ZIM",
    "nepal":                    "NEPAL",
    "oman":                     "OMAN",
    "united_arab_emirates":     "UAE",
    "usa_women":                "USA W",
    "vanuatu":                  "VANUATU",
    "rwanda":                   "RWANDA",
    "luxembourg":               "LUX",
}

# SA20 / CSA franchises
SA20_DISPLAY: dict[str, str] = {
    "durban_super_giants":      "DSG",
    "joburg_super_kings":       "JSK",
    "mi_cape_town":             "MICT",
    "paarl_royals":             "PR",
    "pretoria_capitals":        "PC",
    "sunrisers_eastern_cape":   "SEC",
}

# International soccer (national)
INTL_SOCCER_DISPLAY: dict[str, str] = {
    "south_africa":         "BAFANA",
    "south_africa_women":   "BANYANA",
    "nigeria":              "NIGERIA",
    "ghana":                "GHANA",
    "egypt":                "EGYPT",
    "morocco":              "MOROCCO",
    "senegal":              "SENEGAL",
    "england":              "ENGLAND",
    "france":               "FRANCE",
    "germany":              "GERMANY",
    "spain":                "SPAIN",
    "portugal":             "PORTUGAL",
    "brazil":               "BRAZIL",
    "argentina":            "ARGENTINA",
}

# La Liga / Bundesliga / Serie A / Ligue 1 / UCL frequent flyers
EURO_CLUBS_DISPLAY: dict[str, str] = {
    "atletico_madrid":          "ATLETICO",
    "real_madrid":              "REAL",
    "barcelona":                "BARCELONA",
    "sevilla":                  "SEVILLA",
    "valencia":                 "VALENCIA",
    "bayern_munich":            "BAYERN",
    "borussia_dortmund":        "DORTMUND",
    "rb_leipzig":               "LEIPZIG",
    "leverkusen":               "LEVERKUSEN",
    "bayer_leverkusen":         "LEVERKUSEN",
    "juventus":                 "JUVE",
    "inter":                    "INTER",
    "inter_milan":              "INTER",
    "ac_milan":                 "MILAN",
    "milan":                    "MILAN",
    "napoli":                   "NAPOLI",
    "roma":                     "ROMA",
    "lazio":                    "LAZIO",
    "atalanta":                 "ATALANTA",
    "paris_saint_germain":      "PSG",
    "psg":                      "PSG",
    "olympique_lyon":           "LYON",
    "lyon":                     "LYON",
    "marseille":                "MARSEILLE",
    "monaco":                   "MONACO",
    "ajax":                     "AJAX",
    "porto":                    "PORTO",
    "benfica":                  "BENFICA",
    "celtic":                   "CELTIC",
    "rangers":                  "RANGERS",
    "al_ahli_saudi_fc":         "AL AHLI",
    "shabab_al_ahli_dubai":     "SHABAB AHLI",
    "vissel_kobe":              "VISSEL",
}

# Sport key → ordered list of display dicts to consult.
# The ordering encodes priority: e.g. for ``rugby``, URC takes priority over
# Super Rugby, then international names. For ``cricket``, IPL > SA20 > intl.
_SPORT_LOOKUP: dict[str, tuple[dict[str, str], ...]] = {
    "soccer":   (PSL_DISPLAY, EPL_DISPLAY, EURO_CLUBS_DISPLAY, INTL_SOCCER_DISPLAY),
    "rugby":    (URC_DISPLAY, SUPER_RUGBY_DISPLAY, INTL_RUGBY_DISPLAY),
    "cricket":  (IPL_DISPLAY, SA20_DISPLAY, INTL_CRICKET_DISPLAY),
    # combat: no abbreviations — fighters render with full name (title-cased)
    "combat":   (),
    "boxing":   (),
    "mma":      (),
}


def _normalise_input(team: str) -> str:
    """Strip + lowercase, collapse spaces to underscores. Idempotent across
    raw match-key (``punjab_kings``), upper match-key (``PUNJAB_KINGS``), and
    spaced display (``Punjab Kings``)."""
    s = (team or "").strip().lower()
    s = "_".join(s.split())  # collapse whitespace + spaces to underscores
    return s


def _fallback(team: str) -> str:
    """Return a reasonable uppercase fallback when no map entry exists.

    For 1–2 token names (``arsenal``, ``ipswich``, ``benfica``) returns the full
    name uppercased. For 3+ token names (``manchester_united``,
    ``royal_challengers_bengaluru``), prefers the longest word — usually the
    most identifying token.
    """
    key = _normalise_input(team)
    if not key:
        return ""
    parts = [p for p in key.split("_") if p]
    if len(parts) <= 2:
        return " ".join(p.upper() for p in parts)
    longest = max(parts, key=len)
    return longest.upper()


def display_team_name(match_key_team: str, sport: str = "") -> str:
    """Return the canonical short display for a team.

    The match_key form (``punjab_kings``), uppercase form (``PUNJAB_KINGS``),
    and spaced form (``Punjab Kings``) all resolve to the same display value
    (``PBKS``) when an entry exists.

    Sport-aware: the lookup walks the dicts for the named sport in priority
    order, then falls back to all dicts. Disambiguates same-named teams across
    sports (e.g. ``lions`` resolves to URC LIONS for rugby, falls through for
    other sports).

    Unmapped teams fall back to last-token capitalisation per the brief
    contract — e.g. ``arsenal`` → ``ARSENAL``.
    """
    key = _normalise_input(match_key_team)
    if not key:
        return ""

    sport_key = (sport or "").strip().lower()
    dicts = _SPORT_LOOKUP.get(sport_key, ())
    for d in dicts:
        if key in d:
            return d[key]

    # Sport-blind fallback — teams whose sport is unknown still resolve.
    for d in (
        IPL_DISPLAY,
        PSL_DISPLAY,
        EPL_DISPLAY,
        URC_DISPLAY,
        SUPER_RUGBY_DISPLAY,
        EURO_CLUBS_DISPLAY,
        SA20_DISPLAY,
    ):
        if key in d:
            return d[key]

    return _fallback(key)


def known_team_count() -> dict[str, int]:
    """Diagnostic: count entries per sport map (used by the audit script)."""
    return {
        "ipl": len(IPL_DISPLAY),
        "psl": len(PSL_DISPLAY),
        "epl": len(EPL_DISPLAY),
        "urc": len(URC_DISPLAY),
        "super_rugby": len(SUPER_RUGBY_DISPLAY),
        "intl_rugby": len(INTL_RUGBY_DISPLAY),
        "intl_cricket": len(INTL_CRICKET_DISPLAY),
        "intl_soccer": len(INTL_SOCCER_DISPLAY),
        "sa20": len(SA20_DISPLAY),
        "euro_clubs": len(EURO_CLUBS_DISPLAY),
    }
