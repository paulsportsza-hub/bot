from __future__ import annotations

import os

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("ODDS_API_KEY", "test-odds-key")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-anthropic-key")
os.environ.setdefault("ADMIN_IDS", "123456")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")


def _sample_edge_v2() -> dict:
    return {
        "match_key": "arsenal_vs_chelsea_2026-03-17",
        "tier": "gold",
        "composite_score": 61.0,
        "confirming_signals": 4,
        "contradicting_signals": 1,
        "edge_pct": 4.2,
        "best_bookmaker": "hollywoodbets",
        "best_odds": 2.10,
        "signals": {
            "price_edge": {
                "available": True,
                "signal_strength": 0.84,
                "edge_pct": 4.2,
                "best_odds": 2.10,
                "best_bookmaker": "hollywoodbets",
                "sharp_source": "pinnacle",
            },
            "market_agreement": {
                "available": True,
                "signal_strength": 0.71,
                "agreeing_bookmakers": 4,
                "total_bookmakers": 6,
            },
            "movement": {
                "available": True,
                "signal_strength": 0.67,
                "movement_pct": 2.7,
                "steam_confirms": True,
                "n_bks_moving": 3,
            },
            "form_h2h": {
                "available": True,
                "signal_strength": 0.66,
                "home_form_string": "WWDLW",
                "away_form_string": "LDWWW",
            },
            "tipster": {
                "available": True,
                "signal_strength": 0.31,
                "n_sources": 2,
                "total_sources": 4,
                "agrees_with_edge": False,
            },
            "lineup_injury": {
                "available": True,
                "signal_strength": 0.58,
                "home_injuries": 1,
                "away_injuries": 3,
            },
        },
    }


class TestSignalDetailBlock:
    def test_gold_gets_full_breakdown(self):
        from bot import _build_signal_detail_block

        text = _build_signal_detail_block(
            _sample_edge_v2(),
            user_tier="gold",
            edge_tier="gold",
            access_level="full",
            home_team="Arsenal",
            away_team="Chelsea",
        )

        assert "Signal Breakdown" in text
        assert "4/6 aligned" in text
        assert "Price edge" in text
        assert "▰" in text
        assert "Arsenal WWDLW" in text

    def test_bronze_gets_summary_only(self):
        from bot import _build_signal_detail_block

        text = _build_signal_detail_block(
            _sample_edge_v2(),
            user_tier="bronze",
            edge_tier="silver",
            access_level="partial",
            home_team="Arsenal",
            away_team="Chelsea",
        )

        assert "Signal Snapshot" in text
        assert "Best support" in text
        assert "Price edge" not in text
        assert "▰" not in text

    def test_locked_state_gets_teaser_only(self):
        from bot import _build_signal_detail_block

        text = _build_signal_detail_block(
            _sample_edge_v2(),
            user_tier="bronze",
            edge_tier="gold",
            access_level="locked",
            home_team="Arsenal",
            away_team="Chelsea",
        )

        assert "Signal Preview" in text
        assert "checks sit behind this premium edge" in text
        assert "Unlock to see which signals aligned" in text
        assert "Price edge" not in text
        assert "4/7 aligned" not in text


class TestSignalCountHint:
    def test_hint_uses_confirming_and_total(self):
        from bot import _format_signal_count_hint

        assert _format_signal_count_hint(4, 6) == "4/6 signals aligned"

    def test_hint_hides_zero_confirming_edges(self):
        from bot import _format_signal_count_hint

        assert _format_signal_count_hint(0, 3) == ""

    def test_model_only_hint_degrades_gracefully(self):
        from bot import _format_signal_count_hint

        assert _format_signal_count_hint(0, 0, True) == "model-only signal view"
