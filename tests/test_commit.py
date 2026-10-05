# tests/test_commit.py
"""Committing is a project operation, and it was never captured.

WHAT THIS FIXES. Every commit in this repository has been made by hand as
`git commit --file /tmp/commit-msg.txt --no-verify`. Two defects in one habit:

    NOT A TASK      mise.toml states that every project operation is a task,
                    "not a remembered command, not a paste from scrollback".
                    The single most frequent operation here was the exception.

    --no-verify     the pre-commit hooks -- start:check, fmt, lint -- have been
                    skipped on EVERY commit. The gate was only ever reached at
                    push time, so a protected-branch commit or an unformatted
                    file was caught late or not at all.

NAMED PATHS, NEVER -A. `git add -A` swept a stray zero-byte file into a commit
earlier in this project; the hygiene gate exists because of it. Naming the paths
makes what is committed a decision rather than whatever the tree happened to
hold.

THE OUTCOME IS AN ENVELOPE. This is the first consumer of command-outcome/v1:
a refusal carries a machine code and exits 2, a failure exits 1, and a caller
branches without reading prose.
"""

from __future__ import annotations

from pathlib import Path

from command_outcome import CommandOutcome
from commit import (
    CONVENTIONAL_SUBJECT,
    PROTECTED,
    plan_commit,
)


def plan(**overrides: object) -> CommandOutcome:
    """A valid commit plan, with the field under test overridden."""
    arguments: dict[str, object] = {
        "branch": "feature/a-command-reports-as-data",
        "message": "feat(contracts): a command reports as data",
        "paths": ("scripts/command_outcome.py",),
    }
    arguments.update(overrides)
    return plan_commit(**arguments)  # type: ignore[arg-type]


# --- the protected-branch guard -------------------------------------------------


def test_a_protected_branch_is_refused() -> None:
    """GitFlow: work happens on a feature branch cut from origin/develop.

    start:check already refuses this, and --no-verify meant it never ran.
    """
    for branch in sorted(PROTECTED):
        outcome = plan(branch=branch)
        assert outcome.outcome == "refused"
        assert outcome.code == "protected_branch"
        assert branch in outcome.message


def test_a_feature_branch_is_allowed() -> None:
    assert plan().outcome == "success"


# --- the message ----------------------------------------------------------------


def test_a_conventional_subject_is_required() -> None:
    """The repository's history is conventional commits throughout.

    A subject that does not parse is refused BEFORE anything is staged, so a
    rejected message never leaves a half-staged index behind.
    """
    for subject in ("added a thing", "FEAT: shouting", "feat no scope colon", ""):
        outcome = plan(message=subject)
        assert outcome.outcome == "refused"
        assert outcome.code == "unconventional_subject"


def test_every_conventional_type_is_accepted() -> None:
    for kind in ("feat", "fix", "refactor", "test", "docs", "chore", "ci", "build", "perf"):
        assert plan(message=f"{kind}(scope): a subject").outcome == "success"


def test_a_scope_is_optional() -> None:
    assert plan(message="fix: a subject with no scope").outcome == "success"


def test_the_subject_pattern_is_anchored() -> None:
    """An unanchored pattern would accept prose that merely CONTAINS a type."""
    assert CONVENTIONAL_SUBJECT.match("feat(x): y") is not None
    assert CONVENTIONAL_SUBJECT.match("this is not a feat(x): subject") is None


# --- the paths ------------------------------------------------------------------


def test_no_paths_is_refused() -> None:
    """Committing nothing and reporting success is the shape this repository
    keeps removing: a command that claims an effect it did not have."""
    outcome = plan(paths=())
    assert outcome.outcome == "refused"
    assert outcome.code == "no_paths_named"


def test_a_path_that_does_not_exist_is_refused(tmp_path: Path) -> None:
    """A mistyped path would otherwise stage nothing and commit nothing, while
    the command reported success."""
    outcome = plan_commit(
        branch="feature/x",
        message="feat(x): y",
        paths=("scripts/does_not_exist.py",),
        root=tmp_path,
    )
    assert outcome.outcome == "refused"
    assert outcome.code == "path_not_found"
    assert "does_not_exist" in outcome.message


def test_the_plan_names_every_path_it_would_stage() -> None:
    """The data carries what the command WOULD do, so a caller can show it
    before it happens."""
    outcome = plan(paths=("scripts/command_outcome.py", "tests/test_command_outcome.py"))
    assert outcome.data["paths"] == [
        "scripts/command_outcome.py",
        "tests/test_command_outcome.py",
    ]


# --- the envelope ---------------------------------------------------------------


def test_the_plan_is_an_envelope() -> None:
    outcome = plan()
    assert outcome.contract == "command-outcome/v1"
    assert outcome.command == "commit"


def test_a_refusal_exits_two_and_a_success_exits_zero() -> None:
    """A caller branches on the exit code without parsing a word, and a refusal
    is distinguishable from a crash."""
    assert plan().exit_code == 0
    assert plan(branch="develop").exit_code == 2
