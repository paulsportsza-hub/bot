"""FIX-BOT-PERF-LATENCY-BOUNDS-01 — Driver C contract guard.

Asserts every `asyncio.to_thread(_load_tips_from_edge_results, ...)` callsite
in `bot.py` is wrapped by `asyncio.wait_for(...)`. Without a deadline, a
single stalled SQLite read (busy_timeout = 60s on odds.db during scraper
write windows) holds the PTB dispatcher slot for up to 60s for ALL users.

AST-based scan so split-line forms (callable on the line below `to_thread(`)
are detected. The same gate caught the iter-1 Codex finding at bot.py:3344
where the to_thread call spanned multiple lines.
"""
from __future__ import annotations

import ast
import os
import re


_BOT_PY = os.path.join(os.path.dirname(__file__), "..", "..", "bot.py")
_TARGET_FNS = ("_load_tips_from_edge_results", "_load_edge_tip_by_key")
_TARGET_FN = "_load_tips_from_edge_results"  # legacy alias used by deadline-value test


def _load_source() -> str:
    with open(_BOT_PY, encoding="utf-8") as f:
        return f.read()


def _is_to_thread(node: ast.Call) -> bool:
    """True for `asyncio.to_thread(...)` or bare `to_thread(...)`."""
    func = node.func
    if isinstance(func, ast.Attribute) and func.attr == "to_thread":
        return True
    if isinstance(func, ast.Name) and func.id == "to_thread":
        return True
    return False


def _is_wait_for(node: ast.Call) -> bool:
    """True for `asyncio.wait_for(...)`."""
    func = node.func
    return isinstance(func, ast.Attribute) and func.attr == "wait_for"


def _first_arg_name(node: ast.Call) -> str | None:
    """Return the name of the first positional arg if it's a Name node."""
    if not node.args:
        return None
    first = node.args[0]
    if isinstance(first, ast.Name):
        return first.id
    return None


def _walk_to_thread_calls_to_target(tree: ast.AST):
    """Yield every Call node that is `to_thread(<user-tap DB helper>, ...)`."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _is_to_thread(node) and _first_arg_name(node) in _TARGET_FNS:
            yield node


def _to_thread_calls_inside_wait_for(tree: ast.AST) -> set[int]:
    """Return line numbers of to_thread(target) calls that sit INSIDE asyncio.wait_for(...)."""
    bounded: set[int] = set()
    for outer in ast.walk(tree):
        if isinstance(outer, ast.Call) and _is_wait_for(outer):
            # The first positional arg of wait_for is the awaitable — typically
            # the to_thread Call. Walk into the entire wait_for subtree to find
            # any nested to_thread(target) Call (handles edge cases too).
            for inner in ast.walk(outer):
                if (
                    isinstance(inner, ast.Call)
                    and _is_to_thread(inner)
                    and _first_arg_name(inner) in _TARGET_FNS
                ):
                    bounded.add(inner.lineno)
    return bounded


def test_load_tips_callsites_are_bounded():
    """Every asyncio.to_thread(_load_tips_from_edge_results, ...) call must
    sit inside an asyncio.wait_for(...) — including split-line forms.

    Detection is AST-based, so:
      - same-line:  `await asyncio.to_thread(_load_tips_from_edge_results, 20)`
      - split-line: `await asyncio.to_thread(\\n    _load_tips_from_edge_results, 50,\\n)`
    are both caught.
    """
    src = _load_source()
    tree = ast.parse(src)

    all_calls = list(_walk_to_thread_calls_to_target(tree))
    bounded_lines = _to_thread_calls_inside_wait_for(tree)

    violations: list[int] = []
    for call in all_calls:
        if call.lineno not in bounded_lines:
            violations.append(call.lineno)

    assert not violations, (
        "FIX-BOT-PERF-LATENCY-BOUNDS-01 (Driver C) violation: "
        f"asyncio.to_thread({'/'.join(_TARGET_FNS)}, ...) is not wrapped in "
        "asyncio.wait_for. Each unbounded call can hold the PTB dispatcher "
        f"slot for up to 60s during scraper write windows.\n"
        f"Offending bot.py line(s): {violations}"
    )


def test_at_least_one_load_tips_callsite_exists():
    """Sanity check: the AST scan must find at least one target callsite —
    otherwise `_load_tips_from_edge_results` was renamed and the regression
    guard above is silently a no-op.
    """
    tree = ast.parse(_load_source())
    found = list(_walk_to_thread_calls_to_target(tree))
    assert found, (
        f"FIX-BOT-PERF-LATENCY-BOUNDS-01: zero asyncio.to_thread({_TARGET_FN}) "
        "callsites detected. Either the helper was renamed (update _TARGET_FN) "
        "or the production code stopped using it (delete this test)."
    )


def test_user_tap_callsites_use_25_second_deadline():
    """User-tap DB reads must use timeout=2.5s.

    Two callsites are expected to use a different deadline:
      - Card deeplink lookup uses 5.0s (deeplink path tolerates a bit more).
      - Precompute cron uses 10.0s (background job, not user-tap).
    All other to_thread(_load_tips_from_edge_results, ...) callsites — the
    user-tap surface (Hot Tips fast path, detail tip lookup, snapshot seed,
    welcome-pick fallback, card-render seed) — must be 2.5s.
    """
    src = _load_source()
    block_re = re.compile(
        r"asyncio\.wait_for\(\s*"
        r"asyncio\.to_thread\(\s*" + re.escape(_TARGET_FN) + r"[^)]*?\)\s*,\s*"
        r"timeout\s*=\s*([0-9]+\.[0-9]+)",
        flags=re.DOTALL,
    )
    same_line_timeouts = [float(m) for m in block_re.findall(src)]

    # Split-line form: capture timeout from the wait_for that wraps a multi-line to_thread.
    # The shape is:
    #   asyncio.wait_for(\n    asyncio.to_thread(\n        _load_tips_from_edge_results, ...\n    ),\n    timeout=2.5,\n)
    split_block_re = re.compile(
        r"asyncio\.wait_for\(\s*"
        r"asyncio\.to_thread\(\s*\n[^)]*?" + re.escape(_TARGET_FN) + r"[^)]*?\)\s*,\s*"
        r"timeout\s*=\s*([0-9]+\.[0-9]+)",
        flags=re.DOTALL,
    )
    split_line_timeouts = [float(m) for m in split_block_re.findall(src)]
    timeouts = same_line_timeouts + split_line_timeouts

    assert timeouts, (
        "FIX-BOT-PERF-LATENCY-BOUNDS-01: regex matched no wait_for/to_thread/"
        f"{_TARGET_FN} blocks — pattern likely drifted from production code."
    )
    user_tap_count = sum(1 for t in timeouts if t == 2.5)
    assert user_tap_count >= 4, (
        f"FIX-BOT-PERF-LATENCY-BOUNDS-01: expected ≥4 user-tap callsites with "
        f"timeout=2.5s, found {user_tap_count}. All deadlines: {timeouts}"
    )
