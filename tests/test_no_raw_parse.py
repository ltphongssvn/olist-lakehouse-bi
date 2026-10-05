"""No raw parse outside a model: every external read is validated where it enters (C.19).

THE SYNTAX TREE DECIDES WHAT IS RAW. A json, tomllib or yaml parse whose result
goes straight into model_validate or validate_python is sanctioned; any other is
untyped data entering unchecked. A text search cannot tell the two apart, and
matches parses named in comments.

SCOPED TO scripts/, where external input enters. Tests read their own command
envelopes, which is trusted internal data the two-axis rule does not re-validate.
"""

from __future__ import annotations

import pathlib

from pydantic import JsonValue

from opa import denials
from parse_inventory import ParseInventory, observe, observe_source

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _denied(inventory: ParseInventory | None) -> list[str]:
    payload: dict[str, JsonValue] = {}
    if inventory is not None:
        payload["raw_parses"] = inventory.model_dump(mode="json")
    return [d for d in denials("data.parsing.deny", payload) if d.startswith("[ERR_PARSE_")]


def test_this_repository_parses_nothing_raw() -> None:
    """THE REAL SCRIPTS, through the real policy."""
    inventory = observe(ROOT)
    assert inventory.files_scanned > 20
    assert _denied(inventory) == []


def test_a_raw_parse_is_observed() -> None:
    uses = observe_source("x.py", "import json\nvalue = json.loads(text)\n")
    assert [(u.line, u.call) for u in uses] == [(2, "json.loads")]


def test_a_parse_straight_into_a_model_is_sanctioned() -> None:
    source = "import tomllib\nplan = Plan.model_validate(tomllib.loads(text))\n"
    assert observe_source("x.py", source) == ()


def test_a_parse_through_a_variable_is_raw() -> None:
    """The variable is where unvalidated data lives, however briefly."""
    source = "import tomllib\nraw = tomllib.loads(text)\nplan = Plan.model_validate(raw)\n"
    assert [u.line for u in observe_source("x.py", source)] == [2]


def test_a_parse_named_in_a_comment_is_not_a_parse() -> None:
    assert observe_source("x.py", "# json.loads(sys.stdin)\nx = 1\n") == ()


def test_the_policy_denies_a_raw_parse() -> None:
    inventory = ParseInventory.model_validate(
        {"files_scanned": 1, "uses": [{"path": "x.py", "line": 2, "call": "json.loads"}]}
    )
    assert any(d.startswith("[ERR_PARSE_RAW]") for d in _denied(inventory))


def test_the_policy_allows_none() -> None:
    """THE CONTROL: a policy refusing everything would pass the rest."""
    assert _denied(ParseInventory.model_validate({"files_scanned": 1, "uses": []})) == []


def test_an_absent_inventory_is_denied() -> None:
    assert any(d.startswith("[ERR_PARSE_UNOBSERVED]") for d in _denied(None))
