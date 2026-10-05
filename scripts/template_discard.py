# scripts/template_discard.py
"""An unpublished generated project holding only its generated commit can be discarded (D.63).

A project generated before D.61 has a first commit its own matrix flags forever, and
history is not rewritten; when it holds nothing authored and nothing published, it is
regenerated instead. Removal is irreversible, so every fact is observed first and the
policy decides: generated, not a symlink, no remote, one commit, clean, not this
repository or home, and an rmtree that resists symlink attacks on this platform.
"""

from __future__ import annotations

import json
import shutil
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict

from command_outcome import CommandOutcome
from gitenv import git
from opa import denials

ENTRYPOINT = "data.template.discard.deny"
ANSWERS = ".copier-answers.yml"
SOURCE = Path(__file__).resolve().parent.parent


class DiscardRequest(BaseModel):
    """template-discard/v1: a project about to be removed, as observed."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    CONTRACT_ID: ClassVar[str] = "template-discard/v1"

    contract: Literal["template-discard/v1"] = "template-discard/v1"
    destination: str
    resolved: str
    is_symlink: bool
    answers_present: bool
    has_remote: bool
    commits: int
    clean: bool
    protected: bool
    safe_removal: bool


def _protected(target: Path) -> bool:
    """This repository, anything inside or above it, home or above it, or a root."""
    home = Path.home().resolve()
    return (
        target == Path(target.anchor)
        or target.is_relative_to(SOURCE)
        or SOURCE.is_relative_to(target)
        or home.is_relative_to(target)
    )


def observe(destination: Path) -> DiscardRequest:
    """Every fact the policy needs, observed before anything can be removed."""
    given = destination.expanduser()
    target = given.resolve()
    clean, has_remote, commits = False, False, 0
    # ONLY ITS OWN REPOSITORY: without .git, git would answer for an enclosing one.
    if (target / ".git").exists():
        status = git("status", "--porcelain", cwd=target)
        clean = status.returncode == 0 and not status.stdout.strip()
        has_remote = bool(git("remote", cwd=target).stdout.strip())
        counted = git("rev-list", "--count", "HEAD", cwd=target)
        commits = int(counted.stdout.strip()) if counted.returncode == 0 else 0
    return DiscardRequest.model_validate(
        {
            "destination": str(given),
            "resolved": str(target),
            # BEFORE RESOLVING: a resolved path is never a symlink.
            "is_symlink": given.is_symlink(),
            "answers_present": (target / ANSWERS).is_file(),
            "has_remote": has_remote,
            "commits": commits,
            "clean": clean,
            "protected": _protected(target),
            "safe_removal": shutil.rmtree.avoids_symlink_attacks,
        }
    )


def _report(outcome: str, code: str, message: str, data: Mapping[str, object]) -> int:
    envelope = CommandOutcome.model_validate(
        {
            "command": "template:discard",
            "outcome": outcome,
            "code": code,
            "message": message,
            "data": data,
        }
    )
    print(json.dumps(envelope.model_dump(), indent=2))
    return envelope.exit_code


def main(argv: Sequence[str] | None = None) -> int:
    """template:discard <destination> -- removed, or refused with the reason."""
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        raise SystemExit("usage: mise run run template:discard <destination>")
    made = observe(Path(args[0]))
    observed = made.model_dump(mode="json")
    found = denials(ENTRYPOINT, {"template_discard": observed})
    if found:
        return _report("refused", "discard_refused", "; ".join(found), observed)
    failures: list[str] = []

    def collect(function: object, path: str, error: BaseException) -> None:
        failures.append(f"{path}: {error}")

    shutil.rmtree(made.resolved, onexc=collect)
    # REPORTS WHAT HAPPENED, NOT WHAT WAS MEANT: the directory is observed gone.
    if failures or Path(made.resolved).exists():
        message = "; ".join(failures[-5:]) or f"{made.resolved} still exists"
        left = {**observed, "failures": failures}
        return _report("failed", "discard_incomplete", message, left)
    removed = {**observed, "removed": True}
    return _report("success", "project_discarded", f"{made.resolved}: removed", removed)


if __name__ == "__main__":
    sys.exit(main())
