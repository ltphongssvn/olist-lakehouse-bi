# tests/test_source_search.py
"""Code is searched by a task, its matches as data (D.27).

GROUNDED. `git grep -n -z` separates path, line number and text with NUL bytes, so
paths containing colons are unambiguous; a CRLF line's trailing carriage return is
stripped; --full-name gives paths from the repository root. It searches tracked
files only, and exit code 1 means no match -- an empty result, not an error.

A REAL REPOSITORY, BUILT LOCALLY: C.20's isolation keeps these git calls off this one.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from source_search import search


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def _repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "a.py").write_text("x = 1\nneedle = 2\n", encoding="utf-8")
    (tmp_path / "odd:name.txt").write_text("a needle here\n", encoding="utf-8")
    (tmp_path / "crlf.txt").write_bytes(b"needle\r\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "start")
    (tmp_path / "untracked.txt").write_text("needle\n", encoding="utf-8")
    return tmp_path


def test_matches_come_back_as_data(tmp_path: Path) -> None:
    found = search(_repo(tmp_path), "needle", ())
    assert ("a.py", 2, "needle = 2") in [(m.path, m.number, m.text) for m in found.matches]
    assert found.count == len(found.matches) == 3


def test_a_path_containing_a_colon_parses(tmp_path: Path) -> None:
    found = search(_repo(tmp_path), "needle", ())
    assert ("odd:name.txt", 1, "a needle here") in [
        (m.path, m.number, m.text) for m in found.matches
    ]


def test_an_untracked_file_is_not_searched(tmp_path: Path) -> None:
    assert "untracked.txt" not in {m.path for m in search(_repo(tmp_path), "needle", ()).matches}


def test_a_crlf_carriage_return_is_stripped(tmp_path: Path) -> None:
    found = search(_repo(tmp_path), "needle", ("crlf.txt",))
    assert [m.text for m in found.matches] == ["needle"]


def test_no_match_is_an_empty_result(tmp_path: Path) -> None:
    found = search(_repo(tmp_path), "no-such-thing", ())
    assert (found.count, found.matches) == (0, ())
