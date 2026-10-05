"""Prove the secret scanner can actually detect something.

WHY THIS EXISTS
`mise run check` reported "PASS secrets (history)" before anyone had confirmed
the scanner could detect anything at all. A gate that has only ever passed is
indistinguishable from one that cannot fail, and this one guards credentials.

The first manual attempt at this test FAILED TO FAIL, for two reasons worth
recording because both look like scanner bugs and are not:

  1. The classic GitHub PAT rule is ghp_ followed by EXACTLY 36 characters. The
     canary had 38, so no rule matched.
  2. Token efficiency, betterleaks' replacement for Shannon entropy, ships a
     default cutoff of 2.5 for strings of 12 characters or more. It measures how
     efficiently a BPE tokenizer compresses a string, so an obviously synthetic
     filler like "0123456789abcdef..." is rejected by design.

Hence the canary below is generated from os.urandom rather than written by hand:
correct length, genuinely high entropy, and it has never existed anywhere else.
"""

from __future__ import annotations

import pathlib
import secrets
import shutil
import string
import subprocess
import tempfile

ALPHABET = string.ascii_letters + string.digits


def _canary() -> str:
    """A syntactically valid, never-issued GitHub PAT.

    Generated per-run so no credential-shaped literal is ever committed to this
    repository -- the same reason the scanner exists at all.
    """
    return "ghp_" + "".join(secrets.choice(ALPHABET) for _ in range(36))


def test_scanner_detects_a_planted_credential() -> None:
    workdir = tempfile.mkdtemp()
    try:
        (pathlib.Path(workdir) / "config.txt").write_text(f'token = "{_canary()}"\n')
        result = subprocess.run(
            ["betterleaks", "dir", workdir, "--redact", "--no-banner"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode != 0, (
            "scanner reported clean on a planted credential. It is not protecting anything."
        )
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def test_scanner_reports_clean_on_innocuous_content() -> None:
    """The other half: a scanner that flags everything trains people to bypass it.

    Precision matters as much as recall -- that is the stated reason this project
    uses betterleaks rather than gitleaks.
    """
    workdir = tempfile.mkdtemp()
    try:
        (pathlib.Path(workdir) / "notes.txt").write_text(
            "The quick brown fox jumps over the lazy dog.\n"
        )
        result = subprocess.run(
            ["betterleaks", "dir", workdir, "--redact", "--no-banner"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, "scanner flagged ordinary prose as a secret"
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def test_findings_are_redacted() -> None:
    """A scanner that prints secrets to CI logs turns reporting a leak into causing one."""
    workdir = tempfile.mkdtemp()
    try:
        canary = _canary()
        (pathlib.Path(workdir) / "config.txt").write_text(f'token = "{canary}"\n')
        result = subprocess.run(
            ["betterleaks", "dir", workdir, "--redact", "--no-banner"],
            capture_output=True,
            text=True,
            check=False,
        )
        combined = result.stdout + result.stderr
        assert canary not in combined, "the secret appeared verbatim in scanner output"
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
