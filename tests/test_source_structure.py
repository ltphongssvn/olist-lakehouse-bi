# tests/test_source_structure.py
"""A file's structure, or a model's schema, is read by a task, as data (D.36).

Read by hand three times: pyproject's ruff settings, CommandOutcome's schema, the
plan files' shapes. A TOML or JSON file comes back as its top-level keys -- kind,
entry count and a sample -- validated as JsonValue rather than left as raw parse
output; a model comes back as its JSON schema, from model_json_schema.
"""

from __future__ import annotations

from pathlib import Path

from source_structure import describe, main


def test_a_files_structure_comes_back_as_data(tmp_path: Path) -> None:
    path = tmp_path / "plan.toml"
    path.write_text(
        'contract = "plan/v1"\n\n[[steps]]\nid = "A.1"\n\n[[steps]]\nid = "A.2"\n', encoding="utf-8"
    )
    keys = {k.key: k for k in describe(str(path)).keys or ()}
    assert (keys["contract"].kind, keys["contract"].entries) == ("string", None)
    assert (keys["steps"].kind, keys["steps"].entries, keys["steps"].sample) == (
        "array",
        2,
        {"id": "A.1"},
    )


def test_a_json_file_is_described_too(tmp_path: Path) -> None:
    path = tmp_path / "data.json"
    path.write_text('{"versions": {"18.0": {"python": "3.12"}}, "count": 3}', encoding="utf-8")
    keys = {k.key: k for k in describe(str(path)).keys or ()}
    assert (keys["versions"].kind, keys["versions"].entries, keys["count"].kind) == (
        "table",
        1,
        "number",
    )


def test_a_models_schema_comes_back(tmp_path: Path) -> None:
    report = describe("command_outcome:CommandOutcome")
    assert report.schema_ is not None
    properties = report.schema_["properties"]
    assert isinstance(properties, dict) and "outcome" in properties


def test_an_unsupported_file_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "notes.txt"
    path.write_text("plain\n", encoding="utf-8")
    assert main([str(path)]) == 2


def test_a_name_that_is_not_a_model_is_refused() -> None:
    assert main(["command_outcome:json"]) == 2
