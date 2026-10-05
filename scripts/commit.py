# scripts/commit.py
"""Committing, as a task that decides before it acts.

WHAT THIS FIXES. Every commit in this repository was made by hand as
`git commit --file /tmp/commit-msg.txt --no-verify`. Two defects in one habit:

    NOT A TASK      mise.toml states that every project operation is a task,
                    "not a remembered command, not a paste from scrollback".
                    The most frequent operation here was the exception.

    --no-verify     the pre-commit hooks -- start:check, fmt, lint -- were
                    skipped on EVERY commit. The gate was only reached at push
                    time, so a protected-branch commit or an unformatted file
                    was caught late or not at all.

THIS MODULE PLANS; IT DOES NOT YET ACT.

plan_commit answers one question -- may this commit proceed, and with what --
and returns the answer as a command-outcome/v1 envelope. Running git is a
separate concern with its own tests, written next. Splitting them keeps the
decision pure and testable without a repository, and means a caller can show
what WOULD happen before anything is staged.

NAMED PATHS, NEVER -A. `git add -A` swept a stray zero-byte file into a commit
earlier in this project; scripts/check_repo_hygiene.py exists because of it.
Naming the paths makes the content of a commit a decision rather than whatever
the working tree happened to hold.

THE ORDER OF REFUSALS IS DELIBERATE. The branch is checked first because it is
the cheapest and most fundamental guard. The subject is checked BEFORE the
paths, so a rejected message never leaves a half-staged index behind.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path

from command_outcome import CommandOutcome

__all__ = [
    "CONVENTIONAL_SUBJECT",
    "PROTECTED",
    "execute_commit",
    "main",
    "plan_commit",
    "run_git",
]

ROOT = Path(__file__).resolve().parent.parent

# GITFLOW: work happens on a feature branch cut from origin/develop. The same
# set start:check guards, restated here because --no-verify meant that guard
# never ran on a commit.
PROTECTED = frozenset({"develop", "main"})

# CONVENTIONAL COMMITS, ANCHORED AT BOTH ENDS.
#
# An unanchored pattern accepts prose that merely CONTAINS a type -- "this is
# not a feat(x): subject" would match in the middle and pass. The ^ and the
# explicit alternation are what make this a format check rather than a search.
#
# The scope is optional because "fix: ..." is valid; the ! is optional because a
# breaking change marks itself.
CONVENTIONAL_SUBJECT = re.compile(
    r"^(?:feat|fix|refactor|test|docs|chore|ci|build|perf|style|revert)"
    r"(?:\([a-z0-9][a-z0-9:_-]*\))?!?: .+$"
)


def _outcome(code: str, message: str, verdict: str, **data: object) -> CommandOutcome:
    """One envelope, so every exit from this module has the same shape."""
    return CommandOutcome.model_validate(
        {
            "command": "commit",
            "outcome": verdict,
            "code": code,
            "message": message,
            "data": data,
        }
    )


def plan_commit(
    branch: str,
    message: str,
    paths: Sequence[str],
    root: Path = ROOT,
) -> CommandOutcome:
    """Decide whether this commit may proceed, and say why when it may not.

    REFUSED, NOT FAILED. Every negative answer here is the command working
    correctly and declining: the branch is protected, the subject is not
    conventional, no path was named. None of them is a crash, and the exit code
    says so -- 2 rather than 1 -- so a caller can tell a rule from a bug.
    """
    if branch in PROTECTED:
        return _outcome(
            "protected_branch",
            f"refusing to commit on {branch!r}: work happens on a feature branch "
            "cut from origin/develop",
            "refused",
            branch=branch,
        )

    # THE FIRST LINE IS THE SUBJECT. A body may say anything; the subject is the
    # part every tool, changelog and reader depends on.
    subject = message.split("\n", 1)[0]
    if CONVENTIONAL_SUBJECT.match(subject) is None:
        return _outcome(
            "unconventional_subject",
            f"the subject {subject!r} is not a conventional commit: "
            "expected type(scope): description",
            "refused",
            subject=subject,
        )

    if not paths:
        return _outcome(
            "no_paths_named",
            "no paths named: committing nothing and reporting success is not an outcome",
            "refused",
        )

    # A MISTYPED PATH WOULD OTHERWISE STAGE NOTHING AND COMMIT NOTHING, while
    # the command reported success -- the claim-without-effect shape this
    # repository keeps removing.
    missing = [name for name in paths if not (root / name).exists()]
    if missing:
        return _outcome(
            "path_not_found",
            f"named but not on disk: {', '.join(sorted(missing))}",
            "refused",
            missing=sorted(missing),
        )

    return _outcome(
        "ready_to_commit",
        f"{len(paths)} path(s) ready on {branch}",
        "success",
        branch=branch,
        subject=subject,
        # A LIST, NOT A TUPLE: JsonValue admits lists, and a tuple would fail at
        # the contract boundary rather than silently serialising.
        paths=list(paths),
    )


GitRunner = Callable[[list[str]], tuple[int, str]]
NEWLINE = chr(10)


def run_git(argv: list[str]) -> tuple[int, str]:
    """The real boundary: run git, report (code, stderr)."""
    done = subprocess.run(["git", *argv], capture_output=True, text=True, check=False, cwd=ROOT)
    return done.returncode, done.stderr.strip()


def execute_commit(
    branch: str,
    message: str,
    paths: Sequence[str],
    git: GitRunner = run_git,
    root: Path = ROOT,
) -> CommandOutcome:
    """Stage the named paths and commit them, THROUGH THE HOOKS.

    NO --no-verify, which is why this task exists: every commit here carried it,
    so start:check, fmt and lint never ran on a commit.

    THE PLAN IS CONSULTED FIRST and its refusal returned untouched, so git is
    never reached when a rule says no.

    THE MESSAGE GOES THROUGH A FILE: -m is where shell quoting breaks.
    """
    planned = plan_commit(branch=branch, message=message, paths=paths, root=root)
    if planned.outcome != "success":
        return planned

    code, err = git(["add", "--", *paths])
    if code != 0:
        return _outcome("stage_failed", "could not stage: " + err, "failed", paths=list(paths))

    # delete_on_close=False IS THE DOCUMENTED ANSWER TO EXACTLY THIS NEED.
    #
    # git must reopen the file by name, so it cannot be deleted at close; it
    # must still be deleted afterwards, because a message file left behind is a
    # draft someone later mistakes for the current one.
    #
    # Two earlier shapes were worse. delete=False with os.unlink in a finally
    # met the second obligation and not the first: ruff's SIM115 saw that the
    # HANDLE escaped the context manager, so a raising write would leak it.
    #
    # CPython names this case: "to use the file name within a with statement,
    # set the delete_on_close parameter to be false. The latter approach is
    # recommended as it provides assistance in automatic cleaning of the
    # temporary file upon the context manager exit." The removal becomes the
    # context manager's obligation rather than mine, so no exit path skips it.
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete_on_close=False, encoding="utf-8"
    ) as draft:
        draft.write(message if message.endswith(NEWLINE) else message + NEWLINE)
        # CLOSED SO GIT SEES THE WHOLE MESSAGE: an unflushed buffer would hand
        # git a truncated file, and a short commit message is worse than none.
        draft.close()
        code, err = git(["commit", "--file", draft.name])

    if code != 0:
        return _outcome("commit_failed", "git refused: " + err, "failed", branch=branch)

    return _outcome(
        "committed",
        "committed " + str(len(paths)) + " path(s) on " + branch,
        "success",
        branch=branch,
        subject=message.split(NEWLINE, 1)[0],
        paths=list(paths),
    )


def current_branch(git: GitRunner = run_git) -> str:
    """The branch this shell is on, read once at the boundary.

    PASSED IN, NOT READ INSIDE main(). The branch is ambient state; reading it
    where the decision happens would make the decision untestable without
    checking out a protected branch to prove the guard fires.
    """
    code, _ = git(["rev-parse", "--abbrev-ref", "HEAD"])
    if code != 0:
        return "(unknown)"
    done = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
        cwd=ROOT,
    )
    return done.stdout.strip() or "(unknown)"


def main(
    argv: Sequence[str] | None = None,
    branch: str | None = None,
    git: GitRunner = run_git,
) -> int:
    """Commit the named paths, and report the outcome as data.

    STDOUT CARRIES THE ENVELOPE AND NOTHING ELSE, which is what
    command-outcome/v1 says it is for. A caller pipes this into jq; progress and
    diagnostics belong on stderr.

    THE EXIT CODE IS THE ENVELOPE'S -- 0, 1 or 2 -- so a shell branches on a
    refusal without parsing a word.

    --path REPEATS rather than splitting a list, so a path containing a space
    needs no quoting convention invented for it.
    """
    parser = argparse.ArgumentParser(prog="commit", add_help=True)
    parser.add_argument("--message", "-m", required=True)
    parser.add_argument("--path", "-p", action="append", default=[])
    parsed = parser.parse_args(list(argv) if argv is not None else None)

    outcome = execute_commit(
        branch=branch if branch is not None else current_branch(git),
        message=parsed.message,
        paths=tuple(parsed.path),
        git=git,
    )
    print(json.dumps(outcome.model_dump(), indent=2))
    return outcome.exit_code


if __name__ == "__main__":
    sys.exit(main())
