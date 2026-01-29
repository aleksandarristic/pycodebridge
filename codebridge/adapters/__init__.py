"""Platform adapters for message transport."""

from .discord import DiscordAdapter, DiscordResponseSink
from .slack import SlackAdapter, SlackResponseSink
from .telegram import TelegramAdapter, TelegramResponseSink

__all__ = [
    "DiscordAdapter",
    "DiscordResponseSink",
    "SlackAdapter",
    "SlackResponseSink",
    "TelegramAdapter",
    "TelegramResponseSink",
]
