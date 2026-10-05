"""The requirement matrix: change and requirement traced to each other, both ways (G.5).

DERIVED, NEVER WRITTEN BY HAND. The plan, its trace, the decided status and the
commits on develop are joined into one row per id; the rules are policy.

BOTH DIRECTIONS. A commit on develop that names no step and is cited nowhere is
work no step authorised. A step that reads done with no commit naming it and no
historical source is done with no record of the work.
"""

from __future__ import annotations

import pathlib

from pydantic import JsonValue

from opa import denials
from plan_matrix import build
from plan_models import RequirementMatrix

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _denied(matrix: RequirementMatrix | None) -> list[str]:
    payload: dict[str, JsonValue] = {}
    if matrix is not None:
        payload["requirement_matrix"] = matrix.model_dump(mode="json")
    return [d for d in denials("data.plan.deny", payload) if d.startswith("[ERR_MATRIX_")]


def _matrix(
    requirements: list[dict[str, JsonValue]], commits: list[dict[str, JsonValue]]
) -> RequirementMatrix:
    return RequirementMatrix.model_validate(
        {"ref": "origin/develop", "requirements": requirements, "commits": commits}
    )


def _row(state: str, justified: list[str], referenced: list[str]) -> dict[str, JsonValue]:
    by: list[JsonValue] = [*justified]
    refs: list[JsonValue] = [*referenced]
    return {
        "id": "G.9",
        "title": "t",
        "kind": "step",
        "state": state,
        "justified_by": by,
        "referenced_by": refs,
    }


def _commit(steps: list[str], *, cited: bool = False, merge: bool = False) -> dict[str, JsonValue]:
    named: list[JsonValue] = [*steps]
    return {"sha": "abc1234", "subject": "s", "merge": merge, "steps": named, "cited": cited}


def test_every_change_and_every_done_step_trace_to_each_other() -> None:
    """THE REAL HISTORY, the real plan and the decided status, through the real policy."""
    matrix = build(ROOT)
    assert matrix.requirements and matrix.commits
    assert _denied(matrix) == []


def test_traced_both_ways_is_allowed() -> None:
    """THE CONTROL: a policy refusing everything would pass the rest."""
    assert _denied(_matrix([_row("done", [], ["abc1234"])], [_commit(["G.9"])])) == []


def test_an_untraced_commit_is_denied() -> None:
    denied = _denied(_matrix([], [_commit([])]))
    assert any(d.startswith("[ERR_MATRIX_COMMIT_UNTRACED]") for d in denied), denied


def test_a_commit_cited_by_history_is_traced() -> None:
    assert _denied(_matrix([], [_commit([], cited=True)])) == []


def test_a_merge_needs_no_trace() -> None:
    assert _denied(_matrix([], [_commit([], merge=True)])) == []


def test_a_done_step_with_no_record_of_the_work_is_denied() -> None:
    denied = _denied(_matrix([_row("done", ["SESSION:2026-10-01"], [])], []))
    assert any(d.startswith("[ERR_MATRIX_DONE_UNTRACED]") for d in denied), denied


def test_history_is_a_record_of_the_work() -> None:
    assert _denied(_matrix([_row("done", ["HISTORY:b2e1f4e"], [])], [])) == []


def test_an_open_step_needs_no_record_yet() -> None:
    assert _denied(_matrix([_row("ready", ["SESSION:2026-10-01"], [])], [])) == []


def test_an_absent_matrix_is_denied() -> None:
    assert any(d.startswith("[ERR_MATRIX_UNOBSERVED]") for d in _denied(None))
