import re
from typing import Optional

import discord

from . import config as cfgmod
from .audit import Logger as AuditLogger
from .codex import Runner
from .queue import Manager
from .state import Store
from .util import path as pathutil


FORBIDDEN_PREFIX = "I'm sorry, Dave. I'm afraid I can't do that."


class Router:
    def __init__(self, cfg: cfgmod.Config, state: Store, audit: AuditLogger, runner: Runner, queue: Manager, logger):
        self.cfg = cfg
        self.state = state
        self.audit = audit
        self.runner = runner
        self.queue = queue
        self.logger = logger

    async def handle_message(self, client: discord.Client, message: discord.Message) -> None:
        if message.author.bot:
            return

        channel = message.channel
        is_dm = isinstance(channel, (discord.DMChannel, discord.GroupChannel))
        channel_name = channel.name if hasattr(channel, "name") and channel.name else str(channel.id)

        if is_dm:
            if not self.cfg.discord.dm_admin_enabled:
                return
            if not self._dm_admin_allowed(str(message.author.id)):
                await self.reply_forbidden(channel, "You are not allowed to use DM admin commands.")
                return
            await self.reply_forbidden(channel, "DM admin commands not implemented yet.")
            return

        if self.cfg.discord.guild_id and str(message.guild.id) != self.cfg.discord.guild_id:
            await self.reply_forbidden(channel, "This bot is not configured for this guild.")
            return

        if str(message.author.id) not in self.cfg.discord.allowed_user_ids:
            await self.reply_forbidden(channel, "You are not allowed to use this bot.")
            return

        rexp = self.cfg.channel_regex()
        match = rexp.match(channel_name)
        if not match:
            return

        repo_name = match.group(1)
        prefix = self.cfg.discord.prefix or "!c"
        content = (message.content or "").strip()
        if not content.startswith(prefix):
            if not self.cfg.discord.allow_plain_prompts:
                return
            prompt = content.strip()
            if not prompt:
                return
            try:
                _ = pathutil.resolve_repo_path(self.cfg.codex.code_root, repo_name)
            except Exception as exc:
                await self.reply_forbidden(channel, f"Repo error: {exc}")
                return
            await self.reply_forbidden(channel, "Plain prompt handling not implemented yet.")
            return

        cmdline = content[len(prefix):].strip()
        if not cmdline:
            return

        parts = cmdline.split()
        cmd = parts[0].lower()
        try:
            _ = pathutil.resolve_repo_path(self.cfg.codex.code_root, repo_name)
        except Exception as exc:
            await self.reply_forbidden(channel, f"Repo error: {exc}")
            return

        await self.reply_forbidden(channel, f"Command '{cmd}' not implemented yet.")

    async def reply(self, channel: discord.abc.Messageable, content: str) -> None:
        await channel.send(content)

    async def reply_forbidden(self, channel: discord.abc.Messageable, detail: str) -> None:
        text = f"{FORBIDDEN_PREFIX}\n```text\n{detail}\n```"
        await channel.send(text)

    def _dm_admin_allowed(self, user_id: str) -> bool:
        if self.cfg.discord.dm_admin_user_ids:
            return user_id in self.cfg.discord.dm_admin_user_ids
        return user_id in self.cfg.discord.allowed_user_ids

