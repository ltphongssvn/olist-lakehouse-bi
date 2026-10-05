"""Decide each step's status by policy, from facts observed on the integration branch.

THE PAIR. This module observes: what holds on the ref, as plan-facts/v1.
policies/plan decides each step's state. plan-status/v1 validates the decision
on its way back, because OPA's output crosses a boundary like any other.

OBSERVED ON THE REF, NEVER THE DISK. An uncommitted file must not make a step
look done, so paths, tasks and test functions are read from the ref itself.

A PROOF IS A DEFINED TEST. The source this is ported from checked only that the
test FILE was in the tree, though its own comment promised the named function;
a renamed test went on reading as proof. Here the function must be defined.

UNOBSERVED IS NOT ABSENT. Merged pull requests come from GitHub, which tests and
offline gates cannot reach; unless a reader is passed in, that kind is recorded
as blind, and the policy leaves such a step unknown rather than undone.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
import tomllib
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, JsonValue, RootModel

from command_outcome import CommandOutcome
from gitenv import git
from opa import query
from plan_files import load
from plan_models import Facts, Kind, PlanFacts, PlanStatus
from plan_render import render

ROOT = Path(__file__).resolve().parent.parent
POLICIES = ROOT / "policies"
RECORDS = ROOT / ".artifacts" / "plan-status"
BASE_REFS = frozenset(
    {"HEAD", "origin/HEAD", "origin", "main", "origin/main", "develop", "origin/develop"}
)


class _MiseTasks(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")
    tasks: dict[str, JsonValue] = Field(default_factory=dict)


class _Pr(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")
    number: int


class _MergedPrs(RootModel[tuple[_Pr, ...]]):
    """gh pr list answers with a top-level array."""


def defined_tests(path: str, source: str) -> set[str]:
    """Every module-level test function a file defines, as path::name."""
    tree = ast.parse(source)
    return {
        f"{path}::{node.name}"
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name.startswith("test")
    }


def _lines(root: Path, *args: str) -> list[str]:
    result = git(*args, cwd=root)
    if result.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return [line for line in result.stdout.splitlines() if line]


def _show(root: Path, ref: str, path: str) -> str | None:
    shown = git("show", f"{ref}:{path}", cwd=root)
    return shown.stdout if shown.returncode == 0 else None


def merged_prs_from_github() -> frozenset[int]:
    """Every merged pull request, read through a model of what gh answers."""
    result = subprocess.run(
        ["gh", "pr", "list", "--state", "merged", "--limit", "1000", "--json", "number"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(f"gh pr list failed: {result.stderr.strip()}")
    return frozenset(pr.number for pr in _MergedPrs.model_validate_json(result.stdout).root)


def gather(
    root: Path, ref: str, *, merged_prs: Callable[[], frozenset[int]] | None = None
) -> PlanFacts:
    """Observe the evidence ON THE REF, and pair it with the plan's own steps."""
    paths = _lines(root, "ls-tree", "-r", "--name-only", ref)
    mise = _show(root, ref, "mise.toml")
    tasks = tuple(_MiseTasks.model_validate(tomllib.loads(mise)).tasks) if mise else ()
    proofs: set[str] = set()
    for path in paths:
        name = Path(path).name
        if path.startswith("tests/") and name.startswith("test_") and name.endswith(".py"):
            source = _show(root, ref, path)
            if source is not None:
                proofs |= defined_tests(path, source)
    with_work = tuple(
        name.removeprefix("origin/")
        for name in _lines(
            root, "for-each-ref", "--format=%(refname:short)", "refs/heads", "refs/remotes/origin"
        )
        if name not in BASE_REFS
        and int(_lines(root, "rev-list", "--count", f"{ref}..{name}")[0]) > 0
    )
    blind: tuple[Kind, ...] = () if merged_prs is not None else ("pr",)
    facts = Facts(
        ref=ref,
        paths=tuple(paths),
        tasks=tasks,
        merged_prs=tuple(sorted(merged_prs())) if merged_prs is not None else (),
        tags=tuple(_lines(root, "tag", "--list")),
        proofs=tuple(sorted(proofs)),
        branches_with_work=tuple(sorted(set(with_work))),
        blind=blind,
    )
    plan, _, _ = load(root)
    return PlanFacts(facts=facts, steps=plan.steps)


def _query(entrypoint: str, payload: dict[str, JsonValue]) -> JsonValue:
    return query(entrypoint, dict(payload))


def decide(observed: PlanFacts) -> PlanStatus:
    """The policy's decision for every step, validated as plan-status/v1."""
    decided = _query("data.plan.status", {"plan_facts": observed.model_dump(mode="json")})
    return PlanStatus.model_validate({"ref": observed.facts.ref, "steps": decided})


def main() -> int:
    """plan:status -- decide, record, and report as a command-outcome envelope."""
    status = decide(gather(ROOT, "origin/develop", merged_prs=merged_prs_from_github))
    RECORDS.mkdir(parents=True, exist_ok=True)
    record = RECORDS / f"{datetime.now(UTC):%Y%m%dT%H%M%S%fZ}.json"
    record.write_text(status.model_dump_json(indent=2) + "\n", encoding="utf-8")

    plan, _, _ = load(ROOT)
    # THE REPORT FOR A PERSON ON STDERR; STDOUT CARRIES ONLY THE ENVELOPE.
    print(render(plan, status), file=sys.stderr)

    counts: dict[str, int] = {}
    for entry in status.steps.values():
        counts[entry.state] = counts.get(entry.state, 0) + 1

    done = counts.get("done", 0)
    outcome = CommandOutcome.model_validate(
        {
            "command": "plan:status",
            "outcome": "success",
            "code": "plan_observed",
            "message": f"{done} of {len(status.steps)} steps done on {status.ref}",
            "data": {"ref": status.ref, "states": counts, "record": str(record.relative_to(ROOT))},
        }
    )
    print(json.dumps(outcome.model_dump(), indent=2))
    return outcome.exit_code


if __name__ == "__main__":
    sys.exit(main())
