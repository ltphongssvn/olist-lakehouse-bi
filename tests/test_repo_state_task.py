# tests/test_repo_state_task.py
"""Repository state is observed by a task, as data (D.16).

TYPED EVIDENCE, NOT TEXT. git status --porcelain=v1 -z is parsed into records:
a status and a path, and for a rename the original path too -- which a
line-based reader of the human output gets wrong. Verdicts are booleans
computed from those records, and the task records its run in the ledger.
"""

from __future__ import annotations

from pathlib import Path

from repo_report import RepositoryReport, main, observe, parse_porcelain
from run_ledger import verify

ROOT = Path(__file__).resolve().parent.parent


def test_porcelain_is_parsed_into_typed_changes() -> None:
    changes = parse_porcelain(" M a.py\0?? b.py\0R  new.py\0old.py\0")
    assert [(c.status, c.path, c.original_path) for c in changes] == [
        (" M", "a.py", None),
        ("??", "b.py", None),
        ("R ", "new.py", "old.py"),
    ]


def test_the_state_is_typed_evidence_with_verdicts() -> None:
    report = observe(ROOT)
    assert report.contract == "repository-state/v1"
    assert any(worktree.is_main for worktree in report.worktrees)
    assert all(isinstance(value, bool) for value in report.verdicts.model_dump().values())
    assert RepositoryReport.model_validate_json(report.model_dump_json()) == report


def test_the_task_records_its_run(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    assert main(ledger=ledger) == 0
    report = verify(ledger)
    assert (report.records, report.intact) == (1, True)
    assert report.tasks == ("repo:state",)
