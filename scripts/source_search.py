# scripts/source_search.py
"""Search tracked source by a task, its matches as data (D.27).

GROUNDED. `git grep -n -z` separates path, line number and text with NUL bytes, so
a path containing a colon is unambiguous; a CRLF line's trailing carriage return is
stripped; --full-name gives paths from the repository root; -I skips binary files.
It searches tracked files -- and untracked, unignored ones when a guard asks, since a
guard must see what is about to be committed. Exit code 1 means no match -- an empty result,
not an error. A record without both separators is malformed and refused, never
skipped. Records share source:read's shape: path, number, text.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, NonNegativeInt, PositiveInt

from command_outcome import CommandOutcome
from gitenv import git

ROOT = Path(__file__).resolve().parent.parent


class Match(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    path: str
    number: PositiveInt
    text: str


class SourceMatches(BaseModel):
    """source-matches/v1: every tracked line matching a pattern."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    CONTRACT_ID: ClassVar[str] = "source-matches/v1"

    contract: Literal["source-matches/v1"] = "source-matches/v1"
    pattern: str
    paths: tuple[str, ...]
    matches: tuple[Match, ...]
    count: NonNegativeInt
    files: NonNegativeInt


def search(
    root: Path, pattern: str, paths: Sequence[str], *, untracked: bool = False
) -> SourceMatches:
    """Lines matching `pattern` in tracked files -- and untracked, unignored ones if asked."""
    scope = ("--untracked",) if untracked else ()
    result = git(
        "grep", *scope, "-n", "-z", "--full-name", "-I", "-e", pattern, "--", *paths, cwd=root
    )
    if result.returncode not in (0, 1):
        raise ValueError(result.stderr.strip() or f"git grep exited {result.returncode}")
    matches: list[Match] = []
    for record in result.stdout.split("\n") if result.returncode == 0 else ():
        if not record:
            continue
        fields = record.split("\0", 2)
        if len(fields) != 3:
            raise ValueError(f"malformed git grep record: {record!r}")
        path, number, text = fields
        matches.append(Match(path=path, number=int(number), text=text.removesuffix("\r")))
    return SourceMatches(
        pattern=pattern,
        paths=tuple(paths),
        matches=tuple(matches),
        count=len(matches),
        files=len({match.path for match in matches}),
    )


def main(argv: Sequence[str] | None = None) -> int:
    """source:search <pattern> [path...]."""
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        raise SystemExit("usage: mise run run source:search <pattern> [path...]")
    try:
        found = search(ROOT, args[0], args[1:])
    except ValueError as problem:
        envelope = CommandOutcome.model_validate(
            {
                "command": "source:search",
                "outcome": "refused",
                "code": "search_refused",
                "message": str(problem),
                "data": {"pattern": args[0]},
            }
        )
    else:
        envelope = CommandOutcome.model_validate(
            {
                "command": "source:search",
                "outcome": "success",
                "code": "matches_found",
                "message": f"{found.count} match(es) in {found.files} file(s)",
                "data": found.model_dump(mode="json"),
            }
        )
    print(json.dumps(envelope.model_dump(), indent=2))
    return envelope.exit_code


if __name__ == "__main__":
    sys.exit(main())
