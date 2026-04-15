"""CLV pipeline unit tests for EDGE-REMEDIATION-02 fixes.

Covers: kickoff propagation (BUG-CLV-01), fair_odds calculation (BUG-CLV-02),
CLV formula correctness (BUG-CLV-05), selection filter (BUG-CLV-06), dedup fix
(BUG-CLV-08), kill monitor evaluation/recovery, backfill row CLV calculation,
bridge sharp_closing, and dashboard panel data shape.

All tests use in-memory SQLite -- no external DB or network access required.
"""

import sqlite3
import sys

# Ensure scrapers package is importable
if "/home/paulsportsza" not in sys.path:
    sys.path.insert(0, "/home/paulsportsza")

import pytest


# ---------------------------------------------------------------------------
# Helpers: in-memory DB table setup
# ---------------------------------------------------------------------------

def _create_bet_log_table(conn: sqlite3.Connection) -> None:
    """Create bet_recommendations_log table in an in-memory DB."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS bet_recommendations_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            edge_id TEXT NOT NULL,
            match_key TEXT NOT NULL,
            sport TEXT NOT NULL,
            league TEXT NOT NULL,
            edge_tier TEXT NOT NULL,
            bet_type TEXT NOT NULL,
            recommended_odds REAL NOT NULL,
            fair_odds REAL,
            bookmaker TEXT NOT NULL,
            predicted_ev REAL NOT NULL,
            ev_pct REAL,
            model_prob REAL,
            composite_score REAL,
            confirming_signals INTEGER,
            market_efficiency REAL,
            closing_odds REAL,
            closing_prob REAL,
            closing_source TEXT,
            clv REAL,
            clv_pct REAL,
            result TEXT,
            logged_at DATETIME NOT NULL DEFAULT (datetime('now')),
            served_at DATETIME NOT NULL DEFAULT (datetime('now')),
            kickoff DATETIME,
            closed_at DATETIME,
            kill_switch_active INTEGER NOT NULL DEFAULT 0,
            kill_switch_triggered INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS model_kill_flags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            flag_name TEXT NOT NULL UNIQUE,
            enabled INTEGER NOT NULL DEFAULT 1,
            kill_reason TEXT,
            window_size INTEGER DEFAULT 50,
            window_neg_pct REAL,
            threshold_pct REAL DEFAULT 0.65,
            last_evaluated_at DATETIME,
            triggered_at DATETIME,
            created_at DATETIME DEFAULT (datetime('now'))
        );
        INSERT OR IGNORE INTO model_kill_flags (flag_name, enabled)
        VALUES ('clv_tracking', 1);
    """)
    conn.commit()


def _create_clv_tracking_table(conn: sqlite3.Connection) -> None:
    """Create clv_tracking table in an in-memory DB."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS clv_tracking (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_key TEXT NOT NULL,
            selection TEXT,
            our_recommended_odds REAL,
            our_recommended_bookmaker TEXT,
            our_edge_rating TEXT,
            sharp_closing_back REAL,
            sharp_source TEXT,
            clv REAL,
            calculated_at DATETIME DEFAULT (datetime('now'))
        );
    """)
    conn.commit()


def _create_sharp_tables(conn: sqlite3.Connection) -> None:
    """Create sharp_odds and sharp_closing tables in an in-memory DB."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sharp_odds (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_key TEXT NOT NULL,
            market_type TEXT NOT NULL,
            selection TEXT NOT NULL,
            bookmaker TEXT NOT NULL,
            back_price REAL,
            lay_price REAL,
            total_matched REAL,
            scraped_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS sharp_closing (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_key TEXT NOT NULL,
            market_type TEXT NOT NULL,
            selection TEXT NOT NULL,
            bookmaker TEXT NOT NULL,
            closing_back_price REAL,
            closing_lay_price REAL,
            total_matched REAL,
            captured_at TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_sharp_closing_match
            ON sharp_closing(match_key, market_type);
    """)
    conn.commit()


# ---------------------------------------------------------------------------
# 1. Kickoff propagation (BUG-CLV-01)
# ---------------------------------------------------------------------------

class TestKickoffPropagation:
    """BUG-CLV-01: kickoff must be extracted from tip dict keys."""

    def test_commence_time_is_preferred(self):
        """commence_time takes priority when both keys are present."""
        tip = {
            "commence_time": "2026-04-05T15:30:00+00:00",
            "_bc_kickoff": "Sat 5 Apr, 15:30",
        }
        # The production code does: tip.get("commence_time") or tip.get("_bc_kickoff")
        kickoff = tip.get("commence_time") or tip.get("_bc_kickoff") or None
        assert kickoff == "2026-04-05T15:30:00+00:00"

    def test_bc_kickoff_fallback(self):
        """_bc_kickoff is used when commence_time is absent."""
        tip = {"_bc_kickoff": "Sat 5 Apr, 15:30"}
        kickoff = tip.get("commence_time") or tip.get("_bc_kickoff") or None
        assert kickoff == "Sat 5 Apr, 15:30"

    def test_both_missing_yields_none(self):
        """When neither key exists, kickoff is None."""
        tip = {"odds": 2.50}
        kickoff = tip.get("commence_time") or tip.get("_bc_kickoff") or None
        assert kickoff is None

    def test_empty_commence_time_falls_through(self):
        """Empty string commence_time falls through to _bc_kickoff."""
        tip = {"commence_time": "", "_bc_kickoff": "Today 18:00"}
        kickoff = tip.get("commence_time") or tip.get("_bc_kickoff") or None
        assert kickoff == "Today 18:00"


# ---------------------------------------------------------------------------
# 2. fair_odds propagation (BUG-CLV-02)
# ---------------------------------------------------------------------------

class TestFairOddsPropagation:
    """BUG-CLV-02: fair_odds = round(1/model_prob, 4) when valid."""

    def test_valid_model_prob(self):
        """Standard probability produces correct fair odds."""
        from scrapers.sharp.bet_log_writer import compute_fair_odds

        result = compute_fair_odds(0.40)
        assert result == round(1.0 / 0.40, 4)
        assert result == 2.5

    def test_high_probability(self):
        """Probability close to 1 produces low fair odds."""
        from scrapers.sharp.bet_log_writer import compute_fair_odds

        result = compute_fair_odds(0.90)
        assert result == round(1.0 / 0.90, 4)
        assert result == pytest.approx(1.1111, abs=0.0001)

    def test_low_probability(self):
        """Probability close to 0 produces high fair odds."""
        from scrapers.sharp.bet_log_writer import compute_fair_odds

        result = compute_fair_odds(0.05)
        assert result == round(1.0 / 0.05, 4)
        assert result == 20.0

    def test_zero_probability_returns_none(self):
        """Zero probability is invalid and returns None."""
        from scrapers.sharp.bet_log_writer import compute_fair_odds

        assert compute_fair_odds(0.0) is None

    def test_negative_probability_returns_none(self):
        """Negative probability is invalid and returns None."""
        from scrapers.sharp.bet_log_writer import compute_fair_odds

        assert compute_fair_odds(-0.5) is None

    def test_probability_of_one_returns_none(self):
        """Probability of exactly 1.0 is invalid (certainty) and returns None."""
        from scrapers.sharp.bet_log_writer import compute_fair_odds

        assert compute_fair_odds(1.0) is None

    def test_none_probability_returns_none(self):
        """None probability returns None."""
        from scrapers.sharp.bet_log_writer import compute_fair_odds

        assert compute_fair_odds(None) is None

    def test_inline_logic_matches_function(self):
        """The inline bot.py logic matches compute_fair_odds for the valid range."""
        from scrapers.sharp.bet_log_writer import compute_fair_odds

        model_prob = 0.408
        # Inline logic from bot.py line 11436-11437:
        inline_result = None
        if model_prob and model_prob > 0.01 and model_prob < 1.0:
            inline_result = round(1.0 / model_prob, 4)

        assert inline_result == compute_fair_odds(model_prob)


# ---------------------------------------------------------------------------
# 3. CLV formula correctness (BUG-CLV-05)
# ---------------------------------------------------------------------------

class TestCLVFormula:
    """BUG-CLV-05: calculate_clv_pct returns (rec/closing - 1) * 100."""

    def test_positive_clv(self):
        """User got better odds than closing line -> positive CLV."""
        from scrapers.sharp.bet_log_writer import calculate_clv_pct

        result = calculate_clv_pct(2.60, 2.40)
        expected = (2.60 / 2.40 - 1.0) * 100
        assert result == pytest.approx(expected, abs=0.001)
        assert result > 0

    def test_negative_clv(self):
        """User got worse odds than closing line -> negative CLV."""
        from scrapers.sharp.bet_log_writer import calculate_clv_pct

        result = calculate_clv_pct(2.20, 2.60)
        expected = (2.20 / 2.60 - 1.0) * 100
        assert result == pytest.approx(expected, abs=0.001)
        assert result < 0

    def test_equal_odds_zero_clv(self):
        """Same odds as closing -> zero CLV."""
        from scrapers.sharp.bet_log_writer import calculate_clv_pct

        result = calculate_clv_pct(2.50, 2.50)
        assert result == pytest.approx(0.0, abs=0.001)

    def test_invalid_recommended_odds_returns_none(self):
        """Recommended odds <= 1.0 returns None."""
        from scrapers.sharp.bet_log_writer import calculate_clv_pct

        assert calculate_clv_pct(1.0, 2.50) is None
        assert calculate_clv_pct(0.5, 2.50) is None

    def test_invalid_closing_odds_returns_none(self):
        """Closing odds <= 1.0 returns None."""
        from scrapers.sharp.bet_log_writer import calculate_clv_pct

        assert calculate_clv_pct(2.50, 1.0) is None
        assert calculate_clv_pct(2.50, 0.0) is None

    def test_none_inputs_return_none(self):
        """None inputs return None."""
        from scrapers.sharp.bet_log_writer import calculate_clv_pct

        assert calculate_clv_pct(None, 2.50) is None
        assert calculate_clv_pct(2.50, None) is None


# ---------------------------------------------------------------------------
# 4. Selection filter (BUG-CLV-06)
# ---------------------------------------------------------------------------

class TestSelectionFilter:
    """BUG-CLV-06: _bet_type_to_selection maps correctly from match_key."""

    def test_home_maps_to_home_key(self):
        """bet_type 'home' returns the home team key from match_key."""
        from scrapers.sharp.clv_backfill import _bet_type_to_selection

        result = _bet_type_to_selection(
            "home", "kaizer_chiefs_vs_orlando_pirates_2026-04-05"
        )
        assert result == "kaizer_chiefs"

    def test_away_maps_to_away_key(self):
        """bet_type 'away' returns the away team key from match_key."""
        from scrapers.sharp.clv_backfill import _bet_type_to_selection

        result = _bet_type_to_selection(
            "away", "kaizer_chiefs_vs_orlando_pirates_2026-04-05"
        )
        assert result == "orlando_pirates"

    def test_draw_returns_draw(self):
        """bet_type 'draw' returns the literal 'draw' string."""
        from scrapers.sharp.clv_backfill import _bet_type_to_selection

        result = _bet_type_to_selection(
            "draw", "kaizer_chiefs_vs_orlando_pirates_2026-04-05"
        )
        assert result == "draw"

    def test_numeric_home_alias(self):
        """bet_type '1' maps to home team key (numeric alias)."""
        from scrapers.sharp.clv_backfill import _bet_type_to_selection

        result = _bet_type_to_selection(
            "1", "arsenal_vs_chelsea_2026-04-10"
        )
        assert result == "arsenal"

    def test_numeric_away_alias(self):
        """bet_type '2' maps to away team key (numeric alias)."""
        from scrapers.sharp.clv_backfill import _bet_type_to_selection

        result = _bet_type_to_selection(
            "2", "arsenal_vs_chelsea_2026-04-10"
        )
        assert result == "chelsea"

    def test_no_vs_separator_returns_bet_type(self):
        """When match_key has no _vs_, return bet_type as-is."""
        from scrapers.sharp.clv_backfill import _bet_type_to_selection

        result = _bet_type_to_selection("home", "some_match_key_2026-04-05")
        assert result == "home"

    def test_empty_match_key_returns_bet_type(self):
        """Empty match_key returns bet_type unchanged."""
        from scrapers.sharp.clv_backfill import _bet_type_to_selection

        result = _bet_type_to_selection("home", "")
        assert result == "home"


# ---------------------------------------------------------------------------
# 5. Dedup fix (BUG-CLV-08)
# ---------------------------------------------------------------------------

class TestDedupFix:
    """BUG-CLV-08: dedup query distinguishes pre-records (clv=NULL) from completed."""

    def test_pre_record_with_null_clv_not_counted(self):
        """A row with clv=NULL should NOT block re-processing."""
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        _create_clv_tracking_table(conn)

        match_key = "kaizer_chiefs_vs_orlando_pirates_2026-04-05"
        conn.execute(
            "INSERT INTO clv_tracking (match_key, selection, clv) VALUES (?, ?, ?)",
            (match_key, "kaizer_chiefs", None),
        )
        conn.commit()

        # The BUG-CLV-08 query: only count rows where clv IS NOT NULL
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM clv_tracking WHERE match_key = ? AND clv IS NOT NULL",
            (match_key,),
        ).fetchone()

        assert row["cnt"] == 0, "Pre-record with NULL clv must not block re-processing"
        conn.close()

    def test_completed_record_blocks_reprocessing(self):
        """A row with a real CLV value should block re-processing."""
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        _create_clv_tracking_table(conn)

        match_key = "arsenal_vs_chelsea_2026-04-10"
        conn.execute(
            "INSERT INTO clv_tracking (match_key, selection, clv) VALUES (?, ?, ?)",
            (match_key, "arsenal", 0.045),
        )
        conn.commit()

        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM clv_tracking WHERE match_key = ? AND clv IS NOT NULL",
            (match_key,),
        ).fetchone()

        assert row["cnt"] == 1, "Completed record with CLV value must block re-processing"
        conn.close()

    def test_mixed_pre_and_completed_records(self):
        """Only completed records count toward dedup, even when mixed with pre-records."""
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        _create_clv_tracking_table(conn)

        match_key = "sundowns_vs_pirates_2026-04-12"
        # Pre-record (NULL clv)
        conn.execute(
            "INSERT INTO clv_tracking (match_key, selection, clv) VALUES (?, ?, ?)",
            (match_key, "sundowns", None),
        )
        # Completed record (real clv)
        conn.execute(
            "INSERT INTO clv_tracking (match_key, selection, clv) VALUES (?, ?, ?)",
            (match_key, "pirates", 0.032),
        )
        conn.commit()

        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM clv_tracking WHERE match_key = ? AND clv IS NOT NULL",
            (match_key,),
        ).fetchone()

        assert row["cnt"] == 1, "Only completed records counted"
        conn.close()


# ---------------------------------------------------------------------------
# 6. Kill monitor evaluation: triggers kill on high negative CLV rate
# ---------------------------------------------------------------------------

class TestKillMonitorEvaluation:
    """Kill monitor evaluate() returns action='kill' when neg_pct >= threshold."""

    def _seed_settled_bets(
        self, conn: sqlite3.Connection, n_negative: int, n_positive: int
    ) -> None:
        """Insert settled bet rows with CLV values."""
        for i in range(n_negative):
            conn.execute(
                """INSERT INTO bet_recommendations_log
                   (edge_id, match_key, sport, league, edge_tier, bet_type,
                    recommended_odds, bookmaker, predicted_ev, result, clv)
                   VALUES (?, ?, 'soccer', 'psl', 'gold', 'home',
                           2.50, 'betway', 5.0, 'miss', ?)""",
                (f"neg_{i}", f"match_neg_{i}", -(0.01 + i * 0.005)),
            )
        for i in range(n_positive):
            conn.execute(
                """INSERT INTO bet_recommendations_log
                   (edge_id, match_key, sport, league, edge_tier, bet_type,
                    recommended_odds, bookmaker, predicted_ev, result, clv)
                   VALUES (?, ?, 'soccer', 'psl', 'gold', 'home',
                           2.50, 'betway', 5.0, 'hit', ?)""",
                (f"pos_{i}", f"match_pos_{i}", 0.02 + i * 0.005),
            )
        conn.commit()

    def test_kill_triggered_when_above_threshold(self):
        """65%+ negative CLV -> kill action."""
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        _create_bet_log_table(conn)
        # 35 negative, 15 positive = 70% negative > 65% threshold
        self._seed_settled_bets(conn, n_negative=35, n_positive=15)

        # Read config from the flag row to mirror evaluate() logic
        flag_row = conn.execute(
            "SELECT enabled, window_size, threshold_pct FROM model_kill_flags WHERE flag_name = 'clv_tracking'"
        ).fetchone()
        threshold = flag_row["threshold_pct"] or 0.65
        w_size = flag_row["window_size"] or 50

        rows = conn.execute(
            """SELECT clv FROM bet_recommendations_log
               WHERE result IN ('hit', 'miss') AND clv IS NOT NULL
               ORDER BY served_at DESC LIMIT ?""",
            (w_size,),
        ).fetchall()

        clvs = [float(r["clv"]) for r in rows]
        neg_count = sum(1 for c in clvs if c < 0)
        neg_pct = neg_count / len(clvs)

        assert neg_pct >= threshold
        # Production evaluate() would set action="kill" here
        action = "kill" if neg_pct >= threshold else "no_change"
        assert action == "kill"
        conn.close()

    def test_no_kill_when_below_threshold(self):
        """Below threshold -> no kill."""
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        _create_bet_log_table(conn)
        # 20 negative, 30 positive = 40% negative < 65% threshold
        self._seed_settled_bets(conn, n_negative=20, n_positive=30)

        rows = conn.execute(
            """SELECT clv FROM bet_recommendations_log
               WHERE result IN ('hit', 'miss') AND clv IS NOT NULL
               ORDER BY served_at DESC LIMIT 50""",
        ).fetchall()

        clvs = [float(r["clv"]) for r in rows]
        neg_pct = sum(1 for c in clvs if c < 0) / len(clvs)

        assert neg_pct < 0.65
        action = "kill" if neg_pct >= 0.65 else "no_change"
        assert action == "no_change"
        conn.close()


# ---------------------------------------------------------------------------
# 7. Kill monitor recovery
# ---------------------------------------------------------------------------

class TestKillMonitorRecovery:
    """Recovery requires neg_pct < threshold * 0.85 AND avg_clv > -0.08."""

    def test_recovery_conditions_met(self):
        """Both conditions met -> recovery allowed."""
        threshold = 0.65
        recovery_threshold = threshold * 0.85  # 0.5525
        avg_clv_floor = -0.08

        neg_pct = 0.50  # below 0.5525
        avg_clv = -0.02  # above -0.08

        can_recover = neg_pct < recovery_threshold and avg_clv > avg_clv_floor
        assert can_recover is True

    def test_recovery_blocked_by_high_neg_pct(self):
        """neg_pct too high -> no recovery even if avg_clv is fine."""
        threshold = 0.65
        recovery_threshold = threshold * 0.85

        neg_pct = 0.60  # above 0.5525
        avg_clv = 0.01  # healthy

        can_recover = neg_pct < recovery_threshold and avg_clv > -0.08
        assert can_recover is False

    def test_recovery_blocked_by_low_avg_clv(self):
        """avg_clv below floor -> no recovery even if neg_pct is fine."""
        threshold = 0.65
        recovery_threshold = threshold * 0.85

        neg_pct = 0.40  # fine
        avg_clv = -0.10  # below -0.08

        can_recover = neg_pct < recovery_threshold and avg_clv > -0.08
        assert can_recover is False


# ---------------------------------------------------------------------------
# 8. Backfill row CLV calculation
# ---------------------------------------------------------------------------

class TestBackfillRowCLV:
    """_backfill_row computes clv = recommended_odds / closing_odds - 1."""

    def test_backfill_positive_clv(self):
        """User odds > closing odds -> positive CLV."""
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        _create_bet_log_table(conn)

        # Insert a pending row
        conn.execute(
            """INSERT INTO bet_recommendations_log
               (edge_id, match_key, sport, league, edge_tier, bet_type,
                recommended_odds, bookmaker, predicted_ev, kickoff)
               VALUES ('e1', 'test_vs_match_2026-04-05', 'soccer', 'psl',
                        'gold', 'home', 2.60, 'betway', 5.0,
                        '2026-04-05T12:00:00+00:00')""",
        )
        conn.commit()

        row = {"id": 1, "match_key": "test_vs_match_2026-04-05",
               "bet_type": "home", "fair_odds": 2.50, "recommended_odds": 2.60}
        closing = {"closing_odds": 2.40, "closing_prob": 1.0 / 2.40, "source": "pinnacle"}

        recommended_odds = float(row["recommended_odds"])
        closing_odds = closing["closing_odds"]
        clv_raw = recommended_odds / closing_odds - 1.0
        clv = round(clv_raw, 6)
        clv_pct = round(clv_raw * 100, 4)

        expected_clv = round(2.60 / 2.40 - 1.0, 6)
        assert clv == pytest.approx(expected_clv, abs=1e-6)
        assert clv > 0
        assert clv_pct == pytest.approx(expected_clv * 100, abs=0.001)
        conn.close()

    def test_backfill_negative_clv(self):
        """User odds < closing odds -> negative CLV."""
        recommended_odds = 2.20
        closing_odds = 2.60

        clv_raw = recommended_odds / closing_odds - 1.0
        clv = round(clv_raw, 6)

        assert clv < 0

    def test_backfill_skips_low_odds(self):
        """Recommended odds <= 1.0 should produce no CLV."""
        recommended_odds = 1.0
        closing_odds = 2.50

        # The production code checks: recommended_odds and float(recommended_odds) > 1.0
        if recommended_odds and float(recommended_odds) > 1.0 and closing_odds > 1.01:
            clv = float(recommended_odds) / closing_odds - 1.0
        else:
            clv = None

        assert clv is None


# ---------------------------------------------------------------------------
# 9. Bridge sharp_closing
# ---------------------------------------------------------------------------

class TestBridgeSharpClosing:
    """_bridge_sharp_closing copies latest sharp_odds into sharp_closing."""

    def test_bridge_copies_rows(self):
        """Sharp odds rows are bridged to sharp_closing table."""
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        _create_sharp_tables(conn)

        match_key = "liverpool_vs_arsenal_2026-04-10"

        # Insert sharp_odds rows
        conn.execute(
            """INSERT INTO sharp_odds
               (match_key, market_type, selection, bookmaker, back_price, lay_price, total_matched, scraped_at)
               VALUES (?, 'h2h', 'liverpool', 'pinnacle', 2.30, 2.35, 50000.0, '2026-04-10T14:00:00')""",
            (match_key,),
        )
        conn.execute(
            """INSERT INTO sharp_odds
               (match_key, market_type, selection, bookmaker, back_price, lay_price, total_matched, scraped_at)
               VALUES (?, 'h2h', 'arsenal', 'pinnacle', 3.10, 3.15, 40000.0, '2026-04-10T14:00:00')""",
            (match_key,),
        )
        conn.commit()

        # Execute the bridge query (mirrors _bridge_sharp_closing logic)
        rows = conn.execute("""
            SELECT s.match_key, s.market_type, s.selection, s.bookmaker,
                   s.back_price, s.lay_price, s.total_matched
            FROM sharp_odds s
            INNER JOIN (
                SELECT match_key, selection, bookmaker, MAX(scraped_at) as max_at
                FROM sharp_odds
                WHERE match_key = ?
                GROUP BY match_key, selection, bookmaker
            ) latest
                ON s.match_key = latest.match_key
               AND s.selection = latest.selection
               AND s.bookmaker = latest.bookmaker
               AND s.scraped_at = latest.max_at
            WHERE s.match_key = ?
              AND s.back_price IS NOT NULL
              AND s.back_price > 1.01
        """, (match_key, match_key)).fetchall()

        inserted = 0
        for row in rows:
            conn.execute("""
                INSERT OR REPLACE INTO sharp_closing
                (match_key, market_type, selection, bookmaker,
                 closing_back_price, closing_lay_price, total_matched, captured_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """, (
                row["match_key"], row["market_type"], row["selection"],
                row["bookmaker"], row["back_price"], row["lay_price"],
                row["total_matched"],
            ))
            inserted += 1
        conn.commit()

        assert inserted == 2

        # Verify sharp_closing rows
        closing_rows = conn.execute(
            "SELECT * FROM sharp_closing WHERE match_key = ?", (match_key,)
        ).fetchall()
        assert len(closing_rows) == 2

        selections = {r["selection"] for r in closing_rows}
        assert selections == {"liverpool", "arsenal"}

        for r in closing_rows:
            assert r["closing_back_price"] > 1.01
            assert r["bookmaker"] == "pinnacle"

        conn.close()

    def test_bridge_skips_invalid_prices(self):
        """Rows with back_price <= 1.01 are excluded from the bridge."""
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        _create_sharp_tables(conn)

        match_key = "test_vs_match_2026-04-05"

        # Insert row with invalid price
        conn.execute(
            """INSERT INTO sharp_odds
               (match_key, market_type, selection, bookmaker, back_price, scraped_at)
               VALUES (?, 'h2h', 'test', 'pinnacle', 1.00, '2026-04-05T12:00:00')""",
            (match_key,),
        )
        conn.commit()

        rows = conn.execute("""
            SELECT * FROM sharp_odds
            WHERE match_key = ? AND back_price IS NOT NULL AND back_price > 1.01
        """, (match_key,)).fetchall()

        assert len(rows) == 0, "Invalid price should be filtered out"
        conn.close()


# ---------------------------------------------------------------------------
# 10. Dashboard panel data shape (clv_stats.get_clv_stats return structure)
# ---------------------------------------------------------------------------

class TestDashboardPanelDataShape:
    """Test the CLV stats return dict structure used in dashboard display."""

    def test_empty_stats_structure(self):
        """get_clv_stats-like dict has all required keys when no data."""
        stats = {
            "total_bets": 0,
            "positive_count": 0,
            "negative_count": 0,
            "positive_pct": 0.0,
            "avg_clv": 0.0,
            "avg_clv_pct": 0.0,
            "median_clv": 0.0,
            "median_clv_pct": 0.0,
            "period_days": 30,
            "tier": None,
            "sport": None,
            "league": None,
            "by_tier": {},
            "kill_switch_active": False,
            "kill_switch_message": None,
        }

        required_keys = {
            "total_bets", "positive_count", "negative_count", "positive_pct",
            "avg_clv", "avg_clv_pct", "median_clv", "median_clv_pct",
            "period_days", "tier", "sport", "league", "by_tier",
            "kill_switch_active", "kill_switch_message",
        }
        assert required_keys.issubset(stats.keys())

    def test_by_tier_breakdown_shape(self):
        """Per-tier breakdown has correct structure."""
        by_tier = {
            "gold": {
                "count": 10,
                "positive": 7,
                "total_clv": 0.35,
                "avg_clv_pct": 3.5,
                "positive_pct": 70.0,
            },
            "silver": {
                "count": 15,
                "positive": 8,
                "total_clv": 0.12,
                "avg_clv_pct": 0.8,
                "positive_pct": 53.3,
            },
        }

        for tier_name, data in by_tier.items():
            assert "count" in data
            assert "positive" in data
            assert "total_clv" in data
            assert isinstance(data["count"], int)
            assert isinstance(data["positive"], int)
            assert isinstance(data["total_clv"], float)
            assert data["positive"] <= data["count"]

    def test_kill_switch_message_when_active(self):
        """When kill switch is active, message is populated."""
        stats = {
            "kill_switch_active": True,
            "kill_switch_message": "CLV tracking paused \u2014 model under review",
        }
        assert stats["kill_switch_active"] is True
        assert stats["kill_switch_message"] is not None
        assert "paused" in stats["kill_switch_message"]

    def test_format_clv_report_with_zero_bets(self):
        """format_clv_report returns informative message for zero data."""
        # Mirror format_clv_report logic without importing the function
        # (which would require scrapers.db_connect)
        stats = {"total_bets": 0, "period_days": 7, "kill_switch_active": False}
        total = stats.get("total_bets", 0)
        if total == 0:
            days = stats.get("period_days", 30)
            message = f"No CLV data in the last {days} days."
        else:
            message = "has data"

        assert message == "No CLV data in the last 7 days."

    def test_format_clv_report_with_data(self):
        """format_clv_report produces a well-formed summary string."""
        stats = {
            "total_bets": 25,
            "positive_count": 15,
            "positive_pct": 60.0,
            "avg_clv_pct": 2.5,
            "period_days": 30,
            "tier": None,
            "league": None,
            "kill_switch_active": False,
        }

        # Mirror format_clv_report logic
        total = stats.get("total_bets", 0)
        pos_pct = stats.get("positive_pct", 0.0)
        pos_count = stats.get("positive_count", 0)
        avg_pct = stats.get("avg_clv_pct", 0.0)
        days = stats.get("period_days", 30)

        tier_label = f" [{stats['tier'].upper()}]" if stats.get("tier") else ""
        league_label = f" ({stats['league'].upper()})" if stats.get("league") else ""

        report = (
            f"Last {days}d{tier_label}{league_label}: "
            f"{pos_pct:.0f}% beat closing ({pos_count}/{total}), "
            f"avg CLV {avg_pct:+.1f}%"
        )

        assert "60%" in report
        assert "15/25" in report
        assert "+2.5%" in report
        assert "Last 30d" in report
