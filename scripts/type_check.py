"""type-check/v1: what mypy is configured to check, and every place it is invoked.

THE FILE SET WAS WRITTEN TWICE -- `scripts` in the types task, `scripts tests`
in the gate -- so the task reported success over errors the gate refused. It is
declared once now, in pyproject.toml, and this records every mypy invocation so
the policy can refuse any that names paths: a path on the command line overrides
the configured files, leaving the declaration looking like a control while
governing nothing.

THE COMMANDS COME FROM invocations.py, filtered here to mypy, so the shape of an
invocation is defined once for every policy that reads one.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict

from invocations import Invocation
from invocations import observe as observe_invocations

ROOT = Path(__file__).resolve().parent.parent


class TypeCheck(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    CONTRACT_ID: ClassVar[str] = "type-check/v1"

    contract: Literal["type-check/v1"] = "type-check/v1"
    # OBSERVED, NOT REQUIRED: whether an empty set is acceptable is the
    # policy's decision, so the contract records what it found.
    files: tuple[str, ...]
    invocations: tuple[Invocation, ...]


class _Mypy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")
    files: tuple[str, ...] = ()


class _Tool(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")
    mypy: _Mypy = _Mypy()


class _Pyproject(BaseModel):
    """The one part of pyproject.toml this reads."""

    model_config = ConfigDict(frozen=True, extra="ignore")
    tool: _Tool = _Tool()


def observe(root: Path = ROOT) -> TypeCheck:
    """The configured files, and every mypy invocation in the tasks and the gate."""
    text = (root / "pyproject.toml").read_text(encoding="utf-8")
    files = _Pyproject.model_validate(tomllib.loads(text)).tool.mypy.files
    mypy = tuple(i for i in observe_invocations(root).invocations if "mypy" in i.argv)
    return TypeCheck(files=files, invocations=mypy)
