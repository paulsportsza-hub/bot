from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from scrapers.monitors import run_all_monitors
from scrapers.monitors.alert import send_alert
from scrapers.monitors.bookmaker_coverage import check_coverage
from scrapers.monitors.join_health import check_join_health
from scrapers.monitors.null_rate_monitor import check_null_rates
from scrapers.monitors.odds_freshness import check_freshness


SCHEMA = """
CREATE TABLE odds_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bookmaker TEXT,
    match_id TEXT,
    home_team TEXT,
    away_team TEXT,
    league TEXT,
    sport TEXT NOT NULL DEFAULT 'football',
    market_type TEXT NOT NULL DEFAULT '1x2',
    home_odds REAL,
    draw_odds REAL,
    away_odds REAL,
    over_odds REAL,
    under_odds REAL,
    scraped_at TEXT,
    source_url TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    run_id INTEGER,
    handicap_line REAL
)
"""


def _shared_memory_db(name: str) -> tuple[str, sqlite3.Connection]:
    path = f"file:{name}?mode=memory&cache=shared"
    conn = sqlite3.connect(path, uri=True)
    conn.execute(SCHEMA)
    conn.commit()
    return path, conn


def _insert_rows(conn: sqlite3.Connection, rows: list[tuple]) -> None:
    conn.executemany(
        """
        INSERT INTO odds_snapshots (
            bookmaker,
            match_id,
            home_team,
            away_team,
            league,
            sport,
            market_type,
            home_odds,
            draw_odds,
            away_odds,
            over_odds,
            under_odds,
            scraped_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()


def _recent_timestamp(minutes_ago: int = 5) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()


def _stale_timestamp(hours_ago: int = 3) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()


def test_null_rate_monitor_passes_with_clean_db() -> None:
    db_path, conn = _shared_memory_db("null-clean")
    try:
        _insert_rows(
            conn,
            [
                ("betway", "m1", "Arsenal", "Chelsea", "epl", "football", "1x2", 2.1, 3.2, 3.5, None, None, _recent_timestamp()),
                ("hollywoodbets", "m1", "Arsenal", "Chelsea", "epl", "football", "1x2", 2.0, 3.3, 3.6, None, None, _recent_timestamp()),
            ],
        )
        assert check_null_rates(db_path) == []
    finally:
        conn.close()


def test_null_rate_monitor_fails_above_threshold() -> None:
    db_path, conn = _shared_memory_db("null-fail")
    try:
        rows = [
            ("betway", "m1", "Arsenal", "Chelsea", "epl", "football", "1x2", 2.1, 3.2, 3.5, None, None, _recent_timestamp())
            for _ in range(8)
        ]
        rows.extend(
            [
                ("betway", "", "Arsenal", "Chelsea", "epl", "football", "1x2", 2.1, 3.2, 3.5, None, None, _recent_timestamp()),
                ("betway", "", "Arsenal", "Chelsea", "epl", "football", "1x2", 2.1, 3.2, 3.5, None, None, _recent_timestamp()),
            ]
        )
        _insert_rows(conn, rows)
        violations = check_null_rates(db_path)
        assert len(violations) == 1
        assert violations[0]["field"] == "match_id"
        assert violations[0]["null_rate"] == 0.2
    finally:
        conn.close()


def test_bookmaker_coverage_passes_with_good_coverage() -> None:
    db_path, conn = _shared_memory_db("coverage-pass")
    try:
        _insert_rows(
            conn,
            [
                ("betway", "m1", "Arsenal", "Chelsea", "epl", "football", "1x2", 2.1, 3.2, 3.5, None, None, _recent_timestamp()),
                ("hollywoodbets", "m1", "Arsenal", "Chelsea", "epl", "football", "1x2", 2.0, 3.3, 3.6, None, None, _recent_timestamp()),
                ("betway", "m2", "Liverpool", "Everton", "epl", "football", "1x2", 1.8, 3.4, 4.2, None, None, _recent_timestamp()),
                ("sportingbet", "m2", "Liverpool", "Everton", "epl", "football", "1x2", 1.9, 3.5, 4.0, None, None, _recent_timestamp()),
            ],
        )
        assert check_coverage(db_path) == []
    finally:
        conn.close()


def test_bookmaker_coverage_fails_below_threshold() -> None:
    db_path, conn = _shared_memory_db("coverage-fail")
    try:
        _insert_rows(
            conn,
            [
                ("betway", "m1", "Arsenal", "Chelsea", "epl", "football", "1x2", 2.1, 3.2, 3.5, None, None, _recent_timestamp()),
                ("hollywoodbets", "m1", "Arsenal", "Chelsea", "epl", "football", "1x2", 2.0, 3.3, 3.6, None, None, _recent_timestamp()),
                ("betway", "m2", "Liverpool", "Everton", "epl", "football", "1x2", 1.8, 3.4, 4.2, None, None, _recent_timestamp()),
                ("betway", "m3", "Spurs", "City", "epl", "football", "1x2", 3.2, 3.4, 2.1, None, None, _recent_timestamp()),
            ],
        )
        violations = check_coverage(db_path)
        assert len(violations) == 1
        assert violations[0]["league"] == "epl"
        assert violations[0]["rate"] == 0.3333
    finally:
        conn.close()


def test_odds_freshness_passes_with_fresh_data() -> None:
    db_path, conn = _shared_memory_db("freshness-pass")
    try:
        _insert_rows(
            conn,
            [
                ("betway", "m1", "Arsenal", "Chelsea", "epl", "football", "1x2", 2.1, 3.2, 3.5, None, None, _recent_timestamp(10)),
                ("hollywoodbets", "m2", "Liverpool", "Everton", "epl", "football", "1x2", 1.8, 3.4, 4.2, None, None, _recent_timestamp(30)),
            ],
        )
        assert check_freshness(db_path) == []
    finally:
        conn.close()


def test_odds_freshness_fails_with_stale_data() -> None:
    db_path, conn = _shared_memory_db("freshness-fail")
    try:
        _insert_rows(
            conn,
            [
                ("betway", "m1", "Arsenal", "Chelsea", "epl", "football", "1x2", 2.1, 3.2, 3.5, None, None, _stale_timestamp(3)),
            ],
        )
        violations = check_freshness(db_path)
        assert len(violations) == 1
        assert violations[0]["bookmaker"] == "betway"
        assert violations[0]["hours_stale"] >= 3.0
    finally:
        conn.close()


def test_join_health_passes_with_good_resolution() -> None:
    db_path, conn = _shared_memory_db("join-pass")
    try:
        _insert_rows(
            conn,
            [
                ("betway", "m1", "Arsenal", "Chelsea", "epl", "football", "1x2", 2.1, 3.2, 3.5, None, None, _recent_timestamp()),
                ("hollywoodbets", "m1", "Arsenal", "Chelsea", "epl", "football", "1x2", 2.0, 3.3, 3.6, None, None, _recent_timestamp()),
                ("betway", "m2", "Liverpool", "Everton", "epl", "football", "1x2", 1.8, 3.4, 4.2, None, None, _recent_timestamp()),
                ("sportingbet", "m2", "Liverpool", "Everton", "epl", "football", "1x2", 1.9, 3.5, 4.0, None, None, _recent_timestamp()),
                ("betway", "m3", "Spurs", "City", "epl", "football", "1x2", 3.2, 3.4, 2.1, None, None, _recent_timestamp()),
                ("gbets", "m3", "Spurs", "City", "epl", "football", "1x2", 3.1, 3.5, 2.2, None, None, _recent_timestamp()),
            ],
        )
        assert check_join_health(db_path) == []
    finally:
        conn.close()


def test_join_health_fails_above_threshold() -> None:
    db_path, conn = _shared_memory_db("join-fail")
    try:
        _insert_rows(
            conn,
            [
                ("betway", "m1", "Arsenal", "Chelsea", "epl", "football", "1x2", 2.1, 3.2, 3.5, None, None, _recent_timestamp()),
                ("betway", "m2", "Liverpool", "Everton", "epl", "football", "1x2", 1.8, 3.4, 4.2, None, None, _recent_timestamp()),
                ("betway", "m3", "Spurs", "City", "epl", "football", "1x2", 3.2, 3.4, 2.1, None, None, _recent_timestamp()),
                ("hollywoodbets", "m3", "Spurs", "City", "epl", "football", "1x2", 3.1, 3.5, 2.2, None, None, _recent_timestamp()),
            ],
        )
        violations = check_join_health(db_path)
        assert len(violations) == 1
        assert violations[0]["issue"] == "high_single_bookmaker_rate"
        assert violations[0]["rate"] == 0.6667
    finally:
        conn.close()


@patch("scrapers.monitors.alert.requests.post")
def test_alert_module_constructs_expected_payload(mock_post: MagicMock) -> None:
    mock_post.return_value.ok = True
    with patch("scrapers.monitors.alert.ALERT_BOT_TOKEN", "token-123"), patch(
        "scrapers.monitors.alert.ALERT_CHAT_ID", "chat-456"
    ):
        assert send_alert("null_rate", "Detected missing values", severity="CRITICAL") is True

    mock_post.assert_called_once()
    _, kwargs = mock_post.call_args
    assert kwargs["json"]["chat_id"] == "chat-456"
    assert "Monitor: null_rate" in kwargs["json"]["text"]
    assert "Detected missing values" in kwargs["json"]["text"]
    assert "CRITICAL" in kwargs["json"]["text"]


def test_run_all_monitors_returns_all_results() -> None:
    db_path, conn = _shared_memory_db("run-all")
    try:
        _insert_rows(
            conn,
            [
                ("betway", "m1", "Arsenal", "Chelsea", "epl", "football", "1x2", 2.1, 3.2, 3.5, None, None, _recent_timestamp()),
                ("hollywoodbets", "m1", "Arsenal", "Chelsea", "epl", "football", "1x2", 2.0, 3.3, 3.6, None, None, _recent_timestamp()),
            ],
        )
        with patch("scrapers.monitors.null_rate_monitor.send_all_clear", return_value=True), patch(
            "scrapers.monitors.bookmaker_coverage.send_all_clear", return_value=True
        ), patch("scrapers.monitors.join_health.send_all_clear", return_value=True), patch(
            "scrapers.monitors.odds_freshness.send_all_clear", return_value=True
        ):
            result = run_all_monitors(db_path)
        assert result == {
            "null_rate": True,
            "bookmaker_coverage": True,
            "join_health": True,
            "odds_freshness": True,
        }
    finally:
        conn.close()
