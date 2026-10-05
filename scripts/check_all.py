"""Run every gate, report every result, exit nonzero if any failed.

THE PROBLEM THIS REPLACES
`check` was a mise task with depends = [lint, types, test, ...]. mise runs
dependencies in PARALLEL, up to four jobs, with no order among them, and reports
failure as soon as one fails. The observed effect: `test` failed at 1.4s and
`types` never reported at all -- mypy was still running and nobody was listening.

That produces fix-one, re-run, discover-the-next: a treadmill built into the gate
itself. Worse, a task whose result is never printed is indistinguishable from one
that passed, so the gate can quietly under-report what it checked.

WHAT THIS DOES INSTEAD
Runs each gate to completion, captures its output, and prints a summary of ALL
results. Same contract as `pre-commit run --all-files`: one invocation tells the
whole truth. Serial and slower, deliberately -- correctness of reporting beats
a few seconds on a gate that runs on every commit.

WHY EACH GATE IS STILL ITS OWN mise TASK
So `mise run lint` works standalone during iteration. This aggregates them; it
does not replace them, and there is no second copy of the list to drift.
"""

from __future__ import annotations

import subprocess
import sys

# ONE LIST, TWO MODES. Each gate declares whether it needs the network.
#
# WHY NOT TWO LISTS: hooks must be fast and must work offline, CI must be
# exhaustive. Writing that as two sets of checks in two places is precisely the
# drift this repo exists to prevent -- add a gate to one, forget the other, and
# the difference is invisible until something ships broken. A flag over a single
# list cannot drift.
#
# Order is presentation order, not dependency order; every selected gate runs
# regardless of whether an earlier one failed.
#
# WHY ONE SERIAL RUNNER RATHER THAN PARALLEL CI JOBS.
# A matrix fanning these into separate jobs would give per-gate check names that
# branch protection could require individually, and failure attribution visible
# from the check list rather than the log. Both are real advantages, and both
# are rejected on one ground: a matrix must ENUMERATE the gates in YAML, making
# ci.yml a second source of truth for this list. That copy goes stale silently,
# which is the drift the whole design avoids -- ci.yml runs `mise run check` and
# restates nothing.
#
# Running everything and reporting everything is also the right choice for a
# QUALITY gate specifically: fail-fast minimises wasted work after a decisive
# failure, while running all checks maximises the diagnostic information from
# one commit. A gate wants the second.
#
# (name, command, ci_only)
#
# ci_only means "not in the git hooks": either it needs the network and valid
# Databricks auth, or it is slow enough that including it would train people to
# bypass the hook. Both make a gate that belongs in CI, where a bypass is caught.
GATES: list[tuple[str, list[str], bool]] = [
    ("lint", ["uv", "run", "ruff", "check", "--no-cache", "."], False),
    ("format", ["uv", "run", "ruff", "format", "--check", "."], False),
    # BOTH PLATFORMS, DELIBERATELY. mypy defaults to the OS it runs on and
    # NARROWS sys.platform comparisons, so a Darwin-only branch is invisible to a
    # Linux run and vice versa. This repo is a macOS laptop plus a Linux CI
    # runner; checking one leaves the other branch unverified everywhere.
    ("types (darwin)", ["uv", "run", "mypy", "--platform", "darwin"], False),
    ("types (linux)", ["uv", "run", "mypy", "--platform", "linux"], False),
    ("test", ["uv", "run", "pytest", "-q"], False),
    # Policy gets the same treatment as the Python: well-formed and tested, then
    # evaluated against the actual repo. Both are offline.
    ("policy", ["mise", "run", "check:policy"], False),
    ("policy decisions", ["uv", "run", "python", "scripts/evaluate_policies.py"], False),
    # FULL HISTORY, NOT THE WORKING TREE. A pre-commit hook only ever sees the
    # incoming change, so anything committed before hooks existed -- or pushed
    # with --no-verify -- has never been scanned. This repo already leaked an
    # OAuth secret to a terminal; the credential never reached a commit, but the
    # class of mistake did happen here.
    #
    # betterleaks rather than gitleaks: same author, MIT, drop-in, and gitleaks
    # now receives security patches only. It replaces Shannon entropy with token
    # efficiency scoring, which raises precision substantially -- precision
    # matters as much as recall, because a scanner that cries wolf trains people
    # to bypass it, which is how the gate really fails.
    #
    # --redact keeps any finding out of CI logs, where it would become a second
    # leak in the process of reporting the first.
    # DEBRIS, alongside the secret and PII scans. Those ask what a file
    # CONTAINS; this asks whether a tracked file looks like an accident at all.
    #
    # A zero-byte `nix_contract` -- a mistyped shell redirect -- was swept into
    # a commit by `git add -A` and no gate saw it. Offline and instant, so it
    # belongs in the hooks where the mistake is made.
    ("repo hygiene", ["uv", "run", "python", "scripts/check_repo_hygiene.py"], False),
    ("secrets (history)", ["betterleaks", "git", "--redact", "--no-banner"], False),
    # PII BY CONTENT, alongside the secret scan and the structural checks.
    # .gitignore filters by format and test_no_data_in_repo filters by path;
    # both are proxies. This reads what is in the file.
    #
    # Pattern-based recognizers only -- no PERSON. An earlier version enabled it
    # and reported 75 findings of which ~70 were `ruff`, `Darwin` and `dict[str`:
    # NER trained on prose reads capitalised identifiers in source as names.
    # Presidio's own guidance is to remove recognizers the data does not need.
    # MARKED AS "NETWORK" THOUGH IT MAKES NO NETWORK CALL.
    #
    # The flag really means "too expensive or too dependent for a git hook", and
    # this is the first gate that is slow rather than remote. Loading spaCy takes
    # ~16s, which took the pre-push gate from 4.5s to 20.8s -- a 4x cost on the
    # hook that runs most often.
    #
    # That matters more than it sounds: a slow hook is one people bypass with
    # --no-verify, and a bypassed hook catches nothing. The same reasoning put
    # the Databricks checks in CI. Renaming the flag would be honest and is
    # deferred deliberately -- it appears in three files and this is not the
    # branch for it.
    ("pii", ["uv", "run", "python", "scripts/check_pii.py"], True),
    # NETWORK + DATABRICKS AUTH. Excluded from hooks deliberately: a pre-commit
    # that needs a live workspace blocks legitimate offline work, and a local
    # commit cannot invalidate server-side state anyway. More importantly, a hook
    # that fails on a plane is a hook people bypass with --no-verify, and a
    # bypassed hook catches nothing. CI is where these run.
    # Needs the bundle, so it needs the network.
    ("fixtures", ["uv", "run", "python", "scripts/update_fixtures.py", "--check"], True),
    # The integration-marked tests, deselected from the hermetic `test` gate.
    ("test (integration)", ["uv", "run", "pytest", "-m", "integration"], True),
    ("prereqs", ["uv", "run", "python", "scripts/check_prereqs.py"], True),
    # THE MACHINE ITSELF, judged by policies/machine/nix.
    #
    # NOT ci_only, AND THE FIRST ATTEMPT HAD THIS BACKWARDS. ci_only means
    # "skipped in hooks, run in CI" -- so marking it true ran the check ONLY on
    # the runner, which has no Nix, and never on the developer machine it
    # exists to judge. CI failed with observe_error, correctly.
    #
    # This gate is about the LOCAL toolchain. A CI runner needs Nix only once
    # flake.nix exists and the build depends on it; until then, checking the
    # runner's Nix is checking nothing anyone uses.
    #
    # It exits 1 on a policy-denied machine and 2 when the contract cannot be
    # evaluated at all, so the aggregator's returncode != 0 test covers both.
    ("nix contract", ["uv", "run", "python", "scripts/nix_contract.py"], False),
    # THE FLAKE EVALUATES ON EVERY PLATFORM, not just the one running the gate.
    #
    # nix:flake-check existed as a task and no gate ran it -- the
    # built-and-not-wired shape this session keeps removing. A flake that stops
    # evaluating is a toolchain nobody can install.
    #
    # ci_only BECAUSE CI NOW HAS NIX. The first draft of this line said
    # ci_only=True with a comment claiming it matched the contract, which is
    # ci_only=FALSE precisely because the runner had none -- the same backwards
    # flag that cost two CI failures earlier. Installing Nix on the runner is
    # what makes True correct here rather than a third repeat.
    #
    # --no-build proves every package NAME resolves on all four platforms in
    # seconds. It does NOT prove they build: an unfree licence passed four
    # green platforms and failed on the first real `nix develop`.
    ("nix flake", ["nix", "flake", "check", "--no-build", "--all-systems"], True),
    ("env-parity", ["uv", "run", "python", "scripts/check_env_parity.py"], True),
]


def main() -> int:
    offline = "--offline" in sys.argv
    gates = [g for g in GATES if not (offline and g[2])]

    if offline:
        skipped = [name for name, _, network in GATES if network]
        print(f"offline mode: skipping {', '.join(skipped)}\n")

    results: list[tuple[str, bool, str]] = []

    for name, command, _ in gates:
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        passed = completed.returncode == 0
        output = (completed.stdout + completed.stderr).strip()
        results.append((name, passed, output))
        print(f"{'PASS' if passed else 'FAIL'}  {name}", flush=True)

    failed = [(name, output) for name, passed, output in results if not passed]

    if failed:
        for name, output in failed:
            print(f"\n{'=' * 70}\nFAILED: {name}\n{'=' * 70}", file=sys.stderr)
            print(output, file=sys.stderr)
        print(
            f"\n{len(failed)} of {len(results)} gates failed: "
            f"{', '.join(name for name, _ in failed)}",
            file=sys.stderr,
        )
        return 1

    print(f"\nall {len(results)} gates passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
