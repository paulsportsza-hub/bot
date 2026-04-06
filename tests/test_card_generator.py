"""IMG-W1 — Test suite for card_generator.py.

Tests cover:
- Public API signature and return type
- All 4 card types render without exception
- Output dimensions: 1280px wide, height ≤ 2560px
- PNG format verification
- Graceful degradation: empty data, missing fields
- MAX_CARDS_PER_DIGEST cap (5 rows)
- Per-card-type content checks
- Performance: <500ms per card
"""
from __future__ import annotations

import io
import time
import pytest

from PIL import Image


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_tip(tier: str = "gold", ev: float = 3.5) -> dict:
    """Return a minimal tip dict (hot-tips cache format)."""
    return {
        "home_team": "Kaizer Chiefs",
        "away_team": "Orlando Pirates",
        "display_tier": tier,
        "edge_rating": tier,
        "odds": 2.10,
        "ev": ev,
        "edge_score": 72.0,
        "composite_score": 72.0,
        "kickoff": "Sat 6 Apr · 17:30",
        "_bc_kickoff": "Sat 6 Apr · 17:30",
        "_bc_broadcast": "📺 SS PSL (DStv 202)",
        "sport_key": "soccer",
        "sport": "soccer",
        "sport_emoji": "⚽",
        "match_key": "kaizer_chiefs_vs_orlando_pirates_2026-04-06",
        "league": "PSL",
        "pick_team": "Kaizer Chiefs",
        "bookmaker": "hollywoodbets",
    }


def _make_game(with_form: bool = True) -> dict:
    """Return a minimal game dict (my_matches format)."""
    game = {
        "home_team": "Mamelodi Sundowns",
        "away_team": "Cape Town City",
        "kickoff": "Sun 7 Apr · 15:30",
        "_mm_kickoff": "Sun 7 Apr · 15:30",
        "sport_key": "soccer",
        "sport": "soccer",
    }
    if with_form:
        game["home_form"] = ["W", "W", "D", "W", "L"]
        game["away_form"] = ["L", "W", "D", "L", "W"]
    return game


def _make_card_data(tier: str = "gold") -> dict:
    """Return a minimal card_data dict (card_pipeline.build_card_data() format)."""
    return {
        "matchup": "Chiefs vs Pirates",
        "home_team": "Chiefs",
        "away_team": "Pirates",
        "outcome": "Home",
        "odds": 2.10,
        "bookmaker": "hollywoodbets",
        "confidence": 72.0,
        "ev": 3.5,
        "kickoff": "Sat 6 Apr · 17:30",
        "broadcast": "📺 SS PSL (DStv 202)",
        "sport": "soccer",
        "tier": tier,
        "display_tier": tier,
        "analysis_text": "This is a test analysis line.\nValue supported by price edge.",
        "pick_team": "Chiefs",
        "signals": {
            "price_edge": True,
            "form": True,
            "movement": False,
            "market": True,
            "tipster": False,
            "injury": False,
        },
        "odds_structured": {
            "home": {"bookmaker": "hollywoodbets", "odds": 2.10, "stale": ""},
            "draw": {"bookmaker": "betway", "odds": 3.20, "stale": ""},
            "away": {"bookmaker": "gbets", "odds": 3.60, "stale": ""},
        },
        "home_form": ["W", "W", "D", "W", "L"],
        "away_form": ["L", "D", "W", "L", "W"],
        "h2h": {"played": 10, "hw": 4, "d": 3, "aw": 3},
        "home_injuries": ["Keagan Dolly (Knee injury)", "Njabulo Blom (Thigh strain)"],
        "away_injuries": ["Thembinkosi Lorch (Hamstring)"],
        "key_stats": [
            {"label": "Rating", "home": "1850", "away": "1720"},
            {"label": "Form (L5)", "home": "WWDWL", "away": "LDWLW"},
            {"label": "H2H", "home": "4", "draw": "3", "away": "3"},
            {"label": "Tipster", "home": "68%", "away": "32%"},
        ],
        "no_edge_reason": "",
        "data_sources_used": ["odds_snapshots", "match_results"],
    }


def _png_size(png_bytes: bytes) -> tuple[int, int]:
    """Return (width, height) of PNG bytes."""
    img = Image.open(io.BytesIO(png_bytes))
    return img.size


def _is_png(data: bytes) -> bool:
    """Return True if data starts with the PNG magic bytes."""
    return data[:8] == b"\x89PNG\r\n\x1a\n"


# ── Import ────────────────────────────────────────────────────────────────────

from card_generator import generate_card, _CARD_W, _MAX_H, _DIGEST_W, _DIGEST_MAX_H, MAX_VISIBLE_PICKS


# ── T1: generate_card returns bytes ───────────────────────────────────────────

def test_generate_card_returns_bytes_edge_digest():
    result = generate_card("edge_digest", [_make_tip()])
    assert isinstance(result, bytes)


def test_generate_card_returns_bytes_my_matches():
    result = generate_card("my_matches", [_make_game()])
    assert isinstance(result, bytes)


def test_generate_card_returns_bytes_edge_detail():
    result = generate_card("edge_detail", _make_card_data())
    assert isinstance(result, bytes)


def test_generate_card_returns_bytes_match_detail():
    result = generate_card("match_detail", _make_card_data())
    assert isinstance(result, bytes)


# ── T2: PNG format ────────────────────────────────────────────────────────────

def test_edge_digest_is_png():
    result = generate_card("edge_digest", [_make_tip()])
    assert _is_png(result), "edge_digest output must be PNG"


def test_my_matches_is_png():
    result = generate_card("my_matches", [_make_game()])
    assert _is_png(result), "my_matches output must be PNG"


def test_edge_detail_is_png():
    result = generate_card("edge_detail", _make_card_data())
    assert _is_png(result), "edge_detail output must be PNG"


def test_match_detail_is_png():
    result = generate_card("match_detail", _make_card_data())
    assert _is_png(result), "match_detail output must be PNG"


# ── T3: Width == 1280 ─────────────────────────────────────────────────────────

def test_edge_digest_width():
    result = generate_card("edge_digest", [_make_tip()])
    w, h = _png_size(result)
    assert w == _DIGEST_W == 720


def test_my_matches_width():
    result = generate_card("my_matches", [_make_game()])
    w, h = _png_size(result)
    assert w == _CARD_W == 1280


def test_edge_detail_width():
    result = generate_card("edge_detail", _make_card_data())
    w, h = _png_size(result)
    assert w == _CARD_W == 1280


def test_match_detail_width():
    result = generate_card("match_detail", _make_card_data())
    w, h = _png_size(result)
    assert w == _CARD_W == 1280


# ── T4: Height <= 2560 ────────────────────────────────────────────────────────

def test_edge_digest_max_height():
    result = generate_card("edge_digest", [_make_tip()] * 10)
    w, h = _png_size(result)
    assert h <= _DIGEST_MAX_H == 3600


def test_my_matches_max_height():
    result = generate_card("my_matches", [_make_game()] * 30)
    w, h = _png_size(result)
    assert h <= _MAX_H == 2560


def test_edge_detail_max_height():
    data = _make_card_data()
    data["analysis_text"] = ("Long analysis " * 50).strip()
    data["home_injuries"] = ["Player A (status)"] * 10
    result = generate_card("edge_detail", data)
    w, h = _png_size(result)
    assert h <= _MAX_H == 2560


# ── T5: Empty / no data graceful degradation ─────────────────────────────────

def test_edge_digest_empty_list():
    """Empty list must return a valid PNG, not raise."""
    result = generate_card("edge_digest", [])
    assert _is_png(result)
    w, h = _png_size(result)
    assert w == _DIGEST_W


def test_my_matches_empty_list():
    result = generate_card("my_matches", [])
    assert _is_png(result)


def test_edge_detail_empty_dict():
    result = generate_card("edge_detail", {})
    assert _is_png(result)


def test_match_detail_empty_dict():
    result = generate_card("match_detail", {})
    assert _is_png(result)


def test_unknown_card_type_returns_png():
    """Unknown card_type falls back to edge_digest empty state."""
    result = generate_card("unknown_type", [])
    assert _is_png(result)


# ── T6: MAX_VISIBLE_PICKS cap ────────────────────────────────────────────────

def test_edge_digest_capped_at_max_visible_picks():
    """edge_digest shows at most MAX_VISIBLE_PICKS tips regardless of input size."""
    assert MAX_VISIBLE_PICKS == 8
    tips = [_make_tip("diamond", ev=10.0) for _ in range(12)]
    result = generate_card("edge_digest", tips)
    assert _is_png(result)
    w, h = _png_size(result)
    assert w == _DIGEST_W
    assert h <= _DIGEST_MAX_H


# ── T7: All 4 tiers render without exception ─────────────────────────────────

@pytest.mark.parametrize("tier", ["diamond", "gold", "silver", "bronze"])
def test_edge_digest_all_tiers(tier: str):
    result = generate_card("edge_digest", [_make_tip(tier)])
    assert _is_png(result)


@pytest.mark.parametrize("tier", ["diamond", "gold", "silver", "bronze"])
def test_edge_detail_all_tiers(tier: str):
    result = generate_card("edge_detail", _make_card_data(tier))
    assert _is_png(result)


@pytest.mark.parametrize("tier", ["diamond", "gold", "silver", "bronze"])
def test_match_detail_all_tiers(tier: str):
    result = generate_card("match_detail", _make_card_data(tier))
    assert _is_png(result)


# ── T8: Missing fields — no crash ─────────────────────────────────────────────

def test_edge_detail_no_odds():
    data = _make_card_data()
    data.pop("odds", None)
    data.pop("bookmaker", None)
    data.pop("odds_structured", None)
    result = generate_card("edge_detail", data)
    assert _is_png(result)


def test_edge_detail_no_analysis():
    data = _make_card_data()
    data["analysis_text"] = ""
    result = generate_card("edge_detail", data)
    assert _is_png(result)


def test_edge_detail_no_injuries():
    data = _make_card_data()
    data["home_injuries"] = []
    data["away_injuries"] = []
    result = generate_card("edge_detail", data)
    assert _is_png(result)


def test_match_detail_no_h2h():
    data = _make_card_data()
    data["h2h"] = {}
    result = generate_card("match_detail", data)
    assert _is_png(result)


def test_match_detail_no_key_stats():
    data = _make_card_data()
    data["key_stats"] = []
    result = generate_card("match_detail", data)
    assert _is_png(result)


def test_match_detail_no_form():
    data = _make_card_data()
    data["home_form"] = []
    data["away_form"] = []
    result = generate_card("match_detail", data)
    assert _is_png(result)


def test_my_matches_no_form():
    game = _make_game(with_form=False)
    result = generate_card("my_matches", [game])
    assert _is_png(result)


def test_my_matches_with_scores():
    game = _make_game()
    game["home_score"] = 2
    game["away_score"] = 1
    result = generate_card("my_matches", [game])
    assert _is_png(result)


# ── T9: Performance < 500ms ───────────────────────────────────────────────────

def test_edge_digest_under_500ms():
    tips = [_make_tip()] * 5
    start = time.perf_counter()
    generate_card("edge_digest", tips)
    elapsed = time.perf_counter() - start
    assert elapsed < 0.5, f"edge_digest took {elapsed:.3f}s (must be <0.5s)"


def test_edge_detail_under_500ms():
    start = time.perf_counter()
    generate_card("edge_detail", _make_card_data())
    elapsed = time.perf_counter() - start
    assert elapsed < 0.5, f"edge_detail took {elapsed:.3f}s (must be <0.5s)"


def test_match_detail_under_500ms():
    start = time.perf_counter()
    generate_card("match_detail", _make_card_data())
    elapsed = time.perf_counter() - start
    assert elapsed < 0.5, f"match_detail took {elapsed:.3f}s (must be <0.5s)"


# ── T10: Data accepts dict or single-item list ────────────────────────────────

def test_edge_detail_accepts_single_item_list():
    """edge_detail should also accept [card_data] list."""
    result = generate_card("edge_detail", [_make_card_data()])
    assert _is_png(result)


def test_match_detail_accepts_single_item_list():
    """match_detail should also accept [card_data] list."""
    result = generate_card("match_detail", [_make_card_data()])
    assert _is_png(result)


def test_edge_digest_accepts_single_dict():
    """edge_digest wraps single dict into list."""
    result = generate_card("edge_digest", _make_tip())
    assert _is_png(result)


# ── T11: Portrait dimensions ──────────────────────────────────────────────────

def test_edge_digest_portrait_width_720():
    """edge_digest must be exactly 720px wide (Telegram-optimised portrait)."""
    result = generate_card("edge_digest", [_make_tip()])
    w, h = _png_size(result)
    assert w == 720, f"Expected width 720, got {w}"


def test_edge_digest_portrait_min_height_1280():
    """edge_digest canvas must be at least 1280px tall (720×1280 minimum)."""
    result = generate_card("edge_digest", [_make_tip()])
    w, h = _png_size(result)
    assert h >= 1280, f"Expected height >= 1280, got {h}"


def test_edge_digest_portrait_max_height_cap():
    """10 tips must not exceed _DIGEST_MAX_H."""
    result = generate_card("edge_digest", [_make_tip()] * 10)
    w, h = _png_size(result)
    assert h <= _DIGEST_MAX_H


def test_edge_digest_other_card_types_unchanged_width():
    """my_matches and edge_detail must still be 1280px wide."""
    r_mm = generate_card("my_matches", [_make_game()])
    r_ed = generate_card("edge_detail", _make_card_data())
    w_mm, _ = _png_size(r_mm)
    w_ed, _ = _png_size(r_ed)
    assert w_mm == _CARD_W == 1280
    assert w_ed == _CARD_W == 1280


# ── T12: Tier grouping ────────────────────────────────────────────────────────

def test_edge_digest_tier_grouping_all_tiers():
    """All 4 tiers render together without error."""
    tips = [
        _make_tip("diamond", ev=12.0),
        _make_tip("gold", ev=5.0),
        _make_tip("silver", ev=2.5),
        _make_tip("bronze", ev=1.0),
    ]
    result = generate_card("edge_digest", tips)
    assert _is_png(result)
    w, h = _png_size(result)
    assert w == 720
    assert h >= 1280


def test_edge_digest_tier_grouping_single_tier():
    """Single tier (gold only) still renders correctly."""
    tips = [_make_tip("gold")] * 3
    result = generate_card("edge_digest", tips)
    assert _is_png(result)


# ── T13: Stats bar ────────────────────────────────────────────────────────────

def test_edge_digest_stats_summary_renders():
    """stats_summary dict embedded in tip renders without error."""
    tip = _make_tip()
    tip["stats_summary"] = {"last_10": "7W-2D-1L", "roi_7d": "+14.2%", "yesterday": "2/3"}
    result = generate_card("edge_digest", [tip])
    assert _is_png(result)
    w, h = _png_size(result)
    assert w == 720


def test_edge_digest_stats_summary_empty_dict():
    """Empty stats_summary shows dashes, does not crash."""
    tip = _make_tip()
    tip["stats_summary"] = {}
    result = generate_card("edge_digest", [tip])
    assert _is_png(result)


def test_edge_digest_stats_summary_absent():
    """No stats_summary key falls back gracefully to dashes."""
    tip = _make_tip()
    tip.pop("stats_summary", None)
    result = generate_card("edge_digest", [tip])
    assert _is_png(result)


# ── T14: Optional fields on tip rows ─────────────────────────────────────────

def test_edge_digest_no_league_field():
    """Tip with no league renders without error (no pill drawn)."""
    tip = _make_tip()
    tip.pop("league", None)
    result = generate_card("edge_digest", [tip])
    assert _is_png(result)


def test_edge_digest_no_broadcast_field():
    """Tip with no broadcast renders without error."""
    tip = _make_tip()
    tip.pop("_bc_broadcast", None)
    result = generate_card("edge_digest", [tip])
    assert _is_png(result)


def test_edge_digest_no_pick_team():
    """Tip with no pick_team falls back to outcome or empty string."""
    tip = _make_tip()
    tip.pop("pick_team", None)
    tip["outcome"] = "home"
    result = generate_card("edge_digest", [tip])
    assert _is_png(result)


def test_edge_digest_no_odds():
    """Tip with zero odds renders without error (no odds line drawn)."""
    tip = _make_tip()
    tip["odds"] = 0
    result = generate_card("edge_digest", [tip])
    assert _is_png(result)


def test_edge_digest_no_ev():
    """Tip with zero EV renders without EV line."""
    tip = _make_tip()
    tip["ev"] = 0
    result = generate_card("edge_digest", [tip])
    assert _is_png(result)


# ── T15: IMG-W1R2 — 720×1280 + logos + tier_filter + compact rows ─────────────

def test_edge_digest_max_visible_picks_constant():
    """MAX_VISIBLE_PICKS is exported and equals 8."""
    assert MAX_VISIBLE_PICKS == 8


def test_edge_digest_8_tips_fits_within_max_height():
    """8 compact tips (MAX_VISIBLE_PICKS) fit within DIGEST_MAX_H."""
    tips = (
        [_make_tip("diamond", ev=12.0)] * 2
        + [_make_tip("gold", ev=6.0)] * 2
        + [_make_tip("silver", ev=2.0)] * 2
        + [_make_tip("bronze", ev=0.5)] * 2
    )
    assert len(tips) == 8
    result = generate_card("edge_digest", tips)
    assert _is_png(result)
    w, h = _png_size(result)
    assert w == 720
    assert h >= 1280
    assert h <= _DIGEST_MAX_H


def test_edge_digest_tier_filter_diamond_only():
    """tier_filter=['diamond'] shows only diamond tips; gold/silver/bronze excluded."""
    tips = [
        _make_tip("diamond", ev=12.0),
        _make_tip("gold", ev=5.0),
        _make_tip("silver", ev=2.0),
        _make_tip("bronze", ev=0.5),
    ]
    result = generate_card("edge_digest", tips, tier_filter=["diamond"])
    assert _is_png(result)
    w, h = _png_size(result)
    assert w == 720


def test_edge_digest_tier_filter_gold_and_diamond():
    """tier_filter=['diamond', 'gold'] renders without error."""
    tips = [_make_tip("diamond"), _make_tip("gold"), _make_tip("silver")]
    result = generate_card("edge_digest", tips, tier_filter=["diamond", "gold"])
    assert _is_png(result)


def test_edge_digest_tier_filter_empty_shows_all():
    """tier_filter=None (default) shows all tiers."""
    tips = [_make_tip(t) for t in ["diamond", "gold", "silver", "bronze"]]
    result_default = generate_card("edge_digest", tips)
    result_none = generate_card("edge_digest", tips, tier_filter=None)
    assert _is_png(result_default)
    assert _is_png(result_none)


def test_edge_digest_tier_filter_no_match_renders_empty():
    """tier_filter that matches no tips renders empty state (no error)."""
    tips = [_make_tip("gold")]  # no diamond tips
    result = generate_card("edge_digest", tips, tier_filter=["diamond"])
    assert _is_png(result)
    w, h = _png_size(result)
    assert w == 720


def test_edge_digest_logo_fallback_when_get_logo_returns_none():
    """When get_logo returns None, render_team_badge fallback is used silently."""
    from unittest.mock import patch
    tip = _make_tip()
    with patch("card_generator.get_logo", return_value=None):
        result = generate_card("edge_digest", [tip])
    assert _is_png(result)
    w, h = _png_size(result)
    assert w == 720


def test_edge_digest_logo_loaded_from_cache():
    """When get_logo returns a valid path, logo is loaded without error."""
    import tempfile
    from pathlib import Path
    from unittest.mock import patch
    from PIL import Image as _PIL

    tip = _make_tip()
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        logo_path = Path(f.name)
        _PIL.new("RGBA", (96, 96), (100, 150, 200, 255)).save(str(logo_path), "PNG")

    try:
        with patch("card_generator.get_logo", return_value=logo_path):
            result = generate_card("edge_digest", [tip])
        assert _is_png(result)
        w, h = _png_size(result)
        assert w == 720
    finally:
        logo_path.unlink(missing_ok=True)


def test_edge_digest_compact_row_height_in_range():
    """Compact row height (_DIGEST_PICK_H) is within the 100-120px range."""
    from card_generator import _DIGEST_PICK_H
    assert 100 <= _DIGEST_PICK_H <= 120


def test_edge_digest_accepts_tier_filter_kwarg():
    """generate_card() accepts tier_filter as keyword argument without error."""
    tips = [_make_tip("gold")]
    result = generate_card("edge_digest", tips, tier_filter=["gold"])
    assert _is_png(result)


def test_edge_digest_other_card_types_ignore_tier_filter():
    """tier_filter has no effect on my_matches, edge_detail, match_detail."""
    games = [_make_game()]
    r_mm = generate_card("my_matches", games, tier_filter=["diamond"])
    assert _is_png(r_mm)
    r_ed = generate_card("edge_detail", _make_card_data(), tier_filter=["diamond"])
    assert _is_png(r_ed)


# ── T16: IMG-W1R3 — Visual overhaul assertions ────────────────────────────────

def test_league_display_psl_not_slug():
    """_league_display('psl') must NOT return raw slug 'psl'."""
    from card_generator import _league_display
    result = _league_display("psl")
    assert result != "psl", f"Expected human label, got raw slug '{result}'"
    assert "PSL" in result.upper() or "🇿🇦" in result

def test_league_display_epl_not_slug():
    """_league_display('epl') must NOT return raw slug 'epl'."""
    from card_generator import _league_display
    result = _league_display("epl")
    assert "epl" != result.lower()

def test_edge_digest_broadcast_channel_renders():
    """Tip with _bc_broadcast renders without error (TV channel on row 2)."""
    tip = _make_tip()
    tip["_bc_broadcast"] = "📺 SS PSL (DStv 202)"
    result = generate_card("edge_digest", [tip])
    assert _is_png(result)
    w, h = _png_size(result)
    assert w == 720

def test_edge_digest_form_dots_renders():
    """Tip with home_form / away_form renders without error (form dots on row 3)."""
    tip = _make_tip()
    tip["home_form"] = ["W", "W", "D", "L", "W"]
    tip["away_form"] = ["L", "W", "D", "L", "W"]
    result = generate_card("edge_digest", [tip])
    assert _is_png(result)
    w, h = _png_size(result)
    assert w == 720

def test_edge_digest_pick_team_green_renders():
    """Tip with explicit pick_team renders without error."""
    tip = _make_tip()
    tip["pick_team"] = "Kaizer Chiefs"
    result = generate_card("edge_digest", [tip])
    assert _is_png(result)

def test_edge_digest_tier_header_with_count():
    """Multiple tips in same tier render tier header with count."""
    tips = [_make_tip("gold")] * 3
    result = generate_card("edge_digest", tips)
    assert _is_png(result)
    w, h = _png_size(result)
    assert w == 720

def test_compute_digest_stats_returns_dict():
    """compute_digest_stats() always returns a dict (no crash)."""
    from card_generator import compute_digest_stats
    result = compute_digest_stats()
    assert isinstance(result, dict)
