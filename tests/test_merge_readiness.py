# tests/test_merge_readiness.py
"""A pull request merges on GitHub's own verdict, decided by policy (D.19).

WHAT BROKE. Release's promotion PR had a finished check on its head commit --
develop's own push run -- so every VISIBLE check was green while the PR's required
run had not registered. The merge was attempted and refused: GitHub's
mergeStateStatus said BLOCKED, which it reports while required checks are queued.

THE PAIR. MergeState admits exactly GitHub's eight values; merge.readiness decides
wait, merge or refuse from the state and every check; the wait loop returns only
on a decision. These tests prove it bites.
"""

from __future__ import annotations

import time

import pytest
from pydantic import ValidationError

import pr
from pr import PullRequest, readiness


def _pr(state: str, *checks: tuple[str, str]) -> PullRequest:
    return PullRequest.model_validate(
        {
            "number": 58,
            "state": "OPEN",
            "mergeStateStatus": state,
            "url": "https://example.invalid/pull/58",
            "statusCheckRollup": [{"name": name, "conclusion": c} for name, c in checks],
        }
    )


def test_a_blocked_pr_with_every_visible_check_green_waits() -> None:
    """THE REGRESSION: one finished check on the head commit, the required run unseen."""
    assert readiness(_pr("BLOCKED", ("quality gate", "SUCCESS"))).decision == "wait"


def test_a_clean_pr_with_every_check_green_merges() -> None:
    """THE CONTROL: a policy that always waits would pass the rest."""
    assert readiness(_pr("CLEAN", ("quality gate", "SUCCESS"))).decision == "merge"


def test_a_pending_check_waits() -> None:
    assert readiness(_pr("CLEAN", ("quality gate", ""))).decision == "wait"


def test_a_failed_check_refuses_naming_it() -> None:
    verdict = readiness(_pr("BLOCKED", ("quality gate", "FAILURE")))
    assert verdict.decision == "refuse"
    assert any(
        r.startswith("[ERR_MERGE_CHECK_FAILED]") and "quality gate" in r for r in verdict.reasons
    )


def test_a_conflicting_pr_refuses() -> None:
    verdict = readiness(_pr("DIRTY", ("quality gate", "SUCCESS")))
    assert verdict.decision == "refuse"
    assert any(r.startswith("[ERR_MERGE_CONFLICTING]") for r in verdict.reasons)


def test_an_unknown_merge_state_fails_at_the_boundary() -> None:
    """GitHub spells a conflict DIRTY; CONFLICTING is not one of its states."""
    with pytest.raises(ValidationError):
        _pr("CONFLICTING", ("quality gate", "SUCCESS"))


def test_the_wait_returns_only_on_a_decision(monkeypatch: pytest.MonkeyPatch) -> None:
    polls = iter(
        (_pr("BLOCKED", ("quality gate", "SUCCESS")), _pr("CLEAN", ("quality gate", "SUCCESS")))
    )
    seen: list[PullRequest] = []

    def observe() -> PullRequest:
        seen.append(next(polls))
        return seen[-1]

    monkeypatch.setattr(pr, "observe_pull_request", observe)
    monkeypatch.setattr(pr, "poll_delay", lambda: 0.0)
    returned = pr.wait_for_checks(time.monotonic() + 30)
    assert returned.merge_state == "CLEAN"
    assert len(seen) == 2
