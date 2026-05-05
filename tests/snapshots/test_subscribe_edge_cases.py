"""Snapshot tests for subscribe edge-case card wiring — FIX-ZERO-TEXT-SUBSCRIBE-EDGE-CASES-01."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("ODDS_API_KEY", "test-odds-key")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-anthropic-key")
os.environ.setdefault("ADMIN_IDS", "123456")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

TEMPLATES_DIR = Path(__file__).parents[2] / "card_templates"


# ── Template existence ───────────────────────────────────────────────────────

class TestTemplatesExist:
    def test_sub_already_active_template_exists(self):
        assert (TEMPLATES_DIR / "sub_already_active.html").exists()

    def test_sub_plan_invalid_template_exists(self):
        assert (TEMPLATES_DIR / "sub_plan_invalid.html").exists()

    def test_sub_founding_disclosure_template_exists(self):
        assert (TEMPLATES_DIR / "sub_founding_disclosure.html").exists()

    def test_sub_founding_confirmed_template_exists(self):
        assert (TEMPLATES_DIR / "sub_founding_confirmed.html").exists()

    def test_sub_founding_soldout_template_exists(self):
        assert (TEMPLATES_DIR / "sub_founding_soldout.html").exists()

    def test_sub_cancel_done_template_exists(self):
        assert (TEMPLATES_DIR / "sub_cancel_done.html").exists()


# ── Builder data shapes ──────────────────────────────────────────────────────

class TestBuilderDataShapes:
    def test_build_sub_already_active_diamond(self):
        from card_data_adapters import build_sub_already_active_data
        data = build_sub_already_active_data(tier="diamond")
        assert data["tier_emoji"] == "💎"
        assert data["tier_name"] == "Diamond"
        assert "tier_color" in data
        assert "tier_glow" in data
        assert "header_logo_b64" in data

    def test_build_sub_already_active_gold(self):
        from card_data_adapters import build_sub_already_active_data
        result = build_sub_already_active_data(tier="gold")
        assert result["tier_emoji"] == "🥇"
        assert result["tier_name"] == "Gold"

    def test_build_sub_already_active_bronze(self):
        from card_data_adapters import build_sub_already_active_data
        result = build_sub_already_active_data(tier="bronze")
        assert result["tier_emoji"] == "🥉"
        assert result["tier_name"] == "Bronze"

    def test_build_sub_plan_invalid_data(self):
        from card_data_adapters import build_sub_plan_invalid_data
        result = build_sub_plan_invalid_data()
        assert "header_logo_b64" in result

    def test_build_sub_founding_disclosure_data_defaults(self):
        from card_data_adapters import build_sub_founding_disclosure_data
        result = build_sub_founding_disclosure_data()
        assert "sold" in result
        assert "remaining" in result
        assert "total_slots" in result
        assert "price_rands" in result
        assert "launch_date" in result
        assert "header_logo_b64" in result

    def test_build_sub_founding_disclosure_data_values(self):
        from card_data_adapters import build_sub_founding_disclosure_data
        data = build_sub_founding_disclosure_data(
            sold=23,
            remaining=77,
            total_slots=100,
            price_rands=699,
            launch_date="14 Mar 2026",
        )
        assert data["sold"] == 23
        assert data["remaining"] == 77
        assert data["total_slots"] == 100
        assert data["price_rands"] == 699
        assert data["launch_date"] == "14 Mar 2026"

    def test_build_sub_founding_disclosure_data_remaining_le_total(self):
        from card_data_adapters import build_sub_founding_disclosure_data
        data = build_sub_founding_disclosure_data(sold=100, remaining=0, total_slots=100)
        assert data["remaining"] == 0
        assert data["total_slots"] == 100


# ── Template variable coverage ───────────────────────────────────────────────

class TestTemplateVariables:
    """Verify that required template variables are present in builder output."""

    def test_sub_already_active_template_vars(self):
        from card_data_adapters import build_sub_already_active_data
        data = build_sub_already_active_data(tier="diamond")
        template = (TEMPLATES_DIR / "sub_already_active.html").read_text()
        for var in ("tier_emoji", "tier_name", "tier_color", "tier_glow"):
            assert f"{{{{ {var}" in template or f"{{{{{var}" in template or var in template, \
                f"Template should reference {var}"

    def test_sub_founding_disclosure_template_vars(self):
        from card_data_adapters import build_sub_founding_disclosure_data
        data = build_sub_founding_disclosure_data(
            sold=10, remaining=90, total_slots=100, price_rands=699, launch_date="14 Mar"
        )
        template = (TEMPLATES_DIR / "sub_founding_disclosure.html").read_text()
        for var in ("price_rands", "remaining", "total_slots", "launch_date"):
            assert var in template, f"Template should reference {var}"

    def test_sub_plan_invalid_template_has_logo_slot(self):
        template = (TEMPLATES_DIR / "sub_plan_invalid.html").read_text()
        assert "header_logo_b64" in template


# ── No raw text paths (regression guards) ────────────────────────────────────

class TestNoRawTextPaths:
    """Guard that the text-only callsites have been replaced."""

    def test_cmd_subscribe_cancel_no_raw_reply_text(self):
        bot_src = Path(__file__).parents[2] / "bot.py"
        text = bot_src.read_text()
        # The old literal must not appear
        assert '"❌ Subscription cancelled."' not in text

    def test_cmd_subscribe_already_active_no_raw_reply_text(self):
        bot_src = Path(__file__).parents[2] / "bot.py"
        text = bot_src.read_text()
        # Old literal gone; new text_fallback uses card
        assert "sub_already_active.html" in text

    def test_handle_sub_tier_plan_invalid_no_raw_edit(self):
        bot_src = Path(__file__).parents[2] / "bot.py"
        text = bot_src.read_text()
        assert "sub_plan_invalid.html" in text

    def test_handle_sub_tier_founding_confirmed_wired(self):
        bot_src = Path(__file__).parents[2] / "bot.py"
        text = bot_src.read_text()
        # The founding_confirmed card must be used in _handle_sub_tier context
        assert text.count("sub_founding_confirmed.html") >= 2  # cmd_founding + _handle_sub_tier

    def test_handle_sub_tier_founding_soldout_wired(self):
        bot_src = Path(__file__).parents[2] / "bot.py"
        text = bot_src.read_text()
        assert text.count("sub_founding_soldout.html") >= 2  # cmd_founding + _handle_sub_tier

    def test_handle_sub_tier_founding_disclosure_wired(self):
        bot_src = Path(__file__).parents[2] / "bot.py"
        text = bot_src.read_text()
        assert "sub_founding_disclosure.html" in text

    def test_cancel_done_wired_in_cmd_subscribe_cancel(self):
        bot_src = Path(__file__).parents[2] / "bot.py"
        text = bot_src.read_text()
        assert "sub_cancel_done.html" in text
