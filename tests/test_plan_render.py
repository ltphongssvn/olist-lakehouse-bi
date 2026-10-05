"""The plan's status, rendered in otsafety-gnn's report format (G.3).

PRESENTATION ONLY. The decision is the policy's and is validated before it gets
here; this lays it out for a person, grouped by thread since this repository's
threads are its capability groups.
"""

from __future__ import annotations

from plan_models import PlanStatus, ProjectPlan
from plan_render import render

PLAN = ProjectPlan.model_validate(
    {
        "contract": "project-plan/v1",
        "threads": [{"id": "G", "title": "Planning"}],
        "steps": [
            {
                "id": "G.1",
                "title": "contracts",
                "thread": "G",
                "done_when": [{"kind": "task", "name": "a"}],
            },
            {
                "id": "G.2",
                "title": "trace",
                "thread": "G",
                "done_when": [{"kind": "task", "name": "b"}],
            },
            {
                "id": "G.3",
                "title": "status",
                "thread": "G",
                "depends_on": ["G.2"],
                "done_when": [{"kind": "task", "name": "c"}],
            },
        ],
        "decisions": [{"id": "X.1", "title": "no loops", "state": "declined", "reason": "r"}],
    }
)
STATUS = PlanStatus.model_validate(
    {
        "ref": "origin/develop",
        "steps": {
            "G.1": {"state": "done"},
            "G.2": {"state": "ready"},
            "G.3": {"state": "blocked", "blocked_by": ["G.2"]},
        },
    }
)


def test_the_header_counts_what_is_done_where() -> None:
    assert render(PLAN, STATUS).splitlines()[0] == (
        "PROJECT PLAN -- observed on origin/develop: 1 of 3 steps done"
    )


def test_steps_are_grouped_by_thread_with_their_titles() -> None:
    text = render(PLAN, STATUS)
    assert "-- Thread G . Planning  (1/3)" in text
    assert "✅ G.1   contracts" in text


def test_a_blocked_step_names_what_it_waits_for() -> None:
    assert "🔒 G.3   status   [after G.2]" in render(PLAN, STATUS)


def test_each_thread_gets_a_progress_bar() -> None:
    bar = next(
        line for line in render(PLAN, STATUS).splitlines() if line.startswith("   G Planning")
    )
    assert "#######............." in bar and "1/3" in bar


def test_now_lists_what_can_start() -> None:
    text = render(PLAN, STATUS)
    now = text[text.index("-- NOW") : text.index("-- DECISIONS")]
    assert "G.2" in now and "G.3" not in now


def test_decisions_are_listed_with_their_state() -> None:
    assert "declined   X.1       no loops" in render(PLAN, STATUS)
