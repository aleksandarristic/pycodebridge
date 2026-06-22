import discord

from codebridge.adapters.discord import DiscordAdapter
from tests.fixtures_adapter_payloads import (
    FakeAuthor,
    FakeChannel,
    FakeGuild,
    FakeThread,
)


def test_discord_event_contract_thread(monkeypatch):
    adapter = DiscordAdapter()
    monkeypatch.setattr(discord, "Thread", FakeThread)

    channel = FakeThread("thread-1", "code-thread")
    message = type(
        "FakeMessage",
        (),
        {
            "channel": channel,
            "content": "hello",
            "id": "msg",
            "author": FakeAuthor("user"),
            "guild": FakeGuild("guild"),
        },
    )()

    event = adapter.event_from_message(message)
    assert event.platform == "discord"
    assert event.channel_id == "thread-1"
    assert event.channel_name == "code-thread"
    assert event.author_id == "user"
    assert event.guild_id == "guild"
    assert event.message_id == "msg"
    assert event.platform_thread_id == "thread-1"


def test_discord_event_contract_channel(monkeypatch):
    adapter = DiscordAdapter()
    monkeypatch.setattr(discord, "Thread", FakeThread)

    channel = FakeChannel("chan", "code-test")
    message = type(
        "FakeMessage",
        (),
        {
            "channel": channel,
            "content": "hello",
            "id": "msg",
            "author": FakeAuthor("user"),
            "guild": FakeGuild("guild"),
        },
    )()

    event = adapter.event_from_message(message)
    assert event.platform_thread_id == ""
