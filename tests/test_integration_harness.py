import asyncio
import base64
import hashlib
import hmac
import os
import struct
import time

from codebridge import config as cfgmod
from codebridge.codex import Options
from codebridge.router import Router
from codebridge.session_coordinator import SessionCoordinator
from codebridge.state import Store
from codebridge.totp import TotpAttemptLimiter
from codebridge.transport import Attachment, Capabilities, MessageEvent


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


def _discord_event(content: str, channel_name: str, channel_id: str = "chan") -> MessageEvent:
    return MessageEvent(
        platform="discord",
        content=content,
        channel_id=channel_id,
        channel_name=channel_name,
        author_id="user",
        author_is_bot=False,
        is_dm=False,
        guild_id="guild",
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
    assert any("resume" in args for args in runner.calls)
    assert sink.files == [(str(target), "note.txt", None, None)]


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
    assert any("Waiting for input: default" in msg for msg, _, _ in sink.sent)


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
