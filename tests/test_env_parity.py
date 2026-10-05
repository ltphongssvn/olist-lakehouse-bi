"""Tests for the interpreter-parity gate.

WHY THE GATE ITSELF IS TESTED
check:env-parity is what three other files cite as the reason the derived
interpreter design is safe. If its comparison logic is wrong it reports green
while drift accumulates -- worse than no gate, because it manufactures
confidence. These tests exercise the mapping and comparison WITHOUT the network,
so a Databricks outage cannot make them pass vacuously.

THE SHAPE IS THE MODEL'S NOW. These tests used to assert the file's structure by
hand; environment_versions.py declares it, and the gate reads the same model.
What is tested here is that the model REFUSES a broken mapping.
"""

from __future__ import annotations

import pathlib

import pytest
from pydantic import JsonValue, TypeAdapter, ValidationError

from environment_versions import CONTRACT, EnvironmentVersions, load

ROOT = pathlib.Path(__file__).resolve().parent.parent
PYTHON_VERSION = ROOT / ".python-version"
RAW = TypeAdapter(dict[str, JsonValue])


@pytest.fixture(scope="module")
def contract() -> EnvironmentVersions:
    return load()


def _raw() -> dict[str, JsonValue]:
    """The committed file as plain JSON, for breaking it on purpose."""
    return RAW.validate_json(CONTRACT.read_text(encoding="utf-8"))


def _versions(raw: dict[str, JsonValue]) -> dict[str, JsonValue]:
    versions = raw["versions"]
    assert isinstance(versions, dict)
    return versions


def test_the_committed_mapping_validates(contract: EnvironmentVersions) -> None:
    """THE CONTROL: every refusal below would pass against a model refusing all."""
    assert contract.versions


def test_a_version_without_an_interpreter_is_refused() -> None:
    """A version missing python would have made the gate raise KeyError."""
    raw = _raw()
    five = _versions(raw)["5"]
    assert isinstance(five, dict)
    del five["python"]
    with pytest.raises(ValidationError):
        EnvironmentVersions.model_validate(raw)


def test_a_non_numeric_version_key_is_refused() -> None:
    """The gate sorts keys with int() when reporting an unknown version."""
    raw = _raw()
    versions = _versions(raw)
    versions["five"] = versions["5"]
    with pytest.raises(ValidationError):
        EnvironmentVersions.model_validate(raw)


def test_local_interpreter_matches_the_declared_target(contract: EnvironmentVersions) -> None:
    """The parity assertion without the network round-trip.

    The bundle declares environment_version 5. Duplicating that constant here is
    deliberate: changing the bundle default without updating the contract or
    .python-version fails this test whether or not a workspace is reachable.
    """
    assert PYTHON_VERSION.read_text().strip() == contract.versions["5"].python


def test_superseded_versions_are_retained(contract: EnvironmentVersions) -> None:
    """Deleting a published mapping is itself a breaking change.

    Environment version 1 is supported until March 2027; someone targeting it
    needs its mapping. The check is 'is every version present', never 'does this
    file contain nothing else'.
    """
    assert set(contract.versions) >= {"1", "2", "3", "4", "5"}


def test_the_hand_maintained_seam_must_stay_documented() -> None:
    """This file is transcribed from docs, not generated. That must stay visible."""
    for documented in ("x-source", "x-review-trigger"):
        raw = _raw()
        del raw[documented]
        with pytest.raises(ValidationError):
            EnvironmentVersions.model_validate(raw)
