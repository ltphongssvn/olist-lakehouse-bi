# scripts/export_copy.py
"""Copy a released assignment's HTML export out of the repository, verified (D.21).

THE PAIR. export-copy/v1 records the assignment, its newest release tag, the source
and destination and both digests; export.copy refuses an unreleased assignment, a
missing export, an existing destination and a copy that differs from its source.
The policy is asked before anything is written, and again after the copy.

NEVER OVERWRITES. The copy is opened in exclusive-create mode, so even a file that
appears between the check and the write is left alone. Named for its tag -- for
example assignment_02_etl_assignment-02-v1.html -- so a released file cannot be
mistaken for a draft. Run through `mise run run`, which records it.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field

from command_outcome import CommandOutcome
from gitenv import git
from opa import denials

ROOT = Path(__file__).resolve().parent.parent
HASH = r"^[0-9a-f]{64}$"


class ExportCopy(BaseModel):
    """export-copy/v1: one copy of a released export, before and after."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    CONTRACT_ID: ClassVar[str] = "export-copy/v1"

    contract: Literal["export-copy/v1"] = "export-copy/v1"
    assignment: str = Field(min_length=1)
    tag: str | None
    source: str
    destination: str
    source_exists: bool
    destination_existed: bool
    source_sha256: str | None = Field(default=None, pattern=HASH)
    copy_sha256: str | None = Field(default=None, pattern=HASH)


def latest_tag(root: Path, assignment: str) -> str | None:
    """The newest <assignment>-vN tag, in version order so v10 follows v9."""
    listed = git("tag", "--list", f"{assignment}-v*", "--sort=-v:refname", cwd=root).stdout.split()
    return listed[0] if listed else None


def _source(root: Path, assignment: str) -> Path | None:
    exports = root / "assignments" / assignment / "exports"
    found = sorted(exports.glob("*.html")) if exports.is_dir() else []
    return found[0] if len(found) == 1 else None


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _refusals(copy: ExportCopy) -> list[str]:
    return denials("data.export.copy.deny", {"export_copy": copy.model_dump(mode="json")})


def _report(copy: ExportCopy, outcome: str, code: str, problems: list[str]) -> int:
    message = f"copied to {copy.destination}" if outcome == "success" else "; ".join(problems)
    envelope = CommandOutcome.model_validate(
        {
            "command": "export:copy",
            "outcome": outcome,
            "code": code,
            "message": message,
            "data": copy.model_dump(mode="json"),
        }
    )
    print(json.dumps(envelope.model_dump(), indent=2))
    return envelope.exit_code


def main(
    argv: Sequence[str] | None = None,
    *,
    root: Path = ROOT,
    downloads: Path | None = None,
) -> int:
    """export:copy <assignment> -- refuse, or copy and verify."""
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        raise SystemExit("usage: mise run run export:copy <assignment>, e.g. assignment-02")
    assignment = args[0]
    folder = downloads or Path.home() / "Downloads"
    tag = latest_tag(root, assignment)
    source = _source(root, assignment)
    name = (
        f"{source.stem}_{tag}.html"
        if source is not None and tag
        else f"{assignment}_unreleased.html"
    )
    destination = folder / name

    before = ExportCopy(
        assignment=assignment,
        tag=tag,
        source=str(source if source is not None else root / "assignments" / assignment / "exports"),
        destination=str(destination),
        source_exists=source is not None,
        destination_existed=destination.exists(),
        source_sha256=_digest(source) if source is not None else None,
    )
    problems = _refusals(before)
    if problems or source is None:
        return _report(before, "refused", "export_copy_refused", problems)

    # EXCLUSIVE CREATE: a file that appeared since the check is never overwritten.
    with destination.open("xb") as handle:
        handle.write(source.read_bytes())
    after = before.model_copy(update={"copy_sha256": _digest(destination)})
    problems = _refusals(after)
    if problems:
        return _report(after, "failed", "export_copy_mismatch", problems)
    return _report(after, "success", "export_copied", [])


if __name__ == "__main__":
    sys.exit(main())
