# tests/test_plan_step.py
"""A plan step is read by a task, as data (D.22).

TWO VIEWS, ONE DOCUMENT. plan-step/v1 carries the step as ProjectPlan validates it
AND its block exactly as written, with line numbers -- the validated view says
what the step contains, the written view is what an edit must anchor on. Reading
D.12 by hand twice is what made this a task.

READ-ONLY: these tests read the committed fixture plan (D.53), changing nothing.
"""

from __future__ import annotations

from pathlib import Path

from plan_step import main, read_step

ROOT = Path(__file__).resolve().parent / "fixtures" / "plan"


def test_a_step_is_read_as_validated_data_and_as_written() -> None:
    view = read_step(ROOT, "D.12")
    assert view.step["id"] == "D.12"
    assert view.block[:2] == ("[[steps]]", 'id = "D.12"')
    lines = (ROOT / "context" / "plan.toml").read_text(encoding="utf-8").splitlines()
    assert view.block == tuple(lines[view.first_line - 1 : view.last_line])


def test_the_block_ends_before_the_next_entry() -> None:
    view = read_step(ROOT, "D.12")
    assert view.block.count("[[steps]]") == 1
    assert view.block[-1].strip(), "the block ends on its last line of content, not a blank"


def test_a_decision_is_read_too() -> None:
    """Decisions are plan entries with ids; reading one by hand is the repetition to avoid."""
    view = read_step(ROOT, "X.1")
    assert view.step["id"] == "X.1"
    assert view.block[:2] == ("[[decisions]]", 'id = "X.1"')


def test_an_unknown_step_is_refused() -> None:
    assert main(["Z.99"], root=ROOT) == 2
