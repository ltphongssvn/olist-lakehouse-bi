# tests/test_source_read.py
"""A file is read by a task, its lines numbered, as data (D.26).

The audit counted 110 `cat` reads. Each line comes back as a record -- its number and
its text, ripgrep's own --json convention -- so a reader and a searcher speak one
shape. A range past the end is refused rather than silently shortened.
"""

from __future__ import annotations

from pathlib import Path

from source_read import main, read_lines


def _file(tmp_path: Path) -> Path:
    path = tmp_path / "five.txt"
    path.write_text("a\nb\nc\nd\ne\n", encoding="utf-8")
    return path


def test_lines_come_back_numbered_as_data(tmp_path: Path) -> None:
    view = read_lines(_file(tmp_path), 2, 4)
    assert (view.first_line, view.last_line, view.total_lines) == (2, 4, 5)
    assert [(line.number, line.text) for line in view.lines] == [(2, "b"), (3, "c"), (4, "d")]


def test_no_range_means_the_whole_file(tmp_path: Path) -> None:
    view = read_lines(_file(tmp_path), None, None)
    assert [line.number for line in view.lines] == [1, 2, 3, 4, 5]


def test_a_range_past_the_end_is_refused(tmp_path: Path) -> None:
    assert main([str(_file(tmp_path)), "4", "9"]) == 2


def test_a_missing_file_is_refused(tmp_path: Path) -> None:
    assert main([str(tmp_path / "missing.txt")]) == 2
