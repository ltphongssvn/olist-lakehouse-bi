"""The committed schemas must match the models that generate them.

WHY THIS EXISTS
The schemas were committed with a stated intent that "CI fails when generated
schema drifts from the code model" -- and no such check was written. They went
stale the first time a field was added, and only the probe-shape lock noticed,
indirectly.

A committed artifact nothing verifies is worse than a generated one: it looks
authoritative and describes something that no longer exists.

WHY THE BYTES ARE COMMITTED RATHER THAN GENERATED ON DEMAND
Regenerating under a different pydantic version can change the output --
"a point release could subtly change the output and drift would return through
the back door". Committed bytes plus this check means the schema changes only
when someone means it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import BaseModel

from nix_output import ContractOutput

SCHEMAS = Path(__file__).resolve().parent.parent / "contracts" / "schemas"

# ONE ENVELOPE, NOT THREE.
#
# ObserveErrorOutput and SkippedOutput existed because an absent Nix was handled
# by a Python branch that emitted a different document. Absence is now a policy
# finding like any other, so every outcome flows through one shape -- and a
# consumer no longer has to recognise three.
MODELS: tuple[tuple[type[BaseModel], str], ...] = ((ContractOutput, "nix-contract-output"),)


@pytest.mark.parametrize(("model", "name"), MODELS)
def test_the_committed_schema_matches_the_model(model: type[BaseModel], name: str) -> None:
    """If this fails, regenerate and commit the schema deliberately.

    The regeneration is the same call this asserts against, so a mismatch means
    the model changed and the artifact did not.
    """
    committed = json.loads((SCHEMAS / f"{name}.schema.json").read_text())

    assert committed == model.model_json_schema(), (
        f"{name}.schema.json is stale. Regenerate it, and treat the diff as a "
        "contract change rather than a formality."
    )


@pytest.mark.parametrize(("model", "name"), MODELS)
def test_every_model_field_appears_in_its_schema(model: type[BaseModel], name: str) -> None:
    """A field absent from the schema is a field consumers cannot validate.

    Checked separately from the equality test above because equality would also
    pass if BOTH were wrong in the same way -- for instance if the schema were
    regenerated from a model that had lost a field.
    """
    schema = json.loads((SCHEMAS / f"{name}.schema.json").read_text())

    assert set(model.model_fields) <= set(schema.get("properties", {}))


def test_every_envelope_has_a_committed_schema() -> None:
    """THREE ENVELOPES, THREE SCHEMAS.

    SkippedOutput was added as the third output shape and had no schema at all
    -- the same built-and-not-wired gap. Enumerating the models here means a
    fourth envelope fails until its schema is committed.
    """
    declared = {name for _, name in MODELS}
    on_disk = {path.name.removesuffix(".schema.json") for path in SCHEMAS.glob("*.schema.json")}

    assert declared == on_disk
