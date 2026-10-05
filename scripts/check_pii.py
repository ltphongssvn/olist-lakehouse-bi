"""Scan tracked files for personal information, by content.

WHY THIS EXISTS ALONGSIDE THE STRUCTURAL CHECKS
.gitignore filters by FORMAT; tests/test_no_data_in_repo.py filters by PATH.
Both are proxies for the real rule, which is about CONTENT. The gap is not
hypothetical: an HTML export of an executed notebook carries names, birth dates
and salaries in its cell outputs.

WHY PERSON IS NOT DETECTED, WHICH LOOKS LIKE A GAP AND IS NOT
The first version enabled PERSON and reported 75 findings, of which roughly 70
were `ruff`, `Darwin`, `ci.yml`, `dict[str`, `.replace` and `cli#4872`. PERSON is
NER-based, and a model trained on prose reads every capitalised identifier in
source code as a name. That is a category error, not a threshold to tune, and
Presidio's own FAQ prescribes the fix: remove recognizers the data does not
need.

The pattern-based recognizers below combine regex with dictionary matching and
give explainable detection with minimal false positives. They found every real
issue in this repo; PERSON found none that they missed.

The same failure is documented elsewhere in different clothes -- general NER
tagging a drug name as a PERSON in clinical text -- and the accepted fix is to
suppress the NER layer rather than allowlist each false positive.

THERE IS NO ALLOWLIST, DELIBERATELY
An earlier draft carried an ALLOWED_TEXT set naming public figures who appear in
assignment questions. That is the "pragma: allowlist" pattern: suppressing a
finding instead of removing its cause, which makes a scanner decoration. Every
finding this reports is now eliminated at source. The first real one -- a
hardcoded email in databricks.yml -- became ${workspace.current_user.userName},
which was better configuration anyway.

WHAT IT STILL CANNOT DO
Free-text names in a committed data file would pass. The structural checks are
what prevent such a file from being tracked at all; this is the layer that
catches a credential-shaped or contact-shaped value hiding in something that
looks like code.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from presidio_analyzer import AnalyzerEngine
from presidio_analyzer.nlp_engine import NlpEngineProvider

ROOT = Path(__file__).resolve().parent.parent

# PATTERN-BASED ONLY. Every entity here is detected by regex plus dictionary and
# checksum validation, not by a language model. PERSON, LOCATION and
# ORGANIZATION are deliberately absent -- see the module docstring.
ENTITIES = [
    "EMAIL_ADDRESS",
    "US_SSN",
    "CREDIT_CARD",
    "IBAN_CODE",
    "US_PASSPORT",
    "US_DRIVER_LICENSE",
    "PHONE_NUMBER",
    "MEDICAL_LICENSE",
    "CRYPTO",
]

# 0.8, matching the threshold production PII platforms use for pattern-based
# detection. Lower admits partial matches; higher would drop a valid SSN that
# lacks surrounding context words.
THRESHOLD = 0.8

SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".woff", ".woff2"}
# Lockfiles are hashes and URLs by construction: nothing a human wrote, and
# scanning them wastes time on content that cannot contain personal data.
SKIP_PATHS = {"uv.lock", "mise.lock"}


def tracked_text_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files"], capture_output=True, text=True, check=True, cwd=ROOT
    )
    paths = []
    for line in result.stdout.splitlines():
        if not line or line in SKIP_PATHS:
            continue
        path = ROOT / line
        if path.suffix.lower() in SKIP_SUFFIXES or not path.is_file():
            continue
        paths.append(path)
    return paths


def build_analyzer() -> AnalyzerEngine:
    """Analyzer pinned to the small spaCy model.

    AnalyzerEngine() with no arguments loads en_core_web_lg and DOWNLOADS IT --
    560MB, on first run, ignoring whatever the lockfile pinned. That happened
    here. NlpEngineProvider makes the choice explicit and keeps the install
    reproducible.

    An NLP engine is required even with NER entities disabled, because Presidio
    uses spaCy for tokenization regardless.
    """
    provider = NlpEngineProvider(
        nlp_configuration={
            "nlp_engine_name": "spacy",
            "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}],
        }
    )
    return AnalyzerEngine(nlp_engine=provider.create_engine(), supported_languages=["en"])


def main() -> int:
    analyzer = build_analyzer()
    files = tracked_text_files()
    findings: list[str] = []

    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue

        for result in analyzer.analyze(text=text, entities=ENTITIES, language="en"):
            if result.score < THRESHOLD:
                continue
            line = text[: result.start].count("\n") + 1
            findings.append(
                f"{path.relative_to(ROOT)}:{line}  {result.entity_type} (score {result.score:.2f})"
            )

    if findings:
        # The matched TEXT is deliberately not printed. Reporting a leak must not
        # become a second copy of it -- the same reason betterleaks runs with
        # --redact. The path and line are enough to find it.
        print(f"{len(findings)} PII finding(s):", file=sys.stderr)
        for finding in sorted(findings):
            print(f"  {finding}", file=sys.stderr)
        print(
            "\nEliminate at SOURCE -- substitute a variable, generate at runtime, "
            "or remove the file. Do not add an allowlist: `git rm` does not "
            "remove data from history, and a suppressed finding makes the scanner "
            "decoration.",
            file=sys.stderr,
        )
        return 1

    print(f"no PII detected across {len(files)} tracked files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
