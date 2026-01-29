"""Platform adapters for message transport."""

from .discord import DiscordAdapter, DiscordResponseSink
from .slack import SlackAdapter, SlackResponseSink

__all__ = ["DiscordAdapter", "DiscordResponseSink", "SlackAdapter", "SlackResponseSink"]
