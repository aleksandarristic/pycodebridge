"""Git helper command handlers."""

from __future__ import annotations

import shlex
from typing import TYPE_CHECKING

from ..commands.parse import parse_log_count
from ..routing.helpers import find_unsafe_git_flag, has_forbidden_flags, run_limited_command, trim_output
from ..platform.transport import ResponseSink
from ..util.ansi import strip_control_codes
from ..util.chunk import chunk_text

if TYPE_CHECKING:
    from ..routing.router import Router


async def handle_git(router: "Router", sink: ResponseSink, repo_path: str, rest: str) -> None:
    """Run safe git helper commands."""
    fields = shlex.split(rest) if rest else []
    if not fields:
        await router.reply(
            sink,
            "Usage: !c git <status|log|branches|branch|show|diff|remote|fetch|pull|add|commit|push|merge> [args]",
        )
        return
    sub = fields[0].lower()
    args = fields[1:]
    bad = find_unsafe_git_flag(args)
    if bad:
        await router.reply_forbidden(sink, f"Forbidden git flag: {bad}")
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
            await router.reply(sink, "Usage: !c git show <rev>")
            return
        git_args = ["show", args[0]] + args[1:]
    elif sub == "branch":
        dangerous_reason = _dangerous_git_reason(sub, args)
        ok, args = await _allow_dangerous_or_reply(router, sink, dangerous_reason, args)
        if not ok:
            return
        git_args = ["branch"] + args
    elif sub == "diff":
        if not args:
            await router.reply_forbidden(sink, "Usage: !c git diff <args>")
            return
        git_args = ["diff"] + args
        wrap_diff = True
    elif sub == "remote":
        git_args = ["remote"] + args
    elif sub == "fetch":
        if has_forbidden_flags(args):
            await router.reply_forbidden(sink, "Forbidden flags detected (--force/-f/--rebase/--squash).")
            return
        git_args = ["fetch"] + args
    elif sub == "pull":
        if has_forbidden_flags(args):
            await router.reply_forbidden(sink, "Forbidden flags detected (--force/-f/--rebase/--squash).")
            return
        git_args = ["pull", "--no-rebase"] + args
    elif sub == "add":
        git_args = ["add"] + args
    elif sub == "commit":
        if not args:
            await router.reply_forbidden(sink, "Usage: !c git commit <message>")
            return
        msg = " ".join(args)
        git_args = ["commit", "-am", msg]
    elif sub == "push":
        dangerous_reason = _dangerous_git_reason(sub, args)
        ok, args = await _allow_dangerous_or_reply(router, sink, dangerous_reason, args)
        if not ok:
            return
        git_args = ["push"] + args
    elif sub == "merge":
        if not args:
            await router.reply_forbidden(sink, "Usage: !c git merge <branch>")
            return
        if has_forbidden_flags(args):
            await router.reply_forbidden(sink, "Forbidden flags detected (--force/-f/--rebase/--squash).")
            return
        git_args = ["merge"] + args
    else:
        await router.reply_forbidden(sink, "Unknown git subcommand.")
        return

    out, err = await run_limited_command(repo_path, ["git"] + git_args)
    text = strip_control_codes(out)
    text = trim_output(text, 200, 4000)
    if wrap_diff:
        text = "```diff\n" + text + "\n```"
    if err:
        text = f"git {sub} error: {err}\n{text}"
    elif not text.strip():
        text = f"git {sub} completed successfully (no output)."
    for chunk in chunk_text(text, router.cfg.discord.max_discord_message_chars):
        await router.reply(sink, chunk)


async def handle_branch(router: "Router", sink: ResponseSink, repo_path: str) -> None:
    """Show current git branch and clean/not-clean state."""
    out, err = await run_limited_command(repo_path, ["git", "status", "--short", "--branch"])
    text = strip_control_codes(out)
    text = trim_output(text, 200, 4000)
    if err:
        rendered = f"git branch error: {err}\n{text}"
    else:
        branch, is_clean = _summarize_branch_status(text)
        rendered = f"Current branch: {branch}\nWorking tree: {'clean' if is_clean else 'not clean'}"
    for chunk in chunk_text(rendered, router.cfg.discord.max_discord_message_chars):
        await router.reply(sink, chunk)


def _summarize_branch_status(text: str) -> tuple[str, bool]:
    """Parse `git status --short --branch` output into branch + clean flag."""
    lines = [line.rstrip() for line in (text or "").splitlines() if line.strip()]
    branch = "unknown"
    if lines and lines[0].startswith("##"):
        head = lines[0][2:].strip()
        if head.startswith("No commits yet on "):
            branch = head[len("No commits yet on ") :].strip() or "unknown"
        elif head.startswith("HEAD (no branch)"):
            branch = "detached HEAD"
        else:
            branch = head.split("...", 1)[0].split(" [", 1)[0].strip() or "unknown"
    changed = [line for line in lines[1:] if not line.startswith("##")]
    return branch, not changed


def _dangerous_git_reason(sub: str, args: list[str]) -> str:
    if sub == "push":
        force_flags = {"-f", "--force", "--force-with-lease"}
        if any(a in force_flags for a in args):
            return "force push"
        if "--delete" in args:
            return "remote branch delete"
    if sub == "branch":
        if any(a in {"-d", "-D", "--delete"} for a in args):
            return "local branch delete"
    return ""


async def _allow_dangerous_or_reply(
    router: "Router", sink: ResponseSink, reason: str, args: list[str]
) -> tuple[bool, list[str]]:
    if not reason:
        return True, args
    token = (router.cfg.git.dangerous_confirmation_token or "--confirm-dangerous").strip() or "--confirm-dangerous"
    confirmed = token in args
    filtered = [a for a in args if a != token]
    if not router.cfg.git.allow_dangerous_ops:
        await router.reply_forbidden(
            sink,
            f"Dangerous git operation blocked ({reason}). "
            "Set `git.allow_dangerous_ops: true` to enable guarded execution.",
        )
        return False, filtered
    if router.cfg.git.require_confirmation_for_dangerous_ops and not confirmed:
        await router.reply_forbidden(
            sink,
            f"Dangerous git operation detected ({reason}). Re-run with `{token}` to confirm.",
        )
        return False, filtered
    return True, filtered
