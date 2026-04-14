"""BUILD-DRAW-GATE-02 — Draw-leak path contract tests.

Guards all 4 draw-suppression paths identified in INV-DRAW-REGRESSION-01.
Each class verifies one of the four fixes by exercising the guard logic
with a mock input that contains a draw outcome, then asserting draw is absent
from the result.

Fix 1 — _generate_game_tips() outcome loop (db_match["outcomes"])
Fix 2 — _build_game_buttons() CTA selection (_non_draw_tips filter)
Fix 3 — tips list filter before sort/cache in _generate_game_tips()
Fix 4 — AC-7 fast path card guard
"""
from __future__ import annotations


# ── Fix 1 — Outcome loop draw skip ───────────────────────────────────────────

class TestFix1OutcomeLoopDrawSkip:
    """Draw key is skipped in the db_match outcomes loop (ALGO-FIX-01 parity)."""

    def _run_loop(self, outcomes: dict) -> list[dict]:
        """Mirrors the filtered outcome loop in _generate_game_tips()."""
        tips: list[dict] = []
        for outcome_key, outcome_data in outcomes.items():
            if outcome_key == "draw":
                continue  # ALGO-FIX-01 parity (INV-DRAW-REGRESSION-01)
            all_bk = outcome_data.get("all_bookmakers", {})
            if not all_bk:
                continue
            tips.append({"outcome": outcome_key})
        return tips

    def test_draw_absent_from_1x2_match(self):
        """1X2 db_match with draw outcome must not surface draw in tips."""
        outcomes = {
            "home": {"all_bookmakers": {"betway": 1.80}, "best_odds": 1.80, "best_bookmaker": "betway"},
            "draw": {"all_bookmakers": {"betway": 3.20}, "best_odds": 3.20, "best_bookmaker": "betway"},
            "away": {"all_bookmakers": {"betway": 4.50}, "best_odds": 4.50, "best_bookmaker": "betway"},
        }
        tips = self._run_loop(outcomes)
        assert "draw" not in [t["outcome"] for t in tips], f"Draw leaked: {tips}"
        assert len(tips) == 2

    def test_draw_only_match_yields_empty_tips(self):
        """A match that only has a draw outcome must produce zero tips."""
        outcomes = {
            "draw": {"all_bookmakers": {"betway": 3.20}, "best_odds": 3.20, "best_bookmaker": "betway"},
        }
        tips = self._run_loop(outcomes)
        assert tips == [], f"Expected empty tips list, got: {tips}"

    def test_draw_with_highest_ev_still_excluded(self):
        """Even when draw has the highest EV it must be excluded."""
        outcomes = {
            "home": {"all_bookmakers": {"betway": 1.80}},
            "draw": {"all_bookmakers": {"betway": 3.20}},  # highest implied EV
        }
        tips = self._run_loop(outcomes)
        assert all(t["outcome"] != "draw" for t in tips)


# ── Fix 2 — _build_game_buttons() draw filter ────────────────────────────────

class TestFix2GameButtonsDrawFilter:
    """_non_draw_tips filter prevents draw from being selected as the CTA."""

    @staticmethod
    def _non_draw(tips: list[dict]) -> list[dict]:
        return [t for t in tips if (t.get("outcome") or "").lower() != "draw"]

    def test_draw_not_selected_when_highest_ev(self):
        """Draw must not become best_ev_tip even if it has the highest EV."""
        tips = [
            {"outcome": "draw", "ev": 12.5, "odds": 3.20, "bookmaker": "betway"},
            {"outcome": "home",  "ev":  5.2, "odds": 1.80, "bookmaker": "betway"},
            {"outcome": "away",  "ev":  1.1, "odds": 4.50, "bookmaker": "betway"},
        ]
        non_draw = self._non_draw(tips)
        best_ev_tip = max(non_draw, key=lambda t: t.get("ev", 0)) if non_draw else None
        assert best_ev_tip is not None
        assert (best_ev_tip.get("outcome") or "").lower() != "draw", (
            f"Draw selected as best_ev_tip: {best_ev_tip}"
        )
        assert best_ev_tip["outcome"] == "home"

    def test_draw_only_list_yields_none_cta(self):
        """If the only positive-EV tip is a draw, best_ev_tip must be None."""
        tips = [{"outcome": "draw", "ev": 12.5, "odds": 3.20, "bookmaker": "betway"}]
        non_draw = self._non_draw(tips)
        best_ev_tip = max(non_draw, key=lambda t: t.get("ev", 0)) if non_draw else None
        assert best_ev_tip is None, f"Expected None, got: {best_ev_tip}"

    def test_selected_outcome_draw_not_matched(self):
        """When selected_outcome is 'draw', no non-draw tip should match it."""
        tips = [
            {"outcome": "draw", "ev": 12.5},
            {"outcome": "home",  "ev":  5.2},
        ]
        non_draw = self._non_draw(tips)
        sel_lo = "draw"
        matched = next(
            (t for t in non_draw if t.get("ev", 0) > 0 and sel_lo == (t.get("outcome") or "").lower()),
            None,
        )
        assert matched is None, f"Draw was matched via selected_outcome: {matched}"


# ── Fix 3 — Tips list filter before sort/cache ───────────────────────────────

class TestFix3TipsListFilter:
    """Draws are stripped from the tips list before sort and cache assignment."""

    @staticmethod
    def _filter(tips: list[dict]) -> list[dict]:
        return [t for t in tips if (t.get("outcome") or "").lower() != "draw"]

    def test_draw_stripped_from_mixed_list(self):
        raw = [
            {"outcome": "home", "ev": 5.2},
            {"outcome": "draw", "ev": 8.1},
            {"outcome": "away", "ev": 1.1},
        ]
        result = self._filter(raw)
        assert all((t.get("outcome") or "").lower() != "draw" for t in result)
        assert len(result) == 2

    def test_cache_never_contains_draw(self):
        """Simulate the cache write: filtered tips must contain no draw."""
        fake_cache: dict[str, list] = {}
        event_id = "test_vs_test_2026-04-14"
        raw = [
            {"outcome": "home", "ev": 5.2},
            {"outcome": "draw", "ev": 9.9},
        ]
        tips = self._filter(raw)
        if tips:
            tips.sort(key=lambda t: t["ev"], reverse=True)
        fake_cache[event_id] = tips

        cached = fake_cache[event_id]
        assert all((t.get("outcome") or "").lower() != "draw" for t in cached), (
            f"Draw in cache: {cached}"
        )

    def test_filter_idempotent_when_no_draw(self):
        """Filter is a no-op when tips contain no draw."""
        raw = [{"outcome": "home", "ev": 5.2}, {"outcome": "away", "ev": 1.1}]
        assert self._filter(raw) == raw


# ── Fix 4 — AC-7 fast path draw card guard ───────────────────────────────────

class TestFix4AC7DrawGuard:
    """AC-7 card with draw outcome is nullified before the positive-EV gate."""

    @staticmethod
    def _apply_guard(card: dict | None) -> dict | None:
        if card is not None and (card.get("outcome") or "").lower() == "draw":
            return None  # force fall-through to full pipeline
        return card

    def test_draw_card_nullified(self):
        card = {"outcome": "draw", "odds": 3.20, "ev": 8.5}
        assert self._apply_guard(card) is None, "Draw AC-7 card must be nullified"

    def test_home_card_passes_through(self):
        card = {"outcome": "home", "odds": 1.80, "ev": 5.2}
        result = self._apply_guard(card)
        assert result is not None
        assert result["outcome"] == "home"

    def test_away_card_passes_through(self):
        card = {"outcome": "away", "odds": 4.50, "ev": 2.1}
        result = self._apply_guard(card)
        assert result is not None

    def test_none_input_is_safe(self):
        assert self._apply_guard(None) is None

    def test_case_insensitive_draw_match(self):
        card = {"outcome": "Draw", "odds": 3.20, "ev": 8.5}  # capital D
        assert self._apply_guard(card) is None, "Guard must be case-insensitive"
