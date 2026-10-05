# scripts/template_init.py
"""A generated project is born a git repository whose first commit is the template (D.58).

copier update needs a repository with a clean working tree, setup needs .git to install
its hooks, and a project's own commit task refuses main. So template:init makes the
template's output the first commit on main and starts develop from it. Every git call
goes through gitenv, so no hook's repository routing can redirect it, and a failed call
is reported as data. Python observes; policies/template/init decides.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict

from command_outcome import CommandOutcome
from gitenv import git
from opa import denials
from plan_init import PLAN as PLAN_FILE
from plan_init import write_day_one

ROOT = Path(__file__).resolve().parent.parent
ENTRYPOINT = "data.template.init.deny"
ANSWERS = ".copier-answers.yml"
# THE TEMPLATE COMMIT IS ALREADY IN .copier-answers.yml, which this commit includes.
# BORN WITH ITS PLAN, TRACED (D.61): the first commit names A.1, the step it serves.
MESSAGE = "chore: generate from the platform template\n\nPlan-Step: A.1"
STEPS: tuple[tuple[str, ...], ...] = (
    ("init", "-b", "main"),
    ("add", "-A"),
    ("commit", "-q", "-m", MESSAGE),
    ("branch", "develop"),
)


class InitRequest(BaseModel):
    """template-init/v1: where a generated project would become a repository, as observed."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    CONTRACT_ID: ClassVar[str] = "template-init/v1"

    contract: Literal["template-init/v1"] = "template-init/v1"
    destination: str
    answers_present: bool
    already_repository: bool
    inside_source: bool


def observe(destination: Path, *, root: Path = ROOT) -> InitRequest:
    """The destination as it is: generated or not, a repository or not, and where."""
    target = destination.expanduser().resolve()
    return InitRequest(
        destination=str(target),
        answers_present=(target / ANSWERS).is_file(),
        already_repository=(target / ".git").exists(),
        inside_source=target.is_relative_to(root.resolve()),
    )


def _report(outcome: str, code: str, message: str, data: dict[str, object]) -> int:
    envelope = CommandOutcome.model_validate(
        {
            "command": "template:init",
            "outcome": outcome,
            "code": code,
            "message": message,
            "data": data,
        }
    )
    print(json.dumps(envelope.model_dump(), indent=2))
    return envelope.exit_code


def main(argv: Sequence[str] | None = None) -> int:
    """template:init <destination> -- main and develop at one commit, or refuse."""
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        raise SystemExit("usage: mise run run template:init <destination>")
    made = observe(Path(args[0]))
    observed = made.model_dump(mode="json")
    found = denials(ENTRYPOINT, {"template_init": observed})
    if found:
        return _report("refused", "init_refused", "; ".join(found), observed)
    if not (Path(made.destination) / PLAN_FILE).exists():
        write_day_one(Path(made.destination))
    for step in STEPS:
        done = git(*step, cwd=made.destination)
        if done.returncode != 0:
            reason = done.stderr.strip() or f"git {step[0]} exited {done.returncode}"
            failed = {**observed, "step": list(step)}
            return _report("failed", "init_failed", reason.splitlines()[0], failed)
    # REPORTS WHAT RAN, NOT WHAT WAS MEANT: the steps executed are the evidence.
    ran = [" ".join(step) for step in STEPS]
    message = f"{made.destination}: {len(ran)} git step(s) ran"
    return _report("success", "project_initialised", message, {**observed, "ran": ran})


if __name__ == "__main__":
    sys.exit(main())
