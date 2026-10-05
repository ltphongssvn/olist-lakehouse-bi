"""Refuse tracked files that look like accidents.

WHY THIS EXISTS
A zero-byte file named `nix_contract` -- the debris of a mistyped shell
redirect -- sat at the repository root and was swept into a commit by
`git add -A`. No gate saw it: not the secret scan, not the PII scan, not
check:no-data-in-repo, not lint. It surfaced only because the commit output
listed it and someone read the list.

The same accident is common enough to be recognisable: one project records "a
Mach-O executable from a one-off test harness in the repo root was accidentally
swept into PR #54 by git add -A", another removed "7 stray files" from a
dogfooding run.

PROPERTIES, NOT AN ALLOWLIST
The obvious fix is a list of permitted root entries. This repository has
watched that shape go stale three times, so the check asks what makes a file
look accidental instead:

  EMPTY. A tracked zero-byte file carries nothing. The legitimate exceptions
  are marker files, which are named for the purpose.

  NO EXTENSION AND NO KNOWN NAME. Root-level files are either dotfiles,
  conventional extensionless names (LICENSE, Makefile), or they have a
  suffix. `nix_contract` was none of those -- it was a script name with the
  .py lost to a redirect.

Neither property needs maintaining when a real file is added, because a real
file has content and a name that fits one of those shapes.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Extensionless files that are conventional at a repository root. Short by
# design: anything else without a suffix is more likely a mistake than a
# convention, and the failure message says how to record a real exception.
CONVENTIONAL_NAMES = frozenset(
    {
        "LICENSE",
        "LICENCE",
        "Makefile",
        "Dockerfile",
        "CODEOWNERS",
        "NOTICE",
        "AUTHORS",
        "Justfile",
    }
)

# Files that are legitimately empty because their NAME is the whole content.
MARKER_NAMES = frozenset({".gitkeep", ".keep", ".nojekyll", "py.typed"})


def tracked_files() -> list[Path]:
    """Every file git tracks, from git itself rather than a directory walk.

    A walk would see build output, virtualenvs and caches -- none of which are
    the problem. What matters is what has been COMMITTED, because that is what
    an accident becomes permanent as.
    """
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        capture_output=True,
        text=True,
        check=False,
        cwd=ROOT,
    )
    if result.returncode != 0:
        raise SystemExit(f"git ls-files failed: {result.stderr.strip()}")

    return [Path(name) for name in result.stdout.split("\0") if name]


def looks_accidental(path: Path) -> str | None:
    """Why this file looks like debris, or None if it looks deliberate."""
    absolute = ROOT / path

    if not absolute.is_file():
        return None

    if absolute.stat().st_size == 0 and path.name not in MARKER_NAMES:
        return "tracked and empty; a zero-byte file carries nothing"

    # Only the root is checked for naming. Deeper paths are inside directories
    # someone created on purpose, and extensionless files are ordinary there.
    if len(path.parts) == 1 and not path.suffix:
        if path.name.startswith("."):
            return None
        if path.name in CONVENTIONAL_NAMES:
            return None
        return "at the repository root with no extension and no conventional name"

    return None


def main() -> int:
    findings = [
        (path, reason) for path in tracked_files() if (reason := looks_accidental(path)) is not None
    ]

    if findings:
        print(f"{len(findings)} file(s) look accidental:", file=sys.stderr)
        for path, reason in sorted(findings):
            print(f"  {path}: {reason}", file=sys.stderr)
        print(
            "\nIf one is deliberate, give it a suffix, put it in a directory, or "
            "add its name to CONVENTIONAL_NAMES or MARKER_NAMES with a reason.",
            file=sys.stderr,
        )
        return 1

    print(f"repo hygiene ok: {len(tracked_files())} tracked files, none look accidental")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
