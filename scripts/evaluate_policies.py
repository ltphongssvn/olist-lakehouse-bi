"""Evaluate the repo's own tasks and bundle against the Rego policies.

THE SPLIT THAT MATTERS, BECAUSE IT IS A DIFFERENCE IN KIND
  check:policy   are the policies well-formed and tested?
  this script    does the CODEBASE satisfy them?

A policy suite can be immaculate and enforce nothing. `opa test` proves the rules
behave; only evaluating real input proves the repo obeys them.

ENTRYPOINTS ARE DISCOVERED, NOT LISTED
They were a hand-maintained tuple, and policies/merge was written, tested and
committed without being added to it -- so its rules passed their unit tests and
were never evaluated against this repo at all. The gate went green for a policy
enforcing nothing.

That is the same shape as the known-first-party list that went stale three times:
a second copy of something the directory already knows. Package names now come
from the .rego files themselves, so a new policy is enforced because it exists.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Mapping
from pathlib import Path

from any_inventory import observe
from databricks_cli import ResolvedBundle, cli
from hooks import observe as observe_hooks
from invocations import observe as observe_invocations
from named_tasks import named_tasks
from opa import denials
from parse_inventory import observe as observe_parses
from plan_matrix import build as build_matrix
from plan_status import gather
from plan_trailers import observe as observe_trailers
from project_identity import observe as observe_identity
from task_commands import command_invocations, task_input
from type_check import observe as observe_type_check

ROOT = Path(__file__).resolve().parent.parent
MISE_TOML = ROOT / "mise.toml"
POLICIES = ROOT / "policies"

# Dotted package names are legal Rego and the previous pattern silently
# ignored them -- a package named `machine.nix` would not have matched at all,
# which is fail-OPEN: the policy would exist and never be discovered.
PACKAGE_PATTERN = re.compile(r"^package\s+([a-z_][a-z0-9_.]*)\s*$", re.MULTILINE)


def entrypoints() -> tuple[str, ...]:
    """Every deny rule the policy tree defines.

    Test packages are excluded by name: they assert ABOUT rules and define no
    deny of their own, so querying them would always return undefined.
    """
    found: set[str] = set()
    for path in sorted(POLICIES.rglob("*.rego")):
        for package in PACKAGE_PATTERN.findall(path.read_text()):
            if package.endswith("_test"):
                continue
            # PACKAGES UNDER `machine.` JUDGE A HOST, NOT THIS REPOSITORY.
            #
            # policies/nix judges an observation produced by observe() at
            # runtime; feeding it this script's task-and-bundle payload would
            # evaluate rules against a document they were never written for.
            #
            # Selected by NAMESPACE rather than by an exception list, because a
            # hardcoded exception is the stale-list failure this script exists
            # to have fixed. A new host policy is excluded because of where it
            # lives, not because someone remembered to name it here.
            if package.startswith("machine."):
                continue
            found.add(f"data.{package}.deny")

    if not found:
        raise SystemExit(f"no policy packages found under {POLICIES}")
    return tuple(sorted(found))


def bundle_input() -> ResolvedBundle:
    """The resolved bundle, as the CLI itself reports it, validated where it enters.

    NOT the raw YAML. Reading databricks.yml would judge what was WRITTEN;
    `bundle validate --output json` reports what actually DEPLOYS, after variable
    substitution and target overrides.

    THE FIXTURE TARGET, for the same reason update_fixtures.py uses it: `dev`
    embeds the deployer in 19 places and requires deploy-time variables the
    policy has no business supplying.

    THROUGH A MODEL, NO LONGER json.loads: ResolvedBundle declares what the
    policies read and keeps everything else, since the CLI owns the schema.
    """
    return cli(ResolvedBundle, "bundle", "validate", "-t", "fixture", "--output", "json", cwd=ROOT)


def evaluate(entrypoint: str, payload: Mapping[str, object]) -> list[str]:
    return denials(entrypoint, payload)


def main() -> int:
    tasks = task_input()
    resolved = bundle_input()

    # ONE MERGED DOCUMENT, EVERY PART FROM A MODEL. Each package reads only the
    # keys it cares about, so a single input shape serves all of them. The
    # bundle's keys sit at the top level, as the bundle policy reads them;
    # exclude_unset keeps its shape exactly what the CLI reported.
    payload: dict[str, object] = {
        "tasks": tasks.tasks,
        "descriptions": tasks.descriptions,
        **resolved.model_dump(mode="json", exclude_unset=True),
        # Parsed command invocations, so policy matches STRUCTURE rather than
        # regexing shell text full of comments and quoted regions.
        "commands": [
            command.model_dump(mode="json", exclude_none=True)
            for command in command_invocations(tasks.tasks)
        ],
        # Every Any the code writes or implies, observed from the syntax tree.
        "any_inventory": observe(ROOT).model_dump(mode="json"),
        # What holds on origin/develop, for policies/plan to judge the plan against.
        "plan_facts": gather(ROOT, "origin/develop").model_dump(mode="json"),
        # Every mypy invocation and the files it is meant to check.
        "type_check": observe_type_check(ROOT).model_dump(mode="json"),
        # Every command the tasks and the gate run, for policies/lint.
        "invocations": observe_invocations(ROOT).model_dump(mode="json"),
        # This branch's commits and the steps each names, for policies/plan.
        "branch_commits": observe_trailers(ROOT).model_dump(mode="json"),
        # What the git hooks run, read as lefthook reads it, for policies/hooks.
        "hooks": observe_hooks(ROOT).model_dump(mode="json"),
        # The plan, trace, status and develop's commits joined, for policies/plan.
        "requirement_matrix": build_matrix(ROOT).model_dump(mode="json"),
        # Every json, tomllib or yaml parse that enters unvalidated, for policies/parsing.
        "raw_parses": observe_parses(ROOT).model_dump(mode="json"),
        # Every task a tracked message tells the reader to run, for policies/tasks/named.
        "named_tasks": named_tasks(ROOT).model_dump(mode="json"),
        # Every identity value and whether a slot holds it, for policies/identity.
        "identity_inventory": observe_identity(ROOT).model_dump(mode="json"),
    }

    queried = entrypoints()
    failures: list[str] = []
    for entrypoint in queried:
        failures.extend(evaluate(entrypoint, payload))

    if failures:
        print(f"{len(failures)} policy violation(s):", file=sys.stderr)
        for reason in sorted(failures):
            print(f"  {reason}", file=sys.stderr)
        return 1

    print(
        f"policy ok: {len(tasks.tasks)} tasks and the resolved bundle satisfy "
        f"{len(queried)} policy packages ({', '.join(queried)})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
