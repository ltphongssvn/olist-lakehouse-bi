# scripts/sync.py
"""Return to develop, bring every long-lived branch current, and remove only what is safe.

WHY THIS IS A SCRIPT AND NOT A SHELL PIPELINE
The previous implementation deleted every branch whose upstream reported [gone].
When a worktree held one, git refused and the task aborted mid-sync. The fix is
not a filter -- it is having a model of the state, so "may this be deleted" is
answered by the state rather than discovered from an error.

EVERY LONG-LIVED BRANCH, NOT ONLY THE ONE CHECKED OUT (D.10). sync pulled the
branch it stood on and nothing else, so local main sat eleven releases behind.
A branch nobody has checked out is updated with `git fetch origin main:main`,
which git refuses unless it is a fast-forward -- a divergence surfaces instead
of being clobbered. git also refuses to fetch into a branch a worktree holds, so
that one is fast-forwarded inside its own worktree, and only when it is clean.
Ahead and diverged need a person: they are reported, never forced.

THEN THE INVARIANT IS ASKED, NOT ASSUMED. machine.branches judges the state
after the updates, and anything still out of place fails sync loudly.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from env_sync import environment_denials, follow_lock
from gitenv import git
from opa import denials
from repo_state import INTEGRATION_BRANCH, PROTECTED_BRANCHES, RepositoryState, gather

ROOT = Path(__file__).resolve().parent.parent

Action = Literal["fast_forward", "fast_forward_in_worktree", "held_dirty", "diverged", "ahead"]

REPORTS: dict[str, str] = {
    "held_dirty": "behind its remote, but checked out with uncommitted changes; "
    "commit or stash them there, then sync again",
    "diverged": "diverged from its remote; resolve it by hand -- sync never forces",
    "ahead": "holds commits its remote lacks; long-lived branches change only by pull request",
}


class Update(BaseModel):
    """What sync does, or reports, for one long-lived branch out of place."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    branch: str
    action: Action
    # The git arguments to run; None when the branch is reported, not touched.
    argv: tuple[str, ...] | None = None


def updates(state: RepositoryState) -> tuple[Update, ...]:
    """The remediation for every long-lived branch not in sync with its remote."""
    dirty = {worktree.path: worktree.is_dirty for worktree in state.worktrees}
    planned: list[Update] = []
    for branch in state.branches:
        name = branch.name
        if name not in PROTECTED_BRANCHES:
            continue
        if branch.position in ("diverged", "ahead"):
            planned.append(Update(branch=name, action=branch.position))
        elif branch.position == "behind":
            # NARROWED ONCE: who holds the branch decides how it catches up.
            holder = branch.held_by
            if holder is None:
                fetch = ("fetch", "origin", f"{name}:{name}")
                planned.append(Update(branch=name, action="fast_forward", argv=fetch))
            elif dirty.get(holder, True):
                # An unknown worktree is treated as dirty: never touch what is not seen.
                planned.append(Update(branch=name, action="held_dirty"))
            else:
                merge = ("-C", str(holder), "merge", "--ff-only", f"origin/{name}")
                planned.append(Update(branch=name, action="fast_forward_in_worktree", argv=merge))
    return tuple(planned)


def run(*args: str) -> None:
    result = git(*args, cwd=ROOT)
    if result.returncode != 0:
        print(result.stderr.strip(), file=sys.stderr)
        raise SystemExit(f"git {' '.join(args)} failed")
    if result.stdout.strip():
        print(result.stdout.strip())


def main() -> int:
    current = git("rev-parse", "--abbrev-ref", "HEAD", cwd=ROOT).stdout.strip()

    if current != INTEGRATION_BRANCH:
        # REFUSE TO SWITCH WITH A DIRTY TREE. `git switch` carries uncommitted
        # changes across, which silently moved work off a feature branch onto
        # develop -- where the pre-commit guard then refuses to commit it.
        status = git("status", "--porcelain", cwd=ROOT)
        if status.stdout.strip():
            raise SystemExit(
                f"refusing: on {current} with uncommitted changes.\n"
                "sync switches to develop, which would carry them off this "
                "branch. Commit or stash them first."
            )
        run("switch", INTEGRATION_BRANCH)

    before = git("rev-parse", "HEAD", cwd=ROOT).stdout.strip()
    run("pull", "--ff-only")
    run("remote", "prune", "origin")

    # THE ENVIRONMENT FOLLOWS THE LOCK (D.38): a pull that changed uv.lock installs it.
    environment = follow_lock(ROOT, before)

    state = gather(ROOT)

    for update in updates(state):
        if update.argv is not None:
            run(*update.argv)
            print(f"current {update.branch}: fast-forwarded to its remote")
        else:
            print(f"kept    {update.branch}: {REPORTS[update.action]}")

    for branch in state.deletable:
        # -d, not -D. It refuses anything not fully merged, so it stays a check
        # rather than an instruction -- the model has already established that
        # this branch IS merged, and the two agreeing is the point.
        result = subprocess.run(
            ["git", "branch", "-d", branch.name],
            capture_output=True,
            text=True,
            check=False,
            cwd=ROOT,
        )
        if result.returncode != 0:
            print(f"could not delete {branch.name}: {result.stderr.strip()}", file=sys.stderr)
        else:
            print(f"deleted {branch.name}")

    # REPORTED, NOT SKIPPED. A cleanup that quietly leaves something behind is
    # the failure this rewrite exists to remove.
    for branch in state.blocked:
        print(f"kept    {branch.name}: {branch.blocked_because}")

    if not state.deletable and not state.blocked:
        print("no branches to clean up")

    after = gather(ROOT)
    print()
    for worktree in after.worktrees:
        marker = "main" if worktree.is_main else "linked"
        dirty = " [dirty]" if worktree.is_dirty else ""
        print(f"{marker:7} {worktree.path}  {worktree.branch or '(detached)'}{dirty}")

    problems = denials(
        "data.machine.branches.deny", {"repository_state": after.model_dump(mode="json")}
    )
    problems += environment_denials(environment)
    if problems:
        print("\nsync left something out of place:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
