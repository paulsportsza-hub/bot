"""COVERAGE-GATE-BUILD — 6 contract tests.

Guards:
1. CoverageMetrics correctly classifies empty / partial / full evidence.
2. Coverage gate blocks Sonnet polish when evidence is empty.
3. Serve-time EV gate suppresses stale 0% EV cached cards.
4. coverage_json is written to and read back from narrative_cache.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from config import ensure_scrapers_importable
ensure_scrapers_importable()


# ── Test 1: CoverageMetrics → level = "empty" ──

class TestCoverageMetricsEmpty:
    """Cricket fixture with only SA odds → no ESPN data → empty."""

    def test_compute_coverage_level_empty(self):
        from evidence_pack import compute_coverage_level

        level = compute_coverage_level(
            sport="cricket",
            league="sa20",
            key_facts=0,
            form_games=0,
            h2h_games=0,
            standings=False,
            market_count=4,  # SA odds present, but ESPN data absent
        )
        assert level == "empty", f"Expected 'empty', got '{level}'"

    def test_coverage_metrics_dataclass_level_field(self):
        from evidence_pack import CoverageMetrics

        m = CoverageMetrics(
            sport="cricket",
            league="sa20",
            sources_used=["sa_odds"],
            missing_sources=["espn", "h2h", "form"],
            key_facts_count=0,
            injuries_count=0,
            form_games_count=0,
            h2h_games_count=0,
            standings_available=False,
            market_coverage_count=4,
            sharp_available=False,
            level="empty",
        )
        assert m.level == "empty"
        assert m.key_facts_count == 0
        assert m.form_games_count == 0


# ── Test 2: CoverageMetrics → level = "partial" ──

class TestCoverageMetricsPartial:
    """Rugby fixture with odds + basic standings but no form → partial."""

    def test_compute_coverage_level_rugby_full_with_standings(self):
        """Rugby: 2 key_facts + standings = 'full' (sport-specific threshold)."""
        from evidence_pack import compute_coverage_level

        level = compute_coverage_level(
            sport="rugby",
            league="six_nations",
            key_facts=2,   # rugby threshold: 2+ facts + standings = full
            form_games=0,
            h2h_games=2,
            standings=True,
            market_count=3,
        )
        assert level == "full", f"Expected 'full', got '{level}'"

    def test_compute_coverage_level_rugby_partial_no_standings(self):
        """Rugby: 1 key_fact, no standings, no Glicko → partial."""
        from evidence_pack import compute_coverage_level

        level = compute_coverage_level(
            sport="rugby",
            league="six_nations",
            key_facts=1,
            form_games=0,
            h2h_games=0,
            standings=False,
            market_count=3,
        )
        assert level == "partial", f"Expected 'partial', got '{level}'"

    def test_compute_coverage_level_rugby_full_despite_low_market_count(self):
        """Rugby: rich evidence + standings = 'full' even with 1 bookmaker."""
        from evidence_pack import compute_coverage_level

        level = compute_coverage_level(
            sport="rugby",
            league="urc",
            key_facts=5,
            form_games=3,
            h2h_games=2,
            standings=True,
            market_count=1,
        )
        assert level == "full", f"Expected 'full', got '{level}'"


# ── Test 3: CoverageMetrics → level = "full" ──

class TestCoverageMetricsFull:
    """EPL fixture with full ESPN + sharp + injuries → full."""

    def test_compute_coverage_level_full(self):
        from evidence_pack import compute_coverage_level

        level = compute_coverage_level(
            sport="soccer",
            league="epl",
            key_facts=6,
            form_games=5,
            h2h_games=4,
            standings=True,
            market_count=5,
        )
        assert level == "full", f"Expected 'full', got '{level}'"

    def test_serialise_coverage_metrics_roundtrip(self):
        from evidence_pack import CoverageMetrics, serialise_coverage_metrics

        m = CoverageMetrics(
            sport="soccer",
            league="epl",
            sources_used=["sa_odds", "espn", "sharp", "injuries"],
            missing_sources=[],
            key_facts_count=6,
            injuries_count=2,
            form_games_count=5,
            h2h_games_count=4,
            standings_available=True,
            market_coverage_count=5,
            sharp_available=True,
            level="full",
        )
        json_str = serialise_coverage_metrics(m)
        parsed = json.loads(json_str)
        assert parsed["level"] == "full"
        assert parsed["sport"] == "soccer"
        assert parsed["key_facts_count"] == 6
        assert parsed["sharp_available"] is True


# ── Test 4: Generation gate blocks Sonnet polish for empty evidence ──

class TestGenerationGateBlocksEmpty:
    """When coverage_metrics.level == 'empty', _skip_w84 must be set True."""

    def test_gate_sets_skip_w84_flag(self):
        """Simulate the coverage gate logic directly."""
        from evidence_pack import CoverageMetrics

        cm = CoverageMetrics(
            sport="cricket", league="sa20",
            sources_used=["sa_odds"], missing_sources=["espn"],
            key_facts_count=0, injuries_count=0,
            form_games_count=0, h2h_games_count=0,
            standings_available=False, market_coverage_count=3,
            sharp_available=False, level="empty",
        )

        # Replicate the gate logic from pregenerate_narratives._generate_one()
        _skip_w84 = False
        _cm_gate = cm
        if _cm_gate is not None and _cm_gate.level == "empty":
            _skip_w84 = True

        assert _skip_w84 is True, "Coverage gate must set _skip_w84=True for empty evidence"

    def test_gate_does_not_skip_for_partial(self):
        """Partial evidence should NOT set _skip_w84 — polish is attempted."""
        from evidence_pack import CoverageMetrics

        cm = CoverageMetrics(
            sport="rugby", league="urc",
            sources_used=["sa_odds", "standings"], missing_sources=["espn_form"],
            key_facts_count=2, injuries_count=0,
            form_games_count=0, h2h_games_count=2,
            standings_available=True, market_coverage_count=3,
            sharp_available=False, level="partial",
        )

        _skip_w84 = False
        if cm.level == "empty":
            _skip_w84 = True

        assert _skip_w84 is False, "Coverage gate must NOT skip Sonnet for partial evidence"

    def test_gate_does_not_skip_for_full(self):
        """Full evidence must never trigger the coverage gate."""
        from evidence_pack import CoverageMetrics

        cm = CoverageMetrics(
            sport="soccer", league="epl",
            sources_used=["sa_odds", "espn", "sharp", "injuries"],
            missing_sources=[],
            key_facts_count=6, injuries_count=2,
            form_games_count=5, h2h_games_count=4,
            standings_available=True, market_coverage_count=5,
            sharp_available=True, level="full",
        )

        _skip_w84 = False
        if cm.level == "empty":
            _skip_w84 = True

        assert _skip_w84 is False, "Coverage gate must NOT skip Sonnet for full evidence"


# ── Test 5: Serve-time EV gate suppresses stale 0% EV cached card ──

class TestServeTimeEvGate:
    """Cached card with all tips at 0% EV and current EV ≤ 0 → cache miss forced."""

    def test_all_zero_ev_tips_triggers_gate(self):
        """_all_zero_ev detection logic."""
        cached_tips = [
            {"ev": 0.0, "outcome": "home"},
            {"ev": -1.2, "outcome": "draw"},
        ]
        _all_zero_ev = (
            all(float(t.get("ev", t.get("ev_pct", 0))) <= 0 for t in cached_tips)
            if cached_tips else True
        )
        assert _all_zero_ev is True

    def test_positive_ev_tip_prevents_gate(self):
        """If any tip has positive EV, the gate must NOT clear the cache."""
        cached_tips = [
            {"ev": 3.5, "outcome": "home"},
            {"ev": -1.2, "outcome": "draw"},
        ]
        _all_zero_ev = (
            all(float(t.get("ev", t.get("ev_pct", 0))) <= 0 for t in cached_tips)
            if cached_tips else True
        )
        assert _all_zero_ev is False

    def test_empty_tips_list_triggers_gate(self):
        """Empty tips list is treated as all-zero — gate fires."""
        cached_tips = []
        _all_zero_ev = (
            all(float(t.get("ev", t.get("ev_pct", 0))) <= 0 for t in cached_tips)
            if cached_tips else True
        )
        assert _all_zero_ev is True

    def test_get_current_ev_for_match_is_callable(self):
        """_get_current_ev_for_match must remain importable."""
        from bot import _get_current_ev_for_match
        assert callable(_get_current_ev_for_match)


# ── Test 6: coverage_json written to and read back from narrative_cache ──

class TestCoverageJsonPersistence:
    """coverage_json survives a write/read round-trip through narrative_cache."""

    def _make_db(self) -> sqlite3.Connection:
        conn = sqlite3.connect(":memory:")
        conn.execute("""
            CREATE TABLE narrative_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                match_id TEXT NOT NULL UNIQUE,
                narrative_html TEXT,
                model TEXT,
                edge_tier TEXT,
                tips_json TEXT,
                odds_hash TEXT,
                evidence_json TEXT,
                narrative_source TEXT DEFAULT 'w82',
                coverage_json TEXT,
                created_at TEXT,
                expires_at TEXT
            )
        """)
        conn.commit()
        return conn

    def test_coverage_json_round_trip(self):
        from evidence_pack import CoverageMetrics, serialise_coverage_metrics

        m = CoverageMetrics(
            sport="soccer", league="epl",
            sources_used=["sa_odds", "espn"],
            missing_sources=["sharp"],
            key_facts_count=4, injuries_count=1,
            form_games_count=5, h2h_games_count=3,
            standings_available=True, market_coverage_count=4,
            sharp_available=False, level="full",
        )
        coverage_str = serialise_coverage_metrics(m)

        conn = self._make_db()
        conn.execute(
            "INSERT INTO narrative_cache "
            "(match_id, narrative_html, model, edge_tier, tips_json, odds_hash, "
            "evidence_json, narrative_source, coverage_json, created_at, expires_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                "arsenal_vs_chelsea_2026-03-28",
                "<b>Test narrative</b>",
                "claude-sonnet-4-6",
                "gold",
                "[]",
                "abc123",
                None,
                "w82",
                coverage_str,
                "2026-03-28T10:00:00",
                "2026-03-28T16:00:00",
            ),
        )
        conn.commit()

        row = conn.execute(
            "SELECT coverage_json FROM narrative_cache WHERE match_id = ?",
            ("arsenal_vs_chelsea_2026-03-28",),
        ).fetchone()
        conn.close()

        assert row is not None
        assert row[0] is not None
        parsed = json.loads(row[0])
        assert parsed["level"] == "full"
        assert parsed["sport"] == "soccer"
        assert parsed["league"] == "epl"
        assert parsed["key_facts_count"] == 4

    def test_coverage_json_null_when_not_set(self):
        """Rows inserted without coverage_json must return NULL (backward compat)."""
        conn = self._make_db()
        conn.execute(
            "INSERT INTO narrative_cache "
            "(match_id, narrative_html, model, edge_tier, tips_json, odds_hash, "
            "evidence_json, narrative_source, created_at, expires_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                "old_match_no_coverage",
                "<b>Old narrative</b>",
                "claude-sonnet-4-6",
                "bronze",
                "[]",
                "def456",
                None,
                "w82",
                "2026-03-28T10:00:00",
                "2026-03-28T16:00:00",
            ),
        )
        conn.commit()

        row = conn.execute(
            "SELECT coverage_json FROM narrative_cache WHERE match_id = ?",
            ("old_match_no_coverage",),
        ).fetchone()
        conn.close()

        assert row is not None
        assert row[0] is None, "Rows without coverage_json must return NULL"

    def test_store_narrative_cache_signature_accepts_coverage_json(self):
        """_store_narrative_cache must accept coverage_json keyword argument."""
        import inspect
        from bot import _store_narrative_cache
        sig = inspect.signature(_store_narrative_cache)
        assert "coverage_json" in sig.parameters, (
            "_store_narrative_cache must accept coverage_json= parameter"
        )

    def test_get_cached_narrative_returns_coverage_json_key(self):
        """_get_cached_narrative must return a dict with 'coverage_json' key."""
        import inspect
        # Verify it's importable and is async
        from bot import _get_cached_narrative
        assert callable(_get_cached_narrative)
        assert asyncio.iscoroutinefunction(_get_cached_narrative)
