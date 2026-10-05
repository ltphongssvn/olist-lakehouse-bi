"""Verify an exported job run before a release ships it.

WHY THIS IS NOT A CONTENT CHECK, HAVING BEEN INTENDED AS ONE
The obvious verification is to decode the notebook out of the HTML and assert
that known cells and outputs are present. That decoding depends on
__DATABRICKS_NOTEBOOK_MODEL -- an INTERNAL, undocumented detail of Databricks'
HTML template, not part of any API contract. A check keyed to it would break the
next time that template changes, and it would break by reporting a good export as
bad.

The episode that prompted this is the argument. Grepping the raw HTML for
`spark.` returned zero and I concluded the 311KB export was empty chrome. It was
not: the browser rendered the full notebook with executed outputs. The
verification read the wrong layer and reported confidently.

AND THEN THIS MODULE MADE THE SAME MISTAKE
Its first version checked that the view's NAME matched the notebook, on the
strength of a documented sentence: "in the case of code view, it would be the
notebook's name". That does not hold for a bundle-deployed serverless run, where
the executed notebook is an EPHEMERAL COPY named by UUID -- 889aaa43-222f-... in
practice. The check refused a correct export on its first real use.

A doc sentence is not a guarantee until it has been checked against the actual
response. That check now exists, in the form of this comment and the removal.

WHAT IS VERIFIED, USING FIELDS OBSERVED TO BEHAVE AS DOCUMENTED
  exactly one NOTEBOOK view   a multi-task job exports several, and silently
                              taking the first is how the wrong notebook ships
  substantial size            an export of a run whose cells produced no output
                              is far smaller

WHAT ESTABLISHES IDENTITY INSTEAD
The RUN, not the view. latest_successful_run selects a run of the job whose name
ends with the assignment's, and the release records that run id in the tag
message. The view's name adds nothing and, as shown, refuses everything.

THE HONEST LIMIT, STATED RATHER THAN PAPERED OVER
None of this proves a specific cell ran. It proves the run Databricks reports as
successful produced a single notebook view of substantial size. Opening the file
is what proves the rest, and the release says so on completion.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

ROOT = Path(__file__).resolve().parent.parent

# An export of a run whose cells produced no output is a few tens of kilobytes:
# the HTML shell plus source. One with rendered outputs is hundreds. This
# separates those two, and nothing finer.
MINIMUM_EXPORT_BYTES = 50_000


class ExportedView(BaseModel):
    """One view item from /api/2.2/jobs/runs/export.

    extra="ignore" because the response may carry more and unknown fields are
    not a defect here -- unlike MergeResult, whose fields ARE the contract.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    content: str = ""
    name: str = ""
    type: str = ""


class ExportResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    views: tuple[ExportedView, ...] = Field(default=())

    @property
    def notebooks(self) -> tuple[ExportedView, ...]:
        return tuple(view for view in self.views if view.type == "NOTEBOOK")


def fetch_export(run_id: int) -> ExportResponse:
    """Fetch the run export. views_to_export defaults to CODE, which is what we want."""
    result = subprocess.run(
        ["databricks", "api", "get", f"/api/2.2/jobs/runs/export?run_id={run_id}"],
        capture_output=True,
        text=True,
        check=False,
        cwd=ROOT,
    )
    if result.returncode != 0:
        print(result.stderr.strip(), file=sys.stderr)
        raise SystemExit(f"export failed for run {run_id}")

    return ExportResponse.model_validate_json(result.stdout)


def verify(response: ExportResponse) -> ExportedView:
    """Refuse anything a release should not ship."""
    notebooks = response.notebooks

    if not notebooks:
        kinds = sorted({view.type for view in response.views}) or ["nothing"]
        raise SystemExit(f"export contains no NOTEBOOK view; got {kinds}")

    if len(notebooks) > 1:
        names = ", ".join(view.name for view in notebooks)
        raise SystemExit(
            f"export contains {len(notebooks)} notebook views ({names}). "
            "A release must be unambiguous about what it ships."
        )

    view = notebooks[0]

    # BYTES, NOT CHARACTERS. len() on the string UNDER-reports a notebook whose
    # outputs contain non-ASCII, which is most of them -- this assignment prints
    # names. Measured wrongly, a valid export would be refused as too small.
    size = len(view.content.encode("utf-8"))
    if size < MINIMUM_EXPORT_BYTES:
        raise SystemExit(
            f"export is only {size:,} bytes. A run whose cells produced outputs is "
            "far larger; this is likely source without results."
        )

    return view


def main() -> int:
    if len(sys.argv) < 2:
        raise SystemExit("usage: verify_export.py <run_id>")

    view = verify(fetch_export(int(sys.argv[1])))

    print(
        json.dumps(
            {
                "view": view.name,
                "type": view.type,
                "bytes": len(view.content.encode("utf-8")),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
