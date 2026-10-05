# tests/test_release_target.py
"""A release is derived from its job in the bundle, and its tag names it (D.14).

HARD-WIRED TO ASSIGNMENT 1. release.py fixed its export directory, job name
suffix and notebook name, so no other assignment could be released. Each is now
derived from one job key in the RESOLVED bundle -- the job's name, and from its
notebook_path the assignment directory and the notebook -- so there is no second
mapping to drift.

THE FIXTURE IS THE CLI'S REAL SHAPE, captured from bundle validate, not an
imitation written for the test.

A TAG NAMES ITS ASSIGNMENT. assignment-02-v1 on Assignment 1's run would point a
regrade at the wrong work; policies/release refuses it before anything merges.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import JsonValue

from databricks_cli import ResolvedBundle
from opa import denials
from release import ReleaseTarget, release_target

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "bundle-resolved-fixture-target.json"
JOB = "assignment_01_ingest"


def _bundle() -> ResolvedBundle:
    return ResolvedBundle.model_validate_json(FIXTURE.read_text(encoding="utf-8"))


def _denied(release: dict[str, JsonValue] | None) -> list[str]:
    payload: dict[str, JsonValue] = {} if release is None else {"release": release}
    return [d for d in denials("data.release.deny", payload) if d.startswith("[ERR_RELEASE_")]


def _release(tag: str) -> dict[str, JsonValue]:
    return {"tag": tag, "target": release_target(_bundle(), JOB).model_dump(mode="json")}


def test_the_target_is_derived_from_the_bundle() -> None:
    assert release_target(_bundle(), JOB) == ReleaseTarget(
        job_key=JOB,
        job_name="assignment-01-spark-api",
        assignment="assignment-01",
        notebook="assignment_01_spark_api",
    )


def test_exports_land_beside_their_assignment() -> None:
    assert release_target(_bundle(), JOB).exports == Path("assignments/assignment-01/exports")


def test_an_unknown_job_is_refused() -> None:
    with pytest.raises(SystemExit, match="no job"):
        release_target(_bundle(), "assignment_99_missing")


def test_a_tag_naming_its_own_assignment_is_allowed() -> None:
    """THE CONTROL: a policy refusing every tag would pass the rest."""
    assert _denied(_release("assignment-01-v3")) == []


def test_a_tag_naming_another_assignment_is_refused() -> None:
    denied = _denied(_release("assignment-02-v1"))
    assert any(d.startswith("[ERR_RELEASE_TAG_MISMATCH]") for d in denied), denied


def test_a_tag_without_a_version_is_refused() -> None:
    denied = _denied(_release("assignment-01"))
    assert any(d.startswith("[ERR_RELEASE_TAG_MISMATCH]") for d in denied), denied


def test_with_no_release_the_policy_is_quiet() -> None:
    """The gate's payload holds no release, so it must never be refused here."""
    assert _denied(None) == []
