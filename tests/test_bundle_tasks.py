# tests/test_bundle_tasks.py
"""Deploying and running the bundle are tasks, validated strictly first (D.13).

NO TASK DEPLOYED OR RAN THE BUNDLE. Assignment 1's job was deployed by hand, so
the one operation running an assignment in Databricks rests on lived only in a
shell's history.

VALIDATE --strict BEFORE EVERY DEPLOY. 2026 practice makes validate the reflex
before deploy, and --strict because a plain validate reported an unknown
property only as a warning -- and the job deployed without its task.

RUN WAITS. bundle run waits for the job and exits non-zero when it fails, so a
failed run fails the task; --no-wait would report success for work not done.
"""

from __future__ import annotations

from pathlib import Path

from task_commands import command_invocations, task_input

ROOT = Path(__file__).resolve().parent.parent


def _commands(task: str) -> list[tuple[str, ...]]:
    tasks = task_input(ROOT / "mise.toml").tasks
    assert task in tasks, f"{task} is not a task"
    return [command.argv for command in command_invocations({task: tasks[task]})]


def _target(argv: tuple[str, ...]) -> str:
    return argv[argv.index("-t") + 1]


def test_deploy_validates_strictly_before_it_deploys() -> None:
    commands = [argv for argv in _commands("bundle:deploy") if argv[:1] == ("databricks",)]
    assert [argv[1:3] for argv in commands] == [("bundle", "validate"), ("bundle", "deploy")]
    assert "--strict" in commands[0]


def test_validate_and_deploy_name_the_same_target() -> None:
    validate, deploy = (argv for argv in _commands("bundle:deploy") if argv[:1] == ("databricks",))
    assert _target(validate) == _target(deploy)


def test_run_waits_for_the_job_it_starts() -> None:
    (run,) = (argv for argv in _commands("bundle:run") if argv[:1] == ("databricks",))
    assert run[1:3] == ("bundle", "run")
    assert "--no-wait" not in run
    assert "-t" in run
