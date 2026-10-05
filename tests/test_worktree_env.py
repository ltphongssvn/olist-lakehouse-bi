# tests/test_worktree_env.py
"""A worktree's setup never inherits another checkout's virtual environment (D.12).

WHAT HAPPENED. worktree:add ran `mise run setup` in the new worktree with the
caller's whole environment, so uv saw VIRTUAL_ENV pointing at the main checkout's
.venv and warned on every worktree. 2026 practice: uv is not run FROM an
environment, it manages one -- never pass the caller's VIRTUAL_ENV, and clear
UV_PROJECT_ENVIRONMENT too; a clean environment, not a suppressed warning.

THE PAIR. setup-environment/v1 records which of uv's environment-selecting
variables setup would inherit; machine.setup decides none may.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from pydantic import JsonValue

import worktree

_REAL_RUN = subprocess.run
SELECTING = ("UV_PROJECT_ENVIRONMENT", "VIRTUAL_ENV")


def test_setup_runs_without_the_callers_virtual_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VIRTUAL_ENV", "/elsewhere/.venv")
    monkeypatch.setenv("UV_PROJECT_ENVIRONMENT", "/elsewhere/env")
    monkeypatch.setattr(worktree, "_git", lambda *args, **kwargs: "")
    monkeypatch.setattr(worktree, "sibling_path", lambda slug: tmp_path / slug)
    given: dict[str, object] = {}

    def run(command: list[str], **kwargs: object) -> object:
        if command[:1] == ["mise"]:
            given[" ".join(command)] = kwargs.get("env")
            return subprocess.CompletedProcess(command, 0, "", "")
        stdin = kwargs.get("input")
        return _REAL_RUN(
            command,
            input=stdin if isinstance(stdin, str) else None,
            capture_output=True,
            text=True,
            check=False,
        )

    monkeypatch.setattr(subprocess, "run", run)
    assert worktree.cmd_add("probe") == 0
    assert set(given) == {"mise trust", "mise run setup"}
    for command, env in given.items():
        assert isinstance(env, dict), f"{command} inherited the caller's whole environment"
        assert not set(SELECTING) & set(env), f"{command} received {set(SELECTING) & set(env)}"
        assert env.get("PATH") == os.environ["PATH"]


def _denied(observation: dict[str, JsonValue] | None) -> list[str]:
    from opa import denials

    payload: dict[str, JsonValue] = (
        {} if observation is None else {"setup_environment": observation}
    )
    return [d for d in denials("data.machine.setup.deny", payload) if d.startswith("[ERR_SETUP_")]


def test_the_policy_refuses_an_inherited_environment() -> None:
    from setup_env import SetupEnvironment

    leak = SetupEnvironment(selecting_variables=SELECTING, present=("VIRTUAL_ENV",))
    assert any(
        d.startswith("[ERR_SETUP_ENV_INHERITED]") for d in _denied(leak.model_dump(mode="json"))
    )


def test_the_policy_allows_a_clean_environment() -> None:
    """THE CONTROL: a policy refusing everything would pass the rest."""
    from setup_env import SetupEnvironment

    clean = SetupEnvironment(selecting_variables=SELECTING, present=())
    assert _denied(clean.model_dump(mode="json")) == []


def test_an_absent_observation_is_refused() -> None:
    assert any(d.startswith("[ERR_SETUP_ENV_UNOBSERVED]") for d in _denied(None))


def test_only_uvs_selecting_variables_are_removed() -> None:
    from setup_env import setup_environment

    caller = {
        "VIRTUAL_ENV": "/x",
        "UV_PROJECT_ENVIRONMENT": "/y",
        "PATH": "/bin",
        "UV_CACHE_DIR": "/c",
    }
    assert setup_environment(caller) == {"PATH": "/bin", "UV_CACHE_DIR": "/c"}
    assert "VIRTUAL_ENV" in caller, "the caller's own mapping must be left untouched"
