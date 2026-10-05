# scripts/plan_init.py
"""A project starts its own plan by task (D.53).

A project generated from the platform template carries no plan: it would otherwise
inherit the source's history as its own. plan:init writes a day-one plan, its trace
and its id ledger -- one thread, one step, one source -- validated together through
project-plan/v1, id-ledger/v1 and plan-trace/v1 before any is written, as plan:add
writes. It refuses when any plan file exists: a plan is extended, never reset.

THE SHAPES plan:add EXPECTS: steps an array of tables, issued and candidates inline
arrays, so plan:add and plan:amend work on the new project from its first commit.
"""

from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path

from command_outcome import CommandOutcome
from plan_models import IdLedger, PlanTrace, ProjectPlan

ROOT = Path(__file__).resolve().parent.parent
PLAN, IDS, TRACE = (
    Path("context/plan.toml"),
    Path("context/plan-ids.toml"),
    Path("context/plan-trace.toml"),
)

DAY_ONE_PLAN = """\
# context/plan.toml
# This project's plan: intent only, never status (project-plan/v1). plan:status decides
# each step's state from its evidence; plan:add and plan:amend are its only writers.
contract = "project-plan/v1"

threads = [
  { id = "A", title = "Platform" },
]

[[steps]]
id = "A.1"
title = "The project is generated from the platform template"
thread = "A"
done_when = [
  { kind = "task", name = "identity:set" },
  { kind = "task", name = "plan:init" },
]
"""

DAY_ONE_IDS = """\
# context/plan-ids.toml
# Every id this plan has issued, append-only (id-ledger/v1): none is ever reused.
contract = "id-ledger/v1"
issued = [
  { id = "A.1", first_title = "The project is generated from the platform template" },
]
"""

DAY_ONE_TRACE = """\
# context/plan-trace.toml
# Where every plan item came from (plan-trace/v1), traced in both directions.
contract = "plan-trace/v1"
candidates = [
  { source = "TEMPLATE", ref = "day one", text = "its own plan, from day one", maps_to = ["A.1"] },
]

[[sources]]
id = "TEMPLATE"
title = "the platform template this project was generated from"
locator = ".copier-answers.yml"
"""


def _report(outcome: str, code: str, message: str, data: dict[str, object]) -> int:
    envelope = CommandOutcome.model_validate(
        {
            "command": "plan:init",
            "outcome": outcome,
            "code": code,
            "message": message,
            "data": data,
        }
    )
    print(json.dumps(envelope.model_dump(), indent=2))
    return envelope.exit_code


def write_day_one(root: Path) -> list[str]:
    """The day-one plan, trace and id ledger, validated together, then written (D.61).

    template:init calls this so a project is born with its plan in its first commit;
    plan:init calls it for a project that has none. Neither prints from here.
    """
    ProjectPlan.model_validate(tomllib.loads(DAY_ONE_PLAN))
    IdLedger.model_validate(tomllib.loads(DAY_ONE_IDS))
    PlanTrace.model_validate(tomllib.loads(DAY_ONE_TRACE))
    (root / PLAN).parent.mkdir(parents=True, exist_ok=True)
    for path, text in ((PLAN, DAY_ONE_PLAN), (IDS, DAY_ONE_IDS), (TRACE, DAY_ONE_TRACE)):
        (root / path).write_text(text, encoding="utf-8")
    return [str(path) for path in (PLAN, IDS, TRACE)]


def init(*, root: Path = ROOT) -> int:
    """plan:init -- a day-one plan, trace and id ledger, together or not at all."""
    present = [str(path) for path in (PLAN, IDS, TRACE) if (root / path).exists()]
    if present:
        message = f"a plan already exists: {', '.join(present)}"
        return _report("refused", "plan_exists", message, {"present": present})
    written = write_day_one(root)
    return _report("success", "plan_initialised", "day-one plan written", {"files": written})


if __name__ == "__main__":
    sys.exit(init())
