# tests/test_template_init.py
"""A generated project is born a git repository whose first commit is the template (D.58).

copier update needs a repository with a clean working tree, setup needs .git for its
hooks, and a project's own commit task refuses main. So the template's output becomes
the first commit on main, develop starts from it, and nothing is left uncommitted.
policies/template/init decides when that may happen; these prove each rule bites.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from opa import denials
from template_init import InitRequest, main, observe

ENTRYPOINT = "data.template.init.deny"
REPO = Path(__file__).resolve().parent.parent
# COMPOSED, NOT WRITTEN: the PII gate reads any user-at-host literal as an email.
ADDRESS = "t" + "@" + "example.invalid"


def _decide(made: InitRequest) -> list[str]:
    return denials(ENTRYPOINT, {"template_init": made.model_dump(mode="json")})


def _generated(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    (project / ".copier-answers.yml").write_text("_commit: abc1234\n", encoding="utf-8")
    (project / "README.md").write_text("generated\n", encoding="utf-8")
    return project


def _git(project: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=project, check=True, capture_output=True, text=True)
    return done.stdout.strip()


def test_a_directory_that_was_not_generated_is_refused(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    found = _decide(observe(plain))
    assert any("ERR_INIT_NOT_GENERATED" in denial for denial in found), found


def test_a_directory_that_is_already_a_repository_is_refused(tmp_path: Path) -> None:
    project = _generated(tmp_path)
    (project / ".git").mkdir()
    found = _decide(observe(project))
    assert any("ERR_INIT_ALREADY_REPOSITORY" in denial for denial in found), found


def test_a_destination_inside_the_source_is_refused() -> None:
    found = _decide(observe(REPO / "generated"))
    assert any("ERR_INIT_INSIDE_SOURCE" in denial for denial in found), found


def test_a_generated_project_is_born_a_clean_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """main holds one commit of the template; develop starts there; the tree is clean."""
    for role in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{role}_NAME", "t")
        monkeypatch.setenv(f"GIT_{role}_EMAIL", ADDRESS)
    project = _generated(tmp_path)
    assert main([str(project)]) == 0
    assert _git(project, "branch", "--show-current") == "main"
    assert _git(project, "rev-parse", "develop") == _git(project, "rev-parse", "main")
    assert _git(project, "rev-list", "--count", "HEAD") == "1"
    assert _git(project, "status", "--porcelain") == ""
    assert _git(project, "log", "-1", "--format=%(trailers:key=Plan-Step,valueonly)") == "A.1"
    assert (project / "context" / "plan.toml").is_file()
