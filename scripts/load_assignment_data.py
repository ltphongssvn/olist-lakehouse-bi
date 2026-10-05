"""Upload assignment source data into the Unity Catalog volume.

WHY A SCRIPT AND NOT `databricks fs cp` TYPED BY HAND
Every project operation is a task or a committed script. A hand-typed upload is
behavior living in one shell's history: nobody can rerun it, review it, or learn
from the repo which files the volume is supposed to contain.

WHY THE DATA IS NOT COMMITTED
Source parquet is ~9 MB of binary git cannot diff and would store in full on
every change. It lives in the gitignored staging directory and in the volume; the
repo holds the code that moves it.

THE VOLUME PATH IS RESOLVED, NEVER HARDCODED
Development mode renames the schema, so the effective path differs per target.
Reading it from `bundle validate` means this follows the rename rather than
breaking on it -- the same reason notebooks take the schema name as a parameter.

IDEMPOTENCE, AND ITS HONEST LIMIT
A file is skipped when the remote size matches the local size. That catches
missing and truncated uploads, which are the realistic failures. It does NOT
catch a same-size content change. A checksum would, but the CLI exposes no remote
hash, so comparing would mean downloading every file -- more expensive than
re-uploading. `--force` re-uploads unconditionally when that matters.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from pydantic import BaseModel, ConfigDict, RootModel, ValidationError

from databricks_cli import ResolvedBundle, call, cli

ROOT = Path(__file__).resolve().parent.parent
STAGING = ROOT / "assignments" / "assignment-01" / "data" / "Assignment-01" / "data"

# Local path -> path within the volume. The mapping is explicit rather than a
# directory walk: the volume's contents are a contract the notebooks depend on,
# and "whatever happens to be in the staging directory" is not a contract.
SOURCES = {
    "people10m/people10m-file1.parquet": "people10m/people10m-file1.parquet",
    "names-1880-2024/names_file1.parquet": "names-1880-2024/names_file1.parquet",
    "databricks-blog.json": "databricks-blog.json",
}


class _Vendor(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")


class _Schema(_Vendor):
    name: str
    catalog_name: str


class _Volume(_Vendor):
    name: str


class _Entry(_Vendor):
    name: str = ""
    is_directory: bool = False
    size: int | None = None


class _FsListing(RootModel[tuple[_Entry, ...]]):
    """fs ls answers with a top-level array."""


def volume_root() -> str:
    """Build the volume path from RESOLVED fields only.

    The volume's own schema_name is the literal string
    "${resources.schemas.assignment_01.name}" in this output, not a schema name.
    Cross-resource references resolve at APPLY time, while variable substitution
    resolves at config-load time -- two phases, easily misread as one. Following
    that pointer produced a path containing the reference text verbatim.

    The schema resource's `name` IS resolved, and carries development mode's
    rename, so it is read directly instead.
    """
    resolved = cli(ResolvedBundle, "bundle", "validate", "-t", "dev", "--output", "json", cwd=ROOT)
    schema = _Schema.model_validate(resolved.resources["schemas"]["assignment_01"])
    volume = _Volume.model_validate(resolved.resources["volumes"]["assignment_01_raw"])

    for field, value in (("schema.name", schema.name), ("volume.name", volume.name)):
        if "${" in value:
            raise SystemExit(
                f"{field} is unresolved: {value!r}. "
                "A path built from a reference string would create a directory "
                "named after the reference."
            )

    # THE dbfs: SCHEME IS REQUIRED, NOT DECORATIVE. `fs mkdir` treats a bare
    # /Volumes path as LOCAL and fails creating /Volumes on the laptop, while
    # `fs cp` and `fs ls` tolerate it -- so the scheme goes on every path.
    return f"dbfs:/Volumes/{schema.catalog_name}/{schema.name}/{volume.name}"


def remote_size(path: str) -> int | None:
    """Size of a remote file, or None when it does not exist.

    LISTS THE PARENT AND MATCHES BY NAME, because `fs ls` on a FILE path fails
    with "not a directory" and exit 1 -- it lists directories only. The field is
    `size`; an earlier `file_size` disabled the skip entirely.

    AN ANSWER OF ANOTHER SHAPE REFUSES rather than reading as "absent", which
    would silently re-upload every file.
    """
    parent, _, filename = path.rpartition("/")
    result = subprocess.run(
        ["databricks", "fs", "ls", parent, "--output", "json"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    try:
        listing = _FsListing.model_validate_json(result.stdout or "[]").root
    except ValidationError as error:
        raise SystemExit(
            f"databricks fs ls {parent} answered in a shape this script cannot read"
        ) from error
    for entry in listing:
        if entry.name == filename and not entry.is_directory:
            return entry.size
    return None


def main() -> int:
    force = "--force" in sys.argv
    root = volume_root()
    print(f"volume: {root}\n")

    missing = [s for s in SOURCES if not (STAGING / s).exists()]
    if missing:
        print(f"staging directory: {STAGING}", file=sys.stderr)
        for name in missing:
            print(f"  MISSING {name}", file=sys.stderr)
        return 1

    for source, target in SOURCES.items():
        local = STAGING / source
        destination = f"{root}/{target}"
        local_size = local.stat().st_size

        if not force and remote_size(destination) == local_size:
            print(f"ok      {target} ({local_size:,} bytes)")
            continue

        # CREATE THE PARENT FIRST. `fs cp` does NOT create intermediate
        # directories and fails with "no such directory" -- the volume starts
        # empty, so people10m/ and names-1880-2024/ do not exist.
        #
        # `fs mkdir` is idempotent by design: if the directory already exists,
        # nothing happens. So this runs unconditionally rather than being
        # guarded by an existence check that would itself need testing.
        parent = destination.rsplit("/", 1)[0]
        if parent != root:
            call("fs", "mkdir", parent)

        call("fs", "cp", str(local), destination, "--overwrite")
        print(f"copied  {target} ({local_size:,} bytes)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
