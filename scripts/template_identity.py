# scripts/template_identity.py
"""A generated project takes its identity from the source, before it has a remote (D.59).

start:here needs origin, origin needs the repository named rightly, the name needs the
identity, and committing it needs a feature branch. So the source applies the identity
to a fresh project -- one commit, no remote -- as its second commit, and develop follows.
set_identity rewrites exactly the declared slots (D.52); every git call goes through
gitenv; a failed step is reported as data. Python observes; policies/template/identity
decides.
"""

from __future__ import annotations

import json
import sys
import tomllib
from collections.abc import Sequence
from pathlib import Path
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, NonNegativeInt

from command_outcome import CommandOutcome
from gitenv import git
from opa import denials
from project_identity import IdentitySpec, load, set_identity

ENTRYPOINT = "data.template.identity.deny"
ANSWERS = ".copier-answers.yml"
MESSAGE = "chore: take the project identity"
STEPS: tuple[tuple[str, ...], ...] = (
    ("add", "-A"),
    ("commit", "-q", "-m", MESSAGE),
    ("branch", "-f", "develop", "main"),
)


class IdentityRequest(BaseModel):
    """template-identity/v1: a project about to take its identity, as observed."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    CONTRACT_ID: ClassVar[str] = "template-identity/v1"

    contract: Literal["template-identity/v1"] = "template-identity/v1"
    destination: str
    answers_present: bool
    commits: NonNegativeInt
    has_remote: bool


def observe(destination: Path) -> IdentityRequest:
    """Generated or not, how much history, and whether it is published anywhere."""
    target = destination.expanduser().resolve()
    commits, has_remote = 0, False
    # ONLY ITS OWN REPOSITORY: without .git, git would answer for an enclosing one.
    if (target / ".git").exists():
        counted = git("rev-list", "--count", "HEAD", cwd=target)
        if counted.returncode == 0:
            commits = int(counted.stdout.strip())
        has_remote = bool(git("remote", cwd=target).stdout.strip())
    return IdentityRequest(
        destination=str(target),
        answers_present=(target / ANSWERS).is_file(),
        commits=commits,
        has_remote=has_remote,
    )


def _report(outcome: str, code: str, message: str, data: dict[str, object]) -> int:
    envelope = CommandOutcome.model_validate(
        {
            "command": "template:identity",
            "outcome": outcome,
            "code": code,
            "message": message,
            "data": data,
        }
    )
    print(json.dumps(envelope.model_dump(), indent=2))
    return envelope.exit_code


def main(argv: Sequence[str] | None = None) -> int:
    """template:identity <destination> <spec> -- the second commit, or refuse."""
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2:
        raise SystemExit("usage: mise run run template:identity <destination> <spec>")
    made = observe(Path(args[0]))
    observed = made.model_dump(mode="json")
    found = denials(ENTRYPOINT, {"template_identity": observed})
    if found:
        return _report("refused", "identity_refused", "; ".join(found), observed)
    destination = Path(made.destination)
    try:
        text = Path(args[1]).read_text(encoding="utf-8")
        spec = IdentitySpec.model_validate(tomllib.loads(text))
        target = load(destination).model_copy(update=spec.model_dump())
        changed = set_identity(destination, target)
    except (OSError, ValueError) as problem:
        reason = str(problem).strip() or type(problem).__name__
        return _report("refused", "identity_refused", reason.splitlines()[0], observed)
    for step in STEPS:
        done = git(*step, cwd=destination)
        if done.returncode != 0:
            reason = done.stderr.strip() or f"git {step[0]} exited {done.returncode}"
            failed = {**observed, "step": list(step)}
            return _report("failed", "identity_failed", reason.splitlines()[0], failed)
    ran = [" ".join(step) for step in STEPS]
    taken = {**observed, "changed": list(changed), "ran": ran}
    message = f"{made.destination}: {len(changed)} file(s) took the identity"
    return _report("success", "identity_taken", message, taken)


if __name__ == "__main__":
    sys.exit(main())
