import asyncio

from codebridge.transport import MessageEvent, null_typing


def test_message_event_fields():
    event = MessageEvent(
        platform="discord",
        content="hello",
        channel_id="chan",
        channel_name="codex-test",
        author_id="user",
        author_is_bot=False,
        is_dm=False,
        guild_id="guild",
    )
    assert event.channel_id == "chan"
    assert event.author_id == "user"
    assert event.guild_id == "guild"


def test_null_typing_context():
    async def run():
        async with null_typing():
            return True

    assert asyncio.run(run()) is True
