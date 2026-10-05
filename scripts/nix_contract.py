"""Validate that this machine's Nix installation matches what the project needs.

WHY THIS EXISTS
Nix was installed with `curl -fsSL https://install.determinate.systems/nix | sh`
-- a throw-away command that permanently changed the machine: an encrypted APFS
volume at /nix, a launchd daemon, build users 351-382, group 350, and edits to
/etc/zshrc, /etc/bashrc and /etc/fstab. Every other operation here is a captured
task with a contract and a policy. That one was not.

THE IMPURE BOUNDARY IS INJECTED
observe() called subprocess.run and Path.is_dir directly, which made it
untestable without a real Nix installation -- so the tests constructed
NixInstallation by hand, covering verify() and leaving the COLLECTION untested.
It now takes a System, and main() is the only place a real one is built. The
standard: "outside a composition root, a package must not call an impure stdlib
entry point -- the clock, the network, a subprocess -- directly."

PROBLEMS CARRY CODES, NOT PROSE
They were tuple[str, ...], forcing callers to STRING-MATCH to tell "no receipt"
from "version too low". Each is now a typed record with an enum code, a message
and a remediation.

VALUES IN THE CORE, EXCEPTIONS AT THE BOUNDARY
An earlier version raised SystemExit from verify() and observe(), so a caller
could not distinguish "the contract is unsatisfied" from "this process must
die", nor remediate what it cannot catch.

IT TESTS CAPABILITY, NOT CONFIGURATION
A first version asserted `experimental-features` contained nix-command and
flakes. On this machine that setting is EMPTY and flakes work anyway, because
Determinate Nix 3.x ships them as STABLE. A second used `nix flake --help`,
which proves the subcommand exists, not that flakes work.

The eval probe carries NO --impure. That flag was added defensively and never
tested against; Nix documents pure evaluation as restricting filesystem and
network access and disabling currentSystem/currentTime, none of which
arithmetic touches. Dropping it makes the probe STRONGER: it proves evaluation
works in the strictest mode rather than the loosest.

SEARCH DIRECTORIES AND TRUSTED ROOTS ARE DIFFERENT THINGS
`nix` is FOUND in the profile directory and resolves into /nix/store/<hash>/...
Requiring the resolved path to be inside a SEARCH directory refused Nix itself,
because a profile is entirely symlinks into the store by design.

WHAT TRUSTING THE STORE MEANS, STATED ACCURATELY
Nix documents three ALTERNATIVES for a path being trusted -- signed by a trusted
key, content-addressed, or built locally -- and most nixpkgs paths are
input-addressed and trusted by SIGNATURE. `nix store verify` reports with SUMMED
exit codes (1 corrupted, 2 untrusted, 4 unverifiable). Its limit: verifying nix
USING nix is circular against a substituted binary. It detects corruption, not
replacement.
"""

from __future__ import annotations

import sys
import tempfile
from enum import StrEnum
from pathlib import Path
from typing import TextIO

from pydantic import JsonValue, TypeAdapter

from nix_evidence import RecordingSystem, bundle_digest, save_bundle
from nix_ledger import append
from nix_models import (
    BUILD_GROUP,
    MINIMUM_NIX_VERSION,
    NIX_INSTALLER,
    NIX_RECEIPT,
    NIX_STORE,
    NOLOGIN_SHELLS,
    RECEIPT_REQUIRED_KEYS,
    STORE_VERIFY_NOT_RUN,
    TRUSTED_ROOTS,
    ContractReport,
    NixInstallation,
    NixPolicyInput,
    ProbeOutcome,
    ProblemCode,
    classify_failure,
)
from nix_observability import ProbeRecord, RunMetadata, Timer
from nix_output import build_output
from nix_policy import evaluate, policy_revision, verdicts
from nix_remediation import ActionableError, ContractProblem
from nix_request import ContractRequest
from nix_system import SEARCH_DIRS, CommandResult, RealSystem, System

__all__ = [
    "EXIT_CODES",
    "INFORMATIONAL_ONLY",
    "MINIMUM_NIX_VERSION",
    "NIX_RECEIPT",
    "NIX_STORE",
    "OUTPUT_SCHEMA_VERSION",
    "POLICY_INPUTS",
    "TRUSTED_ROOTS",
    "ContractProblem",
    "ContractReport",
    "NixContractError",
    "NixInstallation",
    "Outcome",
    "ProblemCode",
    "UntrustedBinaryError",
    "flake_probe",
    "observe",
    "resolve_binary",
    "run",
    "verify",
]

ROOT = Path(__file__).resolve().parent.parent

# THE RECEIPT IS JSON NOBODY HERE WROTE: read as a JSON object, then judged.
_OBJECT = TypeAdapter(dict[str, JsonValue])

# THE OUTPUT CONTRACT'S VERSION, AND IT IS LOCKED BY A TEST.
#
# A consumer parsing this document has no other way to detect that the shape
# changed. The convention is consistent across 2026 CLIs: a schema_version field
# "so external tooling can pin a format and detect breaking changes".
#
# The field alone would be decoration. tests/test_nix_output_contract.py asserts
# the exact top-level key set, so ADDING OR REMOVING A KEY FAILS THE SUITE until
# this constant is bumped -- which is the point: "forcing the bump to be
# intentional".
#
# Semver-ish: additive keys are a minor bump, renames and removals a major one.
# 2.0 AND NOT 1.7: `evaluable` was RENAMED to `nix_present`, and two Outcome
# values were removed. Both break a consumer that pinned to 1.x -- the rule
# stated here is that "additive keys are a minor bump, renames and removals a
# major one", and this is both.
OUTPUT_SCHEMA_VERSION = "2.3"

# THE RULES' VERSION, DISTINCT FROM THE ENVELOPE'S AND DERIVED FROM THE RULES.
#
# schema_version answers "has the shape changed"; this answers "have the
# JUDGEMENTS changed". Raising MINIMUM_NIX_VERSION or reclassifying a problem
# alters verdicts without touching a single key, and a consumer comparing two
# reports needs to tell "the machine changed" from "we changed our mind".
#
# IT WAS A HAND-MAINTAINED CONSTANT HERE, describing rules written in Rego in
# another file -- so bumping it was a matter of remembering. It is now a hash of
# the rule files themselves, computed by nix_policy.policy_revision(), and
# cannot drift from what it versions because it IS what it versions.

# WHICH OBSERVATIONS POLICY MAY READ.
#
# NixInstallation holds two kinds of field and nothing distinguished them:
# facts that DECIDE the verdict, and facts merely RECORDED. is_determinate is
# the dangerous case -- it notes that this machine runs a vendor fork, and a
# later reader could easily start enforcing it, quietly making the fork
# mandatory.
#
# A comment saying "informational" would be exactly the kind of aspirational
# document that "lived in wikis and slide decks" and was never enforced.
# tests/test_nix_policy_inputs.py parses verify() and asserts it touches ONLY
# these, so widening policy requires widening this set deliberately.
POLICY_INPUTS = frozenset(
    {
        "store_exists",
        "store_writable_by_me",
        "store_owner",
        "store_mode",
        "semantic_version",
        "meets_version_floor",
        "can_evaluate",
        "can_evaluate_a_flake",
        "evaluate_outcome",
        "flake_outcome",
        "evaluate_error",
        "flake_error",
        "project_flake_checked",
        "project_flake_outcome",
        "project_flake_error",
        "is_corrupted",
        "is_untrusted",
        "store_verify_ran",
        "store_verify_signal",
        "is_uninstallable",
        "receipt_is_valid",
        "uninstaller_exists",
        "build_group_id",
        "build_users_with_login_shells",
        "binary",
    }
)

# RECORDED, NEVER ENFORCED. Kept as an explicit list so the distinction is a
# declaration rather than an absence.
INFORMATIONAL_ONLY = frozenset(
    {
        "is_determinate",
        "is_from_the_store",
        "version",
        "probes",
        "build_user_count",
        "receipt_exists",
        "system",
        "store_verify_status",
    }
)


class Outcome(StrEnum):
    """What happened, named rather than inferred.

    The distinction existed only implicitly: a consumer had to derive "the tool
    crashed" from evaluable=false and "the contract failed" from
    satisfied=false, which is two booleans encoding one thing.

    The problem is documented elsewhere in exactly these terms: a wrapper "cannot
    distinguish 'the analysis ran and found a regression' from 'the file was
    unreadable', which forces log-parsing heuristics downstream".

    EXIT CODES MIRROR THIS, following the grep convention (0 hit, 1 miss,
    2 error) and matching what comparable tools ship -- "1 = violations found,
    2 = tool error":

        SATISFIED      0   observed, and every rule passed
        POLICY_DENIED  1   observed, and a rule failed

    An absent Nix is neither: it is a FINDING, judged by the policy like any
    other, so it lands in one of these two according to whether the repository
    needs a Nix at all.
    """

    SATISFIED = "satisfied"
    POLICY_DENIED = "policy_denied"


EXIT_CODES = {
    Outcome.SATISFIED: 0,
    Outcome.POLICY_DENIED: 1,
}
"""TWO OUTCOMES, BECAUSE TWO ARE REACHABLE.

OBSERVE_ERROR and SKIPPED were both produced by the branch that raised on an
absent Nix. Observation now always succeeds and absence is a policy finding, so
nothing emits either -- and a declared state nothing can reach is the same
"declared but impossible" shape this contract keeps removing.

The grep convention still holds for what remains: 0 when every rule passed, 1
when one did not. Exit 2 was "the tool could not run", and the tool always runs.
"""


class NixContractError(ActionableError):
    """Base for everything this module raises.

    A CONSUMER SHOULD BE ABLE TO CATCH ONE TYPE. Without a base, an orchestrator
    wanting "anything this module can raise" must enumerate subclasses and will
    miss the next one added -- the same stale-list failure this repository has
    hit with entrypoints and first-party module names.

    Exception, not BaseException: that tier is for SystemExit and
    KeyboardInterrupt, and inheriting from it would let this bypass the broad
    `except Exception` handlers callers use for cleanup.
    """


class UntrustedBinaryError(NixContractError):
    """A required binary was not found, or was found somewhere untrustworthy.

    AN EXCEPTION RATHER THAN A PROBLEM CODE: this is not the contract being
    unsatisfied, it is the contract being UNEVALUABLE. There is no installation
    to describe.

    THE DETAIL IS IN ATTRIBUTES, NOT ONLY IN THE MESSAGE. An orchestrator
    deciding whether to remediate needs to know WHICH binary and WHERE it was
    looked for; a formatted string carries that "in an inaccessible form".
    """

    code = "ERR_NIX_BINARY_UNTRUSTED"

    def __init__(self, message: str, *, name: str, searched: tuple[Path, ...] = ()) -> None:
        super().__init__(
            message,
            remediation="Install Nix with the captured bootstrap: `mise run nix:bootstrap`. "
            "If it is installed elsewhere, it is outside every trusted directory "
            "and will not be used.",
            binary=name,
            searched=[str(path) for path in searched],
        )
        self.name = name
        self.searched = searched


def resolve_binary(system: System, name: str, *, search: tuple[Path, ...] = SEARCH_DIRS) -> Path:
    """Find a binary by searching trusted directories, and resolve it.

    `search` IS A PARAMETER SO THE ABSENT-NIX PATH CAN BE TESTED END TO END.
    Two attempts to contrive that with the environment failed -- PATH does not
    reach this function by design, and a copied tree lost its tool versions. A
    parameter turns "cannot test" into "pass a different tuple", which is the
    same fix that made observe() testable.

    The default is the real list, so no caller changes and the hardening is
    unaffected: nothing outside SEARCH_DIRS is searched unless a test says so.
    """
    for directory in search:
        candidate = directory / name
        if system.is_executable_file(candidate):
            resolved = system.resolve(candidate)
            if not resolved.is_absolute():
                raise UntrustedBinaryError(
                    f"{name} resolved to a relative path: {resolved}",
                    name=name,
                    searched=SEARCH_DIRS,
                )
            return resolved

    searched = ", ".join(str(directory) for directory in search)
    raise UntrustedBinaryError(
        f"{name} not found in any searched directory ({searched})",
        name=name,
        searched=search,
    )


# Generous, but bounded. A 500-character cap is a documented complaint --
# "losing critical debugging information" -- and Nix errors carry a trace whose
# useful part is often not in the first line. Unbounded is also wrong: a runaway
# error would land whole in a JSON document something else has to parse.
MAX_DIAGNOSTIC_CHARACTERS = 4000


def _diagnostic(result: CommandResult) -> str:
    """What the command said, when it failed. Empty when it succeeded.

    NO REDACTION IS APPLIED, AND THAT IS A DELIBERATE, NARROW CALL.
    Secrets on stderr are a real hazard in general -- URL-embedded credentials
    in git errors, tokens in verbose output. Here the environment is CONSTRUCTED
    rather than inherited: NIX_*, tokens and every unrelated variable are absent
    by construction, so there is nothing passed in for Nix to echo back.

    If this ever runs a command that receives a credential, the redaction must
    come first.
    """
    if result.succeeded:
        return ""

    text = (result.stderr or result.stdout).strip()
    if len(text) <= MAX_DIAGNOSTIC_CHARACTERS:
        return text
    return text[:MAX_DIAGNOSTIC_CHARACTERS] + f"\n[truncated at {MAX_DIAGNOSTIC_CHARACTERS} chars]"


def outcome_of(result: CommandResult) -> ProbeOutcome:
    """Classify a probe result into a typed outcome.

    Success is OK. A recognised failure gets its cause. An unrecognised one gets
    UNKNOWN_FAILURE rather than the nearest plausible guess.
    """
    if result.succeeded:
        return ProbeOutcome.OK

    classified = classify_failure(_diagnostic(result))
    return classified[0] if classified else ProbeOutcome.UNKNOWN_FAILURE


def receipt_is_valid(system: System) -> bool:
    """Whether the receipt is a receipt, not merely a file at that path.

    `touch /nix/receipt.json` passed the previous existence check. This parses
    it and requires the installer's own structure -- observed on a real
    installation as {"version", "planner", "actions"}.

    IT DOES NOT VERIFY AUTHENTICITY, and cannot. The receipt records what the
    installer did on THIS machine: the volume, the UIDs it allocated, the
    daemon it created. Every machine's differs, so there is no known-good hash
    or signature to compare against. A determined forgery would pass; a stray
    file, an interrupted write, or a hand-created placeholder will not.

    Distinguishing "structurally a receipt" from "provably the installer's" is
    the honest limit, and it is stated rather than implied by a green field.
    """
    if not system.is_file(NIX_RECEIPT):
        return False

    try:
        parsed = _OBJECT.validate_json(system.read_text(NIX_RECEIPT))
    except (ValueError, OSError):
        return False

    if not RECEIPT_REQUIRED_KEYS.issubset(parsed):
        return False

    actions = parsed.get("actions")
    return isinstance(actions, list) and bool(actions)


def flake_probe(system: System, nix: Path) -> CommandResult:
    """Evaluate a real flake, locally, with no network.

    RETURNS THE RESULT, NOT A BOOLEAN. The previous version returned success or
    failure and discarded what Nix said about it, which is how an operator ends
    up with "a trivial flake could not be evaluated" and no idea why.

    A trivial flake with no inputs is enough: parsing and evaluating it
    exercises the machinery the project depends on, which `--help` does not.
    """
    with tempfile.TemporaryDirectory() as directory:
        probe = Path(directory)
        system.write_probe_flake(probe)
        # NETWORK DENIED EXPLICITLY, PURITY REQUESTED EXPLICITLY.
        #
        # The probe flake has no inputs, so nothing should be fetched -- and
        # allowed-uris is the restriction Nix's maintainers say "cannot be
        # easily enforced via sandboxing", which makes it the one worth stating
        # rather than assuming.
        #
        # NOT seccomp, and not a sandbox wrapper. Nix's build sandbox is OFF by
        # default on macOS -- observed in this machine's own config -- so a
        # claim of sandboxed evaluation would be false here. The honest
        # hardening is the restrictions that actually bind EVALUATION.
        return system.run(
            nix,
            "flake",
            "metadata",
            "--no-write-lock-file",
            "--option",
            "allowed-uris",
            "",
            "--option",
            "pure-eval",
            "true",
            # Observe, do not recall -- and cached FAILURES are the worse half:
            # a flake probe that failed once would keep reporting a problem that
            # no longer exists.
            "--option",
            "eval-cache",
            "false",
            probe,
        )


def project_flake_probe(system: System, nix: Path, root: Path) -> CommandResult | None:
    """Evaluate THIS REPOSITORY's flake, not a synthetic one.

    THE SYNTHETIC PROBE PROVES THE MACHINERY, NOT THE PROJECT. It writes a
    trivial flake to a temp directory and evaluates it, which answers "can this
    Nix evaluate flakes at all". The contract passed with a broken flake.nix
    sitting in the repository root, because nothing ever looked at it.

    NOT `nix flake check`, WHICH BUILDS. That command "verifies that the flake
    can be evaluated successfully AND that the derivations specified by the
    flake's checks output can be built successfully" -- minutes of work and a
    filled store, for a probe that runs on every gate.

    `metadata` evaluates and resolves inputs without building, and
    --no-update-lock-file means "do not allow any updates to the flake's lock
    file" -- so an incomplete lock FAILS here rather than being silently
    repaired, which is the drift a health check should catch.

    NETWORK IS NOT DENIED HERE, unlike the synthetic probe.
    That one sets allowed-uris to "" because it has no inputs, so any fetch
    would be a bug. A real project flake has real inputs, and resolving a
    LOCKED input is legitimate work. Denying it would fail the probe for a
    reason that has nothing to do with the flake being broken.

    Returns None when there is no flake, which is not a failure: this project
    does not have one yet, and a probe that cannot run is different from one
    that ran and failed.
    """
    if not system.is_file(root / "flake.nix"):
        return None

    return system.run(
        nix,
        "flake",
        "metadata",
        "--no-update-lock-file",
        "--no-write-lock-file",
        "--option",
        "eval-cache",
        "false",
        root,
    )


def observe(
    system: System, *, search: tuple[Path, ...] = SEARCH_DIRS, root: Path | None = None
) -> NixInstallation:
    """Read the installation through the injected boundary.

    `search` is threaded through so a test can exercise the absent-Nix path
    against the REAL subprocess, not only against a fake.
    """
    try:
        nix = resolve_binary(system, "nix", search=search)
    except UntrustedBinaryError:
        # ABSENCE IS A RESULT, NOT AN EXCEPTION. Everything knowable about a
        # machine without Nix is knowable: it has none, and here is where we
        # looked. Raising forced a special-case branch in run() that no policy
        # rule covered and no verdict reported.
        return NixInstallation(
            nix_present=False,
            searched=search,
            system=system.platform_double(),
            store_exists=system.is_dir(NIX_STORE),
            receipt_exists=system.is_file(NIX_RECEIPT),
            store_verify_status=STORE_VERIFY_NOT_RUN,
        )

    version = system.run(nix, "--version")
    if not version.succeeded:
        # A BINARY THAT WILL NOT REPORT ITS VERSION IS A DIFFERENT FACT from an
        # absent one, and both are observations. This one is worse: something is
        # there and it does not work.
        return NixInstallation(
            nix_present=True,
            searched=search,
            system=system.platform_double(),
            binary=nix,
            version="",
            store_exists=system.is_dir(NIX_STORE),
            receipt_exists=system.is_file(NIX_RECEIPT),
            store_verify_status=STORE_VERIFY_NOT_RUN,
            evaluate_outcome=ProbeOutcome.UNKNOWN_FAILURE,
            evaluate_error=_diagnostic(version),
            probes=(ProbeRecord.of("version", version),),
        )

    # PURITY IS REQUESTED, NOT INHERITED.
    #
    # Nix's own defaults are pure-eval=false and restrict-eval=false; this
    # machine's Determinate build sets pure-eval=true. So the same probe tested
    # a STRONGER property here than it would upstream -- a health check whose
    # meaning depends on the host running it.
    #
    # Asking explicitly makes it mean one thing everywhere. Same mistake as the
    # earlier --impure, inverted: there the contract taught the runtime that
    # impurity was acceptable; here it accepted whatever purity the runtime
    # happened to offer.
    evaluation = system.run(
        nix,
        "eval",
        "--option",
        "pure-eval",
        "true",
        # A HEALTH CHECK MUST OBSERVE, NOT RECALL.
        #
        # Nix caches evaluation, and it caches FAILURES too -- a documented
        # issue reads "error: cached failure of attribute" persisting after the
        # cause is fixed, with no indication why. In both directions that is
        # disqualifying for a probe whose whole job is to report current state:
        # a stale success hides a broken installation, a stale failure invents
        # one.
        "--option",
        "eval-cache",
        "false",
        "--expr",
        "1 + 1",
    )
    flake = flake_probe(system, nix)

    # THIS REPOSITORY'S FLAKE, not a synthetic one. The contract passed with a
    # broken flake.nix in the root because nothing ever evaluated it.
    project_flake = project_flake_probe(system, nix, root) if root is not None else None

    store_verify = system.run(nix, "store", "verify", nix)
    store_owner, store_mode = system.owner_and_mode(NIX_STORE)

    # THE FOOTPRINT THE DOCSTRING NARRATED, NOW INSPECTED.
    #
    # The receipt DECLARES these were created; this checks they exist and are
    # still what they should be. A build user whose shell became a real login
    # shell is an account someone can log in as -- and nothing in a receipt
    # would ever tell you, because the receipt records what was done, not what
    # is true now.
    group = system.group_members(BUILD_GROUP)
    build_group_id = group[0] if group else None
    build_members = group[1] if group else ()
    with_login_shells = tuple(
        member
        for member in build_members
        if (system.user_shell(member) or "") not in NOLOGIN_SHELLS
    )

    return NixInstallation(
        # EVERY PROBE, INCLUDING THE ONES THAT PASSED. A contract reporting only
        # conclusions cannot be audited: this is which commands produced the
        # verdict. `store verify` in particular had its stderr discarded
        # entirely -- only the exit code survived.
        probes=(
            ProbeRecord.of("version", version),
            ProbeRecord.of("eval", evaluation),
            ProbeRecord.of("flake", flake),
            ProbeRecord.of("store_verify", store_verify),
            *(
                (ProbeRecord.of("project_flake", project_flake),)
                if project_flake is not None
                else ()
            ),
        ),
        binary=nix,
        system=system.platform_double(),
        version=version.stdout,
        store_exists=system.is_dir(NIX_STORE),
        # THE PRECONDITION FOR TRUSTED_ROOTS, PREVIOUSLY ASSUMED.
        #
        # This contract accepts any binary resolving into /nix/store. That is
        # only sound if the store is not writable by the user running the check
        # -- otherwise anyone could place a binary there and satisfy it.
        #
        # Nix states the threat plainly: if users can modify the store "they
        # could install a Trojan horse in some package and compromise the
        # accounts of other users".
        store_writable_by_me=system.is_writable_by_me(NIX_STORE),
        store_owner=store_owner,
        store_mode=store_mode,
        build_group_id=build_group_id,
        build_user_count=len(build_members),
        build_users_with_login_shells=with_login_shells,
        receipt_exists=system.is_file(NIX_RECEIPT),
        receipt_is_valid=receipt_is_valid(system),
        uninstaller_exists=system.is_executable_file(NIX_INSTALLER),
        evaluate_outcome=outcome_of(evaluation),
        flake_outcome=outcome_of(flake),
        project_flake_checked=project_flake is not None,
        project_flake_outcome=(
            ProbeOutcome.OK if project_flake is None else outcome_of(project_flake)
        ),
        project_flake_error="" if project_flake is None else _diagnostic(project_flake),
        store_verify_status=store_verify.returncode,
        # KEEP WHAT NIX ACTUALLY SAID.
        #
        # These were booleans, and the stderr explaining them was discarded --
        # so an operator saw "`nix eval` fails" and never learned why. Someone
        # who hit this pattern elsewhere described the consequence exactly:
        # "agents loop, retry, or give up because the wrapper hides the actual
        # error."
        #
        # Bounded, but not meanly: a 500-character cap is a documented
        # complaint ("losing critical debugging information"). Nix errors carry
        # a trace, and the useful part is often not in the first line.
        evaluate_error=_diagnostic(evaluation),
        flake_error=_diagnostic(flake),
    )


def policy_input(installation: NixInstallation, *, flake_present: bool) -> NixPolicyInput:
    """The observation, as the document the policy judges.

    ONE MAPPING, and the only place the Python model meets the Rego rules. Every
    field is referenced by policies/machine/nix/nix.rego, and NixPolicyInput
    refuses any other: it was a hand-built dict, where a misspelt key would have
    reached the policy as an absence.
    """
    return NixPolicyInput(
        # THE FACTS THAT USED TO BE A PYTHON BRANCH. Whether an absent Nix
        # matters is a POLICY question, so both facts go to the policy.
        nix_present=installation.nix_present,
        flake_present=flake_present,
        searched=tuple(str(path) for path in installation.searched),
        system=installation.system,
        store_path=str(NIX_STORE),
        store_exists=installation.store_exists,
        store_writable_by_me=installation.store_writable_by_me,
        store_owner=installation.store_owner,
        store_mode=installation.store_mode,
        binary="" if installation.binary is None else str(installation.binary),
        semantic_version=".".join(str(part) for part in installation.semantic_version),
        minimum_version=".".join(str(part) for part in MINIMUM_NIX_VERSION),
        meets_version_floor=installation.meets_version_floor,
        evaluate_outcome=installation.evaluate_outcome.value,
        evaluate_error=installation.evaluate_error,
        flake_outcome=installation.flake_outcome.value,
        flake_error=installation.flake_error,
        project_flake_checked=installation.project_flake_checked,
        project_flake_outcome=installation.project_flake_outcome.value,
        project_flake_error=installation.project_flake_error,
        is_corrupted=installation.is_corrupted,
        is_untrusted=installation.is_untrusted,
        store_verify_ran=installation.store_verify_ran,
        store_verify_signal=installation.store_verify_signal,
        is_uninstallable=installation.is_uninstallable,
        receipt_is_valid=installation.receipt_is_valid,
        uninstaller_exists=installation.uninstaller_exists,
        build_group_id=installation.build_group_id,
        build_users_with_login_shells=tuple(installation.build_users_with_login_shells),
    )


def verify(installation: NixInstallation, *, flake_present: bool = False) -> ContractReport:
    """Judge an observation against policies/nix/nix.rego.

    THE RULES USED TO LIVE HERE, as ~300 lines of `if` statements appending to a
    list: unenumerable, individually untestable, and -- once the Rego existed --
    a SECOND IMPLEMENTATION of the same policy. Two implementations drift, and
    the drift is silent, so the Python ones are deleted rather than kept beside.

    This builds the input, evaluates, and returns the result typed. The
    judgement is in the Rego, where `opa test` exercises every rule in both
    directions.
    """
    problems, warnings = evaluate(policy_input(installation, flake_present=flake_present))

    # A VERDICT FOR EVERY RULE, NOT ONLY THE ONES THAT FIRED. Without this, a
    # deleted rule and a passing rule produce identical output.
    fired = frozenset(finding.code for finding in (*problems, *warnings))

    return ContractReport(
        problems=problems,
        warnings=warnings,
        verdicts=verdicts(fired),
    )


def run(
    system: System,
    *,
    out: TextIO,
    root: Path,
    search: tuple[Path, ...] = SEARCH_DIRS,
    evidence_path: Path | None = None,
    ledger_path: Path | None = None,
    request: ContractRequest | None = None,
) -> int:
    """The whole program, with its dependencies handed to it.

    THE SKIP BRANCH IS GONE. It used to live here as a Python `if`: no nix and
    no flake meant exit 0 with a bespoke envelope. That decision was invisible
    to the policy, absent from the verdicts, and untestable except through this
    function.

    Whether an absent Nix matters is a POLICY question -- it depends on whether
    anything in the repository needs one -- so the policy answers it now. A
    machine without Nix produces a warning when no flake exists and a problem
    when one does, both reported like every other rule.
    """
    timer = Timer()

    recorder = RecordingSystem(system) if evidence_path else None
    observed_through: System = recorder if recorder is not None else system

    # OBSERVE ALWAYS SUCCEEDS. Absence is a fact about the machine, not a
    # failure to look at it.
    installation = observe(observed_through, search=search, root=root)
    report = verify(installation, flake_present=(root / "flake.nix").exists())
    outcome = Outcome.SATISFIED if report.satisfied else Outcome.POLICY_DENIED

    # ONE RunMetadata, REUSED. It was constructed inline here and the ledger
    # had no access to it, so the run_id in the printed document and the entry
    # written beside it were unrelatable.
    run_metadata = RunMetadata.create(timer.elapsed_ms)

    print(
        build_output(
            installation=installation,
            report=report,
            outcome=outcome.value,
            run=run_metadata,
            schema_version=OUTPUT_SCHEMA_VERSION,
            policy_version=policy_revision(),
            request=(request or ContractRequest()).as_record(),
        ).model_dump_json(indent=2),
        file=out,
    )

    # THE BUNDLE IS WRITTEN BEFORE THE LEDGER ENTRY, so the entry can bind
    # itself to bytes that already exist. The reverse order would record a
    # digest of something not yet on disk.
    evidence_binding: dict[str, JsonValue] = {}
    if recorder is not None and evidence_path is not None:
        save_bundle(recorder.bundle(), evidence_path)
        evidence_binding = {
            "path": str(evidence_path),
            "sha256": bundle_digest(evidence_path),
        }

    if ledger_path is not None:
        append(
            {
                "outcome": outcome.value,
                "satisfied": report.satisfied,
                "policy_revision": policy_revision(),
                "codes": [problem.code for problem in report.problems],
                # THE LINK THAT WAS MISSING. The ledger recorded WHAT a run
                # concluded and the bundle recorded WHAT IT SAW, with nothing
                # connecting them -- given an entry you could not find its
                # bundle, and given a bundle you could not tell which entry it
                # belonged to.
                #
                # Bound by DIGEST, so a swapped or edited bundle fails the
                # check. Empty when no bundle was written, which is honest:
                # most runs produce no evidence, and a fabricated digest would
                # be worse than an absent one.
                "evidence": evidence_binding,
                # AND THE RUN ITSELF. Without this an entry could not be
                # correlated with the JSON document the same invocation printed.
                "run_id": run_metadata.run_id,
            },
            path=ledger_path,
        )

    return EXIT_CODES[outcome]


def main() -> int:
    """The composition root: the only place real dependencies are built."""
    # THE INVOCATION, VALIDATED ONCE. Three environment variables steered this
    # program and none was declared, validated or recorded -- so a report
    # produced with a narrowed search said "nix not found" while hiding that the
    # search had been redirected.
    request = ContractRequest()

    search: tuple[Path, ...] = SEARCH_DIRS
    if request.search_dirs:
        # NARROWING ONLY. A resolved path is still validated against
        # TRUSTED_ROOTS, so this cannot widen what is trusted -- and the
        # override is now RECORDED, which is what makes it safe to have.
        search = tuple(Path(part) for part in request.search_dirs.split(":") if part)

    return run(
        RealSystem(),
        out=sys.stdout,
        root=ROOT,
        search=search,
        evidence_path=request.evidence,
        ledger_path=request.ledger,
        request=request,
    )


if __name__ == "__main__":
    raise SystemExit(main())
