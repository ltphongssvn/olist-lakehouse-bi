"""Tests for observing a Nix installation, using a fake System.

WHY THESE COULD NOT EXIST BEFORE
observe() called subprocess.run and Path.is_dir directly, so testing it needed a
real Nix -- and a BROKEN real Nix to test the failure paths. The existing tests
sidestepped that by constructing NixInstallation by hand, which covered verify()
and left the collection entirely unexercised: the argv actually passed, the
version string actually parsed, the flake probe.

A FAKE, NOT A MOCK
This returns canned results and records nothing about how it was called. A mock
would let a test assert on call order or argument shape, coupling the test to
the implementation; a fake only has to behave. The guidance is explicit: "test
with fakes, not mocks -- fakes are simpler and more maintainable".

It does not inherit from System. Structural subtyping means having the methods
is enough, and inheriting would defeat the point of a Protocol.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nix_contract import (
    NIX_RECEIPT,
    NIX_STORE,
    observe,
)
from nix_models import NIX_INSTALLER
from nix_system import CommandResult

PROFILE_NIX = Path("/nix/var/nix/profiles/default/bin/nix")
STORE_NIX = NIX_STORE / "c4rn9q0v4f2kpkci2ghg36r729w9j6sg-determinate-nix-3.22.3" / "bin" / "nix"

DETERMINATE_VERSION = "nix (Determinate Nix 3.22.3) 2.35.2\n"


class FakeSystem:
    """A System that answers from a script rather than from the machine."""

    def __init__(
        self,
        *,
        executables: tuple[Path, ...] = (PROFILE_NIX, NIX_INSTALLER),
        resolved: dict[Path, Path] | None = None,
        results: dict[str, CommandResult] | None = None,
        directories: tuple[Path, ...] = (NIX_STORE,),
        files: tuple[Path, ...] = (NIX_RECEIPT,),
        files_text: dict[Path, str] | None = None,
        store_writable: bool = False,
        store_owner: str = "root",
        store_mode: int = 0o1775,
        build_group: tuple[int, tuple[str, ...]] | None = None,
        shells: dict[str, str] | None = None,
        system: str = "aarch64-darwin",
    ) -> None:
        self.executables = executables
        self.resolved = resolved or {PROFILE_NIX: STORE_NIX}
        self.results = results or {}
        self.directories = directories
        self.files = files
        self.store_writable = store_writable
        self.store_owner = store_owner
        self.store_mode = store_mode
        self.build_group = (
            build_group
            if build_group is not None
            else (350, tuple(f"_nixbld{n}" for n in range(1, 33)))
        )
        self.shells = shells or {}
        self.system = system
        # A structurally valid receipt by default: the observed shape is
        # {"version", "planner", "actions"} with a non-empty action list.
        self.files_text = files_text or {
            NIX_RECEIPT: json.dumps(
                {
                    "version": "3.22.3",
                    "planner": "macos",
                    "actions": [{"action": {}, "state": "Completed"}],
                }
            )
        }

    def run(self, *args: str | Path, cwd: Path | None = None) -> CommandResult:
        """Dispatch on the SUBCOMMAND, not the whole argv.

        Keying on the full command line would make every test restate the exact
        arguments, which is the coupling a fake exists to avoid.
        """
        tokens = [str(argument) for argument in args]
        for key, result in self.results.items():
            if key in tokens:
                return result

        if "--version" in tokens:
            return CommandResult(returncode=0, stdout=DETERMINATE_VERSION)
        return CommandResult(returncode=0)

    def is_dir(self, path: Path) -> bool:
        return path in self.directories

    def is_file(self, path: Path) -> bool:
        return path in self.files

    def is_executable_file(self, path: Path) -> bool:
        return path in self.executables

    def resolve(self, path: Path) -> Path:
        return self.resolved.get(path, path)

    def write_probe_flake(self, directory: Path) -> None:
        """A fake writes nothing: there is no flake to evaluate."""

    def group_members(self, name: str) -> tuple[int, tuple[str, ...]] | None:
        """Defaults to the real footprint: gid 350, 32 members.

        Read off this machine rather than invented, so a test asserting the
        healthy path asserts against a shape that exists.
        """
        return self.build_group

    def user_shell(self, name: str) -> str | None:
        """Every build user gets nologin unless a test says otherwise.

        A test wanting the compromised case passes shells={"_nixbld7": "/bin/zsh"}.
        """
        return self.shells.get(name, "/sbin/nologin")

    def is_writable_by_me(self, path: Path) -> bool:
        """Defaults to NOT writable, which is the safe direction.

        A test wanting the compromised-store case passes store_writable=True.
        Defaulting the other way would make every existing test silently
        exercise a broken trust model.
        """
        return self.store_writable

    def owner_and_mode(self, path: Path) -> tuple[str, int]:
        """Defaults to what a correct macOS installation actually reports:
        root:nixbld, mode 1775 -- read off this machine, not invented."""
        return self.store_owner, self.store_mode

    def platform_double(self) -> str:
        """Defaults to this machine's real shape, overridable per test.

        A test judging a Linux machine passes system="x86_64-linux" rather than
        inheriting the author's laptop -- which is how the build-group rule came
        to assume Darwin in the first place.
        """
        return self.system

    def read_text(self, path: Path) -> str:
        """Canned file contents, so receipt validation is testable.

        Defaults to a structurally valid receipt. A test wanting the
        touch-created case passes receipt_text="".
        """
        return self.files_text.get(path, "")


def test_observes_a_healthy_installation() -> None:
    installation = observe(FakeSystem())

    assert installation.binary == STORE_NIX
    assert installation.semantic_version == (2, 35, 2)
    assert installation.store_exists
    assert installation.receipt_exists
    assert installation.can_evaluate
    assert installation.can_evaluate_a_flake


def test_the_profile_symlink_is_resolved_into_the_store() -> None:
    """The conflation that broke an earlier version.

    nix is FOUND in the profile and RESOLVES into the store. A contract
    requiring the resolved path to be inside a search directory refused Nix
    itself.
    """
    installation = observe(FakeSystem())

    assert installation.is_from_the_store


def test_a_missing_nix_is_observed_rather_than_raised() -> None:
    """ABSENCE IS A RESULT, NOT AN EXCEPTION.

    This used to assert a raise. Searching four directories and finding nothing
    is a SUCCESSFUL search with a negative result -- the same way querying an
    account and finding zero resources is a fact. Raising forced a special-case
    branch in run() that no policy rule covered and no verdict reported.
    """
    installation = observe(FakeSystem(executables=()))

    assert not installation.nix_present
    assert installation.binary is None
    assert installation.searched, "an absence must name where it looked"


def test_a_binary_that_will_not_report_its_version_is_observed() -> None:
    """A DIFFERENT FACT FROM AN ABSENT ONE, and worse: something is there and it
    does not work. Collapsing the two would lose that distinction."""
    system = FakeSystem(
        results={"--version": CommandResult(returncode=1, stderr="segmentation fault")}
    )

    installation = observe(system)

    assert installation.nix_present, "the binary exists; it just does not answer"
    assert installation.binary is not None
    assert installation.version == ""
    assert "segmentation fault" in installation.evaluate_error


def test_an_absent_store_is_observed() -> None:
    installation = observe(FakeSystem(directories=()))

    assert not installation.store_exists


def test_an_absent_receipt_is_observed() -> None:
    installation = observe(FakeSystem(files=()))

    assert not installation.receipt_exists


def test_a_nix_that_cannot_evaluate_is_observed() -> None:
    """The upstream-with-flakes-disabled case, without needing such a machine."""
    system = FakeSystem(results={"eval": CommandResult(returncode=1, stderr="not allowed")})

    installation = observe(system)

    assert not installation.can_evaluate


def test_a_nix_that_cannot_evaluate_a_flake_is_observed() -> None:
    system = FakeSystem(results={"metadata": CommandResult(returncode=1)})

    installation = observe(system)

    assert not installation.can_evaluate_a_flake


def test_the_store_verify_status_is_carried_through() -> None:
    """2 is untrusted-by-signature, which is what a substituted binary reports."""
    system = FakeSystem(results={"verify": CommandResult(returncode=2)})

    installation = observe(system)

    assert installation.store_verify_status == 2
    assert installation.is_untrusted
    assert not installation.is_corrupted


def test_a_binary_resolving_outside_a_trusted_root_is_refused() -> None:
    """The drift case: a Homebrew nix reached through a profile symlink."""
    from pydantic import ValidationError

    system = FakeSystem(resolved={PROFILE_NIX: Path("/opt/homebrew/bin/nix")})

    with pytest.raises(ValidationError, match="outside every trusted root"):
        observe(system)
