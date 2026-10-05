# tests/test_git_isolation.py
"""No test can act on the repository a git hook names (C.20).

WHAT HAPPENED. Under the pre-push hook, git exported GIT_DIR, and it overrides any
cwd or -C: a test's throwaway git init, commit and update-ref landed on this
repository and moved develop, origin/develop and a feature branch.

THE PAIR. git-isolation/v1 records which of git's repository-local variables --
git's own list, from rev-parse --local-env-vars -- the session holds;
machine.testing decides that none may; conftest removes what the policy names,
asks again, and stops the session on any leak. These tests prove it bites.

THE PROOF IS OUTSIDE-IN: the suite's real git-shelling tests, run with GIT_DIR
aimed at a sentinel repository, must pass and leave the sentinel untouched.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from pydantic import JsonValue

ROOT = Path(__file__).resolve().parent.parent


def _clean_env() -> dict[str, str]:
    return {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
        cwd=repo,
        env=_clean_env(),
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def _state(repo: Path) -> tuple[str, str]:
    refs = _git(repo, "for-each-ref", "--format=%(refname) %(objectname)")
    return refs, _git(repo, "config", "--get", "core.bare").strip()


def test_a_hooks_git_dir_cannot_reach_the_suite(tmp_path: Path) -> None:
    sentinel = tmp_path / "sentinel"
    sentinel.mkdir()
    _git(sentinel, "init", "-q", "-b", "sentinel")
    _git(sentinel, "commit", "-q", "--allow-empty", "-m", "sentinel")
    before = _state(sentinel)

    hooked = {
        **_clean_env(),
        "GIT_DIR": str(sentinel / ".git"),
        "GIT_INDEX_FILE": str(sentinel / ".git" / "index"),
    }
    child = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "tests/test_integration_ref.py",
        ],
        cwd=ROOT,
        env=hooked,
        capture_output=True,
        text=True,
        check=False,
    )
    assert _state(sentinel) == before, "a test acted on the repository GIT_DIR named"
    assert child.returncode == 0, child.stdout[-2000:]


def test_the_variables_are_gits_own_list() -> None:
    from git_isolation import local_variables

    names = local_variables()
    assert "GIT_DIR" in names and "GIT_INDEX_FILE" in names


def _denied(observation: dict[str, JsonValue] | None) -> list[str]:
    from opa import denials

    payload: dict[str, JsonValue] = {} if observation is None else {"git_isolation": observation}
    return [d for d in denials("data.machine.testing.deny", payload) if d.startswith("[ERR_TEST_")]


def test_the_policy_refuses_a_leak() -> None:
    from git_isolation import GitIsolation

    leak = GitIsolation(local_variables=("GIT_DIR", "GIT_INDEX_FILE"), present=("GIT_DIR",))
    denied = _denied(leak.model_dump(mode="json"))
    assert any(d.startswith("[ERR_TEST_GIT_ENV_LEAKED]") for d in denied), denied


def test_the_policy_allows_a_clean_environment() -> None:
    """THE CONTROL: a policy refusing everything would pass the rest."""
    from git_isolation import GitIsolation

    clean = GitIsolation(local_variables=("GIT_DIR", "GIT_INDEX_FILE"), present=())
    assert _denied(clean.model_dump(mode="json")) == []


def test_an_absent_observation_is_refused() -> None:
    assert any(d.startswith("[ERR_TEST_GIT_ENV_UNOBSERVED]") for d in _denied(None))


def test_isolate_removes_only_what_the_policy_names() -> None:
    from git_isolation import isolate

    environ = {"GIT_DIR": "/elsewhere/.git", "GIT_AUTHOR_NAME": "a", "PATH": "/bin"}
    after = isolate(environ)
    assert "GIT_DIR" not in environ
    assert environ["PATH"] == "/bin" and environ["GIT_AUTHOR_NAME"] == "a"
    assert after.present == ()
