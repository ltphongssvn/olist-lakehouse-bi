# scripts/pr_logs.py
"""A failed CI run, read by a task as data (D.18).

THE FORMAT, GROUNDED. gh run view --log-failed prints one record per line as
<job> TAB <step> TAB <timestamp> <text>. Lines gh cannot place under a step carry
UNKNOWN STEP, and a line with neither column is kept there whole: output outside
any step is the first place to look when a job failed with nothing under a named
one. ANSI colour codes are stripped; a first word counts as a timestamp only when
it has a timestamp's shape, so a column-less line is never cut in two.

RECORDED, from day one: ci-failure/v1 inside command-outcome/v1, appended to the
run ledger. No failed run is an outcome too, not an error.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, NonNegativeInt, RootModel

from command_outcome import CommandOutcome
from gitenv import git
from run_ledger import append

ROOT = Path(__file__).resolve().parent.parent
UNKNOWN_STEP = "UNKNOWN STEP"
TAIL = 40
# BOTH FORMS OF THE ESCAPE: the byte itself, and gh's caret notation, ^[ as two characters.
ANSI = re.compile(r"(?:\x1b|\^\[)\[[0-9;]*[A-Za-z]")
TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T[0-9:.]+Z$")
SIGNAL = re.compile(r"FAIL|Error|error:|Traceback|assert")


class _Strict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class LogLine(_Strict):
    timestamp: str | None
    text: str


class FailedStep(_Strict):
    job: str
    step: str
    lines: NonNegativeInt
    tail: tuple[LogLine, ...]


class CiFailure(_Strict):
    """ci-failure/v1: the branch's latest failed run, its failed steps and its signals."""

    contract: Literal["ci-failure/v1"] = "ci-failure/v1"
    branch: str
    run_id: int | None
    head_sha: str | None
    url: str | None
    steps: tuple[FailedStep, ...]
    signals: tuple[str, ...]


class _Run(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")
    databaseId: int  # noqa: N815 -- gh's own field name
    headSha: str  # noqa: N815
    url: str


class _Runs(RootModel[tuple[_Run, ...]]):
    """gh run list --json answers with a top-level array."""


def _line(rest: str) -> LogLine:
    stamp, separator, text = rest.partition(" ")
    if separator and TIMESTAMP.match(stamp):
        return LogLine(timestamp=stamp, text=ANSI.sub("", text))
    return LogLine(timestamp=None, text=ANSI.sub("", rest))


def parse_log(raw: str) -> tuple[FailedStep, ...]:
    """Every line grouped by job and step, in the order they appear."""
    groups: dict[tuple[str, str], list[LogLine]] = {}
    for line in raw.splitlines():
        if not line.strip():
            continue
        columns = line.split("\t", 2)
        job, step, rest = columns if len(columns) == 3 else ("", UNKNOWN_STEP, line)
        groups.setdefault((job, step), []).append(_line(rest))
    return tuple(
        FailedStep(job=job, step=step, lines=len(lines), tail=tuple(lines[-TAIL:]))
        for (job, step), lines in groups.items()
    )


def signals(steps: tuple[FailedStep, ...]) -> tuple[str, ...]:
    """The lines that look like failures, in order."""
    return tuple(line.text for step in steps for line in step.tail if SIGNAL.search(line.text))


def _gh(*args: str) -> str:
    result = subprocess.run(["gh", *args], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise SystemExit(f"gh {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def main(ledger: Path | None = None) -> int:
    """pr:logs -- the branch's latest failed CI run, as data, recorded."""
    branch = git("rev-parse", "--abbrev-ref", "HEAD", cwd=ROOT).stdout.strip()
    listed = _gh(
        "run",
        "list",
        "--branch",
        branch,
        "--status",
        "failure",
        "--limit",
        "1",
        "--json",
        "databaseId,headSha,url",
    )
    runs = _Runs.model_validate_json(listed).root
    if not runs:
        failure = CiFailure(
            branch=branch, run_id=None, head_sha=None, url=None, steps=(), signals=()
        )
        code, message = "no_failed_run", f"no failed run on {branch}"
    else:
        run = runs[0]
        steps = parse_log(_gh("run", "view", str(run.databaseId), "--log-failed"))
        failure = CiFailure(
            branch=branch,
            run_id=run.databaseId,
            head_sha=run.headSha,
            url=run.url,
            steps=steps,
            signals=signals(steps),
        )
        code, message = "ci_failure_read", f"run {run.databaseId}: {len(steps)} failed step(s)"
    outcome = CommandOutcome.model_validate(
        {
            "command": "pr:logs",
            "outcome": "success",
            "code": code,
            "message": message,
            "data": failure.model_dump(mode="json"),
        }
    )
    append(outcome, ledger=ledger)
    print(json.dumps(outcome.model_dump(), indent=2))
    return outcome.exit_code


if __name__ == "__main__":
    sys.exit(main())
