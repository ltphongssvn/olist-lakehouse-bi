"""The Databricks CLI as a boundary: every response validated by what is read from it.

ONE BOUNDARY, WHERE THERE WERE TWO. bootstrap_identity.py and check_prereqs.py
held byte-identical copies of a helper returning the CLI's JSON as Any, and
release.py parsed the same CLI's output raw. Untrusted input with no model, in
three places.

THE CLI OWNS THESE SCHEMAS, so each model declares only the fields this
repository reads and ignores the rest. The fields are the ones the scripts
already relied on, through two releases and a provisioned workspace.

AN UNEXPECTED SHAPE REFUSES, NAMING THE COMMAND. The old helpers turned an
unreadable answer into an empty result, so check:prereqs could report a catalog
missing when the truth was a response it could not read.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, JsonValue, RootModel, ValidationError


class _Vendor(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore", populate_by_name=True)


class ScimResource(_Vendor):
    id: str | None = None
    display_name: str | None = Field(default=None, alias="displayName")
    application_id: str | None = Field(default=None, alias="applicationId")


class ScimList(_Vendor):
    resources: tuple[ScimResource, ...] = Field(default=(), alias="Resources")


class GroupMember(_Vendor):
    display: str | None = None


class GroupDetail(_Vendor):
    members: tuple[GroupMember, ...] = ()


class PrivilegeAssignment(_Vendor):
    principal: str
    privileges: tuple[str, ...] = ()


class CatalogPermissions(_Vendor):
    privilege_assignments: tuple[PrivilegeAssignment, ...] = ()


class Catalog(_Vendor):
    name: str | None = None


class Catalogs(RootModel[tuple[Catalog, ...]]):
    """catalogs list answers with a top-level array."""


class JobSettings(_Vendor):
    name: str = ""


class Job(_Vendor):
    job_id: int
    settings: JobSettings = JobSettings()


class Jobs(RootModel[tuple[Job, ...]]):
    """jobs list answers with a top-level array."""


class RunState(_Vendor):
    result_state: str | None = None


class Run(_Vendor):
    run_id: int
    start_time: int = 0
    state: RunState = RunState()


class Runs(RootModel[tuple[Run, ...]]):
    """jobs list-runs answers with a top-level array."""


class _Open(BaseModel):
    """A vendor document whose unread fields are KEPT, because a policy reads them."""

    model_config = ConfigDict(frozen=True, extra="allow")


class BundleVariable(_Open):
    value: str | int | float | bool | None = None


class BundleWorkspace(_Open):
    host: str | None = None


class ResolvedBundle(_Open):
    """`bundle validate --output json`: what the policies and the parity gate read.

    OPEN WHERE THE VENDOR IS OPEN. It declares the shape the bundle policy and
    check:env-parity depend on -- workspace, resources as objects of objects,
    variables -- and keeps every other field, so a policy reading one no script
    names still sees it.
    """

    bundle: dict[str, JsonValue] = Field(default_factory=dict)
    workspace: BundleWorkspace = Field(default_factory=BundleWorkspace)
    resources: dict[str, dict[str, dict[str, JsonValue]]] = Field(default_factory=dict)
    variables: dict[str, BundleVariable] = Field(default_factory=dict)


def _invoke(args: tuple[str, ...], cwd: Path | None = None) -> str:
    result = subprocess.run(
        ["databricks", *args], capture_output=True, text=True, check=False, cwd=cwd
    )
    if result.returncode != 0:
        print(result.stderr.strip(), file=sys.stderr)
        raise SystemExit(f"databricks {' '.join(args)} failed")
    return result.stdout


def cli[M: BaseModel](model: type[M], *args: str, cwd: Path | None = None) -> M:
    """Call the CLI and validate its answer as `model`, or refuse naming the call."""
    output = _invoke(args, cwd)
    try:
        return model.model_validate_json(output)
    except ValidationError as error:
        raise SystemExit(
            f"databricks {' '.join(args)} answered in a shape this script cannot read: {error}"
        ) from error


def call(*args: str) -> None:
    """A call whose answer is not read: a POST or PATCH that changes state."""
    _invoke(args)
