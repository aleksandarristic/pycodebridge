"""Platform-agnostic message event and response sink contracts."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncContextManager, Protocol


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
    guild_id: str | None = None
    raw_event: Any | None = None


class ResponseSink(Protocol):
    """Platform-agnostic response surface for a channel."""

    channel_id: str

    async def send(self, content: str) -> None:
        """Send a response message to the channel."""

    def typing(self) -> AsyncContextManager[None]:
        """Return an async typing context for the channel."""

    async def update_pinned_status(self, user_id: str, session: str, text: str) -> None:
        """Update a pinned status message for the channel, if supported."""


@asynccontextmanager
async def null_typing() -> AsyncContextManager[None]:
    """No-op typing context for platforms without typing support."""
    yield
