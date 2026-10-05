# tests/test_command_outcome.py
"""The envelope every command writes to stdout, asserted before it exists.

WHY THIS FILE COMES FIRST. The contract is the deliverable; the model is an
implementation of it. Written the other way round, a test proves only that the
author can describe what they already wrote.

WHAT IS BEING FIXED. Every command in this repository prints prose, so a caller
reads it with grep -- presentation filtering, not evidence. check_all.py prints
PASS and FAIL; nix_contract.py prints JSON but of its own shape; pr.py prints
sentences. Nothing a machine consumes is a declared contract.

THREE OUTCOMES, NOT TWO, AND THAT IS THE POINT. A refusal is not a failure: the
command worked and denied what was asked. This repository already draws that
line inside the Nix contract -- POLICY_DENIED is not an error -- and then loses
it at the process boundary, where exit 1 means both "the policy said no" and
"the command broke". A caller cannot tell them apart.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from command_outcome import EXIT_CODES, CommandOutcome


def outcome(**overrides: object) -> CommandOutcome:
    """A valid envelope, with the field under test overridden."""
    fields: dict[str, object] = {
        "command": "check",
        "outcome": "success",
        "code": "all_gates_passed",
        "message": "16 gates passed",
        "data": {"gates": 16},
    }
    fields.update(overrides)
    return CommandOutcome.model_validate(fields)


# --- the shape ------------------------------------------------------------------


def test_the_contract_field_names_the_schema() -> None:
    """A document that does not name its own contract cannot be dispatched on.

    The consumer reads `contract` and knows which shape it holds, which is what
    makes a versioned envelope different from an ad hoc dict.
    """
    assert outcome().contract == "command-outcome/v1"


def test_the_contract_field_cannot_be_changed() -> None:
    """Literal, not str. A document claiming another contract is not this one."""
    with pytest.raises(ValidationError):
        outcome(contract="command-outcome/v2")


def test_the_envelope_is_frozen() -> None:
    """A result that can be edited after the fact is not a record of anything."""
    with pytest.raises(ValidationError, match="frozen"):
        outcome().command = "something-else"


def test_an_unexpected_field_is_refused() -> None:
    """extra=forbid, so a new field is a deliberate contract change.

    The same reasoning as ContractOutput: a field appearing is as much a
    contract change as a field vanishing, and both should fail at the boundary.
    """
    with pytest.raises(ValidationError):
        outcome(unexpected=1)


# --- the three outcomes ---------------------------------------------------------


def test_every_declared_outcome_validates() -> None:
    for verdict in ("success", "refused", "failed"):
        assert outcome(outcome=verdict).outcome == verdict


def test_an_undeclared_outcome_is_refused() -> None:
    """Drift detection. A plain str would have accepted anything."""
    with pytest.raises(ValidationError):
        outcome(outcome="ok")


def test_a_refusal_is_not_a_failure() -> None:
    """THE DISTINCTION THIS CONTRACT EXISTS TO CARRY.

    A policy denial is a command that ran correctly and said no. A failure is a
    command that broke. Collapsing them is what exit codes 0 and 1 do today.
    """
    assert EXIT_CODES["refused"] != EXIT_CODES["failed"]


def test_the_exit_codes_are_the_documented_ones() -> None:
    """0 succeeded, 1 the command broke, 2 the request was refused.

    A caller branches on these without parsing a word.
    """
    assert EXIT_CODES == {"success": 0, "failed": 1, "refused": 2}


def test_the_envelope_reports_its_own_exit_code() -> None:
    assert outcome(outcome="success").exit_code == 0
    assert outcome(outcome="failed").exit_code == 1
    assert outcome(outcome="refused").exit_code == 2


# --- the machine code -----------------------------------------------------------


def test_a_code_is_a_machine_token() -> None:
    assert outcome(code="nix_absent").code == "nix_absent"


def test_a_code_in_prose_is_refused() -> None:
    """A caller matches on the code, so it must not read like a sentence."""
    for prose in ("Nix is absent", "NIX_ABSENT", "nix-absent", "1_leading_digit"):
        with pytest.raises(ValidationError):
            outcome(code=prose)


def test_a_message_cannot_be_empty() -> None:
    """A code with no message is unactionable; a message with no code cannot be
    branched on. Both are required, and this asserts the half a default hides."""
    with pytest.raises(ValidationError):
        outcome(message="")


def test_a_command_cannot_be_empty() -> None:
    with pytest.raises(ValidationError):
        outcome(command="")


# --- the payload ----------------------------------------------------------------


def test_data_defaults_to_an_empty_object_rather_than_being_absent() -> None:
    """Required but defaulted: every envelope carries a payload, even an empty
    one, so a consumer never branches on whether the key exists."""
    parsed = CommandOutcome.model_validate(
        {
            "command": "status",
            "outcome": "success",
            "code": "clean",
            "message": "nothing to report",
        }
    )
    assert parsed.data == {}


def test_data_carries_structured_values() -> None:
    nested = {"gates": [{"name": "lint", "verdict": "pass"}], "total": 16}
    assert outcome(data=nested).data == nested


def test_data_refuses_a_value_that_is_not_json() -> None:
    """JsonValue, not Any. An object that cannot be serialised would produce an
    envelope that fails at the moment it is written, which is too late."""
    with pytest.raises(ValidationError):
        outcome(data={"when": object()})


# --- the wire -------------------------------------------------------------------


def test_the_serialised_document_round_trips() -> None:
    """stdout carries this and nothing else, so what is written must be exactly
    what a consumer can read back."""
    original = outcome()
    assert CommandOutcome.model_validate_json(original.model_dump_json()) == original
