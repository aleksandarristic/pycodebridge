"""Helpers for formatting and sending router replies."""

from __future__ import annotations

from .router_helpers import forbidden_message
from .transport import ResponseSink
from .util.ansi import strip_control_codes
from .util.chunk import chunk_text


async def send_reply(sink: ResponseSink, content: str, max_chars: int) -> None:
    """Send a reply to a channel, chunking as needed."""
    content = strip_control_codes(content)
    for chunk in chunk_text(content, max_chars):
        await sink.send(chunk)


async def send_forbidden(sink: ResponseSink, detail: str, max_chars: int) -> None:
    """Send a standardized forbidden/invalid response."""
    await send_reply(sink, forbidden_message(detail), max_chars)
