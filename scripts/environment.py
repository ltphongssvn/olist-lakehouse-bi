"""The process environment as a validated, frozen snapshot.

WHY THIS EXISTS
Every script here depends on environment variables that nothing declared.
DATABRICKS_HOST and the M2M credentials decide which workspace a command
reaches. GIT_DIR silently redirects git calls made from a hook, overriding both
`-C` and cwd. BUNDLE_VAR_owner_email decides whether a deploy runs at all.

None of that was written down. It was read from os.environ where it happened to
be needed, differently in each file, and the union of those reads existed only
in whoever last debugged it. That is ambient state: invisible, unvalidated, and
different on every machine.

It cost four CI runs. A bundle resolved differently on a runner than on a
laptop, and nothing in the code said which variables governed the difference, so
each fix addressed the shape of the symptom rather than the boundary.

WHAT A SNAPSHOT BUYS OVER os.environ
  DECLARED    the variables this project depends on are enumerable, in one
              place, with their meaning attached.
  VALIDATED   a malformed host fails at construction naming the field, not at
              the API call that could not parse it.
  FROZEN      reading os.environ twice can give two answers; a frozen model
              cannot drift mid-run.
  INSPECTABLE it can be printed, logged and diffed -- exactly what was missing
              when local and CI disagreed.

WHY extra="ignore" AND NOT "forbid"
`forbid` looks like the fail-closed choice and does not do the job. With a field
POSTGRES_USER declared, pydantic-settings does NOT report a stray
POSTGRES_USER_2 as extra -- it is silently missed (pydantic-settings#384). And
env_prefix is ignored when an unprefixed variable matches (#437), so prefix
scoping is not reliable either. Meanwhile `forbid` on an environment source
rejects every unrelated variable in the process, which is why teams that enabled
it reverted after developers' local files started failing validation.

Typo detection is therefore an explicit check, below, rather than a setting that
reads stricter than it behaves.
"""

from __future__ import annotations

import os

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Git's repository-routing variables OVERRIDE `-C` and cwd, and git exports them
# into every hook. Recorded rather than merely stripped, so a report can say WHY
# a git call had to be isolated.
GIT_ROUTING_VARIABLES = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR",
)

# Namespaces this project owns. A variable matching one of these prefixes that is
# not a declared field is a typo, and a typo is indistinguishable from an unset
# variable at the point of use.
OWNED_PREFIXES = ("DATABRICKS_", "BUNDLE_VAR_")


class Environment(BaseSettings):
    """The ambient state this project depends on, snapshotted once."""

    model_config = SettingsConfigDict(
        case_sensitive=True,
        extra="ignore",
        frozen=True,
    )

    # Absent on a laptop, present in CI. Their presence is what distinguishes the
    # two, and reading that from a model beats inferring it per script.
    databricks_host: str | None = Field(default=None, alias="DATABRICKS_HOST")
    databricks_client_id: str | None = Field(default=None, alias="DATABRICKS_CLIENT_ID")
    databricks_client_secret: SecretStr | None = Field(
        default=None, alias="DATABRICKS_CLIENT_SECRET"
    )
    databricks_auth_type: str | None = Field(default=None, alias="DATABRICKS_AUTH_TYPE")
    databricks_config_profile: str | None = Field(default=None, alias="DATABRICKS_CONFIG_PROFILE")

    bundle_owner_email: str | None = Field(default=None, alias="BUNDLE_VAR_owner_email")

    ci: bool = Field(default=False, alias="CI")

    @field_validator("databricks_host")
    @classmethod
    def host_must_be_https(cls, value: str | None) -> str | None:
        """A bare hostname or an http URL fails later and less clearly."""
        if value is None:
            return None
        if not value.startswith("https://"):
            raise ValueError(f"DATABRICKS_HOST must start with https://, got {value!r}")
        return value.rstrip("/")

    @property
    def has_unified_auth(self) -> bool:
        """Whether machine-to-machine credentials are present.

        THE DISTINCTION THAT MATTERED, PREVIOUSLY GUESSED AT. Scripts branched on
        DATABRICKS_HOST alone, which says WHERE the workspace is and nothing
        about proving identity -- so a laptop with a host and no credentials took
        the CI path and failed with "cannot configure default credentials".
        Credentials decide it, not the host.
        """
        return self.databricks_client_id is not None and self.databricks_client_secret is not None

    @property
    def git_routing_overrides(self) -> dict[str, str]:
        """Repository-routing variables currently set, if any.

        Non-empty means git calls WILL be redirected unless the environment is
        scrubbed -- the case inside every git hook.
        """
        return {name: os.environ[name] for name in GIT_ROUTING_VARIABLES if name in os.environ}


def declared_aliases() -> set[str]:
    """The environment variable names this model actually reads."""
    return {field.alias for field in Environment.model_fields.values() if field.alias is not None}


def unknown_owned_variables() -> dict[str, str]:
    """Variables in this project's namespaces that no field declares.

    THE TYPO CHECK pydantic CANNOT DO. extra="forbid" does not report a stray
    DATABRICKS_HOSTT -- with a similarly-named field declared it is silently
    missed (pydantic-settings#384) -- and forbidding extras outright rejects
    every unrelated variable in the process.

    Comparing what is PRESENT against what is DECLARED is the check that
    actually answers the question, and it is scoped to namespaces this project
    owns so an unrelated variable is never anyone's problem.
    """
    declared = declared_aliases()
    return {
        name: value
        for name, value in os.environ.items()
        if name.startswith(OWNED_PREFIXES) and name not in declared
    }


def snapshot() -> Environment:
    """Read the environment once. Callers share the result rather than re-reading."""
    return Environment()
