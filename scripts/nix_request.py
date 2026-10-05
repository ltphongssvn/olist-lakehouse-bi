"""What this run was ASKED to do, as data.

WHY THIS IS NOT AN `EnsureNixContract` COMMAND OBJECT
The 2026 answer for exposing a tool to an agent is a CLI that emits typed JSON,
which this already is: "the agent could just run the CLI directly -- the MCP
server was pure overhead. The agent already knows how to read --help, parse
output, and handle errors." Wrapping the call in an intent object adds
indirection the caller does not want.

THE REAL GAP WAS THAT THE INPUTS WERE UNDECLARED
Three environment variables steered this program and none of them was
validated, documented, or recorded. The output described what was OBSERVED and
what was JUDGED, and never what was REQUESTED.

That is not academic. NIX_CONTRACT_SEARCH_DIRS narrows where nix is looked for
-- a test seam -- and a report produced with it set says "nix not found in any
searched directory" while concealing that the search was deliberately narrowed.
The evidence hid the one fact needed to interpret it.

Recording the request makes a report self-describing: a reader can tell a
genuine absence from a narrowed search without access to the shell that ran it.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = ["ContractRequest"]


class ContractRequest(BaseSettings):
    """The invocation, validated once and carried into the output.

    A FROZEN SNAPSHOT. A request that can be edited after the fact is not a
    record of what was asked.
    """

    model_config = SettingsConfigDict(
        env_prefix="NIX_CONTRACT_",
        frozen=True,
        # extra="ignore" rather than "forbid": the process environment holds
        # hundreds of unrelated variables, and forbidding them would fail on
        # every machine. The prefix already scopes what is read.
        extra="ignore",
    )

    search_dirs: str = Field(
        default="",
        description="Colon-separated override for where nix is looked for; NARROWS only",
    )
    evidence: Path | None = Field(
        default=None, description="Where to write the record-and-replay bundle"
    )
    ledger: Path | None = Field(
        default=None, description="Where to append the hash-chained run record"
    )

    @property
    def search_was_overridden(self) -> bool:
        """THE FACT A REPORT MUST NOT HIDE.

        With the search narrowed, "nix not found in any searched directory" is
        true and misleading at once. A reader needs to know the search was
        redirected before believing the absence.
        """
        return bool(self.search_dirs)

    def as_record(self) -> dict[str, object]:
        """The request, for the output envelope.

        Paths are stringified rather than omitted: WHERE evidence was written
        is part of what was asked, and a reader chasing a bundle needs it.
        """
        return {
            "search_overridden": self.search_was_overridden,
            "search_dirs": self.search_dirs,
            "evidence_path": None if self.evidence is None else str(self.evidence),
            "ledger_path": None if self.ledger is None else str(self.ledger),
        }
