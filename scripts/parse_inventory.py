"""raw-parse-inventory/v1: every json, tomllib or yaml parse that enters unvalidated.

A PARSE STRAIGHT INTO A MODEL IS SANCTIONED -- model_validate(tomllib.loads(...))
-- because the untyped value never exists anywhere a caller can reach it. Any
other parse, including one held in a variable on its way to a model, is raw.

THE SYNTAX TREE, NEVER TEXT: a text search matched parses written in comments.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, PositiveInt

ROOT = Path(__file__).resolve().parent.parent
PARSERS = {"json": {"loads", "load"}, "tomllib": {"loads", "load"}, "yaml": {"safe_load", "load"}}
VALIDATORS = {"model_validate", "validate_python"}


class RawParse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str = Field(min_length=1)
    line: PositiveInt
    call: str = Field(min_length=1)


class ParseInventory(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    CONTRACT_ID: ClassVar[str] = "raw-parse-inventory/v1"

    contract: Literal["raw-parse-inventory/v1"] = "raw-parse-inventory/v1"
    # A SCAN OVER NOTHING PROVES NOTHING, so an empty one is refused here.
    files_scanned: PositiveInt
    uses: tuple[RawParse, ...]


def _parser(node: ast.Call) -> str | None:
    """`module.function` when this call is a json, tomllib or yaml parse."""
    if not isinstance(node.func, ast.Attribute):
        return None
    module = node.func.value
    if isinstance(module, ast.Name) and node.func.attr in PARSERS.get(module.id, set()):
        return f"{module.id}.{node.func.attr}"
    return None


def observe_source(path: str, source: str) -> tuple[RawParse, ...]:
    """Every unsanctioned parse in one module."""
    calls = [node for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Call)]
    sanctioned = {
        id(argument)
        for call in calls
        if isinstance(call.func, ast.Attribute) and call.func.attr in VALIDATORS
        for argument in call.args
    }
    uses = [
        RawParse(path=path, line=call.lineno, call=name)
        for call in calls
        if (name := _parser(call)) is not None and id(call) not in sanctioned
    ]
    return tuple(sorted(uses, key=lambda use: use.line))


def observe(root: Path = ROOT) -> ParseInventory:
    """The inventory of every module under scripts/."""
    files = sorted((root / "scripts").rglob("*.py"))
    uses: list[RawParse] = []
    for path in files:
        uses.extend(observe_source(str(path.relative_to(root)), path.read_text(encoding="utf-8")))
    return ParseInventory(files_scanned=len(files), uses=tuple(uses))
