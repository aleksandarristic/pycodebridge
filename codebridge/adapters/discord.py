"""Discord adapter for MessageEvent and ResponseSink."""

from __future__ import annotations

from typing import Dict

import discord

from ..transport import Attachment, MessageEvent, ResponseSink, null_typing


class DiscordAdapter:
    """Translate discord.py messages into transport-agnostic events and sinks."""

    def __init__(self) -> None:
        self._pins: Dict[str, int] = {}

    def event_from_message(self, message: discord.Message) -> MessageEvent:
        """Create a MessageEvent from a discord.py message."""
        channel = message.channel
        is_dm = isinstance(channel, (discord.DMChannel, discord.GroupChannel))
        channel_name = channel.name if hasattr(channel, "name") and channel.name else str(channel.id)
        guild_id = str(message.guild.id) if message.guild else None
        thread_id = ""
        if isinstance(channel, discord.Thread):
            thread_id = str(channel.id)
        attachments = []
        for att in getattr(message, "attachments", []) or []:
            attachments.append(
                Attachment(
                    filename=att.filename,
                    size=att.size,
                    content_type=getattr(att, "content_type", None),
                    save=att.save,
                )
            )
        return MessageEvent(
            platform="discord",
            content=message.content or "",
            channel_id=str(channel.id),
            channel_name=channel_name,
            author_id=str(message.author.id),
            author_is_bot=bool(message.author.bot),
            is_dm=is_dm,
            message_id=str(message.id),
            platform_thread_id=thread_id,
            guild_id=guild_id,
            attachments=attachments,
            raw_event=message,
        )

    def sink_for_channel(self, channel: discord.abc.Messageable) -> ResponseSink:
        """Return a ResponseSink for a Discord channel."""
        return DiscordResponseSink(self, channel)

    async def update_pinned_status(self, channel: discord.abc.Messageable, text: str) -> None:
        """Update or pin the current session status message."""
        if not isinstance(channel, discord.TextChannel):
            return
        channel_id = str(channel.id)
        msg_id = self._pins.get(channel_id)
        if msg_id:
            try:
                msg = await channel.fetch_message(msg_id)
                await msg.edit(content=text)
                return
            except Exception:
                self._pins.pop(channel_id, None)
        try:
            msg = await channel.send(text)
        except Exception:
            return
        try:
            await msg.pin()
        except Exception:
            pass
        self._pins[channel_id] = msg.id


class DiscordResponseSink:
    """Response sink backed by a discord.py channel."""

    def __init__(self, adapter: DiscordAdapter, channel: discord.abc.Messageable) -> None:
        self._adapter = adapter
        self._channel = channel
        self.channel_id = str(channel.id)

    async def send(self, content: str, thread_id: str | None = None, reply_to_id: str | None = None) -> None:
        """Send a message to the channel."""
        _ = (thread_id, reply_to_id)
        await self._channel.send(content)

    def typing(self):  # type: ignore[override]
        """Return a typing indicator context if supported."""
        if hasattr(self._channel, "typing"):
            return self._channel.typing()
        return null_typing()

    async def update_pinned_status(self, user_id: str, session: str, text: str) -> None:
        """Update pinned status for this channel."""
        await self._adapter.update_pinned_status(self._channel, text)

    async def send_file(self, path: str, filename: str, thread_id: str | None = None, reply_to_id: str | None = None) -> None:
        """Send a file to the channel."""
        _ = (thread_id, reply_to_id)
        await self._channel.send(file=discord.File(path, filename=filename))
