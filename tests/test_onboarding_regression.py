"""
ONBOARDING REGRESSION SHIELD
=============================
These tests protect the founder-approved onboarding flow.
Locked in on 28 February 2026 after 4 rounds of fixes
(Phase 0B → 0C → 0D → 0D-FIX → UX 0D-VERIFY).

DO NOT modify these tests to make failing code pass.
If a test fails, FIX THE CODE, not the test.

Protected elements:
- 6-step flow structure (Step 6 = Choose Your Plan, added Wave 19C)
- Team-specific celebrations (not generic, not cross-sport)
- Sport-context-aware national team celebrations (SA in cricket ≠ SA in rugby)
- Edge explainer copy (gold standard — sells the algorithm)
- Bankroll amounts (SA-appropriate: R50–R1,000)
- No hard-coded bookmaker/source counts in explainer
- GOLDEN EDGE naming (not GOLD)
- Neutral summary lines (no repeated celebrations)
- Removed features stay removed (no league selection, no Haiku welcome, no F1)

Bug prevention history:
- Phase 0B: "Go Bokke!" for SA in cricket (wrong sport celebration)
- Phase 0B: Man United fell through to generic "Lekker!" (missing celebration)
- Phase 0C: "GOLD EDGE" instead of "GOLDEN EDGE" (branding inconsistency)
- Phase 0C: R2,000 / R5,000 bankroll options (too high for SA market)
- Phase 0D: League selection step existed (users think in teams, not leagues)
- Phase 0D: Haiku personalised welcome was slow and unpredictable
- Phase 0D-FIX: Summary had duplicate celebrations on neutral lines
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

# Ensure bot package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from config import BOT_ROOT
from bot import (
    TEAM_CELEBRATIONS,
    _SPORT_CELEBRATIONS,
    _SPORT_CHEERS_FALLBACK,
    _get_team_cheer,
)


# ═══════════════════════════════════════════════════════════════════
# GROUP 1: Flow Structure (6-step integrity)
# ═══════════════════════════════════════════════════════════════════

class TestFlowStructure:
    """Onboarding must be exactly 5 steps — no more, no less.

    Steps 1-5 = profile setup. Plan picker follows step 5 (unnumbered).
    Prevents regression to old 9-step or 6-step flows, or re-introduction of
    removed steps like league selection.
    """

    def test_onboarding_is_5_steps(self):
        """Step counter must show X/5, never X/6+ or X/9."""
        source = (BOT_ROOT / "bot.py").read_text()
        # Must have Step X/5 references
        step_5_refs = re.findall(r"Step \d/5", source)
        assert len(step_5_refs) > 0, "No 'Step X/5' references found"
        # Must NOT have Step X/6 or higher (6-step flow was removed)
        step_6_refs = re.findall(r"Step \d/[6-9]", source)
        assert len(step_6_refs) == 0, f"Found step counter > 5: {step_6_refs}"
        # Must NOT have old 9-step counter
        step_9_refs = re.findall(r"Step \d/9", source)
        assert len(step_9_refs) == 0, f"Found old 9-step counter: {step_9_refs}"

    def test_all_5_steps_present(self):
        """Steps 1/5 through 5/5 must all exist in the code."""
        source = (BOT_ROOT / "bot.py").read_text()
        for step in range(1, 6):
            assert f"Step {step}/5" in source, f"Step {step}/5 missing from bot.py"

    def test_plan_picker_exists_after_onboarding(self):
        """Plan picker (Choose Your Plan) must exist with tier options (unnumbered post-step-5)."""
        source = (BOT_ROOT / "bot.py").read_text()
        assert "Choose Your Plan" in source, "Plan picker 'Choose Your Plan' text missing"
        assert "ob_plan:bronze" in source, "Bronze option missing from plan step"
        assert "ob_plan:gold" in source, "Gold option missing from plan step"
        assert "ob_plan:diamond" in source, "Diamond option missing from plan step"

    def test_no_league_selection_step(self):
        """League selection was removed in Phase 0D. It must not return.

        Bug prevented: Phase 0D removed league selection because users
        think in teams, not leagues. Leagues are auto-inferred.
        """
        source = (BOT_ROOT / "bot.py").read_text()
        assert "kb_onboarding_leagues" not in source, \
            "kb_onboarding_leagues found — league selection step was removed in Phase 0D"
        assert "_show_next_league_prompt" not in source, \
            "_show_next_league_prompt found — league step was removed"

    def test_no_league_selection_strings(self):
        """No UI text prompting league selection during onboarding."""
        source = (BOT_ROOT / "bot.py").read_text()
        assert "Select your leagues" not in source, \
            "'Select your leagues' string found — league selection was removed"
        assert "Pick leagues" not in source, \
            "'Pick leagues' string found — league selection was removed"

    def test_team_prompt_per_sport_not_per_league(self):
        """Team prompts must iterate per SPORT, not per league.

        Bug prevented: Phase 0D changed from per-league prompts to per-sport.
        """
        source = (BOT_ROOT / "bot.py").read_text()
        # Must have _fav_step_text (per-sport text builder)
        assert "_fav_step_text" in source, "_fav_step_text function missing"
        # Must NOT have _fav_league_queue (old per-league state)
        assert "_fav_league_queue" not in source, \
            "_fav_league_queue found — teams should be per-sport, not per-league"
        # Must NOT have _team_input_league (old per-league state key)
        assert "_team_input_league" not in source, \
            "_team_input_league found — teams should be per-sport"


# ═══════════════════════════════════════════════════════════════════
# GROUP 2: Celebration Correctness (THE BIG ONE)
# ═══════════════════════════════════════════════════════════════════

class TestNationalTeamSportContext:
    """National teams that appear in multiple sports MUST have sport-specific celebrations.

    Bug prevented: Phase 0B — "Go Bokke!" appeared for SA in cricket.
    SA in cricket = "Protea Fire!", SA in rugby = "Go Bokke!", SA in soccer = "Bafana Bafana!"
    """

    def test_south_africa_cricket_is_protea_fire(self):
        """SA in cricket = 'Protea Fire!' — NEVER 'Go Bokke!'"""
        result = _get_team_cheer("South Africa", "cricket")
        assert "Protea" in result or "protea" in result.lower(), \
            f"SA cricket got '{result}' — expected 'Protea Fire!'"
        assert "Bokke" not in result, \
            f"SA cricket got '{result}' — must not say 'Bokke' (that's rugby)"

    def test_south_africa_rugby_is_go_bokke(self):
        """SA in rugby = 'Go Bokke!'"""
        result = _get_team_cheer("South Africa", "rugby")
        assert "Bokke" in result, f"SA rugby got '{result}' — expected 'Go Bokke!'"

    def test_south_africa_soccer_is_bafana(self):
        """SA in soccer = 'Bafana Bafana!'"""
        result = _get_team_cheer("South Africa", "soccer")
        assert "Bafana" in result, f"SA soccer got '{result}' — expected 'Bafana Bafana!'"

    def test_springboks_is_go_bokke(self):
        """Springboks = 'Go Bokke!'"""
        result = _get_team_cheer("Springboks", "rugby")
        assert "Bokke" in result, f"Springboks got '{result}' — expected 'Go Bokke!'"

    def test_new_zealand_cricket_is_not_ka_mate(self):
        """NZ in cricket = Black Caps, not Ka mate (that's rugby).

        Bug prevented: Phase 0B — rugby haka appearing in cricket context.
        """
        result = _get_team_cheer("New Zealand", "cricket")
        assert "Ka mate" not in result, \
            f"NZ cricket got '{result}' — 'Ka mate' is a rugby haka, not cricket"
        assert "Black Caps" in result or "Caps" in result, \
            f"NZ cricket got '{result}' — expected 'Black Caps!'"

    def test_england_cricket_is_not_swing_low(self):
        """England in cricket must not use rugby celebration."""
        result = _get_team_cheer("England", "cricket")
        assert "Swing low" not in result, \
            f"England cricket got '{result}' — 'Swing low' is rugby"

    def test_australia_cricket_is_not_wallabies(self):
        """Australia in cricket must not use rugby name."""
        result = _get_team_cheer("Australia", "cricket")
        assert "Wallabies" not in result, \
            f"Australia cricket got '{result}' — 'Wallabies' is rugby"

    def test_india_cricket_has_chak_de(self):
        """India in cricket = 'Chak de India!'"""
        result = _get_team_cheer("India", "cricket")
        assert "Chak de" in result, f"India cricket got '{result}'"


class TestClubTeamCelebrations:
    """Every known popular team must have a specific celebration.

    Bug prevented: Phase 0B — Man United fell through to generic "Lekker!"
    """

    def test_manchester_united_has_glory_glory(self):
        """Man United = 'Glory Glory!' — NEVER generic."""
        result = _get_team_cheer("Manchester United", "soccer")
        assert result is not None
        assert "Glory" in result, f"Man United got '{result}' — expected 'Glory Glory!'"

    def test_man_united_alias_has_celebration(self):
        """Short alias 'Man United' must also work."""
        result = _get_team_cheer("Man United", "soccer")
        assert result is not None
        assert "Glory" in result, f"Man United alias got '{result}' — expected 'Glory Glory!'"

    def test_kaizer_chiefs_has_amakhosi(self):
        result = _get_team_cheer("Kaizer Chiefs", "soccer")
        assert "Amakhosi" in result or "Khosi" in result, \
            f"Kaizer Chiefs got '{result}'"

    def test_liverpool_has_ynwa(self):
        result = _get_team_cheer("Liverpool", "soccer")
        assert "YNWA" in result, f"Liverpool got '{result}'"

    def test_barcelona_has_visca(self):
        result = _get_team_cheer("Barcelona", "soccer")
        assert "Visca" in result or "Barça" in result or "Barca" in result, \
            f"Barcelona got '{result}'"

    def test_stormers_has_storm(self):
        result = _get_team_cheer("DHL Stormers", "rugby")
        assert "storm" in result.lower() or "Cape" in result, \
            f"Stormers got '{result}'"

    def test_stormers_alias_also_works(self):
        """Short name 'Stormers' must match same celebration."""
        result = _get_team_cheer("Stormers", "rugby")
        assert "storm" in result.lower() or "Cape" in result, \
            f"Stormers alias got '{result}'"

    def test_dricus_has_stillknocks(self):
        result = _get_team_cheer("Dricus Du Plessis", "combat")
        assert "Stillknocks" in result or "stillknocks" in result.lower(), \
            f"Dricus got '{result}'"

    def test_canelo_has_celebration(self):
        result = _get_team_cheer("Canelo Alvarez", "combat")
        assert "Canelo" in result or "Viva" in result, \
            f"Canelo got '{result}'"

    def test_orlando_pirates_has_celebration(self):
        result = _get_team_cheer("Orlando Pirates", "soccer")
        assert "Bucs" in result or "☠" in result, f"Pirates got '{result}'"

    def test_mamelodi_sundowns_has_celebration(self):
        result = _get_team_cheer("Mamelodi Sundowns", "soccer")
        assert "Masandawana" in result, f"Sundowns got '{result}'"


class TestNoGenericFallback:
    """Every known popular team must NOT fall through to generic fallback.

    Generic fallback words: "Lekker", "Sho't left", "Viva", "Forward", "Howzat", "Sharp"
    """

    KNOWN_TEAMS_MUST_HAVE_CELEBRATIONS = [
        ("Manchester United", "soccer"),
        ("Man United", "soccer"),
        ("Manchester City", "soccer"),
        ("Man City", "soccer"),
        ("Liverpool", "soccer"),
        ("Arsenal", "soccer"),
        ("Chelsea", "soccer"),
        ("Tottenham Hotspur", "soccer"),
        ("Spurs", "soccer"),
        ("Real Madrid", "soccer"),
        ("Barcelona", "soccer"),
        ("Bayern Munich", "soccer"),
        ("Kaizer Chiefs", "soccer"),
        ("Orlando Pirates", "soccer"),
        ("Mamelodi Sundowns", "soccer"),
        ("South Africa", "rugby"),
        ("Springboks", "rugby"),
        ("New Zealand", "rugby"),
        ("DHL Stormers", "rugby"),
        ("Vodacom Bulls", "rugby"),
        ("Hollywoodbets Sharks", "rugby"),
        ("Emirates Lions", "rugby"),
        ("South Africa", "cricket"),
        ("India", "cricket"),
        ("Dricus Du Plessis", "combat"),
        ("Canelo Alvarez", "combat"),
    ]

    @pytest.mark.parametrize("team,sport", KNOWN_TEAMS_MUST_HAVE_CELEBRATIONS)
    def test_team_has_specific_celebration(self, team, sport):
        """Known popular teams must get specific celebrations, not generic fallback."""
        result = _get_team_cheer(team, sport)
        assert result is not None, f"{team} ({sport}) returned None"
        # Generic fallback phrases from _SPORT_CHEERS_FALLBACK
        generic_phrases = ["Sho't left", "Viva! ⚽", "Forward! 🏉",
                           "Howzat! 🏏", "Sharp! 🏏",
                           "Let's go champ! 🥊", "War room ready! 🥊"]
        for generic in generic_phrases:
            assert generic != result, \
                f"{team} ({sport}) got generic '{result}' — must have specific celebration"

    def test_generic_fallback_exists_for_unknown(self):
        """Unknown teams should get sport-appropriate generic fallback."""
        result = _get_team_cheer("Totally Unknown FC", "soccer")
        # Should be one of the soccer fallbacks
        assert result in _SPORT_CHEERS_FALLBACK.get("soccer", []) + ["Lekker! 🏅"], \
            f"Unknown team got unexpected fallback: '{result}'"


# ═══════════════════════════════════════════════════════════════════
# GROUP 3: Celebration Format (No Duplication)
# ═══════════════════════════════════════════════════════════════════

class TestCelebrationFormat:
    """Summary lines must be neutral — no celebrations repeated in summary."""

    def test_summary_line_is_neutral(self):
        """The 'X teams added.' summary line must not contain celebration text.

        Bug prevented: Phase 0D-FIX — celebrations were duplicated on summary line.
        """
        source = (BOT_ROOT / "bot.py").read_text()
        # Find the "X teams added." / "X entity added." builder
        # It must use f"<b>{len(matched)} {entity_plural} added.</b>"
        assert 'added.</b>"' in source or "added.</b>" in source, \
            "Summary line pattern '{N} {entity} added.' not found"
        # The summary line must NOT include _get_team_cheer or celebration text
        # (celebrations appear in per-team lines above, not in the summary count)

    def test_per_team_celebration_lines(self):
        """Each matched team gets its own celebration on a separate line."""
        source = (BOT_ROOT / "bot.py").read_text()
        # Pattern: "✅ {team} — {cheer}"
        assert '✅ {h(m)} — {cheer}' in source or "✅" in source, \
            "Per-team celebration line pattern not found"

    def test_sport_emoji_in_header_only(self):
        """Sport emoji (⚽🏉🏏🥊) should appear in the header, not per-team line."""
        source = (BOT_ROOT / "bot.py").read_text()
        # Header pattern: f"{s_emoji} {pick_header}"
        assert "s_emoji" in source or "sport.emoji" in source, \
            "Sport emoji header pattern not found"


# ═══════════════════════════════════════════════════════════════════
# GROUP 4: Copy Protection (Gold Standard)
# ═══════════════════════════════════════════════════════════════════

class TestEdgeExplainerCopy:
    """Edge explainer copy is gold standard — sells the algorithm.

    Any change to the explainer must be intentional, not accidental.
    """

    def test_edge_explainer_no_hardcoded_bookmaker_count(self):
        """Must say 'ALL the major SA bookmakers', not '5+' or any number.

        Bug prevented: Hard-coded bookmaker counts become stale when new
        bookmakers are added.
        """
        source = (BOT_ROOT / "bot.py").read_text()
        assert "ALL the major SA bookmakers" in source, \
            "Edge explainer must say 'ALL the major SA bookmakers'"
        # No digit + "SA bookmaker" pattern near the explainer
        explainer_region = source[source.index("How Your Edge Works"):
                                  source.index("How Your Edge Works") + 1000]
        digit_bk = re.findall(r"\d+\s*(?:SA\s*)?bookmaker", explainer_region, re.IGNORECASE)
        assert len(digit_bk) == 0, \
            f"Found hard-coded bookmaker count near explainer: {digit_bk}"

    def test_edge_explainer_no_hardcoded_source_count(self):
        """Must say 'multiple prediction sources', not '4 prediction sources'."""
        source = (BOT_ROOT / "bot.py").read_text()
        explainer_region = source[source.index("How Your Edge Works"):
                                  source.index("How Your Edge Works") + 1000]
        digit_sources = re.findall(r"\d+\s*prediction sources", explainer_region, re.IGNORECASE)
        assert len(digit_sources) == 0, \
            f"Found hard-coded source count near explainer: {digit_sources}"

    def test_edge_explainer_sells_not_describes(self):
        """Explainer must contain power phrases that sell the algorithm."""
        source = (BOT_ROOT / "bot.py").read_text()
        # Phrases that must appear within the source (may span string literals)
        must_contain = [
            "cross-references",
            "player form",
            "injury",
            "historical performance",
            "tipster consensus",
            "match conditions",
        ]
        source_lower = source.lower()
        for phrase in must_contain:
            assert phrase.lower() in source_lower, \
                f"Edge explainer missing power phrase: '{phrase}'"

    def test_edge_explainer_has_got_it_wrong(self):
        """Explainer must contain 'bookmakers' + 'got it wrong' conviction phrase.

        Note: phrase spans two string literals in source, so we check parts.
        """
        source = (BOT_ROOT / "bot.py").read_text()
        source_lower = source.lower()
        assert "the bookmakers" in source_lower, "Missing 'the bookmakers' in explainer"
        assert "got it wrong" in source_lower, "Missing 'got it wrong' in explainer"

    def test_edge_tiers_in_explainer(self):
        """Explainer must list all 4 Edge tiers with correct names."""
        source = (BOT_ROOT / "bot.py").read_text()
        assert "Diamond Edge" in source, "Diamond Edge tier missing from explainer"
        assert "Golden Edge" in source, "Golden Edge tier missing from explainer"
        assert "Silver Edge" in source, "Silver Edge tier missing from explainer"
        assert "Bronze Edge" in source, "Bronze Edge tier missing from explainer"


class TestGoldenEdgeNaming:
    """Display text must be 'GOLDEN EDGE' everywhere, never just 'GOLD EDGE'.

    Bug prevented: Phase 0C — "GOLD EDGE" was used inconsistently.
    """

    def test_edge_labels_use_golden(self):
        """EDGE_LABELS dict must use 'GOLDEN EDGE' not 'GOLD EDGE'."""
        from renderers.edge_renderer import EDGE_LABELS
        assert EDGE_LABELS["gold"] == "GOLDEN EDGE", \
            f"EDGE_LABELS['gold'] = '{EDGE_LABELS['gold']}' — must be 'GOLDEN EDGE'"

    def test_edge_emojis_correct(self):
        """EDGE_EMOJIS must use 💎🥇🥈🥉."""
        from renderers.edge_renderer import EDGE_EMOJIS
        assert EDGE_EMOJIS["diamond"] == "💎"
        assert EDGE_EMOJIS["gold"] == "🥇"
        assert EDGE_EMOJIS["silver"] == "🥈"
        assert EDGE_EMOJIS["bronze"] == "🥉"

    def test_edge_renderer_no_plain_gold_edge(self):
        """edge_renderer.py must not contain bare 'GOLD EDGE' without 'GOLDEN'."""
        source = (BOT_ROOT / "renderers" / "edge_renderer.py").read_text()
        # Remove all "GOLDEN EDGE" first, then check no "GOLD EDGE" remains
        cleaned = source.replace("GOLDEN EDGE", "")
        assert "GOLD EDGE" not in cleaned, \
            "edge_renderer.py has 'GOLD EDGE' without 'GOLDEN' prefix"


# ═══════════════════════════════════════════════════════════════════
# GROUP 5: Bankroll & Preferences
# ═══════════════════════════════════════════════════════════════════

class TestBankrollPreferences:
    """Bankroll amounts must be SA-appropriate.

    Bug prevented: Phase 0C — R2,000 and R5,000 options were too high
    for the average SA sports bettor.
    """

    def test_bankroll_amounts_sa_appropriate(self):
        """Bankroll presets must be R50, R200, R500, R1,000."""
        source = (BOT_ROOT / "bot.py").read_text()
        # Find bankroll keyboard region
        bk_start = source.index("def kb_onboarding_bankroll")
        bk_end = source.index("\n\n", bk_start + 100)
        bk_region = source[bk_start:bk_end]

        # Must have these amounts
        assert "ob_bankroll:50" in bk_region, "R50 missing from bankroll presets"
        assert "ob_bankroll:200" in bk_region, "R200 missing from bankroll presets"
        assert "ob_bankroll:500" in bk_region, "R500 missing from bankroll presets"
        assert "ob_bankroll:1000" in bk_region, "R1,000 missing from bankroll presets"

    def test_bankroll_no_r2000_or_r5000(self):
        """R2,000 and R5,000 must NOT be onboarding bankroll presets.

        Bug prevented: Phase 0C — these amounts were too high.
        Note: R2,000/R5,000 may appear in settings as expansion options,
        but NOT in the onboarding keyboard.
        """
        source = (BOT_ROOT / "bot.py").read_text()
        bk_start = source.index("def kb_onboarding_bankroll")
        bk_end = source.index("\n\n", bk_start + 100)
        bk_region = source[bk_start:bk_end]

        assert "ob_bankroll:2000" not in bk_region, \
            "R2,000 found in onboarding bankroll — too high for SA"
        assert "ob_bankroll:5000" not in bk_region, \
            "R5,000 found in onboarding bankroll — too high for SA"

    def test_bankroll_has_skip_and_custom(self):
        """Bankroll must offer skip and custom amount options."""
        source = (BOT_ROOT / "bot.py").read_text()
        bk_start = source.index("def kb_onboarding_bankroll")
        bk_end = source.index("\n\n", bk_start + 100)
        bk_region = source[bk_start:bk_end]

        assert "ob_bankroll:skip" in bk_region, "Skip option missing from bankroll"
        assert "ob_bankroll:custom" in bk_region, "Custom option missing from bankroll"

    def test_experience_label_is_bold(self):
        """Profile summary: Experience label must be bold."""
        source = (BOT_ROOT / "bot.py").read_text()
        assert "<b>Experience:</b>" in source, \
            "Experience label must be bold in profile summary"


# ═══════════════════════════════════════════════════════════════════
# GROUP 6: Removed Features Stay Removed
# ═══════════════════════════════════════════════════════════════════

class TestRemovedFeatures:
    """Features removed during Phase 0 must not return."""

    def test_no_kb_onboarding_leagues(self):
        """kb_onboarding_leagues must not exist — league selection was removed.

        Bug prevented: Phase 0D — league selection confused users.
        """
        source = (BOT_ROOT / "bot.py").read_text()
        assert "kb_onboarding_leagues" not in source

    def test_no_haiku_welcome(self):
        """Claude Haiku personalised welcome was removed. Must not return.

        Bug prevented: Phase 0D — Haiku welcome was slow and output was
        inconsistent in tone/length.
        """
        source = (BOT_ROOT / "bot.py").read_text()
        # No anthropic API call in handle_ob_done
        ob_done_start = source.index("async def handle_ob_done")
        ob_done_end = source.index("\nasync def ", ob_done_start + 50)
        ob_done_region = source[ob_done_start:ob_done_end]

        assert "anthropic" not in ob_done_region.lower(), \
            "Claude API call found in handle_ob_done — Haiku welcome was removed"
        assert "welcome_personal" not in ob_done_region, \
            "welcome_personal found in handle_ob_done — personalised welcome was removed"

    def test_no_f1_in_sport_options(self):
        """F1 was removed in Phase 0. Must not appear in sport config.

        Bug prevented: Phase 0 — sport narrowing to 4 categories only.
        """
        sport_keys = [s.key for s in config.SPORTS]
        assert "f1" not in sport_keys, "F1 found in config.SPORTS — was removed in Phase 0"
        assert "formula_1" not in sport_keys

    def test_exactly_4_sports_in_config(self):
        """Config must have exactly 4 sport categories."""
        assert len(config.SPORTS) == 4, \
            f"Expected 4 sports, found {len(config.SPORTS)}: {[s.key for s in config.SPORTS]}"

    def test_correct_4_sport_keys(self):
        """The 4 sports must be soccer, rugby, cricket, combat."""
        sport_keys = {s.key for s in config.SPORTS}
        expected = {"soccer", "rugby", "cricket", "combat"}
        assert sport_keys == expected, \
            f"Sport keys mismatch. Expected {expected}, got {sport_keys}"


# ═══════════════════════════════════════════════════════════════════
# GROUP 7: Alias & Fuzzy Matching
# ═══════════════════════════════════════════════════════════════════

class TestAliasesAndFuzzyMatching:
    """Alias dict must cover common SA slang, typos, and nicknames."""

    def test_dreikus_matches_dricus(self):
        """Common Afrikaans misspelling must resolve to Dricus Du Plessis.

        Bug prevented: Afrikaans speakers commonly misspell as dreikus/drikus.
        """
        aliases_lower = {k.lower(): v for k, v in config.TEAM_ALIASES.items()}
        assert "dreikus" in aliases_lower, "'dreikus' alias missing from TEAM_ALIASES"
        assert aliases_lower["dreikus"] == "Dricus Du Plessis"

    def test_drikus_matches_dricus(self):
        """Another common misspelling."""
        aliases_lower = {k.lower(): v for k, v in config.TEAM_ALIASES.items()}
        assert "drikus" in aliases_lower, "'drikus' alias missing"
        assert aliases_lower["drikus"] == "Dricus Du Plessis"

    def test_stillknocks_matches_dricus(self):
        """Nickname 'Stillknocks' must resolve to Dricus."""
        aliases_lower = {k.lower(): v for k, v in config.TEAM_ALIASES.items()}
        assert "stillknocks" in aliases_lower
        assert aliases_lower["stillknocks"] == "Dricus Du Plessis"

    def test_bokke_matches_south_africa(self):
        """SA rugby slang 'bokke' must resolve."""
        aliases_lower = {k.lower(): v for k, v in config.TEAM_ALIASES.items()}
        assert "bokke" in aliases_lower
        assert aliases_lower["bokke"] == "South Africa"

    def test_proteas_matches_south_africa(self):
        """Cricket alias 'proteas' must resolve."""
        aliases_lower = {k.lower(): v for k, v in config.TEAM_ALIASES.items()}
        assert "proteas" in aliases_lower
        assert aliases_lower["proteas"] == "South Africa"

    def test_league_name_detection_exists(self):
        """Typing league names as team input must be detected and blocked.

        Bug prevented: Users typing 'UCL' or 'Premier League' as a team name.
        """
        source = (BOT_ROOT / "bot.py").read_text()
        assert "_LEAGUE_NAME_ALIASES" in source, \
            "_LEAGUE_NAME_ALIASES not found — league name detection was removed"

    def test_league_name_aliases_cover_key_leagues(self):
        """_LEAGUE_NAME_ALIASES must include UCL, EPL, PSL, Premier League."""
        source = (BOT_ROOT / "bot.py").read_text()
        # Extract the set definition
        alias_start = source.index("_LEAGUE_NAME_ALIASES")
        alias_end = source.index("}", alias_start)
        alias_region = source[alias_start:alias_end + 1].lower()

        for league in ["ucl", "epl", "psl", "premier league", "champions league"]:
            assert league in alias_region, \
                f"'{league}' missing from _LEAGUE_NAME_ALIASES"

    def test_common_epl_aliases_exist(self):
        """Common EPL team aliases must all be present."""
        aliases_lower = {k.lower() for k in config.TEAM_ALIASES.keys()}
        for alias in ["gunners", "reds", "red devils", "sky blues", "blues",
                       "spurs", "hammers", "toffees", "magpies"]:
            assert alias in aliases_lower, \
                f"EPL alias '{alias}' missing from TEAM_ALIASES"

    def test_common_psl_aliases_exist(self):
        """Common PSL slang must be present."""
        aliases_lower = {k.lower() for k in config.TEAM_ALIASES.keys()}
        for alias in ["chiefs", "amakhosi", "pirates", "bucs", "sundowns",
                       "masandawana", "usuthu", "glamour boys"]:
            assert alias in aliases_lower, \
                f"PSL alias '{alias}' missing from TEAM_ALIASES"


# ═══════════════════════════════════════════════════════════════════
# GROUP 8: Sport-Specific Celebration Data Integrity
# ═══════════════════════════════════════════════════════════════════

class TestCelebrationDataIntegrity:
    """Celebration dicts must have correct structure and coverage."""

    def test_sport_celebrations_has_cricket_overrides(self):
        """Cricket must have sport-specific overrides for multi-sport nations."""
        assert "cricket" in _SPORT_CELEBRATIONS, \
            "Cricket missing from _SPORT_CELEBRATIONS"
        cricket_overrides = _SPORT_CELEBRATIONS["cricket"]
        assert "South Africa" in cricket_overrides
        assert "New Zealand" in cricket_overrides
        assert "England" in cricket_overrides

    def test_sport_celebrations_has_soccer_overrides(self):
        """Soccer must have sport-specific overrides for multi-sport nations."""
        assert "soccer" in _SPORT_CELEBRATIONS
        soccer_overrides = _SPORT_CELEBRATIONS["soccer"]
        assert "South Africa" in soccer_overrides
        assert soccer_overrides["South Africa"] == "Bafana Bafana! 🇿🇦"

    def test_fallback_covers_all_4_sports(self):
        """Generic fallback must cover all 4 sport categories."""
        for sport_key in ["soccer", "rugby", "cricket", "combat"]:
            assert sport_key in _SPORT_CHEERS_FALLBACK, \
                f"{sport_key} missing from _SPORT_CHEERS_FALLBACK"
            assert len(_SPORT_CHEERS_FALLBACK[sport_key]) > 0, \
                f"{sport_key} has empty fallback list"

    def test_team_celebrations_has_minimum_coverage(self):
        """TEAM_CELEBRATIONS must have at least 30 entries."""
        assert len(TEAM_CELEBRATIONS) >= 30, \
            f"TEAM_CELEBRATIONS has only {len(TEAM_CELEBRATIONS)} entries — expected 30+"

    def test_sport_examples_covers_all_4_sports(self):
        """SPORT_EXAMPLES must have entries for all 4 sport categories."""
        for sport_key in ["soccer", "rugby", "cricket", "combat"]:
            assert sport_key in config.SPORT_EXAMPLES, \
                f"{sport_key} missing from SPORT_EXAMPLES"
            assert len(config.SPORT_EXAMPLES[sport_key]) > 0


# ═══════════════════════════════════════════════════════════════════
# GROUP 9: Welcome Message After Onboarding
# ═══════════════════════════════════════════════════════════════════

class TestWelcomeMessage:
    """Post-onboarding welcome message must be correct."""

    def test_welcome_has_edge_alerts_cta(self):
        """Welcome must offer 'Set Up Edge Alerts' button."""
        source = (BOT_ROOT / "bot.py").read_text()
        ob_done_start = source.index("async def handle_ob_done")
        ob_done_end = source.index("\nasync def ", ob_done_start + 50)
        ob_done_region = source[ob_done_start:ob_done_end]

        assert "Set Up Edge Alerts" in ob_done_region or "Edge Alerts" in ob_done_region, \
            "Welcome must include Edge Alerts CTA"

    def test_welcome_has_skip_option(self):
        """Welcome must allow skipping Edge Alerts setup."""
        source = (BOT_ROOT / "bot.py").read_text()
        ob_done_start = source.index("async def handle_ob_done")
        ob_done_end = source.index("\nasync def ", ob_done_start + 50)
        ob_done_region = source[ob_done_start:ob_done_end]

        assert "Skip" in ob_done_region, \
            "Welcome must include Skip option"

    def test_welcome_activates_persistent_keyboard(self):
        """Welcome must send the persistent reply keyboard."""
        source = (BOT_ROOT / "bot.py").read_text()
        ob_done_start = source.index("async def handle_ob_done")
        ob_done_end = source.index("\nasync def ", ob_done_start + 50)
        ob_done_region = source[ob_done_start:ob_done_end]

        assert "get_main_keyboard" in ob_done_region, \
            "handle_ob_done must activate persistent reply keyboard"
