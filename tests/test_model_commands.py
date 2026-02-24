import asyncio
from types import SimpleNamespace

from codebridge import config as cfgmod
from codebridge.codex import Options
from codebridge.routing.router import Router
from codebridge.sessions.coordinator import SessionCoordinator
from codebridge.sessions.state import Store
from codebridge.platform.transport import Capabilities, MessageEvent


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
    def info(self, name: str, extra=None):
        return None

    def warning(self, name: str, extra=None):
        return None

    def error(self, name: str, extra=None):
        return None


class _FakeProc:
    def __init__(self, done: asyncio.Event) -> None:
        self._done = done

    async def wait(self) -> int:
        await self._done.wait()
        return 0

    async def stop(self) -> None:
        self._done.set()

    async def interrupt(self) -> None:
        return None

    async def kill(self) -> None:
        self._done.set()

    async def write(self, data: str) -> None:
        _ = data
        return None


class _FakeRunner:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.last_proc: _FakeProc | None = None
        self._block_event: asyncio.Event | None = None

    def build_start_args(self, repo_path: str, prompt: str, model: str, reasoning: str) -> list[str]:
        _ = (repo_path, model, reasoning)
        return ["start", prompt]

    def build_resume_args(self, repo_path: str, thread_id: str, prompt: str, model: str, reasoning: str) -> list[str]:
        _ = (repo_path, thread_id, model, reasoning)
        return ["resume", prompt]

    def build_resume_last_args(self, repo_path: str, prompt: str, model: str, reasoning: str) -> list[str]:
        _ = (repo_path, model, reasoning)
        return ["resume-last", prompt]

    async def run(self, opts: Options):
        self.calls.append(opts.args)
        if opts.on_thread:
            await opts.on_thread("thread-1")
        # Provide some visible output so Router's streaming path is exercised.
        if opts.on_jsonl:
            await opts.on_jsonl("hello from codex")
        if opts.on_output and any(a == "/models" for a in opts.args):
            await opts.on_output("Available models:")
            await opts.on_output("- `gpt-5.2-codex` (recommended)")
            await opts.on_output("- o3-mini")

        done = asyncio.Event()
        # Block "start" calls so tests can queue commands behind an active job.
        if opts.args and opts.args[0] == "start":
            self._block_event = done
        else:
            done.set()
        proc = _FakeProc(done)
        self.last_proc = proc
        return proc

    def finish_blocking(self) -> None:
        if self._block_event:
            self._block_event.set()


class _FakeSink:
    def __init__(self, caps: Capabilities) -> None:
        self._caps = caps
        self.channel_id = "chan"
        self.sent: list[str] = []

    def capabilities(self) -> Capabilities:
        return self._caps

    async def send(self, content: str, thread_id: str | None = None, reply_to_id: str | None = None) -> None:
        _ = (thread_id, reply_to_id)
        self.sent.append(content)

    def typing(self):
        return _FakeAsyncContext()

    async def update_pinned_status(self, user_id: str, session: str, text: str) -> None:
        _ = (user_id, session)
        self.sent.append(text)

    async def send_file(self, path: str, filename: str, thread_id: str | None = None, reply_to_id: str | None = None) -> None:
        _ = (path, filename, thread_id, reply_to_id)
        return None


class _FakeAsyncContext:
    async def __aenter__(self):
        return None

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _build_router(tmp_path):
    cfg = cfgmod.Config()
    cfg.discord.allowed_user_ids = ["user"]
    cfg.codex.code_root = str(tmp_path)
    cfg.codex.model = "gpt-default"
    cfg.state.data_dir = str(tmp_path / "state")
    cfg.state.log_dir = str(tmp_path / "logs")

    store = Store(cfg.state.data_dir)
    coordinator = SessionCoordinator(store, cfg)
    runner = _FakeRunner()
    router = Router(cfg, store, _FakeAudit(), runner, coordinator, _FakeLogger())
    return router, runner


def _discord_event(content: str, channel_name: str) -> MessageEvent:
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


def test_start_resume_reports_model_and_model_change_is_queued(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    router, runner = _build_router(tmp_path)
    sink = _FakeSink(Capabilities(threads=True, uploads=True, downloads=True, typing=True))

    async def run():
        await router.handle_message(_discord_event("!c start", "codex-repo"), sink)

        # Wait until the start job is actually running.
        for _ in range(200):
            if await router.get_active("chan", "default") is not None:
                break
            await asyncio.sleep(0.01)
        assert await router.get_active("chan", "default") is not None

        await router.handle_message(_discord_event("!model gpt-new", "codex-repo"), sink)
        assert any("Queued model change" in s and "gpt-new" in s for s in sink.sent)
        assert router.session_model("chan", "default") == "gpt-default"

        # Unblock the start job so the queued model change can run.
        runner.finish_blocking()
        for _ in range(200):
            if router.session_model("chan", "default") == "gpt-new":
                break
            await asyncio.sleep(0.01)
        assert router.session_model("chan", "default") == "gpt-new"
        assert any("Model for session 'default' set to gpt-new" in s for s in sink.sent)

        assert any("model gpt-new" in s.lower() for s in sink.sent)

        await router.handle_message(_discord_event("!models", "codex-repo"), sink)
        for _ in range(200):
            if any("Available models" in s for s in sink.sent):
                break
            await asyncio.sleep(0.01)
        assert any("gpt-5.2-codex" in s for s in sink.sent)

    asyncio.run(run())
