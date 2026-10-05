# scripts/env_sync.py
"""Sync brings the environment to a lock that changed (D.38).

GROUNDED. After pulling changes that touched uv.lock, run uv sync. 2026 practice
asks git which files changed between the old and new commits and syncs only when
the lockfile is among them; --locked fails loudly if the lock disagrees with
pyproject.toml instead of silently re-resolving.

THE PAIR. environment-sync/v1 records whether the lock changed, whether the
environment was brought to it and the install's exit code; machine.environment
refuses a stale environment, so sync fails rather than leave .venv behind its lock.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict

from gitenv import git
from opa import denials


class EnvironmentSync(BaseModel):
    """environment-sync/v1: did the lock change, and does the environment follow it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    CONTRACT_ID: ClassVar[str] = "environment-sync/v1"

    contract: Literal["environment-sync/v1"] = "environment-sync/v1"
    lock_changed: bool
    installed: bool
    install_exit_code: int | None


def follow_lock(root: Path, before: str) -> EnvironmentSync:
    """Install the lock if it changed between `before` and the current HEAD."""
    after = git("rev-parse", "HEAD", cwd=root).stdout.strip()
    changed = before != after and bool(
        git("diff", "--name-only", before, after, "--", "uv.lock", cwd=root).stdout.strip()
    )
    if not changed:
        return EnvironmentSync(lock_changed=False, installed=False, install_exit_code=None)
    result = subprocess.run(["uv", "sync", "--locked"], cwd=root, check=False)
    print(f"environment: uv.lock changed; uv sync --locked exited {result.returncode}")
    return EnvironmentSync(
        lock_changed=True, installed=result.returncode == 0, install_exit_code=result.returncode
    )


def environment_denials(synced: EnvironmentSync) -> list[str]:
    return denials(
        "data.machine.environment.deny", {"environment_sync": synced.model_dump(mode="json")}
    )
