#!/usr/bin/env python3
"""BUILD-WAVE1-SUB-01: Preview all 19 subscription card templates.

Run from /home/paulsportsza/bot/:
    python scripts/preview_wave1.py

Renders each template to PNG, saves to /home/paulsportsza/template_previews/,
and creates wave1_subscription_preview.zip.
"""
from __future__ import annotations

import os
import sys
import zipfile
from pathlib import Path

# Ensure bot dir is on path
BOT_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, BOT_DIR)

OUTPUT_DIR = Path("/home/paulsportsza/template_previews")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

from card_renderer import render_card_sync
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

# --- Template → (template_name, data_fn_call, description) ---
PREVIEWS: list[tuple[str, dict, str]] = [
    (
        "sub_plans.html",
        build_sub_plans_data(
            current_tier="bronze",
            founding_days_left=12,
            founding_slots_remaining=47,
        ),
        "1. Plans (with founding offer)",
    ),
    (
        "sub_upgrade_bronze.html",
        build_sub_upgrade_bronze_data(founding_days_left=12),
        "2. Upgrade Bronze",
    ),
    (
        "sub_upgrade_gold.html",
        build_sub_upgrade_gold_data(founding_days_left=12),
        "3. Upgrade Gold → Diamond",
    ),
    (
        "sub_upgrade_diamond_max.html",
        build_sub_upgrade_diamond_max_data(),
        "4. Already on Diamond",
    ),
    (
        "sub_payment_ready.html",
        build_sub_payment_ready_data(
            plan_name="Gold",
            price_display="R99/mo",
            reference="mze-12345-gold_monthly-abc123",
            is_founding=False,
        ),
        "5. Payment Ready",
    ),
    (
        "sub_payment_error.html",
        build_sub_payment_error_data(
            error_message="Could not connect to payment provider.",
        ),
        "6. Payment Error",
    ),
    (
        "sub_email_redirect.html",
        build_sub_email_redirect_data(),
        "7. Email Redirect",
    ),
    (
        "sub_status_active.html",
        build_sub_status_active_data(
            tier="gold",
            member_since="01 Jan 2026",
            expires_label="01 Apr 2026",
            founding_slot=None,
            founding_slots_remaining=47,
        ),
        "8. Status Active (Gold)",
    ),
    (
        "sub_status_bronze.html",
        build_sub_status_bronze_data(
            daily_views_used=1,
            daily_cap=3,
            founding_days_left=12,
            founding_slots_remaining=47,
        ),
        "9. Status Bronze",
    ),
    (
        "sub_billing_active.html",
        build_sub_billing_active_data(
            tier="gold",
            plan_code="gold_monthly",
            member_since="01 Jan 2026",
            next_renewal="01 May 2026",
            is_founding=False,
            founding_slot=None,
        ),
        "10. Billing Active",
    ),
    (
        "sub_billing_inactive.html",
        build_sub_billing_inactive_data(),
        "11. Billing Inactive",
    ),
    (
        "sub_cancel_confirm.html",
        build_sub_cancel_confirm_data(
            plan_name="Gold Monthly",
            access_until="01 May 2026",
        ),
        "12. Cancel Confirm",
    ),
    (
        "sub_cancel_done.html",
        build_sub_cancel_done_data(access_until="01 May 2026"),
        "13. Cancel Done",
    ),
    (
        "sub_founding_confirmed.html",
        build_sub_founding_confirmed_data(
            slot_number=42,
            founding_price_cents=69900,
        ),
        "14. Founding Confirmed",
    ),
    (
        "sub_founding_soldout.html",
        build_sub_founding_soldout_data(),
        "15. Founding Sold Out",
    ),
    (
        "sub_founding_ended.html",
        build_sub_founding_ended_data(diamond_monthly=199, diamond_annual=1599),
        "16. Founding Ended",
    ),
    (
        "sub_founding_live.html",
        build_sub_founding_live_data(
            annual_price=699,
            normal_monthly=199,
            days_left=12,
            slots_remaining=47,
        ),
        "17. Founding Live Offer",
    ),
    (
        "sub_expiry_notice.html",
        build_sub_expiry_notice_data(old_tier="gold", old_tier_emoji="🥇"),
        "18. Expiry Notice",
    ),
    (
        "sub_trial_expiry.html",
        build_sub_trial_expiry_data(days_used=7, hit_rate=0.68),
        "19. Trial Expiry",
    ),
]


def main() -> None:
    passed = 0
    failed = 0
    png_files: list[Path] = []

    for template, data, desc in PREVIEWS:
        stem = template.replace(".html", "")
        out_path = OUTPUT_DIR / f"wave1_{stem}.png"
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

    zip_path = OUTPUT_DIR / "wave1_subscription_preview.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for png in png_files:
            zf.write(png, png.name)

    print(f"\n{passed}/{passed + failed} templates rendered OK")
    print(f"Zip: {zip_path}")
    print(f"\nDownload:\n  scp paulsportsza@37.27.179.53:{zip_path} ~/Downloads/")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
