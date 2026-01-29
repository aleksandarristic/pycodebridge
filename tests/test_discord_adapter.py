import asyncio

from codebridge.adapters.discord import DiscordAdapter, DiscordResponseSink


class _FakeAuthor:
    def __init__(self, author_id: str, bot: bool = False) -> None:
        self.id = author_id
        self.bot = bot


class _FakeGuild:
    def __init__(self, guild_id: str) -> None:
        self.id = guild_id


class _FakeChannel:
    def __init__(self, channel_id: str, name: str = "") -> None:
        self.id = channel_id
        self.name = name
        self.sent = []

    async def send(self, content: str) -> None:
        self.sent.append(content)


class _FakeTypingChannel(_FakeChannel):
    def typing(self):
        return _FakeAsyncContext()


class _FakeAsyncContext:
    async def __aenter__(self):
        return None

    async def __aexit__(self, exc_type, exc, tb):
        return False


def test_discord_adapter_event_mapping():
    adapter = DiscordAdapter()
    channel = _FakeChannel("chan", "codex-test")
    message = type(
        "FakeMessage",
        (),
        {
            "channel": channel,
            "content": "hello",
            "id": "msg",
            "author": _FakeAuthor("user"),
            "guild": _FakeGuild("guild"),
        },
    )()
    event = adapter.event_from_message(message)
    assert event.channel_id == "chan"
    assert event.channel_name == "codex-test"
    assert event.author_id == "user"
    assert event.guild_id == "guild"
    assert event.author_is_bot is False


def test_discord_response_sink_send_and_typing():
    adapter = DiscordAdapter()
    channel = _FakeTypingChannel("chan", "codex-test")
    sink = DiscordResponseSink(adapter, channel)

    async def run():
        await sink.send("hi")
        async with sink.typing():
            pass

    asyncio.run(run())
    assert channel.sent == ["hi"]


def test_discord_adapter_update_pinned_status_noop():
    adapter = DiscordAdapter()
    channel = _FakeChannel("chan", "codex-test")

    async def run():
        await adapter.update_pinned_status(channel, "status text")

    asyncio.run(run())
