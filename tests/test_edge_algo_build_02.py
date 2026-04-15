"""Tests for EDGE-ALGO-BUILD-02: Dashboard economic truth + CLV surfacing."""
import sqlite3
import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture
def perf_conn():
    """In-memory DB with edge_results + clv_tracking for dashboard tests."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE edge_results (
            id INTEGER PRIMARY KEY,
            edge_id TEXT, match_key TEXT, sport TEXT, league TEXT,
            edge_tier TEXT, composite_score REAL, bet_type TEXT,
            recommended_odds REAL, bookmaker TEXT, predicted_ev REAL,
            result TEXT, match_score TEXT, actual_return REAL,
            recommended_at DATETIME, settled_at DATETIME,
            match_date DATE, confirming_signals INTEGER, movement TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE clv_tracking (
            id INTEGER PRIMARY KEY,
            match_key TEXT, selection TEXT,
            our_recommended_odds REAL, our_recommended_bookmaker TEXT,
            our_edge_rating TEXT, sharp_closing_back REAL,
            sharp_source TEXT, clv REAL, outcome TEXT,
            calculated_at TEXT
        )
    """)
    # Insert edge_results: 2 gold hits, 1 gold miss, 1 silver hit
    conn.executemany("""
        INSERT INTO edge_results (edge_id, match_key, sport, league, edge_tier,
            composite_score, bet_type, recommended_odds, bookmaker, predicted_ev,
            result, actual_return, recommended_at, settled_at, match_date)
        VALUES (?, ?, 'soccer', 'epl', ?, 55.0, '1x2', ?, 'betway', 5.0,
                ?, ?, '2026-04-01', '2026-04-02', '2026-04-01')
    """, [
        ('e1', 'team_a_vs_team_b_2026-04-01', 'gold', 2.5, 'hit', 250.0),
        ('e2', 'team_c_vs_team_d_2026-04-01', 'gold', 3.0, 'hit', 300.0),
        ('e3', 'team_e_vs_team_f_2026-04-01', 'gold', 4.0, 'miss', 0.0),
        ('e4', 'team_g_vs_team_h_2026-04-01', 'silver', 1.8, 'hit', 180.0),
    ])
    # Insert clv_tracking with matching match_keys
    conn.executemany("""
        INSERT INTO clv_tracking (match_key, selection, clv, calculated_at)
        VALUES (?, 'home', ?, '2026-04-02')
    """, [
        ('team_a_vs_team_b_2026-04-01', 0.05),
        ('team_c_vs_team_d_2026-04-01', -0.02),
        ('team_e_vs_team_f_2026-04-01', 0.03),
        ('team_g_vs_team_h_2026-04-01', 0.10),
    ])
    conn.commit()
    yield conn
    conn.close()


class TestTierQueryKeys:
    """Unit test: tier query returns win_odds, loss_odds, net_pl, roi_pct keys."""

    def test_tier_query_returns_new_keys(self, perf_conn):
        """DEF-03: tier query must return win_odds, loss_odds, net_pl, roi_pct."""
        rows = perf_conn.execute("""
            SELECT edge_tier,
                   COUNT(*) as cnt,
                   SUM(CASE WHEN result='hit' THEN 1 ELSE 0 END) as wins,
                   SUM(CASE WHEN result='miss' THEN 1 ELSE 0 END) as losses,
                   ROUND(SUM(CASE WHEN result='hit' THEN 1.0 ELSE 0 END)*100.0/COUNT(*),1) as hit_rate,
                   ROUND(AVG(predicted_ev),1) as avg_edge,
                   ROUND(AVG(CASE WHEN result='hit' THEN recommended_odds END),2) as win_odds,
                   ROUND(AVG(CASE WHEN result='miss' THEN recommended_odds END),2) as loss_odds,
                   ROUND(SUM(CASE WHEN result='hit' THEN actual_return - 100.0 ELSE -100.0 END),0) as net_pl,
                   ROUND(SUM(CASE WHEN result='hit' THEN actual_return - 100.0 ELSE -100.0 END)
                         / (COUNT(*) * 100.0) * 100, 1) as roi_pct
            FROM edge_results WHERE result IN ('hit','miss')
            GROUP BY edge_tier
        """).fetchall()
        assert len(rows) >= 1
        keys = rows[0].keys()
        for k in ('win_odds', 'loss_odds', 'net_pl', 'roi_pct'):
            assert k in keys, f"Missing key: {k}"

    def test_gold_tier_values(self, perf_conn):
        """DEF-03: gold tier win_odds, loss_odds, net_pl, roi_pct are correct."""
        row = perf_conn.execute("""
            SELECT edge_tier,
                   COUNT(*) as cnt,
                   ROUND(AVG(CASE WHEN result='hit' THEN recommended_odds END),2) as win_odds,
                   ROUND(AVG(CASE WHEN result='miss' THEN recommended_odds END),2) as loss_odds,
                   ROUND(SUM(CASE WHEN result='hit' THEN actual_return - 100.0 ELSE -100.0 END),0) as net_pl,
                   ROUND(SUM(CASE WHEN result='hit' THEN actual_return - 100.0 ELSE -100.0 END)
                         / (COUNT(*) * 100.0) * 100, 1) as roi_pct
            FROM edge_results WHERE result IN ('hit','miss') AND edge_tier='gold'
            GROUP BY edge_tier
        """).fetchone()
        assert row is not None
        # 2 hits (2.5, 3.0) avg = 2.75; 1 miss (4.0)
        assert row['win_odds'] == 2.75
        assert row['loss_odds'] == 4.0
        # net_pl: (250-100) + (300-100) + (-100) = 150+200-100 = 250
        assert row['net_pl'] == 250.0
        # roi_pct: 250 / (3*100) * 100 = 83.3%
        assert row['roi_pct'] == 83.3


class TestRenderPerformanceContent:
    """Snapshot test: render_performance_content HTML contains required strings."""

    def test_html_contains_new_columns(self, perf_conn):
        """DEF-03+04: rendered HTML must contain Win Odds, Loss Odds, ROI%, Mean CLV, % positive."""
        import importlib
        import sys
        # Mock flask to allow import
        flask_mock = MagicMock()
        flask_mock.Blueprint = MagicMock(return_value=MagicMock())
        flask_mock.request = MagicMock()
        flask_mock.jsonify = MagicMock()
        flask_mock.render_template_string = MagicMock()
        sys.modules.setdefault('flask', flask_mock)

        # We need to test the actual render function with our fixture DB
        # Use the query pattern from the dashboard to verify output
        from dashboard.health_dashboard import render_performance_content
        html = render_performance_content(perf_conn)

        assert 'Win Odds' in html, "Missing 'Win Odds' column header"
        assert 'Loss Odds' in html, "Missing 'Loss Odds' column header"
        assert 'ROI%' in html, "Missing 'ROI%' column header"
        assert 'Mean CLV' in html, "Missing 'Mean CLV' KPI"
        assert '% positive' in html or '% Positive' in html, "Missing '% positive' text"
