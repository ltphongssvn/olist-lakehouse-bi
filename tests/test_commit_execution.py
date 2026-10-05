# tests/test_commit_execution.py
"""Running the commit, with git injected so the test commits nothing.

WHY A SEPARATE FILE FROM test_commit.py. Planning is a pure decision and needs
no repository; executing runs a process and must not mutate one. Keeping them
apart means the planner's tests stay fast and total, and these tests assert on
the argv that WOULD have run rather than on a commit that did.

THE BOUNDARY IS INJECTED, exactly as nix_contract.py injects System. A fake
records what was asked of it, so the argv is observable without git being
involved at all.

THE ONE ASSERTION THIS FILE EXISTS FOR. --no-verify must never appear. Every
commit in this repository carried it, which skipped start:check, fmt and lint on
every single commit. A test that watches for its return is the only thing that
stops the habit coming back.
"""

from __future__ import annotations

from pathlib import Path

from commit import execute_commit


class FakeGit:
    """Records every invocation and reports the code it was told to."""

    def __init__(self, code: int = 0, stderr: str = "") -> None:
        self.calls: list[list[str]] = []
        self.code = code
        self.stderr = stderr

    def __call__(self, argv: list[str]) -> tuple[int, str]:
        self.calls.append(list(argv))
        return self.code, self.stderr


def run(git: FakeGit, **overrides: object) -> object:
    arguments: dict[str, object] = {
        "branch": "feature/a-command-reports-as-data",
        "message": "feat(contracts): a command reports as data",
        "paths": ("scripts/command_outcome.py",),
        "git": git,
    }
    arguments.update(overrides)
    return execute_commit(**arguments)  # type: ignore[arg-type]


# --- the habit this task exists to end ------------------------------------------


def test_no_verify_is_never_passed() -> None:
    """THE REASON THIS TASK EXISTS.

    `git commit --no-verify` skipped the pre-commit hooks on every commit in
    this repository's history. The hooks run start:check, fmt and lint; none of
    them ever fired on a commit.
    """
    git = FakeGit()
    run(git)

    for call in git.calls:
        assert "--no-verify" not in call, f"--no-verify returned in {call}"
        assert "-n" not in call, f"the short form of --no-verify returned in {call}"


def test_the_hooks_are_not_bypassed_by_any_other_flag() -> None:
    """--no-gpg-sign and friends are fine; anything that skips verification is not."""
    git = FakeGit()
    run(git)

    forbidden = {"--no-verify", "-n", "--no-post-rewrite"}
    for call in git.calls:
        assert not forbidden.intersection(call)


# --- staging --------------------------------------------------------------------


def test_only_the_named_paths_are_staged() -> None:
    """NEVER -A. A stray zero-byte file was swept into a commit that way, and
    check_repo_hygiene.py exists because of it."""
    git = FakeGit()
    run(git, paths=("scripts/command_outcome.py", "tests/test_command_outcome.py"))

    staged = [call for call in git.calls if "add" in call]
    assert staged, "nothing was staged"
    for call in staged:
        assert "-A" not in call
        assert "--all" not in call
        assert "." not in call

    named = {argument for call in staged for argument in call}
    assert "scripts/command_outcome.py" in named
    assert "tests/test_command_outcome.py" in named


def test_staging_happens_before_committing() -> None:
    """An empty commit would otherwise be reported as a success."""
    git = FakeGit()
    run(git)

    kinds = [call[0] for call in git.calls]
    assert kinds.index("add") < kinds.index("commit")


# --- the message ----------------------------------------------------------------


def test_the_message_is_passed_as_a_file_not_inline() -> None:
    """-m WITH A MULTI-PARAGRAPH MESSAGE IS WHERE QUOTING BREAKS.

    The commit messages in this repository run to several paragraphs and
    contain backticks, quotes and newlines. Every one of them was written to a
    file for exactly this reason; the task keeps that rather than rediscovering
    it.
    """
    git = FakeGit()
    run(git)

    committed = [call for call in git.calls if "commit" in call]
    assert committed
    for call in committed:
        assert "-m" not in call
        assert "--message" not in call
        assert "--file" in call or "-F" in call


# --- a refused plan never reaches git -------------------------------------------


def test_a_protected_branch_never_reaches_git() -> None:
    """The planner refuses, and the executor must stop rather than stage first
    and ask afterwards."""
    git = FakeGit()
    outcome = run(git, branch="develop")

    assert outcome.outcome == "refused"  # type: ignore[attr-defined]
    assert outcome.code == "protected_branch"  # type: ignore[attr-defined]
    assert git.calls == [], "git was called despite a refused plan"


def test_an_unconventional_subject_never_reaches_git() -> None:
    git = FakeGit()
    outcome = run(git, message="added a thing")

    assert outcome.outcome == "refused"  # type: ignore[attr-defined]
    assert git.calls == []


# --- the outcome ----------------------------------------------------------------


def test_a_successful_commit_reports_success() -> None:
    git = FakeGit(code=0)
    outcome = run(git)

    assert outcome.outcome == "success"  # type: ignore[attr-defined]
    assert outcome.exit_code == 0  # type: ignore[attr-defined]


def test_a_failing_git_is_a_failure_not_a_refusal() -> None:
    """A refusal is a rule saying no; git exiting non-zero is the command
    breaking. Collapsing them is what exit codes 0 and 1 did."""
    git = FakeGit(code=1, stderr="nothing to commit")
    outcome = run(git)

    assert outcome.outcome == "failed"  # type: ignore[attr-defined]
    assert outcome.exit_code == 1  # type: ignore[attr-defined]
    assert "nothing to commit" in outcome.message  # type: ignore[attr-defined]


def test_the_outcome_is_an_envelope() -> None:
    git = FakeGit()
    outcome = run(git)

    assert outcome.contract == "command-outcome/v1"  # type: ignore[attr-defined]
    assert outcome.command == "commit"  # type: ignore[attr-defined]


def test_a_missing_path_never_reaches_git(tmp_path: Path) -> None:
    git = FakeGit()
    outcome = execute_commit(
        branch="feature/x",
        message="feat(x): y",
        paths=("scripts/nope.py",),
        git=git,
        root=tmp_path,
    )

    assert outcome.code == "path_not_found"
    assert git.calls == []
