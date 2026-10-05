"""Tests for the merge protocol.

WHY THESE EXIST
The protocol was verified by running the task once and watching it work. That is
the "worked when I tried it" standard this repo rejects everywhere else, and it
covers only the path the run happened to take -- not the refusals, which are the
part that matters.

Every refusal below is asserted FIRING. A guard seen only passing is
indistinguishable from one that cannot fire, and this project has shipped
exactly that: a Rego rule using a negative lookahead RE2 does not support, which
matched nothing while 21 tests passed.
"""

from __future__ import annotations

import subprocess
import time
from collections.abc import Callable

import pytest
from pydantic import ValidationError

from pr import Check, CheckConclusion, MergeResult, PullRequest, verify_checks


def check(name: str, conclusion: str | None) -> Check:
    return Check.model_validate({"name": name, "conclusion": conclusion})


def test_accepts_every_passing_conclusion() -> None:
    """SUCCESS, NEUTRAL and SKIPPED are all acceptable.

    NEUTRAL and SKIPPED matter: a skipped job is not a failure, and treating it
    as one would block every merge where a path-filtered workflow did not run.
    """
    verify_checks(
        (
            check("gate", "SUCCESS"),
            check("optional", "NEUTRAL"),
            check("path-filtered", "SKIPPED"),
        )
    )


def test_refuses_an_empty_check_list() -> None:
    """FAIL CLOSED: nothing to object to is not approval.

    An empty rollup passed every filter in an earlier version and would have
    merged. It means the workflow never ran or the query returned nothing --
    both reasons to stop, neither a reason to proceed.
    """
    with pytest.raises(SystemExit, match="no checks reported"):
        verify_checks(())


def test_refuses_while_a_check_is_still_running() -> None:
    with pytest.raises(SystemExit, match="still running"):
        verify_checks((check("gate", "SUCCESS"), check("slow", None)))


def test_refuses_a_failure() -> None:
    with pytest.raises(SystemExit, match="unacceptable"):
        verify_checks((check("gate", "FAILURE"),))


def test_refuses_cancelled_timed_out_and_action_required() -> None:
    """None is a pass, and none is a failure a person would notice in passing."""
    for conclusion in ("CANCELLED", "TIMED_OUT", "ACTION_REQUIRED", "STARTUP_FAILURE"):
        with pytest.raises(SystemExit, match="unacceptable"):
            verify_checks((check("gate", conclusion),))


def test_the_refusal_names_the_offending_check() -> None:
    """A refusal that does not say WHICH check sends people to the Actions tab."""
    with pytest.raises(SystemExit, match="quality gate"):
        verify_checks((check("quality gate", "FAILURE"), check("other", "SUCCESS")))


def test_an_empty_conclusion_means_pending() -> None:
    """gh reports a pending check as an empty string, not null.

    The enum found this on its first real call and validation failed during the
    wait the task exists to perform. Normalised so pending has ONE
    representation in this program.
    """
    assert check("gate", "").conclusion is None


def test_an_unknown_conclusion_is_rejected() -> None:
    """Drift detection, which is the point of the enum.

    A string comparison would have accepted anything and silently classified a
    new conclusion as non-passing.
    """
    with pytest.raises(ValidationError):
        check("gate", "SOMETHING_NEW")


def test_merge_result_parses_the_documented_response() -> None:
    result = MergeResult.model_validate(
        {"merged": True, "sha": "abc123", "message": "Pull Request successfully merged"}
    )
    assert result.merged
    assert result.sha == "abc123"


def test_merge_result_rejects_an_unexpected_field() -> None:
    """Forbidding extras is deliberate.

    REST API version 2026-03-10 removed merge_commit_sha from pull request
    responses, and automation reading it "does not crash -- it reads null and
    keeps going", surfacing later as a deploy to the wrong commit. A contract
    that moves should fail at the boundary, not downstream.
    """
    with pytest.raises(ValidationError):
        MergeResult.model_validate({"merged": True, "sha": "abc", "message": "ok", "unexpected": 1})


def test_merge_result_is_frozen() -> None:
    result = MergeResult.model_validate({"merged": True, "sha": "abc", "message": "ok"})

    with pytest.raises(ValidationError, match="frozen"):
        result.merged = False


def test_pull_request_reads_the_camel_case_fields_gh_returns() -> None:
    pull_request = PullRequest.model_validate(
        {
            "number": 19,
            "state": "MERGED",
            "mergeStateStatus": "UNKNOWN",
            "url": "https://example.invalid/pr/19",
            "statusCheckRollup": [{"name": "gate", "conclusion": "SUCCESS"}],
        }
    )

    assert pull_request.is_merged
    assert pull_request.is_terminal
    assert pull_request.checks[0].conclusion is CheckConclusion.SUCCESS


def test_an_open_pull_request_is_not_terminal() -> None:
    pull_request = PullRequest.model_validate(
        {
            "number": 1,
            "state": "OPEN",
            "mergeStateStatus": "BLOCKED",
            "url": "https://example.invalid/pr/1",
            "statusCheckRollup": [],
        }
    )

    assert not pull_request.is_terminal
    assert not pull_request.is_merged


# --- the poll loop -------------------------------------------------------------
#
# THIS REPLACED A WATCH PHASE THAT FAILED THREE DIFFERENT WAYS.
#
# The watch held a long-lived connection to the GraphQL API. It failed by
# returning early with its exit code discarded, then by buying that exit code at
# the cost of live output, then by having the connection reset mid-gate. Each
# fix revealed the next, and the third arrived on the very next run.
#
# Polling has no connection to lose: a failed poll is one that told us nothing.
# These tests cover the two properties that replaced it -- absorb a blip, surface
# a standing failure -- plus the bound, which is the one property that survived
# the deletion.


class FakeCompleted:
    """Enough of CompletedProcess for these tests to read."""

    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


_REAL_RUN = subprocess.run


def _stub_gh(monkeypatch: pytest.MonkeyPatch, answer: Callable[[], FakeCompleted]) -> None:
    """Stub gh, and only gh: every other process runs for real.

    wait_for_checks asks merge.readiness on every poll, through opa (D.19). A stub
    answering every process would hand the policy a fake gh reply, so opa runs for
    real and the policy genuinely decides in every polling test.
    """

    def run(command: list[str], **kwargs: object) -> object:
        if command[:1] == ["gh"]:
            return answer()
        given = kwargs.get("input")
        return _REAL_RUN(
            command,
            input=given if isinstance(given, str) else None,
            capture_output=True,
            text=True,
            check=False,
        )

    monkeypatch.setattr(subprocess, "run", run)


SETTLED_PR = (
    '{"number": 1, "state": "OPEN", "mergeStateStatus": "CLEAN", '
    '"url": "https://example.invalid/pr/1", '
    '"statusCheckRollup": [{"name": "gate", "conclusion": "SUCCESS"}]}'
)

PENDING_PR = (
    '{"number": 1, "state": "OPEN", "mergeStateStatus": "BLOCKED", '
    '"url": "https://example.invalid/pr/1", '
    '"statusCheckRollup": [{"name": "gate", "conclusion": ""}]}'
)


def test_a_failed_poll_is_not_a_verdict(monkeypatch: pytest.MonkeyPatch) -> None:
    """THE BUG THIS LOOP EXISTS TO PREVENT.

    A dropped connection ended a nine-minute wait seconds after it began, and
    the PR sat green and unmerged while the task reported failure. A poll that
    fails has told us nothing about the checks -- it is not evidence either way.
    """
    import pr

    responses = [FakeCompleted(1, stderr="connection reset by peer"), FakeCompleted(0, SETTLED_PR)]
    _stub_gh(monkeypatch, lambda: responses.pop(0))
    monkeypatch.setattr(pr, "poll_delay", lambda: 0)

    observed = pr.wait_for_checks(time.monotonic() + 60)

    assert observed.checks_settled
    assert not responses, "the loop must poll again after a failure, not give up"


def test_a_standing_failure_surfaces_rather_than_polling_forever(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE OPPOSITE BUG, AND IT IS DOCUMENTED JUST AS CLEARLY.

    Monitors that "wrapped every poll in catch { transient }" meant "a standing
    failure silenced the watcher forever". Tolerating a blip must not become
    tolerating an outage.
    """
    import pr

    _stub_gh(monkeypatch, lambda: FakeCompleted(1, stderr="auth failed"))
    monkeypatch.setattr(pr, "poll_delay", lambda: 0)

    with pytest.raises(SystemExit, match="standing failure"):
        pr.wait_for_checks(time.monotonic() + 60)


def test_a_good_poll_resets_the_failure_count(monkeypatch: pytest.MonkeyPatch) -> None:
    """Occasional blips must never accumulate into a false standing failure.

    Two failures, a success, then two more failures is four failures in five
    polls and no outage. Without the reset it would trip the threshold.
    """
    import pr

    responses = [
        FakeCompleted(1, stderr="reset"),
        FakeCompleted(1, stderr="reset"),
        FakeCompleted(0, PENDING_PR),
        FakeCompleted(1, stderr="reset"),
        FakeCompleted(1, stderr="reset"),
        FakeCompleted(0, SETTLED_PR),
    ]
    _stub_gh(monkeypatch, lambda: responses.pop(0))
    monkeypatch.setattr(pr, "poll_delay", lambda: 0)

    observed = pr.wait_for_checks(time.monotonic() + 60)

    assert observed.checks_settled
    assert not responses


def test_the_wait_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    """THE ONE PROPERTY THAT SURVIVED DELETING THE WATCH.

    A wait with no deadline hangs when a workflow never terminates. The bound is
    sized from measurement -- 9m37s observed with a cold Nix store -- and sits
    far below the six-hour GitHub job limit.
    """
    import pr

    _stub_gh(monkeypatch, lambda: FakeCompleted(0, PENDING_PR))
    monkeypatch.setattr(pr, "poll_delay", lambda: 0)

    with pytest.raises(SystemExit, match="did not conclude"):
        pr.wait_for_checks(time.monotonic() + 0.05)

    assert pr.CHECKS_COMPLETE_TIMEOUT > pr.CHECKS_APPEAR_TIMEOUT


def test_the_timeout_message_names_what_was_pending(monkeypatch: pytest.MonkeyPatch) -> None:
    """A timeout that does not say WHICH check sends someone to the Actions tab."""
    import pr

    _stub_gh(monkeypatch, lambda: FakeCompleted(0, PENDING_PR))
    monkeypatch.setattr(pr, "poll_delay", lambda: 0)

    with pytest.raises(SystemExit, match="gate"):
        pr.wait_for_checks(time.monotonic() + 0.05)


def test_an_unparseable_response_is_not_treated_as_settled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A SHAPE CHANGE MUST NOT READ AS SUCCESS.

    GitHub removed a field from pull request responses in API version
    2026-03-10, and automation reading it "does not crash -- it reads null and
    keeps going". Here a response that will not validate counts as a failed
    poll, so it reaches the threshold rather than the merge.
    """
    import pr

    _stub_gh(monkeypatch, lambda: FakeCompleted(0, '{"unexpected": true}'))
    monkeypatch.setattr(pr, "poll_delay", lambda: 0)

    with pytest.raises(SystemExit, match="standing failure"):
        pr.wait_for_checks(time.monotonic() + 60)


def test_jitter_stays_within_a_sensible_spread() -> None:
    """Fixed intervals from several machines "re-poll in lockstep and re-trip
    the shared secondary rate limit". The spread must be real but bounded."""
    import pr

    delays = {pr.poll_delay() for _ in range(50)}

    assert len(delays) > 1, "a constant delay is not jitter"
    assert all(pr.POLL_INTERVAL <= d <= pr.POLL_INTERVAL * 1.5 for d in delays)


def test_a_nonzero_exit_produces_no_observation(monkeypatch: pytest.MonkeyPatch) -> None:
    """THE RETURNCODE CHECK ITSELF, WHICH THE LOOP TEST DOES NOT COVER.

    test_a_failed_poll_is_not_a_verdict passes even with the returncode branch
    disabled, because its fixture has empty stdout -- so validation fails and
    the except clause returns None regardless. Both paths reach the same place,
    which makes that test blind to this line.

    Verified by mutation: replacing `if result.returncode != 0` with `if False`
    left it green. This one asserts the branch directly, with stdout that WOULD
    parse, so only the returncode check can produce the None.
    """
    import pr

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: FakeCompleted(1, stdout=SETTLED_PR, stderr="connection reset by peer"),
    )

    assert pr.observe_pull_request() is None, "a failed call must not be read as an observation"


def test_a_zero_exit_with_valid_output_produces_an_observation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other direction, so the check above cannot pass by rejecting everything."""
    import pr

    _stub_gh(monkeypatch, lambda: FakeCompleted(0, stdout=SETTLED_PR))

    observed = pr.observe_pull_request()

    assert observed is not None
    assert observed.checks_settled
