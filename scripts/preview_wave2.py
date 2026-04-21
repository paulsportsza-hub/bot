#!/usr/bin/env python3
"""BUILD-WAVE2-ONBOARDING-01: Preview all 17 onboarding card templates.

Run from /home/paulsportsza/bot/:
    python scripts/preview_wave2.py

Renders each template to PNG, saves to /home/paulsportsza/template_previews/,
and creates wave2_onboarding_preview.zip.
"""
from __future__ import annotations

import os
import sys
import zipfile
from pathlib import Path

BOT_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, BOT_DIR)

OUTPUT_DIR = Path("/home/paulsportsza/template_previews")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

from card_renderer import render_card_sync
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

_SAMPLE_OB = {
    "experience": "casual",
    "selected_sports": ["soccer", "rugby"],
    "favourites": {
        "soccer": ["Arsenal", "Kaizer Chiefs"],
        "rugby": ["South Africa", "Bulls"],
    },
    "risk": "moderate",
    "bankroll": 500.0,
    "notify_hour": 18,
}

_STORY_PROMPT = {
    "title": "Daily AI Picks",
    "body": "Get your morning Edge picks delivered at your preferred time. Our AI scans all SA bookmakers overnight so you wake up with the best value bets ready.",
    "yes": "✅ Yes, send me picks",
    "no": "❌ Skip this one",
}

PREVIEWS: list[tuple[str, dict, str]] = [
    (
        "onboarding_welcome.html",
        build_onboarding_welcome_data("Paul", trial_started=True, trial_days=7),
        "1. Welcome (with trial)",
    ),
    (
        "onboarding_experience.html",
        build_onboarding_experience_data(),
        "2. Experience Level",
    ),
    (
        "onboarding_sports.html",
        build_onboarding_sports_data(selected_sports=["soccer", "rugby"]),
        "3. Sports Selection (2 selected)",
    ),
    (
        "onboarding_favourites.html",
        build_onboarding_favourites_data(
            "soccer", "Soccer", "⚽",
            teams=[
                {"name": "Arsenal", "selected": True},
                {"name": "Kaizer Chiefs", "selected": True},
                {"name": "Liverpool", "selected": False},
                {"name": "Man City", "selected": False},
                {"name": "Mamelodi Sundowns", "selected": False},
                {"name": "Orlando Pirates", "selected": False},
            ],
            selected_count=2,
        ),
        "4. Favourites (Soccer, 2 selected)",
    ),
    (
        "onboarding_favourites_manual.html",
        build_onboarding_favourites_manual_data(
            "soccer", "Soccer", "⚽",
            fav_label="team",
            example="e.g. Chiefs, Arsenal, Barcelona, Sundowns",
        ),
        "5. Favourites Manual Input",
    ),
    (
        "onboarding_fuzzy_suggest.html",
        build_onboarding_fuzzy_suggest_data(
            "soccer", "Soccer", "⚽",
            input_text="arsnal",
            suggestions=[
                {"label": "Arsenal", "confidence": 92},
                {"label": "Arsenale Taranto", "confidence": 68},
            ],
        ),
        "6. Fuzzy Suggest",
    ),
    (
        "onboarding_team_celebration.html",
        build_onboarding_team_celebration_data(
            "soccer", "Soccer", "⚽",
            matched=[
                {"name": "Arsenal", "cheer": "YNWA! ❤️"},
                {"name": "Kaizer Chiefs", "cheer": "Amakhosi! 💛🖤"},
            ],
            unmatched=["Arsenale"],
        ),
        "7. Team Celebration",
    ),
    (
        "onboarding_edge_explainer.html",
        build_onboarding_edge_explainer_data(),
        "8. Edge Explainer",
    ),
    (
        "onboarding_risk.html",
        build_onboarding_risk_data(current="moderate"),
        "9. Risk Profile (Moderate selected)",
    ),
    (
        "onboarding_bankroll.html",
        build_onboarding_bankroll_data(current=500.0),
        "10. Bankroll (R500 selected)",
    ),
    (
        "onboarding_bankroll_custom.html",
        build_onboarding_bankroll_custom_data(validation_error="", min_value=20),
        "11. Bankroll Custom",
    ),
    (
        "onboarding_notify.html",
        build_onboarding_notify_data(current_hour=18),
        "12. Notification Time (18:00 selected)",
    ),
    (
        "onboarding_summary.html",
        build_onboarding_summary_data(_SAMPLE_OB),
        "13. Summary",
    ),
    (
        "onboarding_done.html",
        build_onboarding_done_data("Paul", trial_started=True, trial_days=7),
        "14. Done / Welcome",
    ),
    (
        "onboarding_restart.html",
        build_onboarding_restart_data(first_name="Paul"),
        "15. Restart Warning",
    ),
    (
        "story_quiz_step.html",
        build_story_quiz_step_data("daily_picks", _STORY_PROMPT, step_num=1, total_steps=6),
        "16. Story Quiz Step",
    ),
    (
        "story_quiz_complete.html",
        build_story_quiz_complete_data({
            "daily_picks": True, "game_day_alerts": True,
            "weekly_recap": True, "edu_tips": False,
            "market_movers": False, "bankroll_updates": True,
            "live_scores": True,
        }),
        "17. Story Quiz Complete",
    ),
]


def main() -> None:
    passed = 0
    failed = 0
    png_files: list[Path] = []

    for template, data, desc in PREVIEWS:
        stem = template.replace(".html", "")
        out_path = OUTPUT_DIR / f"wave2_{stem}.png"
        try:
            png_bytes = render_card_sync(template, data)
            if not png_bytes:
                print(f"  FAIL  {desc}: render returned empty bytes")
                failed += 1
                continue
            out_path.write_bytes(png_bytes)
            kb = len(png_bytes) // 1024
            print(f"  OK    {desc} → {out_path.name} ({kb}KB)")
            png_files.append(out_path)
            passed += 1
        except Exception as exc:
            print(f"  FAIL  {desc}: {exc}")
            failed += 1

    zip_path = OUTPUT_DIR / "wave2_onboarding_preview.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for png in png_files:
            zf.write(png, png.name)

    print(f"\n{passed}/{passed + failed} templates rendered OK")
    print(f"Zip: {zip_path}")
    print(f"\nDownload:\n  scp paulsportsza@178.128.171.28:{zip_path} ~/Downloads/")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
