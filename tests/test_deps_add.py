# tests/test_deps_add.py
"""A dependency is added by a task, with its lock (D.32).

GROUNDED. `uv add` updates pyproject.toml and uv.lock together; `uv lock --check`
then confirms the lock matches. uv never treats a lock as outdated because new
versions were released -- upgrading is a separate, explicit act -- so ADDING a
package must not change any package already locked.

THE PAIR. deps-change/v1 records the package, whether it landed, its locked version
and the lock diff; deps.add refuses a stale lock, a package that did not land, and
any already-locked package changed or removed. A refusal restores both files.

ONLY `uv` IS STUBBED: a fake `uv add` rewrites the throwaway project's files the
way the real one would; reading them, the diff, opa's decision and the rollback
are real.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from deps_add import main

PYPROJECT = '[project]\nname = "demo"\nversion = "0"\ndependencies = ["pydantic>=2"]\n'
LOCK = 'version = 1\n\n[[package]]\nname = "pydantic"\nversion = "2.13.5"\n'
ADDED_PYPROJECT = (
    '[project]\nname = "demo"\nversion = "0"\ndependencies = ["pydantic>=2", "tomlkit>=0.13.3"]\n'
)
ADDED_LOCK = LOCK + '\n[[package]]\nname = "tomlkit"\nversion = "0.13.3"\n'
_REAL_RUN = subprocess.run


def _project(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    (tmp_path / "uv.lock").write_text(LOCK, encoding="utf-8")
    return tmp_path


def _uv(monkeypatch: pytest.MonkeyPatch, root: Path, *, lock: str, check: int) -> list[list[str]]:
    seen: list[list[str]] = []

    def run(command: list[str], **kwargs: object) -> object:
        if command[:1] == ["uv"]:
            seen.append(command)
            if command[1:2] == ["add"]:
                (root / "pyproject.toml").write_text(ADDED_PYPROJECT, encoding="utf-8")
                (root / "uv.lock").write_text(lock, encoding="utf-8")
                return subprocess.CompletedProcess(command, 0, "", "")
            return subprocess.CompletedProcess(command, check, "", "lock outdated" if check else "")
        given = kwargs.get("input")
        return _REAL_RUN(
            command,
            input=given if isinstance(given, str) else None,
            capture_output=True,
            text=True,
            check=False,
        )

    monkeypatch.setattr(subprocess, "run", run)
    return seen


def test_a_package_is_added_with_its_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _project(tmp_path)
    _uv(monkeypatch, root, lock=ADDED_LOCK, check=0)
    assert main(["tomlkit"], root=root) == 0
    envelope = json.loads(capsys.readouterr().out)
    assert envelope["code"] == "dependency_added"
    assert (envelope["data"]["landed"], envelope["data"]["locked_version"]) == (True, "0.13.3")


def test_a_stale_lock_is_refused_and_rolled_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _project(tmp_path)
    _uv(monkeypatch, root, lock=ADDED_LOCK, check=1)
    assert main(["tomlkit"], root=root) == 2
    assert (root / "pyproject.toml").read_text(encoding="utf-8") == PYPROJECT
    assert (root / "uv.lock").read_text(encoding="utf-8") == LOCK


def test_an_existing_package_changed_is_refused_and_rolled_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _project(tmp_path)
    bumped = ADDED_LOCK.replace('version = "2.13.5"', 'version = "2.13.6"')
    _uv(monkeypatch, root, lock=bumped, check=0)
    assert main(["tomlkit"], root=root) == 2
    assert (root / "uv.lock").read_text(encoding="utf-8") == LOCK


def test_a_group_reaches_uv_add(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _project(tmp_path)
    seen = _uv(monkeypatch, root, lock=ADDED_LOCK, check=0)
    main(["tomlkit", "--group", "dev"], root=root)
    assert ["uv", "add", "--group", "dev", "tomlkit"] in seen
