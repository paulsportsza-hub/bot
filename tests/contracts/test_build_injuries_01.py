"""BUILD-INJURIES-01 — Contract tests for team_injuries pipeline + card_pipeline wiring.

Verifies:
  1. team_injuries rows (API-Football source) appear in build_verified_data_block injuries list.
  2. 'team_injuries' is appended to data_sources_used when rows are found.
  3. 'Missing Fixture' and 'Unknown' statuses are excluded from the card pipeline.
  4. Players are assigned to the correct side (home/away) via snake_case normalisation.
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def _make_db(tmp_path) -> tuple[str, sqlite3.Connection]:
    """Create a minimal odds.db with team_injuries, extracted_injuries, and fpl_injuries tables."""
    db_path = str(tmp_path / "test_odds.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS team_injuries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            league TEXT NOT NULL,
            team TEXT NOT NULL,
            player_name TEXT NOT NULL,
            player_id INTEGER,
            injury_type TEXT,
            injury_reason TEXT,
            injury_status TEXT,
            fixture_id INTEGER,
            fixture_date TEXT,
            fetched_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS extracted_injuries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            article_id INTEGER,
            player_name TEXT NOT NULL,
            team_key TEXT NOT NULL,
            status TEXT NOT NULL,
            injury_type TEXT,
            keyword_match TEXT,
            confidence TEXT DEFAULT 'medium',
            extracted_at TEXT NOT NULL,
            expires_at TEXT
        );
        CREATE TABLE IF NOT EXISTS fpl_injuries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fpl_player_id INTEGER NOT NULL,
            player_name TEXT NOT NULL,
            team_key TEXT NOT NULL,
            fpl_status TEXT NOT NULL,
            news TEXT,
            news_added TEXT,
            chance_this_round INTEGER,
            chance_next_round INTEGER,
            fetched_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS match_lineups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_key TEXT NOT NULL,
            api_fixture_id INTEGER NOT NULL,
            team TEXT NOT NULL,
            team_side TEXT NOT NULL,
            formation TEXT,
            player_name TEXT NOT NULL,
            player_id INTEGER,
            player_number INTEGER,
            player_pos TEXT,
            is_starter INTEGER DEFAULT 1,
            grid_position TEXT,
            lineup_source TEXT DEFAULT 'api_football',
            confirmed INTEGER DEFAULT 0,
            fetched_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS odds_latest (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bookmaker TEXT NOT NULL,
            match_id TEXT NOT NULL,
            home_team TEXT,
            away_team TEXT,
            league TEXT,
            home_odds REAL,
            draw_odds REAL,
            away_odds REAL,
            scraped_at TEXT,
            market_type TEXT DEFAULT '1x2'
        );
        CREATE TABLE IF NOT EXISTS odds_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bookmaker TEXT NOT NULL,
            match_id TEXT NOT NULL,
            home_team TEXT,
            away_team TEXT,
            league TEXT,
            home_odds REAL,
            draw_odds REAL,
            away_odds REAL,
            over_odds REAL,
            under_odds REAL,
            scraped_at TEXT,
            market_type TEXT DEFAULT '1x2'
        );
        CREATE TABLE IF NOT EXISTS match_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_key TEXT,
            home_team TEXT,
            away_team TEXT,
            home_score INTEGER,
            away_score INTEGER,
            league TEXT,
            match_date TEXT
        );
        CREATE TABLE IF NOT EXISTS team_ratings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            team_name TEXT NOT NULL,
            sport TEXT,
            mu REAL,
            phi REAL,
            sigma REAL
        );
        CREATE TABLE IF NOT EXISTS elo_ratings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            team TEXT NOT NULL,
            sport TEXT,
            rating REAL
        );
        CREATE TABLE IF NOT EXISTS narrative_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_key TEXT UNIQUE,
            narrative_html TEXT,
            odds_hash TEXT,
            updated_at TEXT
        );
    """)
    conn.commit()
    return db_path, conn


def _insert_team_injury(conn, team, player_name, injury_status, injury_reason="", league="epl"):
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO team_injuries (league, team, player_name, injury_type, "
        "injury_reason, injury_status, fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (league, team, player_name, injury_status, injury_reason, injury_status, now),
    )
    conn.commit()


# ── AC-1: team_injuries rows appear in the injuries list ──────────────────────

def test_ac1_team_injuries_appear_in_verified_data(tmp_path, monkeypatch):
    """team_injuries rows are fetched and added to verified_data['injuries']."""
    db_path, conn = _make_db(tmp_path)
    _insert_team_injury(conn, "Arsenal", "B. White", "Doubtful", "Knee")
    _insert_team_injury(conn, "Bournemouth", "D. Brooks", "Injured", "Ankle")
    conn.close()

    import card_pipeline
    monkeypatch.setattr(card_pipeline, "_ODDS_DB_PATH", db_path)

    verified = card_pipeline.build_verified_data_block(
        "arsenal_vs_bournemouth_2026-04-11",
        conn=None,
    )
    injuries = verified.get("injuries", [])
    sources = verified.get("data_sources_used", [])

    # At least one team_injuries entry must appear
    assert any("B. White" in inj or "D. Brooks" in inj for inj in injuries), (
        f"team_injuries players not found in injuries list: {injuries}"
    )
    assert "team_injuries" in sources, f"team_injuries not in data_sources_used: {sources}"


# ── AC-2: Missing Fixture / Unknown are excluded ──────────────────────────────

def test_ac2_missing_fixture_excluded(tmp_path, monkeypatch):
    """Players with Missing Fixture or Unknown status must not appear in injuries."""
    db_path, conn = _make_db(tmp_path)
    _insert_team_injury(conn, "Arsenal", "Ghost Player", "Missing Fixture")
    _insert_team_injury(conn, "Arsenal", "Unknown Player", "Unknown")
    _insert_team_injury(conn, "Arsenal", "Real Player", "Questionable", "Hamstring")
    conn.close()

    import card_pipeline
    monkeypatch.setattr(card_pipeline, "_ODDS_DB_PATH", db_path)

    verified = card_pipeline.build_verified_data_block(
        "arsenal_vs_chelsea_2026-04-12",
        conn=None,
    )
    injuries = verified.get("injuries", [])

    assert not any("Ghost Player" in inj for inj in injuries), (
        "Missing Fixture player leaked into injuries"
    )
    assert not any("Unknown Player" in inj for inj in injuries), (
        "Unknown status player leaked into injuries"
    )
    assert any("Real Player" in inj for inj in injuries), (
        f"Valid injury not found: {injuries}"
    )


# ── AC-3: Side assignment — home vs away ──────────────────────────────────────

def test_ac3_player_assigned_to_correct_side(tmp_path, monkeypatch):
    """Home player gets home_key in injury string; away player gets away_key."""
    db_path, conn = _make_db(tmp_path)
    _insert_team_injury(conn, "West Ham", "L. Fabianski", "Injured", "Back")
    _insert_team_injury(conn, "Wolves", "L. Chiwome", "Doubtful", "Knee")
    conn.close()

    import card_pipeline
    monkeypatch.setattr(card_pipeline, "_ODDS_DB_PATH", db_path)

    verified = card_pipeline.build_verified_data_block(
        "west_ham_vs_wolves_2026-04-10",
        conn=None,
    )
    injuries = verified.get("injuries", [])

    home_entry = next((inj for inj in injuries if "Fabianski" in inj), None)
    away_entry = next((inj for inj in injuries if "Chiwome" in inj), None)

    assert home_entry is not None, f"Home player not found: {injuries}"
    assert away_entry is not None, f"Away player not found: {injuries}"
    # Side key should be snake_case team key, not raw API team name
    assert "west_ham" in home_entry, f"Expected west_ham in '{home_entry}'"
    assert "wolves" in away_entry, f"Expected wolves in '{away_entry}'"


# ── AC-4: No crash when team_injuries table is empty ─────────────────────────

def test_ac4_empty_team_injuries_no_crash(tmp_path, monkeypatch):
    """build_verified_data_block must not crash when team_injuries has no rows."""
    db_path, conn = _make_db(tmp_path)
    conn.close()

    import card_pipeline
    monkeypatch.setattr(card_pipeline, "_ODDS_DB_PATH", db_path)

    verified = card_pipeline.build_verified_data_block(
        "liverpool_vs_mancity_2026-04-13",
        conn=None,
    )
    # Should not raise, injuries list may be empty or have other sources
    assert isinstance(verified.get("injuries", []), list)
    assert "team_injuries" not in verified.get("data_sources_used", [])
