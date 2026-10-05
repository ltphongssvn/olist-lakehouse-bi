"""Provision the account identities the bundle depends on. Idempotent.

Groups the bundle grants to, and the service principal CI authenticates as.
Both are identity, so they share one mechanism rather than two.

WHY THIS IS NOT TERRAFORM
The industry split is settled: Terraform owns platform infrastructure that does
not change run-to-run -- workspaces, account-level UC objects, and IDENTITY,
including groups. Bundles own the deployable workload. Group provisioning
belongs in the Terraform layer, and on a paid tier that is where it should live.

It cannot live there here. The Terraform provider reaches account-level identity
through a `databricks.account` provider aimed at the ACCOUNT host, and Free
Edition documents no access to the account console or account-level APIs. The
endpoint this script uses is a WORKSPACE-domain route
(/api/2.0/account/scim/v2/) that workspace admins and group managers may call --
reachable here, verified 2026-09-02.

That places this squarely in the third layer of the standard governance pattern:
Terraform for the platform foundation, Bundles for Databricks-native resources,
and imperative automation for the gaps where declarative configuration cannot
reach. The alternative -- forcing identity into the bundle because it is
technically possible -- is the named anti-pattern.

MIGRATION TRIGGER: if this account moves to a paid tier, delete this script and
move the group into Terraform. It exists because of a tier limitation, not
because a script is the right home for identity.

WHY A PURPOSE-NAMED GROUP RATHER THAN `account users`
`account users` exists and would work, but it means every account user. UC best
practice is least privilege through purpose-named groups. `users` and `admins`
are workspace-local and cannot hold UC privileges at all -- the API reports that
attempt as PRINCIPAL_DOES_NOT_EXIST, which reads as a missing group but is a
category error.
"""

from __future__ import annotations

import json

from pydantic import BaseModel, ConfigDict

from databricks_cli import CatalogPermissions, GroupDetail, ScimList, call, cli
from project_identity import ProjectIdentity, load

GROUPS_ENDPOINT = "/api/2.0/account/scim/v2/Groups"
SPS_ENDPOINT = "/api/2.0/account/scim/v2/ServicePrincipals"
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


# The reader group is named in contracts/project-identity.toml; desired() derives it.
# WHY A SERVICE PRINCIPAL AT ALL
# CI cannot use OAuth user-to-machine: it is browser-based and interactive. The
# alternative is a personal access token in a GitHub secret -- a long-lived
# bearer credential, which is the exact exposure this repo avoided when the CLI
# offered plaintext credential storage.
#
# It also closes a gap recorded in databricks.yml: the prod target currently runs
# as a human identity. UC guidance is explicit that jobs writing to production
# should run as a service principal, because running them as a user risks
# accidental overwrites and ties job ownership to an individual.
# The principal is named in contracts/project-identity.toml; desired() derives it.

# WORKSPACE ASSIGNMENT AND GROUP MEMBERSHIP, RECONCILED HERE BECAUSE THEY WERE
# ONCE DONE BY HAND.
#
# An account-level service principal can exist and still be unable to log in: it
# must also be assigned to the workspace, with an entitlement. And it holds no UC
# privileges until it joins a group that does. Both steps were originally run as
# one-off `databricks api post/patch` commands, which meant a workspace rebuilt
# from this script would produce a principal that authenticates nowhere and can
# read nothing -- coverage claimed but not delivered.
#
# MINIMUM ENTITLEMENT, DELIBERATELY: workspace-access only. Not
# allow-cluster-create, not databricks-sql-access. CI validates and deploys
# bundles; it does not need compute. An entitlement granted just in case is one
# nobody removes later.
WORKSPACE_SPS_ENDPOINT = "/api/2.0/preview/scim/v2/ServicePrincipals"
WORKSPACE_ENTITLEMENTS = ["workspace-access"]

# Group membership rather than direct grants: UC guidance is to use groups and
# avoid granting individual principals, so a second CI identity joins the group
# instead of accumulating its own privileges.
# desired() derives the membership: the CI principal joins the reader group.

# Catalog-level grants, reconciled here because the bundle cannot own them: a
# declared catalog is always CREATED via POST /catalogs and cannot be adopted
# (databricks/cli#4842), so the catalog stays a prerequisite.
#
# GRANTED TO THE GROUP, NOT TO THE SERVICE PRINCIPAL. UC guidance is to use
# groups and avoid direct grants to individual principals; a second CI identity
# then inherits this by joining the group instead of accumulating its own grant.
#
# USE_CATALOG is required to reach anything inside. BROWSE allows listing objects
# without reading data, which is what check:prereqs and bundle validate need.
# Deliberately NOT ALL_PRIVILEGES or CREATE_SCHEMA: this identity reads and
# validates, and the schema grants it already inherits cover the rest.
CATALOG_PRIVILEGES = ("USE_CATALOG", "BROWSE")


class Desired(BaseModel):
    """Every identity relation this script reconciles, derived from one declaration."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    groups: tuple[str, ...]
    service_principals: tuple[str, ...]
    memberships: dict[str, tuple[str, ...]]
    catalog_grants: dict[str, dict[str, tuple[str, ...]]]


def desired(identity: ProjectIdentity) -> Desired:
    """The groups, principals, memberships and grants this project needs (D.52)."""
    return Desired(
        groups=(identity.reader_group,),
        service_principals=(identity.ci_principal,),
        memberships={identity.reader_group: (identity.ci_principal,)},
        catalog_grants={identity.catalog: {identity.reader_group: CATALOG_PRIVILEGES}},
    )


def _existing(endpoint: str) -> dict[str, str]:
    listed = cli(ScimList, "api", "get", endpoint)
    return {r.display_name: r.id for r in listed.resources if r.display_name and r.id}


def _reconcile(endpoint: str, schema: str, names: list[str], label: str) -> None:
    present = _existing(endpoint)
    for name in names:
        if name in present:
            print(f"ok      {label} {name} (id {present[name]})")
            continue
        call(
            "api",
            "post",
            endpoint,
            "--json",
            json.dumps({"schemas": [schema], "displayName": name}),
        )
        print(f"created {label} {name}")


def _reconcile_workspace_assignment(principals: tuple[str, ...]) -> None:
    """Assign account service principals to the workspace so they can log in."""
    present = _existing(WORKSPACE_SPS_ENDPOINT)
    account = _existing(SPS_ENDPOINT)
    detail = cli(ScimList, "api", "get", SPS_ENDPOINT)

    app_ids = {
        r.display_name: r.application_id
        for r in detail.resources
        if r.display_name and r.application_id
    }

    for name in principals:
        if name in present:
            print(f"ok      workspace assignment {name}")
            continue
        if name not in account:
            print(f"SKIP    workspace assignment {name}: not an account principal")
            continue
        # POST the applicationId, NOT the SCIM id. The workspace endpoint links to
        # the account identity by application id; posting the SCIM id creates a
        # SECOND, unlinked principal -- a failure worth avoiding rather than
        # debugging later.
        call(
            "api",
            "post",
            WORKSPACE_SPS_ENDPOINT,
            "--json",
            json.dumps(
                {
                    "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ServicePrincipal"],
                    "applicationId": app_ids[name],
                    "displayName": name,
                    "entitlements": [{"value": e} for e in WORKSPACE_ENTITLEMENTS],
                }
            ),
        )
        print(f"created workspace assignment {name}")


def _reconcile_group_memberships(memberships: dict[str, tuple[str, ...]]) -> None:
    groups = _existing(GROUPS_ENDPOINT)
    principals = _existing(SPS_ENDPOINT)

    for group, members in memberships.items():
        if group not in groups:
            print(f"SKIP    membership {group}: group does not exist")
            continue
        current = cli(GroupDetail, "api", "get", f"{GROUPS_ENDPOINT}/{groups[group]}")
        held = {m.display for m in current.members}

        for member in members:
            if member in held:
                print(f"ok      membership {group} <- {member}")
                continue
            if member not in principals:
                print(f"SKIP    membership {group} <- {member}: principal missing")
                continue
            call(
                "api",
                "patch",
                f"{GROUPS_ENDPOINT}/{groups[group]}",
                "--json",
                json.dumps(
                    {
                        "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
                        "Operations": [
                            {
                                "op": "add",
                                "path": "members",
                                "value": [{"value": principals[member]}],
                            }
                        ],
                    }
                ),
            )
            print(f"added   membership {group} <- {member}")


def _reconcile_catalog_grants(grants: dict[str, dict[str, tuple[str, ...]]]) -> None:
    for catalog, wanted in grants.items():
        endpoint = f"/api/2.1/unity-catalog/permissions/catalog/{catalog}"
        current = cli(CatalogPermissions, "api", "get", endpoint)
        held = {a.principal: set(a.privileges) for a in current.privilege_assignments}
        for principal, privileges in wanted.items():
            missing = sorted(set(privileges) - held.get(principal, set()))
            if not missing:
                print(f"ok      grant {catalog} -> {principal}")
                continue
            call(
                "api",
                "patch",
                endpoint,
                "--json",
                json.dumps({"changes": [{"principal": principal, "add": missing}]}),
            )
            print(f"granted {catalog} -> {principal}: {', '.join(missing)}")


def main() -> int:
    # READ ONCE, AT THE BOUNDARY: every name below derives from the declaration (D.52).
    wanted = desired(load())
    _reconcile(
        GROUPS_ENDPOINT,
        "urn:ietf:params:scim:schemas:core:2.0:Group",
        list(wanted.groups),
        "group",
    )
    _reconcile(
        SPS_ENDPOINT,
        "urn:ietf:params:scim:schemas:core:2.0:ServicePrincipal",
        list(wanted.service_principals),
        "service principal",
    )
    _reconcile_workspace_assignment(wanted.service_principals)
    _reconcile_group_memberships(wanted.memberships)
    _reconcile_catalog_grants(wanted.catalog_grants)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


# --- OAuth secrets are DELIBERATELY not created here -------------------------
#
# WHY NOT, GIVEN EVERYTHING ELSE IN THIS FILE IS AUTOMATED
# Databricks returns an OAuth client secret exactly ONCE, in the response body.
# Anything that prints it puts it in terminal scrollback, in shell history, and
# in any log capturing that session. That happened during this project: a secret
# was generated with a bare `databricks api post`, rendered to the terminal, and
# had to be revoked and reissued immediately.
#
# The fix is not "remember to be careful". It is that a secret must never exist
# anywhere a human or a log can see it -- so it is piped from the API straight
# into the secret store, never through a variable, a file, or a screen:
#
#   databricks api post \
#     /api/2.0/accounts/servicePrincipals/<sp-id>/credentials/secrets \
#     -p cscie103 --json '{"lifetime":"7776000s"}' \
#     | python3 -c 'import sys,json; print(json.load(sys.stdin)["secret"], end="")' \
#     | gh secret set DATABRICKS_CLIENT_SECRET
#
# That is a one-time, human-supervised act with a destination, not something a
# reconciliation script should perform. Automating it here would mean this script
# either prints a secret or silently rotates a live credential -- both worse than
# leaving it out.
#
# LIFETIME IS BOUNDED AT 90 DAYS ON PURPOSE. A credential with no expiry is one
# nobody ever rotates; an expiring one forces the rotation path to stay working.
#
# WHAT IS AND IS NOT SECRET
#   applicationId  NOT secret. It is the OAuth client ID and belongs in the repo
#                  and in workflow files, exactly like a username.
#   client secret  Secret. Exists only inside GitHub Actions secrets. Never in
#                  the repo, never in a comment, never in a commit message.
