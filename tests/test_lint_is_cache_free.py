"""The local gate lints as CI does: every ruff check runs cache-free (C.17).

WHY. ruff decides whether an import is first-party by whether the module exists
on disk, and its cache does not key on that. A module created after the file
importing it was linted left a stale classification the laptop kept passing,
while CI -- which has no cache -- refused the same file with I001.

ruff format IS EXEMPT: formatting does not depend on which modules exist.
"""

from __future__ import annotations

import pathlib

from pydantic import JsonValue

from evaluate_policies import evaluate
from invocations import Invocations, observe

ROOT = pathlib.Path(__file__).resolve().parent.parent
POLICY = "data.lint.deny"


def _denied(observed: Invocations | None) -> list[str]:
    payload: dict[str, JsonValue] = {}
    if observed is not None:
        payload["invocations"] = observed.model_dump(mode="json")
    return [d for d in evaluate(POLICY, payload) if d.startswith("[ERR_RUFF_")]


def _of(*argvs: list[str]) -> Invocations:
    listed = [{"source": f"task:{i}", "argv": argv} for i, argv in enumerate(argvs)]
    return Invocations.model_validate({"invocations": listed})


CACHE_FREE = ["uv", "run", "ruff", "check", "--no-cache", "."]
CACHED = ["uv", "run", "ruff", "check", "."]
FORMAT = ["uv", "run", "ruff", "format", "."]


def test_every_ruff_check_runs_cache_free() -> None:
    """THE REAL TASKS AND THE REAL GATE, through the real policy."""
    observed = observe(ROOT)
    sources = {i.source for i in observed.invocations if "ruff" in i.argv}
    assert "task:lint" in sources and "gate:lint" in sources, sources
    assert _denied(observed) == []


def test_a_cache_free_check_is_allowed() -> None:
    """THE CONTROL: a policy denying every check would pass the rest."""
    assert _denied(_of(CACHE_FREE)) == []


def test_a_cached_check_is_denied() -> None:
    denied = _denied(_of(CACHE_FREE, CACHED))
    assert any(d.startswith("[ERR_RUFF_CACHED]") for d in denied), denied


def test_format_is_exempt() -> None:
    """Formatting does not depend on which modules exist."""
    assert _denied(_of(CACHE_FREE, FORMAT)) == []


def test_no_ruff_check_at_all_is_denied() -> None:
    """A gate that stopped linting must not read as clean."""
    denied = _denied(_of(FORMAT))
    assert any(d.startswith("[ERR_RUFF_UNOBSERVED]") for d in denied), denied


def test_an_absent_observation_is_denied() -> None:
    assert any(d.startswith("[ERR_RUFF_UNOBSERVED]") for d in _denied(None))
