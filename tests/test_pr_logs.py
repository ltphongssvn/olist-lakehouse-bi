# tests/test_pr_logs.py
"""A failed CI run is read by a task, as data (D.18).

THE FORMAT, GROUNDED. gh run view --log-failed prints one line per log record as
<job> TAB <step> TAB <timestamp> <text>. Lines gh cannot place under a step carry
UNKNOWN STEP, and a line with no columns at all is kept there too -- output
outside any step is the first place to look when a job failed with nothing
under a named one. ANSI colour codes are stripped from the text.

ONLY THE PROCESS IS STUBBED: subprocess.run is the boundary to gh and git.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from pr_logs import main, parse_log, signals
from run_ledger import verify

SAMPLE = (
    "quality gate\tmise run check\t2026-10-01T23:15:10.2466261Z \x1b[31mFAILED: test\x1b[0m\n"
    "quality gate\tmise run check\t2026-10-01T23:15:10.2468064Z E   AssertionError: boom\n"
    "quality gate\tSet up job\t2026-10-01T23:13:49.0177400Z Ubuntu\n"
    "quality gate\tUNKNOWN STEP\t2026-10-01T23:15:11.0000000Z orphan line\n"
)


def test_a_failed_log_is_parsed_into_typed_steps() -> None:
    steps = parse_log(SAMPLE)
    assert [(s.job, s.step, s.lines) for s in steps] == [
        ("quality gate", "mise run check", 2),
        ("quality gate", "Set up job", 1),
        ("quality gate", "UNKNOWN STEP", 1),
    ]
    first = steps[0].tail[0]
    assert (first.timestamp, first.text) == ("2026-10-01T23:15:10.2466261Z", "FAILED: test")


def test_a_line_without_columns_is_kept_under_unknown_step() -> None:
    (step,) = parse_log("plain line without columns\n")
    assert step.step == "UNKNOWN STEP"
    assert step.tail[0].text == "plain line without columns"


def test_caret_notation_escapes_are_stripped_too() -> None:
    """gh renders ESC as the two characters ^[ in some logs, not as the byte."""
    (step,) = parse_log(
        "quality gate\tmise run check\t2026-10-02T15:30:09.0936591Z ^[[31mERROR^[[0m\n"
    )
    assert step.tail[0].text == "ERROR"


def test_failure_signals_are_picked_out() -> None:
    assert signals(parse_log(SAMPLE)) == ("FAILED: test", "E   AssertionError: boom")


def test_the_task_reads_the_branchs_failed_run_and_records_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake(args: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        if args[:3] == ["gh", "run", "list"]:
            output = '[{"databaseId": 42, "headSha": "abc123", "url": "https://example.invalid/runs/42"}]'
        elif args[:3] == ["gh", "run", "view"]:
            output = SAMPLE
        else:
            output = "feature/x\n"
        return subprocess.CompletedProcess(args, 0, output, "")

    monkeypatch.setattr(subprocess, "run", fake)
    ledger = tmp_path / "ledger.jsonl"
    assert main(ledger=ledger) == 0
    report = verify(ledger)
    assert (report.records, report.intact, report.tasks) == (1, True, ("pr:logs",))
