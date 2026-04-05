"""Tests for message_types.py — P3-02: Split Monolith into Message Types.

Coverage:
    DigestMessage.build()       — compact digest with ≤7 picks
    DigestMessage._empty_state()
    DigestMessage.expired_response()
    DetailMessage.build()       — full analysis with back button
    AlertMessage.build()        — pre-match alert
    ResultMessage.build()       — post-match result + totals
    is_stale_hash()             — stale digest detection utility
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("ODDS_API_KEY", "test-key")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("SENTRY_DSN", "")

from message_types import (
    AlertMessage,
    DetailMessage,
    DigestMessage,
    ResultMessage,
    is_stale_hash,
    EDGE_EMOJIS,
    EDGE_LABELS,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────

def _tip(
    tier: str = "gold",
    home: str = "Kaizer Chiefs",
    away: str = "Orlando Pirates",
    kickoff: str = "Today 19:30",
    ev: float = 4.2,
    odds: float = 2.10,
    narrative: bool = True,
    cb_key: str = "kc_vs_op_2026",
    sport_emoji: str = "⚽",
    outcome: str = "Kaizer Chiefs to Win",
    bookmaker: str = "hollywoodbets",
) -> dict:
    """Return a minimal tip dict for testing."""
    return {
        "display_tier": tier,
        "edge_rating": tier,
        "home_team": home,
        "away_team": away,
        "kickoff": kickoff,
        "_bc_kickoff": kickoff,
        "ev": ev,
        "odds": odds,
        "has_narrative": narrative,
        "cb_key": cb_key,
        "sport_emoji": sport_emoji,
        "outcome": outcome,
        "bookmaker": bookmaker,
        "league": "PSL",
        "match_id": cb_key,
        "access": "full",
    }


# ── is_stale_hash ─────────────────────────────────────────────────────────────

class TestIsStaleHash:
    def test_10_char_hex_is_stale(self):
        assert is_stale_hash("a1b2c3d4e5") is True

    def test_md5_prefix_is_stale(self):
        import hashlib
        h = hashlib.md5(b"some_match_key").hexdigest()[:10]
        assert is_stale_hash(h) is True

    def test_full_match_key_not_stale(self):
        assert is_stale_hash("kaizer_chiefs_vs_pirates_2026-04-06") is False

    def test_short_match_key_not_stale(self):
        # Short match keys with underscores are NOT hashes
        assert is_stale_hash("kc_vs_op") is False

    def test_9_chars_not_stale(self):
        assert is_stale_hash("a1b2c3d4e") is False

    def test_11_chars_not_stale(self):
        assert is_stale_hash("a1b2c3d4e5f") is False

    def test_uppercase_not_stale(self):
        assert is_stale_hash("A1B2C3D4E5") is False  # uppercase → not an MD5[:10]

    def test_contains_non_hex_not_stale(self):
        assert is_stale_hash("a1b2c3g4e5") is False  # 'g' not hex


# ── DigestMessage ─────────────────────────────────────────────────────────────

class TestDigestMessage:
    def test_empty_picks_returns_empty_state(self):
        text, markup = DigestMessage.build([])
        assert "No Edges today" in text
        labels = [btn.text for row in markup.inline_keyboard for btn in row]
        assert any("Refresh" in lbl for lbl in labels)

    def test_compact_format_contains_team_names(self):
        picks = [_tip()]
        text, markup = DigestMessage.build(picks)
        assert "Kaizer Chiefs" in text
        assert "Orlando Pirates" in text

    def test_compact_format_contains_tier_emoji(self):
        picks = [_tip(tier="gold")]
        text, _ = DigestMessage.build(picks)
        assert "🥇" in text

    def test_compact_format_contains_kickoff(self):
        picks = [_tip(kickoff="Today 19:30")]
        text, _ = DigestMessage.build(picks)
        assert "Today 19:30" in text

    def test_max_items_enforced(self):
        picks = [_tip(cb_key=f"match_{i}", home=f"Team{i}", away=f"Away{i}") for i in range(10)]
        text, markup = DigestMessage.build(picks)
        # Max 7 items → [1] through [7]
        assert "[7]" in text
        assert "[8]" not in text

    def test_no_narrative_shows_warning(self):
        picks = [_tip(narrative=False)]
        text, _ = DigestMessage.build(picks)
        assert "⚠️" in text

    def test_has_narrative_no_warning(self):
        picks = [_tip(narrative=True)]
        text, _ = DigestMessage.build(picks)
        assert "⚠️" not in text

    def test_callback_uses_edge_detail(self):
        picks = [_tip(cb_key="abc123def0", tier="gold")]
        _, markup = DigestMessage.build(picks)
        flat = [btn.callback_data for row in markup.inline_keyboard for btn in row if btn.callback_data]
        assert any("edge:detail:abc123def0" in cb for cb in flat)

    def test_locked_pick_uses_upgrade_callback(self):
        pick = _tip(cb_key="lockedkey01")
        pick["access"] = "locked"
        _, markup = DigestMessage.build([pick])
        flat = [btn.callback_data for row in markup.inline_keyboard for btn in row if btn.callback_data]
        assert any("hot:upgrade" in cb for cb in flat)

    def test_text_within_char_limit(self):
        picks = [_tip(cb_key=f"m{i}", home=f"LongTeamName{i}", away=f"AnotherLongTeam{i}") for i in range(7)]
        text, _ = DigestMessage.build(picks)
        assert len(text) <= 4096

    def test_callback_data_within_limit(self):
        """All callback_data strings must be ≤64 bytes."""
        picks = [_tip(cb_key=f"keyx{i}short") for i in range(7)]
        _, markup = DigestMessage.build(picks)
        for row in markup.inline_keyboard:
            for btn in row:
                if btn.callback_data:
                    assert len(btn.callback_data.encode()) <= 64, (
                        f"callback_data too long: {btn.callback_data!r}"
                    )

    def test_back_navigation_buttons_present(self):
        picks = [_tip()]
        _, markup = DigestMessage.build(picks)
        flat = [btn.callback_data for row in markup.inline_keyboard for btn in row if btn.callback_data]
        assert "yg:all:0" in flat
        assert "nav:main" in flat

    def test_diamond_tier_emoji(self):
        picks = [_tip(tier="diamond")]
        text, _ = DigestMessage.build(picks)
        assert "💎" in text

    def test_silver_tier_emoji(self):
        picks = [_tip(tier="silver")]
        text, _ = DigestMessage.build(picks)
        assert "🥈" in text

    def test_bronze_tier_emoji(self):
        picks = [_tip(tier="bronze")]
        text, _ = DigestMessage.build(picks)
        assert "🥉" in text

    def test_expired_response_content(self):
        text, markup = DigestMessage.expired_response()
        assert "expired" in text.lower()
        assert "/today" in text
        labels = [btn.callback_data for row in markup.inline_keyboard for btn in row if btn.callback_data]
        assert "hot:go" in labels

    def test_custom_title(self):
        picks = [_tip()]
        text, _ = DigestMessage.build(picks, title="Morning Picks")
        assert "Morning Picks" in text

    def test_html_escaping_in_team_names(self):
        picks = [_tip(home="A&B", away="C<D>")]
        text, _ = DigestMessage.build(picks)
        assert "&amp;" in text
        assert "&lt;" in text

    def test_multiple_picks_numbered_sequentially(self):
        picks = [
            _tip(cb_key="k1", home="Team1", away="Team2"),
            _tip(cb_key="k2", home="Team3", away="Team4"),
            _tip(cb_key="k3", home="Team5", away="Team6"),
        ]
        text, _ = DigestMessage.build(picks)
        assert "[1]" in text
        assert "[2]" in text
        assert "[3]" in text


# ── DetailMessage ─────────────────────────────────────────────────────────────

class TestDetailMessage:
    def test_contains_team_names(self):
        tip = _tip()
        text, _ = DetailMessage.build(tip)
        assert "Kaizer Chiefs" in text
        assert "Orlando Pirates" in text

    def test_contains_tier_badge(self):
        tip = _tip(tier="gold")
        text, _ = DetailMessage.build(tip)
        assert "🥇" in text
        assert "GOLDEN EDGE" in text

    def test_diamond_badge(self):
        tip = _tip(tier="diamond")
        text, _ = DetailMessage.build(tip)
        assert "💎" in text
        assert "DIAMOND EDGE" in text

    def test_back_button_present(self):
        tip = _tip()
        _, markup = DetailMessage.build(tip, back_cb="hot:back:0")
        flat = [btn.callback_data for row in markup.inline_keyboard for btn in row if btn.callback_data]
        assert "hot:back:0" in flat

    def test_custom_back_callback(self):
        tip = _tip()
        _, markup = DetailMessage.build(tip, back_cb="today:back:0")
        flat = [btn.callback_data for row in markup.inline_keyboard for btn in row if btn.callback_data]
        assert "today:back:0" in flat

    def test_back_button_label(self):
        tip = _tip()
        _, markup = DetailMessage.build(tip)
        labels = [btn.text for row in markup.inline_keyboard for btn in row]
        assert any("Back" in lbl for lbl in labels)

    def test_bookmaker_cta_button(self):
        tip = _tip()
        _, markup = DetailMessage.build(
            tip,
            bookmaker_name="Hollywoodbets",
            bookmaker_url="https://hwb.co.za/affiliate",
        )
        url_btns = [btn for row in markup.inline_keyboard for btn in row if btn.url]
        assert len(url_btns) == 1
        assert "Hollywoodbets" in url_btns[0].text

    def test_no_bookmaker_url_no_cta(self):
        tip = _tip()
        _, markup = DetailMessage.build(tip)
        url_btns = [btn for row in markup.inline_keyboard for btn in row if btn.url]
        assert len(url_btns) == 0

    def test_compare_odds_button_when_cb_given(self):
        tip = _tip()
        _, markup = DetailMessage.build(tip, compare_odds_cb="odds:compare:abc123")
        flat = [btn.callback_data for row in markup.inline_keyboard for btn in row if btn.callback_data]
        assert "odds:compare:abc123" in flat

    def test_no_compare_odds_button_when_cb_missing(self):
        tip = _tip()
        _, markup = DetailMessage.build(tip, compare_odds_cb="")
        flat = [btn.callback_data for row in markup.inline_keyboard for btn in row if btn.callback_data]
        assert not any("odds:compare" in cb for cb in flat)

    def test_narrative_included(self):
        tip = _tip()
        text, _ = DetailMessage.build(tip, narrative="📋 <b>The Setup</b>\nTest narrative")
        assert "Test narrative" in text

    def test_fallback_when_no_narrative(self):
        tip = _tip()
        text, _ = DetailMessage.build(tip, narrative="")
        assert "The Setup" in text

    def test_odds_block_shown_when_show_odds_true(self):
        tip = _tip(odds=2.10, ev=4.2, outcome="Chiefs to Win")
        text, _ = DetailMessage.build(tip, show_odds=True)
        assert "2.10" in text       # inside <code> tags — substring still present
        assert "4.2%" in text       # inside <code> tags — substring still present
        assert "EV" in text

    def test_odds_block_hidden_when_show_odds_false(self):
        tip = _tip(odds=2.10, ev=4.2)
        text, _ = DetailMessage.build(tip, show_odds=False)
        # EV + odds should not appear
        assert "+4.2% EV" not in text

    def test_injury_flags_included(self):
        tip = _tip()
        text, _ = DetailMessage.build(tip, injury_flags="💉 No injuries flagged")
        assert "No injuries flagged" in text

    def test_blockquote_present_when_deep_analysis_available(self):
        tip = _tip()
        tip["odds_by_bookmaker"] = {"hollywoodbets": 2.15, "betway": 2.10}
        text, _ = DetailMessage.build(tip, show_odds=True)
        assert "<blockquote expandable>" in text
        assert "</blockquote>" in text

    def test_all_bookmaker_odds_in_blockquote(self):
        tip = _tip()
        tip["odds_by_bookmaker"] = {
            "hollywoodbets": 2.15,
            "betway": 2.10,
            "gbets": 2.05,
        }
        text, _ = DetailMessage.build(tip, show_odds=True)
        assert "Hollywoodbets" in text
        assert "Betway" in text
        assert "GBets" in text

    def test_best_bookmaker_starred(self):
        tip = _tip()
        tip["odds_by_bookmaker"] = {
            "hollywoodbets": 2.15,
            "betway": 2.10,
        }
        text, _ = DetailMessage.build(tip, show_odds=True)
        # Best odds (2.15 — Hollywoodbets) should have ⭐
        assert "⭐" in text

    def test_header_marker_present(self):
        """The 🎯 header marker must be present (used by _inject_narrative_header)."""
        tip = _tip()
        text, _ = DetailMessage.build(tip)
        assert "🎯" in text

    def test_league_shown(self):
        tip = _tip()
        text, _ = DetailMessage.build(tip)
        assert "PSL" in text

    def test_kickoff_shown(self):
        tip = _tip(kickoff="Today 19:30")
        text, _ = DetailMessage.build(tip)
        assert "Today 19:30" in text

    def test_callback_data_within_limit(self):
        tip = _tip()
        _, markup = DetailMessage.build(
            tip,
            back_cb="hot:back:0",
            compare_odds_cb="odds:compare:abc123",
        )
        for row in markup.inline_keyboard:
            for btn in row:
                if btn.callback_data:
                    assert len(btn.callback_data.encode()) <= 64


# ── AlertMessage ──────────────────────────────────────────────────────────────

class TestAlertMessage:
    def test_contains_team_names(self):
        tip = _tip(tier="gold")
        text, _ = AlertMessage.build(tip)
        assert "Kaizer Chiefs" in text
        assert "Orlando Pirates" in text

    def test_contains_tier_label(self):
        tip = _tip(tier="gold")
        text, _ = AlertMessage.build(tip)
        assert "GOLDEN EDGE" in text
        assert "🥇" in text

    def test_diamond_tier(self):
        tip = _tip(tier="diamond")
        text, _ = AlertMessage.build(tip)
        assert "DIAMOND EDGE" in text
        assert "💎" in text

    def test_time_to_kickoff_hours_and_minutes(self):
        tip = _tip()
        text, _ = AlertMessage.build(tip, minutes_to_kickoff=150)
        assert "2h 30m" in text

    def test_time_to_kickoff_hours_only(self):
        tip = _tip()
        text, _ = AlertMessage.build(tip, minutes_to_kickoff=120)
        assert "2h" in text
        assert "0m" not in text

    def test_time_to_kickoff_minutes_only(self):
        tip = _tip()
        text, _ = AlertMessage.build(tip, minutes_to_kickoff=45)
        assert "45 min" in text

    def test_no_time_string_when_zero(self):
        tip = _tip()
        text, _ = AlertMessage.build(tip, minutes_to_kickoff=0)
        assert "Kicking off" not in text

    def test_bookmaker_url_creates_cta(self):
        tip = _tip()
        _, markup = AlertMessage.build(
            tip,
            bookmaker_name="Hollywoodbets",
            bookmaker_url="https://hwb.co.za/aff",
        )
        url_btns = [btn for row in markup.inline_keyboard for btn in row if btn.url]
        assert len(url_btns) == 1
        assert "Hollywoodbets" in url_btns[0].text

    def test_fallback_button_when_no_url(self):
        tip = _tip()
        _, markup = AlertMessage.build(tip)
        all_cbs = [btn.callback_data for row in markup.inline_keyboard for btn in row if btn.callback_data]
        assert "hot:go" in all_cbs

    def test_detail_cb_adds_analysis_button(self):
        tip = _tip()
        _, markup = AlertMessage.build(tip, detail_cb="edge:detail:abc123")
        all_cbs = [btn.callback_data for row in markup.inline_keyboard for btn in row if btn.callback_data]
        assert "edge:detail:abc123" in all_cbs

    def test_odds_and_ev_in_text(self):
        tip = _tip(odds=2.10, ev=4.2, outcome="Chiefs to Win", bookmaker="hollywoodbets")
        text, _ = AlertMessage.build(tip, bookmaker_name="Hollywoodbets")
        assert "2.10" in text
        assert "4.2%" in text

    def test_league_shown(self):
        tip = _tip()
        text, _ = AlertMessage.build(tip)
        assert "PSL" in text

    def test_kickoff_shown(self):
        tip = _tip(kickoff="Today 19:30")
        text, _ = AlertMessage.build(tip)
        assert "Today 19:30" in text

    def test_alert_header_present(self):
        tip = _tip()
        text, _ = AlertMessage.build(tip)
        assert "Match Alert" in text

    def test_callback_data_within_limit(self):
        tip = _tip()
        _, markup = AlertMessage.build(tip, detail_cb="edge:detail:abc123")
        for row in markup.inline_keyboard:
            for btn in row:
                if btn.callback_data:
                    assert len(btn.callback_data.encode()) <= 64

    def test_html_escaping_in_team_names(self):
        tip = _tip(home="A&B FC", away="C>D United")
        text, _ = AlertMessage.build(tip)
        assert "&amp;" in text


# ── ResultMessage ─────────────────────────────────────────────────────────────

class TestResultMessage:
    def test_hit_shows_checkmark(self):
        result = {"result": "hit", "edge_tier": "gold", "match_key": "chf_vs_pir"}
        text, markup = ResultMessage.build(result)
        assert "✅" in text
        assert "HIT" in text
        assert markup is None  # No keyboard for silent messages

    def test_miss_shows_cross(self):
        result = {"result": "miss", "edge_tier": "silver", "match_key": "chf_vs_pir"}
        text, _ = ResultMessage.build(result)
        assert "❌" in text
        assert "MISS" in text

    def test_tier_emoji_included(self):
        result = {"result": "hit", "edge_tier": "diamond"}
        text, _ = ResultMessage.build(result)
        assert "💎" in text

    def test_gold_tier_emoji(self):
        result = {"result": "hit", "edge_tier": "gold"}
        text, _ = ResultMessage.build(result)
        assert "🥇" in text

    def test_match_display_shown(self):
        result = {"result": "hit", "edge_tier": "bronze", "match_key": "chiefs_vs_pirates"}
        text, _ = ResultMessage.build(result)
        assert "chiefs_vs_pirates" in text

    def test_score_shown(self):
        result = {"result": "hit", "edge_tier": "gold", "match_score": "2-1"}
        text, _ = ResultMessage.build(result)
        assert "2-1" in text

    def test_outcome_and_odds_shown(self):
        result = {
            "result": "hit",
            "edge_tier": "gold",
            "outcome": "Chiefs to Win",
            "odds": 2.10,
        }
        text, _ = ResultMessage.build(result)
        assert "Chiefs to Win" in text
        assert "2.10" in text

    def test_running_totals_shown(self):
        result = {"result": "hit", "edge_tier": "gold"}
        totals = {"total": 12, "hits": 8, "hit_rate": 0.667, "roi_pct": 12.3, "period": "7 days"}
        text, _ = ResultMessage.build(result, totals)
        assert "8/12" in text
        assert "67%" in text
        assert "+12.3%" in text
        assert "7 days" in text

    def test_totals_normalise_percentage_hit_rate(self):
        """hit_rate of 0.667 and 66.7 should both render as ~67%."""
        result = {"result": "hit", "edge_tier": "gold"}
        totals_decimal = {"total": 10, "hits": 6, "hit_rate": 0.6, "roi_pct": 5.0}
        text_decimal, _ = ResultMessage.build(result, totals_decimal)
        totals_pct = {"total": 10, "hits": 6, "hit_rate": 60.0, "roi_pct": 5.0}
        text_pct, _ = ResultMessage.build(result, totals_pct)
        assert "60%" in text_decimal
        assert "60%" in text_pct

    def test_no_keyboard_returned(self):
        result = {"result": "miss", "edge_tier": "bronze"}
        _, markup = ResultMessage.build(result)
        assert markup is None

    def test_no_totals_omits_totals_line(self):
        result = {"result": "hit", "edge_tier": "gold"}
        text, _ = ResultMessage.build(result, totals=None)
        assert "Last" not in text
        assert "ROI" not in text

    def test_empty_totals_omits_totals_line(self):
        result = {"result": "hit", "edge_tier": "gold"}
        text, _ = ResultMessage.build(result, totals={"total": 0})
        assert "Last" not in text

    def test_negative_roi_shows_minus(self):
        result = {"result": "miss", "edge_tier": "bronze"}
        totals = {"total": 10, "hits": 3, "hit_rate": 0.3, "roi_pct": -5.5}
        text, _ = ResultMessage.build(result, totals)
        assert "-5.5%" in text

    def test_html_safe_match_display(self):
        result = {"result": "hit", "edge_tier": "gold", "match_key": "A&B vs C<D>"}
        text, _ = ResultMessage.build(result)
        assert "&amp;" in text

    def test_recommended_odds_fallback(self):
        """Should use recommended_odds when odds key is absent."""
        result = {
            "result": "hit",
            "edge_tier": "gold",
            "outcome": "Win",
            "recommended_odds": 1.95,
        }
        text, _ = ResultMessage.build(result)
        assert "1.95" in text


# ── Integration: DigestMessage → DetailMessage round-trip ────────────────────

class TestDigestDetailIntegration:
    """Validate that DigestMessage buttons produce valid edge:detail callbacks
    that DetailMessage can build a proper response for."""

    def test_digest_button_cb_is_valid_detail_cb(self):
        """Button callback from digest should match expected edge:detail format."""
        pick = _tip(cb_key="kc_vs_op_2026")
        _, markup = DigestMessage.build([pick])

        # Find the first non-nav button
        detail_cbs = [
            btn.callback_data
            for row in markup.inline_keyboard
            for btn in row
            if btn.callback_data and btn.callback_data.startswith("edge:detail:")
        ]
        assert len(detail_cbs) >= 1
        cb = detail_cbs[0]
        assert cb == "edge:detail:kc_vs_op_2026"

    def test_detail_back_button_sends_user_to_digest(self):
        """Back button in detail must use a callback that returns to digest view."""
        tip = _tip()
        _, markup = DetailMessage.build(tip, back_cb="hot:back:0")

        back_cbs = [
            btn.callback_data
            for row in markup.inline_keyboard
            for btn in row
            if btn.callback_data and "back" in btn.callback_data.lower()
        ]
        assert len(back_cbs) >= 1
        assert "hot:back:0" in back_cbs

    def test_today_back_callback_alternative(self):
        """DetailMessage supports today:back:0 callback for /today flow."""
        tip = _tip()
        _, markup = DetailMessage.build(tip, back_cb="today:back:0")
        flat = [btn.callback_data for row in markup.inline_keyboard for btn in row if btn.callback_data]
        assert "today:back:0" in flat


# ── P3-04: Template Consistency Tests ────────────────────────────────────────

class TestP304Templates:
    """P3-04: Consistent message templates across all 4 message types."""

    # ── Monospace numbers ──────────────────────────────────────────────────

    def test_detail_odds_in_code_tags(self):
        tip = _tip(odds=2.10)
        text, _ = DetailMessage.build(tip, show_odds=True)
        assert "<code>2.10</code>" in text

    def test_detail_ev_in_code_tags(self):
        tip = _tip(ev=4.2)
        text, _ = DetailMessage.build(tip, show_odds=True)
        assert "<code>4.2%</code>" in text

    def test_alert_odds_in_code_tags(self):
        tip = _tip(odds=2.10)
        text, _ = AlertMessage.build(tip)
        assert "<code>2.10</code>" in text

    def test_alert_ev_in_code_tags(self):
        tip = _tip(ev=4.2)
        text, _ = AlertMessage.build(tip)
        assert "<code>4.2%</code>" in text

    def test_result_odds_in_code_tags(self):
        result = {"result": "hit", "edge_tier": "gold", "outcome": "Win", "odds": 2.10}
        text, _ = ResultMessage.build(result)
        assert "<code>2.10</code>" in text

    def test_result_hit_rate_in_code_tags(self):
        result = {"result": "hit", "edge_tier": "gold"}
        totals = {"total": 10, "hits": 7, "hit_rate": 0.7, "roi_pct": 5.0}
        text, _ = ResultMessage.build(result, totals)
        assert "<code>7/10</code>" in text
        assert "<code>70%</code>" in text

    def test_result_roi_in_code_tags(self):
        result = {"result": "hit", "edge_tier": "gold"}
        totals = {"total": 10, "hits": 7, "hit_rate": 0.7, "roi_pct": 12.5}
        text, _ = ResultMessage.build(result, totals)
        assert "<code>+12.5%</code>" in text

    def test_digest_ev_in_code_tags(self):
        picks = [_tip(ev=3.8)]
        text, _ = DigestMessage.build(picks)
        assert "<code>+3.8%</code>" in text

    def test_digest_no_ev_when_zero(self):
        picks = [_tip(ev=0.0)]
        text, _ = DigestMessage.build(picks)
        assert "EV" not in text

    # ── Expandable blockquotes ─────────────────────────────────────────────

    def test_detail_narrative_in_blockquote(self):
        tip = _tip()
        text, _ = DetailMessage.build(tip, narrative="📋 <b>The Setup</b>\nTest analysis")
        assert "<blockquote expandable>" in text
        assert "Test analysis" in text

    def test_alert_analysis_blockquote(self):
        tip = _tip()
        text, _ = AlertMessage.build(tip, analysis="Strong market movement towards home win.")
        assert "<blockquote expandable>" in text
        assert "Strong market movement" in text

    def test_alert_no_blockquote_when_no_analysis(self):
        tip = _tip()
        text, _ = AlertMessage.build(tip)
        assert "<blockquote expandable>" not in text

    def test_result_post_match_analysis_blockquote(self):
        result = {"result": "hit", "edge_tier": "gold"}
        text, _ = ResultMessage.build(result, post_match_analysis="Market was correctly priced at 68%.")
        assert "<blockquote expandable>" in text
        assert "Market was correctly priced" in text

    def test_result_no_blockquote_when_no_analysis(self):
        result = {"result": "hit", "edge_tier": "gold"}
        text, _ = ResultMessage.build(result)
        assert "<blockquote expandable>" not in text

    def test_digest_stats_blockquote(self):
        picks = [_tip()]
        text, _ = DigestMessage.build(picks, stats_summary="7-day hit rate: 68% · ROI +14.2%")
        assert "<blockquote expandable>" in text
        assert "68%" in text

    def test_digest_no_blockquote_when_no_stats(self):
        picks = [_tip()]
        text, _ = DigestMessage.build(picks)
        assert "<blockquote expandable>" not in text

    # ── P/L in Rands ──────────────────────────────────────────────────────

    def test_result_pl_rands_shown_for_hit(self):
        result = {"result": "hit", "edge_tier": "gold", "pl_rands": 110.0}
        text, _ = ResultMessage.build(result)
        assert "P/L" in text
        assert "+R110" in text

    def test_result_pl_rands_shown_for_miss(self):
        result = {"result": "miss", "edge_tier": "gold", "pl_rands": -100.0}
        text, _ = ResultMessage.build(result)
        assert "P/L" in text
        assert "-R100" in text

    def test_result_pl_rands_omitted_when_zero(self):
        result = {"result": "hit", "edge_tier": "gold"}
        text, _ = ResultMessage.build(result)
        assert "P/L" not in text

    def test_result_pl_rands_in_code_tags(self):
        result = {"result": "hit", "edge_tier": "gold", "pl_rands": 75.0}
        text, _ = ResultMessage.build(result)
        assert "<code>+R75</code>" in text

    # ── Alert "View Details" button ────────────────────────────────────────

    def test_alert_view_details_button_label(self):
        tip = _tip()
        _, markup = AlertMessage.build(tip, detail_cb="edge:detail:abc123")
        labels = [btn.text for row in markup.inline_keyboard for btn in row]
        assert any("View Details" in lbl for lbl in labels)

    # ── Confidence % ──────────────────────────────────────────────────────

    def test_detail_confidence_pct_shown(self):
        tip = _tip(odds=2.10, ev=4.2)
        text, _ = DetailMessage.build(tip, show_odds=True, confidence_pct=72.0)
        assert "<code>72%</code>" in text
        assert "Confidence" in text

    def test_detail_confidence_pct_omitted_when_zero(self):
        tip = _tip()
        text, _ = DetailMessage.build(tip)
        assert "Confidence" not in text

    # ── Missing data graceful handling ────────────────────────────────────

    def test_result_missing_pl_rands_no_crash(self):
        result = {"result": "hit", "edge_tier": "gold"}
        text, markup = ResultMessage.build(result)
        assert "HIT" in text
        assert markup is None

    def test_alert_missing_analysis_no_crash(self):
        tip = _tip()
        text, _ = AlertMessage.build(tip, analysis="")
        assert "Match Alert" in text

    def test_detail_missing_confidence_pct_no_crash(self):
        tip = _tip()
        text, _ = DetailMessage.build(tip, confidence_pct=0.0)
        assert "Kaizer Chiefs" in text

    # ── 4096 / 1024 char limits ────────────────────────────────────────────

    def test_detail_within_char_limit(self):
        tip = _tip(odds=2.10, ev=4.2)
        tip["odds_by_bookmaker"] = {f"bk{i}": 2.0 + i * 0.05 for i in range(8)}
        text, _ = DetailMessage.build(
            tip,
            narrative="📋 " + "x" * 800,
            show_odds=True,
            confidence_pct=65.0,
        )
        assert len(text) <= 4096

    def test_alert_within_char_limit(self):
        tip = _tip(odds=2.10, ev=4.2)
        text, _ = AlertMessage.build(
            tip,
            analysis="A" * 500,
            minutes_to_kickoff=90,
        )
        assert len(text) <= 4096

    def test_result_within_char_limit(self):
        result = {"result": "hit", "edge_tier": "diamond", "pl_rands": 200.0,
                  "outcome": "Home Win", "odds": 2.50, "match_score": "2-1"}
        totals = {"total": 50, "hits": 34, "hit_rate": 0.68, "roi_pct": 22.1, "period": "30 days"}
        text, _ = ResultMessage.build(
            result, totals,
            post_match_analysis="The model had this at 61% true probability." * 5,
        )
        assert len(text) <= 4096
