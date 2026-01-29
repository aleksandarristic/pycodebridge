"""Telegram adapter scaffold for MessageEvent and ResponseSink."""

from __future__ import annotations

from typing import Any, Dict

from ..transport import MessageEvent, ResponseSink, null_typing


class TelegramAdapter:
    """Scaffold adapter for Telegram updates."""

    def event_from_update(self, update: Dict[str, Any]) -> MessageEvent:
        """Create a MessageEvent from a Telegram update payload."""
        message = update.get("message") or update.get("edited_message") or {}
        chat = message.get("chat", {}) if isinstance(message, dict) else {}
        from_user = message.get("from", {}) if isinstance(message, dict) else {}
        chat_id = str(chat.get("id", ""))
        text = str(message.get("text", "") or "")
        is_bot = bool(from_user.get("is_bot", False))
        return MessageEvent(
            platform="telegram",
            content=text,
            channel_id=chat_id,
            channel_name=chat_id,
            author_id=str(from_user.get("id", "")),
            author_is_bot=is_bot,
            is_dm=bool(chat.get("type") == "private"),
            guild_id=None,
            raw_event=update,
        )

    def sink_for_chat(self, chat_id: str) -> ResponseSink:
        """Return a ResponseSink for a Telegram chat."""
        return TelegramResponseSink(chat_id)


class TelegramResponseSink:
    """Response sink scaffold for Telegram."""

    def __init__(self, chat_id: str) -> None:
        self.channel_id = chat_id

    async def send(self, content: str) -> None:
        """Send a message to the chat."""
        raise NotImplementedError("Telegram adapter is scaffold-only; send is not wired.")

    def typing(self):  # type: ignore[override]
        """Return a typing indicator context (no-op for scaffold)."""
        return null_typing()

    async def update_pinned_status(self, user_id: str, session: str, text: str) -> None:
        """Update pinned status (no-op for scaffold)."""
        _ = (user_id, session, text)
        return None
