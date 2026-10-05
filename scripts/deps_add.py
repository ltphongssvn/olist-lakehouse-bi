# scripts/deps_add.py
"""Add a dependency with uv and its lock, refusing any change to what is locked (D.32).

GROUNDED. `uv add` updates pyproject.toml and uv.lock together, and `uv lock
--check` confirms they match. uv never treats a lock as outdated because new
versions were released: upgrading is a separate, explicit act. So ADDING a
package must not change or remove any package already locked.

THE PAIR. deps-change/v1 records the package, whether the lock is current, whether
the package landed, its locked version and the lock diff; deps.add refuses a stale
lock, a package that did not land, and any locked package changed or removed.
On a refusal -- or if `uv add` itself fails -- both files are restored byte for byte.

Names compare under PEP 503 normalisation, as package indexes compare them.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tomllib
from collections.abc import Sequence
from pathlib import Path
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field

from command_outcome import CommandOutcome
from opa import denials

ROOT = Path(__file__).resolve().parent.parent
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*")
FILES = ("pyproject.toml", "uv.lock")


def normalise(name: str) -> str:
    """PEP 503: runs of -, _ and . are one -, and case does not matter."""
    return re.sub(r"[-_.]+", "-", name).lower()


class _Locked(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")
    name: str
    version: str | None = None


class _Lock(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")
    package: tuple[_Locked, ...] = ()


class _Project(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")
    dependencies: tuple[str, ...] = ()


class _Pyproject(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore", populate_by_name=True)
    project: _Project = _Project()
    dependency_groups: dict[str, tuple[str, ...]] = Field(
        default_factory=dict, alias="dependency-groups"
    )


class DepsChange(BaseModel):
    """deps-change/v1: one addition, and everything it did to the lock."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    CONTRACT_ID: ClassVar[str] = "deps-change/v1"

    contract: Literal["deps-change/v1"] = "deps-change/v1"
    package: str
    group: str | None
    lock_current: bool
    landed: bool
    locked_version: str | None
    added: tuple[str, ...]
    changed: tuple[str, ...]
    removed: tuple[str, ...]


def _locked(root: Path) -> dict[str, str]:
    lock = _Lock.model_validate(tomllib.loads((root / "uv.lock").read_text(encoding="utf-8")))
    return {normalise(package.name): package.version or "" for package in lock.package}


def _declared(root: Path) -> set[str]:
    pyproject = _Pyproject.model_validate(
        tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    )
    requirements = [*pyproject.project.dependencies]
    for group in pyproject.dependency_groups.values():
        requirements.extend(group)
    return {normalise(match.group(0)) for r in requirements if (match := NAME.match(r.strip()))}


def _report(outcome: str, code: str, message: str, data: dict[str, object]) -> int:
    envelope = CommandOutcome.model_validate(
        {"command": "deps:add", "outcome": outcome, "code": code, "message": message, "data": data}
    )
    print(json.dumps(envelope.model_dump(), indent=2))
    return envelope.exit_code


def main(argv: Sequence[str] | None = None, *, root: Path = ROOT) -> int:
    """deps:add <requirement> [--group <name>]."""
    args = list(sys.argv[1:] if argv is None else argv)
    group = None
    if "--group" in args:
        at = args.index("--group")
        if at + 1 >= len(args):
            raise SystemExit("--group needs a name, e.g. --group dev")
        group = args[at + 1]
        del args[at : at + 2]
    if len(args) != 1 or not (match := NAME.match(args[0].strip())):
        raise SystemExit("usage: mise run run deps:add <requirement> [--group <name>]")
    spec, package = args[0], normalise(match.group(0))

    saved = {name: (root / name).read_bytes() for name in FILES}

    def restore() -> None:
        for name, content in saved.items():
            (root / name).write_bytes(content)

    before = _locked(root)
    added = subprocess.run(
        ["uv", "add", *(["--group", group] if group else []), spec],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if added.returncode != 0:
        restore()
        return _report("failed", "uv_add_failed", added.stderr.strip(), {"package": package})
    checked = subprocess.run(
        ["uv", "lock", "--check"], cwd=root, capture_output=True, text=True, check=False
    )
    after = _locked(root)
    change = DepsChange(
        package=package,
        group=group,
        lock_current=checked.returncode == 0,
        landed=package in _declared(root),
        locked_version=after.get(package),
        added=tuple(sorted(set(after) - set(before))),
        changed=tuple(
            sorted(name for name in before if name in after and after[name] != before[name])
        ),
        removed=tuple(sorted(set(before) - set(after))),
    )
    problems = denials("data.deps.add.deny", {"deps_change": change.model_dump(mode="json")})
    if problems:
        restore()
        return _report(
            "refused", "dependency_refused", "; ".join(problems), change.model_dump(mode="json")
        )
    message = f"{package} {change.locked_version} added"
    return _report("success", "dependency_added", message, change.model_dump(mode="json"))


if __name__ == "__main__":
    sys.exit(main())
