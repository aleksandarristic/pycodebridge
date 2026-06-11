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
        self.router.set_guild_text_channels_fn(self._get_guild_text_channels)

    async def _get_guild_text_channels(self) -> list[discord.TextChannel]:
        """Return all text channels across all connected guilds."""
        channels: list[discord.TextChannel] = []
        for guild in self.guilds:
            for ch in guild.channels:
                if isinstance(ch, discord.TextChannel):
                    channels.append(ch)
        return channels

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
        await self._ensure_thread_parent_context(message)
        event = self.adapter.event_from_message(message)
        sink_channel = getattr(message, "thread", None) or message.channel
        sink = self.adapter.sink_for_channel(sink_channel)
        await self.router.handle_message(event, sink)

    async def _ensure_thread_parent_context(self, message: discord.Message) -> None:
        """Attach fetched parent channel metadata when a thread parent is not cached."""
        channel = getattr(message, "thread", None) or getattr(message, "channel", None)
        if not isinstance(channel, discord.Thread):
            return
        if getattr(channel, "parent", None) is not None:
            return
        parent_id = getattr(channel, "parent_id", None)
        if parent_id is None:
            return
        guild = getattr(message, "guild", None) or getattr(channel, "guild", None)
        if guild is None:
            return
        parent = None
        get_channel = getattr(guild, "get_channel", None)
        if callable(get_channel):
            try:
                parent = get_channel(int(parent_id))
            except Exception:
                parent = None
        if parent is None:
            fetch_channel = getattr(guild, "fetch_channel", None)
            if callable(fetch_channel):
                try:
                    parent = await fetch_channel(int(parent_id))
                except Exception as exc:
                    self.router.logger.warning(
                        "discord.thread_parent_fetch_failed",
                        extra={"thread_id": str(getattr(channel, "id", "")), "parent_id": str(parent_id), "error": str(exc)},
                    )
        if parent is not None:
            setattr(message, "_codebridge_parent_channel", parent)

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
