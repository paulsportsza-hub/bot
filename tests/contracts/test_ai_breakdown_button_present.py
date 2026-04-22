"""FIX-NARRATIVE-AIBREAKDOWN-REGRESSION-01 — AI Breakdown button contract.

Regression guard for the disappearing AI Breakdown button. Commit 247e077 on
2026-04-20 removed the `source=="edge_picks"` implicit override so the button
only renders when `has_narrative=True` is passed explicitly. Five `edge:detail`
call sites in bot.py never received that parameter after the refactor, so the
button disappeared from every Hot Tips detail card post-deploy (22 Apr 2026).

This test locks:
1. `_build_hot_tips_detail_rows(has_narrative=True)` renders the AI Breakdown
   button for every (tier, narrative_source) combination that reaches the
   detail-card renderer.
2. `_build_game_buttons(source="edge_picks", has_narrative=True)` routes via
   `_build_hot_tips_detail_rows` and emits the same button.
3. `_build_game_buttons(source="matches", has_narrative=True)` emits the AI
   Breakdown button on the My Matches detail path.
4. `_has_any_cached_narrative()` accepts every production `narrative_source`
   (w84, w82, baseline_no_edge, verdict-cache) and honours expiry/quarantine.
5. Every edge:detail / tip:detail / alerts_deeplink call site in bot.py that
   lands on the detail-card renderer passes `has_narrative` explicitly.
"""

from __future__ import annotations

import os
import pathlib
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT.parent))
sys.path.insert(0, str(_REPO_ROOT.parent / "scrapers"))
os.chdir(str(_REPO_ROOT))

import bot


USER_TIERS = ("bronze", "silver", "gold", "diamond")
# Every narrative_source production pregen / live-tap / polish paths emit.
NARRATIVE_SOURCES = ("w84", "w82", "baseline_no_edge", "verdict-cache")


def _extract_button_texts(rows) -> list[str]:
    """Flatten button rows → list of button texts (skips url/callback metadata)."""
    out: list[str] = []
    for row in rows:
        for btn in row:
            text = getattr(btn, "text", "") or ""
            out.append(text)
    return out


def _has_ai_breakdown_button(rows) -> bool:
    """True when any button in the markup matches the AI Breakdown label."""
    for text in _extract_button_texts(rows):
        # Both 🤖 Full AI Breakdown (diamond) and 🔒 Full AI Breakdown (gated)
        # must count — both lead to the breakdown or upgrade flow.
        if "Full AI Breakdown" in text:
            return True
    return False


class TestHotTipsDetailRowsContract:
    """_build_hot_tips_detail_rows is the canonical button builder for Hot Tips."""

    @pytest.mark.parametrize("user_tier", USER_TIERS)
    def test_button_present_when_has_narrative_true(self, user_tier):
        rows = bot._build_hot_tips_detail_rows(
            user_id=1001,
            match_key=f"arsenal_vs_tottenham_2026-05-01",
            primary_button=None,
            fallback_page=0,
            user_tier=user_tier,
            has_narrative=True,
        )
        assert _has_ai_breakdown_button(rows), (
            f"AI Breakdown button missing for user_tier={user_tier}. "
            f"Buttons: {_extract_button_texts(rows)}"
        )

    @pytest.mark.parametrize("user_tier", USER_TIERS)
    def test_button_suppressed_when_has_narrative_false(self, user_tier):
        rows = bot._build_hot_tips_detail_rows(
            user_id=1001,
            match_key="arsenal_vs_tottenham_2026-05-01",
            primary_button=None,
            fallback_page=0,
            user_tier=user_tier,
            has_narrative=False,
        )
        assert not _has_ai_breakdown_button(rows), (
            f"AI Breakdown button must NOT render when has_narrative=False "
            f"(user_tier={user_tier}). Buttons: {_extract_button_texts(rows)}"
        )

    def test_button_suppressed_when_match_key_missing(self):
        rows = bot._build_hot_tips_detail_rows(
            user_id=1001,
            match_key="",
            primary_button=None,
            fallback_page=0,
            user_tier="diamond",
            has_narrative=True,
        )
        assert not _has_ai_breakdown_button(rows), (
            "AI Breakdown button must NOT render without a match_key — "
            "breakdown callback needs the key to resolve the narrative."
        )

    def test_diamond_gets_breakdown_callback(self):
        rows = bot._build_hot_tips_detail_rows(
            user_id=1001,
            match_key="arsenal_vs_tottenham_2026-05-01",
            primary_button=None,
            fallback_page=0,
            user_tier="diamond",
            has_narrative=True,
        )
        for row in rows:
            for btn in row:
                if "Full AI Breakdown" in (btn.text or ""):
                    cb = getattr(btn, "callback_data", "") or ""
                    assert cb.startswith("edge:breakdown:"), (
                        f"Diamond AI Breakdown must route to edge:breakdown: "
                        f"(got {cb!r})"
                    )
                    return
        pytest.fail("AI Breakdown button not found for diamond user")

    @pytest.mark.parametrize("user_tier", ("bronze", "silver", "gold"))
    def test_non_diamond_routes_to_gate(self, user_tier):
        rows = bot._build_hot_tips_detail_rows(
            user_id=1001,
            match_key="arsenal_vs_tottenham_2026-05-01",
            primary_button=None,
            fallback_page=0,
            user_tier=user_tier,
            has_narrative=True,
        )
        for row in rows:
            for btn in row:
                if "Full AI Breakdown" in (btn.text or ""):
                    cb = getattr(btn, "callback_data", "") or ""
                    assert cb.startswith("edge:breakdown_gate:"), (
                        f"Non-diamond AI Breakdown must route to edge:breakdown_gate: "
                        f"(got {cb!r} for tier={user_tier})"
                    )
                    return
        pytest.fail(f"AI Breakdown button not found for tier={user_tier}")


class TestBuildGameButtonsEdgePicksContract:
    """_build_game_buttons(source='edge_picks') delegates to hot tips rows."""

    @pytest.mark.parametrize("user_tier", USER_TIERS)
    @pytest.mark.parametrize("edge_tier", ("bronze", "silver", "gold", "diamond"))
    def test_edge_picks_has_breakdown_when_narrative_present(self, user_tier, edge_tier):
        tip = {
            "match_id": "arsenal_vs_tottenham_2026-05-01",
            "home_team": "Arsenal",
            "away_team": "Tottenham",
            "outcome": "home",
            "ev": 3.2,
            "odds": 2.10,
            "bookmaker": "Betway",
            "bookmaker_key": "betway",
            "odds_by_bookmaker": {"betway": {"home": 2.10, "away": 3.80, "draw": 3.20}},
            "edge_rating": edge_tier,
            "display_tier": edge_tier,
        }
        markup = bot._build_game_buttons(
            [tip],
            event_id="arsenal_vs_tottenham_2026-05-01",
            user_id=1001,
            source="edge_picks",
            user_tier=user_tier,
            edge_tier=edge_tier,
            has_narrative=True,
        )
        assert _has_ai_breakdown_button(markup), (
            f"edge_picks source with has_narrative=True must include AI Breakdown "
            f"button (user_tier={user_tier}, edge_tier={edge_tier}). "
            f"Buttons: {_extract_button_texts(markup)}"
        )

    @pytest.mark.parametrize("user_tier", USER_TIERS)
    def test_edge_picks_suppresses_breakdown_when_no_narrative(self, user_tier):
        tip = {
            "match_id": "arsenal_vs_tottenham_2026-05-01",
            "home_team": "Arsenal",
            "away_team": "Tottenham",
            "outcome": "home",
            "ev": 3.2,
            "odds": 2.10,
            "bookmaker": "Betway",
            "bookmaker_key": "betway",
        }
        markup = bot._build_game_buttons(
            [tip],
            event_id="arsenal_vs_tottenham_2026-05-01",
            user_id=1001,
            source="edge_picks",
            user_tier=user_tier,
            edge_tier="gold",
            has_narrative=False,
        )
        assert not _has_ai_breakdown_button(markup), (
            f"edge_picks source with has_narrative=False must NOT show the "
            f"breakdown button (user_tier={user_tier})."
        )


class TestBuildGameButtonsMatchesContract:
    """source='matches' (My Matches edge cards) honours has_narrative."""

    @pytest.mark.parametrize("user_tier", USER_TIERS)
    def test_matches_has_breakdown_when_narrative_present(self, user_tier):
        tip = {
            "match_id": "arsenal_vs_tottenham_2026-05-01",
            "home_team": "Arsenal",
            "away_team": "Tottenham",
            "outcome": "home",
            "ev": 3.2,
            "odds": 2.10,
            "bookmaker": "Betway",
            "bookmaker_key": "betway",
            "edge_rating": "gold",
            "display_tier": "gold",
        }
        markup = bot._build_game_buttons(
            [tip],
            event_id="arsenal_vs_tottenham_2026-05-01",
            user_id=1001,
            source="matches",
            user_tier=user_tier,
            edge_tier="gold",
            has_narrative=True,
        )
        assert _has_ai_breakdown_button(markup), (
            f"matches source with has_narrative=True must include AI Breakdown "
            f"(user_tier={user_tier}). Buttons: {_extract_button_texts(markup)}"
        )

    def test_matches_suppresses_breakdown_when_no_narrative(self):
        tip = {
            "match_id": "arsenal_vs_tottenham_2026-05-01",
            "home_team": "Arsenal",
            "away_team": "Tottenham",
            "outcome": "home",
            "ev": 0,
            "odds": 2.10,
            "bookmaker": "Betway",
            "bookmaker_key": "betway",
        }
        markup = bot._build_game_buttons(
            [tip],
            event_id="arsenal_vs_tottenham_2026-05-01",
            user_id=1001,
            source="matches",
            user_tier="diamond",
            edge_tier="bronze",
            has_narrative=False,
        )
        assert not _has_ai_breakdown_button(markup), (
            "No-narrative My Matches taps must NOT show AI Breakdown button."
        )


class TestHasAnyCachedNarrativeContract:
    """_has_any_cached_narrative accepts every production narrative_source."""

    @pytest.fixture
    def synthetic_db(self, monkeypatch, tmp_path):
        """Build a minimal narrative_cache table we can point bot at."""
        db_path = tmp_path / "test_narrative.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE narrative_cache (
                match_id TEXT PRIMARY KEY,
                narrative_html TEXT NOT NULL,
                model TEXT NOT NULL,
                edge_tier TEXT NOT NULL,
                tips_json TEXT NOT NULL,
                odds_hash TEXT NOT NULL,
                evidence_json TEXT,
                narrative_source TEXT NOT NULL DEFAULT 'w82',
                coverage_json TEXT,
                created_at TEXT,
                expires_at TEXT,
                quarantined INTEGER DEFAULT 0,
                verdict_html TEXT,
                evidence_class TEXT
            )
        """)
        conn.commit()
        conn.close()
        monkeypatch.setattr(bot, "_NARRATIVE_DB_PATH", str(db_path))
        return db_path

    @pytest.mark.parametrize("narrative_source", NARRATIVE_SOURCES)
    def test_helper_accepts_every_narrative_source(self, synthetic_db, narrative_source):
        """Gate must not filter by source — build_ai_breakdown_data reads any source."""
        match_id = f"arsenal_vs_tottenham_2026-05-01_{narrative_source}"
        expires_at = (datetime.now(timezone.utc) + timedelta(hours=6)).isoformat()
        conn = sqlite3.connect(str(synthetic_db))
        conn.execute(
            "INSERT INTO narrative_cache "
            "(match_id, narrative_html, model, edge_tier, tips_json, odds_hash, "
            " narrative_source, expires_at, quarantined) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)",
            (match_id, "<b>Setup</b>...", "sonnet", "bronze", "[]", "abc",
             narrative_source, expires_at),
        )
        conn.commit()
        conn.close()

        assert bot._has_any_cached_narrative(match_id) is True, (
            f"_has_any_cached_narrative rejected narrative_source={narrative_source!r} "
            f"— must accept ALL sources the pregen pipeline emits."
        )

    def test_helper_rejects_quarantined_rows(self, synthetic_db):
        match_id = "arsenal_vs_tottenham_2026-05-01_quar"
        expires_at = (datetime.now(timezone.utc) + timedelta(hours=6)).isoformat()
        conn = sqlite3.connect(str(synthetic_db))
        conn.execute(
            "INSERT INTO narrative_cache "
            "(match_id, narrative_html, model, edge_tier, tips_json, odds_hash, "
            " narrative_source, expires_at, quarantined) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)",
            (match_id, "<b>Setup</b>...", "sonnet", "bronze", "[]", "abc",
             "w84", expires_at),
        )
        conn.commit()
        conn.close()

        assert bot._has_any_cached_narrative(match_id) is False, (
            "Quarantined rows must NOT arm the AI Breakdown button — they won't "
            "render in build_ai_breakdown_data either."
        )

    def test_helper_rejects_expired_rows(self, synthetic_db):
        match_id = "arsenal_vs_tottenham_2026-05-01_expired"
        expires_at = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        conn = sqlite3.connect(str(synthetic_db))
        conn.execute(
            "INSERT INTO narrative_cache "
            "(match_id, narrative_html, model, edge_tier, tips_json, odds_hash, "
            " narrative_source, expires_at, quarantined) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)",
            (match_id, "<b>Setup</b>...", "sonnet", "bronze", "[]", "abc",
             "w84", expires_at),
        )
        conn.commit()
        conn.close()

        assert bot._has_any_cached_narrative(match_id) is False, (
            "Expired rows must NOT arm the AI Breakdown button."
        )

    def test_helper_returns_false_for_empty_match_id(self):
        assert bot._has_any_cached_narrative("") is False
        assert bot._has_any_cached_narrative(None) is False  # type: ignore[arg-type]


class TestCallSitesPassHasNarrative:
    """Static guard: every detail-card _build_game_buttons call site passes has_narrative.

    Regression source for commit 247e077 was partial refactor — future edits
    adding a new cache-hit path must pass has_narrative or fail this guard.
    """

    def test_all_detail_card_call_sites_pass_has_narrative(self):
        bot_py_raw = (_REPO_ROOT / "bot.py").read_text(encoding="utf-8")
        # Strip line comments so regex doesn't match `# _build_game_buttons()` prose.
        # Simple scrub: for each line, drop text from the first unescaped # that is not
        # inside a string. We accept a little imprecision because comments mentioning
        # the call site in prose should never count as call sites.
        scrubbed_lines: list[str] = []
        for raw in bot_py_raw.splitlines():
            # Heuristic: a leading-spaces `#` followed by text is pure comment.
            stripped = raw.lstrip()
            if stripped.startswith("#"):
                scrubbed_lines.append("")
                continue
            # Drop trailing `  # comment` on the line while keeping code intact.
            # This is fine because any `#` inside a string is rare in call-site lines.
            if "  #" in raw:
                raw = raw.split("  #", 1)[0]
            scrubbed_lines.append(raw)
        bot_py = "\n".join(scrubbed_lines)

        # Find every _build_game_buttons( invocation and its immediate argument block.
        # The block ends at the first matching ).
        pattern = re.compile(
            r"_build_game_buttons\(([^()]*(?:\([^()]*\)[^()]*)*)\)",
            re.DOTALL,
        )
        missing: list[str] = []
        for match in pattern.finditer(bot_py):
            block = match.group(0)
            args = match.group(1).strip()
            # Skip the function definition itself: first positional arg is `tips`.
            # A definition always has a type annotation or default.
            if ":" in args.split(",")[0] if args else False:
                continue
            # Skip zero-arg matches (false positives from any residual prose).
            if not args:
                continue
            if "has_narrative" not in block:
                start = match.start()
                line_no = bot_py_raw[:start].count("\n") + 1
                missing.append(
                    f"  bot.py:{line_no} — block: {block[:120].replace(chr(10), ' ')}"
                )
        assert not missing, (
            "Every _build_game_buttons() call site on the detail-card render path "
            "must pass has_narrative explicitly. Missing call sites:\n"
            + "\n".join(missing)
        )
