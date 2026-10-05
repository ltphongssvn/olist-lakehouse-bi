"""No Any is written or implied: an inventory, a contract, and a policy (C.14).

WHY IT REACHED THE CODE. mypy's strict mode does not include
disallow_any_explicit, so the explicit form was never checked here; strict does
catch unannotated definitions, but only in what mypy reads.

THE PAIR, AND WHAT PROVES IT. The observer walks the syntax tree -- never text,
which matches Any in comments and docstrings -- and records every explicit Any
and every implicit one: a parameter other than self or cls, or a return, left
unannotated. The any-inventory/v1 contract validates and serialises that
record. Rego decides. These tests only prove the pair bites.

WHAT IT CANNOT SEE: an Any arriving through a call to something untyped is
invisible without running mypy. The observer records what is written.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import JsonValue, ValidationError

from any_inventory import observe, observe_source
from any_models import AnyInventory
from evaluate_policies import evaluate

ROOT = Path(__file__).resolve().parent.parent
POLICY = "data.typing.deny"


def _any(denials: list[str]) -> list[str]:
    """Only this family's denials: the typing package also judges mypy invocations."""
    return [d for d in denials if d.startswith("[ERR_ANY_")]


def _inventory(*uses: dict[str, JsonValue], files: int = 1) -> dict[str, JsonValue]:
    inventory = AnyInventory.model_validate({"files_scanned": files, "uses": list(uses)})
    return {"any_inventory": inventory.model_dump(mode="json")}


def test_an_explicit_any_is_observed() -> None:
    uses = observe_source("x.py", "from typing import Any\ndef f(x: Any) -> None: ...\n")
    assert [(u.form, u.line) for u in uses] == [("explicit", 2)]


def test_an_unannotated_parameter_and_return_are_implicit() -> None:
    uses = observe_source("x.py", "def f(x, y: int):\n    return y\n")
    assert sorted((u.form, u.name) for u in uses) == [
        ("implicit", "f -> return"),
        ("implicit", "x"),
    ]


def test_self_and_cls_are_not_implicit() -> None:
    source = (
        "class A:\n    def m(self) -> None: ...\n    @classmethod\n    def c(cls) -> None: ...\n"
    )
    assert observe_source("x.py", source) == ()


def test_a_comment_or_docstring_naming_any_is_not_any() -> None:
    """THE REASON FOR THE SYNTAX TREE: text search hit three such files here."""
    assert observe_source("x.py", '"""Any, Any, Any."""\n# Any\nx: int = 1\n') == ()


def test_an_inventory_of_nothing_is_refused() -> None:
    """A scan over no files passes and proves nothing."""
    with pytest.raises(ValidationError):
        AnyInventory.model_validate({"files_scanned": 0, "uses": []})


def test_the_policy_allows_a_clean_inventory() -> None:
    """THE CONTROL: a policy denying everything would satisfy every denial below."""
    assert _any(evaluate(POLICY, _inventory())) == []


def test_the_policy_denies_an_explicit_any() -> None:
    denied = evaluate(
        POLICY, _inventory({"path": "x.py", "line": 2, "form": "explicit", "name": "Any"})
    )
    assert any(d.startswith("[ERR_ANY_EXPLICIT]") for d in denied), denied


def test_the_policy_denies_an_implicit_any() -> None:
    denied = evaluate(
        POLICY, _inventory({"path": "x.py", "line": 1, "form": "implicit", "name": "x"})
    )
    assert any(d.startswith("[ERR_ANY_IMPLICIT]") for d in denied), denied


def test_a_missing_inventory_is_a_denial_not_permission() -> None:
    """FAIL CLOSED: an inventory nobody produced must not read as clean."""
    denied = evaluate(POLICY, {})
    assert any(d.startswith("[ERR_ANY_UNOBSERVED]") for d in denied), denied


def test_this_repository_holds_no_any() -> None:
    """THE REAL INVENTORY, through the real policy."""
    inventory = observe(ROOT)
    assert inventory.files_scanned > 50, "the scan reached too few files to mean anything"
    assert _any(evaluate(POLICY, {"any_inventory": inventory.model_dump(mode="json")})) == []
