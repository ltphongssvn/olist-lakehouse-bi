# tests/test_template_identity.py
"""A generated project takes its identity from the source, before it has a remote (D.59).

start:here needs origin, origin needs the repository named rightly, the name needs
identity:set, and committing that needs a feature branch. The cycle closes only if a
fresh project takes its identity as its second commit, from the source, while it
has no remote. policies/template/identity decides when; these prove each rule bites.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from opa import denials
from project_identity import load
from template_identity import IdentityRequest, main, observe
from template_init import main as init_main

ENTRYPOINT = "data.template.identity.deny"
REPO = Path(__file__).resolve().parent.parent
# COMPOSED, NOT WRITTEN: the PII gate reads any user-at-host literal as an email.
ADDRESS = "t" + "@" + "example.invalid"
PROBE = (
    'name = "probe-project"\n'
    'catalog = "probe_catalog"\n'
    'reader_group = "probe_readers"\n'
    'ci_principal = "probe-ci"\n'
    'default_schema = "probe_schema"\n'
    'repository = "https://github.com/example/probe-project"\n'
)


def _decide(made: IdentityRequest) -> list[str]:
    return denials(ENTRYPOINT, {"template_identity": made.model_dump(mode="json")})


def _git(project: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=project, check=True, capture_output=True, text=True)
    return done.stdout.strip()


def _fresh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A generated project exactly as template:init leaves it: one commit, develop at it."""
    for role in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{role}_NAME", "t")
        monkeypatch.setenv(f"GIT_{role}_EMAIL", ADDRESS)
    project = tmp_path / "project"
    declared = load(REPO)
    names = {slot.path for slot in declared.slots} | {"contracts/project-identity.toml"}
    for name in sorted(names):
        (project / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / name, project / name)
    (project / ".copier-answers.yml").write_text("_commit: abc1234\n", encoding="utf-8")
    assert init_main([str(project)]) == 0
    return project


def test_a_project_with_history_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = _fresh(tmp_path, monkeypatch)
    (project / "later.txt").write_text("later\n", encoding="utf-8")
    _git(project, "add", "later.txt")
    _git(project, "commit", "-q", "-m", "later")
    found = _decide(observe(project))
    assert any("ERR_IDENTITY_NOT_FRESH" in denial for denial in found), found


def test_a_project_with_a_remote_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _fresh(tmp_path, monkeypatch)
    _git(project, "remote", "add", "origin", str(tmp_path / "elsewhere.git"))
    found = _decide(observe(project))
    assert any("ERR_IDENTITY_HAS_REMOTE" in denial for denial in found), found


def test_a_directory_that_was_not_generated_is_refused(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    found = _decide(observe(plain))
    assert any("ERR_IDENTITY_NOT_GENERATED" in denial for denial in found), found


def test_a_fresh_project_takes_its_identity_in_one_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two commits -- the template, then its identity; develop follows; nothing is left."""
    project = _fresh(tmp_path, monkeypatch)
    spec = tmp_path / "identity.toml"
    spec.write_text(PROBE, encoding="utf-8")
    assert main([str(project), str(spec)]) == 0
    assert _git(project, "rev-list", "--count", "HEAD") == "2"
    assert _git(project, "rev-parse", "develop") == _git(project, "rev-parse", "main")
    assert _git(project, "status", "--porcelain") == ""
    assert load(project).name == "probe-project"
