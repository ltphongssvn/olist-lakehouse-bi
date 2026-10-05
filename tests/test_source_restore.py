# tests/test_source_restore.py
"""A file's changes are discarded by a task that refuses untracked paths (D.34).

GROUNDED. `git restore --staged --worktree --source=HEAD -- <paths>` resets both the
index and the working tree to HEAD, and replaces `git checkout --`. It acts on
tracked files only -- and on a path HEAD has never seen it DROPS the file, so such
a path is refused. Without --yes it reports what it would restore and changes nothing.

A REAL REPOSITORY, BUILT LOCALLY: C.20's isolation keeps these git calls off this one.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from source_restore import main

COMMITTED = "committed\n"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def _repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "f.txt").write_text(COMMITTED, encoding="utf-8")
    _git(tmp_path, "add", "f.txt")
    _git(tmp_path, "commit", "-q", "-m", "start")
    return tmp_path


def test_an_untracked_path_is_refused(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "new.txt").write_text("not in HEAD\n", encoding="utf-8")
    assert main(["--yes", "new.txt"], root=repo) == 2
    assert (repo / "new.txt").exists(), "a path HEAD never saw must not be dropped"


def test_a_dry_run_changes_nothing(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "f.txt").write_text("edited\n", encoding="utf-8")
    assert main(["f.txt"], root=repo) == 0
    assert (repo / "f.txt").read_text(encoding="utf-8") == "edited\n"


def test_a_changed_file_is_restored_with_yes(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "f.txt").write_text("edited\n", encoding="utf-8")
    _git(repo, "add", "f.txt")
    assert main(["--yes", "f.txt"], root=repo) == 0
    assert (repo / "f.txt").read_text(encoding="utf-8") == COMMITTED
    assert _git(repo, "status", "--porcelain") == ""


def test_naming_no_path_is_refused(tmp_path: Path) -> None:
    assert main(["--yes"], root=_repo(tmp_path)) == 2
