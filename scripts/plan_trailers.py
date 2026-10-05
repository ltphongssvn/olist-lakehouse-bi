"""Every commit names the plan steps it serves: observed by git, decided by policy.

TRAILERS ARE READ BY GIT, NOT BY A REGEX. git decides what a trailer is -- the
final paragraph, all trailers or a quarter of them -- and both observation
points use its parser: `git log`'s trailer placeholder for saved commits, and
`interpret-trailers --parse` for a message the commit-msg hook holds unsaved.

TWO POINTS, ONE POLICY. The hook refuses at zero latency; the gate, which CI
runs, refuses a commit made with --no-verify before it can merge.

ONE READER OF COMMITS. log_commits serves this check, over the branch, and the
requirement matrix, over all of develop.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from command_outcome import CommandOutcome
from gitenv import git
from opa import denials
from plan_files import load
from plan_models import BranchCommits, CommitSteps

ROOT = Path(__file__).resolve().parent.parent
BASE = "origin/develop"
KEY = "Plan-Step"
FIELD, RECORD = "\x1f", "\x1e"
FORMAT = f"%H%x1f%P%x1f%s%x1f%(trailers:key={KEY},valueonly=true,separator=%x2C)%x1e"


def _ledger(root: Path) -> tuple[tuple[str, ...], tuple[str, ...]]:
    _, _, ids = load(root)
    return (
        tuple(entry.id for entry in ids.issued),
        tuple(entry.id for entry in ids.issued if entry.retired),
    )


def log_commits(root: Path, revision: str) -> tuple[CommitSteps, ...]:
    """Every commit in a revision or range, with the steps its trailers name."""
    shown = git("log", f"--format={FORMAT}", revision, cwd=root)
    if shown.returncode != 0:
        raise SystemExit(f"git log {revision} failed: {shown.stderr.strip()}")
    commits: list[CommitSteps] = []
    for record in shown.stdout.split(RECORD):
        record = record.strip("\n")
        if not record:
            continue
        sha, parents, subject, steps = record.split(FIELD)
        named = tuple(step.strip() for step in steps.split(",") if step.strip())
        merge = len(parents.split()) > 1
        commits.append(CommitSteps(sha=sha, subject=subject, merge=merge, steps=named))
    return tuple(commits)


def observe(root: Path = ROOT, base: str = BASE) -> BranchCommits:
    """Every commit on this branch since the base, with the steps it names."""
    issued, retired = _ledger(root)
    commits = log_commits(root, f"{base}..HEAD")
    return BranchCommits(base=base, commits=commits, issued=issued, retired=retired)


def observe_message(root: Path, message: Path) -> BranchCommits:
    """One message not yet committed, as the commit-msg hook holds it."""
    parsed = git("interpret-trailers", "--parse", str(message), cwd=root)
    if parsed.returncode != 0:
        raise SystemExit(f"git interpret-trailers failed: {parsed.stderr.strip()}")
    steps: list[str] = []
    for line in parsed.stdout.splitlines():
        key, _, value = line.partition(":")
        if key.strip().lower() == KEY.lower() and value.strip():
            steps.append(value.strip())
    subject = message.read_text(encoding="utf-8").splitlines()[0] if message.stat().st_size else ""
    commit = CommitSteps(sha="(uncommitted)", subject=subject, merge=False, steps=tuple(steps))
    issued, retired = _ledger(root)
    return BranchCommits(base="(message)", commits=(commit,), issued=issued, retired=retired)


def main(argv: list[str] | None = None) -> int:
    """plan:trailers -- one message file when given, else the branch since develop."""
    args = list(sys.argv[1:] if argv is None else argv)
    observed = observe_message(ROOT, Path(args[0])) if args else observe(ROOT)
    payload = {"branch_commits": observed.model_dump(mode="json")}
    problems = [d for d in denials("data.plan.deny", payload) if d.startswith("[ERR_TRAILER_")]
    outcome = CommandOutcome.model_validate(
        {
            "command": "plan:trailers",
            "outcome": "refused" if problems else "success",
            "code": "trailers_refused" if problems else "trailers_named",
            "message": (
                f"{len(problems)} commit trailer problem(s)"
                if problems
                else f"{len(observed.commits)} commit(s), every one naming an issued plan step"
            ),
            "data": {"commits": len(observed.commits), "problems": problems},
        }
    )
    print(json.dumps(outcome.model_dump(), indent=2))
    return outcome.exit_code


if __name__ == "__main__":
    sys.exit(main())
