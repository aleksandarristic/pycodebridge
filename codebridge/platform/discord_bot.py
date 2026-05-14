"""Discord client adapter for the bridge."""

import discord

from ..adapters.discord import DiscordAdapter
from ..routing.router import Router


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
        await self._enforce_guild_lock()
        if self._startup_notified:
            return
        self._startup_notified = True
        cfg = self.router.cfg.discord
        recipients = cfg.dm_admin_user_ids
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
        recipients = cfg.dm_admin_user_ids
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
        sink_channel = getattr(message, "thread", None) or message.channel
        sink = self.adapter.sink_for_channel(sink_channel)
        await self.router.handle_message(event, sink)

    async def on_guild_join(self, guild: discord.Guild) -> None:
        """Immediately leave guilds that do not match configured lock."""
        cfg_guild_id = (self.router.cfg.discord.guild_id or "").strip()
        if not cfg_guild_id:
            return
        if str(guild.id) == cfg_guild_id:
            return
        try:
            await guild.leave()
            self.router.logger.warning(
                "discord.guild_left_unconfigured",
                extra={"guild_id": str(guild.id), "configured_guild_id": cfg_guild_id},
            )
        except Exception:
            self.router.logger.warning("discord.guild_leave_failed", extra={"guild_id": str(guild.id)})

    async def _enforce_guild_lock(self, guilds: list[discord.Guild] | None = None) -> None:
        cfg_guild_id = (self.router.cfg.discord.guild_id or "").strip()
        if not cfg_guild_id:
            self.router.logger.warning("discord.guild_lock_unset")
            return
        for guild in list(guilds or self.guilds):
            if str(guild.id) == cfg_guild_id:
                continue
            try:
                await guild.leave()
                self.router.logger.warning(
                    "discord.guild_left_unconfigured",
                    extra={"guild_id": str(guild.id), "configured_guild_id": cfg_guild_id},
                )
            except Exception:
                self.router.logger.warning("discord.guild_leave_failed", extra={"guild_id": str(guild.id)})


def build_client(router: Router) -> BridgeClient:
    """Construct a BridgeClient with the provided router."""
    return BridgeClient(router)
