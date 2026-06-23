"""Tests for TaskCloser and parse_close_mode."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import List
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

from codebridge.dispatch.closer import TaskCloser, TaskCloseError, parse_close_mode


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

@dataclass
class FakeSink:
    messages: List[str] = field(default_factory=list)

    async def send(self, content, thread_id=None, reply_to_id=None):
        self.messages.append(content)


class FakeCoordinator:
    def __init__(self, task_branch=""):
        self._branch = task_branch

    def get_task_branch(self, channel_id, session):
        return self._branch

    def update_task_branch(self, channel_id, session, branch):
        self._branch = branch

    def clear_task_branch(self, channel_id, session):
        self._branch = ""


def _make_cfg(close_mode="pr"):
    cfg = MagicMock()
    cfg.dispatch.close_mode = close_mode
    return cfg


# ---------------------------------------------------------------------------
# parse_close_mode
# ---------------------------------------------------------------------------

def test_parse_close_mode_default():
    assert parse_close_mode("", "pr") == "pr"
    assert parse_close_mode("", "merge") == "merge"


def test_parse_close_mode_explicit_pr():
    assert parse_close_mode("--pr", "merge") == "pr"


def test_parse_close_mode_explicit_merge():
    assert parse_close_mode("--merge", "pr") == "merge"


def test_parse_close_mode_unknown_falls_back_to_default():
    assert parse_close_mode("--other", "pr") == "pr"


# ---------------------------------------------------------------------------
# TaskCloser.close
# ---------------------------------------------------------------------------

def test_close_raises_when_no_task_branch():
    coord = FakeCoordinator(task_branch="")
    closer = TaskCloser(_make_cfg(), coord)
    sink = FakeSink()

    with pytest.raises(TaskCloseError, match="No active task branch"):
        run(closer.close("chan1", "default", "/repo", "pr", sink))


def test_close_pr_mode_calls_open_pr(monkeypatch):
    coord = FakeCoordinator(task_branch="task/myrepo/20260623-120000")
    closer = TaskCloser(_make_cfg(), coord)
    sink = FakeSink()

    calls = []

    async def fake_open_pr(self, repo_path, task_branch, sink):
        calls.append(("pr", repo_path, task_branch))

    async def fake_cleanup(self, repo_path, task_branch):
        pass

    monkeypatch.setattr(TaskCloser, "_open_pr", fake_open_pr)
    monkeypatch.setattr(TaskCloser, "_cleanup_worker_branches", fake_cleanup)

    run(closer.close("chan1", "default", "/repo", "pr", sink))

    assert len(calls) == 1
    assert calls[0] == ("pr", "/repo", "task/myrepo/20260623-120000")
    # task branch cleared after close
    assert coord.get_task_branch("chan1", "default") == ""


def test_close_merge_mode_calls_merge(monkeypatch):
    coord = FakeCoordinator(task_branch="task/myrepo/20260623-130000")
    closer = TaskCloser(_make_cfg(), coord)
    sink = FakeSink()

    calls = []

    async def fake_merge(self, repo_path, task_branch, sink):
        calls.append(("merge", repo_path, task_branch))

    async def fake_cleanup(self, repo_path, task_branch):
        pass

    monkeypatch.setattr(TaskCloser, "_merge", fake_merge)
    monkeypatch.setattr(TaskCloser, "_cleanup_worker_branches", fake_cleanup)

    run(closer.close("chan1", "default", "/repo", "merge", sink))

    assert len(calls) == 1
    assert calls[0][0] == "merge"


def test_close_preserves_task_branch_on_error(monkeypatch):
    coord = FakeCoordinator(task_branch="task/myrepo/20260623-140000")
    closer = TaskCloser(_make_cfg(), coord)
    sink = FakeSink()
    cleaned = []

    async def fake_open_pr(self, repo_path, task_branch, sink):
        raise TaskCloseError("push failed")

    async def fake_cleanup(self, repo_path, task_branch):
        cleaned.append(task_branch)

    monkeypatch.setattr(TaskCloser, "_open_pr", fake_open_pr)
    monkeypatch.setattr(TaskCloser, "_cleanup_worker_branches", fake_cleanup)

    with pytest.raises(TaskCloseError):
        run(closer.close("chan1", "default", "/repo", "pr", sink))

    assert coord.get_task_branch("chan1", "default") == "task/myrepo/20260623-140000"
    assert cleaned == []


def test_cleanup_called_after_close(monkeypatch):
    coord = FakeCoordinator(task_branch="task/myrepo/20260623-150000")
    closer = TaskCloser(_make_cfg(), coord)
    sink = FakeSink()

    cleaned = []

    async def fake_open_pr(self, repo_path, task_branch, sink):
        pass

    async def fake_cleanup(self, repo_path, task_branch):
        cleaned.append(task_branch)

    monkeypatch.setattr(TaskCloser, "_open_pr", fake_open_pr)
    monkeypatch.setattr(TaskCloser, "_cleanup_worker_branches", fake_cleanup)

    run(closer.close("chan1", "default", "/repo", "pr", sink))

    assert cleaned == ["task/myrepo/20260623-150000"]
