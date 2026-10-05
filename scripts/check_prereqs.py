"""Verify the things the bundle depends on but cannot own.

WHY THESE ARE NOT BUNDLE RESOURCES
  the catalog        Catalogs ARE a bundle resource type, but a declared catalog
                     is always CREATED via POST /catalogs, and
                     `bundle deployment bind` cannot adopt UC catalogs
                     (databricks/cli#4842). This one already exists, so declaring
                     it guarantees a create-conflict with no way out.
  the reader group   Groups are not a bundle resource type at all. Provisioned by
                     scripts/bootstrap_groups.py; see that file for why it is not
                     Terraform on this tier.

WHY CHECK RATHER THAN ASSUME
An unmanaged dependency that nothing verifies is an assumption wearing a
comment. When one of these is missing, `bundle deploy` fails with an API error
that names the symptom, not the cause. This fails first and says what to run.
"""

from __future__ import annotations

import sys

from pydantic import BaseModel, ConfigDict

from databricks_cli import Catalogs, ScimList, cli
from project_identity import ProjectIdentity, load

# NO PROFILE HANDLING HERE, DELIBERATELY.
#
# The CLI resolves credentials in a documented order -- SDK config, then
# ENVIRONMENT VARIABLES, then the .databrickscfg DEFAULT profile -- stopping at
# the first success, and environment variables take precedence over the profile.
#
# That is exactly the branch this file used to implement in Python:
#   CI       has DATABRICKS_CLIENT_ID and _SECRET -> found at step 2
#   a laptop has neither -> falls through to the DEFAULT profile
#
# Earlier versions passed "-p cscie103" and later branched on env vars to decide
# whether to. Both were code compensating for one original choice: authenticating
# into a NAMED profile instead of DEFAULT. Removing that removes the branch, the
# heuristic, and the whole class of "which environment am I in" bug.


class Required(BaseModel):
    """The two prerequisites the bundle cannot create, derived from the declaration."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    catalog: str
    group: str


def required(identity: ProjectIdentity) -> Required:
    """The catalog and the account group this project needs to exist first (D.52)."""
    return Required(catalog=identity.catalog, group=identity.reader_group)


def main() -> int:
    failures: list[str] = []
    needed = required(load())

    catalogs = cli(Catalogs, "catalogs", "list", "--output", "json")
    names = {c.name for c in catalogs.root}
    if needed.catalog in names:
        print(f"ok      catalog {needed.catalog}")
    else:
        failures.append(
            f"MISSING catalog {needed.catalog}\n"
            f"  visible catalogs: {', '.join(sorted(n for n in names if n))}\n"
            "  The bundle cannot create it. Create it once, deliberately:\n"
            f"    databricks catalogs create {needed.catalog}"
        )

    groups = cli(ScimList, "api", "get", "/api/2.0/account/scim/v2/Groups")
    account_groups = {g.display_name for g in groups.resources}
    if needed.group in account_groups:
        print(f"ok      account group {needed.group}")
    else:
        failures.append(
            f"MISSING account group {needed.group}\n"
            "  Grants target it, and workspace-local groups cannot hold UC\n"
            "  privileges, so this must be an ACCOUNT group.\n"
            "  Create it:\n"
            "    mise run bootstrap:identity"
        )

    if failures:
        print("\n" + "\n\n".join(failures), file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
