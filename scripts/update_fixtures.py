"""Recapture the resolved-bundle fixture, with identity redacted.

WHY THE FIXTURE EXISTS
Rego unit tests use hand-written input. That tests rule LOGIC and cannot catch a
rule reading a path the real system does not produce -- which happened here: a
rule iterated input.bundle.targets[_].workspace.host, a shape that exists in
databricks.yml and not in resolved output, so it could never fire while 21 tests
passed. This fixture is captured from the real command so that class of drift
breaks a test instead of silently killing a rule.

WHY IT CAPTURES THE `fixture` TARGET
It captured `dev` first, and that made the fixture identity-dependent: 19
occurrences across 8 fields, because dev mode prefixes resource names with the
deployer and deploys to a user-scoped path. CI runs as a service principal and a
laptop runs as a person, so the same bundle resolved differently and the check
failed in CI while passing locally.

Scrubbing those fields was a losing game -- the next bundle change adds another
place for identity to appear. The snapshot-testing guidance is to INJECT a
deterministic input rather than scrub nondeterministic output, so `fixture` is a
synthetic target declaring no mode and no current_user. It resolves identically
for every deployer and is never deployed.

Redaction remains as a belt-and-braces check: if an address ever reappears, the
capture refuses to write rather than committing it.

WHY A TASK AND NOT A SHELL REDIRECT
`databricks bundle validate --output json > fixture.json` was how this was first
captured, and it committed three email addresses. A redirect has no redaction
step and no way to acquire one. The capture must own it.
"""

from __future__ import annotations

import difflib
import json
import re
import subprocess
import sys
from pathlib import Path

from pydantic import JsonValue, TypeAdapter

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "bundle-resolved-fixture-target.json"

REDACTED_USER = "fixture-user@example.invalid"
EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


# SCRUBBERS.
#
# This is an approval test -- a committed golden file compared against generated
# output -- and the established discipline for it is to scrub non-deterministic
# values. The rule, stated in the snapshot-testing literature: scrub only times,
# dates, identifiers and randomly generated things, and only when they are
# produced INSIDE the subject under test.
#
# bundle.git qualifies exactly. The CLI populates it from ambient git state, so a
# fixture containing it goes stale on every branch. That is not drift detection;
# it is noise that teaches people to run fixtures:update reflexively without
# reading the diff, at which point the check stops meaning anything.
#
# The tests assert on STRUCTURE -- targets collapsed, workspace.host absent,
# resources carrying grants and lifecycle. None reads git state.
#
# NOTHING ELSE IS SCRUBBED. Every other field is what the bundle actually
# resolves to, and hiding one to quiet a diff would defeat the purpose.
SCRUBBED_PATHS = (
    # THE ONLY REMAINING SCRUBBER, and the only one that can still fire.
    #
    # bundle.git is populated by the CLI from ambient git state -- branch and
    # origin -- so a fixture containing it goes stale on every branch. That is
    # the "global state dependency in the SUT" the snapshot-testing guidance
    # warns about, and there is no target setting that removes it.
    ("bundle", "git"),
    # WHO AUTHENTICATED, WHICH NO TARGET SETTING CAN CHANGE.
    #
    # The `fixture` target removed identity from paths, resource names, tags and
    # the name prefix -- everything a target controls. It does NOT remove
    # workspace.current_user, which the CLI populates from the credentials in
    # use: an email and short_name locally, an application UUID and
    # "cscie103_ci" on a CI service principal, plus entirely different group
    # memberships and entitlements.
    #
    # This scrubber was DELETED once, on the assumption that switching targets
    # covered it. CI proved otherwise on the next push. The assumption was
    # testable and I did not test it -- capturing under a second identity is
    # exactly what CI does, and what I should have done before removing it.
    #
    # presets.name_prefix and presets.tags stay removed: the fixture target
    # declares no mode, so those genuinely do not exist in its output.
    ("workspace", "current_user"),
)


# THE CLI'S ANSWER IS AN OPEN TREE, validated as a JSON object where it enters.
_OBJECT = TypeAdapter(dict[str, JsonValue])


def scrub_nondeterministic(document: dict[str, JsonValue]) -> dict[str, JsonValue]:
    for path in SCRUBBED_PATHS:
        node: JsonValue = document
        for key in path[:-1]:
            node = node.get(key) if isinstance(node, dict) else None
            if node is None:
                break
        if isinstance(node, dict):
            node.pop(path[-1], None)
    return document


def redact(node: JsonValue) -> JsonValue:
    """Replace every email-shaped value, at any depth.

    Recursive rather than a single pass over the serialised text, so a value
    nested inside a structure the schema gains later is still caught. example.invalid
    is the RFC-reserved TLD, guaranteed never to resolve.
    """
    if isinstance(node, dict):
        return {key: redact(value) for key, value in node.items()}
    if isinstance(node, list):
        return [redact(value) for value in node]
    if isinstance(node, str):
        return EMAIL_PATTERN.sub(REDACTED_USER, node)
    return node


def capture() -> str:
    result = subprocess.run(
        # THE FIXTURE TARGET, NOT dev. dev applies a name prefix and a user-scoped
        # root path, so its resolved output embeds the deployer in 19 places and
        # differs between a laptop and a CI service principal. `fixture` declares
        # no mode and no current_user, so it resolves identically for everyone.
        ["databricks", "bundle", "validate", "-t", "fixture", "--output", "json"],
        capture_output=True,
        text=True,
        check=False,
        cwd=ROOT,
    )
    if result.returncode != 0:
        print(result.stderr.strip(), file=sys.stderr)
        raise SystemExit("bundle validate failed; fixture not updated")

    redacted = redact(scrub_nondeterministic(_OBJECT.validate_json(result.stdout)))
    serialised = json.dumps(redacted, indent=2, sort_keys=True) + "\n"

    # A redaction that silently missed would commit the address it was written to
    # remove. Verify before writing rather than after.
    remaining = EMAIL_PATTERN.findall(serialised)
    unexpected = [address for address in remaining if address != REDACTED_USER]
    if unexpected:
        raise SystemExit(
            f"redaction incomplete: {len(unexpected)} address(es) survived. Fixture NOT written."
        )

    return serialised


def main() -> int:
    """Write the fixture, or with --check, fail if the committed one is stale.

    THE --check MODE EXISTS BECAUSE A STALE FIXTURE FAILS CONFUSINGLY.
    Adding a grants block to a volume in the bundle left the committed fixture
    describing the previous shape, and the test reported "volumes.X has no grants
    key" -- which reads as a bundle defect and is actually a capture that was
    never refreshed. Diffing says so directly.

    Same pattern as contract drift checking: generate, compare, and make the
    committed artifact authoritative by failing when it disagrees.
    """
    serialised = capture()

    if "--check" in sys.argv:
        if not FIXTURE.exists():
            raise SystemExit(f"{FIXTURE.relative_to(ROOT)} does not exist; run fixtures:update")
        committed = FIXTURE.read_text()
        if committed != serialised:
            # PRINT THE DIFF, NOT JUST THE VERDICT.
            #
            # The first version said only that the fixture differed. When it then
            # failed in CI while passing locally, the only way to learn WHY was
            # to go digging in run logs -- which is an alarm, not a diagnostic.
            # A check that cannot explain itself sends people to the wrong place.
            diff = difflib.unified_diff(
                committed.splitlines(keepends=True),
                serialised.splitlines(keepends=True),
                fromfile="committed",
                tofile="regenerated",
                n=1,
            )
            print("".join(diff), file=sys.stderr)
            raise SystemExit(
                f"{FIXTURE.relative_to(ROOT)} does not match the current bundle.\n"
                "If the diff above is a real bundle change, refresh it:\n"
                "  mise run fixtures:update\n"
                "If it is nondeterminism -- an identity, a branch, a timestamp -- "
                "it belongs in SCRUBBED_PATHS or the redactor, not in the fixture."
            )
        print("fixture matches the current bundle")
        return 0

    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_text(serialised)
    print(f"wrote {FIXTURE.relative_to(ROOT)} ({len(serialised):,} bytes, identity redacted)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
