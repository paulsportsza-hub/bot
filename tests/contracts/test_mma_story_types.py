"""BUILD-ENRICH-08: Contract tests for MMA story type classification.

Covers:
(a) MMA ranking → story type mapping for each tier
(b) Record-based modifier application
(c) Missing data graceful fallback to neutral
(d) Non-MMA sports unaffected (zero regressions)
"""
from __future__ import annotations

import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def _load_decide_fn():
    """Extract _decide_team_story from bot.py without importing the full bot module.

    Importing bot.py initialises Sentry + PTB which requires live env vars.
    We extract + exec the function in isolation instead (same pattern as
    test_cricket_standings.py).
    """
    bot_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "bot.py",
    )
    with open(bot_path) as f:
        source = f.read()

    fn_match = re.search(
        r"(def _decide_team_story\(.*?)(?=\ndef |\nclass |\Z)",
        source,
        re.DOTALL,
    )
    assert fn_match, "_decide_team_story not found in bot.py"
    ns: dict = {}
    exec(fn_match.group(1), ns)  # noqa: S102
    return ns["_decide_team_story"]


@pytest.fixture(scope="module")
def decide():
    return _load_decide_fn()


# ── (a) Ranking tier mapping ───────────────────────────────────────────────

class TestMmaRankingTiers:
    """Contract: ranking position maps to correct base story type."""

    def test_rank_1_is_title_contender(self, decide):
        result = decide(pos=1, pts=None, form="", home_rec=None, away_rec=None, gpg=None, is_home=True, sport="mma")
        assert result == "title_contender"

    def test_rank_2_is_title_contender(self, decide):
        result = decide(pos=2, pts=None, form="", home_rec=None, away_rec=None, gpg=None, is_home=False, sport="mma")
        assert result == "title_contender"

    def test_rank_3_is_title_contender(self, decide):
        result = decide(pos=3, pts=None, form="", home_rec=None, away_rec=None, gpg=None, is_home=True, sport="mma")
        assert result == "title_contender"

    def test_rank_4_is_gatekeeper(self, decide):
        result = decide(pos=4, pts=None, form="", home_rec=None, away_rec=None, gpg=None, is_home=True, sport="mma")
        assert result == "gatekeeper"

    def test_rank_10_is_gatekeeper(self, decide):
        result = decide(pos=10, pts=None, form="", home_rec=None, away_rec=None, gpg=None, is_home=False, sport="mma")
        assert result == "gatekeeper"

    def test_rank_11_is_prospect(self, decide):
        result = decide(pos=11, pts=None, form="", home_rec=None, away_rec=None, gpg=None, is_home=True, sport="mma")
        assert result == "prospect"

    def test_rank_25_is_prospect(self, decide):
        result = decide(pos=25, pts=None, form="", home_rec=None, away_rec=None, gpg=None, is_home=False, sport="mma")
        assert result == "prospect"


# ── (b) Record-based modifier application ─────────────────────────────────

class TestMmaRecordModifiers:
    """Contract: fighter record applies correct modifier to base tier."""

    def test_dominant_modifier_on_title_contender(self, decide):
        # 22-3-0 → wins >= 20 and losses <= 5 → dominant
        result = decide(pos=2, pts=None, form="22-3-0", home_rec=None, away_rec=None, gpg=None, is_home=True, sport="mma")
        assert result == "title_contender_dominant"

    def test_dominant_modifier_on_gatekeeper(self, decide):
        result = decide(pos=7, pts=None, form="25-4-0", home_rec=None, away_rec=None, gpg=None, is_home=False, sport="mma")
        assert result == "gatekeeper_dominant"

    def test_dominant_modifier_on_prospect(self, decide):
        result = decide(pos=15, pts=None, form="20-5-0", home_rec=None, away_rec=None, gpg=None, is_home=True, sport="mma")
        assert result == "prospect_dominant"

    def test_dominant_boundary_exactly_20_wins_5_losses(self, decide):
        result = decide(pos=5, pts=None, form="20-5-0", home_rec=None, away_rec=None, gpg=None, is_home=True, sport="mma")
        assert result == "gatekeeper_dominant"

    def test_no_dominant_when_losses_exceed_5(self, decide):
        # 22-6-0 — wins ≥ 20 but losses > 5 → no dominant modifier
        result = decide(pos=2, pts=None, form="22-6-0", home_rec=None, away_rec=None, gpg=None, is_home=True, sport="mma")
        assert result == "title_contender"

    def test_no_dominant_when_wins_below_20(self, decide):
        # 19-4-0 — wins < 20 → no dominant modifier
        result = decide(pos=3, pts=None, form="19-4-0", home_rec=None, away_rec=None, gpg=None, is_home=True, sport="mma")
        assert result == "title_contender"

    def test_comeback_modifier_on_title_contender(self, decide):
        # losses > wins → comeback
        result = decide(pos=1, pts=None, form="8-10-0", home_rec=None, away_rec=None, gpg=None, is_home=True, sport="mma")
        assert result == "title_contender_comeback"

    def test_comeback_modifier_on_gatekeeper(self, decide):
        result = decide(pos=6, pts=None, form="5-8-0", home_rec=None, away_rec=None, gpg=None, is_home=False, sport="mma")
        assert result == "gatekeeper_comeback"

    def test_comeback_modifier_on_prospect(self, decide):
        result = decide(pos=12, pts=None, form="3-7-0", home_rec=None, away_rec=None, gpg=None, is_home=True, sport="mma")
        assert result == "prospect_comeback"

    def test_no_modifier_when_wins_equal_losses(self, decide):
        # Equal record — neither dominant nor comeback
        result = decide(pos=5, pts=None, form="10-10-0", home_rec=None, away_rec=None, gpg=None, is_home=False, sport="mma")
        assert result == "gatekeeper"

    def test_no_modifier_when_wins_slightly_ahead(self, decide):
        # 12-10 — wins > losses but not dominant
        result = decide(pos=8, pts=None, form="12-10-0", home_rec=None, away_rec=None, gpg=None, is_home=True, sport="mma")
        assert result == "gatekeeper"


# ── (c) Missing data / edge cases ─────────────────────────────────────────

class TestMmaMissingData:
    """Contract: missing data falls back gracefully."""

    def test_no_ranking_no_record_returns_neutral(self, decide):
        result = decide(pos=None, pts=None, form="", home_rec=None, away_rec=None, gpg=None, is_home=True, sport="mma")
        assert result == "neutral"

    def test_no_ranking_no_form_returns_neutral(self, decide):
        result = decide(pos=None, pts=None, form=None, home_rec=None, away_rec=None, gpg=None, is_home=False, sport="mma")
        assert result == "neutral"

    def test_ranking_only_no_record_returns_base_tier(self, decide):
        # Has ranking but form is empty — use tier only, no modifier
        result = decide(pos=3, pts=None, form="", home_rec=None, away_rec=None, gpg=None, is_home=True, sport="mma")
        assert result == "title_contender"

    def test_ranking_only_form_none_returns_base_tier(self, decide):
        result = decide(pos=7, pts=None, form=None, home_rec=None, away_rec=None, gpg=None, is_home=False, sport="mma")
        assert result == "gatekeeper"

    def test_record_only_dominant_no_ranking(self, decide):
        # No ranking, dominant record → "dominant"
        result = decide(pos=None, pts=None, form="25-3-0", home_rec=None, away_rec=None, gpg=None, is_home=True, sport="mma")
        assert result == "dominant"

    def test_record_only_comeback_no_ranking(self, decide):
        # No ranking, comeback record → "comeback"
        result = decide(pos=None, pts=None, form="4-9-0", home_rec=None, away_rec=None, gpg=None, is_home=False, sport="mma")
        assert result == "comeback"

    def test_record_only_neutral_no_ranking(self, decide):
        # No ranking, wins > losses but not dominant → "neutral"
        result = decide(pos=None, pts=None, form="10-5-0", home_rec=None, away_rec=None, gpg=None, is_home=True, sport="mma")
        assert result == "neutral"

    def test_malformed_record_falls_back_to_tier_only(self, decide):
        # Malformed form string — parser falls back to None, tier used alone
        result = decide(pos=5, pts=None, form="badrecord", home_rec=None, away_rec=None, gpg=None, is_home=True, sport="mma")
        assert result == "gatekeeper"

    def test_partial_record_single_number_falls_back(self, decide):
        # Only one number — no "-" separator
        result = decide(pos=2, pts=None, form="15", home_rec=None, away_rec=None, gpg=None, is_home=True, sport="mma")
        assert result == "title_contender"

    def test_non_numeric_record_falls_back_to_tier(self, decide):
        result = decide(pos=9, pts=None, form="W-L-D", home_rec=None, away_rec=None, gpg=None, is_home=False, sport="mma")
        assert result == "gatekeeper"

    def test_both_unranked_no_records_returns_neutral(self, decide):
        """Both fighters unranked with no records → neutral (current behaviour preserved)."""
        home = decide(pos=None, pts=None, form="", home_rec=None, away_rec=None, gpg=None, is_home=True, sport="mma")
        away = decide(pos=None, pts=None, form="", home_rec=None, away_rec=None, gpg=None, is_home=False, sport="mma")
        assert home == "neutral"
        assert away == "neutral"


# ── (d) Non-MMA sports unaffected ─────────────────────────────────────────

class TestNonMmaSportsUnaffected:
    """Contract: soccer/rugby/cricket story type logic is unchanged."""

    def test_soccer_title_push_unchanged(self, decide):
        result = decide(pos=1, pts=6, form="WWW", home_rec=None, away_rec=None, gpg=None, is_home=True, sport="soccer")
        assert result == "title_push"

    def test_soccer_crisis_unchanged(self, decide):
        result = decide(pos=14, pts=2, form="LLL", home_rec=None, away_rec=None, gpg=None, is_home=False, sport="soccer")
        assert result == "crisis"

    def test_soccer_neutral_no_data(self, decide):
        result = decide(pos=None, pts=None, form="", home_rec=None, away_rec=None, gpg=None, is_home=True, sport="soccer")
        assert result == "neutral"

    def test_soccer_momentum_unchanged(self, decide):
        result = decide(pos=6, pts=10, form="WW", home_rec=None, away_rec=None, gpg=None, is_home=True, sport="soccer")
        assert result == "momentum"

    def test_rugby_default_to_soccer_logic(self, decide):
        # sport="rugby" — no explicit rugby branch, falls through to soccer logic
        result = decide(pos=1, pts=6, form="WWW", home_rec=None, away_rec=None, gpg=None, is_home=True, sport="rugby")
        assert result == "title_push"

    def test_cricket_default_to_soccer_logic(self, decide):
        result = decide(pos=2, pts=4, form="WW", home_rec=None, away_rec=None, gpg=None, is_home=True, sport="cricket")
        assert result != "neutral"

    def test_default_sport_is_soccer(self, decide):
        """sport param defaults to 'soccer' — existing call sites without sport= arg are unaffected."""
        result = decide(pos=1, pts=6, form="WWW", home_rec=None, away_rec=None, gpg=None, is_home=True)
        assert result == "title_push"

    def test_boxing_has_no_mma_branch(self, decide):
        # sport="boxing" — not "mma", falls through to soccer logic
        result = decide(pos=None, pts=None, form="", home_rec=None, away_rec=None, gpg=None, is_home=True, sport="boxing")
        assert result == "neutral"
