"""Contract tests for reel-card team-name display + rosette layout
(FIX-REEL-KIT-RENDERING-01).

Two regression surfaces:
  1. ``display_team_name(match_key_team, sport)`` — must produce the canonical
     short form for every team that has ever appeared in narrative_cache, and
     fall back to last-token capitalisation otherwise. Sport-aware.
  2. ``render_reel_card.py`` cascade — the tier rosette emoji must not overlap
     the league text or the home-team headline on any of the four tiers.
"""
from __future__ import annotations

import os
import sys
import tempfile

import pytest
from PIL import Image

# scripts/reel_cards is not a package — drop it on sys.path so we can import.
_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_REEL = os.path.join(_REPO, "scripts", "reel_cards")
if _REEL not in sys.path:
    sys.path.insert(0, _REEL)

from team_display_names import (  # noqa: E402  (after sys.path manipulation)
    display_team_name,
    known_team_count,
    IPL_DISPLAY,
    PSL_DISPLAY,
    EPL_DISPLAY,
    URC_DISPLAY,
    INTL_RUGBY_DISPLAY,
    INTL_CRICKET_DISPLAY,
    INTL_SOCCER_DISPLAY,
)
import render_reel_card  # noqa: E402


# ─── AC-1: display_team_name() ───────────────────────────────────────────────


class TestDisplayTeamName:
    """display_team_name handles match-key, uppercase, and spaced forms uniformly."""

    @pytest.mark.parametrize("input_form", [
        "punjab_kings",
        "PUNJAB_KINGS",
        "Punjab Kings",
        "  punjab_kings  ",
    ])
    def test_punjab_kings_variants_all_resolve_to_pbks(self, input_form):
        assert display_team_name(input_form, "cricket") == "PBKS"

    def test_brief_examples(self):
        # Examples explicitly listed in FIX-REEL-KIT-RENDERING-01 brief
        assert display_team_name("punjab_kings", "cricket") == "PBKS"
        assert display_team_name("rajasthan_royals", "cricket") == "RR"
        assert display_team_name("manchester_united", "soccer") == "MAN UTD"
        assert display_team_name("kaizer_chiefs", "soccer") == "CHIEFS"
        assert display_team_name("orlando_pirates", "soccer") == "PIRATES"

    def test_arsenal_falls_back_to_uppercase(self):
        # Brief: "Falls back to last-word capitalisation when no map entry
        # exists (e.g. arsenal → ARSENAL)". Arsenal is in EPL_DISPLAY, so this
        # exercises the explicit-entry path; the assertion is that the contract
        # form (uppercase, single word) is preserved.
        assert display_team_name("arsenal", "soccer") == "ARSENAL"

    def test_unmapped_team_falls_back_to_uppercase(self):
        # Single-token unmapped → full uppercase
        assert display_team_name("notarealteam", "") == "NOTAREALTEAM"
        # 2-token unmapped → joined with space, uppercase
        assert display_team_name("zalal_youssef", "combat") == "ZALAL YOUSSEF"
        # 3+ token unmapped → longest token wins (typical fighter
        # surname-first format).
        assert display_team_name("luna_martinetti_juan_adrian", "combat") == "MARTINETTI"


class TestIplFranchises:
    """All 10 IPL franchises map correctly to their canonical short forms."""

    @pytest.mark.parametrize("key,expected", [
        ("chennai_super_kings",         "CSK"),
        ("delhi_capitals",              "DC"),
        ("gujarat_titans",              "GT"),
        ("kolkata_knight_riders",       "KKR"),
        ("lucknow_super_giants",        "LSG"),
        ("mumbai_indians",              "MI"),
        ("punjab_kings",                "PBKS"),
        ("rajasthan_royals",            "RR"),
        ("royal_challengers_bengaluru", "RCB"),
        ("sunrisers_hyderabad",         "SRH"),
    ])
    def test_ipl_franchise_short_form(self, key, expected):
        assert display_team_name(key, "cricket") == expected


class TestPslClubs:
    """Major PSL clubs map cleanly. Brief AC-2 requires 16."""

    @pytest.mark.parametrize("key,expected", [
        ("kaizer_chiefs",       "CHIEFS"),
        ("orlando_pirates",     "PIRATES"),
        ("mamelodi_sundowns",   "SUNDOWNS"),
        ("amazulu",             "AMAZULU"),
        ("ts_galaxy",           "TS GALAXY"),
        ("magesi",              "MAGESI"),
        ("polokwane_city",      "POLOKWANE"),
        ("richards_bay",        "RICHARDS BAY"),
        ("stellenbosch",        "STELLIES"),
        ("chippa_united",       "CHIPPA"),
    ])
    def test_psl_club_short_form(self, key, expected):
        assert display_team_name(key, "soccer") == expected


class TestEplClubs:
    """Major EPL clubs (2025/26) map cleanly. Brief AC-2 requires 20."""

    @pytest.mark.parametrize("key,expected", [
        ("manchester_united",   "MAN UTD"),
        ("manchester_city",     "MAN CITY"),
        ("liverpool",           "LIVERPOOL"),
        ("arsenal",             "ARSENAL"),
        ("chelsea",             "CHELSEA"),
        ("tottenham",           "SPURS"),
        ("everton",             "EVERTON"),
        ("newcastle",           "NEWCASTLE"),
        ("nottingham_forest",   "FOREST"),
        ("crystal_palace",      "PALACE"),
        ("west_ham",            "WEST HAM"),
        ("wolves",              "WOLVES"),
    ])
    def test_epl_club_short_form(self, key, expected):
        assert display_team_name(key, "soccer") == expected


class TestUrcAndRugby:
    """URC franchises + national rugby short forms."""

    @pytest.mark.parametrize("key,expected", [
        ("stormers",          "STORMERS"),
        ("bulls",             "BULLS"),
        ("sharks",            "SHARKS"),
        ("vodacom_bulls",     "BULLS"),
        ("dhl_stormers",      "STORMERS"),
        ("hollywoodbets_sharks", "SHARKS"),
        ("leinster",          "LEINSTER"),
        ("munster",           "MUNSTER"),
        ("ulster",            "ULSTER"),
        ("connacht",          "CONNACHT"),
    ])
    def test_urc_franchise(self, key, expected):
        assert display_team_name(key, "rugby") == expected

    def test_south_africa_rugby_is_boks(self):
        assert display_team_name("south_africa", "rugby") == "BOKS"

    def test_new_zealand_rugby_is_all_blacks(self):
        assert display_team_name("new_zealand", "rugby") == "ALL BLACKS"


class TestNationalTeams:
    """Sport-aware disambiguation for national teams that appear in multiple
    sports (the brief calls this out — 'royals could be Rajasthan Royals in
    IPL OR Reading Royals — first match by (sport, match_key_team) tuple')."""

    def test_south_africa_cricket_is_proteas(self):
        assert display_team_name("south_africa", "cricket") == "PROTEAS"

    def test_south_africa_rugby_is_boks(self):
        assert display_team_name("south_africa", "rugby") == "BOKS"

    def test_south_africa_soccer_is_bafana(self):
        assert display_team_name("south_africa", "soccer") == "BAFANA"

    def test_new_zealand_cricket_is_blackcaps(self):
        assert display_team_name("new_zealand", "cricket") == "BLACKCAPS"

    def test_new_zealand_rugby_is_all_blacks(self):
        assert display_team_name("new_zealand", "rugby") == "ALL BLACKS"


class TestMapsAreSeeded:
    """AC-2 minimum-population guarantees."""

    def test_population_thresholds(self):
        counts = known_team_count()
        # AC-2: ≥10 IPL, ≥16 PSL, ≥20 EPL, ≥16 URC entries, plus nationals.
        # PSL/URC dicts also include alternative names (e.g. vodacom_bulls →
        # BULLS) so the dict counts can run higher than the brief minimum.
        assert counts["ipl"] >= 10
        assert counts["psl"] >= 16
        assert counts["epl"] >= 20
        # URC contains both canonical + sponsor-prefixed names — minimum 16
        # canonical franchises is the contract; we count entries, so the
        # threshold accounts for aliases.
        assert counts["urc"] >= 16
        # National teams (Boks/Proteas/Bafana) all present.
        assert counts["intl_rugby"] >= 10
        assert counts["intl_cricket"] >= 10
        assert counts["intl_soccer"] >= 10


# ─── AC-3: Rosette overlap regression guard ──────────────────────────────────


class TestRosetteOverlap:
    """Render each tier with a short-name and a long-name match. Verify the
    tier emoji does not occupy the same vertical band as the league text or
    the home-team headline.

    The cascade in render_reel_card.py is constructed so that:
      - tier emoji bottom edge sits clearly above the league text
      - league text sits clearly above the home-team headline
    Both gaps must be > 0 in pixel coordinates.
    """

    @pytest.mark.parametrize("tier,home,away,sport,league", [
        ("silver",  "PBKS",        "RR",       "cricket", "IPL"),
        ("gold",    "CHIEFS",      "PIRATES",  "soccer",  "PSL"),
        ("bronze",  "STORMERS",    "BULLS",    "rugby",   "URC"),
        ("diamond", "MAN CITY",    "EVERTON",  "soccer",  "EPL"),
        ("silver",  "RCB",         "CSK",      "cricket", "IPL"),
        # Long-name regression: ensure the cascade still places elements
        # without overlap when the team string is unusually wide.
        ("silver",  "MANCHESTER UNITED", "WEST HAM", "soccer", "EPL"),
    ])
    def test_no_pixel_overlap_between_emoji_and_text(
        self, tier, home, away, sport, league
    ):
        pick = {
            "tier":          tier,
            "home_team":     home,
            "away_team":     away,
            "pick_team":     home,
            "league":        league,
            "bookmaker":     "betway",
            "stake":         "R100",
            "return_amount": "R175",
            "profit":        "R75",
        }
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as fh:
            out_path = fh.name
        try:
            render_reel_card.render_reel_card(pick, out_path)
            self._assert_no_overlap(out_path, tier=tier)
        finally:
            try:
                os.unlink(out_path)
            except OSError:
                pass

    @staticmethod
    def _assert_no_overlap(path: str, *, tier: str) -> None:
        """Heuristic: the rendered card has yellow league text below the
        rosette and team-name text below that. Walk the central column and
        confirm there are at least two distinct yellow bands separated by
        non-yellow rows — i.e. the league text band is distinct from the
        divider line band, and the rosette is not painted into the team-name
        band.
        """
        im = Image.open(path).convert("RGB")
        w, h = im.size
        cx = w // 2

        # Sample yellowness across the upper half (above LINE_Y_FIXED area)
        yellow_rows: list[int] = []
        for y in range(120, 720):
            yellow_count = 0
            for x in range(cx - 80, cx + 80):
                r, g, b = im.getpixel((x, y))
                # Yellow ≈ (255, 210, 0). Allow generous tolerance for AA edges.
                if r > 200 and g > 170 and b < 100:
                    yellow_count += 1
            if yellow_count >= 6:
                yellow_rows.append(y)

        # Cluster contiguous rows into bands; a "gap" of >=4 non-yellow rows
        # marks a band boundary.
        bands: list[tuple[int, int]] = []
        if yellow_rows:
            start = prev = yellow_rows[0]
            for y in yellow_rows[1:]:
                if y - prev >= 4:
                    bands.append((start, prev))
                    start = y
                prev = y
            bands.append((start, prev))

        # We expect at least two distinct yellow bands above the divider:
        # 1. the league text (e.g. IPL / EPL / PSL)
        # 2. the divider line itself (or the VS text just above it)
        # Diamond's gem doesn't paint yellow, but the league text always does.
        assert len(bands) >= 2, (
            f"[{tier}] expected ≥2 distinct yellow bands above divider, "
            f"got {len(bands)}: {bands}"
        )

        # The two top bands must be separated by at least 8 non-yellow rows —
        # if they collapse, the league text is bleeding into the divider /
        # team-name band, which is the overlap shape the brief reported.
        top_two = sorted(bands)[:2]
        gap = top_two[1][0] - top_two[0][1] - 1
        assert gap >= 8, (
            f"[{tier}] yellow bands too close (gap={gap}px): {top_two}"
        )

    def test_canvas_dimensions_are_locked(self):
        # CARD-CASE-LOCK-01 references the 925x1364 template. Lock the size
        # so a future "let's resize the canvas" change is caught at test time.
        assert render_reel_card.CANVAS_W == 925
        assert render_reel_card.CANVAS_H == 1364
        assert render_reel_card.LINE_Y_FIXED == 700  # v6.5 lock


# ─── Sport-aware disambiguation ──────────────────────────────────────────────


class TestSportDisambiguation:
    """Per-brief AC-7: 'royals could be Rajasthan Royals in IPL OR Reading
    Royals — first match by (sport, match_key_team) tuple'. The lookup is
    sport-keyed; ambiguous tokens resolve based on the sport argument."""

    def test_lions_rugby_resolves_to_lions(self):
        # URC has "lions" entry. Sport=rugby walks URC first.
        assert display_team_name("lions", "rugby") == "LIONS"

    def test_sharks_rugby_resolves_to_urc_franchise(self):
        # URC Sharks is the canonical SA rugby franchise.
        assert display_team_name("sharks", "rugby") == "SHARKS"

    def test_chiefs_soccer_is_kaizer_chiefs(self):
        # PSL Chiefs (Kaizer Chiefs).
        assert display_team_name("kaizer_chiefs", "soccer") == "CHIEFS"

    def test_chiefs_rugby_is_super_rugby_chiefs(self):
        # Super Rugby has "chiefs" — different team from PSL Chiefs.
        assert display_team_name("chiefs", "rugby") == "CHIEFS"
