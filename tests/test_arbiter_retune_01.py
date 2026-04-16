"""Tests for ARBITER-RETUNE-01 — 4 new sub-checks in score_card().

Covers:
  - Generic risk detection (structure sub-check a)
  - Template opener detection (structure sub-check b)
  - Synthesised fixture penalty (overall_feel sub-check a)
  - Cricket card without cricket terms (overall_feel sub-check b)
  - MMA card without MMA terms (overall_feel sub-check b)
  - Normal card — no spurious deductions
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

BOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BOT_DIR))
sys.path.insert(0, str(BOT_DIR / "scripts"))

import os
os.environ.setdefault("SENTRY_DSN", "")
os.environ.setdefault("BOT_TOKEN", "DUMMY")

from qa_baseline_02 import score_card  # noqa: E402


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_narrative(
    setup: str = "Arsenal host Newcastle in a fixture that should engage the defence.",
    edge: str = "The edge is priced in at Supabets. Lay it here.",
    risk: str = "There is genuine injury doubt in midfield — this matters.",
    verdict: str = "Back Arsenal.",
) -> str:
    """Build a 4-section narrative with emojis matching production format."""
    return (
        f"🎯 Arsenal vs Newcastle / 🏆 EPL\n\n"
        f"📋 <b>The Setup</b>\n{setup}\n\n"
        f"🎯 <b>The Edge</b>\n{edge}\n\n"
        f"⚠️ <b>The Risk</b>\n{risk}\n\n"
        f"🏆 <b>Verdict</b>\n{verdict}"
    )


_BASE_FX = {
    "bk": "Supabets",
    "odds": 1.53,
    "home": "Arsenal",
    "away": "Newcastle",
    "pick": "Home Win",
    "tier": "gold",
    "source": "DB: arsenal_vs_newcastle_2026-04-25",
    "sport": "soccer",
}

_GOOD_NARRATIVE = _make_narrative()
_GOOD_VERDICT = "Supabets have this underpriced. Back Arsenal."


# ─────────────────────────────────────────────────────────────────────────────
# 1. Structure sub-check (a) — Generic risk phrase → deduct -1
# ─────────────────────────────────────────────────────────────────────────────

class TestStructureGenericRisk:
    """score_card() deducts 1 from structure when Risk section is stock boilerplate."""

    def _score(self, risk_text: str) -> dict:
        narr = _make_narrative(risk=risk_text)
        return score_card(_BASE_FX, narr, _GOOD_VERDICT)

    def test_stock_phrase_price_and_signals_aligned(self):
        result = self._score("Price and signals are aligned. Typical match uncertainty applies.")
        s = result["scores"]["structure"]
        assert s <= 9, f"Expected structure ≤9 for generic risk, got {s}"
        reasons = result["reasons"]["structure"]
        assert any("Risk" in r for r in reasons), f"No Risk reason found: {reasons}"

    def test_stock_phrase_typical_match_uncertainty(self):
        result = self._score("Typical match uncertainty is the main remaining variable.")
        s = result["scores"]["structure"]
        assert s <= 9, f"Expected structure ≤9 for generic risk, got {s}"

    def test_stock_phrase_standard_match_volatility(self):
        result = self._score("Standard match volatility is the only real risk here.")
        s = result["scores"]["structure"]
        assert s <= 9, f"Expected structure ≤9 for generic risk, got {s}"

    def test_stock_phrase_normal_match_variance(self):
        result = self._score("Normal match variance applies — nothing specific flagged.")
        s = result["scores"]["structure"]
        assert s <= 9, f"Expected structure ≤9 for generic risk, got {s}"

    def test_short_risk_section_under_50_chars(self):
        result = self._score("Minor form concern.")   # <50 chars
        s = result["scores"]["structure"]
        assert s <= 9, f"Expected structure ≤9 for short risk, got {s}"

    def test_specific_risk_not_penalised(self):
        result = self._score(
            "The left back is a doubt — this could expose the flank. "
            "Away side have won the last three H2H away from home."
        )
        s = result["scores"]["structure"]
        # Should NOT deduct for generic risk (specific content)
        # Base score without bookmaker check should be >= 9 (may vary per card)
        assert "Risk section is generic or boilerplate" not in result["reasons"]["structure"], (
            "Specific risk section should not be flagged as generic"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 2. Structure sub-check (b) — Template opener → deduct -1
# ─────────────────────────────────────────────────────────────────────────────

class TestStructureTemplateOpener:
    """score_card() deducts 1 from structure when Setup opens with a template pattern."""

    def _score(self, setup_text: str) -> dict:
        narr = _make_narrative(setup=setup_text)
        return score_card(_BASE_FX, narr, _GOOD_VERDICT)

    def test_this_league_fixture_between(self):
        result = self._score(
            "This league fixture between Arsenal and Newcastle in Premier League "
            "should be approached with discipline."
        )
        s = result["scores"]["structure"]
        assert s <= 9, f"Expected structure ≤9 for template opener, got {s}"
        reasons = result["reasons"]["structure"]
        assert any("template opener" in r.lower() for r in reasons), f"No opener reason: {reasons}"

    def test_this_match_between(self):
        result = self._score(
            "This match between Arsenal and Newcastle will hinge on set pieces."
        )
        s = result["scores"]["structure"]
        assert s <= 9, f"Expected structure ≤9 for template opener, got {s}"

    def test_should_be_judged_through(self):
        result = self._score(
            "The season context should be judged through the lens of form and set pieces."
        )
        s = result["scores"]["structure"]
        assert s <= 9, f"Expected structure ≤9 for template opener, got {s}"

    def test_this_fixture_pits(self):
        result = self._score(
            "This fixture pits Arsenal's clinical attack against Newcastle's dogged back line."
        )
        s = result["scores"]["structure"]
        assert s <= 9, f"Expected structure ≤9 for template opener, got {s}"

    def test_organic_opener_not_penalised(self):
        result = self._score(
            "Arsenal have dropped just two points at home this season — that tells you "
            "something about the defensive structure Arteta has built."
        )
        reasons = result["reasons"]["structure"]
        assert "Setup section uses template opener" not in reasons, (
            "Organic Setup opener should not be flagged"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 3. Overall feel sub-check (a) — Synthesised fixture → deduct -1
# ─────────────────────────────────────────────────────────────────────────────

class TestOverallFeelSynthesised:
    """score_card() deducts 1 from overall_feel for synthesised fixtures."""

    def _score(self, source: str) -> dict:
        fx = dict(_BASE_FX, source=source)
        return score_card(fx, _GOOD_NARRATIVE, _GOOD_VERDICT)

    def test_synthesised_source_penalised(self):
        result = self._score("Synthesised: no Diamond soccer home-underdog in DB")
        f = result["scores"]["overall_feel"]
        assert f <= 8, f"Expected overall_feel ≤8 for synthesised fixture, got {f}"
        reasons = result["reasons"]["overall_feel"]
        assert any("Synthesised" in r for r in reasons), f"No synthesised reason: {reasons}"

    def test_synthesised_lowercase_penalised(self):
        result = self._score("synthesised from match_results hulk_vs_robot")
        f = result["scores"]["overall_feel"]
        assert f <= 8, f"Expected overall_feel ≤8 for synthesised (lowercase), got {f}"

    def test_synthetic_penalised(self):
        result = self._score("synthetic data for test cell")
        f = result["scores"]["overall_feel"]
        assert f <= 8, f"Expected overall_feel ≤8 for synthetic fixture, got {f}"

    def test_db_source_not_penalised(self):
        result = self._score("DB: arsenal_vs_newcastle_2026-04-25")
        reasons = result["reasons"]["overall_feel"]
        assert "Synthesised fixture" not in reasons, (
            "DB-sourced fixture should not be penalised as synthesised"
        )

    def test_fallback_source_not_penalised(self):
        result = self._score("Fallback from real edge data")
        reasons = result["reasons"]["overall_feel"]
        assert "Synthesised fixture" not in reasons, (
            "Fallback source should not be penalised as synthesised"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 4. Overall feel sub-check (b) — Cricket card without cricket terms → -1
# ─────────────────────────────────────────────────────────────────────────────

class TestOverallFeelCricket:
    """score_card() deducts 1 from overall_feel for cricket cards without cricket terms."""

    def _cricket_fx(self) -> dict:
        return dict(
            _BASE_FX,
            home="Chennai Super Kings",
            away="Delhi Capitals",
            sport="cricket",
            source="Synthesised",
        )

    def test_cricket_card_no_cricket_terms_penalised(self):
        narr = _make_narrative(
            setup="Both sides come in with similar form from the last week.",
            edge="The edge here is in the price — Betway has mispriced this.",
            risk="Generic uncertainty applies.",
        )
        fx = self._cricket_fx()
        result = score_card(fx, narr, _GOOD_VERDICT)
        f = result["scores"]["overall_feel"]
        reasons = result["reasons"]["overall_feel"]
        assert any("Cricket" in r for r in reasons), (
            f"Cricket penalty reason missing. Got: {reasons}"
        )

    def test_cricket_card_with_pitch_not_penalised(self):
        narr = _make_narrative(
            setup="The pitch at this venue tends to assist fast bowling early doors.",
            edge="Betway have this at 1.54 which looks generous.",
            risk="Toss could shift the dynamic here.",
        )
        fx = self._cricket_fx()
        result = score_card(fx, narr, _GOOD_VERDICT)
        reasons = result["reasons"]["overall_feel"]
        assert "Cricket card lacks sport-specific content" not in reasons, (
            "Cricket card with cricket terms should not be penalised"
        )

    def test_cricket_card_with_bowling_not_penalised(self):
        narr = _make_narrative(
            setup="The bowling attack is the strongest on display this tournament.",
            edge="Betway price is generous.",
            risk="Powerplay conditions are uncertain.",
        )
        fx = self._cricket_fx()
        result = score_card(fx, narr, _GOOD_VERDICT)
        reasons = result["reasons"]["overall_feel"]
        assert "Cricket card lacks sport-specific content" not in reasons

    def test_soccer_card_not_penalised_by_cricket_check(self):
        fx = dict(_BASE_FX, sport="soccer")
        result = score_card(fx, _GOOD_NARRATIVE, _GOOD_VERDICT)
        reasons = result["reasons"]["overall_feel"]
        assert "Cricket card lacks sport-specific content" not in reasons


# ─────────────────────────────────────────────────────────────────────────────
# 5. Overall feel sub-check (b) — MMA card without MMA terms → -1
# ─────────────────────────────────────────────────────────────────────────────

class TestOverallFeelMMA:
    """score_card() deducts 1 from overall_feel for MMA cards without MMA terms."""

    def _mma_fx(self) -> dict:
        return dict(
            _BASE_FX,
            home="Dricus Du Plessis",
            away="Sean Strickland",
            sport="mma",
            source="Synthesised",
        )

    def test_mma_card_no_mma_terms_penalised(self):
        narr = _make_narrative(
            setup="Two elite competitors come in with strong recent form.",
            edge="Betway has this priced short — the model says longer.",
            risk="Price and signals are broadly aligned here.",
        )
        fx = self._mma_fx()
        result = score_card(fx, narr, _GOOD_VERDICT)
        reasons = result["reasons"]["overall_feel"]
        assert any("MMA" in r for r in reasons), (
            f"MMA penalty reason missing. Got: {reasons}"
        )

    def test_mma_card_with_round_not_penalised(self):
        narr = _make_narrative(
            setup="The fight has a round 3 finish vibe — gassing is a real concern.",
            edge="Betway price is attractive at 1.55.",
            risk="Wrestling sprawl could change the finish type.",
        )
        fx = self._mma_fx()
        result = score_card(fx, narr, _GOOD_VERDICT)
        reasons = result["reasons"]["overall_feel"]
        assert "MMA card lacks sport-specific content" not in reasons, (
            "MMA card with MMA terms should not be penalised"
        )

    def test_mma_card_with_ko_not_penalised(self):
        narr = _make_narrative(
            setup="The KO threat from the favourite is the main variable.",
            edge="Betway price agrees with the model.",
            risk="Decision outcome would shift the market.",
        )
        fx = self._mma_fx()
        result = score_card(fx, narr, _GOOD_VERDICT)
        reasons = result["reasons"]["overall_feel"]
        assert "MMA card lacks sport-specific content" not in reasons

    def test_rugby_card_not_penalised_by_mma_check(self):
        fx = dict(_BASE_FX, sport="rugby")
        result = score_card(fx, _GOOD_NARRATIVE, _GOOD_VERDICT)
        reasons = result["reasons"]["overall_feel"]
        assert "MMA card lacks sport-specific content" not in reasons


# ─────────────────────────────────────────────────────────────────────────────
# 6. Normal card — no spurious deductions
# ─────────────────────────────────────────────────────────────────────────────

class TestNormalCardNoSpuriousDeductions:
    """A well-crafted card with specific content should not trigger any retune deductions."""

    def test_normal_soccer_card_no_retune_deductions(self):
        narr = _make_narrative(
            setup=(
                "Arsenal have been the most consistent home side in the division this term — "
                "nine wins from eleven, the best defensive record in the top half. "
                "Newcastle arrive without their first-choice striker and with two key defenders "
                "carrying knocks. The H2H at the Emirates reads 4-1 in Arsenal's favour "
                "over the past five meetings."
            ),
            edge=(
                "Supabets have this at 1.53 — the model puts fair probability at 67%, "
                "implying true decimal odds of 1.49. That 4c gap is the play."
            ),
            risk=(
                "Partey's fitness is not confirmed. If he misses, the midfield anchor role "
                "is filled by a player with 40% less duels-won rate — that matters when "
                "Newcastle's transition game is sharp."
            ),
        )
        fx = dict(_BASE_FX, source="DB: arsenal_vs_newcastle_2026-04-25", sport="soccer")
        result = score_card(fx, narr, "Supabets have this right. Back Arsenal.")
        reasons_s = result["reasons"]["structure"]
        reasons_f = result["reasons"]["overall_feel"]
        assert "Risk section is generic or boilerplate" not in reasons_s
        assert "Setup section uses template opener" not in reasons_s
        assert "Synthesised fixture" not in reasons_f

    def test_floor_at_7_not_below(self):
        """Structure and overall_feel floors should be 7, not lower."""
        # Provide a narrative with multiple issues to stress-test the floor
        narr = (
            "📋 <b>The Setup</b>\nThis match between X and Y should be judged through history.\n\n"
            "🎯 <b>The Edge</b>\nBetway offers 1.53.\n\n"
            "⚠️ <b>The Risk</b>\nPrice and signals are aligned.\n\n"
            "🏆 <b>Verdict</b>\nBack home."
        )
        fx = dict(
            _BASE_FX,
            source="Synthesised: test floor",
            sport="cricket",  # no cricket terms → additional feel deduction
        )
        result = score_card(fx, narr, "Back home.")
        assert result["scores"]["structure"] >= 7, "Structure floor violated (<7)"
        assert result["scores"]["overall_feel"] >= 7, "Overall feel floor violated (<7)"
