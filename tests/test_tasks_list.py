# tests/test_tasks_list.py
"""Every task is listed by a task, as data (D.35).

MISE'S OWN INVENTORY. `mise tasks ls --json --local --hidden` reports every task
mise will actually run, as mise resolves it -- name, description, source, usage --
so the inventory is asked of mise rather than parsed out of mise.toml by hand.
It is validated at the boundary, and an undescribed task is reported, never dropped.

ONLY THE PROCESS IS STUBBED: subprocess.run answers `mise`, and nothing else.
"""

from __future__ import annotations

import json
import subprocess

import pytest
from pydantic import ValidationError

from tasks_list import inventory

REPLY = json.dumps(
    [
        {
            "name": "sync",
            "description": "Bring every long-lived branch current",
            "source": "/r/mise.toml",
            "usage": "",
            "aliases": [],
            "hide": False,
        },
        {
            "name": "check",
            "description": "Run every gate",
            "source": "/r/mise.toml",
            "usage": "",
            "aliases": [],
            "hide": False,
        },
    ]
)


def _mise(monkeypatch: pytest.MonkeyPatch, reply: str) -> None:
    def run(command: list[str], **kwargs: object) -> object:
        assert command[:3] == ["mise", "tasks", "ls"], command
        return subprocess.CompletedProcess(command, 0, reply, "")

    monkeypatch.setattr(subprocess, "run", run)


def test_every_task_is_listed_with_its_description(monkeypatch: pytest.MonkeyPatch) -> None:
    _mise(monkeypatch, REPLY)
    listed = inventory()
    assert [t.name for t in listed.tasks] == ["check", "sync"]
    assert listed.tasks[0].description == "Run every gate"
    assert (listed.count, listed.every_task_described) == (2, True)


def test_an_undescribed_task_is_listed_and_turns_the_verdict_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reply = json.loads(REPLY)
    reply.append({"name": "mystery", "description": "", "source": "/r/mise.toml", "usage": ""})
    _mise(monkeypatch, json.dumps(reply))
    listed = inventory()
    assert "mystery" in [t.name for t in listed.tasks]
    assert listed.every_task_described is False


def test_a_malformed_reply_fails_at_the_boundary(monkeypatch: pytest.MonkeyPatch) -> None:
    _mise(monkeypatch, json.dumps([{"description": "a task with no name"}]))
    with pytest.raises(ValidationError):
        inventory()
