import sqlite3


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return conn


def _sast_today():
    conn = sqlite3.connect(":memory:")
    try:
        return conn.execute("SELECT date('now', '+2 hours')").fetchone()[0]
    finally:
        conn.close()


def test_source_health_monitor_prefers_live_bookmaker_and_system_evidence(monkeypatch):
    from dashboard import health_dashboard as dash

    conn = _conn()
    conn.executescript(
        """
        CREATE TABLE source_registry (
            source_id TEXT PRIMARY KEY,
            source_name TEXT,
            category TEXT,
            critical INTEGER,
            enabled INTEGER,
            expected_interval_minutes INTEGER,
            cron_schedule TEXT
        );
        CREATE TABLE source_health_current (
            source_id TEXT PRIMARY KEY,
            status TEXT,
            last_success_at TEXT,
            consecutive_failures INTEGER,
            last_rows_produced INTEGER
        );
        CREATE TABLE odds_snapshots (
            bookmaker TEXT,
            match_id TEXT,
            sport TEXT,
            league TEXT,
            scraped_at TEXT
        );
        CREATE TABLE sharp_odds (scraped_at TEXT);
        """
    )
    conn.executemany(
        "INSERT INTO source_registry VALUES (?,?,?,?,?,?,?)",
        [
            ("bk_betway", "Betway", "bookmaker", 1, 1, 90, ""),
            ("sys_disk_usage", "Disk Usage", "system", 1, 1, 30, "*/30 * * * *"),
            ("sys_memory_available", "Memory Available", "system", 1, 1, 30, "*/30 * * * *"),
        ],
    )
    conn.executemany(
        "INSERT INTO source_health_current VALUES (?,?,?,?,?)",
        [
            ("bk_betway", "red", "2026-01-01T00:00:00Z", 4, 0),
            ("sys_disk_usage", "red", "2026-01-01T00:00:00Z", 4, 95),
            ("sys_memory_available", "red", "2026-01-01T00:00:00Z", 4, 500),
        ],
    )
    conn.execute(
        "INSERT INTO odds_snapshots VALUES ('betway', 'team_a_vs_team_b_{}', 'football', 'epl', datetime('now'))".format(_sast_today())
    )

    monkeypatch.setattr(
        dash,
        "_read_server_resources",
        lambda: {"disk_pct": 14, "disk_used": "41G", "disk_total": "300G", "mem_avail_mb": 10_240},
    )

    monitor = dash.build_source_health_monitor(conn)

    assert monitor["green_count"] == 3
    assert monitor["red_count"] == 0
    assert monitor["critical_issues"] == []


def test_card_coverage_matrix_is_core7_and_upcoming_only():
    from dashboard import health_dashboard as dash

    today = _sast_today()
    conn = _conn()
    conn.executescript(
        """
        CREATE TABLE odds_snapshots (
            bookmaker TEXT,
            match_id TEXT,
            sport TEXT,
            league TEXT,
            scraped_at TEXT
        );
        """
    )
    rows = [
        ("betway", f"a_vs_b_{today}", "football", "epl", "now"),
        ("supabets", f"a_vs_b_{today}", "football", "epl", "now"),
        ("betway", f"fighter_a_vs_fighter_b_{today}", "combat", "ufc", "now"),
        ("betway", f"test_a_vs_test_b_{today}", "cricket", "test_cricket", "now"),
        ("betway", "old_a_vs_old_b_2026-01-01", "football", "psl", "now"),
    ]
    conn.executemany(
        "INSERT INTO odds_snapshots VALUES (?,?,?,?,datetime('now'))",
        [(b, m, s, l) for b, m, s, l, _ in rows],
    )

    coverage = dash.build_coverage_matrix(conn)

    assert [(r["sport"], r["league"], r["total"], r["card_ready"]) for r in coverage if r["total"] > 0] == [
        ("football", "EPL", 1, 1)
    ]


def test_brl_orphan_rate_uses_joined_calibration_denominator(monkeypatch):
    from dashboard import health_dashboard as dash

    conn = _conn()
    conn.executescript(
        """
        CREATE TABLE edge_results (
            edge_id TEXT,
            match_key TEXT,
            sport TEXT,
            league TEXT,
            result TEXT,
            recommended_at TEXT
        );
        CREATE TABLE bet_recommendations_log (
            edge_id TEXT,
            logged_at TEXT
        );
        CREATE TABLE odds_snapshots (
            bookmaker TEXT,
            match_id TEXT,
            sport TEXT,
            league TEXT,
            scraped_at TEXT
        );
        """
    )
    conn.execute(
        "INSERT INTO edge_results VALUES ('edge_old_logged','old_logged','football','epl',NULL,datetime('now','-2 hours'))"
    )
    conn.execute(
        "INSERT INTO edge_results VALUES ('edge_recent','recent','football','epl',NULL,datetime('now','-20 minutes'))"
    )
    conn.execute(
        "INSERT INTO edge_results VALUES ('edge_settled','settled','football','epl','hit',datetime('now','-2 hours'))"
    )
    conn.execute(
        "INSERT INTO bet_recommendations_log VALUES ('edge_old_logged',datetime('now','-2 hours'))"
    )

    monkeypatch.setattr(dash, "_fetch_sentry_data", lambda: {"available": True, "total_issues": 0, "by_level": {}, "top_issues": []})
    monkeypatch.setattr(
        dash,
        "_read_server_resources",
        lambda: {
            "cpu_1": 0.1,
            "cpu_5": 0.1,
            "cpu_15": 0.1,
            "mem_pct": 10,
            "mem_used_mb": 100,
            "mem_total_mb": 1000,
            "mem_avail_mb": 900,
            "swap_pct": 0,
            "swap_used_mb": 0,
            "swap_total_mb": 0,
            "disk_pct": 10,
            "disk_used": "1G",
            "disk_total": "10G",
        },
    )
    monkeypatch.setattr(
        dash,
        "_read_process_monitor",
        lambda: {
            "bot": {"running": False, "started": ""},
            "dashboard": {"running": False, "started": ""},
            "publisher": {"running": False, "started": ""},
            "cron_jobs": [],
        },
    )
    monkeypatch.setattr(
        dash,
        "_read_publisher_exceptions",
        lambda: {
            "publisher_last_exception_at": None,
            "publisher_exceptions_24h": 0,
            "publisher_exceptions_72h": 0,
            "recent": [],
        },
    )

    html = dash.render_unified_health_content(conn, "Connected")

    assert "BRL Orphan Rate (24h)" in html
    assert "0.0<span" in html
    assert "1/1 edges logged" in html
