# scripts/plan_edit.py
"""Add and amend plan entries, preserving every comment (D.23, D.24).

THE 2026 STYLE-PRESERVING EDITOR. tomlkit round-trips all three plan files byte for
byte, so editing through it keeps every comment and layout -- where hand-made text
edits anchored on a guessed layout, and one was refused on a formatting difference.

VALUES ARE BUILT EXPLICITLY. Handed a plain list of dictionaries, tomlkit writes an
array of tables; lists become tomlkit arrays, multi-line when they hold tables, and
dictionaries become inline tables, matching the files' own style.

ALL OR NOTHING. Every edited document is re-read through its contract -- ProjectPlan,
IdLedger, PlanTrace -- before any file is written; any failure writes nothing.
"""

from __future__ import annotations

import json
import sys
import tomllib
from collections.abc import Sequence
from pathlib import Path

import tomlkit
from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError
from tomlkit.items import AoT, Array, Item, Table
from tomlkit.toml_document import TOMLDocument

from command_outcome import CommandOutcome
from plan_models import IdLedger, PlanTrace, ProjectPlan

ROOT = Path(__file__).resolve().parent.parent
PLAN = Path("context") / "plan.toml"
IDS = Path("context") / "plan-ids.toml"
TRACE = Path("context") / "plan-trace.toml"


class _Trace(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    source: str = Field(min_length=1)
    ref: str = Field(min_length=1)
    text: str = Field(min_length=1)


class AddSpec(BaseModel):
    """What plan:add reads: new steps, and the one trace entry they map from."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    steps: tuple[dict[str, JsonValue], ...] = Field(min_length=1)
    trace: _Trace


class AmendSpec(BaseModel):
    """What plan:amend reads: one step, and the fields to replace."""

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)
    id: str = Field(min_length=1)
    fields: dict[str, JsonValue] = Field(alias="set", min_length=1)


# TOML'S BARE-KEY ALPHABET. A key outside it must be quoted: a step id such as D.32,
# written bare, is the dotted key D -> 32, and the contract refuses that nested table.
# Every plan key that is a step id holds a dot, so without this no because could be
# written at all (D.51).
_BARE_KEY = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-")


def _key(name: str) -> str:
    """A key as TOML text: bare when TOML allows it, else a basic string with TOML's escaping."""
    if name and set(name) <= _BARE_KEY:
        return name
    return tomlkit.item(name).as_string()


def _render(value: JsonValue) -> str:
    """A value as TOML text in the plan files' own style.

    { key = value } with a space inside the braces, always on one line as TOML
    requires; a multi-line array, two-space indented, when it holds tables; scalars
    through tomlkit, so strings get TOML's own escaping.
    """
    if isinstance(value, dict):
        pairs = ", ".join(f"{_key(key)} = {_render(item)}" for key, item in value.items())
        return "{ " + pairs + " }"
    if isinstance(value, list):
        if any(isinstance(item, dict) for item in value):
            return "[\n" + "".join(f"  {_render(item)},\n" for item in value) + "]"
        return "[" + ", ".join(_render(item) for item in value) + "]"
    return tomlkit.item(value).as_string()


def _value(value: JsonValue) -> Item:
    """Parsed by tomlkit from text in the files' style, so it keeps that whitespace exactly."""
    parsed = tomlkit.parse(f"value = {_render(value)}\n")["value"]
    if not isinstance(parsed, Item):
        raise SystemExit("a rendered value did not parse as a TOML item")
    return parsed


def _parse(root: Path, relative: Path) -> TOMLDocument:
    return tomlkit.parse((root / relative).read_text(encoding="utf-8"))


def _array(document: TOMLDocument, key: str) -> Array:
    found = document[key]
    if not isinstance(found, Array):
        raise SystemExit(f"{key} is not an inline array")
    return found


def _steps(document: TOMLDocument) -> AoT:
    found = document["steps"]
    if not isinstance(found, AoT):
        raise SystemExit("steps is not an array of tables")
    return found


def _validated(documents: dict[Path, TOMLDocument]) -> dict[Path, str]:
    """Each document rendered and re-read through its contract; raises on any failure."""
    rendered = {relative: tomlkit.dumps(document) for relative, document in documents.items()}
    ProjectPlan.model_validate(tomllib.loads(rendered[PLAN]))
    if IDS in rendered:
        IdLedger.model_validate(tomllib.loads(rendered[IDS]))
    if TRACE in rendered:
        PlanTrace.model_validate(tomllib.loads(rendered[TRACE]))
    return rendered


def _errors(error: ValidationError) -> list[JsonValue]:
    """Every validation error as data: the field's path, pydantic's message and its type.

    "1 validation error" says that something failed; these say what, and for a value
    outside a fixed set the message names the values the contract accepts.
    """
    return [
        {
            "field": ".".join(str(part) for part in detail["loc"]),
            "message": detail["msg"],
            "type": detail["type"],
        }
        for detail in error.errors(include_url=False)
    ]


def _report(command: str, outcome: str, code: str, message: str, data: dict[str, JsonValue]) -> int:
    envelope = CommandOutcome.model_validate(
        {"command": command, "outcome": outcome, "code": code, "message": message, "data": data}
    )
    print(json.dumps(envelope.model_dump(), indent=2))
    return envelope.exit_code


def _spec_text(argv: Sequence[str] | None, verb: str) -> str:
    args = list(sys.argv[2:] if argv is None else argv)
    if len(args) != 1:
        raise SystemExit(f"usage: mise run run plan:{verb} <spec.toml>")
    return Path(args[0]).read_text(encoding="utf-8")


def add(argv: Sequence[str] | None = None, *, root: Path = ROOT) -> int:
    """plan:add <spec> -- steps, their ids and one trace entry, together or not at all."""
    spec = AddSpec.model_validate(tomllib.loads(_spec_text(argv, "add")))
    documents = {relative: _parse(root, relative) for relative in (PLAN, IDS, TRACE)}
    planned = {str(step["id"]) for step in _steps(documents[PLAN])}
    issued = {str(entry["id"]) for entry in _array(documents[IDS], "issued")}
    new_ids = [str(step.get("id", "")) for step in spec.steps]
    taken = sorted(set(new_ids) & (planned | issued))
    if taken:
        return _report(
            "plan:add",
            "refused",
            "id_taken",
            f"already planned or issued: {', '.join(taken)}",
            {"taken": list(taken)},
        )

    for step in spec.steps:
        table = tomlkit.table()
        for key, value in step.items():
            table[key] = _value(value)
        _steps(documents[PLAN]).append(table)
        _array(documents[IDS], "issued").add_line(
            _value({"id": step["id"], "first_title": step.get("title", "")}), indent="  "
        )
    _array(documents[TRACE], "candidates").add_line(
        _value({**spec.trace.model_dump(), "maps_to": list(new_ids)}), indent="  "
    )
    try:
        rendered = _validated(documents)
    except ValidationError as error:
        return _report(
            "plan:add",
            "refused",
            "contract_violated",
            str(error).splitlines()[0],
            {"ids": list(new_ids), "errors": _errors(error)},
        )
    for relative, text in rendered.items():
        (root / relative).write_text(text, encoding="utf-8")
    return _report(
        "plan:add",
        "success",
        "entries_added",
        f"added {', '.join(new_ids)}",
        {"ids": list(new_ids)},
    )


def _entries(document: TOMLDocument) -> list[Table]:
    """Every plan entry that has an id: steps, then decisions."""
    entries: list[Table] = []
    for key in ("steps", "decisions"):
        found = document.get(key)
        if isinstance(found, AoT):
            entries.extend(found)
    return entries


def amend(argv: Sequence[str] | None = None, *, root: Path = ROOT) -> int:
    """plan:amend <spec> -- replace named fields of one step or decision, in place."""
    spec = AmendSpec.model_validate(tomllib.loads(_spec_text(argv, "amend")))
    document = _parse(root, PLAN)
    target = next((t for t in _entries(document) if t["id"] == spec.id), None)
    if target is None:
        return _report(
            "plan:amend",
            "refused",
            "entry_unknown",
            f"{spec.id} is not a step or a decision",
            {"id": spec.id},
        )
    for key, value in spec.fields.items():
        target[key] = _value(value)
    try:
        rendered = _validated({PLAN: document})
    except ValidationError as error:
        return _report(
            "plan:amend",
            "refused",
            "contract_violated",
            str(error).splitlines()[0],
            {"id": spec.id, "errors": _errors(error)},
        )
    (root / PLAN).write_text(rendered[PLAN], encoding="utf-8")
    return _report(
        "plan:amend",
        "success",
        "entry_amended",
        f"{spec.id}: {', '.join(spec.fields)}",
        {"id": spec.id, "fields": list(spec.fields)},
    )


if __name__ == "__main__":
    verbs = {"add": add, "amend": amend}
    if len(sys.argv) < 2 or sys.argv[1] not in verbs:
        raise SystemExit("usage: plan_edit.py add|amend <spec.toml>")
    sys.exit(verbs[sys.argv[1]]())
