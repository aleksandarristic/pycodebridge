import discord

from codebridge.adapters.discord import DiscordAdapter
from codebridge.adapters.slack import SlackAdapter
from codebridge.adapters.telegram import TelegramAdapter
from tests.fixtures_adapter_payloads import (
    FakeAuthor,
    FakeBot,
    FakeChannel,
    FakeChat,
    FakeGuild,
    FakeMessage,
    FakeThread,
    FakeUpdate,
    FakeUser,
)


def test_discord_event_contract_thread(monkeypatch):
    adapter = DiscordAdapter()
    monkeypatch.setattr(discord, "Thread", FakeThread)

    channel = FakeThread("thread-1", "codex-thread")
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
    assert event.channel_name == "codex-thread"
    assert event.author_id == "user"
    assert event.guild_id == "guild"
    assert event.message_id == "msg"
    assert event.platform_thread_id == "thread-1"


def test_discord_event_contract_channel(monkeypatch):
    adapter = DiscordAdapter()
    monkeypatch.setattr(discord, "Thread", FakeThread)

    channel = FakeChannel("chan", "codex-test")
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


def test_slack_event_contract_thread():
    adapter = SlackAdapter()
    payload = {
        "team_id": "T123",
        "event": {
            "channel": "C123",
            "user": "U123",
            "text": "hi",
            "ts": "1700000000.0001",
            "thread_ts": "1700000000.0000",
        },
    }

    event = adapter.event_from_payload(payload)
    assert event.platform == "slack"
    assert event.channel_id == "C123"
    assert event.author_id == "U123"
    assert event.message_id == "1700000000.0001"
    assert event.platform_thread_id == "1700000000.0000"
    assert event.guild_id == "T123"


def test_telegram_event_contract_thread():
    adapter = TelegramAdapter()
    message = FakeMessage("hi", message_id=42, thread_id=7)
    update = FakeUpdate(message, FakeChat("chat", "codex-test", "group"), FakeUser("user"))

    event = adapter.event_from_update(update, FakeBot())
    assert event.platform == "telegram"
    assert event.channel_id == "chat"
    assert event.message_id == "42"
    assert event.platform_thread_id == "7"
