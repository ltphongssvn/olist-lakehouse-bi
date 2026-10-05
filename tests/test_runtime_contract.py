"""Tests for the runtime contract.

WHY THE CONTRACT IS ITSELF TESTED
It exists because fourteen tasks ran on the wrong interpreter for as long as
they existed, and nothing noticed. A guard against that which is not verified in
both directions would be the same failure wearing a different hat.

The violating cases construct a RuntimeContract directly rather than
manipulating the filesystem or spawning interpreters -- expected_venv and
expected_version are fields precisely so the failure paths are reachable in
process.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from runtime_contract import RuntimeContract, enforce


def test_this_process_satisfies_the_contract() -> None:
    """The suite runs under uv, so it must pass. If it does not, everything else
    in this file is measuring the wrong interpreter."""
    contract = enforce()

    assert contract.in_a_venv
    assert contract.in_the_expected_venv
    assert contract.version == contract.expected_version


def test_denies_running_outside_any_venv() -> None:
    """prefix == base_prefix is the canonical 'not in a venv' signal."""
    with pytest.raises(ValidationError, match="not in a virtual environment"):
        RuntimeContract(
            executable=Path("/opt/homebrew/bin/python3"),
            prefix=Path("/opt/homebrew"),
            base_prefix=Path("/opt/homebrew"),
            version="3.12.3",
            expected_version="3.12.3",
            expected_venv=Path("/project/.venv"),
        )


def test_denies_a_different_venv() -> None:
    """Being in A venv is not enough.

    Another project's venv satisfies prefix != base_prefix and holds none of
    this project's locked dependencies.
    """
    with pytest.raises(ValidationError, match="different virtual environment"):
        RuntimeContract(
            executable=Path("/other/.venv/bin/python"),
            prefix=Path("/other/.venv"),
            base_prefix=Path("/usr"),
            version="3.12.3",
            expected_version="3.12.3",
            expected_venv=Path("/project/.venv"),
        )


def test_denies_a_version_mismatch() -> None:
    """The case that actually occurred: 3.14.7 where 3.12.3 was declared.

    Spark Connect requires client and server to share the same Python minor
    version, so this is not a preference.
    """
    # ESCAPED, BECAUSE match= IS A REGEX. "3.14.7" also matches "3x14y7" --
    # RUF043 flags exactly this ambiguity, and a test that passes on a value it
    # was not looking for is the shape this repo keeps finding.
    with pytest.raises(ValidationError, match=re.escape("3.14.7")):
        RuntimeContract(
            executable=Path("/project/.venv/bin/python"),
            prefix=Path("/project/.venv"),
            base_prefix=Path("/usr"),
            version="3.14.7",
            expected_version="3.12.3",
            expected_venv=Path("/project/.venv"),
        )


def test_reports_every_problem_at_once() -> None:
    """Fix-one-rerun-discover-the-next is the treadmill this repo removes."""
    with pytest.raises(ValidationError) as raised:
        RuntimeContract(
            executable=Path("/opt/homebrew/bin/python3"),
            prefix=Path("/opt/homebrew"),
            base_prefix=Path("/opt/homebrew"),
            version="3.14.7",
            expected_version="3.12.3",
            expected_venv=Path("/project/.venv"),
        )

    message = str(raised.value)
    assert "not in a virtual environment" in message
    assert "3.14.7" in message


def test_the_contract_is_frozen() -> None:
    """A snapshot of the running process that can be edited is not evidence."""
    contract = enforce()

    with pytest.raises(ValidationError, match="frozen"):
        contract.version = "3.14.7"


def test_the_message_names_the_remedy() -> None:
    """A diagnostic that states the problem and not the fix sends people guessing."""
    with pytest.raises(ValidationError, match="uv run python"):
        RuntimeContract(
            executable=Path(sys.executable),
            prefix=Path("/opt/homebrew"),
            base_prefix=Path("/opt/homebrew"),
            version="3.12.3",
            expected_version="3.12.3",
            expected_venv=Path("/project/.venv"),
        )
