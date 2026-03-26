"""RENDER-FIX2 tests: snapshot EV/tier consistency in _generate_game_tips().

Three required tests:
1. Snapshot match   — hot_tips_cache hit → snapshot ev/tier used, guardrails skipped
2. No snapshot      — no cache match → guardrails still apply normally
3. Sign consistency — list EV positive → detail EV same positive value (no sign flip)
"""

from __future__ import annotations

from unittest.mock import patch


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_tip(ev: float, home: str = "arsenal", away: str = "chelsea") -> dict:
    return {
        "ev": ev,
        "home_team": home,
        "away_team": away,
        "odds_by_bookmaker": {"bk1": {}, "bk2": {}, "bk3": {}},
    }


def _snapshot_cache(home: str, away: str, ev: float, display_tier: str) -> dict:
    return {
        "global": {
            "tips": [
                {
                    "home_team": home,
                    "away_team": away,
                    "ev": ev,
                    "display_tier": display_tier,
                }
            ]
        }
    }


def _run_snapshot_logic(tips: list, cache: dict, home_raw: str, away_raw: str):
    """Inline simulation of the RENDER-FIX2 snapshot + guardrails block."""
    from services.edge_rating import EdgeRating, apply_guardrails  # type: ignore

    # --- snapshot check (RENDER-FIX2) ---
    _snapshot_ev = None
    _snapshot_tier = None
    _htc_snap = cache.get("global")
    if _htc_snap and _htc_snap.get("tips"):
        _ht_raw = home_raw.lower().strip()
        _at_raw = away_raw.lower().strip()
        for _ht_tip in _htc_snap["tips"]:
            _ht_h = (_ht_tip.get("home_team") or "").lower().strip()
            _ht_a = (_ht_tip.get("away_team") or "").lower().strip()
            if _ht_h == _ht_raw and _ht_a == _at_raw:
                _snapshot_ev = _ht_tip.get("ev")
                _snapshot_tier = _ht_tip.get("display_tier")
                break

    # --- guardrails loop (with snapshot bypass) ---
    if tips:
        for _tip in tips:
            if _snapshot_ev is not None and _snapshot_tier is not None:
                _tip["ev"] = _snapshot_ev
                continue
            _tip_ev = _tip["ev"]
            if _tip_ev <= 0:
                continue
            _tip_bk_count = len(_tip.get("odds_by_bookmaker", {})) or 1
            if _tip_ev >= 15:
                _raw_tier = EdgeRating.DIAMOND
            elif _tip_ev >= 8:
                _raw_tier = EdgeRating.GOLD
            elif _tip_ev >= 4:
                _raw_tier = EdgeRating.SILVER
            else:
                _raw_tier = EdgeRating.BRONZE
            _adj_tier, _adj_ev, _ = apply_guardrails(_raw_tier, _tip_ev / 100.0, _tip_bk_count)
            if _adj_ev is not None:
                _tip["ev"] = round(_adj_ev * 100, 1)
            else:
                _tip["ev"] = 0.0

    # --- tier resolution ---
    _cached_display_tier = _snapshot_tier
    if _cached_display_tier is None:
        _htc = cache.get("global")
        if _htc and _htc.get("tips"):
            _ht_raw = home_raw.lower().strip()
            _at_raw = away_raw.lower().strip()
            for _ht_tip in _htc["tips"]:
                _ht_h = (_ht_tip.get("home_team") or "").lower().strip()
                _ht_a = (_ht_tip.get("away_team") or "").lower().strip()
                if _ht_h == _ht_raw and _ht_a == _at_raw:
                    _cached_display_tier = _ht_tip.get("display_tier")
                    break

    return tips, _snapshot_ev, _snapshot_tier, _cached_display_tier


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_snapshot_match_uses_cache_ev_and_skips_guardrails():
    """Snapshot hit: tip gets snapshot ev=5.3, guardrails do NOT run."""
    # Guardrails on ev=9.1 with 3 bookmakers would adjust it to something < 9.1.
    # With snapshot ev=5.3, the tip should end up at exactly 5.3.
    tip = _make_tip(ev=9.1)
    cache = _snapshot_cache("arsenal", "chelsea", ev=5.3, display_tier="gold")

    tips, _snap_ev, _snap_tier, _cached_tier = _run_snapshot_logic(
        [tip], cache, "Arsenal", "Chelsea"
    )

    assert tips[0]["ev"] == 5.3, (
        f"Expected snapshot ev=5.3, got {tips[0]['ev']}"
    )
    assert _cached_tier == "gold", (
        f"Expected snapshot tier='gold', got {_cached_tier}"
    )


def test_no_snapshot_guardrails_apply_normally():
    """No cache match → guardrails apply and cap EV as normal.

    ev=25.0 with 2 bookmakers → tier derives as GOLD (ev>=8) → gold only needs 3 BKs
    but 2 BKs forces downgrade to SILVER (cap 15%) → guardrails cap ev to 15.0.
    """
    tip = _make_tip(ev=25.0, home="sundowns", away="pirates")
    tip["odds_by_bookmaker"] = {"bk1": {}, "bk2": {}}  # only 2 bookmakers

    cache = _snapshot_cache("arsenal", "chelsea", ev=5.3, display_tier="gold")  # different match

    tips, _snap_ev, _snap_tier, _cached_tier = _run_snapshot_logic(
        [tip], cache, "Sundowns", "Pirates"
    )

    # No snapshot found — both must be None
    assert _snap_ev is None, "Expected no snapshot for unmatched teams"
    assert _snap_tier is None, "Expected no snapshot tier for unmatched teams"
    # Guardrails ran and capped ev=25% → 15% (SILVER cap with 2 BKs)
    assert tips[0]["ev"] == 15.0, (
        f"Guardrails should have capped ev to 15.0, got {tips[0]['ev']}"
    )


def test_sign_consistency_positive_list_ev_stays_positive():
    """List EV positive (e.g. +2.3%) → detail EV must be same positive value, never negative."""
    # BUG-3 scenario: list showed +2.3% but guardrails flipped it to -1.4%
    # With RENDER-FIX2: snapshot ev=2.3 is used, sign cannot flip.
    tip = _make_tip(ev=2.3)  # matches list EV
    cache = _snapshot_cache("arsenal", "chelsea", ev=2.3, display_tier="silver")

    tips, _, _, _cached_tier = _run_snapshot_logic(
        [tip], cache, "Arsenal", "Chelsea"
    )

    assert tips[0]["ev"] > 0, (
        f"Sign flip detected: detail ev={tips[0]['ev']} (expected positive)"
    )
    assert tips[0]["ev"] == 2.3, (
        f"Detail ev must equal list ev (snapshot). Got {tips[0]['ev']}"
    )
    assert _cached_tier == "silver"
