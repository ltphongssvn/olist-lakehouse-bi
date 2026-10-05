# tests/test_sync_environment.py
"""Sync brings the environment to a lock that changed (D.38).

GROUNDED. After pulling changes that touched uv.lock, run uv sync -- 2026 practice
checks which files changed between the old and new commits and syncs only when the
lockfile is among them, with --locked so a lock out of step with pyproject fails.

THE PAIR. environment-sync/v1 records whether the lock changed and whether the
environment was brought to it; machine.environment refuses a stale environment.

A REAL REPOSITORY; ONLY `uv` IS STUBBED. Other calls run for real, with their own cwd
and env -- gitenv scrubs the environment and names the directory.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from pydantic import JsonValue

from env_sync import EnvironmentSync, follow_lock

_REAL_RUN = subprocess.run


def _git(repo: Path, *args: str) -> str:
    return _REAL_RUN(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _repo(tmp_path: Path, second: str) -> tuple[Path, str]:
    _git(tmp_path, "init", "-q", "-b", "develop")
    (tmp_path / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("a\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "first")
    before = _git(tmp_path, "rev-parse", "HEAD")
    (tmp_path / second).write_text("changed\n", encoding="utf-8")
    _git(tmp_path, "commit", "-q", "-am", "second")
    return tmp_path, before


def _uv(monkeypatch: pytest.MonkeyPatch, code: int) -> list[list[str]]:
    seen: list[list[str]] = []

    def run(command: list[str], **kwargs: object) -> object:
        if command[:1] == ["uv"]:
            seen.append(command)
            return subprocess.CompletedProcess(command, code, "", "")
        given, cwd, env = kwargs.get("input"), kwargs.get("cwd"), kwargs.get("env")
        return _REAL_RUN(
            command,
            input=given if isinstance(given, str) else None,
            capture_output=True,
            text=True,
            check=False,
            cwd=cwd if isinstance(cwd, (str, Path)) else None,
            env=env if isinstance(env, dict) else None,
        )

    monkeypatch.setattr(subprocess, "run", run)
    return seen


def _denied(observation: EnvironmentSync | None) -> list[str]:
    from opa import denials

    payload: dict[str, JsonValue] = (
        {} if observation is None else {"environment_sync": observation.model_dump(mode="json")}
    )
    return [
        d for d in denials("data.machine.environment.deny", payload) if d.startswith("[ERR_ENV_")
    ]


def test_a_changed_lock_is_installed_by_sync(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, before = _repo(tmp_path, "uv.lock")
    seen = _uv(monkeypatch, 0)
    synced = follow_lock(repo, before)
    assert (synced.lock_changed, synced.installed) == (True, True)
    assert seen == [["uv", "sync", "--locked"]]
    assert _denied(synced) == []


def test_an_unchanged_lock_installs_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, before = _repo(tmp_path, "notes.txt")
    seen = _uv(monkeypatch, 0)
    synced = follow_lock(repo, before)
    assert (synced.lock_changed, synced.installed, seen) == (False, False, [])


def test_a_failed_install_is_refused_by_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, before = _repo(tmp_path, "uv.lock")
    _uv(monkeypatch, 1)
    synced = follow_lock(repo, before)
    assert any(d.startswith("[ERR_ENV_STALE]") for d in _denied(synced))


def test_an_absent_observation_is_refused() -> None:
    assert any(d.startswith("[ERR_ENV_UNOBSERVED]") for d in _denied(None))
