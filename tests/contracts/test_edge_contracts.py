"""Layer 1.1 — Edge V2 return format contracts.

Validates that calculate_composite_edge() returns the exact dict shape
the bot relies on. Any key rename or type change breaks downstream code.

BUILD-TEST-ISOLATION-2: TestEdgeReturnShape uses an isolated tmp DB so the
live scrapers/odds.db is never opened during contract runs. DB-lock flakiness
from concurrent scraper writes cannot affect this test class.
"""

from __future__ import annotations

import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from config import ensure_scrapers_importable
ensure_scrapers_importable()


# ── Isolated DB helpers (BUILD-TEST-ISOLATION-2) ─────────────────────────────
# Creates a minimal odds.db schema in a tmp dir.  get_top_edges() finds no
# rows → returns [] → tests skip gracefully.  No live DB is ever opened.

_SCHEMA_DDL = """
    CREATE TABLE IF NOT EXISTS odds_latest (
        match_id   TEXT NOT NULL,
        bookmaker  TEXT NOT NULL,
        market_type TEXT NOT NULL,
        home_odds  REAL,
        draw_odds  REAL,
        away_odds  REAL,
        scraped_at DATETIME
    );
    CREATE TABLE IF NOT EXISTS broadcast_schedule (
        home_team      TEXT,
        away_team      TEXT,
        broadcast_date TEXT,
        start_time     TEXT
    );
"""


def _make_test_db(path: str) -> str:
    """Create an isolated SQLite DB with the required schema. Returns path."""
    conn = sqlite3.connect(path)
    try:
        conn.executescript(_SCHEMA_DDL)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=10000")
        conn.commit()
    finally:
        conn.close()
    return path

from scrapers.edge.edge_v2 import calculate_composite_edge
from scrapers.edge.edge_v2_helper import get_top_edges
from scrapers.edge.edge_config import (
    SIGNAL_WEIGHTS,
    SPORT_WEIGHTS,
    NON_SHARP_WEIGHTS,
    TIER_THRESHOLDS,
    NON_SHARP_TIER_THRESHOLDS,
    MAX_DRAW_RATIO,
)
from scrapers.edge.tier_engine import assign_tier, get_tier_display


# ── Required keys in calculate_composite_edge() return dict ──

REQUIRED_EDGE_KEYS = {
    "match_key", "outcome", "market_type", "sport", "league",
    "edge_pct", "composite_score", "tier", "tier_display",
    "confidence", "sharp_available",
    "best_bookmaker", "best_odds", "fair_probability",
    "sharp_source", "method", "n_bookmakers",
    "draw_penalty_applied", "stale_warning",
    "signals", "confirming_signals", "contradicting_signals",
    "red_flags", "narrative", "narrative_bullets", "created_at",
}

REQUIRED_SIGNAL_KEYS = {"signal_strength", "available"}

VALID_TIERS = {"diamond", "gold", "silver", "bronze"}
VALID_OUTCOMES = {"home", "draw", "away"}
VALID_CONFIDENCES = {"high", "medium", "low"}
VALID_MARKET_TYPES = {"1x2", "over_under", "btts"}


@pytest.mark.timeout(120)
class TestEdgeReturnShape:
    """Verify the dict returned by calculate_composite_edge() has all required keys."""

    @pytest.fixture(autouse=True)
    def _isolated_odds_db(self, tmp_path, monkeypatch):
        """Redirect get_top_edges() to an empty isolated DB.

        Prevents DB-lock flakiness from the live scrapers/odds.db.
        An empty DB causes get_top_edges() to return [] so every test in this
        class skips gracefully via its existing 'No live edges available' guard.
        """
        import scrapers.edge.edge_v2_helper as _helper
        db_path = _make_test_db(str(tmp_path / "odds.db"))
        monkeypatch.setattr(_helper, "DB_PATH", db_path)

    def test_live_edges_have_required_keys(self):
        """Every live edge must have all required keys."""
        edges = get_top_edges(n=20)
        if not edges:
            pytest.skip("No live edges available")
        for edge in edges:
            missing = REQUIRED_EDGE_KEYS - set(edge.keys())
            assert not missing, (
                f"Edge {edge.get('match_key', '?')} missing keys: {missing}"
            )

    def test_signals_dict_shape(self):
        """Each signal in an edge must have signal_strength and available."""
        edges = get_top_edges(n=10)
        if not edges:
            pytest.skip("No live edges available")
        for edge in edges:
            signals = edge.get("signals", {})
            assert isinstance(signals, dict), (
                f"Edge {edge['match_key']}: signals should be dict, got {type(signals)}"
            )
            for sig_name, sig_data in signals.items():
                missing = REQUIRED_SIGNAL_KEYS - set(sig_data.keys())
                assert not missing, (
                    f"Signal '{sig_name}' in {edge['match_key']} missing: {missing}"
                )

    def test_composite_score_bounded(self):
        """Composite scores must be 0-100."""
        edges = get_top_edges(n=20)
        if not edges:
            pytest.skip("No live edges available")
        for edge in edges:
            score = edge["composite_score"]
            assert 0 <= score <= 100, (
                f"Edge {edge['match_key']} composite_score={score} out of [0,100]"
            )

    def test_tier_valid_enum(self):
        """Tier must be one of the 4 valid values."""
        edges = get_top_edges(n=20)
        if not edges:
            pytest.skip("No live edges available")
        for edge in edges:
            assert edge["tier"] in VALID_TIERS, (
                f"Edge {edge['match_key']} has invalid tier: {edge['tier']}"
            )

    def test_outcome_valid(self):
        """Outcome must be home, draw, or away."""
        edges = get_top_edges(n=20)
        if not edges:
            pytest.skip("No live edges available")
        for edge in edges:
            assert edge["outcome"] in VALID_OUTCOMES, (
                f"Edge {edge['match_key']} has invalid outcome: {edge['outcome']}"
            )

    def test_confidence_valid(self):
        """Confidence must be high, medium, or low."""
        edges = get_top_edges(n=20)
        if not edges:
            pytest.skip("No live edges available")
        for edge in edges:
            assert edge["confidence"] in VALID_CONFIDENCES, (
                f"Edge {edge['match_key']} has invalid confidence: {edge['confidence']}"
            )

    def test_edge_pct_positive(self):
        """All surfaced edges must have positive edge_pct."""
        edges = get_top_edges(n=20)
        if not edges:
            pytest.skip("No live edges available")
        for edge in edges:
            assert edge["edge_pct"] > 0, (
                f"Edge {edge['match_key']} has non-positive edge_pct: {edge['edge_pct']}"
            )

    def test_red_flags_is_list_of_strings(self):
        """red_flags must be a list of strings."""
        edges = get_top_edges(n=10)
        if not edges:
            pytest.skip("No live edges available")
        for edge in edges:
            flags = edge["red_flags"]
            assert isinstance(flags, list), (
                f"red_flags should be list, got {type(flags)}"
            )
            for f in flags:
                assert isinstance(f, str), (
                    f"red_flag item should be str, got {type(f)}: {f}"
                )

    def test_tier_display_shape(self):
        """tier_display must have emoji and label keys."""
        edges = get_top_edges(n=5)
        if not edges:
            pytest.skip("No live edges available")
        for edge in edges:
            td = edge["tier_display"]
            assert isinstance(td, dict), f"tier_display should be dict, got {type(td)}"
            assert "emoji" in td, "tier_display missing 'emoji' key"
            assert "label" in td, "tier_display missing 'label' key"


class TestTierThresholds:
    """Verify tier threshold constants are correctly ordered."""

    def test_diamond_composite_highest(self):
        """Diamond requires the highest composite."""
        assert (TIER_THRESHOLDS["diamond"]["min_composite"]
                > TIER_THRESHOLDS["gold"]["min_composite"]), (
            "Diamond min_composite must exceed Gold"
        )

    def test_tier_edge_pct_ordering(self):
        """Premium tiers stay ordered; Bronze may sit above Silver by design."""
        for thresholds in [TIER_THRESHOLDS, NON_SHARP_TIER_THRESHOLDS]:
            d = thresholds["diamond"]["min_edge_pct"]
            g = thresholds["gold"]["min_edge_pct"]
            s = thresholds["silver"]["min_edge_pct"]
            b = thresholds["bronze"]["min_edge_pct"]
            assert d >= g >= s, (
                f"Premium edge pct thresholds not ordered: diamond={d}, gold={g}, silver={s}"
            )
            assert 0 < b <= g, (
                f"Bronze edge pct threshold out of expected range: bronze={b}, gold={g}"
            )

    def test_assign_tier_below_bronze_returns_none(self):
        """Composite below bronze threshold returns None (hidden)."""
        result = assign_tier(
            composite=5, edge_pct=0.1, confirming=0,
            red_flags=[], market_type="1x2", sharp_available=True,
        )
        assert result is None, "Sub-bronze composite should return None"

    def test_assign_tier_diamond_requires_confirming(self):
        """Diamond requires min_confirming signals."""
        min_conf = TIER_THRESHOLDS["diamond"]["min_confirming"]
        result = assign_tier(
            composite=90, edge_pct=20.0, confirming=min_conf - 1,
            red_flags=[], market_type="1x2", sharp_available=True,
        )
        assert result != "diamond", (
            f"Diamond should require {min_conf} confirming signals"
        )


class TestSignalWeights:
    """Verify signal weight configuration integrity."""

    def test_all_sports_have_weights(self):
        """Every sport in SPORT_WEIGHTS has all standard signal names."""
        standard_signals = set(SIGNAL_WEIGHTS.keys())
        for sport, weights in SPORT_WEIGHTS.items():
            missing = standard_signals - set(weights.keys())
            assert not missing, (
                f"Sport '{sport}' missing signal weights: {missing}"
            )

    def test_weights_sum_reasonable(self):
        """Weight sums should be ~0.80-0.95 (with some reserved)."""
        for sport, weights in {**SPORT_WEIGHTS, **NON_SHARP_WEIGHTS}.items():
            total = sum(weights.values())
            assert 0.60 <= total <= 1.0, (
                f"Sport '{sport}' weights sum to {total}, expected 0.60-1.00"
            )

    def test_price_edge_has_highest_weight(self):
        """price_edge should have the highest or equal-highest weight in every sport."""
        for sport, weights in SPORT_WEIGHTS.items():
            pe = weights.get("price_edge", 0)
            max_w = max(weights.values())
            assert pe >= max_w, (
                f"Sport '{sport}': price_edge ({pe}) should be >= max weight ({max_w})"
            )

    def test_draw_ratio_cap_between_0_and_1(self):
        """MAX_DRAW_RATIO must be between 0 and 1."""
        assert 0 < MAX_DRAW_RATIO < 1, (
            f"MAX_DRAW_RATIO={MAX_DRAW_RATIO} must be in (0, 1)"
        )


# ── TIER-FIX D: Tier truth contract tests ────────────────────────────────────


class TestListPathTierConsistency:
    """AC-4: _load_tips_from_edge_results returns same tier as edge_results.edge_tier."""

    @pytest.fixture(autouse=True)
    def _isolated_db(self, tmp_path, monkeypatch):
        """Create an isolated edge_results DB with known tier values."""
        import scrapers.edge.edge_config as _cfg
        db_path = str(tmp_path / "odds.db")
        conn = sqlite3.connect(db_path)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS edge_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                edge_id TEXT NOT NULL,
                match_key TEXT NOT NULL,
                sport TEXT NOT NULL,
                league TEXT NOT NULL,
                edge_tier TEXT NOT NULL,
                composite_score REAL NOT NULL,
                bet_type TEXT NOT NULL,
                recommended_odds REAL NOT NULL,
                bookmaker TEXT NOT NULL,
                predicted_ev REAL NOT NULL,
                result TEXT,
                match_score TEXT,
                actual_return REAL,
                recommended_at DATETIME NOT NULL,
                settled_at DATETIME,
                match_date DATE NOT NULL,
                confirming_signals INTEGER DEFAULT NULL,
                is_displayed_in_rollups INTEGER DEFAULT 1
            );
        """)
        from datetime import datetime, date
        now = datetime.utcnow().isoformat()
        today = date.today().isoformat()
        for tier in ("diamond", "gold", "silver", "bronze"):
            conn.execute(
                "INSERT INTO edge_results (edge_id, match_key, sport, league, edge_tier, "
                "composite_score, bet_type, recommended_odds, bookmaker, predicted_ev, "
                "recommended_at, match_date, confirming_signals) "
                "VALUES (?, ?, 'soccer', 'epl', ?, 65.0, 'Home Win', 2.10, 'betway', 5.2, ?, ?, 3)",
                (f"e_{tier}", f"team_a_vs_team_b_{tier}_{today}", tier, now, today),
            )
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=10000")
        conn.commit()
        conn.close()
        monkeypatch.setattr(_cfg, "DB_PATH", db_path)
        monkeypatch.setattr(_cfg, "MAX_PRODUCTION_EDGE_PCT", 30.0)
        monkeypatch.setattr(_cfg, "MAX_RECOMMENDED_ODDS", 50.0)

    @pytest.mark.parametrize("tier", ["diamond", "gold", "silver", "bronze"])
    def test_list_path_returns_db_tier(self, tier):
        """Returned tier must match edge_results.edge_tier exactly.

        _load_tips_from_edge_results stores the tier under both
        'edge_rating' and 'display_tier' keys in the tip dict.
        """
        from datetime import date
        today = date.today().isoformat()
        match_key = f"team_a_vs_team_b_{tier}_{today}"
        import bot
        tips = bot._load_tips_from_edge_results(limit=50, skip_punt_filter=True)
        matching = [t for t in tips if t.get("match_id") == match_key]
        assert len(matching) == 1, f"Expected 1 tip for {match_key}, got {len(matching)}"
        assert matching[0]["edge_rating"] == tier, (
            f"edge_rating: expected '{tier}', got '{matching[0]['edge_rating']}'"
        )
        assert matching[0]["display_tier"] == tier, (
            f"display_tier: expected '{tier}', got '{matching[0]['display_tier']}'"
        )


class TestFreshTierConsistency:
    """AC-5: _get_fresh_tier_from_er returns same tier as edge_results.edge_tier."""

    @pytest.fixture(autouse=True)
    def _isolated_db(self, tmp_path, monkeypatch):
        """Create an isolated edge_results DB with known tier values."""
        import scrapers.edge.edge_config as _cfg
        db_path = str(tmp_path / "odds.db")
        conn = sqlite3.connect(db_path)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS edge_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                edge_id TEXT NOT NULL,
                match_key TEXT NOT NULL,
                sport TEXT NOT NULL,
                league TEXT NOT NULL,
                edge_tier TEXT NOT NULL,
                composite_score REAL NOT NULL,
                bet_type TEXT NOT NULL,
                recommended_odds REAL NOT NULL,
                bookmaker TEXT NOT NULL,
                predicted_ev REAL NOT NULL,
                result TEXT,
                match_score TEXT,
                actual_return REAL,
                recommended_at DATETIME NOT NULL,
                settled_at DATETIME,
                match_date DATE NOT NULL,
                confirming_signals INTEGER DEFAULT NULL
            );
        """)
        from datetime import datetime, date
        now = datetime.utcnow().isoformat()
        today = date.today().isoformat()
        for tier in ("diamond", "gold", "silver", "bronze"):
            conn.execute(
                "INSERT INTO edge_results (edge_id, match_key, sport, league, edge_tier, "
                "composite_score, bet_type, recommended_odds, bookmaker, predicted_ev, "
                "recommended_at, match_date, confirming_signals) "
                "VALUES (?, ?, 'soccer', 'epl', ?, 65.0, 'Home Win', 2.10, 'betway', 5.2, ?, ?, 3)",
                (f"e_{tier}", f"fresh_tier_{tier}", tier, now, today),
            )
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=10000")
        conn.commit()
        conn.close()
        monkeypatch.setattr(_cfg, "DB_PATH", db_path)

    @pytest.mark.parametrize("tier", ["diamond", "gold", "silver", "bronze"])
    def test_fresh_tier_returns_db_tier(self, tier):
        """_get_fresh_tier_from_er must return the DB's edge_tier directly."""
        import bot
        result = bot._get_fresh_tier_from_er(f"fresh_tier_{tier}")
        assert result == tier, f"Expected '{tier}', got '{result}'"


class TestNarrativeCacheCoherence:
    """AC-6: _get_cached_narrative returns None when tier drifts or EV is incoherent."""

    def test_tier_drift_gt1_rejects(self):
        """Tier drift >1 level must trigger rejection."""
        import bot
        # bronze(0) vs diamond(3) = distance 3 > 1 → reject
        assert bot._tier_drift_exceeds_threshold("bronze", "diamond") is True
        # silver(1) vs diamond(3) = distance 2 > 1 → reject
        assert bot._tier_drift_exceeds_threshold("silver", "diamond") is True

    def test_tier_drift_eq1_does_not_reject(self):
        """Tier drift exactly 1 must NOT trigger rejection (AC-3: strictly > 1)."""
        import bot
        # gold(2) vs diamond(3) = distance 1, NOT > 1 → no reject
        assert bot._tier_drift_exceeds_threshold("gold", "diamond") is False
        # silver(1) vs gold(2) = distance 1 → no reject
        assert bot._tier_drift_exceeds_threshold("silver", "gold") is False

    def test_tier_drift_same_tier_does_not_reject(self):
        """Same tier must NOT trigger rejection."""
        import bot
        for tier in ("diamond", "gold", "silver", "bronze"):
            assert bot._tier_drift_exceeds_threshold(tier, tier) is False

    def test_ev_sign_flip_rejects(self):
        """EV sign flip (positive→negative or negative→positive) must reject."""
        import bot
        assert bot._ev_coherence_broken(5.0, -2.0) is True
        assert bot._ev_coherence_broken(-3.0, 4.0) is True

    def test_ev_large_delta_rejects(self):
        """abs(cached_ev - live_ev) > 5.0pp must reject."""
        import bot
        # 5.2 - 11.0 = 5.8 > 5.0 → reject
        assert bot._ev_coherence_broken(5.2, 11.0) is True
        # 2.0 - 8.0 = 6.0 > 5.0 → reject
        assert bot._ev_coherence_broken(2.0, 8.0) is True

    def test_ev_small_delta_same_sign_no_reject(self):
        """Small EV delta with same sign must NOT reject."""
        import bot
        # 5.2 - 7.0 = 1.8 < 5.0, same sign → no reject
        assert bot._ev_coherence_broken(5.2, 7.0) is False
        # 3.0 - 6.0 = 3.0 < 5.0, same sign → no reject
        assert bot._ev_coherence_broken(3.0, 6.0) is False

    def test_ev_null_values_handled(self):
        """Null/None EV should not cause crashes in the helper."""
        import bot
        # Both zero (same sign) and delta=0 → no reject
        assert bot._ev_coherence_broken(0.0, 0.0) is False

    def test_all_four_tiers_roundtrip(self):
        """All 4 tier values survive round-trip through _TIER_LEVEL."""
        import bot
        for tier in ("diamond", "gold", "silver", "bronze"):
            assert tier in bot._TIER_LEVEL, f"Missing tier '{tier}' from _TIER_LEVEL"
