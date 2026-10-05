# scripts/any_inventory.py
"""Observe every Any the code writes or implies, from the syntax tree.

THE SYNTAX TREE, NEVER TEXT. A text search for Any matched three comments and
docstrings in this repository; the tree sees only names and annotations.

IMPLICIT ANY is a parameter -- other than a leading self or cls -- or a return,
left unannotated: mypy treats it as Any without the word ever appearing, which
is why a ban on the explicit form alone misses it.

WHAT THIS CANNOT SEE: Any arriving through a call to something untyped is
invisible without running mypy. This records what is written, and says so.
"""

from __future__ import annotations

import ast
from pathlib import Path

from any_models import AnyInventory, AnyUse

ROOT = Path(__file__).resolve().parent.parent
SCANNED = ("scripts", "tests")
RECEIVERS = {"self", "cls"}


def _explicit(node: ast.AST) -> bool:
    if isinstance(node, ast.Name):
        return node.id == "Any"
    return isinstance(node, ast.Attribute) and node.attr == "Any"


def _implicit(path: str, node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[AnyUse]:
    arguments = node.args
    positional = [*arguments.posonlyargs, *arguments.args]
    found: list[AnyUse] = []
    for index, argument in enumerate([*positional, *arguments.kwonlyargs]):
        if argument.annotation is not None:
            continue
        if index == 0 and argument.arg in RECEIVERS:
            continue
        found.append(AnyUse(path=path, line=argument.lineno, form="implicit", name=argument.arg))
    for star in (arguments.vararg, arguments.kwarg):
        if star is not None and star.annotation is None:
            found.append(AnyUse(path=path, line=star.lineno, form="implicit", name=star.arg))
    if node.returns is None:
        found.append(
            AnyUse(path=path, line=node.lineno, form="implicit", name=f"{node.name} -> return")
        )
    return found


def observe_source(path: str, source: str) -> tuple[AnyUse, ...]:
    """Every Any in one module, in source order."""
    uses: list[AnyUse] = []
    for node in ast.walk(ast.parse(source)):
        if _explicit(node):
            uses.append(
                AnyUse(path=path, line=getattr(node, "lineno", 1), form="explicit", name="Any")
            )
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            uses.extend(_implicit(path, node))
    return tuple(sorted(uses, key=lambda use: (use.line, use.form, use.name)))


def observe(root: Path = ROOT) -> AnyInventory:
    """The inventory of every scanned module under the repository."""
    files = sorted(path for folder in SCANNED for path in (root / folder).rglob("*.py"))
    uses: list[AnyUse] = []
    for path in files:
        relative = str(path.relative_to(root))
        uses.extend(observe_source(relative, path.read_text(encoding="utf-8")))
    return AnyInventory(files_scanned=len(files), uses=tuple(uses))
