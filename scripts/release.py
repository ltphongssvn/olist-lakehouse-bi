# scripts/release.py
"""Perform a release: promote, export the executed run, verify it, and tag.

WHY THIS EXISTS
main advanced once with no release performed -- no export, no submission, no tag
-- because someone clicked GitHub's "Compare & pull request" banner. The ruleset
allowed it correctly: a PR and a green gate, both satisfied. Nothing in this repo
said WHEN main may advance, so that rule lived in commit prose and enforced
nothing.

WHY THE RUN IS EXPORTED, NOT THE NOTEBOOK
The Canvas deliverable is an EXECUTED notebook. The bundle deploys the notebook
as source; the outputs belong to the RUN. `workspace export` would produce the
file the job READ, not what it produced -- source with empty cells, which looks
like a valid submission and is not one.

WHY THE TAG MATTERS MORE THAN IT LOOKS
Without one, "which commit was submitted for assignment 1" is answerable only by
reading merge dates. With one it is a name -- which also makes a regrade or a
late fix a hotfix off a known point rather than archaeology. The tag message
records the JOB RUN, which is what identifies the exported work.

EVERY REFUSAL RUNS BEFORE THE IRREVERSIBLE STEP
An earlier version promoted develop to main and THEN checked the working tree,
refusing after a merge to a protected branch had already happened.

ANY ASSIGNMENT, DERIVED FROM THE BUNDLE (D.14). The export directory, job name
and notebook name were fixed to Assignment 1. They are derived now from one job
key in the bundle resolved for the fixture target -- whose names carry no dev
prefix -- so a suffix match finds the job in dev and prod alike, and there is no
second mapping of assignments to jobs to drift. policies/release then refuses a
tag that does not name the assignment being released.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from databricks_cli import Jobs, ResolvedBundle, Run, Runs, cli
from opa import denials
from pr import merge_when_green
from verify_export import fetch_export, verify

ROOT = Path(__file__).resolve().parent.parent
NOTEBOOK_PATH = re.compile(
    r"/assignments/(?P<assignment>[^/]+)/notebooks/(?P<notebook>[^/.]+)(?:\.py)?$"
)


class ReleaseTarget(BaseModel):
    """What one release exports, derived from its job in the resolved bundle."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    job_key: str
    job_name: str
    assignment: str
    notebook: str

    @property
    def exports(self) -> Path:
        return Path("assignments") / self.assignment / "exports"


class _NotebookTask(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")
    notebook_path: str


class _Task(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")
    notebook_task: _NotebookTask


class _ReleasableJob(BaseModel):
    """The two things a release reads from a job: its name and its notebook."""

    model_config = ConfigDict(frozen=True, extra="ignore")
    name: str
    tasks: tuple[_Task, ...] = Field(min_length=1)


def release_target(bundle: ResolvedBundle, job_key: str) -> ReleaseTarget:
    """The release target for one job, or a refusal naming the jobs that exist."""
    jobs = bundle.resources.get("jobs", {})
    if job_key not in jobs:
        raise SystemExit(f"no job {job_key!r} in the bundle; it declares {sorted(jobs)}")
    job = _ReleasableJob.model_validate(jobs[job_key])
    match = NOTEBOOK_PATH.search(job.tasks[0].notebook_task.notebook_path)
    if match is None:
        raise SystemExit(
            f"{job_key}'s notebook is not under assignments/<assignment>/notebooks/, "
            "so its export has no assignment to land beside"
        )
    return ReleaseTarget(
        job_key=job_key,
        job_name=job.name,
        assignment=match["assignment"],
        notebook=match["notebook"],
    )


def resolved_bundle() -> ResolvedBundle:
    """The bundle resolved for the fixture target: identity-free, so names are unprefixed."""
    return cli(ResolvedBundle, "bundle", "validate", "-t", "fixture", "--output", "json", cwd=ROOT)


def refuse_unless_policy_allows(tag: str, target: ReleaseTarget) -> None:
    """policies/release judges the tag before anything merges."""
    release = {"tag": tag, "target": target.model_dump(mode="json")}
    problems = [
        d
        for d in denials("data.release.deny", {"release": release})
        if d.startswith("[ERR_RELEASE_")
    ]
    if problems:
        raise SystemExit("refusing:\n" + "\n".join(f"  {problem}" for problem in problems))


def _run(*args: str) -> str:
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        print(result.stderr.strip(), file=sys.stderr)
        raise SystemExit(f"{' '.join(args)} failed")
    return result.stdout


def promote_develop_to_main() -> None:
    """Open and merge a develop -> main pull request, waiting for CI.

    Promotion is part of the release rather than something that happens beside
    it -- which is how main advanced once with nothing released.
    """
    behind = _run("git", "rev-list", "--count", "origin/main..origin/develop").strip()
    if behind == "0":
        print("main already matches develop")
        return

    print(f"promoting develop to main ({behind} commits)")
    existing = _run(
        "gh",
        "pr",
        "list",
        "--base",
        "main",
        "--head",
        "develop",
        "--state",
        "open",
        "--json",
        "number",
        "--jq",
        ".[0].number // empty",
    ).strip()

    if not existing:
        _run(
            "gh",
            "pr",
            "create",
            "--base",
            "main",
            "--head",
            "develop",
            "--title",
            "release: promote develop to main",
            "--body",
            "Automated by `mise run release`. Export and tag follow.",
        )

    # THE SHARED IMPLEMENTATION, not a second copy. This called
    # `gh pr merge --auto` immediately and GitHub rejected it -- auto-merge
    # cannot be enabled before requirements are met -- so the PR sat green and
    # unmerged. Two copies of a timing-sensitive sequence is one too many, and
    # the copy that drifted was the one that promotes to main.
    merge_when_green()

    # Fetch ALL refs. `fetch origin main:main` updates the local branch and
    # leaves origin/main -- the ref every comparison here uses -- untouched.
    _run("git", "fetch", "origin", "--prune")
    behind_after = _run("git", "rev-list", "--count", "origin/main..origin/develop").strip()
    if behind_after != "0":
        raise SystemExit(
            f"promotion did not complete: main is still {behind_after} commits behind. "
            "Check the PR before releasing."
        )
    print("main now matches develop")


def refuse_if_dirty() -> None:
    """A release built from uncommitted work cannot be reproduced from its tag."""
    if _run("git", "status", "--porcelain").strip():
        raise SystemExit(
            "refusing: working tree is dirty.\n"
            "A release built from uncommitted work cannot be reproduced from the "
            "tag it creates."
        )


def refuse_if_tag_exists(tag: str) -> None:
    if _run("git", "tag", "-l", tag).strip():
        raise SystemExit(
            f"refusing: tag {tag} already exists.\n"
            "Releases are immutable. For a correction, cut a hotfix from the tag."
        )


def refuse_unless_promoted() -> None:
    """origin/main must CONTAIN origin/develop -- not equal it.

    An earlier version compared SHAs and refused a promotion that had just
    succeeded. Merging develop into main creates a MERGE COMMIT that exists only
    on main, so the two can never share a SHA after promotion -- by design, since
    squash and rebase are disabled to preserve GitFlow topology.

    THE EXIT CODES ARE NOT A BOOLEAN. 0 means ancestor, 1 means not, and anything
    else -- 128 for a missing or misspelled ref -- is an ERROR. Treating every
    non-zero as "not merged" would report a typo as an unmerged branch.
    """
    ancestry = subprocess.run(
        ["git", "merge-base", "--is-ancestor", "origin/develop", "origin/main"],
        capture_output=True,
        text=True,
        check=False,
        cwd=ROOT,
    )
    if ancestry.returncode == 1:
        raise SystemExit(
            "refusing: origin/main does not contain origin/develop.\n"
            "The release would tag a commit that is not what was verified."
        )
    if ancestry.returncode != 0:
        raise SystemExit(
            f"ancestry check failed (exit {ancestry.returncode}): "
            f"{ancestry.stderr.strip()}\n"
            "This is an error, not a negative answer -- usually a ref that does "
            "not exist."
        )


def latest_successful_run(target: ReleaseTarget) -> Run:
    """The most recent successful run of the assignment job.

    Matched on a name SUFFIX because development mode prefixes job names with
    "[dev <user>] ". An exact match would find nothing in dev and silently report
    no runs.

    THIS IS WHAT ESTABLISHES IDENTITY. The export's view name cannot: for a
    bundle-deployed serverless run the executed notebook is an ephemeral copy
    named by UUID, so a check against the notebook's name refuses every correct
    export. The run id is recorded in the tag message instead.
    """
    jobs = cli(Jobs, "jobs", "list", "--output", "json").root
    matches = [j for j in jobs if j.settings.name.endswith(target.job_name)]
    if not matches:
        raise SystemExit(
            f"no job whose name ends with {target.job_name!r}; deploy and run it first"
        )

    job_id = matches[0].job_id
    runs = cli(Runs, "jobs", "list-runs", "--job-id", str(job_id), "--output", "json").root

    successful = [r for r in runs if r.state.result_state == "SUCCESS"]
    if not successful:
        raise SystemExit(
            f"job {job_id} has no successful run. A release must export a run that "
            "actually completed."
        )

    return max(successful, key=lambda r: r.start_time)


def export_verified_run(run_id: int, target: ReleaseTarget) -> Path:
    """Fetch, VERIFY, then write.

    An earlier version wrote the file and judged it afterwards, which leaves a
    rejected export on disk for someone to find and mistake for a deliverable.
    """
    view = verify(fetch_export(run_id))

    exports = ROOT / target.exports
    exports.mkdir(parents=True, exist_ok=True)
    destination = exports / f"{target.notebook}.html"
    destination.write_text(view.content)
    return destination


def main() -> int:
    if len(sys.argv) < 3:
        raise SystemExit("usage: release.py <job> <tag>   e.g. ingest_job ingest-v1")

    job_key, tag = sys.argv[1], sys.argv[2]

    # A dirty tree, an existing tag, a tag naming the wrong assignment, and a job
    # run that never succeeded are all knowable before anything merges.
    refuse_if_dirty()
    refuse_if_tag_exists(tag)
    target = release_target(resolved_bundle(), job_key)
    refuse_unless_policy_allows(tag, target)
    run = latest_successful_run(target)
    run_id = run.run_id

    # Only now, with every precondition satisfied, does anything change.
    promote_develop_to_main()
    refuse_unless_promoted()

    print(f"exporting run {run_id}")
    exported = export_verified_run(run_id, target)
    print(f"exported {exported.relative_to(ROOT)} ({exported.stat().st_size:,} bytes)")

    # TAG origin/main EXPLICITLY, not HEAD. HEAD is whatever branch this runs
    # from; the release is what was promoted.
    commit = _run("git", "rev-parse", "origin/main").strip()
    _run(
        "git",
        "tag",
        "-a",
        tag,
        commit,
        "-m",
        f"Release {tag}\n\nCommit: {commit}\nJob run: {run_id}",
    )
    _run("git", "push", "origin", tag)
    print(f"tagged {tag} at {commit[:12]} (job run {run_id}) and pushed")
    print(f"\nnext: open {exported.relative_to(ROOT)} to check it, then upload to Canvas")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
