# tests/test_run_task.py
"""Every task is run through one wrapper that streams and records it (D.17).

mise run run <task> runs the task, streams every line to the console as it
arrives, records the run in the ledger as task-run/v1, and returns the task's OWN
exit code -- CommandOutcome collapses exit codes to 0, 1 and 2, and a task such as
check:ruleset gives 2 a meaning of its own.

A REAL CHILD PROCESS. The launcher is swapped from `mise run` to a small script
standing in for a task, so streaming, recording and exit codes run for real.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from run_ledger import RunRecord, verify
from run_task import TaskRun, main

FAKE_TASK = """
import json
import sys

task, *args = sys.argv[1:]
if task == "ok":
    print("hello \x1b[31mred\x1b[0m")
    print("done")
elif task == "fails":
    print("broken")
    sys.exit(2)
elif task == "echo":
    print(json.dumps(args))
elif task == "ordered":
    import subprocess
    print("first")
    subprocess.run([sys.executable, "-c", "print('second')"], check=True)
"""


@pytest.fixture
def launcher(tmp_path: Path) -> tuple[str, ...]:
    script = tmp_path / "fake_task.py"
    script.write_text(FAKE_TASK, encoding="utf-8")
    return (sys.executable, str(script))


def _last_run(ledger: Path) -> tuple[RunRecord, TaskRun]:
    record = RunRecord.model_validate_json(ledger.read_text(encoding="utf-8").splitlines()[-1])
    return record, TaskRun.model_validate(record.outcome["data"])


def test_every_task_records_its_runs(
    tmp_path: Path, launcher: tuple[str, ...], capsys: pytest.CaptureFixture[str]
) -> None:
    ledger = tmp_path / "ledger.jsonl"
    assert main(["ok"], ledger=ledger, launcher=launcher) == 0
    assert "hello" in capsys.readouterr().out, "the task's output must reach the console"
    report = verify(ledger)
    assert (report.records, report.intact, report.tasks) == (1, True, ("ok",))
    record, run = _last_run(ledger)
    assert record.verdict == "pass"
    assert (run.exit_code, run.output_lines) == (0, 2)
    assert run.tail == ("hello red", "done")


def test_a_failing_task_keeps_its_own_exit_code(tmp_path: Path, launcher: tuple[str, ...]) -> None:
    ledger = tmp_path / "ledger.jsonl"
    assert main(["fails"], ledger=ledger, launcher=launcher) == 2
    record, run = _last_run(ledger)
    assert (record.verdict, run.exit_code) == ("fail", 2)


def test_arguments_pass_through_untouched(tmp_path: Path, launcher: tuple[str, ...]) -> None:
    ledger = tmp_path / "ledger.jsonl"
    assert main(["echo", "--help", "a b"], ledger=ledger, launcher=launcher) == 0
    _, run = _last_run(ledger)
    assert run.arguments == ("--help", "a b")
    assert json.loads(run.tail[0]) == ["--help", "a b"]


def test_a_tasks_lines_keep_their_order(tmp_path: Path, launcher: tuple[str, ...]) -> None:
    """A line printed before a child starts must arrive before the child's (D.20)."""
    ledger = tmp_path / "ledger.jsonl"
    assert main(["ordered"], ledger=ledger, launcher=launcher) == 0
    _, run = _last_run(ledger)
    assert run.tail == ("first", "second")


def test_naming_no_task_refuses_and_records_nothing(
    tmp_path: Path, launcher: tuple[str, ...]
) -> None:
    ledger = tmp_path / "ledger.jsonl"
    with pytest.raises(SystemExit, match="task"):
        main([], ledger=ledger, launcher=launcher)
    assert not ledger.exists()
