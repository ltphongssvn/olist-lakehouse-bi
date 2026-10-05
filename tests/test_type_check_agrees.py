"""The types task and the gate check the same files, declared once (C.16).

WHY IT DRIFTED. The file set was written twice -- `scripts` in mise.toml,
`scripts tests` in check_all.py -- so the task reported success over errors the
gate refused.

WHY CONFIGURATION ALONE IS NOT THE FIX. mypy checks its configured `files` only
when no path is given on the command line; a path given there overrides them.
Declared once and bypassed silently, `files` would look like a control while
governing nothing. So the policy refuses any invocation that names a path.
"""

from __future__ import annotations

import pathlib

from pydantic import JsonValue

from evaluate_policies import evaluate
from type_check import TypeCheck, observe

ROOT = pathlib.Path(__file__).resolve().parent.parent
POLICY = "data.typing.deny"


def _denied(type_check: TypeCheck | None) -> list[str]:
    """Only this rule family's denials: the typing package also judges Any."""
    payload: dict[str, JsonValue] = {}
    if type_check is not None:
        payload["type_check"] = type_check.model_dump(mode="json")
    return [d for d in evaluate(POLICY, payload) if d.startswith("[ERR_MYPY_")]


def _observed(files: list[str], *argvs: list[str]) -> TypeCheck:
    invocations = [{"source": f"task:{i}", "argv": argv} for i, argv in enumerate(argvs)]
    return TypeCheck.model_validate({"files": files, "invocations": invocations})


BARE = ["uv", "run", "mypy", "--platform", "darwin"]
WITH_PATH = [*BARE, "scripts"]


def test_the_task_and_the_gate_check_the_same_files() -> None:
    """THE REAL TASK AND THE REAL GATE: no paths, one declared file set."""
    observed = observe(ROOT)
    assert set(observed.files) == {"scripts", "tests"}
    sources = {invocation.source for invocation in observed.invocations}
    assert "task:types" in sources, sources
    assert any(source.startswith("gate:types") for source in sources), sources
    assert _denied(observed) == []


def test_a_bare_invocation_is_allowed() -> None:
    """THE CONTROL: a policy denying every invocation would pass the rest."""
    assert _denied(_observed(["scripts", "tests"], BARE)) == []


def test_a_path_on_the_command_line_is_denied() -> None:
    """It overrides the declared files, which is the drift this exists to stop."""
    denied = _denied(_observed(["scripts"], WITH_PATH))
    assert any(d.startswith("[ERR_MYPY_PATHS]") for d in denied), denied


def test_a_platform_value_is_not_mistaken_for_a_path() -> None:
    """--platform darwin takes a value; darwin is not a path."""
    assert _denied(_observed(["scripts"], BARE)) == []


def test_no_declared_files_is_denied() -> None:
    denied = _denied(_observed([], BARE))
    assert any(d.startswith("[ERR_MYPY_FILES_UNDECLARED]") for d in denied), denied


def test_an_absent_observation_is_denied() -> None:
    """FAIL CLOSED: no observation must not read as agreement."""
    assert any(d.startswith("[ERR_MYPY_UNOBSERVED]") for d in _denied(None))
