# tests/test_repo_state.py
"""Tests for the repository state model.

WHY THIS IS TESTED IN BOTH DIRECTIONS
The model exists because cleanup with no model of what it was cleaning aborted
mid-sync. A replacement whose decision logic is unverified would be the same
failure with more structure.

Every case constructs Branch and Worktree directly rather than manipulating a
repository -- the fields are the state, so the decision table is reachable in
process without creating branches on disk.
"""

from __future__ import annotations

from pathlib import Path

from repo_state import Branch, RepositoryState, Worktree

WORKTREE_PATH = Path("/repo-feature-x")


def branch(**overrides: object) -> Branch:
    """A deletable branch, unless an override says otherwise."""
    defaults: dict[str, object] = {
        "name": "feature/x",
        "position": "gone",
        "is_merged": True,
        "held_by": None,
    }
    return Branch(**{**defaults, **overrides})  # type: ignore[arg-type]


def test_a_merged_gone_unheld_branch_is_deletable() -> None:
    assert branch().is_deletable
    assert branch().blocked_because is None


def test_a_protected_branch_is_never_deletable() -> None:
    """develop and main are excluded whatever their state.

    `git branch -d` would refuse an unmerged one, but develop is normally
    fully merged -- so nothing in git stops this. The rule has to be ours.
    """
    for name in ("develop", "main"):
        assert not branch(name=name).is_deletable
        assert branch(name=name).blocked_because == "protected branch"


def test_a_branch_held_by_a_worktree_is_not_deletable() -> None:
    """The case that broke sync.

    git refuses with "cannot delete branch used by worktree" and the old
    pipeline aborted on it, leaving the sync half done.
    """
    held = branch(held_by=WORKTREE_PATH)

    assert not held.is_deletable
    assert held.blocked_because is not None
    assert str(WORKTREE_PATH) in held.blocked_because
    assert "worktree:remove" in held.blocked_because


def test_an_unmerged_branch_is_not_deletable() -> None:
    unmerged = branch(is_merged=False)

    assert not unmerged.is_deletable
    assert unmerged.blocked_because == "not merged into develop"


def test_a_branch_with_a_live_upstream_is_not_deletable() -> None:
    """Work in progress: the remote still exists, so nothing has been merged."""
    live = branch(position="in_sync")

    assert not live.is_deletable
    assert live.blocked_because is not None
    assert "upstream still exists" in live.blocked_because


def test_blocked_branches_are_reported_not_dropped() -> None:
    """A cleanup that quietly leaves something behind is the documented failure
    signal for this class of bug."""
    state = RepositoryState(
        worktrees=(),
        branches=(
            branch(name="feature/deletable"),
            branch(name="feature/held", held_by=WORKTREE_PATH),
            branch(name="develop", position="in_sync"),
        ),
    )

    assert [b.name for b in state.deletable] == ["feature/deletable"]
    assert [b.name for b in state.blocked] == ["feature/held"]


def test_the_first_worktree_is_the_main_one() -> None:
    """is_linked is the canonical predicate for worktree-aware cleanup."""
    main = Worktree(path=Path("/repo"), branch="develop", is_main=True, is_dirty=False)
    linked = Worktree(path=WORKTREE_PATH, branch="feature/x", is_main=False, is_dirty=False)

    assert not main.is_linked
    assert linked.is_linked


def test_state_is_frozen() -> None:
    """A snapshot that can be edited after the fact is not a snapshot."""
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="frozen"):
        branch().name = "other"
