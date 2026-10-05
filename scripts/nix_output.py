"""The output envelope, as a type rather than a hand-built dict.

WHY THIS EXISTS
main() assembled a dict literal, which meant the output shape existed nowhere as
a declaration. Three consequences, all of which happened:

  No schema could be exported, because there was no type to generate one from.
  The key set had to be maintained BY HAND in a test, and was updated three
  separate times as fields were added.
  A typo in a key name would have produced a silently wrong document -- valid
  JSON, wrong contract.

Declaring the envelope fixes all three at the source. extra="forbid" "rejects
any new/renamed/removed fields or wrong types", the test validates against the
model rather than a remembered list, and model_json_schema() exports the
contract for consumers.

THE TYPE_CHECKING GUARD IS GONE, AND ITS ABSENCE IS THE POINT
This module imported nix_contract under `if TYPE_CHECKING` to get the types for
build_output without closing an import cycle. That does not remove a cycle, it
hides one -- and the guidance is explicit that hiding an import from the runtime
while exposing it to the type checker is the pattern to avoid, not adopt.

The models moved to nix_models, a leaf both sides import and neither imports
back. The dependency graph is now acyclic by construction rather than by a
comment asking the next reader not to tidy an import.

WHY THE SCHEMA IS COMMITTED RATHER THAN GENERATED ON DEMAND
Regenerating from the model under a different pydantic version can change the
output: "a pydantic point release could subtly change the output and drift would
return through the back door". The generated schema is committed, and a test
fails if the model no longer produces it -- so the bytes change deliberately.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from nix_models import ContractReport, NixInstallation
from nix_observability import ProbeRecord, RunMetadata
from nix_remediation import ContractProblem

__all__ = [
    "ContractOutput",
    "build_output",
]


class ContractOutput(BaseModel):
    """What the contract prints when it could observe the machine.

    FROZEN AND extra="forbid": a field added here is a deliberate contract
    change that fails the schema test until the committed schema is regenerated.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = Field(description="Shape of this document")
    policy_version: str = Field(description="Version of the RULES, not the shape")
    outcome: str = Field(description="satisfied | policy_denied")
    run: RunMetadata
    request: dict[str, object] = Field(
        default_factory=dict,
        description="What this run was ASKED to do, distinct from what it found",
    )
    """WITHOUT THIS, A REPORT CANNOT BE INTERPRETED.

    NIX_CONTRACT_SEARCH_DIRS narrows where nix is looked for. A report produced
    with it set says "nix not found in any searched directory" -- true, and
    misleading, because the search was redirected. The evidence hid the one fact
    a reader needs in order to judge it.

    The document described what was observed and what was judged. This is the
    third thing: what was requested.
    """
    satisfied: bool
    nix_present: bool = Field(
        description="Whether a nix binary was found; replaces `evaluable`",
    )
    """`evaluable` BECAME A LIE AND HAD TO GO.

    It meant "the machine could be observed at all", which was true when
    observe() raised on an absent Nix. Observation now ALWAYS succeeds --
    absence is a result -- so build_output hardcoded it to True, and two tests
    that guarded on it silently stopped skipping and failed in CI.

    A field whose value is a constant is not a fact. This reports the thing a
    consumer actually needs to branch on: whether there is a Nix to describe.
    """

    binary: str
    from_store: bool
    version: str
    semantic_version: str
    system: str = Field(
        default="",
        description="Nix system double, e.g. aarch64-darwin -- the KIND of machine, not which one",
    )
    distribution: str

    uninstallable: bool
    receipt_valid: bool
    uninstaller_present: bool

    can_evaluate: bool
    can_evaluate_a_flake: bool
    project_flake_checked: bool = Field(
        default=False,
        description="Whether THIS repository's flake was evaluated, distinct from passing",
    )
    store_verify_status: int
    untrusted_signature: bool

    probes: tuple[ProbeRecord, ...]
    # TYPED, not tuple[dict[str, Any], ...]. Using Any here would have defeated
    # the point: the exported schema would describe these as arbitrary objects,
    # so a consumer could not validate the very fields it must branch on.
    problems: tuple[ContractProblem, ...]
    warnings: tuple[ContractProblem, ...]
    verdicts: dict[str, str] = Field(
        default_factory=dict,
        description="pass or fail for every declared rule, so a passing rule is visible",
    )


def build_output(
    *,
    installation: NixInstallation,
    report: ContractReport,
    outcome: str,
    run: RunMetadata,
    schema_version: str,
    policy_version: str,
    request: dict[str, object] | None = None,
) -> ContractOutput:
    """THE SINGLE MAPPING FUNCTION between the model and the wire.

    The guidance is explicit: "prefer an explicit response DTO and a single
    mapping function". Previously this was a dict literal in main(), so the
    mapping existed only as the act of writing it out -- which is why the wire
    names drifted from the field names with nothing to notice.

    RENAMING HERE IS DELIBERATE AND FINE. `uninstallable` reads better on the
    wire than `is_uninstallable`, and `distribution: "determinate"` is more
    useful to a consumer than `is_determinate: true` because it leaves room for
    a third distribution without a boolean lying about it. A boundary "needs a
    data shape different from the domain model"; what it must not have is an
    UNDECLARED one.
    """
    return ContractOutput(
        schema_version=schema_version,
        policy_version=policy_version,
        outcome=outcome,
        run=run,
        request=request or {},
        satisfied=report.satisfied,
        nix_present=installation.nix_present,
        binary=str(installation.binary),
        from_store=installation.is_from_the_store,
        version=installation.version,
        system=installation.system,
        semantic_version=".".join(str(part) for part in installation.semantic_version),
        distribution=("determinate" if installation.is_determinate else "upstream"),
        uninstallable=installation.is_uninstallable,
        receipt_valid=installation.receipt_is_valid,
        uninstaller_present=installation.uninstaller_exists,
        can_evaluate=installation.can_evaluate,
        can_evaluate_a_flake=installation.can_evaluate_a_flake,
        project_flake_checked=installation.project_flake_checked,
        store_verify_status=installation.store_verify_status,
        untrusted_signature=installation.is_untrusted,
        probes=installation.probes,
        problems=report.problems,
        warnings=report.warnings,
        verdicts=report.verdicts,
    )
