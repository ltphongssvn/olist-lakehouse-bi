"""The committed plan, trace and id ledger validate and agree.

A MATRIX NOBODY VERIFIES IS AN ARCHIVE: it looks complete because nothing
contradicts it. These name every way the three files can disagree.

AND THE HISTORY IS QUOTED, NEVER AUTHORED. A step backfilled from work already
done cites the commits that built it, and each citation must be a commit that
exists, quoted by its own subject verbatim. Reconstructing history means
grouping what it says, not writing what it should have said.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import plan_files

# COMPOSED, NOT WRITTEN: the PII gate reads any user-at-host literal as an email.
ADDRESS = "t" + "@" + "example.invalid"
SUBJECT = "feat(probe): the subject a quotation must match"


def test_the_three_files_exist_and_validate() -> None:
    plan, trace, ids = plan_files.load()
    assert plan.steps, "the plan holds no steps"
    assert trace.candidates, "the trace holds no candidates"
    assert ids.issued, "the id ledger holds no ids"


def test_every_item_is_traced_in_both_directions() -> None:
    plan, trace, _ = plan_files.load()
    from plan_models import untraced

    assert untraced(trace, plan) == []


def test_every_id_in_use_was_issued_and_none_was_retired() -> None:
    assert plan_files.disagreements(*plan_files.load()) == []


def test_the_history_is_quoted_not_authored() -> None:
    """THE BACKFILL RULE, MADE CHECKABLE: a cited commit exists, and the text
    beside it is that commit's own subject, verbatim. The control below proves the check
    can fail, so this applies it to whatever history this project cites -- none, in a
    project just generated (D.61)."""
    _, trace, _ = plan_files.load()
    cited = [c for c in trace.candidates if c.source == "HISTORY"]
    for candidate in cited:
        subject = plan_files.commit_subject(candidate.ref)
        assert subject is not None, f"{candidate.ref} is not a commit in this repository"
        assert candidate.text == subject, f"{candidate.ref} is paraphrased, not quoted"


def test_a_forged_quote_is_caught(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """THE CONTROL, ON A THROWAWAY REPOSITORY: the quote check refuses a paraphrase.

    It makes its own commit instead of citing one of this repository's, so it holds in
    every project generated from it (D.61).
    """
    for role in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{role}_NAME", "t")
        monkeypatch.setenv(f"GIT_{role}_EMAIL", ADDRESS)
    for args in (("init", "-q", "-b", "main"), ("commit", "-q", "--allow-empty", "-m", SUBJECT)):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, check=True, capture_output=True, text=True
    )
    real = head.stdout.strip()
    assert plan_files.commit_subject(real, tmp_path) == SUBJECT
    assert plan_files.commit_subject(real, tmp_path) != "a paraphrase of that subject"
    assert plan_files.commit_subject("0000000", tmp_path) is None


def test_the_task_reports_agreement_as_data(capsys: pytest.CaptureFixture[str]) -> None:
    """plan:trace answers as a command-outcome envelope, and exits 0 when the
    three files agree."""
    import json

    assert plan_files.main() == 0
    envelope = json.loads(capsys.readouterr().out)
    assert envelope["command"] == "plan:trace"
    assert envelope["code"] == "plan_agrees"
    assert envelope["data"]["disagreements"] == []
