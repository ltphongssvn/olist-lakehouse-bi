# tests/conftest.py
"""Session-wide isolation from the git environment a hook exports (C.20).

pytest_configure runs once, before any test is collected: git_isolation removes
every repository-local variable machine.testing names, then requires the policy
to allow what remains -- so no test, existing or future, can reach the
repository a hook's GIT_DIR names.
"""

from __future__ import annotations

import os

from git_isolation import isolate


def pytest_configure() -> None:
    isolate(os.environ)
