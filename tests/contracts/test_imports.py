"""Layer 1.4 — Module import validation.

All core modules must import without error. Catches missing dependencies,
circular imports, and broken __init__.py files.
"""

from __future__ import annotations

import importlib
import os
import sys

import pytest

sys.path.insert(0, os.path.expanduser("~"))
sys.path.insert(0, os.path.join(os.path.expanduser("~"), "bot"))

# ── Core bot modules ──

BOT_MODULES = [
    "bot",
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
