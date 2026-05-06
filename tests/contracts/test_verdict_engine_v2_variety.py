from verdict_engine_v2 import VerdictContext, render_verdict_v2


TEAMS = (
    ("Liverpool", "Chelsea", "Slot", "the Reds", "Anfield"),
    ("Manchester City", "Brentford", "Guardiola", "City", "Etihad Stadium"),
    ("Arsenal", "Tottenham", "Arteta", "the Gunners", "Emirates Stadium"),
    ("Sundowns", "Orlando Pirates", "Mngqithi", "Sundowns", "Loftus"),
    ("Kaizer Chiefs", "Stellenbosch", "Nabi", "Amakhosi", "FNB Stadium"),
    ("Bulls", "Stormers", "White", "the Bulls", "Loftus"),
    ("Sharks", "Lions", "Plumtree", "the Sharks", "Kings Park"),
    ("Chennai Super Kings", "Delhi Capitals", "Fleming", "Chennai", "Chepauk"),
    ("Mumbai Indians", "Royal Challengers Bengaluru", "Jayawardene", "Mumbai", "Wankhede"),
    ("England", "Ireland", "Borthwick", "England", "Twickenham"),
    ("France", "Wales", "Galthie", "France", "Stade de France"),
    ("Crusaders", "Blues", "Penney", "the Crusaders", "Apollo Projects Stadium"),
)


def primary_clause(text: str) -> str:
    if "—" in text:
        return text.split("—", 1)[0].strip()
    if "." in text:
        return text.split(".", 1)[0].strip()
    return text.strip()


def price_form_ctx(index: int) -> VerdictContext:
    home, away, coach, nickname, venue = TEAMS[index % len(TEAMS)]
    sport = "cricket" if "Chennai" in home or "Mumbai" in home else "rugby" if home in {"Bulls", "Sharks", "England", "France", "Crusaders"} else "soccer"
    league = "ipl" if sport == "cricket" else "urc" if sport == "rugby" else "epl"
    return VerdictContext(
        match_key=f"{home.lower().replace(' ', '_')}_vs_{away.lower().replace(' ', '_')}_{index}",
        edge_revision="rev-1",
        sport=sport,
        league=league,
        home_name=home,
        away_name=away,
        recommended_team=home,
        outcome_label=home,
        odds=f"{1.72 + (index % 9) / 20:.2f}",
        bookmaker=("Supabets", "Betway", "Hollywoodbets")[index % 3],
        tier="gold",
        signals={
            "price_edge": {"available": True},
            "form_h2h": {"available": True},
        },
        venue=venue,
        coach=coach,
        nickname=nickname,
    )


def mixed_ctx(index: int) -> VerdictContext:
    base = price_form_ctx(index)
    signal_sets = (
        {
            "price_edge": {"available": True},
            "form_h2h": {"available": True},
            "market_agreement": {"available": True, "bookmaker_count": 4},
        },
        {
            "price_edge": {"available": True},
            "lineup_injury": {"available": True},
        },
        {
            "price_edge": {"available": True},
            "movement": {"available": True, "direction": "toward"},
        },
        {
            "price_edge": {"available": True},
            "market_agreement": {"available": True, "bookmaker_count": 5},
            "tipster": {"available": True},
        },
        {
            "price_edge": {"available": True},
            "form_h2h": {"available": True},
            "lineup_injury": {"available": True},
            "movement": {"available": True, "direction": "against"},
        },
    )
    return VerdictContext(
        **{
            **base.__dict__,
            "match_key": f"{base.match_key}_mixed_{index}",
            "signals": signal_sets[index % len(signal_sets)],
            "line_movement_direction": "toward" if index % 5 == 2 else "against" if index % 5 == 4 else None,
            "tier": ("diamond", "gold", "silver", "bronze")[index % 4],
        }
    )


def test_price_form_heavy_24_card_slate_has_at_least_15_distinct_primary_clauses():
    verdicts = [render_verdict_v2(price_form_ctx(index)) for index in range(24)]

    assert all(verdict.valid for verdict in verdicts)
    assert len({primary_clause(verdict.text) for verdict in verdicts}) >= 15


def test_mixed_core7_slate_has_at_least_18_distinct_primary_clauses():
    verdicts = [render_verdict_v2(mixed_ctx(index)) for index in range(24)]

    assert all(verdict.valid for verdict in verdicts)
    assert len({primary_clause(verdict.text) for verdict in verdicts}) >= 18


def test_no_exact_duplicate_verdicts_in_24_card_slate():
    verdicts = [render_verdict_v2(price_form_ctx(index)).text for index in range(24)]

    assert len(set(verdicts)) == 24


def test_same_match_and_revision_byte_identical_across_repeated_calls():
    context = mixed_ctx(7)

    verdicts = [render_verdict_v2(context).text for _ in range(100)]

    assert len(set(verdicts)) == 1
