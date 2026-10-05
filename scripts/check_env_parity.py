"""Fail the build when the local interpreter drifts from the deployed target.

THE PROBLEM THIS EXISTS TO PREVENT
Databricks serverless runs Spark Connect. Client and server must agree on the
Python MINOR version or every Python UDF fails with "Python versions in the Spark
Connect client and server are different." The failure appears at UDF execution
time, far from the change that caused it.

WHY A GATE AND NOT A COMMENT
The interpreter version exists in two places by necessity: .python-version drives
the local toolchain, and environment_version drives what the server runs. Two
copies of one fact drift. A comment saying "keep these in sync" documents an
intention; this makes disagreement a red build.

THE CHAIN
  databricks.yml  var.environment_version   authoritative, what deploys
  contracts/environment-versions.json       version -> interpreter mapping
  .python-version                           what the local toolchain installs

THE SEAM, NAMED RATHER THAN HIDDEN
The mapping file is transcribed from published documentation because Databricks
exposes environment version contents as a reference table, not an API. It is the
one link a human maintains. Its review trigger is a new environment version
shipping, not a calendar date.
"""

from __future__ import annotations

import pathlib

from databricks_cli import ResolvedBundle, cli
from environment_versions import CONTRACT, load

ROOT = pathlib.Path(__file__).resolve().parent.parent
PYTHON_VERSION = ROOT / ".python-version"
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


# The fixture target resolves without deployer identity, which is what this
# check wants too: it reads environment_version, a value that does not vary by
# who runs it.
TARGET = "fixture"


def bundle_environment_version() -> str:
    """Read the authoritative environment_version from the resolved bundle.

    THROUGH THE ONE BUNDLE MODEL, databricks_cli.ResolvedBundle, which the policy
    pipeline reads too -- this gate kept a private pair of models for the same
    answer.
    """
    resolved = cli(ResolvedBundle, "bundle", "validate", "-t", TARGET, "--output", "json", cwd=ROOT)
    if "environment_version" not in resolved.variables:
        raise SystemExit(
            "databricks.yml declares no environment_version variable.\n"
            "It is the authoritative target; without it there is nothing to check."
        )
    value = resolved.variables["environment_version"].value
    if value is None:
        raise SystemExit("environment_version resolved to no value")
    return str(value)


def main() -> int:
    env_version = bundle_environment_version()

    contract = load()
    versions = contract.versions
    if env_version not in versions:
        known = ", ".join(sorted(versions, key=int, reverse=True))
        raise SystemExit(
            f"environment version {env_version} is not in {CONTRACT.name}.\n"
            f"known versions: {known}\n"
            "A new environment version is the review trigger for that file:\n"
            f"  {contract.source}"
        )

    expected = versions[env_version].python
    local = PYTHON_VERSION.read_text().strip()

    if local != expected:
        raise SystemExit(
            f"INTERPRETER DRIFT\n"
            f"  bundle environment_version : {env_version}\n"
            f"  that version ships Python  : {expected}\n"
            f"  .python-version says       : {local}\n\n"
            "Spark Connect requires the client and server to share the same "
            "Python minor version.\n"
            f"Fix by writing {expected} to .python-version, then `mise install`."
        )

    print(f"env parity ok: environment_version {env_version} -> Python {expected}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
