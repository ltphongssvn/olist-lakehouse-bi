# tests/test_lockfile_drift.py
"""No task may dirty the lockfile merely by starting.

THE DEFECT. uv locks and syncs automatically: "when uv run is used, the project
is locked and synced before invoking the requested command". So every bare
uv run in mise.toml can rewrite uv.lock, and the change then looks exactly like
the developer's own uncommitted work.

WHY IT MATTERS HERE SPECIFICALLY. sync refuses to switch branches with a dirty
tree, and sync is itself a bare uv run. A stale checkout therefore cannot run
the one task that would bring it current, and every command used to diagnose
that reproduces the condition it is diagnosing.

THE FIX IS A FLAG AND A GATE. --no-sync implies --frozen, so the lockfile
becomes read-only for anything that is not installing. The flag alone would be a
cleanup; this gate is what stops the next bare uv run being added.

ONE CAVEAT, FROM 2026 PRACTICE RATHER THAN FROM THE FLAG'S NAME. --no-sync
"will run against whatever happens to be installed -- on a fresh runner,
nothing". A task whose job is to CREATE the environment cannot use it, which is
why setup is exempt and why the exemption is declared rather than assumed.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# DECLARED, NOT INFERRED. A task is exempt because resolving is its purpose,
# and the reason is written beside it. An inferred exemption -- "it looks like
# an install task" -- is the stale-list failure this repository has removed
# four times.
# EMPTY, AND THAT IS THE FINDING. setup was written as the exemption, on the
# assumption that creating the environment needs an unfrozen uv run. It does
# not: setup calls `uv sync --locked`, which ASSERTS the lockfile is current and
# errors rather than rewriting it -- a stronger guarantee than --no-sync gives,
# because it also catches a lock that has drifted from pyproject.toml.
#
# So no task here needs to resolve, and the register stays empty until one does.
# Declaring an exemption nobody uses would be a permission nobody reviews.
MAY_RESOLVE: dict[str, str] = {}


def tasks() -> dict[str, dict[str, object]]:
    config = tomllib.loads((ROOT / "mise.toml").read_text(encoding="utf-8"))
    return {name: spec for name, spec in config.get("tasks", {}).items() if isinstance(spec, dict)}


def bodies() -> dict[str, str]:
    """Each task's body as one string, whatever shape mise.toml declared it in.

    A `run` may be a STRING OR A LIST of commands -- both are valid in
    mise.toml, and this repository uses both. Reading it as `object` and
    narrowing is not pedantry: mypy caught a version of this that called
    str.join on anything that was not a string, which would have raised on a
    task whose run was a number or a table rather than reporting it.
    """
    out: dict[str, str] = {}
    for name, spec in tasks().items():
        run = spec.get("run", "")
        if isinstance(run, str):
            out[name] = run
        elif isinstance(run, list):
            # EVERY ELEMENT COERCED, not assumed to be a string: a list whose
            # entries are not strings is malformed, and str() says so in the
            # assertion message rather than raising here.
            out[name] = chr(10).join(str(line) for line in run)
        else:
            out[name] = str(run)
    return out


def test_no_task_runs_uv_without_freezing_the_lockfile() -> None:
    """THE GATE. A bare uv run re-resolves and rewrites uv.lock in place."""
    offenders = sorted(
        name
        for name, body in bodies().items()
        if name not in MAY_RESOLVE and "uv run" in body and "--no-sync" not in body
    )
    assert not offenders, (
        "these tasks run uv without --no-sync, so starting them can rewrite "
        f"uv.lock: {', '.join(offenders)}"
    )


def test_every_exemption_names_a_task_that_exists() -> None:
    """THE LIST CANNOT GO STALE IN THE OTHER DIRECTION EITHER.

    An exemption for a task that was renamed or removed is a permission nobody
    is using and nobody will notice -- until it silently covers a new task that
    happens to take the old name.
    """
    missing = sorted(set(MAY_RESOLVE) - set(tasks()))
    assert not missing, f"exempt but no such task: {', '.join(missing)}"


def test_every_exemption_states_why() -> None:
    """A permission without a reason cannot be reviewed."""
    for name, reason in MAY_RESOLVE.items():
        assert reason.strip(), f"{name} is exempt with no reason given"


def test_an_exempt_task_actually_resolves() -> None:
    """An exemption is for a task that INSTALLS. If it carries --no-sync it is
    not resolving, and the exemption is dead.

    VACUOUS TODAY, DELIBERATELY. MAY_RESOLVE is empty, so this loop runs zero
    times -- and that is the correct state, not a gap. It is here so the first
    exemption anyone adds is judged on the day it is added rather than on the
    day someone notices.
    """
    for name in MAY_RESOLVE:
        body = bodies().get(name, "")
        assert "--no-sync" not in body, f"{name} is exempt but freezes anyway"


def test_setup_asserts_the_lockfile_rather_than_rewriting_it() -> None:
    """WHY NO TASK NEEDS AN EXEMPTION.

    setup creates the environment, which is exactly the case --no-sync cannot
    serve: it "will run against whatever happens to be installed -- on a fresh
    runner, nothing". It uses `uv sync --locked` instead, which installs from
    the lockfile and errors if the lockfile has drifted from pyproject.toml.
    """
    body = bodies()["setup"]
    assert "uv sync --locked" in body
    assert "uv run" not in body
