"""Tests for the accidental-file check.

WHY BOTH DIRECTIONS
A guard seen only passing is indistinguishable from one that cannot fire. This
one was verified by hand against the actual debris -- a zero-byte `nix_contract`
at the root -- and a hand-verification is not a test.

The false-positive cases matter as much: a check that flags legitimate files is
one people disable, and a disabled check catches nothing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from check_repo_hygiene import looks_accidental


def test_a_zero_byte_root_file_is_flagged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """THE ACTUAL DEBRIS: a mistyped redirect left `nix_contract` at the root."""
    import check_repo_hygiene

    monkeypatch.setattr(check_repo_hygiene, "ROOT", tmp_path)
    (tmp_path / "nix_contract").write_text("")

    reason = looks_accidental(Path("nix_contract"))

    assert reason is not None
    assert "empty" in reason


def test_a_root_file_with_no_extension_is_flagged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Non-empty, but still nameless in the way a lost suffix leaves a file."""
    import check_repo_hygiene

    monkeypatch.setattr(check_repo_hygiene, "ROOT", tmp_path)
    (tmp_path / "nix_contract").write_text("print('hello')\n")

    reason = looks_accidental(Path("nix_contract"))

    assert reason is not None
    assert "no extension" in reason


def test_a_conventional_extensionless_name_is_allowed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LICENSE and Makefile belong at a root without suffixes."""
    import check_repo_hygiene

    monkeypatch.setattr(check_repo_hygiene, "ROOT", tmp_path)
    (tmp_path / "LICENSE").write_text("MIT\n")

    assert looks_accidental(Path("LICENSE")) is None


def test_a_dotfile_is_allowed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """.gitignore has no suffix and is obviously deliberate."""
    import check_repo_hygiene

    monkeypatch.setattr(check_repo_hygiene, "ROOT", tmp_path)
    (tmp_path / ".gitignore").write_text("*.pyc\n")

    assert looks_accidental(Path(".gitignore")) is None


def test_an_empty_marker_file_is_allowed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A .gitkeep is empty ON PURPOSE -- its name is the whole content."""
    import check_repo_hygiene

    monkeypatch.setattr(check_repo_hygiene, "ROOT", tmp_path)
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / ".gitkeep").write_text("")

    assert looks_accidental(Path("data/.gitkeep")) is None


def test_an_extensionless_file_inside_a_directory_is_allowed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only the ROOT is checked for naming.

    A directory someone created on purpose can hold extensionless files --
    scripts, fixtures, data -- and flagging those would make this the check
    people disable.
    """
    import check_repo_hygiene

    monkeypatch.setattr(check_repo_hygiene, "ROOT", tmp_path)
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "release").write_text("#!/bin/sh\n")

    assert looks_accidental(Path("bin/release")) is None


def test_an_ordinary_root_file_is_allowed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import check_repo_hygiene

    monkeypatch.setattr(check_repo_hygiene, "ROOT", tmp_path)
    (tmp_path / "mise.toml").write_text("[tools]\n")

    assert looks_accidental(Path("mise.toml")) is None
