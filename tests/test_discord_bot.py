from types import SimpleNamespace

import asyncio

from codebridge.discord_bot import BridgeClient


class _FakeRouter:
    def __init__(self):
        self.logger = _FakeLogger()
        self.cfg = SimpleNamespace(discord=SimpleNamespace(dm_admin_user_ids=["1"], allowed_user_ids=[], guild_id=""))
        self.startup_calls = 0
        self.shutdown_calls = 0

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

    async def leave(self) -> None:
        self.left = True


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
