# scripts/run_task.py
"""Run any task through one wrapper that streams its output and records the run (D.17).

EVERY OPERATION GOES THROUGH HERE: mise run run <task> [arguments...]. The task's
stdout and stderr are merged and written to the console line by line as they
arrive, so a person watches it live; the run is recorded in the ledger as
task-run/v1 -- arguments, exit code, duration, a SHA-256 of the whole output and
its last lines -- and a one-line run-summary/v1 closes the console output as data.

THE TASK'S OWN EXIT CODE IS RETURNED. CommandOutcome collapses exit codes to 0, 1
and 2, and a task such as check:ruleset gives 2 a meaning of its own, so the
outcome carries only the verdict and the real code travels in task-run/v1.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, NonNegativeFloat, NonNegativeInt

from command_outcome import CommandOutcome
from pr_logs import ANSI
from run_ledger import append

TAIL = 40


class TaskRun(BaseModel):
    """task-run/v1: one task run through the wrapper."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    CONTRACT_ID: ClassVar[str] = "task-run/v1"

    contract: Literal["task-run/v1"] = "task-run/v1"
    task: str = Field(min_length=1)
    arguments: tuple[str, ...]
    exit_code: int
    duration_seconds: NonNegativeFloat
    output_lines: NonNegativeInt
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    tail: tuple[str, ...]


def main(
    argv: Sequence[str] | None = None,
    *,
    ledger: Path | None = None,
    launcher: Sequence[str] = ("mise", "run"),
) -> int:
    """Run the task, stream it, record it, and return its own exit code."""
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        raise SystemExit("usage: mise run run <task> [arguments...] -- name the task to run")
    task, arguments = args[0], tuple(args[1:])

    started = time.monotonic()
    digest = hashlib.sha256()
    tail: list[str] = []
    count = 0
    with subprocess.Popen(
        [*launcher, task, *arguments],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        # PYTHON CHILDREN WRITE EACH LINE AS THEY PRINT IT: into a pipe Python
        # block-buffers stdout, so a task's own lines arrived after a child's (D.20).
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    ) as process:
        if process.stdout is None:
            raise SystemExit("the task's output could not be captured")
        for line in process.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            digest.update(line.encode("utf-8"))
            count += 1
            tail.append(ANSI.sub("", line.rstrip("\n")))
            if len(tail) > TAIL:
                del tail[0]
        exit_code = process.wait()

    run = TaskRun(
        task=task,
        arguments=arguments,
        exit_code=exit_code,
        duration_seconds=round(time.monotonic() - started, 3),
        output_lines=count,
        output_sha256=digest.hexdigest(),
        tail=tuple(tail),
    )
    outcome = CommandOutcome.model_validate(
        {
            "command": task,
            "outcome": "success" if exit_code == 0 else "failed",
            "code": "task_succeeded" if exit_code == 0 else "task_failed",
            "message": f"{task} exited {exit_code}",
            "data": run.model_dump(mode="json"),
        }
    )
    record = append(outcome, ledger=ledger)
    summary = {
        "contract": "run-summary/v1",
        "task": task,
        "exit_code": exit_code,
        "verdict": record.verdict,
        "run_id": record.run_id,
    }
    sys.stdout.write(json.dumps(summary) + "\n")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
