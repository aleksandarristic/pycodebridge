"""Platform-agnostic message event and response sink contracts."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncContextManager, Awaitable, Callable, Protocol


@dataclass(frozen=True)
class Attachment:
    """File attachment metadata and save handler."""

    filename: str
    size: int
    content_type: str | None
    save: Callable[[str], Awaitable[None]]


@dataclass(frozen=True)
class MessageEvent:
    """Normalized inbound message event."""

    platform: str
    content: str
    channel_id: str
    channel_name: str
    author_id: str
    author_is_bot: bool
    is_dm: bool
    message_id: str = ""
    platform_thread_id: str = ""
    guild_id: str | None = None
    attachments: list[Attachment] = field(default_factory=list)
    raw_event: Any | None = None


@dataclass(frozen=True)
class Capabilities:
    """Capabilities supported by a ResponseSink."""

    threads: bool = False
    replies: bool = False
    uploads: bool = False
    downloads: bool = False
    typing: bool = False


class ResponseSink(Protocol):
    """Platform-agnostic response surface for a channel."""

    channel_id: str

    def capabilities(self) -> Capabilities:
        """Return capability flags for this sink."""

    async def send(self, content: str, thread_id: str | None = None, reply_to_id: str | None = None) -> None:
        """Send a response message to the channel."""

    def typing(self) -> AsyncContextManager[None]:
        """Return an async typing context for the channel."""

    async def update_pinned_status(self, user_id: str, session: str, text: str) -> None:
        """Update a pinned status message for the channel, if supported."""

    async def send_file(self, path: str, filename: str, thread_id: str | None = None, reply_to_id: str | None = None) -> None:
        """Send a file to the channel."""


@asynccontextmanager
async def null_typing() -> AsyncContextManager[None]:
    """No-op typing context for platforms without typing support."""
    yield
