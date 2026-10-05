"""Evaluate the Nix contract policy, which lives in Rego.

WHY THE RULES ARE NOT IN PYTHON
verify() was a sequence of `if` statements appending to a list -- rules that
could not be enumerated or tested individually without running the whole
function. Rego describes "what is true under what conditions, not a sequence of
imperative steps", which is "significantly easier to audit, peer-review, and
test than procedural logic embedded inside application code".

It is this repository's convention too: policies/ already holds bundle, merge,
runtime and task rules, linted by regal and exercised by `opa test`. Having the
rules in BOTH places would be worse than either, because two implementations of
one policy drift and the drift is silent.

WHY A SUBPROCESS RATHER THAN AN EMBEDDED INTERPRETER
The embedded options were checked and each costs more than it saves:
regorus's Python bindings are "not yet available in PyPI"; opa-eval requires a
Rust toolchain and maturin; opa-golib-python-bindings requires Go >= 1.26 and
Python >= 3.14, while this project pins 3.12.3.

Subprocess overhead is documented at 50-200 ms per call. This runs ONCE per
contract invocation, and opa is already a pinned tool that evaluate_policies.py
already calls the same way. Adding a Rust or Go toolchain to reclaim 150 ms
once would be a poor trade.

WHY opa IS RESOLVED DIFFERENTLY FROM nix
nix probes run in a CONSTRUCTED environment, because the environment can change
what nix reports -- an inherited NIX_CONFIG could enable a feature and make a
probe certify a capability the project does not have.

opa evaluates a JSON document handed to it on stdin. No environment variable
changes that verdict. So opa is a project tool from the toolchain, like ruff,
rather than a subject of the trusted-directory allowlist that exists to stop a
substituted `nix`. The distinction looks like an inconsistency and is not: one
is the thing under investigation, the other is the instrument.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path

from pydantic import BaseModel, ConfigDict, JsonValue, ValidationError

from nix_models import NixPolicyInput
from nix_remediation import ActionableError, Autonomy, ContractProblem, Remediation
from opa import value_of

__all__ = [
    "POLICY_DIR",
    "PolicyEvaluationError",
    "declared_rules",
    "evaluate",
    "policy_revision",
    "resolve_opa",
    "verdicts",
]

# policies/machine/nix, mirroring the package name machine.nix -- regal enforces
# that the directory structure matches, so someone looking for a package finds it
# where its name says.
POLICY_DIR = Path(__file__).resolve().parent.parent / "policies" / "machine" / "nix"


class _Annotations(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")
    custom: dict[str, JsonValue] = {}


class _Annotated(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")
    annotations: _Annotations = _Annotations()


class _Inspected(BaseModel):
    """`opa inspect --format json -a`, read for each rule's custom annotations."""

    model_config = ConfigDict(frozen=True, extra="ignore")
    annotations: tuple[_Annotated, ...] = ()


def declared_rules(*, opa: Path | None = None, policy_dir: Path = POLICY_DIR) -> dict[str, str]:
    """Every rule the policy defines, DERIVED from the rules themselves.

    NOT A DECLARED LIST. The first attempt put an `every_rule` set in the Rego
    and guarded it with a test -- but a guarded hand-list is still a hand-list,
    and this repository has watched that shape go stale three times.

    Rego cannot enumerate its own rules: rego.metadata.rule() returns
    annotations for the ACTIVE rule only, and querying other rules' metadata is
    an open OPA request rather than a feature. So the enumeration happens from
    OUTSIDE, where `opa inspect -a` reads the annotations the rules carry.

    Each rule declares its own code in `custom:`, which is where arbitrary
    fields must live -- attributes outside it "won't be available to other tools
    that process annotations", which would silently defeat this.

    A rule added without an annotation does not appear here; a rule deleted
    takes its code with it. There is nothing to keep in sync.
    """
    binary = opa or resolve_opa()

    result = subprocess.run(
        [str(binary), "inspect", "--format", "json", "-a", str(policy_dir)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise PolicyEvaluationError(
            f"opa inspect failed on {policy_dir}",
            remediation="Check that the directory contains valid .rego files.",
            exit_code=result.returncode,
            opa_said=result.stderr.strip() or "(nothing)",
        )

    try:
        inspected = _Inspected.model_validate_json(result.stdout)
    except ValueError as error:
        raise PolicyEvaluationError(
            "opa inspect returned unreadable JSON",
            remediation="Re-run `opa inspect --format json -a` by hand.",
            detail=str(error),
        ) from error

    rules: dict[str, str] = {}
    for entry in inspected.annotations:
        custom = entry.annotations.custom
        code = custom.get("code")
        if code:
            rules[str(code)] = str(custom.get("severity", "problem"))

    if not rules:
        # FAIL CLOSED. No annotations means either the policy is missing or
        # every rule lost its metadata -- and reporting "no rules" as "all
        # verdicts pass" is the vacuous-truth failure this module guards.
        raise PolicyEvaluationError(
            f"no annotated rules found in {policy_dir}",
            remediation="Every rule needs a # METADATA block with custom.code. "
            "Without one it cannot be reported as passing.",
        )

    return rules


def verdicts(
    fired: frozenset[str], *, opa: Path | None = None, policy_dir: Path = POLICY_DIR
) -> dict[str, str]:
    """A verdict for EVERY rule, not only the ones that matched.

    `problems` and `warnings` contain only rules that FIRED, so a deleted rule
    and a passing rule produced identical output -- absence read as success,
    which is the failure this contract exists to remove, present in the contract
    itself.

    Computed here rather than in Rego because the declared set is derived from
    annotations, which Rego cannot read for other rules. The verdict is a diff:
    a rule is "fail" exactly when it appears in the findings.
    """
    return {
        code: ("fail" if code in fired else "pass")
        for code in declared_rules(opa=opa, policy_dir=policy_dir)
    }


def policy_revision(policy_dir: Path = POLICY_DIR) -> str:
    """A revision DERIVED from the rules, so it cannot drift from them.

    POLICY_VERSION WAS A HAND-MAINTAINED PYTHON CONSTANT describing Rego rules
    -- the version and the thing it versioned lived in different languages, in
    different files, with nothing connecting them. Bumping one without the other
    was a matter of remembering, which is the drift shape this repository
    removes everywhere else.

    Moving the string into .manifest would have RELOCATED the problem, not fixed
    it. A hand-maintained number drifts wherever it lives.

    WHY A CONTENT HASH AND NOT A COMMIT SHA
    OPA's own guidance is that a revision must be STABLE: identifiers like
    uuid or time.now_ns "will cause your bundles to be replaced for every
    build", while hash sums give "the same result" when nothing changed. Both a
    commit SHA and a content hash satisfy that.

    A content hash wins here because the policy is evaluated from the WORKING
    TREE, which can be dirty. A commit SHA would name a commit whose content is
    not what actually ran -- reporting a version that was never evaluated, which
    is worse than no version.

    Sorted paths and file bytes, so the digest depends on the rules and nothing
    else: not on filesystem order, not on when it was read.
    """
    digest = hashlib.sha256()
    for rego in sorted(policy_dir.glob("*.rego")):
        if rego.name.endswith("_test.rego"):
            # TESTS ARE NOT THE POLICY. Editing a test changes what is verified,
            # not what is enforced, and a revision that moved on test edits
            # would report a policy change that did not happen.
            continue
        digest.update(rego.name.encode("utf-8"))
        digest.update(rego.read_bytes())

    if not digest.hexdigest():  # pragma: no cover - sha256 always yields a digest
        raise PolicyEvaluationError(
            "could not compute a policy revision",
            remediation=f"Check that {policy_dir} contains .rego files.",
        )

    return digest.hexdigest()[:12]


class PolicyEvaluationError(ActionableError):
    """The policy could not be evaluated.

    FAIL CLOSED. An unevaluable policy is not an empty policy: reading "no
    problems" out of a failed evaluation would report every machine as healthy,
    which is the vacuous-truth failure this repository has fixed before.

    Enforced by opa's own --fail flag rather than by an emptiness check here,
    so the guarantee lives in the tool rather than in every caller that
    remembers to re-implement it.

    CARRIES A CODE AND A REMEDIATION like every problem does. It was a bare
    RuntimeError, which is why each of its messages had to be hand-improved --
    the fourth time that defect appeared today.
    """

    code = "ERR_NIX_POLICY_UNEVALUABLE"


def resolve_opa() -> Path:
    """Find opa from the project toolchain."""
    found = shutil.which("opa")
    if found is None:
        raise PolicyEvaluationError(
            "opa was not found on PATH",
            remediation="It is a pinned project tool: run `mise install`.",
        )
    return Path(found).resolve()


class _Verdict(BaseModel):
    """data.machine.nix, read for the two lists this side needs.

    THE MIDDLE OF THE ANSWER, NOW CHECKED. The package was checked to be an
    object by hand, and its `problems` and `warnings` were then iterated on
    trust; that they are lists is declared here. Each item is still read
    strictly by _problem_from, so a malformed problem keeps its precise error.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")
    problems: tuple[JsonValue, ...] = ()
    warnings: tuple[JsonValue, ...] = ()


def _problem_from(raw: object) -> ContractProblem:
    """Build a typed problem from a Rego object.

    STRICT: a rule emitting the wrong shape fails here rather than producing a
    half-populated problem. The Rego tests assert the shape; this is the second
    gate on it, because a policy edit could pass `opa test` and still emit a key
    this side does not expect.
    """
    if not isinstance(raw, dict):
        raise PolicyEvaluationError(
            "the policy emitted something that is not an object",
            remediation="Fix the rule in policies/machine/nix/nix.rego to emit "
            "{code, message, remediation}.",
            emitted=repr(raw),
        )

    remediation = raw.get("remediation")
    if not isinstance(remediation, dict):
        raise PolicyEvaluationError(
            "the policy emitted a problem with no remediation",
            remediation="Every rule must emit a remediation object; copy the shape "
            "from the others in policies/machine/nix/nix.rego.",
            emitted=repr(raw),
        )

    try:
        return ContractProblem(
            code=str(raw["code"]),
            message=str(raw["message"]),
            remediation=Remediation(
                description=str(remediation["description"]),
                command=(
                    None if remediation.get("command") is None else str(remediation["command"])
                ),
                autonomy=Autonomy(remediation["autonomy"]),
                reversible=bool(remediation["reversible"]),
                privileged=bool(remediation["privileged"]),
            ),
        )
    except (KeyError, ValueError) as error:
        raise PolicyEvaluationError(
            "the policy emitted a problem this side could not read",
            remediation="Check the rule's keys against ContractProblem and Remediation.",
            detail=str(error),
        ) from error


def evaluate(
    policy_input: NixPolicyInput,
    *,
    opa: Path | None = None,
    policy_dir: Path = POLICY_DIR,
) -> tuple[tuple[ContractProblem, ...], tuple[ContractProblem, ...]]:
    """Run the policy against an observation, returning (problems, warnings)."""
    binary = opa or resolve_opa()

    result = subprocess.run(
        [
            str(binary),
            "eval",
            "--data",
            str(policy_dir),
            "--stdin-input",
            "--format",
            "json",
            # FAIL CLOSED AT THE SOURCE, not with a Python emptiness check.
            #
            # If POLICY_DIR is wrong, opa returns an empty result and
            # value.get("problems", []) yields nothing -- reporting every
            # machine as satisfied. That is fail-OPEN, and it is the shape a
            # 2026 ADR describes as exploitable: "an adversary who can trigger
            # evaluation errors could bypass all governance controls".
            #
            # --fail exits non-zero on an UNDEFINED result, which is precisely
            # the missing-policy case: `problems` and `warnings` are multi-value
            # rules, and those "are never undefined, but they might be empty
            # sets". So a present policy finding nothing still exits 0, while an
            # absent package exits 1. Verified both ways before adopting.
            "--fail",
            # A builtin error otherwise makes a rule UNDEFINED and evaluation
            # continues -- losing that rule silently. Fatal is the honest
            # setting for a gate.
            "--strict-builtin-errors",
            # NAMESPACED under machine. because this judges a HOST, not this
            # repository. evaluate_policies.py discovers repo policies and
            # queries their `deny` rule; excluding this one by namespace rather
            # than by an exception list means a future host policy is excluded
            # because of where it lives.
            "data.machine.nix",
        ],
        input=policy_input.model_dump_json(),
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        # --fail EXITS 1 WITH AN EMPTY STDERR, so a raw message reads
        # "opa eval failed (1):" and tells an operator nothing.
        detail = result.stderr.strip() or result.stdout.strip()
        raise PolicyEvaluationError(
            f"opa could not evaluate data.machine.nix against {policy_dir}",
            remediation="The query was UNDEFINED, which usually means the policy is "
            "not at that path. Check POLICY_DIR.",
            exit_code=result.returncode,
            opa_said=detail or "(nothing)",
        )

    try:
        # THROUGH THE ONE READER OF OPA'S ANSWER, not by indexing raw JSON.
        value = value_of(result.stdout)
    except (ValueError, KeyError, IndexError) as error:
        raise PolicyEvaluationError(
            "opa returned a result this side could not read",
            remediation="Re-run the same `opa eval` by hand to see the raw output.",
            detail=str(error),
        ) from error

    try:
        verdict = _Verdict.model_validate(value)
    except ValidationError as error:
        raise PolicyEvaluationError(
            "the policy returned something other than {problems, warnings} as lists",
            remediation="data.machine.nix must evaluate to {problems, warnings}.",
            returned=repr(value),
        ) from error

    return (
        tuple(_problem_from(item) for item in verdict.problems),
        tuple(_problem_from(item) for item in verdict.warnings),
    )
