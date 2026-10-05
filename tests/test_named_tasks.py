# tests/test_named_tasks.py
"""Every task a message tells the reader to run is a task mise.toml declares (D.56).

A remediation message is an instruction: one naming a task that does not exist fails at
the moment someone follows it. check_prereqs.py and databricks.yml both said
`mise run bootstrap:groups` after bootstrap:identity replaced it.

THE DECLARED SET COMES FROM tasks:list (D.35), mise's own resolution of every task, not
a second parser of mise.toml. Rego decides over the typed inventory; these prove it bites.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from named_tasks import Mention, NamedTasks, mentioned, named_tasks
from opa import denials

ENTRYPOINT = "data.tasks.named.deny"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def _decide(inventory: NamedTasks) -> list[str]:
    return denials(ENTRYPOINT, {"named_tasks": inventory.model_dump(mode="json")})


def test_the_runner_is_not_the_named_task() -> None:
    assert mentioned("mise run run plan:add spec.toml") == ["plan:add"]
    assert mentioned("mise -C ~/repo run run repo:state") == ["repo:state"]
    assert mentioned("then `mise run bootstrap:groups`.") == ["bootstrap:groups"]
    assert mentioned("usage: mise run run plan:{verb} <spec.toml>") == []
    assert mentioned("no task here") == []


def test_a_named_task_that_does_not_exist_is_refused() -> None:
    declared = ("bootstrap:identity", "run")
    stale = Mention(path="scripts/check_prereqs.py", number=1, task="bootstrap:groups")
    found = _decide(NamedTasks(declared=declared, mentions=(stale,)))
    assert any("bootstrap:groups" in denial for denial in found), found
    current = Mention(path="scripts/check_prereqs.py", number=1, task="bootstrap:identity")
    assert _decide(NamedTasks(declared=declared, mentions=(current,))) == []


def test_every_task_named_in_the_repository_is_declared() -> None:
    assert _decide(named_tasks()) == []


def test_the_gate_cannot_pass_without_the_inventory() -> None:
    """The gate merges one payload for every policy: an absent key must fail, not pass."""
    payloads: tuple[dict[str, object], ...] = ({}, {"tasks": {}})
    for payload in payloads:
        found = denials(ENTRYPOINT, payload)
        assert any("ERR_TASK_NAMED_INPUT_MISSING" in denial for denial in found), (payload, found)


def test_an_uncommitted_instruction_is_judged_before_it_is_committed(tmp_path: Path) -> None:
    """check passed while named_tasks.py was untracked; pre-push then refused it."""
    _git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "tracked.md").write_text("nothing to run\n", encoding="utf-8")
    _git(tmp_path, "add", "tracked.md")
    _git(tmp_path, "commit", "-q", "-m", "start")
    (tmp_path / "new.md").write_text("then mise run no:such-task\n", encoding="utf-8")
    found = named_tasks(tmp_path)
    assert [(m.path, m.task) for m in found.mentions] == [("new.md", "no:such-task")]
