"""Text golden snapshots for page templates, card states, and helper renders."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

from .conftest import assert_snapshot, serialize_snapshot
from .fixtures import make_edge_tracker_summary, make_settled_edge, make_tip, sample_tips

_BROADCAST_PATCH = patch(
    "bot._get_broadcast_details",
    return_value={"broadcast": "", "kickoff": "Sat 10 Mar · 17:30"},
)
_PORTFOLIO_PATCH = patch(
    "bot._get_portfolio_line",
    return_value="📈 <b>R100 on our top 5</b> → R487 total return",
)
_FOUNDING_PATCH = patch("bot._founding_days_left", return_value=8)
_TIER_GATE_FOUNDING_PATCH = patch(
    "tier_gate._founding_member_line",
    return_value="\n🎁 Founding Member: R699/yr Diamond — 8 days left",
)


def _snapshot_page(name: str, update_snapshots: bool, **kwargs) -> None:
    with _BROADCAST_PATCH, _PORTFOLIO_PATCH, _FOUNDING_PATCH:
        from bot import _build_hot_tips_page

        text, markup = asyncio.run(_build_hot_tips_page(**kwargs))
    assert_snapshot(name, serialize_snapshot(text, markup), update_snapshots)


class TestHotTipsPageSnapshots:
    def test_header_above_threshold(self, update_snapshots):
        _snapshot_page(
            "page_header_above_threshold",
            update_snapshots,
            tips=sample_tips()[:4],
            page=0,
            user_tier="diamond",
            hit_rate_7d=62.0,
            resource_count=347043,
        )

    def test_header_below_threshold(self, update_snapshots):
        _snapshot_page(
            "page_header_below_threshold",
            update_snapshots,
            tips=sample_tips()[:4],
            page=0,
            user_tier="diamond",
            hit_rate_7d=38.0,
            resource_count=347043,
        )

    def test_result_proof_page(self, update_snapshots):
        _snapshot_page(
            "page_result_proof",
            update_snapshots,
            tips=sample_tips()[:4],
            page=0,
            user_tier="diamond",
            hit_rate_7d=38.0,
            resource_count=347043,
            last_10_results=["hit", "miss", "hit", "hit", "miss", "hit", "miss", "hit", "hit", "miss"],
            roi_7d=-4.2,
            edge_tracker_summary={"total": 60, "hits": 36, "hit_rate_pct": 60.0, "roi": -4.2},
            recently_settled=[
                make_settled_edge("kaizer_chiefs_vs_orlando_pirates_2026-03-13"),
                make_settled_edge(
                    "mamelodi_sundowns_vs_cape_town_city_2026-03-13",
                    result="miss",
                    edge_tier="bronze",
                    bet_type="Away Win",
                    recommended_odds=1.80,
                    actual_return=0.0,
                ),
            ],
            yesterday_results=[
                make_settled_edge("kaizer_chiefs_vs_orlando_pirates_2026-03-13"),
                make_settled_edge(
                    "mamelodi_sundowns_vs_cape_town_city_2026-03-13",
                    result="miss",
                    edge_tier="bronze",
                    bet_type="Away Win",
                    recommended_odds=1.80,
                    actual_return=0.0,
                ),
            ],
        )

    def test_thin_slate_empty(self, update_snapshots):
        _snapshot_page(
            "page_thin_slate_empty",
            update_snapshots,
            tips=[],
            page=0,
            user_tier="diamond",
        )

    def test_thin_slate_watchlist(self, update_snapshots):
        _snapshot_page(
            "page_thin_slate_watchlist",
            update_snapshots,
            tips=[],
            page=0,
            user_tier="diamond",
            thin_slate_mode="below_threshold",
            thin_slate_weaker_tip=make_tip(
                home="Kaizer Chiefs",
                away="Cape Town City",
                outcome="Chiefs",
                odds=2.45,
                ev=1.8,
                display_tier="bronze",
                edge_score=22.0,
                match_id="chiefs_vs_cape_town_city_2026-03-11",
            ),
            thin_slate_fixtures=[
                {
                    "sport_key": "soccer_epl",
                    "home_team": "Arsenal",
                    "away_team": "Spurs",
                    "commence_time": "2026-03-11T18:30:00Z",
                },
                {
                    "sport_key": "rugby_urc",
                    "home_team": "Sharks",
                    "away_team": "Lions",
                    "commence_time": "2026-03-11T16:00:00Z",
                },
            ],
        )

    def test_bronze_full_access_card(self, update_snapshots):
        _snapshot_page(
            "card_bronze_full_access",
            update_snapshots,
            tips=[make_tip(display_tier="bronze", edge_score=22.0)],
            page=0,
            user_tier="bronze",
            resource_count=100000,
        )

    def test_bronze_partial_access_card(self, update_snapshots):
        _snapshot_page(
            "card_bronze_partial_access",
            update_snapshots,
            tips=[make_tip(display_tier="silver", edge_score=39.0)],
            page=0,
            user_tier="bronze",
            resource_count=100000,
        )

    def test_bronze_blurred_access_card(self, update_snapshots):
        _snapshot_page(
            "card_bronze_blurred_access",
            update_snapshots,
            tips=[make_tip(display_tier="gold", edge_score=46.0)],
            page=0,
            user_tier="bronze",
            resource_count=100000,
        )

    def test_bronze_locked_access_card(self, update_snapshots):
        _snapshot_page(
            "card_bronze_locked_access",
            update_snapshots,
            tips=[make_tip(display_tier="diamond", edge_score=62.0)],
            page=0,
            user_tier="bronze",
            resource_count=100000,
        )

    def test_gold_blurred_diamond_card(self, update_snapshots):
        _snapshot_page(
            "card_gold_blurred_diamond",
            update_snapshots,
            tips=[make_tip(display_tier="diamond", edge_score=62.0)],
            page=0,
            user_tier="gold",
            resource_count=100000,
        )

    def test_bronze_footer_with_locks(self, update_snapshots):
        _snapshot_page(
            "footer_bronze_with_locks",
            update_snapshots,
            tips=sample_tips()[:4],
            page=0,
            user_tier="bronze",
            consecutive_misses=0,
            hit_rate_7d=55.0,
            resource_count=347043,
            edge_tracker_summary=make_edge_tracker_summary(),
        )

    def test_bronze_footer_losing_streak(self, update_snapshots):
        _snapshot_page(
            "footer_bronze_losing_streak",
            update_snapshots,
            tips=sample_tips()[:4],
            page=0,
            user_tier="bronze",
            consecutive_misses=4,
            hit_rate_7d=55.0,
            resource_count=347043,
        )

    def test_gold_footer_with_diamond_locked(self, update_snapshots):
        _snapshot_page(
            "footer_gold_diamond_locked",
            update_snapshots,
            tips=sample_tips()[:4],
            page=0,
            user_tier="gold",
            hit_rate_7d=55.0,
            resource_count=347043,
        )

    def test_diamond_page_no_footer(self, update_snapshots):
        _snapshot_page(
            "footer_diamond_none",
            update_snapshots,
            tips=sample_tips()[:4],
            page=0,
            user_tier="diamond",
            hit_rate_7d=55.0,
            resource_count=347043,
        )


class TestHelperSnapshots:
    def test_section_header_diamond(self, update_snapshots):
        from bot import _format_hot_tips_section_header

        assert_snapshot(
            "helper_section_header_diamond",
            _format_hot_tips_section_header("diamond", 2) + "\n",
            update_snapshots,
        )

    def test_section_header_gold(self, update_snapshots):
        from bot import _format_hot_tips_section_header

        assert_snapshot(
            "helper_section_header_gold",
            _format_hot_tips_section_header("gold", 3) + "\n",
            update_snapshots,
        )

    def test_section_header_silver(self, update_snapshots):
        from bot import _format_hot_tips_section_header

        assert_snapshot(
            "helper_section_header_silver",
            _format_hot_tips_section_header("silver", 1) + "\n",
            update_snapshots,
        )

    def test_section_header_bronze(self, update_snapshots):
        from bot import _format_hot_tips_section_header

        assert_snapshot(
            "helper_section_header_bronze",
            _format_hot_tips_section_header("bronze", 4) + "\n",
            update_snapshots,
        )

    def test_track_record_line(self, update_snapshots):
        from bot import _format_hot_tips_track_record_line

        actual = _format_hot_tips_track_record_line(
            ["hit", "miss", "hit", "hit", "miss", "hit", "miss", "hit", "hit", "miss"],
            -4.2,
        )
        assert_snapshot("helper_track_record_line", actual + "\n", update_snapshots)

    def test_edge_tracker_record_line(self, update_snapshots):
        from bot import _format_edge_tracker_record_line

        actual = _format_edge_tracker_record_line(make_edge_tracker_summary())
        assert_snapshot("helper_edge_tracker_record_line", actual + "\n", update_snapshots)

    def test_yesterday_lines_hit(self, update_snapshots):
        from bot import _build_hot_tips_yesterday_lines

        actual = "\n".join(
            _build_hot_tips_yesterday_lines(
                [
                    make_settled_edge("chiefs_vs_pirates_2026-03-13"),
                    make_settled_edge(
                        "sundowns_vs_city_2026-03-13",
                        result="miss",
                        edge_tier="bronze",
                        actual_return=0.0,
                    ),
                ]
            )
        )
        assert_snapshot("helper_yesterday_lines_hit", actual + "\n", update_snapshots)

    def test_yesterday_lines_all_missed(self, update_snapshots):
        from bot import _build_hot_tips_yesterday_lines

        actual = "\n".join(
            _build_hot_tips_yesterday_lines(
                [
                    make_settled_edge("chiefs_vs_pirates_2026-03-13", result="miss", actual_return=0.0),
                    make_settled_edge("sundowns_vs_city_2026-03-13", result="miss", actual_return=0.0),
                ]
            )
        )
        assert_snapshot("helper_yesterday_lines_all_missed", actual + "\n", update_snapshots)

    def test_recently_settled_lines(self, update_snapshots):
        from bot import _build_recently_settled_lines

        actual = "\n".join(
            _build_recently_settled_lines(
                [
                    make_settled_edge("chiefs_vs_pirates_2026-03-13"),
                    make_settled_edge(
                        "sundowns_vs_city_2026-03-13",
                        result="miss",
                        edge_tier="bronze",
                        actual_return=0.0,
                    ),
                ]
            )
        )
        assert_snapshot("helper_recently_settled_lines", actual + "\n", update_snapshots)

    def test_upgrade_message_bronze_tip(self, update_snapshots):
        with _TIER_GATE_FOUNDING_PATCH:
            from tier_gate import get_upgrade_message

            actual = get_upgrade_message("bronze", context="tip")
        assert_snapshot("helper_upgrade_message_bronze_tip", actual + "\n", update_snapshots)

    def test_upgrade_message_bronze_gold_edge(self, update_snapshots):
        with _TIER_GATE_FOUNDING_PATCH:
            from tier_gate import get_upgrade_message

            actual = get_upgrade_message("bronze", context="gold_edge")
        assert_snapshot("helper_upgrade_message_bronze_gold_edge", actual + "\n", update_snapshots)

    def test_upgrade_message_bronze_diamond_edge(self, update_snapshots):
        with _TIER_GATE_FOUNDING_PATCH:
            from tier_gate import get_upgrade_message

            actual = get_upgrade_message("bronze", context="diamond_edge")
        assert_snapshot("helper_upgrade_message_bronze_diamond_edge", actual + "\n", update_snapshots)

    def test_upgrade_message_gold(self, update_snapshots):
        with _TIER_GATE_FOUNDING_PATCH:
            from tier_gate import get_upgrade_message

            actual = get_upgrade_message("gold", context="diamond_edge")
        assert_snapshot("helper_upgrade_message_gold", actual + "\n", update_snapshots)

    def test_sanitize_markdown(self, update_snapshots):
        from bot import sanitize_ai_response

        raw = (
            "## The Setup\n"
            "**Arsenal** are in fine form with WDWWW.\n"
            "# The Edge\n"
            "The bookies have undervalued the draw.\n"
            "## The Risk\n"
            "- Key player rotation possible\n"
            "- Weather could play a role\n"
            "## Verdict\n"
            "Back the draw with Medium conviction.\n"
        )
        assert_snapshot(
            "helper_sanitize_markdown",
            sanitize_ai_response(raw) + "\n",
            update_snapshots,
        )

    def test_sanitize_clean(self, update_snapshots):
        from bot import sanitize_ai_response

        raw = (
            "📋 <b>The Setup</b>\n"
            "Arsenal sit 2nd in the table.\n\n"
            "🎯 <b>The Edge</b>\n"
            "Value on the draw at 3.40.\n\n"
            "⚠️ <b>The Risk</b>\n"
            "Derby day unpredictability.\n\n"
            "🏆 <b>Verdict</b>\n"
            "Draw is the pick."
        )
        assert_snapshot(
            "helper_sanitize_clean",
            sanitize_ai_response(raw) + "\n",
            update_snapshots,
        )


class TestSnapshotInfrastructure:
    def test_golden_dir_exists(self):
        from .conftest import GOLDEN_DIR

        assert GOLDEN_DIR.is_dir(), "golden/ directory must exist"

    def test_snapshot_create_and_match(self, tmp_path, monkeypatch):
        import tests.snapshots.conftest as snapshot_support

        test_golden = tmp_path / "golden"
        monkeypatch.setattr(snapshot_support, "GOLDEN_DIR", test_golden)

        snapshot_support.assert_snapshot("test_infra", "Hello World\n", update=True)
        snapshot_support.assert_snapshot("test_infra", "Hello World\n", update=False)

    def test_snapshot_mismatch_fails(self, tmp_path, monkeypatch):
        import pytest
        import tests.snapshots.conftest as snapshot_support

        test_golden = tmp_path / "golden"
        monkeypatch.setattr(snapshot_support, "GOLDEN_DIR", test_golden)

        snapshot_support.assert_snapshot("test_mismatch", "Original\n", update=True)
        with pytest.raises(pytest.fail.Exception, match="Snapshot mismatch"):
            snapshot_support.assert_snapshot("test_mismatch", "Changed\n", update=False)

    def test_all_fixtures_defined(self):
        tips = [
            make_tip(display_tier="diamond", edge_score=62.0),
            make_tip(display_tier="gold", edge_score=46.0),
            make_tip(display_tier="silver", edge_score=39.0),
            make_tip(display_tier="bronze", edge_score=22.0),
        ]
        assert [tip["edge_score"] for tip in tips] == [62.0, 46.0, 39.0, 22.0]
