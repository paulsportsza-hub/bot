"""BUILD-ENRICH-09: Contract tests for fixture-based pregen discovery.

Guards:
  (a) discover_pregen_targets() finds matches from each fixture table
  (b) Deduplication: odds_snapshots version preferred; fuzzy dedup for team-name variants
  (c) 48h window filter: matches outside window are excluded
  (d) Existing odds_snapshots-only path still works when fixture tables are empty
  (e) Missing/empty fixture tables handled gracefully (no exception)
  (f) Matches with NULL commence_time are skipped
  (g) _build_fixture_only_edge produces valid edge dicts
  (h) _load_pregen_edges integrates fixture targets additively
"""
from __future__ import annotations

import sqlite3
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

import pytest

# Ensure scripts/ is on sys.path for direct import of pregenerate_narratives
_BOT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SCRIPTS_DIR = os.path.join(_BOT_ROOT, "scripts")
if _BOT_ROOT not in sys.path:
    sys.path.insert(0, _BOT_ROOT)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)


# ---------------------------------------------------------------------------
# Helpers: build an in-memory (or tmp) odds.db with the fixture tables
# ---------------------------------------------------------------------------

def _make_odds_db(path: str) -> sqlite3.Connection:
    """Create a minimal odds.db with all four fixture/snapshot tables."""
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")

    # odds_snapshots (soccer primary source)
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

    # sportmonks_fixtures (cricket)
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

    # mma_fixtures (MMA/combat)
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

    # rugby_fixtures (rugby)
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

    # edge_results (FIX-PREGEN-EDGE-RESULTS-COUPLING-01: discover_pregen_targets()
    # now intersects candidates with edge_results.match_key. Tests that expect a
    # fixture/snapshot to surface MUST also seed edge_results via _seed_edge().)
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


def _seed_edge(conn: sqlite3.Connection, match_key: str) -> None:
    """Seed an unsettled edge_results row so the coupling filter accepts the candidate.

    FIX-PREGEN-EDGE-RESULTS-COUPLING-01: discover_pregen_targets() filters candidates
    against unsettled edge_results.match_key. Without a matching row the candidate
    is dropped (treated as ghost-cache risk).
    """
    conn.execute(
        "INSERT INTO edge_results (match_key, result, recommended_at, edge_tier) "
        "VALUES (?, NULL, ?, 'gold')",
        (match_key, datetime.now(timezone.utc).isoformat()),
    )


def _tomorrow_date() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=24)).strftime("%Y-%m-%d")


def _far_future_date() -> str:
    return (datetime.now(timezone.utc) + timedelta(days=10)).strftime("%Y-%m-%d")


def _yesterday_date() -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=24)).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# (a) Discovery finds matches from each fixture table
# ---------------------------------------------------------------------------

class TestDiscoveryFindsAllSources:
    def test_finds_sportmonks_cricket(self, tmp_path):
        """sportmonks_fixtures rows within 48h window appear in targets."""
        from pregenerate_narratives import discover_pregen_targets

        db = str(tmp_path / "odds.db")
        conn = _make_odds_db(db)
        tomorrow = _tomorrow_date()
        conn.execute(
            "INSERT INTO sportmonks_fixtures (league_name, match_date, status, home_team, away_team) "
            "VALUES (?, ?, 'NS', ?, ?)",
            ("IPL", f"{tomorrow} 14:00:00", "Gujarat Titans", "Rajasthan Royals"),
        )
        _seed_edge(conn, f"gujarat_titans_vs_rajasthan_royals_{tomorrow}")
        conn.commit()
        conn.close()

        targets = discover_pregen_targets(db_path=db)
        fixture_targets = [t for t in targets if t["source_table"] == "sportmonks_fixtures"]

        assert len(fixture_targets) == 1
        t = fixture_targets[0]
        assert t["sport"] == "cricket"
        assert "gujarat_titans" in t["match_key"]
        assert "rajasthan_royals" in t["match_key"]
        assert t["league"] == "IPL"
        assert t["commence_time"] != ""

    def test_finds_mma_fixtures(self, tmp_path):
        """mma_fixtures rows within 48h window appear in targets."""
        from pregenerate_narratives import discover_pregen_targets

        db = str(tmp_path / "odds.db")
        conn = _make_odds_db(db)
        tomorrow = _tomorrow_date()
        conn.execute(
            "INSERT INTO mma_fixtures (event_slug, fight_date, weight_class, status, fighter1_name, fighter2_name) "
            "VALUES (?, ?, ?, 'NS', ?, ?)",
            ("UFC Fight Night", tomorrow, "Middleweight", "Dricus Du Plessis", "Israel Adesanya"),
        )
        _seed_edge(conn, f"dricus_du_plessis_vs_israel_adesanya_{tomorrow}")
        conn.commit()
        conn.close()

        targets = discover_pregen_targets(db_path=db)
        fixture_targets = [t for t in targets if t["source_table"] == "mma_fixtures"]

        assert len(fixture_targets) == 1
        t = fixture_targets[0]
        assert t["sport"] == "mma"
        assert "dricus" in t["match_key"] or "du_plessis" in t["match_key"]
        assert t["commence_time"] != ""

    def test_finds_rugby_fixtures(self, tmp_path):
        """rugby_fixtures rows within 48h window appear in targets."""
        from pregenerate_narratives import discover_pregen_targets

        db = str(tmp_path / "odds.db")
        conn = _make_odds_db(db)
        tomorrow = _tomorrow_date()
        conn.execute(
            "INSERT INTO rugby_fixtures (league_name, match_date, status, home_team, away_team) "
            "VALUES (?, ?, 'NS', ?, ?)",
            ("Super Rugby", tomorrow, "Chiefs", "Waratahs"),
        )
        _seed_edge(conn, f"chiefs_vs_waratahs_{tomorrow}")
        conn.commit()
        conn.close()

        targets = discover_pregen_targets(db_path=db)
        fixture_targets = [t for t in targets if t["source_table"] == "rugby_fixtures"]

        assert len(fixture_targets) == 1
        t = fixture_targets[0]
        assert t["sport"] == "rugby"
        assert "chiefs" in t["match_key"]
        assert "waratahs" in t["match_key"]

    def test_finds_odds_snapshots(self, tmp_path):
        """odds_snapshots rows within 48h window appear in targets."""
        from pregenerate_narratives import discover_pregen_targets

        db = str(tmp_path / "odds.db")
        conn = _make_odds_db(db)
        tomorrow = _tomorrow_date()
        conn.execute(
            "INSERT INTO odds_snapshots (match_id, home_team, away_team, league, sport, bookmaker, market_type, scraped_at) "
            "VALUES (?, 'kaizer_chiefs', 'orlando_pirates', 'psl', 'football', 'betway', '1x2', ?)",
            (f"kaizer_chiefs_vs_orlando_pirates_{tomorrow}", "2026-04-04 06:00:00"),
        )
        _seed_edge(conn, f"kaizer_chiefs_vs_orlando_pirates_{tomorrow}")
        conn.commit()
        conn.close()

        targets = discover_pregen_targets(db_path=db)
        snap_targets = [t for t in targets if t["source_table"] == "odds_snapshots"]

        assert len(snap_targets) == 1
        assert snap_targets[0]["league"] == "psl"


# ---------------------------------------------------------------------------
# (b) Deduplication
# ---------------------------------------------------------------------------

class TestDeduplication:
    def test_exact_dedup_prefers_odds_snapshots(self, tmp_path):
        """When same match_key in odds_snapshots and fixture table, only one entry returned."""
        from pregenerate_narratives import discover_pregen_targets

        db = str(tmp_path / "odds.db")
        conn = _make_odds_db(db)
        tomorrow = _tomorrow_date()
        # odds_snapshots: uses normalised key
        conn.execute(
            "INSERT INTO odds_snapshots (match_id, home_team, away_team, league, sport, bookmaker, market_type, scraped_at) "
            "VALUES (?, 'gujarat_titans', 'rajasthan_royals', 'ipl', 'cricket', 'betway', '1x2', ?)",
            (f"gujarat_titans_vs_rajasthan_royals_{tomorrow}", "2026-04-04 06:00:00"),
        )
        # sportmonks_fixtures: same match, capitalised names → same normalised key
        conn.execute(
            "INSERT INTO sportmonks_fixtures (league_name, match_date, status, home_team, away_team) "
            "VALUES (?, ?, 'NS', ?, ?)",
            ("IPL", f"{tomorrow} 14:00:00", "Gujarat Titans", "Rajasthan Royals"),
        )
        _seed_edge(conn, f"gujarat_titans_vs_rajasthan_royals_{tomorrow}")
        conn.commit()
        conn.close()

        targets = discover_pregen_targets(db_path=db)
        match_keys = [t["match_key"] for t in targets]

        # Should appear exactly once
        expected_key = f"gujarat_titans_vs_rajasthan_royals_{tomorrow}"
        assert match_keys.count(expected_key) == 1

        # The surviving entry should be from odds_snapshots
        surviving = next(t for t in targets if t["match_key"] == expected_key)
        assert surviving["source_table"] == "odds_snapshots"

    def test_fuzzy_dedup_city_rename(self, tmp_path):
        """Fuzzy dedup: 'Royal Challengers Bengaluru' vs 'royal_challengers_bangalore'."""
        from pregenerate_narratives import discover_pregen_targets

        db = str(tmp_path / "odds.db")
        conn = _make_odds_db(db)
        tomorrow = _tomorrow_date()
        # odds_snapshots uses the old spelling
        conn.execute(
            "INSERT INTO odds_snapshots (match_id, home_team, away_team, league, sport, bookmaker, market_type, scraped_at) "
            "VALUES (?, 'royal_challengers_bangalore', 'chennai_super_kings', 'ipl', 'cricket', 'betway', '1x2', ?)",
            (f"royal_challengers_bangalore_vs_chennai_super_kings_{tomorrow}", "2026-04-04 06:00:00"),
        )
        # sportmonks_fixtures uses the new city spelling
        conn.execute(
            "INSERT INTO sportmonks_fixtures (league_name, match_date, status, home_team, away_team) "
            "VALUES (?, ?, 'NS', ?, ?)",
            ("IPL", f"{tomorrow} 14:00:00", "Royal Challengers Bengaluru", "Chennai Super Kings"),
        )
        _seed_edge(conn, f"royal_challengers_bangalore_vs_chennai_super_kings_{tomorrow}")
        conn.commit()
        conn.close()

        targets = discover_pregen_targets(db_path=db)

        # Both rcb_bangalore and rcb_bengaluru should not both appear
        rcb_keys = [t["match_key"] for t in targets if "royal_challengers" in t["match_key"]]
        assert len(rcb_keys) == 1, (
            f"Expected 1 RCB entry (fuzzy dedup should suppress sportmonks), got {rcb_keys}"
        )

        # The surviving entry should be from odds_snapshots
        surviving = next(t for t in targets if "royal_challengers" in t["match_key"])
        assert surviving["source_table"] == "odds_snapshots"

    def test_no_dedup_across_different_sports(self, tmp_path):
        """Cricket and rugby fixtures on the same date with different teams are both returned."""
        from pregenerate_narratives import discover_pregen_targets

        db = str(tmp_path / "odds.db")
        conn = _make_odds_db(db)
        tomorrow = _tomorrow_date()
        # Cricket: IPL teams
        conn.execute(
            "INSERT INTO sportmonks_fixtures (league_name, match_date, status, home_team, away_team) "
            "VALUES (?, ?, 'NS', ?, ?)",
            ("IPL", f"{tomorrow} 10:00:00", "Gujarat Titans", "Delhi Capitals"),
        )
        # Rugby: Super Rugby franchises (completely different teams)
        conn.execute(
            "INSERT INTO rugby_fixtures (league_name, match_date, status, home_team, away_team) "
            "VALUES (?, ?, 'NS', ?, ?)",
            ("Super Rugby", tomorrow, "Chiefs", "Waratahs"),
        )
        _seed_edge(conn, f"gujarat_titans_vs_delhi_capitals_{tomorrow}")
        _seed_edge(conn, f"chiefs_vs_waratahs_{tomorrow}")
        conn.commit()
        conn.close()

        targets = discover_pregen_targets(db_path=db)
        cricket_targets = [t for t in targets if t["sport"] == "cricket"]
        rugby_targets = [t for t in targets if t["sport"] == "rugby"]

        # Both should appear — completely different teams/match_keys prevent dedup
        assert len(cricket_targets) == 1
        assert len(rugby_targets) == 1


# ---------------------------------------------------------------------------
# (c) 48h window filter
# ---------------------------------------------------------------------------

class TestWindowFilter:
    def test_excludes_past_matches(self, tmp_path):
        """Matches with dates before today are not returned."""
        from pregenerate_narratives import discover_pregen_targets

        db = str(tmp_path / "odds.db")
        conn = _make_odds_db(db)
        yesterday = _yesterday_date()
        conn.execute(
            "INSERT INTO sportmonks_fixtures (league_name, match_date, status, home_team, away_team) "
            "VALUES (?, ?, 'Finished', ?, ?)",
            ("IPL", f"{yesterday} 14:00:00", "Gujarat Titans", "Rajasthan Royals"),
        )
        conn.commit()
        conn.close()

        targets = discover_pregen_targets(db_path=db)
        assert len(targets) == 0

    def test_excludes_far_future_matches(self, tmp_path):
        """Matches more than 48h away are not returned."""
        from pregenerate_narratives import discover_pregen_targets

        db = str(tmp_path / "odds.db")
        conn = _make_odds_db(db)
        far = _far_future_date()
        conn.execute(
            "INSERT INTO sportmonks_fixtures (league_name, match_date, status, home_team, away_team) "
            "VALUES (?, ?, 'NS', ?, ?)",
            ("IPL", f"{far} 14:00:00", "Gujarat Titans", "Rajasthan Royals"),
        )
        conn.commit()
        conn.close()

        targets = discover_pregen_targets(db_path=db)
        assert len(targets) == 0

    def test_includes_matches_within_window(self, tmp_path):
        """Matches within 48h are returned."""
        from pregenerate_narratives import discover_pregen_targets

        db = str(tmp_path / "odds.db")
        conn = _make_odds_db(db)
        tomorrow = _tomorrow_date()
        conn.execute(
            "INSERT INTO rugby_fixtures (league_name, match_date, status, home_team, away_team) "
            "VALUES (?, ?, 'NS', ?, ?)",
            ("URC", tomorrow, "Leinster", "Munster"),
        )
        _seed_edge(conn, f"leinster_vs_munster_{tomorrow}")
        conn.commit()
        conn.close()

        targets = discover_pregen_targets(db_path=db)
        assert len(targets) == 1

    def test_excludes_terminal_status(self, tmp_path):
        """Matches with Finished or Cancelled status are excluded regardless of date."""
        from pregenerate_narratives import discover_pregen_targets

        db = str(tmp_path / "odds.db")
        conn = _make_odds_db(db)
        tomorrow = _tomorrow_date()
        conn.execute(
            "INSERT INTO mma_fixtures (event_slug, fight_date, weight_class, status, fighter1_name, fighter2_name) "
            "VALUES (?, ?, ?, 'Cancelled', ?, ?)",
            ("UFC 310", tomorrow, "HW", "Jon Jones", "Stipe Miocic"),
        )
        conn.execute(
            "INSERT INTO mma_fixtures (event_slug, fight_date, weight_class, status, fighter1_name, fighter2_name) "
            "VALUES (?, ?, ?, 'Finished', ?, ?)",
            ("UFC 310", tomorrow, "LHW", "Alex Pereira", "Khalil Rountree"),
        )
        conn.commit()
        conn.close()

        targets = discover_pregen_targets(db_path=db)
        assert len(targets) == 0


# ---------------------------------------------------------------------------
# (d) Existing odds_snapshots-only path still works when fixture tables are empty
# ---------------------------------------------------------------------------

class TestOddsSnapshotsFallback:
    def test_empty_fixture_tables_still_returns_snapshots(self, tmp_path):
        """When all fixture tables are empty, odds_snapshots matches are still returned."""
        from pregenerate_narratives import discover_pregen_targets

        db = str(tmp_path / "odds.db")
        conn = _make_odds_db(db)
        tomorrow = _tomorrow_date()
        conn.execute(
            "INSERT INTO odds_snapshots (match_id, home_team, away_team, league, sport, bookmaker, market_type, scraped_at) "
            "VALUES (?, 'wolves', 'aston_villa', 'epl', 'football', 'betway', '1x2', ?)",
            (f"wolves_vs_aston_villa_{tomorrow}", "2026-04-04 06:00:00"),
        )
        _seed_edge(conn, f"wolves_vs_aston_villa_{tomorrow}")
        conn.commit()
        conn.close()

        targets = discover_pregen_targets(db_path=db)
        assert len(targets) == 1
        assert targets[0]["source_table"] == "odds_snapshots"
        assert targets[0]["league"] == "epl"

    def test_completely_empty_db_returns_empty_list(self, tmp_path):
        """When all tables are empty, returns empty list without error."""
        from pregenerate_narratives import discover_pregen_targets

        db = str(tmp_path / "odds.db")
        _make_odds_db(db).close()

        targets = discover_pregen_targets(db_path=db)
        assert targets == []


# ---------------------------------------------------------------------------
# (e) Missing fixture tables handled gracefully
# ---------------------------------------------------------------------------

class TestMissingTables:
    def test_missing_fixture_table_does_not_raise(self, tmp_path):
        """If a fixture table doesn't exist, discovery continues with other sources."""
        from pregenerate_narratives import discover_pregen_targets

        db = str(tmp_path / "odds.db")
        conn = sqlite3.connect(db)
        conn.execute("PRAGMA journal_mode=WAL")
        # Only create odds_snapshots — no fixture tables
        conn.execute("""
            CREATE TABLE odds_snapshots (
                id INTEGER PRIMARY KEY,
                match_id TEXT NOT NULL,
                home_team TEXT, away_team TEXT, league TEXT, sport TEXT,
                bookmaker TEXT, market_type TEXT, scraped_at TEXT
            )
        """)
        # FIX-PREGEN-EDGE-RESULTS-COUPLING-01 requires edge_results presence
        # for any candidate to surface; missing fixture tables remain a separate
        # graceful-degradation concern.
        conn.execute("""
            CREATE TABLE edge_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                match_key TEXT, result TEXT, recommended_at TEXT, edge_tier TEXT
            )
        """)
        tomorrow = _tomorrow_date()
        conn.execute(
            "INSERT INTO odds_snapshots VALUES (1, ?, 'team_a', 'team_b', 'psl', 'football', 'betway', '1x2', '2026-04-04')",
            (f"team_a_vs_team_b_{tomorrow}",),
        )
        _seed_edge(conn, f"team_a_vs_team_b_{tomorrow}")
        conn.commit()
        conn.close()

        # Must not raise — missing tables are handled gracefully
        targets = discover_pregen_targets(db_path=db)
        assert isinstance(targets, list)
        # odds_snapshots match still returned
        assert len(targets) == 1

    def test_all_tables_missing_returns_empty_list(self, tmp_path):
        """If no known tables exist, returns empty list without exception."""
        from pregenerate_narratives import discover_pregen_targets

        db = str(tmp_path / "odds.db")
        # Empty SQLite file — no tables at all
        sqlite3.connect(db).close()

        targets = discover_pregen_targets(db_path=db)
        assert targets == []


# ---------------------------------------------------------------------------
# (f) NULL commence_time rows are skipped
# ---------------------------------------------------------------------------

class TestNullCommenceTime:
    def test_null_date_in_fixture_table_skipped(self, tmp_path):
        """Rows with NULL match_date/fight_date in fixture tables are excluded."""
        from pregenerate_narratives import discover_pregen_targets

        db = str(tmp_path / "odds.db")
        conn = _make_odds_db(db)
        # NULL match_date — should be excluded by SQL WHERE clause
        conn.execute(
            "INSERT INTO rugby_fixtures (league_name, match_date, status, home_team, away_team) "
            "VALUES (?, NULL, 'NS', ?, ?)",
            ("URC", "Bulls", "Sharks"),
        )
        conn.commit()
        conn.close()

        targets = discover_pregen_targets(db_path=db)
        assert len(targets) == 0


# ---------------------------------------------------------------------------
# (g) _build_fixture_only_edge produces valid edge dicts
# ---------------------------------------------------------------------------

class TestBuildFixtureOnlyEdge:
    def test_required_fields_present(self):
        """_build_fixture_only_edge returns a dict with all required fields."""
        from pregenerate_narratives import _build_fixture_only_edge

        target = {
            "match_key": "gujarat_titans_vs_rajasthan_royals_2026-04-06",
            "sport": "cricket",
            "home_team": "Gujarat Titans",
            "away_team": "Rajasthan Royals",
            "league": "IPL",
            "commence_time": "2026-04-06T14:00:00+00:00",
            "source_table": "sportmonks_fixtures",
        }
        edge = _build_fixture_only_edge(target)

        assert edge["match_key"] == target["match_key"]
        assert edge["sport"] == "cricket"
        assert edge["home_team"] == "Gujarat Titans"
        assert edge["away_team"] == "Rajasthan Royals"
        assert edge["league"] == "IPL"
        assert edge["commence_time"] == "2026-04-06T14:00:00+00:00"
        assert edge["narrative_source_hint"] == "fixture_only"
        # Cricket fixture-only: skip_sonnet_polish is False (enriched sport)
        assert edge["skip_sonnet_polish"] is False
        assert edge["tier"] == "bronze"

    def test_zero_odds_and_ev(self):
        """Fixture-only edges have no odds/EV data."""
        from pregenerate_narratives import _build_fixture_only_edge

        edge = _build_fixture_only_edge({
            "match_key": "test_vs_test_2026-04-06",
            "sport": "mma",
            "home_team": "Fighter A",
            "away_team": "Fighter B",
            "league": "UFC",
            "commence_time": "2026-04-06T00:00:00+00:00",
            "source_table": "mma_fixtures",
        })

        assert edge["best_odds"] == 0.0
        assert edge["ev"] == 0.0
        assert edge["edge_pct"] == 0.0
        assert edge["confirming_signals"] == 0
        assert edge["bookmaker_count"] == 0


# ---------------------------------------------------------------------------
# (h) _load_pregen_edges integrates fixture targets additively
# ---------------------------------------------------------------------------

class TestLoadPregenEdgesIntegration:
    def test_fixture_targets_added_to_load(self, tmp_path, monkeypatch):
        """_load_pregen_edges includes fixture-table targets not in existing edge sources."""
        from pregenerate_narratives import (
            _build_fixture_only_edge,
            discover_pregen_targets,
        )
        import pregenerate_narratives as pn

        tomorrow = _tomorrow_date()
        fixture_target = {
            "match_key": f"chiefs_vs_waratahs_{tomorrow}",
            "sport": "rugby",
            "home_team": "Chiefs",
            "away_team": "Waratahs",
            "league": "Super Rugby",
            "commence_time": f"{tomorrow}T14:00:00+00:00",
            "source_table": "rugby_fixtures",
        }

        # Stub out the existing discovery to return empty lists
        monkeypatch.setattr(pn, "_load_shadow_pregen_edges", lambda **kw: [])
        monkeypatch.setattr(pn, "_load_snapshot_baseline_edges", lambda **kw: [])
        monkeypatch.setattr(pn, "discover_pregen_targets", lambda **kw: [fixture_target])

        edges = pn._load_pregen_edges(limit=10)

        assert len(edges) == 1
        assert edges[0]["match_key"] == fixture_target["match_key"]
        assert edges[0]["sport"] == "rugby"
        assert edges[0]["narrative_source_hint"] == "fixture_only"

    def test_fixture_target_not_added_if_already_in_live_edges(self, tmp_path, monkeypatch):
        """If a fixture match_key is already in live_edges, it is not added again."""
        import pregenerate_narratives as pn

        tomorrow = _tomorrow_date()
        existing_key = f"gujarat_titans_vs_rajasthan_royals_{tomorrow}"
        existing_edge = {
            "match_key": existing_key,
            "sport": "cricket",
            "best_odds": 2.1,
            "ev": 5.0,
        }
        # discover_pregen_targets returns this same match as an odds_snapshots entry
        oddssnap_target = {
            "match_key": existing_key,
            "sport": "cricket",
            "home_team": "gujarat_titans",
            "away_team": "rajasthan_royals",
            "league": "ipl",
            "commence_time": f"{tomorrow}T14:00:00+00:00",
            "source_table": "odds_snapshots",
        }

        monkeypatch.setattr(pn, "_load_shadow_pregen_edges", lambda **kw: [existing_edge])
        monkeypatch.setattr(pn, "_load_snapshot_baseline_edges", lambda **kw: [])
        monkeypatch.setattr(pn, "discover_pregen_targets", lambda **kw: [oddssnap_target])

        edges = pn._load_pregen_edges(limit=10)

        # Should still be exactly 1 — no duplicate
        assert len(edges) == 1
        assert edges[0]["best_odds"] == 2.1  # the original live edge (with odds) is kept

    def test_discovery_failure_is_non_fatal(self, monkeypatch):
        """If discover_pregen_targets raises, _load_pregen_edges continues without fixture targets."""
        import pregenerate_narratives as pn

        monkeypatch.setattr(pn, "_load_shadow_pregen_edges", lambda **kw: [])
        monkeypatch.setattr(pn, "_load_snapshot_baseline_edges", lambda **kw: [])
        monkeypatch.setattr(pn, "discover_pregen_targets", lambda **kw: (_ for _ in ()).throw(RuntimeError("DB exploded")))

        # Must not raise
        edges = pn._load_pregen_edges(limit=10)
        assert isinstance(edges, list)
