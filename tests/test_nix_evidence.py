"""Prove that a recorded observation replays to the same verdict.

WHY THIS TEST IS THE POINT
Without it, nix_evidence.py is a plausible-looking mechanism nobody has
exercised -- and a replayer that silently diverged would be worse than none,
because a wrong answer that looks like evidence is harder to doubt than no
answer at all.

The property being asserted is the one record-and-replay exists for: "if all
inputs and nondeterminism have truly been captured, the state during replay will
match that during recording."

RECORDED FROM A FAKE, NOT THE REAL MACHINE. The fake is deterministic, so a
divergence means the recorder or replayer is wrong rather than the machine
having changed between the two runs -- which is the only way this test can
accuse the right component.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from test_nix_observe import FakeSystem

from nix_contract import observe, verify
from nix_evidence import EvidenceBundle, RecordingSystem, ReplaySystem, UnrecordedCallError


def record(system: FakeSystem) -> EvidenceBundle:
    recorder = RecordingSystem(system)
    observe(recorder)
    return recorder.bundle()


def test_a_replayed_observation_matches_the_recorded_one() -> None:
    """The whole property, on a healthy machine."""
    original = observe(FakeSystem())
    bundle = record(FakeSystem())

    replayed = observe(ReplaySystem(bundle))

    # Probes carry durations, which differ between runs by design. Everything
    # the VERDICT depends on must match exactly.
    assert replayed.binary == original.binary
    assert replayed.semantic_version == original.semantic_version
    assert replayed.store_exists == original.store_exists
    assert replayed.receipt_is_valid == original.receipt_is_valid
    assert replayed.can_evaluate == original.can_evaluate
    assert replayed.can_evaluate_a_flake == original.can_evaluate_a_flake
    assert replayed.store_verify_status == original.store_verify_status
    assert replayed.build_users_with_login_shells == original.build_users_with_login_shells


def test_the_verdict_survives_a_round_trip() -> None:
    """What an auditor actually asks: did this conclusion follow from this evidence?"""
    original = verify(observe(FakeSystem()))
    replayed = verify(observe(ReplaySystem(record(FakeSystem()))))

    assert replayed.codes == original.codes
    assert replayed.satisfied == original.satisfied


def test_a_failing_machine_replays_its_failures() -> None:
    """A bundle from a BROKEN machine must reproduce the same problems.

    The healthy case passing proves less than this: a replayer that returned
    defaults for everything would satisfy the happy path and lose every fault.
    """
    broken = FakeSystem(
        directories=(),
        store_writable=True,
        shells={"_nixbld7": "/bin/zsh"},
    )

    original = verify(observe(broken))
    replayed = verify(observe(ReplaySystem(record(broken))))

    assert original.codes, "the broken fixture produced no problems; it is not broken"
    assert replayed.codes == original.codes


def test_the_recorded_platform_survives_replay() -> None:
    """A DARWIN RECORDING STAYS DARWIN WHEREVER IT IS REPLAYED.

    Reading the local platform during replay would judge a recorded machine by
    the host that happens to replay it -- which is precisely the
    machine-dependence record-and-replay exists to remove. The contract now has
    platform-specific rules, so this is load-bearing rather than cosmetic.
    """
    bundle = record(FakeSystem(system="x86_64-linux"))

    assert bundle.platform == "x86_64-linux"
    assert observe(ReplaySystem(bundle)).system == "x86_64-linux"


def test_a_bundle_with_no_platform_refuses_rather_than_guessing() -> None:
    """An older bundle predates the field. Guessing the local platform would
    silently judge it by the wrong rules."""
    with pytest.raises(UnrecordedCallError, match="records no platform"):
        ReplaySystem(EvidenceBundle()).platform_double()


def test_replay_refuses_a_call_it_has_no_record_of() -> None:
    """Fails rather than guessing.

    An invented answer would produce a verdict from data that never existed --
    which looks like evidence and is not.
    """
    empty = ReplaySystem(EvidenceBundle())

    with pytest.raises(UnrecordedCallError, match="not in the evidence bundle"):
        empty.is_dir(Path("/nix/store"))


def test_replay_writes_nothing() -> None:
    """A replayed observation that touched the filesystem would not be a replay."""
    nowhere = Path("/nonexistent-directory-that-must-not-be-created")

    ReplaySystem(EvidenceBundle()).write_probe_flake(nowhere)

    assert not nowhere.exists()


def test_a_bundle_survives_serialisation() -> None:
    """It has to travel: the point is diagnosing a machine you do not have."""
    bundle = record(FakeSystem())

    restored = EvidenceBundle.model_validate_json(bundle.model_dump_json())

    assert (
        verify(observe(ReplaySystem(restored))).codes == verify(observe(ReplaySystem(bundle))).codes
    )


def test_the_command_key_does_not_collide() -> None:
    """A space separator would make ("a b",) and ("a", "b") the same call."""
    assert EvidenceBundle.key("a b") != EvidenceBundle.key("a", "b")


def test_recording_does_not_change_what_is_observed() -> None:
    """The recorder must be transparent.

    A wrapper that altered the observation would make every bundle a record of
    the wrapper rather than the machine.
    """
    direct = observe(FakeSystem())
    through_recorder = observe(RecordingSystem(FakeSystem()))

    assert through_recorder.binary == direct.binary
    assert through_recorder.store_verify_status == direct.store_verify_status
