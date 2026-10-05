"""The impure boundary: subprocesses and filesystem probes, behind a Protocol.

WHY THIS EXISTS
scripts/nix_contract.py called subprocess.run and Path.is_dir directly inside
observe(), which made that function untestable without a real Nix installation.
The tests worked around it by constructing NixInstallation by hand -- so verify()
was covered and the COLLECTION was not: the subprocess invocations, the version
string actually returned, the flake probe.

The standard this violates is stated plainly elsewhere: "outside a composition
root, a package must not call an impure stdlib entry point -- the clock, the
global random source, the network, a subprocess -- directly."

A PROTOCOL, NOT AN ABC
Protocols are structural: an implementer satisfies one by having the methods,
with no inheritance. That is what a boundary wants -- a test fake should not
need to import and subclass anything. ABCs are for sharing implementation
between subclasses, which is not the situation here.

FAKES, NOT MOCKS
The test double lives in the test file and returns canned results. Mock
libraries let a test assert on HOW a function was called, which couples the test
to the implementation; a fake only has to behave.

THE ENVIRONMENT SANITIZATION LIVES HERE
It belongs with the subprocess call it protects, not in the module that happens
to need one. NIX_* is excluded by construction -- an inherited NIX_CONFIG can
enable flakes for a probe while the project's real shell has them off,
certifying a capability that does not exist.
"""

from __future__ import annotations

import grp
import os
import platform
import pwd
import stat
import subprocess
import time
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict

__all__ = [
    "PASSTHROUGH_VARIABLES",
    "SEARCH_DIRS",
    "CommandResult",
    "RealSystem",
    "System",
    "clean_env",
]

# WHERE A BINARY NAME IS LOOKED UP. Never PATH, which is the input this guards
# against: "an attacker who can prepend a directory to PATH -- a CI runner
# stage, a malicious dotfile -- substitutes their own binary."
SEARCH_DIRS = (
    Path("/nix/var/nix/profiles/default/bin"),
    Path("/run/current-system/sw/bin"),
    Path("/usr/bin"),
    Path("/bin"),
)

# DEFAULT-DENY, built rather than filtered: a variable added tomorrow is
# excluded by default instead of allowed by omission.
PASSTHROUGH_VARIABLES = ("HOME", "USER", "TMPDIR")


class CommandResult(BaseModel):
    """What a command did. Frozen: an observation that can be edited is not one.

    ARGV AND DURATION ARE PART OF THE OBSERVATION, not incidental.
    A record of "it failed" without what ran and how long it took is what a
    production runner calls insufficient: the requirement is "structured
    exit/timing evidence", because a controller "recording only subprocess exit
    status would miss the distinction".
    """

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    argv: tuple[str, ...] = ()
    returncode: int
    stdout: str = ""
    stderr: str = ""
    duration_ms: int = 0

    @property
    def succeeded(self) -> bool:
        return self.returncode == 0

    @property
    def killed_by_signal(self) -> bool:
        """A NEGATIVE returncode is a SIGNAL NUMBER, not an exit code.

        Python documents it: "a negative value -N indicates that the child was
        terminated by signal N". Treating it as an exit code is a documented bug
        class -- one project's fix reads "when a child process is killed by a
        signal, the returned exit status is simply corrupted".

        It matters here concretely. `nix store verify` returns SUMMED FLAGS, and
        the contract reads them bitwise. Under SIGKILL the returncode is -9, and
        -9 & 1 is 1 -- so a killed probe reported the Nix binary as CORRUPTED,
        and -9 & 2 is 2, so it reported untrusted as well. The most likely signal
        produced the most alarming verdict, on a healthy store.
        """
        return self.returncode < 0

    @property
    def signal_number(self) -> int | None:
        return -self.returncode if self.killed_by_signal else None


class System(Protocol):
    """Everything impure the contract needs, in one injectable seam.

    Deliberately narrow. A broad interface is one a fake has to implement in
    full to test a single path.
    """

    def run(self, *args: str | Path, cwd: Path | None = None) -> CommandResult:
        """Execute a command and report what happened."""
        ...

    def is_dir(self, path: Path) -> bool:
        """Whether a directory exists."""
        ...

    def is_file(self, path: Path) -> bool:
        """Whether a regular file exists."""
        ...

    def is_executable_file(self, path: Path) -> bool:
        """Whether a path is a file this process may execute."""
        ...

    def resolve(self, path: Path) -> Path:
        """Follow symlinks to a canonical absolute path."""
        ...

    def write_probe_flake(self, directory: Path) -> None:
        """Write a trivial flake used to test flake evaluation locally."""
        ...

    def is_writable_by_me(self, path: Path) -> bool:
        """Whether the current user can write to a path.

        On the seam because the answer decides whether the store is trustworthy,
        and a contract that cannot be tested against a compromised store is one
        that has never exercised its own most important assumption.
        """
        ...

    def owner_and_mode(self, path: Path) -> tuple[str, int]:
        """The owning user name and permission bits of a path."""
        ...

    def group_members(self, name: str) -> tuple[int, tuple[str, ...]] | None:
        """A group's gid and members, or None when it does not exist."""
        ...

    def user_shell(self, name: str) -> str | None:
        """A user's login shell, or None when the user does not exist.

        The SHELL specifically: a build user with a real shell is an account
        someone could log in as, which is the point of /sbin/nologin.
        """
        ...

    def platform_double(self) -> str:
        """The platform as a Nix system double: cpu-os, e.g. aarch64-darwin.

        ON THE SEAM because the policy needs it: this contract hardcodes macOS
        assumptions -- a nixbld group, store mode 1775, /sbin/nologin -- and no
        rule currently knows which platform it is judging.

        A DOUBLE, NOT platform.machine(). Nix's own format is [cpu]-[os] with
        "built-in support in Nix, such as the builtins.currentSystem impure
        string", and the canonical set is four values. Deriving it from Python's
        platform module would guess at Nix's naming rather than read it.
        """
        ...

    def read_text(self, path: Path) -> str:
        """Read a file's contents.

        On the seam because the contract now VALIDATES the installer receipt
        rather than checking that a file exists there -- and a validation that
        cannot be exercised without a real receipt on disk is one the tests
        cannot cover.
        """
        ...


def clean_env() -> dict[str, str]:
    """A minimal environment, constructed rather than filtered.

    A March 2026 CVE (CWE-15) describes approval "tied to the reviewed binary
    and argv, while the launched process could still inherit attacker-controlled
    env overrides"; its fix blocked PREFIX FAMILIES rather than a narrow list.
    NIX_* is excluded here by never being copied in.
    """
    environment = {"PATH": ":".join(str(directory) for directory in SEARCH_DIRS)}
    for name in PASSTHROUGH_VARIABLES:
        value = os.environ.get(name)
        if value is not None:
            environment[name] = value
    return environment


class RealSystem:
    """The production implementation. Constructed only at the composition root.

    Does NOT inherit from System: structural subtyping means implementing the
    methods is enough, and inheriting would defeat the point of a Protocol.
    """

    def run(self, *args: str | Path, cwd: Path | None = None) -> CommandResult:
        argv = [str(argument) for argument in args]

        # MONOTONIC, not wall clock: a clock correction mid-command would
        # produce a negative duration.
        started = time.monotonic()
        completed = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            check=False,
            cwd=cwd,
            env=clean_env(),
        )
        elapsed_ms = int((time.monotonic() - started) * 1000)

        return CommandResult(
            argv=tuple(argv),
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            duration_ms=elapsed_ms,
        )

    def is_dir(self, path: Path) -> bool:
        return path.is_dir()

    def is_file(self, path: Path) -> bool:
        return path.is_file()

    def is_executable_file(self, path: Path) -> bool:
        return path.is_file() and os.access(path, os.X_OK)

    def resolve(self, path: Path) -> Path:
        return path.resolve()

    def write_probe_flake(self, directory: Path) -> None:
        (directory / "flake.nix").write_text("{ outputs = _: { }; }\n")

    def is_writable_by_me(self, path: Path) -> bool:
        return os.access(path, os.W_OK)

    def group_members(self, name: str) -> tuple[int, tuple[str, ...]] | None:
        try:
            group = grp.getgrnam(name)
        except KeyError:
            return None
        return group.gr_gid, tuple(group.gr_mem)

    def user_shell(self, name: str) -> str | None:
        try:
            return pwd.getpwnam(name).pw_shell
        except KeyError:
            return None

    def owner_and_mode(self, path: Path) -> tuple[str, int]:
        info = path.stat()
        try:
            owner = pwd.getpwuid(info.st_uid).pw_name
        except KeyError:
            # A uid with no passwd entry is itself a finding, and reporting the
            # number is more useful than raising.
            owner = str(info.st_uid)
        return owner, stat.S_IMODE(info.st_mode)

    def platform_double(self) -> str:
        """Read Python's view, normalised to Nix's naming.

        ASKED OF THE PLATFORM MODULE AND TRANSLATED, rather than shelled out to
        nix -- because this must answer on a machine with NO nix, which is the
        case the policy most needs it for.

        The translation is the part worth having: Darwin reports "arm64" where
        Nix says "aarch64", and a Nix issue records the same mismatch in the
        other direction -- "Nix standalone on macOS's system string is
        arm64-apple-darwin and not aarch64-darwin". Guessing either way would
        produce a value no rule could match.
        """
        machine = platform.machine().lower()
        cpu = {"arm64": "aarch64", "amd64": "x86_64"}.get(machine, machine)
        operating_system = platform.system().lower()
        return f"{cpu}-{operating_system}"

    def read_text(self, path: Path) -> str:
        return path.read_text(encoding="utf-8")
