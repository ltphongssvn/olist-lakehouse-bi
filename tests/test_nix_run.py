"""Tests for the CLI entry point, including the branch CI actually hit.

WHY THESE COULD NOT EXIST BEFORE
main() built its own RealSystem, read a real path and printed to real stdout.
The skip branch below is the one CI exercised -- and it could not be asserted
"without hijacking process globals", which is the documented reason for
extracting a run() that takes its dependencies.

The bug this covers was real: the contract gate was marked ci_only, so it ran
ONLY on a runner with no Nix and never on the developer machine it judges. CI
failed with observe_error, correctly.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

from test_nix_observe import FakeSystem

from nix_contract import run


def run_capturing(system: FakeSystem, root: Path) -> tuple[dict[str, object], int]:
    out = io.StringIO()
    code = run(system, out=out, root=root)
    parsed: dict[str, object] = json.loads(out.getvalue())
    return parsed, code


def test_a_healthy_machine_exits_zero(tmp_path: Path) -> None:
    document, code = run_capturing(FakeSystem(), tmp_path)

    assert code == 0
    assert document["outcome"] == "satisfied"


def test_a_denied_machine_exits_one(tmp_path: Path) -> None:
    """The grep convention: 1 means the analysis ran and found a problem."""
    document, code = run_capturing(FakeSystem(store_writable=True), tmp_path)

    assert code == 1
    assert document["outcome"] == "policy_denied"


def test_no_nix_and_no_flake_is_a_warning_not_a_failure(tmp_path: Path) -> None:
    """THE BRANCH CI HIT, now decided by the policy rather than by an `if`.

    A runner has no Nix and, until flake.nix exists, nothing there depends on
    one. The decision is the same; what changed is that a rule makes it, so it
    appears in the verdicts and is testable in Rego.
    """
    document, code = run_capturing(FakeSystem(executables=()), tmp_path)

    assert code == 0
    assert document["outcome"] == "satisfied"

    warnings = document["warnings"]
    assert isinstance(warnings, list)
    assert any(w["code"] == "WARN_NIX_ABSENT_NOT_REQUIRED" for w in warnings)


def test_no_nix_but_a_flake_present_is_a_hard_failure(tmp_path: Path) -> None:
    """THE GUARD THAT STOPS THE ALLOWANCE BECOMING PERMANENT.

    Once a flake exists the project genuinely cannot build without Nix, so the
    same machine that warned above must now fail. Both conditions are required,
    which is what keeps this from being an escape hatch -- and both are now
    inputs to a rule rather than clauses in a Python condition.
    """
    (tmp_path / "flake.nix").write_text("{ outputs = _: { }; }\n")

    document, code = run_capturing(FakeSystem(executables=()), tmp_path)

    assert code == 1
    assert document["outcome"] == "policy_denied"

    problems = document["problems"]
    assert isinstance(problems, list)
    assert any(p["code"] == "ERR_NIX_ABSENT" for p in problems)


def test_an_absent_nix_still_reports_what_it_found(tmp_path: Path) -> None:
    """A finding that says nothing is indistinguishable from a pass."""
    document, _ = run_capturing(FakeSystem(executables=()), tmp_path)

    warnings = document["warnings"]
    assert isinstance(warnings, list)

    absent = [w for w in warnings if w["code"] == "WARN_NIX_ABSENT_NOT_REQUIRED"]
    assert absent
    assert "not found in any searched directory" in str(absent[0]["message"])


def test_nothing_is_written_to_real_stdout(tmp_path: Path) -> None:
    """The whole point of the extraction: the stream is a parameter."""
    out = io.StringIO()

    run(FakeSystem(), out=out, root=tmp_path)

    assert out.getvalue().strip().startswith("{")
