"""FIX-PREGEN-COVERAGE-DIAMOND-01 — regression guard.

Two pre-launch gates that policed "Gold/Diamond cards must be Sonnet-polished
or no row at all" are LIFTED:

1. Stream4 refusal at bot.py::_store_narrative_cache (formerly returned early
   on `narrative_source in ("w82", "baseline_no_edge") AND edge_tier in ("gold",
   "diamond")`).
2. Serve-time `w82_for_tier:gold|diamond` quarantine at
   bot.py::_get_cached_narrative (formerly returned None + UPDATE SET status =
   'quarantined' on premium-tier baseline reads).

Justification: locked Rules 12, 14, 17, 18 ensure w82 templates produce
editorial-quality content suitable for any tier. The original gates were
correct in pre-launch architecture when w82 was lower quality. Together with
FIX-AI-BREAKDOWN-BUTTON-GATE-COVERAGE-01 (Rule 20), the bulletproof
contract is: edge exists → button shows → content renders, regardless of
tier or polish state.

Tests:
- Stream4 refusal removed (writer accepts w82 + Gold/Diamond)
- Premium-tier baseline writes are LOGGED (monitorable polish-failure rate)
- Serve-time gate removed (reader returns w82 row for Gold/Diamond)
- Premium-tier baseline serves are LOGGED
- Quarantine reason `w82_for_tier:` is no longer set anywhere
- CLAUDE.md Rule 21 carries the lift documentation
"""
from __future__ import annotations

from pathlib import Path

import pytest


_BOT_PY = Path(__file__).resolve().parents[2] / "bot.py"
_CLAUDE_MD = Path(__file__).resolve().parents[2] / "CLAUDE.md"


# ── Source-level: writer no longer refuses ────────────────────────────────────


def test_stream4_refusal_removed_from_writer():
    """The pregen writer must NOT early-return on (w82|baseline_no_edge) + (gold|diamond).

    Previously: lines 15198-15206 had a `return` statement after a Stream4Refused
    log warning. Now: the warning is replaced with a PremiumW82Write log + no
    early return — pregen persists the safety-net baseline.
    """
    src = _BOT_PY.read_text()
    # The full _store_narrative_cache function body
    fn_start = src.index("async def _store_narrative_cache(")
    fn_end = src.index("\nasync def _store_narrative_evidence", fn_start)
    fn_body = src[fn_start:fn_end]

    # Smoke check: function body still references w82 + gold/diamond
    assert '"w82"' in fn_body or "'w82'" in fn_body
    assert '"gold"' in fn_body or "'gold'" in fn_body

    # The old refusal log message must be gone
    assert "Stream4Refused" not in fn_body, (
        "Stream4Refused log line still present — Stream4 refusal not fully lifted. "
        "Re-introducing the refusal will reopen the FIX-PREGEN-COVERAGE-DIAMOND-01 "
        "coverage gap."
    )

    # The lift-marker log message must be present
    assert "PremiumW82Write" in fn_body, (
        "Premium-tier baseline writes must be logged so polish-failure rates "
        "remain monitorable in journalctl."
    )

    # Verify no early-return branches into the (w82, gold|diamond) condition.
    # Use indent-based block scoping (sibling-aware) to avoid picking up `return`
    # statements from later sibling blocks at the same indent.
    cond_idx = fn_body.index("if _wg_src in (\"w82\", \"baseline_no_edge\")")
    line_start = fn_body.rfind("\n", 0, cond_idx) + 1
    if_line = fn_body[line_start: fn_body.index("\n", cond_idx)]
    if_indent = len(if_line) - len(if_line.lstrip())

    block_lines: list[str] = []
    cursor = fn_body.index("\n", cond_idx) + 1
    while cursor < len(fn_body):
        next_nl = fn_body.find("\n", cursor)
        if next_nl == -1:
            line = fn_body[cursor:]
            cursor = len(fn_body)
        else:
            line = fn_body[cursor:next_nl]
            cursor = next_nl + 1
        if not line.strip():
            block_lines.append(line)
            continue
        indent = len(line) - len(line.lstrip())
        if indent <= if_indent:
            break
        block_lines.append(line)

    block_body = "\n".join(block_lines)
    if "return" in block_body:
        # Allow `return` in nested function definitions if any (defensive),
        # but reject any top-level-of-block `return` statement.
        for line in block_lines:
            stripped = line.strip()
            if stripped.startswith("return"):
                pytest.fail(
                    "Stream4 (w82/baseline_no_edge × gold/diamond) conditional "
                    "still contains a `return` — refusal not fully lifted. "
                    f"Pregen will continue silent-dropping premium-tier baseline "
                    f"rows. Block was:\n---\n{block_body}\n---"
                )


# ── Source-level: reader no longer quarantines ────────────────────────────────


def test_w82_for_tier_quarantine_lifted():
    """Serve-time gate at bot.py::_get_cached_narrative must NOT return None on
    (w82|baseline_no_edge) + (gold|diamond). It also must NOT issue an UPDATE
    SET quarantine_reason = 'w82_for_tier:...' for these rows."""
    src = _BOT_PY.read_text()
    fn_start = src.index("async def _get_cached_narrative(")
    # Bound to next async def
    fn_end = src.index("\nasync def _store_narrative_cache(", fn_start)
    fn_body = src[fn_start:fn_end]

    assert "w82_for_tier:" not in fn_body, (
        "Quarantine reason 'w82_for_tier:' still appears in _get_cached_narrative. "
        "The lift is incomplete and premium-tier rows will continue being "
        "quarantined on read, leaving the AI Breakdown button hidden."
    )

    # Scope to ONLY the lifted conditional block. Find its `if` line, then
    # capture lines until the next sibling `if`/`else`/`elif` at the same indent
    # (i.e. until we exit this conditional block).
    cond_text = (
        "narrative_source in (\"w82\", \"baseline_no_edge\") "
        "and tier in (\"gold\", \"diamond\")"
    )
    assert cond_text in fn_body, (
        "Premium-tier conditional removed entirely — log marker won't fire. "
        "Keep the conditional as a logging hook even after lifting the gate."
    )
    cond_idx = fn_body.index(cond_text)
    # Determine the indent of the `if` line itself
    line_start = fn_body.rfind("\n", 0, cond_idx) + 1
    if_line = fn_body[line_start: fn_body.index("\n", cond_idx)]
    if_indent = len(if_line) - len(if_line.lstrip())

    # Walk forward line-by-line and collect ONLY lines whose indent is STRICTLY
    # GREATER than if_indent (i.e. the body of the if block). Stop at the first
    # line whose indent is ≤ if_indent.
    block_lines: list[str] = []
    cursor = fn_body.index("\n", cond_idx) + 1
    while cursor < len(fn_body):
        next_nl = fn_body.find("\n", cursor)
        if next_nl == -1:
            line = fn_body[cursor:]
            cursor = len(fn_body)
        else:
            line = fn_body[cursor:next_nl]
            cursor = next_nl + 1
        if not line.strip():
            block_lines.append(line)
            continue
        indent = len(line) - len(line.lstrip())
        if indent <= if_indent:
            break
        block_lines.append(line)

    # Strip line comments before scanning for `return` — comments can mention
    # `return None` informationally without being a real return statement.
    code_only_lines = [
        line.split("#", 1)[0].rstrip()
        for line in block_lines
        if line.split("#", 1)[0].strip()
    ]
    code_only_body = "\n".join(code_only_lines)
    for stripped in (l.strip() for l in code_only_lines):
        if stripped.startswith("return"):
            pytest.fail(
                "Serve-time premium-w82 conditional block still contains a "
                "`return` statement (executable, not in a comment). The lift "
                "is incomplete — readers will treat premium baselines as cache "
                "miss, leaving the button hidden when polish fails. Code-only "
                f"block was:\n---\n{code_only_body}\n---"
            )

    # The lift-marker log message must be present
    assert "PremiumW82Serve" in fn_body, (
        "Premium-tier baseline serves must be logged so polish-failure rates "
        "remain monitorable in journalctl."
    )


def test_gate_lift_log_messages_use_brief_id():
    """Both lift-marker logs reference the brief ID for traceability."""
    src = _BOT_PY.read_text()
    assert "FIX-PREGEN-COVERAGE-DIAMOND-01 PremiumW82Write" in src
    assert "FIX-PREGEN-COVERAGE-DIAMOND-01 PremiumW82Serve" in src


# ── Source-level: card-image surface still independent ────────────────────────


def test_get_cached_verdict_still_serves_verdict_cache_rows_for_card():
    """AC-13 from the prior brief: card-image (verdict_html) surface must not
    be touched. _get_cached_verdict has no narrative_html filter and no tier
    policy — verdict-cache rows produced by _store_verdict_cache_sync continue
    to fill the card image's verdict box.
    """
    src = _BOT_PY.read_text()
    fn_start = src.index("def _get_cached_verdict(match_key: str)")
    fn_end = src.index("\ndef ", fn_start + 1)
    fn_body = src[fn_start:fn_end]
    assert "SELECT verdict_html" in fn_body
    assert "LENGTH(TRIM(COALESCE(narrative_html" not in fn_body
    assert "w82_for_tier" not in fn_body


# ── CLAUDE.md ─────────────────────────────────────────────────────────────────


def test_claude_md_rule_21_present():
    md = _CLAUDE_MD.read_text()
    assert "### Rule 21 — w82 / baseline_no_edge are valid for ALL tiers" in md
    assert "FIX-PREGEN-COVERAGE-DIAMOND-01" in md
