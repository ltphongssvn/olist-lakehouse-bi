# scripts/project_identity.py
"""Project identity, declared once (D.52).

contracts/project-identity.toml names the project and the Databricks objects it owns.
Code reads it here, at the boundary, and derives every relation from it. Files that
cannot read it -- TOML names, YAML defaults, a Nix string, a JSON $id, two shell lines --
hold SLOTS: line templates the declaration renders, and identity:set rewrites only those.

GROUNDED. One source of truth for identity is the 2026 pattern: when the project renames,
only the declaration changes, and a guard proves no hard-coded copy survives elsewhere.
policies/identity decides that over the inventory observed here, tracked and untracked.
"""

from __future__ import annotations

import json
import sys
import tomllib
from collections.abc import Sequence
from pathlib import Path
from typing import ClassVar, Literal

import tomlkit
from pydantic import BaseModel, ConfigDict, Field, PositiveInt

from command_outcome import CommandOutcome
from source_search import search

ROOT = Path(__file__).resolve().parent.parent
DECLARATION = Path("contracts/project-identity.toml")


class Slot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    path: str = Field(min_length=1)
    line: str = Field(min_length=1)


class ProjectIdentity(BaseModel):
    """project-identity/v1: who this project is, and where files hold it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    CONTRACT_ID: ClassVar[str] = "project-identity/v1"

    contract: Literal["project-identity/v1"] = "project-identity/v1"
    name: str = Field(pattern=r"^[a-z][a-z0-9-]*$")
    catalog: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    reader_group: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    ci_principal: str = Field(pattern=r"^[a-z][a-z0-9-]*$")
    default_schema: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    repository: str = Field(pattern=r"^https://github\.com/[\w.-]+/[\w.-]+$")
    exempt: tuple[str, ...]
    slots: tuple[Slot, ...] = Field(min_length=1)


class Occurrence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    path: str
    number: PositiveInt
    value: str
    slot: bool


class IdentityInventory(BaseModel):
    """identity-inventory/v1: every identity value found, and whether a slot holds it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    CONTRACT_ID: ClassVar[str] = "identity-inventory/v1"

    contract: Literal["identity-inventory/v1"] = "identity-inventory/v1"
    exempt: tuple[str, ...]
    occurrences: tuple[Occurrence, ...]


def _values(identity: ProjectIdentity) -> dict[str, str]:
    return {
        "name": identity.name,
        "catalog": identity.catalog,
        "reader_group": identity.reader_group,
        "ci_principal": identity.ci_principal,
        "default_schema": identity.default_schema,
        "repository": identity.repository,
    }


def load(root: Path = ROOT) -> ProjectIdentity:
    """The declaration, validated where it enters."""
    text = (root / DECLARATION).read_text(encoding="utf-8")
    return ProjectIdentity.model_validate(tomllib.loads(text))


def render(slot: Slot, identity: ProjectIdentity) -> str:
    """The line a slot holds for this identity."""
    return slot.line.format_map(_values(identity))


def observe(root: Path = ROOT) -> IdentityInventory:
    """Every identity value in tracked and untracked files, and whether a slot holds it."""
    identity = load(root)
    slotted = {(slot.path, render(slot, identity)) for slot in identity.slots}
    occurrences: list[Occurrence] = []
    for value in _values(identity).values():
        for match in search(root, value, (), untracked=True).matches:
            # EXACT, NOT REGEX: a basic regex reads the URL dots as any character.
            if value in match.text:
                held = (match.path, match.text) in slotted
                occurrences.append(
                    Occurrence(path=match.path, number=match.number, value=value, slot=held)
                )
    return IdentityInventory(exempt=identity.exempt, occurrences=tuple(occurrences))


def set_identity(root: Path, target: ProjectIdentity) -> tuple[str, ...]:
    """Rewrite every slot line and the declaration for `target`, all or nothing."""
    target = ProjectIdentity.model_validate(target.model_dump())
    current = load(root)
    planned: dict[Path, str] = {}
    for path in sorted({slot.path for slot in current.slots}):
        lines = (root / path).read_text(encoding="utf-8").split("\n")
        for slot in (slot for slot in current.slots if slot.path == path):
            old, new = render(slot, current), render(slot, target)
            hits = [index for index, line in enumerate(lines) if line == old]
            if not hits:
                raise ValueError(f"{path}: no line holds the slot {old!r}")
            for index in hits:
                lines[index] = new
        planned[root / path] = "\n".join(lines)
    document = tomlkit.parse((root / DECLARATION).read_text(encoding="utf-8"))
    for key, value in _values(target).items():
        document[key] = value
    rendered = tomlkit.dumps(document)
    ProjectIdentity.model_validate(tomllib.loads(rendered))
    planned[root / DECLARATION] = rendered
    for destination, text in planned.items():
        destination.write_text(text, encoding="utf-8")
    return tuple(sorted(str(path.relative_to(root)) for path in planned))


class IdentitySpec(BaseModel):
    """What identity:set reads: the six identity values, and nothing else."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    catalog: str
    reader_group: str
    ci_principal: str
    default_schema: str
    repository: str


def _report(outcome: str, code: str, message: str, data: dict[str, object]) -> int:
    envelope = CommandOutcome.model_validate(
        {
            "command": "identity:set",
            "outcome": outcome,
            "code": code,
            "message": message,
            "data": data,
        }
    )
    print(json.dumps(envelope.model_dump(), indent=2))
    return envelope.exit_code


def main(argv: Sequence[str] | None = None) -> int:
    """identity:set <spec> -- every slot and the declaration, together or not at all."""
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        raise SystemExit("usage: mise run run identity:set <spec.toml>")
    try:
        text = Path(args[0]).read_text(encoding="utf-8")
        spec = IdentitySpec.model_validate(tomllib.loads(text))
        target = load().model_copy(update=spec.model_dump())
        changed = set_identity(ROOT, target)
    except (OSError, ValueError) as problem:
        return _report("refused", "identity_refused", str(problem).splitlines()[0], {})
    message = f"{target.name}: {len(changed)} file(s) set"
    return _report("success", "identity_set", message, {"changed": list(changed)})


if __name__ == "__main__":
    sys.exit(main())
