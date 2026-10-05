"""The plan, its trace and its id ledger, as contracts (ported from otsafety-gnn).

WHY THE PLAN IS A FILE. This repository's history -- sixty-six commits across
toolchain, platform, gates, workflow and coursework -- was organised only in
conversations. A plan held in a conversation is lost with it, and is wrong
whenever memory is.

STATUS IS NEVER WRITTEN. A step declares the evidence that proves it done, and
status is observed from that evidence. A hand-written status is refused outright.

RAW INPUT IS JsonValue, NOT Any. These helpers deliberately build invalid
shapes to prove the contract refuses them, so they cannot be typed as the
models; JsonValue names exactly "untyped JSON, to be validated", and keeps
everything else checked.
"""

from __future__ import annotations

import pytest
from pydantic import JsonValue, ValidationError

from plan_models import IdLedger, PlanTrace, ProjectPlan, Step, untraced

Raw = dict[str, JsonValue]


def _step(step_id: str = "D.1", **overrides: JsonValue) -> Raw:
    return {
        "id": step_id,
        "title": "the pull request blocks until merged",
        "thread": "D",
        "done_when": [{"kind": "path", "path": "scripts/pr.py"}],
        **overrides,
    }


def _plan(*steps: Raw, decisions: tuple[Raw, ...] = ()) -> Raw:
    listed: list[JsonValue] = [*steps] or [_step()]
    declined: list[JsonValue] = [*decisions]
    return {
        "contract": "project-plan/v1",
        "threads": [{"id": "D", "title": "Workflow"}, {"id": "E", "title": "Coursework"}],
        "steps": listed,
        "decisions": declined,
    }


def test_a_valid_plan_validates() -> None:
    """THE CONTROL: every refusal below would pass against a contract refusing all."""
    plan = ProjectPlan.model_validate(_plan(_step("D.1"), _step("D.2", depends_on=["D.1"])))
    assert [s.id for s in plan.steps] == ["D.1", "D.2"]


def test_a_hand_written_status_is_refused() -> None:
    """THE RULE THIS EXISTS FOR: status is observed, never declared."""
    with pytest.raises(ValidationError):
        ProjectPlan.model_validate(_plan(_step(status="done")))


def test_an_id_used_twice_is_refused_across_steps_and_decisions() -> None:
    decision: Raw = {"id": "D.1", "title": "x", "state": "declined", "reason": "y"}
    with pytest.raises(ValidationError):
        ProjectPlan.model_validate(_plan(_step("D.1"), decisions=(decision,)))


def test_a_reference_that_resolves_nowhere_is_refused() -> None:
    broken: tuple[Raw, ...] = (_step(thread="Z"), _step(depends_on=["D.9"]))
    for step in broken:
        with pytest.raises(ValidationError):
            ProjectPlan.model_validate(_plan(step))


def test_a_dependency_cycle_is_refused() -> None:
    with pytest.raises(ValidationError):
        ProjectPlan.model_validate(
            _plan(_step("D.1", depends_on=["D.2"]), _step("D.2", depends_on=["D.1"]))
        )


def test_a_reason_must_name_a_real_dependency() -> None:
    with pytest.raises(ValidationError):
        ProjectPlan.model_validate(_plan(_step(because={"D.9": "a note pointing at nothing"})))


def test_a_proof_names_a_test_not_a_file() -> None:
    """A file cannot say which test; path::name can."""
    named = "tests/test_pr_progress.py::test_x"
    ProjectPlan.model_validate(_plan(_step(done_when=[{"kind": "proof", "test": named}])))
    with pytest.raises(ValidationError):
        ProjectPlan.model_validate(
            _plan(_step(done_when=[{"kind": "proof", "test": "tests/test_pr_progress.py"}]))
        )


def test_a_release_is_this_repositorys_tag_convention() -> None:
    """ADAPTED: the source required v1.2.3; releases here are tagged assignment-NN-vN."""
    tagged: list[JsonValue] = [{"kind": "release", "tag": "assignment-01-v2"}]
    ProjectPlan.model_validate(_plan(_step("E.3", thread="E", done_when=tagged)))
    with pytest.raises(ValidationError):
        semver: list[JsonValue] = [{"kind": "release", "tag": "v1.0.0"}]
        ProjectPlan.model_validate(_plan(_step("E.3", thread="E", done_when=semver)))


def test_a_step_needs_no_loop() -> None:
    """NOT PORTED: the source's loops are its own vocabulary, and requiring one here
    would mean inventing a loop for every existing step."""
    assert "serves" not in Step.model_fields


def _trace(*candidates: Raw) -> Raw:
    listed: list[JsonValue] = [*candidates]
    return {
        "contract": "plan-trace/v1",
        "sources": [{"id": "HISTORY", "title": "this repository's commits", "locator": "git log"}],
        "candidates": listed,
    }


def test_a_candidate_has_exactly_one_disposition() -> None:
    neither: Raw = {"source": "HISTORY", "ref": "b2e1f4e", "text": "x"}
    both: Raw = {**neither, "maps_to": ["D.1"], "not_a_plan_item": "y"}
    for candidate in (neither, both):
        with pytest.raises(ValidationError):
            PlanTrace.model_validate(_trace(candidate))


def test_untraced_reports_both_directions() -> None:
    """A candidate pointing at nothing, and an item no candidate authorises."""
    plan = ProjectPlan.model_validate(_plan(_step("D.1"), _step("D.2")))
    trace = PlanTrace.model_validate(
        _trace({"source": "HISTORY", "ref": "b2e1f4e", "text": "x", "maps_to": ["D.1", "D.7"]})
    )
    problems = untraced(trace, plan)
    assert any("D.7" in p for p in problems), problems
    assert any(p.startswith("D.2") for p in problems), problems


def test_the_id_ledger_keeps_a_retired_id() -> None:
    ledger = IdLedger.model_validate(
        {
            "contract": "id-ledger/v1",
            "issued": [
                {"id": "D.1", "first_title": "x"},
                {"id": "D.2", "first_title": "y", "retired": True},
            ],
        }
    )
    assert [e.retired for e in ledger.issued] == [False, True]
