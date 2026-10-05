"""The Databricks CLI boundary: every answer validated by what is read from it.

ONLY THE PROCESS IS STUBBED. subprocess.run is the one thing here that reaches
Databricks; the models, the validation and the refusal all run for real.

THE OLD BEHAVIOUR WAS THE BUG. Two copies of a helper returned the CLI's JSON as
Any, and an unreadable answer became an empty result -- so check:prereqs could
report a catalog missing when it could not read the reply.
"""

from __future__ import annotations

import ast
import pathlib
import subprocess

import pytest

from databricks_cli import Catalogs, GroupDetail, Jobs, Runs, ScimList, call, cli

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _answer(monkeypatch: pytest.MonkeyPatch, stdout: str, code: int = 0) -> list[list[str]]:
    seen: list[list[str]] = []

    def fake(args: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        seen.append(args)
        return subprocess.CompletedProcess(args, code, stdout, "the CLI said no")

    monkeypatch.setattr(subprocess, "run", fake)
    return seen


def test_a_scim_list_is_read_and_unread_fields_are_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    """THE CONTROL: a well-formed answer yields the typed fields the scripts read."""
    _answer(
        monkeypatch,
        '{"totalResults": 1, "schemas": ["urn:x"], '
        '"Resources": [{"displayName": "cscie103_readers", "id": "123", "meta": {}}]}',
    )
    listed = cli(ScimList, "api", "get", "/groups")
    assert [(r.display_name, r.id) for r in listed.resources] == [("cscie103_readers", "123")]


def test_an_absent_list_reads_as_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    _answer(monkeypatch, "{}")
    assert cli(ScimList, "api", "get", "/groups").resources == ()
    assert cli(GroupDetail, "api", "get", "/groups/1").members == ()


def test_top_level_arrays_are_read(monkeypatch: pytest.MonkeyPatch) -> None:
    """catalogs list, jobs list and list-runs each answer with an array."""
    _answer(monkeypatch, '[{"name": "cscie103_catalog", "owner": "x"}]')
    assert [c.name for c in cli(Catalogs, "catalogs", "list").root] == ["cscie103_catalog"]

    _answer(monkeypatch, '[{"job_id": 7, "settings": {"name": "[dev x] assignment_01_ingest"}}]')
    assert cli(Jobs, "jobs", "list").root[0].settings.name.endswith("assignment_01_ingest")

    _answer(
        monkeypatch,
        '[{"run_id": 9, "start_time": 1700000000000, '
        '"state": {"life_cycle_state": "TERMINATED", "result_state": "SUCCESS"}}]',
    )
    assert cli(Runs, "jobs", "list-runs").root[0].state.result_state == "SUCCESS"


def test_an_unreadable_answer_refuses_naming_the_call(monkeypatch: pytest.MonkeyPatch) -> None:
    """THE RULE: an unexpected shape is a refusal, never an empty result."""
    _answer(monkeypatch, '{"Resources": "not a list"}')
    with pytest.raises(SystemExit, match="databricks api get /groups answered in a shape"):
        cli(ScimList, "api", "get", "/groups")


def test_a_failed_call_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    _answer(monkeypatch, "", code=1)
    with pytest.raises(SystemExit, match="failed"):
        cli(ScimList, "api", "get", "/groups")


def test_a_write_parses_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """A POST or PATCH whose answer is not read needs no model and no JSON."""
    seen = _answer(monkeypatch, "")
    call("api", "post", "/groups", "--json", "{}")
    assert seen == [["databricks", "api", "post", "/groups", "--json", "{}"]]


def test_there_is_one_boundary() -> None:
    """AXIS 2: the helper written twice is gone from both scripts."""
    for name in (
        "bootstrap_identity.py",
        "check_prereqs.py",
        "release.py",
        "load_assignment_data.py",
    ):
        tree = ast.parse((ROOT / "scripts" / name).read_text(encoding="utf-8"))
        defined = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
        assert "_cli" not in defined, f"{name} still defines its own CLI helper"
