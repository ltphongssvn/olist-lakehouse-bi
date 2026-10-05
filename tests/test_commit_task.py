# tests/test_commit_task.py
"""The task that makes the module reachable.

A MODULE NOBODY CAN RUN IS NOT A CAPTURED OPERATION. scripts/commit.py plans
and executes correctly and 22 tests prove it, but until mise.toml names a task
the only way to commit is still the hand-typed git command this work exists to
replace. That gap -- built and not wired -- is the shape this repository has
removed four times already.

STDOUT CARRIES THE ENVELOPE AND NOTHING ELSE, which is what command-outcome/v1
says: "the only thing it writes to stdout". A caller pipes it into jq without
filtering prose, and progress belongs on stderr.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

from commit import main

ROOT = Path(__file__).resolve().parent.parent


class FakeGit:
    """INJECTED, SO NO TEST TOUCHES THE REAL INDEX.

    An earlier version of test_several_paths_are_accepted called main() with a
    live runner: it staged two files and attempted a real commit. 2026 practice
    is explicit -- "all subprocess calls are dependency-injected so tests never
    spawn real processes" -- and main() had no seam to inject through, which was
    a gap in its signature rather than only in the test.
    """

    def __init__(self, code: int = 0) -> None:
        self.calls: list[list[str]] = []
        self.code = code

    def __call__(self, argv: list[str]) -> tuple[int, str]:
        self.calls.append(list(argv))
        return self.code, ""


def tasks() -> dict[str, object]:
    config = tomllib.loads((ROOT / "mise.toml").read_text(encoding="utf-8"))
    return dict(config.get("tasks", {}))


# --- the task is declared --------------------------------------------------------


def test_the_commit_task_exists() -> None:
    """Without this, the module is unreachable and the hand-typed git command
    remains the only way to commit."""
    assert "commit" in tasks()


def test_the_task_has_a_description() -> None:
    """policies/tasks denies an undescribed task; this asserts it directly so
    the failure names the cause rather than the rule."""
    spec = tasks()["commit"]
    assert isinstance(spec, dict)
    assert spec.get("description")


def test_the_task_never_bypasses_the_hooks() -> None:
    """THE DEFECT THIS WHOLE CHANGE EXISTS TO END.

    Every commit in this repository's history carried --no-verify, so
    start:check, fmt and lint never ran on a commit.
    """
    spec = tasks()["commit"]
    assert isinstance(spec, dict)
    body = str(spec.get("run", ""))
    assert "--no-verify" not in body


def test_the_task_runs_python_through_uv() -> None:
    """A bare interpreter is a PATH lookup, and PATH is ambient state this repo
    does not control -- policies/runtime denies it. Homebrew's python3 shadowed
    the pinned 3.12.3 during this very session and could not import ast."""
    spec = tasks()["commit"]
    assert isinstance(spec, dict)
    body = str(spec.get("run", ""))
    assert "uv run" in body


# --- the entry point -------------------------------------------------------------


def test_stdout_carries_only_the_envelope(capsys: pytest.CaptureFixture[str]) -> None:
    """A consumer parses stdout whole. One prose line would break that."""
    main(
        ["--message", "feat(x): a subject", "--path", "mise.toml"],
        branch="feature/x",
        git=FakeGit(),
    )
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["contract"] == "command-outcome/v1"
    assert parsed["command"] == "commit"


def test_a_refusal_prints_its_envelope_and_exits_two(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Exiting silently would make a refusal invisible to anything but a shell."""
    code = main(["--message", "feat(x): y", "--path", "mise.toml"], branch="develop", git=FakeGit())
    parsed = json.loads(capsys.readouterr().out)
    assert code == 2
    assert parsed["outcome"] == "refused"
    assert parsed["code"] == "protected_branch"


def test_an_unconventional_subject_exits_two(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(
        ["--message", "added a thing", "--path", "mise.toml"], branch="feature/x", git=FakeGit()
    )
    parsed = json.loads(capsys.readouterr().out)
    assert code == 2
    assert parsed["code"] == "unconventional_subject"


def test_several_paths_are_accepted(capsys: pytest.CaptureFixture[str]) -> None:
    """--path repeats, so a path containing a space needs no quoting rules."""
    main(
        ["--message", "feat(x): y", "--path", "mise.toml", "--path", "flake.nix"],
        branch="feature/x",
        git=FakeGit(),
    )
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["data"]["paths"] == ["mise.toml", "flake.nix"]


def test_no_path_exits_two(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["--message", "feat(x): y"], branch="feature/x", git=FakeGit())
    parsed = json.loads(capsys.readouterr().out)
    assert code == 2
    assert parsed["code"] == "no_paths_named"
