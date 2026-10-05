# scripts/tasks_list.py
"""Every task, listed by a task, as data (D.35).

MISE'S OWN INVENTORY. `mise tasks ls --json --local --hidden` reports every task
mise will actually run, as mise resolves it, so the inventory is asked of mise
rather than parsed out of mise.toml by hand. The reply is validated at the
boundary -- extra fields ignored, a name required -- so a malformed reply fails
instead of yielding a partial inventory. An undescribed task is listed, and
turns every_task_described false; it is never dropped.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, NonNegativeInt, RootModel

from command_outcome import CommandOutcome

ROOT = Path(__file__).resolve().parent.parent


class MiseTask(BaseModel):
    """One task as `mise tasks ls --json` reports it; fields not read are ignored."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    name: str = Field(min_length=1)
    description: str = ""
    source: str = ""
    usage: str | None = None


class _Reply(RootModel[tuple[MiseTask, ...]]):
    """mise answers with a top-level array."""


class ListedTask(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    description: str
    source: str
    declares_usage: bool


class TaskInventory(BaseModel):
    """task-inventory/v1: every task, sorted, and whether each is described."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    CONTRACT_ID: ClassVar[str] = "task-inventory/v1"

    contract: Literal["task-inventory/v1"] = "task-inventory/v1"
    tasks: tuple[ListedTask, ...]
    count: NonNegativeInt
    every_task_described: bool


def inventory() -> TaskInventory:
    """Ask mise for every local task, hidden ones included, and validate the reply."""
    result = subprocess.run(
        ["mise", "tasks", "ls", "--json", "--local", "--hidden"],
        capture_output=True,
        text=True,
        check=False,
        cwd=ROOT,
    )
    if result.returncode != 0:
        raise SystemExit(f"mise tasks ls failed: {result.stderr.strip()}")
    listed = sorted(
        (
            ListedTask(
                name=task.name,
                description=task.description,
                source=task.source,
                declares_usage=bool((task.usage or "").strip()),
            )
            for task in _Reply.model_validate_json(result.stdout).root
        ),
        key=lambda task: task.name,
    )
    return TaskInventory(
        tasks=tuple(listed),
        count=len(listed),
        every_task_described=all(task.description.strip() for task in listed),
    )


def main() -> int:
    """tasks:list -- the inventory as a command-outcome envelope."""
    listed = inventory()
    envelope = CommandOutcome.model_validate(
        {
            "command": "tasks:list",
            "outcome": "success",
            "code": "tasks_listed",
            "message": f"{listed.count} task(s)",
            "data": listed.model_dump(mode="json"),
        }
    )
    print(json.dumps(envelope.model_dump(), indent=2))
    return envelope.exit_code


if __name__ == "__main__":
    sys.exit(main())
