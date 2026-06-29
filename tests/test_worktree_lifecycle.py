"""Tests for WorktreeManager lifecycle wiring in Router."""

import asyncio
import logging
import os
from typing import List, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from codebridge import config as cfgmod
from codebridge.observability.audit import Logger as AuditLogger
from codebridge.routing.router import Router
from codebridge.services.worktree import WorktreeError, WorktreeManager
from codebridge.sessions.coordinator import SessionCoordinator
from codebridge.sessions.state import Store
from codebridge.platform.transport import Capabilities, MessageEvent


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class _FakeEntry:
    def append_codex_line(self, line): pass
    def append_discord_out(self, msg): pass
    def append_stderr(self, msg): pass
    def close(self): pass


class _FakeAudit:
    def start(self, channel_id, session, thread_id, request):
        return _FakeEntry()
    def close(self, entry): pass
    def append_stderr(self, entry, line): pass
    def append_codex_line(self, entry, line): pass
    def append_discord_out(self, entry, msg): pass


class _FakeLogger:
    def info(self, *a, **kw): pass
    def warning(self, *a, **kw): pass
    def error(self, *a, **kw): pass
    def debug(self, *a, **kw): pass
    def exception(self, *a, **kw): pass
    def getChild(self, name): return self


class _FakeAsyncCtx:
    async def __aenter__(self): return None
    async def __aexit__(self, *a): return False


class _FakeSink:
    def __init__(self, channel_id: str = "chan1"):
        self.messages: List[str] = []
        self.channel_id = channel_id

    def capabilities(self) -> Capabilities:
        return Capabilities()

    async def send(self, content: str, thread_id=None, reply_to_id=None) -> None:
        self.messages.append(content)

    def typing(self): return _FakeAsyncCtx()

    async def update_pinned_status(self, *a): pass

    async def send_file(self, *a): pass


class _FakeProcess:
    def __init__(self):
        self.thread_id = ""
    async def wait(self): return 0
    async def stop(self): pass
    def interrupt(self): pass
    def kill(self): pass


class _FakeRunner:
    """Fake backend that immediately calls on_exit with rc=0."""
    def __init__(self, captured: list):
        self.captured_repo_paths: list = captured

    async def run(self, opts):
        self.captured_repo_paths.append(opts.repo_path)
        proc = _FakeProcess()
        if opts.on_exit:
            asyncio.get_event_loop().call_soon(
                lambda: asyncio.ensure_future(opts.on_exit(None, 0))
            )
        return proc

    def build_start_args(self, *a, **kw): return ["--start"]
    def build_resume_args(self, *a, **kw): return ["--resume"]
    def build_resume_last_args(self, *a, **kw): return ["--resume-last"]
    def parse(self, line): return None

    @property
    def ask_prefix(self): return "Agent asks:"


class _FakeWorktreeManager:
    def __init__(self, wt_path: str = "/fake/worktree", raise_on_create: bool = False):
        self._wt_path = wt_path
        self._raise_on_create = raise_on_create
        self.create_calls: List[tuple] = []
        self.remove_calls: List[str] = []
        self.prune_calls: List[str] = []
        self.cleanup_on_end = "remove"

    async def create(self, repo_path: str, session_key: str, symlink_dirs=None, **kwargs) -> str:
        self.create_calls.append((repo_path, session_key))
        if self._raise_on_create:
            raise WorktreeError("max worktrees reached")
        return self._wt_path

    async def remove(self, worktree_path: str) -> None:
        self.remove_calls.append(worktree_path)

    async def prune_stale(self, repo_path: str) -> None:
        self.prune_calls.append(repo_path)

    def count_for_repo(self, repo_path: str): return 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_router(tmp_path, *, wt_manager=None, captured_paths=None):
    cfg = cfgmod.Config()
    cfg.discord.allowed_user_ids = ["user1"]
    cfg.codex.code_root = str(tmp_path)
    cfg.state.data_dir = str(tmp_path / "state")
    cfg.state.log_dir = str(tmp_path / "logs")

    store = Store(cfg.state.data_dir)
    coordinator = SessionCoordinator(store, cfg)
    if captured_paths is None:
        captured_paths = []
    runner = _FakeRunner(captured_paths)
    router = Router(cfg, store, _FakeAudit(), runner, coordinator, _FakeLogger(), wt_manager=wt_manager)
    return router, coordinator, captured_paths


def _event(channel_name: str = "code-myrepo", channel_id: str = "chan1") -> MessageEvent:
    ch = MagicMock()
    ch.name = channel_name
    ch.id = channel_id
    ch.type.name = "text"
    ch.permissions_for = MagicMock(return_value=MagicMock(read_messages=True))
    return MessageEvent(
        platform="discord",
        channel_id=channel_id,
        channel_name=channel_name,
        author_id="user1",
        author_is_bot=False,
        is_dm=False,
        content="!c start",
        raw_event=MagicMock(channel=ch, guild=MagicMock(id="guild1")),
        attachments=[],
        guild_id="guild1",
    )


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_no_worktree_when_manager_is_none(tmp_path):
    captured = []
    router, coordinator, captured_paths = _build_router(tmp_path, captured_paths=captured)
    repo_dir = tmp_path / "myrepo"
    repo_dir.mkdir()

    sink = _FakeSink()
    run(router.run_codex(
        _event(), sink,
        repo_name="myrepo",
        repo_path=str(repo_dir),
        session="default",
        model="", reasoning_effort="",
        args=["--start"],
    ))

    assert captured_paths == [str(repo_dir)]


def test_no_worktree_when_session_isolation_disabled(tmp_path):
    wt = _FakeWorktreeManager(wt_path=str(tmp_path / "myrepo-wt-ch1"))
    captured = []
    router, coordinator, captured_paths = _build_router(tmp_path, wt_manager=wt, captured_paths=captured)
    repo_dir = tmp_path / "myrepo"
    repo_dir.mkdir()

    sink = _FakeSink()
    run(router.run_codex(
        _event(), sink,
        repo_name="myrepo",
        repo_path=str(repo_dir),
        session="default",
        model="", reasoning_effort="",
        args=["--start"],
    ))

    assert wt.create_calls == []
    assert captured_paths == [str(repo_dir)]


def test_worktree_created_when_session_isolation_enabled(tmp_path):
    wt = _FakeWorktreeManager(wt_path=str(tmp_path / "myrepo-wt-ch1"))
    captured = []
    router, coordinator, captured_paths = _build_router(tmp_path, wt_manager=wt, captured_paths=captured)
    router.cfg.worktrees.session_isolation = True
    repo_dir = tmp_path / "myrepo"
    repo_dir.mkdir()

    sink = _FakeSink()
    run(router.run_codex(
        _event(), sink,
        repo_name="myrepo",
        repo_path=str(repo_dir),
        session="default",
        model="", reasoning_effort="",
        args=["--start"],
    ))

    assert len(wt.create_calls) == 1
    assert wt.create_calls[0][0] == str(repo_dir)
    assert captured_paths == [str(tmp_path / "myrepo-wt-ch1")]


def test_worktree_removed_on_exit_when_cleanup_remove(tmp_path):
    wt_path = str(tmp_path / "myrepo-wt-ch1")
    wt = _FakeWorktreeManager(wt_path=wt_path)
    wt.cleanup_on_end = "remove"
    router, coordinator, _ = _build_router(tmp_path, wt_manager=wt)
    router.cfg.worktrees.session_isolation = True
    repo_dir = tmp_path / "myrepo"
    repo_dir.mkdir()

    sink = _FakeSink()
    run(router.run_codex(
        _event(), sink,
        repo_name="myrepo",
        repo_path=str(repo_dir),
        session="default",
        model="", reasoning_effort="",
        args=["--start"],
    ))

    # Give the on_exit callback a moment to fire
    run(asyncio.sleep(0.05))
    assert wt_path in wt.remove_calls


def test_worktree_not_removed_when_cleanup_keep(tmp_path):
    wt_path = str(tmp_path / "myrepo-wt-ch1")
    wt = _FakeWorktreeManager(wt_path=wt_path)
    wt.cleanup_on_end = "keep"
    router, coordinator, _ = _build_router(tmp_path, wt_manager=wt)
    router.cfg.worktrees.session_isolation = True
    repo_dir = tmp_path / "myrepo"
    repo_dir.mkdir()

    sink = _FakeSink()
    run(router.run_codex(
        _event(), sink,
        repo_name="myrepo",
        repo_path=str(repo_dir),
        session="default",
        model="", reasoning_effort="",
        args=["--start"],
    ))

    run(asyncio.sleep(0.05))
    assert wt.remove_calls == []


def test_worktree_create_error_aborts_run(tmp_path):
    wt = _FakeWorktreeManager(raise_on_create=True)
    captured = []
    router, coordinator, captured_paths = _build_router(tmp_path, wt_manager=wt, captured_paths=captured)
    router.cfg.worktrees.session_isolation = True
    repo_dir = tmp_path / "myrepo"
    repo_dir.mkdir()

    sink = _FakeSink()
    run(router.run_codex(
        _event(), sink,
        repo_name="myrepo",
        repo_path=str(repo_dir),
        session="default",
        model="", reasoning_effort="",
        args=["--start"],
    ))

    assert captured_paths == []
    assert any("Cannot start session" in m for m in sink.messages)
