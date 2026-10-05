# scripts/template_publish.py
"""A generated project is published with main and develop before anything else (D.60).

This repository was published right after its root commit and changed only through pull
requests; the sibling ran gh repo create, pushed develop and made it the default. So
template:publish creates the GitHub repository, adds origin over SSH, pushes main and
develop, and makes develop the default -- non-interactively (D.57). gh exit 4 means
authentication required and is reported as data; a failed push takes origin away again,
so nothing is left half-done. Python observes; policies/template/publish decides.

D.62: it refuses once hooks are installed (a project's own pre-push gate needs the
origin/develop only this push creates), adopts an empty repository an earlier attempt
made, and reports the hook's own words when a push is refused.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from command_outcome import CommandOutcome
from gitenv import git
from opa import denials
from pr_logs import ANSI
from template_new import SSH_USER, _non_interactive

ENTRYPOINT = "data.template.publish.deny"
ANSWERS = ".copier-answers.yml"
HOST = "github.com"
AUTH_REQUIRED = 4
BRANCHES = ("main", "develop")
Call = Callable[[str, str], int]
Remote = Literal["absent", "empty", "populated", "unknown"]
# ENOUGH TO KEEP WHAT A HOOK PRINTED above git's own closing line.
TAIL = 12


class PublishRequest(BaseModel):
    """template-publish/v1: a generated project about to be published, as observed."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    CONTRACT_ID: ClassVar[str] = "template-publish/v1"

    contract: Literal["template-publish/v1"] = "template-publish/v1"
    destination: str
    repository: str = Field(pattern=r"^[\w.-]+/[\w.-]+$")
    visibility: Literal["public", "private"]
    answers_present: bool
    clean: bool
    has_remote: bool
    hooks_installed: bool
    remote: Remote


def _hooks_installed(target: Path) -> bool:
    """Any hook a setup wrote, wherever core.hooksPath points; never assume .git/hooks."""
    where = git("rev-parse", "--git-path", "hooks", cwd=target)
    if where.returncode != 0:
        return False
    hooks = Path(where.stdout.strip())
    hooks = hooks if hooks.is_absolute() else target / hooks
    return hooks.is_dir() and any(
        entry.is_file() and not entry.name.endswith(".sample") for entry in hooks.iterdir()
    )


def observe(
    destination: Path, repository: str, visibility: str, *, remote: str = "unknown"
) -> PublishRequest:
    """Generated or not, clean or not, and whether it is published anywhere already."""
    target = destination.expanduser().resolve()
    clean, has_remote, hooks = False, False, False
    # ONLY ITS OWN REPOSITORY: without .git, git would answer for an enclosing one.
    if (target / ".git").exists():
        status = git("status", "--porcelain", cwd=target)
        clean = status.returncode == 0 and not status.stdout.strip()
        has_remote = bool(git("remote", cwd=target).stdout.strip())
        hooks = _hooks_installed(target)
    return PublishRequest.model_validate(
        {
            "destination": str(target),
            "repository": repository,
            "visibility": visibility,
            "answers_present": (target / ANSWERS).is_file(),
            "clean": clean,
            "has_remote": has_remote,
            "hooks_installed": hooks,
            "remote": remote,
        }
    )


def _gh(*args: str) -> int:
    """gh with prompts off: a missing answer fails instead of waiting (D.57)."""
    environment = {**os.environ, "GH_PROMPT_DISABLED": "1"}
    return subprocess.run(["gh", *args], env=environment, check=False).returncode


def create_repository(repository: str, visibility: str) -> int:
    return _gh("repo", "create", repository, f"--{visibility}")


def default_branch(repository: str, branch: str) -> int:
    return _gh("repo", "edit", repository, "--default-branch", branch)


def ssh_url(repository: str) -> str:
    """The SSH remote this machine pushes with, composed rather than written (D.57)."""
    return f"{SSH_USER}@{HOST}:{repository}.git"


def inspect_remote(repository: str) -> str:
    """absent, empty or populated, from gh's isEmpty; unknown when gh cannot say (D.62).

    Not the REST size field: GitHub updates it in the background, so it lags a push.
    """
    environment = {**os.environ, "GH_PROMPT_DISABLED": "1"}
    viewed = subprocess.run(
        ["gh", "repo", "view", repository, "--json", "isEmpty", "--jq", ".isEmpty"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    if viewed.returncode == 0:
        return "empty" if viewed.stdout.strip() == "true" else "populated"
    if "Could not resolve to a Repository" in viewed.stderr:
        return "absent"
    return "unknown"


def _reason(stderr: str) -> str:
    """What refused, colours stripped: the tail of stderr, where a hook writes its reason
    above git's generic last line, which alone says nothing (D.62).
    """
    lines = [line.strip() for line in ANSI.sub("", stderr).splitlines() if line.strip()]
    return " | ".join(lines[-TAIL:]) if lines else "the command failed without a message"


def _report(outcome: str, code: str, message: str, data: Mapping[str, object]) -> int:
    # READ-ONLY, SO Mapping: dict is invariant in its value type, Mapping covariant --
    # the convention opa.denials and evaluate_policies already follow.
    envelope = CommandOutcome.model_validate(
        {
            "command": "template:publish",
            "outcome": outcome,
            "code": code,
            "message": message,
            "data": data,
        }
    )
    print(json.dumps(envelope.model_dump(), indent=2))
    return envelope.exit_code


def main(
    argv: Sequence[str] | None = None,
    *,
    inspect: Callable[[str], str] = inspect_remote,
    create: Call = create_repository,
    make_default: Call = default_branch,
    remote_url: Callable[[str], str] = ssh_url,
) -> int:
    """template:publish <destination> <owner/name> <visibility> -- published, or refused."""
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 3:
        raise SystemExit("usage: mise run run template:publish <destination> <repo> <visibility>")
    try:
        made = observe(Path(args[0]), args[1], args[2], remote=inspect(args[1]))
    except ValidationError as problem:
        asked = {"repository": args[1], "visibility": args[2]}
        return _report("refused", "publish_refused", str(problem).splitlines()[0], asked)
    observed = made.model_dump(mode="json")
    found = denials(ENTRYPOINT, {"template_publish": observed})
    if found:
        return _report("refused", "publish_refused", "; ".join(found), observed)
    destination = Path(made.destination)
    # CREATE ONLY WHAT IS ABSENT: an empty repository from an earlier attempt is adopted.
    if made.remote == "absent":
        created = create(made.repository, made.visibility)
        if created == AUTH_REQUIRED:
            message = "gh needs authentication: run gh auth login, then publish again"
            return _report("failed", "auth_required", message, observed)
        if created != 0:
            message = f"gh repo create exited {created}"
            return _report("failed", "create_failed", message, observed)
    added = git("remote", "add", "origin", remote_url(made.repository), cwd=destination)
    if added.returncode != 0:
        return _report("failed", "remote_failed", _reason(added.stderr), observed)
    with _non_interactive():
        pushed = git("push", "-u", "origin", *BRANCHES, cwd=destination)
    if pushed.returncode != 0:
        # ATOMIC LOCALLY: the remote repository exists, but this project is as it was.
        git("remote", "remove", "origin", cwd=destination)
        undone = {**observed, "origin_removed": True}
        return _report("failed", "push_failed", _reason(pushed.stderr), undone)
    defaulted = make_default(made.repository, "develop")
    if defaulted != 0:
        message = f"gh repo edit exited {defaulted}; main and develop are pushed"
        return _report("failed", "default_failed", message, observed)
    published = {**observed, "pushed": list(BRANCHES), "default": "develop"}
    # REPORTS WHAT WAS PUSHED, NOT WHAT WAS MEANT: the branch list is the evidence.
    message = f"{made.repository}: pushed {', '.join(BRANCHES)}; develop the default"
    return _report("success", "project_published", message, published)


if __name__ == "__main__":
    sys.exit(main())
