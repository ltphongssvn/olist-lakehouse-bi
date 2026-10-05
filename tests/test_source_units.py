# tests/test_source_units.py
"""Functions and classes are read by syntax tree, by a task (D.28).

GROUNDED in 2026 practice -- ast, with each node's lineno and end_lineno -- so a
function is read exactly as written, whatever the formatter made of it, instead of
by hand-written scripts that had to guess its layout.
"""

from __future__ import annotations

from pathlib import Path

from source_units import main, read_units

MODULE = """import os


def alpha(x: int) -> int:
    return x + 1


class Beta:
    \"\"\"A class.\"\"\"

    value = 1


def gamma() -> None:
    pass
"""


def _module(tmp_path: Path) -> Path:
    path = tmp_path / "module.py"
    path.write_text(MODULE, encoding="utf-8")
    return path


def test_units_come_back_with_their_line_ranges(tmp_path: Path) -> None:
    units = read_units(_module(tmp_path), ("alpha", "Beta"))
    assert [(u.name, u.kind, u.first_line, u.last_line) for u in units] == [
        ("alpha", "function", 4, 5),
        ("Beta", "class", 8, 11),
    ]
    assert units[0].source == ("def alpha(x: int) -> int:", "    return x + 1")


def test_no_names_means_every_top_level_unit(tmp_path: Path) -> None:
    assert [u.name for u in read_units(_module(tmp_path), ())] == ["alpha", "Beta", "gamma"]


def test_an_unknown_name_is_refused(tmp_path: Path) -> None:
    assert main([str(_module(tmp_path)), "delta"]) == 2
