"""FIX-CARD-SURFACE-TIER-CAP-REASON-01 — card-side regression guard.

AC-6: uncapped edges (no cap fired) MUST NOT carry irrelevant cap text on the
card. Capped edges MUST surface the structural reason verbatim.

AC-9: no regression on uncapped Edges — Diamond/Gold cards remain clean.
"""
from card_data import build_edge_detail_data, _resolve_cap_reason


# ── _resolve_cap_reason() unit coverage ─────────────────────────────────────

class TestResolveCapReason:
    def test_super_rugby_silver_returns_reason(self):
        tip = {"league_key": "super_rugby"}
        reason = _resolve_cap_reason(tip, "silver")
        assert reason
        assert "Super Rugby" in reason
        assert "Capped at Silver" in reason

    def test_super_rugby_silver_via_league_field(self):
        # Tip path may set "league" instead of "league_key" — both must work.
        tip = {"league": "super_rugby"}
        reason = _resolve_cap_reason(tip, "silver")
        assert reason
        assert "Super Rugby" in reason

    def test_currie_cup_silver_returns_reason(self):
        tip = {"league_key": "currie_cup"}
        reason = _resolve_cap_reason(tip, "silver")
        assert reason
        assert "SA-domestic" in reason

    def test_super_rugby_bronze_returns_empty(self):
        # bronze BELOW the cap — no cap text on a card that wasn't capped.
        assert _resolve_cap_reason({"league_key": "super_rugby"}, "bronze") == ""

    def test_super_rugby_gold_returns_empty(self):
        # gold ABOVE the cap — defensive; cap-reason MUST NOT mislabel.
        assert _resolve_cap_reason({"league_key": "super_rugby"}, "gold") == ""

    def test_uncapped_league_returns_empty(self):
        for lg in ("epl", "ipl", "champions_league", "psl", "super_rugby_aus"):
            for tier in ("bronze", "silver", "gold", "diamond"):
                assert _resolve_cap_reason({"league_key": lg}, tier) == "", (
                    f"{lg}/{tier} surfaced cap text but is not in LEAGUE_TIER_CAP"
                )

    def test_no_tier_returns_empty(self):
        assert _resolve_cap_reason({"league_key": "super_rugby"}, None) == ""
        assert _resolve_cap_reason({"league_key": "super_rugby"}, "") == ""

    def test_no_league_returns_empty(self):
        assert _resolve_cap_reason({}, "silver") == ""
        assert _resolve_cap_reason({"league_key": ""}, "silver") == ""

    def test_league_normalises_case_and_spaces(self):
        # Display strings ("Super Rugby", "Currie Cup") MUST normalise to the
        # league_key form before lookup.
        assert _resolve_cap_reason({"league": "Super Rugby"}, "silver")
        assert _resolve_cap_reason({"league": "CURRIE_CUP"}, "silver")


# ── build_edge_detail_data() integration ────────────────────────────────────

class TestBuildEdgeDetailData:
    def _base_tip(self, **overrides):
        tip = {
            "home": "Blues",
            "away": "Reds",
            "league_key": "super_rugby",
            "league_display": "Super Rugby",
            "edge_tier": "silver",
            "ev": 7.3,
            "pick_odds": 1.85,
            "bookmaker": "SuperSportBet",
            "verdict": "Blues to win — Reds wobbling.",
        }
        tip.update(overrides)
        return tip

    def test_super_rugby_silver_card_carries_cap_reason(self):
        # AC-2: capped edge surfaces the cap reason on the card data dict
        data = build_edge_detail_data(self._base_tip())
        assert data["cap_reason"]
        assert "Super Rugby" in data["cap_reason"]
        assert "Capped at Silver" in data["cap_reason"]

    def test_super_rugby_bronze_card_no_cap_reason(self):
        # AC-6: bronze Super Rugby was not capped — cap_reason MUST be empty
        data = build_edge_detail_data(self._base_tip(edge_tier="bronze"))
        assert data["cap_reason"] == ""

    def test_epl_gold_card_no_cap_reason(self):
        # AC-9: uncapped Gold/Diamond stays clean
        data = build_edge_detail_data(self._base_tip(
            league_key="epl", league_display="Premier League", edge_tier="gold"
        ))
        assert data["cap_reason"] == ""

    def test_currie_cup_silver_carries_cap_reason(self):
        data = build_edge_detail_data(self._base_tip(
            league_key="currie_cup", edge_tier="silver"
        ))
        assert data["cap_reason"]
        assert "SA-domestic" in data["cap_reason"]

    def test_no_tier_card_has_empty_cap_reason(self):
        # No-edge cards (display_tier=None path): cap_reason key still present, empty
        tip = self._base_tip()
        tip.pop("edge_tier", None)
        data = build_edge_detail_data(tip)
        assert "cap_reason" in data
        assert data["cap_reason"] == ""
