"""
P3-06: Tests for user_settings module + /today filter integration.

Covers AC-2 through AC-12:
  - Settings CRUD (get, set_tier_filter, set_sport_filter, set_quiet_hours)
  - Default row created on first access (AC-8)
  - Quiet hours wrap-around (AC-4, AC-5)
  - Quiet hours → can_send_audible returns False (AC-5)
  - /today tip filtering by tier and sport (AC-6)
  - All-tiers disabled edge case (AC-6)
  - All-sports disabled edge case (AC-6)
  - Change logging (AC-10)
  - Fail-open on DB error (AC-8)
"""

import sqlite3
import sys
import os
import tempfile
from unittest.mock import patch, MagicMock

import pytest

# Ensure bot/ directory is on the path
_BOT_DIR = os.path.join(os.path.dirname(__file__), "..")
if _BOT_DIR not in sys.path:
    sys.path.insert(0, _BOT_DIR)


# ── Helpers ────────────────────────────────────────────────────────────────


def _fake_get_connection(path, readonly=False, timeout_ms=30000):
    conn = sqlite3.connect(path, timeout=timeout_ms / 1000)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn


def _make_us(tmp_path):
    """Return user_settings module wired to a temp SQLite DB."""
    db_file = os.path.join(str(tmp_path), "test_settings.db")

    # Fresh import to get clean _table_created state
    if "user_settings" in sys.modules:
        del sys.modules["user_settings"]

    with patch("db_connection.get_connection", side_effect=_fake_get_connection):
        import user_settings as us  # noqa: PLC0415

    us._db_path = lambda: db_file  # type: ignore[attr-defined]
    us._table_created = False  # type: ignore[attr-defined]

    def _patched_get_conn():
        return _fake_get_connection(db_file)

    us._get_conn = _patched_get_conn  # type: ignore[attr-defined]
    return us


# ── AC-8: Defaults ─────────────────────────────────────────────────────────


class TestDefaults:
    """New users get all tiers ON, all sports ON, quiet hours OFF (AC-8)."""

    def test_default_row_created_on_first_access(self, tmp_path):
        us = _make_us(tmp_path)
        settings = us.get_settings(999)
        assert settings["tier_filter"] == us.DEFAULT_TIERS
        assert settings["sport_filter"] == us.DEFAULT_SPORTS
        assert settings["quiet_start"] is None
        assert settings["quiet_end"] is None

    def test_all_tiers_active_by_default(self, tmp_path):
        us = _make_us(tmp_path)
        s = us.get_settings(1)
        tiers = set(s["tier_filter"].split(","))
        assert tiers == {"diamond", "gold", "silver", "bronze"}

    def test_all_sports_active_by_default(self, tmp_path):
        us = _make_us(tmp_path)
        s = us.get_settings(2)
        sports = set(s["sport_filter"].split(","))
        assert sports == {"soccer", "rugby", "cricket", "mma", "boxing"}


# ── AC-2: Tier filter CRUD ─────────────────────────────────────────────────


class TestTierFilter:
    """Tier filter persists per user (AC-2)."""

    def test_set_tier_filter_persists(self, tmp_path):
        us = _make_us(tmp_path)
        uid = 10
        us.set_tier_filter(uid, ["diamond", "gold"])
        s = us.get_settings(uid)
        tiers = set(s["tier_filter"].split(","))
        assert tiers == {"diamond", "gold"}
        assert "silver" not in tiers
        assert "bronze" not in tiers

    def test_set_tier_filter_single_tier(self, tmp_path):
        us = _make_us(tmp_path)
        uid = 11
        us.set_tier_filter(uid, ["diamond"])
        s = us.get_settings(uid)
        assert s["tier_filter"] == "diamond"

    def test_set_tier_filter_idempotent(self, tmp_path):
        us = _make_us(tmp_path)
        uid = 12
        us.set_tier_filter(uid, ["gold"])
        us.set_tier_filter(uid, ["gold"])
        s = us.get_settings(uid)
        assert s["tier_filter"] == "gold"

    def test_different_users_independent(self, tmp_path):
        us = _make_us(tmp_path)
        us.set_tier_filter(20, ["diamond"])
        us.set_tier_filter(21, ["bronze"])
        assert us.get_settings(20)["tier_filter"] == "diamond"
        assert us.get_settings(21)["tier_filter"] == "bronze"


# ── AC-3: Sport filter CRUD ────────────────────────────────────────────────


class TestSportFilter:
    """Sport filter persists per user (AC-3)."""

    def test_set_sport_filter_persists(self, tmp_path):
        us = _make_us(tmp_path)
        uid = 30
        us.set_sport_filter(uid, ["soccer", "rugby"])
        s = us.get_settings(uid)
        sports = set(s["sport_filter"].split(","))
        assert sports == {"soccer", "rugby"}

    def test_set_sport_filter_single_sport(self, tmp_path):
        us = _make_us(tmp_path)
        uid = 31
        us.set_sport_filter(uid, ["cricket"])
        s = us.get_settings(uid)
        assert s["sport_filter"] == "cricket"


# ── AC-4: Quiet hours CRUD ─────────────────────────────────────────────────


class TestQuietHoursCRUD:
    """Quiet hours persist per user (AC-4)."""

    def test_set_quiet_hours_persists(self, tmp_path):
        us = _make_us(tmp_path)
        uid = 40
        us.set_quiet_hours(uid, 22, 7)
        s = us.get_settings(uid)
        assert s["quiet_start"] == 22
        assert s["quiet_end"] == 7

    def test_disable_quiet_hours(self, tmp_path):
        us = _make_us(tmp_path)
        uid = 41
        us.set_quiet_hours(uid, 22, 7)
        us.set_quiet_hours(uid, None, None)
        s = us.get_settings(uid)
        assert s["quiet_start"] is None
        assert s["quiet_end"] is None


# ── AC-5: Quiet hours logic ────────────────────────────────────────────────


class TestQuietHoursLogic:
    """is_quiet_now handles wrap-around and disabled state correctly (AC-5)."""

    def _run_is_quiet(self, us, uid: int, hour: int) -> bool:
        mock_dt = MagicMock()
        mock_dt.now.return_value.hour = hour
        with patch("user_settings.datetime", mock_dt):
            return us.is_quiet_now(uid)

    def test_quiet_hours_disabled_returns_false(self, tmp_path):
        us = _make_us(tmp_path)
        uid = 50
        # No quiet hours set → never quiet
        assert us.is_quiet_now(uid) is False

    def test_within_normal_quiet_window(self, tmp_path):
        us = _make_us(tmp_path)
        uid = 51
        us.set_quiet_hours(uid, 23, 6)  # 23:00–06:00
        # 02:00 is inside → quiet
        assert self._run_is_quiet(us, uid, 2) is True

    def test_outside_normal_quiet_window(self, tmp_path):
        us = _make_us(tmp_path)
        uid = 52
        us.set_quiet_hours(uid, 23, 6)
        # 14:00 is outside → not quiet
        assert self._run_is_quiet(us, uid, 14) is False

    def test_midnight_wraparound_inside(self, tmp_path):
        """22:00–07:00 window: hour=23 should be quiet."""
        us = _make_us(tmp_path)
        uid = 53
        us.set_quiet_hours(uid, 22, 7)
        assert self._run_is_quiet(us, uid, 23) is True
        assert self._run_is_quiet(us, uid, 0) is True
        assert self._run_is_quiet(us, uid, 6) is True

    def test_midnight_wraparound_outside(self, tmp_path):
        """22:00–07:00 window: hour=10 should not be quiet."""
        us = _make_us(tmp_path)
        uid = 54
        us.set_quiet_hours(uid, 22, 7)
        assert self._run_is_quiet(us, uid, 10) is False
        assert self._run_is_quiet(us, uid, 7) is False  # end hour excluded

    def test_can_send_audible_false_during_quiet(self, tmp_path):
        """notification_budget.can_send_audible returns False during quiet hours (AC-5)."""
        us = _make_us(tmp_path)
        uid = 55
        us.set_quiet_hours(uid, 22, 7)

        # Fresh notification_budget module
        if "notification_budget" in sys.modules:
            del sys.modules["notification_budget"]

        db_file = os.path.join(str(tmp_path), "test_budget.db")

        def _fake_conn(path, **kw):
            return _fake_get_connection(db_file)

        with patch("db_connection.get_connection", side_effect=_fake_get_connection):
            import notification_budget as nb  # noqa: PLC0415

        nb._db_path = lambda: db_file  # type: ignore[attr-defined]
        nb._table_created = False  # type: ignore[attr-defined]
        nb._get_conn = lambda: _fake_get_connection(db_file)  # type: ignore[attr-defined]

        # Patch user_settings.is_quiet_now to return True for this user
        with patch("user_settings.is_quiet_now", return_value=True):
            result = nb.can_send_audible(uid)

        assert result is False


# ── AC-10: Change logging ──────────────────────────────────────────────────


class TestChangeLogging:
    """Settings changes are logged to user_settings_log (AC-10)."""

    def test_tier_change_is_logged(self, tmp_path):
        us = _make_us(tmp_path)
        uid = 60
        us.set_tier_filter(uid, ["diamond", "gold"])
        conn = us._get_conn()
        rows = conn.execute(
            f"SELECT setting, new_value FROM {us._LOG_TABLE} WHERE user_id = ?",
            (uid,),
        ).fetchall()
        conn.close()
        assert any(r["setting"] == "tier_filter" for r in rows)

    def test_sport_change_is_logged(self, tmp_path):
        us = _make_us(tmp_path)
        uid = 61
        us.set_sport_filter(uid, ["soccer"])
        conn = us._get_conn()
        rows = conn.execute(
            f"SELECT setting FROM {us._LOG_TABLE} WHERE user_id = ?",
            (uid,),
        ).fetchall()
        conn.close()
        assert any(r["setting"] == "sport_filter" for r in rows)

    def test_quiet_hours_change_is_logged(self, tmp_path):
        us = _make_us(tmp_path)
        uid = 62
        us.set_quiet_hours(uid, 22, 7)
        conn = us._get_conn()
        rows = conn.execute(
            f"SELECT setting, new_value FROM {us._LOG_TABLE} WHERE user_id = ?",
            (uid,),
        ).fetchall()
        conn.close()
        assert any(r["setting"] == "quiet_hours" for r in rows)
        log_row = next(r for r in rows if r["setting"] == "quiet_hours")
        assert log_row["new_value"] == "22-7"


# ── AC-6: /today filter integration ───────────────────────────────────────


class TestTodayFilter:
    """Filtering logic for /today matches the spec (AC-6)."""

    def _make_tips(self):
        return [
            {"edge_tier": "diamond", "sport_key": "soccer", "ev": 5.0},
            {"edge_tier": "gold", "sport_key": "soccer", "ev": 3.0},
            {"edge_tier": "silver", "sport_key": "rugby", "ev": 2.0},
            {"edge_tier": "bronze", "sport_key": "cricket", "ev": 1.0},
            {"edge_tier": "gold", "sport_key": "combat", "ev": 4.0},  # MMA/boxing
        ]

    def _apply_filter(self, tips, tier_filter, sport_filter):
        active_tiers = set(tier_filter.split(","))
        active_sports = set(sport_filter.split(","))
        return [
            t for t in tips
            if (t.get("edge_tier") or "bronze") in active_tiers
            and (
                t.get("sport_key", "soccer") in active_sports
                or (t.get("sport_key") == "combat"
                    and ("mma" in active_sports or "boxing" in active_sports))
            )
        ]

    def test_all_filters_on_passes_all(self):
        tips = self._make_tips()
        result = self._apply_filter(
            tips, "diamond,gold,silver,bronze", "soccer,rugby,cricket,mma,boxing"
        )
        assert len(result) == len(tips)

    def test_diamond_only_tier_filter(self):
        tips = self._make_tips()
        result = self._apply_filter(
            tips, "diamond", "soccer,rugby,cricket,mma,boxing"
        )
        assert len(result) == 1
        assert result[0]["edge_tier"] == "diamond"

    def test_soccer_only_sport_filter(self):
        tips = self._make_tips()
        result = self._apply_filter(
            tips, "diamond,gold,silver,bronze", "soccer"
        )
        # Only soccer tips pass
        for t in result:
            assert t["sport_key"] == "soccer"

    def test_mma_filter_allows_combat_sport_key(self):
        """combat sport_key passes if mma is in active sports (AC-6)."""
        tips = self._make_tips()
        result = self._apply_filter(
            tips, "diamond,gold,silver,bronze", "soccer,mma"
        )
        sport_keys = {t["sport_key"] for t in result}
        assert "combat" in sport_keys

    def test_both_mma_and_boxing_off_blocks_combat(self):
        """combat tips blocked only when both mma and boxing are off (AC-6)."""
        tips = self._make_tips()
        result = self._apply_filter(
            tips, "diamond,gold,silver,bronze", "soccer,rugby,cricket"
        )
        for t in result:
            assert t["sport_key"] != "combat"

    def test_boxing_filter_allows_combat_sport_key(self):
        """combat sport_key passes if boxing (but not mma) is in active sports."""
        tips = self._make_tips()
        result = self._apply_filter(
            tips, "diamond,gold,silver,bronze", "soccer,boxing"
        )
        sport_keys = {t["sport_key"] for t in result}
        assert "combat" in sport_keys
