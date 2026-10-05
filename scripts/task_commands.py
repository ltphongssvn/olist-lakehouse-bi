"""The commands each task runs, as typed data: task-input/v1 and Command.

ONE PARSER, SHARED. It lived inside evaluate_policies.py; the type-check
observer needs it too, and importing it from there would have made a cycle once
the pipeline imported the observer. Moved, not copied.

THROUGH A MODEL. mise.toml was read with raw tomllib and handed on as a dict,
and each command as a dict a caller had to pick apart with isinstance. The file
is validated as it enters, and a command is a Command.

A NEWLINE ENDS A COMMAND. The parser split on | && || ; & and treated a newline
as whitespace, so a two-line body read as ONE command. Backslash-continued lines
are joined first, so a command spanning lines stays one, and a quoted string
spanning lines stays one token.
"""

from __future__ import annotations

import shlex
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field

ROOT = Path(__file__).resolve().parent.parent
MISE_TOML = ROOT / "mise.toml"


class _Task(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")
    run: str | tuple[str, ...] = ""
    description: str | None = None


class _Mise(BaseModel):
    """The one part of mise.toml this reads."""

    model_config = ConfigDict(frozen=True, extra="ignore")
    tasks: dict[str, _Task] = Field(default_factory=dict)


class TaskInput(BaseModel):
    """task-input/v1: every task's body and description, as the policies read them."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    CONTRACT_ID: ClassVar[str] = "task-input/v1"

    contract: Literal["task-input/v1"] = "task-input/v1"
    tasks: dict[str, str]
    descriptions: dict[str, str]


class Command(BaseModel):
    """One command a task runs. `unparsed` holds a body that could not be tokenised."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    task: str = Field(min_length=1)
    argv: tuple[str, ...]
    unparsed: str | None = None


def task_input(path: Path = MISE_TOML) -> TaskInput:
    """Every task's body and description, validated as mise.toml enters."""
    mise = _Mise.model_validate(tomllib.loads(path.read_text(encoding="utf-8")))
    return TaskInput(
        tasks={
            name: task.run if isinstance(task.run, str) else "\n".join(task.run)
            for name, task in mise.tasks.items()
        },
        descriptions={
            name: task.description for name, task in mise.tasks.items() if task.description
        },
    )


def command_invocations(tasks: Mapping[str, str]) -> tuple[Command, ...]:
    """The commands each task runs, one argv per command.

    FAIL CLOSED: a body that cannot be tokenised is reported, never skipped.
    """
    commands: list[Command] = []
    for name, body in tasks.items():
        joined = body.replace("\\\n", " ")
        lexer = shlex.shlex(joined, posix=True, punctuation_chars="();<>|&\n")
        lexer.whitespace = " \t\r"
        lexer.whitespace_split = True
        try:
            tokens = list(lexer)
        except ValueError:
            commands.append(Command(task=name, argv=(), unparsed=body[:120]))
            continue

        argv: list[str] = []
        for token in tokens:
            # A RUN OF SEPARATORS IS ONE BOUNDARY: ";\n" and "\n\n" end a command too.
            if token and all(char in ";&|\n" for char in token):
                if argv:
                    commands.append(Command(task=name, argv=tuple(argv)))
                argv = []
                continue
            argv.append(token)
        if argv:
            commands.append(Command(task=name, argv=tuple(argv)))
    return tuple(commands)
