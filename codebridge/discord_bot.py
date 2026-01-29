"""Discord client adapter for the bridge."""

import discord

from .adapters.discord import DiscordAdapter
from .router import Router


class BridgeClient(discord.Client):
    """Discord client that delegates message handling to the Router."""
    def __init__(self, router: Router, **kwargs):
        """Initialize the client with required intents and a router."""
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True
        intents.messages = True
        intents.dm_messages = True
        super().__init__(intents=intents, **kwargs)
        self.router = router
        self.adapter = DiscordAdapter()

    async def on_ready(self) -> None:
        """Log when the Discord client is ready."""
        self.router.logger.info("discord.ready", extra={"user": str(self.user)})

    async def on_message(self, message: discord.Message) -> None:
        """Dispatch incoming messages to the Router."""
        event = self.adapter.event_from_message(message)
        sink = self.adapter.sink_for_channel(message.channel)
        await self.router.handle_message(event, sink)


def build_client(router: Router) -> BridgeClient:
    """Construct a BridgeClient with the provided router."""
    return BridgeClient(router)
