import asyncio

from codebridge.handlers import core


class _FakeSink:
    def __init__(self) -> None:
        self.channel_id = "chan"
        self.messages: list[str] = []
        self.forbidden: list[str] = []


class _FakeProc:
    def __init__(self) -> None:
        self.stopped = False
        self.interrupted = False
        self.killed = False
        self.writes: list[str] = []

    async def stop(self) -> None:
        self.stopped = True

    async def interrupt(self) -> None:
        self.interrupted = True

    async def kill(self) -> None:
        self.killed = True

    async def write(self, text: str) -> None:
        self.writes.append(text)


class _Stats:
    def __init__(self, i: int, o: int, t: int) -> None:
        self.input_tokens = i
        self.output_tokens = o
        self.total_tokens = t


class _FakeRouter:
    def __init__(self, proc: _FakeProc) -> None:
        self._proc = proc
        self._stats = _Stats(10, 20, 30)

    async def get_active(self, channel_id: str, session: str):
        _ = (channel_id, session)
        return self._proc

    def get_usage(self, channel_id: str, session: str):
        _ = (channel_id, session)
        return self._stats

    async def reply(self, sink: _FakeSink, content: str) -> None:
        sink.messages.append(content)

    async def reply_forbidden(self, sink: _FakeSink, detail: str) -> None:
        sink.forbidden.append(detail)


def test_end_commands_include_usage_summary():
    async def run():
        sink = _FakeSink()
        proc = _FakeProc()
        router = _FakeRouter(proc)

        await core.handle_stop(router, sink, "default")
        await core.handle_kill(router, sink, "default")
        await core.handle_quit(router, sink, "default")

        joined = "\n".join(sink.messages)
        assert "Usage so far: input 10, output 20, total 30." in joined

    asyncio.run(run())
