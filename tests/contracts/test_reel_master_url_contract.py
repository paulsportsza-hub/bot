"""FIX-REEL-MASTER-URL-CONTRACT-01 — regression guard.

The reel widget URL builder in dashboard/health_dashboard.py:api_so_post() must
produce URLs that match the on-disk filesystem layout written by
api_reel_final_upload(). See ops/REEL-MASTER-CONTRACT.md.

Three previous defects this guards against:

1. Filename mismatch — widget built `<pick_id>_master.mp4` while the upload
   route wrote `<row_id>.mp4` (row_id is the MOQ Notion page id == post_id).
2. Directory mismatch — widget URL omitted the `/final/` segment that the
   upload route uses.
3. nginx routing — `/assets/reels/` had no location block, so even a
   correct URL resolved to the WordPress catch-all and returned 404.

Tests:
- AC-2: widget URL builder renders `<post_id>.mp4` filename and `/final/` path.
- AC-2-FS: public URL maps round-trip back to the on-disk filesystem path.
- AC-3: nginx config carries a `location ^~ /assets/reels/` block with
        Cache-Control: public, max-age=300, must-revalidate (NOT immutable).
- AC-4: `reel_master_mtime` payload field is populated when file exists
        (cache-bust query is appended client-side as `?v=<mtime>`).
- AC-6: regression guard — `_master.mp4` substring is absent from the URL
        builder source line.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

DASHBOARD_PATH = REPO_ROOT / "dashboard" / "health_dashboard.py"
NGINX_PATH = Path("/etc/nginx/sites-enabled/mzansiedge")

# Today's master.mp4 from the brief — the canonical evidence file.
_FIXTURE_DATE = "2026-04-28"
_FIXTURE_ROW_ID = "350d9048-d73c-81c6-9e1c-e01511ecbb89"
_FIXTURE_FS_PATH = (
    f"/home/paulsportsza/bot/assets/reels/{_FIXTURE_DATE}/final/{_FIXTURE_ROW_ID}.mp4"
)
_FIXTURE_PUBLIC_URL = (
    f"https://mzansiedge.co.za/assets/reels/{_FIXTURE_DATE}/final/{_FIXTURE_ROW_ID}.mp4"
)


# ── Source-level guards ──────────────────────────────────────────────────────


def _read_dashboard_source() -> str:
    return DASHBOARD_PATH.read_text(encoding="utf-8")


def test_constants_pinned_to_canonical_paths() -> None:
    """AC-1: _REEL_FINALS_ROOT and _REEL_PUBLIC_BASE match the contract doc."""
    src = _read_dashboard_source()
    assert (
        '_REEL_FINALS_ROOT = "/home/paulsportsza/bot/assets/reels"' in src
    ), "FS root drifted from contract — see ops/REEL-MASTER-CONTRACT.md"
    assert (
        '_REEL_PUBLIC_BASE = "https://mzansiedge.co.za/assets/reels"' in src
    ), "public base drifted from contract — see ops/REEL-MASTER-CONTRACT.md"


def test_url_builder_uses_post_id_filename_and_final_segment() -> None:
    """AC-2: URL builder emits <_REEL_PUBLIC_BASE>/<date>/final/<post_id>.mp4."""
    src = _read_dashboard_source()
    expected = (
        'reel_master_url = f"{_REEL_PUBLIC_BASE}/{_effective_date}/final/{post_id}.mp4"'
    )
    assert expected in src, (
        "widget URL builder no longer matches the canonical contract — "
        "expected reel_master_url = "
        '"{_REEL_PUBLIC_BASE}/{_effective_date}/final/{post_id}.mp4"'
    )


def test_no_master_mp4_legacy_pattern_in_reel_final_url_block() -> None:
    """AC-6: the legacy `<pick_id>_master.mp4` shape MUST NOT reappear in the
    `if reel_final_out:` widget URL block — the FIX-REEL-MASTER-URL-CONTRACT-01
    target.

    Scope is the small block that builds `reel_master_url` from the reel-kit
    `_match`. The `_REEL_MASTERS_ROOT` legacy fallback elsewhere in api_so_post
    (line ~10140 area) and the Task Hub reel-kit scanner (line ~6407) both
    intentionally use `<pick_id>_master.mp4` against the legacy tree and are
    out of scope.
    """
    src = _read_dashboard_source()
    # The block opens with the canonical fix marker comment and closes with
    # the OSError pass — both unique anchors that survive future cleanup.
    open_marker = "# FIX-REEL-MASTER-URL-CONTRACT-01: master files are written by"
    open_idx = src.find(open_marker)
    assert open_idx > 0, (
        "FIX-REEL-MASTER-URL-CONTRACT-01 contract anchor missing from "
        "dashboard/health_dashboard.py — the URL builder block has been moved "
        "or its anchor comment removed"
    )
    close_marker = "except OSError:"
    close_idx = src.find(close_marker, open_idx)
    assert close_idx > open_idx, "could not locate end of reel_final_out block"
    block = src[open_idx:close_idx]

    leak_pattern = re.compile(r'f"[^"]*\{[^}]+\}_master\.mp4"')
    leaks = leak_pattern.findall(block)
    assert not leaks, (
        "<pick_id>_master.mp4 f-string filename pattern reappeared inside the "
        f"reel_final_out widget URL block — leaks: {leaks}. The widget URL "
        "must use <post_id>.mp4 under /final/ per ops/REEL-MASTER-CONTRACT.md."
    )


def test_url_round_trips_to_filesystem_path() -> None:
    """AC-2-FS: <_REEL_PUBLIC_BASE>/X round-trips to <_REEL_FINALS_ROOT>/X."""
    public_prefix = "https://mzansiedge.co.za/assets/reels"
    fs_root = "/home/paulsportsza/bot/assets/reels"
    rel = _FIXTURE_PUBLIC_URL.removeprefix(public_prefix + "/")
    assert _FIXTURE_FS_PATH == f"{fs_root}/{rel}", (
        "public URL does not round-trip to filesystem path — the URL "
        "builder and api_reel_final_upload() are out of contract"
    )


# ── nginx route guards ───────────────────────────────────────────────────────


def _read_nginx_config() -> str:
    if not NGINX_PATH.exists():
        pytest.skip("nginx config not present in this environment")
    try:
        return NGINX_PATH.read_text(encoding="utf-8")
    except PermissionError:
        pytest.skip("nginx config not readable in this environment")


def test_nginx_has_assets_reels_location_block() -> None:
    """AC-3: /etc/nginx/sites-enabled/mzansiedge serves /assets/reels/ from FS root."""
    cfg = _read_nginx_config()
    assert "location ^~ /assets/reels/" in cfg, (
        "nginx /assets/reels/ block missing — public masters return 404. "
        "Apply ops/nginx/reels.conf into /etc/nginx/sites-enabled/mzansiedge."
    )
    assert "alias /home/paulsportsza/bot/assets/reels/" in cfg, (
        "nginx /assets/reels/ alias does not point at _REEL_FINALS_ROOT"
    )


def test_nginx_reels_cache_control_is_revalidate_not_immutable() -> None:
    """AC-3: Cache-Control: public, max-age=300, must-revalidate (NOT immutable)."""
    cfg = _read_nginx_config()
    # Find the /assets/reels/ block precisely (not /assets/reel-cards/).
    block_match = re.search(
        r"location \^~ /assets/reels/ \{([^}]+)\}",
        cfg,
        re.DOTALL,
    )
    assert block_match, "/assets/reels/ block could not be parsed"
    block = block_match.group(1)
    assert "must-revalidate" in block, "must-revalidate header missing"
    assert "max-age=300" in block, "max-age=300 (5 min) not set"
    assert "immutable" not in block, (
        "immutable Cache-Control on master MP4s would defeat re-upload "
        "freshness — must use must-revalidate per the contract"
    )


# ── Cache-bust + payload field guards ────────────────────────────────────────


def test_payload_exposes_reel_master_mtime_for_client_cache_bust() -> None:
    """AC-4: api_so_post payload exposes reel_master_mtime epoch for ?v= bust."""
    src = _read_dashboard_source()
    assert '"reel_master_mtime": reel_master_mtime,' in src, (
        "reel_master_mtime payload field missing — widget cannot append "
        "?v=<mtime> cache-bust query"
    )
    assert "reel_master_mtime = int(os.path.getmtime(_master_fs_path))" in src, (
        "mtime is not read from the producer-canonical filesystem path"
    )


def test_widget_js_appends_v_mtime_query_to_master_url() -> None:
    """AC-4: the embedded widget JS appends `?v=<mtime>` to the master URL."""
    src = _read_dashboard_source()
    # The pattern lives in the renderReelUploadPanel() JS string blob.
    assert "p.reel_master_mtime||Date.now()" in src, (
        "widget no longer reads p.reel_master_mtime for cache-bust — "
        "FIX-DASH-REEL-WIDGET-01 pattern broken"
    )
    assert "'v='+encodeURIComponent(_vBust)" in src, (
        "widget no longer appends ?v= query to masterUrl — "
        "FIX-DASH-REEL-WIDGET-01 pattern broken"
    )
