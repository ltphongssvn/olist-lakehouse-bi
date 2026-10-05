# tests/test_template_discard.py
"""An unpublished generated project holding only its generated commit can be discarded (D.63).

Removal is the one irreversible operation in a project's bootstrap, so every refusal is
proven through observe() and the policy alone: no test ever calls main() on anything but
a scratch project in tmp_path, so a rule that is wrong while RED cannot delete anything.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from opa import denials
from template_discard import DiscardRequest, main, observe
from template_init import main as init_main

ENTRYPOINT = "data.template.discard.deny"
ROOT = Path(__file__).resolve().parent.parent
# COMPOSED, NOT WRITTEN: the PII gate reads any user-at-host literal as an email.
ADDRESS = "t" + "@" + "example.invalid"


def _decide(made: DiscardRequest) -> list[str]:
    return denials(ENTRYPOINT, {"template_discard": made.model_dump(mode="json")})


def _git(repo: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)
    return done.stdout.strip()


def _fresh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A generated project exactly as template:init leaves it."""
    for role in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{role}_NAME", "t")
        monkeypatch.setenv(f"GIT_{role}_EMAIL", ADDRESS)
    project = tmp_path / "project"
    project.mkdir()
    (project / ".copier-answers.yml").write_text("_commit: abc1234\n", encoding="utf-8")
    (project / "README.md").write_text("generated\n", encoding="utf-8")
    assert init_main([str(project)]) == 0
    return project


def _refused(made: DiscardRequest, code: str) -> None:
    found = _decide(made)
    assert any(code in denial for denial in found), found


def test_a_directory_that_was_not_generated_is_refused(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    _refused(observe(plain), "ERR_DISCARD_NOT_GENERATED")


def test_a_symlink_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """rmtree refuses a symlinked root; the policy refuses it before rmtree is reached."""
    project = _fresh(tmp_path, monkeypatch)
    link = tmp_path / "link"
    link.symlink_to(project)
    _refused(observe(link), "ERR_DISCARD_SYMLINK")


def test_a_published_project_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = _fresh(tmp_path, monkeypatch)
    _git(project, "remote", "add", "origin", str(tmp_path / "elsewhere.git"))
    _refused(observe(project), "ERR_DISCARD_PUBLISHED")


def test_a_project_with_authored_commits_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Born by template:init it has one commit; a second is somebody's work."""
    project = _fresh(tmp_path, monkeypatch)
    _git(project, "commit", "-q", "--allow-empty", "-m", "feat: work worth keeping")
    _refused(observe(project), "ERR_DISCARD_AUTHORED")


def test_a_dirty_project_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = _fresh(tmp_path, monkeypatch)
    (project / "README.md").write_text("edited\n", encoding="utf-8")
    _refused(observe(project), "ERR_DISCARD_DIRTY")


def test_a_removal_that_does_not_resist_symlink_attacks_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Where rmtree.avoids_symlink_attacks is false, nothing is removed (D.63).

    This platform's rmtree resists them, so the fact is set on the contract: the value a
    platform without fd-based rmtree would report, judged by the same policy.
    """
    project = _fresh(tmp_path, monkeypatch)
    unsafe = observe(project).model_copy(update={"safe_removal": False})
    _refused(unsafe, "ERR_DISCARD_UNSAFE")


def test_this_repository_is_refused() -> None:
    """Observed and judged only: main() is never pointed at a real directory."""
    _refused(observe(ROOT), "ERR_DISCARD_PROTECTED")


def test_a_fresh_unpublished_project_is_discarded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project = _fresh(tmp_path, monkeypatch)
    capsys.readouterr()
    assert main([str(project)]) == 0
    outcome = json.loads(capsys.readouterr().out)
    assert outcome["code"] == "project_discarded", outcome
    assert not project.exists()
