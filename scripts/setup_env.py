# scripts/setup_env.py
"""A worktree's setup never inherits another checkout's virtual environment (D.12).

uv is not run FROM an environment, it manages one: it locates the project's .venv
from the working directory, and an inherited VIRTUAL_ENV -- here, the main
checkout's -- only earns "does not match the project environment path" on every
worktree. 2026 practice is a clean environment, not a suppressed warning:
VIRTUAL_ENV and UV_PROJECT_ENVIRONMENT are removed before uv runs.

THE PAIR. setup-environment/v1 records which of those variables setup would
inherit; machine.setup decides which have leaked and refuses any that remain.
The caller's own environment is never modified -- a new mapping is returned.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from opa import denials, query

SELECTING = ("UV_PROJECT_ENVIRONMENT", "VIRTUAL_ENV")
_NAMES = TypeAdapter(tuple[str, ...])


class SetupEnvironment(BaseModel):
    """setup-environment/v1: uv's environment-selecting variables, and which are present."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    CONTRACT_ID: ClassVar[str] = "setup-environment/v1"

    contract: Literal["setup-environment/v1"] = "setup-environment/v1"
    selecting_variables: tuple[str, ...] = Field(min_length=1)
    present: tuple[str, ...]


def observe(environ: Mapping[str, str]) -> SetupEnvironment:
    present = tuple(sorted(name for name in SELECTING if name in environ))
    return SetupEnvironment(selecting_variables=SELECTING, present=present)


def setup_environment(environ: Mapping[str, str]) -> dict[str, str]:
    """A copy of environ without what machine.setup says leaked, verified clean."""
    before = observe(environ)
    leaked = set(
        _NAMES.validate_python(
            query(
                "data.machine.setup.leaked", {"setup_environment": before.model_dump(mode="json")}
            )
        )
    )
    cleaned = {name: value for name, value in environ.items() if name not in leaked}
    after = observe(cleaned)
    problems = denials(
        "data.machine.setup.deny", {"setup_environment": after.model_dump(mode="json")}
    )
    if problems:
        raise SystemExit("setup would still inherit uv's environment: " + "; ".join(problems))
    return cleaned
