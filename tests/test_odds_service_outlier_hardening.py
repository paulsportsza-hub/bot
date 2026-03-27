from __future__ import annotations

import os
import sqlite3
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import ensure_scrapers_importable
ensure_scrapers_importable()

from services import odds_service
from scrapers.edge.signal_collectors import get_clean_best_odds
from scrapers.odds_integrity import detect_price_outliers


def _build_temp_odds_db() -> str:
    fd, path = tempfile.mkstemp(suffix=".sqlite3")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE odds_latest (
            match_id TEXT,
            bookmaker TEXT,
            market_type TEXT,
            home_odds REAL,
            draw_odds REAL,
            away_odds REAL,
            over_odds REAL,
            under_odds REAL,
            last_seen TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE odds_snapshots (
            match_id TEXT,
            home_team TEXT,
            away_team TEXT,
            league TEXT,
            scraped_at TEXT
        )
        """
    )

    match_id = "tottenham_vs_nottingham_forest_2099-01-01"
    rows = [
        (match_id, "betway", "1x2", 1.45, 4.70, 3.00, None, None, "2099-01-01T10:00:00+00:00"),
        (match_id, "hollywoodbets", "1x2", 1.44, 4.75, 3.10, None, None, "2099-01-01T10:00:00+00:00"),
        (match_id, "gbets", "1x2", 1.46, 4.72, 3.20, None, None, "2099-01-01T10:00:00+00:00"),
        (match_id, "sportingbet", "1x2", 1.45, 4.71, 26.00, None, None, "2099-01-01T10:00:00+00:00"),
    ]
    conn.executemany("INSERT INTO odds_latest VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    conn.execute(
        "INSERT INTO odds_snapshots VALUES (?, ?, ?, ?, ?)",
        (match_id, "Tottenham", "Nottingham Forest", "epl", "2099-01-01T10:00:00+00:00"),
    )
    conn.commit()
    conn.close()
    return path


def test_detect_price_outliers_flags_gt_four_x_median_of_others():
    outliers = detect_price_outliers(
        [
            ("betway", 3.00),
            ("hollywoodbets", 3.10),
            ("gbets", 3.20),
            ("sportingbet", 26.00),
        ],
        match_id="tottenham_vs_nottingham_forest_2099-01-01",
        selection="away",
    )

    assert len(outliers) == 1
    assert outliers[0]["bookmaker"] == "sportingbet"
    assert outliers[0]["ratio_vs_others"] > 4.0
    assert "median-of-others" in outliers[0]["reason"]


def test_detect_price_outliers_still_catches_milder_outlier():
    outliers = detect_price_outliers(
        [
            ("bk1", 3.00),
            ("bk2", 3.05),
            ("bk3", 3.10),
            ("bk4", 6.20),
        ],
        match_id="mild_outlier_match",
        selection="away",
    )

    assert len(outliers) == 1
    assert outliers[0]["bookmaker"] == "bk4"


def test_detect_price_outliers_keeps_normal_variation():
    outliers = detect_price_outliers(
        [
            ("bk1", 2.70),
            ("bk2", 2.74),
            ("bk3", 2.78),
            ("bk4", 2.80),
        ],
        match_id="normal_variation_match",
        selection="away",
    )

    assert outliers == []


def test_get_clean_best_odds_excludes_extreme_outlier():
    best_odds, best_bookmaker, outliers = get_clean_best_odds(
        [
            (3.00, "betway"),
            (3.10, "hollywoodbets"),
            (3.20, "gbets"),
            (26.00, "sportingbet"),
        ],
        "tottenham_vs_nottingham_forest_2099-01-01",
    )

    assert best_odds == 3.20
    assert best_bookmaker == "gbets"
    assert any(item[1] == "sportingbet" for item in outliers)


@pytest.mark.asyncio
async def test_get_best_odds_filters_outlier_from_best_price():
    temp_db = _build_temp_odds_db()
    original_path = odds_service.ODDS_DB_PATH
    odds_service.ODDS_DB_PATH = temp_db
    try:
        result = await odds_service.get_best_odds(
            "tottenham_vs_nottingham_forest_2099-01-01",
            "1x2",
        )
    finally:
        odds_service.ODDS_DB_PATH = original_path
        os.unlink(temp_db)

    away = result["outcomes"]["away"]
    assert away["best_odds"] == 3.20
    assert away["best_bookmaker"] == "gbets"
    assert "sportingbet" not in away["all_bookmakers"]
