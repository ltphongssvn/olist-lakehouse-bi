# scripts/source_read.py
"""Read a file's lines, numbered, as data (D.26).

The audit counted 110 `cat` reads. Each line comes back as a record -- its number and
its text, ripgrep's own --json convention -- so reading and searching speak one shape.
A range past the end, a missing file or a file that is not UTF-8 text is refused
rather than silently shortened or garbled.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, NonNegativeInt, PositiveInt

from command_outcome import CommandOutcome


class Line(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    number: PositiveInt
    text: str


class SourceLines(BaseModel):
    """source-lines/v1: a file's lines in a range, numbered."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    CONTRACT_ID: ClassVar[str] = "source-lines/v1"

    contract: Literal["source-lines/v1"] = "source-lines/v1"
    file: str
    first_line: NonNegativeInt
    last_line: NonNegativeInt
    total_lines: NonNegativeInt
    lines: tuple[Line, ...]


def read_lines(path: Path, first: int | None, last: int | None) -> SourceLines:
    """Lines first..last, inclusive; the whole file when no range is given."""
    lines = path.read_text(encoding="utf-8").splitlines()
    total = len(lines)
    start = 1 if first is None else first
    end = total if last is None else last
    if total and (start < 1 or end > total or end < start):
        raise ValueError(f"lines {start}-{end} are outside 1-{total}")
    return SourceLines(
        file=str(path),
        first_line=start if total else 0,
        last_line=end if total else 0,
        total_lines=total,
        lines=tuple(Line(number=n, text=lines[n - 1]) for n in range(start, end + 1))
        if total
        else (),
    )


def main(argv: Sequence[str] | None = None) -> int:
    """source:read <path> [first] [last]."""
    args = list(sys.argv[1:] if argv is None else argv)
    if not 1 <= len(args) <= 3 or not all(arg.isdigit() for arg in args[1:]):
        raise SystemExit("usage: mise run run source:read <path> [first] [last]")
    path = Path(args[0])
    first = int(args[1]) if len(args) > 1 else None
    last = int(args[2]) if len(args) > 2 else None
    try:
        view = read_lines(path, first, last)
    except (OSError, UnicodeDecodeError, ValueError) as problem:
        envelope = CommandOutcome.model_validate(
            {
                "command": "source:read",
                "outcome": "refused",
                "code": "read_refused",
                "message": f"{path}: {problem}",
                "data": {"file": str(path)},
            }
        )
    else:
        envelope = CommandOutcome.model_validate(
            {
                "command": "source:read",
                "outcome": "success",
                "code": "lines_read",
                "message": (
                    f"{path}: lines {view.first_line}-{view.last_line} of {view.total_lines}"
                ),
                "data": view.model_dump(mode="json"),
            }
        )
    print(json.dumps(envelope.model_dump(), indent=2))
    return envelope.exit_code


if __name__ == "__main__":
    sys.exit(main())
