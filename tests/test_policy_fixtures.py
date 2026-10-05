"""Assert the bundle policy reads shapes the real system actually produces.

WHY THIS EXISTS, AND WHY IT IS PYTHON RATHER THAN REGO
The Rego unit tests use input fixtures written by hand. That tests rule LOGIC,
which is necessary and not sufficient: a rule can be logically perfect and read a
path that does not exist, in which case it iterates nothing and denies nothing.

That happened here. A rule read input.bundle.targets[_].workspace.host -- the
structure of databricks.yml as WRITTEN -- while `bundle validate --output json`
reports the bundle as RESOLVED, with targets already collapsed into a flat
workspace block. The rule could never fire. It passed every test, because the
tests used fixtures invented from the same wrong assumption. Two errors in the
same direction cancel out and look like correctness.

The industry name for the failure is fixture drift, and the consequence is worse
than no gate: a check that passes what the real system would reject erodes trust
faster than having no check at all.

So these assertions run against tests/fixtures/bundle-resolved-fixture-target.json, captured
from the actual command. `mise run fixtures:update` regenerates it, and
check:fixtures fails the build when the captured shape no longer matches what the
CLI produces.
"""

from __future__ import annotations

import json
import pathlib

import pytest
from pydantic import JsonValue, TypeAdapter

ROOT = pathlib.Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "bundle-resolved-fixture-target.json"

# OPEN VENDOR JSON, VALIDATED AS JSON. These tests assert ABSENCES -- no targets,
# no catalogs -- and a model ignoring unknown keys would drop exactly what they
# look for. The policy-input contract that will model this belongs to C.15.
OBJECT = TypeAdapter(dict[str, JsonValue])


def _object(value: JsonValue, where: str) -> dict[str, JsonValue]:
    assert isinstance(value, dict), f"{where} is not an object"
    return value


@pytest.fixture(scope="module")
def resolved() -> dict[str, JsonValue]:
    return OBJECT.validate_json(FIXTURE.read_text())


def test_targets_are_collapsed_in_resolved_output(resolved: dict[str, JsonValue]) -> None:
    """The exact assumption that killed a rule.

    If a future CLI starts emitting targets in resolved output, the host rule
    needs revisiting -- so this asserts the collapse rather than trusting it.
    """
    assert "targets" not in _object(resolved.get("bundle", {}), "bundle")
    assert "targets" not in resolved


def test_workspace_is_a_flat_block(resolved: dict[str, JsonValue]) -> None:
    """Where workspace.host WOULD appear, which is what the rule must read."""
    assert "workspace" in resolved
    assert isinstance(resolved["workspace"], dict)


def test_the_bundle_does_not_pin_a_host(resolved: dict[str, JsonValue]) -> None:
    """The four-CI-failure bug, asserted against real output rather than a guess."""
    assert _object(resolved["workspace"], "workspace").get("host") is None, (
        "workspace.host is set. That forces host-based profile resolution, "
        "which needs a .databrickscfg that CI does not have."
    )


def test_resource_shapes_match_what_the_policy_reads(resolved: dict[str, JsonValue]) -> None:
    """Five rules read resources.<kind>.<name>.grants and .lifecycle.

    Unlike the host rule, these paths were correct -- but nothing proved it.
    """
    resources = _object(resolved.get("resources", {}), "resources")
    assert {"schemas", "volumes"} <= set(resources)

    for kind in ("schemas", "volumes"):
        for name, value in _object(resources[kind], kind).items():
            spec = _object(value, f"{kind}.{name}")
            assert "grants" in spec, f"{kind}.{name} has no grants key to evaluate"
            assert "lifecycle" in spec, f"{kind}.{name} has no lifecycle key to evaluate"


def test_no_catalogs_are_declared(resolved: dict[str, JsonValue]) -> None:
    """Catalogs are always CREATED and cannot be bound (databricks/cli#4842)."""
    assert "catalogs" not in _object(resolved.get("resources", {}), "resources")


@pytest.mark.integration
def test_fixture_is_identity_independent() -> None:
    """The same bundle must produce the same fixture for any deployer.

    THIS IS THE CHECK WHOSE ABSENCE COST THREE CI RUNS.
    The fixture captured `dev` at first, whose resolved output embeds the
    deployer in 19 places. Switching to the `fixture` target removed identity
    from paths, resource names, tags and the name prefix -- everything a target
    controls -- so I concluded the scrubbers were dead and deleted them.

    They were not. workspace.current_user is populated from the CREDENTIALS in
    use, which no target setting changes, and CI failed on the next push. The
    assumption was testable; I tested it only afterwards, by hand.

    MARKED integration BECAUSE IT SHELLS OUT TO THE CLI. It needs network and
    Databricks auth, and `test` runs in check:offline behind the pre-push hook.
    A test requiring credentials there would break the offline guarantee, and a
    hook that fails on a plane is a hook people bypass.

    The substituted identity is synthetic -- a zero UUID, `some_sp` -- rather
    than the real service principal's, so this does not hardcode the identity it
    exists to be independent of.
    """
    import subprocess

    from update_fixtures import redact, scrub_nondeterministic

    raw = subprocess.run(
        ["databricks", "bundle", "validate", "-t", "fixture", "--output", "json"],
        capture_output=True,
        text=True,
        check=True,
        cwd=ROOT,
    ).stdout

    document = OBJECT.validate_json(raw)
    _object(document["workspace"], "workspace")["current_user"] = {
        "active": True,
        "displayName": "some-service-principal",
        "domain_friendly_name": "some-service-principal",
        "emails": [
            {"primary": True, "type": "work", "value": "00000000-0000-0000-0000-000000000000"}
        ],
        "id": "000000000000000",
        "short_name": "some_sp",
        "userName": "00000000-0000-0000-0000-000000000000",
    }

    as_other_identity = (
        json.dumps(redact(scrub_nondeterministic(document)), indent=2, sort_keys=True) + "\n"
    )

    assert as_other_identity == FIXTURE.read_text(), (
        "the fixture differs when captured under another identity. Something "
        "identity-dependent survives the scrubbers, and CI will fail on it."
    )
