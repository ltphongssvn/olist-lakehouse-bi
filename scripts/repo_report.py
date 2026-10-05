# scripts/repo_report.py
"""Repository state, observed by a task as typed evidence (D.16).

NOT TEXT. git status --porcelain=v1 -z is the stable, machine-readable form:
NUL-separated records of a two-character status and a path, with a rename or
copy carrying its original path as a second record -- which a line-based reader
of the human output gets wrong. Each worktree's changes, its position against
origin/develop and the long-lived branches' positions become typed fields, and
every verdict is a boolean computed from them.

RECORDED. The task's outcome is appended to the run ledger, from day one.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, NonNegativeInt

from command_outcome import CommandOutcome
from gitenv import git
from repo_state import Position, gather
from run_ledger import append

ROOT = Path(__file__).resolve().parent.parent
BASE = "origin/develop"


class _Strict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Change(_Strict):
    status: str = Field(min_length=2, max_length=2)
    path: str = Field(min_length=1)
    original_path: str | None = None


class WorktreeReport(_Strict):
    path: str
    branch: str | None
    is_main: bool
    ahead_of_develop: NonNegativeInt
    behind_develop: NonNegativeInt
    changes: tuple[Change, ...]


class BranchPosition(_Strict):
    name: str
    position: Position


class ReportVerdicts(_Strict):
    every_worktree_clean: bool
    no_worktree_behind_develop: bool
    long_lived_branches_in_sync: bool


class RepositoryReport(_Strict):
    """repository-state/v1."""

    contract: Literal["repository-state/v1"] = "repository-state/v1"
    worktrees: tuple[WorktreeReport, ...]
    long_lived: tuple[BranchPosition, ...]
    verdicts: ReportVerdicts


def parse_porcelain(raw: str) -> tuple[Change, ...]:
    """Records of `git status --porcelain=v1 -z`; a rename or copy takes two."""
    tokens = raw.split("\0")
    changes: list[Change] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        index += 1
        if not token:
            continue
        status, path = token[:2], token[3:]
        original = None
        if status[0] in "RC":
            original = tokens[index]
            index += 1
        changes.append(Change(status=status, path=path, original_path=original))
    return tuple(changes)


def _count(cwd: Path, revisions: str) -> int:
    return int(git("rev-list", "--count", revisions, cwd=cwd).stdout.strip())


def observe(root: Path = ROOT) -> RepositoryReport:
    """Every worktree and every long-lived branch, as typed evidence."""
    state = gather(root)
    worktrees = tuple(
        WorktreeReport(
            path=str(worktree.path),
            branch=worktree.branch,
            is_main=worktree.is_main,
            ahead_of_develop=_count(worktree.path, f"{BASE}..HEAD"),
            behind_develop=_count(worktree.path, f"HEAD..{BASE}"),
            changes=parse_porcelain(
                git(
                    "status", "--porcelain=v1", "-z", "--untracked-files=all", cwd=worktree.path
                ).stdout
            ),
        )
        for worktree in state.worktrees
    )
    long_lived = tuple(
        BranchPosition(name=branch.name, position=branch.position)
        for branch in state.branches
        if branch.name in state.long_lived
    )
    return RepositoryReport(
        worktrees=worktrees,
        long_lived=long_lived,
        verdicts=ReportVerdicts(
            every_worktree_clean=all(not worktree.changes for worktree in worktrees),
            no_worktree_behind_develop=all(worktree.behind_develop == 0 for worktree in worktrees),
            long_lived_branches_in_sync=all(branch.position == "in_sync" for branch in long_lived),
        ),
    )


def main(ledger: Path | None = None) -> int:
    """repo:state -- observe, record the run, and report as a command-outcome envelope."""
    report = observe(ROOT)
    outcome = CommandOutcome.model_validate(
        {
            "command": "repo:state",
            "outcome": "success",
            "code": "state_observed",
            "message": (
                f"{len(report.worktrees)} worktree(s), "
                f"{len(report.long_lived)} long-lived branch(es)"
            ),
            "data": report.model_dump(mode="json"),
        }
    )
    append(outcome, ledger=ledger)
    print(json.dumps(outcome.model_dump(), indent=2))
    return outcome.exit_code


if __name__ == "__main__":
    sys.exit(main())
