from __future__ import annotations

import ast
from pathlib import Path


BOT_PATH = Path(__file__).resolve().parents[2] / "bot.py"


def _function_node(name: str) -> ast.FunctionDef:
    tree = ast.parse(BOT_PATH.read_text())
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"Function not found: {name}")


def _assert_helper_uses_startup_timeout(function_name: str) -> None:
    func = _function_node(function_name)
    for node in ast.walk(func):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Name) or node.func.id != "get_connection":
            continue
        timeout_kw = next((kw for kw in node.keywords if kw.arg == "timeout_ms"), None)
        assert timeout_kw is not None, f"{function_name} must pass timeout_ms to get_connection()"
        assert isinstance(timeout_kw.value, ast.Constant), (
            f"{function_name} timeout_ms must be a constant"
        )
        assert timeout_kw.value.value == 3000, (
            f"{function_name} must use timeout_ms=3000"
        )
        return
    raise AssertionError(f"{function_name} does not call get_connection()")


def test_ensure_narrative_cache_table_uses_startup_timeout_budget() -> None:
    _assert_helper_uses_startup_timeout("_ensure_narrative_cache_table")


def test_ensure_shadow_narratives_table_uses_startup_timeout_budget() -> None:
    _assert_helper_uses_startup_timeout("_ensure_shadow_narratives_table")
