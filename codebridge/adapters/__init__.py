"""Platform adapters for message transport."""

from .discord import DiscordAdapter, DiscordResponseSink

__all__ = [
    "DiscordAdapter",
    "DiscordResponseSink",
]
