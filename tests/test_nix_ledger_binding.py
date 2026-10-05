"""The ledger, the bundle, and the printed document must be one record.

WHAT WAS MISSING
A ledger entry said a run happened and what it concluded. A bundle said what
that run saw. A printed document said the same verdict a third time. Nothing
connected them -- given an entry you could not find its bundle, and given a
bundle you could not tell which entry it belonged to.

The binding is by DIGEST, following the in-toto subject shape, because a path
can be reused and an id can be copied: only a hash stops matching when the
bytes change.
"""

from __future__ import annotations

import hashlib
import io
import json
import threading
from pathlib import Path

import pytest
from test_nix_observe import FakeSystem

from nix_contract import run
from nix_evidence import bundle_digest
from nix_ledger import LedgerLockError, append, verify_chain


def run_recording(tmp_path: Path) -> tuple[dict[str, object], Path, Path]:
    evidence = tmp_path / "evidence.json"
    ledger = tmp_path / "ledger.jsonl"
    out = io.StringIO()

    run(
        FakeSystem(),
        out=out,
        root=tmp_path,
        evidence_path=evidence,
        ledger_path=ledger,
    )

    document: dict[str, object] = json.loads(out.getvalue())
    return document, evidence, ledger


def last_entry(ledger: Path) -> dict[str, object]:
    payload: dict[str, object] = json.loads(ledger.read_text().splitlines()[-1])["payload"]
    return payload


def test_the_entry_and_the_document_share_a_run_id(tmp_path: Path) -> None:
    """Otherwise a report and its audit record cannot be matched up.

    RunMetadata was built inline for the document, so the ledger had no access
    to it and wrote no id at all.
    """
    document, _, ledger = run_recording(tmp_path)

    run_block = document["run"]
    assert isinstance(run_block, dict)
    assert last_entry(ledger)["run_id"] == run_block["run_id"]


def test_the_entry_binds_to_the_bundle_by_digest(tmp_path: Path) -> None:
    _, evidence, ledger = run_recording(tmp_path)

    evidence_block = last_entry(ledger)["evidence"]
    assert isinstance(evidence_block, dict)

    assert evidence_block["sha256"] == bundle_digest(evidence)
    assert evidence_block["path"] == str(evidence)


def test_an_edited_bundle_stops_matching(tmp_path: Path) -> None:
    """THE PROPERTY A DIGEST BUYS OVER A PATH.

    A path still resolves after the file beneath it changes. A digest does not,
    which is the whole reason the in-toto subject is a hash.
    """
    _, evidence, ledger = run_recording(tmp_path)
    recorded = last_entry(ledger)["evidence"]
    assert isinstance(recorded, dict)

    tampered = json.loads(evidence.read_text())
    tampered["platform"] = "x86_64-linux"
    evidence.write_text(json.dumps(tampered, indent=2, sort_keys=True))

    assert bundle_digest(evidence) != recorded["sha256"]


def test_a_run_without_evidence_records_no_binding(tmp_path: Path) -> None:
    """Empty, not fabricated.

    Most runs write no bundle. A digest invented for an absent artifact would
    be worse than none, because it would verify against nothing while looking
    like proof.
    """
    ledger = tmp_path / "ledger.jsonl"
    run(FakeSystem(), out=io.StringIO(), root=tmp_path, ledger_path=ledger)

    assert last_entry(ledger)["evidence"] == {}


def test_the_bundle_is_written_before_the_entry_that_names_it(tmp_path: Path) -> None:
    """Ordering, asserted rather than assumed.

    Appending first would record a digest of bytes not yet on disk -- and the
    check would pass on a machine where the write happened to land first.
    """
    _, evidence, ledger = run_recording(tmp_path)

    assert evidence.exists()
    recorded = last_entry(ledger)["evidence"]
    assert isinstance(recorded, dict)
    assert recorded["sha256"] == hashlib.sha256(evidence.read_bytes()).hexdigest()


def test_concurrent_appends_do_not_fork_the_chain(tmp_path: Path) -> None:
    """THE RACE THE LOCK EXISTS FOR, EXERCISED.

    The unlocked version read the tail, computed sequence and previous_hash,
    then appended -- three steps with no lock. Two writers read the same tail
    and both wrote sequence N: "both read the same value, both insert max + 1,
    THE CHAIN FORKS."

    Twenty threads is enough to hit it reliably without the lock, and a forked
    chain fails verify_chain -- so this asserts the fix rather than the bug.
    """
    ledger = tmp_path / "ledger.jsonl"
    errors: list[Exception] = []

    def write(index: int) -> None:
        try:
            append({"n": index}, path=ledger, timeout_seconds=10.0)
        except Exception as error:
            errors.append(error)

    threads = [threading.Thread(target=write, args=(i,)) for i in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors, f"appends failed: {errors}"

    result = verify_chain(ledger)
    assert result.intact, "concurrent appends forked the chain"
    assert result.entries == 20, f"expected 20 entries, found {result.entries}"


def test_a_held_lock_fails_closed(tmp_path: Path) -> None:
    """A record that cannot be written safely is not written at all.

    Falling through to an unlocked append would fork the chain permanently and
    silently, which is worse than the visible failure.
    """
    import fcntl

    ledger = tmp_path / "ledger.jsonl"
    lock_path = ledger.with_suffix(ledger.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    with lock_path.open("w", encoding="utf-8") as holder:
        fcntl.flock(holder.fileno(), fcntl.LOCK_EX)

        with pytest.raises(LedgerLockError, match="could not lock"):
            append({"n": 1}, path=ledger, timeout_seconds=0.2)

        fcntl.flock(holder.fileno(), fcntl.LOCK_UN)
