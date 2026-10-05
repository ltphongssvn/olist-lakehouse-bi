"""Correlation and timing metadata for a single contract run.

WHY PROPAGATE RATHER THAN INVENT
A trace id this process makes up correlates with nothing. The standard is to
read one a caller already established: OpenTelemetry specifies environment
variables as context carriers, and real systems do exactly this -- an agent SDK
"injects TRACEPARENT and TRACESTATE into the child process environment, and the
CLI reads them so its span becomes a child of your span".

So TRACEPARENT is read when present and reported as null when absent. Absent is
the honest answer for a run nobody traced.

WHY THERE IS A run_id ANYWAY
Correlation still has to work without a tracer. A run id groups the lines of one
invocation when several are aggregated, and costs nothing when nothing reads it.

WHY THERE IS NO HOSTNAME
The obvious field, and this machine's is "thanhphongle-MacBookPro" -- it
contains a person's name. This repository runs a PII scanner precisely to keep
identifying data out of committed artifacts, and emitting a hostname into a JSON
document destined for logs would plant PII deliberately.

If a fleet ever needs to distinguish machines, an opaque per-machine identifier
derived and stored locally is the shape to use -- not the name the person gave
their laptop.

WHY DURATION IS MEASURED
A `nix eval` that succeeds in thirty seconds is a signal -- a daemon under
strain, a cold cache -- that a boolean cannot carry. It is the difference
between "it worked" and "it worked, barely".
"""

from __future__ import annotations

import os
import re
import time
import uuid
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from nix_system import CommandResult

__all__ = [
    "MAX_PROBE_STDERR",
    "ProbeRecord",
    "RunMetadata",
    "Timer",
    "parse_traceparent",
]

# W3C Trace Context: version-traceid-spanid-flags, all lowercase hex.
# Anchored, because a partial match on malformed input is worse than no match:
# it would report a trace id that correlates with nothing.
TRACEPARENT_PATTERN = re.compile(
    r"^(?P<version>[0-9a-f]{2})-(?P<trace_id>[0-9a-f]{32})-"
    r"(?P<span_id>[0-9a-f]{16})-(?P<flags>[0-9a-f]{2})$"
)


def parse_traceparent(value: str | None) -> tuple[str | None, str | None]:
    """Extract (trace_id, parent_span_id) from a W3C traceparent header.

    Returns (None, None) for anything malformed. A trace id that does not parse
    is not a trace id, and reporting a fragment would produce orphaned spans --
    the documented symptom of broken propagation.
    """
    if not value:
        return None, None

    match = TRACEPARENT_PATTERN.match(value.strip())
    if match is None:
        return None, None

    # Version ff is forbidden by the spec, and an all-zero id is the "invalid"
    # sentinel rather than a real identifier.
    if match["version"] == "ff":
        return None, None
    if set(match["trace_id"]) == {"0"} or set(match["span_id"]) == {"0"}:
        return None, None

    return match["trace_id"], match["span_id"]


# Per probe, not per document. A trace whose useful part is at the end is
# common in Nix; a mean cap discards exactly the part that explains the failure.
MAX_PROBE_STDERR = 2000


class ProbeRecord(BaseModel):
    """One command this contract ran, and what it did.

    WHY EVERY PROBE IS RECORDED, INCLUDING THE ONES THAT SUCCEEDED
    A contract that reports only conclusions cannot be audited. With this, a
    reader can see WHICH commands produced the verdict -- and a slow success
    ("`nix eval` took 30s") is a signal a boolean cannot carry.

    TRUNCATION IS EVIDENCE, NOT SILENCE
    `truncated` is recorded rather than left implicit, so a reader can tell a
    short error from a cut one. A production runner names this requirement
    exactly: "bounded stdout/stderr capture WITH TRUNCATION EVIDENCE".

    ARGV IS RECORDED, AND THAT IS SAFE HERE SPECIFICALLY
    Argument redaction matters wherever a command receives a secret. These are
    fixed `nix` invocations with store paths, run in an environment CONSTRUCTED
    rather than inherited -- nothing sensitive is passed in to echo back. That
    reasoning does not survive a command taking a credential as an argument, and
    redaction must come first if one is ever added.
    """

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    name: str = Field(description="What this probe was for, not what it ran")
    argv: tuple[str, ...]
    exit_code: int
    duration_ms: int
    stdout: str = ""
    """WHAT THE COMMAND RETURNED, not only what it complained about.

    The transcript recorded argv, exit code, duration and stderr -- three of the
    four facts a behaviour record needs, the fourth being stdout. Without it a
    reader can see that `nix --version` ran and cannot see the string that
    became semantic_version.

    The gap is named precisely elsewhere: "if only execution units are recorded,
    the system may know that a tool was called but not whether its output
    actually supported the final answer."
    """
    stderr: str = ""
    truncated: bool = False

    @property
    def succeeded(self) -> bool:
        return self.exit_code == 0

    @classmethod
    def of(cls, name: str, result: CommandResult) -> ProbeRecord:
        err = (result.stderr or "").strip()
        out = (result.stdout or "").strip()

        # BOTH STREAMS ARE BOUNDED, and truncation of EITHER is reported, so a
        # reader can tell a short output from a cut one.
        err_cut = len(err) > MAX_PROBE_STDERR
        out_cut = len(out) > MAX_PROBE_STDERR

        return cls(
            name=name,
            argv=result.argv,
            exit_code=result.returncode,
            duration_ms=result.duration_ms,
            stdout=out[:MAX_PROBE_STDERR] if out_cut else out,
            stderr=err[:MAX_PROBE_STDERR] if err_cut else err,
            truncated=err_cut or out_cut,
        )


class RunMetadata(BaseModel):
    """Who asked, when, and how long it took."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    run_id: str = Field(description="Unique to this invocation")
    observed_at: str = Field(description="RFC 3339, UTC")
    duration_ms: int = Field(description="How long the observation took")
    trace_id: str | None = Field(
        default=None, description="From an inherited TRACEPARENT, never invented"
    )
    parent_span_id: str | None = Field(default=None, description="From TRACEPARENT")

    @classmethod
    def create(cls, duration_ms: int) -> RunMetadata:
        trace_id, parent_span_id = parse_traceparent(os.environ.get("TRACEPARENT"))
        return cls(
            run_id=str(uuid.uuid4()),
            # UTC and RFC 3339. A local timestamp is ambiguous the moment two
            # machines in different zones report the same incident.
            observed_at=datetime.now(UTC).isoformat(timespec="seconds"),
            duration_ms=duration_ms,
            trace_id=trace_id,
            parent_span_id=parent_span_id,
        )


class Timer:
    """Measure a block with the monotonic clock.

    MONOTONIC, NOT wall clock: a wall clock can move backwards -- NTP
    correction, daylight saving -- and produce a negative duration. The
    timestamp above is wall clock because it answers a different question.
    """

    def __init__(self) -> None:
        self._started = time.monotonic()

    @property
    def elapsed_ms(self) -> int:
        return int((time.monotonic() - self._started) * 1000)
