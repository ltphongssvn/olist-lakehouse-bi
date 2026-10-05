"""Tests for the check-settling race.

WHY THIS EXISTS
`gh pr checks --watch` returns when each check RUN reaches a terminal state. The
pull request's statusCheckRollup is a different view and lags it: querying
immediately after --watch printed "All checks were successful" still returned
conclusion "" -- pending -- and the merge was refused as "still running".

Two views of the same fact, updated at different times. Treating the faster one
as authoritative for the slower one is the race, and it stopped a release.

These tests cover the predicate that resolves it. The waiting loop itself polls
a live API and is exercised by every `mise run pr`.
"""

from __future__ import annotations

from pr import PullRequest


def pull_request(*conclusions: str | None, state: str = "OPEN") -> PullRequest:
    return PullRequest.model_validate(
        {
            "number": 1,
            "state": state,
            "mergeStateStatus": "BLOCKED",
            "url": "https://example.invalid/pr/1",
            "statusCheckRollup": [
                {"name": f"check-{index}", "conclusion": conclusion}
                for index, conclusion in enumerate(conclusions)
            ],
        }
    )


def test_settled_when_every_check_has_a_conclusion() -> None:
    assert pull_request("SUCCESS", "SUCCESS").checks_settled


def test_not_settled_while_one_reports_pending() -> None:
    """The exact state that refused the release.

    gh reports pending as an empty string, which the model normalises to None.
    """
    assert not pull_request("SUCCESS", "").checks_settled


def test_not_settled_when_the_rollup_is_empty() -> None:
    """FAIL CLOSED: no checks is not "all checks concluded".

    An empty rollup satisfies `all(...)` vacuously, so without the explicit
    emptiness test this would report settled and hand an empty tuple to
    verify_checks -- which refuses it, but for a reason two steps removed from
    the truth.
    """
    assert not pull_request().checks_settled


def test_settled_with_mixed_acceptable_conclusions() -> None:
    """Settling is about REPORTING, not about passing.

    A FAILURE has concluded. verify_checks decides whether it is acceptable;
    conflating the two questions would make a failing check wait forever.
    """
    assert pull_request("SUCCESS", "FAILURE", "SKIPPED").checks_settled
