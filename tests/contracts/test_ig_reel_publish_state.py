"""Contract tests for INV-IG-REEL-SILVER-PUBLISH-FAIL-01.

AC-5: 4+ tests covering the identified failure modes and fixes.

(a) Publisher cron entry covers 20:30 SAST (18:30 UTC).
(b) api_reel_final_upload() writes canonical public HTTPS URL, not admin path.
(c) _heal_admin_reel_path() rewrites healable admin paths; non-healable → None.
(d) SILVER tier with MP4 asset is routed as REEL (in-scope confirmation).
"""

import re
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers — resolve paths without importing heavy dependencies
# ---------------------------------------------------------------------------

PUBLISHER_DIR = Path("/home/paulsportsza/publisher")
BOT_DIR = Path("/home/paulsportsza/bot")
DASHBOARD_PATH = BOT_DIR / "dashboard" / "health_dashboard.py"
PUBLISHER_PY = PUBLISHER_DIR / "publisher.py"
INSTAGRAM_PY = PUBLISHER_DIR / "channels" / "instagram.py"


# ---------------------------------------------------------------------------
# (a) Cron schedule covers 20:30 SAST = 18:30 UTC
# ---------------------------------------------------------------------------

def test_publisher_cron_covers_2030_sast():
    """Publisher cron `0,30 4-21 * * *` must fire at 18:30 UTC (20:30 SAST)."""
    cron_src = Path("/etc/cron.d/mzansiedge-publisher")
    if not cron_src.exists():
        # Try user crontab export
        import subprocess
        result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        cron_text = result.stdout
    else:
        cron_text = cron_src.read_text()

    # The canonical publisher cron fires at minutes 0 and 30 for hours 4–21 UTC
    # 18:30 UTC = minute 30, hour 18 — within range 4–21, minute list includes 30.
    # Verify the schedule string exists verbatim in cron config.
    assert re.search(r"0,30\s+4-21\s+\*\s+\*\s+\*", cron_text), (
        "Publisher cron '0,30 4-21 * * *' not found — 20:30 SAST slot would be missed. "
        f"Cron text:\n{cron_text[:500]}"
    )


# ---------------------------------------------------------------------------
# (b) api_reel_final_upload() uses _REEL_PUBLIC_BASE, not admin path
# ---------------------------------------------------------------------------

def test_dashboard_upload_handler_writes_public_url():
    """api_reel_final_upload() must write _REEL_PUBLIC_BASE URL, never /admin/... path."""
    src = DASHBOARD_PATH.read_text()

    # The bad pattern that triggered this incident
    bad_pattern = r'/admin/social-ops/asset/reels/'
    assert bad_pattern not in src, (
        "health_dashboard.py still contains the admin path in api_reel_final_upload(). "
        "INV-IG-REEL-SILVER-PUBLISH-FAIL-01 fix was not applied."
    )

    # The fix must use _REEL_PUBLIC_BASE constant in the upload handler
    assert "_REEL_PUBLIC_BASE" in src, (
        "health_dashboard.py does not define _REEL_PUBLIC_BASE constant."
    )

    # Confirm the api_reel_final_upload function uses the public base constant
    fn_idx = src.find("def api_reel_final_upload(")
    assert fn_idx != -1, "api_reel_final_upload() not found in health_dashboard.py"
    fn_body = src[fn_idx: fn_idx + 2000]
    assert "_REEL_PUBLIC_BASE" in fn_body, (
        "api_reel_final_upload() does not reference _REEL_PUBLIC_BASE — "
        "upload handler still writes relative/admin URL to Notion."
    )


# ---------------------------------------------------------------------------
# (c) _heal_admin_reel_path() auto-heal logic
# ---------------------------------------------------------------------------

def test_heal_admin_reel_path_rewrites_known_pattern():
    """_heal_admin_reel_path() must convert admin path to canonical public URL."""
    sys.path.insert(0, str(PUBLISHER_DIR))
    from publisher import _heal_admin_reel_path  # noqa: PLC0415

    admin_path = (
        "/admin/social-ops/asset/reels/2026-04-28/final/"
        "350d9048-d73c-81c6-9e1c-e01511ecbb89.mp4"
    )
    healed = _heal_admin_reel_path(admin_path)
    assert healed == (
        "https://mzansiedge.co.za/assets/reels/2026-04-28/final/"
        "350d9048-d73c-81c6-9e1c-e01511ecbb89.mp4"
    ), f"Unexpected healed URL: {healed}"


def test_heal_admin_reel_path_returns_none_for_unknown_scheme():
    """_heal_admin_reel_path() must return None for unrecognised bad URLs."""
    sys.path.insert(0, str(PUBLISHER_DIR))
    from publisher import _heal_admin_reel_path  # noqa: PLC0415

    assert _heal_admin_reel_path("computer://some/path.mp4") is None
    assert _heal_admin_reel_path("http://example.com/video.mp4") is None
    assert _heal_admin_reel_path("") is None
    assert _heal_admin_reel_path("/some/other/admin/path.mp4") is None


# ---------------------------------------------------------------------------
# (d) SILVER tier with MP4 asset resolves to REEL
# ---------------------------------------------------------------------------

def test_silver_tier_mp4_resolves_to_reel():
    """SILVER tier row with .mp4 asset_link must be routed as REEL (not IMAGE)."""
    sys.path.insert(0, str(PUBLISHER_DIR))
    from channels.instagram import _resolve_media_type  # noqa: PLC0415

    item = {
        "tier": "silver",
        "asset_link": "https://mzansiedge.co.za/assets/reels/2026-04-28/final/test.mp4",
        "media_type": "",
    }
    media_type = _resolve_media_type(item)
    assert media_type == "REEL", (
        f"SILVER + MP4 should resolve to REEL, got {media_type!r}. "
        "IG reel publish will be skipped for SILVER tier."
    )
