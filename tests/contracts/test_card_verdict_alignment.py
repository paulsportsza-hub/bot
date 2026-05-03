"""FIX-CARD-VERDICT-RECOMMENDATION-ALIGNMENT-01 — card-verdict alignment guard.

QA-LIVE-CARDS-EVERY-ACTIVE-01 (2026-05-02) found 8 of 25 in-scope edges (32%)
where the card image displayed one recommendation while the verdict text
referenced a different team / odds / bookmaker. The root cause was the
``_enrich_tip_for_card`` fallback at ``bot.py`` lines 9128-9137: when the
serve-time staleness check detected drift between the cached
``narrative_cache.verdict_html`` and the live ``edge_results`` row, the code
re-served the same stale verdict text instead of regenerating from the live
tip the card image was rendering from.

The fix routes the regenerate path through ``build_narrative_spec`` →
``_render_verdict`` so both the card image (``build_card_data`` in
``card_pipeline.py``) and the verdict text consume the same single source of
truth: the latest unsettled ``edge_results`` row, expressed via the live
``tip`` dict.

This regression guard pins:

1. ``test_render_verdict_uses_live_tip_outcome_odds_bookmaker`` — when called
   with a ``NarrativeSpec`` derived from the live tip, ``_render_verdict``
   produces text that references the same outcome team, odds, and bookmaker
   that ``build_card_data`` exposes for the same tip.
2. ``test_outcome_flip_emits_aligned_verdict`` — flipping the tip's outcome
   key (home → away) flips the verdict's outcome team to match.
3. ``test_bookmaker_drift_emits_aligned_verdict`` — changing only the tip's
   bookmaker propagates into the verdict text.
4. ``test_odds_drift_emits_aligned_verdict`` — changing the tip's odds value
   propagates into the verdict text (within fmt tolerance).
5. ``test_enrich_tip_for_card_regenerates_on_stale_cache`` — when
   ``_enrich_tip_for_card`` sees a stale ``narrative_cache.verdict_html`` row
   that disagrees with the current tip, ``enriched["verdict"]`` is rebuilt
   from the live tip and references the live tip's recommendation, not the
   stale cache row's recommendation.
6. ``test_failure_corpus_aligned_post_fix`` (parametrized over the 8 known
   failures + 5 controls) — the live tip the card image consumes and the
   verdict ``_render_verdict`` produces share outcome / odds / bookmaker.

These tests do not require a populated odds.db. They construct synthetic tips
mirroring the production ``_load_tips_from_edge_results`` shape and assert
the deterministic ``_render_verdict`` output uses those values verbatim.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


@pytest.fixture(autouse=True)
def _force_corpus_path(monkeypatch):
    """Pin _render_verdict / render_verdict to the legacy corpus path.

    BUILD-VERDICT-SIGNAL-MAPPED-01 (2026-05-03): The new spec §10 tier
    actions explicitly remove odds + bookmaker from non-Diamond closes
    (Gold = "back {team}, standard stake" etc.). The original alignment
    guard from FIX-CARD-VERDICT-RECOMMENDATION-ALIGNMENT-01 was authored
    against the corpus where every tier slot-fills {odds} and
    {bookmaker}. Pinning the flag off keeps the corpus alignment guard
    intact as the rollback regression. The signal-mapped path has its
    own alignment + tier-action coverage in test_verdict_signal_mapper.py.
    """
    monkeypatch.setenv("USE_SIGNAL_MAPPED_VERDICTS", "0")
    yield


# ── Failure corpus from QA-LIVE-CARDS-EVERY-ACTIVE-01 ─────────────────────────
# Each entry: (match_key, tier, outcome_key, outcome_label, odds, bookmaker_display, ev_pct, sport)

_FAILURE_CASES: tuple[tuple[str, str, str, str, float, str, float, str], ...] = (
    # Brentford-WestHam: edge_results says Home Win 1.93 @ playabets (Gold)
    ("brentford_vs_west_ham_2026-05-02", "gold", "home", "Brentford",
     1.93, "PlayaBets", 2.7, "soccer"),
    # Fijian Drua-Highlanders: edge_results says Away Win 2.75 @ hollywoodbets (Silver)
    ("fijian_drua_vs_highlanders_2026-05-02", "silver", "away", "Highlanders",
     2.75, "HWB", 5.3, "rugby"),
    # Aston Villa-Tottenham: edge_results says Away Win 3.40 @ wsb (Bronze)
    ("aston_villa_vs_tottenham_2026-05-03", "bronze", "away", "Tottenham",
     3.40, "WSB", 2.4, "soccer"),
    # Hurricanes-Crusaders: cached verdict said Crusaders 8.50 @ WSB
    ("hurricanes_vs_crusaders_2026-05-01", "bronze", "away", "Crusaders",
     8.50, "WSB", 2.4, "rugby"),
    # Stellenbosch-Orlando Pirates: edge_results says Away Win 1.90 @ hollywoodbets (Silver)
    ("stellenbosch_vs_orlando_pirates_2026-05-05", "silver", "away", "Orlando Pirates",
     1.90, "HWB", 5.6, "soccer"),
    # Waratahs-Western Force: cached verdict said Waratahs 1.68 @ GBets
    ("waratahs_vs_western_force_2026-05-01", "silver", "home", "Waratahs",
     1.68, "GBets", 2.9, "rugby"),
    # Arsenal-Fulham: edge_results says Home Win 1.51 @ supersportbet (Gold)
    ("arsenal_vs_fulham_2026-05-02", "gold", "home", "Arsenal",
     1.51, "SuperSportBet", 2.7, "soccer"),
    # Chelsea-Nottingham Forest: edge_results says Home Win 1.73 @ playabets (Silver)
    ("chelsea_vs_nottingham_forest_2026-05-04", "silver", "home", "Chelsea",
     1.73, "PlayaBets", 3.6, "soccer"),
)

# Control cases — already-clean fixtures from QA-LIVE-CARDS-EVERY-ACTIVE-01.
_CONTROL_CASES: tuple[tuple[str, str, str, str, float, str, float, str], ...] = (
    ("everton_vs_manchester_city_2026-05-04", "gold", "away", "Manchester City",
     1.53, "Supabets", 4.0, "soccer"),
    ("brighton_vs_wolves_2026-05-09", "gold", "home", "Brighton & Hove Albion",
     1.37, "Supabets", 5.5, "soccer"),
    ("manchester_city_vs_brentford_2026-05-09", "diamond", "home", "Manchester City",
     1.36, "Supabets", 6.0, "soccer"),
    ("liverpool_vs_chelsea_2026-05-09", "diamond", "home", "Liverpool",
     1.96, "Supabets", 8.0, "soccer"),
    ("fulham_vs_bournemouth_2026-05-09", "silver", "away", "AFC Bournemouth",
     2.62, "PlayaBets", 4.5, "soccer"),
)

_ALL_CASES = _FAILURE_CASES + _CONTROL_CASES

_BOOKMAKER_SWEEP_CASES: tuple[tuple[str, str, str, str, str, float], ...] = (
    ("diamond", "soccer", "Manchester City", "Brentford", "Supabets", 1.40),
    ("diamond", "rugby", "Bulls", "Stormers", "Hollywoodbets", 1.65),
    ("gold", "cricket", "Delhi Capitals", "Chennai Super Kings", "WSB", 1.91),
    ("gold", "soccer", "Liverpool", "Chelsea", "Supabets", 1.95),
    ("silver", "soccer", "Stellenbosch", "Orlando Pirates", "Hollywoodbets", 1.90),
    ("silver", "rugby", "Fijian Drua", "Highlanders", "Betway", 2.75),
    ("silver", "cricket", "Sunrisers Hyderabad", "Kolkata Knight Riders", "Sportingbet", 1.63),
    ("bronze", "soccer", "Arsenal", "Atletico Madrid", "SuperSportBet", 1.66),
    ("bronze", "rugby", "Waratahs", "Western Force", "GBets", 1.68),
    ("bronze", "cricket", "Punjab Kings", "Mumbai Indians", "PlayaBets", 2.80),
)


def _build_synthetic_tip(
    match_key: str, tier: str, outcome_key: str, outcome_label: str,
    odds: float, bookmaker: str, ev_pct: float, sport: str,
) -> dict:
    """Mirror the shape produced by ``_load_tips_from_edge_results``."""
    import re as _re
    _mk_no_date = _re.sub(r"_\d{4}-\d{2}-\d{2}$", "", match_key)
    _h_raw, _a_raw = _mk_no_date.split("_vs_", 1)
    home_display = " ".join(w.capitalize() for w in _h_raw.split("_"))
    away_display = " ".join(w.capitalize() for w in _a_raw.split("_"))
    return {
        "match_id": match_key,
        "match_key": match_key,
        "sport_key": sport,
        "sport": sport,
        "home_team": home_display,
        "away_team": away_display,
        "outcome": outcome_label,
        "outcome_key": outcome_key,
        "outcome_label": outcome_label,
        "odds": odds,
        "bookmaker": bookmaker,
        "bookmaker_key": bookmaker.lower(),
        "ev": ev_pct,
        "predicted_ev": ev_pct,
        "edge_rating": tier,
        "display_tier": tier,
        "edge_tier": tier,
        "edge_score": 70.0 if tier == "diamond" else (55.0 if tier == "gold" else (40.0 if tier == "silver" else 25.0)),
        "league": "epl" if sport == "soccer" else ("super_rugby" if sport == "rugby" else ""),
        "league_key": "epl" if sport == "soccer" else ("super_rugby" if sport == "rugby" else ""),
        "edge_v2": {
            "match_key": match_key,
            "home_team": home_display,
            "away_team": away_display,
            "league": "epl" if sport == "soccer" else "super_rugby",
            "sport": sport,
            "recommended_outcome": outcome_key,
            "outcome": outcome_key,
            "best_odds": odds,
            "best_bookmaker": bookmaker,
            "best_bookmaker_key": bookmaker.lower(),
            "edge_pct": ev_pct,
            "fair_probability": (1 + ev_pct / 100.0) / odds if odds > 1.0 else 0,
            "composite_score": 70.0 if tier == "diamond" else (55.0 if tier == "gold" else (40.0 if tier == "silver" else 25.0)),
            "confirming_signals": 3 if tier == "diamond" else (2 if tier == "gold" else (1 if tier == "silver" else 0)),
            "contradicting_signals": 0,
            "tier": tier,
            "ev": ev_pct,
        },
    }


@pytest.mark.parametrize(
    "match_key,tier,outcome_key,outcome_label,odds,bookmaker,ev_pct,sport",
    _ALL_CASES,
    ids=[c[0] for c in _ALL_CASES],
)
def test_failure_corpus_aligned_post_fix(
    match_key, tier, outcome_key, outcome_label, odds, bookmaker, ev_pct, sport,
):
    """AC-3: card_image and verdict_html share outcome / odds / bookmaker.

    The test reflects the production path: the live tip is the single source
    of truth. ``build_card_data`` exposes ``outcome``, ``odds``,
    ``bookmaker`` from ``tip`` directly. ``build_narrative_spec`` →
    ``_render_verdict`` produces text that references the same values.
    """
    from narrative_spec import build_narrative_spec, _render_verdict

    tip = _build_synthetic_tip(
        match_key, tier, outcome_key, outcome_label,
        odds, bookmaker, ev_pct, sport,
    )

    # Build the same edge_data shape the production path uses
    # (mirrors _extract_edge_data without requiring bot import).
    edge_data = {
        "home_team": tip["home_team"],
        "away_team": tip["away_team"],
        "league": tip["league"],
        "best_bookmaker": tip["bookmaker"],
        "best_odds": tip["odds"],
        "edge_pct": tip["ev"],
        "outcome": outcome_key,
        "outcome_team": outcome_label,
        "confirming_signals": tip["edge_v2"]["confirming_signals"],
        "contradicting_signals": 0,
        "composite_score": tip["edge_v2"]["composite_score"],
        "fair_prob": tip["edge_v2"]["fair_probability"],
        "edge_tier": tier,
    }

    spec = build_narrative_spec({}, edge_data, [tip], sport)
    verdict = _render_verdict(spec)
    assert verdict, f"empty verdict for {match_key}"

    # Card image consumes these directly from the live tip; verdict text
    # MUST reference the same recommendation row.
    #
    # Alignment checks:
    #   1. The recommendation phrase ("<TEAM> win at <ODDS> with
    #      <BOOKMAKER>" / "<TEAM> at <ODDS> with <BOOKMAKER>") in the
    #      verdict references the recommended team's distinguishing tokens
    #      (verdict templates may use a short form like "Brighton" for
    #      "Brighton & Hove Albion").
    #   2. The OPPOSING team is not the subject of the recommendation
    #      phrase — this is the exact failure mode QA captured (verdict
    #      recommended the wrong team while the card image showed the
    #      correct one).
    #   3. Odds value matches (formatted to 2dp).
    #   4. Bookmaker name matches.
    home_team = tip["home_team"]
    away_team = tip["away_team"]
    other_team = away_team if outcome_key == "home" else home_team
    card_odds = f"{odds:.2f}"
    card_bookmaker = bookmaker

    def _meaningful_tokens(label: str) -> set[str]:
        _noise = {"the", "and", "fc", "afc", "city", "united"}
        return {
            t.lower() for t in label.replace("&", " ").split()
            if len(t) >= 4 and t.lower() not in _noise
        }

    def _recommendation_phrase(text: str, odds_str: str) -> str:
        """Extract substring from start of verdict up to and including the
        bookmaker mention adjacent to the recommended odds.

        The recommendation always has the shape ``<TEAM> ... at <ODDS> ...
        with <BOOKMAKER>``. We capture from a wide left edge (last sentence
        boundary before the odds) through the bookmaker word to grab the
        adjacent team mention without grabbing setup-paragraph references.
        """
        import re as _re
        odds_idx = text.find(odds_str)
        if odds_idx < 0:
            return ""
        # Left bound: previous sentence boundary (".", "!", "?", "—", ":")
        left = max(
            text.rfind(p, 0, odds_idx) for p in (". ", "! ", "? ", " — ", ": ")
        )
        if left < 0:
            left = 0
        # Right bound: end of the bookmaker reference. Find " with " then the
        # following word, OR fall back to next sentence stop.
        right_search = text[odds_idx:]
        m = _re.search(r"(?:with|@)\s+\S+", right_search, _re.IGNORECASE)
        if m:
            right = odds_idx + m.end()
        else:
            stop = next(
                (text.find(p, odds_idx) for p in (".", "!", "?", "—", ":")
                 if text.find(p, odds_idx) > 0),
                len(text),
            )
            right = stop if stop > 0 else len(text)
        return text[left:right]

    verdict_lc = verdict.lower()
    rec_phrase = _recommendation_phrase(verdict, card_odds).lower()
    assert rec_phrase, (
        f"no recommendation phrase containing odds '{card_odds}' in verdict "
        f"for {match_key}: {verdict}"
    )

    pick_tokens = _meaningful_tokens(outcome_label)
    other_tokens = _meaningful_tokens(other_team)
    pick_tokens -= other_tokens
    other_tokens -= _meaningful_tokens(outcome_label)

    assert pick_tokens, (
        f"no meaningful tokens for outcome_label '{outcome_label}'; "
        "test setup error"
    )
    assert any(tok in rec_phrase for tok in pick_tokens), (
        f"recommendation phrase missing any token of outcome team "
        f"'{outcome_label}' (tokens={sorted(pick_tokens)}, "
        f"phrase='{rec_phrase}') for {match_key}: {verdict}"
    )
    if other_tokens:
        # Cross-team leak in the recommendation phrase IS the failure mode
        # QA captured. (The setup paragraph may mention both teams in
        # context — that's acceptable narrative; only the recommendation
        # phrase must align.)
        assert not any(tok in rec_phrase for tok in other_tokens), (
            f"recommendation phrase references OPPOSING team tokens "
            f"{sorted(other_tokens)} for {match_key}; "
            f"card recommends '{outcome_label}'. Phrase: '{rec_phrase}'"
        )
    assert card_odds in verdict, (
        f"verdict missing odds '{card_odds}' for {match_key}: {verdict}"
    )
    assert card_bookmaker.lower() in verdict_lc, (
        f"verdict missing bookmaker '{card_bookmaker}' for {match_key}: {verdict}"
    )


def test_outcome_flip_emits_aligned_verdict():
    """Flipping the tip's outcome flips the verdict's referenced team."""
    from narrative_spec import build_narrative_spec, _render_verdict

    base = _build_synthetic_tip(
        "brentford_vs_west_ham_2026-05-02", "gold", "home", "Brentford",
        1.93, "PlayaBets", 2.7, "soccer",
    )
    flipped = _build_synthetic_tip(
        "brentford_vs_west_ham_2026-05-02", "silver", "away", "West Ham",
        3.87, "PlayaBets", 4.49, "soccer",
    )

    def _ed(t, oc):
        return {
            "home_team": t["home_team"], "away_team": t["away_team"],
            "league": t["league"], "best_bookmaker": t["bookmaker"],
            "best_odds": t["odds"], "edge_pct": t["ev"], "outcome": oc,
            "outcome_team": t["outcome_label"],
            "confirming_signals": t["edge_v2"]["confirming_signals"],
            "contradicting_signals": 0,
            "composite_score": t["edge_v2"]["composite_score"],
            "fair_prob": t["edge_v2"]["fair_probability"],
            "edge_tier": t["edge_tier"],
        }

    base_spec = build_narrative_spec({}, _ed(base, "home"), [base], "soccer")
    base_verdict = _render_verdict(base_spec)
    flipped_spec = build_narrative_spec({}, _ed(flipped, "away"), [flipped], "soccer")
    flipped_verdict = _render_verdict(flipped_spec)

    # Setup paragraph may reference both teams in context; only the
    # recommendation phrase (right around the odds) must align with the
    # pick. 25-char window captures "<TEAM> win at <ODDS> with <BK>" but
    # excludes the setup paragraph that introduces both sides.
    def _window(text: str, anchor: str, before: int = 25, after: int = 30) -> str:
        idx = text.find(anchor)
        return text[max(0, idx - before): idx + after].lower()

    base_phrase = _window(base_verdict, "1.93")
    flip_phrase = _window(flipped_verdict, "3.87")

    assert "brentford" in base_phrase
    assert "west ham" not in base_phrase
    assert "west ham" in flip_phrase
    assert "brentford" not in flip_phrase


def test_bookmaker_drift_emits_aligned_verdict():
    """Changing only the tip's bookmaker propagates to verdict text."""
    from narrative_spec import build_narrative_spec, _render_verdict

    tip_a = _build_synthetic_tip(
        "arsenal_vs_fulham_2026-05-02", "gold", "home", "Arsenal",
        1.51, "SuperSportBet", 2.7, "soccer",
    )
    tip_b = _build_synthetic_tip(
        "arsenal_vs_fulham_2026-05-02", "gold", "home", "Arsenal",
        1.51, "PlayaBets", 2.7, "soccer",
    )

    def _ed(t):
        return {
            "home_team": t["home_team"], "away_team": t["away_team"],
            "league": t["league"], "best_bookmaker": t["bookmaker"],
            "best_odds": t["odds"], "edge_pct": t["ev"], "outcome": "home",
            "outcome_team": t["outcome_label"],
            "confirming_signals": t["edge_v2"]["confirming_signals"],
            "contradicting_signals": 0,
            "composite_score": t["edge_v2"]["composite_score"],
            "fair_prob": t["edge_v2"]["fair_probability"],
            "edge_tier": t["edge_tier"],
        }

    v_a = _render_verdict(build_narrative_spec({}, _ed(tip_a), [tip_a], "soccer"))
    v_b = _render_verdict(build_narrative_spec({}, _ed(tip_b), [tip_b], "soccer"))

    assert "supersportbet" in v_a.lower()
    assert "playabets" not in v_a.lower()
    assert "playabets" in v_b.lower()
    assert "supersportbet" not in v_b.lower()


def test_qa03_arsenal_atletico_bookmaker_pinned_to_edge_results() -> None:
    """Regression: verdict cites edge_results.bookmaker, not latest odds book."""
    from narrative_spec import build_narrative_spec, _render_verdict

    tip = _build_synthetic_tip(
        "arsenal_vs_atletico_madrid_2026-05-05",
        "bronze",
        "home",
        "Arsenal",
        1.66,
        "PlayaBets",
        1.2,
        "soccer",
    )
    edge_data = {
        "home_team": "Arsenal",
        "away_team": "Atletico Madrid",
        "league": "champions_league",
        "best_bookmaker": "SuperSportBet",
        "best_odds": 1.66,
        "edge_pct": 1.2,
        "outcome": "home",
        "outcome_team": "Arsenal",
        "confirming_signals": 1,
        "contradicting_signals": 0,
        "composite_score": 53.6,
        "fair_prob": (1 + 1.2 / 100.0) / 1.66,
        "edge_tier": "bronze",
    }

    spec = build_narrative_spec({}, edge_data, [tip], "soccer")
    verdict = _render_verdict(spec)
    assert spec.bookmaker.lower() == "supersportbet"
    assert "supersportbet" in verdict.lower(), verdict
    assert "playabets" not in verdict.lower(), verdict


@pytest.mark.parametrize(
    "tier,sport,home,away,bookmaker,odds",
    _BOOKMAKER_SWEEP_CASES,
    ids=[
        f"{tier}-{sport}-{bookmaker}"
        for tier, sport, _home, _away, bookmaker, _odds in _BOOKMAKER_SWEEP_CASES
    ],
)
def test_10_fixture_bookmaker_sweep_uses_edge_results_bookmaker(
    tier: str,
    sport: str,
    home: str,
    away: str,
    bookmaker: str,
    odds: float,
) -> None:
    from narrative_spec import build_narrative_spec, _render_verdict

    composite = {
        "diamond": 92.0,
        "gold": 78.0,
        "silver": 65.0,
        "bronze": 50.0,
    }[tier]
    support = 4 if tier == "diamond" else 3
    edge_data = {
        "home_team": home,
        "away_team": away,
        "league": "epl" if sport == "soccer" else ("urc" if sport == "rugby" else "ipl"),
        "best_bookmaker": bookmaker,
        "best_odds": odds,
        "edge_pct": 3.0,
        "outcome": "home",
        "outcome_team": home,
        "confirming_signals": support,
        "contradicting_signals": 0,
        "composite_score": composite,
        "fair_prob": (1 + 3.0 / 100.0) / odds,
        "edge_tier": tier,
    }
    tip = {
        "match_key": f"{home.lower().replace(' ', '_')}_vs_{away.lower().replace(' ', '_')}_2026-05-05",
        "home_team": home,
        "away_team": away,
        "outcome": home,
        "outcome_key": "home",
        "odds": odds,
        "bookmaker": bookmaker,
        "recommended_odds": odds,
        "recommended_bookmaker": bookmaker,
        "ev": 3.0,
        "display_tier": tier,
        "sport_key": sport,
    }

    spec = build_narrative_spec({}, edge_data, [tip], sport)
    verdict = _render_verdict(spec)
    assert spec.bookmaker.lower() == bookmaker.lower()
    assert bookmaker.lower() in verdict.lower(), verdict


def test_odds_drift_emits_aligned_verdict():
    """Changing the tip's odds propagates to verdict text."""
    from narrative_spec import build_narrative_spec, _render_verdict

    tip_a = _build_synthetic_tip(
        "chelsea_vs_nottingham_forest_2026-05-04", "silver", "home", "Chelsea",
        1.73, "PlayaBets", 3.6, "soccer",
    )
    tip_b = _build_synthetic_tip(
        "chelsea_vs_nottingham_forest_2026-05-04", "silver", "home", "Chelsea",
        1.75, "HWB", 3.4, "soccer",
    )

    def _ed(t):
        return {
            "home_team": t["home_team"], "away_team": t["away_team"],
            "league": t["league"], "best_bookmaker": t["bookmaker"],
            "best_odds": t["odds"], "edge_pct": t["ev"], "outcome": "home",
            "outcome_team": t["outcome_label"],
            "confirming_signals": t["edge_v2"]["confirming_signals"],
            "contradicting_signals": 0,
            "composite_score": t["edge_v2"]["composite_score"],
            "fair_prob": t["edge_v2"]["fair_probability"],
            "edge_tier": t["edge_tier"],
        }

    v_a = _render_verdict(build_narrative_spec({}, _ed(tip_a), [tip_a], "soccer"))
    v_b = _render_verdict(build_narrative_spec({}, _ed(tip_b), [tip_b], "soccer"))

    assert "1.73" in v_a
    assert "1.75" in v_b
    assert "1.75" not in v_a
    assert "1.73" not in v_b


def test_enrich_tip_for_card_fallback_does_not_reuse_stale_cache_text():
    """Source-level guard: the buggy fallback chain is gone.

    Pre-fix, ``bot.py`` lines 9128-9137 contained a fallback that re-served
    ``_cached_verdict.get('verdict_html')`` whenever the staleness check
    fired (``_use_cached_verdict = False``). That fallback caused the 8/25
    QA-LIVE-CARDS-EVERY-ACTIVE-01 failures: the card image rebuilt from
    fresh edge_results data, but the verdict text stayed stale.

    This test asserts the ``_cv_fb`` fallback assignment is no longer
    present in ``_enrich_tip_for_card`` so the regression cannot return
    via a copy-paste regression.
    """
    bot_py = (_ROOT / "bot.py").read_text(encoding="utf-8")
    # Locate the verdict-resolution block by its docstring marker.
    # Pre-fix the fallback was:  enriched["verdict"] = _cv_fb
    # Post-fix the fallback path goes through build_narrative_spec.
    # Find the section between "Try cached verdict from narrative_cache"
    # and "Top tipsters" markers.
    start = bot_py.find("# 10) Verdict — PIPELINE-BUILD-01")
    end = bot_py.find("# 11) Top tipsters", start) if start >= 0 else -1
    assert start >= 0 and end > start, "verdict-resolution block not found in bot.py"
    block = bot_py[start:end]
    assert "_cv_fb" not in block, (
        "FIX-CARD-VERDICT-RECOMMENDATION-ALIGNMENT-01 regression: "
        "the stale-cache fallback (`_cv_fb`) is back in _enrich_tip_for_card. "
        "The fallback re-served stale narrative_cache.verdict_html when the "
        "card image was rendering from a newer edge_results row, causing "
        "8/25 QA-LIVE-CARDS-EVERY-ACTIVE-01 failures. Regenerate via "
        "build_narrative_spec(...) → _render_verdict(...) instead."
    )
    # Also assert the new path is present.
    assert "FIX-CARD-VERDICT-RECOMMENDATION-ALIGNMENT-01" in block
    assert "build_narrative_spec" in block
    assert "_render_verdict" in block


def test_multibookmaker_enrichment_does_not_rewrite_verdict_source_fields() -> None:
    """Source guard: odds_snapshots enrichment must not overwrite edge_results recommendation."""
    bot_py = (_ROOT / "bot.py").read_text(encoding="utf-8")
    start = bot_py.find("# R10-BUILD-01: Multi-BK enrichment")
    end = bot_py.find("# AC-8: Optionally attach CLV", start) if start >= 0 else -1
    assert start >= 0 and end > start, "multi-bookmaker enrichment block not found"
    block = bot_py[start:end]
    assert 'tips[-1]["bookmaker"] =' not in block
    assert 'tips[-1]["bookmaker_key"] =' not in block
    assert 'tips[-1]["odds"] =' not in block
    assert "best_available_bookmaker" in block


def test_pregen_refresh_skips_positive_edge_results_rows_source_guard() -> None:
    pregen_py = (_ROOT / "scripts" / "pregenerate_narratives.py").read_text(encoding="utf-8")
    start = pregen_py.find("async def _refresh_edge_from_odds_db")
    end = pregen_py.find("match_key = edge.get", start) if start >= 0 else -1
    assert start >= 0 and end > start, "_refresh_edge_from_odds_db guard block not found"
    guard = pregen_py[start:end]
    assert "FIX-VERDICT-CORPUS-ARCHITECTURE-HARDENING-01" in guard
    assert 'not edge.get("is_non_edge", False)' in guard
    assert 'edge.get("best_bookmaker")' in guard
    assert 'edge.get("best_odds")' in guard
    assert "return edge" in guard
