"""The findings and the verdicts must agree, enforced by the model.

WHY THE INVARIANT IS IN THE MODEL, NOT HERE
A test checks a relationship where it happens to look. A validator checks it
everywhere a report is constructed -- in replay, in the fake-driven tests, and
in any caller written later.

WHY EXHAUSTIVE RATHER THAN PROPERTY-BASED
Hypothesis is the right tool when an input space is too large to enumerate, and
the framing that motivates it is exact: "example-based unit tests catch a
specific bug; mechanical invariants catch the class of bug."

This space is small enough to enumerate COMPLETELY -- which codes fired, crossed
with what verdict each carries. Exhaustive enumeration is strictly stronger than
random sampling over the same space, and it adds no dependency. Sampling would
be a weaker check bought at a higher price.

The example tests below remain, because a named case documents WHY a
combination is illegal in a way a generated counterexample does not.
"""

from __future__ import annotations

import itertools

import pytest
from pydantic import ValidationError

from nix_contract import ContractReport
from nix_remediation import Autonomy, ContractProblem, Remediation

CODES = ("ERR_A", "ERR_B", "WARN_C")
VERDICTS = ("pass", "fail")


def problem(code: str) -> ContractProblem:
    return ContractProblem(
        code=code,
        message="x",
        remediation=Remediation(description="y", autonomy=Autonomy.ALERT),
    )


def test_the_invariant_holds_over_every_combination() -> None:
    """EXHAUSTIVE: every subset of fired codes against every verdict assignment.

    2^3 subsets x 2^3 assignments = 64 cases, all checked. A report is
    constructible exactly when each code's verdict is "fail" if and only if it
    fired.
    """
    checked = 0

    for fired_count in range(len(CODES) + 1):
        for fired in itertools.combinations(CODES, fired_count):
            for assignment in itertools.product(VERDICTS, repeat=len(CODES)):
                verdicts = dict(zip(CODES, assignment, strict=True))
                should_be_valid = all(
                    (verdicts[code] == "fail") == (code in fired) for code in CODES
                )
                checked += 1

                if should_be_valid:
                    report = ContractReport(
                        problems=tuple(problem(code) for code in fired),
                        verdicts=verdicts,
                    )
                    assert report.satisfied == (not fired)
                else:
                    with pytest.raises(ValidationError):
                        ContractReport(
                            problems=tuple(problem(code) for code in fired),
                            verdicts=verdicts,
                        )

    assert checked == 2 ** len(CODES) * 2 ** len(CODES), "the space was not fully covered"


def test_a_fired_code_missing_from_verdicts_is_refused() -> None:
    """Not reachable by the enumeration above, which always supplies every code.

    A verdict block that omits a rule that fired claims to cover every rule
    while hiding the one that failed.
    """
    with pytest.raises(ValidationError, match="absent from verdicts"):
        ContractReport(problems=(problem("ERR_A"),), verdicts={"ERR_B": "pass"})


def test_a_verdict_outside_pass_or_fail_is_refused() -> None:
    with pytest.raises(ValidationError, match="must be pass or fail"):
        ContractReport(problems=(), verdicts={"ERR_A": "maybe"})


def test_a_warning_counts_as_fired_without_making_the_contract_unsatisfied() -> None:
    """Warnings are rules: their verdict says they fired, severity is separate."""
    report = ContractReport(warnings=(problem("WARN_C"),), verdicts={"WARN_C": "fail"})

    assert report.verdicts["WARN_C"] == "fail"
    assert report.satisfied


def test_a_report_without_verdicts_is_still_valid() -> None:
    """Permitted deliberately: there is nothing to cross-check.

    Refusing it would break every test that builds a report directly, for no
    gain -- an empty verdict block cannot mislead anyone into thinking a rule
    passed.
    """
    ContractReport(problems=(problem("ERR_A"),))
