# scripts/source_restore.py
"""Discard changes to tracked paths, back to HEAD -- a dry run unless --yes (D.34).

GROUNDED. `git restore --staged --worktree --source=HEAD -- <paths>` resets the index
and the working tree to HEAD, and replaces `git checkout --`. It acts on tracked
files only, and on a path HEAD has never seen it drops the file -- so such a path is
refused. Without --yes it reports what it would restore and changes nothing.

THE PAIR. restore-plan/v1 records, per path, whether HEAD knows it and whether it
differs, observed through plumbing rather than human output; source.restore refuses
an untracked path and an empty list. After restoring, each path is observed again.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, JsonValue

from command_outcome import CommandOutcome
from gitenv import git
from opa import denials

ROOT = Path(__file__).resolve().parent.parent


class PathState(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    path: str
    in_head: bool
    changed: bool


class RestorePlan(BaseModel):
    """restore-plan/v1: what a restore would touch, observed before it acts."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    CONTRACT_ID: ClassVar[str] = "restore-plan/v1"

    contract: Literal["restore-plan/v1"] = "restore-plan/v1"
    paths: tuple[PathState, ...]
    apply: bool


def _state(root: Path, path: str) -> PathState:
    in_head = git("cat-file", "-e", f"HEAD:{path}", cwd=root).returncode == 0
    changed = bool(git("status", "--porcelain=v1", "--", path, cwd=root).stdout.strip())
    return PathState(path=path, in_head=in_head, changed=changed)


def _report(outcome: str, code: str, message: str, data: dict[str, JsonValue]) -> int:
    envelope = CommandOutcome.model_validate(
        {
            "command": "source:restore",
            "outcome": outcome,
            "code": code,
            "message": message,
            "data": data,
        }
    )
    print(json.dumps(envelope.model_dump(), indent=2))
    return envelope.exit_code


def main(argv: Sequence[str] | None = None, *, root: Path = ROOT) -> int:
    """source:restore [--yes] <path>..."""
    args = list(sys.argv[1:] if argv is None else argv)
    apply = "--yes" in args
    paths = [arg for arg in args if arg != "--yes"]
    plan = RestorePlan(paths=tuple(_state(root, path) for path in paths), apply=apply)
    data = plan.model_dump(mode="json")
    problems = denials("data.source.restore.deny", {"restore_plan": data})
    if problems:
        return _report("refused", "restore_refused", "; ".join(problems), data)

    changed = [state.path for state in plan.paths if state.changed]
    if not apply:
        message = f"would restore: {', '.join(changed) or 'nothing'}; pass --yes to restore"
        return _report("success", "restore_previewed", message, data)
    if changed:
        restored = git(
            "restore", "--staged", "--worktree", "--source=HEAD", "--", *changed, cwd=root
        )
        if restored.returncode != 0:
            return _report("failed", "restore_failed", restored.stderr.strip(), data)
    still = [path for path in paths if _state(root, path).changed]
    if still:
        return _report(
            "failed", "restore_incomplete", f"still differs from HEAD: {', '.join(still)}", data
        )
    return _report("success", "restored", f"restored: {', '.join(changed) or 'nothing'}", data)


if __name__ == "__main__":
    sys.exit(main())
