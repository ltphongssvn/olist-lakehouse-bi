# scripts/repo_state.py
"""The repository's branch and worktree state, as a validated snapshot.

WHY A STATE MODEL AND NOT A PIPELINE
`mise run sync` deleted merged branches by piping `git for-each-ref` through
awk. It worked until a worktree held one of those branches, at which point git
refused -- correctly -- and the task aborted mid-way, leaving the sync half done
after the pull had already succeeded.

The bug was not the missing filter. It was that cleanup had no model of what it
was cleaning: it knew "upstream is gone" and nothing else, so every other fact
about a branch was invisible. The documented failure signal for exactly this
class is "reporting cleanup done while a worktree or branch remains".

WHAT THE MODEL MAKES EXPLICIT
  is_protected     develop and main are never deleted, whatever their state
  worktree         the linked worktree holding it, if any -- one branch, one
                   worktree, and git enforces that
  position         where it stands against its remote: in_sync, behind, ahead,
                   diverged, gone (the remote branch was deleted, usually by a
                   merge) or untracked
  is_merged        its commits are in develop

Deletability is then a property of the state rather than a guess, and the reason
a branch is NOT deletable is answerable instead of inferred from an error.

POSITION, NOT A FLAG (D.10). The model kept only whether git's tracking said
[gone] and threw away [behind 21] -- so nothing could see that local main sat
eleven releases behind. upstream_gone is now derived from position, so the two
cannot disagree.

WHY --porcelain -z EVERYWHERE
Human-readable git output is explicitly not a stable interface, and porcelain
does not quote paths -- so a path containing a newline corrupts a line-based
parser. The docs recommend combining --porcelain with -z for that reason.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from gitenv import scrubbed_env

PROTECTED_BRANCHES = frozenset({"develop", "main"})
INTEGRATION_BRANCH = "develop"

Position = Literal["in_sync", "behind", "ahead", "diverged", "gone", "untracked"]


def position_of(upstream: str, track: str) -> Position:
    """Where a branch stands against its upstream, from git's own tracking.

    %(upstream:track) is empty when in sync, "[gone]" when the remote branch was
    deleted, and "[ahead N]", "[behind N]" or "[ahead N, behind M]" otherwise.
    An empty %(upstream) means the branch tracks nothing at all.
    """
    if not upstream:
        return "untracked"
    if track == "[gone]":
        return "gone"
    ahead, behind = "ahead" in track, "behind" in track
    if ahead and behind:
        return "diverged"
    if behind:
        return "behind"
    if ahead:
        return "ahead"
    return "in_sync"


class Worktree(BaseModel):
    """A checkout: the main clone or a linked worktree."""

    model_config = ConfigDict(frozen=True)

    path: Path
    branch: str | None
    is_main: bool
    is_dirty: bool

    @property
    def is_linked(self) -> bool:
        """The canonical predicate. A linked worktree cannot check out a branch
        another worktree already holds, and the default branch is normally held
        by the main clone."""
        return not self.is_main


class Branch(BaseModel):
    """A local branch and everything that decides what may be done with it."""

    model_config = ConfigDict(frozen=True)

    name: str
    position: Position
    is_merged: bool
    held_by: Path | None

    @property
    def upstream_gone(self) -> bool:
        return self.position == "gone"

    @property
    def is_protected(self) -> bool:
        return self.name in PROTECTED_BRANCHES

    @property
    def is_deletable(self) -> bool:
        """Every condition, not just the one that happened to fail last."""
        return (
            not self.is_protected and self.upstream_gone and self.is_merged and self.held_by is None
        )

    @property
    def blocked_because(self) -> str | None:
        """Why this branch is not deletable, in the words a person needs.

        An error message from git says a delete failed. This says which
        condition holds and what to do about it.
        """
        if self.is_protected:
            return "protected branch"
        if not self.upstream_gone:
            return "upstream still exists; it has not been merged and deleted"
        if not self.is_merged:
            return f"not merged into {INTEGRATION_BRANCH}"
        if self.held_by is not None:
            return (
                f"checked out in a worktree at {self.held_by}. "
                "Remove the worktree first: mise run worktree:remove <slug>"
            )
        return None


class RepositoryState(BaseModel):
    """Everything sync needs to decide, gathered once."""

    model_config = ConfigDict(frozen=True)

    worktrees: tuple[Worktree, ...]
    branches: tuple[Branch, ...]
    # WHICH BRANCHES THE CURRENCY INVARIANT COVERS, carried in the snapshot so
    # machine.branches reads them from the model rather than restating them.
    long_lived: tuple[str, ...] = tuple(sorted(PROTECTED_BRANCHES))

    @property
    def deletable(self) -> tuple[Branch, ...]:
        return tuple(branch for branch in self.branches if branch.is_deletable)

    @property
    def blocked(self) -> tuple[Branch, ...]:
        """Branches whose upstream is gone but which cannot be removed yet.

        Reported rather than silently skipped: a cleanup that quietly leaves
        something behind is the documented failure signal for this class of bug.
        """
        return tuple(
            branch
            for branch in self.branches
            if branch.upstream_gone and not branch.is_deletable and not branch.is_protected
        )


def _git(*args: str, cwd: Path | None = None) -> str:
    result = subprocess.run(
        ["git", *args], capture_output=True, text=True, check=False, cwd=cwd, env=scrubbed_env()
    )
    if result.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def _worktrees(root: Path) -> tuple[Worktree, ...]:
    raw = subprocess.run(
        ["git", "worktree", "list", "--porcelain", "-z"],
        capture_output=True,
        check=False,
        cwd=root,
        env=scrubbed_env(),
    )
    if raw.returncode != 0:
        raise SystemExit("git worktree list failed")

    records: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for token in raw.stdout.split(b"\0"):
        if token == b"":
            if current:
                records.append(current)
                current = {}
            continue
        key, _, value = token.decode("utf-8").partition(" ")
        current[key] = value
    if current:
        records.append(current)

    worktrees: list[Worktree] = []
    for index, record in enumerate(records):
        path = Path(record["worktree"])
        status = subprocess.run(
            ["git", "status", "--porcelain", "-z"],
            capture_output=True,
            check=False,
            cwd=path,
            env=scrubbed_env(),
        )
        worktrees.append(
            Worktree(
                path=path,
                branch=record.get("branch", "").removeprefix("refs/heads/") or None,
                # The FIRST record is the main worktree; the rest are linked.
                is_main=index == 0,
                is_dirty=bool(status.returncode == 0 and status.stdout.strip(b"\0")),
            )
        )
    return tuple(worktrees)


def integration_ref(root: Path) -> str:
    """The integration branch as a ref this checkout has: the local one, else origin's.

    A pull-request checkout in CI has origin/develop and no local develop, so naming
    the local branch failed with "malformed object name develop". Each candidate is
    verified with rev-parse --verify, peeled to a commit; when neither exists this
    refuses rather than report every branch as unmerged.
    """
    for candidate in (
        f"refs/heads/{INTEGRATION_BRANCH}",
        f"refs/remotes/origin/{INTEGRATION_BRANCH}",
    ):
        probe = subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", f"{candidate}^{{commit}}"],
            capture_output=True,
            check=False,
            cwd=root,
            env=scrubbed_env(),
        )
        if probe.returncode == 0:
            return candidate
    raise SystemExit(
        f"neither {INTEGRATION_BRANCH} nor origin/{INTEGRATION_BRANCH} exists in {root}; "
        "fetch origin first"
    )


def gather(root: Path) -> RepositoryState:
    """Read the repository's state once, from plumbing only."""
    worktrees = _worktrees(root)
    holders = {w.branch: w.path for w in worktrees if w.branch}

    # for-each-ref, NOT `git branch --merged`.
    #
    # `git branch` is porcelain and prefixes its output: "* " for the current
    # branch and "+ " for one held by a LINKED WORKTREE. A parser stripping only
    # "* " would read "+ feature/x" as unmerged -- silently wrong for exactly
    # the branches this model exists to reason about.
    #
    # for-each-ref is plumbing, takes --merged as a filter, and emits bare names.
    merged = {
        name
        for name in _git(
            "for-each-ref",
            "--format=%(refname:short)",
            "--merged",
            integration_ref(root),
            "refs/heads",
            cwd=root,
        ).split()
        if name
    }

    branches: list[Branch] = []
    listing = _git(
        "for-each-ref",
        "--format=%(refname:short)%00%(upstream)%00%(upstream:track)",
        "refs/heads",
        cwd=root,
    )
    for line in listing.splitlines():
        if not line:
            continue
        name, upstream, track = line.split("\0")
        branches.append(
            Branch(
                name=name,
                position=position_of(upstream, track),
                is_merged=name in merged,
                held_by=holders.get(name),
            )
        )

    return RepositoryState(worktrees=worktrees, branches=tuple(branches))
