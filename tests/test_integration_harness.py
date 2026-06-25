"""End-to-end router integration harness.

This file exercises the Router as a whole using transport-level MessageEvent
inputs and fake sink/runner collaborators. The focus is behavior contracts:

- command routing and shortcut normalization
- session lifecycle and run-control semantics
- Discord transport context behavior (threads, replies)
- TOTP gating and unlock scope behavior
- persistence-facing side effects (state, options, audit summaries)

Use this harness when validating changes that cross command boundaries or when
router behavior depends on multiple subsystems at once.
"""

import asyncio
import base64
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import os
import struct
import time
import json
from types import MethodType
from types import SimpleNamespace

from codebridge import config as cfgmod
from codebridge.agents.claude import ClaudeBackend
from codebridge.agents.gemini import GeminiBackend
from codebridge.codex import CodexBackend, Options, Runner
from codebridge.observability.audit import Logger as AuditLogger, Redactor
from codebridge.routing.event_context import build_contextual_sink
from codebridge.routing.router import Router
from codebridge.sessions.coordinator import SessionCoordinator
from codebridge.sessions.state import Store
from codebridge.security.totp import TotpAttemptLimiter
from codebridge.platform.transport import Attachment, Capabilities, MessageEvent


class _FakeEntry:

    def append_codex_line(self, line: str) -> None:
        return None

    def append_discord_out(self, msg: str) -> None:
        return None

    def append_stderr(self, msg: str) -> None:
        return None

    def close(self) -> None:
        return None


class _FakeAudit:
    def start(self, channel_id: str, session: str, thread_id: str, request):
        return _FakeEntry()


class _FakeLogger:
    def __init__(self) -> None:
        self.entries = []

    def info(self, name: str, extra=None):
        self.entries.append(("info", name, extra or {}))
        return None

    def warning(self, name: str, extra=None):
        self.entries.append(("warning", name, extra or {}))
        return None

    def error(self, name: str, extra=None):
        self.entries.append(("error", name, extra or {}))
        return None


class _FakeProc:
    def __init__(self) -> None:
        self.stopped = False
        self.interrupted = False
        self.killed = False
        self.writes = []
        self._done = asyncio.Event()

    async def wait(self) -> int:
        await self._done.wait()
        return 0

    async def stop(self) -> None:
        self.stopped = True
        self._done.set()

    def interrupt(self) -> None:
        self.interrupted = True

    def kill(self) -> None:
        self.killed = True
        self._done.set()

    async def write(self, data: str) -> None:
        self.writes.append(data)


class _ProcDone:
    def __init__(self, rc: int) -> None:
        self._rc = rc

    async def wait(self) -> int:
        return self._rc

    async def stop(self) -> None:
        return None

    def interrupt(self) -> None:
        return None

    def kill(self) -> None:
        return None

    async def write(self, data: str) -> None:
        _ = data
        return None


class _ProcNeverDone:
    def __init__(self) -> None:
        self.killed = False
        self._done = asyncio.Event()

    async def wait(self) -> int:
        await self._done.wait()
        return 0

    async def stop(self) -> None:
        return None

    def interrupt(self) -> None:
        return None

    def kill(self) -> None:
        self.killed = True

    async def write(self, data: str) -> None:
        _ = data
        return None


class _FakeRunner:
    # Emulate the Codex backend's JSONL parsing for router fallback parsing.
    parse = CodexBackend.parse
    ask_prefix = "Codex asks:"

    def __init__(self) -> None:
        self.calls = []
        self.last_proc = None

    def build_start_args(self, repo_path: str, prompt: str, model: str, reasoning: str) -> list[str]:
        _ = (repo_path, prompt, model, reasoning)
        return ["start"]

    def build_resume_args(self, repo_path: str, thread_id: str, prompt: str, model: str, reasoning: str) -> list[str]:
        _ = (repo_path, thread_id, prompt, model, reasoning)
        return ["resume", thread_id]

    def build_resume_last_args(self, repo_path: str, prompt: str, model: str, reasoning: str) -> list[str]:
        _ = (repo_path, prompt, model, reasoning)
        return ["resume", "--last"]

    async def run(self, opts: Options):
        self.calls.append(opts.args)
        if opts.on_thread:
            await opts.on_thread("thread-1")
        if opts.on_jsonl:
            await opts.on_jsonl("hello from codex")
        self.last_proc = _FakeProc()
        return self.last_proc


class _LateOutputRunner:
    # Emulate the Codex backend's JSONL parsing for router fallback parsing.
    parse = CodexBackend.parse

    def __init__(self, *, initial_line: str = "", late_line: str = "", rc: int = 0, delay: float = 0.02) -> None:
        self.calls = []
        self.last_proc = None
        self.initial_line = initial_line
        self.late_line = late_line
        self.rc = rc
        self.delay = delay

    async def run(self, opts: Options):
        self.calls.append(opts.args)
        if opts.on_thread:
            await opts.on_thread("thread-1")
        if self.initial_line and opts.on_jsonl:
            await opts.on_jsonl(self.initial_line)

        async def _late() -> None:
            await asyncio.sleep(self.delay)
            if self.late_line and opts.on_jsonl:
                await opts.on_jsonl(self.late_line)
            if opts.on_exit:
                await opts.on_exit(None, self.rc)

        asyncio.create_task(_late())
        self.last_proc = _ProcDone(self.rc)
        return self.last_proc


class _ImmediateExitRunner:
    # Emulate the Codex backend's JSONL parsing for router fallback parsing.
    parse = CodexBackend.parse
    ask_prefix = "Codex asks:"

    def __init__(self, *, jsonl_lines=(), stderr_lines=(), rc: int = 1) -> None:
        self.calls = []
        self.jsonl_lines = list(jsonl_lines)
        self.stderr_lines = list(stderr_lines)
        self.rc = rc

    async def run(self, opts: Options):
        self.calls.append(list(opts.args))
        if opts.on_thread:
            await opts.on_thread("thread-1")
        if opts.on_jsonl:
            for line in self.jsonl_lines:
                await opts.on_jsonl(line)
        if opts.on_stderr:
            for line in self.stderr_lines:
                await opts.on_stderr(line)
        return _ProcDone(self.rc)


class _ClaudeImmediateExitRunner(_ImmediateExitRunner):
    ask_prefix = "Claude asks:"

    def __init__(self, *, jsonl_lines=(), stderr_lines=(), rc: int = 1) -> None:
        super().__init__(jsonl_lines=jsonl_lines, stderr_lines=stderr_lines, rc=rc)
        self._backend = ClaudeBackend(binary="claude")

    def parse(self, line: str):
        return self._backend.parse(line)


class _ClaudeFinalResultLingeringRunner:
    ask_prefix = "Claude asks:"

    def __init__(self, line: str) -> None:
        self.calls = []
        self._backend = ClaudeBackend(binary="claude")
        self.last_proc: _ProcNeverDone | None = None
        self.line = line

    async def run(self, opts: Options):
        self.calls.append(list(opts.args))
        if opts.on_thread:
            await opts.on_thread("thread-1")
        if opts.on_jsonl:
            await opts.on_jsonl(self.line)
        self.last_proc = _ProcNeverDone()
        return self.last_proc

    def parse(self, line: str):
        return self._backend.parse(line)


class _GeminiImmediateExitRunner(_ImmediateExitRunner):
    ask_prefix = "Gemini asks:"

    def __init__(self, *, jsonl_lines=(), stderr_lines=(), rc: int = 1, model: str = "") -> None:
        super().__init__(jsonl_lines=jsonl_lines, stderr_lines=stderr_lines, rc=rc)
        self._backend = GeminiBackend(binary="gemini", model=model)
        self.default_model = self._backend.default_model

    def parse(self, line: str):
        return self._backend.parse(line)


class _CapturingRealRunner(Runner):
    def __init__(self, sandbox: str, ask_for_approval: str, network_access: bool) -> None:
        super().__init__("codex", sandbox, {}, ask_for_approval, network_access)
        self.calls = []
        self.last_proc = None

    async def run(self, opts: Options):
        self.calls.append(opts.args)
        if opts.on_thread:
            await opts.on_thread("thread-1")
        if opts.on_jsonl:
            await opts.on_jsonl("hello from codex")
        self.last_proc = _FakeProc()
        return self.last_proc


class _FakeSink:
    def __init__(self, caps: Capabilities) -> None:
        self._caps = caps
        self.channel_id = "chan"
        self.sent = []
        self.files = []

    def capabilities(self) -> Capabilities:
        return self._caps

    async def send(self, content: str, thread_id: str | None = None, reply_to_id: str | None = None) -> None:
        self.sent.append((content, thread_id, reply_to_id))

    def typing(self):
        return _FakeAsyncContext()

    async def update_pinned_status(self, user_id: str, session: str, text: str) -> None:
        return None

    async def send_file(self, path: str, filename: str, thread_id: str | None = None, reply_to_id: str | None = None) -> None:
        self.files.append((path, filename, thread_id, reply_to_id))


class _FailingSendSink(_FakeSink):
    async def send(self, content: str, thread_id: str | None = None, reply_to_id: str | None = None) -> None:
        _ = (content, thread_id, reply_to_id)
        raise RuntimeError("Separator is not found, and chunk exceed the limit")


class _FakeTaskCloser:
    def __init__(self) -> None:
        self.calls = []

    async def close(self, channel_id: str, session: str, repo_path: str, mode: str, sink) -> None:
        self.calls.append((channel_id, session, repo_path, mode, sink))


class _FakeAsyncContext:
    async def __aenter__(self):
        return None

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeDiscordPermissions:
    def __init__(self, *, view_channel: bool) -> None:
        self.view_channel = view_channel


class _FakeDiscordGuild:
    def __init__(self) -> None:
        self.default_role = object()


class _FakeDiscordChannelType:
    def __init__(self, name: str) -> None:
        self.name = name

    def __str__(self) -> str:
        return self.name


class _FakeDiscordChannel:
    def __init__(
        self,
        *,
        is_private: bool,
        channel_id: str = "chan",
        channel_name: str = "chan",
        channel_type: str = "text",
        parent=None,
        parent_id: str = "",
    ) -> None:
        self.id = channel_id
        self.name = channel_name
        self.guild = _FakeDiscordGuild()
        self.type = _FakeDiscordChannelType(channel_type)
        self._is_private = is_private
        self.parent = parent
        self.parent_id = parent_id or (str(getattr(parent, "id", "")) if parent is not None else "")

    def permissions_for(self, role) -> _FakeDiscordPermissions:
        _ = role
        return _FakeDiscordPermissions(view_channel=not self._is_private)


class _FakeDiscordMessage:
    def __init__(self, channel: _FakeDiscordChannel) -> None:
        self.channel = channel


def _hotp(secret_b32: str, counter: int) -> str:
    secret = base64.b32decode(secret_b32, casefold=True)
    msg = struct.pack(">Q", counter)
    digest = hmac.new(secret, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(value % 1_000_000).zfill(6)


def _totp_code(secret_b32: str, step_offset: int = 0) -> str:
    step = int(time.time() // 30) + step_offset
    return _hotp(secret_b32, step)


def _build_router(tmp_path, *, totp_enabled: bool = False, runner=None, audit=None):
    """Construct a Router wired to test doubles and temp-backed state."""
    cfg = cfgmod.Config()
    cfg.discord.allowed_user_ids = ["user"]
    cfg.discord.totp_enabled = totp_enabled
    cfg.discord.totp_secret_env = "DISCORD_TOTP_SECRET"
    cfg.discord.totp_window = 1
    cfg.codex.code_root = str(tmp_path)
    cfg.state.data_dir = str(tmp_path / "state")
    cfg.state.log_dir = str(tmp_path / "logs")

    store = Store(cfg.state.data_dir)
    coordinator = SessionCoordinator(store, cfg)
    runner = runner or _FakeRunner()
    logger = _FakeLogger()
    router = Router(cfg, store, audit if audit is not None else _FakeAudit(), runner, coordinator, logger)
    return router, runner


def _discord_event(
    content: str,
    channel_name: str,
    channel_id: str = "chan",
    *,
    is_private: bool = True,
    platform_thread_id: str = "",
    parent_channel_id: str = "",
    parent_channel_name: str = "",
) -> MessageEvent:
    """Build a Discord channel or thread event.

    When platform_thread_id is provided, this simulates a Discord thread event
    with parent channel metadata available on raw_event.channel.
    """
    if platform_thread_id:
        parent_id = parent_channel_id or "parent-chan"
        parent_name = parent_channel_name or "code-repo"
        parent_channel = _FakeDiscordChannel(
            is_private=is_private,
            channel_id=parent_id,
            channel_name=parent_name,
            channel_type="text",
        )
        channel = _FakeDiscordChannel(
            is_private=is_private,
            channel_id=channel_id,
            channel_name=channel_name,
            channel_type="public_thread",
            parent=parent_channel,
            parent_id=parent_id,
        )
    else:
        channel = _FakeDiscordChannel(
            is_private=is_private,
            channel_id=channel_id,
            channel_name=channel_name,
            channel_type="text",
        )
    return MessageEvent(
        platform="discord",
        content=content,
        channel_id=channel_id,
        channel_name=channel_name,
        author_id="user",
        author_is_bot=False,
        is_dm=False,
        platform_thread_id=platform_thread_id,
        guild_id="guild",
        raw_event=_FakeDiscordMessage(channel),
    )


def _discord_dm_event(content: str, channel_id: str = "dm-1") -> MessageEvent:
    return MessageEvent(
        platform="discord",
        content=content,
        channel_id=channel_id,
        channel_name="",
        author_id="user",
        author_is_bot=False,
        is_dm=True,
    )


# ---------------------------------------------------------------------------
# Core lifecycle and room/thread scoping
# ---------------------------------------------------------------------------

def test_integration_start_stop(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    router, runner = _build_router(tmp_path)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(_discord_event("!c start", "code-repo"), sink)
        for _ in range(50):
            proc = await router.get_active("chan", "default")
            if proc is not None:
                break
            await asyncio.sleep(0.01)
        await router.handle_message(_discord_event("!c stop", "code-repo"), sink)

    asyncio.run(run())
    assert runner.last_proc is not None
    assert runner.last_proc.stopped is True
    assert runner.last_proc.interrupted is True


def test_integration_start_builds_exec_args_in_expected_order(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    runner = _CapturingRealRunner("workspace-write", "on-request", True)
    router, _ = _build_router(tmp_path, runner=runner)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(_discord_event("!c start", "code-repo"), sink)
        for _ in range(50):
            proc = await router.get_active("chan", "default")
            if proc is not None:
                break
            await asyncio.sleep(0.01)
        await router.handle_message(_discord_event("!c stop", "code-repo"), sink)

    asyncio.run(run())

    assert runner.calls
    args = runner.calls[0]
    assert args[:10] == [
        "exec",
        "--json",
        "--cd",
        str(repo),
        "--sandbox",
        "workspace-write",
        "-c",
        'approval_policy="on-request"',
        "-c",
        "sandbox_workspace_write.network_access=true",
    ]
    assert args[-1] == router.cfg.codex.start_prompt.replace("{{REPO_NAME}}", "repo")


def test_integration_discord_thread_uses_parent_repo_mapping_and_room_scope(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    room_key = "discord:chan-parent:thread-a"
    thread_session = "topic-a"
    router, runner = _build_router(tmp_path)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(
            _discord_event(
                "!c start",
                "topic-a",
                channel_id="thread-a",
                platform_thread_id="thread-a",
                parent_channel_id="chan-parent",
                parent_channel_name="code-repo",
            ),
            sink,
        )
        for _ in range(100):
            proc = await router.get_active(room_key, thread_session)
            if proc is not None:
                break
            await asyncio.sleep(0.01)
        await router.handle_message(
            _discord_event(
                "!c stop",
                "topic-a",
                channel_id="thread-a",
                platform_thread_id="thread-a",
                parent_channel_id="chan-parent",
                parent_channel_name="code-repo",
            ),
            sink,
        )

    asyncio.run(run())

    state = router.state.load()
    assert room_key in state.channels
    assert any(args and args[0] == "start" for args in runner.calls)
    assert any(thread_id == "thread-a" for _, thread_id, _ in sink.sent)


def test_integration_discord_sibling_threads_are_isolated(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    room_a = "discord:chan-parent:thread-a"
    room_b = "discord:chan-parent:thread-b"
    session_a = "topic-a"
    session_b = "topic-b"
    router, _ = _build_router(tmp_path)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(
            _discord_event(
                "!c start",
                "topic-a",
                channel_id="thread-a",
                platform_thread_id="thread-a",
                parent_channel_id="chan-parent",
                parent_channel_name="code-repo",
            ),
            sink,
        )
        await router.handle_message(
            _discord_event(
                "!c start",
                "topic-b",
                channel_id="thread-b",
                platform_thread_id="thread-b",
                parent_channel_id="chan-parent",
                parent_channel_name="code-repo",
            ),
            sink,
        )
        for _ in range(100):
            proc_a = await router.get_active(room_a, session_a)
            proc_b = await router.get_active(room_b, session_b)
            if proc_a is not None and proc_b is not None:
                break
            await asyncio.sleep(0.01)

        await router.handle_message(
            _discord_event(
                "!c stop",
                "topic-a",
                channel_id="thread-a",
                platform_thread_id="thread-a",
                parent_channel_id="chan-parent",
                parent_channel_name="code-repo",
            ),
            sink,
        )
        for _ in range(100):
            if await router.get_active(room_a, session_a) is None:
                break
            await asyncio.sleep(0.01)
        assert await router.get_active(room_a, session_a) is None
        assert await router.get_active(room_b, session_b) is not None

        await router.handle_message(
            _discord_event(
                "!c stop",
                "topic-b",
                channel_id="thread-b",
                platform_thread_id="thread-b",
                parent_channel_id="chan-parent",
                parent_channel_name="code-repo",
            ),
            sink,
        )

    asyncio.run(run())
    assert any(thread_id == "thread-a" for _, thread_id, _ in sink.sent)
    assert any(thread_id == "thread-b" for _, thread_id, _ in sink.sent)


def test_integration_discord_thread_session_name_falls_back_to_default_when_not_normalizable(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    room_key = "discord:chan-parent:thread-a"
    router, _ = _build_router(tmp_path)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(
            _discord_event(
                "!c start",
                "___",
                channel_id="thread-a",
                platform_thread_id="thread-a",
                parent_channel_id="chan-parent",
                parent_channel_name="code-repo",
            ),
            sink,
        )
        proc = None
        for _ in range(100):
            proc = await router.get_active(room_key, "default")
            if proc is not None:
                break
            await asyncio.sleep(0.01)
        assert proc is not None
        await router.handle_message(
            _discord_event(
                "!c stop",
                "___",
                channel_id="thread-a",
                platform_thread_id="thread-a",
                parent_channel_id="chan-parent",
                parent_channel_name="code-repo",
            ),
            sink,
        )

    asyncio.run(run())


def test_integration_discord_parent_channel_remains_backward_compatible_with_thread_rooms(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    parent_channel_id = "chan-parent"
    thread_room = "discord:chan-parent:thread-a"
    thread_session = "topic-a"
    router, _ = _build_router(tmp_path)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(_discord_event("!c start", "code-repo", channel_id=parent_channel_id), sink)
        await router.handle_message(
            _discord_event(
                "!c start",
                "topic-a",
                channel_id="thread-a",
                platform_thread_id="thread-a",
                parent_channel_id=parent_channel_id,
                parent_channel_name="code-repo",
            ),
            sink,
        )
        for _ in range(100):
            parent_proc = await router.get_active(parent_channel_id, "default")
            thread_proc = await router.get_active(thread_room, thread_session)
            if parent_proc is not None and thread_proc is not None:
                break
            await asyncio.sleep(0.01)

        await router.handle_message(_discord_event("!c stop", "code-repo", channel_id=parent_channel_id), sink)
        for _ in range(100):
            if await router.get_active(parent_channel_id, "default") is None:
                break
            await asyncio.sleep(0.01)
        assert await router.get_active(parent_channel_id, "default") is None
        assert await router.get_active(thread_room, thread_session) is not None

        await router.handle_message(
            _discord_event(
                "!c stop",
                "topic-a",
                channel_id="thread-a",
                platform_thread_id="thread-a",
                parent_channel_id=parent_channel_id,
                parent_channel_name="code-repo",
            ),
            sink,
        )

    asyncio.run(run())
    state = router.state.load()
    assert parent_channel_id in state.channels
    assert thread_room in state.channels


def test_integration_discord_thread_stop_rekeys_legacy_thread_scope(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    room_key = "discord:chan-parent:thread-a"
    router, _ = _build_router(tmp_path)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))
    proc = _FakeProc()
    router.update_state("thread-a", "default", "repo", str(repo), "thread-legacy", "", "")

    async def run():
        await router.set_active("thread-a", "default", proc)
        await router.handle_message(
            _discord_event(
                "!c stop",
                "topic-a",
                channel_id="thread-a",
                platform_thread_id="thread-a",
                parent_channel_id="chan-parent",
                parent_channel_name="code-repo",
            ),
            sink,
        )

    asyncio.run(run())

    assert proc.stopped is True
    assert proc.interrupted is True
    state = router.state.load()
    assert room_key in state.channels
    assert "thread-a" not in state.channels


def test_integration_discord_thread_mention_without_command_is_ignored(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    router, runner = _build_router(tmp_path)
    router.cfg.discord.allow_plain_prompts = True
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(
            _discord_event(
                "<@123456789> please take over",
                "topic-a",
                channel_id="thread-a",
                platform_thread_id="thread-a",
                parent_channel_id="chan-parent",
                parent_channel_name="code-repo",
            ),
            sink,
        )

    asyncio.run(run())
    assert runner.calls == []
    assert sink.sent == []


def test_integration_discord_thread_mention_with_prefix_runs_command(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    router, runner = _build_router(tmp_path)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(
            _discord_event(
                "<@123456789> !c start",
                "topic-a",
                channel_id="thread-a",
                platform_thread_id="thread-a",
                parent_channel_id="chan-parent",
                parent_channel_name="code-repo",
            ),
            sink,
        )
        await asyncio.sleep(0)

    asyncio.run(run())
    assert any(args and args[0] == "start" for args in runner.calls)


def test_integration_bang_stop_runs_stop_command(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    router, runner = _build_router(tmp_path)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(_discord_event("!c start", "code-repo"), sink)
        for _ in range(50):
            proc = await router.get_active("chan", "default")
            if proc is not None:
                break
            await asyncio.sleep(0.01)
        await router.handle_message(_discord_event("!stop", "code-repo"), sink)

    asyncio.run(run())
    assert runner.last_proc is not None
    assert runner.last_proc.stopped is True
    assert runner.last_proc.interrupted is True


def test_integration_bang_interrupt_uses_esc_only(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    router, runner = _build_router(tmp_path)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(_discord_event("!c start", "code-repo"), sink)
        for _ in range(50):
            proc = await router.get_active("chan", "default")
            if proc is not None:
                break
            await asyncio.sleep(0.01)
        await router.handle_message(_discord_event("!interrupt", "code-repo"), sink)

    asyncio.run(run())
    assert runner.last_proc is not None
    assert runner.last_proc.stopped is True
    assert runner.last_proc.interrupted is False


def test_integration_interrupt_aliases_dispatch(tmp_path):
    for trigger in ("!int", "!esc", "!escape"):
        case_tmp = tmp_path / f"case-{trigger[1:]}"
        case_tmp.mkdir()
        repo = case_tmp / f"repo-{trigger[1:]}"
        repo.mkdir()
        (repo / ".git").mkdir()

        router, runner = _build_router(case_tmp)
        sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

        async def run():
            await router.handle_message(_discord_event("!c start", f"code-repo-{trigger[1:]}"), sink)
            for _ in range(50):
                proc = await router.get_active("chan", "default")
                if proc is not None:
                    break
                await asyncio.sleep(0.01)
            await router.handle_message(_discord_event(trigger, f"code-repo-{trigger[1:]}"), sink)

        asyncio.run(run())
        assert runner.last_proc is not None
        assert runner.last_proc.stopped is True
        assert runner.last_proc.interrupted is False


# ---------------------------------------------------------------------------
# Transport privacy and identity gating
# ---------------------------------------------------------------------------

def test_integration_ignores_public_discord_repo_channel(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    router, runner = _build_router(tmp_path)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(_discord_event("!c start", "code-repo", is_private=False), sink)

    asyncio.run(run())
    assert runner.calls == []
    assert sink.sent == []
    assert router.state.load().channels == {}


def test_transport_user_allowed_discord_denies_when_allowlist_empty(tmp_path):
    router, _ = _build_router(tmp_path)
    router.cfg.discord.allowed_user_ids = []
    event = MessageEvent(
        platform="discord",
        content="!c status",
        channel_id="chan",
        channel_name="code-repo",
        author_id="intruder",
        author_is_bot=False,
        is_dm=False,
        guild_id="guild",
        raw_event=_FakeDiscordMessage(_FakeDiscordChannel(is_private=True, channel_id="chan", channel_name="code-repo")),
    )

    assert router._transport_user_allowed(event) is False


# ---------------------------------------------------------------------------
# Repo/session/run-control flows and command shortcuts
# ---------------------------------------------------------------------------

def test_integration_start_with_case_variant_repo_dir(tmp_path):
    repo = tmp_path / "ProbablyFine"
    repo.mkdir()
    (repo / ".git").mkdir()

    router, _ = _build_router(tmp_path)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(_discord_event("!c start", "code-probablyfine"), sink)
        for _ in range(200):
            state = router.state.load()
            ch = state.channels.get("chan")
            if ch and "default" in ch.sessions:
                break
            await asyncio.sleep(0.01)

    asyncio.run(run())
    state = router.state.load()
    sess = state.channels["chan"].sessions["default"]
    assert sess.repo_name == "probablyfine"
    assert os.path.basename(sess.repo_path).lower() == "probablyfine"
    assert os.path.samefile(sess.repo_path, str(repo))


def test_integration_kill(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    router, runner = _build_router(tmp_path)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(_discord_event("!c start", "code-repo"), sink)
        for _ in range(50):
            proc = await router.get_active("chan", "default")
            if proc is not None:
                break
            await asyncio.sleep(0.01)
        await router.handle_message(_discord_event("!c kill", "code-repo"), sink)

    asyncio.run(run())
    assert runner.last_proc is not None
    assert runner.last_proc.killed is True


def test_integration_reset_session_clears_context_and_allows_fresh_start(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    router, runner = _build_router(tmp_path)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(_discord_event("!c start", "code-repo"), sink)
        first_proc = None
        for _ in range(100):
            first_proc = await router.get_active("chan", "default")
            if first_proc is not None:
                break
            await asyncio.sleep(0.01)
        assert first_proc is not None

        await router.handle_message(_discord_event("!c reset", "code-repo"), sink)
        for _ in range(100):
            if await router.get_active("chan", "default") is None:
                break
            await asyncio.sleep(0.01)
        assert first_proc.killed is True

        state = router.state.load()
        ch = state.channels.get("chan")
        assert ch is not None
        assert "default" not in ch.sessions

        await router.handle_message(_discord_event("!c start", "code-repo"), sink)
        for _ in range(200):
            if len(runner.calls) >= 2:
                break
            await asyncio.sleep(0.01)

    asyncio.run(run())
    assert len(runner.calls) >= 2
    assert not any("already exists" in msg for msg, _, _ in sink.sent)


def test_integration_bang_reset_alias_clears_context_and_allows_fresh_start(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    router, runner = _build_router(tmp_path)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        for _ in range(3):
            await router.handle_message(_discord_event("!c start", "code-repo"), sink)
            proc = None
            for _ in range(100):
                proc = await router.get_active("chan", "default")
                if proc is not None:
                    break
                await asyncio.sleep(0.01)
            assert proc is not None
            await router.handle_message(_discord_event("!reset", "code-repo"), sink)
            for _ in range(100):
                if await router.get_active("chan", "default") is None:
                    break
                await asyncio.sleep(0.01)
            assert proc.killed is True

    asyncio.run(run())
    state = router.state.load()
    ch = state.channels.get("chan")
    if ch:
        assert "default" not in ch.sessions
    assert any("reset" in msg.lower() for msg, _, _ in sink.sent)
    assert len([args for args in runner.calls if args and args[0] == "start"]) >= 3


def test_integration_single_session_scope_rejects_named_channel_session(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    router, runner = _build_router(tmp_path)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(_discord_event("!c start custom", "code-repo"), sink)

    asyncio.run(run())
    assert len(runner.calls) == 0
    assert any("single session 'default'" in msg.lower() for msg, _, _ in sink.sent)


def test_integration_single_session_scope_rejects_named_thread_session(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    router, runner = _build_router(tmp_path)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(
            _discord_event(
                "!c start default",
                "topic-a",
                channel_id="thread-a",
                platform_thread_id="thread-a",
                parent_channel_id="chan-parent",
                parent_channel_name="code-repo",
            ),
            sink,
        )

    asyncio.run(run())
    assert len(runner.calls) == 0
    assert any("single session 'topic-a'" in msg.lower() for msg, _, _ in sink.sent)


def test_integration_purge_removes_session_artifacts(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    router, _ = _build_router(tmp_path)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    session_log = tmp_path / "logs" / "session_jsonl" / "active" / "chan" / "repo-repo__session-default.jsonl"
    session_log.parent.mkdir(parents=True, exist_ok=True)
    session_log.write_text('{"event":"x"}\n', encoding="utf-8")

    audit_file = tmp_path / "logs" / "chan" / "repo-repo__session-default" / "thread-pending" / "000001.request.json"
    audit_file.parent.mkdir(parents=True, exist_ok=True)
    audit_file.write_text("{}", encoding="utf-8")

    archive_file = (
        tmp_path
        / "logs"
        / "session_archives"
        / "chan"
        / "repo-repo__session-default"
        / "20260101T000000Z.txt"
    )
    archive_file.parent.mkdir(parents=True, exist_ok=True)
    archive_file.write_text("archived", encoding="utf-8")

    async def run():
        await router.handle_message(_discord_event("!c start", "code-repo"), sink)
        await router.handle_message(_discord_event("!c purge", "code-repo"), sink)

    asyncio.run(run())
    state = router.state.load()
    ch = state.channels.get("chan")
    if ch:
        assert "default" not in ch.sessions
    assert not session_log.exists()
    assert not audit_file.exists()
    assert not archive_file.exists()
    assert any("purged" in msg.lower() for msg, _, _ in sink.sent)


def test_integration_purge_stale_ttl_removes_old_scope_session(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    router, _ = _build_router(tmp_path)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(_discord_event("!c start", "code-repo"), sink)

    asyncio.run(run())

    stale_ts = (datetime.now(timezone.utc) - timedelta(hours=4)).strftime("%Y-%m-%dT%H:%M:%SZ")

    def mutator(fs):
        ch = fs.channels.get("chan")
        assert ch is not None
        sess = ch.sessions.get("default")
        assert sess is not None
        sess.last_used_at = stale_ts
        ch.sessions["default"] = sess
        fs.channels["chan"] = ch

    router.state.update(mutator)
    session_log = tmp_path / "logs" / "session_jsonl" / "active" / "chan" / "repo-repo__session-default.jsonl"
    session_log.parent.mkdir(parents=True, exist_ok=True)
    session_log.write_text('{"event":"x"}\n', encoding="utf-8")

    async def prune():
        await router.handle_message(_discord_event("!c purge stale 1h", "code-repo"), sink)

    asyncio.run(prune())
    state = router.state.load()
    ch = state.channels.get("chan")
    if ch:
        assert "default" not in ch.sessions
    assert not session_log.exists()
    assert any("purged" in msg.lower() and "stale" in msg.lower() for msg, _, _ in sink.sent)


def test_api_reset_session_hook_supports_purge(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    router, _ = _build_router(tmp_path)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    session_log = tmp_path / "logs" / "session_jsonl" / "active" / "chan" / "repo-repo__session-default.jsonl"
    session_log.parent.mkdir(parents=True, exist_ok=True)
    session_log.write_text('{"event":"x"}\n', encoding="utf-8")

    async def run():
        await router.handle_message(_discord_event("!c start", "code-repo"), sink)
        result = await router.api_reset_session("chan", "default", purge=True)
        assert result["session"] == "default"
        assert result["purged_artifacts"] >= 1

    asyncio.run(run())
    assert not session_log.exists()


def test_integration_bang_reset_alias_works_in_discord_thread_scope(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    room_key = "discord:chan-parent:thread-a"
    thread_session = "topic-a"
    router, _ = _build_router(tmp_path)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(
            _discord_event(
                "!c start",
                "topic-a",
                channel_id="thread-a",
                platform_thread_id="thread-a",
                parent_channel_id="chan-parent",
                parent_channel_name="code-repo",
            ),
            sink,
        )
        proc = None
        for _ in range(100):
            proc = await router.get_active(room_key, thread_session)
            if proc is not None:
                break
            await asyncio.sleep(0.01)
        assert proc is not None

        await router.handle_message(
            _discord_event(
                "!reset",
                "topic-a",
                channel_id="thread-a",
                platform_thread_id="thread-a",
                parent_channel_id="chan-parent",
                parent_channel_name="code-repo",
            ),
            sink,
        )
        for _ in range(100):
            if await router.get_active(room_key, thread_session) is None:
                break
            await asyncio.sleep(0.01)
        assert proc.killed is True

    asyncio.run(run())
    state = router.state.load()
    ch = state.channels.get(room_key)
    if ch:
        assert thread_session not in ch.sessions
    assert any("reset" in msg.lower() for msg, thread_id, _ in sink.sent if thread_id == "thread-a")


def test_integration_resume_and_download(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    target = repo / "note.txt"
    target.write_text("hi")

    router, runner = _build_router(tmp_path)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(_discord_event("!c resume hello", "code-repo"), sink)
        await router.handle_message(_discord_event("!c download note.txt", "code-repo"), sink)

    asyncio.run(run())
    assert any(args and args[0] == "start" for args in runner.calls)
    assert sink.files == [(str(target), "note.txt", None, None)]


def test_integration_download_alias_and_usage(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    target = repo / "note.txt"
    target.write_text("hi")

    router, _ = _build_router(tmp_path)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(_discord_event("!c dl note.txt", "code-repo"), sink)
        await router.handle_message(_discord_event("!c download", "code-repo"), sink)

    asyncio.run(run())
    assert sink.files == [(str(target), "note.txt", None, None)]
    assert any("Usage: !c download <path>" in msg for msg, _, _ in sink.sent)


def test_integration_workflow_command_expands_prompt_and_respects_session(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    router, runner = _build_router(tmp_path)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))
    captured = {"prompt": "", "session": ""}

    def _build_start_args(repo_path: str, prompt: str, model: str, reasoning: str) -> list[str]:
        _ = (repo_path, model, reasoning)
        captured["prompt"] = prompt
        return ["start"]

    runner.build_start_args = _build_start_args
    original_handle_resume = router.handle_resume

    async def _capture_handle_resume(self, event, sink_obj, repo_name, repo_path, session, prompt, skip_idle_ttl_check=False):
        _ = (event, sink_obj, repo_name, repo_path, skip_idle_ttl_check)
        captured["session"] = session
        await original_handle_resume(event, sink, repo_name, repo_path, session, prompt, skip_idle_ttl_check=skip_idle_ttl_check)

    router.handle_resume = MethodType(_capture_handle_resume, router)

    async def run():
        await router.handle_message(
            _discord_event(
                "!c workflow release fix failing tests",
                "release",
                channel_id="thread-chan",
                platform_thread_id="thread-1",
                parent_channel_name="code-repo",
            ),
            sink,
        )

    asyncio.run(run())
    assert captured["session"] == "release"
    assert "Investigate and fix the requested problem" in captured["prompt"]
    assert "Repository: repo." in captured["prompt"]
    assert "Focus: failing tests" in captured["prompt"]
    assert any(args == ["start"] for args in runner.calls)


def test_integration_updates_command_dispatches(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    router, _ = _build_router(tmp_path)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))
    called: list[str] = []

    async def _fake_handle_updates(self, sink_obj, repo_path: str) -> None:
        called.append(repo_path)
        await self.reply(sink_obj, "updates-ok")

    router.handle_updates = MethodType(_fake_handle_updates, router)

    async def run():
        await router.handle_message(_discord_event("!c updates", "code-repo"), sink)

    asyncio.run(run())
    assert called == [str(repo)]
    assert any("updates-ok" in msg for msg, _, _ in sink.sent)


def test_integration_workflow_list_shows_available_macros(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    router, runner = _build_router(tmp_path)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(_discord_event("!c workflow list", "code-repo"), sink)

    asyncio.run(run())
    assert runner.calls == []
    texts = [msg for msg, _, _ in sink.sent]
    assert any("Built-in workflows:" in t for t in texts)
    assert any("`inspect`" in t for t in texts)
    assert any("`fix`" in t for t in texts)


def test_integration_answer_command_relays_to_active_session(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    router, runner = _build_router(tmp_path)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(_discord_event("!c start", "code-repo"), sink)
        for _ in range(50):
            proc = await router.get_active("chan", "default")
            if proc is not None:
                break
            await asyncio.sleep(0.01)
        await router.handle_message(_discord_event("!c answer yes", "code-repo"), sink)

    asyncio.run(run())
    assert runner.last_proc is not None
    assert runner.last_proc.writes[-1] == "yes\n"
    assert any("Sent response to session 'default'." in msg for msg, _, _ in sink.sent)


def test_integration_steer_command_relays_to_active_session(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    router, runner = _build_router(tmp_path)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(_discord_event("!c start", "code-repo"), sink)
        for _ in range(50):
            proc = await router.get_active("chan", "default")
            if proc is not None:
                break
            await asyncio.sleep(0.01)
        await router.handle_message(_discord_event("!c steer focus on failing tests", "code-repo"), sink)

    asyncio.run(run())
    assert runner.last_proc is not None
    assert runner.last_proc.writes[-1] == "focus on failing tests\n"
    assert any("Steer delivered to session 'default'." in msg for msg, _, _ in sink.sent)


def test_integration_bang_steer_relays_to_active_session(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    router, runner = _build_router(tmp_path)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(_discord_event("!c start", "code-repo"), sink)
        for _ in range(50):
            proc = await router.get_active("chan", "default")
            if proc is not None:
                break
            await asyncio.sleep(0.01)
        await router.handle_message(_discord_event("!steer keep current plan, reduce scope", "code-repo"), sink)

    asyncio.run(run())
    assert runner.last_proc is not None
    assert runner.last_proc.writes[-1] == "keep current plan, reduce scope\n"
    assert any("Steer delivered to session 'default'." in msg for msg, _, _ in sink.sent)


def test_integration_bang_s_shortcut_relays_to_active_session(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    router, runner = _build_router(tmp_path)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(_discord_event("!c start", "code-repo"), sink)
        for _ in range(50):
            proc = await router.get_active("chan", "default")
            if proc is not None:
                break
            await asyncio.sleep(0.01)
        await router.handle_message(_discord_event("!s tighten scope", "code-repo"), sink)

    asyncio.run(run())
    assert runner.last_proc is not None
    assert runner.last_proc.writes[-1] == "tighten scope\n"
    assert any("Steer delivered to session 'default'." in msg for msg, _, _ in sink.sent)


def test_integration_bang_s_shortcut_with_non_space_whitespace_relays(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    router, runner = _build_router(tmp_path)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(_discord_event("!c start", "code-repo"), sink)
        for _ in range(50):
            proc = await router.get_active("chan", "default")
            if proc is not None:
                break
            await asyncio.sleep(0.01)
        await router.handle_message(_discord_event("!s\ttrim scope", "code-repo"), sink)
        await router.handle_message(_discord_event("!s\nkeep only tests", "code-repo"), sink)

    asyncio.run(run())
    assert runner.last_proc is not None
    assert "trim scope\n" in runner.last_proc.writes
    assert "keep only tests\n" in runner.last_proc.writes
    assert any("Steer delivered to session 'default'." in msg for msg, _, _ in sink.sent)


def test_integration_bare_s_and_a_shortcuts_show_validation_errors(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    router, _ = _build_router(tmp_path)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(_discord_event("!s", "code-repo"), sink)
        await router.handle_message(_discord_event("!a", "code-repo"), sink)

    asyncio.run(run())
    texts = [msg for msg, _, _ in sink.sent]
    assert any("Usage: !c steer [session] -- <text>  or  !c steer <text>" in msg for msg in texts)
    assert any("Usage: !c answer [session] -- <text>  or  !c answer <text>" in msg for msg in texts)


def test_integration_steer_fails_loudly_when_no_active_session(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    router, _ = _build_router(tmp_path)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(_discord_event("!s tighten scope", "code-repo"), sink)

    asyncio.run(run())
    texts = [msg for msg, _, _ in sink.sent]
    assert any("Cannot steer: no active session in this channel." in msg for msg in texts)


def test_integration_steer_fails_loudly_when_multiple_active_sessions(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    router, _ = _build_router(tmp_path)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.set_active("chan", "default", _FakeProc())
        await router.set_active("chan", "alpha", _FakeProc())
        await router.handle_message(_discord_event("!s tighten scope", "code-repo"), sink)

    asyncio.run(run())
    texts = [msg for msg, _, _ in sink.sent]
    assert any("Cannot steer: multiple active sessions (alpha, default)." in msg for msg in texts)


def test_integration_plain_message_auto_steers_single_active_session(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    router, _ = _build_router(tmp_path)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))
    proc = _FakeProc()

    async def run():
        await router.set_active("chan", "default", proc)
        await router.handle_message(_discord_event("focus on the failing tests", "code-repo"), sink)

    asyncio.run(run())
    assert "focus on the failing tests\n" in proc.writes
    texts = [msg for msg, _, _ in sink.sent]
    assert any("Steer delivered to session 'default'." in msg for msg in texts)


def test_integration_plain_message_steer_ack_failure_does_not_abort(tmp_path):
    router, _ = _build_router(tmp_path)
    sink = _FailingSendSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))
    proc = _FakeProc()

    async def run():
        await router.set_active("chan", "default", proc)
        await router.handle_message(_discord_event("focus on the failing tests", "code-repo"), sink)

    asyncio.run(run())

    assert "focus on the failing tests\n" in proc.writes
    assert any(
        level == "warning"
        and name == "relay.steer_ack_failed"
        and extra["error"] == "Separator is not found, and chunk exceed the limit"
        for level, name, extra in router.logger.entries
    )
    assert any(
        level == "info" and name == "relay.steer"
        for level, name, _ in router.logger.entries
    )


def test_integration_plain_message_with_multiple_active_sessions_is_rejected(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    router, _ = _build_router(tmp_path)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.set_active("chan", "default", _FakeProc())
        await router.set_active("chan", "alpha", _FakeProc())
        await router.handle_message(_discord_event("focus on the failing tests", "code-repo"), sink)

    asyncio.run(run())
    texts = [msg for msg, _, _ in sink.sent]
    assert any("Multiple sessions are running." in msg for msg in texts)
    assert any("!s:<session>" in msg for msg in texts)


def test_integration_plain_message_with_no_active_session_falls_through_to_resume(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    router, runner = _build_router(tmp_path)
    router.cfg.discord.allow_plain_prompts = True
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(_discord_event("start fresh on the API", "code-repo"), sink)
        await asyncio.sleep(0)

    asyncio.run(run())
    assert runner.calls != [] or runner.last_proc is not None


def test_integration_done_merge_rejected_while_session_active(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    router, _ = _build_router(tmp_path)
    closer = _FakeTaskCloser()
    router._task_closer = closer
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.set_active("chan", "default", _FakeProc())
        await router.handle_message(_discord_event("!c done --merge", "code-repo"), sink)

    asyncio.run(run())

    texts = [msg for msg, _, _ in sink.sent]
    assert any("Cannot close dispatch task while session 'default' is still running." in msg for msg in texts)
    assert closer.calls == []


def test_integration_session_targeted_steer_and_answer_shortcuts(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    router, runner = _build_router(tmp_path)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(_discord_event("!c start", "code-repo"), sink)
        for _ in range(50):
            proc = await router.get_active("chan", "default")
            if proc is not None:
                break
            await asyncio.sleep(0.01)
        await router.handle_message(_discord_event("!s:default keep edits minimal", "code-repo"), sink)
        await router.handle_message(_discord_event("!a:default yes proceed", "code-repo"), sink)

    asyncio.run(run())
    assert runner.last_proc is not None
    assert "keep edits minimal\n" in runner.last_proc.writes
    assert "yes proceed\n" in runner.last_proc.writes


def test_integration_cfg_and_opts_shortcuts(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    router, _ = _build_router(tmp_path)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(_discord_event("!cfg", "code-repo"), sink)
        await router.handle_message(_discord_event("!opts", "code-repo"), sink)

    asyncio.run(run())
    texts = [msg for msg, _, _ in sink.sent]
    assert any("code_root:" in msg for msg in texts)
    assert any("Runtime options (persisted):" in msg for msg in texts)


def test_integration_auto_relays_plain_reply_when_codex_waits_for_input(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    router, runner = _build_router(tmp_path)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(_discord_event("!c start", "code-repo"), sink)
        for _ in range(50):
            proc = await router.get_active("chan", "default")
            if proc is not None:
                break
            await asyncio.sleep(0.01)
        await router.on_jsonl(
            sink,
            "chan",
            "default",
            "repo",
            None,
            '{"type":"item.completed","item":{"type":"agent_message","text":"Proceed?"}}',
            True,
        )
        await router.handle_message(_discord_event("yes", "code-repo"), sink)

    asyncio.run(run())
    assert runner.last_proc is not None
    assert runner.last_proc.writes[-1] == "yes\n"
    assert len(runner.calls) == 1


def test_integration_wait_command_reports_pending_input(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    router, _ = _build_router(tmp_path)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(_discord_event("!c start", "code-repo"), sink)
        for _ in range(50):
            proc = await router.get_active("chan", "default")
            if proc is not None:
                break
            await asyncio.sleep(0.01)
        await router.handle_message(_discord_event("!c wait", "code-repo"), sink)
        await router.on_jsonl(
            sink,
            "chan",
            "default",
            "repo",
            None,
            '{"type":"item.completed","item":{"type":"agent_message","text":"Proceed?"}}',
            True,
        )
        await router.handle_message(_discord_event("!c wait", "code-repo"), sink)

    asyncio.run(run())
    assert any("No sessions are waiting for input." in msg for msg, _, _ in sink.sent)
    assert any("Related: !ps, !c status" in msg for msg, _, _ in sink.sent)
    assert any("Waiting for input: default" in msg for msg, _, _ in sink.sent)
    assert any("Related: !c answer, !a <text>" in msg for msg, _, _ in sink.sent)


def test_integration_run_completion_summary_for_long_run(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    router, _ = _build_router(tmp_path)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))
    router._set_runtime_option("local", "chan", "run_completion_min_seconds", 1)

    async def run():
        await router.handle_message(_discord_event("!c start", "code-repo"), sink)
        for _ in range(50):
            proc = await router.get_active("chan", "default")
            if proc is not None:
                break
            await asyncio.sleep(0.01)
        await asyncio.sleep(1.05)
        await router.handle_message(_discord_event("!c stop", "code-repo"), sink)

    asyncio.run(run())
    texts = [msg for msg, _, _ in sink.sent]
    assert any("Run complete for session 'default'" in t for t in texts)


def test_integration_run_completion_summary_suppressed_for_short_run(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    router, _ = _build_router(tmp_path)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))
    router._set_runtime_option("local", "chan", "run_completion_min_seconds", 10)

    async def run():
        await router.handle_message(_discord_event("!c start", "code-repo"), sink)
        for _ in range(50):
            proc = await router.get_active("chan", "default")
            if proc is not None:
                break
            await asyncio.sleep(0.01)
        await router.handle_message(_discord_event("!c stop", "code-repo"), sink)

    asyncio.run(run())
    texts = [msg for msg, _, _ in sink.sent]
    assert not any("Run complete for session 'default'" in t for t in texts)


def test_integration_run_heartbeat_message(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    router, _ = _build_router(tmp_path)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))
    router._set_runtime_option("local", "chan", "run_heartbeat_seconds", 1)

    async def run():
        await router.handle_message(_discord_event("!c start", "code-repo"), sink)
        await asyncio.sleep(1.12)
        await router.handle_message(_discord_event("!c kill", "code-repo"), sink)

    asyncio.run(run())
    texts = [msg for msg, _, _ in sink.sent]
    assert any("working for" in t for t in texts)


def test_integration_late_progress_is_suppressed_after_terminal_summary(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    runner = _LateOutputRunner(
        initial_line='{"type":"item.completed","item":{"type":"agent_message","text":"First output"}}',
        late_line='{"type":"item.completed","item":{"type":"agent_message","text":"Late progress"}}',
    )
    router, _ = _build_router(tmp_path, runner=runner)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))
    router._runtime_options_channels["chan"] = {"run_completion_min_seconds": 0}

    async def run():
        await router.run_codex(_discord_event("!c start", "code-repo"), sink, "repo", str(repo), "default", "", "", ["start"])
        await asyncio.sleep(0.05)

    asyncio.run(run())
    texts = [msg for msg, _, _ in sink.sent]
    assert any("First output" in t for t in texts)
    assert not any("Late progress" in t for t in texts)
    assert texts[-1].startswith("Run complete for session 'default'")


def test_run_codex_success_without_output_sends_terminal_notice(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    line = json.dumps(
        {
            "type": "result",
            "usage": {"input_tokens": 2, "output_tokens": 0, "total_tokens": 2},
        }
    )
    runner = _ImmediateExitRunner(jsonl_lines=[line], rc=0)
    router, _ = _build_router(tmp_path, runner=runner)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.run_codex(
            _discord_event("!c start", "code-repo"),
            sink,
            "repo",
            str(repo),
            "default",
            "",
            "",
            ["start"],
        )

    asyncio.run(run())
    texts = [msg for msg, _, _ in sink.sent]
    assert any("but no assistant message was emitted" in t for t in texts)
    assert any("Use `!c logs` for raw details." in t for t in texts)


def test_integration_budget_notice_precedes_terminal_summary(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    runner = _LateOutputRunner(
        initial_line='{"type":"item.completed","usage":{"input_tokens":2,"output_tokens":3,"total_tokens":5},"item":{"type":"agent_message","text":"Done"}}'
    )
    router, _ = _build_router(tmp_path, runner=runner)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))
    router._runtime_options_channels["chan"] = {"run_completion_min_seconds": 0}
    router._budget_thresholds_channel["chan"] = (1, 0)

    async def run():
        await router.run_codex(_discord_event("!c start", "code-repo"), sink, "repo", str(repo), "default", "", "", ["start"])
        await asyncio.sleep(0.05)

    asyncio.run(run())
    texts = [msg for msg, _, _ in sink.sent]
    assert any(t.startswith("Budget notice:") for t in texts)
    assert texts[-1].startswith("Run complete for session 'default'")


# ---------------------------------------------------------------------------
# Runtime options, lifecycle persistence, and operator visibility commands
# ---------------------------------------------------------------------------

def test_integration_options_show_and_set_runtime(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    router, _ = _build_router(tmp_path)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(_discord_event("!c options", "code-repo"), sink)
        await router.handle_message(_discord_event("!c options set run_heartbeat_seconds 90", "code-repo"), sink)
        await router.handle_message(_discord_event("!c options set run_completion_min_seconds 480", "code-repo"), sink)
        await router.handle_message(_discord_event("!c options set show_reasoning_details false", "code-repo"), sink)
        await router.handle_message(_discord_event("!c options", "code-repo"), sink)

    asyncio.run(run())
    texts = [msg for msg, _, _ in sink.sent]
    assert router._runtime_option_value("chan", "run_heartbeat_seconds") == 90
    assert router._runtime_option_value("chan", "run_completion_min_seconds") == 480
    assert router._runtime_option_value("chan", "show_reasoning_details") is False
    assert any("Runtime options (persisted):" in t for t in texts)
    assert any("local.show_reasoning_details: False" in t for t in texts)


def test_integration_options_set_requires_totp_when_enabled(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    secret = "JBSWY3DPEHPK3PXP"
    monkeypatch.setenv("DISCORD_TOTP_SECRET", secret)

    router, _ = _build_router(tmp_path, totp_enabled=True)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(_discord_event("!c options set run_heartbeat_seconds 90", "code-repo"), sink)
        code = _totp_code(secret)
        await router.handle_message(
            _discord_event(f"!c options set run_heartbeat_seconds 90 --totp {code}", "code-repo"),
            sink,
        )

    asyncio.run(run())
    texts = [msg for msg, _, _ in sink.sent]
    assert any("TOTP required for 'options'" in t for t in texts)
    assert any("Runtime option updated: run_heartbeat_seconds=90" in t for t in texts)


def test_integration_options_set_allowed_when_unlocked(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    secret = "JBSWY3DPEHPK3PXP"
    monkeypatch.setenv("DISCORD_TOTP_SECRET", secret)

    router, _ = _build_router(tmp_path, totp_enabled=True)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(_discord_event(f"!c unlock {_totp_code(secret)}", "code-repo"), sink)
        await router.handle_message(_discord_event("!c options set run_heartbeat_seconds 90", "code-repo"), sink)

    asyncio.run(run())
    texts = [msg for msg, _, _ in sink.sent]
    assert any("TOTP unlock active for 1h" in t for t in texts)
    assert any("Runtime option updated: run_heartbeat_seconds=90" in t for t in texts)
    assert not any("TOTP required for 'options'" in t for t in texts)


def test_integration_options_persist_across_router_restart(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    router, _ = _build_router(tmp_path)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run_set():
        await router.handle_message(_discord_event("!c options set run_completion_min_seconds 480", "code-repo"), sink)

    asyncio.run(run_set())

    router2, _ = _build_router(tmp_path)
    sink2 = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run_show():
        await router2.handle_message(_discord_event("!c options", "code-repo"), sink2)

    asyncio.run(run_show())
    texts = [msg for msg, _, _ in sink2.sent]
    assert any("local.run_completion_min_seconds: 480" in t for t in texts)


def test_integration_options_dm_global_scope_applies_to_channels(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    router, _ = _build_router(tmp_path)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(_discord_dm_event("!c options set show_reasoning_details false global"), sink)
        await router.handle_message(_discord_event("!c options", "code-repo"), sink)

    asyncio.run(run())
    texts = [msg for msg, _, _ in sink.sent]
    assert any("scope: global" in t for t in texts)
    assert any("local.show_reasoning_details: False" in t for t in texts)


def test_integration_options_channel_rejects_scope_token(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    router, _ = _build_router(tmp_path)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(_discord_event("!c options set run_heartbeat_seconds 120 global", "code-repo"), sink)

    asyncio.run(run())
    texts = [msg for msg, _, _ in sink.sent]
    assert any("Scope is only supported in DM." in t for t in texts)


def test_integration_cfg_set_returns_hint(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    router, _ = _build_router(tmp_path)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(_discord_event("!cfg set wrong_key value", "code-repo"), sink)

    asyncio.run(run())
    texts = [msg for msg, _, _ in sink.sent]
    assert any("Use `!cfg` to show effective config." in t for t in texts)
    assert any("!opts set <key> <value>" in t for t in texts)


# ---------------------------------------------------------------------------
# Session expiration, budgets, and audit command surfaces
# ---------------------------------------------------------------------------

def test_integration_session_prune_removes_idle_sessions(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    router, _ = _build_router(tmp_path)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))
    old_ts = (datetime.now(timezone.utc) - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    new_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def _seed(fs):
        from codebridge.sessions.state import ChannelState, SessionState

        ch = fs.channels.get("chan") or ChannelState()
        ch.sessions["old"] = SessionState(repo_name="repo", repo_path=str(repo), thread_id="", last_used_at=old_ts)
        ch.sessions["new"] = SessionState(repo_name="repo", repo_path=str(repo), thread_id="", last_used_at=new_ts)
        fs.channels["chan"] = ch

    router.state.update(_seed)

    async def run():
        await router.handle_message(_discord_event("!c session prune 1h", "code-repo"), sink)
        await router.handle_message(_discord_event("!c session status", "code-repo"), sink)

    asyncio.run(run())
    texts = [msg for msg, _, _ in sink.sent]
    assert any("Pruned 1 session(s)" in t for t in texts)
    assert any("- new:" in t for t in texts)
    assert not any("- old:" in t for t in texts)


def test_integration_session_archive_and_restore(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    router, runner = _build_router(tmp_path)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(_discord_event("!c start", "code-repo"), sink)
        for _ in range(50):
            proc = await router.get_active("chan", "default")
            if proc is not None:
                break
            await asyncio.sleep(0.01)
        await router.handle_message(_discord_event("!c session archive default", "code-repo"), sink)
        await router.handle_message(_discord_event("!c session restore default", "code-repo"), sink)
        await router.handle_message(_discord_event("!c stop", "code-repo"), sink)
        await asyncio.sleep(0.05)

    asyncio.run(run())
    texts = [msg for msg, _, _ in sink.sent]
    assert any("Archived session 'default'" in t for t in texts)
    assert any(args and args[0] == "resume" for args in runner.calls)


def test_integration_resume_expired_session_asks_user(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    router, runner = _build_router(tmp_path)
    router.cfg.state.session_idle_ttl_seconds = 3600
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))
    old_ts = (datetime.now(timezone.utc) - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ")

    def _seed(fs):
        from codebridge.sessions.state import ChannelState, SessionState

        ch = fs.channels.get("chan") or ChannelState()
        ch.sessions["default"] = SessionState(
            repo_name="repo",
            repo_path=str(repo),
            thread_id="thread-old",
            last_used_at=old_ts,
        )
        fs.channels["chan"] = ch

    router.state.update(_seed)

    async def run():
        await router.handle_message(_discord_event("!c resume default continue work", "code-repo"), sink)

    asyncio.run(run())
    texts = [msg for msg, _, _ in sink.sent]
    assert any("expired" in t.lower() for t in texts)
    assert any("!cont" in t for t in texts)
    assert any("!compact" in t for t in texts)
    assert any("!new" in t for t in texts)
    # No job started yet — waiting for user choice
    assert not runner.calls


def test_integration_resume_expired_session_compact_choice_uses_original_prompt(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    router, runner = _build_router(tmp_path)
    router.cfg.state.session_idle_ttl_seconds = 3600
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))
    old_ts = (datetime.now(timezone.utc) - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    captured_prompt = {"value": ""}

    def _build_start_args(repo_path: str, prompt: str, model: str, reasoning: str) -> list[str]:
        _ = (repo_path, model, reasoning)
        captured_prompt["value"] = prompt
        return ["start"]

    runner.build_start_args = _build_start_args

    def _seed(fs):
        from codebridge.sessions.state import ChannelState, SessionState

        ch = fs.channels.get("chan") or ChannelState()
        ch.sessions["default"] = SessionState(
            repo_name="repo",
            repo_path=str(repo),
            thread_id="thread-old",
            last_used_at=old_ts,
        )
        fs.channels["chan"] = ch

    router.state.update(_seed)

    async def run():
        await router.handle_message(_discord_event("!c resume default focus only tests", "code-repo"), sink)
        await router.handle_message(_discord_event("!compact", "code-repo"), sink)

    asyncio.run(run())
    assert "Session summary from the previous thread" in captured_prompt["value"]
    assert "New request:\nfocus only tests" in captured_prompt["value"]
    assert any(args == ["start"] for args in runner.calls)
    assert not any(args == ["resume", "thread-old"] for args in runner.calls)


def test_integration_start_conflict_bang_new_shortcut_starts_fresh(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    router, runner = _build_router(tmp_path)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    def _seed(fs):
        from codebridge.sessions.state import ChannelState, SessionState

        ch = fs.channels.get("chan") or ChannelState()
        ch.sessions["default"] = SessionState(
            repo_name="repo",
            repo_path=str(repo),
            thread_id="thread-old",
        )
        fs.channels["chan"] = ch

    router.state.update(_seed)

    async def run():
        await router.handle_message(_discord_event("!c start", "code-repo"), sink)
        await router.handle_message(_discord_event("!new", "code-repo"), sink)

    asyncio.run(run())
    texts = [msg for msg, _, _ in sink.sent]
    assert any("already exists" in t for t in texts)
    assert any("!new" in t for t in texts)
    assert any(args == ["start"] for args in runner.calls)
    assert not any(args == ["resume", "thread-old"] for args in runner.calls)


def test_integration_start_conflict_bang_cont_shortcut_continues(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    router, runner = _build_router(tmp_path)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    def _seed(fs):
        from codebridge.sessions.state import ChannelState, SessionState

        ch = fs.channels.get("chan") or ChannelState()
        ch.sessions["default"] = SessionState(
            repo_name="repo",
            repo_path=str(repo),
            thread_id="thread-old",
        )
        fs.channels["chan"] = ch

    router.state.update(_seed)

    async def run():
        await router.handle_message(_discord_event("!c start", "code-repo"), sink)
        await router.handle_message(_discord_event("!cont", "code-repo"), sink)

    asyncio.run(run())
    assert any(args == ["resume", "thread-old"] for args in runner.calls)
    assert not any(args == ["start"] for args in runner.calls)


def test_integration_start_conflict_bang_compact_summarizes_and_starts_fresh(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    router, runner = _build_router(tmp_path)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))
    captured_prompt = {"value": ""}

    def _build_start_args(repo_path: str, prompt: str, model: str, reasoning: str) -> list[str]:
        _ = (repo_path, model, reasoning)
        captured_prompt["value"] = prompt
        return ["start"]

    runner.build_start_args = _build_start_args

    def _seed(fs):
        from codebridge.sessions.state import ChannelState, SessionState

        ch = fs.channels.get("chan") or ChannelState()
        ch.sessions["default"] = SessionState(
            repo_name="repo",
            repo_path=str(repo),
            thread_id="thread-old",
        )
        fs.channels["chan"] = ch

    router.state.update(_seed)

    async def run():
        await router.handle_message(_discord_event("!c start", "code-repo"), sink)
        await router.handle_message(_discord_event("!compact", "code-repo"), sink)

    asyncio.run(run())
    texts = [msg for msg, _, _ in sink.sent]
    assert any("already exists" in t for t in texts)
    assert any("!compact" in t for t in texts)
    assert "Session summary from the previous thread" in captured_prompt["value"]
    assert any(args == ["start"] for args in runner.calls)
    assert not any(args == ["resume", "thread-old"] for args in runner.calls)


def test_integration_budget_status_and_set(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    router, _ = _build_router(tmp_path)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(_discord_event("!c budget status", "code-repo"), sink)
        await router.handle_message(_discord_event("!c budget set channel 100 200", "code-repo"), sink)
        await router.handle_message(_discord_event("!c budget set user 50 80", "code-repo"), sink)
        await router.handle_message(_discord_event("!c budget set session 30 60", "code-repo"), sink)
        await router.handle_message(_discord_event("!c budget set run 10 20", "code-repo"), sink)
        await router.handle_message(_discord_event("!c budget status", "code-repo"), sink)

    asyncio.run(run())
    texts = [msg for msg, _, _ in sink.sent]
    assert any("Budgets:" in t for t in texts)
    assert any("Budget channel thresholds set: soft=100, hard=200." in t for t in texts)
    assert any("Budget user thresholds set: soft=50, hard=80." in t for t in texts)
    assert any("Budget session thresholds set: soft=30, hard=60." in t for t in texts)
    assert any("Budget run thresholds set: soft=10, hard=20." in t for t in texts)
    assert any("soft=100 hard=200" in t for t in texts)
    assert any("Session usage (default):" in t for t in texts)
    assert any("Last run (default):" in t for t in texts)


def test_integration_budget_hard_limit_blocks_new_runs(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    router, runner = _build_router(tmp_path)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(_discord_event("!c budget set channel 0 10", "code-repo"), sink)
        router._budget_usage_channel["chan"] = 10
        await router.handle_message(_discord_event("!c start", "code-repo"), sink)

    asyncio.run(run())
    texts = [msg for msg, _, _ in sink.sent]
    assert any("Budget limit reached" in t for t in texts)
    assert not any(args and args[0] == "start" for args in runner.calls)


def test_integration_budget_session_hard_limit_blocks_new_runs(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    router, runner = _build_router(tmp_path)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(_discord_event("!c budget set session 0 10", "code-repo"), sink)
        from codebridge.routing.helpers import UsageStats

        router._usage.setdefault("chan", {})["default"] = UsageStats(total_tokens=10)
        await router.handle_message(_discord_event("!c start", "code-repo"), sink)

    asyncio.run(run())
    texts = [msg for msg, _, _ in sink.sent]
    assert any("session hard budget reached (10/10)" in t for t in texts)
    assert not any(args and args[0] == "start" for args in runner.calls)


def test_integration_budget_run_and_session_notices(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    class _UsageRunner(_FakeRunner):
        async def run(self, opts: Options):
            self.calls.append(opts.args)
            if opts.on_thread:
                await opts.on_thread("thread-1")
            if opts.on_jsonl:
                await opts.on_jsonl('{"type":"usage","usage":{"input_tokens":12,"output_tokens":8,"total_tokens":20}}')
                await opts.on_jsonl("hello from codex")
            self.last_proc = _ProcDone(0)
            return self.last_proc

    router, runner = _build_router(tmp_path, runner=_UsageRunner())
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(_discord_event("!c budget set run 10 15", "code-repo"), sink)
        await router.handle_message(_discord_event("!c budget set session 15 20", "code-repo"), sink)
        await router.handle_message(_discord_event("!c start", "code-repo"), sink)

    asyncio.run(run())
    texts = [msg for msg, _, _ in sink.sent]
    assert any("run hard budget reached (20/15)" in t for t in texts)
    assert any("session hard budget reached (20/20)" in t for t in texts)
    assert router._budget_last_run_total["chan"]["default"] == 20


def test_integration_audit_show_find_and_bundle(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    audit_dir = tmp_path / "audit" / "chan" / "default" / "thread-1"
    audit_dir.mkdir(parents=True)
    (audit_dir / "000001.request.json").write_text(
        json.dumps({"command": "start", "args": "", "timestamp": "2026-01-01T00:00:00Z"}),
        encoding="utf-8",
    )
    (audit_dir / "000001.codex.jsonl").write_text('{"type":"item.completed"}\n', encoding="utf-8")
    (audit_dir / "000001.discord_out.txt").write_text("hello\n", encoding="utf-8")
    (audit_dir / "000001.codex.stderr.txt").write_text("", encoding="utf-8")

    router, _ = _build_router(tmp_path)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    class _FakeAudit:
        def summaries(self, channel_id: str, session: str, limit: int):
            _ = (channel_id, session, limit)
            return [
                SimpleNamespace(
                    seq="000001",
                    channel_id="chan",
                    session="default",
                    thread_id="thread-1",
                    request={"command": "start", "args": "", "timestamp": "2026-01-01T00:00:00Z"},
                    path=str(audit_dir),
                    started_at="2026-01-01T00:00:00Z",
                    ended_at="2026-01-01T00:01:00Z",
                )
            ]

    router.audit = _FakeAudit()

    async def run():
        await router.handle_message(_discord_event("!c audit show 000001", "code-repo"), sink)
        await router.handle_message(_discord_event("!c audit find start", "code-repo"), sink)
        await router.handle_message(_discord_event("!c audit bundle 000001", "code-repo"), sink)

    asyncio.run(run())
    texts = [msg for msg, _, _ in sink.sent]
    assert any("Audit `000001`" in t for t in texts)
    assert any("Audit matches for `start`" in t for t in texts)
    assert any("Audit bundle ready" in t for t in texts)
    assert any(name == "audit-000001.zip" for _, name, _, _ in sink.files)
    bundle_paths = [path for path, name, _, _ in sink.files if name == "audit-000001.zip"]
    assert bundle_paths
    assert all(not os.path.exists(path) for path in bundle_paths)


# ---------------------------------------------------------------------------
# Help rendering, chunking, and transport-specific reply behavior
# ---------------------------------------------------------------------------

def test_integration_misc_shortcuts_dispatch(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    router, runner = _build_router(tmp_path)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def _fake_handle_updates(self, sink_obj, repo_path: str) -> None:
        _ = repo_path
        await self.reply(sink_obj, "updates-ok")

    async def _fake_handle_health(self, sink_obj, repo_path: str) -> None:
        _ = repo_path
        await self.reply(sink_obj, "health-ok")

    async def _fake_handle_branch(self, sink_obj, repo_path: str) -> None:
        _ = repo_path
        await self.reply(sink_obj, "branch-ok")

    router.handle_updates = MethodType(_fake_handle_updates, router)
    router.handle_health = MethodType(_fake_handle_health, router)
    router.handle_branch = MethodType(_fake_handle_branch, router)

    async def run():
        await router.handle_message(_discord_event("!help", "code-repo"), sink)
        await router.handle_message(_discord_event("!st", "code-repo"), sink)
        await router.handle_message(_discord_event("!u", "code-repo"), sink)
        await router.handle_message(_discord_event("!health", "code-repo"), sink)
        await router.handle_message(_discord_event("!diag", "code-repo"), sink)
        await router.handle_message(_discord_event("!branch", "code-repo"), sink)
        await router.handle_message(_discord_event("!w", "code-repo"), sink)
        await router.handle_message(_discord_event("!unlock status", "code-repo"), sink)
        await router.handle_message(_discord_event("!ul status", "code-repo"), sink)
        await router.handle_message(_discord_event("!lock status", "code-repo"), sink)
        await router.handle_message(_discord_event("!ps", "code-repo"), sink)
        await router.handle_message(_discord_event("!log", "code-repo"), sink)
        await router.handle_message(_discord_event("!retry", "code-repo"), sink)
        await router.handle_message(_discord_event("!c start", "code-repo"), sink)
        for _ in range(50):
            proc = await router.get_active("chan", "default")
            if proc is not None:
                break
            await asyncio.sleep(0.01)
        await router.handle_message(_discord_event("!y", "code-repo"), sink)
        await router.handle_message(_discord_event("!n", "code-repo"), sink)
        await router.handle_message(_discord_event("!a keep going", "code-repo"), sink)
        await router.handle_message(_discord_event("!pause", "code-repo"), sink)

    asyncio.run(run())
    texts = [msg for msg, _, _ in sink.sent]
    assert any("Commands:" in t for t in texts)
    assert any("Golden path:" in t for t in texts)
    assert any("Repo: repo" in t for t in texts)
    assert any("Related: !c start" in t for t in texts)
    assert any("updates-ok" in t for t in texts)
    assert sum("health-ok" in t for t in texts) >= 2
    assert any("branch-ok" in t for t in texts)
    assert any("No sessions are waiting for input." in t for t in texts)
    assert any("TOTP default unlock: inactive." in t for t in texts)
    assert any("TOTP gh unlock: inactive." in t for t in texts)
    assert any("No jobs queued or running." in t for t in texts)
    assert any("logs error:" in t for t in texts)
    assert any("No prior job to rerun." in t for t in texts)
    assert runner.last_proc is not None
    assert "yes\n" in runner.last_proc.writes
    assert "no\n" in runner.last_proc.writes
    assert "keep going\n" in runner.last_proc.writes
    assert runner.last_proc.interrupted is True


def test_integration_help_command_details(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    router, _ = _build_router(tmp_path)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(_discord_event("!c help git", "code-repo"), sink)

    asyncio.run(run())
    texts = [msg for msg, _, _ in sink.sent]
    assert any("Help: `git`" in t for t in texts)
    assert any("Preferred:" in t for t in texts)
    assert any("!c git status" in t for t in texts)


def test_integration_repo_help_is_chunked_for_discord_limit(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    router, _ = _build_router(tmp_path)
    router.cfg.discord.max_discord_message_chars = 250
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(_discord_event("!help", "code-repo"), sink)

    asyncio.run(run())
    texts = [msg for msg, _, _ in sink.sent]
    assert len(texts) > 1
    assert any("Golden path:" in t for t in texts)


def test_integration_repo_help_chunks_stay_within_limit_with_lock_prefix(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    router, _ = _build_router(tmp_path, totp_enabled=True)
    router.cfg.discord.max_discord_message_chars = 120
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(_discord_event("!help", "code-repo"), sink)

    asyncio.run(run())
    texts = [msg for msg, _, _ in sink.sent]
    assert len(texts) > 1
    assert all(len(t) <= 120 for t in texts)
    assert all(t.startswith("🔒 ") for t in texts if t)


def test_integration_contextual_sink_chunks_raw_send_globally(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    router, _ = _build_router(tmp_path)
    router.cfg.discord.max_discord_message_chars = 80
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))
    event = _discord_event("noop", "code-repo")
    wrapped = build_contextual_sink(event, sink, router.cfg.discord.max_discord_message_chars)

    async def run():
        await wrapped.send("x" * 260)

    asyncio.run(run())
    texts = [msg for msg, _, _ in sink.sent]
    assert len(texts) > 1
    assert all(len(t) <= 80 for t in texts)


def test_integration_dm_shortcuts_and_help_details(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    router, _ = _build_router(tmp_path)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def _fake_handle_updates(self, sink_obj, repo_path: str) -> None:
        _ = repo_path
        await self.reply(sink_obj, "updates-ok")

    async def _fake_handle_health(self, sink_obj, repo_path: str) -> None:
        _ = repo_path
        await self.reply(sink_obj, "health-ok")

    router.handle_updates = MethodType(_fake_handle_updates, router)
    router.handle_health = MethodType(_fake_handle_health, router)

    async def run():
        await router.handle_message(_discord_dm_event("!help"), sink)
        await router.handle_message(_discord_dm_event("!help git"), sink)
        await router.handle_message(_discord_dm_event("!c commands"), sink)
        await router.handle_message(_discord_dm_event("!c commands git"), sink)
        await router.handle_message(_discord_dm_event("!st"), sink)
        await router.handle_message(_discord_dm_event("!u"), sink)
        await router.handle_message(_discord_dm_event("!health"), sink)
        await router.handle_message(_discord_dm_event("!diag"), sink)
        await router.handle_message(_discord_dm_event("!unlock status"), sink)
        await router.handle_message(_discord_dm_event("!ul status"), sink)
        await router.handle_message(_discord_dm_event("!lock status"), sink)

    asyncio.run(run())
    texts = [msg for msg, _, _ in sink.sent]
    assert any("DM Commands:" in t for t in texts)
    assert any("Repo-bound workflow:" in t for t in texts)
    assert any("`!c gh <args>`" in t for t in texts)
    assert any("Unknown DM command `git`." in t for t in texts)
    assert any("`!c bind <repo>`" in t for t in texts)
    assert any("Bound repo: none" in t for t in texts)
    assert any("updates-ok" in t for t in texts)
    assert sum("health-ok" in t for t in texts) >= 2
    assert sum("TOTP default unlock: inactive." in t for t in texts) >= 2


def test_integration_dm_help_is_chunked_for_discord_limit(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    router, _ = _build_router(tmp_path)
    router.cfg.discord.max_discord_message_chars = 250
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(_discord_dm_event("!help"), sink)

    asyncio.run(run())
    texts = [msg for msg, _, _ in sink.sent]
    assert len(texts) > 1
    assert any("DM Commands:" in t for t in texts)


def test_dm_assistant_disabled_keeps_no_repo_bound_message(tmp_path):
    router, _ = _build_router(tmp_path)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(_discord_dm_event("what repos are running?"), sink)

    asyncio.run(run())
    assert any("No repo bound" in msg for msg, _, _ in sink.sent)


def test_dm_assistant_first_message_starts_dm_session(tmp_path):
    repo = tmp_path / "pycodebridge"
    repo.mkdir()
    router, runner = _build_router(tmp_path)
    router.cfg.dm_assistant.enabled = True
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))
    captured = {"prompt": "", "repo_path": "", "model": "", "reasoning": ""}

    def _build_start_args(repo_path: str, prompt: str, model: str, reasoning: str) -> list[str]:
        captured["repo_path"] = repo_path
        captured["prompt"] = prompt
        captured["model"] = model
        captured["reasoning"] = reasoning
        return ["assistant-start"]

    runner.build_start_args = _build_start_args

    async def run():
        await router.handle_message(_discord_dm_event("what sessions are active?"), sink)

    asyncio.run(run())
    assert runner.calls and runner.calls[0] == ["assistant-start"]
    assert captured["repo_path"] == str(repo)
    assert "pycodebridge assistant" in captured["prompt"]
    assert "## Current user message\nwhat sessions are active?" in captured["prompt"]
    state = router.state.load()
    assert "dm" in state.channels["dm-1"].sessions


def test_dm_assistant_second_message_resumes_dm_session(tmp_path):
    repo = tmp_path / "pycodebridge"
    repo.mkdir()
    router, runner = _build_router(tmp_path)
    router.cfg.dm_assistant.enabled = True
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))
    captured = {"resume_prompt": ""}

    def _build_resume_args(repo_path: str, thread_id: str, prompt: str, model: str, reasoning: str) -> list[str]:
        _ = (repo_path, model, reasoning)
        captured["resume_prompt"] = prompt
        return ["assistant-resume", thread_id]

    async def _completed_run(opts: Options):
        runner.calls.append(opts.args)
        if opts.on_thread:
            await opts.on_thread("thread-1")
        return _ProcDone(0)

    runner.build_resume_args = _build_resume_args
    runner.run = _completed_run

    async def run():
        await router.handle_message(_discord_dm_event("first question"), sink)
        await asyncio.sleep(0.05)
        await router.handle_message(_discord_dm_event("second question"), sink)
        await asyncio.sleep(0.05)

    asyncio.run(run())
    assert ["assistant-resume", "thread-1"] in runner.calls
    assert captured["resume_prompt"] == "second question"


def test_dm_assistant_expired_session_prompts_for_choice(tmp_path):
    repo = tmp_path / "pycodebridge"
    repo.mkdir()
    router, runner = _build_router(tmp_path)
    router.cfg.dm_assistant.enabled = True
    router.cfg.state.session_idle_ttl_seconds = 1
    old = (datetime.now(timezone.utc) - timedelta(seconds=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
    router.update_state("dm-1", "dm", "pycodebridge", str(repo), "thread-old", "", "")

    def _mark_old(state):
        state.channels["dm-1"].sessions["dm"].last_used_at = old

    router.state.update(_mark_old)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(_discord_dm_event("continue this"), sink)

    asyncio.run(run())
    assert not runner.calls
    assert any("Session 'dm' expired" in msg for msg, _, _ in sink.sent)
    pending = asyncio.run(router.consume_pending("dm-1", "dm"))
    assert pending is not None
    assert pending.prompt == "continue this"


def test_dm_assistant_prompt_requires_default_totp_when_enabled(tmp_path, monkeypatch):
    repo = tmp_path / "pycodebridge"
    repo.mkdir()
    secret = "JBSWY3DPEHPK3PXP"
    monkeypatch.setenv("DISCORD_TOTP_SECRET", secret)

    router, runner = _build_router(tmp_path, totp_enabled=True)
    router.cfg.dm_assistant.enabled = True
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(_discord_dm_event("assistant question"), sink)

    asyncio.run(run())
    assert not runner.calls
    assert any("TOTP required for 'resume'" in msg for msg, _, _ in sink.sent)


# ---------------------------------------------------------------------------
# TOTP authorization model (default scope, gh scope, lock state, cooldowns)
# ---------------------------------------------------------------------------

def test_totp_required_for_state_changing_and_gh(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    secret = "JBSWY3DPEHPK3PXP"
    monkeypatch.setenv("DISCORD_TOTP_SECRET", secret)

    router, runner = _build_router(tmp_path, totp_enabled=True)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(_discord_event("!c start", "code-repo"), sink)
        await router.handle_message(_discord_event("!c gh pr status", "code-repo"), sink)
        start_code = _totp_code(secret)
        await router.handle_message(_discord_event(f"!c start --totp {start_code}", "code-repo"), sink)
        gh_code = _totp_code(secret, step_offset=1)
        await router.handle_message(_discord_event(f"!c gh --totp {gh_code} pr status", "code-repo"), sink)

    asyncio.run(run())
    assert any("TOTP required for 'start'" in msg for msg, _, _ in sink.sent)
    assert any("TOTP required for 'gh'" in msg for msg, _, _ in sink.sent)
    assert any(args and args[0] == "start" for args in runner.calls)


def test_dm_admin_reset_all_requires_totp_before_confirmation(tmp_path, monkeypatch):
    secret = "JBSWY3DPEHPK3PXP"
    monkeypatch.setenv("DISCORD_TOTP_SECRET", secret)

    router, _ = _build_router(tmp_path, totp_enabled=True)
    router.cfg.discord.dm_admin_enabled = True
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))
    probe = _discord_dm_event("")

    async def run():
        await router.handle_dm_message(_discord_dm_event("!c reset all"), sink)
        assert router.has_reset_all_confirmation_pending(probe) is False

        await router.handle_dm_message(_discord_dm_event(f"!c reset all --totp {_totp_code(secret)}"), sink)
        assert router.has_reset_all_confirmation_pending(probe) is True

        await router.handle_dm_message(_discord_dm_event("yes"), sink)

    asyncio.run(run())
    texts = [msg for msg, _, _ in sink.sent]
    assert any("TOTP required for 'reset'" in t for t in texts)
    assert any("Are you sure you want to reset all sessions" in t for t in texts)
    assert any("Reset all sessions:" in t for t in texts)


def test_totp_unlock_allows_plain_resume_for_ttl(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    secret = "JBSWY3DPEHPK3PXP"
    monkeypatch.setenv("DISCORD_TOTP_SECRET", secret)

    router, runner = _build_router(tmp_path, totp_enabled=True)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(_discord_event(f"!c unlock {_totp_code(secret)} 2h", "code-repo"), sink)
        await router.handle_message(_discord_event("hi there", "code-repo"), sink)

    asyncio.run(run())
    assert any("TOTP unlock active for 2h" in msg for msg, _, _ in sink.sent)
    assert any(args and args[0] == "start" for args in runner.calls)


def test_totp_unlock_still_requires_totp_for_high_risk(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    secret = "JBSWY3DPEHPK3PXP"
    monkeypatch.setenv("DISCORD_TOTP_SECRET", secret)

    router, _ = _build_router(tmp_path, totp_enabled=True)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(_discord_event(f"!c unlock {_totp_code(secret)}", "code-repo"), sink)
        await router.handle_message(_discord_event("!c gh pr status", "code-repo"), sink)

    asyncio.run(run())
    assert any("TOTP unlock active for 1h" in msg for msg, _, _ in sink.sent)
    assert any("TOTP required for 'gh'" in msg for msg, _, _ in sink.sent)


def test_totp_command_group_toggles_control_enforcement(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    secret = "JBSWY3DPEHPK3PXP"
    monkeypatch.setenv("DISCORD_TOTP_SECRET", secret)

    router, _ = _build_router(tmp_path, totp_enabled=True)
    event = _discord_event("!c status", "code-repo")

    assert router._totp_required_for_command(event, "gh", "pr status") is True
    router.cfg.discord.totp_enforce_gh = False
    assert router._totp_required_for_command(event, "gh", "pr status") is False

    assert router._totp_required_for_command(event, "git", "status") is True
    router.cfg.discord.totp_enforce_git = False
    assert router._totp_required_for_command(event, "git", "status") is False
    router.cfg.discord.totp_enforce_git = True
    assert router._totp_required_for_command(event, "branch", "") is False

    router._set_totp_unlock(event, "default", 3600)
    assert router._totp_required_for_command(event, "create", "demo-repo") is True
    router.cfg.discord.totp_enforce_high_risk = False
    assert router._totp_required_for_command(event, "create", "demo-repo") is False


def test_totp_defaults_follow_command_spec_auth(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    secret = "JBSWY3DPEHPK3PXP"
    monkeypatch.setenv("DISCORD_TOTP_SECRET", secret)

    router, _ = _build_router(tmp_path, totp_enabled=True)
    event = _discord_event("!c status", "code-repo")

    # `start` is AUTH_UNLOCK by default.
    assert router._totp_required_for_command(event, "start", "") is True

    # Changing auth metadata should immediately affect default enforcement.
    spec = router._command_registry["start"]
    router._command_registry["start"] = replace(spec, auth="open")
    assert router._totp_required_for_command(event, "start", "") is False


def test_totp_unlock_status_and_lock(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    secret = "JBSWY3DPEHPK3PXP"
    monkeypatch.setenv("DISCORD_TOTP_SECRET", secret)

    router, _ = _build_router(tmp_path, totp_enabled=True)
    router.cfg.discord.allow_plain_prompts = True
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(_discord_event(f"!c unlock {_totp_code(secret)} 1h", "code-repo"), sink)
        await router.handle_message(_discord_event("!c unlock status", "code-repo"), sink)
        await router.handle_message(_discord_event("!c lock status", "code-repo"), sink)
        await router.handle_message(_discord_event("!c status", "code-repo"), sink)
        await router.handle_message(_discord_event("!c lock", "code-repo"), sink)
        await router.handle_message(_discord_event("hello", "code-repo"), sink)

    asyncio.run(run())
    assert any("TOTP default unlock: active for" in msg for msg, _, _ in sink.sent)
    assert any("TOTP gh unlock: inactive." in msg for msg, _, _ in sink.sent)
    assert any("Unlocks: default" in msg for msg, _, _ in sink.sent)
    assert any("TOTP unlocks cleared for your account." in msg for msg, _, _ in sink.sent)
    assert any("TOTP required for 'resume'" in msg for msg, _, _ in sink.sent)


def test_totp_lock_extend_updates_remaining_time(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    secret = "JBSWY3DPEHPK3PXP"
    monkeypatch.setenv("DISCORD_TOTP_SECRET", secret)

    router, _ = _build_router(tmp_path, totp_enabled=True)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(_discord_event(f"!c unlock {_totp_code(secret)} 1h", "code-repo"), sink)
        await router.handle_message(_discord_event("!c lock extend 30m", "code-repo"), sink)
        await router.handle_message(_discord_event(f"!c lock extend 30m --totp {_totp_code(secret, step_offset=1)}", "code-repo"), sink)
        await router.handle_message(_discord_event("!c lock status", "code-repo"), sink)

    asyncio.run(run())
    assert any("TOTP required for 'lock'" in msg for msg, _, _ in sink.sent)
    assert any("unlock extended by 30m" in msg for msg, _, _ in sink.sent)
    assert any("TOTP default unlock: active for" in msg for msg, _, _ in sink.sent)


def test_totp_extend_requires_active_unlock_window(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    secret = "JBSWY3DPEHPK3PXP"
    monkeypatch.setenv("DISCORD_TOTP_SECRET", secret)

    router, _ = _build_router(tmp_path, totp_enabled=True)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(_discord_event(f"!c lock extend 30m --totp {_totp_code(secret)}", "code-repo"), sink)
        await router.handle_message(_discord_event(f"!c unlock extend 30m --totp {_totp_code(secret, step_offset=1)}", "code-repo"), sink)

    asyncio.run(run())
    assert any("No active unlock window to extend" in msg for msg, _, _ in sink.sent)


def test_totp_unlock_extend_alias_works(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    secret = "JBSWY3DPEHPK3PXP"
    monkeypatch.setenv("DISCORD_TOTP_SECRET", secret)

    router, _ = _build_router(tmp_path, totp_enabled=True)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(_discord_event(f"!c unlock {_totp_code(secret)} 1h", "code-repo"), sink)
        await router.handle_message(_discord_event(f"!c unlock extend 15m --totp {_totp_code(secret, step_offset=1)}", "code-repo"), sink)
        await router.handle_message(_discord_event("!c lock status", "code-repo"), sink)

    asyncio.run(run())
    assert any("unlock extended by 15m" in msg for msg, _, _ in sink.sent)
    assert any("TOTP default unlock: active for" in msg for msg, _, _ in sink.sent)


def test_totp_unlock_gh_is_separate_scope(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    secret = "JBSWY3DPEHPK3PXP"
    monkeypatch.setenv("DISCORD_TOTP_SECRET", secret)

    router, _ = _build_router(tmp_path, totp_enabled=True)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(_discord_event(f"!c unlock gh {_totp_code(secret)} 1h", "code-repo"), sink)
        await router.handle_message(_discord_event("!c gh pr status", "code-repo"), sink)
        await router.handle_message(_discord_event("!c start", "code-repo"), sink)

    asyncio.run(run())
    assert any("TOTP gh unlock active for 1h" in msg for msg, _, _ in sink.sent)
    assert not any("TOTP required for 'gh'" in msg for msg, _, _ in sink.sent)
    assert any("TOTP required for 'start'" in msg for msg, _, _ in sink.sent)


def test_totp_unlock_all_covers_default_and_gh(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    secret = "JBSWY3DPEHPK3PXP"
    monkeypatch.setenv("DISCORD_TOTP_SECRET", secret)

    router, runner = _build_router(tmp_path, totp_enabled=True)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(_discord_event(f"!c unlock all {_totp_code(secret)} 1h", "code-repo"), sink)
        await router.handle_message(_discord_event("!c start", "code-repo"), sink)
        await router.handle_message(_discord_event("!c gh pr status", "code-repo"), sink)

    asyncio.run(run())
    assert any("default + gh" in msg for msg, _, _ in sink.sent)
    assert not any("TOTP required for 'start'" in msg for msg, _, _ in sink.sent)
    assert not any("TOTP required for 'gh'" in msg for msg, _, _ in sink.sent)
    assert any(args and args[0] == "start" for args in runner.calls)


def test_totp_unlock_is_global_for_user_across_channels(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    secret = "JBSWY3DPEHPK3PXP"
    monkeypatch.setenv("DISCORD_TOTP_SECRET", secret)

    router, runner = _build_router(tmp_path, totp_enabled=True)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(_discord_event(f"!c unlock {_totp_code(secret)} 1h", "code-repo", channel_id="chan-a"), sink)
        await router.handle_message(_discord_event("hello", "code-repo", channel_id="chan-b"), sink)
        await router.handle_message(_discord_event("!c lock", "code-repo", channel_id="chan-b"), sink)
        await router.handle_message(_discord_event("!c start", "code-repo", channel_id="chan-a"), sink)

    asyncio.run(run())
    assert any(args and args[0] == "start" for args in runner.calls)
    assert any("TOTP unlocks cleared for your account." in msg for msg, _, _ in sink.sent)
    assert any("TOTP required for 'start'" in msg for msg, _, _ in sink.sent)


def test_totp_replies_include_lock_emoji_prefix(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    secret = "JBSWY3DPEHPK3PXP"
    monkeypatch.setenv("DISCORD_TOTP_SECRET", secret)

    router, _ = _build_router(tmp_path, totp_enabled=True)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(_discord_event("!c status", "code-repo"), sink)
        await router.handle_message(_discord_event(f"!c unlock {_totp_code(secret)}", "code-repo"), sink)
        await router.handle_message(_discord_event("!c status", "code-repo"), sink)

    asyncio.run(run())
    messages = [msg for msg, _, _ in sink.sent]
    assert any(msg.startswith("🔒 ") for msg in messages)
    assert any(msg.startswith("🔓 ") for msg in messages)


def test_totp_git_status_requires_totp_when_locked(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    secret = "JBSWY3DPEHPK3PXP"
    monkeypatch.setenv("DISCORD_TOTP_SECRET", secret)

    router, _ = _build_router(tmp_path, totp_enabled=True)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(_discord_event("!c git status", "code-repo"), sink)

    asyncio.run(run())
    assert any("TOTP required for 'git'" in msg for msg, _, _ in sink.sent)


def test_totp_bang_git_status_requires_totp_when_locked(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    secret = "JBSWY3DPEHPK3PXP"
    monkeypatch.setenv("DISCORD_TOTP_SECRET", secret)

    router, _ = _build_router(tmp_path, totp_enabled=True)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(_discord_event("!git status", "code-repo"), sink)

    asyncio.run(run())
    assert any("TOTP required for 'git'" in msg for msg, _, _ in sink.sent)


def test_totp_git_push_allowed_without_totp_when_unlocked(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    secret = "JBSWY3DPEHPK3PXP"
    monkeypatch.setenv("DISCORD_TOTP_SECRET", secret)

    router, _ = _build_router(tmp_path, totp_enabled=True)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(_discord_event(f"!c unlock {_totp_code(secret)} 1h", "code-repo"), sink)
        await router.handle_message(_discord_event("!c git push", "code-repo"), sink)

    asyncio.run(run())
    assert not any("TOTP required for 'git'" in msg for msg, _, _ in sink.sent)
    assert not any("Unknown git subcommand." in msg for msg, _, _ in sink.sent)


def test_totp_git_remote_set_url_still_requires_totp_when_unlocked(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    secret = "JBSWY3DPEHPK3PXP"
    monkeypatch.setenv("DISCORD_TOTP_SECRET", secret)

    router, _ = _build_router(tmp_path, totp_enabled=True)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(_discord_event(f"!c unlock {_totp_code(secret)} 1h", "code-repo"), sink)
        await router.handle_message(
            _discord_event("!c git remote set-url origin https://github.com/acme/repo.git", "code-repo"),
            sink,
        )

    asyncio.run(run())
    assert any("TOTP required for 'git'" in msg for msg, _, _ in sink.sent)


def test_totp_bang_git_remote_set_url_still_requires_totp_when_unlocked(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    secret = "JBSWY3DPEHPK3PXP"
    monkeypatch.setenv("DISCORD_TOTP_SECRET", secret)

    router, _ = _build_router(tmp_path, totp_enabled=True)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(_discord_event(f"!c unlock {_totp_code(secret)} 1h", "code-repo"), sink)
        await router.handle_message(
            _discord_event("!git remote set-url origin https://github.com/acme/repo.git", "code-repo"),
            sink,
        )

    asyncio.run(run())
    assert any("TOTP required for 'git'" in msg for msg, _, _ in sink.sent)


def test_totp_bang_gh_requires_gh_scope_or_totp(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    secret = "JBSWY3DPEHPK3PXP"
    monkeypatch.setenv("DISCORD_TOTP_SECRET", secret)

    router, _ = _build_router(tmp_path, totp_enabled=True)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(_discord_event("!gh pr status", "code-repo"), sink)

    asyncio.run(run())
    assert any("TOTP required for 'gh'" in msg for msg, _, _ in sink.sent)


def test_totp_updates_read_only_without_totp(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    secret = "JBSWY3DPEHPK3PXP"
    monkeypatch.setenv("DISCORD_TOTP_SECRET", secret)

    router, _ = _build_router(tmp_path, totp_enabled=True)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))
    called: list[str] = []

    async def _fake_handle_updates(self, sink_obj, repo_path: str) -> None:
        called.append(repo_path)
        await self.reply(sink_obj, "updates-ok")

    router.handle_updates = MethodType(_fake_handle_updates, router)

    async def run():
        await router.handle_message(_discord_event("!c updates", "code-repo"), sink)

    asyncio.run(run())
    assert called == [str(repo)]
    assert not any("TOTP required for 'updates'" in msg for msg, _, _ in sink.sent)


def test_totp_required_for_config_tests_download_logs_and_upload(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    (repo / "note.txt").write_text("hi")

    secret = "JBSWY3DPEHPK3PXP"
    monkeypatch.setenv("DISCORD_TOTP_SECRET", secret)

    router, _ = _build_router(tmp_path, totp_enabled=True)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def save_noop(path: str) -> None:
        _ = path

    upload_event = MessageEvent(
        platform="discord",
        content="",
        channel_id="chan",
        channel_name="code-repo",
        author_id="user",
        author_is_bot=False,
        is_dm=False,
        guild_id="guild",
        attachments=[Attachment(filename="note.txt", size=2, content_type="text/plain", save=save_noop)],
        raw_event=_FakeDiscordMessage(_FakeDiscordChannel(is_private=True, channel_id="chan", channel_name="code-repo")),
    )

    async def run():
        await router.handle_message(_discord_event("!c config", "code-repo"), sink)
        await router.handle_message(_discord_event("!c tests", "code-repo"), sink)
        await router.handle_message(_discord_event("!c download note.txt", "code-repo"), sink)
        await router.handle_message(_discord_event("!c logs", "code-repo"), sink)
        await router.handle_message(upload_event, sink)

    asyncio.run(run())
    assert any("TOTP required for 'config'" in msg for msg, _, _ in sink.sent)
    assert any("TOTP required for 'tests'" in msg for msg, _, _ in sink.sent)
    assert any("TOTP required for 'download'" in msg for msg, _, _ in sink.sent)
    assert any("TOTP required for 'logs'" in msg for msg, _, _ in sink.sent)
    assert any("TOTP required for 'upload'" in msg for msg, _, _ in sink.sent)


def test_totp_file_transfer_group_can_be_disabled(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    (repo / "note.txt").write_text("hi")

    secret = "JBSWY3DPEHPK3PXP"
    monkeypatch.setenv("DISCORD_TOTP_SECRET", secret)

    router, _ = _build_router(tmp_path, totp_enabled=True)
    router.cfg.discord.totp_enforce_file_transfer = False
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def save_noop(path: str) -> None:
        _ = path

    upload_event = MessageEvent(
        platform="discord",
        content="",
        channel_id="chan",
        channel_name="code-repo",
        author_id="user",
        author_is_bot=False,
        is_dm=False,
        guild_id="guild",
        attachments=[Attachment(filename="note.txt", size=2, content_type="text/plain", save=save_noop)],
        raw_event=_FakeDiscordMessage(_FakeDiscordChannel(is_private=True, channel_id="chan", channel_name="code-repo")),
    )

    async def run():
        await router.handle_message(_discord_event("!c download note.txt", "code-repo"), sink)
        await router.handle_message(upload_event, sink)

    asyncio.run(run())
    assert sink.files and sink.files[0][1] == "note.txt"
    assert any("Where do you want to put these file(s)?" in msg for msg, _, _ in sink.sent)
    assert not any("TOTP required for 'download'" in msg for msg, _, _ in sink.sent)
    assert not any("TOTP required for 'upload'" in msg for msg, _, _ in sink.sent)


def test_totp_rate_limit_lock_and_cooldown(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    secret = "JBSWY3DPEHPK3PXP"
    monkeypatch.setenv("DISCORD_TOTP_SECRET", secret)

    router, runner = _build_router(tmp_path, totp_enabled=True)
    now = [1000.0]
    router._totp_limiter = TotpAttemptLimiter(
        max_failures=2,
        window_seconds=120,
        cooldown_seconds=60,
        now_fn=lambda: now[0],
    )
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(_discord_event("!c start --totp 000000", "code-repo"), sink)
        await router.handle_message(_discord_event("!c start --totp 000000", "code-repo"), sink)
        await router.handle_message(_discord_event(f"!c start --totp {_totp_code(secret)}", "code-repo"), sink)
        now[0] += 61
        await router.handle_message(_discord_event(f"!c start --totp {_totp_code(secret)}", "code-repo"), sink)

    asyncio.run(run())
    assert any("Invalid TOTP code." in msg for msg, _, _ in sink.sent)
    assert any("Too many invalid TOTP attempts." in msg for msg, _, _ in sink.sent)
    assert any(args and args[0] == "start" for args in runner.calls)
    event_names = [name for _, name, _ in router.logger.entries]
    assert "security.totp_invalid" in event_names
    assert "security.totp_locked" in event_names
    assert "security.totp_unlock" in event_names
    assert "security.totp_success" in event_names


def test_dm_audit_sanitizes_unlock_totp_before_valid_and_replay_paths(tmp_path, monkeypatch):
    secret = "JBSWY3DPEHPK3PXP"
    monkeypatch.setenv("DISCORD_TOTP_SECRET", secret)
    audit = AuditLogger(str(tmp_path / "logs"))
    router, _ = _build_router(tmp_path, totp_enabled=True, audit=audit)
    router.cfg.discord.dm_admin_enabled = True
    router.cfg.discord.allowed_user_ids = ["user"]
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))
    code = _totp_code(secret)

    async def run():
        await router.handle_dm_message(_discord_dm_event(f"!c unlock {code}"), sink)
        await router.handle_dm_message(_discord_dm_event(f"!c unlock {code}"), sink)

    asyncio.run(run())
    request_text = "\n".join(path.read_text(encoding="utf-8") for path in (tmp_path / "logs").rglob("*.request.json"))
    output_text = "\n".join(path.read_text(encoding="utf-8") for path in (tmp_path / "logs").rglob("*.discord_out.txt"))
    assert code not in request_text
    assert code not in output_text
    assert "--totp <redacted>" in request_text
    assert any("TOTP code already used" in msg for msg, _, _ in sink.sent)


def test_dm_admin_audit_sanitizes_invalid_high_risk_totp_args(tmp_path, monkeypatch):
    monkeypatch.setenv("DISCORD_TOTP_SECRET", "JBSWY3DPEHPK3PXP")
    audit = AuditLogger(str(tmp_path / "logs"))
    router, _ = _build_router(tmp_path, totp_enabled=True, audit=audit)
    router.cfg.discord.dm_admin_enabled = True
    router.cfg.discord.allowed_user_ids = ["user"]
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_dm_message(_discord_dm_event("!c create demo --totp 000000"), sink)
        await router.handle_dm_message(_discord_dm_event("!c deleterepo demo --totp 000000 --confirm-dangerous"), sink)

    asyncio.run(run())
    raw_logs = "\n".join(path.read_text(encoding="utf-8") for path in (tmp_path / "logs").rglob("*") if path.is_file())
    assert "000000" not in raw_logs
    assert raw_logs.count("--totp <redacted>") >= 2
    assert any("Invalid TOTP code." in msg for msg, _, _ in sink.sent)


# ---------------------------------------------------------------------------
# Regression tests for local router helper behavior
# ---------------------------------------------------------------------------

def test_router_dm_binding_is_normalized(tmp_path):
    router, _ = _build_router(tmp_path)
    event = MessageEvent(
        platform="discord",
        content="",
        channel_id="dm-1",
        channel_name="",
        author_id="user",
        author_is_bot=False,
        is_dm=True,
    )

    router.set_dm_binding(event, "ProbablyFine")
    assert router.get_dm_binding(event) == "probablyfine"


def _unsupported_model_error_line(model: str = "gpt-5.3-codex") -> str:
    return json.dumps(
        {
            "type": "error",
            "status": 400,
            "error": {
                "type": "invalid_request_error",
                "message": f"The '{model}' model is not supported when using Codex with a ChatGPT account.",
            },
        }
    )


def _claude_usage_limit_result_line(message: str = "You've hit your session limit · resets 6:30pm (UTC)") -> str:
    return json.dumps(
        {
            "type": "result",
            "subtype": "error",
            "is_error": True,
            "api_error_status": 429,
            "result": message,
            "session_id": "thread-1",
        }
    )


def _claude_success_result_line() -> str:
    return json.dumps(
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "session_id": "thread-1",
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }
    )


def test_run_codex_wraps_duplicate_unsupported_model_jsonl_error(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    line = _unsupported_model_error_line()
    runner = _ImmediateExitRunner(jsonl_lines=[line, line], rc=1)
    router, _ = _build_router(tmp_path, runner=runner)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))
    event = _discord_event("!c resume fix", "code-repo")

    async def run():
        await router.run_codex(
            event,
            sink,
            "repo",
            str(repo),
            "default",
            "gpt-5.3-codex",
            "",
            ["exec", "resume"],
        )

    asyncio.run(run())
    output = "\n".join(msg for msg, _, _ in sink.sent)
    assert output.count("Cannot use model 'gpt-5.3-codex' with this ChatGPT account.") == 1
    assert "Session 'default' is configured for unsupported model 'gpt-5.3-codex'." in output
    assert "`!model default <model-id>`" in output
    assert "`!reset default`" in output
    assert '"type": "error"' not in output
    assert '{"type":"error"' not in output


def test_relay_output_send_failure_does_not_abort_run(tmp_path):
    router, _ = _build_router(tmp_path)
    sink = _FailingSendSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router._relay_output_text(
            sink,
            "chan",
            "default",
            "repo",
            None,
            "x" * 200,
        )

    asyncio.run(run())

    assert any(
        level == "warning"
        and name == "discord.output_send_failed"
        and extra["error"] == "Separator is not found, and chunk exceed the limit"
        for level, name, extra in router.logger.entries
    )


def test_run_codex_unsupported_configured_default_points_to_config(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    line = _unsupported_model_error_line()
    runner = _ImmediateExitRunner(jsonl_lines=[line], rc=1)
    router, _ = _build_router(tmp_path, runner=runner)
    router.cfg.codex.model = "gpt-5.3-codex"
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))
    event = _discord_event("!c resume fix", "code-repo")

    async def run():
        await router.run_codex(
            event,
            sink,
            "repo",
            str(repo),
            "default",
            "gpt-5.3-codex",
            "",
            ["exec", "--model", "gpt-5.3-codex"],
        )

    asyncio.run(run())
    output = "\n".join(msg for msg, _, _ in sink.sent)
    assert "Configured default model is unsupported: 'gpt-5.3-codex'." in output
    assert "Change `codex.model` in the bridge config" in output
    assert "`!model default <model-id>`" not in output
    assert "`!reset default`" not in output


def test_run_codex_surfaces_claude_usage_limit_result_even_on_zero_exit(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    message = "You've hit your session limit · resets 6:30pm (UTC)"
    runner = _ClaudeImmediateExitRunner(jsonl_lines=[_claude_usage_limit_result_line(message)], rc=0)
    router, _ = _build_router(tmp_path, runner=runner)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))
    event = _discord_event("!c resume fix", "code-repo")

    async def run():
        await router.run_codex(
            event,
            sink,
            "repo",
            str(repo),
            "default",
            "",
            "",
            ["-p", "fix"],
        )

    asyncio.run(run())
    output = "\n".join(msg for msg, _, _ in sink.sent)
    assert "Claude reported a usage limit:" in output
    assert message in output
    assert "local reset: 20:30 Central European time" in output
    assert "Run complete" not in output


def test_run_codex_final_result_kills_lingering_process(tmp_path, monkeypatch):
    import codebridge.routing.router as router_mod

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    runner = _ClaudeFinalResultLingeringRunner(_claude_success_result_line())
    router, _ = _build_router(tmp_path, runner=runner)
    router._runtime_options_channels["chan"] = {
        "run_heartbeat_seconds": 1,
        "run_completion_min_seconds": 0,
    }
    monkeypatch.setattr(router_mod, "_FINAL_RESULT_EXIT_GRACE_SECONDS", 0.01)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))
    event = _discord_event("!c resume fix", "code-repo")
    active_after = {}

    async def run():
        await router.run_codex(
            event,
            sink,
            "repo",
            str(repo),
            "default",
            "",
            "",
            ["-p", "fix"],
            backend=runner,
        )
        active_after["proc"] = await router.get_active("chan", "default")

    asyncio.run(run())
    assert runner.last_proc is not None
    assert runner.last_proc.killed is True
    assert active_after["proc"] is None
    texts = [msg for msg, _, _ in sink.sent]
    assert not any("working for" in text for text in texts)
    assert any("but no assistant message was emitted" in text for text in texts)


def test_claude_usage_limit_formatter_adds_central_european_reset_time(tmp_path):
    router, _ = _build_router(tmp_path)
    message = "You've hit your session limit · resets 6:30pm (UTC)"

    formatted = router._format_claude_usage_limit_message(
        message,
        now_utc=datetime(2026, 6, 9, 18, 3, tzinfo=timezone.utc),
    )

    assert formatted == (
        "You've hit your session limit · resets 6:30pm (UTC) "
        "(local reset: 20:30 Central European time)"
    )


def test_run_codex_surfaces_claude_usage_limit_stderr(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    message = "Error: Claude usage limit reached. Try again in 2 hours."
    runner = _ClaudeImmediateExitRunner(stderr_lines=[message], rc=1)
    router, _ = _build_router(tmp_path, runner=runner)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))
    event = _discord_event("!c resume fix", "code-repo")

    async def run():
        await router.run_codex(
            event,
            sink,
            "repo",
            str(repo),
            "default",
            "",
            "",
            ["-p", "fix"],
        )

    asyncio.run(run())
    output = "\n".join(msg for msg, _, _ in sink.sent)
    assert "Claude reported a usage limit:" in output
    assert message in output
    assert "Last stderr:" not in output


def test_run_codex_wraps_gemini_model_not_found_stderr(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    runner = _GeminiImmediateExitRunner(
        stderr_lines=["ModelNotFoundError: Requested entity was not found."],
        rc=1,
    )
    router, _ = _build_router(tmp_path, runner=runner)
    router.set_session_model("chan", "default", "repo", str(repo), "gpt-5.3-codex", "")
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))
    event = _discord_event("!c resume fix", "code-repo")

    async def run():
        await router.run_codex(
            event,
            sink,
            "repo",
            str(repo),
            "default",
            "gpt-5.3-codex",
            "",
            ["-m", "gpt-5.3-codex", "-p", "fix"],
            backend=runner,
        )

    asyncio.run(run())
    output = "\n".join(msg for msg, _, _ in sink.sent)
    assert "Gemini could not find the configured model." in output
    assert "Session 'default' is configured for Gemini model 'gpt-5.3-codex'" in output
    assert "`!models`" in output
    assert "`!model <model-id>`" in output
    assert "`!model default`" in output
    assert "Last stderr:" not in output
    assert "Agent exited with code" not in output


def test_run_codex_wraps_unsupported_model_stderr_error(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    line = _unsupported_model_error_line()
    runner = _ImmediateExitRunner(stderr_lines=[line, line], rc=1)
    router, _ = _build_router(tmp_path, runner=runner)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))
    event = _discord_event("!c resume fix", "code-repo")

    async def run():
        await router.run_codex(
            event,
            sink,
            "repo",
            str(repo),
            "default",
            "gpt-5.3-codex",
            "",
            ["exec", "resume"],
        )

    asyncio.run(run())
    output = "\n".join(msg for msg, _, _ in sink.sent)
    assert output.count("Cannot use model 'gpt-5.3-codex' with this ChatGPT account.") == 1
    assert "Last stderr:" not in output
    assert '"type": "error"' not in output
    assert '{"type":"error"' not in output


def test_run_codex_fails_fast_on_usage_error_without_compat_retry(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    class _UsageErrorRunner:
        def __init__(self) -> None:
            self.calls = []

        async def run(self, opts: Options):
            self.calls.append(list(opts.args))
            if opts.on_stderr:
                await opts.on_stderr("usage: codex exec [OPTIONS] [PROMPT]")
            if opts.on_stderr:
                await opts.on_stderr("error: unexpected argument '--bad-flag'")
            return _ProcDone(2)

    runner = _UsageErrorRunner()
    router, _ = _build_router(tmp_path, runner=runner)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))
    event = _discord_event("!c start", "code-repo")
    args = ["exec", "--json", "--cd", str(repo), "--bad-flag", "hello"]

    async def run():
        await router.run_codex(event, sink, "repo", str(repo), "default", "", "", args)

    asyncio.run(run())
    assert len(runner.calls) == 1
    assert runner.calls[0] == args
    assert any("Agent exited with code 2." in msg for msg, _, _ in sink.sent)
    assert any("Last stderr: error: unexpected argument '--bad-flag'" in msg for msg, _, _ in sink.sent)
    assert not any("retrying with compatibility args" in msg for msg, _, _ in sink.sent)
    event_names = [name for _, name, _ in router.logger.entries]
    assert "codex.retry.stale_thread" not in event_names


def test_router_writes_codex_error_log(tmp_path):
    router, _ = _build_router(tmp_path)
    router._append_codex_error_log(
        channel_id="chan",
        session="default",
        repo_name="repo",
        repo_path="/tmp/repo",
        args=["exec", "hello"],
        return_code=2,
        stderr_lines=["usage: codex ...", "For more information, try '--help'."],
        note="non-zero exit",
    )
    path = tmp_path / "logs" / "codex_errors.log"
    assert path.exists()
    line = path.read_text(encoding="utf-8").strip().splitlines()[-1]
    payload = json.loads(line)
    assert payload["channel_id"] == "chan"
    assert payload["return_code"] == 2
    assert payload["args"] == ["exec", "hello"]
    assert payload["stderr_tail"][-1] == "For more information, try '--help'."
    session_path = tmp_path / "logs" / "session_jsonl" / "active" / "chan" / "repo-repo__session-default.jsonl"
    session_lines = session_path.read_text(encoding="utf-8").strip().splitlines()
    event_payload = json.loads(session_lines[-1])
    assert event_payload["event"] == "codex.error"
    assert event_payload["data"]["return_code"] == 2


def test_router_redacts_codex_error_and_session_jsonl_logs(tmp_path):
    audit = AuditLogger(str(tmp_path / "logs"), redactor=Redactor())
    router, _ = _build_router(tmp_path, audit=audit)
    router._append_codex_error_log(
        channel_id="chan",
        session="default",
        repo_name="repo",
        repo_path="/tmp/repo",
        args=[
            "exec",
            "--totp",
            "123456",
            "token=abc123",
            "sk-abcdefghijklmnopqrstuv",
        ],
        return_code=2,
        stderr_lines=["totp=654321 password = p@ss"],
        note="secret: hello",
    )
    error_log = (tmp_path / "logs" / "codex_errors.log").read_text(encoding="utf-8")
    session_path = tmp_path / "logs" / "session_jsonl" / "active" / "chan" / "repo-repo__session-default.jsonl"
    session_log = session_path.read_text(encoding="utf-8")
    combined = error_log + "\n" + session_log
    for raw in (
        "123456",
        "654321",
        "token=abc123",
        "sk-abcdefghijklmnopqrstuv",
        "password = p@ss",
        "secret: hello",
    ):
        assert raw not in combined
    assert "<redacted>" in combined
