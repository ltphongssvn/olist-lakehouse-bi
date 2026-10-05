# tests/test_plan_amend.py
"""A plan entry is amended by a task that preserves the files' formatting (D.24).

Six amendments this session -- evidence and dependencies of existing steps -- were
hand-made text edits, one refused on a formatting difference. tomlkit replaces the
named fields of one step in place; every comment, and every other step, survives.

FIXTURE FILES, COPIED: each test works on a copy of the committed fixture plan (D.53).
"""

from __future__ import annotations

import json
import shutil
import tomllib
from pathlib import Path

import pytest

from plan_edit import amend
from plan_models import ProjectPlan

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "plan"
FILES = ("context/plan.toml", "context/plan-ids.toml", "context/plan-trace.toml")


def _copy(tmp_path: Path) -> Path:
    for relative in FILES:
        (tmp_path / relative).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(FIXTURE / relative, tmp_path / relative)
    return tmp_path


def _comments(root: Path) -> dict[str, list[str]]:
    return {
        r: [
            line
            for line in (root / r).read_text(encoding="utf-8").splitlines()
            if line.lstrip().startswith("#")
        ]
        for r in FILES
    }


def _plan(root: Path) -> ProjectPlan:
    return ProjectPlan.model_validate(tomllib.loads((root / FILES[0]).read_text(encoding="utf-8")))


def _bytes(root: Path) -> dict[str, bytes]:
    return {r: (root / r).read_bytes() for r in FILES}


SPEC = """
id = "D.32"

[set]
done_when = [
  { kind = "task", name = "deps:add" },
  { kind = "proof", test = "tests/test_deps_add.py::test_a_package_is_added_with_its_lock" },
]
"""


def test_amending_evidence_keeps_every_comment(tmp_path: Path) -> None:
    root = _copy(tmp_path)
    before_comments, before_plan = _comments(root), _plan(root)
    spec = tmp_path / "amend.toml"
    spec.write_text(SPEC, encoding="utf-8")
    assert amend([str(spec)], root=root) == 0
    after_comments, after_plan = _comments(root), _plan(root)
    assert all(line in after_comments[FILES[0]] for line in before_comments[FILES[0]])
    amended = next(s for s in after_plan.steps if s.id == "D.32")
    assert len(amended.done_when) == 2
    others_before = [s for s in before_plan.steps if s.id != "D.32"]
    others_after = [s for s in after_plan.steps if s.id != "D.32"]
    assert others_before == others_after


def test_a_decision_can_be_amended(tmp_path: Path) -> None:
    """X.3 deferred a plan writer until edits became frequent; decisions must be amendable."""
    root = _copy(tmp_path)
    before = _plan(root)
    spec = tmp_path / "amend.toml"
    spec.write_text('id = "X.3"\n\n[set]\nreason = "a probe reason"\n', encoding="utf-8")
    assert amend([str(spec)], root=root) == 0
    after = _plan(root)
    assert next(d for d in after.decisions if d.id == "X.3").reason == "a probe reason"
    assert [d for d in before.decisions if d.id != "X.3"] == [
        d for d in after.decisions if d.id != "X.3"
    ]


def test_a_refusal_reports_the_failing_field_as_data(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """'1 validation error' says that something failed; the errors say what."""
    root = _copy(tmp_path)
    before = _bytes(root)
    spec = tmp_path / "amend.toml"
    spec.write_text('id = "X.3"\n\n[set]\nstate = "no-such-state"\n', encoding="utf-8")
    assert amend([str(spec)], root=root) == 2
    assert _bytes(root) == before
    errors = json.loads(capsys.readouterr().out)["data"]["errors"]
    assert any(e["field"].endswith("state") and e["message"] for e in errors), errors


def test_an_unknown_step_cannot_be_amended(tmp_path: Path) -> None:
    root = _copy(tmp_path)
    before = _bytes(root)
    spec = tmp_path / "amend.toml"
    spec.write_text(SPEC.replace('"D.32"', '"Z.99"'), encoding="utf-8")
    assert amend([str(spec)], root=root) == 2
    assert _bytes(root) == before


def test_an_amended_because_keyed_by_a_step_id_round_trips(tmp_path: Path) -> None:
    """amend writes keys through the same renderer as add, so they are quoted there too (D.51)."""
    root = _copy(tmp_path)
    spec = tmp_path / "amend.toml"
    spec.write_text(
        'id = "D.32"\n\n[set]\ndepends_on = ["D.22"]\n'
        'because = { "D.22" = "the probe reads a plan step by task" }\n',
        encoding="utf-8",
    )
    assert amend([str(spec)], root=root) == 0
    amended = next(s for s in _plan(root).steps if s.id == "D.32")
    assert amended.because == {"D.22": "the probe reads a plan step by task"}
    block = (root / FILES[0]).read_text(encoding="utf-8").split('id = "D.32"', 1)[1]
    assert 'because = { "D.22" = "the probe reads a plan step by task" }' in block
