# tests/test_project_identity.py
"""Project identity is declared once, read by code, set where code cannot read it (D.52).

source:search found the name, catalog, reader group, CI principal, default schema and
repository hard-coded across 20 files. A generated project would inherit all of them,
and Jinja twins of live files would write every identity-bearing file twice.

ONE DECLARATION, contracts/project-identity.toml: scripts derive their relations from
it; files that cannot read it hold declared SLOTS, and identity:set rewrites only those.
Rego decides that no identity literal lives anywhere else; these prove it bites.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from bootstrap_identity import desired
from check_prereqs import required
from opa import denials
from project_identity import (
    IdentityInventory,
    Occurrence,
    load,
    main,
    observe,
    render,
    set_identity,
)

REPO = Path(__file__).resolve().parent.parent
ENTRYPOINT = "data.identity.deny"
PROBE = {
    "name": "probe-project",
    "catalog": "probe_catalog",
    "reader_group": "probe_readers",
    "ci_principal": "probe-ci",
    "default_schema": "probe_schema",
    "repository": "https://github.com/example/probe-project",
}


def _decide(inventory: IdentityInventory) -> list[str]:
    return denials(ENTRYPOINT, {"identity_inventory": inventory.model_dump(mode="json")})


def test_scripts_derive_identity_relations_from_the_declaration() -> None:
    probe = load(REPO).model_copy(update=PROBE)
    wanted = desired(probe)
    assert wanted.groups == ("probe_readers",)
    assert wanted.service_principals == ("probe-ci",)
    assert wanted.memberships == {"probe_readers": ("probe-ci",)}
    assert wanted.catalog_grants == {"probe_catalog": {"probe_readers": ("USE_CATALOG", "BROWSE")}}
    needed = required(probe)
    assert (needed.catalog, needed.group) == ("probe_catalog", "probe_readers")


def test_a_stray_identity_literal_is_refused() -> None:
    exempt = load(REPO).exempt
    stray = Occurrence(path="scripts/new_tool.py", number=3, value="cscie103_catalog", slot=False)
    found = _decide(IdentityInventory(exempt=exempt, occurrences=(stray,)))
    assert any("scripts/new_tool.py" in denial for denial in found), found
    slotted = Occurrence(path="databricks.yml", number=174, value="cscie103_catalog", slot=True)
    derived = Occurrence(path="uv.lock", number=1, value="cscie103-data-engineering", slot=False)
    assert _decide(IdentityInventory(exempt=exempt, occurrences=(slotted, derived))) == []
    assert any("ERR_IDENTITY_INPUT_MISSING" in denial for denial in denials(ENTRYPOINT, {}))


def test_the_repository_holds_identity_only_in_slots() -> None:
    assert _decide(observe(REPO)) == []


def test_identity_set_rewrites_every_slot_and_nothing_else(tmp_path: Path) -> None:
    declared = load(REPO)
    slotted = sorted({slot.path for slot in declared.slots})
    for name in [*slotted, "contracts/project-identity.toml"]:
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / name, tmp_path / name)
    before = {name: (tmp_path / name).read_text(encoding="utf-8") for name in slotted}
    target = declared.model_copy(update=PROBE)
    set_identity(tmp_path, target)
    for name in slotted:
        rewrites = {
            render(slot, declared): render(slot, target)
            for slot in declared.slots
            if slot.path == name
        }
        old_lines = before[name].splitlines()
        assert all(line in old_lines for line in rewrites), (name, rewrites)
        expected = [rewrites.get(line, line) for line in old_lines]
        assert (tmp_path / name).read_text(encoding="utf-8").splitlines() == expected, name
    after = load(tmp_path)
    values = (after.name, after.catalog, after.reader_group, after.ci_principal)
    assert (*values, after.default_schema, after.repository) == tuple(PROBE.values())


def test_identity_set_refuses_a_spec_it_cannot_apply(tmp_path: Path) -> None:
    """A spec that fails the contract writes nothing: the refusal is all of the outcome."""
    spec = tmp_path / "identity.toml"
    spec.write_text('name = "Not A Valid Name"\n', encoding="utf-8")
    declaration = REPO / "contracts" / "project-identity.toml"
    before = declaration.read_bytes()
    assert main([str(spec)]) == 2
    assert declaration.read_bytes() == before
