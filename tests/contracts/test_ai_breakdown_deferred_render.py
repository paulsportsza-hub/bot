"""FIX-AI-BREAKDOWN-DEFERRED-PLACEHOLDER-RENDER-01 — AC-1 + AC-3.

The AI Breakdown template (`card_templates/ai_breakdown.html`) MUST render
cleanly given any of three input shapes:

1. **Deferred sentinel** — `{"deferred": True, "match_id": ...,
   "edge_tier": "gold", "defer_count": 1, "fixture": ""}` from
   `card_data._check_premium_defer` / `_check_premium_quarantined`.
   No `setup_html`, `edge_html`, `risk_html`, `verdict_html`, `ev_pct`,
   `home`, `away`, `tier_label`, `verdict_tag`. The template's bare
   `{% if ev_pct > 0 %}` was the leak vector pre-fix — Jinja default
   `Undefined` raises on `> 0` comparison.

2. **Full breakdown** — the standard 4-section dict from
   `build_ai_breakdown_data` with all fields populated. Pre-fix render
   path; must remain unchanged.

3. **Partial / orphan** — `None` / empty / partial dicts. Should NOT
   crash the template even if rendered (defence in depth — the live
   handler `_handle_ai_breakdown` short-circuits on these).

This test exercises the template directly against synthetic inputs.
The wider end-to-end harness lives at
`tests/qa/fix_ai_breakdown_deferred_placeholder_render_01_telethon.py`.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Add the bot dir to sys.path so we can import card_templates.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


_TEMPLATE_PATH = Path(__file__).parents[2] / "card_templates" / "ai_breakdown.html"


def _render_template(data: dict) -> str:
    """Render the template against a synthetic data dict and return the HTML.

    Bypasses the Playwright pipeline (we don't need PNG bytes, we just need
    to confirm the Jinja render doesn't crash).
    """
    from jinja2 import Environment, FileSystemLoader

    template_dir = _TEMPLATE_PATH.parent
    env = Environment(loader=FileSystemLoader(str(template_dir)), autoescape=True)
    template = env.get_template("ai_breakdown.html")
    return template.render(**data)


# ─────────────────────────────────────────────────────────────────────────────
# AC-1: Deferred sentinel renders the placeholder block, never crashes.
# ─────────────────────────────────────────────────────────────────────────────


def test_deferred_sentinel_renders_placeholder_block():
    """A deferred sentinel from _check_premium_defer/_check_premium_quarantined
    MUST render the placeholder block instead of crashing on undefined fields."""
    data = {
        "deferred": True,
        "match_id": "liverpool_vs_chelsea_2026-05-09",
        "edge_tier": "gold",
        "defer_count": 1,
        "fixture": "",
    }
    html = _render_template(data)
    assert "AI Breakdown updating" in html, (
        "Deferred sentinel MUST render the 'AI Breakdown updating' placeholder. "
        "Pre-fix the template crashed with `'ev_pct' is undefined` and the user "
        "saw '❌ Could not render breakdown'."
    )
    assert "regenerating right now" in html, (
        "Placeholder body text must explain the regenerating state"
    )
    # The 4-section layout must NOT render in deferred mode — the deferred
    # dict carries no setup_html/edge_html/risk_html/verdict_html so injecting
    # them as `{{ ... | safe }}` would render empty divs.
    assert "The Setup" not in html or "AI Breakdown updating" in html
    # Specifically: tag-red CAUTION (the Risk section header tag) must NOT
    # appear in deferred mode.
    assert "CAUTION" not in html, (
        "Deferred mode must NOT render the 4-section card body — only the "
        "placeholder block"
    )


def test_deferred_sentinel_with_quarantine_reason_renders_cleanly():
    """The quarantine path (FIX-PREMIUM-POSTWRITE-PROTECTION-01 AC-2)
    surfaces deferred=True with a quarantine_reason key. Same render path."""
    data = {
        "deferred": True,
        "match_id": "brentford_vs_west_ham_2026-05-02",
        "edge_tier": "gold",
        "defer_count": 0,
        "fixture": "",
        "quarantine_reason": "ev_incoherent:cached=0.5,live=3.0",
    }
    html = _render_template(data)
    assert "AI Breakdown updating" in html


def test_deferred_with_no_ev_pct_does_not_crash():
    """The pre-fix crash signature: 'ev_pct' is undefined. With the deferred
    branch in place, the Jinja render MUST complete without raising."""
    data = {"deferred": True, "match_id": "x", "edge_tier": "diamond"}
    # If this test raises, the template still has unguarded `ev_pct > 0` in the
    # deferred branch — the fix is broken.
    html = _render_template(data)
    assert html  # non-empty — it rendered


# ─────────────────────────────────────────────────────────────────────────────
# AC-1: Standard full-data render path is unchanged (regression guard).
# ─────────────────────────────────────────────────────────────────────────────


def test_full_data_renders_4_sections():
    """Backward-compat: full data (4 sections + header) must render exactly
    as before — the deferred branch is opt-in via `deferred=True`."""
    data = {
        "home": "Arsenal",
        "away": "Fulham",
        "tier_label": "🥇 GOLD EDGE",
        "ev_pct": 4.5,
        "verdict_tag": "GOLD",
        "setup_html": "<p>Arsenal arrive in form.</p>",
        "edge_html": "<p>The price gap is real.</p>",
        "risk_html": "<p>Form gap.</p>",
        "verdict_prose_html": "<p>Lean home.</p>",
        "cap_reason": "",
    }
    html = _render_template(data)
    # All 4 sections must render
    assert "The Setup" in html
    assert "The Edge" in html
    assert "The Risk" in html
    assert "Verdict" in html
    # EV badge renders the value
    assert "+4.5% EV" in html
    # Header renders teams + tier
    assert "Arsenal" in html
    assert "Fulham" in html
    # Placeholder block must NOT render in non-deferred mode
    assert "AI Breakdown updating" not in html


def test_full_data_with_zero_ev_pct_uses_bare_label():
    """ev_pct=0 path: the EV badge falls back to the bare 'EV' label,
    not '+0.0% EV'."""
    data = {
        "home": "Liverpool",
        "away": "Chelsea",
        "tier_label": "🥇 GOLD EDGE",
        "ev_pct": 0,  # Falsy but defined
        "verdict_tag": "GOLD",
        "setup_html": "<p>S.</p>",
        "edge_html": "<p>E.</p>",
        "risk_html": "<p>R.</p>",
        "verdict_prose_html": "<p>V.</p>",
        "cap_reason": "",
    }
    html = _render_template(data)
    # The defensive guard `ev_pct is defined and ev_pct and ev_pct > 0`
    # short-circuits on 0 (falsy), so no '+0.0% EV' label.
    assert "+0.0%" not in html
    assert ">EV<" in html  # bare 'EV' label inside the tag


def test_full_data_with_undefined_ev_pct_does_not_crash():
    """Defence-in-depth: even on the non-deferred path, the template MUST
    NOT crash if ev_pct is undefined. Pre-fix the bare `{% if ev_pct > 0 %}`
    crashed; post-fix the `is defined` guard short-circuits."""
    data = {
        "home": "Liverpool",
        "away": "Chelsea",
        "tier_label": "🥇 GOLD EDGE",
        # ev_pct intentionally OMITTED — should NOT crash the template
        "verdict_tag": "GOLD",
        "setup_html": "<p>S.</p>",
        "edge_html": "<p>E.</p>",
        "risk_html": "<p>R.</p>",
        "verdict_prose_html": "<p>V.</p>",
        "cap_reason": "",
    }
    # Pre-fix this raised UndefinedError on `ev_pct > 0`. Post-fix it renders.
    html = _render_template(data)
    assert "The Setup" in html
    assert "+0.0%" not in html  # no fabricated EV badge


# ─────────────────────────────────────────────────────────────────────────────
# AC-1 wiring guards (structural — easy to grep, hard to silently revert).
# ─────────────────────────────────────────────────────────────────────────────


def test_template_carries_deferred_branch_marker():
    """Structural guard: the template MUST contain the deferred branch marker
    so future edits don't silently remove it."""
    template_text = _TEMPLATE_PATH.read_text(encoding="utf-8")
    assert "{% if deferred is defined and deferred %}" in template_text, (
        "Deferred branch missing from ai_breakdown.html — re-introduce or the "
        "template will crash on quarantined Gold/Diamond rows"
    )
    assert "FIX-AI-BREAKDOWN-DEFERRED-PLACEHOLDER-RENDER-01" in template_text, (
        "Brief marker must remain in the template comment block"
    )


def test_template_ev_pct_guard_uses_is_defined():
    """Structural guard: the EV-percent conditional MUST use `is defined`
    so that an undefined ev_pct doesn't crash. Pre-fix was bare `ev_pct > 0`."""
    template_text = _TEMPLATE_PATH.read_text(encoding="utf-8")
    # The bare unguarded comparison was the leak vector — must NOT appear.
    assert "{% if ev_pct > 0 %}" not in template_text, (
        "Bare `{% if ev_pct > 0 %}` re-introduced — undefined ev_pct will "
        "crash the template again"
    )
    # The defensive guard must be present.
    assert "ev_pct is defined" in template_text, (
        "Defensive `is defined` guard missing on ev_pct conditional"
    )


def test_handler_short_circuits_before_render():
    """Structural guard: bot.py::_handle_ai_breakdown MUST call
    `_build_bd_data` BEFORE `render_ai_breakdown_card`. Pre-fix, an
    `asyncio.gather` ran them in parallel — the render crash on the
    deferred sentinel propagated up before the deferred check could
    short-circuit. Post-fix, the build runs first, the deferred check
    fires, and render is only invoked when data is full-shape."""
    bot_path = Path(__file__).parents[2] / "bot.py"
    src = bot_path.read_text(encoding="utf-8")
    # The pre-fix asyncio.gather pattern must be gone.
    assert "asyncio.gather(\n            asyncio.to_thread(render_ai_breakdown_card, match_key)" not in src, (
        "Pre-fix asyncio.gather(render, build) pattern is back — the deferred "
        "check cannot short-circuit before render crashes"
    )
    # The new short-circuit log marker must be present.
    assert "FIX-AI-BREAKDOWN-DEFERRED-PLACEHOLDER-RENDER-01 PlaceholderServed" in src, (
        "PlaceholderServed log marker missing from _handle_ai_breakdown — "
        "QA observability is broken"
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
