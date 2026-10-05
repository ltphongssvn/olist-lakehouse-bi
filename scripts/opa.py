"""OPA, as one boundary: every evaluation's output validated before it is read.

ONE DEFINITION, WHERE THERE WERE THREE. evaluate_policies.py parsed OPA's
output with raw json.loads, plan_status.py kept its own models of it, and
nix_policy.py indexed the raw JSON by hand. value_of is the one reader of an
answer; nix_policy, which resolves its own trusted binary, reads through it too.

UNDEFINED IS NOT EMPTY. OPA reports a query naming nothing as an empty result,
indistinguishable from a policy that ran and found nothing -- so an undefined
query fails loudly rather than reading as clean.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

from pydantic import BaseModel, ConfigDict, JsonValue, ValidationError

ROOT = Path(__file__).resolve().parent.parent
POLICIES = ROOT / "policies"


class _Expression(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")
    value: JsonValue


class _Result(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")
    expressions: tuple[_Expression, ...]


class _Evaluation(BaseModel):
    """`opa eval --format json`, read for the one value a caller needs."""

    model_config = ConfigDict(frozen=True, extra="ignore")
    result: tuple[_Result, ...] = ()


class _Denial(BaseModel):
    """What every deny rule here emits, its code read from the rule's annotation."""

    model_config = ConfigDict(frozen=True, extra="ignore")
    code: str
    message: str


def value_of(stdout: str) -> JsonValue:
    """The value of one evaluation, validated; ValueError when nothing was evaluated."""
    evaluation = _Evaluation.model_validate_json(stdout)
    if not evaluation.result or not evaluation.result[0].expressions:
        raise ValueError("the query is UNDEFINED, so nothing was evaluated")
    return evaluation.result[0].expressions[0].value


def query(entrypoint: str, payload: Mapping[str, object]) -> JsonValue:
    """The value of one query, or a loud failure when nothing was evaluated."""
    result = subprocess.run(
        ["opa", "eval", "--format", "json", "--data", str(POLICIES), "--stdin-input", entrypoint],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        print(result.stderr.strip(), file=sys.stderr)
        raise SystemExit(f"opa eval failed for {entrypoint}")
    try:
        return value_of(result.stdout)
    except ValueError as error:
        raise SystemExit(
            f"{entrypoint} is UNDEFINED. The package or rule does not exist, so nothing was "
            f"evaluated. This must fail loudly rather than read as clean. ({error})"
        ) from error


def denials(entrypoint: str, payload: Mapping[str, object]) -> list[str]:
    """Each denial as `[CODE] message`; an unstructured one is marked, never dropped."""
    value = query(entrypoint, payload)
    rendered: list[str] = []
    for item in value if isinstance(value, list) else []:
        try:
            denial = _Denial.model_validate(item)
        except ValidationError:
            rendered.append(f"[UNSTRUCTURED] {item}")
            continue
        rendered.append(f"[{denial.code}] {denial.message}")
    return rendered
