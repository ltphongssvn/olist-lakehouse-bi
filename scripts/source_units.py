# scripts/source_units.py
"""Read functions and classes from a Python file by syntax tree, as data (D.28).

GROUNDED in 2026 practice -- ast, with each node's lineno and end_lineno -- so a unit
is read exactly as written, whatever the formatter made of it. A unit's first line
includes its decorators, which belong to it. Named units come back in file order;
an unknown name is refused rather than silently skipped.
"""

from __future__ import annotations

import ast
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, PositiveInt

from command_outcome import CommandOutcome

UNITS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


class SourceUnit(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    name: str
    kind: Literal["function", "class"]
    first_line: PositiveInt
    last_line: PositiveInt
    source: tuple[str, ...]


class UnitsReport(BaseModel):
    """source-units/v1: the named units of one file, as written."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    CONTRACT_ID: ClassVar[str] = "source-units/v1"

    contract: Literal["source-units/v1"] = "source-units/v1"
    file: str
    units: tuple[SourceUnit, ...]


def read_units(path: Path, names: Sequence[str]) -> tuple[SourceUnit, ...]:
    """The top-level units named -- or all of them -- in file order."""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    nodes = [node for node in ast.parse(text).body if isinstance(node, UNITS)]
    if names:
        missing = sorted(set(names) - {node.name for node in nodes})
        if missing:
            raise LookupError(", ".join(missing))
        nodes = [node for node in nodes if node.name in set(names)]
    units = []
    for node in nodes:
        first = min([decorator.lineno for decorator in node.decorator_list] + [node.lineno])
        last = node.end_lineno or node.lineno
        units.append(
            SourceUnit(
                name=node.name,
                kind="class" if isinstance(node, ast.ClassDef) else "function",
                first_line=first,
                last_line=last,
                source=tuple(lines[first - 1 : last]),
            )
        )
    return tuple(units)


def main(argv: Sequence[str] | None = None) -> int:
    """source:units <file> [name...]."""
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        raise SystemExit("usage: mise run run source:units <file> [name...]")
    path, names = Path(args[0]), tuple(args[1:])
    try:
        units = read_units(path, names)
    except LookupError as missing:
        envelope = CommandOutcome.model_validate(
            {
                "command": "source:units",
                "outcome": "refused",
                "code": "unit_unknown",
                "message": f"not found in {path}: {missing}",
                "data": {"file": str(path), "names": list(names)},
            }
        )
    else:
        report = UnitsReport(file=str(path), units=units)
        envelope = CommandOutcome.model_validate(
            {
                "command": "source:units",
                "outcome": "success",
                "code": "units_read",
                "message": f"{len(units)} unit(s) from {path}",
                "data": report.model_dump(mode="json"),
            }
        )
    print(json.dumps(envelope.model_dump(), indent=2))
    return envelope.exit_code


if __name__ == "__main__":
    sys.exit(main())
