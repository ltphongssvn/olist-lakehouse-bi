# scripts/source_structure.py
"""A file's structure, or a model's schema, read by a task, as data (D.36).

Read by hand three times: pyproject's ruff settings, CommandOutcome's schema, the plan
files' shapes. A TOML or JSON file comes back as its top-level keys -- kind, entry
count and a sample -- validated as JsonValue, never left as raw parse output. A
module:Model target comes back as the model's JSON schema, from model_json_schema,
and is refused unless it really is a Pydantic model.
"""

from __future__ import annotations

import importlib
import json
import sys
import tomllib
from collections.abc import Sequence
from pathlib import Path
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, NonNegativeInt, TypeAdapter

from command_outcome import CommandOutcome

_JSON: TypeAdapter[JsonValue] = TypeAdapter(JsonValue)
Kind = Literal["table", "array", "string", "number", "boolean", "null"]


class KeyShape(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    key: str
    kind: Kind
    entries: NonNegativeInt | None
    sample: JsonValue


class StructureReport(BaseModel):
    """structure-report/v1: a file's top-level shape, or a model's schema."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    CONTRACT_ID: ClassVar[str] = "structure-report/v1"

    contract: Literal["structure-report/v1"] = "structure-report/v1"
    source: str
    form: Literal["toml", "json", "model"]
    keys: tuple[KeyShape, ...] | None = None
    # SERIALIZATION ALIAS ONLY: a plain alias would become the constructor's keyword
    # for type checkers; `schema` itself shadows a BaseModel attribute.
    schema_: dict[str, JsonValue] | None = Field(default=None, serialization_alias="schema")


def _kind(value: JsonValue) -> Kind:
    if isinstance(value, dict):
        return "table"
    if isinstance(value, list):
        return "array"
    if isinstance(value, str):
        return "string"
    if isinstance(value, bool):
        return "boolean"
    if value is None:
        return "null"
    return "number"


def _shape(key: str, value: JsonValue) -> KeyShape:
    if isinstance(value, dict):
        first = next(iter(value.items()), None)
        return KeyShape(
            key=key, kind="table", entries=len(value), sample=dict([first]) if first else None
        )
    if isinstance(value, list):
        return KeyShape(
            key=key, kind="array", entries=len(value), sample=value[0] if value else None
        )
    return KeyShape(key=key, kind=_kind(value), entries=None, sample=value)


def describe(target: str) -> StructureReport:
    """Describe a .toml or .json file's top-level keys, or a module:Model's schema."""
    path = Path(target)
    if ":" in target and not path.exists():
        module, name = target.split(":", 1)
        found = getattr(importlib.import_module(module), name, None)
        if not (isinstance(found, type) and issubclass(found, BaseModel)):
            raise ValueError(f"{target} is not a Pydantic model")
        schema = _JSON.validate_python(found.model_json_schema())
        if not isinstance(schema, dict):
            raise ValueError(f"{target}'s schema is not an object")
        return StructureReport(source=target, form="model", schema_=schema)
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".toml":
        data, form = _JSON.validate_python(tomllib.loads(text)), "toml"
    elif path.suffix == ".json":
        data, form = _JSON.validate_json(text), "json"
    else:
        raise ValueError(f"{path} is not a .toml or .json file")
    if not isinstance(data, dict):
        raise ValueError(f"{path}'s top level is not a table")
    keys = tuple(_shape(key, value) for key, value in data.items())
    return StructureReport(source=target, form="toml" if form == "toml" else "json", keys=keys)


def main(argv: Sequence[str] | None = None) -> int:
    """source:structure <file.toml | file.json | module:Model>."""
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        raise SystemExit(
            "usage: mise run run source:structure <file.toml | file.json | module:Model>"
        )
    try:
        report = describe(args[0])
    except (OSError, ValueError, ImportError) as problem:
        envelope = CommandOutcome.model_validate(
            {
                "command": "source:structure",
                "outcome": "refused",
                "code": "structure_refused",
                "message": str(problem).splitlines()[0],
                "data": {"source": args[0]},
            }
        )
    else:
        envelope = CommandOutcome.model_validate(
            {
                "command": "source:structure",
                "outcome": "success",
                "code": "structure_read",
                "message": f"{report.source}: {report.form}",
                "data": report.model_dump(mode="json", by_alias=True),
            }
        )
    print(json.dumps(envelope.model_dump(), indent=2))
    return envelope.exit_code


if __name__ == "__main__":
    sys.exit(main())
