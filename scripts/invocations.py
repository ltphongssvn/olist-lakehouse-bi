"""invocations/v1: every command the tasks and the gate run, as structured data.

ONE OBSERVATION, MANY POLICIES. The type-check observer collected these itself,
filtered to mypy, with its own model; the lint policy needs the same commands
filtered to ruff. Both now read this, so the shape is defined once.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field

from check_all import GATES
from task_commands import command_invocations, task_input

ROOT = Path(__file__).resolve().parent.parent


class Invocation(BaseModel):
    """One command, and where it runs: task:<name> or gate:<name>."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: str = Field(min_length=1)
    argv: tuple[str, ...]


class Invocations(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    CONTRACT_ID: ClassVar[str] = "invocations/v1"

    contract: Literal["invocations/v1"] = "invocations/v1"
    invocations: tuple[Invocation, ...]


def observe(root: Path = ROOT) -> Invocations:
    """Every command in every task, and every gate the quality gate runs."""
    found = [
        Invocation(source=f"task:{command.task}", argv=command.argv)
        for command in command_invocations(task_input(root / "mise.toml").tasks)
        if command.argv
    ]
    found += [Invocation(source=f"gate:{name}", argv=tuple(argv)) for name, argv, *_ in GATES]
    return Invocations(invocations=tuple(found))
