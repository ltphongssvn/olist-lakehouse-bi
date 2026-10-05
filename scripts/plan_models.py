# scripts/plan_models.py
"""The plan, its trace and its id ledger: project-plan/v1, plan-trace/v1, id-ledger/v1.

PORTED FROM otsafety-gnn, where these rules held across a plan of two hundred
steps. Three contracts there; one module here, beside nix_models.py and
command_outcome.py, because this repository keeps its models as flat modules.

INTENT ONLY, NEVER STATUS. A step declares the evidence that proves it done --
a merged pull request, a release tag, a file, a task, a named test -- and status
is observed from that evidence. extra is forbidden, so a hand-written status is
refused rather than trusted: every status written by hand drifts from the work.

SEMANTIC RULES A SCHEMA CANNOT STATE: ids unique across steps and decisions,
every reference resolvable, dependencies acyclic, and a reason only for a
dependency the step actually has. A decision not to do something is data too.

TWO ADAPTATIONS, AND ONE THING NOT PORTED:

  release tags   the source required v1.2.3; this repository's release task
                 tags assignment-NN-vN, so a coursework release could never
                 have been proven done under the source's pattern.
  one module     rather than three, to match how models live here.
  NO LOOPS       the source requires every step to name one of its five
                 loops, which is that project's own architecture vocabulary.
                 Requiring it here would mean inventing a loop for each
                 existing step -- authoring a judgement the history never
                 made. Its absence is recorded as a decision in the plan.
"""

from __future__ import annotations

from typing import Annotated, ClassVar, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, model_validator

ID = r"^[0-9A-Z]+\.[0-9A-Z]+$"


class _Strict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


# --- project-plan/v1 ------------------------------------------------------------


class Thread(_Strict):
    """A capability area: toolchain, platform, gates, workflow, coursework, planning."""

    id: str = Field(pattern=r"^[A-Z]$")
    title: str = Field(min_length=1)


class PrEvidence(_Strict):
    """Done when this pull request is merged."""

    kind: Literal["pr"]
    number: PositiveInt


class ReleaseEvidence(_Strict):
    """Done when this release tag exists, in this repository's own convention."""

    kind: Literal["release"]
    tag: str = Field(pattern=r"^[a-z][a-z0-9-]*-v[0-9]+$")


class PathEvidence(_Strict):
    """Done when this file exists on the integration branch, and names the step."""

    kind: Literal["path"]
    path: str = Field(min_length=1)


class TaskEvidence(_Strict):
    """Done when mise.toml declares this task."""

    kind: Literal["task"]
    name: str = Field(min_length=1)


class ProofEvidence(_Strict):
    """Done when this named test passes -- and it fails when the rule is broken.

    THE ONLY KIND THAT IS NOT INSPECTION. A file, a task, a merge and a tag each
    show that something exists; none shows that a rule refuses anything.

    path::name, BECAUSE A FILE CANNOT SAY WHICH TEST.
    """

    kind: Literal["proof"]
    test: str = Field(pattern=r"^[^:]+\.py::[A-Za-z_][A-Za-z0-9_]*$")


Evidence = Annotated[
    PrEvidence | ReleaseEvidence | PathEvidence | TaskEvidence | ProofEvidence,
    Field(discriminator="kind"),
]


class Step(_Strict):
    id: str = Field(pattern=ID)
    title: str = Field(min_length=1)
    thread: str
    depends_on: tuple[str, ...] = ()
    # The branch carrying the work, so an open branch shows a step in progress.
    branch: str | None = Field(default=None, pattern=r"^(feature|release|hotfix)/[a-z0-9-]+$")
    source: str | None = None
    # WHY A DEPENDENCY EXISTS, per dependency. A reason for an edge the step
    # does not have is a note pointing at nothing, and is refused.
    because: dict[str, str] = Field(default_factory=dict)
    # Every item must hold for the step to be done.
    done_when: tuple[Evidence, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _a_reason_names_a_dependency_this_step_has(self) -> Self:
        dangling = sorted(set(self.because) - set(self.depends_on))
        if dangling:
            raise ValueError(f"{self.id} explains {dangling}, which it does not depend on")
        return self


class Decision(_Strict):
    """Something this plan deliberately does not do, or defers, and why."""

    id: str = Field(pattern=ID)
    title: str = Field(min_length=1)
    state: Literal["declined", "deferred", "superseded"]
    reason: str = Field(min_length=1)
    source: str | None = None


class ProjectPlan(_Strict):
    CONTRACT_ID: ClassVar[str] = "project-plan/v1"

    contract: Literal["project-plan/v1"]
    threads: tuple[Thread, ...] = Field(min_length=1)
    steps: tuple[Step, ...] = Field(min_length=1)
    decisions: tuple[Decision, ...] = ()

    @model_validator(mode="after")
    def _references_resolve_and_nothing_cycles(self) -> Self:
        for kind, ids in (
            ("thread", [t.id for t in self.threads]),
            ("step or decision", [s.id for s in self.steps] + [d.id for d in self.decisions]),
        ):
            seen: set[str] = set()
            for item in ids:
                if item in seen:
                    raise ValueError(f"duplicate {kind} id {item}")
                seen.add(item)

        threads = {t.id for t in self.threads}
        steps = {s.id: s for s in self.steps}
        for step in self.steps:
            if step.thread not in threads:
                raise ValueError(f"{step.id} names unknown thread {step.thread}")
            for dependency in step.depends_on:
                if dependency not in steps:
                    raise ValueError(f"{step.id} depends on unknown step {dependency}")

        visiting: set[str] = set()
        finished: set[str] = set()

        def visit(step_id: str, trail: tuple[str, ...]) -> None:
            if step_id in finished:
                return
            if step_id in visiting:
                raise ValueError(f"dependency cycle: {' -> '.join((*trail, step_id))}")
            visiting.add(step_id)
            for dependency in steps[step_id].depends_on:
                visit(dependency, (*trail, step_id))
            visiting.discard(step_id)
            finished.add(step_id)

        for step_id in steps:
            visit(step_id, ())
        return self


# --- plan-trace/v1 --------------------------------------------------------------


class TraceSource(_Strict):
    id: str = Field(pattern=r"^[A-Z][A-Z0-9-]*$")
    title: str = Field(min_length=1)
    # Where it can be found: a commit range, a transcript, a file.
    locator: str = Field(min_length=1)


class Candidate(_Strict):
    """One thing a source asked for: mapped to plan items, or declared not one."""

    source: str = Field(min_length=1)
    # Where in the source -- here, usually a commit sha.
    ref: str = Field(min_length=1)
    # THE SOURCE'S OWN WORDS. For a backfilled step, a commit subject verbatim.
    text: str = Field(min_length=1)
    maps_to: tuple[str, ...] = ()
    not_a_plan_item: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _exactly_one_disposition(self) -> Self:
        if bool(self.maps_to) == (self.not_a_plan_item is not None):
            raise ValueError(
                f"{self.source} {self.ref}: needs exactly one of maps_to or not_a_plan_item"
            )
        return self


class PlanTrace(_Strict):
    CONTRACT_ID: ClassVar[str] = "plan-trace/v1"

    contract: Literal["plan-trace/v1"]
    sources: tuple[TraceSource, ...] = Field(min_length=1)
    candidates: tuple[Candidate, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _sources_resolve(self) -> Self:
        ids = [s.id for s in self.sources]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate source id")
        for candidate in self.candidates:
            if candidate.source not in set(ids):
                raise ValueError(f"{candidate.ref} names unknown source {candidate.source}")
        return self


def untraced(trace: PlanTrace, plan: ProjectPlan) -> list[str]:
    """Every gap between the trace and the plan, in BOTH directions.

    A candidate pointing at nothing means the plan is missing something; an item
    no candidate points at means the plan holds something no source asked for.
    """
    items = {s.id for s in plan.steps} | {d.id for d in plan.decisions}
    problems: list[str] = []
    targeted: set[str] = set()
    for candidate in trace.candidates:
        for target in candidate.maps_to:
            targeted.add(target)
            if target not in items:
                problems.append(
                    f"{candidate.source} {candidate.ref} maps to {target}, which is not in the plan"
                )
    problems += [f"{item} is traced to no source" for item in sorted(items - targeted)]
    return problems


# --- id-ledger/v1 ---------------------------------------------------------------


class IssuedId(_Strict):
    """One identifier, issued once. A retired id stays, so none is ever reused."""

    id: str = Field(pattern=r"^[A-Z0-9]+\.[A-Za-z0-9]+$")
    first_title: str = Field(min_length=1)
    retired: bool = False


class IdLedger(_Strict):
    """context/plan-ids.yaml: append-only.

    NAMED plan-ids, NOT "the ledger": nix_ledger.py already holds a hash-chained
    ledger of Nix evidence here, and one word meaning two things is a defect.
    """

    CONTRACT_ID: ClassVar[str] = "id-ledger/v1"

    contract: Literal["id-ledger/v1"] = "id-ledger/v1"
    issued: tuple[IssuedId, ...] = Field(min_length=1)


# --- branch-commits/v1 ----------------------------------------------------------


class CommitSteps(_Strict):
    """One commit, and the plan steps its Plan-Step trailers name, as git parsed them."""

    sha: str = Field(min_length=1)
    subject: str
    # GitHub writes merges; the pull request's own commits carry the steps.
    merge: bool
    steps: tuple[str, ...]


class BranchCommits(_Strict):
    """branch-commits/v1: a branch's commits, and the ids the ledger issued and retired."""

    CONTRACT_ID: ClassVar[str] = "branch-commits/v1"

    contract: Literal["branch-commits/v1"] = "branch-commits/v1"
    base: str = Field(min_length=1)
    commits: tuple[CommitSteps, ...]
    issued: tuple[str, ...]
    retired: tuple[str, ...]


# --- requirement-matrix/v1 -------------------------------------------------------


class Requirement(_Strict):
    """One row: a step or decision, its decided state, and what traces it."""

    id: str = Field(pattern=ID)
    title: str = Field(min_length=1)
    kind: Literal["step", "decision"]
    # A decision has no state: it is deliberately not done.
    state: Literal["done", "unknown", "in_progress", "ready", "blocked"] | None
    # source:ref for each trace candidate pointing here.
    justified_by: tuple[str, ...]
    # Short shas of the commits whose trailers name this id.
    referenced_by: tuple[str, ...]


class TracedCommit(_Strict):
    """One commit on the ref, and whether anything authorises it."""

    sha: str = Field(min_length=1)
    subject: str
    merge: bool
    steps: tuple[str, ...]
    # Cited verbatim by the trace's history, as a backfilled commit is.
    cited: bool


class RequirementMatrix(_Strict):
    """requirement-matrix/v1: derived from the plan, trace, status and commits -- never by hand."""

    CONTRACT_ID: ClassVar[str] = "requirement-matrix/v1"

    contract: Literal["requirement-matrix/v1"] = "requirement-matrix/v1"
    ref: str = Field(min_length=1)
    requirements: tuple[Requirement, ...]
    commits: tuple[TracedCommit, ...]


# --- plan-facts/v1 and plan-status/v1 ---------------------------------------
#
# ONE HOME FOR EVERY PLAN CONTRACT. These lived in plan_status.py, so the renderer
# imported the observer to read a status and the observer imported the renderer
# to print one -- a cycle the module-graph test refused.


Kind = Literal["pr", "release", "path", "task", "proof"]
State = Literal["done", "unknown", "in_progress", "ready", "blocked"]


class Facts(_Strict):
    """What was observed on one ref, and which kinds of evidence could not be seen."""

    ref: str = Field(min_length=1)
    paths: tuple[str, ...]
    tasks: tuple[str, ...]
    merged_prs: tuple[int, ...]
    tags: tuple[str, ...]
    # "path::name" for every module-level test function each test file defines.
    proofs: tuple[str, ...]
    # Branches holding commits beyond the ref -- not merely existing.
    branches_with_work: tuple[str, ...]
    blind: tuple[Kind, ...] = ()


class PlanFacts(_Strict):
    """plan-facts/v1: the plan's own steps, and what was observed about their evidence."""

    CONTRACT_ID: ClassVar[str] = "plan-facts/v1"

    contract: Literal["plan-facts/v1"] = "plan-facts/v1"
    facts: Facts
    steps: tuple[Step, ...] = Field(min_length=1)


class StepStatus(_Strict):
    state: State
    unmet: tuple[str, ...] = ()
    blocked_by: tuple[str, ...] = ()


class PlanStatus(_Strict):
    """plan-status/v1: the policy's decision, validated on its way back from OPA."""

    CONTRACT_ID: ClassVar[str] = "plan-status/v1"

    contract: Literal["plan-status/v1"] = "plan-status/v1"
    ref: str = Field(min_length=1)
    steps: dict[str, StepStatus]
