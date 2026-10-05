"""Tests for the environment snapshot.

WHY THE BOUNDARY IS ITSELF TESTED
The snapshot exists because ambient state caused four CI failures that were hard
to diagnose: local and CI resolved differently and nothing rendered the
difference. An unverified boundary would relocate the problem, not remove it.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from environment import Environment, declared_aliases, snapshot, unknown_owned_variables


def test_absent_variables_yield_none(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in declared_aliases():
        monkeypatch.delenv(name, raising=False)

    environment = Environment()

    assert environment.databricks_host is None
    assert environment.has_unified_auth is False


def test_host_must_be_https(monkeypatch: pytest.MonkeyPatch) -> None:
    """A bare hostname fails at construction, naming the field.

    Without it, failure arrives at the API call that could not parse the value
    and reports a connection error rather than a configuration error.
    """
    monkeypatch.setenv("DATABRICKS_HOST", "dbc-example.cloud.databricks.com")

    with pytest.raises(ValidationError, match="must start with https"):
        Environment()


def test_trailing_slash_is_normalised(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABRICKS_HOST", "https://example.cloud.databricks.com/")
    assert Environment().databricks_host == "https://example.cloud.databricks.com"


def test_unified_auth_needs_credentials_not_a_host(monkeypatch: pytest.MonkeyPatch) -> None:
    """The exact bug this property replaces.

    Scripts branched on DATABRICKS_HOST alone. A host says WHERE the workspace is
    and nothing about proving identity, so a laptop with a host and no
    credentials took the CI path and failed with "cannot configure default
    credentials".
    """
    monkeypatch.setenv("DATABRICKS_HOST", "https://example.cloud.databricks.com")
    monkeypatch.delenv("DATABRICKS_CLIENT_ID", raising=False)
    monkeypatch.delenv("DATABRICKS_CLIENT_SECRET", raising=False)

    assert Environment().has_unified_auth is False

    monkeypatch.setenv("DATABRICKS_CLIENT_ID", "some-id")
    monkeypatch.setenv("DATABRICKS_CLIENT_SECRET", "some-secret")

    assert Environment().has_unified_auth is True


def test_secret_does_not_render(monkeypatch: pytest.MonkeyPatch) -> None:
    """SecretStr is the guarantee; not printing it is the discipline it replaces.

    This project rendered a live OAuth secret to a terminal once. A type that
    cannot print itself is stronger than remembering not to.
    """
    monkeypatch.setenv("DATABRICKS_CLIENT_SECRET", "must-not-appear-in-output")

    environment = Environment()

    assert "must-not-appear-in-output" not in repr(environment)
    assert "must-not-appear-in-output" not in environment.model_dump_json()
    assert environment.databricks_client_secret is not None
    assert environment.databricks_client_secret.get_secret_value() == "must-not-appear-in-output"


def test_the_snapshot_is_frozen() -> None:
    """A snapshot that can be mutated is not a snapshot.

    frozen=True in the config raises ValidationError with type=frozen_instance
    and the message "Instance is frozen".
    """
    environment = snapshot()

    with pytest.raises(ValidationError, match="frozen"):
        # NO type: ignore HERE. One was written, and mypy reported it as an
        # UNUSED ignore -- BaseSettings does not generate the read-only property
        # that a plain BaseModel with frozen=True does, so there was nothing to
        # suppress. warn_unused_ignores caught a suppression the moment it became
        # unnecessary, which is the entire reason strict mode enables it.
        environment.databricks_host = "https://elsewhere.example.com"


def test_typos_in_owned_namespaces_are_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    """The check pydantic cannot do.

    extra="forbid" does NOT report a stray DATABRICKS_HOSTT when a similarly
    named field is declared -- it is silently missed (pydantic-settings#384) --
    and forbidding extras outright rejects every unrelated variable in the
    process. Comparing present against declared answers the question.
    """
    monkeypatch.setenv("DATABRICKS_HOSTT", "https://typo.example.com")

    assert "DATABRICKS_HOSTT" in unknown_owned_variables()


def test_unrelated_variables_are_not_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    """Scoped to namespaces this project owns, so PATH is never anyone's problem."""
    monkeypatch.setenv("SOME_UNRELATED_TOOL_SETTING", "value")

    assert "SOME_UNRELATED_TOOL_SETTING" not in unknown_owned_variables()
