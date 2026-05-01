#!/usr/bin/env python3
"""
MzansiEdge QA Gallery Generator — real builders, mirrors bot 1:1.
Usage: python3 scripts/generate_qa_gallery.py
"""
import sys
from pathlib import Path
from datetime import date

BOT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BOT_ROOT))

from card_renderer import render_card_sync
from card_data import (
    build_edge_detail_data,
    build_edge_picks_data,
    build_edge_summary_data,
    build_my_matches_data,
    build_match_detail_data,
    build_tier_page_data,
    logo_b64 as _card_logo_b64,
)
import card_data_adapters as cda

TEMPLATES_DIR = BOT_ROOT / "card_templates"
OUTPUT_BASE   = BOT_ROOT / "static" / "qa-gallery"
TODAY         = date.today().isoformat()
OUTPUT_DIR    = OUTPUT_BASE / TODAY
LATEST_LINK   = OUTPUT_BASE / "latest"

_LOGO_PATH = BOT_ROOT / "assets" / "LOGO" / "mzansiedge-wordmark-dark-transparent.png"

# ---------------------------------------------------------------------------
# Inlined tier_lock (avoids heavy card_pipeline import)
# ---------------------------------------------------------------------------
_TL_PRICE  = {"bronze": "Free", "gold": "R99", "diamond": "R199"}
_TL_COLOUR = {"diamond": "#B9F2FF", "gold": "#FFD700", "silver": "#C0C0C0", "bronze": "#CD7F32"}
_SE_MAP    = {"soccer": "⚽", "football": "⚽", "rugby": "🏉", "cricket": "🏏",
              "mma": "🥊", "boxing": "🥊", "tennis": "🎾", "basketball": "🏀"}

def _sport_emoji_tl(sport_key: str) -> str:
    for k, v in _SE_MAP.items():
        if k in (sport_key or "").lower():
            return v
    return "🏅"

def _build_tier_lock(edge_tier, home, away, sport_key, league,
                     kickoff_str, broadcast, confirming_signals, tracker_summary=None):
    ts  = tracker_summary or {}
    hr  = ts.get("hit_rate_7d") or 0
    roi = ts.get("roi_7d") or 0
    roi_str = f"+R{int(roi)}" if roi >= 0 else f"-R{abs(int(roi))}"
    tier = (edge_tier or "gold").lower()
    return {
        "header_logo_b64": _card_logo_b64(_LOGO_PATH, max_height=64),
        "edge_tier": tier,
        "edge_tier_display": tier.title(),
        "tier_colour": _TL_COLOUR.get(tier, "#FFD700"),
        "sport_emoji": _sport_emoji_tl(sport_key),
        "home": home,  "away": away,  "league": league,
        "kickoff": kickoff_str,
        "broadcast": broadcast or "",
        "confirming_signals": confirming_signals or 0,
        "hit_rate_7d": str(int(hr)),
        "roi_7d": roi_str,
        "price": _TL_PRICE.get(tier, "R199"),
    }

# ---------------------------------------------------------------------------
# Sample raw tip inputs → passed to real builders
# ---------------------------------------------------------------------------
GOLD_TIP = {
    "display_tier": "gold",
    "home": "Kaizer Chiefs", "away": "Mamelodi Sundowns",
    "league": "DStv Premiership", "sport_emoji": "⚽",
    "date": "Sat 26 Apr", "time": "15:30",
    "pick": "Kaizer Chiefs to Win", "pick_odds": 2.40, "odds": 2.40,
    "ev": 12.5, "bookmaker": "Betway",
    "all_odds": [
        {"bookie": "Betway", "odds": 2.40, "is_pick": True},
        {"bookie": "Hollywoodbets", "odds": 2.35},
        {"bookie": "10bet", "odds": 2.30},
    ],
    "signals": {"price_edge": True, "form": True, "line_mvt": False,
                "market": True, "tipster": False, "injury": False},
    "home_form": ["W", "W", "D", "W", "L"], "away_form": ["W", "L", "W", "D", "W"],
    "fair_value": 72, "confidence": 81,
    "h2h": {"n": 10, "hw": 5, "d": 2, "aw": 3},
    "home_injuries": [], "away_injuries": [],
    "verdict": "Chiefs have won 4 of their last 5 home fixtures against Sundowns. Value confirmed at 2.40.",
    "channel": "SuperSport 211",
}
DIAMOND_TIP = {
    **GOLD_TIP, "display_tier": "diamond",
    "home": "Manchester City", "away": "Arsenal",
    "league": "Premier League", "date": "Sun 27 Apr", "time": "16:00",
    "pick": "Both Teams to Score", "pick_odds": 1.85, "odds": 1.85,
    "ev": 18.3, "confidence": 91, "fair_value": 84,
    "verdict": "Both sides scored in 8 of last 10 H2H. City's leaky defence makes BTTS the value call.",
}
SILVER_TIP = {
    **GOLD_TIP, "display_tier": "silver",
    "home": "Stormers", "away": "Bulls", "league": "URC", "sport_emoji": "🏉",
    "pick": "Stormers -4.5", "pick_odds": 1.95, "odds": 1.95, "ev": 7.2,
    "confidence": 68, "fair_value": 60,
    "verdict": "Stormers at home covered -4.5 in 6 of last 8. Line value confirmed.",
}
BRONZE_TIP = {
    **GOLD_TIP, "display_tier": "bronze",
    "home": "Proteas", "away": "India", "league": "T20 International", "sport_emoji": "🏏",
    "pick": "Proteas to Win", "pick_odds": 2.10, "odds": 2.10, "ev": 4.1,
    "confidence": 55, "fair_value": 52,
    "verdict": "Proteas back on home soil. Mild lean.",
}
ALL_TIPS = [DIAMOND_TIP, GOLD_TIP, SILVER_TIP, BRONZE_TIP]

EDGE_MATCH = {
    "has_edge": True,
    "home": "Kaizer Chiefs", "away": "Mamelodi Sundowns",
    "league": "DStv Premiership", "sport_emoji": "⚽",
    "date": "Sat 26 Apr", "time": "15:30", "channel": "SuperSport 211",
    "edge_tier": "gold", "pick": "Kaizer Chiefs to Win", "bookmaker": "Betway",
}
PLAIN_MATCH = {
    "has_edge": False,
    "home": "Stormers", "away": "Bulls",
    "league": "URC", "sport_emoji": "🏉",
    "date": "Sat 26 Apr", "time": "17:00", "channel": "SuperSport 4",
    "odds_home": 1.80, "odds_draw": None, "odds_away": 2.10,
}
DETAIL_MATCH = {
    "home": "Kaizer Chiefs", "away": "Mamelodi Sundowns",
    "league": "DStv Premiership", "sport_emoji": "⚽",
    "date": "Sat 26 Apr", "time": "15:30", "channel": "SuperSport 211",
    "home_form": ["W", "W", "D", "W", "L"], "away_form": ["W", "L", "W", "D", "W"],
    "home_odds": 2.40, "home_bookie": "Betway",
    "draw_odds": 3.20, "draw_bookie": "Hollywoodbets",
    "away_odds": 2.90, "away_bookie": "10bet",
    "h2h": {"n": 10, "hw": 5, "d": 2, "aw": 3},
    "stats": [
        {"label": "Goals/Game", "value": "2.4", "context": "Home"},
        {"label": "Clean Sheets", "value": "40%", "context": "Chiefs"},
    ],
    "analysis_text": "Chiefs in strong home form. Sundowns missing key midfielder through injury.",
}

# ---------------------------------------------------------------------------
# Build sample data using real builders
# ---------------------------------------------------------------------------
def make_sample_data():
    _logo64 = _card_logo_b64(_LOGO_PATH, max_height=64)

    # ── Edge cards ──
    edge_detail  = build_edge_detail_data(GOLD_TIP)
    edge_picks   = build_edge_picks_data(ALL_TIPS, page=1, per_page=4, user_tier="diamond")
    edge_summary = build_edge_summary_data(ALL_TIPS)
    tier_lock    = _build_tier_lock(
        "diamond", "Manchester City", "Arsenal",
        "soccer", "Premier League", "Sun 27 Apr · 16:00",
        "SuperSport 3", 4, {"hit_rate_7d": 68, "roi_7d": 22},
    )
    # BUILD-VERDICT-ONLY-STRIP-AI-BREAKDOWN-01 — ai_breakdown surface retired.
    # Template archived to archive/card_templates/ai_breakdown.html.

    # ── Match cards ──
    my_matches = build_my_matches_data([EDGE_MATCH, PLAIN_MATCH], page=1)
    match_det  = build_match_detail_data(DETAIL_MATCH)
    tier_page  = build_tier_page_data(ALL_TIPS, "gold")
    home_winners = cda.build_home_winners_data(wins=[
        {"match_key": "kaizer_chiefs_vs_sundowns_2026-04-20", "bet_type": "Kaizer Chiefs to Win",
         "recommended_odds": 2.40, "actual_return": 480, "edge_tier": "gold", "sport": "soccer"},
        {"match_key": "man_city_vs_arsenal_2026-04-19", "bet_type": "Both Teams to Score",
         "recommended_odds": 1.85, "actual_return": 370, "edge_tier": "diamond", "sport": "soccer"},
    ])

    # ── Profile / settings ──
    profile_home = cda.build_profile_card_data(
        first_name="Paul", tier="gold", trial_active=False,
        is_founding_member=False, member_since="1 Jan 2026",
        member_label="Member since", days_as_member=114,
        edge_7d_has_data=False, edge_7d_hits=0, edge_7d_total=0,
        edge_7d_hit_pct=0.0, edge_7d_roi=None, edge_7d_streak="",
        total_views=42, recent_views=12,
        focus_sport={"emoji": "⚽", "label": "Soccer"},
        experience_label="Experienced", risk_label="Moderate",
        bankroll_str="R1,000–R2,500",
        sports=[
            {"emoji": "⚽", "label": "Soccer",
             "leagues": [{"teams": ["Man Utd", "Kaizer Chiefs"]}]},
            {"emoji": "🏉", "label": "Rugby",
             "leagues": [{"teams": ["Stormers"]}]},
        ],
    )
    # settings_sports: built manually (builder reads config.SPORTS which needs env)
    settings_sports = {
        "header_logo_b64": _logo64,
        "user_name": "Paul",
        "sports": [
            {"key": "soccer",  "emoji": "⚽", "label": "Soccer",  "enabled": True,  "league_count": 8, "team_count": 2},
            {"key": "rugby",   "emoji": "🏉", "label": "Rugby",   "enabled": True,  "league_count": 6, "team_count": 1},
            {"key": "cricket", "emoji": "🏏", "label": "Cricket", "enabled": False, "league_count": 7, "team_count": 0},
            {"key": "combat",  "emoji": "🥊", "label": "Combat Sports", "enabled": False, "league_count": 2, "team_count": 0},
        ],
    }

    # ── Billing / subscription ──
    sub_payment_confirmed = {
        "first_name": "Paul", "plan_label": "Gold Monthly",
        "tier": "gold", "tier_badge": "🥇",
        "amount_zar": "R99", "expires_at_human": "27 May 2026",
        "renewal_cadence": "Renews monthly", "header_logo_b64": _logo64,
    }

    # ── Story quiz ──
    story_quiz_step = cda.build_story_quiz_step_data(
        step_key="daily_picks",
        prompt={"title": "Daily AI Picks", "body": "Get notified when today's edge picks are ready?",
                "yes": "Yes, notify me", "no": "Skip"},
        step_num=3, total_steps=8,
    )

    # ── Onboarding summary ──
    onb_summary = cda.build_onboarding_summary_data({
        "first_name": "Paul", "experience": "experienced",
        "risk": "moderate", "bankroll": "R1000-R2500",
        "sports": ["soccer", "rugby"],
        "teams": {"soccer": ["manu", "kc"], "rugby": ["stormers"]},
    })

    return {
        # Edge
        "edge_detail.html":      edge_detail,
        "edge_picks.html":       edge_picks,
        "edge_summary.html":     edge_summary,
        "tier_lock_upsell.html": tier_lock,
        # Match
        "my_matches.html":   my_matches,
        "match_detail.html": match_det,
        "home_winners.html": home_winners,
        "tier_page.html":    tier_page,
        # Profile
        "profile_home.html":    profile_home,
        "settings_sports.html": settings_sports,
        "my_teams.html": cda.build_my_teams_data(
            teams_by_sport=[
                {"sport_emoji": "⚽", "sport_label": "Soccer",
                 "teams": [{"name": "Manchester United", "league": "Premier League"},
                            {"name": "Kaizer Chiefs", "league": "PSL"}]},
                {"sport_emoji": "🏉", "sport_label": "Rugby",
                 "teams": [{"name": "Stormers", "league": "URC"}]},
            ],
            has_teams=True,
        ),
        "help.html": cda.build_help_data(),
        # Billing
        "sub_billing_active.html":     cda.build_sub_billing_active_data(
            tier="gold", plan_code="gold_monthly",
            member_since="1 Jan 2026", next_renewal="1 Jun 2026"),
        "sub_billing_inactive.html":   cda.build_sub_billing_inactive_data(
            last_plan="Gold Monthly", ended_at="1 Apr 2026"),
        "sub_cancel_confirm.html":     cda.build_sub_cancel_confirm_data(
            plan_name="Gold Monthly", access_until="27 May 2026"),
        "sub_cancel_done.html":        cda.build_sub_cancel_done_data(access_until="27 May 2026"),
        "sub_email_redirect.html":     cda.build_sub_email_redirect_data(),
        "sub_expiry_notice.html":      cda.build_sub_expiry_notice_data(old_tier="gold", old_tier_emoji="🥇"),
        "sub_founding_confirmed.html": cda.build_sub_founding_confirmed_data(slot_number=7),
        "sub_founding_ended.html":     cda.build_sub_founding_ended_data(),
        "sub_founding_live.html":      cda.build_sub_founding_live_data(days_left=3, slots_remaining=23),
        "sub_founding_soldout.html":   cda.build_sub_founding_soldout_data(),
        "sub_payment_confirmed.html":  sub_payment_confirmed,
        "sub_payment_error.html":      cda.build_sub_payment_error_data(
            error_message="Card declined — please try a different card."),
        "sub_payment_ready.html":      cda.build_sub_payment_ready_data(
            plan_name="Gold Monthly", price_display="R99/month",
            reference="ME-20260427-ABC123"),
        "sub_plans.html":              cda.build_sub_plans_data(
            current_tier="bronze", founding_days_left=3, founding_slots_remaining=23),
        "sub_status_active.html":      cda.build_sub_status_active_data(
            tier="gold", expires_label="27 May 2026", days_left=32, member_since="1 Jan 2026"),
        "sub_status_bronze.html":      cda.build_sub_status_bronze_data(
            daily_views_used=2, daily_cap=3),
        "sub_trial_expiry.html":       cda.build_sub_trial_expiry_data(days_used=7, hit_rate=0.0),
        "sub_upgrade_bronze.html":     cda.build_sub_upgrade_bronze_data(),
        "sub_upgrade_diamond_max.html": cda.build_sub_upgrade_diamond_max_data(),
        "sub_upgrade_gold.html":       cda.build_sub_upgrade_gold_data(),
        # Onboarding
        "onboarding_bankroll.html":          cda.build_onboarding_bankroll_data(),
        "onboarding_bankroll_custom.html":   cda.build_onboarding_bankroll_custom_data(),
        "onboarding_done.html":              cda.build_onboarding_done_data(
            first_name="Paul", user_tier="bronze",
            founding_offer=True, founding_days_left=3),
        "onboarding_edge_explainer.html":    cda.build_onboarding_edge_explainer_data(),
        "onboarding_experience.html":        cda.build_onboarding_experience_data(),
        "onboarding_favourites.html":        cda.build_onboarding_favourites_data(
            sport_key="soccer", sport_label="Soccer", sport_emoji="⚽",
            teams=[{"name": "Manchester United", "id": "manu"},
                   {"name": "Kaizer Chiefs", "id": "kc"}],
            selected_count=1,
        ),
        "onboarding_favourites_manual.html": cda.build_onboarding_favourites_data(
            sport_key="soccer", sport_label="Soccer", sport_emoji="⚽",
        ),
        "onboarding_fuzzy_suggest.html":     cda.build_onboarding_fuzzy_suggest_data(
            sport_key="soccer", sport_label="Soccer", sport_emoji="⚽",
            input_text="Man U",
            suggestions=[{"name": "Manchester United", "confidence": 95},
                         {"name": "Manchester City", "confidence": 72}],
        ),
        "onboarding_notify.html":            cda.build_onboarding_notify_data(current_hour=8),
        "onboarding_restart.html":           cda.build_onboarding_restart_data(first_name="Paul"),
        "onboarding_risk.html":              cda.build_onboarding_risk_data(),
        "onboarding_sports.html":            cda.build_onboarding_sports_data(
            selected_sports=["soccer"]),
        "onboarding_summary.html":           onb_summary,
        "onboarding_team_celebration.html":  cda.build_onboarding_team_celebration_data(
            sport_key="soccer", sport_label="Soccer", sport_emoji="⚽",
            matched=[{"name": "Manchester United", "league": "Premier League"},
                     {"name": "Kaizer Chiefs", "league": "PSL"}],
            unmatched=[],
        ),
        "onboarding_welcome.html":           cda.build_onboarding_welcome_data(first_name="Paul"),
        # Story quiz
        "story_quiz_complete.html": cda.build_story_quiz_complete_data(
            prefs={"daily_picks": True, "game_day_alerts": True, "weekly_recap": False}),
        "story_quiz_step.html":     story_quiz_step,
        # Bookmaker directory
        "bookmaker_directory.html": cda.build_bookmaker_directory_data(),
    }

# ---------------------------------------------------------------------------
# Gallery HTML
# ---------------------------------------------------------------------------
def build_gallery_html(results: list) -> str:
    cards_html = ""
    for r in results:
        img_tag = (
            f'<img src="{r["png_name"]}" alt="{r["template"]}" '
            'style="max-width:480px;width:100%;display:block;border-radius:8px;">'
            if r["ok"] else
            f'<div style="background:#3a0000;color:#ff6b6b;padding:16px;border-radius:8px;'
            f'font-family:monospace;white-space:pre-wrap;font-size:11px;">'
            f'RENDER ERROR: {r["error"]}</div>'
        )
        cards_html += f"""
        <div class="card-block">
          <div class="card-label">{'✅' if r['ok'] else '❌'} {r['template']}</div>
          {img_tag}
          <div class="feedback-label">Feedback</div>
          <textarea class="feedback-box" data-template="{r['template']}" placeholder="Notes, bugs, visual issues..."></textarea>
        </div>"""

    ok  = sum(1 for r in results if r["ok"])
    err = len(results) - ok
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>MzansiEdge Card QA — {TODAY}</title>
<style>
  *{{margin:0;padding:0;box-sizing:border-box}}
  body{{background:#0A0A0A;color:#E0E0E0;font-family:'Inter',-apple-system,system-ui,sans-serif;padding-bottom:80px}}
  header{{background:#111;border-bottom:1px solid #222;padding:20px 24px;position:sticky;top:0;z-index:10}}
  header h1{{font-size:20px;font-weight:700;color:#FF6B00}}
  header p{{font-size:13px;color:#888;margin-top:4px}}
  .grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(500px,1fr));gap:24px;padding:24px}}
  .card-block{{background:#141414;border:1px solid #222;border-radius:12px;padding:16px;display:flex;flex-direction:column;gap:12px}}
  .card-label{{font-size:13px;font-weight:600;color:#aaa;font-family:monospace}}
  .feedback-label{{font-size:11px;color:#555;text-transform:uppercase;letter-spacing:1px}}
  .feedback-box{{background:#0A0A0A;border:1px solid #333;border-radius:6px;color:#ccc;font-size:13px;padding:10px;resize:vertical;min-height:72px;width:100%;outline:none}}
  .feedback-box:focus{{border-color:#FF6B00}}
  footer{{position:fixed;bottom:0;left:0;right:0;background:#111;border-top:1px solid #222;padding:12px 24px;display:flex;align-items:center;justify-content:space-between}}
  footer span{{font-size:12px;color:#555}}
  #export-btn{{background:#FF6B00;color:#fff;border:none;padding:10px 20px;border-radius:8px;font-weight:700;font-size:14px;cursor:pointer}}
  #export-btn:hover{{background:#e85c00}}
</style>
</head>
<body>
<header>
  <h1>MzansiEdge Card QA — {TODAY}</h1>
  <p>{ok} rendered · {err} errors · {len(results)} templates total</p>
</header>
<div class="grid">{cards_html}</div>
<footer>
  <span>Feedback is client-side only — click Export to download JSON</span>
  <button id="export-btn">Export Feedback JSON</button>
</footer>
<script>
document.getElementById('export-btn').addEventListener('click',()=>{{
  const out={{}};
  document.querySelectorAll('.feedback-box').forEach(t=>{{if(t.value.trim())out[t.dataset.template]=t.value.trim()}});
  const blob=new Blob([JSON.stringify(out,null,2)],{{type:'application/json'}});
  const a=document.createElement('a');a.href=URL.createObjectURL(blob);
  a.download='qa-feedback-{TODAY}.json';a.click();
}});
</script>
</body>
</html>"""

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("Building sample data via real builders...")
    try:
        sample_data = make_sample_data()
        print(f"  OK — {len(sample_data)} templates mapped")
    except Exception:
        import traceback; traceback.print_exc()
        sys.exit(1)

    templates = sorted(TEMPLATES_DIR.glob("*.html"))
    print(f"Found {len(templates)} templates")

    results = []
    for tmpl in templates:
        name = tmpl.name
        data = sample_data.get(name)
        if data is None:
            print(f"  [WARN] {name} — no sample data")
            results.append({"template": name, "png_name": None, "ok": False, "error": "No sample data"})
            continue
        try:
            png = render_card_sync(name, data)
            out = OUTPUT_DIR / name.replace(".html", ".png")
            out.write_bytes(png)
            print(f"  [OK]  {name} ({len(png)//1024}KB)")
            results.append({"template": name, "png_name": out.name, "ok": True, "error": None})
        except Exception as e:
            print(f"  [ERR] {name} → {e}")
            results.append({"template": name, "png_name": None, "ok": False, "error": str(e)})

    (OUTPUT_DIR / "index.html").write_text(build_gallery_html(results))

    if LATEST_LINK.is_symlink() or LATEST_LINK.exists():
        LATEST_LINK.unlink()
    LATEST_LINK.symlink_to(TODAY)

    ok  = sum(1 for r in results if r["ok"])
    err = len(results) - ok
    print(f"\n{'✅' if err == 0 else '⚠️'} {ok}/{len(results)} rendered, {err} errors")
    print(f"URL: https://mzansiedge.co.za/qa-gallery/latest/index.html")

if __name__ == "__main__":
    main()
