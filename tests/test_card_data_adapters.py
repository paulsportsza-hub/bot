"""Tests for card data adapters — BUILD-WAVE1-SUB-01 + BUILD-WAVE2-ONBOARDING-01."""
from __future__ import annotations

import pytest

from card_data_adapters import (
    build_sub_plans_data,
    build_sub_upgrade_bronze_data,
    build_sub_upgrade_gold_data,
    build_sub_upgrade_diamond_max_data,
    build_sub_payment_ready_data,
    build_sub_payment_error_data,
    build_sub_email_redirect_data,
    build_sub_status_active_data,
    build_sub_status_bronze_data,
    build_sub_billing_active_data,
    build_sub_billing_inactive_data,
    build_sub_cancel_confirm_data,
    build_sub_cancel_done_data,
    build_sub_founding_confirmed_data,
    build_sub_founding_soldout_data,
    build_sub_founding_ended_data,
    build_sub_founding_live_data,
    build_sub_expiry_notice_data,
    build_sub_trial_expiry_data,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _has_logo(data: dict) -> bool:
    return "header_logo_b64" in data


# ── 1: sub_plans ──────────────────────────────────────────────────────────────

def test_sub_plans_keys():
    d = build_sub_plans_data()
    assert "plans" in d
    assert "founding_offer" in d
    assert _has_logo(d)


def test_sub_plans_three_tiers():
    d = build_sub_plans_data()
    tiers = [p["tier"] for p in d["plans"]]
    assert tiers == ["bronze", "gold", "diamond"]


def test_sub_plans_founding_offer_none_when_no_days():
    d = build_sub_plans_data(founding_days_left=0)
    assert d["founding_offer"] is None


def test_sub_plans_founding_offer_present_when_days_left():
    d = build_sub_plans_data(founding_days_left=5, founding_slots_remaining=20)
    assert d["founding_offer"] is not None
    assert d["founding_offer"]["days_left"] == 5
    assert d["founding_offer"]["slots_remaining"] == 20


# ── 2: upgrade_bronze ─────────────────────────────────────────────────────────

def test_upgrade_bronze_has_two_plans():
    d = build_sub_upgrade_bronze_data()
    assert len(d["target_plans"]) == 2


def test_upgrade_bronze_founding_offer_absent_when_zero():
    d = build_sub_upgrade_bronze_data(founding_days_left=0)
    assert d["founding_offer"] is None


def test_upgrade_bronze_founding_offer_present():
    d = build_sub_upgrade_bronze_data(founding_days_left=3)
    assert d["founding_offer"]["days_left"] == 3


# ── 3: upgrade_gold ───────────────────────────────────────────────────────────

def test_upgrade_gold_has_features():
    d = build_sub_upgrade_gold_data()
    assert isinstance(d["features"], list)
    assert len(d["features"]) >= 3


def test_upgrade_gold_founding_offer_present():
    d = build_sub_upgrade_gold_data(founding_days_left=10)
    assert d["founding_offer"]["days_left"] == 10


# ── 4: upgrade_diamond_max ────────────────────────────────────────────────────

def test_upgrade_diamond_max_logo():
    d = build_sub_upgrade_diamond_max_data()
    assert _has_logo(d)


# ── 5: payment_ready ──────────────────────────────────────────────────────────

def test_payment_ready_fields():
    d = build_sub_payment_ready_data(
        plan_name="Gold",
        price_display="R99/mo",
        reference="mze-123-gold",
        is_founding=False,
    )
    assert d["plan_name"] == "Gold"
    assert d["reference"] == "mze-123-gold"
    assert d["is_founding"] is False
    assert _has_logo(d)


def test_payment_ready_founding_flag():
    d = build_sub_payment_ready_data(is_founding=True)
    assert d["is_founding"] is True


# ── 6: payment_error ──────────────────────────────────────────────────────────

def test_payment_error_has_message_and_support():
    d = build_sub_payment_error_data(error_message="Timeout")
    assert d["error_message"] == "Timeout"
    assert "support_handle" in d
    assert _has_logo(d)


# ── 7: email_redirect ─────────────────────────────────────────────────────────

def test_email_redirect_logo():
    d = build_sub_email_redirect_data()
    assert _has_logo(d)


# ── 8: status_active ──────────────────────────────────────────────────────────

def test_status_active_tier_defaults():
    d = build_sub_status_active_data(tier="gold")
    assert d["tier"] == "gold"
    assert d["tier_emoji"] == "🥇"
    assert d["tier_name"] == "Gold"


def test_status_active_founding_slot_none_when_not_founding():
    d = build_sub_status_active_data(founding_slot=None)
    assert d["founding_slot"] is None


def test_status_active_founding_slot_set():
    d = build_sub_status_active_data(founding_slot=7)
    assert d["founding_slot"] == 7


# ── 9: status_bronze ──────────────────────────────────────────────────────────

def test_status_bronze_daily_pct_zero_when_no_views():
    d = build_sub_status_bronze_data(daily_views_used=0, daily_cap=3)
    assert d["daily_pct"] == 0


def test_status_bronze_daily_pct_capped_at_100():
    d = build_sub_status_bronze_data(daily_views_used=10, daily_cap=3)
    assert d["daily_pct"] == 100


def test_status_bronze_founding_offer():
    d = build_sub_status_bronze_data(founding_days_left=5, founding_slots_remaining=30)
    assert d["founding_offer"]["days_left"] == 5


# ── 10: billing_active ────────────────────────────────────────────────────────

def test_billing_active_tier_emoji():
    d = build_sub_billing_active_data(tier="diamond")
    assert d["tier_emoji"] == "💎"


def test_billing_active_founding_flag():
    d = build_sub_billing_active_data(is_founding=True, founding_slot=3)
    assert d["is_founding"] is True
    assert d["founding_slot"] == 3


# ── 11: billing_inactive ──────────────────────────────────────────────────────

def test_billing_inactive_logo():
    d = build_sub_billing_inactive_data()
    assert _has_logo(d)


def test_billing_inactive_last_plan_optional():
    d = build_sub_billing_inactive_data(last_plan="gold_monthly")
    assert d["last_plan"] == "gold_monthly"


# ── 12: cancel_confirm ────────────────────────────────────────────────────────

def test_cancel_confirm_fields():
    d = build_sub_cancel_confirm_data(plan_name="Gold Monthly", access_until="01 May 2026")
    assert d["plan_name"] == "Gold Monthly"
    assert d["access_until"] == "01 May 2026"


# ── 13: cancel_done ───────────────────────────────────────────────────────────

def test_cancel_done_access_until():
    d = build_sub_cancel_done_data(access_until="01 May 2026")
    assert d["access_until"] == "01 May 2026"


# ── 14: founding_confirmed ────────────────────────────────────────────────────

def test_founding_confirmed_slot_number():
    d = build_sub_founding_confirmed_data(slot_number=42, founding_price_cents=69900)
    assert d["slot_number"] == 42
    assert d["founding_price"] == "R699"


def test_founding_confirmed_has_benefits():
    d = build_sub_founding_confirmed_data()
    assert isinstance(d["benefits"], list)
    assert len(d["benefits"]) >= 3


# ── 15: founding_soldout ──────────────────────────────────────────────────────

def test_founding_soldout_logo():
    d = build_sub_founding_soldout_data()
    assert _has_logo(d)


# ── 16: founding_ended ───────────────────────────────────────────────────────

def test_founding_ended_prices():
    d = build_sub_founding_ended_data(diamond_monthly=199, diamond_annual=1599)
    assert d["diamond_monthly"] == 199
    assert d["diamond_annual"] == 1599


# ── 17: founding_live ─────────────────────────────────────────────────────────

def test_founding_live_computes_monthly_equiv():
    d = build_sub_founding_live_data(annual_price=699, normal_monthly=199)
    assert d["monthly_equiv"] == 699 // 12


def test_founding_live_computes_savings_pct():
    d = build_sub_founding_live_data(annual_price=699, normal_monthly=199)
    normal_annual = 199 * 12
    expected = round((1 - 699 / normal_annual) * 100)
    assert d["savings_pct"] == expected


def test_founding_live_slots_days():
    d = build_sub_founding_live_data(days_left=12, slots_remaining=47)
    assert d["days_left"] == 12
    assert d["slots_remaining"] == 47


# ── 18: expiry_notice ────────────────────────────────────────────────────────

def test_expiry_notice_fields():
    d = build_sub_expiry_notice_data(old_tier="gold", old_tier_emoji="🥇")
    assert d["old_tier"] == "gold"
    assert d["old_tier_emoji"] == "🥇"
    assert d["old_tier_name"] == "Gold"
    assert d["new_tier"] == "bronze"


def test_expiry_notice_emoji_fallback():
    # No emoji supplied — should fall back to tier dict
    d = build_sub_expiry_notice_data(old_tier="diamond")
    assert d["old_tier_emoji"] == "💎"


# ── 19: trial_expiry ─────────────────────────────────────────────────────────

def test_trial_expiry_days_used():
    d = build_sub_trial_expiry_data(days_used=7, hit_rate=0.0)
    assert d["days_used"] == 7


def test_trial_expiry_hit_rate_pct_conversion():
    d = build_sub_trial_expiry_data(days_used=7, hit_rate=0.68)
    assert d["hit_rate_pct"] == 68


def test_trial_expiry_zero_hit_rate():
    d = build_sub_trial_expiry_data(hit_rate=0.0)
    assert d["hit_rate_pct"] == 0


# ── Wave 2: Onboarding adapters (BUILD-WAVE2-ONBOARDING-01) ───────────────────

from card_data_adapters import (
    build_onboarding_welcome_data,
    build_onboarding_experience_data,
    build_onboarding_sports_data,
    build_onboarding_favourites_data,
    build_onboarding_favourites_manual_data,
    build_onboarding_fuzzy_suggest_data,
    build_onboarding_team_celebration_data,
    build_onboarding_edge_explainer_data,
    build_onboarding_risk_data,
    build_onboarding_bankroll_data,
    build_onboarding_bankroll_custom_data,
    build_onboarding_notify_data,
    build_onboarding_summary_data,
    build_onboarding_done_data,
    build_onboarding_restart_data,
    build_story_quiz_step_data,
    build_story_quiz_complete_data,
)


def test_welcome_has_required_keys():
    d = build_onboarding_welcome_data("Paul")
    for k in ("header_logo_b64", "first_name", "trial_started", "trial_days"):
        assert k in d, f"missing key: {k}"


def test_welcome_default_name():
    d = build_onboarding_welcome_data("")
    assert d["first_name"] == "champ"


def test_welcome_trial_flags():
    d = build_onboarding_welcome_data("Sipho", trial_started=True, trial_days=7)
    assert d["trial_started"] is True
    assert d["trial_days"] == 7


def test_welcome_founding_offer():
    d = build_onboarding_welcome_data("Sipho", founding_offer=True, founding_days_left=5)
    assert d["founding_offer"] is True
    assert d["founding_days_left"] == 5


def test_experience_has_three_options():
    d = build_onboarding_experience_data()
    assert len(d["options"]) == 3
    values = {o["value"] for o in d["options"]}
    assert values == {"experienced", "casual", "newbie"}


def test_sports_no_selection():
    d = build_onboarding_sports_data()
    assert d["selected_count"] == 0
    assert all(not s["selected"] for s in d["sports"])


def test_sports_with_selection():
    d = build_onboarding_sports_data(["soccer", "rugby"])
    assert d["selected_count"] == 2
    selected = [s for s in d["sports"] if s["selected"]]
    assert {s["key"] for s in selected} == {"soccer", "rugby"}


def test_favourites_teams_format():
    teams = [{"name": "Arsenal", "selected": True}, {"name": "Chiefs", "selected": False}]
    d = build_onboarding_favourites_data("soccer", "Soccer", "⚽", teams=teams, selected_count=1)
    assert d["sport"]["key"] == "soccer"
    assert len(d["teams"]) == 2
    assert d["selected_count"] == 1


def test_favourites_empty_teams():
    d = build_onboarding_favourites_data("rugby", "Rugby", "🏉")
    assert d["teams"] == []
    assert d["selected_count"] == 0


def test_favourites_manual_fav_label():
    d = build_onboarding_favourites_manual_data("combat", "Combat", "🥊", fav_label="fighter")
    assert d["fav_label"] == "fighter"
    assert d["sport"]["key"] == "combat"


def test_favourites_manual_example():
    d = build_onboarding_favourites_manual_data("soccer", "Soccer", "⚽", example="e.g. Arsenal")
    assert "Arsenal" in d["example"]


def test_fuzzy_suggest_suggestions_list():
    sug = [{"label": "Arsenal", "confidence": 92}]
    d = build_onboarding_fuzzy_suggest_data("soccer", "Soccer", "⚽", "arsnal", suggestions=sug)
    assert d["input"] == "arsnal"
    assert len(d["suggestions"]) == 1
    assert d["suggestions"][0]["label"] == "Arsenal"


def test_fuzzy_suggest_no_suggestions():
    d = build_onboarding_fuzzy_suggest_data("soccer", "Soccer", "⚽", "xyz")
    assert d["suggestions"] == []


def test_team_celebration_matched_format():
    matched = [{"name": "Arsenal", "cheer": "YNWA!"}]
    d = build_onboarding_team_celebration_data("soccer", "Soccer", "⚽", matched=matched)
    assert len(d["matched"]) == 1
    assert d["matched"][0]["cheer"] == "YNWA!"
    assert d["summary_line"] == "1 team added."


def test_team_celebration_plural():
    matched = [{"name": "A", "cheer": "x"}, {"name": "B", "cheer": "y"}]
    d = build_onboarding_team_celebration_data("soccer", "Soccer", "⚽", matched=matched)
    assert d["summary_line"] == "2 teams added."


def test_team_celebration_unmatched():
    d = build_onboarding_team_celebration_data("soccer", "Soccer", "⚽",
                                                matched=[], unmatched=["xyz"])
    assert d["unmatched"] == ["xyz"]


def test_team_celebration_combat_header():
    d = build_onboarding_team_celebration_data("combat", "Combat", "🥊")
    assert d["header_text"] == "War room loaded!"


def test_edge_explainer_four_tiers():
    d = build_onboarding_edge_explainer_data()
    assert len(d["tiers"]) == 4
    emojis = [t["emoji"] for t in d["tiers"]]
    assert "💎" in emojis and "🥇" in emojis


def test_risk_profiles_present():
    d = build_onboarding_risk_data()
    keys = {p["key"] for p in d["profiles"]}
    assert keys == {"conservative", "moderate", "aggressive"}


def test_risk_selected_profile():
    d = build_onboarding_risk_data(current="aggressive")
    sel = [p for p in d["profiles"] if p["selected"]]
    assert len(sel) == 1
    assert sel[0]["key"] == "aggressive"


def test_bankroll_options_count():
    d = build_onboarding_bankroll_data()
    assert len(d["amounts"]) == 6


def test_bankroll_current_formatted():
    d = build_onboarding_bankroll_data(current=500.0)
    assert d["current"] == "R500"


def test_bankroll_custom_min_value():
    d = build_onboarding_bankroll_custom_data(min_value=50)
    assert d["min_value"] == 50


def test_bankroll_custom_validation_error():
    d = build_onboarding_bankroll_custom_data(validation_error="Too low")
    assert d["validation_error"] == "Too low"


def test_notify_four_options():
    d = build_onboarding_notify_data()
    assert len(d["hours"]) == 4


def test_notify_selected_hour():
    d = build_onboarding_notify_data(current_hour=18)
    sel = [h for h in d["hours"] if h["selected"]]
    assert len(sel) == 1
    assert sel[0]["value"] == 18


def test_summary_required_keys():
    ob = {
        "experience": "casual",
        "selected_sports": ["soccer"],
        "favourites": {"soccer": ["Arsenal"]},
        "risk": "moderate",
        "bankroll": 500.0,
        "notify_hour": 18,
    }
    d = build_onboarding_summary_data(ob)
    for k in ("experience_label", "sports", "risk", "bankroll_str", "notify_str"):
        assert k in d, f"missing key: {k}"


def test_summary_sports_list():
    ob = {
        "experience": "experienced",
        "selected_sports": ["soccer", "rugby"],
        "favourites": {"soccer": ["Arsenal"], "rugby": ["Bulls"]},
        "risk": "aggressive",
        "bankroll": 1000.0,
        "notify_hour": 7,
    }
    d = build_onboarding_summary_data(ob)
    assert len(d["sports"]) == 2


def test_done_features_count():
    d = build_onboarding_done_data("Paul")
    assert len(d["features"]) == 3


def test_done_default_name():
    d = build_onboarding_done_data("")
    assert d["first_name"] == "champ"


def test_done_founding_flags():
    d = build_onboarding_done_data("X", founding_offer=True, founding_days_left=3)
    assert d["founding_offer"] is True
    assert d["founding_days_left"] == 3


def test_restart_first_name():
    d = build_onboarding_restart_data(first_name="Sipho")
    assert d["first_name"] == "Sipho"


def test_restart_empty_name():
    d = build_onboarding_restart_data()
    assert d["first_name"] == ""


def test_story_quiz_step_keys():
    prompt = {"title": "Daily Picks", "body": "Get picks", "yes": "Yes", "no": "No"}
    d = build_story_quiz_step_data("daily_picks", prompt, step_num=1, total_steps=6)
    assert d["step_num"] == 1
    assert d["total_steps"] == 6
    assert d["notification_key"] == "daily_picks"
    assert d["title"] == "Daily Picks"
    assert d["body"] == "Get picks"


def test_story_quiz_step_labels():
    prompt = {"title": "T", "body": "B", "yes": "Yes please", "no": "No thanks"}
    d = build_story_quiz_step_data("edu_tips", prompt, 3, 6)
    assert d["yes_label"] == "Yes please"
    assert d["no_label"] == "No thanks"


def test_story_quiz_complete_prefs():
    prefs = {
        "daily_picks": True, "game_day_alerts": True,
        "weekly_recap": False, "edu_tips": False,
        "market_movers": False, "bankroll_updates": True,
        "live_scores": True,
    }
    d = build_story_quiz_complete_data(prefs)
    assert d["enabled_count"] == 4
    assert len(d["prefs"]) == 7


def test_story_quiz_complete_all_off():
    prefs = {k: False for k in ["daily_picks", "game_day_alerts", "weekly_recap",
                                  "edu_tips", "market_movers", "bankroll_updates", "live_scores"]}
    d = build_story_quiz_complete_data(prefs)
    assert d["enabled_count"] == 0
