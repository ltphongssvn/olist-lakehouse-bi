"""Tests for the Nix installation contract.

WHY THESE EXIST
The contract's claims were verified by running it once against one machine.
That confirms the happy path on this laptop and nothing else -- not the
refusals, which are the part that matters, and not the parsing, which is where
the subtle mistakes live.

Every refusal below is asserted FIRING. A guard seen only passing is
indistinguishable from one that cannot fire, and this repository has shipped
exactly that.

CONSTRUCTED, NOT OBSERVED. Every case builds a NixInstallation directly rather
than touching the real machine, so the failure paths are reachable without a
broken Nix to test against.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from nix_contract import (
    NIX_STORE,
    ContractProblem,
    ContractReport,
    NixInstallation,
    ProblemCode,
    UntrustedBinaryError,
    resolve_binary,
    verify,
)
from nix_models import ProbeOutcome
from nix_remediation import Autonomy, Remediation
from nix_system import RealSystem, clean_env

STORE_BINARY = NIX_STORE / "c4rn9q0v4f2kpkci2ghg36r729w9j6sg-determinate-nix-3.22.3" / "bin" / "nix"


def installation(**overrides: object) -> NixInstallation:
    """A satisfying installation, unless an override says otherwise."""
    defaults: dict[str, object] = {
        "binary": STORE_BINARY,
        "version": "nix (Determinate Nix 3.22.3) 2.35.2",
        "store_exists": True,
        "receipt_exists": True,
        "receipt_is_valid": True,
        "uninstaller_exists": True,
        "evaluate_outcome": ProbeOutcome.OK,
        "flake_outcome": ProbeOutcome.OK,
        "store_verify_status": 0,
    }
    return NixInstallation(**{**defaults, **overrides})  # type: ignore[arg-type]


def test_a_healthy_installation_satisfies_the_contract() -> None:
    report = verify(installation())

    assert report.satisfied
    assert report.problems == ()


def test_the_nix_version_is_taken_not_the_distribution_version() -> None:
    """Determinate reports TWO version numbers.

    "nix (Determinate Nix 3.22.3) 2.35.2" -- 3.22.3 is the distribution, 2.35.2
    is Nix. Taking the first would compare an unrelated number against the
    version floor, and would happen to PASS, which is worse than failing.
    """
    assert installation().semantic_version == (2, 35, 2)


def test_an_upstream_version_string_also_parses() -> None:
    """Upstream reports one number, and the same rule must handle it."""
    assert installation(version="nix (Nix) 2.18.1").semantic_version == (2, 18, 1)


def test_a_version_below_the_floor_is_refused() -> None:
    report = verify(installation(version="nix (Nix) 2.3.16"))

    assert not report.satisfied
    assert ProblemCode.VERSION_BELOW_FLOOR in report.codes


def test_a_missing_store_is_refused() -> None:
    report = verify(installation(store_exists=False))

    assert ProblemCode.STORE_NOT_MOUNTED in report.codes


def test_an_installation_that_cannot_evaluate_is_refused() -> None:
    report = verify(installation(evaluate_outcome=ProbeOutcome.FEATURE_DISABLED))

    assert ProblemCode.CANNOT_EVALUATE in report.codes


def test_an_installation_without_flakes_is_refused() -> None:
    """flake.nix and flake.lock are the toolchain declaration."""
    report = verify(installation(flake_outcome=ProbeOutcome.DAEMON_UNREACHABLE))

    assert ProblemCode.CANNOT_EVALUATE_FLAKE in report.codes


def test_a_missing_receipt_is_refused() -> None:
    """Without it the machine cannot be cleanly reverted."""
    report = verify(installation(receipt_exists=False, receipt_is_valid=False))

    assert ProblemCode.NO_UNINSTALL_RECEIPT in report.codes


def test_a_present_but_invalid_receipt_is_refused() -> None:
    """The touch-created case.

    `touch /nix/receipt.json` satisfied the old existence check and reported
    uninstallable: true on a machine with no uninstaller -- existence standing
    in for authenticity.
    """
    report = verify(installation(receipt_exists=True, receipt_is_valid=False))

    assert ProblemCode.NO_UNINSTALL_RECEIPT in report.codes


def test_a_valid_receipt_without_the_installer_binary_is_refused() -> None:
    """Both artefacts are required.

    The documented procedure is `/nix/nix-installer uninstall`, which READS the
    receipt -- so a receipt without the binary cannot be used.
    """
    report = verify(installation(uninstaller_exists=False))

    assert ProblemCode.NO_UNINSTALL_RECEIPT in report.codes


def test_uninstallability_requires_both_artefacts() -> None:
    assert installation().is_uninstallable
    assert not installation(receipt_is_valid=False).is_uninstallable
    assert not installation(uninstaller_exists=False).is_uninstallable


def test_corruption_is_refused_but_an_untrusted_signature_is_not() -> None:
    """The distinction the contract exists to make.

    Status 2 means untrusted-by-signature, which every substituted binary
    reports and which is not a defect. Status 1 means the contents do not match
    the recorded NAR hash, which is.
    """
    assert verify(installation(store_verify_status=2)).satisfied
    assert not verify(installation(store_verify_status=1)).satisfied


def test_a_summed_status_is_decoded_bitwise() -> None:
    """3 is corrupted AND untrusted.

    An equality test against 1 would miss it, and the exit code is documented
    as a SUM.
    """
    corrupted_and_untrusted = installation(store_verify_status=3)

    assert corrupted_and_untrusted.is_corrupted
    assert corrupted_and_untrusted.is_untrusted
    assert not verify(corrupted_and_untrusted).satisfied


def test_every_problem_is_reported_at_once() -> None:
    """Fix-one, rerun, discover-the-next is the treadmill this removes."""
    report = verify(
        installation(
            store_exists=False,
            evaluate_outcome=ProbeOutcome.FEATURE_DISABLED,
            flake_outcome=ProbeOutcome.DISK_FULL,
            receipt_exists=False,
            receipt_is_valid=False,
        )
    )

    assert len(report.problems) == 4


def test_a_binary_outside_every_trusted_root_is_rejected() -> None:
    """The drift case: a Homebrew nix shadowing the Nix-managed one.

    This is the failure the whole plan exists to prevent -- dual ownership,
    where PATH decides which binary runs. Homebrew is also where today's Python
    3.14 defect came from, so it is the realistic path rather than a contrived
    one."""
    with pytest.raises(ValidationError, match="outside every trusted root"):
        installation(binary=Path("/opt/homebrew/bin/nix"))


def test_a_relative_binary_path_is_rejected() -> None:
    """The documented shape of the '.'-on-PATH attack."""
    with pytest.raises(ValidationError, match="not absolute"):
        installation(binary=Path("nix"))


def test_the_report_is_frozen() -> None:
    report = ContractReport(
        problems=(
            ContractProblem(
                code=ProblemCode.NO_UNINSTALL_RECEIPT,
                message="x",
                remediation=Remediation(description="y", autonomy=Autonomy.ALERT),
            ),
        )
    )

    with pytest.raises(ValidationError, match="frozen"):
        report.problems = ()


def test_clean_env_excludes_every_nix_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    """NIX_CONFIG alone can enable experimental features.

    Inherited, it would let the probe certify a capability the project's real
    shell does not have.
    """
    monkeypatch.setenv("NIX_CONFIG", "experimental-features = nix-command flakes")
    monkeypatch.setenv("NIX_PATH", "/somewhere")
    monkeypatch.setenv("LD_LIBRARY_PATH", "/malicious")

    environment = clean_env()

    assert not any(name.startswith("NIX_") for name in environment)
    assert "LD_LIBRARY_PATH" not in environment


def test_clean_env_pins_path_to_trusted_directories(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", "/malicious/bin:/usr/bin")

    assert "/malicious/bin" not in clean_env()["PATH"]


def test_resolving_a_nonexistent_binary_raises() -> None:
    """Unevaluable, not unsatisfied -- so an exception rather than a report."""
    with pytest.raises(UntrustedBinaryError, match="not found in any searched directory"):
        resolve_binary(RealSystem(), "a-binary-that-does-not-exist")
