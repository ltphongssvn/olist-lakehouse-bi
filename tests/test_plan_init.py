# tests/test_plan_init.py
"""A generated project starts its own plan by task (D.53).

The template carries no plan: a project generated from it would otherwise inherit this
repository's history as its own. plan:init writes a day-one plan, its trace and its id
ledger, validated together through the three contracts before any is written, and
refuses when a plan already exists rather than overwrite one.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from plan_init import init
from plan_models import IdLedger, PlanTrace, ProjectPlan, untraced

FILES = ("context/plan.toml", "context/plan-ids.toml", "context/plan-trace.toml")


def _text(root: Path, index: int) -> str:
    return (root / FILES[index]).read_text(encoding="utf-8")


def test_init_writes_a_plan_the_contracts_accept(tmp_path: Path) -> None:
    assert init(root=tmp_path) == 0
    plan = ProjectPlan.model_validate(tomllib.loads(_text(tmp_path, 0)))
    ids = IdLedger.model_validate(tomllib.loads(_text(tmp_path, 1)))
    trace = PlanTrace.model_validate(tomllib.loads(_text(tmp_path, 2)))
    assert {step.id for step in plan.steps} == {entry.id for entry in ids.issued}
    assert untraced(trace, plan) == []


def test_init_refuses_when_a_plan_exists(tmp_path: Path) -> None:
    (tmp_path / "context").mkdir()
    (tmp_path / FILES[0]).write_text("# a plan already here\n", encoding="utf-8")
    assert init(root=tmp_path) == 2
    assert _text(tmp_path, 0) == "# a plan already here\n"
    assert not (tmp_path / FILES[1]).exists()
    assert not (tmp_path / FILES[2]).exists()
