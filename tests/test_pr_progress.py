"""Waiting for checks reports what changed, not what is still true.

WHY THIS EXISTS. The poll loop printed its pending list on every pass, so a
one-minute gate produced a dozen identical "waiting: quality gate" lines in a
terminal and in every recorded run. The loop had no test of what it prints --
only its predicates were tested -- which is how the repetition shipped.

TWO RULES. A line when the pending set changes. And, only after a long
unchanged stretch, a heartbeat carrying the elapsed time, because a wait that
prints nothing for ten minutes looks exactly like a hang.
"""

from __future__ import annotations

import pytest

import pr
from pr import HEARTBEAT, POLL_INTERVAL, Progress, PullRequest, report


def pull_request(*conclusions: str | None) -> PullRequest:
    return PullRequest.model_validate(
        {
            "number": 1,
            "state": "OPEN",
            # WHAT GITHUB REPORTS: CLEAN once every check has concluded, BLOCKED while
            # any is pending -- the state merge.readiness now decides on (D.19).
            "mergeStateStatus": ("CLEAN" if conclusions and None not in conclusions else "BLOCKED"),
            "url": "https://example.invalid/pr/1",
            "statusCheckRollup": [
                {"name": "quality gate", "conclusion": conclusion} for conclusion in conclusions
            ],
        }
    )


def test_the_first_poll_says_what_it_waits_for() -> None:
    _, line = report(Progress(), "quality gate", now=0.0)
    assert line == "waiting: quality gate"


def test_the_same_pending_set_says_nothing_again() -> None:
    """THE RULE: an unchanged state is not news."""
    state, _ = report(Progress(), "quality gate", now=0.0)
    _, line = report(state, "quality gate", now=6.0)
    assert line is None


def test_a_change_is_reported() -> None:
    state, _ = report(Progress(), "quality gate, zizmor", now=0.0)
    _, line = report(state, "quality gate", now=6.0)
    assert line == "waiting: quality gate"


def test_a_long_silence_gets_a_heartbeat_with_the_elapsed_time() -> None:
    """A quiet wait must still show it is alive."""
    state, _ = report(Progress(), "quality gate", now=0.0)
    _, line = report(state, "quality gate", now=float(HEARTBEAT))
    assert line is not None and line.startswith("still waiting: quality gate")
    assert "1m" in line, line


def test_a_heartbeat_does_not_repeat_on_the_next_poll() -> None:
    state, _ = report(Progress(), "quality gate", now=0.0)
    state, beat = report(state, "quality gate", now=float(HEARTBEAT))
    assert beat is not None
    _, again = report(state, "quality gate", now=HEARTBEAT + POLL_INTERVAL * 1.5)
    assert again is None


def test_the_heartbeat_is_far_slower_than_a_poll() -> None:
    """A heartbeat shorter than the slowest poll would fire every pass."""
    assert HEARTBEAT > POLL_INTERVAL * 1.5 * 4


class _Clock:
    """Time that moves only when the loop sleeps."""

    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def _run(
    polls: list[PullRequest],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> list[str]:
    remaining = iter(polls)
    clock = _Clock()
    monkeypatch.setattr(pr, "observe_pull_request", lambda: next(remaining))
    monkeypatch.setattr(pr, "time", clock)
    pr.wait_for_checks(deadline=10_000.0)
    return [line for line in capsys.readouterr().out.splitlines() if "waiting" in line]


def test_the_real_loop_prints_one_line_for_an_unchanged_wait(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """THE TEST THE LOOP NEVER HAD: five identical polls, then done."""
    printed = _run([pull_request(None)] * 5 + [pull_request("SUCCESS")], monkeypatch, capsys)
    assert printed == ["waiting: quality gate"], printed


def test_the_real_loop_beats_once_through_a_long_wait(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    printed = _run([pull_request(None)] * 15 + [pull_request("SUCCESS")], monkeypatch, capsys)
    assert printed[0] == "waiting: quality gate"
    assert sum(line.startswith("still waiting") for line in printed) == 1, printed
