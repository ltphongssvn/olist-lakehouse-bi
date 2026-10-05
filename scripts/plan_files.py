# scripts/plan_files.py
"""Read the plan, its trace and its id ledger, and name every way they disagree.

    plan.toml  x  plan-trace.toml  x  plan-ids.toml  ->  agreement, or the gaps

A MATRIX NOBODY VERIFIES IS AN ARCHIVE. Four disagreements are named: an item
no source authorises, a claim about an item the plan no longer holds, an id the
ledger never issued, and a retired id back in use.

TOML, READ BY THE STANDARD LIBRARY. These files are written and annotated by a
person, and TOML coerces nothing implicitly; YAML would have added a parser this
repository never needed, whose usual default reads `no` as false.
"""

from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path

from command_outcome import CommandOutcome
from gitenv import git
from plan_models import IdLedger, PlanTrace, ProjectPlan, untraced

ROOT = Path(__file__).resolve().parent.parent
CONTEXT = Path("context")


def load(root: Path = ROOT) -> tuple[ProjectPlan, PlanTrace, IdLedger]:
    """The three files, each parsed straight into its own contract."""
    context = root / CONTEXT
    return (
        ProjectPlan.model_validate(
            tomllib.loads((context / "plan.toml").read_text(encoding="utf-8"))
        ),
        PlanTrace.model_validate(
            tomllib.loads((context / "plan-trace.toml").read_text(encoding="utf-8"))
        ),
        IdLedger.model_validate(
            tomllib.loads((context / "plan-ids.toml").read_text(encoding="utf-8"))
        ),
    )


def disagreements(plan: ProjectPlan, trace: PlanTrace, ids: IdLedger) -> list[str]:
    """Every way the three files fail to agree, named."""
    problems = untraced(trace, plan)
    issued = {entry.id: entry for entry in ids.issued}
    # EACH ID FROM ITS OWN TYPED COLLECTION. Unpacking steps and decisions into
    # one tuple joins them to their shared base, which declares no id at all.
    in_use = [step.id for step in plan.steps] + [decision.id for decision in plan.decisions]
    for item in in_use:
        entry = issued.get(item)
        if entry is None:
            problems.append(f"{item} is in use but was never issued")
        elif entry.retired:
            problems.append(f"{item} was retired and is back in use")
    return problems


def commit_subject(ref: str, root: Path = ROOT) -> str | None:
    """A commit's own subject, or None when the ref names no commit here.

    THE HISTORY IS QUOTED, NEVER AUTHORED: a backfilled source is checked
    against the commit it cites, so a paraphrase cannot pass for a quotation.
    """
    shown = git("show", "-s", "--format=%s", f"{ref}^{{commit}}", cwd=root)
    return shown.stdout.rstrip("\n") if shown.returncode == 0 else None


def main() -> int:
    """plan:trace -- whether the three files agree, as a command-outcome envelope.

    REFUSED, NOT FAILED, when they disagree: the command worked and declined,
    which is a rule rather than a crash, and the exit code says so.
    """
    plan, trace, ids = load()
    problems = disagreements(plan, trace, ids)
    outcome = CommandOutcome.model_validate(
        {
            "command": "plan:trace",
            "outcome": "refused" if problems else "success",
            "code": "plan_disagrees" if problems else "plan_agrees",
            "message": (
                f"{len(problems)} disagreement(s) between the plan, its trace and its ids"
                if problems
                else f"{len(plan.steps)} steps and {len(plan.decisions)} decisions, "
                "every one traced and issued"
            ),
            "data": {
                "steps": len(plan.steps),
                "decisions": len(plan.decisions),
                "candidates": len(trace.candidates),
                "disagreements": problems,
            },
        }
    )
    print(json.dumps(outcome.model_dump(), indent=2))
    return outcome.exit_code


if __name__ == "__main__":
    sys.exit(main())
