"""BUILD-NARRATIVE-WATERTIGHT-01 D.1 — permanent regression guard.

Asserts that the generic "{home} take on {away}." literal is gone from every
narrative-producing source in bot.py. This fixture was the primary leak vector
for cards where league context is unknown — it produced shells like
"Home take on Away." and then an empty Edge section.

The fix (Parts B.2 and B.3) replaces the literal with either a real league
sentence or, for the no-league case, analytical prose sourced from
``_render_setup`` / ``_render_baseline``.

If a future wave re-introduces ``take on`` in any narrative-producing
function, this test will fail before the bot is restarted.
"""
from __future__ import annotations

import inspect
import re

import pytest


NARRATIVE_SOURCE_FUNCTIONS = [
    "_build_signal_only_narrative",
    "_build_legacy_rich_narrative",
    "_build_setup_section_v2",
    "_build_programmatic_narrative",
]

# The escaped literal we are watching for. Allow quotes, curly braces and
# f-string interpolation around "take on".
_TAKE_ON_LITERAL = re.compile(r"take\s+on", re.IGNORECASE)


@pytest.fixture(scope="module")
def bot_module():
    import bot  # noqa: WPS433 — local import so the contract test does not pay the cost unless run

    return bot


@pytest.mark.parametrize("fn_name", NARRATIVE_SOURCE_FUNCTIONS)
def test_no_take_on_literal_in_narrative_sources(bot_module, fn_name):
    fn = getattr(bot_module, fn_name, None)
    if fn is None:
        pytest.skip(f"{fn_name} not present in bot.py — nothing to guard")
    try:
        src = inspect.getsource(fn)
    except (OSError, TypeError):
        pytest.skip(f"cannot inspect source of {fn_name}")
    assert not _TAKE_ON_LITERAL.search(src), (
        f"BUILD-NARRATIVE-WATERTIGHT-01 D.1: {fn_name} re-introduced the "
        f"'take on' literal. Replace with league-bearing prose or "
        f"_render_setup(NarrativeSpec) — see bot.py:17186 / 16985 for the "
        f"approved patterns."
    )
