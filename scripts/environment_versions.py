"""environment-versions/v1: the Databricks environment version to interpreter mapping.

ONE SHAPE, READ IN TWO PLACES. check_env_parity.py and its tests both parsed
contracts/environment-versions.json raw, and the tests re-asserted its shape by
hand -- every version has a python, keys are numeric, the source is documented.
Those assertions WERE the schema, written as asserts. They live here now, and
the gate and its tests read the same model, so the two cannot drift.

THE FILE IS HAND-MAINTAINED, transcribed from Databricks' documentation, which
exposes environment versions as a reference table rather than an API. Its
source and review trigger are therefore required fields: the seam stays visible.
"""

from __future__ import annotations

import pathlib
from datetime import date
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONTRACT = ROOT / "contracts" / "environment-versions.json"

VersionKey = Annotated[str, StringConstraints(pattern=r"^[0-9]+$")]


class EnvironmentVersion(BaseModel):
    """What one serverless environment version ships."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    # THE FIELD THE GATE EXISTS FOR: Spark Connect needs client and server on
    # one Python minor version.
    python: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    databricks_connect: str = Field(min_length=1)
    scala: str | None = None
    jdk: str | None = None
    os: str = Field(min_length=1)
    released: date
    end_of_support: date


class EnvironmentVersions(BaseModel):
    """contracts/environment-versions.json, as committed."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    json_schema: str = Field(alias="$schema")
    identifier: str = Field(alias="$id")
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    source: str = Field(alias="x-source", min_length=1)
    verified_on: date = Field(alias="x-verified-on")
    review_trigger: str = Field(alias="x-review-trigger", min_length=1)
    # NUMERIC KEYS, because the gate sorts them with int() to report an
    # unknown version.
    versions: dict[VersionKey, EnvironmentVersion] = Field(min_length=1)


def load(path: pathlib.Path = CONTRACT) -> EnvironmentVersions:
    """The committed mapping, validated."""
    return EnvironmentVersions.model_validate_json(path.read_text(encoding="utf-8"))
