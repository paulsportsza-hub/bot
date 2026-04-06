"""IMG-W1.5 — Contract tests: logo_cache.py

15 acceptance criteria (AC-1 through AC-15):

AC-1:  get_logo() returns None for an unknown team
AC-2:  get_logo() returns a valid Path for a cached team
AC-3:  get_logo() never makes HTTP calls (cache-only)
AC-4:  Cached logo files are 96×96 PNG
AC-5:  RGBA mode is preserved (transparent backgrounds)
AC-6:  Fuzzy match ≥0.8 similarity returns the canonical name
AC-7:  Fuzzy match <0.8 similarity returns None
AC-8:  prefetch_logo() writes logo to disk and updates DB on API success
AC-9:  prefetch_logo() returns None and records status='failed' on API failure
AC-10: logo_cache.db has correct schema (required columns)
AC-11: Logo stored at bot/card_assets/logos/team/{sport}/{team_key}.png
AC-12: Soccer dispatches to api_football source
AC-13: Cricket dispatches to sportmonks source
AC-14: Rugby dispatches to api_sports_rugby source
AC-15: MMA / boxing / combat dispatches to api_sports_mma source
"""
from __future__ import annotations

import io
import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

# ── Path setup ────────────────────────────────────────────────────────────────

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_png_bytes(width: int = 200, height: int = 200, rgba: bool = True) -> bytes:
    """Create a minimal PNG image as bytes."""
    mode = "RGBA" if rgba else "RGB"
    img = Image.new(mode, (width, height), (255, 0, 0, 128) if rgba else (255, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_transparent_png_bytes() -> bytes:
    """Create a PNG with a transparent background."""
    img = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
    # Add an opaque circle in the centre to simulate a logo
    from PIL import ImageDraw
    draw = ImageDraw.Draw(img)
    draw.ellipse([50, 50, 150, 150], fill=(255, 165, 0, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class LogoCacheFixture:
    """Context manager that isolates logo_cache to temp dirs/DB."""

    def __enter__(self):
        self._td = tempfile.TemporaryDirectory()
        td = Path(self._td.name)
        self._db = str(td / "test_logo_cache.db")
        self._logo_dir = td / "logos"
        self._logo_dir.mkdir()

        # Patch env vars before importing logo_cache
        self._env_patch = patch.dict(os.environ, {
            "LOGO_CACHE_DB": self._db,
            "LOGO_CACHE_DIR": str(self._logo_dir),
        })
        self._env_patch.start()

        # Import (or reload) logo_cache with patched env
        import importlib
        import logo_cache as _lc
        importlib.reload(_lc)
        self.lc = _lc
        return self

    def __exit__(self, *args):
        self._env_patch.stop()
        self._td.cleanup()


# ── AC-10: DB schema ──────────────────────────────────────────────────────────

class TestDBSchema:
    """AC-10: logo_cache table has correct columns."""

    def test_required_columns_exist(self):
        with LogoCacheFixture() as fix:
            lc = fix.lc
            conn = sqlite3.connect(lc._LOGO_DB)
            cursor = conn.execute("PRAGMA table_info(logo_cache)")
            cols = {row[1] for row in cursor.fetchall()}
            conn.close()
            required = {
                "team_key", "team_name", "sport", "league",
                "file_path", "api_source", "fetched_at", "status",
            }
            assert required.issubset(cols), f"Missing columns: {required - cols}"

    def test_team_key_is_primary_key(self):
        with LogoCacheFixture() as fix:
            lc = fix.lc
            conn = sqlite3.connect(lc._LOGO_DB)
            cursor = conn.execute("PRAGMA table_info(logo_cache)")
            pk_cols = [row[1] for row in cursor.fetchall() if row[5] == 1]
            conn.close()
            assert "team_key" in pk_cols


# ── AC-6 & AC-7: Fuzzy matching ───────────────────────────────────────────────

class TestFuzzyMatch:
    """AC-6/7: _fuzzy_match_team respects the 0.8 threshold."""

    def setup_method(self):
        import logo_cache
        self.fn = logo_cache._fuzzy_match_team

    def test_exact_match_returns_canonical(self):
        names = ["Arsenal", "Chelsea", "Liverpool"]
        result = self.fn("Arsenal", names)
        assert result == "Arsenal"

    def test_close_match_above_threshold(self):
        names = ["Manchester City", "Manchester United", "Chelsea"]
        # "Manchestar City" is ~0.94 similar
        result = self.fn("Manchestar City", names)
        assert result == "Manchester City"

    def test_returns_none_below_threshold(self):
        names = ["Arsenal", "Chelsea", "Liverpool"]
        # "Barcelona" has low similarity to all names
        result = self.fn("Barcelona", names)
        assert result is None

    def test_case_insensitive(self):
        names = ["Kaizer Chiefs", "Orlando Pirates"]
        result = self.fn("kaizer chiefs", names)
        assert result == "Kaizer Chiefs"

    def test_empty_known_list_returns_none(self):
        result = self.fn("Arsenal", [])
        assert result is None

    def test_preserves_original_casing(self):
        names = ["Mamelodi Sundowns"]
        result = self.fn("Mamelodi Sundown", names)  # missing 's'
        assert result == "Mamelodi Sundowns"


# ── AC-1: Unknown team ────────────────────────────────────────────────────────

class TestGetLogoUnknown:
    """AC-1: get_logo() returns None for uncached teams."""

    def test_returns_none_for_unknown_team(self):
        with LogoCacheFixture() as fix:
            result = fix.lc.get_logo("Unknown FC", "soccer", "mystery_league")
            assert result is None

    def test_returns_none_when_status_is_failed(self):
        with LogoCacheFixture() as fix:
            lc = fix.lc
            from db_connection import get_connection
            conn = get_connection(db_path=lc._LOGO_DB)
            with conn:
                conn.execute(
                    "INSERT INTO logo_cache (team_key,team_name,sport,league,"
                    "file_path,api_source,fetched_at,status) VALUES (?,?,?,?,?,?,?,'failed')",
                    ("soccer_failed_fc", "Failed FC", "soccer", "", None, "api_football", "2026-04-06T00:00:00"),
                )
            conn.close()
            assert lc.get_logo("Failed FC", "soccer") is None


# ── AC-2 & AC-3: Cache hit ────────────────────────────────────────────────────

class TestGetLogoCacheHit:
    """AC-2 & AC-3: get_logo() returns Path from cache without HTTP."""

    def test_returns_path_when_cached(self):
        with LogoCacheFixture() as fix:
            lc = fix.lc
            # Manually write a PNG to the logo dir and a DB row
            sport_dir = lc._LOGO_DIR / "soccer"
            sport_dir.mkdir(parents=True, exist_ok=True)
            png_path = sport_dir / "soccer_arsenal.png"
            png_path.write_bytes(_make_png_bytes())

            from db_connection import get_connection
            conn = get_connection(db_path=lc._LOGO_DB)
            with conn:
                conn.execute(
                    "INSERT INTO logo_cache (team_key,team_name,sport,league,"
                    "file_path,api_source,fetched_at,status) VALUES (?,?,?,?,?,?,?,'ok')",
                    ("soccer_arsenal", "Arsenal", "soccer", "epl", str(png_path),
                     "api_football", "2026-04-06T00:00:00"),
                )
            conn.close()

            result = lc.get_logo("Arsenal", "soccer", "epl")
            assert result is not None
            assert result == png_path

    def test_no_http_calls_on_miss(self):
        """AC-3: get_logo() must not call urllib.request or any HTTP lib."""
        with LogoCacheFixture() as fix:
            with patch("urllib.request.urlopen") as mock_open:
                fix.lc.get_logo("Completely Unknown Team", "soccer")
                mock_open.assert_not_called()

    def test_no_http_calls_on_hit(self):
        """AC-3: get_logo() must not call urllib.request even on cache hit."""
        with LogoCacheFixture() as fix:
            lc = fix.lc
            sport_dir = lc._LOGO_DIR / "soccer"
            sport_dir.mkdir(parents=True, exist_ok=True)
            png_path = sport_dir / "soccer_chelsea.png"
            png_path.write_bytes(_make_png_bytes())

            from db_connection import get_connection
            conn = get_connection(db_path=lc._LOGO_DB)
            with conn:
                conn.execute(
                    "INSERT INTO logo_cache (team_key,team_name,sport,league,"
                    "file_path,api_source,fetched_at,status) VALUES (?,?,?,?,?,?,?,'ok')",
                    ("soccer_chelsea", "Chelsea", "soccer", "epl", str(png_path),
                     "api_football", "2026-04-06T00:00:00"),
                )
            conn.close()

            with patch("urllib.request.urlopen") as mock_open:
                lc.get_logo("Chelsea", "soccer", "epl")
                mock_open.assert_not_called()


# ── AC-4 & AC-5: Image format ─────────────────────────────────────────────────

class TestImageProcessing:
    """AC-4 & AC-5: _process_image produces 96×96 RGBA PNG."""

    def setup_method(self):
        import logo_cache
        self.fn = logo_cache._process_image

    def test_output_is_96x96(self):
        raw = _make_png_bytes(300, 200)
        result = self.fn(raw)
        assert result is not None
        img = Image.open(io.BytesIO(result))
        assert img.size == (96, 96)

    def test_output_mode_is_rgba(self):
        raw = _make_png_bytes(200, 200, rgba=False)
        result = self.fn(raw)
        assert result is not None
        img = Image.open(io.BytesIO(result))
        assert img.mode == "RGBA"

    def test_output_is_valid_png(self):
        raw = _make_png_bytes()
        result = self.fn(raw)
        assert result is not None
        assert result[:4] == b"\x89PNG"

    def test_transparent_background_preserved(self):
        """AC-5: Alpha channel is preserved (not flattened to white)."""
        raw = _make_transparent_png_bytes()
        result = self.fn(raw)
        assert result is not None
        img = Image.open(io.BytesIO(result))
        assert img.mode == "RGBA"
        # Top-left corner of our test image is fully transparent
        assert img.getpixel((0, 0))[3] == 0

    def test_returns_none_on_invalid_bytes(self):
        result = self.fn(b"not an image")
        assert result is None


# ── AC-8 & AC-11: prefetch success ───────────────────────────────────────────

class TestPrefetchLogoSuccess:
    """AC-8 & AC-11: prefetch_logo writes disk file and DB row on success."""

    def test_returns_path_on_success(self):
        with LogoCacheFixture() as fix:
            lc = fix.lc
            with patch.object(lc, "_fetch_raw_logo",
                              return_value=(_make_png_bytes(), "api_football")):
                result = lc.prefetch_logo("Arsenal", "soccer", "epl")
            assert result is not None
            assert result.exists()
            assert result.suffix == ".png"

    def test_logo_stored_in_sport_subdir(self):
        """AC-11: file is at <logo_dir>/soccer/<team_key>.png."""
        with LogoCacheFixture() as fix:
            lc = fix.lc
            with patch.object(lc, "_fetch_raw_logo",
                              return_value=(_make_png_bytes(), "api_football")):
                result = lc.prefetch_logo("Arsenal", "soccer", "epl")
            assert result is not None
            assert result.parent.name == "soccer"
            assert result.name.startswith("soccer_arsenal")

    def test_db_row_status_ok(self):
        """AC-8: DB row has status='ok' after successful prefetch."""
        with LogoCacheFixture() as fix:
            lc = fix.lc
            with patch.object(lc, "_fetch_raw_logo",
                              return_value=(_make_png_bytes(), "api_football")):
                lc.prefetch_logo("Arsenal", "soccer", "epl")

            from db_connection import get_connection
            conn = get_connection(db_path=lc._LOGO_DB)
            row = conn.execute(
                "SELECT status FROM logo_cache WHERE team_key = 'soccer_arsenal'"
            ).fetchone()
            conn.close()
            assert row is not None
            assert row["status"] == "ok"

    def test_skips_if_already_cached(self):
        """prefetch_logo returns existing path without re-fetching."""
        with LogoCacheFixture() as fix:
            lc = fix.lc
            call_count = [0]

            def _fake_fetch(*a, **kw):
                call_count[0] += 1
                return _make_png_bytes(), "api_football"

            with patch.object(lc, "_fetch_raw_logo", side_effect=_fake_fetch):
                lc.prefetch_logo("Arsenal", "soccer", "epl")
                lc.prefetch_logo("Arsenal", "soccer", "epl")

            assert call_count[0] == 1, "Should only call API once"


# ── AC-9: prefetch failure ────────────────────────────────────────────────────

class TestPrefetchLogoFailure:
    """AC-9: prefetch_logo returns None and records status='failed'."""

    def test_returns_none_on_api_failure(self):
        with LogoCacheFixture() as fix:
            lc = fix.lc
            with patch.object(lc, "_fetch_raw_logo", return_value=(None, "api_football")):
                result = lc.prefetch_logo("Ghost FC", "soccer", "mystery")
            assert result is None

    def test_records_failed_status(self):
        with LogoCacheFixture() as fix:
            lc = fix.lc
            with patch.object(lc, "_fetch_raw_logo", return_value=(None, "api_football")):
                lc.prefetch_logo("Ghost FC", "soccer", "mystery")

            from db_connection import get_connection
            conn = get_connection(db_path=lc._LOGO_DB)
            row = conn.execute(
                "SELECT status FROM logo_cache WHERE team_name = 'Ghost FC'"
            ).fetchone()
            conn.close()
            assert row is not None
            assert row["status"] == "failed"


# ── AC-12 to AC-15: Sport dispatch ────────────────────────────────────────────

class TestAPISourceDispatch:
    """AC-12/13/14/15: _fetch_raw_logo dispatches to the correct source."""

    def _run_dispatch(self, sport: str) -> str:
        """Return the api_source label returned by _fetch_raw_logo."""
        import logo_cache
        # Stub the per-sport fetcher to avoid real HTTP
        with patch.object(logo_cache, "_fetch_soccer_logo", return_value=None), \
             patch.object(logo_cache, "_fetch_rugby_logo", return_value=None), \
             patch.object(logo_cache, "_fetch_cricket_logo", return_value=None), \
             patch.object(logo_cache, "_fetch_mma_logo", return_value=None):
            _, source = logo_cache._fetch_raw_logo("Test Team", sport)
        return source

    def test_soccer_uses_api_football(self):
        """AC-12."""
        assert self._run_dispatch("soccer") == "api_football"

    def test_football_alias_uses_api_football(self):
        assert self._run_dispatch("football") == "api_football"

    def test_rugby_uses_api_sports_rugby(self):
        """AC-14."""
        assert self._run_dispatch("rugby") == "api_sports_rugby"

    def test_cricket_uses_sportmonks(self):
        """AC-13."""
        assert self._run_dispatch("cricket") == "sportmonks"

    def test_mma_uses_api_sports_mma(self):
        """AC-15."""
        assert self._run_dispatch("mma") == "api_sports_mma"

    def test_boxing_uses_api_sports_mma(self):
        """AC-15: boxing is an alias for mma."""
        assert self._run_dispatch("boxing") == "api_sports_mma"

    def test_combat_uses_api_sports_mma(self):
        """AC-15: combat is an alias for mma."""
        assert self._run_dispatch("combat") == "api_sports_mma"
