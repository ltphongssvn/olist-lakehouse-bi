"""Every policy input is validated by a contract at the boundary (C.15).

THE INPUTS THAT PREDATED THE CONTRACTS. The task commands were read from
mise.toml as a raw dict and handed on as dicts; the resolved bundle was CLI
output parsed with json.loads and merged straight into the payload; the Nix
policy input was a dict assembled by hand; and the Nix policy's answer was read
by indexing raw JSON. Each now enters through a model.

OPEN WHERE THE VENDOR IS OPEN. The bundle model declares what policies read and
keeps everything else, because the CLI owns that schema and the policies read
more of it than any one script does.
"""

from __future__ import annotations

import pathlib
import subprocess

import pytest
from pydantic import ValidationError

from databricks_cli import ResolvedBundle, cli
from nix_models import NixPolicyInput
from opa import value_of
from task_commands import Command, command_invocations, task_input


def _answer(monkeypatch: pytest.MonkeyPatch, stdout: str, code: int = 0) -> None:
    def fake(args: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args, code, stdout, "")

    monkeypatch.setattr(subprocess, "run", fake)


def test_cli_output_is_validated_before_policy_reads_it(monkeypatch: pytest.MonkeyPatch) -> None:
    """THE RULE: a resolved bundle of the wrong shape never reaches a policy."""
    _answer(monkeypatch, '{"resources": ["not", "an", "object"]}')
    with pytest.raises(SystemExit, match="bundle validate"):
        cli(ResolvedBundle, "bundle", "validate", "-t", "fixture", "--output", "json")


def test_a_resolved_bundle_keeps_what_no_policy_names(monkeypatch: pytest.MonkeyPatch) -> None:
    """THE CONTROL, and the openness: unread fields survive to the policy."""
    _answer(
        monkeypatch,
        '{"workspace": {"host": null, "current_user": {"id": "1"}},'
        ' "resources": {"volumes": {"raw": {"grants": []}}}, "sync": {"paths": ["."]}}',
    )
    dumped = cli(ResolvedBundle, "bundle", "validate").model_dump(mode="json")
    assert dumped["sync"] == {"paths": ["."]}
    assert dumped["workspace"]["current_user"] == {"id": "1"}
    assert dumped["resources"]["volumes"]["raw"] == {"grants": []}


def test_tasks_are_read_through_a_model(tmp_path: pathlib.Path) -> None:
    mise = tmp_path / "mise.toml"
    mise.write_text(
        '[tasks.a]\ndescription = "does a"\nrun = "echo a"\n'
        '[tasks.b]\nrun = ["echo b", "echo c"]\n',
        encoding="utf-8",
    )
    read = task_input(mise)
    assert read.tasks == {"a": "echo a", "b": "echo b\necho c"}
    assert read.descriptions == {"a": "does a"}


def test_a_task_body_that_is_not_text_is_refused(tmp_path: pathlib.Path) -> None:
    mise = tmp_path / "mise.toml"
    mise.write_text("[tasks.a]\nrun = 7\n", encoding="utf-8")
    with pytest.raises(ValidationError):
        task_input(mise)


def test_commands_are_typed() -> None:
    assert command_invocations({"t": "a && b"}) == (
        Command(task="t", argv=("a",)),
        Command(task="t", argv=("b",)),
    )


def test_the_nix_policy_input_is_a_contract() -> None:
    """The 29 values the Nix policy reads, declared, and nothing else accepted."""
    from nix_contract import policy_input
    from nix_models import STORE_VERIFY_NOT_RUN, NixInstallation

    installation = NixInstallation(
        nix_present=False,
        searched=(),
        system="aarch64-darwin",
        store_exists=False,
        receipt_exists=False,
        store_verify_status=STORE_VERIFY_NOT_RUN,
    )
    built = policy_input(installation, flake_present=False)
    assert isinstance(built, NixPolicyInput)
    assert len(NixPolicyInput.model_fields) == 29
    assert NixPolicyInput.model_config.get("extra") == "forbid"


def test_an_answer_from_opa_is_read_through_a_model() -> None:
    """Nothing evaluated is refused; a value is read without indexing raw JSON."""
    assert value_of('{"result": [{"expressions": [{"value": 3}]}]}') == 3
    with pytest.raises(ValueError):
        value_of('{"result": []}')
