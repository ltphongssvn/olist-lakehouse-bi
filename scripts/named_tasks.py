# scripts/named_tasks.py
"""Every task a message tells the reader to run is a task mise.toml declares (D.56).

A remediation message is an instruction. check_prereqs.py and databricks.yml told the
reader to run bootstrap:groups long after bootstrap:identity replaced it,
so the advice failed at the moment someone followed it.

TWO SOURCES, NO NEW PARSER: tracked lines come from source:search (D.27), and the
declared tasks from tasks:list (D.35) -- mise's own resolution, hidden tasks included.
Rego decides (policies/tasks/named); this module only observes.

A TOKEN NAMES A TASK ONLY WHEN IT IS A WHOLE TASK NAME: `plan:{verb}` is a template and
`<slug>` a placeholder, and reading `plan:` out of the first would refuse a correct message.

NOT INSTRUCTIONS: tests/ holds synthetic mentions, and context/ holds sources verbatim.

UNTRACKED FILES COUNT: the guard judges what is about to be committed. Tracked-only, it
passed check while this very module was new, and pre-push refused it once committed.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, PositiveInt

from source_search import search
from tasks_list import inventory

ROOT = Path(__file__).resolve().parent.parent
RUNNER = "run"
INVOKES = "mise.* run "
NOT_INSTRUCTIONS = (":(exclude)tests", ":(exclude)context")
TASK_NAME = re.compile(r"[a-z][a-z0-9_-]*(?::[a-z0-9_-]+)*")
INVOCATION = re.compile(r"\bmise(?:\s+-C\s+\S+)?\s+run\s+(\S+)(?:\s+(\S+))?")
EDGE = "`'\".,;:()"


class Mention(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    path: str
    number: PositiveInt
    task: str


class NamedTasks(BaseModel):
    """named-tasks/v1: every task a tracked message names, and every task declared."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    CONTRACT_ID: ClassVar[str] = "named-tasks/v1"

    contract: Literal["named-tasks/v1"] = "named-tasks/v1"
    declared: tuple[str, ...]
    mentions: tuple[Mention, ...]


def mentioned(text: str) -> list[str]:
    """The task names a line tells the reader to run, through the runner when used."""
    names: list[str] = []
    for invocation in INVOCATION.finditer(text):
        first, second = invocation.group(1), invocation.group(2)
        token = second if first == RUNNER and second is not None else first
        name = token.strip(EDGE)
        if TASK_NAME.fullmatch(name):
            names.append(name)
    return names


def named_tasks(root: Path = ROOT) -> NamedTasks:
    """Every mention in tracked instructions, with the tasks mise declares."""
    lines = search(root, INVOKES, NOT_INSTRUCTIONS, untracked=True)
    mentions = tuple(
        Mention(path=line.path, number=line.number, task=name)
        for line in lines.matches
        for name in mentioned(line.text)
    )
    declared = tuple(task.name for task in inventory().tasks)
    return NamedTasks(declared=declared, mentions=mentions)
