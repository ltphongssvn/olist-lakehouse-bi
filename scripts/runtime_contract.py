"""Validate that this process satisfies the declared runtime contract.

WHY THIS EXISTS WHEN A POLICY ALREADY DOES
policies/runtime/ denies a TASK that names a bare interpreter. It cannot see a
script invoked any other way -- by an editor, a CI step, a shell alias, a
person. Static policy governs what the repo declares; this governs what is
actually executing.

The gap was not hypothetical. Fourteen tasks ran on Homebrew's Python 3.14.7
rather than the pinned 3.12.3, outside the venv, for as long as they existed.
They passed because they used only the standard library, and check:env-parity
never noticed: it compares two DECLARATIONS and never asks which interpreter is
running.

WHY sys.prefix AND NOT VIRTUAL_ENV
The venv documentation names `sys.prefix != sys.base_prefix` as the reliable
detection. VIRTUAL_ENV is an environment variable -- easy to lose, easy to fake,
and absent whenever an interpreter is invoked directly rather than through an
activation script. A process can be inside a venv with VIRTUAL_ENV unset.
Interpreter state is evidence; the shell environment is a claim.

BEING IN A VENV IS NOT ENOUGH
Another project's venv satisfies prefix != base_prefix and contains none of this
project's locked dependencies, so the check is against THIS venv specifically.

WHY enforce() IS CALLED, NOT RUN AT IMPORT
Import-time enforcement is the obvious design and is wrong three times over.
It makes the failure path untestable, since importing the module inside a test
would end the run. It is the named anti-pattern of doing work during
construction -- "you cannot even construct the object without triggering
external work" -- and this reads a file. And PEP 810 lazy imports, landing in
Python 3.15, shift side effects from import time to first use, so anything
depending on import-time execution becomes unreliable.

A check that cannot be tested for its failure path is a check this session has
repeatedly shown to be worth nothing.
"""

from __future__ import annotations

import sys
from pathlib import Path

# THE IMPORT IS GUARDED BECAUSE THE WRONG INTERPRETER CANNOT REACH THE CHECK.
#
# Under a bare `python3` this module fails at the pydantic import, not at the
# contract check -- the interpreter that violates the contract is precisely the
# one without the dependency the contract is written in.
#
# That is a stronger guarantee and a worse diagnostic: "No module named
# 'pydantic'" says nothing about which interpreter is running or why it is
# wrong. The guard converts it into the message that was going to be printed
# anyway.
try:
    from pydantic import BaseModel, ConfigDict, model_validator
except ModuleNotFoundError as error:  # pragma: no cover - requires a wrong interpreter
    import sys as _sys

    raise SystemExit(
        f"runtime contract violated: {error.name!r} is not importable.\n"
        f"running: {_sys.executable}\n"
        f"prefix:  {_sys.prefix}\n\n"
        "This interpreter is outside the project environment, so the contract "
        "check itself cannot load. Invoke through uv:\n"
        "  uv run python <script>\n"
        "A bare `python3` resolves through PATH, which this repo does not "
        "control."
    ) from error

ROOT = Path(__file__).resolve().parent.parent
EXPECTED_VENV = ROOT / ".venv"
PYTHON_VERSION_FILE = ROOT / ".python-version"


class RuntimeContract(BaseModel):
    """What the executing process must be, checked against what it is."""

    model_config = ConfigDict(frozen=True)

    executable: Path
    prefix: Path
    base_prefix: Path
    version: str
    expected_version: str
    expected_venv: Path

    @property
    def in_a_venv(self) -> bool:
        return self.prefix != self.base_prefix

    @property
    def in_the_expected_venv(self) -> bool:
        return self.prefix == self.expected_venv

    @model_validator(mode="after")
    def enforce_contract(self) -> RuntimeContract:
        problems: list[str] = []

        if not self.in_a_venv:
            problems.append(
                f"not in a virtual environment: sys.prefix and sys.base_prefix "
                f"are both {self.prefix}"
            )
        elif not self.in_the_expected_venv:
            problems.append(
                f"in a different virtual environment: {self.prefix}, expected {self.expected_venv}"
            )

        if self.version != self.expected_version:
            problems.append(
                f"interpreter is {self.version}, .python-version declares {self.expected_version}"
            )

        if problems:
            raise ValueError(
                "runtime contract violated:\n  "
                + "\n  ".join(problems)
                + f"\n\nrunning: {self.executable}\n"
                "Invoke through uv so the pinned interpreter runs:\n"
                "  uv run python <script>\n"
                "A bare `python3` resolves through PATH, which this repo does "
                "not control."
            )

        return self


def enforce() -> RuntimeContract:
    """Check the contract, raising when this process violates it."""
    return RuntimeContract(
        executable=Path(sys.executable),
        prefix=Path(sys.prefix).resolve(),
        base_prefix=Path(sys.base_prefix).resolve(),
        version=".".join(str(part) for part in sys.version_info[:3]),
        expected_version=PYTHON_VERSION_FILE.read_text().strip(),
        expected_venv=EXPECTED_VENV.resolve(),
    )
