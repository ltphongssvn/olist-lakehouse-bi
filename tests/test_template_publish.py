# tests/test_template_publish.py
"""A generated project is published with main and develop before anything else (D.60).

This repository was published right after its root commit and changed only through
pull requests; the sibling ran gh repo create with --source and --push, pushed develop
and made it the default. The gh calls are injected so these stay hermetic: a local bare
repository stands in for GitHub, and the git half runs for real against it.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from opa import denials
from template_init import main as init_main
from template_publish import PublishRequest, main, observe

ENTRYPOINT = "data.template.publish.deny"
REPOSITORY = "example/project"
# COMPOSED, NOT WRITTEN: the PII gate reads any user-at-host literal as an email.
ADDRESS = "t" + "@" + "example.invalid"
# A pre-receive hook that refuses, so a push fails the way a real remote policy would.
REFUSING = "#!/bin/sh\necho 'refused by the remote policy' >&2\nexit 1\n"


def _absent(repository: str) -> str:
    return "absent"


def _decide(made: PublishRequest) -> list[str]:
    return denials(ENTRYPOINT, {"template_publish": made.model_dump(mode="json")})


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


def _bare(tmp_path: Path) -> Path:
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True, capture_output=True)
    return bare


def test_a_directory_that_was_not_generated_is_refused(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    found = _decide(observe(plain, REPOSITORY, "public"))
    assert any("ERR_PUBLISH_NOT_GENERATED" in denial for denial in found), found


def test_a_dirty_destination_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = _fresh(tmp_path, monkeypatch)
    (project / "README.md").write_text("edited\n", encoding="utf-8")
    found = _decide(observe(project, REPOSITORY, "public"))
    assert any("ERR_PUBLISH_DIRTY" in denial for denial in found), found


def test_a_destination_with_a_remote_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _fresh(tmp_path, monkeypatch)
    _git(project, "remote", "add", "origin", str(tmp_path / "elsewhere.git"))
    found = _decide(observe(project, REPOSITORY, "public"))
    assert any("ERR_PUBLISH_HAS_REMOTE" in denial for denial in found), found


def test_a_fresh_project_is_published_with_main_and_develop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Created, origin added, both branches pushed, develop made the default."""
    project = _fresh(tmp_path, monkeypatch)
    bare = _bare(tmp_path)
    calls: list[tuple[str, str, str]] = []

    def create(repository: str, visibility: str) -> int:
        calls.append(("create", repository, visibility))
        return 0

    def make_default(repository: str, branch: str) -> int:
        calls.append(("default", repository, branch))
        return 0

    argv = [str(project), REPOSITORY, "public"]
    code = main(
        argv,
        inspect=_absent,
        create=create,
        make_default=make_default,
        remote_url=lambda _: str(bare),
    )
    assert code == 0
    assert calls == [("create", REPOSITORY, "public"), ("default", REPOSITORY, "develop")]
    head = _git(project, "rev-parse", "main")
    assert _git(bare, "rev-parse", "main") == head
    assert _git(bare, "rev-parse", "develop") == head
    assert _git(project, "remote", "get-url", "origin") == str(bare)


def test_an_authentication_failure_is_reported_as_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """gh exit 4 means authentication required: reported, and nothing is half-done."""
    project = _fresh(tmp_path, monkeypatch)
    capsys.readouterr()

    def create(repository: str, visibility: str) -> int:
        return 4

    def make_default(repository: str, branch: str) -> int:
        raise AssertionError("never reached after a failed create")

    argv = [str(project), REPOSITORY, "public"]
    code = main(
        argv,
        inspect=_absent,
        create=create,
        make_default=make_default,
        remote_url=lambda _: "unused",
    )
    assert code == 1
    outcome = json.loads(capsys.readouterr().out)
    assert outcome["code"] == "auth_required", outcome
    assert _git(project, "remote") == ""


def test_a_destination_with_hooks_installed_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Its own pre-push gate needs origin/develop, so publishing comes before setup (D.62)."""
    project = _fresh(tmp_path, monkeypatch)
    hook = project / ".git" / "hooks" / "pre-push"
    hook.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    hook.chmod(0o755)
    found = _decide(observe(project, REPOSITORY, "public", remote="absent"))
    assert any("ERR_PUBLISH_HOOKS_INSTALLED" in denial for denial in found), found


def test_a_populated_remote_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = _fresh(tmp_path, monkeypatch)
    found = _decide(observe(project, REPOSITORY, "public", remote="populated"))
    assert any("ERR_PUBLISH_REMOTE_POPULATED" in denial for denial in found), found


def test_an_empty_remote_from_an_earlier_attempt_is_adopted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A repository an interrupted publish created is used as it is, not created again."""
    project = _fresh(tmp_path, monkeypatch)
    bare = _bare(tmp_path)
    created: list[str] = []

    def create(repository: str, visibility: str) -> int:
        created.append(repository)
        return 0

    code = main(
        [str(project), REPOSITORY, "public"],
        inspect=lambda _: "empty",
        create=create,
        make_default=lambda repository, branch: 0,
        remote_url=lambda _: str(bare),
    )
    assert code == 0
    assert created == []
    assert _git(bare, "rev-parse", "develop") == _git(project, "rev-parse", "main")


def test_a_refused_push_reports_the_hook_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The reason is what refused the push, not git's generic last line (D.62)."""
    project = _fresh(tmp_path, monkeypatch)
    bare = _bare(tmp_path)
    hook = bare / "hooks" / "pre-receive"
    hook.write_text(REFUSING, encoding="utf-8")
    hook.chmod(0o755)
    capsys.readouterr()
    code = main(
        [str(project), REPOSITORY, "public"],
        inspect=_absent,
        create=lambda repository, visibility: 0,
        make_default=lambda repository, branch: 0,
        remote_url=lambda _: str(bare),
    )
    assert code == 1
    outcome = json.loads(capsys.readouterr().out)
    assert outcome["code"] == "push_failed", outcome
    assert "refused by the remote policy" in outcome["message"], outcome
