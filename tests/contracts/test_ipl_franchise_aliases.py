"""FIX-CORE7-CRICKET-01 — Contract test: IPL franchise team-name normalisation.

Asserts that FORM_TEAM_ALIASES in form_analyser.py resolves all current and
historical IPL franchise name variants to their canonical match_results keys.

Canonical names (from ESPN / match_results table):
  - royal_challengers_bengaluru (renamed from bangalore 2023)
  - punjab_kings (renamed from kings_xi_punjab 2021)
  - delhi_capitals (renamed from delhi_daredevils 2019)
  - chennai_super_kings, mumbai_indians, kolkata_knight_riders
  - sunrisers_hyderabad, rajasthan_royals, gujarat_titans, lucknow_super_giants
"""
from __future__ import annotations

import os
import sys

import pytest

_BOT_DIR = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, _BOT_DIR)
import config
config.ensure_scrapers_importable()

from scrapers.form.form_analyser import FORM_TEAM_ALIASES, _resolve_team


# Canonical names as stored in match_results (ESPN source of truth)
_CANONICAL = {
    "royal_challengers_bengaluru",
    "punjab_kings",
    "delhi_capitals",
    "chennai_super_kings",
    "mumbai_indians",
    "kolkata_knight_riders",
    "sunrisers_hyderabad",
    "rajasthan_royals",
    "gujarat_titans",
    "lucknow_super_giants",
}

# Variants that must resolve to canonical — (variant, expected_canonical)
_ALIAS_CASES = [
    # RCB rename 2023
    ("royal_challengers_bangalore", "royal_challengers_bengaluru"),
    ("rcb", "royal_challengers_bengaluru"),
    # Punjab Kings rename 2021
    ("kings_xi_punjab", "punjab_kings"),
    ("kxip", "punjab_kings"),
    ("pbks", "punjab_kings"),
    # Delhi Capitals rename 2019
    ("delhi_daredevils", "delhi_capitals"),
    ("dd", "delhi_capitals"),
    ("dc", "delhi_capitals"),
    # Short-form aliases used by bookmaker pipelines
    ("csk", "chennai_super_kings"),
    ("mi", "mumbai_indians"),
    ("kkr", "kolkata_knight_riders"),
    ("srh", "sunrisers_hyderabad"),
    ("rr", "rajasthan_royals"),
    ("gt", "gujarat_titans"),
    ("lsg", "lucknow_super_giants"),
]

# Canonical names must pass through unchanged
_PASSTHROUGH_CASES = list(_CANONICAL)


class TestIPLFranchiseAliases:

    @pytest.mark.parametrize("variant,expected", _ALIAS_CASES)
    def test_alias_resolves(self, variant: str, expected: str):
        resolved = _resolve_team(variant)
        assert resolved == expected, (
            f"_resolve_team('{variant}') = '{resolved}', expected '{expected}'. "
            f"Add to FORM_TEAM_ALIASES in form_analyser.py."
        )

    @pytest.mark.parametrize("canonical", _PASSTHROUGH_CASES)
    def test_canonical_passthrough(self, canonical: str):
        resolved = _resolve_team(canonical)
        assert resolved == canonical, (
            f"Canonical team name '{canonical}' must pass through _resolve_team unchanged, "
            f"got '{resolved}'."
        )

    def test_all_aliases_resolve_to_canonical(self):
        """Every FORM_TEAM_ALIASES value that is an IPL team must be a canonical name."""
        ipl_aliases = {
            k: v for k, v in FORM_TEAM_ALIASES.items()
            if v in _CANONICAL
        }
        for variant, canonical in ipl_aliases.items():
            assert canonical in _CANONICAL, (
                f"FORM_TEAM_ALIASES['{variant}'] = '{canonical}' is not a canonical IPL name."
            )

    def test_bangalore_not_in_canonical(self):
        """royal_challengers_bangalore is an alias, not canonical — must resolve."""
        assert "royal_challengers_bangalore" not in _CANONICAL
        assert _resolve_team("royal_challengers_bangalore") == "royal_challengers_bengaluru"

    def test_kings_xi_not_in_canonical(self):
        assert "kings_xi_punjab" not in _CANONICAL
        assert _resolve_team("kings_xi_punjab") == "punjab_kings"

    def test_daredevils_not_in_canonical(self):
        assert "delhi_daredevils" not in _CANONICAL
        assert _resolve_team("delhi_daredevils") == "delhi_capitals"

    def test_form_signal_rcb_bangalore_resolves(self):
        """When match_key uses 'royal_challengers_bangalore', form lookup must
        find results for 'royal_challengers_bengaluru' via alias resolution.

        Validates the full normalisation pipeline end-to-end.
        """
        import sqlite3
        from scrapers.form.form_analyser import get_team_form

        # Build minimal in-memory DB with one match for RCB (canonical name)
        conn = sqlite3.connect(":memory:")
        conn.executescript("""
            CREATE TABLE match_results (
                id INTEGER PRIMARY KEY,
                match_key TEXT, home_team TEXT, away_team TEXT,
                home_score INTEGER, away_score INTEGER,
                result TEXT, match_date TEXT, league TEXT, sport TEXT
            );
        """)
        conn.execute("""
            INSERT INTO match_results
            (match_key, home_team, away_team, home_score, away_score, result, match_date, league, sport)
            VALUES
            ('royal_challengers_bengaluru_vs_mumbai_indians_2026-04-10',
             'royal_challengers_bengaluru', 'mumbai_indians',
             185, 170, 'home', '2026-04-10', 'ipl', 'cricket')
        """)
        conn.commit()

        # Query using the OLD name (what an edge_result match_key might contain)
        # After alias resolution, should find the row
        resolved = _resolve_team("royal_challengers_bangalore")
        rows = get_team_form(resolved, "ipl", conn, last_n=5)
        assert rows["wins"] == 1, (
            f"After resolving 'royal_challengers_bangalore' → 'royal_challengers_bengaluru', "
            f"get_team_form should find 1 match, got: {rows}"
        )

    def test_franchise_coverage_count(self):
        """At least 15 IPL-related alias entries must exist in FORM_TEAM_ALIASES."""
        ipl_aliases = {k: v for k, v in FORM_TEAM_ALIASES.items() if v in _CANONICAL}
        assert len(ipl_aliases) >= 15, (
            f"Expected >= 15 IPL franchise aliases, got {len(ipl_aliases)}: {ipl_aliases}"
        )
