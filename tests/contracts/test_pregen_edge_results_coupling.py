"""FIX-PREGEN-EDGE-RESULTS-COUPLING-01: Contract tests for pregen ↔ edge_results coupling.

Guards (per AC-2/AC-3):
  - discover_pregen_targets() filters candidates against edge_results.match_key
  - Empty edge_results → zero pregen targets (no ghost-cache writes)
  - _PREGEN_WARM_COVERAGE_ALLOWLIST passes through league_keys (default empty)
  - Settled edges (result IS NOT NULL) do NOT count toward intersection
  - Helper _load_unsettled_edge_match_keys returns the exact unsettled set
  - Filter does not crash when edge_results table is missing (best-effort)
"""
from __future__ import annotations

import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

# Ensure scripts/ on sys.path
_BOT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SCRIPTS_DIR = os.path.join(_BOT_ROOT, "scripts")
if _BOT_ROOT not in sys.path:
    sys.path.insert(0, _BOT_ROOT)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)


def _make_db(path: str) -> sqlite3.Connection:
    """Build a minimal odds.db with the tables discover_pregen_targets reads."""
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS odds_snapshots (
            id INTEGER PRIMARY KEY,
            match_id TEXT NOT NULL,
            home_team TEXT,
            away_team TEXT,
            league TEXT,
            sport TEXT,
            bookmaker TEXT,
            market_type TEXT,
            scraped_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sportmonks_fixtures (
            id INTEGER PRIMARY KEY,
            api_id INTEGER,
            league_name TEXT,
            match_date TEXT,
            status TEXT,
            home_team TEXT,
            away_team TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS mma_fixtures (
            id INTEGER PRIMARY KEY,
            api_id INTEGER,
            event_slug TEXT,
            fight_date TEXT,
            weight_class TEXT,
            status TEXT,
            fighter1_name TEXT,
            fighter2_name TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS rugby_fixtures (
            id INTEGER PRIMARY KEY,
            api_id INTEGER,
            league_name TEXT,
            match_date TEXT,
            status TEXT,
            home_team TEXT,
            away_team TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS edge_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            edge_id TEXT,
            match_key TEXT,
            sport TEXT,
            league TEXT,
            edge_tier TEXT,
            composite_score REAL,
            bet_type TEXT,
            recommended_odds REAL,
            bookmaker TEXT,
            predicted_ev REAL,
            recommended_at TEXT,
            match_date TEXT,
            result TEXT,
            actual_return REAL,
            settled_at TEXT,
            confirming_signals INTEGER,
            movement TEXT,
            match_score TEXT
        )
    """)
    conn.commit()
    return conn


def _tomorrow_date() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=24)).strftime("%Y-%m-%d")


def _seed_edge(conn: sqlite3.Connection, match_key: str, *, settled: bool = False) -> None:
    """Insert a single edge_results row."""
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO edge_results (match_key, result, recommended_at, edge_tier) "
        "VALUES (?, ?, ?, 'gold')",
        (match_key, "hit" if settled else None, now),
    )


def _seed_snapshot(conn: sqlite3.Connection, match_key: str, league: str = "epl") -> None:
    """Insert an odds_snapshots row that pregen would discover."""
    conn.execute(
        "INSERT INTO odds_snapshots (match_id, home_team, away_team, league, sport, "
        "bookmaker, market_type, scraped_at) VALUES (?, ?, ?, ?, 'soccer', 'betway', '1x2', ?)",
        (
            match_key,
            match_key.rsplit("_vs_", 1)[0],
            match_key.rsplit("_vs_", 1)[1].rsplit("_", 1)[0],
            league,
            datetime.now(timezone.utc).isoformat(),
        ),
    )


# ---------------------------------------------------------------------------
# AC-2: filter intersects with edge_results
# ---------------------------------------------------------------------------


class TestEdgeResultsIntersection:
    def test_empty_edge_results_filters_all_candidates(self, tmp_path):
        """No unsettled edge_results → zero pregen targets (no ghost cache)."""
        from pregenerate_narratives import discover_pregen_targets

        db = str(tmp_path / "odds.db")
        conn = _make_db(db)
        tomorrow = _tomorrow_date()
        # Two soccer candidates with no matching edge_results
        _seed_snapshot(conn, f"team_a_vs_team_b_{tomorrow}", "epl")
        _seed_snapshot(conn, f"team_c_vs_team_d_{tomorrow}", "epl")
        conn.commit()
        conn.close()

        targets = discover_pregen_targets(db_path=db)
        assert targets == [], (
            f"Expected zero targets when edge_results is empty, got {len(targets)}: "
            f"{[t['match_key'] for t in targets]}"
        )

    def test_intersection_keeps_only_matched_candidates(self, tmp_path):
        """Candidate with edge_results entry passes; without it does not."""
        from pregenerate_narratives import discover_pregen_targets

        db = str(tmp_path / "odds.db")
        conn = _make_db(db)
        tomorrow = _tomorrow_date()
        kept = f"keep_a_vs_keep_b_{tomorrow}"
        dropped = f"drop_a_vs_drop_b_{tomorrow}"
        _seed_snapshot(conn, kept, "epl")
        _seed_snapshot(conn, dropped, "epl")
        _seed_edge(conn, kept)
        conn.commit()
        conn.close()

        targets = discover_pregen_targets(db_path=db)
        match_keys = {t["match_key"] for t in targets}
        assert kept in match_keys, f"Expected {kept} in targets"
        assert dropped not in match_keys, f"Expected {dropped} NOT in targets"

    def test_settled_edges_do_not_count(self, tmp_path):
        """edge_results rows with result IS NOT NULL are excluded from intersection."""
        from pregenerate_narratives import discover_pregen_targets

        db = str(tmp_path / "odds.db")
        conn = _make_db(db)
        tomorrow = _tomorrow_date()
        candidate = f"team_e_vs_team_f_{tomorrow}"
        _seed_snapshot(conn, candidate, "epl")
        # Settled edge: result IS NOT NULL → must NOT keep candidate
        _seed_edge(conn, candidate, settled=True)
        conn.commit()
        conn.close()

        targets = discover_pregen_targets(db_path=db)
        assert candidate not in {t["match_key"] for t in targets}, (
            "Settled edge_results row must not satisfy coupling filter"
        )


# ---------------------------------------------------------------------------
# AC-3: allowlist escape valve
# ---------------------------------------------------------------------------


class TestAllowlistEscapeValve:
    def test_allowlist_constant_is_empty_frozenset_by_default(self):
        """_PREGEN_WARM_COVERAGE_ALLOWLIST defaults to empty frozenset."""
        from pregenerate_narratives import _PREGEN_WARM_COVERAGE_ALLOWLIST

        assert isinstance(_PREGEN_WARM_COVERAGE_ALLOWLIST, frozenset)
        assert len(_PREGEN_WARM_COVERAGE_ALLOWLIST) == 0, (
            "Allowlist must default to empty per AC-3 (zero ghost-cache writes by default)"
        )

    def test_allowlist_keeps_candidate_without_edge_results(self, tmp_path):
        """Allowlisted league passes coupling filter even without edge_results row."""
        from pregenerate_narratives import discover_pregen_targets

        db = str(tmp_path / "odds.db")
        conn = _make_db(db)
        tomorrow = _tomorrow_date()
        warm = f"warm_a_vs_warm_b_{tomorrow}"
        cold = f"cold_a_vs_cold_b_{tomorrow}"
        _seed_snapshot(conn, warm, "epl")
        _seed_snapshot(conn, cold, "psl")
        # No edge_results rows for either
        conn.commit()
        conn.close()

        with patch(
            "pregenerate_narratives._PREGEN_WARM_COVERAGE_ALLOWLIST",
            frozenset({"epl"}),
        ):
            targets = discover_pregen_targets(db_path=db)

        match_keys = {t["match_key"] for t in targets}
        assert warm in match_keys, "Allowlisted league must pass even without edge_results"
        assert cold not in match_keys, "Non-allowlisted league must still be filtered"


# ---------------------------------------------------------------------------
# AC-2 helper: _load_unsettled_edge_match_keys correctness
# ---------------------------------------------------------------------------


class TestLoadUnsettledEdgeMatchKeys:
    def test_returns_only_unsettled(self, tmp_path):
        """Helper returns match_keys where result IS NULL."""
        from pregenerate_narratives import _load_unsettled_edge_match_keys

        db = str(tmp_path / "odds.db")
        conn = _make_db(db)
        _seed_edge(conn, "live_a_vs_live_b_2026-05-01", settled=False)
        _seed_edge(conn, "settled_a_vs_settled_b_2026-04-01", settled=True)
        conn.commit()
        conn.close()

        keys = _load_unsettled_edge_match_keys(db)
        assert keys == {"live_a_vs_live_b_2026-05-01"}

    def test_returns_empty_set_when_table_missing(self, tmp_path):
        """Best-effort: no edge_results table → empty set, no exception."""
        from pregenerate_narratives import _load_unsettled_edge_match_keys

        db = str(tmp_path / "no_edge_table.db")
        conn = sqlite3.connect(db)
        conn.execute("PRAGMA journal_mode=WAL")
        # NB: no edge_results table created
        conn.commit()
        conn.close()

        keys = _load_unsettled_edge_match_keys(db)
        assert keys == set()

    def test_returns_empty_set_when_table_empty(self, tmp_path):
        """Empty edge_results table → empty set."""
        from pregenerate_narratives import _load_unsettled_edge_match_keys

        db = str(tmp_path / "empty_edge.db")
        conn = _make_db(db)
        conn.commit()
        conn.close()

        keys = _load_unsettled_edge_match_keys(db)
        assert keys == set()


# ---------------------------------------------------------------------------
# AC-2 spec contract: function signature stability
# ---------------------------------------------------------------------------


class TestSignatureStability:
    def test_load_unsettled_edge_match_keys_exists(self):
        """_load_unsettled_edge_match_keys is exported from the pregen module."""
        from pregenerate_narratives import _load_unsettled_edge_match_keys

        assert callable(_load_unsettled_edge_match_keys)

    def test_discover_pregen_targets_logs_coupling(self, tmp_path, caplog):
        """discover_pregen_targets emits the edge_results coupling log line."""
        import logging

        from pregenerate_narratives import discover_pregen_targets

        db = str(tmp_path / "odds.db")
        conn = _make_db(db)
        tomorrow = _tomorrow_date()
        kept = f"log_a_vs_log_b_{tomorrow}"
        _seed_snapshot(conn, kept, "epl")
        _seed_edge(conn, kept)
        conn.commit()
        conn.close()

        with caplog.at_level(logging.INFO, logger="pregenerate"):
            discover_pregen_targets(db_path=db)

        coupling_lines = [
            r.getMessage() for r in caplog.records
            if "edge_results coupling" in r.getMessage()
        ]
        assert coupling_lines, "Expected 'edge_results coupling' log line for observability"
        msg = coupling_lines[0]
        assert "raw=" in msg and "edge_intersection=" in msg and "final=" in msg


# ---------------------------------------------------------------------------
# AC-2 extension: snapshot baseline path also coupled to edge_results
# ---------------------------------------------------------------------------


class TestSnapshotBaselineCouplingAtLoadPregenEdges:
    """_load_snapshot_baseline_edges by SQL design returns matches WITHOUT
    edge_results — i.e. exactly the ghost-cache pattern this fix prevents.
    The coupling check at _load_pregen_edges drops them unless allowlisted."""

    def test_snapshot_baseline_dropped_by_default(self):
        import pregenerate_narratives as pn

        ghost_edge = {
            "match_key": "ghost_a_vs_ghost_b_2026-05-01",
            "best_odds": 2.10,
            "edge_pct": -0.5,
            "league": "epl",
            "narrative_source_hint": "baseline_no_edge",
        }
        # Real-world: shadow path returns nothing here, snapshot path returns the ghost
        with patch.object(pn, "_load_shadow_pregen_edges", return_value=[]), \
             patch.object(pn, "_load_snapshot_baseline_edges", return_value=[ghost_edge]), \
             patch.object(pn, "discover_pregen_targets", return_value=[]):
            edges = pn._load_pregen_edges(limit=10)

        keys = [e.get("match_key") for e in edges]
        assert "ghost_a_vs_ghost_b_2026-05-01" not in keys, (
            "Snapshot baseline ghosts must be filtered when allowlist is empty"
        )

    def test_snapshot_baseline_kept_when_allowlisted(self):
        import pregenerate_narratives as pn

        warm_edge = {
            "match_key": "warm_a_vs_warm_b_2026-05-01",
            "best_odds": 2.10,
            "edge_pct": -0.5,
            "league": "epl",
            "narrative_source_hint": "baseline_no_edge",
        }
        with patch.object(pn, "_load_shadow_pregen_edges", return_value=[]), \
             patch.object(pn, "_load_snapshot_baseline_edges", return_value=[warm_edge]), \
             patch.object(pn, "discover_pregen_targets", return_value=[]), \
             patch.object(pn, "_PREGEN_WARM_COVERAGE_ALLOWLIST", frozenset({"epl"})):
            edges = pn._load_pregen_edges(limit=10)

        keys = [e.get("match_key") for e in edges]
        assert "warm_a_vs_warm_b_2026-05-01" in keys, (
            "Allowlist must keep snapshot baseline edges in the candidate set"
        )
