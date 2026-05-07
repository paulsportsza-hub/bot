"""FIX-LOGO-CACHE-RELATIVE-PATHS-01 — Contract tests.

AC-5: logo_cache writer must not emit dev-tree absolute paths.
       Paths written to DB must point to bot-data-shared, not bot/.
"""
from __future__ import annotations

import io
import importlib
import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

_DEV_BOT_PATH = "/home/paulsportsza/bot/card_assets"
_SHARED_PATH = "/home/paulsportsza/bot-data-shared/card_assets"


def _make_png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", (1, 1), (255, 0, 0, 255)).save(buf, "PNG")
    return buf.getvalue()


# ── AC-5a: _LOGO_DIR default must not point into dev tree ────────────────────

def test_logo_dir_default_not_dev_tree():
    """_LOGO_DIR default must not resolve under /home/paulsportsza/bot/card_assets."""
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("LOGO_CACHE_DIR", None)
        import logo_cache as lc
        importlib.reload(lc)
        assert not str(lc._LOGO_DIR).startswith(_DEV_BOT_PATH), (
            f"_LOGO_DIR={lc._LOGO_DIR} still points into mutable dev tree. "
            "Must use bot-data-shared."
        )


def test_logo_dir_default_uses_shared_volume():
    """_LOGO_DIR default must be under bot-data-shared."""
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("LOGO_CACHE_DIR", None)
        import logo_cache as lc
        importlib.reload(lc)
        assert str(lc._LOGO_DIR).startswith(_SHARED_PATH), (
            f"_LOGO_DIR={lc._LOGO_DIR} — expected prefix {_SHARED_PATH!r}"
        )


# ── AC-5b: prefetch_logo writes shared-volume path to DB ────────────────────

def test_prefetch_writes_shared_path():
    """prefetch_logo must write a path under bot-data-shared, not bot/."""
    with tempfile.TemporaryDirectory() as td:
        shared_dir = Path(td) / "bot-data-shared" / "card_assets" / "logos" / "team"
        shared_dir.mkdir(parents=True)
        db_path = str(Path(td) / "logo_cache.db")

        with patch.dict(os.environ, {
            "LOGO_CACHE_DIR": str(shared_dir),
            "LOGO_CACHE_DB": db_path,
        }):
            import logo_cache as lc
            importlib.reload(lc)
            with patch.object(lc, "_fetch_raw_logo", return_value=(_make_png_bytes(), "test")):
                result = lc.prefetch_logo("TestTeam", "soccer")

        assert result is not None, "prefetch_logo should succeed with mocked fetch"

        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT file_path FROM logo_cache WHERE team_key='soccer_testteam'"
        ).fetchone()
        conn.close()

        assert row is not None
        assert _DEV_BOT_PATH not in row[0], (
            f"file_path={row[0]!r} contains dev tree prefix — isolation breach"
        )


# ── AC-3 (read guard): get_logo remaps stale dev-tree paths at read time ────

def test_get_logo_remaps_stale_dev_tree_path(tmp_path):
    """get_logo must remap a stale /bot/card_assets/ DB row to shared volume."""
    shared_dir = tmp_path / "bot-data-shared" / "card_assets" / "logos" / "team" / "soccer"
    shared_dir.mkdir(parents=True)
    fake_logo = shared_dir / "soccer_stale.png"
    buf = io.BytesIO()
    import PIL.Image
    PIL.Image.new("RGBA", (96, 96), (0, 0, 0, 255)).save(buf, "PNG")
    fake_logo.write_bytes(buf.getvalue())

    db_path = str(tmp_path / "logo_cache.db")
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE logo_cache (
            team_key TEXT PRIMARY KEY, team_name TEXT NOT NULL,
            sport TEXT NOT NULL, league TEXT NOT NULL DEFAULT '',
            file_path TEXT, api_source TEXT,
            fetched_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending'
        )
    """)
    stale_path = "/home/paulsportsza/bot/card_assets/logos/team/soccer/soccer_stale.png"
    conn.execute(
        "INSERT INTO logo_cache VALUES (?,?,?,?,?,?,?,?)",
        ("soccer_stale", "Stale", "soccer", "", stale_path, "test",
         "2026-01-01T00:00:00+00:00", "ok"),
    )
    conn.commit()
    conn.close()

    with patch.dict(os.environ, {
        "LOGO_CACHE_DB": db_path,
        "LOGO_CACHE_DIR": str(tmp_path / "bot-data-shared" / "card_assets" / "logos" / "team"),
    }):
        import logo_cache as lc
        importlib.reload(lc)
        # Patch _SHARED_ASSETS to point to tmp_path equivalent
        monkeydir = tmp_path / "bot-data-shared" / "card_assets"
        with patch.object(lc, "_SHARED_ASSETS", monkeydir):
            result = lc.get_logo("stale", "soccer")

    assert result is not None, "get_logo should remap stale path and return valid Path"
    assert str(result) != stale_path, "Should not return the old dev-tree path"


# ── AC-2 (migration): existing dev-tree rows are rewritten ──────────────────

def test_migration_rewrites_dev_tree_rows():
    """Migration must rewrite /bot/card_assets/ rows to shared-volume paths."""
    with tempfile.TemporaryDirectory() as td:
        db_path = str(Path(td) / "logo_cache.db")
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE logo_cache (
                team_key  TEXT PRIMARY KEY, team_name TEXT NOT NULL,
                sport     TEXT NOT NULL, league TEXT NOT NULL DEFAULT '',
                file_path TEXT, api_source TEXT,
                fetched_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending'
            )
        """)
        conn.execute(
            "INSERT INTO logo_cache VALUES (?,?,?,?,?,?,?,?)",
            ("soccer_test", "Test", "soccer", "",
             "/home/paulsportsza/bot/card_assets/logos/team/soccer/soccer_test.png",
             "test", "2026-01-01T00:00:00+00:00", "ok"),
        )
        conn.commit()
        conn.close()

        _run_migration_module(db_path)

        conn2 = sqlite3.connect(db_path)
        row = conn2.execute(
            "SELECT file_path FROM logo_cache WHERE team_key='soccer_test'"
        ).fetchone()
        conn2.close()

        assert _DEV_BOT_PATH not in row[0], f"Old dev-tree path not rewritten: {row[0]}"
        assert row[0].startswith("/home/paulsportsza/bot-data-shared/card_assets"), (
            f"New prefix missing: {row[0]}"
        )


def test_migration_idempotent():
    """Running migration twice must not corrupt paths."""
    with tempfile.TemporaryDirectory() as td:
        db_path = str(Path(td) / "logo_cache.db")
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE logo_cache (
                team_key  TEXT PRIMARY KEY, team_name TEXT NOT NULL,
                sport     TEXT NOT NULL, league TEXT NOT NULL DEFAULT '',
                file_path TEXT, api_source TEXT,
                fetched_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending'
            )
        """)
        conn.execute(
            "INSERT INTO logo_cache VALUES (?,?,?,?,?,?,?,?)",
            ("soccer_test", "Test", "soccer", "",
             "/home/paulsportsza/bot/card_assets/logos/team/soccer/soccer_test.png",
             "test", "2026-01-01T00:00:00+00:00", "ok"),
        )
        conn.commit()
        conn.close()

        mod = _run_migration_module(db_path)
        mod.run_migration(db_path)  # second run

        conn2 = sqlite3.connect(db_path)
        row = conn2.execute(
            "SELECT file_path FROM logo_cache WHERE team_key='soccer_test'"
        ).fetchone()
        conn2.close()

        fp = row[0]
        assert fp.count("bot-data-shared") == 1, f"Path doubled after idempotent run: {fp}"
        assert _DEV_BOT_PATH not in fp


def test_migration_null_paths_untouched():
    """Migration must leave NULL file_path rows (status=failed) unchanged."""
    with tempfile.TemporaryDirectory() as td:
        db_path = str(Path(td) / "logo_cache.db")
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE logo_cache (
                team_key  TEXT PRIMARY KEY, team_name TEXT NOT NULL,
                sport     TEXT NOT NULL, league TEXT NOT NULL DEFAULT '',
                file_path TEXT, api_source TEXT,
                fetched_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending'
            )
        """)
        conn.execute(
            "INSERT INTO logo_cache VALUES (?,?,?,?,?,?,?,?)",
            ("soccer_failed", "Failed", "soccer", "",
             None, "test", "2026-01-01T00:00:00+00:00", "failed"),
        )
        conn.commit()
        conn.close()

        _run_migration_module(db_path)

        conn2 = sqlite3.connect(db_path)
        row = conn2.execute(
            "SELECT file_path FROM logo_cache WHERE team_key='soccer_failed'"
        ).fetchone()
        conn2.close()

        assert row[0] is None, f"NULL file_path should remain NULL, got: {row[0]}"


# ── Helper ───────────────────────────────────────────────────────────────────

def _run_migration_module(db_path: str):
    mig_file = os.path.join(
        os.path.dirname(__file__), "..", "..", "migrations",
        "0002_logo_cache_shared_paths.py",
    )
    import importlib.util
    spec = importlib.util.spec_from_file_location("mig0002", mig_file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.run_migration(db_path)
    return mod
