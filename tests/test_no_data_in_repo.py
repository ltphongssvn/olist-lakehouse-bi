"""Assert that nothing tracked by git is data, and nothing tracked is junk.

WHY TESTS AND NOT JUST .gitignore
.gitignore filters by FORMAT. This repo's policy is about CONTENT: data never
enters version control. Those are different rules, and the gap is not
hypothetical -- an HTML export of an executed notebook carries names, birth dates
and salaries in its cell outputs, and matches no data extension. `git commit
--no-verify` also defeats the hooks silently; a test in CI does not care what ran
locally.

WHAT THESE ARE, AND WHAT THEY ARE NOT
Structural controls: paths, extensions, and file shape. Content-based PII
detection is scripts/check_pii.py, which reads what is actually in a file. These
catch the realistic mistakes cheaply and are not a substitute for that.

WHY THE INDEX, NOT THE FILESYSTEM
Files on disk are irrelevant; staging is what ships. And prevention is the whole
game -- `git rm` does not remove a file from history, since the commit
containing it stays reachable by hash.
"""

from __future__ import annotations

from pathlib import Path

from gitenv import git

ROOT = Path(__file__).resolve().parent.parent

DATA_EXTENSIONS = {".parquet", ".avro", ".orc", ".csv", ".tsv", ".xlsx", ".html"}

# Paths whose CONTENT is data even when the extension is innocuous.
DATA_PATH_FRAGMENTS = ("/exports/", "/data/")

# Configuration captured from a command: structure, no rows, identity redacted at
# capture. Exempted by exact path so a real dataset under tests/ still reports.
ALLOWED = {"tests/fixtures/bundle-resolved-fixture-target.json"}


def tracked_files() -> list[str]:
    # SCRUBBED ENVIRONMENT, NOT bare subprocess.run.
    #
    # This runs under the pre-commit hook, and git exports GIT_DIR, GIT_WORK_TREE
    # and friends into every hook -- variables that OVERRIDE cwd. Git's own hooks
    # documentation says so: a hook invoking git "in a different working tree of
    # the same repository" must clear them.
    #
    # Today the hook's repository and ROOT coincide, so this works by accident.
    # From a linked worktree they differ, and this check -- which asserts no data
    # is tracked -- would read a different index and pass while inspecting the
    # wrong repository.
    result = git("ls-files", cwd=ROOT)
    assert result.returncode == 0, f"git ls-files failed: {result.stderr}"
    return [line for line in result.stdout.splitlines() if line]


def test_no_data_files_are_tracked() -> None:
    offenders = [
        path
        for path in tracked_files()
        if Path(path).suffix.lower() in DATA_EXTENSIONS and path not in ALLOWED
    ]
    assert not offenders, (
        f"data files are tracked by git: {offenders}. "
        "Data lives in Databricks Volumes; the repo holds the code that moves it."
    )


def test_no_export_or_staging_paths_are_tracked() -> None:
    """The rule the extension check cannot express."""
    offenders = [
        path
        for path in tracked_files()
        if any(fragment in f"/{path}" for fragment in DATA_PATH_FRAGMENTS) and path not in ALLOWED
    ]
    assert not offenders, (
        f"files under exports/ or data/ are tracked: {offenders}. "
        "Exports contain cell outputs, and cell outputs contain the data."
    )


def test_no_junk_files_are_tracked() -> None:
    """Every tracked path must plausibly be a source artifact.

    A file literally named "...." was committed and passed twelve gates. A stray
    shell redirect created it, and nothing asked whether it belonged: every other
    gate checks the CONTENT of files it expects to exist, and none asks whether a
    file should exist at all.

    Empty files are the reliable signal -- an intentional source file has
    something in it.
    """
    junk: list[str] = []

    for path in tracked_files():
        name = Path(path).name
        if not any(character.isalnum() for character in name):
            junk.append(f"{path} (no alphanumeric character in the name)")
            continue

        full = ROOT / path
        if full.is_file() and full.stat().st_size == 0:
            junk.append(f"{path} (empty)")

    assert not junk, "tracked files that do not look like source artifacts:\n  " + "\n  ".join(junk)


def _rendered(path: str, text: str) -> list[str]:
    """Why a notebook is more than source: not Databricks format, or carrying outputs."""
    problems: list[str] = []
    if "# COMMAND" not in text:
        problems.append(f"{path} is not Databricks source format")
    if '"output_type"' in text:
        problems.append(
            f"{path} contains rendered cell output. Notebooks are source; outputs belong to a run."
        )
    return problems


def test_a_rendered_notebook_is_caught() -> None:
    """THE CONTROL: the judge refuses output and non-source, and passes clean source.

    It proves the rule below can fail, so that rule holds whatever notebooks a project
    tracks -- none, in a project just generated (D.61).
    """
    source = "# Databricks notebook source\n# COMMAND ----------\nprint(1)\n"
    assert _rendered("n.py", source) == []
    assert _rendered("n.py", source + '{"output_type": "stream"}\n')
    assert _rendered("n.py", "print(1)\n")


def test_notebooks_are_source_without_rendered_output() -> None:
    """A .py under notebooks/ passes both checks above and can still carry results."""
    notebooks = [p for p in tracked_files() if "/notebooks/" in f"/{p}" and p.endswith(".py")]
    problems = [p for path in notebooks for p in _rendered(path, (ROOT / path).read_text())]
    assert problems == [], problems
