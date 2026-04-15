"""team_data.py — Static lookup dicts for verdict personalisation.

NICKNAMES: never hallucinate — these are fixed and validated by the founder.
MANAGERS: flagged entries need founder verification before shipping (see notes).
"""

TEAM_NICKNAMES: dict[str, str] = {
    # === EPL ===
    "chelsea": "Chelsea",
    "manchester united": "United",
    "man united": "United",
    "liverpool": "The Reds",
    "arsenal": "The Gunners",
    "manchester city": "City",
    "man city": "City",
    "tottenham": "Spurs",
    "tottenham hotspur": "Spurs",
    "newcastle": "The Magpies",
    "newcastle united": "The Magpies",
    "aston villa": "Villa",
    "west ham": "The Hammers",
    "west ham united": "The Hammers",
    "brighton": "Brighton",
    "everton": "Everton",
    "fulham": "Fulham",
    "brentford": "Brentford",
    "crystal palace": "Palace",
    "wolves": "Wolves",
    "wolverhampton": "Wolves",
    "nottingham forest": "Forest",
    "leicester": "Leicester",
    "southampton": "Saints",
    "ipswich": "Ipswich",
    "bournemouth": "Bournemouth",
    # === PSL ===
    "kaizer chiefs": "Amakhosi",
    "orlando pirates": "The Bucs",
    "mamelodi sundowns": "The Brazilians",
    "ts galaxy": "Galaxy",
    "sekhukhune united": "Babina Ntwa",
    "richards bay": "Richards Bay",
    "cape town city": "The Citizens",
    "stellenbosch": "Stellies",
    "chippa united": "The Chilli Boys",
    "supersport united": "Matsatsantsa",
    "golden arrows": "Arrows",
    "amazulu": "Usuthu",
    "polokwane city": "Rise and Shine",
    "moroka swallows": "The Birds",
    "durban city": "Durban City",
    "royal am": "Royal AM",
    # === Super Rugby ===
    "blues": "Blues",
    "hurricanes": "Canes",
    "chiefs": "Chiefs",
    "crusaders": "Crusaders",
    "highlanders": "Landers",
    "brumbies": "Brumbies",
    "reds": "Reds",
    "waratahs": "Tahs",
    "bulls": "Bulls",
    "sharks": "Sharks",
    "lions": "Lions",
    "stormers": "Stormers",
    "moana pasifika": "Moana",
    "fijian drua": "Drua",
    # === Champions League (use plain names) ===
    "real madrid": "Real",
    "barcelona": "Barca",
    "bayern munich": "Bayern",
    "psg": "PSG",
    "paris saint-germain": "PSG",
    "inter milan": "Inter",
    "ac milan": "Milan",
    "juventus": "Juve",
    "atletico madrid": "Atletico",
    "borussia dortmund": "Dortmund",
}

# MANAGERS — verified for EPL as at April 2026.
# ⚠️ PSL and Super Rugby entries marked TBC — founder must verify before shipping.
# Leave as empty string if uncertain. Sonnet skips manager name if field is empty.
TEAM_MANAGERS: dict[str, str] = {
    # === EPL (high confidence) ===
    "chelsea": "Maresca",
    "manchester united": "",          # INV-VERDICT-COACH-FABRICATION-01: removed stale name — use evidence_pack
    "man united": "",                  # INV-VERDICT-COACH-FABRICATION-01: removed stale name — use evidence_pack
    "liverpool": "Slot",
    "arsenal": "Arteta",
    "manchester city": "Guardiola",
    "man city": "Guardiola",
    "tottenham": "Postecoglou",    # ⚠️ TBC — may have changed by Apr 2026
    "tottenham hotspur": "Postecoglou",
    "newcastle": "Howe",
    "aston villa": "Emery",
    "west ham": "",               # ⚠️ TBC
    "everton": "",                # ⚠️ TBC
    "fulham": "Silva",
    "crystal palace": "",         # ⚠️ TBC
    "nottingham forest": "Nuno",  # ⚠️ TBC
    # === PSL (founder to verify ALL) ===
    "kaizer chiefs": "",           # ⚠️ TBC — Paul to verify
    "orlando pirates": "",         # ⚠️ TBC — Paul to verify
    "mamelodi sundowns": "",       # ⚠️ TBC — Paul to verify
    "ts galaxy": "",               # ⚠️ TBC
    # === Super Rugby (founder to verify ALL) ===
    "blues": "",                   # ⚠️ TBC
    "hurricanes": "",              # ⚠️ TBC
    "chiefs": "",                  # ⚠️ TBC
    "crusaders": "",               # ⚠️ TBC
    "bulls": "",                   # ⚠️ TBC
    "sharks": "",                  # ⚠️ TBC
    "stormers": "",                # ⚠️ TBC
}


def get_nickname(team_name: str) -> str:
    """Returns nickname if found, else original name. Case-insensitive."""
    return TEAM_NICKNAMES.get(team_name.lower().strip(), team_name)


def get_manager(team_name: str) -> str:
    """Returns manager surname if found and non-empty, else empty string."""
    return TEAM_MANAGERS.get(team_name.lower().strip(), "")


def form_to_plain(form_list: list[str], team_name: str = "") -> str:
    """Convert a form list like ['W','L','L','L','W'] to plain English.

    Most-recent result is the LAST item in the list (already reversed upstream).
    """
    if not form_list:
        return ""
    n = len(form_list)
    wins = form_list.count("W")
    losses = form_list.count("L")
    draws = form_list.count("D")
    recent3 = form_list[-3:]
    recent_wins = recent3.count("W")
    recent_losses = recent3.count("L")

    if wins >= 4:
        return f"won {wins} of their last {n}"
    elif wins >= 3 and losses <= 1:
        return f"in strong form — {wins} wins from their last {n}"
    elif losses >= 4:
        return f"in terrible form — {losses} losses from their last {n}"
    elif losses >= 3:
        return f"struggling — lost {losses} of their last {n}"
    elif recent_losses >= 2 and losses >= 3:
        return f"lost {losses} of their last {n} with {recent_losses} in the last three"
    elif recent_wins >= 2:
        return f"picked up {recent_wins} wins in their last 3"
    elif draws >= 3:
        return f"drawn {draws} of their last {n}"
    else:
        return f"{wins} wins and {losses} losses from their last {n}"
