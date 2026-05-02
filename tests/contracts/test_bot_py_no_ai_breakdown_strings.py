from __future__ import annotations

import ast
import re
from pathlib import Path


BOT_PY = Path(__file__).resolve().parents[2] / "bot.py"
BREAKDOWN_RE = re.compile(r"\b(?:ai\s+)?breakdown\b", re.IGNORECASE)
INTERNAL_TOKEN_RE = re.compile(r"^[a-z0-9_:-]+$", re.IGNORECASE)


def _parent_map(tree: ast.AST) -> dict[int, ast.AST]:
    parents: dict[int, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[id(child)] = parent
    return parents


def _docstring_node_ids(tree: ast.AST) -> set[int]:
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not node.body:
            continue
        first = node.body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            docstrings.add(id(first.value))
    return docstrings


def _inside_internal_log_or_metric(node: ast.AST, parents: dict[int, ast.AST]) -> bool:
    current: ast.AST | None = node
    while current is not None:
        current = parents.get(id(current))
        if not isinstance(current, ast.Call):
            continue
        func = current.func
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            if func.value.id in {"log", "logger"}:
                return True
        if isinstance(func, ast.Name) and func.id == "_sentry_tags":
            return True
    return False


def test_bot_py_has_no_user_facing_ai_breakdown_copy() -> None:
    tree = ast.parse(BOT_PY.read_text(encoding="utf-8"))
    parents = _parent_map(tree)
    docstrings = _docstring_node_ids(tree)

    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        if id(node) in docstrings:
            continue
        if not BREAKDOWN_RE.search(node.value):
            continue
        if INTERNAL_TOKEN_RE.fullmatch(node.value):
            continue
        if _inside_internal_log_or_metric(node, parents):
            continue
        offenders.append(f"{node.lineno}: {node.value!r}")

    assert offenders == []
