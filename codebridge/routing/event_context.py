"""Event context normalization and sink wrappers for routing."""

from __future__ import annotations

from dataclasses import replace

from ..platform.transport import Capabilities, MessageEvent, ResponseSink
from ..util.ansi import strip_control_codes
from ..util.chunk import chunk_text


def normalize_event_context(event: MessageEvent) -> MessageEvent:
    """Normalize Discord thread events to parent-mapped room context."""
    if event.platform != "discord" or event.is_dm or not event.platform_thread_id:
        return event
    parent_id, parent_name = discord_parent_context(event)
    if not parent_id:
        return event
    room_key = f"discord:{parent_id}:{event.platform_thread_id}"
    channel_name = parent_name or event.channel_name
    if room_key == event.channel_id and channel_name == event.channel_name:
        return event
    return replace(event, channel_id=room_key, channel_name=channel_name)


def discord_parent_context(event: MessageEvent) -> tuple[str, str]:
    """Return parent channel id/name for a Discord thread event."""
    message = event.raw_event
    channel = getattr(message, "thread", None) if message is not None else None
    if channel is None:
        channel = getattr(message, "channel", None) if message is not None else None
    if channel is None:
        return "", ""
    parent = getattr(message, "_codebridge_parent_channel", None)
    if parent is None:
        parent = getattr(channel, "parent", None)
    parent_id = getattr(channel, "parent_id", None)
    parent_name = ""
    if parent is None and parent_id is not None:
        guild = getattr(channel, "guild", None) or getattr(message, "guild", None)
        get_channel = getattr(guild, "get_channel", None)
        if callable(get_channel):
            try:
                parent = get_channel(int(parent_id))
            except Exception:
                parent = None
    if parent is not None:
        if parent_id is None:
            parent_id = getattr(parent, "id", None)
        parent_name = str(getattr(parent, "name", "") or "").strip()
    if parent_id is None:
        return "", parent_name
    return str(parent_id), parent_name


def build_contextual_sink(event: MessageEvent, sink: ResponseSink, max_chars: int, lock_emoji: str = "") -> ResponseSink:
    """Compose sink wrappers for thread/reply context, lock prefix, and chunking."""
    wrapped: ResponseSink = sink
    thread_id = event.platform_thread_id or ""
    reply_to_id = ""
    if not thread_id and wrapped.capabilities().replies:
        reply_to_id = event.message_id or ""
    if thread_id or reply_to_id:
        wrapped = ThreadContextSink(wrapped, thread_id, reply_to_id)
    if event.channel_id and wrapped.channel_id != event.channel_id:
        wrapped = ChannelScopeSink(wrapped, event.channel_id)
    if lock_emoji:
        wrapped = LockStateSink(wrapped, lock_emoji, max_chars)
    wrapped = ChunkingSink(wrapped, max_chars)
    return wrapped


class ThreadContextSink:
    """Wrap a sink with thread/reply metadata for message sends."""

    def __init__(self, sink: ResponseSink, thread_id: str, reply_to_id: str) -> None:
        self._sink = sink
        self._thread_id = thread_id
        self._reply_to_id = reply_to_id
        self.channel_id = sink.channel_id

    async def send(self, content: str, thread_id: str | None = None, reply_to_id: str | None = None) -> None:
        caps = self._sink.capabilities()
        use_thread = thread_id or self._thread_id or None
        use_reply = reply_to_id or self._reply_to_id or None
        if not caps.threads:
            use_thread = None
        if not caps.replies:
            use_reply = None
        await self._sink.send(content, thread_id=use_thread, reply_to_id=use_reply)

    def capabilities(self) -> Capabilities:
        return self._sink.capabilities()

    def typing(self):  # type: ignore[override]
        return self._sink.typing()

    async def update_pinned_status(self, user_id: str, session: str, text: str) -> None:
        await self._sink.update_pinned_status(user_id, session, text)

    async def send_file(self, path: str, filename: str, thread_id: str | None = None, reply_to_id: str | None = None) -> None:
        caps = self._sink.capabilities()
        use_thread = thread_id or self._thread_id or None
        use_reply = reply_to_id or self._reply_to_id or None
        if not caps.threads:
            use_thread = None
        if not caps.replies:
            use_reply = None
        await self._sink.send_file(path, filename, thread_id=use_thread, reply_to_id=use_reply)


class ChannelScopeSink:
    """Wrap a sink and override channel_id for routing/state scoping."""

    def __init__(self, sink: ResponseSink, channel_id: str) -> None:
        self._sink = sink
        self.channel_id = channel_id

    async def send(self, content: str, thread_id: str | None = None, reply_to_id: str | None = None) -> None:
        await self._sink.send(content, thread_id=thread_id, reply_to_id=reply_to_id)

    def capabilities(self) -> Capabilities:
        return self._sink.capabilities()

    def typing(self):  # type: ignore[override]
        return self._sink.typing()

    async def update_pinned_status(self, user_id: str, session: str, text: str) -> None:
        await self._sink.update_pinned_status(user_id, session, text)

    async def send_file(self, path: str, filename: str, thread_id: str | None = None, reply_to_id: str | None = None) -> None:
        await self._sink.send_file(path, filename, thread_id=thread_id, reply_to_id=reply_to_id)


class ChunkingSink:
    """Wrap a sink and enforce message-length chunking on every send."""

    def __init__(self, sink: ResponseSink, max_chars: int) -> None:
        self._sink = sink
        self._max_chars = max_chars
        self.channel_id = sink.channel_id

    async def send(self, content: str, thread_id: str | None = None, reply_to_id: str | None = None) -> None:
        text = strip_control_codes(content or "")
        for chunk in chunk_text(text, self._max_chars):
            await self._sink.send(chunk, thread_id=thread_id, reply_to_id=reply_to_id)

    def capabilities(self) -> Capabilities:
        return self._sink.capabilities()

    def typing(self):  # type: ignore[override]
        return self._sink.typing()

    async def update_pinned_status(self, user_id: str, session: str, text: str) -> None:
        await self._sink.update_pinned_status(user_id, session, text)

    async def send_file(self, path: str, filename: str, thread_id: str | None = None, reply_to_id: str | None = None) -> None:
        await self._sink.send_file(path, filename, thread_id=thread_id, reply_to_id=reply_to_id)


class LockStateSink:
    """Wrap a sink and prefix messages with lock-state emoji."""

    def __init__(self, sink: ResponseSink, emoji: str, max_chars: int) -> None:
        self._sink = sink
        self._emoji = emoji
        self._max_chars = max_chars
        self.channel_id = sink.channel_id

    async def send(self, content: str, thread_id: str | None = None, reply_to_id: str | None = None) -> None:
        text = content or ""
        prefix = f"{self._emoji} "
        budget = max(self._max_chars - len(prefix), 1)
        for chunk in chunk_text(text, budget):
            await self._sink.send(f"{prefix}{chunk}", thread_id=thread_id, reply_to_id=reply_to_id)

    def capabilities(self) -> Capabilities:
        return self._sink.capabilities()

    def typing(self):  # type: ignore[override]
        return self._sink.typing()

    async def update_pinned_status(self, user_id: str, session: str, text: str) -> None:
        await self._sink.update_pinned_status(user_id, session, text)

    async def send_file(self, path: str, filename: str, thread_id: str | None = None, reply_to_id: str | None = None) -> None:
        await self._sink.send_file(path, filename, thread_id=thread_id, reply_to_id=reply_to_id)
