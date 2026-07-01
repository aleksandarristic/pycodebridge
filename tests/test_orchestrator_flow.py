"""Tests for the dispatch orchestrator flow."""

from __future__ import annotations

import asyncio
import os
import subprocess
from dataclasses import dataclass, field
from typing import List, Optional
from unittest.mock import MagicMock

import pytest

from codebridge.dispatch import orchestrator as orchestrator_module
from codebridge.dispatch.orchestrator import (
    Orchestrator,
    OrchestratorError,
    _git,
    _make_task_branch_name,
    _branch_to_slug,
    _make_worker_branch_name,
)
from codebridge.dispatch.parser import DispatchSpec
from codebridge.services.worktree import WorktreeError


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def no_dirty_commit_for_fake_worktrees(monkeypatch, request):
    if request.node.name == "test_successful_worker_uncommitted_change_is_preserved_on_worker_branch":
        return
    from codebridge.dispatch import orchestrator as orch_mod

    async def fake_commit_dirty_worktree(wt_path, agent):
        return False

    monkeypatch.setattr(orch_mod, "_commit_dirty_worktree", fake_commit_dirty_worktree)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

@dataclass
class FakeWorktreeManager:
    """Records create/remove calls without touching the filesystem."""
    max_per_repo: int = 8
    cleanup_on_end: str = "remove"
    created: List[dict] = field(default_factory=list)
    removed: List[str] = field(default_factory=list)
    _count: int = 0
    fail_on_create: bool = False

    async def create(self, repo_path, session_key, base_branch="", branch_name="", symlink_dirs=None):
        if self.fail_on_create:
            raise WorktreeError("create failed")
        entry = {
            "repo_path": repo_path,
            "session_key": session_key,
            "base_branch": base_branch,
            "branch_name": branch_name,
        }
        self.created.append(entry)
        self._count += 1
        path = f"/fake/wt/{session_key}"
        return path

    async def remove(self, path):
        self.removed.append(path)
        self._count = max(0, self._count - 1)

    async def count_for_repo(self, repo_path):
        return self._count

    async def prune_stale(self, repo_path):
        pass


@dataclass
class FakeSink:
    messages: List[str] = field(default_factory=list)
    channel_id: str = "chan1"

    async def send(self, content, thread_id=None, reply_to_id=None):
        self.messages.append(content)

    async def send_file(self, path, filename=""):
        pass


class FakeCoordinator:
    def __init__(self):
        self._branches = {}

    def get_task_branch(self, channel_id, session):
        return self._branches.get(f"{channel_id}:{session}", "")

    def update_task_branch(self, channel_id, session, branch):
        self._branches[f"{channel_id}:{session}"] = branch

    def clear_task_branch(self, channel_id, session):
        self._branches.pop(f"{channel_id}:{session}", None)


def _make_cfg(output_mode="both", close_mode="pr"):
    cfg = MagicMock()
    cfg.dispatch.output_mode = output_mode
    cfg.dispatch.close_mode = close_mode
    cfg.dispatch.plan_prompt = (
        "Plan for {{USER_REQUEST}} using {{AGENTS}}"
    )
    cfg.discord.max_discord_message_chars = 2000
    # codex config needed by build_backend
    cfg.codex.binary = "codex"
    cfg.codex.sandbox = "workspace-write"
    cfg.codex.env = {}
    cfg.codex.ask_for_approval = ""
    cfg.codex.network_access = False
    cfg.claude.binary = "claude"
    cfg.claude.permission_mode = "default"
    cfg.claude.env = {}
    cfg.claude.model = ""
    cfg.claude.effort = ""
    cfg.gemini.binary = "gemini"
    cfg.gemini.approval_mode = "yolo"
    cfg.gemini.env = {}
    cfg.gemini.model = ""
    return cfg


# ---------------------------------------------------------------------------
# Helper: patch backend.run so we don't need real CLIs
# ---------------------------------------------------------------------------

class _FakeProcess:
    def kill(self): pass
    def interrupt(self): pass


async def _fake_run_factory(rc=0, output="fake output"):
    """Return a coroutine that patches backend.run and immediately completes."""
    async def _run(self_backend, opts):
        # Call on_output once
        if opts.on_output:
            await opts.on_output(output)
        # Call on_exit to signal completion
        if opts.on_exit:
            await opts.on_exit(None, rc)
        return _FakeProcess()
    return _run


# ---------------------------------------------------------------------------
# Unit tests (no real backends, no real git)
# ---------------------------------------------------------------------------

def test_make_task_branch_name():
    name = _make_task_branch_name("myapp")
    assert name.startswith("task/myapp/")
    assert len(name) > len("task/myapp/")


def test_branch_to_slug():
    assert _branch_to_slug("task/myapp/20260623-143012") == "task-myapp-20260623-143012"
    assert _branch_to_slug("") == "branch"


def test_make_worker_branch_name_is_unique():
    first = _make_worker_branch_name("task/myapp/20260623-143012", "codex")
    second = _make_worker_branch_name("task/myapp/20260623-143012", "codex")
    assert first.startswith("task/myapp/20260623-143012-codex-")
    assert second.startswith("task/myapp/20260623-143012-codex-")
    assert first != second


def test_coordinator_task_branch_lifecycle():
    coord = FakeCoordinator()
    coord.update_task_branch("c1", "default", "task/repo/20260101")
    assert coord.get_task_branch("c1", "default") == "task/repo/20260101"
    coord.clear_task_branch("c1", "default")
    assert coord.get_task_branch("c1", "default") == ""


def test_solo_dispatch_creates_task_branch(monkeypatch):
    from codebridge.agents import base as base_mod

    async def fake_run(self_b, opts):
        if opts.on_output:
            await opts.on_output("done")
        if opts.on_exit:
            await opts.on_exit(None, 0)
        return _FakeProcess()

    monkeypatch.setattr(base_mod.AgentBackend, "run", fake_run)

    wt = FakeWorktreeManager()
    coord = FakeCoordinator()
    cfg = _make_cfg()
    orch = Orchestrator(cfg, wt, coord)
    sink = FakeSink()

    spec = DispatchSpec(agents=["codex"], prompt="implement X", is_orchestrated=False, is_fanout=False, raw="@codex implement X")
    run(orch.run(spec, "chan1", "default", "/repo", "myrepo", sink))

    branch = coord.get_task_branch("chan1", "default")
    assert branch.startswith("task/myrepo/")
    assert len(wt.created) >= 1


def test_solo_dispatch_relays_worker_output(monkeypatch):
    from codebridge.agents import base as base_mod

    async def fake_run(self_b, opts):
        if opts.on_output:
            await opts.on_output("live progress")
        if opts.on_exit:
            await opts.on_exit(None, 0)
        return _FakeProcess()

    monkeypatch.setattr(base_mod.AgentBackend, "run", fake_run)

    wt = FakeWorktreeManager()
    coord = FakeCoordinator()
    cfg = _make_cfg()
    orch = Orchestrator(cfg, wt, coord)
    sink = FakeSink()

    spec = DispatchSpec(agents=["codex"], prompt="implement X", is_orchestrated=False, is_fanout=False, raw="@codex implement X")
    run(orch.run(spec, "chan1", "default", "/repo", "myrepo", sink))

    assert "⚙ @codex: live progress" in sink.messages
    assert sink.messages.index("⚙ @codex: live progress") < sink.messages.index("✅ ⚙ @codex done")


def test_orchestrated_fanout_claude_runs_first(monkeypatch):
    from codebridge.agents import base as base_mod

    call_order = []

    async def fake_run(self_b, opts):
        call_order.append(type(self_b).__name__)
        if opts.on_exit:
            await opts.on_exit(None, 0)
        return _FakeProcess()

    monkeypatch.setattr(base_mod.AgentBackend, "run", fake_run)

    wt = FakeWorktreeManager()
    coord = FakeCoordinator()
    cfg = _make_cfg()
    orch = Orchestrator(cfg, wt, coord)
    sink = FakeSink()

    spec = DispatchSpec(
        agents=["claude", "codex"],
        prompt="implement auth",
        is_orchestrated=True,
        is_fanout=True,
        raw="@claude @codex implement auth",
    )
    run(orch.run(spec, "chan1", "default", "/repo", "myrepo", sink))

    assert call_order[0] == "ClaudeBackend"
    assert "CodexBackend" in call_order


def test_existing_task_branch_reused(monkeypatch):
    from codebridge.agents import base as base_mod

    async def fake_run(self_b, opts):
        if opts.on_exit:
            await opts.on_exit(None, 0)
        return _FakeProcess()

    monkeypatch.setattr(base_mod.AgentBackend, "run", fake_run)

    wt = FakeWorktreeManager()
    coord = FakeCoordinator()
    coord.update_task_branch("chan1", "default", "task/myrepo/20260101-000000")
    cfg = _make_cfg()
    orch = Orchestrator(cfg, wt, coord)
    sink = FakeSink()

    spec = DispatchSpec(agents=["codex"], prompt="add tests", is_orchestrated=False, is_fanout=False, raw="@codex add tests")
    run(orch.run(spec, "chan1", "default", "/repo", "myrepo", sink))

    branch = coord.get_task_branch("chan1", "default")
    assert branch == "task/myrepo/20260101-000000"


def test_worktree_create_failure_returns_gracefully(monkeypatch):
    wt = FakeWorktreeManager(fail_on_create=True)
    coord = FakeCoordinator()
    cfg = _make_cfg()
    orch = Orchestrator(cfg, wt, coord)
    sink = FakeSink()

    spec = DispatchSpec(agents=["codex"], prompt="do X", is_orchestrated=False, is_fanout=False, raw="@codex do X")
    run(orch.run(spec, "chan1", "default", "/repo", "myrepo", sink))
    # Should not raise; sink may have an error message


def test_worker_branches_forked_from_task_branch(monkeypatch):
    from codebridge.agents import base as base_mod

    async def fake_run(self_b, opts):
        if opts.on_exit:
            await opts.on_exit(None, 0)
        return _FakeProcess()

    monkeypatch.setattr(base_mod.AgentBackend, "run", fake_run)

    wt = FakeWorktreeManager()
    coord = FakeCoordinator()
    cfg = _make_cfg()
    orch = Orchestrator(cfg, wt, coord)
    sink = FakeSink()

    spec = DispatchSpec(
        agents=["codex", "gemini"],
        prompt="build feature",
        is_orchestrated=False,
        is_fanout=True,
        raw="@codex @gemini build feature",
    )
    run(orch.run(spec, "chan1", "default", "/repo", "myrepo", sink))

    task_branch = coord.get_task_branch("chan1", "default")
    worker_creates = [c for c in wt.created if c.get("base_branch") == task_branch]
    assert len(worker_creates) >= 1
    assert all(c["branch_name"].startswith(f"{task_branch}-") for c in worker_creates)
    assert len({c["branch_name"] for c in worker_creates}) == len(worker_creates)


def test_repeated_dispatch_creates_fresh_worker_branch(monkeypatch):
    from codebridge.agents import base as base_mod

    async def fake_run(self_b, opts):
        if opts.on_exit:
            await opts.on_exit(None, 0)
        return _FakeProcess()

    monkeypatch.setattr(base_mod.AgentBackend, "run", fake_run)

    wt = FakeWorktreeManager()
    coord = FakeCoordinator()
    cfg = _make_cfg()
    orch = Orchestrator(cfg, wt, coord)
    sink = FakeSink()
    spec = DispatchSpec(agents=["codex"], prompt="build feature", is_orchestrated=False, is_fanout=False, raw="@codex build feature")

    run(orch.run(spec, "chan1", "default", "/repo", "myrepo", sink))
    task_branch = coord.get_task_branch("chan1", "default")
    run(orch.run(spec, "chan1", "default", "/repo", "myrepo", sink))

    worker_branches = [
        c["branch_name"]
        for c in wt.created
        if c.get("base_branch") == task_branch and c.get("branch_name", "").startswith(f"{task_branch}-codex-")
    ]
    assert len(worker_branches) == 2
    assert len(set(worker_branches)) == 2


def test_successful_worker_uncommitted_change_is_preserved_on_worker_branch(monkeypatch, tmp_path):
    from codebridge.agents import base as base_mod
    from codebridge.services.worktree import WorktreeManager

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@t"], check=True, capture_output=True)
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
    }
    subprocess.run(
        ["git", "-C", str(repo), "commit", "--allow-empty", "-m", "init"],
        check=True,
        capture_output=True,
        env=env,
    )

    async def fake_run(self_b, opts):
        with open(os.path.join(opts.repo_path, "worker.txt"), "w", encoding="utf-8") as f:
            f.write("worker change\n")
        if opts.on_exit:
            await opts.on_exit(None, 0)
        return _FakeProcess()

    monkeypatch.setattr(base_mod.AgentBackend, "run", fake_run)

    wt = WorktreeManager(base_dir="", max_per_repo=8, cleanup_on_end="remove")
    coord = FakeCoordinator()
    cfg = _make_cfg(output_mode="aggregate")
    orch = Orchestrator(cfg, wt, coord)
    sink = FakeSink()

    spec = DispatchSpec(
        agents=["codex"],
        prompt="build feature",
        is_orchestrated=False,
        is_fanout=False,
        raw="@codex build feature",
    )
    run(orch.run(spec, "chan1", "default", str(repo), "myrepo", sink))

    task_branch = coord.get_task_branch("chan1", "default")
    task_tree = subprocess.run(
        ["git", "-C", str(repo), "ls-tree", "-r", "--name-only", task_branch],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    branches = subprocess.run(
        ["git", "-C", str(repo), "branch", "--list", f"{task_branch}-codex-*"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    worker_branch = branches[0].strip().lstrip("* ")
    worker_tree = subprocess.run(
        ["git", "-C", str(repo), "ls-tree", "-r", "--name-only", worker_branch],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "worker.txt" not in task_tree.splitlines()
    assert "worker.txt" in worker_tree.splitlines()
    assert any("1 file(s) changed" in msg for msg in sink.messages)


def test_git_command_times_out_instead_of_hanging_forever(tmp_path, monkeypatch):
    """A stalled/prompting git process must be killed, not hang the awaiting task forever."""
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    fake_git = fake_bin / "git"
    fake_git.write_text("#!/bin/sh\nsleep 5\n")
    fake_git.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_bin}:{os.environ['PATH']}")
    monkeypatch.setattr(orchestrator_module, "_GIT_TIMEOUT_SECONDS", 0.2)

    with pytest.raises(OrchestratorError, match="timed out"):
        run(_git(str(tmp_path), ["status"]))
