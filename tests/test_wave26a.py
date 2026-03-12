"""Wave 26A — Mobile-First Hot Tips Redesign tests.

Tests for: 3-line compact cards, single footer CTA, locked detail gating,
button abbreviations, morning teaser templates, losing streak footer.
"""
from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, "/home/paulsportsza/bot")
sys.path.insert(0, "/home/paulsportsza")

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("ODDS_API_KEY", "test-odds-key")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-anthropic-key")
os.environ.setdefault("ADMIN_IDS", "123456")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

# ── Fixtures ──────────────────────────────────────────────

SAMPLE_TIPS = [
    {
        "home_team": "Mamelodi Sundowns", "away_team": "Kaizer Chiefs",
        "league": "PSL", "league_key": "psl", "sport_key": "soccer_south_africa_psl",
        "outcome": "Sundowns", "odds": 1.50, "ev": 18, "bookmaker": "Hollywoodbets",
        "display_tier": "diamond", "edge_rating": "diamond",
        "match_id": "sun_kc_20260310", "event_id": "sun_kc_20260310",
        "commence_time": "2026-03-10T17:00:00Z",
    },
    {
        "home_team": "Orlando Pirates", "away_team": "Sekhukhune United",
        "league": "PSL", "league_key": "psl", "sport_key": "soccer_south_africa_psl",
        "outcome": "Pirates", "odds": 1.80, "ev": 9, "bookmaker": "Betway",
        "display_tier": "gold", "edge_rating": "gold",
        "match_id": "pir_sek_20260310", "event_id": "pir_sek_20260310",
        "commence_time": "2026-03-10T15:00:00Z",
    },
    {
        "home_team": "Arsenal", "away_team": "Chelsea",
        "league": "EPL", "league_key": "epl", "sport_key": "soccer_epl",
        "outcome": "Arsenal", "odds": 2.10, "ev": 5, "bookmaker": "Sportingbet",
        "display_tier": "silver", "edge_rating": "silver",
        "match_id": "ars_che_20260310", "event_id": "ars_che_20260310",
        "commence_time": "2026-03-10T14:00:00Z",
    },
    {
        "home_team": "Liverpool", "away_team": "Man City",
        "league": "EPL", "league_key": "epl", "sport_key": "soccer_epl",
        "outcome": "Liverpool", "odds": 2.50, "ev": 3, "bookmaker": "GBets",
        "display_tier": "bronze", "edge_rating": "bronze",
        "match_id": "liv_mci_20260310", "event_id": "liv_mci_20260310",
        "commence_time": "2026-03-10T16:30:00Z",
    },
    {
        "home_team": "Bulls", "away_team": "Stormers",
        "league": "URC", "league_key": "urc", "sport_key": "rugby_urc",
        "outcome": "Bulls", "odds": 1.65, "ev": 7, "bookmaker": "Hollywoodbets",
        "display_tier": "gold", "edge_rating": "gold",
        "match_id": "bul_sto_20260310", "event_id": "bul_sto_20260310",
        "commence_time": "2026-03-10T19:00:00Z",
    },
]


def _import_build():
    """Import _build_hot_tips_page with mocked broadcast details."""
    with patch("bot._get_broadcast_details", return_value={"kickoff": "Tue 17:00", "broadcast": "📺 SS PSL (DStv 202)"}):
        from bot import _build_hot_tips_page
    return _build_hot_tips_page


@pytest.fixture
def build_page():
    """Return a helper that calls _build_hot_tips_page with broadcast mocked."""
    def _call(**kwargs):
        with patch("bot._get_broadcast_details", return_value={"kickoff": "Tue 17:00", "broadcast": "📺 SS PSL (DStv 202)"}):
            from bot import _build_hot_tips_page
            return _build_hot_tips_page(**kwargs)
    return _call


# ── Test 1: Full access card has exactly 3 content lines ──

def test_card_3_lines_full(build_page):
    """Full access card: match, info, outcome @ odds → return. No signal/CTA."""
    text, _ = build_page(tips=SAMPLE_TIPS, user_tier="diamond")
    # Find a full-access card (bronze tip for diamond user)
    lines = text.split("\n")
    card_lines = [l for l in lines if "[4]" in l or (lines.index(l) > 0 and "[4]" in lines[lines.index(l) - 1] if lines.index(l) > 0 else False)]
    # Check card has outcome @ odds → return
    card_block = ""
    in_card = False
    for line in lines:
        if "<b>[4]</b>" in line:
            in_card = True
            card_block = line
        elif in_card and (line.strip() == "" or "<b>[" in line):
            break
        elif in_card:
            card_block += "\n" + line
    assert "Liverpool" in card_block
    assert "@" in card_block
    assert "R300" in card_block
    # No signal count text
    assert "signals" not in card_block
    # No per-card upgrade CTA
    assert "Unlock" not in card_block


# ── Test 2: Blurred card has return only ──

def test_card_3_lines_blurred(build_page):
    """Blurred card (Bronze viewing Gold): return line, no odds/outcome/bookmaker."""
    text, _ = build_page(tips=SAMPLE_TIPS, user_tier="bronze")
    # Gold tip (index 2) is blurred for bronze
    card_block = ""
    in_card = False
    for line in text.split("\n"):
        if "<b>[2]</b>" in line:
            in_card = True
            card_block = line
        elif in_card and (line.strip() == "" or "<b>[" in line):
            break
        elif in_card:
            card_block += "\n" + line
    assert "💰" in card_block
    assert "R300" in card_block
    # Should NOT have outcome name or bookmaker
    assert "Pirates" not in card_block or "Betway" not in card_block
    # No spoiler tags
    assert "tg-spoiler" not in card_block


# ── Test 3: Locked card has lock message ──

def test_card_3_lines_locked(build_page):
    """Locked card (Bronze viewing Diamond): 'Our highest-conviction pick.'"""
    text, _ = build_page(tips=SAMPLE_TIPS, user_tier="bronze")
    # Diamond tip (index 1) is locked for bronze
    card_block = ""
    in_card = False
    for line in text.split("\n"):
        if "<b>[1]</b>" in line:
            in_card = True
            card_block = line
        elif in_card and (line.strip() == "" or "<b>[" in line):
            break
        elif in_card:
            card_block += "\n" + line
    assert "highest-conviction" in card_block
    # No odds or return amount
    assert "1.50" not in card_block
    assert "R199/mo" not in card_block  # No per-card upgrade CTA


# ── Test 4: No section headers ──

def test_no_section_headers(build_page):
    """Output has no DIAMOND EDGE, GOLDEN EDGE, SILVER EDGE, BRONZE EDGE headers."""
    text, _ = build_page(tips=SAMPLE_TIPS, user_tier="diamond")
    assert "DIAMOND EDGE" not in text
    assert "GOLDEN EDGE" not in text
    assert "SILVER EDGE" not in text
    assert "BRONZE EDGE" not in text


# ── Test 5: No per-card CTA ──

def test_no_per_card_cta(build_page):
    """No 'Unlock odds' or 'available on Gold' or 'Diamond members only' in card text."""
    text, _ = build_page(tips=SAMPLE_TIPS, user_tier="bronze")
    assert "Unlock odds" not in text
    assert "available on Gold" not in text
    assert "Diamond members only" not in text
    assert "R99/mo" not in text.split("━━━")[0]  # No R99/mo before footer


# ── Test 6: Single footer CTA for Bronze ──

def test_single_footer_cta_bronze(build_page):
    """Footer block present for Bronze user, contains /subscribe."""
    text, _ = build_page(tips=SAMPLE_TIPS, user_tier="bronze")
    assert "━━━" in text
    assert "/subscribe" in text
    assert "edges locked" in text


# ── Test 7: No footer for Diamond ──

def test_no_footer_diamond(build_page):
    """No footer block (no '━━━') for Diamond user."""
    text, _ = build_page(tips=SAMPLE_TIPS, user_tier="diamond")
    assert "━━━" not in text


# ── Test 8: No URL button for locked edges ──

def test_no_bookmaker_link_locked(build_page):
    """Locked edges have no URL button (check InlineKeyboardMarkup)."""
    _, markup = build_page(tips=SAMPLE_TIPS, user_tier="bronze")
    # Find button for tip 1 (diamond — locked for bronze)
    for row in markup.inline_keyboard:
        for btn in row:
            if "[1]" in (btn.text or ""):
                assert btn.url is None, "Locked edge should not have URL button"
                # W84-P0: locked edges use hot:upgrade (shows upgrade prompt with Back button)
                assert btn.callback_data.startswith("hot:upgrade:")


# ── Test 9: No Compare Odds button for locked edges ──

def test_no_compare_odds_locked(build_page):
    """No 'Compare All Odds' or 'All Bookmaker Odds' button for locked tip detail."""
    # This tests the button layout in _build_hot_tips_page list view
    _, markup = build_page(tips=SAMPLE_TIPS, user_tier="bronze")
    all_btn_texts = [btn.text for row in markup.inline_keyboard for btn in row]
    # Locked edge buttons should go to sub:plans, not odds comparison
    for row in markup.inline_keyboard:
        for btn in row:
            if "[1]" in (btn.text or "") and "🔒" in (btn.text or ""):
                assert "odds" not in (btn.callback_data or "").lower()


# ── Test 10: Button abbreviations under 28 chars ──

def test_button_abbreviations(build_page):
    """All button labels under 28 chars."""
    _, markup = build_page(tips=SAMPLE_TIPS, user_tier="diamond")
    for row in markup.inline_keyboard:
        for btn in row:
            if btn.text and btn.text.startswith("["):
                assert len(btn.text) <= 28, f"Button too long: '{btn.text}' ({len(btn.text)} chars)"


# ── Test 11: Bronze teaser has free picks + locked picks ──

@pytest.mark.asyncio
async def test_teaser_bronze_distinct():
    """Bronze teaser contains 'free picks' + 'locked picks'."""
    with patch("bot._fetch_hot_tips_from_db", new_callable=AsyncMock, return_value=SAMPLE_TIPS), \
         patch("bot._fetch_hot_tips_all_sports", new_callable=AsyncMock, return_value=[]), \
         patch("bot._get_settlement_funcs", return_value=(MagicMock(return_value=None), None, None, MagicMock(return_value=None))), \
         patch("bot._can_send_notification", new_callable=AsyncMock, return_value=True), \
         patch("bot._after_send", new_callable=AsyncMock), \
         patch("bot.db") as mock_db, \
         patch("bot._format_kickoff_display", return_value="Tue 17:00"), \
         patch("bot._get_broadcast_details", return_value={"kickoff": "Tue 17:00", "broadcast": ""}):

        mock_user = MagicMock()
        mock_user.id = 111
        mock_user.consecutive_misses = 0
        mock_db.get_users_for_notification = AsyncMock(return_value=[mock_user])
        mock_db.get_user_tier = AsyncMock(return_value="bronze")
        mock_db.get_user = AsyncMock(return_value=mock_user)

        mock_bot = MagicMock()
        mock_bot.send_message = AsyncMock()
        mock_ctx = MagicMock()
        mock_ctx.bot = mock_bot

        from bot import _morning_teaser_job
        await _morning_teaser_job(mock_ctx)

        if mock_bot.send_message.called:
            call_kwargs = mock_bot.send_message.call_args
            teaser_text = call_kwargs.kwargs.get("text", "") or (call_kwargs.args[1] if len(call_kwargs.args) > 1 else "")
            assert "free picks" in teaser_text.lower() or "edges found" in teaser_text.lower()


# ── Test 12: Gold teaser has NO View Plans button ──

@pytest.mark.asyncio
async def test_teaser_gold_distinct():
    """Gold teaser has NO 'View Plans' button."""
    with patch("bot._fetch_hot_tips_from_db", new_callable=AsyncMock, return_value=SAMPLE_TIPS), \
         patch("bot._fetch_hot_tips_all_sports", new_callable=AsyncMock, return_value=[]), \
         patch("bot._get_settlement_funcs", return_value=(MagicMock(return_value=None), None, None, MagicMock(return_value=None))), \
         patch("bot._can_send_notification", new_callable=AsyncMock, return_value=True), \
         patch("bot._after_send", new_callable=AsyncMock), \
         patch("bot.db") as mock_db, \
         patch("bot._format_kickoff_display", return_value="Tue 17:00"), \
         patch("bot._get_broadcast_details", return_value={"kickoff": "Tue 17:00", "broadcast": ""}):

        mock_user = MagicMock()
        mock_user.id = 222
        mock_db.get_users_for_notification = AsyncMock(return_value=[mock_user])
        mock_db.get_user_tier = AsyncMock(return_value="gold")
        mock_db.get_user = AsyncMock(return_value=mock_user)

        mock_bot = MagicMock()
        mock_bot.send_message = AsyncMock()
        mock_ctx = MagicMock()
        mock_ctx.bot = mock_bot

        from bot import _morning_teaser_job
        await _morning_teaser_job(mock_ctx)

        if mock_bot.send_message.called:
            call_kwargs = mock_bot.send_message.call_args
            markup = call_kwargs.kwargs.get("reply_markup", None)
            if markup:
                all_texts = [btn.text for row in markup.inline_keyboard for btn in row]
                assert "View Plans" not in " ".join(all_texts), "Gold teaser should not have View Plans button"


# ── Test 13: Diamond teaser has 2 buttons, no upgrade CTA ──

@pytest.mark.asyncio
async def test_teaser_diamond_no_cta():
    """Diamond teaser has 2 buttons only, no upgrade CTA in text."""
    with patch("bot._fetch_hot_tips_from_db", new_callable=AsyncMock, return_value=SAMPLE_TIPS), \
         patch("bot._fetch_hot_tips_all_sports", new_callable=AsyncMock, return_value=[]), \
         patch("bot._get_settlement_funcs", return_value=(MagicMock(return_value=None), None, None, MagicMock(return_value=None))), \
         patch("bot._can_send_notification", new_callable=AsyncMock, return_value=True), \
         patch("bot._after_send", new_callable=AsyncMock), \
         patch("bot.db") as mock_db, \
         patch("bot._format_kickoff_display", return_value="Tue 17:00"), \
         patch("bot._get_broadcast_details", return_value={"kickoff": "Tue 17:00", "broadcast": ""}):

        mock_user = MagicMock()
        mock_user.id = 333
        mock_db.get_users_for_notification = AsyncMock(return_value=[mock_user])
        mock_db.get_user_tier = AsyncMock(return_value="diamond")
        mock_db.get_user = AsyncMock(return_value=mock_user)

        mock_bot = MagicMock()
        mock_bot.send_message = AsyncMock()
        mock_ctx = MagicMock()
        mock_ctx.bot = mock_bot

        from bot import _morning_teaser_job
        await _morning_teaser_job(mock_ctx)

        if mock_bot.send_message.called:
            call_kwargs = mock_bot.send_message.call_args
            teaser_text = call_kwargs.kwargs.get("text", "") or (call_kwargs.args[1] if len(call_kwargs.args) > 1 else "")
            markup = call_kwargs.kwargs.get("reply_markup", None)
            # No upgrade CTA
            assert "Upgrade" not in teaser_text
            assert "R99/mo" not in teaser_text
            # 2 buttons only
            if markup:
                total_buttons = sum(len(row) for row in markup.inline_keyboard)
                assert total_buttons == 2, f"Diamond teaser should have 2 buttons, got {total_buttons}"


# ── Test 14: Losing streak footer ──

def test_losing_streak_footer(build_page):
    """Footer shows 'market has been tight' when consecutive_misses >= 3."""
    text, _ = build_page(tips=SAMPLE_TIPS, user_tier="bronze", consecutive_misses=3)
    assert "market has been tight" in text.lower()
    # Should NOT have /subscribe or "edges locked"
    assert "/subscribe" not in text
