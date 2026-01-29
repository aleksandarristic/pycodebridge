"""Git helper command handlers."""

from __future__ import annotations

import shlex
from typing import TYPE_CHECKING

import discord

from ..command_parse import parse_log_count
from ..router_helpers import find_unsafe_git_flag, has_forbidden_flags, run_limited_command, trim_output
from ..util.ansi import strip_control_codes
from ..util.chunk import chunk_text

if TYPE_CHECKING:
    from ..router import Router


async def handle_git(router: "Router", channel: discord.abc.Messageable, repo_path: str, rest: str) -> None:
    """Run safe git helper commands."""
    fields = shlex.split(rest) if rest else []
    if not fields:
        await router.reply(channel, "Usage: !c git <status|log|branches|show|diff|pull|commit|push|merge> [args]")
        return
    sub = fields[0].lower()
    args = fields[1:]
    bad = find_unsafe_git_flag(args)
    if bad:
        await router.reply_forbidden(channel, f"Forbidden git flag: {bad}")
        return
    git_args: list[str] = []
    wrap_diff = False
    if sub == "status":
        git_args = ["status", "--short", "--branch"]
    elif sub == "log":
        n = parse_log_count(args)
        git_args = ["log", f"-n{n}", "--oneline"]
    elif sub == "branches":
        git_args = ["branch", "--all", "--list"]
    elif sub == "show":
        if not args:
            await router.reply(channel, "Usage: !c git show <rev>")
            return
        git_args = ["show", args[0]] + args[1:]
    elif sub == "diff":
        if not args:
            await router.reply_forbidden(channel, "Usage: !c git diff <args>")
            return
        git_args = ["diff"] + args
        wrap_diff = True
    elif sub == "pull":
        if has_forbidden_flags(args):
            await router.reply_forbidden(channel, "Forbidden flags detected (--force/-f/--rebase/--squash).")
            return
        git_args = ["pull", "--no-rebase"] + args
    elif sub == "commit":
        if not args:
            await router.reply_forbidden(channel, "Usage: !c git commit <message>")
            return
        msg = " ".join(args)
        git_args = ["commit", "-am", msg]
    elif sub == "push":
        if has_forbidden_flags(args):
            await router.reply_forbidden(channel, "Forbidden flags detected (--force/-f/--rebase/--squash).")
            return
        git_args = ["push"] + args
    elif sub == "merge":
        if not args:
            await router.reply_forbidden(channel, "Usage: !c git merge <branch>")
            return
        if has_forbidden_flags(args):
            await router.reply_forbidden(channel, "Forbidden flags detected (--force/-f/--rebase/--squash).")
            return
        git_args = ["merge"] + args
    else:
        await router.reply_forbidden(channel, "Unknown git subcommand.")
        return

    out, err = await run_limited_command(repo_path, ["git"] + git_args)
    text = strip_control_codes(out)
    text = trim_output(text, 200, 4000)
    if wrap_diff:
        text = "```diff\n" + text + "\n```"
    if err:
        text = f"git {sub} error: {err}\n{text}"
    for chunk in chunk_text(text, router.cfg.discord.max_discord_message_chars):
        await router.reply(channel, chunk)
