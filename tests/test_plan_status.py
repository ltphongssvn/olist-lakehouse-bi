"""Status is decided by policy over facts observed on the integration branch (G.3).

THE PAIR. The observer records what holds on origin/develop as plan-facts/v1;
policies/plan decides each step's state; plan-status/v1 validates the decision
coming back from OPA. These tests only prove the policy decides.

UNOBSERVABLE IS NOT DONE. Evidence of a kind this observation could not see --
a merged pull request with GitHub unreachable -- leaves a step unknown, never
done and never failed.

A PROOF HOLDS ONLY WHEN THE TEST EXISTS. The source this is ported from checked
that the test FILE was in the tree, though its comment promised the named
function; a renamed test read as proof. Here the function must be defined.
"""

from __future__ import annotations

import pathlib

from pydantic import JsonValue

from evaluate_policies import evaluate
from plan_models import PlanFacts
from plan_status import decide, defined_tests, gather

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _facts(**overrides: JsonValue) -> dict[str, JsonValue]:
    base: dict[str, JsonValue] = {
        "ref": "origin/develop",
        "paths": ["scripts/a.py", "tests/test_a.py"],
        "tasks": ["a"],
        "merged_prs": [],
        "tags": [],
        "proofs": ["tests/test_a.py::test_a"],
        "branches_with_work": [],
        "blind": [],
    }
    return {**base, **overrides}


def _step(
    step_id: str, *evidence: dict[str, JsonValue], depends_on: tuple[str, ...] = ()
) -> dict[str, JsonValue]:
    listed: list[JsonValue] = [*evidence]
    after: list[JsonValue] = [*depends_on]
    return {
        "id": step_id,
        "title": step_id,
        "thread": "C",
        "depends_on": after,
        "done_when": listed,
    }


def _decide(
    *steps: dict[str, JsonValue], facts: dict[str, JsonValue] | None = None
) -> dict[str, str]:
    listed: list[JsonValue] = [*steps]
    observed = PlanFacts.model_validate({"facts": facts or _facts(), "steps": listed})
    return {step_id: entry.state for step_id, entry in decide(observed).steps.items()}


PATH: dict[str, JsonValue] = {"kind": "path", "path": "scripts/a.py"}
MISSING: dict[str, JsonValue] = {"kind": "path", "path": "scripts/absent.py"}
PROOF: dict[str, JsonValue] = {"kind": "proof", "test": "tests/test_a.py::test_a"}
RENAMED: dict[str, JsonValue] = {"kind": "proof", "test": "tests/test_a.py::test_gone"}
PR: dict[str, JsonValue] = {"kind": "pr", "number": 7}


def test_every_piece_holding_makes_a_step_done() -> None:
    """THE CONTROL: a policy that never said done would pass every test below."""
    assert _decide(_step("C.1", PATH, PROOF)) == {"C.1": "done"}


def test_one_missing_item_leaves_a_step_open() -> None:
    """THE RULE G.3 IS PROVED BY: one unmet item, and the step is not done."""
    observed = PlanFacts.model_validate({"facts": _facts(), "steps": [_step("C.1", PATH, MISSING)]})
    entry = decide(observed).steps["C.1"]
    assert entry.state == "in_progress"
    assert any("scripts/absent.py" in reason for reason in entry.unmet), entry.unmet


def test_a_renamed_test_is_no_proof() -> None:
    """The file survives a rename; the proof must not."""
    assert _decide(_step("C.1", RENAMED)) == {"C.1": "ready"}


def test_a_step_waiting_on_an_open_one_is_blocked() -> None:
    states = _decide(_step("C.1", MISSING), _step("C.2", MISSING, depends_on=("C.1",)))
    assert states == {"C.1": "ready", "C.2": "blocked"}


def test_evidence_that_could_not_be_seen_is_unknown_not_done() -> None:
    """GitHub unreachable: a pull request is unobserved, never merged and never not."""
    assert _decide(_step("C.1", PATH, PR), facts=_facts(blind=["pr"])) == {"C.1": "unknown"}


def test_an_unseen_kind_never_hides_a_failure() -> None:
    """Blindness to one kind does not excuse an item of a kind that WAS seen."""
    assert _decide(_step("C.1", MISSING, PR), facts=_facts(blind=["pr"])) == {"C.1": "ready"}


def test_absent_facts_are_a_denial_not_permission() -> None:
    """FAIL CLOSED: a plan with nothing observed must not read as consistent."""
    assert any(d.startswith("[ERR_PLAN_UNOBSERVED]") for d in evaluate("data.plan.deny", {}))


def test_a_step_done_before_its_dependency_is_denied() -> None:
    """Done while something it depends on is open: the plan or its evidence is wrong."""
    listed: list[JsonValue] = [_step("C.1", MISSING), _step("C.2", PATH, depends_on=("C.1",))]
    observed = PlanFacts.model_validate({"facts": _facts(), "steps": listed})
    denied = evaluate("data.plan.deny", {"plan_facts": observed.model_dump(mode="json")})
    assert any(d.startswith("[ERR_PLAN_DONE_BEFORE_DEPENDENCY]") for d in denied), denied


def test_the_observer_reads_which_tests_a_file_defines() -> None:
    source = (
        "def test_a() -> None: ...\n"
        "def helper() -> None: ...\n"
        "class T:\n"
        "    def test_b(self) -> None: ...\n"
    )
    assert defined_tests("tests/test_x.py", source) == {"tests/test_x.py::test_a"}


def test_this_repositorys_plan_is_decided_on_develop() -> None:
    """THE REAL PLAN, the real facts, the real policy -- invariants that hold forever.

    An earlier version asserted that G.3 was not done, which was true until the
    pull request carrying it merged. A test of a passing moment is not a test.
    """
    observed = gather(ROOT, "origin/develop")
    status = decide(observed)
    assert status.ref == "origin/develop"
    assert set(status.steps) == {step.id for step in observed.steps}
    for step_id, entry in status.steps.items():
        if entry.state not in {"done", "unknown"}:
            assert entry.unmet or entry.blocked_by, f"{step_id} is {entry.state} with no reason"


def test_status_is_read_from_the_ref_never_the_disk() -> None:
    """An untracked file in the working tree must never reach the observed facts."""
    probe = ROOT / "scripts" / "_untracked_probe_for_plan_status.py"
    probe.write_text("# planted by a test, removed by it\n", encoding="utf-8")
    try:
        facts = gather(ROOT, "origin/develop").facts
    finally:
        probe.unlink()
    assert "scripts/_untracked_probe_for_plan_status.py" not in facts.paths
