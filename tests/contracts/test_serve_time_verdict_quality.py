"""BUILD-NARRATIVE-WATERTIGHT-01 C.1 regression guard.

Asserts that ``_get_cached_narrative`` invokes ``min_verdict_quality`` on
both the embedded verdict section AND the standalone ``verdict_html`` column
before returning a cached row. Fails loudly if a future wave removes the
gate — thin 42–65 char verdicts would silently start flowing to Gold /
Diamond subscribers again.
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

    # Gate must be wired into the cache-hit path — look for the three
    # load-bearing tokens: the gate function, the verdict extractor, and
    # a quarantine UPDATE on failure (FIX-NARRATIVE-CACHE-DEATH-01 replaces
    # DELETE with quarantine so the loop cannot restart).
    assert "min_verdict_quality" in src, (
        "BUILD-NARRATIVE-WATERTIGHT-01 C.1: _get_cached_narrative must call "
        "min_verdict_quality on the cached verdict before returning."
    )
    assert "_extract_verdict_text" in src, (
        "BUILD-NARRATIVE-WATERTIGHT-01 C.1: _get_cached_narrative must use "
        "_extract_verdict_text so the embedded verdict section is evaluated."
    )
    assert re.search(r"verdict_html", src), (
        "BUILD-NARRATIVE-WATERTIGHT-01 C.1: _get_cached_narrative must also "
        "evaluate the standalone verdict_html column."
    )
    # FIX-NARRATIVE-CACHE-DEATH-01: quarantine-on-reject replaces DELETE.
    # Quality-gate rejections now set status='quarantined' so the row is not
    # re-generated in an infinite loop. Assert the quarantine UPDATE is present.
    assert re.search(
        r"status\s*=\s*['\"]quarantined['\"]", src, re.IGNORECASE
    ), (
        "FIX-NARRATIVE-CACHE-DEATH-01: _get_cached_narrative must set "
        "status='quarantined' (not DELETE) on quality-gate rejection."
    )
