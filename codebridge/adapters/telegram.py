"""Telegram adapter for MessageEvent and ResponseSink."""

from __future__ import annotations

from contextlib import asynccontextmanager
import mimetypes
import os
from typing import Any

from ..platform.transport import Attachment, Capabilities, MessageEvent, ResponseSink, null_typing


class TelegramAdapter:
    """Adapter for Telegram updates."""

    def event_from_update(self, update: Any, bot: Any | None = None) -> MessageEvent:
        """Create a MessageEvent from a Telegram update."""
        message = getattr(update, "effective_message", None) or getattr(update, "message", None)
        chat = getattr(update, "effective_chat", None)
        user = getattr(update, "effective_user", None)
        chat_id = str(getattr(chat, "id", "") or "")
        chat_title = getattr(chat, "title", None) or ""
        text = ""
        message_id = ""
        thread_id = ""
        if message is not None:
            text = getattr(message, "text", "") or getattr(message, "caption", "") or ""
            message_id = str(getattr(message, "message_id", "") or "")
            thread_id = str(getattr(message, "message_thread_id", "") or "")
        is_bot = bool(getattr(user, "is_bot", False))
        attachments: list[Attachment] = []
        if message is not None and bot is not None:
            attachments = self._attachments_from_message(message, bot)
        return MessageEvent(
            platform="telegram",
            content=str(text),
            channel_id=chat_id,
            channel_name=str(chat_title),
            author_id=str(getattr(user, "id", "") or ""),
            author_is_bot=is_bot,
            is_dm=bool(getattr(chat, "type", "") == "private"),
            message_id=message_id,
            platform_thread_id=thread_id,
            guild_id=None,
            attachments=attachments,
            raw_event=update,
        )

    def sink_for_chat(self, bot: Any, chat_id: str) -> ResponseSink:
        """Return a ResponseSink for a Telegram chat."""
        return TelegramResponseSink(bot, chat_id)

    def _attachments_from_message(self, message: Any, bot: Any) -> list[Attachment]:
        attachments: list[Attachment] = []

        def add_file(file_id: str, filename: str, size: int, content_type: str | None, prefix: str) -> None:
            if not file_id:
                return
            safe_name = self._safe_filename(filename)
            if not safe_name:
                safe_name = self._default_filename(prefix, file_id, content_type)

            async def save(path: str, file_id: str = file_id) -> None:
                file_obj = await bot.get_file(file_id)
                await file_obj.download_to_drive(custom_path=path)

            attachments.append(
                Attachment(
                    filename=safe_name,
                    size=int(size or 0),
                    content_type=content_type,
                    save=save,
                )
            )

        doc = getattr(message, "document", None)
        if doc is not None:
            add_file(
                getattr(doc, "file_id", ""),
                getattr(doc, "file_name", "") or "",
                getattr(doc, "file_size", 0) or 0,
                getattr(doc, "mime_type", None),
                "document",
            )

        photos = list(getattr(message, "photo", None) or [])
        if photos:
            photo = max(photos, key=lambda p: getattr(p, "file_size", 0) or 0)
            add_file(
                getattr(photo, "file_id", ""),
                "",
                getattr(photo, "file_size", 0) or 0,
                "image/jpeg",
                "photo",
            )

        video = getattr(message, "video", None)
        if video is not None:
            add_file(
                getattr(video, "file_id", ""),
                getattr(video, "file_name", "") or "",
                getattr(video, "file_size", 0) or 0,
                getattr(video, "mime_type", None),
                "video",
            )

        audio = getattr(message, "audio", None)
        if audio is not None:
            add_file(
                getattr(audio, "file_id", ""),
                getattr(audio, "file_name", "") or "",
                getattr(audio, "file_size", 0) or 0,
                getattr(audio, "mime_type", None),
                "audio",
            )

        voice = getattr(message, "voice", None)
        if voice is not None:
            add_file(
                getattr(voice, "file_id", ""),
                "",
                getattr(voice, "file_size", 0) or 0,
                getattr(voice, "mime_type", None),
                "voice",
            )

        animation = getattr(message, "animation", None)
        if animation is not None:
            add_file(
                getattr(animation, "file_id", ""),
                getattr(animation, "file_name", "") or "",
                getattr(animation, "file_size", 0) or 0,
                getattr(animation, "mime_type", None),
                "animation",
            )

        sticker = getattr(message, "sticker", None)
        if sticker is not None:
            add_file(
                getattr(sticker, "file_id", ""),
                "",
                getattr(sticker, "file_size", 0) or 0,
                getattr(sticker, "mime_type", None),
                "sticker",
            )

        return attachments

    def _default_filename(self, prefix: str, file_id: str, content_type: str | None) -> str:
        ext = ""
        if content_type:
            ext = mimetypes.guess_extension(content_type) or ""
        return f"{prefix}_{file_id}{ext}"

    def _safe_filename(self, name: str) -> str:
        if not name:
            return ""
        return os.path.basename(name)


class TelegramResponseSink:
    """Response sink for Telegram."""

    def __init__(self, bot: Any, chat_id: str) -> None:
        self._bot = bot
        self.channel_id = chat_id

    async def send(self, content: str, thread_id: str | None = None, reply_to_id: str | None = None) -> None:
        """Send a message to the chat."""
        kwargs: dict[str, int] = {}
        thread_int = _to_int(thread_id)
        if thread_int is not None:
            kwargs["message_thread_id"] = thread_int
        else:
            reply_int = _to_int(reply_to_id)
            if reply_int is not None:
                kwargs["reply_to_message_id"] = reply_int
        await self._bot.send_message(chat_id=self.channel_id, text=content, **kwargs)

    def capabilities(self) -> Capabilities:
        return Capabilities(threads=True, replies=True, uploads=True, downloads=True, typing=True)

    def typing(self):  # type: ignore[override]
        """Return a typing indicator context if supported."""
        return _telegram_typing(self._bot, self.channel_id)

    async def update_pinned_status(self, user_id: str, session: str, text: str) -> None:
        """Update pinned status (no-op for now)."""
        _ = (user_id, session, text)
        return None

    async def send_file(self, path: str, filename: str, thread_id: str | None = None, reply_to_id: str | None = None) -> None:
        """Send a file to the chat."""
        kwargs: dict[str, int] = {}
        thread_int = _to_int(thread_id)
        if thread_int is not None:
            kwargs["message_thread_id"] = thread_int
        else:
            reply_int = _to_int(reply_to_id)
            if reply_int is not None:
                kwargs["reply_to_message_id"] = reply_int
        with open(path, "rb") as fh:
            await self._bot.send_document(chat_id=self.channel_id, document=fh, filename=filename, **kwargs)


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


def _to_int(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
