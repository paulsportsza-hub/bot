"""Wave 1 subscription card data adapters — BUILD-WAVE1-SUB-01."""
from __future__ import annotations
from datetime import datetime
from pathlib import Path
from card_data import logo_b64 as _logo_b64

_BOT_DIR = Path(__file__).parent
_HEADER_LOGO = _BOT_DIR / "assets" / "LOGO" / "mzansiedge-wordmark-dark-transparent.png"

_TIER_EMOJIS: dict[str, str] = {
    "bronze": "🥉",
    "silver": "🥈",
    "gold": "🥇",
    "diamond": "💎",
}
_TIER_NAMES: dict[str, str] = {
    "bronze": "Bronze",
    "silver": "Silver",
    "gold": "Gold",
    "diamond": "Diamond",
}


def _logo() -> str:
    return _logo_b64(_HEADER_LOGO, max_height=64)


# ── 1: Plans ──────────────────────────────────────────────────────────────────

def build_sub_plans_data(
    current_tier: str = "bronze",
    founding_days_left: int = 0,
    founding_slots_remaining: int = 0,
) -> dict:
    """Plan picker — 3 tiers + optional founding offer."""
    plans = [
        {
            "name": "Bronze",
            "tier": "bronze",
            "tier_emoji": "🥉",
            "monthly_price": "Free",
            "annual_price": None,
            "annual_savings": None,
            "features": [
                "See every edge we post — badges visible across all tiers",
                "3 full detail views per day across any tier",
                "Gold edges blurred, Diamond locked until you upgrade",
                "Season hit rate and portfolio return visible to all",
                "Morning teaser with the day's top picks",
            ],
        },
        {
            "name": "Gold",
            "tier": "gold",
            "tier_emoji": "🥇",
            "monthly_price": "R99/mo",
            "annual_price": "R799/yr",
            "annual_savings": "save 33%",
            "features": [
                "Unlimited detail views — no daily cap",
                "Full card detail on every Bronze, Silver and Gold pick",
                "Line movement and full odds comparison unlocked",
                "Morning alerts cover Gold picks, not just Bronze teasers",
                "Diamond edges remain locked — upgrade to reach them",
            ],
        },
        {
            "name": "Diamond",
            "tier": "diamond",
            "tier_emoji": "💎",
            "monthly_price": "R199/mo",
            "annual_price": "R1,599/yr",
            "annual_savings": "save 33%",
            "features": [
                "Every edge unlocked — Diamond picks are Diamond-only",
                "Full AI Breakdown: Setup, Edge, Risk, Verdict on every match",
                "Personalised alerts tuned to your teams and bankroll",
                "Line movement + sharp money + CLV tracking",
                "Priority support when something doesn't look right",
            ],
        },
    ]
    founding_offer = None
    if founding_days_left > 0:
        founding_offer = {
            "days_left": founding_days_left,
            "slots_remaining": founding_slots_remaining,
            "annual_price": 699,
        }
    return {
        "current_tier": current_tier,
        "plans": plans,
        "founding_offer": founding_offer,
        "header_logo_b64": _logo(),
    }


# ── 2: Upgrade (Bronze) ───────────────────────────────────────────────────────

def build_sub_upgrade_bronze_data(founding_days_left: int = 0) -> dict:
    """Upgrade options for Bronze users."""
    target_plans = [
        {
            "name": "Gold",
            "tier": "gold",
            "tier_emoji": "🥇",
            "monthly_price": "R99/mo",
            "annual_price": "R799/yr",
            "differentiator": "Unlimited tips + real-time edges",
            "callback": "sub:tier:gold_monthly",
        },
        {
            "name": "Diamond",
            "tier": "diamond",
            "tier_emoji": "💎",
            "monthly_price": "R199/mo",
            "annual_price": "R1,599/yr",
            "differentiator": "The whole edge system, nothing held back.",
            "features": [
                "Every edge unlocked — Diamond picks are Diamond-only",
                "Full AI Breakdown: Setup, Edge, Risk, Verdict on every match",
                "Personalised alerts tuned to your teams and bankroll",
            ],
            "callback": "sub:tier:diamond_monthly",
        },
    ]
    founding_offer = None
    if founding_days_left > 0:
        founding_offer = {
            "days_left": founding_days_left,
            "annual_price": 699,
        }
    return {
        "current_tier": "bronze",
        "target_plans": target_plans,
        "founding_offer": founding_offer,
        "header_logo_b64": _logo(),
    }


# ── 3: Upgrade (Gold → Diamond) ───────────────────────────────────────────────

def build_sub_upgrade_gold_data(founding_days_left: int = 0) -> dict:
    """Upgrade pitch for Gold users going to Diamond."""
    founding_offer = None
    if founding_days_left > 0:
        founding_offer = {
            "days_left": founding_days_left,
            "annual_price": 699,
        }
    return {
        "current_tier": "gold",
        "diamond_pitch": "You're one step from our best plan.",
        "lock_note": "Diamond edges remain locked — upgrade to reach them.",
        "features": [
            "Every edge unlocked — Diamond picks are Diamond-only",
            "Full AI Breakdown: Setup, Edge, Risk, Verdict on every match",
            "Personalised alerts tuned to your teams and bankroll",
            "Line movement + sharp money + CLV tracking",
            "Priority support when something doesn't look right",
        ],
        "founding_offer": founding_offer,
        "header_logo_b64": _logo(),
    }


# ── 4: Already on Diamond ────────────────────────────────────────────────────

def build_sub_upgrade_diamond_max_data(stats_summary: dict | None = None) -> dict:
    """You're already on Diamond — max tier message."""
    return {
        "stats_summary": stats_summary,
        "header_logo_b64": _logo(),
    }


# ── 5: Payment ready ─────────────────────────────────────────────────────────

def build_sub_payment_ready_data(
    plan_name: str = "",
    price_display: str = "",
    reference: str = "",
    is_founding: bool = False,
) -> dict:
    return {
        "plan_name": plan_name,
        "price_display": price_display,
        "reference": reference,
        "is_founding": is_founding,
        "header_logo_b64": _logo(),
    }


# ── 6: Payment error ──────────────────────────────────────────────────────────

def build_sub_payment_error_data(
    error_message: str = "",
    support_handle: str = "@mzansiedge_support",
) -> dict:
    return {
        "error_message": error_message,
        "support_handle": support_handle,
        "header_logo_b64": _logo(),
    }


# ── 7: Email redirect ─────────────────────────────────────────────────────────

def build_sub_email_redirect_data() -> dict:
    return {
        "header_logo_b64": _logo(),
    }


# ── 8: Status (active paid tier) ─────────────────────────────────────────────

def build_sub_status_active_data(
    tier: str = "gold",
    plan_code: str | None = None,
    expires_label: str = "",
    days_left: int | None = None,
    member_since: str = "",
    founding_slot: int | None = None,
    founding_slots_remaining: int = 0,
) -> dict:
    return {
        "tier": tier,
        "tier_emoji": _TIER_EMOJIS.get(tier, "🥉"),
        "tier_name": _TIER_NAMES.get(tier, tier.title()),
        "plan_code": plan_code or "",
        "expires_label": expires_label,
        "days_left": days_left,
        "member_since": member_since,
        "founding_slot": founding_slot,
        "founding_slots_remaining": founding_slots_remaining,
        "header_logo_b64": _logo(),
    }


# ── 9: Status (Bronze free tier) ─────────────────────────────────────────────

def build_sub_status_bronze_data(
    daily_views_used: int = 0,
    daily_cap: int = 3,
    founding_days_left: int = 0,
    founding_slots_remaining: int = 0,
) -> dict:
    daily_pct = int((daily_views_used / daily_cap) * 100) if daily_cap > 0 else 0
    daily_pct = min(daily_pct, 100)
    founding_offer = None
    if founding_days_left > 0:
        founding_offer = {
            "days_left": founding_days_left,
            "slots_remaining": founding_slots_remaining,
            "annual_price": 699,
        }
    return {
        "daily_views_used": daily_views_used,
        "daily_cap": daily_cap,
        "daily_pct": daily_pct,
        "founding_offer": founding_offer,
        "header_logo_b64": _logo(),
    }


# ── 10: Billing (active) ──────────────────────────────────────────────────────

def build_sub_billing_active_data(
    tier: str = "gold",
    plan_code: str = "",
    member_since: str = "",
    next_renewal: str = "",
    is_founding: bool = False,
    founding_slot: int | None = None,
) -> dict:
    return {
        "tier": tier,
        "tier_emoji": _TIER_EMOJIS.get(tier, "🥉"),
        "tier_name": _TIER_NAMES.get(tier, tier.title()),
        "plan_code": plan_code,
        "member_since": member_since,
        "next_renewal": next_renewal,
        "is_founding": is_founding,
        "founding_slot": founding_slot,
        "header_logo_b64": _logo(),
    }


# ── 11: Billing (inactive) ───────────────────────────────────────────────────

def build_sub_billing_inactive_data(
    last_plan: str | None = None,
    ended_at: str = "",
) -> dict:
    return {
        "last_plan": last_plan,
        "ended_at": ended_at,
        "header_logo_b64": _logo(),
    }


# ── 12: Cancel confirm ───────────────────────────────────────────────────────

def build_sub_cancel_confirm_data(
    plan_name: str = "",
    access_until: str = "",
) -> dict:
    return {
        "plan_name": plan_name,
        "access_until": access_until,
        "header_logo_b64": _logo(),
    }


# ── 12b: Payment confirmed (Gold/Diamond non-founding) ──────────────────────

def build_sub_payment_confirmed_data(
    user,
    plan_code: str,
    amount_cents: int,
    expires_at,
) -> dict:
    """Build data dict for sub_payment_confirmed.html card.

    Maps plan_code → plan_label + tier_badge via STITCH_PRODUCTS lookup.
    Formats expires_at as '21 May 2026'. Amount is in cents.
    """
    import config as _cfg

    _plan = _cfg.STITCH_PRODUCTS.get(plan_code, {})
    _tier = _plan.get("tier", "gold" if "gold" in plan_code else "diamond")
    _period = _plan.get("period", "annual" if "annual" in plan_code else "monthly")
    _tier_badge = "💎" if _tier == "diamond" else "🥇"

    # plan_label: e.g. "Gold Monthly", "Diamond Annual"
    _plan_label = f"{_tier.title()} {_period.title()}"

    # amount_zar: use STITCH_PRODUCTS price if available, else from amount_cents
    _price_cents = _plan.get("price", amount_cents)
    _amount_zar = f"R{_price_cents // 100}"

    # renewal_cadence
    _cadence = "Renews annually" if _period == "annual" else "Renews monthly"

    # expires_at_human: '21 May 2026'
    if expires_at is not None:
        try:
            _expires_str = expires_at.strftime("%-d %b %Y")
        except Exception:
            _expires_str = str(expires_at)[:10]
    else:
        _expires_str = "—"

    _first_name = getattr(user, "first_name", None) or ""

    return {
        "first_name": _first_name,
        "plan_label": _plan_label,
        "tier": _tier,
        "tier_badge": _tier_badge,
        "amount_zar": _amount_zar,
        "expires_at_human": _expires_str,
        "renewal_cadence": _cadence,
        "header_logo_b64": _logo(),
    }


# ── 13: Cancel done ──────────────────────────────────────────────────────────

def build_sub_cancel_done_data(access_until: str = "") -> dict:
    return {
        "access_until": access_until,
        "header_logo_b64": _logo(),
    }


# ── 14: Founding confirmed ───────────────────────────────────────────────────

def build_sub_founding_confirmed_data(
    slot_number: int = 1,
    founding_price_cents: int = 69900,
) -> dict:
    price_rands = founding_price_cents // 100
    return {
        "slot_number": slot_number,
        "founding_price": f"R{price_rands}",
        "benefits": [
            "Full Diamond access for 1 year",
            "Price locked at R699/yr — forever",
            "Real-time edges + line movement",
            "Sharp money + CLV tracking",
            "Founding member badge",
        ],
        "joined_label": datetime.now().strftime("%-d %b %Y"),
        "header_logo_b64": _logo(),
    }


# ── 15: Founding sold out ─────────────────────────────────────────────────────

def build_sub_founding_soldout_data() -> dict:
    return {
        "header_logo_b64": _logo(),
    }


# ── 16: Founding offer ended ──────────────────────────────────────────────────

def build_sub_founding_ended_data(
    diamond_monthly: int = 199,
    diamond_annual: int = 1599,
) -> dict:
    return {
        "diamond_monthly": diamond_monthly,
        "diamond_annual": diamond_annual,
        "header_logo_b64": _logo(),
    }


# ── 17: Founding live offer ───────────────────────────────────────────────────

def build_sub_founding_live_data(
    days_left: int = 7,
    slots_remaining: int = 42,
    annual_price: int = 699,
    normal_monthly: int = 199,
) -> dict:
    monthly_equiv = annual_price // 12
    normal_annual = normal_monthly * 12
    savings_pct = round((1 - annual_price / normal_annual) * 100) if normal_annual > 0 else 0
    return {
        "days_left": days_left,
        "slots_remaining": slots_remaining,
        "annual_price": annual_price,
        "monthly_equiv": monthly_equiv,
        "normal_monthly": normal_monthly,
        "savings_pct": savings_pct,
        "header_logo_b64": _logo(),
    }


# ── 18: Subscription expiry notice ───────────────────────────────────────────

def build_sub_expiry_notice_data(
    old_tier: str = "gold",
    old_tier_emoji: str = "",
) -> dict:
    emoji = old_tier_emoji or _TIER_EMOJIS.get(old_tier, "🥉")
    return {
        "old_tier": old_tier,
        "old_tier_emoji": emoji,
        "old_tier_name": _TIER_NAMES.get(old_tier, old_tier.title()),
        "new_tier": "bronze",
        "header_logo_b64": _logo(),
    }


# ── 19: Trial expiry ─────────────────────────────────────────────────────────

def build_sub_trial_expiry_data(
    days_used: int = 7,
    hit_rate: float = 0.0,
) -> dict:
    return {
        "days_used": days_used,
        "hit_rate_pct": round(hit_rate * 100),
        "header_logo_b64": _logo(),
    }


# ── Wave 2: Onboarding card adapters (BUILD-WAVE2-ONBOARDING-01) ─────────────

_RISK_DISPLAY = {
    "conservative": {"emoji": "🛡️", "label": "Conservative", "desc": "Lower risk, steady returns", "ev": "≥5% EV"},
    "moderate":     {"emoji": "⚖️", "label": "Moderate",     "desc": "Balanced risk and reward",   "ev": "≥3% EV"},
    "aggressive":   {"emoji": "🚀", "label": "Aggressive",   "desc": "Higher risk, higher upside", "ev": "≥1% EV"},
}

_BANKROLL_OPTIONS = [
    {"value": "50",    "label": "R50",    "sub": "Getting started"},
    {"value": "200",   "label": "R200",   "sub": "Casual player"},
    {"value": "500",   "label": "R500",   "sub": "Committed bettor"},
    {"value": "1000",  "label": "R1,000", "sub": "Serious punter"},
    {"value": "skip",  "label": "Skip",   "sub": "Set it later"},
    {"value": "custom","label": "Custom", "sub": "Type your amount"},
]

_NOTIFY_OPTIONS = [
    {"value": 7,  "emoji": "🌅", "label": "07:00", "desc": "Morning picks"},
    {"value": 12, "emoji": "☀️", "label": "12:00", "desc": "Midday update"},
    {"value": 18, "emoji": "🌆", "label": "18:00", "desc": "Evening briefing"},
    {"value": 21, "emoji": "🌙", "label": "21:00", "desc": "Night owl"},
]


def build_onboarding_welcome_data(first_name: str, is_returning: bool = False,
                                   trial_started: bool = False, trial_days: int = 7,
                                   founding_offer: bool = False,
                                   founding_days_left: int = 0) -> dict:
    return {
        "header_logo_b64": _logo(),
        "first_name": first_name or "champ",
        "is_returning": is_returning,
        "trial_started": trial_started,
        "trial_days": trial_days,
        "founding_offer": founding_offer,
        "founding_days_left": founding_days_left,
    }


def build_onboarding_experience_data() -> dict:
    return {
        "header_logo_b64": _logo(),
        "options": [
            {"label": "I bet regularly",        "emoji": "🎯", "value": "experienced"},
            {"label": "I've placed a few bets", "emoji": "🤔", "value": "casual"},
            {"label": "I'm completely new",     "emoji": "🆕", "value": "newbie"},
        ],
    }


def build_onboarding_sports_data(selected_sports: list[str] | None = None) -> dict:
    try:
        import config
        all_sports = list(config.SPORTS)
    except Exception:
        all_sports = []

    selected = set(selected_sports or [])
    sports_data = []
    for s in all_sports:
        sports_data.append({
            "key": s.key,
            "emoji": s.emoji,
            "label": s.label,
            "selected": s.key in selected,
        })
    return {
        "header_logo_b64": _logo(),
        "step": 2,
        "total_steps": 5,
        "sports": sports_data,
        "selected_count": len(selected),
    }


def build_onboarding_favourites_data(sport_key: str, sport_label: str, sport_emoji: str,
                                      teams: list[dict] | None = None,
                                      selected_count: int = 0) -> dict:
    return {
        "header_logo_b64": _logo(),
        "step": 3,
        "total_steps": 5,
        "sport": {"key": sport_key, "emoji": sport_emoji, "label": sport_label},
        "teams": teams or [],
        "selected_count": selected_count,
    }


def build_onboarding_favourites_manual_data(sport_key: str, sport_label: str,
                                             sport_emoji: str, fav_label: str = "team",
                                             example: str = "") -> dict:
    return {
        "header_logo_b64": _logo(),
        "step": 3,
        "total_steps": 5,
        "sport": {"key": sport_key, "emoji": sport_emoji, "label": sport_label},
        "fav_label": fav_label,
        "example": example,
    }


def build_onboarding_fuzzy_suggest_data(sport_key: str, sport_label: str, sport_emoji: str,
                                         input_text: str,
                                         suggestions: list[dict] | None = None) -> dict:
    return {
        "header_logo_b64": _logo(),
        "sport": {"key": sport_key, "emoji": sport_emoji, "label": sport_label},
        "input": input_text,
        "suggestions": suggestions or [],
    }


def build_onboarding_team_celebration_data(sport_key: str, sport_label: str,
                                            sport_emoji: str,
                                            matched: list[dict] | None = None,
                                            unmatched: list[str] | None = None) -> dict:
    matched = matched or []
    unmatched = unmatched or []
    count = len(matched)
    _headers = {
        "soccer": "Nice picks!", "rugby": "Nice picks!",
        "cricket": "Nice picks!", "combat": "War room loaded!",
    }
    return {
        "header_logo_b64": _logo(),
        "sport_emoji": sport_emoji,
        "sport_label": sport_label,
        "header_text": _headers.get(sport_key, "Nice picks!"),
        "matched": matched,
        "unmatched": unmatched,
        "summary_line": f"{count} {'team' if count == 1 else 'teams'} added.",
    }


def build_onboarding_edge_explainer_data() -> dict:
    return {
        "header_logo_b64": _logo(),
        "tiers": [
            {"emoji": "💎", "label": "Diamond Edge", "desc": "When you see this, you MOVE. Extremely rare, high confidence.", "color": "#B9F2FF"},
            {"emoji": "🥇", "label": "Golden Edge",  "desc": "Strong value. These are the bets that build bankrolls.", "color": "#FFD700"},
            {"emoji": "🥈", "label": "Silver Edge",  "desc": "Solid edge. The numbers say there's value here.", "color": "#A0AEC0"},
            {"emoji": "🥉", "label": "Bronze Edge",  "desc": "Small but positive. Worth considering.", "color": "#CD7F32"},
        ],
    }


def build_onboarding_risk_data(current: str | None = None) -> dict:
    profiles = []
    for key, meta in _RISK_DISPLAY.items():
        profiles.append({
            "key": key, "emoji": meta["emoji"], "label": meta["label"],
            "desc": meta["desc"], "ev": meta["ev"],
            "selected": key == current,
        })
    return {
        "header_logo_b64": _logo(),
        "step": 4,
        "total_steps": 5,
        "profiles": profiles,
    }


def build_onboarding_bankroll_data(current: float | None = None) -> dict:
    return {
        "header_logo_b64": _logo(),
        "step": 5,
        "total_steps": 5,
        "amounts": _BANKROLL_OPTIONS,
        "current": f"R{current:,.0f}" if current else None,
    }


def build_onboarding_bankroll_custom_data(validation_error: str = "",
                                           min_value: int = 20) -> dict:
    return {
        "header_logo_b64": _logo(),
        "step": 5,
        "total_steps": 5,
        "validation_error": validation_error,
        "min_value": min_value,
    }


def build_onboarding_notify_data(current_hour: int | None = None) -> dict:
    options = [{**opt, "selected": opt["value"] == current_hour}
               for opt in _NOTIFY_OPTIONS]
    return {
        "header_logo_b64": _logo(),
        "step": 4,
        "total_steps": 6,
        "hours": options,
        "current": current_hour,
    }


def build_onboarding_summary_data(ob: dict) -> dict:
    try:
        import config
        exp_labels = {
            "experienced": "I bet regularly",
            "casual":      "I bet sometimes",
            "newbie":      "I'm new to betting",
        }
        exp = ob.get("experience") or "casual"
        sports = []
        for sk in ob.get("selected_sports", []):
            sport = config.ALL_SPORTS.get(sk)
            favs = ob.get("favourites", {}).get(sk, [])
            if isinstance(favs, dict):
                flat: list[str] = []
                for v in favs.values():
                    flat.extend(v)
                favs = flat
            sports.append({
                "emoji": sport.emoji if sport else "🏅",
                "label": sport.label if sport else sk,
                "teams": favs,
            })
        risk_raw = config.RISK_PROFILES.get(ob.get("risk") or "moderate", {}).get("label", "Moderate")
        risk_label = risk_raw.split(" ", 1)[-1] if " " in risk_raw else risk_raw
        hour = ob.get("notify_hour")
        notify_map = {7: "07:00 SAST", 12: "12:00 SAST", 18: "18:00 SAST", 21: "21:00 SAST"}
        notify_str = notify_map.get(hour, f"{hour}:00") if hour is not None else "Not set"
        bankroll = ob.get("bankroll")
        bankroll_str = f"R{bankroll:,.0f}" if bankroll else "Not set"
    except Exception:
        exp = ob.get("experience", "casual")
        exp_labels = {"experienced": "Regular bettor", "casual": "Casual", "newbie": "Newbie"}
        sports = []
        risk_label = ob.get("risk", "Moderate")
        notify_str = "Not set"
        bankroll_str = "Not set"
    return {
        "header_logo_b64": _logo(),
        "step": 5,
        "total_steps": 5,
        "experience_label": exp_labels.get(exp, exp),
        "sports": sports,
        "risk": risk_label,
        "bankroll_str": bankroll_str,
        "notify_str": notify_str,
    }


def build_onboarding_done_data(first_name: str, trial_started: bool = False,
                                trial_days: int = 7, founding_offer: bool = False,
                                founding_days_left: int = 0) -> dict:
    features = [
        {"emoji": "⚽", "title": "My Matches",     "desc": "Personalised 7-day schedule with Edge-AI on every game."},
        {"emoji": "💎", "title": "Top Edge Picks", "desc": "I scan all SA bookmakers and find exactly where the Edge is."},
        {"emoji": "🔔", "title": "Edge Alerts",    "desc": "Daily picks, game day alerts, market movers, live scores."},
    ]
    return {
        "header_logo_b64": _logo(),
        "first_name": first_name or "champ",
        "trial_started": trial_started,
        "trial_days": trial_days,
        "founding_offer": founding_offer,
        "founding_days_left": founding_days_left,
        "features": features,
    }


def build_story_quiz_step_data(step_key: str, prompt: dict, step_num: int,
                                total_steps: int) -> dict:
    return {
        "header_logo_b64": _logo(),
        "step_num": step_num,
        "total_steps": total_steps,
        "notification_key": step_key,
        "title": prompt.get("title", ""),
        "body": prompt.get("body", ""),
        "yes_label": prompt.get("yes", "Yes"),
        "no_label": prompt.get("no", "No"),
    }


def build_story_quiz_complete_data(prefs: dict) -> dict:
    labels = {
        "daily_picks":      "Daily AI picks",
        "game_day_alerts":  "Game day alerts",
        "weekly_recap":     "Weekly recaps",
        "edu_tips":         "Education tips",
        "market_movers":    "Market movers",
        "bankroll_updates": "Bankroll updates",
        "live_scores":      "Live score updates",
    }
    pref_items = [{"key": k, "label": l, "enabled": prefs.get(k, False)}
                  for k, l in labels.items()]
    return {
        "header_logo_b64": _logo(),
        "prefs": pref_items,
        "enabled_count": sum(1 for p in pref_items if p["enabled"]),
    }


def build_onboarding_restart_data(first_name: str = "") -> dict:
    return {
        "header_logo_b64": _logo(),
        "first_name": first_name or "",
    }


def _sport_emoji(sport: str | None) -> str:
    if not sport:
        return "🏆"
    s = (sport or "").lower()
    if "soccer" in s or "football" in s:
        return "⚽"
    if "rugby" in s:
        return "🏉"
    if "cricket" in s:
        return "🏏"
    if "tennis" in s:
        return "🎾"
    if "basket" in s:
        return "🏀"
    if "boxing" in s or "mma" in s:
        return "🥊"
    return "🏆"


def _match_key_to_display(match_key: str) -> str:
    """Convert 'gujarat_titans_vs_mumbai_indians_2026-04-20' -> 'Gujarat Titans vs Mumbai Indians'."""
    import re as _re
    cleaned = _re.sub(r"_\d{4}-\d{2}-\d{2}$", "", match_key)
    parts = cleaned.replace("_", " ").title()
    parts = _re.sub(r"\bVs\b", "vs", parts)
    return parts[:45]


_TIER_LABELS = {
    "diamond": "DIA",
    "gold": "GOLD",
    "silver": "SIL",
    "bronze": "BRZ",
}


def build_home_winners_data(wins: list) -> dict:
    """Data for home_winners.html — last 5 resolved wins, gold-priority order."""
    rows = []
    for w in wins:
        if isinstance(w, dict):
            odds = w.get("recommended_odds") or 0.0
            actual_return = w.get("actual_return")
            return_zar = f"R{int(actual_return)}" if actual_return else (f"R{round(100 * odds)}" if odds else "—")
            tier = (w.get("edge_tier") or "bronze").lower()
            t_emoji = _TIER_EMOJIS.get(tier, "🥉")
            bet_type = (w.get("bet_type") or "").strip()
            odds_str = f"{odds:.2f}" if odds else "—"
            bet_line = f"{t_emoji} {bet_type} @ {odds_str}" if bet_type else odds_str
            rows.append({
                "match": _match_key_to_display(w.get("match_key", "Unknown")),
                "bet_line": bet_line,
                "return_zar": return_zar,
                "sport_emoji": _sport_emoji(w.get("sport", "")),
                "tier": tier,
            })
        else:
            odds = getattr(w, "odds", None) or 0.0
            return_zar = round(100 * odds) if odds else None
            tier = "bronze"
            t_emoji = _TIER_EMOJIS.get(tier, "🥉")
            bet_type = (getattr(w, "prediction", None) or "").strip()
            odds_str = f"{odds:.2f}" if odds else "—"
            bet_line = f"{t_emoji} {bet_type} @ {odds_str}" if bet_type else odds_str
            rows.append({
                "match": (getattr(w, "match", None) or "Unknown")[:40],
                "bet_line": bet_line,
                "return_zar": f"R{return_zar}" if return_zar else "—",
                "sport_emoji": _sport_emoji(getattr(w, "sport", "")),
                "tier": tier,
            })
    return {
        "wins": rows,
        "header_logo_b64": _logo(),
        "total_count": len(rows),
    }


# ── Wave 3: Notification Templates (BUILD-WAVE3-NOTIFICATIONS-01) ─────────────

def build_notify_morning_bronze_data(
    free_picks: list | None = None,
    locked_count: int = 0,
    upgrade_cta: bool = True,
    hit_rate_7d: float = 0.0,
    results_block: str = "",
) -> dict:
    """Morning teaser for Bronze users — tease locked picks, drive upgrade."""
    return {
        "free_picks": free_picks or [],
        "locked_count": locked_count,
        "upgrade_cta": upgrade_cta,
        "hit_rate_7d": hit_rate_7d,
        "hit_rate_pct": f"{hit_rate_7d * 100:.0f}",
        "results_block": results_block,
        "header_logo_b64": _logo(),
    }


def build_notify_morning_gold_data(
    top_pick: dict | None = None,
    diamond_fomo: str = "",
    hit_rate_7d: float = 0.0,
    tip_count: int = 0,
    results_block: str = "",
) -> dict:
    """Morning teaser for Gold users — best pick + diamond FOMO."""
    return {
        "top_pick": top_pick or {},
        "diamond_fomo": diamond_fomo,
        "hit_rate_7d": hit_rate_7d,
        "hit_rate_pct": f"{hit_rate_7d * 100:.0f}",
        "tip_count": tip_count,
        "results_block": results_block,
        "header_logo_b64": _logo(),
    }


def build_notify_morning_diamond_data(
    top_pick: dict | None = None,
    tip_count: int = 0,
    results_block: str = "",
    hit_rate_7d: float = 0.0,
) -> dict:
    """Morning teaser for Diamond users — clean, confident, full picture."""
    return {
        "top_pick": top_pick or {},
        "tip_count": tip_count,
        "results_block": results_block,
        "hit_rate_7d": hit_rate_7d,
        "header_logo_b64": _logo(),
    }


def build_notify_morning_no_tips_data(
    tomorrow_preview: list | None = None,
    browse_cta: str = "Check back later",
) -> dict:
    """Morning card when no tips found — keep user engaged."""
    return {
        "tomorrow_preview": tomorrow_preview or [],
        "browse_cta": browse_cta,
        "header_logo_b64": _logo(),
    }


def build_notify_weekend_preview_data(
    preview_count: int = 0,
    top_3: list | None = None,
    weekend_leagues: list | None = None,
    user_tier: str = "bronze",
) -> dict:
    """Thursday 18:00 weekend preview."""
    return {
        "preview_count": preview_count,
        "top_3": top_3 or [],
        "weekend_leagues": weekend_leagues or [],
        "user_tier": user_tier,
        "header_logo_b64": _logo(),
    }


def build_notify_monday_recap_data(
    hit_rate_7d: float = 0.0,
    total_edges: int = 0,
    hits: int = 0,
    top_hits: list | None = None,
    misses_count: int = 0,
    portfolio_return: str = "",
    user_tier: str = "bronze",
) -> dict:
    """Monday 08:00 weekend scorecard."""
    return {
        "hit_rate_7d": hit_rate_7d,
        "hit_rate_pct": f"{hit_rate_7d * 100:.0f}",
        "total_edges": total_edges,
        "hits": hits,
        "top_hits": top_hits or [],
        "misses_count": misses_count,
        "portfolio_return": portfolio_return,
        "user_tier": user_tier,
        "header_logo_b64": _logo(),
    }


def build_notify_monthly_report_data(
    month: str = "",
    hit_rate: float = 0.0,
    total_edges: int = 0,
    hits: int = 0,
    roi: float = 0.0,
    best_tier: str = "",
    total_profit: str = "",
    tier_breakdown: list | None = None,
    responsible_footer: bool = True,
) -> dict:
    """Monthly account statement — DETAIL 480×620."""
    return {
        "month": month,
        "hit_rate": hit_rate,
        "hit_rate_pct": f"{hit_rate * 100:.0f}",
        "total_edges": total_edges,
        "hits": hits,
        "roi": roi,
        "roi_str": f"{roi:+.1f}",
        "best_tier": best_tier,
        "total_profit": total_profit,
        "tier_breakdown": tier_breakdown or [],
        "responsible_footer": responsible_footer,
        "header_logo_b64": _logo(),
    }


def build_notify_result_hit_data(
    match: str = "",
    pick: str = "",
    odds: float = 0.0,
    profit_on_R100: str = "",
    season_accuracy: str = "",
    tier: str = "bronze",
    tier_emoji: str = "",
    score: str = "",
) -> dict:
    """Result alert — edge hit."""
    return {
        "match": match,
        "pick": pick,
        "odds": odds,
        "odds_str": f"{odds:.2f}",
        "profit_on_R100": profit_on_R100,
        "season_accuracy": season_accuracy,
        "tier": tier,
        "tier_emoji": tier_emoji,
        "score": score,
        "header_logo_b64": _logo(),
    }


def build_notify_result_miss_data(
    match: str = "",
    pick: str = "",
    odds: float = 0.0,
    loss_on_R100: str = "",
    season_accuracy: str = "",
    transparency_note: str = "",
    tier: str = "bronze",
    tier_emoji: str = "",
    score: str = "",
    consecutive_misses: int = 0,
) -> dict:
    """Result alert — edge missed."""
    return {
        "match": match,
        "pick": pick,
        "odds": odds,
        "odds_str": f"{odds:.2f}",
        "loss_on_R100": loss_on_R100,
        "season_accuracy": season_accuracy,
        "transparency_note": transparency_note,
        "tier": tier,
        "tier_emoji": tier_emoji,
        "score": score,
        "consecutive_misses": consecutive_misses,
        "header_logo_b64": _logo(),
    }


def build_notify_result_bundle_data(
    hits: int = 0,
    misses: int = 0,
    total: int = 0,
    net_on_R100: str = "",
    accuracy_window: str = "",
) -> dict:
    """Bundle result when 3+ edges settle together."""
    return {
        "hits": hits,
        "misses": misses,
        "total": total,
        "net_on_R100": net_on_R100,
        "accuracy_window": accuracy_window,
        "header_logo_b64": _logo(),
    }


def build_notify_pre_match_gold_data(
    match: str = "",
    kickoff_in: str = "",
    pick: str = "",
    odds: float = 0.0,
    bookmaker_url: str = "",
    tier: str = "gold",
    tier_emoji: str = "🥇",
    league: str = "",
    ev: float = 0.0,
) -> dict:
    """Pre-match Gold/Diamond urgency alert."""
    return {
        "match": match,
        "kickoff_in": kickoff_in,
        "pick": pick,
        "odds": odds,
        "odds_str": f"{odds:.2f}",
        "bookmaker_url": bookmaker_url,
        "tier": tier,
        "tier_emoji": tier_emoji,
        "league": league,
        "ev": ev,
        "ev_str": f"+{ev:.1f}",
        "header_logo_b64": _logo(),
    }


def build_notify_reengagement_data(
    days_since_active: int = 0,
    edges_missed: int = 0,
    return_cta: str = "",
    responsible_footer: bool = True,
    settlement_stats: dict | None = None,
    best_hit: dict | None = None,
) -> dict:
    """Re-engagement nudge — warm, not pushy."""
    return {
        "days_since_active": days_since_active,
        "edges_missed": edges_missed,
        "return_cta": return_cta,
        "responsible_footer": responsible_footer,
        "settlement_stats": settlement_stats or {},
        "best_hit": best_hit,
        "header_logo_b64": _logo(),
    }


def build_notify_reengagement_lighter_data(
    days_since_active: int = 0,
    settlement_stats: dict | None = None,
    mute_cta: str = "Mute for 7 days with /mute week",
) -> dict:
    """Lighter re-engagement — stats-forward, mute option prominent."""
    return {
        "days_since_active": days_since_active,
        "settlement_stats": settlement_stats or {},
        "mute_cta": mute_cta,
        "header_logo_b64": _logo(),
    }


def build_notify_mute_confirm_data(
    duration_label: str = "24 hours",
    resumes_at: str = "",
) -> dict:
    """Mute confirmation card."""
    return {
        "duration_label": duration_label,
        "resumes_at": resumes_at,
        "header_logo_b64": _logo(),
    }


def build_notify_mute_resume_data(
    resumed_at: str = "",
    next_notification_at: str = "",
) -> dict:
    """Mute-lifted notification."""
    return {
        "resumed_at": resumed_at,
        "next_notification_at": next_notification_at,
        "header_logo_b64": _logo(),
    }


def build_notify_live_score_data(
    home: str = "",
    away: str = "",
    home_score: int = 0,
    away_score: int = 0,
    event_label: str = "",
    league: str = "",
    completed: bool = False,
) -> dict:
    """Live score update (in-progress)."""
    return {
        "home": home,
        "away": away,
        "home_score": home_score,
        "away_score": away_score,
        "event_label": event_label,
        "league": league,
        "completed": completed,
        "header_logo_b64": _logo(),
    }


def build_notify_live_score_ft_data(
    home: str = "",
    away: str = "",
    home_score: int = 0,
    away_score: int = 0,
    event_label: str = "FT",
    winner_label: str = "",
    settled_edge: dict | None = None,
) -> dict:
    """Full time score — optional settled edge result."""
    return {
        "home": home,
        "away": away,
        "home_score": home_score,
        "away_score": away_score,
        "event_label": event_label,
        "winner_label": winner_label,
        "settled_edge": settled_edge,
        "header_logo_b64": _logo(),
    }


# ── BUILD-PROFILE-CARD-01 ─────────────────────────────────────────────────────

def build_profile_card_data(
    first_name: str = "",
    tier: str = "bronze",
    trial_active: bool = False,
    trial_day: int | None = None,
    trial_total_days: int | None = None,
    trial_days_remaining: int | None = None,
    is_founding_member: bool = False,
    member_since: str = "",
    member_label: str = "Joined",
    days_as_member: int | None = None,
    edge_7d_has_data: bool = False,
    edge_7d_hits: int = 0,
    edge_7d_total: int = 0,
    edge_7d_hit_pct: float = 0.0,
    edge_7d_roi: float | None = None,
    edge_7d_streak: str = "",
    total_views: int = 0,
    recent_views: int = 0,
    focus_sport: str = "",
    experience_label: str = "",
    risk_label: str = "",
    bankroll_str: str = "",
    sports: list[dict] | None = None,
) -> dict:
    """Profile home image card — BUILD-PROFILE-CARD-01."""
    tier = (tier or "bronze").lower()
    tier_emoji = _TIER_EMOJIS.get(tier, "🥉")
    tier_name = _TIER_NAMES.get(tier, tier.title())

    sport_rows: list[dict] = []
    for s in (sports or []):
        teams: list[str] = []
        for lg in s.get("leagues", []):
            teams.extend(lg.get("teams", []))
        seen: set[str] = set()
        deduped: list[str] = []
        for t in teams:
            if t not in seen:
                deduped.append(t)
                seen.add(t)
        preview = ", ".join(deduped[:4])
        if len(deduped) > 4:
            preview += f" +{len(deduped) - 4} more"
        sport_rows.append({
            "emoji": s.get("emoji", "🏅"),
            "label": s.get("label", ""),
            "team_preview": preview,
        })

    return {
        "first_name": first_name,
        "tier": tier,
        "tier_emoji": tier_emoji,
        "tier_name": tier_name,
        "trial_active": trial_active,
        "trial_day": trial_day,
        "trial_total_days": trial_total_days,
        "trial_days_remaining": trial_days_remaining,
        "is_founding_member": is_founding_member,
        "member_since": member_since,
        "member_label": member_label,
        "days_as_member": days_as_member,
        "edge_7d_has_data": edge_7d_has_data,
        "edge_7d_hits": edge_7d_hits,
        "edge_7d_total": edge_7d_total,
        "edge_7d_hit_pct": edge_7d_hit_pct,
        "edge_7d_roi": edge_7d_roi,
        "edge_7d_streak": edge_7d_streak,
        "total_views": total_views,
        "recent_views": recent_views,
        "focus_sport": focus_sport,
        "experience_label": experience_label,
        "risk_label": risk_label,
        "bankroll_str": bankroll_str,
        "sports": sport_rows,
        "header_logo_b64": _logo(),
    }
