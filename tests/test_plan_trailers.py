"""Every commit names the plan steps it serves (G.4).

TRAILERS ARE READ BY GIT, NOT BY A REGEX. git decides what a trailer is -- the
final paragraph, all trailers or a quarter of them -- and both observation
points use its parser: git log for saved commits, interpret-trailers for a
message not yet committed. The policy decides; these tests prove it bites.

MERGES ARE EXEMPT: GitHub writes them, and the pull request's own commits carry
the steps.
"""

from __future__ import annotations

import pathlib

from pydantic import JsonValue

from opa import denials
from plan_models import BranchCommits
from plan_trailers import observe, observe_message

ROOT = pathlib.Path(__file__).resolve().parent.parent
# THE COMMITTED FIXTURE PLAN (D.53): its ledger issues the same ids in every project, so a
# test of git's parser does not depend on which steps this repository has issued (D.61).
FIXTURE = ROOT / "tests" / "fixtures" / "plan"


def _denied(branch: BranchCommits | None) -> list[str]:
    payload: dict[str, JsonValue] = {}
    if branch is not None:
        payload["branch_commits"] = branch.model_dump(mode="json")
    return [d for d in denials("data.plan.deny", payload) if d.startswith("[ERR_TRAILER_")]


def _branch(*commits: tuple[list[str], bool]) -> BranchCommits:
    listed = [
        {"sha": f"c{i}", "subject": "s", "merge": merge, "steps": steps}
        for i, (steps, merge) in enumerate(commits)
    ]
    return BranchCommits.model_validate(
        {
            "base": "origin/develop",
            "commits": listed,
            "issued": ["G.1", "G.4", "X.9"],
            "retired": ["X.9"],
        }
    )


def test_every_commit_names_a_plan_step() -> None:
    """THE REAL BRANCH, through the real policy."""
    branch = observe(ROOT)
    assert branch.base == "origin/develop"
    assert branch.issued, "the id ledger issues no step"
    assert _denied(branch) == []


def test_a_commit_naming_an_issued_step_is_allowed() -> None:
    """THE CONTROL: a policy refusing every commit would pass the rest."""
    assert _denied(_branch((["G.4"], False))) == []


def test_a_commit_naming_no_step_is_denied() -> None:
    assert any(d.startswith("[ERR_TRAILER_MISSING]") for d in _denied(_branch(([], False))))


def test_a_merge_needs_no_step() -> None:
    assert _denied(_branch(([], True))) == []


def test_a_step_never_issued_is_denied() -> None:
    assert any(d.startswith("[ERR_TRAILER_UNKNOWN]") for d in _denied(_branch((["G.99"], False))))


def test_a_retired_step_is_denied() -> None:
    assert any(d.startswith("[ERR_TRAILER_RETIRED]") for d in _denied(_branch((["X.9"], False))))


def test_an_absent_observation_is_denied() -> None:
    assert any(d.startswith("[ERR_TRAILER_UNOBSERVED]") for d in _denied(None))


def test_a_message_is_read_by_gits_own_parser(tmp_path: pathlib.Path) -> None:
    """The hook's path: an unsaved message, trailers parsed by interpret-trailers."""
    message = tmp_path / "MSG"
    message.write_text(
        "feat(x): subject\n\nbody text.\n\nPlan-Step: D.22\nPlan-Step: D.12\n", encoding="utf-8"
    )
    observed = observe_message(FIXTURE, message)
    assert [c.steps for c in observed.commits] == [("D.22", "D.12")]
    assert _denied(observed) == []


def test_a_step_named_mid_body_is_not_a_trailer(tmp_path: pathlib.Path) -> None:
    """Git, not a regex: a line in the body is prose, not a trailer."""
    message = tmp_path / "MSG"
    message.write_text(
        "feat(x): subject\n\nPlan-Step: G.4\nthen more prose.\n\nclosing words.\n", encoding="utf-8"
    )
    observed = observe_message(ROOT, message)
    assert any(d.startswith("[ERR_TRAILER_MISSING]") for d in _denied(observed))
