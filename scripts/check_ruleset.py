"""Verify develop and main are actually protected on the server.

WHY THE CONTENTS ARE CHECKED, NOT MERE EXISTENCE
A ruleset that exists but has been edited to require nothing is the failure mode
that looks like success. Asking "is there a ruleset" answers the wrong question.

WHY THIS IS NOT A DEPENDENCY OF `check`
That gate runs on every commit, and this needs network plus gh auth. Coupling
every commit to both blocks legitimate offline work for no benefit: a local
commit cannot weaken a server-side ruleset. It runs as its own CI step.

WHY NOT A SCHEDULED WORKFLOW
That was the obvious design and it is wrong. GitHub disables scheduled workflows
after 60 days without repository activity, and a successful scheduled run does
not itself count as activity. A security check that silently stops is worse than
no check, because it manufactures confidence. Tying it to CI removes the cron
dependency entirely.

Exit 1 means a required rule is missing. Exit 2 means the check could not run.
Both fail, because an unverifiable protection is not a verified one.
"""

from __future__ import annotations

import subprocess
import sys

from pydantic import BaseModel, ConfigDict, RootModel, ValidationError

RULESET_NAME = "develop-and-main-protection"
REQUIRED_RULES = ("deletion", "non_fast_forward", "pull_request", "required_status_checks")
REQUIRED_REFS = ("refs/heads/develop", "refs/heads/main")
REQUIRED_CHECK = "quality gate"


def _gh(*args: str) -> str:
    result = subprocess.run(["gh", *args], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        print(result.stderr.strip(), file=sys.stderr)
        raise SystemExit(2)
    return result.stdout


class _GitHub(BaseModel):
    """GitHub owns these schemas: only the fields this check reads are declared."""

    model_config = ConfigDict(frozen=True, extra="ignore")


class _Summary(_GitHub):
    id: int
    name: str = ""


class _Listing(RootModel[tuple[_Summary, ...]]):
    """GET .../rulesets answers with a top-level array."""


class _Check(_GitHub):
    context: str


class _Parameters(_GitHub):
    required_status_checks: tuple[_Check, ...] = ()
    allowed_merge_methods: tuple[str, ...] = ()


class _Rule(_GitHub):
    type: str
    parameters: _Parameters | None = None


class _RefName(_GitHub):
    include: tuple[str, ...] = ()


class _Conditions(_GitHub):
    ref_name: _RefName = _RefName()


class _Ruleset(_GitHub):
    enforcement: str = ""
    rules: tuple[_Rule, ...] = ()
    conditions: _Conditions = _Conditions()


def main() -> int:
    # AN ANSWER OF ANOTHER SHAPE MEANS THE CHECK COULD NOT RUN -- exit 2, as an
    # unverifiable protection is not a verified one.
    try:
        listing = _Listing.model_validate_json(_gh("api", "repos/{owner}/{repo}/rulesets")).root
        match = next((r for r in listing if r.name == RULESET_NAME), None)
        if match is None:
            print(f"MISSING ruleset {RULESET_NAME!r}", file=sys.stderr)
            print("develop and main are unprotected. Apply it with:", file=sys.stderr)
            print("  mise run repo:configure", file=sys.stderr)
            return 1
        ruleset = _Ruleset.model_validate_json(
            _gh("api", f"repos/{{owner}}/{{repo}}/rulesets/{match.id}")
        )
    except ValidationError as error:
        print(
            f"the rulesets API answered in a shape this check cannot read: {error}", file=sys.stderr
        )
        return 2

    failures: list[str] = []
    if ruleset.enforcement != "active":
        failures.append(f"enforcement is {ruleset.enforcement!r}, not 'active'")

    types = {rule.type for rule in ruleset.rules}
    failures.extend(f"missing rule: {r}" for r in REQUIRED_RULES if r not in types)

    refs = set(ruleset.conditions.ref_name.include)
    failures.extend(f"not protecting {b}" for b in REQUIRED_REFS if b not in refs)

    for rule in ruleset.rules:
        params = rule.parameters or _Parameters()
        if rule.type == "required_status_checks":
            contexts = {check.context for check in params.required_status_checks}
            if REQUIRED_CHECK not in contexts:
                failures.append(f"{REQUIRED_CHECK!r} not required; found {sorted(contexts)}")
        if rule.type == "pull_request":
            methods = list(params.allowed_merge_methods)
            if methods != ["merge"]:
                failures.append(f"merge methods are {methods}, not ['merge']")

    if failures:
        print("ruleset is not enforcing what this repo assumes:", file=sys.stderr)
        for failure in failures:
            print(f"  {failure}", file=sys.stderr)
        return 1

    print("ruleset ok: develop and main protected, quality gate required")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
