"""BUILD-CONTRACT-TESTS-01 — Test 2: Async Blocking Guard

RUNTIME-R2: Synchronous SQLite work inside an async handler must run inside
asyncio.to_thread(). Direct calls to _get_broadcast_details() or
_get_broadcast_line() inside async def bodies are violations.

AST-based static analysis — no bot import required.
"""
import ast
import os


_BOT_PY = os.path.join(os.path.dirname(__file__), "..", "..", "bot.py")

# Synchronous broadcast functions that must never be called directly in async defs
_BLOCKED_SYNC_CALLS = {"_get_broadcast_details", "_get_broadcast_line"}

# Dead-code async functions retained for reference only (W84-MM2) — skip these
# so violations in dead code don't block the gate.
_DEAD_CODE_SKIP = {"_render_your_games_sport"}


class _DirectCallFinder(ast.NodeVisitor):
    """Finds direct calls to blocked sync functions inside async def bodies.

    A 'direct' call is ast.Call(func=Name('fn')) — as opposed to passing
    the function as a reference: asyncio.to_thread(fn, *args) which is safe.
    """

    def __init__(self):
        self.violations: list[dict] = []
        self._async_stack: list[str] = []

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        if node.name in _DEAD_CODE_SKIP:
            return  # Skip dead-code functions retained for reference
        self._async_stack.append(node.name)
        self.generic_visit(node)
        self._async_stack.pop()

    def visit_Call(self, node: ast.Call):
        if not self._async_stack:
            self.generic_visit(node)
            return

        # Identify the function being called
        func_name: str | None = None
        if isinstance(node.func, ast.Name):
            func_name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            func_name = node.func.attr

        if func_name in _BLOCKED_SYNC_CALLS:
            self.violations.append({
                "line": node.lineno,
                "fn": func_name,
                "async_fn": self._async_stack[-1],
            })
            # Do NOT descend further — we've recorded the violation
            return

        # For to_thread calls: skip descending into to_thread's first arg (the callable
        # reference), but still visit remaining args (they may be sync calls too, but
        # those are passed as arguments to the thread, not called directly on the loop).
        is_to_thread = (
            isinstance(node.func, ast.Attribute) and node.func.attr == "to_thread"
        ) or (
            isinstance(node.func, ast.Name) and node.func.id == "to_thread"
        )
        if is_to_thread:
            # Visit keyword args, but not the callable reference (args[0] is the fn)
            for kw in node.keywords:
                self.visit(kw.value)
            return

        self.generic_visit(node)


def _load_bot_ast() -> ast.Module:
    with open(_BOT_PY, encoding="utf-8") as f:
        source = f.read()
    return ast.parse(source, filename=_BOT_PY)


def test_no_direct_broadcast_calls_in_async_defs():
    """_get_broadcast_details and _get_broadcast_line must not be called directly
    inside any async def — they are synchronous SQLite functions and must always
    be wrapped with asyncio.to_thread() (RUNTIME-R2, W84-RT6).
    """
    tree = _load_bot_ast()
    finder = _DirectCallFinder()
    finder.visit(tree)

    if finder.violations:
        detail = "\n".join(
            f"  Line {v['line']}: {v['fn']}() called directly in async def {v['async_fn']}()"
            for v in finder.violations
        )
        raise AssertionError(
            f"\nRUNTIME-R2 VIOLATION: {len(finder.violations)} direct sync call(s) "
            f"inside async def bodies:\n{detail}\n\n"
            "Fix: wrap with asyncio.to_thread(_get_broadcast_details, home, away, ...)"
        )
