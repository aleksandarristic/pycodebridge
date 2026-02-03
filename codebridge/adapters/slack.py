"""Slack adapter scaffold for MessageEvent and ResponseSink."""

from __future__ import annotations

from typing import Any, Dict

from ..transport import Capabilities, MessageEvent, ResponseSink, null_typing


class SlackAdapter:
    """Scaffold adapter for Slack events."""

    def event_from_payload(self, payload: Dict[str, Any]) -> MessageEvent:
        """Create a MessageEvent from a Slack event payload."""
        event = payload.get("event", {}) if payload else {}
        channel_id = str(event.get("channel", ""))
        user_id = str(event.get("user", ""))
        text = str(event.get("text", "") or "")
        is_bot = bool(event.get("bot_id") or event.get("bot_profile"))
        thread_id = str(event.get("thread_ts") or "")
        message_id = str(event.get("ts") or "")
        return MessageEvent(
            platform="slack",
            content=text,
            channel_id=channel_id,
            channel_name=channel_id,
            author_id=user_id,
            author_is_bot=is_bot,
            is_dm=False,
            message_id=message_id,
            platform_thread_id=thread_id,
            guild_id=str(payload.get("team_id")) if payload else None,
            raw_event=payload,
        )

    def sink_for_channel(self, channel_id: str) -> ResponseSink:
        """Return a ResponseSink for a Slack channel."""
        return SlackResponseSink(channel_id)


class SlackResponseSink:
    """Response sink scaffold for Slack."""

    def __init__(self, channel_id: str) -> None:
        self.channel_id = channel_id

    async def send(self, content: str, thread_id: str | None = None, reply_to_id: str | None = None) -> None:
        """Send a message to the channel."""
        _ = (content, thread_id, reply_to_id)
        raise NotImplementedError("Slack adapter is scaffold-only; send is not wired.")

    def capabilities(self) -> Capabilities:
        return Capabilities()

    def typing(self):  # type: ignore[override]
        """Return a typing indicator context (no-op for scaffold)."""
        return null_typing()

    async def send_file(self, path: str, filename: str, thread_id: str | None = None, reply_to_id: str | None = None) -> None:
        _ = (path, filename, thread_id, reply_to_id)
        raise NotImplementedError("Slack adapter is scaffold-only; send_file is not wired.")

    async def update_pinned_status(self, user_id: str, session: str, text: str) -> None:
        """Update pinned status (no-op for scaffold)."""
        _ = (user_id, session, text)
        return None
