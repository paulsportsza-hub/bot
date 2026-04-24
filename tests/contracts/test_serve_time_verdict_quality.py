"""BUILD-NARRATIVE-WATERTIGHT-01 C.1 regression guard.

Asserts that ``_get_cached_narrative`` invokes ``min_verdict_quality`` on
the standalone ``verdict_html`` column before returning a cached row.

BUILD-C1-OPTIONA-PHASE1-BREAKDOWN-01 AC-1: The embedded-verdict check
(_embedded_ok) was removed. C.1 now gates ONLY on verdict_html
(standalone_ok). The AI Breakdown 🏆 fallback in card_data.py handles
thin embedded verdicts at serve time. See Narrative Wiring Bible v1 §2 Q1.
"""
from __future__ import annotations

import inspect
import re

import pytest


@pytest.fixture(scope="module")
def bot_module():
    import bot

    return bot


def test_get_cached_narrative_invokes_min_verdict_quality(bot_module):
    fn = getattr(bot_module, "_get_cached_narrative", None)
    assert fn is not None, "_get_cached_narrative must remain exported"
    try:
        src = inspect.getsource(fn)
    except (OSError, TypeError):
        pytest.skip("cannot inspect source of _get_cached_narrative")

    # Gate must be wired into the cache-hit path — look for the two
    # load-bearing tokens: the gate function and the standalone verdict_html
    # column. A quarantine UPDATE on failure must also be present.
    assert "min_verdict_quality" in src, (
        "BUILD-NARRATIVE-WATERTIGHT-01 C.1: _get_cached_narrative must call "
        "min_verdict_quality on the cached verdict before returning."
    )
    assert re.search(r"verdict_html", src), (
        "BUILD-NARRATIVE-WATERTIGHT-01 C.1: _get_cached_narrative must "
        "evaluate the standalone verdict_html column."
    )
    # FIX-NARRATIVE-CACHE-DEATH-01: quarantine-on-reject replaces DELETE.
    assert re.search(
        r"status\s*=\s*['\"]quarantined['\"]", src, re.IGNORECASE
    ), (
        "FIX-NARRATIVE-CACHE-DEATH-01: _get_cached_narrative must set "
        "status='quarantined' (not DELETE) on quality-gate rejection."
    )
    # AC-1 guard: _embedded_ok must NOT appear in the gate path.
    # C.1 is standalone_ok only — the embedded check was the root cause of
    # 67% unnecessary quarantines (16/24 rows, verdict_quality:embedded_ok=False).
    assert "_embedded_ok" not in src, (
        "BUILD-C1-OPTIONA-PHASE1-BREAKDOWN-01 AC-1 REGRESSION: _embedded_ok "
        "was found in _get_cached_narrative — the dual gate must not be "
        "re-introduced. Use the standalone_ok-only gate."
    )
