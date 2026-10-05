"""An append-only, hash-chained record of contract runs.

WHAT THIS IS
Each run appends one JSON line carrying the hash of the previous line. Editing,
reordering or deleting a record mid-file breaks the chain at that point and at
every point after it, so alteration is DETECTABLE by recomputing.

WHAT THIS IS NOT, STATED PLAINLY BECAUSE THE DISTINCTION IS USUALLY ELIDED
Tamper-EVIDENT, not tamper-PROOF. A local file is inherently mutable. The chain
detects in-place edits, reorders and mid-chain deletions. It does NOT detect:

  TAIL TRUNCATION   deleting the last N records leaves a shorter valid chain
  GENESIS REWRITE   discarding the file and starting again verifies cleanly

Both are closed the same way and neither is done here: anchoring the chain head
somewhere the writer cannot reach -- an off-machine log, a transparency log, a
timestamp authority. "A hash chain on a single machine is better than no chain,
but it still has a single point of failure."

AND IT IS NOT SOC 2 EVIDENCE
Saying so would be false. A compliance auditor asks how you know the logs were
not modified, and "the chain verifies" answers that only for records still
present, written by a process the same user controls. This is a local integrity
aid for a developer machine. Calling it compliance would be the kind of claim
this repository exists to avoid making.

WHO RAN IT: AN OPAQUE ID, NOT A USERNAME
OWASP asks for the actor. A username or hostname is identifying data -- this
machine's hostname contains a person's name -- and the repository runs a PII
scanner to keep exactly that out of artifacts. A random identifier generated
once and stored locally distinguishes machines without naming anyone.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import time
import uuid
from pathlib import Path
from typing import IO

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from nix_remediation import ActionableError

__all__ = [
    "GENESIS_HASH",
    "LedgerEntry",
    "LedgerLockError",
    "LedgerVerification",
    "append",
    "machine_id",
    "verify_chain",
]

# The previous-hash of the first record. A fixed, recognisable value rather than
# an empty string, so a genesis record is distinguishable from one whose
# previous hash failed to write.
GENESIS_HASH = "0" * 64

LEDGER_PATH = Path(os.environ.get("NIX_CONTRACT_LEDGER", ".nix-contract-ledger.jsonl"))
MACHINE_ID_PATH = Path.home() / ".config" / "cscie103" / "machine-id"


def machine_id() -> str:
    """A stable, opaque identifier for this machine.

    Generated once and stored, so two runs on one laptop share it and two
    laptops differ. It says nothing about who owns the machine, which is the
    whole point -- see the module docstring on why the hostname is unusable.
    """
    if MACHINE_ID_PATH.is_file():
        existing = MACHINE_ID_PATH.read_text().strip()
        if existing:
            return existing

    generated = str(uuid.uuid4())
    MACHINE_ID_PATH.parent.mkdir(parents=True, exist_ok=True)
    MACHINE_ID_PATH.write_text(generated + "\n")
    return generated


class LedgerLockError(ActionableError):
    """The ledger could not be locked, so nothing was written.

    FAIL CLOSED. Appending without the lock risks forking the chain, and a
    forked chain reports tampering that never happened -- which trains people
    to ignore the one signal this file exists to give.

    ActionableError, NOT RuntimeError. The first version inherited from
    RuntimeError and the classification test never saw it, because that test
    walks ActionableError subclasses -- so a new unclassified error slipped
    past the guard built to prevent exactly that.
    """

    code = "ERR_NIX_LEDGER_LOCKED"


class LedgerEntry(BaseModel):
    """One record. The hash covers the payload AND the previous hash."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    sequence: int = Field(description="Position in the chain, from zero")
    previous_hash: str
    entry_hash: str
    machine: str
    payload: dict[str, JsonValue]

    @staticmethod
    def compute_hash(
        sequence: int, previous_hash: str, machine: str, payload: dict[str, JsonValue]
    ) -> str:
        """SHA-256 over a canonical serialisation.

        sort_keys and separators are load-bearing: without them the same payload
        serialises differently between runs and the chain fails to verify for a
        reason that looks like tampering.
        """
        material = json.dumps(
            {
                "sequence": sequence,
                "previous_hash": previous_hash,
                "machine": machine,
                "payload": payload,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()


class LedgerVerification(BaseModel):
    """The result of walking the chain."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    entries: int
    intact: bool
    broken_at: int | None = Field(
        default=None, description="Sequence of the first record that fails"
    )
    detail: str = ""


def _read_entries(path: Path) -> list[LedgerEntry]:
    if not path.is_file():
        return []
    return [
        LedgerEntry.model_validate_json(line)
        for line in path.read_text().splitlines()
        if line.strip()
    ]


def append(
    payload: dict[str, JsonValue], path: Path = LEDGER_PATH, *, timeout_seconds: float = 5.0
) -> LedgerEntry:
    """Append one record, chained to the last, under an exclusive lock.

    THE UNLOCKED VERSION HAD A REAL RACE AND IT WAS MINE.
    It read the tail, computed sequence and previous_hash from it, then
    appended -- three steps with no lock. The failure is documented precisely
    elsewhere: "two concurrent transactions can both execute the MAX query
    before either one has inserted. Neither blocks the other. Both read the
    same value. Both insert max + 1. THE CHAIN FORKS."

    A hash chain has a single-writer invariant: "concurrent appends are not
    safe on a plain hash chain." Two gate runs -- a local `mise run check` and
    a hook firing at the same moment -- are enough to fork it, and verify_chain
    would then report tampering that never happened. A false alarm from a
    tamper-evident log is worse than none, because it teaches people to ignore
    it.

    THE LOCK SPANS THE WHOLE READ-COMPUTE-WRITE, not just the write. Locking
    only the append would leave both writers holding the same stale tail.

    A SIDECAR LOCK FILE, so lock state never touches the ledger bytes: "the
    only new on-disk artifacts are sibling *.lock files used purely for lock
    state."

    FAILS CLOSED ON CONTENTION. A record that cannot be written safely is not
    written at all -- a forked chain would be a permanent, silent lie about
    history.

    LIMITS, STATED: flock is ADVISORY, so a process that ignores it can still
    corrupt the file, and "on NFS, flock is silently ignored". This guards
    concurrent runs of THIS program on a local filesystem, which is the case
    that exists.
    """
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    with lock_path.open("w", encoding="utf-8") as lock_handle:
        _acquire_exclusive(lock_handle, lock_path, timeout_seconds)

        try:
            existing = _read_entries(path)
            sequence = len(existing)
            previous_hash = existing[-1].entry_hash if existing else GENESIS_HASH
            machine = machine_id()

            entry = LedgerEntry(
                sequence=sequence,
                previous_hash=previous_hash,
                entry_hash=LedgerEntry.compute_hash(sequence, previous_hash, machine, payload),
                machine=machine,
                payload=payload,
            )

            with path.open("a", encoding="utf-8") as handle:
                handle.write(entry.model_dump_json() + "\n")
                # FLUSHED AND FSYNCED INSIDE THE LOCK. Releasing before the
                # bytes reach disk would let the next writer read a tail that
                # is still in a buffer.
                handle.flush()
                os.fsync(handle.fileno())
        finally:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)

    return entry


def _acquire_exclusive(handle: IO[str], lock_path: Path, timeout_seconds: float) -> None:
    """Take the lock, or refuse to write.

    Polls rather than blocking indefinitely: an unattended gate that hangs
    forever on a stale lock is its own outage.
    """
    deadline = time.monotonic() + timeout_seconds

    while True:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except OSError:
            if time.monotonic() >= deadline:
                raise LedgerLockError(
                    f"could not lock {lock_path} within {timeout_seconds}s",
                    remediation="Another run holds the ledger lock. Retry; if it "
                    "persists, a crashed process may have left the lock file, and "
                    "removing it is safe once no run is in flight.",
                    lock_path=str(lock_path),
                    timeout_seconds=timeout_seconds,
                ) from None
            time.sleep(0.05)


def verify_chain(path: Path = LEDGER_PATH) -> LedgerVerification:
    """Walk the chain and report the FIRST break.

    Reporting the first break rather than a count is deliberate: every record
    after an alteration also fails, so a count describes the length of the tail
    rather than the location of the problem.
    """
    entries = _read_entries(path)
    if not entries:
        return LedgerVerification(entries=0, intact=True, detail="empty ledger")

    previous_hash = GENESIS_HASH
    for position, entry in enumerate(entries):
        if entry.sequence != position:
            return LedgerVerification(
                entries=len(entries),
                intact=False,
                broken_at=position,
                detail=f"sequence {entry.sequence} found at position {position}",
            )

        if entry.previous_hash != previous_hash:
            return LedgerVerification(
                entries=len(entries),
                intact=False,
                broken_at=position,
                detail="previous_hash does not match the preceding record",
            )

        expected = LedgerEntry.compute_hash(
            entry.sequence, entry.previous_hash, entry.machine, entry.payload
        )
        if expected != entry.entry_hash:
            return LedgerVerification(
                entries=len(entries),
                intact=False,
                broken_at=position,
                detail="the record's contents do not match its hash",
            )

        previous_hash = entry.entry_hash

    return LedgerVerification(
        entries=len(entries),
        intact=True,
        detail=(
            "chain verifies. NOTE: this cannot detect tail truncation or a "
            "genesis rewrite -- see the module docstring."
        ),
    )
