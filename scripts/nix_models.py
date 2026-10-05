"""The observation and the verdict, as types both sides can depend on.

WHY THIS MODULE EXISTS
nix_output needed NixInstallation and ContractReport for its signatures, and
nix_contract needed build_output for its envelope. That is a genuine cycle, and
it was "solved" with a TYPE_CHECKING guard -- which does not remove the cycle,
it hides it from the runtime.

The guidance on that is explicit: "do not move imports into if TYPE_CHECKING
solely to break circular imports... avoid any pattern whose sole purpose is to
hide imports from runtime while exposing them only to the type checker", and
"existing TYPE_CHECKING blocks: do not extend; prefer to remove."

The named fix is this: "when A and B both need the same thing and importing
from each other creates the circle, extract the shared code into a new module C
that neither A nor B imports back. Common extraction targets are constants,
base classes, TYPE DEFINITIONS."

So the models live here, in a leaf. nix_contract and nix_output both import it
and neither imports the other back for types. The graph is acyclic by
construction rather than by a guard someone must remember not to touch, and
runtime and type-checking behaviour no longer diverge.

WHAT IS HERE AND WHAT IS NOT
Types and the constants they validate against. The BEHAVIOUR -- observing a
machine, judging it, printing a report -- stays in nix_contract, because that
is what depends on this and not the reverse.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nix_observability import ProbeRecord
from nix_remediation import ContractProblem
from nix_system import SEARCH_DIRS

__all__ = [
    "BUILD_GROUP",
    "MINIMUM_NIX_VERSION",
    "NIX_INSTALLER",
    "NIX_RECEIPT",
    "NIX_STORE",
    "NOLOGIN_SHELLS",
    "RECEIPT_REQUIRED_KEYS",
    "STORE_VERIFY_NOT_RUN",
    "TRUSTED_ROOTS",
    "ContractReport",
    "NixInstallation",
    "ProbeOutcome",
    "ProblemCode",
    "classify_failure",
]


NIX_STORE = Path("/nix/store")
NIX_RECEIPT = Path("/nix/receipt.json")

# THE UNINSTALLER BINARY, WHICH THE RECEIPT ALONE DOES NOT REPLACE.
# The documented procedure is `/nix/nix-installer uninstall`, and it reads the
# receipt -- so a machine with a receipt and no binary cannot be uninstalled by
# the supported route. Checking only the receipt reported such a machine as
# uninstallable.
NIX_INSTALLER = Path("/nix/nix-installer")

# Observed on a real installation: {"version", "planner", "actions"} with ten
# top-level actions, each {"action", "state"}. A touch-created file has none of
# this, which is the point -- existence is not authenticity.
RECEIPT_REQUIRED_KEYS = frozenset({"version", "planner", "actions"})

# WHAT A PROTECTED STORE LOOKS LIKE, per Nix's own documentation: "/nix/store
# should be owned by the Nix account, its group should be the group specified
# here, and its mode should be 1775".
#
# 0o1775 is rwxrwxr-t: the STICKY BIT is the load-bearing part. Without it any
# member of nixbld could delete another's store paths.
EXPECTED_STORE_MODE = 0o1775
EXPECTED_STORE_OWNER = "root"


# THE PRIVILEGE FOOTPRINT THE INSTALLER CREATED, observed on this machine and
# recorded in the receipt: group nixbld at gid 350, users _nixbld1.._nixbld32 at
# uids 351-382, every one with a nologin shell.
#
# The docstring NARRATED all of this and the contract inspected none of it. A
# build user with a real login shell is an account someone could log in as,
# which is precisely what /sbin/nologin exists to prevent.
# RECOGNISABLE FAILURE CAUSES, matched against what Nix actually said.
#
# The probe previously answered every flake failure with "enable flakes in
# /etc/nix/nix.conf" regardless of cause -- a daemon that was down, a full disk
# and a permissions problem all got the same wrong advice. That is the named
# failure mode of "stalling at the most comfortable explanation rather than the
# accurate one", and it sends an operator to fix something that is not broken.
#
# Each entry is a fragment Nix emits and the remediation that actually applies.
# Anything unmatched is reported as UNKNOWN with the raw error, because no
# advice is better than confident wrong advice.
class ProbeOutcome(StrEnum):
    """WHY a probe ended as it did, not merely whether it succeeded.

    can_evaluate was a bool, which is boolean blindness: "a smell occurring
    whenever a function operating on a boolean value forgets -- or erases -- the
    information about what that boolean was meant to represent". A consumer
    reading false could not tell a disabled feature from a dead daemon from a
    full disk, though the code had already worked out which.

    The classification existed and was flattened into prose. This returns
    "evidence instead of brute fact".

    UNKNOWN_FAILURE is a real member, not a gap. A probe that failed for an
    unrecognised reason must say so rather than be assigned the nearest
    plausible cause -- that is the misattribution this replaced.
    """

    OK = "ok"
    FEATURE_DISABLED = "feature_disabled"
    DAEMON_UNREACHABLE = "daemon_unreachable"
    DISK_FULL = "disk_full"
    PERMISSION_DENIED = "permission_denied"
    READ_ONLY_STORE = "read_only_store"
    UNKNOWN_FAILURE = "unknown_failure"


FLAKE_FAILURE_CAUSES: tuple[tuple[str, ProbeOutcome, str, str], ...] = (
    (
        "experimental",
        ProbeOutcome.FEATURE_DISABLED,
        "flakes are not enabled",
        "Add `experimental-features = nix-command flakes` to /etc/nix/nix.conf.",
    ),
    (
        "connection refused",
        ProbeOutcome.DAEMON_UNREACHABLE,
        "the nix daemon is not reachable",
        "Start it: `sudo launchctl kickstart -k system/systems.determinate.nixd` "
        "on macOS, or `sudo systemctl start nix-daemon` on Linux.",
    ),
    (
        "cannot connect",
        ProbeOutcome.DAEMON_UNREACHABLE,
        "the nix daemon is not reachable",
        "Start the nix daemon; the store socket is not answering.",
    ),
    (
        "no space left",
        ProbeOutcome.DISK_FULL,
        "the disk is full",
        "Free space, then re-run. `nix store gc` reclaims unreferenced paths.",
    ),
    (
        "permission denied",
        ProbeOutcome.PERMISSION_DENIED,
        "a permission problem, not a flake problem",
        "Check ownership of /nix and the daemon socket.",
    ),
    (
        "read-only file system",
        ProbeOutcome.READ_ONLY_STORE,
        "the store is mounted read-only",
        "Remount the Nix Store volume; the installation cannot write.",
    ),
)


def classify_failure(error: str) -> tuple[ProbeOutcome, str, str] | None:
    """Name a cause only when the evidence supports it.

    Returns None for anything unrecognised, and the caller must then say the
    cause is unknown rather than guess. Asserting a cause the code never
    established is how an operator ends up fixing the wrong thing.
    """
    lowered = error.lower()
    for fragment, outcome, cause, remedy in FLAKE_FAILURE_CAUSES:
        if fragment in lowered:
            return outcome, cause, remedy
    return None


BUILD_GROUP = "nixbld"
EXPECTED_BUILD_GROUP_ID = 350
EXPECTED_BUILD_USER_COUNT = 32
NOLOGIN_SHELLS = frozenset({"/sbin/nologin", "/usr/bin/false", "/bin/false", "/usr/sbin/nologin"})

# WHERE A RESOLVED PATH MAY LEGITIMATELY LAND. The store belongs here and not in
# SEARCH_DIRS: you never search it, but every Nix binary resolves into it.
TRUSTED_ROOTS = (*SEARCH_DIRS, NIX_STORE)


MINIMUM_NIX_VERSION = (2, 18)

# A SENTINEL FOR "THE PROBE NEVER RAN", distinct from any exit code it could
# return. Negative values are signal numbers, and -1 is not a signal any process
# receives, so it cannot collide with a real result.
STORE_VERIFY_NOT_RUN = -1

STORE_VERIFY_CORRUPTED = 1
STORE_VERIFY_UNTRUSTED = 2


def _parse_version(version: str) -> tuple[int, ...]:
    """The Nix version, from the LAST version-shaped token.

    Determinate reports TWO: "nix (Determinate Nix 3.22.3) 2.35.2", where
    3.22.3 is the distribution and 2.35.2 is Nix. Taking the first compares
    unrelated numbers against a version floor -- and would PASS, which is worse
    than failing.

    Raises ValueError, which pydantic turns into a ValidationError at
    construction. That is the point: a format Nix changes should fail where the
    observation is built, not later at an arbitrary call site.
    """
    candidates = [
        token
        for token in version.replace("(", " ").replace(")", " ").split()
        if token.replace(".", "").isdigit() and "." in token
    ]
    if not candidates:
        raise ValueError(
            f"no version-shaped token in {version!r}. `nix --version` may have changed format."
        )
    return tuple(int(part) for part in candidates[-1].split("."))


class ProblemCode(StrEnum):
    """Machine-readable codes. A caller branches on these, never on prose."""

    STORE_NOT_MOUNTED = "ERR_NIX_STORE_NOT_MOUNTED"
    VERSION_BELOW_FLOOR = "ERR_NIX_VERSION_BELOW_FLOOR"
    CANNOT_EVALUATE = "ERR_NIX_CANNOT_EVALUATE"
    CANNOT_EVALUATE_FLAKE = "ERR_NIX_CANNOT_EVALUATE_FLAKE"
    STORE_PATH_CORRUPTED = "ERR_NIX_STORE_PATH_CORRUPTED"
    STORE_VERIFY_DID_NOT_RUN = "WARN_NIX_STORE_VERIFY_KILLED"
    NO_UNINSTALL_RECEIPT = "ERR_NIX_NO_RECEIPT"
    STORE_WRITABLE = "ERR_NIX_STORE_WRITABLE"
    BUILD_USER_LOGIN_SHELL = "ERR_NIX_BUILD_USER_LOGIN_SHELL"
    BUILD_GROUP_MISSING = "WARN_NIX_BUILD_GROUP_MISSING"
    STORE_PATH_UNTRUSTED = "WARN_NIX_STORE_PATH_UNTRUSTED"
    STORE_PERMISSIONS_UNEXPECTED = "WARN_NIX_STORE_PERMISSIONS"


class ContractReport(BaseModel):
    """Whether the installation satisfies the contract, and why not."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    problems: tuple[ContractProblem, ...] = ()
    verdicts: dict[str, str] = Field(
        default_factory=dict,
        description="pass or fail for EVERY declared rule, not only those that fired",
    )
    warnings: tuple[ContractProblem, ...] = ()
    """Risk factors that do not fail the contract.

    THE DISTINCTION IS THE 2026 STANDARD, NOT A SOFTENING.
    Supply-chain guidance draws it explicitly: "treat the ABSENCE of provenance
    as a risk factor, not an automatic failure", while "a provenance MISMATCH...
    treat as a security incident".

    A store path with no trusted signature is the first: normal for anything
    substituted from a binary cache, and refusing it would fail every machine
    that did not build its own toolchain. A path whose contents do not match its
    recorded NAR hash is the second, and that is a problem, not a warning.

    Recording a risk factor in a field nobody reads is the gap this closes.
    """

    @model_validator(mode="after")
    def findings_and_verdicts_must_agree(self) -> ContractReport:
        """THE INVARIANT LIVES HERE, NOT IN A TEST.

        A test checks the relationship where it happens to look; a validator
        checks it everywhere a report is constructed -- including in replay, in
        the fake-driven tests, and in any future caller.

        By the time an after-validator runs "every field has been validated and
        is reachable through self, regardless of declaration order", which is
        what makes a cross-field rule expressible at all.

        RAISES RATHER THAN ASSERTS. Pydantic's own documentation warns that
        assert statements "are skipped when Python is run with the -O
        optimization flag" -- an invariant that disappears under a flag is not
        an invariant.
        """
        if not self.verdicts:
            # Permitted: a report built directly in a test, or before verdicts
            # were introduced. Nothing to cross-check.
            return self

        allowed = {"pass", "fail"}
        unexpected = {value for value in self.verdicts.values()} - allowed
        if unexpected:
            raise ValueError(f"verdicts must be pass or fail, found {sorted(unexpected)}")

        fired = {finding.code for finding in (*self.problems, *self.warnings)}

        missing = fired - set(self.verdicts)
        if missing:
            raise ValueError(
                f"findings report codes absent from verdicts: {sorted(missing)}. "
                "A rule that fired must be enumerable."
            )

        disagreeing = {code for code in fired if self.verdicts[code] != "fail"}
        if disagreeing:
            raise ValueError(f"codes fired but their verdict is not 'fail': {sorted(disagreeing)}")

        wrongly_failed = {
            code
            for code, verdict in self.verdicts.items()
            if verdict == "fail" and code not in fired
        }
        if wrongly_failed:
            raise ValueError(
                f"verdicts say 'fail' for codes that produced no finding: {sorted(wrongly_failed)}"
            )

        return self

    @property
    def satisfied(self) -> bool:
        """Warnings deliberately do not affect this.

        A gate that fails on every substituted binary is one people disable,
        and a disabled gate detects nothing at all.
        """
        return not self.problems

    @property
    def codes(self) -> tuple[ProblemCode, ...]:
        """For a caller deciding what to remediate, without reading messages."""
        # ContractProblem.code is typed str, because ContractProblem lives in
        # nix_remediation and importing ProblemCode there would recreate the
        # cycle. Converting here keeps the ENUM at the boundary callers use --
        # they branch on codes, and a bare str would put them back to string
        # comparison, which is the fragility the codes replaced.
        return tuple(ProblemCode(problem.code) for problem in self.problems)


class NixInstallation(BaseModel):
    """The Nix installation as it actually exists on this machine."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    nix_present: bool = Field(
        default=True,
        description="Whether a nix binary was found in any searched directory",
    )
    """ABSENCE IS AN OBSERVATION, NOT A FAILURE TO OBSERVE.

    observe() used to RAISE when nix was not found, which treats a known answer
    as an inability to know. Searching four directories and finding nothing is a
    SUCCESSFUL search with a negative result -- the same way querying an account
    and finding zero resources is a fact rather than an error.

    The distinction is the one compliance engines draw: a COLLECTOR error aborts
    because "partial data would produce misleading findings", while a collected
    fact feeds evaluation. Nix being absent is the second kind.

    Making it a field moves the decision into the POLICY, where it appears in
    the verdicts like every other rule, instead of a special-case branch in
    run() that no rule covered and no verdict reported.
    """
    searched: tuple[Path, ...] = Field(
        default=(),
        description="Where nix was looked for, so an absence names its own scope",
    )
    system: str = Field(
        default="",
        description="Nix system double: cpu-os, e.g. aarch64-darwin",
    )
    """WHICH MACHINE THIS IS, in the naming Nix itself uses.

    The contract hardcodes macOS assumptions -- a nixbld group, store mode 1775,
    /sbin/nologin -- and no rule knew which platform it was judging. A rule that
    is right on Darwin and wrong on Linux cannot be written without this.

    A DOUBLE rather than a hostname. The hostname on this machine contains a
    person's name, and the repository runs a PII scanner to keep exactly that
    out of committed artifacts; the platform identifies the KIND of machine
    without identifying whose it is.
    """
    binary: Path | None = Field(
        default=None,
        description="Absolute path nix resolved to, or None when absent",
    )
    version: str = ""
    semantic_version: tuple[int, ...] = Field(
        default=(),
        description="Parsed at construction from `version`, never on access",
    )
    """The default is never the value that survives.

    A DEFAULT ONLY BECAUSE MYPY CANNOT SEE THE VALIDATOR. The parse happens in
    model_validator(mode="before"), which always supplies this field -- but a
    validator's guarantees "are not exposed to the type checker", so a required
    field here makes mypy reject every construction that relies on the parse.

    The empty tuple is unreachable in practice: the validator either supplies a
    parsed version or raises. It is asserted unreachable in the tests rather
    than left as a claim.
    """
    store_exists: bool
    store_writable_by_me: bool = Field(
        default=False,
        description="Whether the current user can write to /nix/store",
    )
    store_owner: str = Field(default="", description="Owning user of /nix/store")
    build_group_id: int | None = Field(
        default=None, description="gid of the nixbld group, or None if absent"
    )
    build_user_count: int = Field(default=0, description="Members of the build group")
    build_users_with_login_shells: tuple[str, ...] = Field(
        default=(),
        description="Build users whose shell is not a nologin shell",
    )
    store_mode: int = Field(default=0, description="Permission bits of /nix/store, sticky included")
    receipt_exists: bool
    receipt_is_valid: bool = Field(
        default=False,
        description="Parses as JSON and has the installer's structure",
    )
    uninstaller_exists: bool = Field(
        default=False,
        description="/nix/nix-installer, without which the receipt cannot be used",
    )
    evaluate_outcome: ProbeOutcome = Field(
        default=ProbeOutcome.OK,
        description="WHY the eval probe ended as it did, not merely whether it passed",
    )
    flake_outcome: ProbeOutcome = Field(
        default=ProbeOutcome.OK,
        description="WHY the flake probe ended as it did",
    )
    project_flake_checked: bool = Field(
        default=False,
        description="Whether this repository's own flake was evaluated at all",
    )
    """A PROBE THAT COULD NOT RUN IS NOT A PROBE THAT PASSED.

    This project has no flake.nix yet, so the check does not run -- and
    reporting that as OK would be the vacuous truth this contract keeps
    removing. The flag separates "no flake to check" from "checked and fine".
    """
    project_flake_outcome: ProbeOutcome = Field(
        default=ProbeOutcome.OK,
        description="WHY evaluating THIS repository's flake ended as it did",
    )
    project_flake_error: str = Field(
        default="",
        description="What nix said about this repository's flake",
    )
    probes: tuple[ProbeRecord, ...] = Field(
        default=(),
        description="Every command run to produce this observation",
    )
    store_verify_status: int = Field(
        description="`nix store verify` exit code, SUMMED: 1 corrupted, 2 untrusted, 4 error"
    )
    evaluate_error: str = Field(
        default="",
        description="What `nix eval` actually said when it failed",
    )
    flake_error: str = Field(
        default="",
        description="What `nix flake metadata` actually said when it failed",
    )

    @model_validator(mode="before")
    @classmethod
    def parse_the_version_at_construction(cls, data: object) -> object:
        """PARSE, DO NOT VALIDATE.

        semantic_version was a lazy @property. A version string Nix changed the
        format of would CONSTRUCT fine and then raise ValueError from whatever
        touched it first -- including inside verify(), which has no handler.
        That is how a format change becomes an incident rather than a
        validation failure.

        Pydantic is explicit that validation is a non-goal of computed fields,
        so a property is not a validation site. Parsing here means a constructed
        NixInstallation GUARANTEES a usable version, and no caller downstream
        has to consider the parse failing.
        """
        if not isinstance(data, dict):
            return data
        if "semantic_version" in data:
            return data

        version = data.get("version", "")
        if not isinstance(version, str) or not version.strip():
            # AN EMPTY VERSION IS ITSELF AN OBSERVATION, in two distinct cases:
            # nix is absent, or a binary is present and will not report one. The
            # first version of this guard allowed only the first case and then
            # rejected the second -- which is how the version-failure path,
            # written in the same change, failed validation.
            #
            # Both are facts the policy judges. Raising here would put the old
            # exception back under a narrower condition.
            return {**data, "version": "", "semantic_version": ()}

        return {**data, "version": version.strip(), "semantic_version": _parse_version(version)}

    @field_validator("binary")
    @classmethod
    def binary_must_land_in_a_trusted_root(cls, value: Path | None) -> Path | None:
        # None is the ABSENT case, which the policy judges. The trusted-root rule
        # still applies to any path that IS present -- absence must not become a
        # way to bypass the check.
        if value is None:
            return None
        if not value.is_absolute():
            raise ValueError(f"binary path is not absolute: {value}")
        if not any(value.is_relative_to(root) for root in TRUSTED_ROOTS):
            roots = ", ".join(str(root) for root in TRUSTED_ROOTS)
            raise ValueError(f"binary resolved outside every trusted root ({roots}): {value}")
        return value

    @property
    def is_determinate(self) -> bool:
        """Recorded, not required: flake.nix and flake.lock are standard either way."""
        return "Determinate" in self.version

    @property
    def is_from_the_store(self) -> bool:
        """False when nix is absent, which is honest rather than convenient.

        An absent binary did not come from the store; it came from nowhere.
        Reporting True would claim provenance for something that does not exist.
        """
        if self.binary is None:
            return False
        return self.binary.is_relative_to(NIX_STORE)

    @property
    def can_evaluate(self) -> bool:
        """DERIVED from the outcome, not stored beside it.

        Keeping both a bool and an enum would allow them to disagree -- the
        classic four-combinations-two-valid problem. The enum is the fact; this
        is a convenience over it.
        """
        return self.evaluate_outcome is ProbeOutcome.OK

    @property
    def can_evaluate_a_flake(self) -> bool:
        return self.flake_outcome is ProbeOutcome.OK

    @property
    def meets_version_floor(self) -> bool:
        """Compare against MINIMUM_NIX_VERSION with PEP 440 padding.

        A BARE TUPLE COMPARISON IS WRONG WHEN LENGTHS DIFFER. Python's rule is
        prefix-based, so (2, 18) < (2, 18, 0) is TRUE -- meaning a machine
        reporting "2.18" would be declared below a floor of 2.18.0, which is the
        same version.

        It worked only by coincidence: three-component observations against a
        two-component floor. Writing the floor as (2, 18, 0) would have broken
        it silently.

        PEP 440 states the rule: "all release segments involved in the
        comparison MUST be converted to a consistent length by padding shorter
        segments with zeros as needed". Padding is that rule, and it is three
        lines -- packaging.version.Version would add a dependency to handle
        pre-release tags Nix versions do not use.
        """
        width = max(len(self.semantic_version), len(MINIMUM_NIX_VERSION))
        observed = tuple(self.semantic_version) + (0,) * (width - len(self.semantic_version))
        floor = tuple(MINIMUM_NIX_VERSION) + (0,) * (width - len(MINIMUM_NIX_VERSION))
        return observed >= floor

    @property
    def store_verify_signal(self) -> int | None:
        """The signal that killed the verify probe, or None if it exited normally.

        Derived HERE rather than in verify(), because the policy-input test
        caught the alternative: computing -store_verify_status inside verify()
        meant policy was reading a field declared informational. The test was
        right -- the raw status is a recorded fact, and what policy needs is the
        interpretation.
        """
        return -self.store_verify_status if self.store_verify_status < 0 else None

    @property
    def store_verify_ran(self) -> bool:
        """Whether the verify probe produced an exit code at all.

        A NEGATIVE status is a SIGNAL NUMBER, not a bitfield. Reading it as one
        gave arbitrary verdicts: -9 (SIGKILL) reported the binary as BOTH
        corrupted and untrusted; -15 reported corrupted; -6 reported untrusted.
        The likeliest signal produced the most alarming answer, on a healthy
        store.
        """
        return self.store_verify_status >= 0

    @property
    def is_corrupted(self) -> bool:
        """Bitwise, because the exit code is a SUM -- but only when it IS one.

        A path both corrupted and untrusted returns 3, and an equality test
        against 1 would miss it. A killed probe returns nothing meaningful, and
        the honest answer there is "not known to be corrupted" rather than a
        verdict derived from a signal number.
        """
        if not self.store_verify_ran:
            return False
        return bool(self.store_verify_status & STORE_VERIFY_CORRUPTED)

    @property
    def is_uninstallable(self) -> bool:
        """BOTH artefacts, not just the receipt.

        `touch /nix/receipt.json` satisfied the old check and reported
        uninstallable: true on a machine with no uninstaller at all -- existence
        standing in for authenticity.
        """
        return self.receipt_is_valid and self.uninstaller_exists

    @property
    def is_untrusted(self) -> bool:
        if not self.store_verify_ran:
            return False
        return bool(self.store_verify_status & STORE_VERIFY_UNTRUSTED)


class NixPolicyInput(BaseModel):
    """The observation, as the document policies/machine/nix judges.

    IT WAS A DICT ASSEMBLED BY HAND at the one place the Python model meets the
    Rego rules. These are the 29 values the policy reads, and nothing else is
    accepted: a misspelt key would otherwise reach the policy as an absence.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    nix_present: bool
    flake_present: bool
    searched: tuple[str, ...]
    system: str
    store_path: str
    store_exists: bool
    store_writable_by_me: bool
    store_owner: str
    store_mode: int
    binary: str
    semantic_version: str
    minimum_version: str
    meets_version_floor: bool
    evaluate_outcome: str
    evaluate_error: str
    flake_outcome: str
    flake_error: str
    project_flake_checked: bool
    project_flake_outcome: str
    project_flake_error: str
    is_corrupted: bool
    is_untrusted: bool
    store_verify_ran: bool
    store_verify_signal: int | None
    is_uninstallable: bool
    receipt_is_valid: bool
    uninstaller_exists: bool
    build_group_id: int | None
    build_users_with_login_shells: tuple[str, ...]
