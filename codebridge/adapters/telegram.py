"""Telegram adapter for MessageEvent and ResponseSink."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from ..transport import MessageEvent, ResponseSink, null_typing


class TelegramAdapter:
    """Adapter for Telegram updates."""

    def event_from_update(self, update: Any) -> MessageEvent:
        """Create a MessageEvent from a Telegram update."""
        message = getattr(update, "effective_message", None) or getattr(update, "message", None)
        chat = getattr(update, "effective_chat", None)
        user = getattr(update, "effective_user", None)
        chat_id = str(getattr(chat, "id", "") or "")
        chat_title = getattr(chat, "title", None) or ""
        text = ""
        if message is not None:
            text = getattr(message, "text", "") or ""
        is_bot = bool(getattr(user, "is_bot", False))
        return MessageEvent(
            platform="telegram",
            content=str(text),
            channel_id=chat_id,
            channel_name=str(chat_title),
            author_id=str(getattr(user, "id", "") or ""),
            author_is_bot=is_bot,
            is_dm=bool(getattr(chat, "type", "") == "private"),
            guild_id=None,
            raw_event=update,
        )

    def sink_for_chat(self, bot: Any, chat_id: str) -> ResponseSink:
        """Return a ResponseSink for a Telegram chat."""
        return TelegramResponseSink(bot, chat_id)


class TelegramResponseSink:
    """Response sink for Telegram."""

    def __init__(self, bot: Any, chat_id: str) -> None:
        self._bot = bot
        self.channel_id = chat_id

    async def send(self, content: str) -> None:
        """Send a message to the chat."""
        await self._bot.send_message(chat_id=self.channel_id, text=content)

    def typing(self):  # type: ignore[override]
        """Return a typing indicator context if supported."""
        return _telegram_typing(self._bot, self.channel_id)

    async def update_pinned_status(self, user_id: str, session: str, text: str) -> None:
        """Update pinned status (no-op for now)."""
        _ = (user_id, session, text)
        return None


@asynccontextmanager
async def _telegram_typing(bot: Any, chat_id: str):
    try:
        from telegram.constants import ChatAction
    except Exception:
        async with null_typing():
            yield
            return
    try:
        await bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    except Exception:
        async with null_typing():
            yield
            return
    yield
