"""Tests for export verification.

WHY THIS EXISTS
The original guard was a size floor, and size passed while I concluded the
export was empty chrome. It was not -- the browser rendered the full notebook
with outputs. The verification was wrong, not the file.

THEN THE REPLACEMENT MADE THE SAME MISTAKE
Its first version checked that the view's NAME matched the notebook, on the
strength of a documented sentence: "in the case of code view, it would be the
notebook's name". That does not hold for a bundle-deployed serverless run, where
the executed notebook is an ephemeral copy named by UUID. The check refused a
correct export on its first real use -- the exact failure mode I had said I was
avoiding, introduced by the change meant to avoid it.

A doc sentence is not a guarantee until it has been checked against a real
response. What remains is verified against one.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from verify_export import MINIMUM_EXPORT_BYTES, ExportResponse, verify


def response(*views: Mapping[str, object]) -> ExportResponse:
    """Mapping, not dict.

    dict is INVARIANT in its value type, so dict[str, str] is not
    dict[str, object] and mypy rejects it. Mapping is covariant, which is what a
    read-only parameter wants -- mypy names this fix in the error itself.
    """
    return ExportResponse.model_validate({"views": list(views)})


def notebook_view(
    name: str = "889aaa43-222f-4cd5-b344-90c66e732aff", size: int = 200_000
) -> Mapping[str, object]:
    """A view named as Databricks really names it: a UUID, not the notebook.

    Using the observed shape as the default keeps these tests honest about what
    the API returns.
    """
    return {"type": "NOTEBOOK", "name": name, "content": "x" * size}


def test_accepts_a_single_substantial_notebook_view() -> None:
    view = verify(response(notebook_view()))
    assert view.type == "NOTEBOOK"


def test_accepts_a_view_named_by_uuid() -> None:
    """The case that broke the previous version.

    A bundle-deployed serverless run exports an ephemeral notebook copy named by
    UUID. Nothing about that is wrong, and refusing it refused every correct
    export.
    """
    view = verify(response(notebook_view("889aaa43-222f-4cd5-b344-90c66e732aff")))
    assert view.name == "889aaa43-222f-4cd5-b344-90c66e732aff"


def test_refuses_when_there_is_no_notebook_view() -> None:
    """A DASHBOARDS-only export is not a submission."""
    dashboard: Mapping[str, object] = {
        "type": "DASHBOARD",
        "name": "chart",
        "content": "x" * 200_000,
    }
    with pytest.raises(SystemExit, match="no NOTEBOOK view"):
        verify(response(dashboard))


def test_refuses_an_empty_response() -> None:
    """FAIL CLOSED: nothing exported is not a successful export."""
    with pytest.raises(SystemExit, match="no NOTEBOOK view"):
        verify(response())


def test_refuses_more_than_one_notebook_view() -> None:
    """A release must be unambiguous about what it ships.

    A multi-task job exports several, and silently taking the first is how the
    wrong notebook gets submitted.
    """
    with pytest.raises(SystemExit, match="2 notebook views"):
        verify(response(notebook_view("first"), notebook_view("second")))


def test_refuses_an_export_too_small_to_contain_outputs() -> None:
    """Source without results exports successfully and is far smaller.

    This is a proxy rather than a fact, and it is kept because the alternative --
    decoding the notebook out of the HTML -- depends on an undocumented internal
    format that would break on a template change.
    """
    with pytest.raises(SystemExit, match="likely source without results"):
        verify(response(notebook_view(size=MINIMUM_EXPORT_BYTES - 1)))


def test_size_is_measured_in_bytes_not_characters() -> None:
    """A multi-byte character counts once as a character and twice as bytes.

    len() on the string UNDER-reports a notebook whose outputs contain
    non-ASCII, which is most of them: the assignment prints names. Measured
    wrongly, a valid export would be refused as too small.
    """
    multibyte: Mapping[str, object] = {
        "type": "NOTEBOOK",
        "name": "889aaa43-222f-4cd5-b344-90c66e732aff",
        "content": "é" * 30_000,
    }

    view = verify(response(multibyte))

    assert len(view.content) < MINIMUM_EXPORT_BYTES
    assert len(view.content.encode("utf-8")) >= MINIMUM_EXPORT_BYTES
