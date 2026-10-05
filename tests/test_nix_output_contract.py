"""Lock the JSON output contract.

WHY A SCHEMA VERSION NEEDS A TEST TO MEAN ANYTHING
A version field nobody checks is decoration: the shape drifts, the number stays
at 1.0, and a consumer that pinned to it is misled rather than protected.

The 2026 convention pairs the two deliberately -- one project describes golden
tests that "fail until regenerated, forcing the bump to be intentional", another
a CI test asserting "the documented top-level keys, locking the contracts".

WHAT THIS ASSERTS
The EXACT top-level key set of both envelopes. Adding a key, removing one, or
renaming one fails here -- and the fix is either to undo it or to bump
OUTPUT_SCHEMA_VERSION deliberately. That is the whole mechanism.

It does not assert values. Those change with the machine; the shape must not.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from nix_contract import EXIT_CODES, OUTPUT_SCHEMA_VERSION, Outcome

ROOT = Path(__file__).resolve().parent.parent
CONTRACT = ROOT / "scripts" / "nix_contract.py"

# THE CONTRACT. Changing this set is changing the contract, and doing so without
# bumping OUTPUT_SCHEMA_VERSION is the mistake this file exists to prevent.
SUCCESS_KEYS = frozenset(
    {
        "schema_version",
        # Added in 1.1, and the lock caught the change before it shipped --
        # which is the entire mechanism. The bump was deliberate, so the key set
        # follows it here rather than the other way round.
        "policy_version",
        "run",
        # Added in 2.3. Three environment variables steered this program and
        # none was recorded, so a report produced with a narrowed search said
        # "nix not found" while hiding that the search was redirected.
        "request",
        # Added in 1.2. The distinction existed only as two booleans a consumer
        # had to combine; this names it.
        "outcome",
        # Added in 1.3. Every command run to produce the verdict, so the
        # observation is auditable rather than asserted.
        "probes",
        "satisfied",
        "nix_present",
        "binary",
        "from_store",
        "version",
        "semantic_version",
        # Added in 2.1. The contract hardcoded macOS assumptions -- a nixbld
        # group, store mode 1775, /sbin/nologin -- and no rule knew which
        # platform it was judging. The KIND of machine, never which one.
        "system",
        "distribution",
        "uninstallable",
        # Added in 1.4. "uninstallable" used to mean "a file exists at
        # /nix/receipt.json", which `touch` satisfies. These two say what it is
        # actually derived from.
        "receipt_valid",
        "uninstaller_present",
        "can_evaluate",
        "can_evaluate_a_flake",
        # Added in 2.2. The synthetic probe proved the machinery; this says
        # whether THIS repository's flake was evaluated at all -- which is not
        # the same as it passing.
        "project_flake_checked",
        "store_verify_status",
        "untrusted_signature",
        "problems",
        "warnings",
        # Added in 1.6. problems and warnings hold only rules that FIRED, so a
        # deleted rule and a passing rule produced identical output. This
        # carries pass/fail for EVERY declared rule.
        "verdicts",
    }
)

PROBLEM_KEYS = frozenset({"code", "message", "remediation"})

RUN_KEYS = frozenset({"run_id", "observed_at", "duration_ms", "trace_id", "parent_span_id"})

PROBE_KEYS = frozenset(
    {
        "name",
        "argv",
        "exit_code",
        "duration_ms",
        # ADDED: the transcript recorded three of the four facts a behaviour
        # record needs -- argv, exit code, stderr -- and omitted what the
        # command RETURNED. Without it a reader sees that `nix --version` ran
        # and not the string that became semantic_version.
        "stdout",
        "stderr",
        "truncated",
    }
)

REMEDIATION_KEYS = frozenset({"description", "command", "autonomy", "reversible", "privileged"})


def run_contract_without_nix() -> tuple[dict[str, object], int]:
    """Run the REAL script with the search pointed somewhere empty.

    This reproduces CI's condition on a machine that has Nix. Two earlier
    attempts to contrive it failed -- PATH does not reach resolve_binary by
    design, and a copied tree lost its tool versions -- so the search directories
    became a parameter with an environment seam that can only NARROW them.

    Without this, the skip envelope was first exercised in CI, which is where
    both previous failures were discovered rather than prevented.
    """
    result = subprocess.run(
        [sys.executable, str(CONTRACT)],
        capture_output=True,
        text=True,
        check=False,
        cwd=ROOT,
        env={**os.environ, "NIX_CONTRACT_SEARCH_DIRS": "/nonexistent"},
    )
    parsed: dict[str, object] = json.loads(result.stdout)
    return parsed, result.returncode


def test_a_narrowed_search_is_visible_in_the_report() -> None:
    """THE FACT A REPORT MUST NOT HIDE.

    run_contract_without_nix sets NIX_CONTRACT_SEARCH_DIRS to a path that cannot
    exist. The resulting report says "nix not found in any searched directory"
    -- true, and misleading, because the search was deliberately redirected.

    Before this the override left no trace, so a reader could not distinguish a
    genuinely Nix-less machine from one whose search had been pointed at
    nothing. The evidence concealed the one fact needed to interpret it.
    """
    document, _ = run_contract_without_nix()

    request = document["request"]
    assert isinstance(request, dict)

    assert request["search_overridden"] is True
    assert "/nonexistent" in str(request["search_dirs"])


def test_an_ordinary_run_records_no_override() -> None:
    """The other direction: a normal run must not claim one.

    A flag that reads true everywhere carries no information, which is the
    defect `evaluable` had before it was removed.
    """
    request = run_contract()["request"]
    assert isinstance(request, dict)

    assert request["search_overridden"] is False
    assert request["search_dirs"] == ""


def test_the_request_block_names_where_evidence_would_go() -> None:
    """A reader chasing a bundle needs the path that was asked for."""
    request = run_contract()["request"]
    assert isinstance(request, dict)

    assert set(request) == {
        "search_overridden",
        "search_dirs",
        "evidence_path",
        "ledger_path",
    }


def test_a_machine_without_nix_emits_the_ordinary_envelope() -> None:
    """ONE SHAPE, NOT THREE.

    An absent Nix used to produce a bespoke "skipped" document with its own key
    set. Absence is now a policy finding like any other, so the same envelope
    carries it.

    ASSERTS THE SHAPE, NOT THE VERDICT, AND THAT IS THE FIX.
    Three sibling tests asserted the exit code and the exact findings here, and
    all three broke the moment flake.nix was added -- because they ran the real
    script against the REAL repository and encoded its contents as permanent.
    That is a gate going red "for reasons unrelated to the diff", which teaches
    people to ignore a red gate.

    The verdict depends on whether the project needs Nix, so it is tested in
    test_nix_run.py where tmp_path controls whether a flake exists. What only a
    subprocess can prove is the shape of what reaches stdout, which is what
    stays here.
    """
    document, _ = run_contract_without_nix()

    assert set(document) == SUCCESS_KEYS


def run_contract_with_code() -> tuple[dict[str, object], int]:
    """The document AND the exit code, because they are one contract.

    A wrapper branches on the exit code and reads the document; if they
    disagree, the wrapper is misled. Testing them separately would let them
    drift apart.
    """
    result = subprocess.run(
        [sys.executable, str(CONTRACT)],
        capture_output=True,
        text=True,
        check=False,
        cwd=ROOT,
    )
    parsed: dict[str, object] = json.loads(result.stdout)
    return parsed, result.returncode


def run_contract() -> dict[str, object]:
    """Run the real script and parse its stdout.

    A SUBPROCESS, NOT AN IMPORT. The contract being locked is what the COMMAND
    emits, and importing main() would test the function while leaving the actual
    stdout -- the thing consumers read -- unverified.
    """
    result = subprocess.run(
        [sys.executable, str(CONTRACT)],
        capture_output=True,
        text=True,
        check=False,
        cwd=ROOT,
    )
    parsed: dict[str, object] = json.loads(result.stdout)
    return parsed


def test_stdout_is_exactly_one_json_document() -> None:
    """No prose, no banner, no trailing text.

    A consumer does `json.loads(stdout)`. Anything else on that stream breaks
    it, and the failure looks like corrupt output rather than a stray print.
    """
    run_contract()


def test_the_success_envelope_has_exactly_the_documented_keys() -> None:
    document = run_contract()
    # NO SKIP: the envelope is now the SAME shape whether nix is present or
    # not. That is the point of collapsing three envelopes into one.

    assert set(document) == SUCCESS_KEYS, (
        "the output contract changed. Either revert it, or bump "
        f"OUTPUT_SCHEMA_VERSION (currently {OUTPUT_SCHEMA_VERSION}) and update "
        "SUCCESS_KEYS deliberately."
    )


def test_the_envelope_declares_the_current_schema_version() -> None:
    assert run_contract()["schema_version"] == OUTPUT_SCHEMA_VERSION


def test_problems_and_warnings_carry_the_documented_shape() -> None:
    """Checked wherever they appear, since a clean machine has none.

    Asserting only on problems would leave this untested on any machine where
    the contract is satisfied -- which is the normal case, and therefore the
    case where drift would go unnoticed longest.
    """
    document = run_contract()
    if not document["nix_present"]:
        pytest.skip("this machine has no Nix, so there are no probes to record")

    # Narrowed rather than suppressed. A `# type: ignore` was written here
    # first, guessing arg-type; mypy reported the real code as call-overload AND
    # the guess as unused. The cause is dict[str, object]: `object` is not
    # iterable, so list() rejects it. An assertion tells the checker what the
    # runtime already guarantees.
    problems = document["problems"]
    warnings = document["warnings"]
    assert isinstance(problems, list)
    assert isinstance(warnings, list)

    for finding in [*problems, *warnings]:
        assert isinstance(finding, dict)
        assert set(finding) == PROBLEM_KEYS

        remediation = finding["remediation"]
        assert isinstance(remediation, dict)
        assert set(remediation) == REMEDIATION_KEYS


def test_the_run_block_carries_correlation_and_timing() -> None:
    """Absent trace ids are null, not missing.

    A consumer reading document["run"]["trace_id"] should get None on an
    untraced run rather than a KeyError -- the key is part of the contract even
    when nothing populated it.
    """
    document = run_contract()
    if not document["nix_present"]:
        pytest.skip("this machine has no Nix, so there are no probes to record")

    run = document["run"]
    assert isinstance(run, dict)

    assert set(run) == RUN_KEYS
    assert isinstance(run["duration_ms"], int)
    assert run["duration_ms"] >= 0


def test_no_hostname_is_emitted() -> None:
    """Deliberate, and worth locking.

    This machine's hostname contains a person's name. The repository runs a PII
    scanner to keep identifying data out of committed artifacts; emitting a
    hostname into a document destined for logs would plant PII by design. A
    future addition should fail here first.
    """
    document = run_contract()
    if not document["nix_present"]:
        pytest.skip("this machine has no Nix, so there are no probes to record")

    assert "hostname" not in document
    assert "hostname" not in document["run"]  # type: ignore[operator]


def test_the_exit_code_matches_the_reported_outcome() -> None:
    """The pair that must never disagree.

    The exit code and the outcome were independent expressions that happened to
    agree. A wrapper reading exit 1 and finding outcome "satisfied" has no way
    to decide which to believe -- and the documented consequence of conflating
    the codes is downstream "log-parsing heuristics".
    """
    document, exit_code = run_contract_with_code()

    raw = document["outcome"]
    assert isinstance(raw, str)

    assert exit_code == EXIT_CODES[Outcome(raw)]


def test_the_outcome_is_one_of_the_declared_values() -> None:
    """A value outside the enum is drift, not a new state."""
    raw = run_contract()["outcome"]
    assert isinstance(raw, str)

    assert Outcome(raw) in set(Outcome)


def test_the_grep_convention_is_preserved() -> None:
    """0 satisfied, 1 denied.

    Locked because it is the contract every CI wrapper depends on.

    EXIT 2 IS GONE, and its absence is the point. It meant "the tool could not
    run", which was reachable only while observe() raised on an absent Nix.
    Observation always succeeds now, so a state nothing can produce would be a
    declared lie -- and the distinction that justified exit 2, "the analysis ran
    and found a problem" versus "the analysis could not run", is now carried by
    a FINDING rather than by an exit code.
    """
    assert EXIT_CODES[Outcome.SATISFIED] == 0
    assert EXIT_CODES[Outcome.POLICY_DENIED] == 1


def test_every_outcome_has_an_exit_code() -> None:
    """A new outcome without a code would raise KeyError at the exit path --
    after the document was already printed."""
    assert set(EXIT_CODES) == set(Outcome)


def test_every_probe_records_what_ran_and_what_happened() -> None:
    """The audit trail, locked.

    A contract reporting only conclusions cannot be checked. Each probe carries
    the argv that ran, its exit code, how long it took, and its stderr -- which
    is what turns a verdict into evidence.
    """
    document = run_contract()
    if not document["nix_present"]:
        pytest.skip("this machine has no Nix, so there are no probes to record")

    probes = document["probes"]
    assert isinstance(probes, list)
    assert probes, "a successful observation still runs commands; none were recorded"

    for probe in probes:
        assert isinstance(probe, dict)
        assert set(probe) == PROBE_KEYS

        argv = probe["argv"]
        assert isinstance(argv, list)
        assert argv, "a probe with no argv records nothing useful"


def test_store_verify_is_among_the_recorded_probes() -> None:
    """It was the one whose stderr was discarded entirely.

    Only its exit code survived, so a `nix store verify` that failed for an
    unexpected reason reported a bare number.
    """
    document = run_contract()
    if not document["nix_present"]:
        pytest.skip("this machine has no Nix, so there are no probes to record")

    probes = document["probes"]
    assert isinstance(probes, list)

    names = {probe["name"] for probe in probes if isinstance(probe, dict)}
    assert "store_verify" in names


def test_truncation_is_recorded_rather_than_silent() -> None:
    """A short error and a cut one must be distinguishable.

    The requirement is "bounded capture WITH TRUNCATION EVIDENCE" -- without the
    flag, a reader cannot tell whether the useful part was removed.
    """
    document = run_contract()
    if not document["nix_present"]:
        pytest.skip("this machine has no Nix, so there are no probes to record")

    probes = document["probes"]
    assert isinstance(probes, list)

    for probe in probes:
        assert isinstance(probe, dict)
        assert isinstance(probe["truncated"], bool)


def test_the_two_fields_a_consumer_branches_on_are_booleans() -> None:
    """satisfied and evaluable decide what a caller does next.

    A string "false" would be truthy, and the caller would proceed on a machine
    that failed the contract.
    """
    document = run_contract()

    assert isinstance(document["satisfied"], bool)
    assert isinstance(document["nix_present"], bool)
