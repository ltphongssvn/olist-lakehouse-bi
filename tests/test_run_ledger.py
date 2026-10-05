# tests/test_run_ledger.py
"""Every task run is recorded as data, in a hash-chained ledger (D.15).

ONE RECORD PER RUN, append-only. Each record holds the SHA-256 of the record
before it and its own, over a canonical JSON form, so an edited record, a
deleted one and a re-ordered pair all break the chain at a named position --
and storing its own hash means even the LAST record cannot be edited unseen.

THE VERDICT IS A CLOSED SET, from the task's typed outcome: pass, fail, refused.
"""

from __future__ import annotations

from pathlib import Path

from command_outcome import CommandOutcome
from run_ledger import GENESIS, append, verdict_of, verify


def _outcome(outcome: str = "success") -> CommandOutcome:
    return CommandOutcome.model_validate(
        {
            "command": "repo:state",
            "outcome": outcome,
            "code": "observed",
            "message": "m",
            "data": {},
        }
    )


def _ledger(tmp_path: Path, count: int) -> Path:
    ledger = tmp_path / "runs" / "ledger.jsonl"
    for _ in range(count):
        append(_outcome(), ledger=ledger)
    return ledger


def test_records_are_appended_and_chained(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    first = append(_outcome(), ledger=ledger)
    second = append(_outcome(), ledger=ledger)
    assert second.previous_sha256 == first.sha256
    report = verify(ledger)
    assert (report.records, report.intact, report.broken_at) == (2, True, None)


def test_the_first_record_starts_the_chain(tmp_path: Path) -> None:
    assert append(_outcome(), ledger=tmp_path / "ledger.jsonl").previous_sha256 == GENESIS


def test_an_edited_record_breaks_the_chain(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path, 3)
    lines = ledger.read_text(encoding="utf-8").splitlines()
    lines[1] = lines[1].replace('"verdict":"pass"', '"verdict":"fail"')
    ledger.write_text("\n".join(lines) + "\n", encoding="utf-8")
    report = verify(ledger)
    assert (report.intact, report.broken_at) == (False, 2)


def test_the_last_record_cannot_be_edited_unseen(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path, 2)
    lines = ledger.read_text(encoding="utf-8").splitlines()
    lines[-1] = lines[-1].replace('"code":"observed"', '"code":"forged"')
    ledger.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert (verify(ledger).intact, verify(ledger).broken_at) == (False, 2)


def test_a_deleted_record_breaks_the_chain(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path, 3)
    lines = ledger.read_text(encoding="utf-8").splitlines()
    ledger.write_text("\n".join([lines[0], lines[2]]) + "\n", encoding="utf-8")
    assert (verify(ledger).intact, verify(ledger).broken_at) == (False, 2)


def test_an_absent_ledger_is_an_intact_empty_chain(tmp_path: Path) -> None:
    report = verify(tmp_path / "missing.jsonl")
    assert (report.records, report.intact) == (0, True)


def test_the_verdict_follows_the_outcome() -> None:
    assert verdict_of(_outcome("success")) == "pass"
    assert verdict_of(_outcome("refused")) == "refused"
