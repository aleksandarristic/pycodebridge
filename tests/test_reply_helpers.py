from codebridge.routing.reply import send_forbidden, send_reply
from codebridge.transport import Capabilities, ResponseSink


class _FakeSink(ResponseSink):
    def __init__(self) -> None:
        self.sent = []
        self.channel_id = "chan"

    def capabilities(self) -> Capabilities:
        return Capabilities(threads=False, replies=False, uploads=False, downloads=False, typing=False)

    async def send(self, content: str, thread_id: str | None = None, reply_to_id: str | None = None) -> None:
        _ = (thread_id, reply_to_id)
        self.sent.append(content)

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


def test_send_reply_chunks_and_strips_control_codes():
    sink = _FakeSink()

    async def run():
        await send_reply(sink, "hello\x1b[31m world", max_chars=5)

    import asyncio

    asyncio.run(run())
    assert sink.sent == ["hello", " worl", "d"]


def test_send_forbidden_wraps_message():
    sink = _FakeSink()

    async def run():
        await send_forbidden(sink, "nope", max_chars=1000)

    import asyncio

    asyncio.run(run())
    assert sink.sent
    assert "I'm sorry, Dave" in sink.sent[0]
