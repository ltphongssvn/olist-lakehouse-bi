"""A git environment that cannot be redirected by an inherited GIT_DIR.

NAMED gitenv.py, FLAT, DELIBERATELY.
It was scripts/git/env.py first. A directory named `git` on sys.path shadows the
`git` module GitPython installs, and `env` is generic enough to collide with
anything -- the documented failure mode where a file named like a real module is
imported instead of it. Flat names in one directory cannot do that.

KNOWN DEBT, NAMED RATHER THAN HIDDEN: shared helper code belongs in an installed
src/ package, not in scripts/ reached through pythonpath. The 2026 guidance is
explicit -- prefer the src layout, deprecate PYTHONPATH hacks. This repo already
has that arrangement and already imports through it, so this file uses it rather
than enlarging the problem with a shadowing directory. The migration is a change
of its own, not something to half-do inside a branch about worktrees.

THE PROBLEM, IN GIT'S OWN WORDS
"Environment variables, such as GIT_DIR, GIT_WORK_TREE, etc., are exported so
that Git commands run by the hook can correctly locate the repository. If your
hook needs to invoke Git commands in a foreign repository or in a different
working tree of the same repository, then it should clear these environment
variables so they do not interfere with Git operations at the foreign location."

Those variables OVERRIDE `-C` and `cwd`. Any git call made from inside a hook
therefore operates on the hook's repository regardless of where it was pointed.

WHY THIS REPO IS EXPOSED
tests/test_no_data_in_repo.py runs `git ls-files` with cwd=ROOT, and it runs
under the pre-commit hook. Today the hook's repository and ROOT are the same, so
it works by coincidence. From a linked worktree they differ, and the check that
asserts no data is tracked would read a different index entirely -- passing while
inspecting the wrong repository.

Elsewhere the same inheritance produced a real incident: a test fixture's
`git commit` wrote into the actual repository and the stray commit was pushed.

WHY `git rev-parse --local-env-vars` RATHER THAN A HARDCODED LIST
It is git's own enumeration of the repository-routing variables, so it stays
correct when git adds one. A literal list is a second copy of something git
already owns, and it goes stale silently -- the same argument this repo makes
about ci.yml restating the gate list.
"""

from __future__ import annotations

import os
import subprocess


def routing_overrides_present() -> dict[str, str]:
    """Which routing variables are set right now, for diagnostics.

    Reads the declared snapshot rather than os.environ directly, so "what does
    this project depend on" has ONE answer instead of one per file. The absence
    of a single answer is what made four CI failures hard to diagnose.
    """
    from environment import snapshot

    return snapshot().git_routing_overrides


def scrubbed_env() -> dict[str, str]:
    """A copy of the environment with git's repository-routing variables removed."""
    environment = dict(os.environ)

    listing = subprocess.run(
        ["git", "rev-parse", "--local-env-vars"],
        capture_output=True,
        text=True,
        check=False,
    )
    if listing.returncode != 0:
        # FAIL CLOSED ON THE FALLBACK. If git cannot enumerate them, remove every
        # GIT_ variable rather than guessing at a subset: over-removing makes git
        # resolve from cwd, which is exactly what the caller asked for.
        return {key: value for key, value in environment.items() if not key.startswith("GIT_")}

    for name in listing.stdout.split():
        environment.pop(name, None)

    return environment


def git(*args: str, cwd: str | os.PathLike[str] | None = None) -> subprocess.CompletedProcess[str]:
    """Run git with a scrubbed environment, resolving the repo from cwd alone."""
    return subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=cwd,
        env=scrubbed_env(),
    )
