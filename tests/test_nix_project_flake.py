"""The repository's own flake must actually be evaluated.

WHY THESE USE THE REAL NIX
A fake cannot tell a valid flake from a broken one -- it returns whatever it was
told to. The defect being fixed is that the contract passed with a broken
flake.nix in the root, and only a real evaluation demonstrates that it no longer
does.

These are marked integration for that reason: they need Nix, and they are the
one place in this suite where a fake would prove nothing.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from nix_contract import run
from nix_output import ContractOutput
from nix_system import RealSystem

pytestmark = [
    pytest.mark.integration,
    # SKIPPED WHERE NIX IS ABSENT, WHICH IS CI.
    #
    # A fake cannot distinguish a valid flake from a broken one, so these need
    # the real binary -- and the runner has none. Without this they would fail
    # there while passing here, which is the machine-dependence that took two CI
    # failures to learn earlier in this work and which I built straight back in.
    #
    # A skip is VISIBLE in the report; a test that quietly asserted nothing
    # would not be.
    pytest.mark.skipif(
        not Path("/nix/var/nix/profiles/default/bin/nix").is_file(),
        reason="needs a real nix; a fake cannot tell a valid flake from a broken one",
    ),
]

WORKING_FLAKE = "{ outputs = _: { }; }\n"

# `outputs` is required. Nix rejects this at evaluation, which is exactly the
# class of breakage that used to pass unnoticed.
BROKEN_FLAKE = '{ description = "no outputs attribute"; }\n'


def run_against(root: Path) -> tuple[ContractOutput, int]:
    """PARSED INTO THE MODEL, not left as dict[str, object].

    Returning a dict forced narrowing at every call site -- `assert
    isinstance(x, list)` before touching anything -- and I guessed a
    `type: ignore` code wrongly five times fixing it one site at a time. The
    dict was the cause; the suppressions were the symptom.

    "A dict[str, Any] is a function signature that says: I return... something.
    Good luck." Parsing at the boundary means validate once, trust after -- and
    the parse is itself a contract check, because extra="forbid" rejects any key
    the model does not declare.
    """
    out = io.StringIO()
    code = run(RealSystem(), out=out, root=root)
    return ContractOutput.model_validate_json(out.getvalue()), code


def test_a_broken_project_flake_fails_the_contract(tmp_path: Path) -> None:
    """THE DEFECT, DEMONSTRATED.

    Before this, the synthetic probe passed and nothing looked at the real
    flake, so a repository with an unevaluable flake.nix reported a satisfied
    contract.
    """
    (tmp_path / "flake.nix").write_text(BROKEN_FLAKE)

    document, code = run_against(tmp_path)

    assert code == 1
    assert "ERR_NIX_PROJECT_FLAKE_BROKEN" in {p.code for p in document.problems}


def test_a_working_project_flake_passes(tmp_path: Path) -> None:
    """The other direction: a valid flake must not be reported as broken.

    A rule that fires on everything is as useless as one that never fires, and
    this is the case that would make people disable the gate.
    """
    (tmp_path / "flake.nix").write_text(WORKING_FLAKE)

    document, code = run_against(tmp_path)

    assert "ERR_NIX_PROJECT_FLAKE_BROKEN" not in {p.code for p in document.problems}
    assert code == 0


def test_no_flake_means_the_check_did_not_run(tmp_path: Path) -> None:
    """Not the same as passing.

    The outcome field defaults to OK, so without the checked flag this
    repository -- which has no flake yet -- would report a flake check it never
    performed.
    """
    document, _ = run_against(tmp_path)

    assert document.project_flake_checked is False


def test_the_probe_is_recorded_only_when_it_ran(tmp_path: Path) -> None:
    """An empty transcript entry would claim a command executed when none did."""
    without, _ = run_against(tmp_path)
    names_without = {p.name for p in without.probes}
    assert "project_flake" not in names_without

    (tmp_path / "flake.nix").write_text(WORKING_FLAKE)
    with_flake, _ = run_against(tmp_path)
    names_with = {p.name for p in with_flake.probes}
    assert "project_flake" in names_with
