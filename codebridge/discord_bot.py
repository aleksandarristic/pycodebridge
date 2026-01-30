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
        self._startup_notified = False
        self._shutdown_notified = False

    async def on_ready(self) -> None:
        """Log when the Discord client is ready."""
        self.router.logger.info("discord.ready", extra={"user": str(self.user)})
        if self._startup_notified:
            return
        self._startup_notified = True
        cfg = self.router.cfg.discord
        recipients = cfg.dm_admin_user_ids or cfg.allowed_user_ids
        if not recipients:
            return
        summary = await self.router.startup_summary()
        message = f"Startup summary:\n{summary}"
        for user_id in recipients:
            try:
                user = await self.fetch_user(int(user_id))
            except Exception:
                self.router.logger.warning("discord.startup_dm_failed", extra={"user_id": user_id})
                continue
            try:
                await user.send(message)
            except Exception:
                self.router.logger.warning("discord.startup_dm_failed", extra={"user_id": user_id})

    async def close(self) -> None:
        """Send a shutdown summary before closing the Discord client."""
        await self._send_shutdown_summary()
        await super().close()

    async def _send_shutdown_summary(self) -> None:
        if self._shutdown_notified:
            return
        self._shutdown_notified = True
        cfg = self.router.cfg.discord
        recipients = cfg.dm_admin_user_ids or cfg.allowed_user_ids
        if not recipients:
            return
        summary = await self.router.shutdown_summary()
        message = f"Shutdown summary:\n{summary}"
        for user_id in recipients:
            try:
                user = await self.fetch_user(int(user_id))
            except Exception:
                self.router.logger.warning("discord.shutdown_dm_failed", extra={"user_id": user_id})
                continue
            try:
                await user.send(message)
            except Exception:
                self.router.logger.warning("discord.shutdown_dm_failed", extra={"user_id": user_id})

    async def on_message(self, message: discord.Message) -> None:
        """Dispatch incoming messages to the Router."""
        event = self.adapter.event_from_message(message)
        sink = self.adapter.sink_for_channel(message.channel)
        await self.router.handle_message(event, sink)


def build_client(router: Router) -> BridgeClient:
    """Construct a BridgeClient with the provided router."""
    return BridgeClient(router)
