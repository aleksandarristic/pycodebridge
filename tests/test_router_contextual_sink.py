import asyncio

from codebridge import config as cfgmod
from codebridge.audit import Logger as AuditLogger
from codebridge.sessions.queue import Manager
from codebridge.routing.router import Router
from codebridge.sessions.coordinator import SessionCoordinator
from codebridge.sessions.state import Store
from codebridge.transport import Capabilities, MessageEvent, ResponseSink


class _FakeLogger:
    def info(self, *args, **kwargs):
        return None

    def warning(self, *args, **kwargs):
        return None

    def error(self, *args, **kwargs):
        return None


class _FakeRunner:
    def __init__(self):
        pass


class _FakeSink(ResponseSink):
    def __init__(self, caps: Capabilities) -> None:
        self._caps = caps
        self.channel_id = "chan"
        self.sent = []

    def capabilities(self) -> Capabilities:
        return self._caps

    async def send(self, content: str, thread_id: str | None = None, reply_to_id: str | None = None) -> None:
        self.sent.append((content, thread_id, reply_to_id))

    def typing(self):
        class _Ctx:
            async def __aenter__(self):
                return None

            async def __aexit__(self, exc_type, exc, tb):
                return False

        return _Ctx()

    async def update_pinned_status(self, user_id: str, session: str, text: str) -> None:
        return None

    async def send_file(self, path: str, filename: str, thread_id: str | None = None, reply_to_id: str | None = None) -> None:
        return None


def _build_router(tmp_path):
    cfg = cfgmod.Config()
    cfg.codex.code_root = str(tmp_path)
    cfg.state.data_dir = str(tmp_path / "state")
    cfg.state.log_dir = str(tmp_path / "logs")
    store = Store(cfg.state.data_dir)
    coordinator = SessionCoordinator(store, cfg, queue=Manager())
    return Router(cfg, store, AuditLogger(str(tmp_path / "logs")), _FakeRunner(), coordinator, _FakeLogger())


def test_contextual_sink_uses_reply_to_when_supported(tmp_path):
    router = _build_router(tmp_path)
    sink = _FakeSink(Capabilities(threads=False, replies=True, uploads=False, downloads=False, typing=False))
    event = MessageEvent(
        platform="discord",
        content="hi",
        channel_id="chan",
        channel_name="codex-repo",
        author_id="user",
        author_is_bot=False,
        is_dm=False,
        message_id="msg-1",
        platform_thread_id="",
        guild_id="guild",
    )
    wrapped = router._contextual_sink(event, sink)

    async def run():
        await wrapped.send("hello")

    asyncio.run(run())
    assert sink.sent == [("hello", None, "msg-1")]
