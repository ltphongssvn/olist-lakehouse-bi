"""The commands each task runs, one argv per command.

A NEWLINE ENDS A COMMAND in shell. The parser once treated it as whitespace, so
a two-line body read as one command holding both -- and the mypy policy saw one
argv naming mypy twice.
"""

from __future__ import annotations

from task_commands import command_invocations


def _argvs(body: str) -> list[list[str]]:
    return [list(command.argv) for command in command_invocations({"t": body})]


def test_two_lines_are_two_commands() -> None:
    body = "set -euo pipefail\nuv run mypy --platform darwin\nuv run mypy --platform linux\n"
    assert _argvs(body) == [
        ["set", "-euo", "pipefail"],
        ["uv", "run", "mypy", "--platform", "darwin"],
        ["uv", "run", "mypy", "--platform", "linux"],
    ]


def test_a_continued_line_is_one_command() -> None:
    assert _argvs("databricks bundle \\\n  validate --output json\n") == [
        ["databricks", "bundle", "validate", "--output", "json"]
    ]


def test_a_quoted_string_spanning_lines_stays_one_token() -> None:
    assert _argvs('python -c "\nprint(1)\n"\n') == [["python", "-c", "\nprint(1)\n"]]


def test_the_old_separators_still_separate() -> None:
    assert _argvs("a && b | c; d") == [["a"], ["b"], ["c"], ["d"]]
