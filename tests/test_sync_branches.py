# tests/test_sync_branches.py
"""Sync keeps every long-lived branch current, fast-forward only (D.10).

THE INVARIANT. A long-lived branch -- develop or main -- is never behind its
remote, never ahead of it, never diverged from it. Behind is repaired by a
fast-forward; ahead and diverged need a person, so they are reported and never
forced. machine.branches decides; sync remediates and then asks it.

WHY main SAT ELEVEN RELEASES BEHIND. sync pulled the branch it was on and nothing
else. git fetch origin main:main updates a branch without checking it out, and
git itself refuses a non-fast-forward there -- so a divergence surfaces as an
error instead of being clobbered. It also refuses a branch checked out in a
worktree, so that case is fast-forwarded inside its own worktree.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import JsonValue

from opa import denials
from repo_state import Branch, Position, RepositoryState, Worktree, position_of
from sync import Update, updates

HERE = Path("/repo")
ELSEWHERE = Path("/repo-elsewhere")


def _branch(name: str, position: Position, held_by: Path | None = None) -> Branch:
    return Branch(name=name, position=position, is_merged=True, held_by=held_by)


def _state(*branches: Branch, dirty: bool = False) -> RepositoryState:
    worktrees = (
        Worktree(path=HERE, branch="develop", is_main=True, is_dirty=False),
        Worktree(path=ELSEWHERE, branch="main", is_main=False, is_dirty=dirty),
    )
    return RepositoryState(worktrees=worktrees, branches=branches)


def _denied(state: RepositoryState | None) -> list[str]:
    payload: dict[str, JsonValue] = {}
    if state is not None:
        payload["repository_state"] = state.model_dump(mode="json")
    return [
        d for d in denials("data.machine.branches.deny", payload) if d.startswith("[ERR_BRANCH_")
    ]


def test_main_fast_forwards_without_being_checked_out() -> None:
    """THE DEFECT: an unheld long-lived branch behind its remote is fetched into place."""
    assert updates(_state(_branch("main", "behind"))) == (
        Update(branch="main", action="fast_forward", argv=("fetch", "origin", "main:main")),
    )


def test_an_update_is_never_forced() -> None:
    """A leading + would discard a local commit; git refuses the plain refspec instead."""
    for update in updates(_state(_branch("main", "behind"), _branch("develop", "behind"))):
        assert update.argv is not None
        assert not any(argument.startswith("+") for argument in update.argv)


def test_a_branch_held_by_a_clean_worktree_is_fast_forwarded_there() -> None:
    """git refuses to fetch into a checked-out branch, so the merge runs in its worktree."""
    assert updates(_state(_branch("main", "behind", held_by=ELSEWHERE))) == (
        Update(
            branch="main",
            action="fast_forward_in_worktree",
            argv=("-C", str(ELSEWHERE), "merge", "--ff-only", "origin/main"),
        ),
    )


def test_a_branch_held_by_a_dirty_worktree_is_reported_not_touched() -> None:
    state = _state(_branch("main", "behind", held_by=ELSEWHERE), dirty=True)
    assert updates(state) == (Update(branch="main", action="held_dirty"),)


def test_a_diverged_branch_is_reported_never_forced() -> None:
    assert updates(_state(_branch("main", "diverged"))) == (
        Update(branch="main", action="diverged"),
    )


def test_a_long_lived_branch_ahead_is_reported() -> None:
    """Commits on develop or main outside a pull request: reported, never pushed."""
    assert updates(_state(_branch("develop", "ahead"))) == (
        Update(branch="develop", action="ahead"),
    )


def test_branches_in_sync_and_feature_branches_need_nothing() -> None:
    """THE CONTROL: only long-lived branches out of place produce an update."""
    state = _state(_branch("main", "in_sync"), _branch("feature/x", "behind"))
    assert updates(state) == ()


def test_position_is_read_from_gits_upstream_tracking() -> None:
    upstream = "refs/remotes/origin/main"
    assert position_of(upstream, "") == "in_sync"
    assert position_of(upstream, "[behind 21]") == "behind"
    assert position_of(upstream, "[ahead 3]") == "ahead"
    assert position_of(upstream, "[ahead 1, behind 2]") == "diverged"
    assert position_of(upstream, "[gone]") == "gone"
    assert position_of("", "") == "untracked"


def test_the_policy_refuses_a_long_lived_branch_left_behind() -> None:
    denied = _denied(_state(_branch("main", "behind")))
    assert any(d.startswith("[ERR_BRANCH_BEHIND]") for d in denied), denied


def test_the_policy_refuses_ahead_and_diverged() -> None:
    denied = _denied(_state(_branch("develop", "ahead"), _branch("main", "diverged")))
    assert any(d.startswith("[ERR_BRANCH_AHEAD]") for d in denied), denied
    assert any(d.startswith("[ERR_BRANCH_DIVERGED]") for d in denied), denied


def test_the_policy_allows_long_lived_branches_in_sync() -> None:
    """THE CONTROL for the policy: in sync, and a feature branch behind, are both fine."""
    state = _state(
        _branch("develop", "in_sync"), _branch("main", "in_sync"), _branch("feature/x", "behind")
    )
    assert _denied(state) == []


def test_an_absent_state_is_denied() -> None:
    assert any(d.startswith("[ERR_BRANCH_UNOBSERVED]") for d in _denied(None))
