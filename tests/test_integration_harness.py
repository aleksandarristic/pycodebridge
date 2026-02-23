import asyncio
import base64
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
from codebridge.codex import Options
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

    async def interrupt(self) -> None:
        self.interrupted = True

    async def kill(self) -> None:
        self.killed = True
        self._done.set()

    async def write(self, data: str) -> None:
        self.writes.append(data)


class _FakeRunner:
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


class _FakeDiscordChannel:
    def __init__(self, *, is_private: bool) -> None:
        self.guild = _FakeDiscordGuild()
        self.type = "text"
        self._is_private = is_private

    def permissions_for(self, role) -> _FakeDiscordPermissions:
        _ = role
        return _FakeDiscordPermissions(view_channel=not self._is_private)


class _FakeDiscordMessage:
    def __init__(self, *, is_private: bool) -> None:
        self.channel = _FakeDiscordChannel(is_private=is_private)


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


def _build_router(tmp_path, *, totp_enabled: bool = False):
    cfg = cfgmod.Config()
    cfg.discord.allowed_user_ids = ["user"]
    cfg.telegram.allowed_user_ids = ["user"]
    cfg.discord.totp_enabled = totp_enabled
    cfg.discord.totp_secret_env = "DISCORD_TOTP_SECRET"
    cfg.discord.totp_window = 1
    cfg.codex.code_root = str(tmp_path)
    cfg.state.data_dir = str(tmp_path / "state")
    cfg.state.log_dir = str(tmp_path / "logs")

    store = Store(cfg.state.data_dir)
    coordinator = SessionCoordinator(store, cfg)
    runner = _FakeRunner()
    logger = _FakeLogger()
    router = Router(cfg, store, _FakeAudit(), runner, coordinator, logger)
    return router, runner


def _discord_event(content: str, channel_name: str, channel_id: str = "chan", *, is_private: bool = True) -> MessageEvent:
    return MessageEvent(
        platform="discord",
        content=content,
        channel_id=channel_id,
        channel_name=channel_name,
        author_id="user",
        author_is_bot=False,
        is_dm=False,
        guild_id="guild",
        raw_event=_FakeDiscordMessage(is_private=is_private),
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


def _telegram_channel_event(content: str, channel_name: str, channel_id: str = "chat") -> MessageEvent:
    return MessageEvent(
        platform="telegram",
        content=content,
        channel_id=channel_id,
        channel_name=channel_name,
        author_id="user",
        author_is_bot=False,
        is_dm=False,
    )


def test_integration_start_stop(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    router, runner = _build_router(tmp_path)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(_discord_event("!c start", "codex-repo"), sink)
        for _ in range(50):
            proc = await router.get_active("chan", "default")
            if proc is not None:
                break
            await asyncio.sleep(0.01)
        await router.handle_message(_discord_event("!c stop", "codex-repo"), sink)

    asyncio.run(run())
    assert runner.last_proc is not None
    assert runner.last_proc.stopped is True
    assert runner.last_proc.interrupted is True


def test_integration_bang_stop_interrupts_active_prompt(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    router, runner = _build_router(tmp_path)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(_discord_event("!c start", "codex-repo"), sink)
        for _ in range(50):
            proc = await router.get_active("chan", "default")
            if proc is not None:
                break
            await asyncio.sleep(0.01)
        await router.handle_message(_discord_event("!stop", "codex-repo"), sink)

    asyncio.run(run())
    assert runner.last_proc is not None
    assert runner.last_proc.interrupted is True


def test_integration_ignores_public_discord_repo_channel(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    router, runner = _build_router(tmp_path)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(_discord_event("!c start", "codex-repo", is_private=False), sink)

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
        channel_name="codex-repo",
        author_id="intruder",
        author_is_bot=False,
        is_dm=False,
        guild_id="guild",
        raw_event=_FakeDiscordMessage(is_private=True),
    )

    assert router._transport_user_allowed(event) is False


def test_integration_start_with_case_variant_repo_dir(tmp_path):
    repo = tmp_path / "ProbablyFine"
    repo.mkdir()
    (repo / ".git").mkdir()

    router, _ = _build_router(tmp_path)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(_discord_event("!c start", "codex-probablyfine"), sink)
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
        await router.handle_message(_discord_event("!c start", "codex-repo"), sink)
        for _ in range(50):
            proc = await router.get_active("chan", "default")
            if proc is not None:
                break
            await asyncio.sleep(0.01)
        await router.handle_message(_discord_event("!c kill", "codex-repo"), sink)

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
        await router.handle_message(_discord_event("!c start", "codex-repo"), sink)
        first_proc = None
        for _ in range(100):
            first_proc = await router.get_active("chan", "default")
            if first_proc is not None:
                break
            await asyncio.sleep(0.01)
        assert first_proc is not None

        await router.handle_message(_discord_event("!c reset", "codex-repo"), sink)
        for _ in range(100):
            if await router.get_active("chan", "default") is None:
                break
            await asyncio.sleep(0.01)
        assert first_proc.killed is True

        state = router.state.load()
        ch = state.channels.get("chan")
        assert ch is not None
        assert "default" not in ch.sessions

        await router.handle_message(_discord_event("!c start", "codex-repo"), sink)
        for _ in range(200):
            if len(runner.calls) >= 2:
                break
            await asyncio.sleep(0.01)

    asyncio.run(run())
    assert len(runner.calls) >= 2
    assert not any("already exists" in msg for msg, _, _ in sink.sent)


def test_integration_resume_and_download(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    target = repo / "note.txt"
    target.write_text("hi")

    router, runner = _build_router(tmp_path)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(_discord_event("!c resume hello", "codex-repo"), sink)
        await router.handle_message(_discord_event("!c download note.txt", "codex-repo"), sink)

    asyncio.run(run())
    assert any(args and args[0] == "start" for args in runner.calls)
    assert sink.files == [(str(target), "note.txt", None, None)]


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
        await router.handle_message(_discord_event("!c updates", "codex-repo"), sink)

    asyncio.run(run())
    assert called == [str(repo)]
    assert any("updates-ok" in msg for msg, _, _ in sink.sent)


def test_integration_answer_command_relays_to_active_session(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    router, runner = _build_router(tmp_path)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(_discord_event("!c start", "codex-repo"), sink)
        for _ in range(50):
            proc = await router.get_active("chan", "default")
            if proc is not None:
                break
            await asyncio.sleep(0.01)
        await router.handle_message(_discord_event("!c answer yes", "codex-repo"), sink)

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
        await router.handle_message(_discord_event("!c start", "codex-repo"), sink)
        for _ in range(50):
            proc = await router.get_active("chan", "default")
            if proc is not None:
                break
            await asyncio.sleep(0.01)
        await router.handle_message(_discord_event("!c steer focus on failing tests", "codex-repo"), sink)

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
        await router.handle_message(_discord_event("!c start", "codex-repo"), sink)
        for _ in range(50):
            proc = await router.get_active("chan", "default")
            if proc is not None:
                break
            await asyncio.sleep(0.01)
        await router.handle_message(_discord_event("!steer keep current plan, reduce scope", "codex-repo"), sink)

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
        await router.handle_message(_discord_event("!c start", "codex-repo"), sink)
        for _ in range(50):
            proc = await router.get_active("chan", "default")
            if proc is not None:
                break
            await asyncio.sleep(0.01)
        await router.handle_message(_discord_event("!s tighten scope", "codex-repo"), sink)

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
        await router.handle_message(_discord_event("!c start", "codex-repo"), sink)
        for _ in range(50):
            proc = await router.get_active("chan", "default")
            if proc is not None:
                break
            await asyncio.sleep(0.01)
        await router.handle_message(_discord_event("!s\ttrim scope", "codex-repo"), sink)
        await router.handle_message(_discord_event("!s\nkeep only tests", "codex-repo"), sink)

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
        await router.handle_message(_discord_event("!s", "codex-repo"), sink)
        await router.handle_message(_discord_event("!a", "codex-repo"), sink)

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
        await router.handle_message(_discord_event("!s tighten scope", "codex-repo"), sink)

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
        await router.handle_message(_discord_event("!s tighten scope", "codex-repo"), sink)

    asyncio.run(run())
    texts = [msg for msg, _, _ in sink.sent]
    assert any("Cannot steer: multiple active sessions (alpha, default)." in msg for msg in texts)


def test_integration_session_targeted_steer_and_answer_shortcuts(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    router, runner = _build_router(tmp_path)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(_discord_event("!c start", "codex-repo"), sink)
        for _ in range(50):
            proc = await router.get_active("chan", "default")
            if proc is not None:
                break
            await asyncio.sleep(0.01)
        await router.handle_message(_discord_event("!s:default keep edits minimal", "codex-repo"), sink)
        await router.handle_message(_discord_event("!a:default yes proceed", "codex-repo"), sink)

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
        await router.handle_message(_discord_event("!cfg", "codex-repo"), sink)
        await router.handle_message(_discord_event("!opts", "codex-repo"), sink)

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
        await router.handle_message(_discord_event("!c start", "codex-repo"), sink)
        for _ in range(50):
            proc = await router.get_active("chan", "default")
            if proc is not None:
                break
            await asyncio.sleep(0.01)
        await router.on_jsonl(
            sink,
            "chan",
            "default",
            None,
            '{"type":"item.completed","item":{"type":"agent_message","text":"Proceed?"}}',
            True,
        )
        await router.handle_message(_discord_event("yes", "codex-repo"), sink)

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
        await router.handle_message(_discord_event("!c start", "codex-repo"), sink)
        for _ in range(50):
            proc = await router.get_active("chan", "default")
            if proc is not None:
                break
            await asyncio.sleep(0.01)
        await router.handle_message(_discord_event("!c wait", "codex-repo"), sink)
        await router.on_jsonl(
            sink,
            "chan",
            "default",
            None,
            '{"type":"item.completed","item":{"type":"agent_message","text":"Proceed?"}}',
            True,
        )
        await router.handle_message(_discord_event("!c wait", "codex-repo"), sink)

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
        await router.handle_message(_discord_event("!c start", "codex-repo"), sink)
        for _ in range(50):
            proc = await router.get_active("chan", "default")
            if proc is not None:
                break
            await asyncio.sleep(0.01)
        await asyncio.sleep(1.05)
        await router.handle_message(_discord_event("!c stop", "codex-repo"), sink)

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
        await router.handle_message(_discord_event("!c start", "codex-repo"), sink)
        for _ in range(50):
            proc = await router.get_active("chan", "default")
            if proc is not None:
                break
            await asyncio.sleep(0.01)
        await router.handle_message(_discord_event("!c stop", "codex-repo"), sink)

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
        await router.handle_message(_discord_event("!c start", "codex-repo"), sink)
        await asyncio.sleep(1.12)
        await router.handle_message(_discord_event("!c kill", "codex-repo"), sink)

    asyncio.run(run())
    texts = [msg for msg, _, _ in sink.sent]
    assert any("Still running in session 'default'" in t for t in texts)


def test_integration_options_show_and_set_runtime(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    router, _ = _build_router(tmp_path)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(_discord_event("!c options", "codex-repo"), sink)
        await router.handle_message(_discord_event("!c options set run_heartbeat_seconds 90", "codex-repo"), sink)
        await router.handle_message(_discord_event("!c options set run_completion_min_seconds 480", "codex-repo"), sink)
        await router.handle_message(_discord_event("!c options set show_reasoning_details false", "codex-repo"), sink)
        await router.handle_message(_discord_event("!c options", "codex-repo"), sink)

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
        await router.handle_message(_discord_event("!c options set run_heartbeat_seconds 90", "codex-repo"), sink)
        code = _totp_code(secret)
        await router.handle_message(
            _discord_event(f"!c options set run_heartbeat_seconds 90 --totp {code}", "codex-repo"),
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
        await router.handle_message(_discord_event(f"!c unlock {_totp_code(secret)}", "codex-repo"), sink)
        await router.handle_message(_discord_event("!c options set run_heartbeat_seconds 90", "codex-repo"), sink)

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
        await router.handle_message(_discord_event("!c options set run_completion_min_seconds 480", "codex-repo"), sink)

    asyncio.run(run_set())

    router2, _ = _build_router(tmp_path)
    sink2 = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run_show():
        await router2.handle_message(_discord_event("!c options", "codex-repo"), sink2)

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
        await router.handle_message(_discord_event("!c options", "codex-repo"), sink)

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
        await router.handle_message(_discord_event("!c options set run_heartbeat_seconds 120 global", "codex-repo"), sink)

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
        await router.handle_message(_discord_event("!cfg set wrong_key value", "codex-repo"), sink)

    asyncio.run(run())
    texts = [msg for msg, _, _ in sink.sent]
    assert any("Use `!cfg` to show effective config." in t for t in texts)
    assert any("!opts set <key> <value>" in t for t in texts)


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
        await router.handle_message(_discord_event("!c session prune 1h", "codex-repo"), sink)
        await router.handle_message(_discord_event("!c session status", "codex-repo"), sink)

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
        await router.handle_message(_discord_event("!c start", "codex-repo"), sink)
        for _ in range(50):
            proc = await router.get_active("chan", "default")
            if proc is not None:
                break
            await asyncio.sleep(0.01)
        await router.handle_message(_discord_event("!c session archive default", "codex-repo"), sink)
        await router.handle_message(_discord_event("!c session restore default", "codex-repo"), sink)
        await router.handle_message(_discord_event("!c stop", "codex-repo"), sink)
        await asyncio.sleep(0.05)

    asyncio.run(run())
    texts = [msg for msg, _, _ in sink.sent]
    assert any("Archived session 'default'" in t for t in texts)
    assert any(args and args[0] == "resume" for args in runner.calls)


def test_integration_resume_expired_session_requires_continue_or_new(tmp_path):
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
        await router.handle_message(_discord_event("!c resume default continue work", "codex-repo"), sink)
        await router.handle_message(_discord_event("!c choose continue", "codex-repo"), sink)

    asyncio.run(run())
    texts = [msg for msg, _, _ in sink.sent]
    assert any("is inactive" in t for t in texts)
    assert any("!c choose continue" in t for t in texts)
    assert any(args == ["resume", "thread-old"] for args in runner.calls)


def test_integration_resume_expired_session_choose_new_starts_fresh_with_original_prompt(tmp_path):
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
        await router.handle_message(_discord_event("!c resume default focus only tests", "codex-repo"), sink)
        await router.handle_message(_discord_event("!c choose new", "codex-repo"), sink)

    asyncio.run(run())
    assert captured_prompt["value"] == "focus only tests"
    assert any(args == ["start"] for args in runner.calls)
    assert not any(args == ["resume", "thread-old"] for args in runner.calls)


def test_integration_budget_status_and_set(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    router, _ = _build_router(tmp_path)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(_discord_event("!c budget status", "codex-repo"), sink)
        await router.handle_message(_discord_event("!c budget set channel 100 200", "codex-repo"), sink)
        await router.handle_message(_discord_event("!c budget set user 50 80", "codex-repo"), sink)
        await router.handle_message(_discord_event("!c budget status", "codex-repo"), sink)

    asyncio.run(run())
    texts = [msg for msg, _, _ in sink.sent]
    assert any("Budgets:" in t for t in texts)
    assert any("Budget channel thresholds set: soft=100, hard=200." in t for t in texts)
    assert any("Budget user thresholds set: soft=50, hard=80." in t for t in texts)
    assert any("soft=100 hard=200" in t for t in texts)


def test_integration_budget_hard_limit_blocks_new_runs(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    router, runner = _build_router(tmp_path)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(_discord_event("!c budget set channel 0 10", "codex-repo"), sink)
        router._budget_usage_channel["chan"] = 10
        await router.handle_message(_discord_event("!c start", "codex-repo"), sink)

    asyncio.run(run())
    texts = [msg for msg, _, _ in sink.sent]
    assert any("Budget limit reached" in t for t in texts)
    assert not any(args and args[0] == "start" for args in runner.calls)


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
        await router.handle_message(_discord_event("!c audit show 000001", "codex-repo"), sink)
        await router.handle_message(_discord_event("!c audit find start", "codex-repo"), sink)
        await router.handle_message(_discord_event("!c audit bundle 000001", "codex-repo"), sink)

    asyncio.run(run())
    texts = [msg for msg, _, _ in sink.sent]
    assert any("Audit `000001`" in t for t in texts)
    assert any("Audit matches for `start`" in t for t in texts)
    assert any("Audit bundle ready" in t for t in texts)
    assert any(name == "audit-000001.zip" for _, name, _, _ in sink.files)
    bundle_paths = [path for path, name, _, _ in sink.files if name == "audit-000001.zip"]
    assert bundle_paths
    assert all(not os.path.exists(path) for path in bundle_paths)


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

    router.handle_updates = MethodType(_fake_handle_updates, router)
    router.handle_health = MethodType(_fake_handle_health, router)

    async def run():
        await router.handle_message(_discord_event("!help", "codex-repo"), sink)
        await router.handle_message(_discord_event("!st", "codex-repo"), sink)
        await router.handle_message(_discord_event("!u", "codex-repo"), sink)
        await router.handle_message(_discord_event("!health", "codex-repo"), sink)
        await router.handle_message(_discord_event("!diag", "codex-repo"), sink)
        await router.handle_message(_discord_event("!w", "codex-repo"), sink)
        await router.handle_message(_discord_event("!unlock status", "codex-repo"), sink)
        await router.handle_message(_discord_event("!ul status", "codex-repo"), sink)
        await router.handle_message(_discord_event("!lock status", "codex-repo"), sink)
        await router.handle_message(_discord_event("!ps", "codex-repo"), sink)
        await router.handle_message(_discord_event("!log", "codex-repo"), sink)
        await router.handle_message(_discord_event("!retry", "codex-repo"), sink)
        await router.handle_message(_discord_event("!c start", "codex-repo"), sink)
        for _ in range(50):
            proc = await router.get_active("chan", "default")
            if proc is not None:
                break
            await asyncio.sleep(0.01)
        await router.handle_message(_discord_event("!y", "codex-repo"), sink)
        await router.handle_message(_discord_event("!n", "codex-repo"), sink)
        await router.handle_message(_discord_event("!a keep going", "codex-repo"), sink)
        await router.handle_message(_discord_event("!pause", "codex-repo"), sink)

    asyncio.run(run())
    texts = [msg for msg, _, _ in sink.sent]
    assert any("Commands:" in t for t in texts)
    assert any("Repo: repo" in t for t in texts)
    assert any("Related: !c start" in t for t in texts)
    assert any("updates-ok" in t for t in texts)
    assert sum("health-ok" in t for t in texts) >= 2
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
        await router.handle_message(_discord_event("!c help git", "codex-repo"), sink)

    asyncio.run(run())
    texts = [msg for msg, _, _ in sink.sent]
    assert any("Help: `git`" in t for t in texts)
    assert any("!c git status" in t for t in texts)


def test_integration_repo_help_is_chunked_for_discord_limit(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    router, _ = _build_router(tmp_path)
    router.cfg.discord.max_discord_message_chars = 250
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(_discord_event("!help", "codex-repo"), sink)

    asyncio.run(run())
    texts = [msg for msg, _, _ in sink.sent]
    assert len(texts) > 1
    assert any("Commands:" in t for t in texts)


def test_integration_repo_help_chunks_stay_within_limit_with_lock_prefix(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    router, _ = _build_router(tmp_path, totp_enabled=True)
    router.cfg.discord.max_discord_message_chars = 120
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(_discord_event("!help", "codex-repo"), sink)

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
    wrapped = router._contextual_sink(_discord_event("noop", "codex-repo"), sink)

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
    assert any("Commands:" in t for t in texts)
    assert any("Help: `git`" in t for t in texts)
    assert any("!help" in t for t in texts)
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
    assert any("Commands:" in t for t in texts)


def test_integration_telegram_threaded_reply(tmp_path):
    router, _ = _build_router(tmp_path)
    sink = _FakeSink(Capabilities(threads=True, replies=True, uploads=True, downloads=True, typing=True))
    event = MessageEvent(
        platform="telegram",
        content="hello",
        channel_id="chat",
        channel_name="",
        author_id="user",
        author_is_bot=False,
        is_dm=True,
        message_id="42",
        platform_thread_id="7",
    )

    async def run():
        await router.handle_message(event, sink)

    asyncio.run(run())
    assert sink.sent
    assert sink.sent[0][1] == "7"


def test_totp_required_for_state_changing_and_gh(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    secret = "JBSWY3DPEHPK3PXP"
    monkeypatch.setenv("DISCORD_TOTP_SECRET", secret)

    router, runner = _build_router(tmp_path, totp_enabled=True)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(_discord_event("!c start", "codex-repo"), sink)
        await router.handle_message(_discord_event("!c gh pr status", "codex-repo"), sink)
        start_code = _totp_code(secret)
        await router.handle_message(_discord_event(f"!c start --totp {start_code}", "codex-repo"), sink)
        gh_code = _totp_code(secret, step_offset=1)
        await router.handle_message(_discord_event(f"!c gh --totp {gh_code} pr status", "codex-repo"), sink)

    asyncio.run(run())
    assert any("TOTP required for 'start'" in msg for msg, _, _ in sink.sent)
    assert any("TOTP required for 'gh'" in msg for msg, _, _ in sink.sent)
    assert any(args and args[0] == "start" for args in runner.calls)


def test_totp_unlock_allows_plain_resume_for_ttl(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    secret = "JBSWY3DPEHPK3PXP"
    monkeypatch.setenv("DISCORD_TOTP_SECRET", secret)

    router, runner = _build_router(tmp_path, totp_enabled=True)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(_discord_event(f"!c unlock {_totp_code(secret)} 2h", "codex-repo"), sink)
        await router.handle_message(_discord_event("hi there", "codex-repo"), sink)

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
        await router.handle_message(_discord_event(f"!c unlock {_totp_code(secret)}", "codex-repo"), sink)
        await router.handle_message(_discord_event("!c gh pr status", "codex-repo"), sink)

    asyncio.run(run())
    assert any("TOTP unlock active for 1h" in msg for msg, _, _ in sink.sent)
    assert any("TOTP required for 'gh'" in msg for msg, _, _ in sink.sent)


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
        await router.handle_message(_discord_event(f"!c unlock {_totp_code(secret)} 1h", "codex-repo"), sink)
        await router.handle_message(_discord_event("!c unlock status", "codex-repo"), sink)
        await router.handle_message(_discord_event("!c lock status", "codex-repo"), sink)
        await router.handle_message(_discord_event("!c status", "codex-repo"), sink)
        await router.handle_message(_discord_event("!c lock", "codex-repo"), sink)
        await router.handle_message(_discord_event("hello", "codex-repo"), sink)

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
        await router.handle_message(_discord_event(f"!c unlock {_totp_code(secret)} 1h", "codex-repo"), sink)
        await router.handle_message(_discord_event("!c lock extend 30m", "codex-repo"), sink)
        await router.handle_message(_discord_event(f"!c lock extend 30m --totp {_totp_code(secret, step_offset=1)}", "codex-repo"), sink)
        await router.handle_message(_discord_event("!c lock status", "codex-repo"), sink)

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
        await router.handle_message(_discord_event(f"!c lock extend 30m --totp {_totp_code(secret)}", "codex-repo"), sink)
        await router.handle_message(_discord_event(f"!c unlock extend 30m --totp {_totp_code(secret, step_offset=1)}", "codex-repo"), sink)

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
        await router.handle_message(_discord_event(f"!c unlock {_totp_code(secret)} 1h", "codex-repo"), sink)
        await router.handle_message(_discord_event(f"!c unlock extend 15m --totp {_totp_code(secret, step_offset=1)}", "codex-repo"), sink)
        await router.handle_message(_discord_event("!c lock status", "codex-repo"), sink)

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
        await router.handle_message(_discord_event(f"!c unlock gh {_totp_code(secret)} 1h", "codex-repo"), sink)
        await router.handle_message(_discord_event("!c gh pr status", "codex-repo"), sink)
        await router.handle_message(_discord_event("!c start", "codex-repo"), sink)

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
        await router.handle_message(_discord_event(f"!c unlock all {_totp_code(secret)} 1h", "codex-repo"), sink)
        await router.handle_message(_discord_event("!c start", "codex-repo"), sink)
        await router.handle_message(_discord_event("!c gh pr status", "codex-repo"), sink)

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
        await router.handle_message(_discord_event(f"!c unlock {_totp_code(secret)} 1h", "codex-repo", channel_id="chan-a"), sink)
        await router.handle_message(_discord_event("hello", "codex-repo", channel_id="chan-b"), sink)
        await router.handle_message(_discord_event("!c lock", "codex-repo", channel_id="chan-b"), sink)
        await router.handle_message(_discord_event("!c start", "codex-repo", channel_id="chan-a"), sink)

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
        await router.handle_message(_discord_event("!c status", "codex-repo"), sink)
        await router.handle_message(_discord_event(f"!c unlock {_totp_code(secret)}", "codex-repo"), sink)
        await router.handle_message(_discord_event("!c status", "codex-repo"), sink)

    asyncio.run(run())
    messages = [msg for msg, _, _ in sink.sent]
    assert any(msg.startswith("🔒 ") for msg in messages)
    assert any(msg.startswith("🔓 ") for msg in messages)


def test_totp_git_status_read_only_without_totp(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    secret = "JBSWY3DPEHPK3PXP"
    monkeypatch.setenv("DISCORD_TOTP_SECRET", secret)

    router, _ = _build_router(tmp_path, totp_enabled=True)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(_discord_event("!c git status", "codex-repo"), sink)

    asyncio.run(run())
    assert not any("TOTP required for 'git'" in msg for msg, _, _ in sink.sent)


def test_totp_bang_git_status_read_only_without_totp(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    secret = "JBSWY3DPEHPK3PXP"
    monkeypatch.setenv("DISCORD_TOTP_SECRET", secret)

    router, _ = _build_router(tmp_path, totp_enabled=True)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(_discord_event("!git status", "codex-repo"), sink)

    asyncio.run(run())
    assert not any("TOTP required for 'git'" in msg for msg, _, _ in sink.sent)


def test_totp_git_remote_read_only_without_totp(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    secret = "JBSWY3DPEHPK3PXP"
    monkeypatch.setenv("DISCORD_TOTP_SECRET", secret)

    router, _ = _build_router(tmp_path, totp_enabled=True)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(_discord_event("!c git remote -v", "codex-repo"), sink)

    asyncio.run(run())
    assert not any("TOTP required for 'git'" in msg for msg, _, _ in sink.sent)
    assert not any("Unknown git subcommand." in msg for msg, _, _ in sink.sent)


def test_totp_bang_gh_requires_gh_scope_or_totp(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    secret = "JBSWY3DPEHPK3PXP"
    monkeypatch.setenv("DISCORD_TOTP_SECRET", secret)

    router, _ = _build_router(tmp_path, totp_enabled=True)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(_discord_event("!gh pr status", "codex-repo"), sink)

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
        await router.handle_message(_discord_event("!c updates", "codex-repo"), sink)

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
        channel_name="codex-repo",
        author_id="user",
        author_is_bot=False,
        is_dm=False,
        guild_id="guild",
        attachments=[Attachment(filename="note.txt", size=2, content_type="text/plain", save=save_noop)],
        raw_event=_FakeDiscordMessage(is_private=True),
    )

    async def run():
        await router.handle_message(_discord_event("!c config", "codex-repo"), sink)
        await router.handle_message(_discord_event("!c tests", "codex-repo"), sink)
        await router.handle_message(_discord_event("!c download note.txt", "codex-repo"), sink)
        await router.handle_message(_discord_event("!c logs", "codex-repo"), sink)
        await router.handle_message(upload_event, sink)

    asyncio.run(run())
    assert any("TOTP required for 'config'" in msg for msg, _, _ in sink.sent)
    assert any("TOTP required for 'tests'" in msg for msg, _, _ in sink.sent)
    assert any("TOTP required for 'download'" in msg for msg, _, _ in sink.sent)
    assert any("TOTP required for 'logs'" in msg for msg, _, _ in sink.sent)
    assert any("TOTP required for 'upload'" in msg for msg, _, _ in sink.sent)


def test_totp_required_on_telegram_platform(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    secret = "JBSWY3DPEHPK3PXP"
    monkeypatch.setenv("DISCORD_TOTP_SECRET", secret)

    router, _ = _build_router(tmp_path, totp_enabled=True)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(_telegram_channel_event("!c start", "codex-repo"), sink)

    asyncio.run(run())
    assert any("TOTP required for 'start'" in msg for msg, _, _ in sink.sent)


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
        await router.handle_message(_discord_event("!c start --totp 000000", "codex-repo"), sink)
        await router.handle_message(_discord_event("!c start --totp 000000", "codex-repo"), sink)
        await router.handle_message(_discord_event(f"!c start --totp {_totp_code(secret)}", "codex-repo"), sink)
        now[0] += 61
        await router.handle_message(_discord_event(f"!c start --totp {_totp_code(secret)}", "codex-repo"), sink)

    asyncio.run(run())
    assert any("Invalid TOTP code." in msg for msg, _, _ in sink.sent)
    assert any("Too many invalid TOTP attempts." in msg for msg, _, _ in sink.sent)
    assert any(args and args[0] == "start" for args in runner.calls)
    event_names = [name for _, name, _ in router.logger.entries]
    assert "security.totp_invalid" in event_names
    assert "security.totp_locked" in event_names
    assert "security.totp_unlock" in event_names
    assert "security.totp_success" in event_names


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


def test_router_compat_retry_args_drops_resume_and_optional_flags(tmp_path):
    router, _ = _build_router(tmp_path)
    args = [
        "exec",
        "--json",
        "--cd",
        "/workspace/code_root/ProbablyFine",
        "--sandbox",
        "workspace-write",
        "-a",
        "on-request",
        "--model",
        "bad-model",
        "-c",
        'model_reasoning_effort="medium"',
        "resume",
        "--last",
        "hi there",
    ]
    out = router._compat_retry_args(args)
    assert out == [
        "exec",
        "--json",
        "--cd",
        "/workspace/code_root/ProbablyFine",
        "--sandbox",
        "workspace-write",
        "hi there",
    ]


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
