from codebridge.routing.router import _ThreadContextSink
from codebridge.platform.transport import Capabilities


class _FakeSink:
    def __init__(self, caps: Capabilities) -> None:
        self._caps = caps
        self.sent = []
        self.files = []
        self.channel_id = "chan"

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


def test_thread_context_prefers_reply_when_threads_disabled():
    sink = _FakeSink(Capabilities(threads=False, replies=True))
    wrapped = _ThreadContextSink(sink, thread_id="thread", reply_to_id="reply")

    async def run():
        await wrapped.send("hello")
        await wrapped.send_file("/tmp/a", "a")

    import asyncio

    asyncio.run(run())
    assert sink.sent == [("hello", None, "reply")]
    assert sink.files == [("/tmp/a", "a", None, "reply")]


def test_thread_context_prefers_thread_when_supported():
    sink = _FakeSink(Capabilities(threads=True, replies=False))
    wrapped = _ThreadContextSink(sink, thread_id="thread", reply_to_id="reply")

    async def run():
        await wrapped.send("hello")

    import asyncio

    asyncio.run(run())
    assert sink.sent == [("hello", "thread", None)]
