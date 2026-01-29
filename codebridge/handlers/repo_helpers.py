"""Repository helper command handlers."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import discord

from ..router_helpers import TESTS_TIMEOUT, build_tree, run_limited_command, trim_output
from ..util.ansi import strip_control_codes
from ..util.chunk import chunk_text

if TYPE_CHECKING:
    from ..router import Router


async def handle_showrepo(router: "Router", channel: discord.abc.Messageable, repo_path: str) -> None:
    """Show a pruned repo tree for orientation."""
    text = build_tree(repo_path, max_depth=3)
    text = trim_output(text, 300, 6000)
    for chunk in chunk_text(text, router.cfg.discord.max_discord_message_chars):
        await router.reply(channel, chunk)


async def handle_showchanges(router: "Router", channel: discord.abc.Messageable, repo_path: str) -> None:
    """Show git status and diffstat for the repo."""
    out, err = await run_limited_command(repo_path, ["git", "status", "--short", "--branch"])
    out2, err2 = await run_limited_command(repo_path, ["git", "diff", "--stat"])
    text = strip_control_codes(out + "\n" + out2)
    text = trim_output(text, 200, 4000)
    if err or err2:
        text = f"showchanges error: {err or err2}\n{text}"
    text = "```diff\n" + text + "\n```"
    for chunk in chunk_text(text, router.cfg.discord.max_discord_message_chars):
        await router.reply(channel, chunk)


async def handle_tests(router: "Router", channel: discord.abc.Messageable, repo_path: str) -> None:
    """Run tests for the repo (pytest -q)."""
    out, err = await run_limited_command(repo_path, ["pytest", "-q"], timeout=TESTS_TIMEOUT)
    text = strip_control_codes(out)
    text = trim_output(text, 200, 6000)
    if err:
        reason = "Tests failed"
        if isinstance(err, asyncio.TimeoutError):
            reason = "Tests timed out"
        text = f"{reason}: {err}\n{text}"
    for chunk in chunk_text(text, router.cfg.discord.max_discord_message_chars):
        await router.reply(channel, chunk)
