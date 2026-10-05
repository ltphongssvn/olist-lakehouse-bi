"""hooks/v1: what the git hooks run, read as lefthook reads its own configuration.

LEFTHOOK RE-SYNCS HOOKS ITSELF while auto-install is on, which is how a new
commit-msg hook reached every checkout without anyone re-running setup. This
records whether that stays enabled and what each hook runs, so the policy can
refuse a configuration that would let hooks silently stop arriving -- or that
drops the commit-msg job running plan:trailers.

THROUGH `lefthook dump`, NOT A YAML PARSE OF OUR OWN: lefthook merges local
overrides and remotes, and omits defaults, so its view is the one that runs.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter

ROOT = Path(__file__).resolve().parent.parent
DUMP = TypeAdapter(dict[str, JsonValue])

# THE KEYS THAT ARE HOOKS, by git's own names; everything else at the top level
# of a dump is a setting.
GIT_HOOKS = frozenset(
    {
        "applypatch-msg",
        "pre-applypatch",
        "post-applypatch",
        "pre-commit",
        "pre-merge-commit",
        "prepare-commit-msg",
        "commit-msg",
        "post-commit",
        "pre-rebase",
        "post-checkout",
        "post-merge",
        "pre-push",
        "post-rewrite",
        "reference-transaction",
        "push-to-checkout",
        "pre-auto-gc",
    }
)


class HookJob(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    hook: str = Field(min_length=1)
    name: str
    run: str


class Hooks(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    CONTRACT_ID: ClassVar[str] = "hooks/v1"

    contract: Literal["hooks/v1"] = "hooks/v1"
    auto_install: bool
    jobs: tuple[HookJob, ...]


class _Job(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")
    name: str = ""
    run: str = ""


class _Hook(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")
    jobs: tuple[_Job, ...] = ()


def from_dump(text: str) -> Hooks:
    """hooks/v1 from `lefthook dump --format json`, which omits every default."""
    dump = DUMP.validate_json(text)
    jobs = tuple(
        HookJob(hook=hook, name=job.name, run=job.run)
        for hook, value in dump.items()
        if hook in GIT_HOOKS and isinstance(value, dict)
        for job in _Hook.model_validate(value).jobs
    )
    return Hooks(auto_install=dump.get("no_auto_install") is not True, jobs=jobs)


def observe(root: Path = ROOT) -> Hooks:
    """The merged configuration lefthook would run, read from lefthook itself."""
    result = subprocess.run(
        ["lefthook", "dump", "--format", "json"],
        capture_output=True,
        text=True,
        check=False,
        cwd=root,
    )
    if result.returncode != 0:
        raise SystemExit(f"lefthook dump failed: {result.stderr.strip()}")
    return from_dump(result.stdout)
