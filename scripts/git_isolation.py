# scripts/git_isolation.py
"""No test can act on the repository a git hook names (C.20).

WHAT HAPPENED. git exports GIT_DIR and its siblings to hooks, and they override
any cwd or -C. Run under the pre-push hook, a test's throwaway git init, commit
and update-ref landed on this repository and moved develop, origin/develop and a
feature branch onto empty commits.

THE PAIR. git-isolation/v1 records which of git's repository-local variables the
session holds -- git's own list, from rev-parse --local-env-vars, never a guess.
machine.testing decides which have leaked; isolate removes exactly those, then
observes again and stops the session if the policy still refuses. Run once, from
conftest, before any test is collected, it covers every test that runs git --
existing and future -- however pytest is launched.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping, MutableMapping
from pathlib import Path
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from opa import denials, query

ROOT = Path(__file__).resolve().parent.parent
_NAMES = TypeAdapter(tuple[str, ...])


class GitIsolation(BaseModel):
    """git-isolation/v1: git's repository-local variables, and which are present."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    CONTRACT_ID: ClassVar[str] = "git-isolation/v1"

    contract: Literal["git-isolation/v1"] = "git-isolation/v1"
    local_variables: tuple[str, ...] = Field(min_length=1)
    present: tuple[str, ...]


def local_variables() -> tuple[str, ...]:
    """git's own list, asked from this repository with every GIT_* variable cleared."""
    clean = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    result = subprocess.run(
        ["git", "rev-parse", "--local-env-vars"],
        capture_output=True,
        text=True,
        check=False,
        cwd=ROOT,
        env=clean,
    )
    if result.returncode != 0:
        raise SystemExit(f"git rev-parse --local-env-vars failed: {result.stderr.strip()}")
    return tuple(sorted(name for name in result.stdout.split() if name))


def observe(environ: Mapping[str, str], names: tuple[str, ...]) -> GitIsolation:
    present = tuple(sorted(name for name in names if name in environ))
    return GitIsolation(local_variables=names, present=present)


def isolate(environ: MutableMapping[str, str]) -> GitIsolation:
    """Remove what machine.testing says has leaked, then require it to allow the rest."""
    names = local_variables()
    before = observe(environ, names)
    leaked = _NAMES.validate_python(
        query("data.machine.testing.leaked", {"git_isolation": before.model_dump(mode="json")})
    )
    for name in leaked:
        environ.pop(name, None)
    after = observe(environ, names)
    problems = denials(
        "data.machine.testing.deny", {"git_isolation": after.model_dump(mode="json")}
    )
    if problems:
        raise SystemExit(
            "the test session still holds git's repository variables: " + "; ".join(problems)
        )
    return after
