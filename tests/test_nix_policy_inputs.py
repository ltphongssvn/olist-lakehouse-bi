"""Enforce which observations policy is allowed to read.

WHY THIS EXISTS
NixInstallation holds two kinds of field and nothing distinguished them: facts
that DECIDE the verdict and facts merely RECORDED. is_determinate is the
dangerous one -- it notes that this machine runs a vendor fork, and a later
reader could start enforcing it, quietly making the fork mandatory.

A comment saying "informational" would be the kind of aspirational document
that "lived in wikis and slide decks" and was never enforced. This parses
verify() and checks what it actually touches, so the declaration is binding.

WHY AST INSPECTION RATHER THAN A CONVENTION
A convention is followed until someone is in a hurry. Reading the source means
the rule holds regardless of intent: adding `if installation.is_determinate` to
verify() fails here, and the fix is either to remove it or to move the field
into POLICY_INPUTS on purpose -- which is a decision someone makes rather than
one that happens.
"""

from __future__ import annotations

import ast
import inspect
import textwrap

import nix_contract
from nix_contract import INFORMATIONAL_ONLY, POLICY_INPUTS, NixInstallation


def attributes_read_by(function_name: str) -> set[str]:
    """Every `installation.<attr>` the named function reads.

    Parses the function's own source rather than the whole module, so an
    unrelated function touching a field elsewhere does not widen the result.
    """
    # textwrap.dedent, NOT inspect.cleandoc. cleandoc strips leading whitespace
    # from EVERY line, which flattens the function body and makes it unparseable
    # -- it is a docstring tool, not a source tool. dedent removes only the
    # COMMON indentation, preserving structure.
    source = textwrap.dedent(inspect.getsource(getattr(nix_contract, function_name)))
    tree = ast.parse(source)

    found: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "installation"
        ):
            found.add(node.attr)
    return found


def test_verify_reads_only_declared_policy_inputs() -> None:
    """The rule that stops enforcement creep.

    If this fails, verify() started reading a field nobody declared as a policy
    input. Either remove the read, or add the field to POLICY_INPUTS -- but do
    it deliberately, because that is what makes a recorded fact into a required
    one.
    """
    undeclared = attributes_read_by("verify") - POLICY_INPUTS

    assert not undeclared, (
        f"verify() reads undeclared fields: {sorted(undeclared)}. "
        "Add them to POLICY_INPUTS on purpose, or stop reading them."
    )


def test_policy_never_reads_an_informational_field() -> None:
    """is_determinate is the case this protects.

    Enforcing it would make Determinate Nix REQUIRED, which the project has
    deliberately not decided. flake.nix and flake.lock are standard artefacts on
    either distribution.
    """
    enforced_but_informational = attributes_read_by("verify") & INFORMATIONAL_ONLY

    assert not enforced_but_informational, (
        f"verify() enforces informational fields: {sorted(enforced_but_informational)}"
    )


def test_the_two_sets_do_not_overlap() -> None:
    """A field cannot be both, and saying it is means the distinction is noise."""
    assert not (POLICY_INPUTS & INFORMATIONAL_ONLY)


def test_every_declared_field_exists_on_the_model() -> None:
    """A declaration naming a field that does not exist protects nothing.

    Properties count: several policy inputs are derived (is_uninstallable,
    is_corrupted), and those are exactly the ones a rename would silently
    detach from their declaration.
    """
    known = set(NixInstallation.model_fields) | {
        name for name in dir(NixInstallation) if not name.startswith("_")
    }

    for declared in POLICY_INPUTS | INFORMATIONAL_ONLY:
        assert declared in known, f"{declared} is declared but does not exist on the model"
