"""Configured hooks stay installed, and the trailer hook stays configured (C.18).

LEFTHOOK RE-SYNCS HOOKS ITSELF, while auto-install is on: adding commit-msg to
lefthook.yml reached every checkout the next time any hook ran. That protection
is incidental unless something checks it stays enabled -- and that the
commit-msg job running plan:trailers, G.4's zero-latency refusal, stays there.

THE CONFIGURATION IS READ AS LEFTHOOK READS IT, through `lefthook dump`, which
omits defaults: no_auto_install appears only when someone turns it on.
"""

from __future__ import annotations

import pathlib

from pydantic import JsonValue

from hooks import Hooks, from_dump, observe
from opa import denials

ROOT = pathlib.Path(__file__).resolve().parent.parent
TRAILERS: dict[str, JsonValue] = {
    "hook": "commit-msg",
    "name": "plan steps",
    "run": "mise run plan:trailers {1}",
}


def _denied(hooks: Hooks | None) -> list[str]:
    payload: dict[str, JsonValue] = {}
    if hooks is not None:
        payload["hooks"] = hooks.model_dump(mode="json")
    return [d for d in denials("data.hooks.deny", payload) if d.startswith("[ERR_HOOKS_")]


def _hooks(*jobs: dict[str, JsonValue], auto_install: bool = True) -> Hooks:
    listed: list[JsonValue] = [*jobs]
    return Hooks.model_validate({"auto_install": auto_install, "jobs": listed})


def test_the_hooks_install_themselves_and_run_the_trailers() -> None:
    """THE REAL CONFIGURATION, as lefthook reads it, through the real policy."""
    hooks = observe(ROOT)
    assert hooks.auto_install
    assert _denied(hooks) == []


def test_a_configuration_keeping_both_is_allowed() -> None:
    """THE CONTROL: a policy refusing everything would pass the rest."""
    assert _denied(_hooks(TRAILERS)) == []


def test_disabling_auto_install_is_denied() -> None:
    denied = _denied(_hooks(TRAILERS, auto_install=False))
    assert any(d.startswith("[ERR_HOOKS_AUTO_INSTALL_DISABLED]") for d in denied), denied


def test_dropping_the_trailer_hook_is_denied() -> None:
    lint: dict[str, JsonValue] = {"hook": "pre-commit", "name": "lint", "run": "mise run lint"}
    denied = _denied(_hooks(lint))
    assert any(d.startswith("[ERR_HOOKS_TRAILERS_UNHOOKED]") for d in denied), denied


def test_an_absent_observation_is_denied() -> None:
    assert any(d.startswith("[ERR_HOOKS_UNOBSERVED]") for d in _denied(None))


def test_the_dump_is_read_as_lefthook_writes_it() -> None:
    """Defaults are omitted, settings sit beside hooks, and only git's hooks are hooks."""
    dump = (
        '{"no_auto_install": true, "colors": false,'
        ' "commit-msg": {"jobs": [{"name": "plan steps", "run": "mise run plan:trailers {1}"}]}}'
    )
    hooks = from_dump(dump)
    assert not hooks.auto_install
    assert [(j.hook, j.run) for j in hooks.jobs] == [("commit-msg", "mise run plan:trailers {1}")]
    assert from_dump('{"pre-push": {"jobs": []}}').auto_install
