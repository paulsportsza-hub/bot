"""P3-03 — Contract tests: image_card.py + DigestMessage.build_photo().

AC-13 coverage:
    - Card generation produces valid PNG
    - Card respects 5-match limit
    - Fallback (RuntimeError) works
    - DigestMessage.build_photo() returns (bytes, str, InlineKeyboardMarkup)
"""
from __future__ import annotations

import io
import sys
import os

import pytest
from PIL import Image
from telegram import InlineKeyboardMarkup

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from image_card import (
    generate_digest_card,
    _MAX_CARDS,
    _W,
    _H,
)
from message_types import DigestMessage

# ── Test fixtures ─────────────────────────────────────────────────────────────

def _make_pick(i: int, tier: str = "gold") -> dict:
    return {
        "display_tier": tier,
        "home_team": f"Home Team {i}",
        "away_team": f"Away Team {i}",
        "kickoff": f"Sat {15 + i}:00",
        "sport_emoji": "⚽",
        "odds": 1.80 + i * 0.1,
        "composite_score": 50 + i * 5,
        "cb_key": f"home{i}_vs_away{i}_2026-04-05",
    }


def _parse_png(data: bytes) -> Image.Image:
    """Load PNG bytes into PIL Image."""
    return Image.open(io.BytesIO(data))


# ── AC-13-1: valid PNG with correct dimensions ────────────────────────────────

def test_card_generates_valid_png():
    picks = [_make_pick(i) for i in range(3)]
    data = generate_digest_card(picks)
    assert isinstance(data, bytes)
    img = _parse_png(data)
    assert img.width == _W
    assert img.height == _H
    assert img.format == "PNG"


def test_card_zero_edges_produces_valid_png():
    data = generate_digest_card([])
    img = _parse_png(data)
    assert img.size == (_W, _H)


def test_card_single_edge():
    picks = [_make_pick(0, "diamond")]
    data = generate_digest_card(picks)
    img = _parse_png(data)
    assert img.size == (_W, _H)


# ── AC-13-2: 5-match limit ────────────────────────────────────────────────────

def test_card_respects_5_match_limit():
    """Pass 8 picks — card must still generate without error and be valid PNG."""
    picks = [_make_pick(i) for i in range(8)]
    assert len(picks) > _MAX_CARDS
    data = generate_digest_card(picks)
    img = _parse_png(data)
    assert img.size == (_W, _H)


def test_max_cards_constant_is_5():
    assert _MAX_CARDS == 5


# ── AC-13-3: fallback — RuntimeError on failure ───────────────────────────────

def test_generate_raises_runtime_error_on_bad_input(monkeypatch):
    """Simulate Pillow failure → RuntimeError must propagate."""
    import image_card as ic

    def _broken_font(*args, **kwargs):
        raise OSError("mock font failure")

    monkeypatch.setattr(ic, "_font", _broken_font)
    with pytest.raises(RuntimeError):
        generate_digest_card([_make_pick(0)])


# ── All tier variants render without error ────────────────────────────────────

@pytest.mark.parametrize("tier", ["diamond", "gold", "silver", "bronze"])
def test_card_all_tiers(tier):
    picks = [_make_pick(0, tier)]
    data = generate_digest_card(picks)
    img = _parse_png(data)
    assert img.size == (_W, _H)


# ── Long team names (AC edge case) ────────────────────────────────────────────

def test_card_very_long_team_names():
    picks = [{
        "display_tier": "gold",
        "home_team": "Extremely Long Football Club Name United",
        "away_team": "Another Very Long Team Name City FC",
        "odds": 2.0,
    }]
    data = generate_digest_card(picks)
    img = _parse_png(data)
    assert img.size == (_W, _H)


# ── DigestMessage.build_photo() ───────────────────────────────────────────────

def test_build_photo_returns_correct_tuple():
    picks = [_make_pick(i) for i in range(3)]
    png, caption, markup = DigestMessage.build_photo(picks)
    assert isinstance(png, bytes)
    assert len(png) > 0
    assert isinstance(caption, str)
    assert "<b>" in caption
    assert isinstance(markup, InlineKeyboardMarkup)


def test_build_photo_keyboard_has_tier_filter_buttons():
    picks = [_make_pick(0)]
    _, _, markup = DigestMessage.build_photo(picks)
    all_cbs = [
        btn.callback_data
        for row in markup.inline_keyboard
        for btn in row
        if hasattr(btn, "callback_data")
    ]
    assert "digest:filter:gold" in all_cbs
    assert "digest:filter:silver" in all_cbs
    assert "digest:filter:bronze" in all_cbs
    assert "digest:filter:diamond" in all_cbs


def test_build_photo_keyboard_has_nav_button():
    picks = [_make_pick(0)]
    _, _, markup = DigestMessage.build_photo(picks)
    all_cbs = [
        btn.callback_data
        for row in markup.inline_keyboard
        for btn in row
        if hasattr(btn, "callback_data")
    ]
    assert "nav:main" in all_cbs


def test_build_photo_zero_picks_still_works():
    png, caption, markup = DigestMessage.build_photo([])
    assert isinstance(png, bytes)
    assert isinstance(markup, InlineKeyboardMarkup)


def test_build_photo_fallback_on_RuntimeError(monkeypatch):
    """DigestMessage.build_photo() raises RuntimeError on Pillow failure.
    Caller must fall back to DigestMessage.build().
    """
    import image_card as ic
    monkeypatch.setattr(ic, "_font", lambda *a, **kw: (_ for _ in ()).throw(OSError("fail")))

    picks = [_make_pick(0)]
    with pytest.raises(RuntimeError):
        DigestMessage.build_photo(picks)

    # Verify fallback still works
    text, markup = DigestMessage.build(picks)
    assert isinstance(text, str)
    assert isinstance(markup, InlineKeyboardMarkup)


def test_build_photo_caption_mentions_edge_count():
    picks = [_make_pick(i) for i in range(4)]
    _, caption, _ = DigestMessage.build_photo(picks)
    assert "4" in caption or "edge" in caption


def test_build_photo_png_dimensions():
    picks = [_make_pick(0)]
    png, _, _ = DigestMessage.build_photo(picks)
    img = _parse_png(png)
    assert img.width == _W
    assert img.height == _H
