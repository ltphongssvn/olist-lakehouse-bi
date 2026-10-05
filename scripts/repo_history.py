# scripts/repo_history.py
"""Commit history, read by a task, as data (D.29).

GROUNDED. git's %(trailers) takes separator and key_value_separator, which "make it
trivial to produce machine-readable (\0-delimited) output". Fields here are NUL-
separated, each record opened by \x1e; trailers are separated by \x1f and a key from
its value by \x1d, so a colon in a value cannot split it. A commit's files come from
`git show --name-only -z`, so no path can break the parse. The audit counted 20 hand
reads of git log and git show.
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
RECORD, TRAILER, KEY_VALUE = "\x1e", "\x1f", "\x1d"
FORMAT = (
    "--format=%x1e%H%x00%s%x00%aI%x00"
    "%(trailers:only,unfold,separator=%x1f,key_value_separator=%x1d)"
)


class Trailer(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    key: str
    value: str


class Commit(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    sha: str
    subject: str
    authored_at: str
    trailers: tuple[Trailer, ...]
    files: tuple[str, ...]


class RepoHistory(BaseModel):
    """repo-history/v1: commits, newest first, with trailers and files."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    CONTRACT_ID: ClassVar[str] = "repo-history/v1"

    contract: Literal["repo-history/v1"] = "repo-history/v1"
    revision: str
    limit: PositiveInt
    commits: tuple[Commit, ...]
    count: NonNegativeInt


def _files(root: Path, sha: str) -> tuple[str, ...]:
    # FIRST PARENT: git shows no files for a merge by default; against its first parent
    # they are what the merge brought into the branch. A single-parent commit is unchanged.
    shown = git(
        "show", "--name-only", "-z", "--format=", "--diff-merges=first-parent", sha, cwd=root
    )
    return tuple(path.strip("\n") for path in shown.stdout.split("\0") if path.strip("\n"))


def history(root: Path, revision: str, limit: int) -> RepoHistory:
    """The newest `limit` commits reachable from `revision`."""
    logged = git("log", f"-n{limit}", FORMAT, revision, "--", cwd=root)
    if logged.returncode != 0:
        raise ValueError(logged.stderr.strip() or f"git log exited {logged.returncode}")
    commits = []
    for record in logged.stdout.split(RECORD)[1:]:
        fields = record.rstrip("\n").split("\0", 3)
        if len(fields) != 4:
            raise ValueError(f"malformed git log record: {record!r}")
        sha, subject, authored_at, raw = fields
        trailers = tuple(
            Trailer(key=key, value=value)
            for key, _, value in (item.partition(KEY_VALUE) for item in raw.split(TRAILER) if item)
        )
        commits.append(
            Commit(
                sha=sha,
                subject=subject,
                authored_at=authored_at,
                trailers=trailers,
                files=_files(root, sha),
            )
        )
    return RepoHistory(revision=revision, limit=limit, commits=tuple(commits), count=len(commits))


def main(argv: Sequence[str] | None = None) -> int:
    """repo:history [revision] [--limit N]."""
    args = list(sys.argv[1:] if argv is None else argv)
    limit = 20
    if "--limit" in args:
        at = args.index("--limit")
        if at + 1 >= len(args) or not args[at + 1].isdigit() or int(args[at + 1]) < 1:
            raise SystemExit("--limit needs a positive number")
        limit = int(args[at + 1])
        del args[at : at + 2]
    if len(args) > 1:
        raise SystemExit("usage: mise run run repo:history [revision] [--limit N]")
    revision = args[0] if args else "HEAD"
    try:
        read = history(ROOT, revision, limit)
    except ValueError as problem:
        envelope = CommandOutcome.model_validate(
            {
                "command": "repo:history",
                "outcome": "refused",
                "code": "history_refused",
                "message": str(problem),
                "data": {"revision": revision},
            }
        )
    else:
        envelope = CommandOutcome.model_validate(
            {
                "command": "repo:history",
                "outcome": "success",
                "code": "history_read",
                "message": f"{read.count} commit(s) from {revision}",
                "data": read.model_dump(mode="json"),
            }
        )
    print(json.dumps(envelope.model_dump(), indent=2))
    return envelope.exit_code


if __name__ == "__main__":
    sys.exit(main())
