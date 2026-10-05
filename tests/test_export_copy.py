# tests/test_export_copy.py
"""A released export is copied out by a task, verified and recorded (D.21).

THE PAIR. export-copy/v1 records the assignment, its release tag, the source and
destination and both digests; export.copy refuses an unreleased assignment, a
missing export, an existing destination, and a copy whose digest differs. The
copy is named for its tag, so a released file cannot be confused with a draft.

REAL GIT, REAL FILES: each test builds a throwaway repository and Downloads folder.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from pydantic import JsonValue

from export_copy import ExportCopy, main

HTML = "<html><body>assignment 02</body></html>\n"


def _repo(tmp_path: Path, *tags: str) -> Path:
    repo = tmp_path / "repo"
    exports = repo / "assignments" / "assignment-02" / "exports"
    exports.mkdir(parents=True)
    (exports / "assignment_02_etl.html").write_text(HTML, encoding="utf-8")

    def git(*args: str) -> None:
        subprocess.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
            cwd=repo,
            check=True,
            capture_output=True,
        )

    git("init", "-q", "-b", "main")
    git("commit", "-q", "--allow-empty", "-m", "start")
    for tag in tags:
        git("tag", tag)
    return repo


def _downloads(tmp_path: Path) -> Path:
    folder = tmp_path / "Downloads"
    folder.mkdir()
    return folder


def test_a_released_export_is_copied_and_verified(tmp_path: Path) -> None:
    repo, downloads = _repo(tmp_path, "assignment-02-v1"), _downloads(tmp_path)
    assert main(["assignment-02"], root=repo, downloads=downloads) == 0
    copied = downloads / "assignment_02_etl_assignment-02-v1.html"
    assert copied.read_text(encoding="utf-8") == HTML


def test_an_unreleased_export_is_refused(tmp_path: Path) -> None:
    repo, downloads = _repo(tmp_path), _downloads(tmp_path)
    assert main(["assignment-02"], root=repo, downloads=downloads) == 2
    assert list(downloads.iterdir()) == []


def test_an_existing_destination_is_never_overwritten(tmp_path: Path) -> None:
    repo, downloads = _repo(tmp_path, "assignment-02-v1"), _downloads(tmp_path)
    existing = downloads / "assignment_02_etl_assignment-02-v1.html"
    existing.write_text("an earlier copy\n", encoding="utf-8")
    assert main(["assignment-02"], root=repo, downloads=downloads) == 2
    assert existing.read_text(encoding="utf-8") == "an earlier copy\n"


def test_the_newest_release_is_copied(tmp_path: Path) -> None:
    repo, downloads = _repo(tmp_path, "assignment-02-v1", "assignment-02-v2"), _downloads(tmp_path)
    assert main(["assignment-02"], root=repo, downloads=downloads) == 0
    assert (downloads / "assignment_02_etl_assignment-02-v2.html").exists()


def _denied(copy: ExportCopy) -> list[str]:
    from opa import denials

    payload: dict[str, JsonValue] = {"export_copy": copy.model_dump(mode="json")}
    return [d for d in denials("data.export.copy.deny", payload) if d.startswith("[ERR_EXPORT_")]


def test_the_policy_refuses_a_mismatched_copy(tmp_path: Path) -> None:
    base = {
        "assignment": "assignment-02",
        "tag": "assignment-02-v1",
        "source": "assignments/assignment-02/exports/assignment_02_etl.html",
        "destination": str(tmp_path / "Downloads" / "assignment_02_etl_assignment-02-v1.html"),
        "source_exists": True,
        "destination_existed": False,
        "source_sha256": "a" * 64,
    }
    mismatched = ExportCopy.model_validate({**base, "copy_sha256": "b" * 64})
    assert any(d.startswith("[ERR_EXPORT_COPY_MISMATCH]") for d in _denied(mismatched))
    matching = ExportCopy.model_validate({**base, "copy_sha256": "a" * 64})
    assert _denied(matching) == []
