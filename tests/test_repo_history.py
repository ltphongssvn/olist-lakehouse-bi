# tests/test_repo_history.py
"""Commit history is read by a task, as data (D.29).

GROUNDED. git's own %(trailers) takes key_value_separator and separator, which "make it
trivial to produce machine-readable (\0-delimited) output"; fields are NUL-separated
and each record opened by its own separator byte, and a commit's files come from
`git show --name-only -z`, so no subject or path can break the parse.

A REAL REPOSITORY, BUILT LOCALLY: C.20's isolation keeps these git calls off this one.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from repo_history import history, main


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def _repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "a.txt").write_text("a\n", encoding="utf-8")
    _git(tmp_path, "add", "a.txt")
    _git(tmp_path, "commit", "-q", "-m", "start")
    (tmp_path / "b c.txt").write_text("b\n", encoding="utf-8")
    _git(tmp_path, "add", "b c.txt")
    _git(
        tmp_path,
        "commit",
        "-q",
        "-m",
        "feat: add b",
        "-m",
        "A body line.",
        "-m",
        "Plan-Step: D.12\nPlan-Step: D.13",
    )
    return tmp_path


def test_commits_come_back_with_subjects_trailers_and_files(tmp_path: Path) -> None:
    commits = history(_repo(tmp_path), "HEAD", 10).commits
    assert [c.subject for c in commits] == ["feat: add b", "start"]
    assert [(t.key, t.value) for t in commits[0].trailers] == [
        ("Plan-Step", "D.12"),
        ("Plan-Step", "D.13"),
    ]
    assert commits[0].files == ("b c.txt",)
    assert (commits[1].trailers, commits[1].files) == ((), ("a.txt",))


def test_a_merge_lists_the_files_it_brought_in(tmp_path: Path) -> None:
    """Git shows no files for a merge by default; first-parent shows what it brought in."""
    _git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "base.txt").write_text("base\n", encoding="utf-8")
    _git(tmp_path, "add", "base.txt")
    _git(tmp_path, "commit", "-q", "-m", "base")
    _git(tmp_path, "switch", "-q", "-c", "side")
    (tmp_path / "side.txt").write_text("side\n", encoding="utf-8")
    _git(tmp_path, "add", "side.txt")
    _git(tmp_path, "commit", "-q", "-m", "side")
    _git(tmp_path, "switch", "-q", "main")
    _git(tmp_path, "merge", "-q", "--no-ff", "-m", "merge side", "side")
    merge = history(tmp_path, "HEAD", 1).commits[0]
    assert (merge.subject, merge.files) == ("merge side", ("side.txt",))


def test_the_limit_is_respected(tmp_path: Path) -> None:
    assert len(history(_repo(tmp_path), "HEAD", 1).commits) == 1


def test_an_unknown_revision_is_refused() -> None:
    assert main(["no-such-revision-anywhere"]) == 2
