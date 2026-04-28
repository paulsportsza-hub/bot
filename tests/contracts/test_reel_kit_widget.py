"""Contract tests — Reel Kit dashboard widget cache-bust + VO surfacing.

FIX-DASH-REEL-WIDGET-01 — locks in the three widget invariants:

1. Reel-card and VO URLs include a ``?v=<file_mtime_int>`` cache buster
   so a regenerated kit defeats every browser/CDN caching layer.

2. Cache-buster is monotonic — touch a file and the integer increases.

3. The widget JS (`renderReelUploadPanel`) renders a Voice-overs section
   when ``p.reel_vos`` is populated, and the server-side ``_reel_asset_url``
   helper degrades gracefully if a file is missing.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

# Make bot/ importable.
_HERE = Path(__file__).resolve()
_BOT_ROOT = _HERE.parent.parent.parent
sys.path.insert(0, str(_BOT_ROOT))

# Stub the scraper search path so importing health_dashboard works in CI even
# when the scrapers tree isn't on sys.path. The dashboard module is large
# but the helpers we need are pure.
from config import ensure_scrapers_importable  # noqa: E402

ensure_scrapers_importable()


@pytest.fixture
def reel_root(monkeypatch, tmp_path: Path) -> Path:
    """Point the dashboard at a temp reel-cards root so the suite is hermetic."""
    import dashboard.health_dashboard as hd

    monkeypatch.setattr(hd, "_REEL_CARDS_ROOT", str(tmp_path))
    return tmp_path


def _seed_kit(root: Path, date_str: str, pick_id: str) -> dict[str, Path]:
    """Drop a card + 3 VOs + meta into the temp reel root."""
    pick_dir = root / date_str / pick_id
    pick_dir.mkdir(parents=True, exist_ok=True)
    files = {
        "card": pick_dir / f"card_{pick_id}.png",
        "vo1":  pick_dir / f"vo_{pick_id}_v1.mp3",
        "vo2":  pick_dir / f"vo_{pick_id}_v2.mp3",
        "vo3":  pick_dir / f"vo_{pick_id}_v3.mp3",
    }
    for p in files.values():
        p.write_bytes(b"\x00" * 16)
    return files


# ── Test 1: card URL gets a ?v=<mtime> cache buster ─────────────────────────


def test_reel_asset_url_appends_mtime_cache_buster(reel_root: Path) -> None:
    """`_reel_asset_url` MUST append `?v=<int(mtime)>` for existing files."""
    from dashboard.health_dashboard import _reel_asset_url

    date_str = "2026-04-28"
    pick_id = "abc123def456"
    files = _seed_kit(reel_root, date_str, pick_id)

    url = _reel_asset_url(date_str, pick_id, f"card_{pick_id}.png")
    expected_mtime = int(os.path.getmtime(files["card"]))

    assert url.startswith(
        f"https://mzansiedge.co.za/assets/reel-cards/{date_str}/{pick_id}/card_{pick_id}.png"
    )
    assert url.endswith(f"?v={expected_mtime}"), (
        f"URL must end with ?v=<mtime>, got: {url}"
    )


# ── Test 2: missing file falls back to bare URL, never crashes ─────────────


def test_reel_asset_url_handles_missing_file(reel_root: Path) -> None:
    """When the file doesn't exist, return the unversioned URL — don't raise."""
    from dashboard.health_dashboard import _reel_asset_url

    url = _reel_asset_url("2026-04-28", "missing_pick_id", "card_missing.png")

    assert "?v=" not in url, f"missing file must not get a ?v= suffix: {url}"
    assert url == (
        "https://mzansiedge.co.za/assets/reel-cards/2026-04-28/missing_pick_id/card_missing.png"
    )


# ── Test 3: cache buster is monotonic across regen ─────────────────────────


def test_reel_asset_url_mtime_changes_when_file_regenerates(reel_root: Path) -> None:
    """Re-touching the card MUST yield a different ?v= integer."""
    from dashboard.health_dashboard import _reel_asset_url

    date_str = "2026-04-28"
    pick_id = "monotonic1234"
    files = _seed_kit(reel_root, date_str, pick_id)

    url_a = _reel_asset_url(date_str, pick_id, f"card_{pick_id}.png")

    # Bump mtime forward by 1 hour to simulate a regen.
    new_mtime = int(time.time()) + 3600
    os.utime(files["card"], (new_mtime, new_mtime))

    url_b = _reel_asset_url(date_str, pick_id, f"card_{pick_id}.png")

    assert url_a != url_b, "regenerated file must change the cache key"
    assert f"?v={new_mtime}" in url_b


# ── Test 4: widget JS surfaces VO download links + class hooks ─────────────


def test_render_reel_upload_panel_emits_vos_block() -> None:
    """`renderReelUploadPanel` JS body MUST emit Voice-overs surfacing.

    We inspect the raw source string emitted by the dashboard renderer.
    The widget must:
      - read `p.reel_vos`
      - emit the `so-rup-vos` container class
      - emit individual `so-rup-vo` link elements
      - guard against an empty array (no `vosBlock` HTML when none)
    """
    from dashboard import health_dashboard as hd

    src = Path(hd.__file__).read_text(encoding="utf-8")

    # Locate the renderReelUploadPanel function body.
    start = src.index("function renderReelUploadPanel(p)")
    end = src.index("\nfunction ", start + 1)
    body = src[start:end]

    assert "p.reel_vos" in body, "widget MUST read p.reel_vos from server payload"
    assert "so-rup-vos" in body, "widget MUST emit the so-rup-vos container class"
    assert "so-rup-vo" in body, "widget MUST emit individual so-rup-vo links"
    # Empty-array guard: vosBlock starts empty.
    assert "var vosBlock=''" in body, "widget MUST default vosBlock to empty"
    # Voice-overs label — gives operators a clear UI hook.
    assert "Voice-overs" in body


# ── Test 5: server payload exposes reel_vos with versioned URLs ────────────


def test_payload_path_uses_reel_asset_url_helper(reel_root: Path) -> None:
    """The server-side widget payload helper MUST use _reel_asset_url for VOs.

    We assert at the source level — the widget payload code branch
    (around line 10150) MUST call `_reel_asset_url` for each VO and append
    a `{"name":..., "url":..., "label":...}` dict to `reel_vos`. This is
    what makes the cache-buster effective on the dashboard widget end.
    """
    from dashboard import health_dashboard as hd

    src = Path(hd.__file__).read_text(encoding="utf-8")

    assert "reel_vos: list[dict] = []" in src, (
        "payload MUST initialise reel_vos as an empty list"
    )
    assert '_reel_asset_url(_effective_date, reel_pick_id, _vo_name)' in src, (
        "payload MUST call _reel_asset_url for each VO so the URL carries ?v=mtime"
    )
    assert '"reel_vos":        reel_vos,' in src, (
        "payload dict MUST include reel_vos key consumed by renderReelUploadPanel"
    )


# ── Test 6: gallery render also uses the helper ────────────────────────────


def test_gallery_render_uses_reel_asset_url_helper() -> None:
    """`render_reel_kit_page` (the dedicated gallery) MUST also use the helper.

    Defends against a future refactor that re-introduces the unversioned
    URL pattern in the gallery and re-opens the cache regression.
    """
    from dashboard import health_dashboard as hd

    src = Path(hd.__file__).read_text(encoding="utf-8")

    # Find the gallery render function body.
    start = src.index("def render_reel_kit_page")
    end = src.index("\ndef ", start + 1)
    body = src[start:end]

    assert "_reel_asset_url(today_str, pick_id" in body, (
        "gallery render MUST use _reel_asset_url for thumb/card/VO URLs"
    )
    # No regressed unversioned patterns inside this function.
    bad = (
        f'https://mzansiedge.co.za/assets/reel-cards/{{today_str}}/{{pick_id}}/'
        f'card_{{pick_id}}.png"'
    )
    assert bad not in body, (
        "gallery must not build the bare unversioned card URL — use the helper"
    )
