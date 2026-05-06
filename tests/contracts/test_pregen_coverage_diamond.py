"""FIX-PREGEN-COVERAGE-DIAMOND-01 — partial regression guard.

History:
- 2026-04-28 (FIX-PREGEN-COVERAGE-DIAMOND-01): Two pre-launch gates lifted —
  Stream4 refusal at `_store_narrative_cache` and serve-time `w82_for_tier`
  quarantine at `_get_cached_narrative` — to fix the "missing AI Breakdown
  button" symptom on premium-tier edges with failed Sonnet polish.
- 2026-04-30 (FIX-DROP-SONNET-POLISH-W82-CANONICAL-01): the writer-level
  premium W82 refusal was lifted again because W82 became the canonical
  narrative path for all tiers. Premium write safety now comes from the unified
  persistence validator, not from a blanket source/tier ban.

Tests below cover the 2026-04-28 lifts that REMAIN intact:
- Serve-time gate removed (reader returns w82 row for Gold/Diamond when one
  exists).
- Quarantine reason `w82_for_tier:` is no longer set anywhere.
- CLAUDE.md Rule 21 carries the validator-driven premium W82 documentation.

The writer-level behaviour is now covered by the unified persistence validator
contracts and `test_no_gold_baseline_writes.py`.
"""
from __future__ import annotations

from pathlib import Path

import pytest


_BOT_PY = Path(__file__).resolve().parents[2] / "bot.py"
_CLAUDE_MD = Path(__file__).resolve().parents[2] / "CLAUDE.md"


# ── Source-level: writer-level premium validator guard ───────────────────────
#
# Premium W82 rows are allowed by source/tier, but the writer must still refuse
# premium rows that fail the unified persistence validator.


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
    """Lift-marker logs reference the relevant brief ID for traceability.

    The 2026-04-28 read-side lift kept its `PremiumW82Serve` marker.
    The writer-side source/tier refusal marker is retired; premium write
    refusals now happen through `PremiumValidatorRefused`.
    """
    src = _BOT_PY.read_text()
    assert "FIX-PREGEN-COVERAGE-DIAMOND-01 PremiumW82Serve" in src
    assert "PremiumValidatorRefused" in src
    assert "Rule 24 premium-W82 refusal lifted" in src
    assert "PremiumW82WriteRefused" not in src
    assert "FIX-PREGEN-COVERAGE-DIAMOND-01 PremiumW82Write " not in src, (
        "Old PremiumW82Write marker still present — writer-level policy should "
        "be enforced by the unified persistence validator, not source/tier ban."
    )


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
    assert "### Rule 21 — premium w82 / baseline_no_edge writes are validator-driven" in md
    assert "FIX-PREGEN-COVERAGE-DIAMOND-01" in md
    assert "PremiumW82Serve" in md
    assert "PremiumValidatorRefused" in md
    assert "PremiumW82Write" not in md
