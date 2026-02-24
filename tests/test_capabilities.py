from codebridge.adapters.discord import DiscordResponseSink
from codebridge.platform.transport import Capabilities


class _FakeChannel:
    def __init__(self) -> None:
        self.id = "chan"

    async def send(self, content: str) -> None:
        return None

    def typing(self):
        return _FakeAsyncContext()


class _FakeAsyncContext:
    async def __aenter__(self):
        return None

    async def __aexit__(self, exc_type, exc, tb):
        return False


def test_discord_capabilities():
    sink = DiscordResponseSink(None, _FakeChannel())
    assert sink.capabilities() == Capabilities(threads=True, replies=False, uploads=True, downloads=True, typing=True)
