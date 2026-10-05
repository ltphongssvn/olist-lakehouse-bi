"""The requirement matrix: one row per id, change and requirement traced both ways.

DERIVED, NEVER WRITTEN BY HAND. The plan, its trace, the status the policy
decided and every commit on develop are joined here; the rules are in
policies/plan/matrix.rego, so this only observes.

PORTED FROM otsafety-gnn WITHOUT ITS FILE MARKERS. That builder confirmed a file
by a pytest requirement marker, which this repository never adopted; stamping
markers into existing files now would be authoring history after the fact. The
matrix keeps the purpose that ports: traceability in both directions.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from command_outcome import CommandOutcome
from opa import denials
from plan_files import load
from plan_models import Requirement, RequirementMatrix, TracedCommit
from plan_status import decide, gather
from plan_trailers import log_commits

ROOT = Path(__file__).resolve().parent.parent
REF = "origin/develop"
RECORDS = ROOT / ".artifacts" / "plan-matrix"


def build(root: Path = ROOT, ref: str = REF) -> RequirementMatrix:
    """Every requirement and every commit on the ref, each with what traces it."""
    plan, trace, _ = load(root)
    status = decide(gather(root, ref))

    justified: dict[str, list[str]] = {}
    cited: set[str] = set()
    for candidate in trace.candidates:
        for target in candidate.maps_to:
            justified.setdefault(target, []).append(f"{candidate.source}:{candidate.ref}")
        if candidate.source == "HISTORY":
            cited.add(candidate.ref)

    references: dict[str, list[str]] = {}
    commits: list[TracedCommit] = []
    for commit in log_commits(root, ref):
        for step in commit.steps:
            references.setdefault(step, []).append(commit.sha[:9])
        commits.append(
            TracedCommit(
                sha=commit.sha,
                subject=commit.subject,
                merge=commit.merge,
                steps=commit.steps,
                cited=any(commit.sha.startswith(short) for short in cited),
            )
        )

    rows = [
        Requirement(
            id=step.id,
            title=step.title,
            kind="step",
            state=status.steps[step.id].state,
            justified_by=tuple(justified.get(step.id, ())),
            referenced_by=tuple(references.get(step.id, ())),
        )
        for step in plan.steps
    ] + [
        Requirement(
            id=decision.id,
            title=decision.title,
            kind="decision",
            state=None,
            justified_by=tuple(justified.get(decision.id, ())),
            referenced_by=tuple(references.get(decision.id, ())),
        )
        for decision in plan.decisions
    ]
    return RequirementMatrix(ref=ref, requirements=tuple(rows), commits=tuple(commits))


def main() -> int:
    """plan:matrix -- derive, record, and report what fails to trace."""
    matrix = build()
    RECORDS.mkdir(parents=True, exist_ok=True)
    record = RECORDS / f"{datetime.now(UTC):%Y%m%dT%H%M%S%fZ}.json"
    record.write_text(matrix.model_dump_json(indent=2) + "\n", encoding="utf-8")
    payload = {"requirement_matrix": matrix.model_dump(mode="json")}
    problems = [d for d in denials("data.plan.deny", payload) if d.startswith("[ERR_MATRIX_")]
    outcome = CommandOutcome.model_validate(
        {
            "command": "plan:matrix",
            "outcome": "refused" if problems else "success",
            "code": "matrix_untraced" if problems else "matrix_traced",
            "message": (
                f"{len(problems)} untraced link(s) on {matrix.ref}"
                if problems
                else f"{len(matrix.requirements)} requirements and {len(matrix.commits)} "
                f"commits on {matrix.ref}, traced both ways"
            ),
            "data": {"record": str(record.relative_to(ROOT)), "problems": problems},
        }
    )
    print(json.dumps(outcome.model_dump(), indent=2))
    return outcome.exit_code


if __name__ == "__main__":
    sys.exit(main())
