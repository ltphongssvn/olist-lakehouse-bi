"""Remediation as data an agent can act on -- and a classification of what it may act on.

WHY THIS EXISTS
ContractProblem.remediation was PROSE. An agent wanting to fix a problem had to
parse an English sentence, which is the string-matching fragility this
repository removes everywhere else. Machine-readable codes without
machine-readable actions is half a design.

WHY THE CONTRACT STILL DOES NOT EXECUTE ANY OF IT
The obvious next step -- have the agent run the installer and re-observe -- is
the one the 2026 guidance gates specifically. The boundary is stated the same
way across sources: "investigation can and should be autonomous; execution of a
destructive change should be gated", and the mental model is "automated
investigation, human-approved remediation", not self-healing. OWASP puts it as
"separate decision-making from execution for irreversible operations".

Auto-action is defensible only inside "narrow scope, reversible actions, and a
signed audit trail". Installing Nix creates an encrypted APFS volume, a launchd
daemon, 32 system users, and edits /etc/fstab, /etc/zshrc and /etc/bashrc. It is
neither narrow nor reversible in place.

THE LADDER, AND WHERE EACH PROBLEM SITS
The established model is three rungs -- alert, approve, auto-act -- where "rules
earn their way up as confidence grows" and "a defensible policy keeps the
reversible, low-risk classes automatable and gates the rest".

Every problem this contract can detect requires a privileged, system-wide
change. So nothing here is AUTO. That is a finding rather than a limitation: a
tier no problem currently occupies is honest, and it keeps the classification
meaningful if a reversible problem is added later.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "ActionableError",
    "Autonomy",
    "ContractProblem",
    "Remediation",
]


class Autonomy(StrEnum):
    """How much an agent may do about a problem, without being told.

    ALERT     report it; no command exists that fixes it unattended
    APPROVE   a command exists, and a human authorises it before it runs
    AUTO      narrow, reversible, auditable -- safe to run unattended

    FAIL CLOSED: a problem with no explicit tier is ALERT. The guidance is
    explicit that a system should "fail closed when risk classification,
    approval validation, policy lookup, or audit logging fails".
    """

    ALERT = "alert"
    APPROVE = "approve"
    AUTO = "auto"


class ActionableError(Exception):
    """An exception that carries the same three fields a problem does.

    WHY EXCEPTIONS NEEDED THIS TOO
    ContractProblem has carried code + message + remediation for a while, but
    EXCEPTIONS were bare strings -- so every failure path got hand-written prose,
    and the same "diagnostic discarded" defect was fixed four separate times in
    four modules. Writing a better string each time is the treadmill; giving
    errors a shape is the fix.

    The structure is the documented one: "state the problem, guide the user on
    fixing it". And for this codebase specifically it matters twice over, because
    a CLI now "serves humans and AI agents from one binary" -- and "agents need
    remediation DECLARED, not inferred".

    tests/test_nix_errors.py enumerates every subclass and fails if one omits a
    code or a remediation, which is the "automated coverage that prevents new
    errors from going unclassified".
    """

    #: Machine-readable, branchable. Subclasses MUST set it.
    code: str = ""

    def __init__(self, message: str, *, remediation: str, **context: object) -> None:
        if not self.code:
            raise ValueError(f"{type(self).__name__} declares no code")
        if not remediation:
            raise ValueError(f"{type(self).__name__} was raised with no remediation")

        super().__init__(message)
        self.message = message
        self.remediation = remediation
        #: Structured detail, so a caller need not parse it back out of the text.
        self.context = context

    def __str__(self) -> str:
        """Problem, then fix. Never one without the other."""
        return f"[{self.code}] {self.message}\n  fix: {self.remediation}"

    def as_dict(self) -> dict[str, object]:
        """For a machine consumer, which should not parse __str__."""
        return {
            "code": self.code,
            "message": self.message,
            "remediation": self.remediation,
            "context": self.context,
        }


class ContractProblem(BaseModel):
    """One thing wrong, in a form both an agent and a person can use.

    MOVED HERE FROM nix_contract, because a problem IS a code plus a message
    plus a Remediation -- it belongs beside the thing it carries. Leaving it in
    nix_contract would have forced an import cycle the moment nix_output needed
    to type its `problems` field.
    """

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    code: str
    message: str
    remediation: Remediation


class Remediation(BaseModel):
    """What to do about a problem, in a form an agent can act on.

    command IS NOT RUN BY THIS PROGRAM. It is a proposal. The separation is the
    point: this module decides, something else executes, and the something else
    is gated by `autonomy`.
    """

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    description: str = Field(description="What a person should understand")
    command: str | None = Field(
        default=None,
        description="The exact command that would fix it, or None if no single command does",
    )
    autonomy: Autonomy = Autonomy.ALERT
    reversible: bool = Field(
        default=False,
        description="Whether the command can be undone in place, which gates AUTO",
    )
    privileged: bool = Field(
        default=True,
        description="Whether it requires elevation, which forbids AUTO",
    )

    def model_post_init(self, _context: object) -> None:
        """A classification that contradicts itself is refused.

        AUTO on a privileged or irreversible action would be a tier asserting
        safety the action does not have -- and a wrong classification is worse
        than none, because something downstream will trust it.
        """
        if self.autonomy is Autonomy.AUTO and (self.privileged or not self.reversible):
            raise ValueError(
                "AUTO requires a narrow, reversible, unprivileged action; "
                f"privileged={self.privileged} reversible={self.reversible}"
            )
        if self.autonomy is not Autonomy.ALERT and self.command is None:
            raise ValueError(f"autonomy={self.autonomy} promises a command, but none is given")
