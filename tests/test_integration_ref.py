# tests/test_integration_ref.py
"""The integration branch resolves in any checkout, or refuses (D.16's CI failure).

WHAT BROKE. gather ran `git for-each-ref --merged develop`, naming the LOCAL
branch. A pull-request checkout in CI has origin/develop and no local develop,
so CI failed with "malformed object name develop" -- the first time gather ran
there. 2026 practice: verify the ref with rev-parse --verify, peeled to a commit,
and fall back to origin/<branch>; refuse when neither exists.

A REAL REPOSITORY, BUILT LOCALLY: git init in a temporary directory, no network.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from repo_state import integration_ref


def _repo(tmp_path: Path) -> Path:
    def run(*args: str) -> None:
        subprocess.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )

    run("init", "-q", "-b", "feature")
    run("commit", "-q", "--allow-empty", "-m", "start")
    return tmp_path


def _ref(repo: Path, name: str) -> None:
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    subprocess.run(["git", "update-ref", name, head], cwd=repo, check=True)


def test_a_ci_checkout_resolves_to_the_remote_branch(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _ref(repo, "refs/remotes/origin/develop")
    assert integration_ref(repo) == "refs/remotes/origin/develop"


def test_a_local_branch_is_preferred(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _ref(repo, "refs/remotes/origin/develop")
    _ref(repo, "refs/heads/develop")
    assert integration_ref(repo) == "refs/heads/develop"


def test_a_checkout_with_neither_refuses(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="develop"):
        integration_ref(_repo(tmp_path))
