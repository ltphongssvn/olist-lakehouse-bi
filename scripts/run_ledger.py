# scripts/run_ledger.py
"""Every task run, recorded as data in an append-only, hash-chained ledger (D.15).

ONE RECORD PER RUN: the task, when, on which branch and commit, the verdict, and
the task's whole typed outcome. A verdict is a closed set -- pass, fail, refused
-- taken from the outcome, never from text.

HASH-CHAINED, BOTH WAYS. Each record carries the SHA-256 of the record before it
and its own, over a canonical JSON form, so an edited, deleted or re-ordered
record breaks the chain at a named position -- the last one included. The hash
is computed over the record as the model serialises it, so writing and
verifying can never disagree about how a timestamp is formatted.

ONE LEDGER FOR EVERY WORKTREE. It lives in the main checkout's .artifacts/runs/,
found through git's common directory, so removing a worktree destroys no
evidence; appends hold an exclusive lock, so concurrent tasks cannot interleave.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    NonNegativeInt,
    PositiveInt,
    ValidationError,
)

from command_outcome import CommandOutcome
from gitenv import git

ROOT = Path(__file__).resolve().parent.parent
GENESIS = "0" * 64
HASH = r"^[0-9a-f]{64}$"

Verdict = Literal["pass", "fail", "refused"]


class RunRecord(BaseModel):
    """run-record/v1: one task run, as data."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    contract: Literal["run-record/v1"] = "run-record/v1"
    run_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    task: str = Field(min_length=1)
    recorded_at: datetime
    branch: str
    head: str
    verdict: Verdict
    outcome: dict[str, JsonValue]
    previous_sha256: str = Field(pattern=HASH)
    sha256: str = Field(pattern=HASH)


class LedgerReport(BaseModel):
    """run-ledger-report/v1: whether the chain holds, and where it breaks if not."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    contract: Literal["run-ledger-report/v1"] = "run-ledger-report/v1"
    ledger: str
    records: NonNegativeInt
    intact: bool
    broken_at: PositiveInt | None
    tasks: tuple[str, ...]


def _canonical(fields: dict[str, JsonValue]) -> str:
    return json.dumps(fields, sort_keys=True, separators=(",", ":"))


def _digest(record: RunRecord) -> str:
    """The hash of a record's serialised form, without its own hash field."""
    fields = record.model_dump(mode="json")
    del fields["sha256"]
    return hashlib.sha256(_canonical(fields).encode("utf-8")).hexdigest()


def default_ledger() -> Path:
    """The main checkout's ledger, shared by every worktree of this repository."""
    common = git("rev-parse", "--path-format=absolute", "--git-common-dir", cwd=ROOT).stdout.strip()
    return Path(common).parent / ".artifacts" / "runs" / "ledger.jsonl"


def verdict_of(outcome: CommandOutcome) -> Verdict:
    if outcome.outcome == "success":
        return "pass"
    if outcome.outcome == "refused":
        return "refused"
    return "fail"


def append(outcome: CommandOutcome, *, ledger: Path | None = None) -> RunRecord:
    """Record one run, chained to the record before it, under an exclusive lock."""
    path = ledger or default_ledger()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        handle.seek(0)
        lines = [line for line in handle.read().splitlines() if line.strip()]
        previous = RunRecord.model_validate_json(lines[-1]).sha256 if lines else GENESIS
        draft = RunRecord(
            run_id=uuid.uuid4().hex,
            task=outcome.command,
            recorded_at=datetime.now(UTC),
            branch=git("rev-parse", "--abbrev-ref", "HEAD", cwd=ROOT).stdout.strip(),
            head=git("rev-parse", "HEAD", cwd=ROOT).stdout.strip(),
            verdict=verdict_of(outcome),
            outcome=outcome.model_dump(mode="json"),
            previous_sha256=previous,
            sha256=GENESIS,
        )
        record = draft.model_copy(update={"sha256": _digest(draft)})
        handle.write(_canonical(record.model_dump(mode="json")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return record


def verify(ledger: Path) -> LedgerReport:
    """Walk the chain; name the first record that does not hold."""
    lines = (
        [line for line in ledger.read_text(encoding="utf-8").splitlines() if line.strip()]
        if ledger.exists()
        else []
    )
    previous = GENESIS
    tasks: list[str] = []
    for position, line in enumerate(lines, start=1):
        try:
            record = RunRecord.model_validate_json(line)
        except ValidationError:
            return LedgerReport(
                ledger=str(ledger),
                records=len(lines),
                intact=False,
                broken_at=position,
                tasks=tuple(tasks),
            )
        if record.previous_sha256 != previous or _digest(record) != record.sha256:
            return LedgerReport(
                ledger=str(ledger),
                records=len(lines),
                intact=False,
                broken_at=position,
                tasks=tuple(tasks),
            )
        previous = record.sha256
        tasks.append(record.task)
    return LedgerReport(
        ledger=str(ledger), records=len(lines), intact=True, broken_at=None, tasks=tuple(tasks)
    )


def main() -> int:
    """runs:verify -- the chain's verdict as data; its run is recorded only if the chain holds."""
    ledger = default_ledger()
    report = verify(ledger)
    outcome = CommandOutcome.model_validate(
        {
            "command": "runs:verify",
            "outcome": "success" if report.intact else "refused",
            "code": "ledger_intact" if report.intact else "ledger_broken",
            "message": (
                f"{report.records} record(s), chain {'intact' if report.intact else 'broken'}"
            ),
            "data": report.model_dump(mode="json"),
        }
    )
    # A BROKEN CHAIN IS NOT APPENDED TO: chaining onto it would bury the break.
    if report.intact:
        append(outcome, ledger=ledger)
    print(json.dumps(outcome.model_dump(), indent=2))
    return outcome.exit_code


if __name__ == "__main__":
    sys.exit(main())
