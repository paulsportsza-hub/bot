"""ALGO-CAL-1 bot-side serving regressions."""

from __future__ import annotations

import sqlite3
import tempfile
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

# Use dynamic future date so tests don't expire
_FUTURE_DATE = (date.today() + timedelta(days=2)).isoformat()


def _create_edge_results_db(path: str) -> None:
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE edge_results (
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
            confirming_signals INTEGER,
            UNIQUE(match_key, bet_type)
        );
    """)
    conn.executemany("""
        INSERT INTO edge_results
        (edge_id, match_key, sport, league, edge_tier, composite_score, bet_type,
         recommended_odds, bookmaker, predicted_ev, result, recommended_at, match_date)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [
        (
            "edge_old_home",
            f"alpha_vs_beta_{_FUTURE_DATE}",
            "soccer",
            "epl",
            "gold",
            60.0,
            "Home Win",
            2.10,
            "betway",
            5.0,
            None,
            "2026-03-13T08:00:00+00:00",
            _FUTURE_DATE,
        ),
        (
            "edge_new_away",
            f"alpha_vs_beta_{_FUTURE_DATE}",
            "soccer",
            "epl",
            "silver",
            58.0,
            "Away Win",
            2.70,
            "gbets",
            3.5,
            None,
            "2026-03-13T12:00:00+00:00",
            _FUTURE_DATE,
        ),
        (
            "edge_high_ev",
            f"gamma_vs_delta_{_FUTURE_DATE}",
            "soccer",
            "epl",
            "gold",
            65.0,
            "Home Win",
            2.40,
            "betway",
            26.0,
            None,
            "2026-03-13T12:00:00+00:00",
            _FUTURE_DATE,
        ),
        (
            "edge_high_odds",
            f"epsilon_vs_zeta_{_FUTURE_DATE}",
            "soccer",
            "epl",
            "gold",
            64.0,
            "Draw",
            6.40,
            "supabets",
            12.0,
            None,
            "2026-03-13T12:00:00+00:00",
            _FUTURE_DATE,
        ),
        (
            "edge_valid_other",
            f"theta_vs_iota_{_FUTURE_DATE}",
            "soccer",
            "epl",
            "gold",
            62.0,
            "Home Win",
            1.95,
            "hollywoodbets",
            4.2,
            None,
            "2026-03-13T12:00:00+00:00",
            _FUTURE_DATE,
        ),
    ])
    conn.commit()
    conn.close()


def test_load_tips_from_edge_results_serves_one_authoritative_row_per_match():
    import bot

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "odds.db")
        _create_edge_results_db(db_path)

        with patch("scrapers.edge.edge_config.DB_PATH", db_path):
            tips = bot._load_tips_from_edge_results()

    match_ids = [tip["match_id"] for tip in tips]
    assert match_ids.count(f"alpha_vs_beta_{_FUTURE_DATE}") == 1
    assert f"gamma_vs_delta_{_FUTURE_DATE}" not in match_ids
    assert f"epsilon_vs_zeta_{_FUTURE_DATE}" not in match_ids

    alpha_tip = next(tip for tip in tips if tip["match_id"] == f"alpha_vs_beta_{_FUTURE_DATE}")
    assert alpha_tip["outcome"] == "Beta"
    assert alpha_tip["odds"] == 2.7
    assert alpha_tip["ev"] == 3.5
