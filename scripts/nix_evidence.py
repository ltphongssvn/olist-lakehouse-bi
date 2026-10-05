"""Record what crossed the system boundary, so a run can be replayed.

WHY THIS IS POSSIBLE AT ALL
scripts/nix_system.py defines a Protocol through which EVERY impure operation
passes -- subprocess, filesystem, users, groups. That is precisely the boundary
record-and-replay needs: "identify a boundary around state and computation,
record all sources of nondeterminism crossing into the boundary, and reexecute
by replaying them".

Because the boundary already exists, a recorder and a replayer are two more
implementations of it rather than a rewrite.

WHAT IS RECORDED
Both sides of every call. The guidance is explicit that "any subprocess
execution must be traced with both the request and response", because "recording
tool inputs and outputs eliminates the need to query the real system during
replay".

WHAT REPLAY IS FOR
  A verdict can be re-derived from the evidence that produced it. "Did this
  conclusion follow from these observations?" becomes answerable rather than
  assertable.

  A policy change can be tested against real recorded machines instead of
  invented ones -- the strongest use, since a fake reflects what its author
  imagined and a recording reflects a machine that existed.

  A broken installation can be diagnosed without access to it. The bundle
  travels; the laptop does not.

WHAT REPLAY IS NOT
It reproduces the OBSERVATION, not the machine. A bundle recorded before a
change and replayed after gives the old verdict, correctly -- it is evidence of
what was true then. Treating a replay as a current health check would be
exactly the stale-cache mistake the probes were just hardened against.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from collections.abc import Mapping
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from nix_remediation import ActionableError
from nix_system import CommandResult, System

__all__ = [
    "EvidenceBundle",
    "RecordingSystem",
    "ReplaySystem",
    "UnrecordedCallError",
    "bundle_digest",
]


class UnrecordedCallError(ActionableError):
    """Replay was asked for something the recording does not contain.

    FAILS RATHER THAN GUESSING. A replayer that invented a plausible answer
    would produce a verdict from data that never existed -- which is worse than
    no replay, because it looks like evidence.

    ActionableError, AND IT TOOK A BETTER GUARD TO NOTICE. This was written as
    a RuntimeError before ActionableError existed, and the classification test
    walked ActionableError.__subclasses__() -- so it was never in that tree and
    never checked. The second straggler found by parsing the source instead of
    walking the hierarchy.
    """

    code = "ERR_NIX_EVIDENCE_UNRECORDED"


# WHERE THIS PLATFORM PUTS TEMPORARY FILES, asked rather than assumed.
#
# Hardcoding ("/tmp/", "/var/folders/") drew a linter complaint about insecure
# temp usage -- a false positive, since these only RECOGNISE paths and never
# create them. But deriving the answer is better regardless: macOS uses
# /var/folders, Linux /tmp, and a hardcoded list would be wrong on the next
# platform rather than merely noisy.
#
# The realpath variant is included because macOS reports /var/folders while the
# canonical path is /private/var/folders, and a probe path may arrive as either.
def _ephemeral_prefixes() -> tuple[str, ...]:
    root = tempfile.gettempdir()
    resolved = str(Path(root).resolve())
    return tuple(sorted({root.rstrip("/") + "/", resolved.rstrip("/") + "/"}))


EPHEMERAL_PREFIXES = _ephemeral_prefixes()


def _is_ephemeral(value: str) -> bool:
    return value.startswith(EPHEMERAL_PREFIXES)


class EvidenceBundle(BaseModel):
    """Every answer the boundary gave during one observation.

    Keyed by call, so replay is a lookup rather than a re-execution. Frozen
    because evidence that can be edited after the fact is not evidence.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    commands: dict[str, CommandResult] = Field(default_factory=dict)
    directories: dict[str, bool] = Field(default_factory=dict)
    files: dict[str, bool] = Field(default_factory=dict)
    executables: dict[str, bool] = Field(default_factory=dict)
    resolutions: dict[str, str] = Field(default_factory=dict)
    file_contents: dict[str, str] = Field(default_factory=dict)
    writable: dict[str, bool] = Field(default_factory=dict)
    owners: dict[str, tuple[str, int]] = Field(default_factory=dict)
    groups: dict[str, tuple[int, tuple[str, ...]] | None] = Field(default_factory=dict)
    shells: dict[str, str | None] = Field(default_factory=dict)
    platform: str = Field(default="", description="The system double at recording time")

    @staticmethod
    def key(*args: object) -> str:
        """A stable key for a call.

        The argv joined by NUL, which cannot appear in an argument -- a space
        separator would collide between ("a b",) and ("a", "b").

        EPHEMERAL PATHS ARE NORMALISED, and forgetting this broke replay
        entirely. The flake probe passes a fresh mkdtemp path as a POSITIONAL
        ARGUMENT, so the key differed on every run and no recording could ever
        be replayed. Excluding cwd was not enough; the path is in the argv.

        Which temporary directory was used is not part of what the probe
        observed -- the probe observed whether a trivial flake evaluates. The
        placeholder keeps the argument's POSITION, so a command that gained or
        lost one would still fail to match.
        """
        return "\\x00".join(
            "<tmp>" if _is_ephemeral(str(argument)) else str(argument) for argument in args
        )


class RecordingSystem:
    """Wraps a real System and records both sides of every call.

    Does not inherit from System: structural typing means having the methods is
    enough, and inheriting would defeat the Protocol.
    """

    def __init__(self, inner: System) -> None:
        self._inner = inner
        self._commands: dict[str, CommandResult] = {}
        self._directories: dict[str, bool] = {}
        self._files: dict[str, bool] = {}
        self._executables: dict[str, bool] = {}
        self._resolutions: dict[str, str] = {}
        self._file_contents: dict[str, str] = {}
        self._writable: dict[str, bool] = {}
        self._owners: dict[str, tuple[str, int]] = {}
        self._groups: dict[str, tuple[int, tuple[str, ...]] | None] = {}
        self._shells: dict[str, str | None] = {}
        # THE PLATFORM IS PART OF THE EVIDENCE. A bundle recorded on Darwin and
        # replayed without it would be judged by whatever platform the replaying
        # machine happened to be -- which is exactly the machine-dependence
        # record-and-replay exists to remove.
        self._platform = ""

    def bundle(self) -> EvidenceBundle:
        return EvidenceBundle(
            commands=dict(self._commands),
            directories=dict(self._directories),
            files=dict(self._files),
            executables=dict(self._executables),
            resolutions=dict(self._resolutions),
            file_contents=dict(self._file_contents),
            writable=dict(self._writable),
            owners=dict(self._owners),
            groups=dict(self._groups),
            shells=dict(self._shells),
            platform=self._platform,
        )

    def run(self, *args: str | Path, cwd: Path | None = None) -> CommandResult:
        result = self._inner.run(*args, cwd=cwd)
        # NOT keyed on cwd: the flake probe uses a fresh temp directory each
        # run, so including it would make every recording unreplayable.
        self._commands[EvidenceBundle.key(*args)] = result
        return result

    def is_dir(self, path: Path) -> bool:
        answer = self._inner.is_dir(path)
        self._directories[str(path)] = answer
        return answer

    def is_file(self, path: Path) -> bool:
        answer = self._inner.is_file(path)
        self._files[str(path)] = answer
        return answer

    def is_executable_file(self, path: Path) -> bool:
        answer = self._inner.is_executable_file(path)
        self._executables[str(path)] = answer
        return answer

    def resolve(self, path: Path) -> Path:
        answer = self._inner.resolve(path)
        self._resolutions[str(path)] = str(answer)
        return answer

    def read_text(self, path: Path) -> str:
        answer = self._inner.read_text(path)
        self._file_contents[str(path)] = answer
        return answer

    def is_writable_by_me(self, path: Path) -> bool:
        answer = self._inner.is_writable_by_me(path)
        self._writable[str(path)] = answer
        return answer

    def owner_and_mode(self, path: Path) -> tuple[str, int]:
        answer = self._inner.owner_and_mode(path)
        self._owners[str(path)] = answer
        return answer

    def group_members(self, name: str) -> tuple[int, tuple[str, ...]] | None:
        answer = self._inner.group_members(name)
        self._groups[name] = answer
        return answer

    def user_shell(self, name: str) -> str | None:
        answer = self._inner.user_shell(name)
        self._shells[name] = answer
        return answer

    def platform_double(self) -> str:
        answer = self._inner.platform_double()
        self._platform = answer
        return answer

    def write_probe_flake(self, directory: Path) -> None:
        """Recorded as a no-op: it is an OUTPUT, not a source of nondeterminism.

        Replay must not write anything -- a replayed observation that touched
        the filesystem would not be a replay.
        """
        self._inner.write_probe_flake(directory)


class ReplaySystem:
    """Answers from a bundle, touching nothing.

    Every miss raises. A replayer that guessed would produce a verdict from data
    that never existed, which looks like evidence and is not.
    """

    def __init__(self, bundle: EvidenceBundle) -> None:
        self._bundle = bundle

    def _lookup[V](self, table: Mapping[str, V], key: str, what: str) -> V:
        if key not in table:
            raise UnrecordedCallError(
                f"{what} {key!r} is not in the evidence bundle",
                remediation="The bundle was recorded by a run that never made this "
                "call. Re-record against the machine being replayed.",
                call=what,
            )
        return table[key]

    def run(self, *args: str | Path, cwd: Path | None = None) -> CommandResult:
        return self._lookup(self._bundle.commands, EvidenceBundle.key(*args), "command")

    def is_dir(self, path: Path) -> bool:
        return bool(self._lookup(self._bundle.directories, str(path), "is_dir"))

    def is_file(self, path: Path) -> bool:
        return bool(self._lookup(self._bundle.files, str(path), "is_file"))

    def is_executable_file(self, path: Path) -> bool:
        return bool(self._lookup(self._bundle.executables, str(path), "is_executable_file"))

    def resolve(self, path: Path) -> Path:
        return Path(self._lookup(self._bundle.resolutions, str(path), "resolve"))

    def read_text(self, path: Path) -> str:
        return str(self._lookup(self._bundle.file_contents, str(path), "read_text"))

    def is_writable_by_me(self, path: Path) -> bool:
        return bool(self._lookup(self._bundle.writable, str(path), "is_writable_by_me"))

    def owner_and_mode(self, path: Path) -> tuple[str, int]:
        owner, mode = self._lookup(self._bundle.owners, str(path), "owner_and_mode")
        return str(owner), int(mode)

    def group_members(self, name: str) -> tuple[int, tuple[str, ...]] | None:
        recorded = self._lookup(self._bundle.groups, name, "group_members")
        if recorded is None:
            return None
        gid, members = recorded
        return int(gid), tuple(str(member) for member in members)

    def user_shell(self, name: str) -> str | None:
        recorded = self._lookup(self._bundle.shells, name, "user_shell")
        return None if recorded is None else str(recorded)

    def platform_double(self) -> str:
        """From the bundle, not from the replaying machine.

        Reading the local platform here would judge a recorded Darwin machine by
        the platform of whatever host replays it -- reintroducing exactly the
        machine-dependence this exists to remove.
        """
        if not self._bundle.platform:
            raise UnrecordedCallError(
                "the bundle records no platform",
                remediation="Bundles recorded before the platform field existed "
                "cannot be replayed safely; re-record to capture it.",
            )
        return self._bundle.platform

    def write_probe_flake(self, directory: Path) -> None:
        """Deliberately does nothing. A replay writes to no filesystem."""


def bundle_digest(path: Path) -> str:
    """SHA-256 of the bundle AS WRITTEN, for a record to bind itself to.

    THE LEDGER AND THE BUNDLE WERE TWO HALVES OF ONE RECORD WITH NO LINK.
    An entry said a run happened and what it concluded; a bundle said what that
    run saw. Given an entry you could not find its bundle, and given a bundle
    you could not tell which entry it belonged to.

    A DIGEST, NOT A PATH OR AN ID. The in-toto statement binds a record to its
    subject as {"name": ..., "digest": {"sha256": ...}}, because a path can be
    reused and an id can be copied -- only a hash stops matching when the bytes
    change. A swapped or edited bundle fails the binding.

    THE BUNDLE IS KEPT, NOT REPLACED BY ITS HASH. The warning is explicit:
    "deleting the underlying transcript after keeping only its hash proves too
    little for most investigations -- the hash can show that a later transcript
    matches the committed bytes, but it cannot reconstruct those bytes."

    RAW BYTES RATHER THAN RFC 8785 CANONICAL JSON, DELIBERATELY.
    JCS exists because "data is exchanged in its original form on the wire
    while cryptographic operations are performed on the canonicalized
    counterpart in the producer and consumer endpoints" -- a boundary this data
    never crosses. The bundle is written here and read back here.

    And if something DOES re-serialise it, that is a different file, and a
    digest describing the original should stop matching. Python has no JCS in
    the standard library, so adopting it would add a dependency for a guarantee
    this flow does not need. save_bundle writes deterministically instead,
    which is the part of JCS that actually applies.
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_bundle(path: Path) -> EvidenceBundle:
    return EvidenceBundle.model_validate_json(path.read_text(encoding="utf-8"))


def save_bundle(bundle: EvidenceBundle, path: Path) -> None:
    # sort_keys SO THE SAME BUNDLE ALWAYS PRODUCES THE SAME BYTES.
    # Without it, dict ordering could vary between runs and a digest would
    # differ for identical content -- reporting tampering that never happened.
    # This is the part of RFC 8785 that applies here; the rest solves a
    # cross-implementation problem this data does not have.
    path.write_text(
        json.dumps(bundle.model_dump(mode="json"), indent=2, sort_keys=True),
        encoding="utf-8",
    )
