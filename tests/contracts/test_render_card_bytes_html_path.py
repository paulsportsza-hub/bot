"""Contract test: render_card_bytes uses HTML path (BUILD-SERVE-CARD-DETAIL-HTML-01).

Validates that render_card_bytes internals use the HTML render path (render_card_sync +
edge_detail.html) rather than the old Pillow shim (generate_match_card).

Acceptance criteria (AC-D):
  - Image bytes > 100 KB  (HTML renders ~130 KB; shim was ~58 KB)
  - Image dimensions 960×1240  (HTML path: 480×620 CSS × device_scale_factor=2)
  - caption_html contains edge matchup structure (" vs " token)
  - markup is InlineKeyboardMarkup
"""

import io
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

_FIXTURE_MATCH_KEY = "2026-04-21_kaizer-chiefs_orlando-pirates"
_FIXTURE_TIP = {
    "outcome": "Home Win",
    "odds": 2.10,
    "bookmaker": "Betway",
    "home": "Kaizer Chiefs",
    "away": "Orlando Pirates",
    "ev": 6.5,
    "display_tier": "gold",
    "tier": "gold",
    "match_key": _FIXTURE_MATCH_KEY,
}


@pytest.fixture
def rendered():
    """Call render_card_bytes with the fixture tip and return (img, caption, markup)."""
    from card_pipeline import render_card_bytes

    return render_card_bytes(
        _FIXTURE_MATCH_KEY,
        _FIXTURE_TIP,
        include_analysis=False,
        buttons=[],
    )


def test_render_card_bytes_image_size_exceeds_100kb(rendered):
    """HTML renders are ~130 KB; Pillow shim was ~58 KB. Gate at 100 KB."""
    img, _, _ = rendered
    assert len(img) > 100_000, (
        f"Image bytes {len(img)} ≤ 100 KB — render_card_bytes is still using the Pillow shim "
        f"(BUILD-SERVE-CARD-DETAIL-HTML-01 swap failed)."
    )


def test_render_card_bytes_image_dimensions_960x1240(rendered):
    """HTML path renders at 480×620 CSS × device_scale_factor=2 = 960×1240 px."""
    from PIL import Image

    img, _, _ = rendered
    with Image.open(io.BytesIO(img)) as im:
        w, h = im.width, im.height
    assert (w, h) == (960, 1240), (
        f"Image dimensions {w}×{h} ≠ 960×1240 — expected HTML path output "
        f"(BUILD-SERVE-CARD-DETAIL-HTML-01)."
    )


def test_render_card_bytes_caption_contains_matchup_structure(rendered):
    """Caption must contain ' vs ' — the matchup token always present in render_card_html."""
    _, caption, _ = rendered
    assert " vs " in caption, (
        f"caption_html missing ' vs ' token — unexpected caption: {caption[:120]!r}"
    )


def test_render_card_bytes_returns_inline_keyboard_markup(rendered):
    """Third return value must be an InlineKeyboardMarkup."""
    from telegram import InlineKeyboardMarkup

    _, _, markup = rendered
    assert isinstance(markup, InlineKeyboardMarkup), (
        f"Expected InlineKeyboardMarkup, got {type(markup).__name__}"
    )
