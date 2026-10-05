"""Every error this project raises must be classified.

WHY THIS TEST IS THE ACTUAL FIX
The same "diagnostic discarded" defect was fixed FOUR separate times today, in
four modules, each time by hand-writing a better string. That is a treadmill: the
fifth module would have had the same bug.

The root cause was shape, not wording -- exceptions carried a message and
nothing else, so there was nowhere for a code or a remedy to live. ActionableError
gives them somewhere, and this makes the requirement binding: "automated coverage
that prevents new errors from going unclassified".

It matters twice over here, because a CLI now "serves humans and AI agents from
one binary", and "agents need remediation DECLARED, not inferred".
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest

from nix_contract import NixContractError, UntrustedBinaryError
from nix_policy import PolicyEvaluationError
from nix_remediation import ActionableError

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"

# Bases that make a class an exception. Named rather than resolved, because the
# source is parsed rather than imported to find them.
EXCEPTION_BASES = frozenset(
    {"Exception", "RuntimeError", "ValueError", "OSError", "ActionableError"}
)


def every_subclass(root: type[ActionableError]) -> set[type[ActionableError]]:
    """All descendants, so a new error is covered because it exists.

    Enumerated from the class hierarchy rather than a list, for the same reason
    policy entrypoints are discovered from .rego files: a hand-maintained list
    of subclasses goes stale the first time someone adds one.
    """
    found: set[type[ActionableError]] = set()
    for subclass in root.__subclasses__():
        found.add(subclass)
        found |= every_subclass(subclass)
    return found


def project_exception_classes() -> set[type]:
    """Every exception class DEFINED in scripts/, found by reading the source.

    THE PREVIOUS GUARD WALKED ActionableError.__subclasses__() AND MISSED ONE.
    LedgerLockError was written as a RuntimeError, so it was never in that tree
    and the classification test never saw it -- an unclassified error slipping
    past the guard built to prevent unclassified errors.

    That is the stale-tree version of the stale-list problem: enumerating from
    a root only finds what already agreed to be there. Parsing the source finds
    every class that inherits from ANY exception, including ones that opted out
    of the hierarchy by accident.
    """
    found: set[type] = set()

    for module_path in sorted(SCRIPTS.glob("*.py")):
        tree = ast.parse(module_path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            base_names = {
                base.id if isinstance(base, ast.Name) else getattr(base, "attr", "")
                for base in node.bases
            }
            if not (base_names & EXCEPTION_BASES):
                continue

            module = importlib.import_module(module_path.stem)
            found.add(getattr(module, node.name))

    return found


def test_every_project_exception_is_actionable() -> None:
    """A project exception outside the ActionableError tree is unclassified.

    It has no code to branch on and no remediation to act on, and -- as
    LedgerLockError proved -- it is invisible to the test below.
    """
    stragglers = [
        cls.__name__ for cls in project_exception_classes() if not issubclass(cls, ActionableError)
    ]

    assert not stragglers, (
        f"exceptions outside ActionableError: {stragglers}. "
        "Inherit from it so they carry a code and a remediation."
    )


def test_every_error_declares_a_code() -> None:
    """An unclassified error cannot be branched on.

    A caller that must string-match the message is back to the fragility codes
    replaced.
    """
    # Importing the modules above populates __subclasses__.
    unclassified = [
        subclass.__name__
        for subclass in every_subclass(ActionableError)
        if not subclass.code and subclass.__subclasses__() == []
    ]

    assert not unclassified, f"errors with no code: {unclassified}"


def test_an_error_cannot_be_raised_without_a_remediation() -> None:
    """The constructor refuses, rather than a linter catching it later.

    A rule enforced at construction cannot be skipped; one enforced by review
    can.
    """

    class NamelessError(ActionableError):
        code = "ERR_TEST"

    with pytest.raises(ValueError, match="no remediation"):
        NamelessError("something broke", remediation="")


def test_an_error_without_a_code_cannot_be_raised() -> None:
    class UncodedError(ActionableError):
        pass

    with pytest.raises(ValueError, match="declares no code"):
        UncodedError("something broke", remediation="do the thing")


def test_the_message_states_the_problem_and_the_fix() -> None:
    """Never one without the other.

    The documented structure is "state the problem, guide the user on fixing
    it" -- a message that does only the first is what sends someone to search a
    codebase.
    """
    error = UntrustedBinaryError("nix was not found", name="nix", searched=())

    rendered = str(error)
    assert "nix was not found" in rendered
    assert "fix:" in rendered
    assert "nix:bootstrap" in rendered


def test_context_is_structured_not_interpolated() -> None:
    """A caller reads a field; it does not regex the message.

    Interpolating detail into prose carries it "in an inaccessible form".
    """
    error = PolicyEvaluationError(
        "opa could not evaluate",
        remediation="check POLICY_DIR",
        exit_code=1,
        opa_said="(nothing)",
    )

    assert error.context["exit_code"] == 1
    assert error.context["opa_said"] == "(nothing)"


def test_as_dict_gives_a_machine_the_same_three_fields_a_problem_has() -> None:
    """The point of the shared shape: an agent handles an exception and a
    problem the same way."""
    error = UntrustedBinaryError("nix was not found", name="nix", searched=())

    payload = error.as_dict()

    assert set(payload) == {"code", "message", "remediation", "context"}
    assert payload["code"] == "ERR_NIX_BINARY_UNTRUSTED"


def test_the_base_is_catchable_as_one_type() -> None:
    """An orchestrator catches ActionableError and gets everything."""
    assert issubclass(UntrustedBinaryError, ActionableError)
    assert issubclass(PolicyEvaluationError, ActionableError)
    assert issubclass(NixContractError, ActionableError)
