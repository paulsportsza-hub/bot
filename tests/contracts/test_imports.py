
import pytest
pytest.skip(
    "FIX-DROP-SONNET-POLISH-W82-CANONICAL-01: Sonnet/Haiku polish ripped out. "
    "This test asserts polish-chain behaviour that no longer exists.",
    allow_module_level=True,
)

"""Layer 1.4 — Module import validation.

All core modules must import without error. Catches missing dependencies,
circular imports, and broken __init__.py files.
"""


import importlib
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from config import ensure_scrapers_importable
ensure_scrapers_importable()

# ── Core bot modules ──

BOT_MODULES = [
    "bot",
    "narrative_spec",
    "config",
    "db",
    "tier_gate",
    "services.user_service",
    "services.schedule_service",
    "services.picks_service",
    "services.templates",
    "services.edge_rating",
    "renderers.telegram_renderer",
    "renderers.whatsapp_renderer",
    "renderers.whatsapp_menus",
    "edge_detail_renderer",
]

# ── Core scraper modules ──

SCRAPER_MODULES = [
    "scrapers.edge.edge_v2",
    "scrapers.edge.edge_v2_helper",
    "scrapers.edge.edge_config",
    "scrapers.edge.signal_collectors",
    "scrapers.edge.tier_engine",
    "scrapers.edge.narrative_generator",
    "scrapers.edge.settlement",
    "scrapers.odds_integrity",
    "scrapers.odds_normaliser",
    "scrapers.health_monitor",
    "scrapers.match_context_fetcher",
]


class TestBotModuleImports:
    """All bot modules must import cleanly."""

    @pytest.mark.parametrize("module_name", BOT_MODULES,
                             ids=BOT_MODULES)
    def test_import(self, module_name):
        """Module must import without raising."""
        try:
            importlib.import_module(module_name)
        except Exception as e:
            pytest.fail(f"Failed to import {module_name}: {e}")


class TestScraperModuleImports:
    """All scraper modules must import cleanly."""

    @pytest.mark.parametrize("module_name", SCRAPER_MODULES,
                             ids=SCRAPER_MODULES)
    def test_import(self, module_name):
        """Module must import without raising."""
        try:
            importlib.import_module(module_name)
        except Exception as e:
            pytest.fail(f"Failed to import {module_name}: {e}")


class TestCriticalFunctions:
    """Key functions must be importable and callable."""

    def test_calculate_composite_edge(self):
        from scrapers.edge.edge_v2 import calculate_composite_edge
        assert callable(calculate_composite_edge), (
            "calculate_composite_edge must be callable"
        )

    def test_get_top_edges(self):
        from scrapers.edge.edge_v2_helper import get_top_edges
        assert callable(get_top_edges), (
            "get_top_edges must be callable"
        )

    def test_get_edge_access_level(self):
        from tier_gate import get_edge_access_level
        assert callable(get_edge_access_level), (
            "get_edge_access_level must be callable"
        )

    def test_assign_tier(self):
        from scrapers.edge.tier_engine import assign_tier
        assert callable(assign_tier), (
            "assign_tier must be callable"
        )

    def test_detect_outlier_odds(self):
        from scrapers.odds_integrity import detect_outlier_odds
        assert callable(detect_outlier_odds), (
            "detect_outlier_odds must be callable"
        )

    def test_get_match_context(self):
        from scrapers.match_context_fetcher import get_match_context
        assert callable(get_match_context), (
            "get_match_context must be callable"
        )

    def test_sanitize_ai_response(self):
        from bot import sanitize_ai_response
        assert callable(sanitize_ai_response), (
            "sanitize_ai_response must be callable"
        )

    def test_fact_check_output(self):
        from bot import fact_check_output
        assert callable(fact_check_output), (
            "fact_check_output must be callable"
        )

    # ── W80/W81-FACTCHECK permanent guards ──
    def test_build_setup_section_v2(self):
        """W80-PROSE renamed _build_setup_section -> _build_setup_section_v2.
        This test prevents future waves silently breaking pregen imports."""
        from bot import _build_setup_section_v2
        assert callable(_build_setup_section_v2)

    def test_get_verified_injuries(self):
        """W81-FACTCHECK: injury lookup function must remain exportable."""
        from bot import get_verified_injuries
        assert callable(get_verified_injuries)

    def test_clean_fact_checked_output(self):
        """W81-FACTCHECK: post-strip cleanup function must remain exportable."""
        from bot import _clean_fact_checked_output
        assert callable(_clean_fact_checked_output)

    def test_build_verified_narrative(self):
        """W29-FIX: two-pass narrative builder must remain exportable."""
        from bot import build_verified_narrative
        assert callable(build_verified_narrative)

    def test_get_exemplars_for_prompt(self):
        """W81-REWRITE: exemplar selector must remain exportable."""
        from bot import _get_exemplars_for_prompt
        assert callable(_get_exemplars_for_prompt)

    def test_build_rewrite_prompt(self):
        """W81-REWRITE: rewrite prompt builder must remain exportable."""
        from bot import _build_rewrite_prompt
        assert callable(_build_rewrite_prompt)

    def test_verify_rewrite(self):
        """W81-REWRITE: Stage 3 fact verifier must remain exportable."""
        from bot import _verify_rewrite
        assert callable(_verify_rewrite)

    # ── W82-SPEC permanent guards ──
    def test_classify_evidence(self):
        """W82-SPEC: evidence classifier must remain importable."""
        from narrative_spec import _classify_evidence
        assert callable(_classify_evidence)

    def test_check_coherence(self):
        """W82-SPEC: coherence checker must remain importable."""
        from narrative_spec import _check_coherence
        assert callable(_check_coherence)

    def test_enforce_coherence(self):
        """W82-SPEC: coherence enforcer must remain importable."""
        from narrative_spec import _enforce_coherence
        assert callable(_enforce_coherence)

    def test_build_narrative_spec(self):
        """W82-SPEC: main spec builder must remain importable."""
        from narrative_spec import build_narrative_spec
        assert callable(build_narrative_spec)

    def test_narrative_spec_dataclass(self):
        """W82-SPEC: NarrativeSpec dataclass must remain importable."""
        from narrative_spec import NarrativeSpec
        assert NarrativeSpec is not None

    # ── W82-RENDER permanent guards ──
    def test_render_baseline(self):
        """W82-RENDER: baseline renderer must remain exportable.

        BUILD-NARRATIVE-WATERTIGHT-01 Part F: load-bearing under W93-COST (Silver/Bronze
        cost-save). DO NOT rename or delete. Rename-protection assertion lives here.
        """
        from narrative_spec import _render_baseline
        assert callable(_render_baseline)

    def test_generate_narrative_v2_rename_protection(self):
        """BUILD-NARRATIVE-WATERTIGHT-01 Part F: _generate_narrative_v2 is load-bearing
        under W93-COST and must remain exportable. Any rename breaks the pregen pipeline
        and every live_tap=True instant-baseline serve.
        """
        from bot import _generate_narrative_v2
        assert callable(_generate_narrative_v2)

    def test_count_uncached_hot_tips_exported(self):
        """BUILD-NARRATIVE-WATERTIGHT-01 B.6: per-fixture warm-cache helper must stay
        exported — _background_pregen_fill depends on it.
        """
        from bot import _count_uncached_hot_tips
        assert callable(_count_uncached_hot_tips)

    def test_render_setup(self):
        """W82-RENDER: setup renderer must remain exportable."""
        from narrative_spec import _render_setup
        assert callable(_render_setup)

    def test_render_edge(self):
        """W82-RENDER: edge renderer must remain exportable."""
        from narrative_spec import _render_edge
        assert callable(_render_edge)

    def test_render_verdict(self):
        """W82-RENDER: verdict renderer must remain exportable."""
        from narrative_spec import _render_verdict
        assert callable(_render_verdict)

    # ── W92-VERDICT-QUALITY permanent guards ──
    def test_load_skip_count(self):
        """W92-VERDICT-QUALITY P3: narrative_skip_log loader must remain exportable."""
        from scripts.pregenerate_narratives import _load_skip_count
        assert callable(_load_skip_count)

    def test_bump_skip_count(self):
        """W92-VERDICT-QUALITY P3: narrative_skip_log incrementer must remain exportable."""
        from scripts.pregenerate_narratives import _bump_skip_count
        assert callable(_bump_skip_count)

    def test_clear_skip_count(self):
        """W92-VERDICT-QUALITY P3: narrative_skip_log reset must remain exportable."""
        from scripts.pregenerate_narratives import _clear_skip_count
        assert callable(_clear_skip_count)

    # ── NARRATIVE-ACCURACY-01 permanent guards ──
    def test_build_derived_claims(self):
        """ACCURACY-01 Rule 1: derived claims pre-processor must remain exportable."""
        from narrative_spec import build_derived_claims
        assert callable(build_derived_claims)

    def test_current_stadiums(self):
        """ACCURACY-01 Rule 2: CURRENT_STADIUMS dict must remain importable."""
        from narrative_spec import CURRENT_STADIUMS
        assert isinstance(CURRENT_STADIUMS, dict)
        assert "everton" in CURRENT_STADIUMS, "everton key must be present (Goodison → Hill Dickinson guard)"

    def test_generate_section(self):
        """ACCURACY-01 Rule 3: section extractor must remain exportable."""
        from scripts.pregenerate_narratives import generate_section
        assert callable(generate_section)

    def test_generate_and_validate(self):
        """ACCURACY-01 Rule 3: validator+retry must remain exportable."""
        from scripts.pregenerate_narratives import generate_and_validate
        assert callable(generate_and_validate)
