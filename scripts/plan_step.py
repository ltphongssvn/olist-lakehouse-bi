# scripts/plan_step.py
"""Read one plan step as data: validated, and exactly as written (D.22).

TWO VIEWS, ONE DOCUMENT. plan-step/v1 carries the step as ProjectPlan validates it
-- what the step contains -- and its block exactly as written, with line numbers
-- what an edit must anchor on. Reading a step by hand twice, and an edit refused
on a formatting difference, is what made this a task.
"""

from __future__ import annotations

import json
import sys
import tomllib
from collections.abc import Sequence
from pathlib import Path
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, PositiveInt

from command_outcome import CommandOutcome
from plan_models import ProjectPlan

ROOT = Path(__file__).resolve().parent.parent
PLAN = Path("context") / "plan.toml"
HEADERS = ("[[steps]]", "[[decisions]]")


class PlanStepView(BaseModel):
    """plan-step/v1: one step, validated and as written."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    CONTRACT_ID: ClassVar[str] = "plan-step/v1"

    contract: Literal["plan-step/v1"] = "plan-step/v1"
    file: str
    first_line: PositiveInt
    last_line: PositiveInt
    step: dict[str, JsonValue]
    block: tuple[str, ...] = Field(min_length=2)


def read_step(root: Path, step_id: str) -> PlanStepView:
    """The entry -- a step or a decision -- validated, and its block as written.

    SEARCHED SEPARATELY. Merging steps and decisions into one sequence made mypy infer
    their join, a common base without `id`; each search here is over one concrete type.
    """
    text = (root / PLAN).read_text(encoding="utf-8")
    plan = ProjectPlan.model_validate(tomllib.loads(text))
    found = next((s.model_dump(mode="json") for s in plan.steps if s.id == step_id), None)
    if found is None:
        found = next((d.model_dump(mode="json") for d in plan.decisions if d.id == step_id), None)
    if found is None:
        raise LookupError(step_id)
    lines = text.splitlines()
    marker = f'id = "{step_id}"'
    index = next(
        i for i, line in enumerate(lines) if line == marker and i and lines[i - 1] in HEADERS
    )
    start = index - 1
    end = next((i for i in range(index + 1, len(lines)) if lines[i] in HEADERS), len(lines))
    while end > start and not lines[end - 1].strip():
        end -= 1
    return PlanStepView(
        file=str(PLAN),
        first_line=start + 1,
        last_line=end,
        step=found,
        block=tuple(lines[start:end]),
    )


def main(argv: Sequence[str] | None = None, *, root: Path = ROOT) -> int:
    """plan:step <id> -- the step as plan-step/v1, or a refusal for an unknown id."""
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        raise SystemExit("usage: mise run run plan:step <id>, e.g. D.12")
    step_id = args[0]
    try:
        view = read_step(root, step_id)
    except LookupError:
        envelope = CommandOutcome.model_validate(
            {
                "command": "plan:step",
                "outcome": "refused",
                "code": "step_unknown",
                "message": f"{step_id} is not a step in {PLAN}",
                "data": {"id": step_id},
            }
        )
    else:
        envelope = CommandOutcome.model_validate(
            {
                "command": "plan:step",
                "outcome": "success",
                "code": "step_read",
                "message": f"{step_id}: lines {view.first_line}-{view.last_line} of {PLAN}",
                "data": view.model_dump(mode="json"),
            }
        )
    print(json.dumps(envelope.model_dump(), indent=2))
    return envelope.exit_code


if __name__ == "__main__":
    sys.exit(main())
