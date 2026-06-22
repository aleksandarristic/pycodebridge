import asyncio

from codebridge.platform.transport import Capabilities, MessageEvent, ResponseSink
from codebridge.routing.event_context import build_contextual_sink, normalize_event_context


class _FakeSink(ResponseSink):
    def __init__(self, caps: Capabilities) -> None:
        self._caps = caps
        self.channel_id = "chan"
        self.sent = []

    def capabilities(self) -> Capabilities:
        return self._caps

    async def send(self, content: str, thread_id: str | None = None, reply_to_id: str | None = None) -> None:
        self.sent.append((content, thread_id, reply_to_id))

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


class _FakeDiscordPermissions:
    def __init__(self, *, view_channel: bool) -> None:
        self.view_channel = view_channel


class _FakeDiscordGuild:
    def __init__(self, channels=None) -> None:
        self.default_role = object()
        self._channels = channels or {}

    def get_channel(self, channel_id: int):
        return self._channels.get(str(channel_id))


class _FakeDiscordChannelType:
    def __init__(self, name: str) -> None:
        self.name = name

    def __str__(self) -> str:
        return self.name


class _FakeDiscordChannel:
    def __init__(
        self,
        *,
        is_private: bool,
        channel_id: str,
        channel_name: str,
        channel_type: str = "text",
        parent=None,
        parent_id: str = "",
    ) -> None:
        self.id = channel_id
        self.name = channel_name
        self.guild = _FakeDiscordGuild()
        self.type = _FakeDiscordChannelType(channel_type)
        self._is_private = is_private
        self.parent = parent
        self.parent_id = parent_id or (str(getattr(parent, "id", "")) if parent is not None else "")

    def permissions_for(self, role) -> _FakeDiscordPermissions:
        _ = role
        return _FakeDiscordPermissions(view_channel=not self._is_private)


class _FakeDiscordMessage:
    def __init__(self, channel: _FakeDiscordChannel) -> None:
        self.channel = channel


def test_contextual_sink_uses_reply_to_when_supported():
    sink = _FakeSink(Capabilities(threads=False, replies=True, uploads=False, downloads=False, typing=False))
    event = MessageEvent(
        platform="discord",
        content="hi",
        channel_id="chan",
        channel_name="code-repo",
        author_id="user",
        author_is_bot=False,
        is_dm=False,
        message_id="msg-1",
        platform_thread_id="",
        guild_id="guild",
    )
    wrapped = build_contextual_sink(event, sink, max_chars=1800, lock_emoji="")

    async def run():
        await wrapped.send("hello")

    asyncio.run(run())
    assert sink.sent == [("hello", None, "msg-1")]


def test_contextual_sink_overrides_channel_scope_for_thread_rooms():
    sink = _FakeSink(Capabilities(threads=True, replies=False, uploads=False, downloads=False, typing=False))
    event = MessageEvent(
        platform="discord",
        content="hi",
        channel_id="discord:parent:thread-1",
        channel_name="code-repo",
        author_id="user",
        author_is_bot=False,
        is_dm=False,
        message_id="msg-1",
        platform_thread_id="thread-1",
        guild_id="guild",
    )
    wrapped = build_contextual_sink(event, sink, max_chars=1800, lock_emoji="")
    assert wrapped.channel_id == "discord:parent:thread-1"


def test_normalize_event_context_uses_parent_channel_metadata_for_threads():
    parent = _FakeDiscordChannel(is_private=True, channel_id="chan-parent", channel_name="code-repo")
    thread = _FakeDiscordChannel(
        is_private=True,
        channel_id="thread-1",
        channel_name="topic-a",
        channel_type="public_thread",
        parent=parent,
        parent_id="chan-parent",
    )
    event = MessageEvent(
        platform="discord",
        content="!c start",
        channel_id="thread-1",
        channel_name="topic-a",
        author_id="user",
        author_is_bot=False,
        is_dm=False,
        message_id="m1",
        platform_thread_id="thread-1",
        guild_id="guild",
        raw_event=_FakeDiscordMessage(thread),
    )

    normalized = normalize_event_context(event)
    assert normalized.channel_id == "discord:chan-parent:thread-1"
    assert normalized.channel_name == "code-repo"


def test_normalize_event_context_uses_guild_cache_when_thread_parent_missing():
    parent = _FakeDiscordChannel(is_private=True, channel_id="123", channel_name="code-repo")
    guild = _FakeDiscordGuild(channels={"123": parent})
    thread = _FakeDiscordChannel(
        is_private=True,
        channel_id="thread-1",
        channel_name="topic-a",
        channel_type="public_thread",
        parent=None,
        parent_id="123",
    )
    thread.guild = guild
    event = MessageEvent(
        platform="discord",
        content="!c start",
        channel_id="thread-1",
        channel_name="topic-a",
        author_id="user",
        author_is_bot=False,
        is_dm=False,
        message_id="m1",
        platform_thread_id="thread-1",
        guild_id="guild",
        raw_event=_FakeDiscordMessage(thread),
    )

    normalized = normalize_event_context(event)
    assert normalized.channel_id == "discord:123:thread-1"
    assert normalized.channel_name == "code-repo"


def test_normalize_event_context_uses_attached_thread_parent_for_starter_messages():
    parent = _FakeDiscordChannel(is_private=True, channel_id="chan-parent", channel_name="code-repo")
    thread = _FakeDiscordChannel(
        is_private=True,
        channel_id="thread-1",
        channel_name="topic-a",
        channel_type="public_thread",
        parent=parent,
        parent_id="chan-parent",
    )
    message = _FakeDiscordMessage(parent)
    message.thread = thread
    event = MessageEvent(
        platform="discord",
        content="Hi",
        channel_id="chan-parent",
        channel_name="code-repo",
        author_id="user",
        author_is_bot=False,
        is_dm=False,
        message_id="m1",
        platform_thread_id="thread-1",
        guild_id="guild",
        raw_event=message,
    )

    normalized = normalize_event_context(event)
    assert normalized.channel_id == "discord:chan-parent:thread-1"
    assert normalized.channel_name == "code-repo"
