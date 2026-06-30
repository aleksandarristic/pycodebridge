"""Focused tests for TASK-0070: per-session agent backend selection."""

import asyncio
from types import SimpleNamespace
from typing import Any, Optional

import pytest

from codebridge import config as cfgmod
from codebridge.agents.base import AgentBackend, NormalizedEvent, Options
from codebridge.agents.factory import KNOWN_BACKENDS, build_backend
from codebridge.codex import CodexBackend
from codebridge.sessions.coordinator import SessionCoordinator
from codebridge.sessions.service import SessionService
from codebridge.sessions.state import Store
from codebridge.platform.transport import Capabilities, MessageEvent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakeProc:
    def __init__(self) -> None:
        self._done = asyncio.Event()
        self._done.set()
        self.thread_id = ""

    def kill(self) -> None:
        pass

    async def wait(self) -> int:
        await self._done.wait()
        return 0

    async def write(self, text: str) -> None:
        pass


class _FakeBackend(AgentBackend):
    """Minimal AgentBackend double that records build_* calls and returns instantly."""
    parse = CodexBackend.parse

    def __init__(self) -> None:
        super().__init__(binary="fake", base_env={})
        self.started: list[str] = []
        self.resumed: list[str] = []

    def build_start_args(self, repo_path, prompt, model, reasoning_effort):
        self.started.append(prompt)
        return ["fake-start", prompt]

    def build_resume_args(self, repo_path, thread_id, prompt, model, reasoning_effort):
        self.resumed.append(prompt)
        return ["fake-resume", prompt]

    def build_resume_last_args(self, repo_path, prompt, model, reasoning_effort):
        self.resumed.append(prompt)
        return ["fake-resume-last", prompt]

    async def run(self, opts: Options) -> _FakeProc:
        proc = _FakeProc()
        if opts.on_thread:
            await opts.on_thread("thread-fake")
        return proc


# ---------------------------------------------------------------------------
# Config tests
# ---------------------------------------------------------------------------

def test_agent_config_defaults():
    cfg = cfgmod.Config()
    assert cfg.agent.default_backend == "codex"


def test_agent_config_parsed_from_dict():
    cfg = cfgmod.Config()
    cfgmod._apply_dict(cfg, {"agent": {"default_backend": "codex"}})
    cfgmod._apply_defaults(cfg)
    assert cfg.agent.default_backend == "codex"


def test_agent_config_empty_default_backend_falls_back_to_codex():
    cfg = cfgmod.Config()
    cfgmod._apply_dict(cfg, {"agent": {"default_backend": ""}})
    cfgmod._apply_defaults(cfg)
    assert cfg.agent.default_backend == "codex"


# ---------------------------------------------------------------------------
# State round-trip tests
# ---------------------------------------------------------------------------

def test_session_state_backend_round_trip(tmp_path):
    from codebridge.sessions.state import SessionState, ChannelState, FileState, _from_dict, _to_dict
    sess = SessionState(repo_name="r", repo_path="/p", thread_id="t", backend="codex")
    fs = FileState(channels={"c": ChannelState(sessions={"default": sess})})
    d = _to_dict(fs)
    assert d["channels"]["c"]["sessions"]["default"]["backend"] == "codex"
    fs2 = _from_dict(d)
    assert fs2.channels["c"].sessions["default"].backend == "codex"


def test_session_state_backend_missing_in_json_defaults_to_empty(tmp_path):
    """Backward compat: existing state files without 'backend' deserialize cleanly."""
    from codebridge.sessions.state import SessionState, ChannelState, FileState, _from_dict, _to_dict
    sess = SessionState(repo_name="r", repo_path="/p", thread_id="t")
    fs = FileState(channels={"c": ChannelState(sessions={"default": sess})})
    d = _to_dict(fs)
    del d["channels"]["c"]["sessions"]["default"]["backend"]
    fs2 = _from_dict(d)
    assert fs2.channels["c"].sessions["default"].backend == ""


# ---------------------------------------------------------------------------
# SessionService backend tests
# ---------------------------------------------------------------------------

def test_session_backend_returns_configured_default_when_no_override(tmp_path):
    store = Store(str(tmp_path))
    cfg = cfgmod.Config()
    cfg.agent.default_backend = "codex"
    service = SessionService(store, cfg)
    assert service.session_backend("chan", "default") == "codex"


def test_set_session_backend_persists_and_clears_thread(tmp_path):
    store = Store(str(tmp_path))
    cfg = cfgmod.Config()
    service = SessionService(store, cfg)
    # Seed a session with a thread_id.
    service.update_state("chan", "default", "repo", "/repo", "thread-123", "", "")
    state = store.load()
    assert state.channels["chan"].sessions["default"].thread_id == "thread-123"

    result = service.set_session_backend("chan", "default", "codex")
    assert result["cleared_thread"] is True
    state2 = store.load()
    assert state2.channels["chan"].sessions["default"].backend == "codex"
    assert state2.channels["chan"].sessions["default"].thread_id == ""


def test_set_session_backend_clears_model_and_effort(tmp_path):
    store = Store(str(tmp_path))
    cfg = cfgmod.Config()
    service = SessionService(store, cfg)
    service.update_state("chan", "default", "repo", "/repo", "", "gpt-4", "high")
    result = service.set_session_backend("chan", "default", "codex")
    assert result["cleared_model"] == "gpt-4"
    assert result["cleared_effort"] == "high"
    state = store.load()
    assert state.channels["chan"].sessions["default"].model == ""
    assert state.channels["chan"].sessions["default"].reasoning_effort == ""


def test_session_backend_returns_override_after_switch(tmp_path):
    store = Store(str(tmp_path))
    cfg = cfgmod.Config()
    service = SessionService(store, cfg)
    service.update_state("chan", "default", "repo", "/repo", "", "", "")
    service.set_session_backend("chan", "default", "codex")
    assert service.session_backend("chan", "default") == "codex"


# ---------------------------------------------------------------------------
# factory.KNOWN_BACKENDS test
# ---------------------------------------------------------------------------

def test_known_backends_contains_codex():
    assert "codex" in KNOWN_BACKENDS


def test_build_backend_unknown_raises():
    cfg = cfgmod.Config()
    with pytest.raises(ValueError, match="unknown agent backend"):
        build_backend(cfg, "nonexistent")


# ---------------------------------------------------------------------------
# Router.backend_for returns runner when no session override
# ---------------------------------------------------------------------------

class _FakeAudit:
    def start(self, *a, **kw): return None
    def append_codex(self, *a, **kw): pass
    def append_stderr(self, *a, **kw): pass
    def close(self, *a, **kw): pass
    def log(self, *a, **kw): pass

class _FakeLogger:
    def info(self, *a, **kw): pass
    def warning(self, *a, **kw): pass
    def error(self, *a, **kw): pass
    def debug(self, *a, **kw): pass


def _make_router(tmp_path):
    from codebridge.routing.router import Router
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    (repo / ".git").mkdir(exist_ok=True)
    cfg = cfgmod.Config()
    cfg.discord.allowed_user_ids = ["user"]
    cfg.codex.code_root = str(tmp_path)
    cfg.state.data_dir = str(tmp_path / "state")
    store = Store(cfg.state.data_dir)
    coordinator = SessionCoordinator(store, cfg)
    runner = _FakeBackend()
    router = Router(cfg, store, _FakeAudit(), runner, coordinator, _FakeLogger())
    return router, runner, store


def test_router_backend_for_returns_runner_when_no_override(tmp_path):
    router, runner, _ = _make_router(tmp_path)
    assert router.backend_for("chan", "default") is runner


def test_router_backend_for_builds_new_instance_on_explicit_override(tmp_path):
    router, runner, store = _make_router(tmp_path)
    # Set an explicit backend override via the coordinator.
    router.coordinator.set_session_backend("chan", "default", "codex")
    backend = router.backend_for("chan", "default")
    assert backend is not runner
    assert isinstance(backend, CodexBackend)


# ---------------------------------------------------------------------------
# !agent command tests
# ---------------------------------------------------------------------------

def _discord_event(content: str, channel_name: str = "code-repo") -> MessageEvent:
    channel = SimpleNamespace(
        guild=SimpleNamespace(default_role=object()),
        type="text",
        permissions_for=lambda _role: SimpleNamespace(view_channel=False),
    )
    return MessageEvent(
        platform="discord",
        content=content,
        channel_id="chan",
        channel_name=channel_name,
        author_id="user",
        author_is_bot=False,
        is_dm=False,
        guild_id="guild",
        raw_event=SimpleNamespace(channel=channel),
    )


class _FakeSink:
    def __init__(self) -> None:
        self.channel_id = "chan"
        self.sent: list[str] = []

    def capabilities(self) -> Capabilities:
        return Capabilities(threads=True, uploads=True, downloads=True, typing=True)

    async def send(self, content: str, thread_id=None, reply_to_id=None) -> None:
        self.sent.append(content)

    def typing(self):
        return _FakeAsyncCtx()

    async def update_pinned_status(self, user_id: str, session: str, text: str) -> None:
        self.sent.append(text)

    async def send_file(self, path, filename, thread_id=None, reply_to_id=None) -> None:
        pass


class _FakeAsyncCtx:
    async def __aenter__(self): return None
    async def __aexit__(self, *a): return False


def test_cmd_agent_sets_backend_and_replies(tmp_path):
    router, runner, _ = _make_router(tmp_path)
    sink = _FakeSink()

    async def run():
        # Seed a session so !agent has something to switch.
        router.coordinator.update_state("chan", "default", "repo", str(tmp_path / "repo"), "thread-1", "gpt-x", "high")
        await router.handle_message(_discord_event("!c agent codex"), sink)
        # Give the coordinator a tick.
        await asyncio.sleep(0)
        assert any("codex" in s and "default" in s for s in sink.sent)
        assert any("Thread id cleared" in s for s in sink.sent)
        state = router.state.load()
        assert state.channels["chan"].sessions["default"].backend == "codex"
        assert state.channels["chan"].sessions["default"].thread_id == ""

    asyncio.run(run())


def test_cmd_agent_rejects_unknown_backend(tmp_path):
    router, runner, _ = _make_router(tmp_path)
    sink = _FakeSink()

    async def run():
        await router.handle_message(_discord_event("!c agent nonexistent"), sink)
        await asyncio.sleep(0)
        assert any("Unknown backend" in s for s in sink.sent)

    asyncio.run(run())


def test_cmd_agent_no_args_shows_current_backend(tmp_path):
    router, runner, _ = _make_router(tmp_path)
    sink = _FakeSink()

    async def run():
        await router.handle_message(_discord_event("!c agent"), sink)
        await asyncio.sleep(0)
        assert any("Session 'default' backend: codex." in s for s in sink.sent)

    asyncio.run(run())


def test_cmd_which_agent_shows_current_backend(tmp_path):
    router, runner, _ = _make_router(tmp_path)
    sink = _FakeSink()

    async def run():
        await router.handle_message(_discord_event("!c which-agent"), sink)
        await asyncio.sleep(0)
        assert any("Session 'default' backend: codex." in s for s in sink.sent)

    asyncio.run(run())


def test_cmd_agent_with_session_name(tmp_path):
    router, runner, _ = _make_router(tmp_path)
    sink = _FakeSink()

    async def run():
        router.coordinator.update_state("chan", "work", "repo", str(tmp_path / "repo"), "thread-2", "gpt-x", "high")
        await router.handle_message(_discord_event("!c agent work codex", "code-repo"), sink)
        await asyncio.sleep(0)
        state = router.state.load()
        assert state.channels["chan"].sessions["work"].backend == "codex"
        assert state.channels["chan"].sessions["work"].thread_id == ""
        assert state.channels["chan"].sessions["work"].model == ""
        assert state.channels["chan"].sessions["work"].reasoning_effort == ""

    asyncio.run(run())


def test_cmd_agent_maps_codex_extra_high_to_xhigh(tmp_path):
    router, _, _ = _make_router(tmp_path)
    sink = _FakeSink()

    async def run():
        await router.handle_message(_discord_event("!c agent codex gpt-5.3-codex extra-high"), sink)
        await asyncio.sleep(0)
        state = router.state.load()
        sess = state.channels["chan"].sessions["default"]
        assert sess.backend == "codex"
        assert sess.model == "gpt-5.3-codex"
        assert sess.reasoning_effort == "xhigh"
        assert any("effort=xhigh" in s for s in sink.sent)

    asyncio.run(run())
