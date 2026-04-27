"""Contract test: Currie Cup + Rugby Championship bridge wired (BUILD-CORE7-BRIDGE-01).

Asserts that the Jun-Aug rugby bridge leagues are present in every layer that
must know about them for edge generation to flow:

  AC-1: TARGET_LEAGUES in scrapers/api_sports_rugby.py (fixture + standings)
  AC-2: LEAGUE_TO_SPORT in scrapers/edge/edge_config.py
  AC-3: SA_ONLY_LEAGUES (no Odds API key for either league as of 27 Apr 2026)
  AC-4: RUGBY_LEAGUES in scrapers/sharp/rugby_consensus_sharp.py
        (SA Shin consensus → sharp_odds bridge — required for price_edge signal)
  AC-5: RUGBY_LEAGUES in scrapers/elo/results_collector.py (ESPN settlement)
  AC-6: At least one core SA bookmaker has each league mapped (price feed exists)
  AC-7: ESPN league IDs probe-verified at audit time
        Currie Cup = 270555, Rugby Championship = 244293

The Odds API does NOT have sport keys for either league (probe 27 Apr 2026
returned only rugbyleague_nrl, rugbyleague_nrl_state_of_origin,
rugbyunion_six_nations). Sharp benchmark therefore must come from the SA
consensus bridge — without these tests guarding the bridge's RUGBY_LEAGUES
tuple, a regression silently disables sharp coverage for the whole bridge.
"""

import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


BRIDGE_LEAGUES = ("currie_cup", "rugby_championship")


# ── AC-1: rugby fixture scraper covers both leagues ──────────────────────

def test_api_sports_rugby_target_leagues_includes_bridge():
    from scrapers.api_sports_rugby import TARGET_LEAGUES

    league_keys = {v for v in TARGET_LEAGUES.values()}
    # Names in the scraper are display labels; canonicalise to keys.
    canonical = {n.lower().replace(" ", "_") for n in league_keys}
    assert "currie_cup" in canonical, (
        f"Currie Cup missing from api_sports_rugby.TARGET_LEAGUES — "
        f"saw: {sorted(canonical)}"
    )
    assert "rugby_championship" in canonical, (
        f"Rugby Championship missing from api_sports_rugby.TARGET_LEAGUES — "
        f"saw: {sorted(canonical)}"
    )


# ── AC-2 + AC-3: edge_config knows the leagues are rugby + SA-only ───────

def test_edge_config_league_to_sport_includes_bridge():
    from scrapers.edge.edge_config import LEAGUE_TO_SPORT

    for league in BRIDGE_LEAGUES:
        assert LEAGUE_TO_SPORT.get(league) == "rugby", (
            f"{league} not mapped to sport='rugby' in edge_config.LEAGUE_TO_SPORT — "
            f"signal_collectors will fall through to default weights and no rugby "
            f"profile will apply."
        )


def test_edge_config_sa_only_leagues_includes_bridge():
    from scrapers.edge.edge_config import SA_ONLY_LEAGUES

    for league in BRIDGE_LEAGUES:
        assert league in SA_ONLY_LEAGUES, (
            f"{league} not in SA_ONLY_LEAGUES — has_sharp_coverage() will return "
            f"True and price_edge will look for non-existent Pinnacle/Betfair rows. "
            f"Both leagues lack Odds API keys (probe 27 Apr 2026)."
        )


# ── AC-4: SA consensus bridge writes sharp_odds for both leagues ──────────

def test_rugby_consensus_sharp_includes_bridge_leagues():
    from scrapers.sharp.rugby_consensus_sharp import RUGBY_LEAGUES

    for league in BRIDGE_LEAGUES:
        assert league in RUGBY_LEAGUES, (
            f"{league} not in rugby_consensus_sharp.RUGBY_LEAGUES — Shin de-vig "
            f"consensus rows will not be written to sharp_odds for this league, "
            f"and edge generation will lack the price_edge signal."
        )


# ── AC-5: ESPN settlement covers both leagues ────────────────────────────

def test_results_collector_rugby_leagues_includes_bridge():
    from scrapers.elo.results_collector import RUGBY_LEAGUES

    for league in BRIDGE_LEAGUES:
        assert league in RUGBY_LEAGUES, (
            f"{league} not in results_collector.RUGBY_LEAGUES — ESPN match results "
            f"won't be ingested and Glicko-2 ratings will go stale."
        )

    # ESPN IDs verified live on 27 Apr 2026 against api.espn.com:
    #   270555 → Currie Cup
    #   244293 → The Rugby Championship
    assert RUGBY_LEAGUES["currie_cup"]["id"] == "270555"
    assert RUGBY_LEAGUES["rugby_championship"]["id"] == "244293"


# ── AC-6: at least one core SA bookmaker has each bridge league mapped ───

def test_at_least_one_core_bookmaker_has_each_bridge_league():
    """Currie Cup + Rugby Championship must be in at least one bookmaker's
    LEAGUE_CONFIG (or equivalent). Without bookmaker coverage the SA consensus
    bridge has no input rows.

    This intentionally tolerates per-bookmaker gaps (WSB, SuperSportBet may
    not yet have tags discovered) and only asserts the bridge has at least
    one feed per league.
    """
    coverage = {league: [] for league in BRIDGE_LEAGUES}

    bookmaker_files = (
        ("hollywoodbets", "/home/paulsportsza/scrapers/bookmakers/hollywoodbets.py"),
        ("betway", "/home/paulsportsza/scrapers/bookmakers/betway.py"),
        ("sportingbet", "/home/paulsportsza/scrapers/bookmakers/sportingbet.py"),
        ("gbets", "/home/paulsportsza/scrapers/bookmakers/gbets.py"),
        ("supabets", "/home/paulsportsza/scrapers/bookmakers/supabets.py"),
        ("playabets", "/home/paulsportsza/scrapers/bookmakers/playabets.py"),
    )
    # Source-file scan — robust to sys.path / module-state pollution from other
    # tests in the suite. Looks for `"<league>": {` keyed entries in LEAGUE_CONFIG.
    for short_name, path in bookmaker_files:
        try:
            with open(path, encoding="utf-8") as fh:
                src = fh.read()
        except OSError:
            continue
        for league in BRIDGE_LEAGUES:
            if f'"{league}":' in src or f"'{league}':" in src:
                coverage[league].append(short_name)

    for league, books in coverage.items():
        assert books, (
            f"No core SA bookmaker has {league} in LEAGUE_CONFIG — bridge has "
            f"no input rows for SA Shin consensus. Add the league to at least "
            f"one of hollywoodbets/betway/sportingbet/gbets/supabets/playabets."
        )
