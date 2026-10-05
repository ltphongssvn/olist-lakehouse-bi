# scripts/any_models.py
"""any-inventory/v1: every Any the code writes or implies, as validated data.

THE CONTRACT HALF OF THE PAIR. The observer produces this; the policy decides
over it. An inventory with no files scanned is refused here, because a scan over
nothing passes and proves nothing.
"""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, PositiveInt


class AnyUse(BaseModel):
    """One Any: written in source, or implied by a missing annotation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str = Field(min_length=1)
    line: PositiveInt
    # EXPLICIT is the word in source; IMPLICIT is a parameter or a return with
    # no annotation, which mypy reads as Any without the word appearing.
    form: Literal["explicit", "implicit"]
    name: str = Field(min_length=1)


class AnyInventory(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    CONTRACT_ID: ClassVar[str] = "any-inventory/v1"

    contract: Literal["any-inventory/v1"] = "any-inventory/v1"
    files_scanned: PositiveInt
    uses: tuple[AnyUse, ...]
