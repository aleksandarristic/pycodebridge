import asyncio
import time

from codebridge import config as cfgmod
from codebridge.codex import Options
from codebridge.router import Router
from codebridge.session_coordinator import SessionCoordinator
from codebridge.state import Store
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
    def info(self, name: str, extra=None):
        return None

    def warning(self, name: str, extra=None):
        return None

    def error(self, name: str, extra=None):
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

    def build_start_args(self, repo_path: str, prompt: str, model: str) -> list[str]:
        _ = (repo_path, prompt, model)
        return ["start"]

    def build_resume_args(self, repo_path: str, thread_id: str, prompt: str, model: str) -> list[str]:
        _ = (repo_path, thread_id, prompt, model)
        return ["resume", thread_id]

    def build_resume_last_args(self, repo_path: str, prompt: str, model: str) -> list[str]:
        _ = (repo_path, prompt, model)
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


def _build_router(tmp_path):
    cfg = cfgmod.Config()
    cfg.discord.allowed_user_ids = ["user"]
    cfg.telegram.allowed_user_ids = ["user"]
    cfg.codex.code_root = str(tmp_path)
    cfg.state.data_dir = str(tmp_path / "state")
    cfg.state.log_dir = str(tmp_path / "logs")

    store = Store(cfg.state.data_dir)
    coordinator = SessionCoordinator(store, cfg)
    runner = _FakeRunner()
    router = Router(cfg, store, _FakeAudit(), runner, coordinator, _FakeLogger())
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
