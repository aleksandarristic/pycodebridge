"""Tests for WorktreeManager using real git repos in tmp_path."""

import asyncio
import os
import subprocess

import pytest

from codebridge.services import worktree as worktree_module
from codebridge.services.worktree import (
    WorktreeError,
    WorktreeManager,
    _count_session_worktrees,
    _git,
    _safe_slug,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _git_init(path: str) -> None:
    path_obj = os.fspath(path)
    os.makedirs(path_obj, exist_ok=True)
    subprocess.run(["git", "init", path_obj], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", path_obj, "commit", "--allow-empty", "-m", "init"],
        check=True,
        capture_output=True,
        env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
             "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"},
    )


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "myrepo"
    _git_init(str(r))
    return r


@pytest.fixture
def manager(tmp_path):
    return WorktreeManager(base_dir="", max_per_repo=8, cleanup_on_end="remove")


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_create_makes_directory(repo, manager):
    wt_path = run(manager.create(str(repo), "ch1-default"))
    assert os.path.isdir(wt_path)


def test_create_branch_name_format(repo, manager):
    wt_path = run(manager.create(str(repo), "ch1-default"))
    result = subprocess.run(
        ["git", "-C", str(repo), "worktree", "list", "--porcelain"],
        capture_output=True, text=True, check=True,
    )
    assert "branch refs/heads/session/" in result.stdout
    assert os.path.basename(wt_path).startswith("myrepo-wt-")


def test_create_path_sibling_strategy(repo, manager):
    wt_path = run(manager.create(str(repo), "ch1-default"))
    assert os.path.dirname(os.path.realpath(wt_path)) == os.path.dirname(os.path.realpath(str(repo)))


def test_create_path_base_dir_strategy(repo, tmp_path):
    base = tmp_path / "worktrees"
    base.mkdir()
    mgr = WorktreeManager(base_dir=str(base), max_per_repo=8, cleanup_on_end="remove")
    wt_path = run(mgr.create(str(repo), "ch1-default"))
    assert os.path.dirname(os.path.realpath(wt_path)) == str(base)


def test_remove_external_base_dir_unregisters_git_worktree(repo, tmp_path):
    base = tmp_path / "external" / "worktrees"
    base.mkdir(parents=True)
    mgr = WorktreeManager(base_dir=str(base), max_per_repo=8, cleanup_on_end="remove")
    wt_path = run(mgr.create(str(repo), "ch1-default"))

    assert run(mgr.count_for_repo(str(repo))) == 1
    run(mgr.remove(wt_path))

    assert not os.path.isdir(wt_path)
    assert run(mgr.count_for_repo(str(repo))) == 0
    result = subprocess.run(
        ["git", "-C", str(repo), "worktree", "list", "--porcelain"],
        capture_output=True, text=True, check=True,
    )
    assert "prunable gitdir file points to non-existent location" not in result.stdout


def test_remove_deletes_directory(repo, manager):
    wt_path = run(manager.create(str(repo), "ch1-default"))
    assert os.path.isdir(wt_path)
    run(manager.remove(wt_path))
    assert not os.path.isdir(wt_path)


def test_remove_is_idempotent(repo, manager):
    wt_path = run(manager.create(str(repo), "ch1-default"))
    run(manager.remove(wt_path))
    run(manager.remove(wt_path))  # should not raise


def test_remove_missing_path_is_noop(manager):
    run(manager.remove("/nonexistent/worktree/path"))  # should not raise


def test_prune_stale_runs_without_error(repo, manager):
    run(manager.prune_stale(str(repo)))  # should not raise


def test_max_per_repo_raises(repo, tmp_path):
    mgr = WorktreeManager(base_dir="", max_per_repo=2, cleanup_on_end="remove")
    run(mgr.create(str(repo), "ch1-s1"))
    run(mgr.create(str(repo), "ch1-s2"))
    with pytest.raises(WorktreeError, match="max worktrees"):
        run(mgr.create(str(repo), "ch1-s3"))


def test_count_for_repo(repo, manager):
    assert run(manager.count_for_repo(str(repo))) == 0
    run(manager.create(str(repo), "ch1-s1"))
    assert run(manager.count_for_repo(str(repo))) == 1
    run(manager.create(str(repo), "ch1-s2"))
    assert run(manager.count_for_repo(str(repo))) == 2


def test_create_bad_repo_path_raises(tmp_path, manager):
    not_a_repo = str(tmp_path / "notarepo")
    os.makedirs(not_a_repo)
    with pytest.raises(WorktreeError):
        run(manager.create(not_a_repo, "ch1-default"))


# ---------------------------------------------------------------------------
# Unit tests for helpers (no git needed)
# ---------------------------------------------------------------------------

def test_safe_slug_replaces_special_chars():
    assert _safe_slug("ch/123 foo:bar") == "ch-123-foo-bar"


def test_safe_slug_truncates_at_40():
    assert len(_safe_slug("a" * 100)) == 40


def test_git_command_times_out_instead_of_hanging_forever(tmp_path, monkeypatch):
    """A stalled/prompting git process must be killed, not hang the awaiting task forever."""
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    fake_git = fake_bin / "git"
    fake_git.write_text("#!/bin/sh\nsleep 5\n")
    fake_git.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_bin}:{os.environ['PATH']}")
    monkeypatch.setattr(worktree_module, "_GIT_TIMEOUT_SECONDS", 0.2)

    with pytest.raises(WorktreeError, match="timed out"):
        run(_git(str(tmp_path), ["status"]))


def test_count_session_worktrees_parses_porcelain():
    sample = (
        "worktree /repos/myapp\n"
        "HEAD abc123\n"
        "branch refs/heads/main\n"
        "\n"
        "worktree /repos/myapp-wt-ch1\n"
        "HEAD def456\n"
        "branch refs/heads/session/ch1/20260623-120000\n"
        "\n"
        "worktree /repos/myapp-wt-ch2\n"
        "HEAD ghi789\n"
        "branch refs/heads/session/ch2/20260623-120001\n"
    )
    assert _count_session_worktrees(sample) == 2
