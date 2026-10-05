# scripts/command_outcome.py
"""What a command says when it finishes, as data.

WHY THIS EXISTS. Every command here prints prose, so a caller reads it with
grep: presentation filtering, not evidence. check_all.py prints PASS and FAIL,
pr.py prints sentences, and nix_contract.py prints JSON of its own invented
shape. None of it is a declared contract, so nothing downstream can depend on
it without breaking when the wording changes.

2026 practice for a command an agent may run is stream separation -- stdout
carries the payload and nothing else, stderr carries progress and diagnostics --
with a contract field naming the schema, a stable machine code rather than
prose, and deterministic exit codes.

THREE OUTCOMES, NOT TWO, AND THAT IS THE POINT.

A refusal is not a failure: the command worked and denied what was asked. This
repository already draws that line INSIDE the Nix contract -- POLICY_DENIED is
not an error, and absence is an observation rather than an exception -- and then
loses it at the process boundary, where exit 1 means both "the policy said no"
and "the command broke".

    success   0   it did what was asked
    failed    1   the command itself broke
    refused   2   the request or the repository state was not allowed

A caller branches on the exit code without reading a word, and a CI step can
treat a refusal differently from a crash.

WHY THE CODE IS SNAKE_CASE WHILE POLICY CODES ARE NOT.

policies/ emits ERR_TASK_MISE_EXEC and WARN_NIX_UNKNOWN_PLATFORM: a RULE's
identity, read from its annotation by `opa inspect -a`. This code is a
COMMAND's: what the command did, not what a rule found. Two namespaces, kept
visibly distinct so a reader never has to ask which kind of code they are
holding. A command that reports a policy denial carries the rule's codes in
`data`, where they stay the policy's own.
"""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

__all__ = [
    "EXIT_CODES",
    "CommandOutcome",
    "Verdict",
]

Verdict = Literal["success", "refused", "failed"]

# DETERMINISTIC, AND THE ONLY THING A SHELL NEEDS TO READ.
#
# 2 rather than some high number: the convention for "the input was rejected"
# in tools that distinguish it at all, and far enough from 1 that a `|| true`
# cannot swallow a refusal by accident.
EXIT_CODES: dict[Verdict, int] = {"success": 0, "failed": 1, "refused": 2}


class CommandOutcome(BaseModel):
    """One command's result: the only thing it writes to stdout.

    FROZEN AND extra="forbid", like every other contract in this repository. A
    field appearing is as much a contract change as a field vanishing, and both
    fail at the boundary rather than downstream.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    CONTRACT_ID: ClassVar[str] = "command-outcome/v1"

    # THE DOCUMENT NAMES ITS OWN SCHEMA, so a consumer dispatches on this rather
    # than guessing from the shape. Literal, not str: a document claiming
    # another contract is not this one, and must fail to parse as it.
    contract: Literal["command-outcome/v1"] = "command-outcome/v1"

    command: str = Field(min_length=1)
    outcome: Verdict

    # A STABLE MACHINE TOKEN, NEVER PROSE. A caller matches on this, so it must
    # survive rewording the message. The pattern refuses a sentence, a hyphen
    # and a leading digit -- the three shapes that look like a code and are not.
    code: str = Field(pattern=r"^[a-z][a-z0-9_]*$")

    # A CODE WITH NO MESSAGE IS UNACTIONABLE. min_length=1 rather than a
    # default, because an empty message is a mistake rather than a choice.
    message: str = Field(min_length=1)

    # JsonValue, NOT Any. The payload stays open -- each command decides what it
    # carries -- while remaining typed, so mypy keeps working and an object that
    # cannot be serialised fails HERE rather than at the moment of writing.
    #
    # Required but defaulted: every envelope carries a payload, even an empty
    # one, so a consumer never branches on whether the key exists.
    data: dict[str, JsonValue] = Field(default_factory=dict)

    @property
    def exit_code(self) -> int:
        """The process exit code this outcome implies.

        Derived, never stored: a record carrying both an outcome and an exit
        code could contradict itself, and then a reader has to decide which to
        believe.
        """
        return EXIT_CODES[self.outcome]
