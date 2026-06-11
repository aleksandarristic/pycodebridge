from types import SimpleNamespace

import asyncio
import discord

from codebridge.platform.discord_bot import BridgeClient


class _FakeRouter:
    def __init__(self):
        self.logger = _FakeLogger()
        self.cfg = SimpleNamespace(discord=SimpleNamespace(dm_admin_user_ids=["1"], allowed_user_ids=[], guild_id=""))
        self.startup_calls = 0
        self.shutdown_calls = 0

    def set_guild_text_channels_fn(self, fn) -> None:
        pass

    async def startup_summary(self) -> str:
        self.startup_calls += 1
        return "Default model: gpt-test (reasoning medium)"

    async def shutdown_summary(self) -> str:
        self.shutdown_calls += 1
        return "Shutdown summary (commit test)"


class _FakeLogger:
    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass


class _FakeUser:
    def __init__(self):
        self.sent: list[str] = []

    async def send(self, content: str) -> None:
        self.sent.append(content)


class _FakeGuild:
    def __init__(self, guild_id: int) -> None:
        self.id = guild_id
        self.left = False
        self.channels = {}

    async def leave(self) -> None:
        self.left = True

    def get_channel(self, channel_id: int):
        return self.channels.get(str(channel_id))

    async def fetch_channel(self, channel_id: int):
        return self.channels.get(str(channel_id))


class _FakeChannel:
    def __init__(self, channel_id: str, name: str) -> None:
        self.id = channel_id
        self.name = name
        self.sent: list[str] = []

    async def send(self, content: str) -> None:
        self.sent.append(content)


class _FakeThread(_FakeChannel):
    def __init__(self, channel_id: str, name: str, *, parent=None, parent_id: str = "", guild=None) -> None:
        super().__init__(channel_id, name)
        self.parent = parent
        self.parent_id = parent_id or str(getattr(parent, "id", "") or "")
        self.guild = guild


def test_startup_dm_includes_summary_and_runs_once():
    router = _FakeRouter()
    client = BridgeClient(router)
    user = _FakeUser()

    async def fake_fetch_user(user_id: int):
        _ = user_id
        return user

    client.fetch_user = fake_fetch_user

    async def run():
        await client.on_ready()
        await client.on_ready()

    asyncio.run(run())
    assert len(user.sent) == 1
    assert "Startup summary" in user.sent[0]
    assert "Default model" in user.sent[0]
    assert router.startup_calls == 1


def test_shutdown_dm_runs_once():
    router = _FakeRouter()
    client = BridgeClient(router)
    user = _FakeUser()

    async def fake_fetch_user(user_id: int):
        _ = user_id
        return user

    client.fetch_user = fake_fetch_user

    async def run():
        await client.close()
        await client.close()

    asyncio.run(run())
    assert len(user.sent) == 1
    assert "Shutdown summary" in user.sent[0]
    assert router.shutdown_calls == 1


def test_guild_join_leaves_unconfigured_guild_when_locked():
    router = _FakeRouter()
    router.cfg.discord.guild_id = "42"
    client = BridgeClient(router)
    foreign = _FakeGuild(9)

    async def run():
        await client.on_guild_join(foreign)

    asyncio.run(run())
    assert foreign.left is True


def test_enforce_guild_lock_leaves_unconfigured_guilds():
    router = _FakeRouter()
    router.cfg.discord.guild_id = "42"
    client = BridgeClient(router)
    allowed = _FakeGuild(42)
    foreign = _FakeGuild(9)
    async def run():
        await client._enforce_guild_lock([allowed, foreign])

    asyncio.run(run())
    assert allowed.left is False
    assert foreign.left is True


def test_on_message_uses_attached_thread_sink_for_starter_messages(monkeypatch):
    class _CapturingRouter(_FakeRouter):
        def __init__(self):
            super().__init__()
            self.calls = []

        async def handle_message(self, event, sink) -> None:
            self.calls.append((event, sink))
            await sink.send("reply", thread_id=event.platform_thread_id or None)

    router = _CapturingRouter()
    client = BridgeClient(router)
    monkeypatch.setattr(discord, "Thread", _FakeThread)
    parent = _FakeChannel("chan-parent", "codex-repo")
    thread = _FakeThread("thread-1", "Tasks")
    message = type(
        "FakeMessage",
        (),
        {
            "channel": parent,
            "thread": thread,
            "content": "Hi",
            "id": "msg",
            "author": SimpleNamespace(id="1", bot=False),
            "guild": SimpleNamespace(id="42"),
            "attachments": [],
        },
    )()

    async def run():
        await client.on_message(message)

    asyncio.run(run())
    assert len(router.calls) == 1
    event, _ = router.calls[0]
    assert event.platform_thread_id == "thread-1"
    assert parent.sent == []
    assert thread.sent == ["reply"]


def test_on_message_fetches_missing_thread_parent_before_routing(monkeypatch):
    from codebridge.routing.event_context import normalize_event_context

    class _CapturingRouter(_FakeRouter):
        def __init__(self):
            super().__init__()
            self.events = []

        async def handle_message(self, event, sink) -> None:
            _ = sink
            self.events.append(normalize_event_context(event))

    router = _CapturingRouter()
    client = BridgeClient(router)
    monkeypatch.setattr(discord, "Thread", _FakeThread)
    guild = _FakeGuild(42)
    parent = _FakeChannel("123", "codex-repo")
    guild.channels["123"] = parent
    thread = _FakeThread("thread-1", "topic-a", parent=None, parent_id="123", guild=guild)
    message = type(
        "FakeMessage",
        (),
        {
            "channel": thread,
            "content": "!c start",
            "id": "msg",
            "author": SimpleNamespace(id="1", bot=False),
            "guild": guild,
            "attachments": [],
        },
    )()

    async def run():
        await client.on_message(message)

    asyncio.run(run())
    assert len(router.events) == 1
    event = router.events[0]
    assert event.channel_id == "discord:123:thread-1"
    assert event.channel_name == "codex-repo"
